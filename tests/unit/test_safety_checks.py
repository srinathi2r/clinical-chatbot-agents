from pair_crew.tools.safety_checks import run_safety_checks


def test_safety_allows_calculated_vancomycin_value_before_rounding() -> None:
    result = run_safety_checks(
        "Calculated vancomycin dose 1225 mg; rounded dose 1250 mg. "
        "Source: Vancomycin_TDM_non_ESRF.pdf, page 1."
    )

    assert result.passed


def test_safety_rejects_unrounded_vancomycin_recommendation() -> None:
    result = run_safety_checks(
        "Give vancomycin 1225 mg. Source: Vancomycin_TDM_non_ESRF.pdf, page 1."
    )

    assert not result.passed


def test_safety_allows_negated_cbg_4_hypoglycaemia_statement() -> None:
    result = run_safety_checks(
        "CBG 4.0 mmol/L is not hypoglycaemia and is in target range. "
        "Source: NBM_Guidance_2023.pdf, page 1."
    )

    assert result.passed


def test_safety_rejects_affirmative_cbg_4_hypoglycaemia_statement() -> None:
    result = run_safety_checks(
        "CBG 4.0 mmol/L is hypoglycaemia. Source: NBM_Guidance_2023.pdf, page 1."
    )

    assert not result.passed


def test_safety_rejects_cbg_classification_without_nbm_page_citation() -> None:
    result = run_safety_checks("CBG 3.8 mmol/L is hypoglycaemia.")

    assert not result.passed
    assert any("SGH NBM Guidance" in violation for violation in result.violations)


def test_safety_allows_cbg_classification_with_nbm_page_citation() -> None:
    result = run_safety_checks(
        "CBG 3.8 mmol/L is hypoglycaemia. Source: SGH NBM Guidance 2023, page 1."
    )

    assert result.passed


def test_safety_does_not_warn_on_warfarin_partial_coverage_refusal() -> None:
    result = run_safety_checks(
        "Coverage status: Partially covered. Warfarin numeric interaction "
        "adjustments are not covered. Safety escalation: Please consult pharmacist."
    )

    assert result.passed
    assert result.warnings == []


def test_safety_does_not_warn_on_warfarin_interaction_scope_refusal() -> None:
    result = run_safety_checks(
        "Coverage status: Partially covered. The Warfarin Therapy Guide does not "
        "provide a metronidazole interaction dose adjustment."
    )

    assert result.passed
    assert result.warnings == []


def test_safety_ignores_non_vancomycin_antimicrobial_doses() -> None:
    result = run_safety_checks(
        "Use IV clindamycin 600 mg and IV ciprofloxacin 400 mg. "
        "Source: Musculoskeletal_Infections.pdf, page 1."
    )

    assert result.passed
