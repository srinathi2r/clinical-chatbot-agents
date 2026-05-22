from scripts.run_eval import check_scenario


def test_check_scenario_records_optional_miss_without_failing() -> None:
    passed, reason, notes = check_scenario(
        "Musculoskeletal. Traumatised Limb.",
        {
            "expected_patterns": ["Musculoskeletal"],
            "expected_any_patterns": ["Traumatized Limb", "Traumatised Limb"],
            "optional_any_patterns": ["rabies", "ID consultation"],
            "pass_criterion": "ok",
        },
    )

    assert passed
    assert reason == "ok"
    assert notes == ["Optional pattern not found: one of rabies, ID consultation"]
