# clinical-chatbot-agents

An exploration of agentic architecture for a clinical guidance chatbot, built with CrewAI.

## Status

Exploration build. Not production. Iterating on the design before committing to anything.

## Context

This project rebuilds an existing single-LLM RAG chatbot as a multi-agent system. The original chatbot answers clinical queries from junior residents using 19 SingHealth and MOH guideline documents. It was tested in early 2026 under the IMDA Global AI Assurance Sandbox in partnership with Guardrails AI. The Sandbox surfaced consistent failure modes that a single-LLM design struggles to address:

- Routing traps (queries going to the wrong guideline)
- Vancomycin dose-rounding violations
- Warfarin hallucinations (inventing numeric dose adjustments)
- Step-down criteria collapsed to "clinical improvement"
- Recommendations released without complete patient context
- Disclaimers buried after confident answers

This repo is testing whether separating those concerns into distinct agents, each with explicit tools and hand-off contracts, reduces the failure rate. Specifically, the hypothesis is that a five-agent crew can drive the LLM judge flag rate from the Sandbox baseline of 25.3 percent down to below 18 percent on the same query set.

## Architecture

Five agents running sequentially under a CrewAI crew:

1. **Triage and Routing** — classifies the query, picks the right guideline, flags routing uncertainty.
2. **Context Gate** — enforces the mandatory pre-recommendation check; halts the crew if context is incomplete.
3. **Retrieval and Citation** — pulls passages with document name and page number, labels coverage status.
4. **Specialist and Calculator** — drafts the answer; calls deterministic Python functions for arithmetic.
5. **Safety Review** — runs the final checklist, scans for forbidden output patterns, applies the right response template.

Deterministic logic (Cockcroft-Gault CrCl, vancomycin rounding and ceiling, CURB-65, NBM CBG classification) lives in plain Python functions. The LLMs call them; they never do arithmetic.

## Source of truth

`Pair_Prompt_V4.docx` is the clinical specification. All agents load their rules from a markdown copy of this document, generated at build time using pandoc. If the spec is silent, the agents ask rather than assume.

## Files in this repo

- `ClaudeCode_Brief_CrewAI_Exploration.md` — the build brief handed to Claude Code to scaffold the project.
- `Pair_Prompt_V4.docx` — the clinical spec (source of truth).
- `data/sandbox_examples/` — selected Snowglobe simulation JSON files showing real failure cases the crew should prevent.
- `pair_crew/` — Python package containing the CrewAI implementation (created as the project is built out).

## Setup

```
git clone https://github.com/srinathi2r/clinical-chatbot-agents.git
cd clinical-chatbot-agents
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in OPENAI_API_KEY or ANTHROPIC_API_KEY
```

To run a query through the crew:
```
python -m pair_crew.crew --query "Your clinical question here"
```

## Running the eval

Five smoke scenarios cover the distinct failure modes (dog bite routing, vancomycin rounding, warfarin partial coverage, NBM CBG threshold, context gate halt). Run them with:
```
python scripts/run_eval.py
```

## Constraints

- Python only.
- CrewAI for orchestration.
- No clinical recommendation without a document name and page number citation.
- LLMs do not perform arithmetic.
- Agents do not invent rules that are not in V4.

## Background reading

The published IMDA Sandbox case study describing the testing methodology, failure modes, and lessons learnt is available from Changi General Hospital and Guardrails AI. Internal CGH learning synthesis and reviewer notes are held separately and not committed to this repo.

## Author

Srinath Sridharan, AI and Data Science Lead, Changi General Hospital, Singapore.
