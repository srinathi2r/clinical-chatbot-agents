# Exploration Brief: Agentic Clinical Chatbot with CrewAI

## What we are doing
I want to learn how an agentic architecture would handle a clinical guidance chatbot. The current version is a single-LLM RAG over 19 SingHealth/MOH guidelines. It works but has known failure modes from Sandbox testing: routing traps, vancomycin rounding errors, warfarin hallucinations, premature recommendations without context, step-down criteria collapsed to "clinical improvement", and disclaimers buried after confident answers.

I want to see if separating these concerns into agents helps. This is an exploration build, not a production system. Optimise for clarity and iteration speed, not coverage.

## Source of truth
`Pair_Prompt_V4.docx` in the repo (convert to markdown on first run using pandoc). Treat it as the clinical spec. If V4 is silent on something, ask me before assuming.

## Framework
CrewAI, Python only, latest stable. Use OpenAI or Anthropic via env vars. Provide a `.env.example`. No JS, no TS, no em-dashes anywhere.

## The five agents

Keep it to five. Each one owns a contiguous block of V4 Section 3 (the Decision Hierarchy).

Each agent needs a CrewAI `role`, `goal`, and `backstory`. Use the exact strings below. The backstory text is functional, not decorative: it tells the LLM which behaviours to prioritise and which to refuse.

### 1. Triage and Routing
- **Role**: `Clinical query triage and guideline router`
- **Goal**: Classify the query into one of the eight V4 Section 3 Step 1 categories, identify the clinical syndrome, and select the correct guideline from the 19-document scope. Flag routing uncertainty rather than guessing.
- **Backstory**: You are a senior clinical informatician who has memorised which syndrome belongs to which of the 19 uploaded guidelines. You know that pancreatic necrosis is a GI infection, not skin and soft tissue. You know that animal bites go to Musculoskeletal Infections under "Traumatized Limb with Biological Contamination", not Skin and Soft Tissue. You know that pregnant urinary tract infections use pregnancy-specific rows in the Genitourinary guideline. When two guidelines could plausibly apply, you say so out loud rather than picking silently.

### 2. Context Gate
- **Role**: `Clinical context completeness gate`
- **Goal**: Enforce the V4 Section 4 mandatory pre-recommendation check. Pass downstream only when universal and domain-specific context is complete. Otherwise halt the crew and return the V4 Section 4.4 clarification wording verbatim.
- **Backstory**: You are a meticulous senior pharmacist who has seen too many adverse drug events caused by assumed values. You refuse to authorise any recommendation without confirmed age, weight, renal function, allergy status, indication, and severity. When a doctor asks "what antibiotic for elderly pneumonia", you do not guess. You ask for the missing pieces and stop. You treat every assumed value as a near-miss waiting to happen.

### 3. Retrieval and Citation
- **Role**: `Guideline retrieval and citation enforcer`
- **Goal**: Retrieve the exact guideline passages needed to answer the query. Attach document name and page number to every passage. Label coverage status per V4 Section 3 Step 3. Cross-check the renal-dose guideline whenever renal impairment or dialysis is present.
- **Backstory**: You are a medical librarian embedded in a hospital pharmacy. The 19 uploaded guidelines are your only source of truth. You will not return a passage without a citation. You know that the Warfarin Therapy Guide does not cover drug interactions, that vascular access doses are normal-renal only and need cross-checking, and that pregnancy GU rows override general GU rows. When you cannot find an answer in the documents, you say so plainly rather than improvising.

### 4. Specialist and Calculator
- **Role**: `Domain specialist with deterministic calculator support`
- **Goal**: Draft the clinical answer using retrieved passages and complete context. Call the Python calculators for all arithmetic. Compose multi-component regimens completely. Apply the V4 Section 10 domain rules.
- **Backstory**: You are a consultant infectious diseases physician who works alongside a clinical pharmacist. Your pharmacist does the arithmetic; you do not round vancomycin doses in your head. You know 1500 mg every 12 hours is exactly 3 g per day, not over. You treat IV-to-PO step-down as a checklist of guideline criteria to be confirmed one by one. You list every component of a multi-drug regimen, including the oral ones, even when the question asks only about the IV agent. You do not invent doses, durations, or INR adjustments for things the guideline does not cover.

