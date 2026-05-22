"""
Pydantic hand-off contracts between agents.
Keep fields minimal - only what the downstream agent needs.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class RequestCategory(str, Enum):
    classification_only = "classification_only"
    treatment_recommendation = "treatment_recommendation"
    calculation = "calculation"
    citation_lookup = "citation_lookup"
    partial_coverage = "partial_coverage"
    out_of_scope = "out_of_scope"
    jailbreak = "jailbreak"
    safety_sensitive = "safety_sensitive"


class CoverageStatus(str, Enum):
    directly_covered = "directly_covered"
    partially_covered = "partially_covered"
    not_covered = "not_covered"
    routing_uncertain = "routing_uncertain"
    calculation_derived = "calculation_derived"


class TriageOutput(BaseModel):
    category: RequestCategory
    syndrome: str
    selected_guideline: str
    routing_uncertain: bool = False
    routing_rationale: str = ""
    raw_query: str = ""


class ContextGateOutput(BaseModel):
    context_complete: bool
    missing_items: list[str] = []
    clarification_message: str = ""
    triage: Optional[TriageOutput] = None


class CitedPassage(BaseModel):
    text: str
    source: str
    page_hint: str = ""


class RetrievalOutput(BaseModel):
    coverage_status: CoverageStatus
    passages: list[CitedPassage] = []
    renal_cross_check_needed: bool = False
    renal_passages: list[CitedPassage] = []
    context_gate: Optional[ContextGateOutput] = None


class SpecialistOutput(BaseModel):
    draft_answer: str
    calculator_calls: list[str] = []
    retrieval: Optional[RetrievalOutput] = None


class FinalOutput(BaseModel):
    answer: str
    safety_passed: bool
    violations: list[str] = []
    warnings: list[str] = []
    template_used: str = ""
