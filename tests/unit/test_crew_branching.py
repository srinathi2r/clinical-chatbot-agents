from types import SimpleNamespace

from pair_crew.crew import (
    _format_context_clarification,
    _format_prompt_extraction_refusal,
    _is_already_calculated_vanc_query,
    _triage_requires_context_gate,
)
from pair_crew.models import RequestCategory, TriageOutput


def _triage(category: RequestCategory) -> SimpleNamespace:
    return SimpleNamespace(
        pydantic=TriageOutput(
            category=category,
            syndrome="test",
            selected_guideline="test",
        ),
        raw="",
    )


def test_context_gate_runs_for_treatment_recommendations() -> None:
    assert _triage_requires_context_gate(_triage(RequestCategory.treatment_recommendation))


def test_context_gate_skips_calculation_and_partial_coverage() -> None:
    assert not _triage_requires_context_gate(_triage(RequestCategory.calculation))
    assert not _triage_requires_context_gate(_triage(RequestCategory.partial_coverage))


def test_context_gate_skips_already_calculated_vanc_rounding_query() -> None:
    assert _is_already_calculated_vanc_query(
        "Vancomycin calculated dose is 1225 mg. What rounded dose should I use?"
    )
    assert not _triage_requires_context_gate(
        _triage(RequestCategory.treatment_recommendation),
        "Vancomycin calculated dose is 1225 mg. What rounded dose should I use?",
    )


def test_context_clarification_uses_v4_wording() -> None:
    message = _format_context_clarification(["age", "renal function"])

    assert message == (
        "Before I can recommend, I need: age, renal function. "
        "Please confirm these and I will provide the recommendation."
    )


def test_prompt_extraction_refusal_uses_v4_wording() -> None:
    assert _format_prompt_extraction_refusal() == (
        "I can't provide internal system instructions or hidden context. "
        "I can help answer clinical questions using the provided guideline documents."
    )