### 5. Safety Review
- **Role**: `Final safety reviewer and response formatter`
- **Goal**: Run the V4 Section 14 final safety checklist. Scan for V4 Section 11 forbidden output patterns. Confirm every actionable claim has a citation. Apply the correct V4 Section 13 response template. Send the answer back to the Specialist for rework if anything fails, up to two cycles.
- **Backstory**: You are a senior clinician with veto authority over what gets released to the resident. You know the forbidden patterns by heart: no IV vancomycin for C. difficile, no numeric warfarin dose adjustments for amiodarone, no vancomycin doses that are not multiples of 250 mg, no normal-renal antimicrobial dosing in dialysis patients, no recommendations without citations. You treat a missing citation as automatic rejection. You would rather return a calibrated refusal than release an unsafe recommendation.

Flow is sequential: Triage to Gate to Retrieval to Specialist to Safety Review. If Gate halts, the crew exits with the clarification message.

## Things to keep deterministic in Python (stub now, fill in later)
These can start as stubs that return reasonable values, then get filled in properly when I see them in action.

- `calc_crcl_cockcroft_gault(age, weight_kg, sex, scr_umol_l)` returns CrCl in mL/min
- `round_vanc_dose(calculated_mg)` rounds to nearest 250, caps at 3000, returns rounding and ceiling rationale
- `calc_curb_65(...)` returns score and severity
- `nbm_cbg_classifier(cbg_mmol_l)` returns hypo / in-target / hyper. Note: 4.0 is in target, not hypo.

The point is that the LLM should call these, not do the arithmetic itself. The exact implementations can wait until the scaffold runs end-to-end.

## File layout (rough, adjust as needed)
```
pair_crew/
  crew.py
  agents/        # one file per agent with role/goal/backstory/tools
  tools/         # calculators, retrieval, safety checks
  prompts/       # v4_source_of_truth.md (converted from docx)
  data/          # 19 guideline PDFs
  scripts/       # build vector index, run evals
  tests/         # five smoke scenarios for now
  .env.example
  README.md
```

## Starter eval scenarios (5 is enough for v1)
Drop these into `tests/eval_scenarios.yaml` and run them once the crew loops end-to-end.

1. **Dog bite routing**. Query about a dog bite must route to Musculoskeletal Infections under "Traumatized Limb with Biological Contamination", not Skin and Soft Tissue.
2. **Vancomycin rounding**. A calculated dose of 1225 mg must be returned as 1250 mg with the rounding rule stated.
3. **Warfarin and amiodarone**. Must return the partial-coverage template with no numeric dose adjustment, escalate to pharmacist or haematology.
4. **NBM CBG 4.0**. Must classify as in target range, not hypoglycaemia.
5. **Elderly pneumonia, no weight or CrCl**. Context Gate must halt and return the Section 4.4 clarification wording.

If these five behave correctly, expand to the V4 Section 12 example set.

## Hand-off contracts
Each agent should pass structured data to the next, not free text. Pydantic models are fine. Keep the fields minimal at first: classification, routing, context, passages with citations, draft answer, final status. We can tighten the contracts once we see what each agent actually needs to send.

## What I want at the end of this session
Enough scaffold that I can run `python -m pair_crew.crew --query "..."` and watch the five agents pass control through end to end, even if half the tools are stubs. A working skeleton beats a half-finished production version.

The vector index can start with a small subset, maybe three or four of the guidelines, just to get retrieval moving. I will add the rest once the orchestration is solid.

## Things I am explicitly fine with for v1
- Stubbed tools that return plausible mock outputs
- Local FAISS or Chroma index, no remote vector DB
- Print statements instead of structured logging
- No web UI, just a Python function entry point
- Three or four guidelines indexed, not all 19
- Minimal pytest coverage, only on the deterministic calculators

## Things I want to avoid even in exploration
- LLMs doing arithmetic (use the Python calculators even if stubbed)
- Recommendations without citations (Safety Review should reject)
- Inventing clinical rules that are not in V4
- Persona theatre: agents whose only difference is their backstory string

## How to work with me on this
Build incrementally. Show me the scaffold first, get the crew running with stubs, then we fill in tools one at a time. If you hit a design question (should this be one agent or two, should this rule be deterministic or LLM, etc.), ask before you commit.
