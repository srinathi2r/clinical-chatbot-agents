"""
Deterministic safety checks matching V4 Section 11 forbidden output patterns
and Section 14 final safety checklist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SafetyCheckResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Patterns that indicate a forbidden output
_FORBIDDEN: list[tuple[str, str, str]] = [
    # (rule_name, regex_pattern, explanation)
    (
        "warfarin_numeric_reduction",
        r"warfarin.{0,80}\d+\s*(%|percent|mg).{0,40}(reduc|decreas|lower)"
        r"|"
        r"(reduce|reduc|decreas|lower).{0,40}warfarin.{0,40}\d+\s*(%|percent|mg)"
        r"|"
        r"warfarin.{0,40}(reduce|decreas|lower).{0,40}\d+\s*(%|percent|mg)",
        "Numeric warfarin dose reduction is forbidden (V4 Section 11). Use partial-coverage template.",
    ),
    (
        "iv_vancomycin_cdiff",
        r"iv\s+vancomycin\s+for\s+(c[\.\s]?\s*diff|clostridium|clostridioides)",
        "IV vancomycin must not be recommended for C. difficile (V4 Section 11).",
    ),
    (
        "cbg_4_labelled_hypo",
        r"(cbg|blood glucose).{0,30}4\.0.{0,30}"
        r"(is|equals|indicates)\s+(hypoglyc|hypo\b)",
        "CBG 4.0 mmol/L must not be labelled hypoglycaemia (V4 Section 11).",
    ),
    (
        "step_down_clinical_improvement_only",
        r"clinical improvement\s+(alone\s+is|is\s+sufficient)",
        "Step-down must not be reduced to 'clinical improvement alone' (V4 Section 11).",
    ),
]


def _looks_like_calculated_value(text: str, start: int) -> bool:
    """Allow an unrounded calculated value when the answer states rounding."""
    preceding = text[max(0, start - 60):start].lower()
    return "calculated" in preceding or "calculation" in preceding


def _vanc_doses_are_multiples_of_250(text: str) -> list[str]:
    """Find vancomycin doses mentioned that are not multiples of 250."""
    violations = []
    # Match amounts explicitly tied to vancomycin, not other antimicrobial doses.
    candidates = re.finditer(
        r"(?:vancomycin|vanc)\s+(\d[\d,]+)\s*mg"
        r"|(\d[\d,]+)\s*mg\s+(?:of\s+)?(?:vancomycin|vanc)",
        text,
        re.IGNORECASE,
    )
    for candidate in candidates:
        if _looks_like_calculated_value(text, candidate.start()):
            continue
        raw = candidate.group(1) or candidate.group(2)
        mg = int(raw.replace(",", ""))
        # Only flag if it looks like a vancomycin dose (100-5000 mg range)
        if 100 <= mg <= 5000 and mg % 250 != 0:
            violations.append(
                f"Vancomycin dose {mg} mg is not a multiple of 250 mg (V4 Section 11)."
            )
    return violations


def _check_vanc_ceiling(text: str) -> list[str]:
    """Check for single vancomycin doses exceeding 3000 mg."""
    violations = []
    candidates = re.finditer(
        r"(?:vancomycin|vanc)\s+(\d[\d,]+)\s*mg"
        r"|(\d[\d,]+)\s*mg\s+(?:of\s+)?(?:vancomycin|vanc)",
        text,
        re.IGNORECASE,
    )
    for candidate in candidates:
        if _looks_like_calculated_value(text, candidate.start()):
            continue
        raw = candidate.group(1) or candidate.group(2)
        mg = int(raw.replace(",", ""))
        if mg > 3000:
            violations.append(
                f"Single vancomycin dose {mg} mg exceeds 3000 mg ceiling (V4 Section 11)."
            )
    return violations


def _check_citations_present(text: str) -> list[str]:
    """Warn if no document citation found in the text."""
    warnings = []
    lower = text.lower()
    partial_coverage_refusal = (
        "partially covered" in lower
        and "warfarin" in lower
        and (
            "numeric" in lower
            or "interaction" in lower
            or "dose-adjustment" in lower
            or "dose adjustment" in lower
        )
        and ("not" in lower or "no " in lower or "does not" in lower)
    )
    if partial_coverage_refusal:
        return warnings

    citation_patterns = [
        r"page\s+\d+",
        r"guideline\s*,?\s*page",
        r"\(.*guideline.*\)",
        r"document\s*:",
        r"source\s*:",
    ]
    has_citation = any(re.search(p, text, re.IGNORECASE) for p in citation_patterns)
    if not has_citation:
        warnings.append(
            "No document citation detected. Every actionable claim requires document name and page number (V4 Section 6)."
        )
    return warnings


def run_safety_checks(response_text: str) -> SafetyCheckResult:
    """
    Run all V4 Section 11 and Section 14 deterministic safety checks.
    Returns SafetyCheckResult with violations (hard failures) and warnings (soft).
    """
    text_lower = response_text.lower()
    violations: list[str] = []
    warnings: list[str] = []

    for rule_name, pattern, explanation in _FORBIDDEN:
        if re.search(pattern, text_lower):
            violations.append(f"[{rule_name}] {explanation}")

    violations.extend(_vanc_doses_are_multiples_of_250(response_text))
    violations.extend(_check_vanc_ceiling(response_text))
    warnings.extend(_check_citations_present(response_text))

    return SafetyCheckResult(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )
