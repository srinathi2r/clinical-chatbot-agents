#!/usr/bin/env python3
"""
Run the five smoke eval scenarios against the PAIR crew.

Usage:
    python scripts/run_eval.py [--scenario <id>] [--verbose]

Prints pass/fail for each scenario with one-line reason.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

SCENARIOS_PATH = Path("tests/eval_scenarios.yaml")


def check_scenario(answer: str, scenario: dict) -> tuple[bool, str]:
    answer_lower = answer.lower()
    missing_expected = []
    hit_forbidden = []

    for pattern in scenario.get("expected_patterns", []):
        if not re.search(re.escape(pattern.lower()), answer_lower):
            missing_expected.append(pattern)

    for pattern in scenario.get("forbidden_patterns", []):
        if re.search(re.escape(pattern.lower()), answer_lower):
            hit_forbidden.append(pattern)

    if hit_forbidden:
        return False, f"Forbidden pattern(s) found: {hit_forbidden}"
    if missing_expected:
        return False, f"Expected pattern(s) not found: {missing_expected}"
    return True, scenario.get("pass_criterion", "All checks passed")


def run_eval(scenario_id: str | None = None, verbose: bool = False) -> None:
    from pair_crew.crew import run_query

    data = yaml.safe_load(SCENARIOS_PATH.read_text())
    scenarios = data["scenarios"]

    if scenario_id:
        scenarios = [s for s in scenarios if s["id"] == scenario_id]
        if not scenarios:
            print(f"No scenario with id '{scenario_id}' found.")
            sys.exit(1)

    results = []
    for s in scenarios:
        print(f"\n{'='*60}")
        print(f"Scenario: {s['name']}")
        print(f"Query: {s['query'][:80]}{'...' if len(s['query'])>80 else ''}")
        print("-" * 60)

        try:
            t0 = time.time()
            answer = run_query(s["query"], verbose=verbose)
            elapsed = time.time() - t0

            passed, reason = check_scenario(answer, s)
            status = "PASS" if passed else "FAIL"
            print(f"Status: {status} ({elapsed:.1f}s)")
            print(f"Reason: {reason}")
            if not passed or verbose:
                print(f"\nAnswer preview:\n{answer[:500]}{'...' if len(answer)>500 else ''}")
            results.append((s["id"], s["name"], passed, reason))
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append((s["id"], s["name"], False, f"Exception: {exc}"))

    print(f"\n{'='*60}")
    print("EVAL SUMMARY")
    print("="*60)
    pass_count = sum(1 for _, _, p, _ in results if p)
    for sid, name, passed, reason in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            print(f"         Reason: {reason}")
    print(f"\n{pass_count}/{len(results)} scenarios passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PAIR crew eval scenarios")
    parser.add_argument("--scenario", help="Run only this scenario id")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_eval(args.scenario, args.verbose)
