from types import SimpleNamespace

from pair_crew.crew import _format_context_clarification, _triage_requires_context_gate
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


def test_context_clarification_uses_v4_wording() -> None:
    message = _format_context_clarification(["age", "renal function"])

    assert message == (
        "Before I can recommend, I need: age, renal function. "
        "Please confirm these and I will provide the recommendation."
    )
