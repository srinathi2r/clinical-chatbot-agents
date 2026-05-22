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

### 1. Triage and Routing
Owns V4 Section 3 Steps 1 to 3 plus Section 5.
Classifies the query, picks the right guideline from the 19, flags routing uncertainty.
Knows the routing traps in 5.3, including the dog bite case going to Musculoskeletal Infections rather than Skin and Soft Tissue.

### 2. Context Gate
Owns V4 Section 4.
Checks universal minimum context (age, weight, CrCl, allergies, indication, severity) and domain-specific context for the routed syndrome. If anything is missing, halts the crew and returns the exact clarification wording from Section 4.4. No assumed values.

### 3. Retrieval and Citation
Owns V4 Sections 5 Step 5 and 6.
Pulls passages from the routed guideline. Every passage carries document name and page number. Labels coverage status: directly covered, partially covered, not covered, routing uncertain, or calculation derived. Cross-checks the renal-dose guideline when CrCl<60 or any dialysis state is present.

### 4. Specialist and Calculator
Owns V4 Sections 8 to 10.
Drafts the answer using retrieved passages and context. Calls Python functions for arithmetic. Composes multi-component regimens completely. Applies domain rules (vancomycin rounding, warfarin scope, NBM thresholds, GU pregnancy rows, CNS source classification, CDI route).

### 5. Safety Review
Owns V4 Sections 7, 11, 13, and 14.
Runs the final checklist, scans for forbidden patterns, confirms citations exist, applies the right response template. Can send the answer back to the Specialist once for rework. After that, escalates to partial-coverage or out-of-scope template.

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
