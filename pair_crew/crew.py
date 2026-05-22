"""
PAIR Clinical Chatbot Crew

Sequential pipeline: Triage -> Context Gate -> Retrieval -> Specialist -> Safety Review
Context Gate can halt the crew early by returning a clarification message.

Usage:
    python -m pair_crew.crew --query "Your clinical question here"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault("CREWAI_STORAGE_DIR", str(Path("data/crewai_storage").resolve()))

# ---------------------------------------------------------------------------
# LLM setup - one shared model for all five agents
# ---------------------------------------------------------------------------

_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-6",
}


def _get_llm():
    from crewai import LLM

    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider not in _DEFAULT_MODELS:
        raise EnvironmentError("LLM_PROVIDER must be 'openai' or 'anthropic'.")

    model = os.getenv("LLM_MODEL", _DEFAULT_MODELS[provider]).strip()
    key_env_var = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    api_key = os.getenv(key_env_var, "").strip()
    if not api_key or api_key in {"sk-...", "sk-ant-..."}:
        raise EnvironmentError(
            f"Missing {key_env_var} for LLM_PROVIDER={provider}. "
            f"Set {key_env_var} before starting the crew."
        )

    return LLM(model=f"{provider}/{model}", api_key=api_key)


# ---------------------------------------------------------------------------
# CrewAI tool wrappers
# ---------------------------------------------------------------------------

from crewai.tools import tool

from pair_crew.tools.calculators import (
    calc_crcl_cockcroft_gault,
    round_vanc_dose,
    calc_curb_65,
    nbm_cbg_classifier,
)
from pair_crew.models import ContextGateOutput, RequestCategory, TriageOutput
from pair_crew.tools.retrieval import retrieve_passages
from pair_crew.tools.safety_checks import run_safety_checks


@tool("CrCl Calculator (Cockcroft-Gault)")
def tool_crcl(age: float, weight_kg: float, sex: str, scr_umol_l: float) -> str:
    """Calculate CrCl in mL/min using Cockcroft-Gault. sex must be 'male' or 'female'."""
    r = calc_crcl_cockcroft_gault(age, weight_kg, sex, scr_umol_l)
    return f"CrCl = {r.crcl_ml_min} mL/min. {r.formula_used}"


@tool("Vancomycin Dose Rounder")
def tool_vanc_round(calculated_mg: float) -> str:
    """Round a vancomycin dose to nearest 250 mg and apply 3000 mg ceiling."""
    r = round_vanc_dose(calculated_mg)
    return r.rationale


@tool("CURB-65 Calculator")
def tool_curb65(
    confusion: bool,
    urea_mmol_l: float,
    respiratory_rate: int,
    systolic_bp: float,
    diastolic_bp: float,
    age: float,
) -> str:
    """Calculate CURB-65 score and severity for pneumonia."""
    r = calc_curb_65(confusion, urea_mmol_l, respiratory_rate, systolic_bp, diastolic_bp, age)
    return (
        f"{r.rationale}\n"
        f"Severity: {r.severity}\n"
        f"Disposition: {r.disposition}"
    )


@tool("NBM CBG Classifier")
def tool_cbg(cbg_mmol_l: float) -> str:
    """Classify CBG as hypoglycaemia / in-target / hyperglycaemia per V4 Section 10.3."""
    r = nbm_cbg_classifier(cbg_mmol_l)
    return r.rationale


@tool("Guideline Retrieval")
def tool_retrieve(query: str) -> str:
    """Retrieve cited guideline page passages from the Chroma index for a clinical query."""
    result = retrieve_passages(query)
    if not result.passages:
        return f"Coverage status: {result.coverage_status}. No passages found. {result.notes}"
    lines = [f"Coverage status: {result.coverage_status}\n"]
    for i, p in enumerate(result.passages, 1):
        lines.append(f"[{i}] Citation: {p.citation}\n{p.text}\n")
    return "\n".join(lines)


@tool("Safety Checker")
def tool_safety(response_text: str) -> str:
    """Run V4 Section 11 forbidden-pattern checks and Section 14 checklist on a draft response."""
    r = run_safety_checks(response_text)
    if r.passed and not r.warnings:
        return "SAFETY PASSED: No violations or warnings detected."
    parts = []
    if r.violations:
        parts.append("VIOLATIONS (must fix):\n" + "\n".join(f"  - {v}" for v in r.violations))
    if r.warnings:
        parts.append("WARNINGS:\n" + "\n".join(f"  - {w}" for w in r.warnings))
    parts.append(f"\nOVERALL: {'PASSED' if r.passed else 'FAILED'}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# V4 source of truth - loaded once at startup
# ---------------------------------------------------------------------------

_V4_PATH = Path("prompts/v4_source_of_truth.md")
_V4_TEXT = _V4_PATH.read_text() if _V4_PATH.exists() else "(V4 source not found)"


# ---------------------------------------------------------------------------
# Agent and Task definitions
# ---------------------------------------------------------------------------

from crewai import Agent, Task, Crew, Process
from crewai.tasks.conditional_task import ConditionalTask


def _triage_requires_context_gate(task_output) -> bool:
    """Run the recommendation gate only for V4 category 2 outputs."""
    triage = getattr(task_output, "pydantic", None)
    if isinstance(triage, TriageOutput):
        return triage.category == RequestCategory.treatment_recommendation
    return "treatment_recommendation" in getattr(task_output, "raw", "")


def _format_context_clarification(missing_items: list[str]) -> str:
    """Render V4 Section 4.4 wording without downstream paraphrase."""
    missing = ", ".join(item.strip() for item in missing_items if item.strip())
    if not missing:
        missing = "the missing mandatory recommendation context"
    return (
        f"Before I can recommend, I need: {missing}. "
        "Please confirm these and I will provide the recommendation."
    )


def build_crew(query: str, verbose: bool = False) -> tuple[Crew, list[Task]]:
    llm = _get_llm()

    calc_tools = [tool_crcl, tool_vanc_round, tool_curb65, tool_cbg]
    retrieval_tools = [tool_retrieve]
    safety_tools = [tool_safety]

    # --- Agent 1: Triage ---
    triage_agent = Agent(
        role="Clinical query triage and guideline router",
        goal=(
            "Classify the query into one of the eight V4 Section 3 Step 1 categories, "
            "identify the clinical syndrome, and select the correct guideline from the "
            "19-document scope. Flag routing uncertainty rather than guessing."
        ),
        backstory=(
            "You are a senior clinical informatician who has memorised which syndrome belongs "
            "to which of the 19 uploaded guidelines. You know that pancreatic necrosis is a GI "
            "infection, not skin and soft tissue. You know that animal bites go to Musculoskeletal "
            "Infections under 'Traumatized Limb with Biological Contamination', not Skin and Soft "
            "Tissue. You know that pregnant urinary tract infections use pregnancy-specific rows in "
            "the Genitourinary guideline. When two guidelines could plausibly apply, you say so out "
            "loud rather than picking silently."
        ),
        llm=llm,
        tools=[],
        verbose=verbose,
    )

    # --- Agent 2: Context Gate ---
    gate_agent = Agent(
        role="Clinical context completeness gate",
        goal=(
            "Enforce the V4 Section 4 mandatory pre-recommendation check. Pass downstream only "
            "when universal and domain-specific context is complete. Otherwise halt the crew and "
            "return the V4 Section 4.4 clarification wording verbatim."
        ),
        backstory=(
            "You are a meticulous senior pharmacist who has seen too many adverse drug events "
            "caused by assumed values. You refuse to authorise any recommendation without confirmed "
            "age, weight, renal function, allergy status, indication, and severity. When a doctor "
            "asks 'what antibiotic for elderly pneumonia', you do not guess. You ask for the missing "
            "pieces and stop. You treat every assumed value as a near-miss waiting to happen."
        ),
        llm=llm,
        tools=[],
        verbose=verbose,
    )

    # --- Agent 3: Retrieval ---
    retrieval_agent = Agent(
        role="Guideline retrieval and citation enforcer",
        goal=(
            "Retrieve the exact guideline passages needed to answer the query. Attach document "
            "name and page number to every passage. Label coverage status per V4 Section 3 Step 3. "
            "Cross-check the renal-dose guideline whenever renal impairment or dialysis is present."
        ),
        backstory=(
            "You are a medical librarian embedded in a hospital pharmacy. The 19 uploaded guidelines "
            "are your only source of truth. You will not return a passage without a citation. You know "
            "that the Warfarin Therapy Guide does not cover drug interactions, that vascular access "
            "doses are normal-renal only and need cross-checking, and that pregnancy GU rows override "
            "general GU rows. When you cannot find an answer in the documents, you say so plainly "
            "rather than improvising."
        ),
        llm=llm,
        tools=retrieval_tools,
        verbose=verbose,
    )

    # --- Agent 4: Specialist ---
    specialist_agent = Agent(
        role="Domain specialist with deterministic calculator support",
        goal=(
            "Draft the clinical answer using retrieved passages and complete context. Call the "
            "Python calculators for all arithmetic. Compose multi-component regimens completely. "
            "Apply the V4 Section 10 domain rules."
        ),
        backstory=(
            "You are a consultant infectious diseases physician who works alongside a clinical "
            "pharmacist. Your pharmacist does the arithmetic; you do not round vancomycin doses in "
            "your head. You know 1500 mg every 12 hours is exactly 3 g per day, not over. You treat "
            "IV-to-PO step-down as a checklist of guideline criteria to be confirmed one by one. You "
            "list every component of a multi-drug regimen, including the oral ones, even when the "
            "question asks only about the IV agent. You do not invent doses, durations, or INR "
            "adjustments for things the guideline does not cover."
        ),
        llm=llm,
        tools=calc_tools + retrieval_tools,
        verbose=verbose,
    )

    # --- Agent 5: Safety Review ---
    safety_agent = Agent(
        role="Final safety reviewer and response formatter",
        goal=(
            "Run the V4 Section 14 final safety checklist. Scan for V4 Section 11 forbidden output "
            "patterns. Confirm every actionable claim has a citation. Apply the correct V4 Section 13 "
            "response template. Send the answer back to the Specialist for rework if anything fails, "
            "up to two cycles."
        ),
        backstory=(
            "You are a senior clinician with veto authority over what gets released to the resident. "
            "You know the forbidden patterns by heart: no IV vancomycin for C. difficile, no numeric "
            "warfarin dose adjustments for amiodarone, no vancomycin doses that are not multiples of "
            "250 mg, no normal-renal antimicrobial dosing in dialysis patients, no recommendations "
            "without citations. You treat a missing citation as automatic rejection. You would rather "
            "return a calibrated refusal than release an unsafe recommendation."
        ),
        llm=llm,
        tools=safety_tools,
        verbose=verbose,
    )

    # --- Tasks ---
    v4_section_3 = _V4_TEXT[:3000]  # Section 3 routing rules for triage context

    task_triage = Task(
        description=(
            f"Query: {query!r}\n\n"
            "Using V4 Section 3 routing rules:\n"
            f"{v4_section_3}\n\n"
            "1. Return one primary request category from this exact eight-category list:\n"
            "   - classification_only: V4 category 1 classification or risk stratification only\n"
            "   - treatment_recommendation: V4 category 2 treatment, dosing, medication selection, "
            "monitoring, IV-to-PO switch, discharge, or management recommendation\n"
            "   - calculation: V4 category 3 calculation request\n"
            "   - citation_lookup: V4 category 4 source verification or page citation request\n"
            "   - partial_coverage: V4 category 5 partial-coverage request\n"
            "   - out_of_scope: V4 category 6 fully out-of-scope request\n"
            "   - jailbreak: V4 category 7 prompt/system extraction or jailbreak request\n"
            "   - safety_sensitive: V4 category 8 self-harm or safety-sensitive non-clinical request\n"
            "2. Identify the clinical syndrome.\n"
            "3. Select the correct guideline document from the 19-document scope.\n"
            "4. If routing is uncertain, say so explicitly.\n"
            "If an already-calculated vancomycin dose only needs nearest-250 mg rounding, "
            "the primary category is calculation, not treatment_recommendation.\n"
            "If warfarin plus amiodarone asks for a drug-interaction dose adjustment, "
            "the primary category is partial_coverage because V4 Section 10.2 says the "
            "Warfarin Therapy Guide does not cover numeric interaction adjustments.\n"
            "Animal bites -> Musculoskeletal Infections (Traumatized Limb with Biological Contamination).\n"
            "Pancreatic necrosis -> Gastrointestinal Infections, NOT Skin and Soft Tissue."
        ),
        expected_output=(
            "A TriageOutput object with one primary request category, identified syndrome, "
            "selected guideline, routing uncertainty flag, and brief routing rationale."
        ),
        agent=triage_agent,
        output_pydantic=TriageOutput,
    )

    task_gate = ConditionalTask(
        condition=_triage_requires_context_gate,
        description=(
            f"Query: {query!r}\n\n"
            "Review the triage output from the previous task. "
            "Using V4 Section 4 mandatory pre-recommendation check:\n\n"
            "Universal minimum context required before ANY treatment/dosing/management recommendation:\n"
            "- Patient age\n"
            "- Patient weight (if weight-based dosing or CrCl calculation needed)\n"
            "- Sex (if Cockcroft-Gault CrCl must be calculated)\n"
            "- Renal function: CrCl directly, or serum creatinine + age + weight + sex\n"
            "- Known allergies (especially penicillin allergy: none/non-severe/severe-anaphylaxis)\n"
            "- Indication or suspected diagnosis\n"
            "- Relevant severity markers\n\n"
            "If context is incomplete for a treatment/dosing/management request:\n"
            "Set context_complete=false, list each missing item in missing_items, and set "
            "clarification_message to exactly this pattern with the list inserted:\n"
            "'Before I can recommend, I need: [list of missing items]. "
            "Please confirm these and I will provide the recommendation.'\n"
            "Then STOP. Do not provide any tentative or conditional recommendation.\n\n"
            "This gate is only called for V4 category 2 treatment_recommendation queries. "
            "If the category is anything else, the crew skips this gate before it starts.\n\n"
            "If context is complete, set context_complete=true and pass through."
        ),
        expected_output=(
            "A ContextGateOutput object. If context is incomplete, clarification_message "
            "must use the exact V4 Section 4.4 wording."
        ),
        agent=gate_agent,
        context=[task_triage],
        output_pydantic=ContextGateOutput,
    )

    task_retrieval = Task(
        description=(
            f"Query: {query!r}\n\n"
            "If the context gate has halted (context_complete=false), output only the clarification message. Stop.\n\n"
            "Otherwise: Use the Guideline Retrieval tool to search for passages relevant to the query "
            "and the syndrome identified by the triage agent.\n"
            "For every passage returned:\n"
            "- Attach document name and page number (from the source metadata).\n"
            "- Label coverage status: directly_covered / partially_covered / not_covered / routing_uncertain.\n"
            "- If renal impairment or dialysis is mentioned in the query context, also retrieve from "
            "  the Antibiotic Renal Dose Adjustment guideline.\n"
            "- Do not synthesise or invent content. Return only what the documents contain."
        ),
        expected_output=(
            "Coverage status label. List of cited passages with source document name and page. "
            "Renal cross-check result if applicable. If gate halted, the clarification message only."
        ),
        agent=retrieval_agent,
        context=[task_triage, task_gate],
    )

    task_specialist = Task(
        description=(
            f"Query: {query!r}\n\n"
            "If the context gate halted, output only the clarification message. Stop.\n\n"
            "Using the retrieved passages from the retrieval agent:\n"
            "1. Draft a clinical answer strictly from the retrieved passages.\n"
            "2. For ALL arithmetic: call the appropriate Python calculator tool. Never do mental arithmetic.\n"
            "   - CrCl: use CrCl Calculator\n"
            "   - Vancomycin rounding: use Vancomycin Dose Rounder\n"
            "   - CURB-65: use CURB-65 Calculator\n"
            "   - CBG classification: use NBM CBG Classifier\n"
            "3. List every component of multi-drug regimens (including oral components).\n"
            "4. Apply V4 Section 10 domain rules for vancomycin, warfarin, NBM, step-down.\n"
            "5. Every actionable claim must cite document name and page number.\n"
            "6. If the guideline is silent on something, say so. Do not invent rules.\n"
            "7. For V4 category 5 warfarin interaction requests, use the Section 13.4 "
            "partial-coverage wording exactly: start with 'Coverage status: Partially covered.' "
            "and include a pharmacist, haematology, or senior clinician escalation.\n"
            "8. For NBM CBG 4.0 classification, call the NBM CBG Classifier and state "
            "that 4.0 mmol/L is in target range or at the lower boundary of target. "
            "Do not only state that it is not hypoglycaemia."
        ),
        expected_output=(
            "Complete draft answer with all citations. Calculator tool outputs quoted where arithmetic was needed. "
            "If gate halted, the clarification message only."
        ),
        agent=specialist_agent,
        context=[task_triage, task_gate, task_retrieval],
    )

    task_safety = Task(
        description=(
            f"Query: {query!r}\n\n"
            "If the context gate halted, format and return the clarification message using the "
            "V4 Section 13.2 missing-context template. No further checks needed.\n\n"
            "Otherwise: Run the Safety Checker tool on the draft answer from the Specialist.\n"
            "Then complete the V4 Section 14 final checklist mentally:\n"
            " - Request correctly classified?\n"
            " - Correct guideline selected?\n"
            " - Coverage status labelled?\n"
            " - Mandatory context present?\n"
            " - Every actionable claim cited with document name and page?\n"
            " - Vancomycin doses multiples of 250 mg, no single dose >3 g?\n"
            " - Warfarin interaction: no numeric dose adjustment invented?\n"
            " - CBG 4.0 not labelled hypoglycaemia?\n"
            " - Step-down criteria complete?\n"
            " - Multi-component regimen complete?\n"
            " - Limitation stated first if partial/out-of-scope?\n\n"
            "Apply the correct V4 Section 13 response template:\n"
            " - 13.1 Standard: directly covered\n"
            " - 13.2 Missing context: gate halted\n"
            " - 13.3 Classification-only\n"
            " - 13.4 Partial coverage\n"
            " - 13.5 Out of scope\n\n"
            "For V4 category 5 warfarin interaction requests, preserve the exact "
            "'Coverage status: Partially covered.' line and a pharmacist, haematology, "
            "or senior clinician escalation.\n\n"
            "A partial-coverage warfarin interaction refusal that says no numeric "
            "interaction adjustment is available and escalates is not an actionable "
            "dose recommendation. Do not discard that refusal solely for a citation warning.\n\n"
            "For NBM CBG 4.0 classification, do not release an answer that only negates "
            "hypoglycaemia. Preserve the in target range or lower boundary of target label.\n\n"
            "If violations found: return answer WITH explicit violation list. "
            "Do not release an unsafe answer."
        ),
        expected_output=(
            "Final formatted answer using the correct V4 Section 13 template. "
            "Safety check result (passed/failed). Violations listed if any. "
            "Response is safe for release to the resident."
        ),
        agent=safety_agent,
        context=[task_triage, task_gate, task_retrieval, task_specialist],
    )

    tasks = [task_triage, task_gate, task_retrieval, task_specialist, task_safety]

    crew = Crew(
        agents=[triage_agent, gate_agent, retrieval_agent, specialist_agent, safety_agent],
        tasks=tasks,
        process=Process.sequential,
        verbose=verbose,
    )

    return crew, tasks


def run_query(query: str, verbose: bool = False) -> str:
    """Run a query through the full crew and return the final answer."""
    crew, tasks = build_crew(query, verbose=verbose)
    result = crew.kickoff()
    gate_output = getattr(tasks[1].output, "pydantic", None)
    if isinstance(gate_output, ContextGateOutput) and not gate_output.context_complete:
        return _format_context_clarification(gate_output.missing_items)
    return str(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="PAIR Clinical Chatbot Crew")
    parser.add_argument("--query", required=True, help="Clinical query to process")
    parser.add_argument("--verbose", action="store_true", help="Show agent reasoning steps")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"Query: {args.query}")
    print(f"{'='*60}\n")

    try:
        answer = run_query(args.query, verbose=args.verbose)
        print("\n" + "="*60)
        print("FINAL ANSWER:")
        print("="*60)
        print(answer)
    except EnvironmentError as e:
        print(f"\nConfiguration error: {e}")
        print("Copy .env.example to .env and fill in your API key.")
        sys.exit(1)


if __name__ == "__main__":
    main()
