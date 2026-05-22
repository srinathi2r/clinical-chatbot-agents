"""
Deterministic clinical calculators.
The LLM must call these functions. It must never perform arithmetic itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Cockcroft-Gault CrCl
# ---------------------------------------------------------------------------

@dataclass
class CrClResult:
    crcl_ml_min: float
    formula_used: str
    inputs: dict


def calc_crcl_cockcroft_gault(
    age: float,
    weight_kg: float,
    sex: str,
    scr_umol_l: float,
) -> CrClResult:
    """
    Return CrCl in mL/min using Cockcroft-Gault.

    sex: 'male' or 'female' (case-insensitive).
    scr_umol_l: serum creatinine in micromol/L (will be converted to mg/dL internally).

    Raises ValueError on invalid inputs.
    """
    sex_lower = sex.strip().lower()
    if sex_lower not in ("male", "female"):
        raise ValueError(f"sex must be 'male' or 'female', got: {sex!r}")
    if age <= 0 or weight_kg <= 0 or scr_umol_l <= 0:
        raise ValueError("age, weight_kg, and scr_umol_l must all be positive numbers")

    scr_mg_dl = scr_umol_l / 88.4
    numerator = (140 - age) * weight_kg
    denominator = 72 * scr_mg_dl
    crcl = numerator / denominator
    if sex_lower == "female":
        crcl *= 0.85

    formula = (
        f"CrCl = {'0.85 x ' if sex_lower == 'female' else ''}"
        f"[(140 - {age}) x {weight_kg}] / [72 x ({scr_umol_l} / 88.4)] "
        f"= {crcl:.1f} mL/min"
    )
    return CrClResult(
        crcl_ml_min=round(crcl, 1),
        formula_used=formula,
        inputs={"age": age, "weight_kg": weight_kg, "sex": sex_lower, "scr_umol_l": scr_umol_l},
    )


# ---------------------------------------------------------------------------
# Vancomycin rounding and ceiling
# ---------------------------------------------------------------------------

@dataclass
class VancRoundResult:
    calculated_mg: float
    rounded_mg: int
    capped: bool
    rationale: str


def round_vanc_dose(calculated_mg: float) -> VancRoundResult:
    """
    Round to nearest 250 mg. Cap single dose at 3000 mg.
    Returns rounded dose and plain-English rationale.
    """
    if calculated_mg <= 0:
        raise ValueError("calculated_mg must be positive")

    nearest_250 = int(
        (Decimal(str(calculated_mg)) / Decimal("250")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        * Decimal("250")
    )
    capped = nearest_250 > 3000
    final_mg = min(nearest_250, 3000)

    rationale_parts = [
        f"Calculated dose {calculated_mg:.0f} mg; "
        f"rounded to nearest 250 mg = {nearest_250} mg."
    ]
    if capped:
        rationale_parts.append(
            f"Single dose capped at 3000 mg per guideline ceiling (calculated rounded value {nearest_250} mg exceeds cap)."
        )

    return VancRoundResult(
        calculated_mg=calculated_mg,
        rounded_mg=final_mg,
        capped=capped,
        rationale=" ".join(rationale_parts),
    )


# ---------------------------------------------------------------------------
# CURB-65
# ---------------------------------------------------------------------------

@dataclass
class Curb65Result:
    score: int
    severity: str
    disposition: str
    components: dict
    rationale: str


def calc_curb_65(
    confusion: bool,
    urea_mmol_l: float,
    respiratory_rate: int,
    systolic_bp: float,
    diastolic_bp: float,
    age: float,
) -> Curb65Result:
    """
    Calculate CURB-65 score and canonical severity labels.

    Criteria:
      C - Confusion (new mental confusion)
      U - Urea > 7 mmol/L
      R - Respiratory rate >= 30/min
      B - Blood pressure: systolic < 90 OR diastolic <= 60 mmHg
      65 - Age >= 65 years

    This calculator does not pair the result with an antibiotic regimen.
    """
    c = bool(confusion)
    u = urea_mmol_l > 7.0
    r = respiratory_rate >= 30
    b = (systolic_bp < 90) or (diastolic_bp <= 60)
    age_flag = age >= 65

    score = sum([c, u, r, b, age_flag])

    if score <= 1:
        severity = "mild"
        disposition = "outpatient"
    elif score == 2:
        severity = "moderate"
        disposition = "inpatient"
    else:
        severity = "severe"
        disposition = "inpatient, consider ICU"

    components = {
        "Confusion": c,
        "Urea > 7 mmol/L": u,
        "Respiratory rate >= 30/min": r,
        "BP systolic < 90 or diastolic <= 60": b,
        "Age >= 65": age_flag,
    }

    rationale = (
        f"CURB-65 = {score}/5. "
        + " | ".join(f"{k}: {'yes' if v else 'no'}" for k, v in components.items())
    )

    return Curb65Result(
        score=score,
        severity=severity,
        disposition=disposition,
        components=components,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# NBM CBG classifier
# ---------------------------------------------------------------------------

@dataclass
class CbgResult:
    cbg_mmol_l: float
    category: str
    rationale: str


def nbm_cbg_classifier(cbg_mmol_l: float) -> CbgResult:
    """
    Classify capillary blood glucose per V4 Section 10.3.

    Target range: 4.0-10.0 mmol/L (inclusive).
    Hypoglycaemia: < 4.0 mmol/L ONLY.
    CBG exactly 4.0 is IN TARGET, not hypoglycaemic.
    Hyperglycaemia: > 10.0 mmol/L.
    """
    if cbg_mmol_l < 4.0:
        category = "hypo"
        rationale = (
            f"CBG {cbg_mmol_l} mmol/L is below 4.0 mmol/L. "
            "Hypoglycaemia protocol applies (V4 Section 10.3)."
        )
    elif cbg_mmol_l <= 10.0:
        category = "in-target"
        rationale = (
            f"CBG {cbg_mmol_l} mmol/L is within target range 4.0-10.0 mmol/L (inclusive). "
            "No hypoglycaemia protocol. CBG 4.0 is in-target, not hypoglycaemia (V4 Section 10.3)."
        )
    else:
        category = "hyper"
        rationale = (
            f"CBG {cbg_mmol_l} mmol/L exceeds 10.0 mmol/L. "
            "Hyperglycaemia management applies (V4 Section 10.3)."
        )

    return CbgResult(cbg_mmol_l=cbg_mmol_l, category=category, rationale=rationale)
