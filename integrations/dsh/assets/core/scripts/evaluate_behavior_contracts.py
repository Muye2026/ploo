#!/usr/bin/env python3
"""Evaluate captured Product Loop responses against machine-readable behavior cases.

This harness does not invoke a model. A host records the resulting state plus
observable behaviors/actions from a real skill run, then this script checks the
record against the checked-in policy cases.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


class BehaviorEvaluationError(ValueError):
    pass


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise BehaviorEvaluationError(f"{path}:{line_number}: row must be an object")
        rows.append(value)
    return rows


def _unique_by_id(rows: Iterable[Mapping[str, Any]], label: str) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise BehaviorEvaluationError(f"{label}: every row needs a non-empty id")
        if identifier in result:
            raise BehaviorEvaluationError(f"{label}: duplicate id {identifier!r}")
        result[identifier] = row
    return result


def evaluate_response_set(
    cases: Iterable[Mapping[str, Any]], responses: Iterable[Mapping[str, Any]]
) -> List[str]:
    case_by_id = _unique_by_id(cases, "cases")
    response_by_id = _unique_by_id(responses, "responses")
    failures: List[str] = []
    missing = set(case_by_id) - set(response_by_id)
    extra = set(response_by_id) - set(case_by_id)
    if missing:
        failures.append(f"missing responses: {sorted(missing)}")
    if extra:
        failures.append(f"unknown responses: {sorted(extra)}")
    for identifier in sorted(set(case_by_id) & set(response_by_id)):
        case = case_by_id[identifier]
        response = response_by_id[identifier]
        if response.get("state") != case.get("expected_state"):
            failures.append(
                f"{identifier}: state {response.get('state')!r} != {case.get('expected_state')!r}"
            )
        observations = response.get("observations")
        actions = response.get("actions")
        if not isinstance(observations, list) or not all(isinstance(item, str) for item in observations):
            failures.append(f"{identifier}: observations must be a string array")
            observations = []
        if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
            failures.append(f"{identifier}: actions must be a string array")
            actions = []
        missing_observations = set(case.get("must_include", [])) - set(observations)
        prohibited_actions = set(case.get("must_not_do", [])) & set(actions)
        if missing_observations:
            failures.append(f"{identifier}: missing observations {sorted(missing_observations)}")
        if prohibited_actions:
            failures.append(f"{identifier}: prohibited actions {sorted(prohibited_actions)}")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Product Loop captured behavior responses")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--responses", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        failures = evaluate_response_set(load_jsonl(args.cases), load_jsonl(args.responses))
    except (OSError, json.JSONDecodeError, BehaviorEvaluationError) as exc:
        print(f"behavior evaluation error: {exc}", file=sys.stderr)
        return 2
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: all behavior contracts satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
