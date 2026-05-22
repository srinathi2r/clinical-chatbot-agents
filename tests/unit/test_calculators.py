"""
Deterministic calculator tests. No LLM calls here.
"""
import pytest
from pair_crew.tools.calculators import (
    calc_crcl_cockcroft_gault,
    round_vanc_dose,
    vanc_frequency_decision,
    calc_curb_65,
    nbm_cbg_classifier,
)


# ---------------------------------------------------------------------------
# Cockcroft-Gault
# ---------------------------------------------------------------------------

class TestCrCl:
    def test_male_known_values(self):
        # (140-70)*70 / (72 * (100/88.4)) = 70*70 / (72*1.1312...) = 4900 / 81.45 = 60.15
        r = calc_crcl_cockcroft_gault(age=70, weight_kg=70, sex="male", scr_umol_l=100)
        assert 58 < r.crcl_ml_min < 63

    def test_female_is_0_85_of_male(self):
        m = calc_crcl_cockcroft_gault(age=50, weight_kg=60, sex="male", scr_umol_l=80)
        f = calc_crcl_cockcroft_gault(age=50, weight_kg=60, sex="female", scr_umol_l=80)
        assert abs(f.crcl_ml_min - m.crcl_ml_min * 0.85) < 0.5

    def test_invalid_sex_raises(self):
        with pytest.raises(ValueError, match="sex must be"):
            calc_crcl_cockcroft_gault(60, 70, "other", 90)

    def test_zero_weight_raises(self):
        with pytest.raises(ValueError):
            calc_crcl_cockcroft_gault(60, 0, "male", 90)

    def test_case_insensitive_sex(self):
        r = calc_crcl_cockcroft_gault(40, 80, "MALE", 70)
        assert r.crcl_ml_min > 0


# ---------------------------------------------------------------------------
# Vancomycin rounding
# ---------------------------------------------------------------------------

class TestVancRounding:
    def test_rounds_to_nearest_250(self):
        r = round_vanc_dose(1225)
        assert r.rounded_mg == 1250

    def test_rounds_down_when_closer(self):
        r = round_vanc_dose(1100)
        assert r.rounded_mg == 1000

    def test_caps_at_3000(self):
        r = round_vanc_dose(3400)
        assert r.rounded_mg == 3000
        assert r.capped is True

    def test_exactly_3000_not_capped(self):
        r = round_vanc_dose(3000)
        assert r.rounded_mg == 3000
        assert r.capped is False

    def test_1500_not_over_3g_daily_at_q12h(self):
        # 1500 mg Q12H = exactly 3 g/day, not over. Rounding 1500 must stay 1500.
        r = round_vanc_dose(1500)
        assert r.rounded_mg == 1500
        assert r.capped is False

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            round_vanc_dose(0)

    def test_rationale_contains_key_words(self):
        r = round_vanc_dose(1225)
        assert "1225" in r.rationale
        assert "1250" in r.rationale


class TestVancFrequencyDecision:
    @pytest.mark.parametrize("daily_mg", [2999, 3000])
    def test_keeps_q12h_at_or_below_threshold(self, daily_mg):
        r = vanc_frequency_decision(daily_mg)

        assert r.decision == "keep_q12h"

    def test_switches_q8h_above_threshold(self):
        r = vanc_frequency_decision(3001)

        assert r.decision == "switch_to_q8h"


# ---------------------------------------------------------------------------
# CURB-65
# ---------------------------------------------------------------------------

class TestCurb65:
    def test_all_negative_score_0(self):
        r = calc_curb_65(False, 5.0, 20, 120, 80, 40)
        assert r.score == 0
        assert r.severity == "mild"
        assert r.disposition == "outpatient"

    def test_all_positive_score_5(self):
        r = calc_curb_65(True, 8.0, 32, 85, 55, 70)
        assert r.score == 5
        assert r.severity == "severe"
        assert r.disposition == "inpatient, consider ICU"

    def test_urea_exactly_7_not_flagged(self):
        r = calc_curb_65(False, 7.0, 20, 120, 80, 40)
        assert r.components["Urea > 7 mmol/L"] is False

    def test_urea_7_point_1_flagged(self):
        r = calc_curb_65(False, 7.1, 20, 120, 80, 40)
        assert r.components["Urea > 7 mmol/L"] is True

    def test_age_exactly_65_flagged(self):
        r = calc_curb_65(False, 5.0, 20, 120, 80, 65)
        assert r.components["Age >= 65"] is True

    def test_score_2_moderate(self):
        r = calc_curb_65(True, 8.0, 20, 120, 80, 40)
        assert r.score == 2
        assert r.severity == "moderate"
        assert r.disposition == "inpatient"

    def test_bp_systolic_exactly_90_not_flagged(self):
        r = calc_curb_65(False, 5.0, 20, 90, 80, 40)
        assert r.components["BP systolic < 90 or diastolic <= 60"] is False

    def test_bp_diastolic_exactly_60_flagged(self):
        r = calc_curb_65(False, 5.0, 20, 120, 60, 40)
        assert r.components["BP systolic < 90 or diastolic <= 60"] is True


# ---------------------------------------------------------------------------
# NBM CBG classifier
# ---------------------------------------------------------------------------

class TestNbmCbgClassifier:
    def test_4_0_is_in_target_not_hypo(self):
        r = nbm_cbg_classifier(4.0)
        assert r.category == "in-target"

    def test_3_9_is_hypo(self):
        r = nbm_cbg_classifier(3.9)
        assert r.category == "hypo"

    def test_10_0_is_in_target(self):
        r = nbm_cbg_classifier(10.0)
        assert r.category == "in-target"

    def test_10_1_is_hyperglycaemia(self):
        r = nbm_cbg_classifier(10.1)
        assert r.category == "hyper"

    def test_2_5_is_hypo(self):
        r = nbm_cbg_classifier(2.5)
        assert r.category == "hypo"

    def test_7_5_is_in_target(self):
        r = nbm_cbg_classifier(7.5)
        assert r.category == "in-target"
