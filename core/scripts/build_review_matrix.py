#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_v2 import _loads_strict_json, contract_hash, validate_document


DEFAULT_CATEGORIES = [
    "Brief fit",
    "Decision traceability",
    "Visual coherence",
    "Structure plausibility",
    "Component credibility",
    "Electrical readiness",
    "Packaging feasibility",
    "Cross-domain consistency",
    "Execution readiness",
]
MANDATORY_REVIEW_CATEGORIES = {
    "Brief fit",
    "Decision traceability",
    "Structure plausibility",
    "Component credibility",
    "Execution readiness",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an evidence-oriented review report from a Product Loop design pack."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--run-state", type=Path, help="Optional V2 Run State for continuation gating")
    parser.add_argument(
        "--review-results", type=Path,
        help="Optional strict V2 review-results document bound to the Design Pack hash",
    )
    return parser.parse_args()


def stringify(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def table_cell(value):
    return stringify(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def normalize_check(item, index):
    if isinstance(item, dict):
        return {
            "id": item.get("id", f"ac-{index:02d}"),
            "title": item.get("title", "Unnamed check"),
            "priority": item.get("priority", "should"),
            "method": item.get("method", "TBD"),
            "pass_condition": item.get("pass_condition", "TBD"),
            "status": item.get("status", "TBD"),
            "evidence": item.get("evidence", ""),
        }
    return {
        "id": f"ac-{index:02d}",
        "title": stringify(item) or "Unnamed check",
        "priority": "should",
        "method": "TBD",
        "pass_condition": "TBD",
        "status": "TBD",
        "evidence": "",
    }


def category_map(supplied):
    if not isinstance(supplied, list):
        raise ValueError("review_categories must be a list")
    result = {}
    for index, item in enumerate(supplied):
        if not isinstance(item, dict) or not item.get("category"):
            raise ValueError(f"review_categories[{index}] must be an object with category")
        key = str(item["category"]).casefold()
        if key in result:
            raise ValueError(f"review_categories contains duplicate category {item['category']!r}")
        result[key] = item
    return result


def validate_evidence(items, path, *, require_reliable=False, required_types=()):
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} requires structured evidence")
    allowed_types = {
        "api_readback", "source_export", "screenshot", "user_self_report", "unverified"
    }
    evidence_ids = set()
    present_types = set()
    reliable = False
    for index, item in enumerate(items):
        required_fields = {"evidence_id", "type", "source", "captured_at", "ref", "note"}
        if not isinstance(item, dict) or set(item) != required_fields:
            raise ValueError(f"{path}[{index}] has invalid evidence fields")
        if not isinstance(item["evidence_id"], str) or not item["evidence_id"].strip():
            raise ValueError(f"{path}[{index}] has invalid evidence_id")
        if item["evidence_id"] in evidence_ids:
            raise ValueError(f"{path} contains duplicate evidence IDs")
        evidence_ids.add(item["evidence_id"])
        if item["type"] not in allowed_types:
            raise ValueError(f"{path}[{index}] has invalid evidence type")
        if not isinstance(item["source"], str) or not item["source"].strip():
            raise ValueError(f"{path}[{index}] has invalid evidence source")
        if item["captured_at"] is not None and not isinstance(item["captured_at"], str):
            raise ValueError(f"{path}[{index}] has invalid captured_at")
        if item["ref"] is not None and not isinstance(item["ref"], str):
            raise ValueError(f"{path}[{index}] has invalid evidence ref")
        if not isinstance(item["note"], str):
            raise ValueError(f"{path}[{index}] has invalid evidence note")
        present_types.add(item["type"])
        if (
            item["type"] in {"api_readback", "source_export", "screenshot"}
            and isinstance(item["ref"], str) and item["ref"].strip()
            and isinstance(item["captured_at"], str) and item["captured_at"].strip()
        ):
            reliable = True
    if require_reliable and not reliable:
        raise ValueError(f"{path} requires reliable evidence")
    missing_types = set(required_types) - present_types
    if missing_types:
        raise ValueError(f"{path} lacks required evidence types {sorted(missing_types)}")


def validate_review_results(payload, review_results):
    if not isinstance(review_results, dict):
        raise ValueError("review_results must be an object")
    expected_keys = {
        "schema_version", "document_type", "design_pack_ref", "categories",
        "acceptance_results",
    }
    if set(review_results) != expected_keys:
        raise ValueError("review_results has missing or unknown root fields")
    if review_results["schema_version"] != "2.0" or review_results["document_type"] != "review_results":
        raise ValueError("review_results must declare schema_version 2.0 and document_type review_results")
    reference = review_results["design_pack_ref"]
    if not isinstance(reference, dict) or set(reference) != {"artifact_id", "revision", "content_hash"}:
        raise ValueError("review_results design_pack_ref is invalid")
    if (
        reference["artifact_id"] != payload.get("artifact_id")
        or reference["revision"] != payload.get("revision")
        or reference["content_hash"] != contract_hash(payload)
    ):
        raise ValueError("review_results is not bound to the current Design Pack hash")

    categories = review_results["categories"]
    category_results = category_map(categories)
    expected_categories = {item.casefold() for item in DEFAULT_CATEGORIES}
    if set(category_results) != expected_categories:
        raise ValueError("review_results must contain exactly the nine review categories")
    for index, item in enumerate(categories):
        if set(item) != {"category", "status", "evidence", "blocking_issue", "next_action"}:
            raise ValueError(f"review_results.categories[{index}] has invalid fields")
        if item["status"] not in {"pass", "partial", "fail", "not_applicable"}:
            raise ValueError(f"review_results.categories[{index}] has invalid status")
        validate_evidence(
            item["evidence"], f"review_results.categories[{index}].evidence",
            require_reliable=item["status"] in {"pass", "not_applicable"},
        )
        if item["status"] in {"partial", "fail"} and (
            not item["blocking_issue"] or not item["next_action"]
        ):
            raise ValueError(
                f"review_results.categories[{index}] partial/fail requires a blocker and next action"
            )
    results = review_results["acceptance_results"]
    if not isinstance(results, list):
        raise ValueError("review_results.acceptance_results must be a list")
    result_by_id = {}
    for index, item in enumerate(results):
        if not isinstance(item, dict) or set(item) != {"check_id", "status", "evidence"}:
            raise ValueError(f"review_results.acceptance_results[{index}] is invalid")
        if item["check_id"] in result_by_id:
            raise ValueError("review_results contains duplicate acceptance check IDs")
        if item["status"] not in {"pass", "pending", "fail", "waived"}:
            raise ValueError(f"review_results.acceptance_results[{index}] has invalid status")
        definition = next(
            (check for check in payload.get("acceptance_checks", []) if check.get("id") == item["check_id"]),
            None,
        )
        required_types = definition.get("evidence_required", []) if definition else []
        validate_evidence(
            item["evidence"], f"review_results.acceptance_results[{index}].evidence",
            require_reliable=item["status"] == "pass",
            required_types=required_types if item["status"] == "pass" else (),
        )
        result_by_id[item["check_id"]] = item
    expected_check_ids = {item.get("id") for item in payload.get("acceptance_checks", [])}
    if set(result_by_id) != expected_check_ids:
        raise ValueError("review_results acceptance IDs do not exactly match the Design Pack")
    return category_results, result_by_id


def build_matrix(payload, run_state=None, review_results=None):
    if not isinstance(payload, dict):
        raise ValueError("design pack root must be a JSON object")
    if run_state is not None and not isinstance(run_state, dict):
        raise ValueError("run_state must be an object")
    if payload.get("schema_version") == "2.0":
        validate_document(payload, expected_kind="design-pack")
        if run_state is not None:
            validate_document(run_state, expected_kind="run-state")

    lines = [
        "# Review Report",
        "",
        f"- Product goal: {table_cell(payload.get('product_goal', ''))}",
        f"- Artifact status: {table_cell(payload.get('status', 'unverified'))}",
        "",
        "## Category Review",
        "",
        "| Category | Status | Evidence | Blocking issue | Next action |",
        "| --- | --- | --- | --- | --- |",
    ]

    v2 = payload.get("schema_version") == "2.0"
    if review_results is not None:
        supplied, acceptance_results = validate_review_results(payload, review_results)
    else:
        supplied = category_map(payload.get("review_categories", []))
        acceptance_results = {}
    for category in DEFAULT_CATEGORIES:
        item = supplied.get(category.casefold(), {})
        lines.append(
            "| {category} | {status} | {evidence} | {blocking} | {next_action} |".format(
                category=table_cell(category),
                status=table_cell(item.get("status", "TBD")),
                evidence=table_cell(item.get("evidence", "")),
                blocking=table_cell(item.get("blocking_issue", "")),
                next_action=table_cell(item.get("next_action", "")),
            )
        )

    lines.extend(
        [
            "",
            "## Acceptance Matrix",
            "",
            "| ID | Check | Priority | Method | Pass condition | Status | Evidence |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    checks = payload.get("acceptance_checks", [])
    if not isinstance(checks, list):
        raise ValueError("acceptance_checks must be a list")
    normalized_checks = [normalize_check(item, index) for index, item in enumerate(checks, start=1)]
    for item in normalized_checks:
        result = acceptance_results.get(item["id"])
        if result is not None:
            item["status"] = result["status"]
            item["evidence"] = result["evidence"]
    if not normalized_checks:
        lines.append("| ac-00 | No acceptance checks defined | must | TBD | TBD | fail | Add checks before freeze |")
    else:
        for item in normalized_checks:
            check = {key: table_cell(value) for key, value in item.items()}
            lines.append(
                "| {id} | {title} | {priority} | {method} | {pass_condition} | {status} | {evidence} |".format(**check)
            )

    must_failures = [
        item["id"] for item in normalized_checks
        if item["priority"] == "must" and str(item["status"]).casefold() not in {"pass", "passed", "verified"}
    ]
    state_blockers = []
    if v2 and run_state is None:
        state_blockers.append("run_state_missing")
    if v2 and review_results is None:
        state_blockers.append("review_results_missing")
    if run_state is not None:
        if run_state.get("pending_decision_gate") is not None:
            state_blockers.append("pending_user_decision")
        unresolved = [
            track for track, route in run_state.get("track_routes", {}).items() if route is None
        ]
        state_blockers.extend(f"unresolved_route:{track}" for track in unresolved)
        if run_state.get("status") in {"stale", "blocked", "waiting_user_decision"}:
            state_blockers.append(f"run_status:{run_state.get('status')}")
    category_failures = [
        category for category in DEFAULT_CATEGORIES
        if supplied.get(category.casefold(), {}).get("status", "TBD") not in {"pass", "not_applicable"}
        or (
            category in MANDATORY_REVIEW_CATEGORIES
            and supplied.get(category.casefold(), {}).get("status") != "pass"
        )
    ]
    can_continue = (
        bool(normalized_checks) and not must_failures and not state_blockers
        and not category_failures
    )
    lines.extend(
        [
            "",
            "## Continuation Gate",
            "",
            f"- Decision: {'continue' if can_continue else 'blocked'}",
            f"- Failed must checks: {table_cell(must_failures) or 'none'}",
            f"- Failed review categories: {table_cell(category_failures) or 'none'}",
            f"- Run-state blockers: {table_cell(state_blockers) or 'none'}",
            "- Rule: a blocked report must not be treated as authorization to continue.",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    try:
        payload = _loads_strict_json(args.input.read_text(encoding="utf-8"))
        run_state = (
            _loads_strict_json(args.run_state.read_text(encoding="utf-8"))
            if args.run_state is not None
            else None
        )
        review_results = (
            _loads_strict_json(args.review_results.read_text(encoding="utf-8"))
            if args.review_results is not None
            else None
        )
        rendered = build_matrix(payload, run_state, review_results)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
