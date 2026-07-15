#!/usr/bin/env python3

"""Deterministically normalize legacy Product Loop design packs.

This helper performs shape normalization only. It never chooses V2 execution routes.
"""

import argparse
import copy
import json
import sys
from collections import OrderedDict
from pathlib import Path


DEFAULTS = OrderedDict(
    [
        ("product_goal", ""),
        ("hard_constraints", []),
        ("component_envelopes", []),
        ("reference_cases", []),
        ("component_requirements", []),
        ("component_candidates", []),
        ("selected_components", []),
        ("packaging_constraints", []),
        ("sourcing_risks", []),
        ("layout_zones", []),
        ("mounting_strategy", {}),
        ("style_features", []),
        ("manufacturing_risks", []),
        ("forbidden_features", []),
        ("acceptance_checks", []),
    ]
)

LIST_FIELDS = {
    "hard_constraints",
    "component_envelopes",
    "reference_cases",
    "component_requirements",
    "component_candidates",
    "selected_components",
    "packaging_constraints",
    "sourcing_risks",
    "layout_zones",
    "style_features",
    "manufacturing_risks",
    "forbidden_features",
    "acceptance_checks",
}
VALID_MODES = {"full", "spec-only", "handoff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize a Product Loop design-pack JSON document."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    return parser.parse_args()


def normalize(data, warnings=None):
    if not isinstance(data, dict):
        raise ValueError("design pack root must be a JSON object")

    messages = warnings if warnings is not None else []
    source = copy.deepcopy(data)
    normalized = OrderedDict()
    is_v2 = source.get("schema_version") == "2.0"

    if is_v2:
        normalized["schema_version"] = source.pop("schema_version")

    if "execution_mode" in source:
        execution_mode = source.pop("execution_mode")
        if execution_mode not in VALID_MODES:
            raise ValueError(
                "execution_mode must be one of: full, spec-only, handoff"
            )
        normalized["execution_mode"] = execution_mode

    for key, default in DEFAULTS.items():
        missing = key not in source
        value = source.pop(key, copy.deepcopy(default))
        if missing:
            messages.append(f"inserted missing field: {key}")

        if key in LIST_FIELDS:
            if value is None:
                value = []
                messages.append(f"normalized null to empty list: {key}")
            elif not isinstance(value, list):
                value = [value]
                messages.append(f"wrapped scalar as list: {key}")
        elif key == "mounting_strategy":
            if value is None:
                value = {}
                messages.append("normalized null to object: mounting_strategy")
            elif not isinstance(value, dict):
                raise ValueError("mounting_strategy must be an object")
        elif value is None:
            value = copy.deepcopy(default)
            messages.append(f"replaced null value: {key}")

        normalized[key] = value

    for key in sorted(source):
        normalized[key] = source[key]

    return normalized


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        warnings = []
        normalized = normalize(payload, warnings)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
