#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_v2 import _loads_strict_json, contract_hash, validate_document


HEAD_KEYS = ("name", "case", "module", "candidate", "selection", "id", "title")
HANDOFF_DATA_KEYS = {
    "schema_version",
    "document_type",
    "design_pack_ref",
    "modeling_target",
    "expected_fidelity",
    "priority_constraints",
    "suggested_work_split",
    "open_questions",
    "recovery_notes",
}
DESIGN_PACK_REF_KEYS = {"artifact_id", "revision", "content_hash"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit a markdown handoff brief from a Ploo design pack."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--run-state", type=Path, help="Optional V2 Run State for routes, artifacts, and pending gates")
    parser.add_argument(
        "--handoff-data",
        type=Path,
        help="Strict external V2 handoff data bound to the current Design Pack hash",
    )
    return parser.parse_args()


def inline(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def render_list(items, empty_text="None provided."):
    if items is None:
        items = []
    if not isinstance(items, list):
        items = [items]
    if not items:
        return f"- {empty_text}"

    lines = []
    for item in items:
        if isinstance(item, dict):
            head_key = next((key for key in HEAD_KEYS if item.get(key) not in (None, "")), None)
            head = inline(item[head_key]) if head_key else "Item"
            details = [
                f"{key}: {inline(value)}"
                for key, value in item.items()
                if key != head_key
            ]
            lines.append(f"- {head}" + (f" — {'; '.join(details)}" if details else ""))
        else:
            lines.append(f"- {inline(item)}")
    return "\n".join(lines)


def combine_items(*values):
    combined = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            combined.extend(value)
        else:
            combined.append(value)
    return combined


def section(lines, title, body):
    lines.extend(["", f"## {title}", body])


def _require_nonempty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"handoff_data.{field} must be a non-empty string")


def validate_handoff_data(handoff_data, payload):
    if not isinstance(handoff_data, dict):
        raise ValueError("handoff_data must be an object")
    supplied = set(handoff_data)
    if supplied != HANDOFF_DATA_KEYS:
        missing = sorted(HANDOFF_DATA_KEYS - supplied)
        extra = sorted(supplied - HANDOFF_DATA_KEYS)
        raise ValueError(
            f"handoff_data fields must match the strict V2 contract; missing={missing}, extra={extra}"
        )
    if handoff_data["schema_version"] != "2.0":
        raise ValueError("handoff_data.schema_version must equal '2.0'")
    if handoff_data["document_type"] != "handoff_data":
        raise ValueError("handoff_data.document_type must equal 'handoff_data'")
    try:
        json.dumps(handoff_data, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"handoff_data must contain finite JSON values: {exc}") from exc

    reference = handoff_data["design_pack_ref"]
    if not isinstance(reference, dict) or set(reference) != DESIGN_PACK_REF_KEYS:
        raise ValueError(
            "handoff_data.design_pack_ref must contain exactly artifact_id, revision, and content_hash"
        )
    _require_nonempty_string(reference["artifact_id"], "design_pack_ref.artifact_id")
    if not isinstance(reference["revision"], int) or isinstance(reference["revision"], bool) or reference["revision"] < 1:
        raise ValueError("handoff_data.design_pack_ref.revision must be a positive integer")
    _require_nonempty_string(reference["content_hash"], "design_pack_ref.content_hash")
    expected_reference = {
        "artifact_id": payload["artifact_id"],
        "revision": payload["revision"],
        "content_hash": contract_hash(payload),
    }
    if reference != expected_reference:
        raise ValueError("handoff_data.design_pack_ref must match the current Design Pack revision and contract hash")

    for field in ("modeling_target", "expected_fidelity"):
        _require_nonempty_string(handoff_data[field], field)
    for field in (
        "priority_constraints",
        "suggested_work_split",
        "open_questions",
        "recovery_notes",
    ):
        if not isinstance(handoff_data[field], list):
            raise ValueError(f"handoff_data.{field} must be a list")


def build_brief(payload, run_state=None, handoff_data=None):
    if not isinstance(payload, dict):
        raise ValueError("design pack root must be a JSON object")
    if run_state is not None and not isinstance(run_state, dict):
        raise ValueError("run_state must be an object")

    is_v2 = payload.get("schema_version") == "2.0" or payload.get("document_type") == "design_pack"
    if is_v2:
        validate_document(payload, expected_kind="design_pack")
        if run_state is not None:
            validate_document(run_state, expected_kind="run_state")
        if handoff_data is not None:
            validate_handoff_data(handoff_data, payload)
        handoff = handoff_data or {}
    else:
        if handoff_data is not None:
            raise ValueError("--handoff-data requires a V2 Design Pack")
        if run_state is not None and run_state.get("schema_version") == "2.0":
            validate_document(run_state, expected_kind="run_state")
        handoff = payload.get("handoff", {})
        if handoff is None:
            handoff = {}
        if not isinstance(handoff, dict):
            raise ValueError("handoff must be an object")
    mounting = payload.get("mounting_strategy", {}) or {}
    if not isinstance(mounting, dict):
        raise ValueError("mounting_strategy must be an object")

    if is_v2 and handoff_data is None:
        modeling_target = "Not provided; handoff is blocked pending explicit handoff data."
        fidelity = "Not provided."
    else:
        modeling_target = handoff.get("modeling_target") or payload.get("product_goal") or "Define the first implementation target."
        fidelity = handoff.get("expected_fidelity") or "State the required fidelity before downstream work."
    selected_routes = [] if is_v2 else handoff.get("selected_routes") or payload.get("selected_routes") or []
    source_artifacts = [] if is_v2 else handoff.get("source_artifacts", [])
    open_questions = handoff.get("open_questions", [])
    recovery_notes = handoff.get("recovery_notes", [])
    if run_state is not None:
        routes = run_state.get("track_routes", {})
        decision_ids = run_state.get("route_decision_ids", {})
        selected_routes = [
            {
                "id": track,
                "route": route,
                "decision_id": decision_ids.get(track),
                "authorization": "resolved" if route is not None else "waiting_user_decision",
            }
            for track, route in routes.items()
        ]
        source_artifacts = run_state.get("artifacts", [])
        pending = run_state.get("pending_decision_gate")
        if pending is not None:
            open_questions = combine_items(open_questions, [
                {
                    "id": pending.get("decision_id", "pending-decision"),
                    "question": pending.get("question", "User decision required."),
                    "options": [item.get("id") for item in pending.get("options", [])],
                }
            ])
        recovery_notes = combine_items(
            recovery_notes,
            [
                {
                    "id": item.get("artifact_id"),
                    "status": item.get("status"),
                    "invalidation_reasons": item.get("invalidation_reasons", []),
                }
                for item in run_state.get("artifacts", [])
                if item.get("status") in {"stale", "blocked"}
            ],
        )

    v2_blockers = []
    if is_v2:
        if handoff_data is None:
            v2_blockers.append("A hash-bound `handoff_data` document is required.")
        if run_state is None:
            v2_blockers.append("A validated Run State with explicit user-selected routes is required.")
        else:
            if run_state["pending_decision_gate"] is not None:
                v2_blockers.append("A user decision is still pending.")
            unresolved = [
                track for track, route in run_state["track_routes"].items() if route is None
            ]
            if unresolved:
                v2_blockers.append(f"Routes remain unresolved: {', '.join(unresolved)}.")
            if run_state["status"] in {"waiting_user_decision", "stale", "blocked"}:
                v2_blockers.append(f"Run State status is {run_state['status']}.")
            handoff_routes = {
                "mechanical": {"spec", "handoff"},
                "schematic": {"handoff"},
                "pcb": {"handoff"},
            }
            approved_handoff_tracks = [
                track for track, allowed in handoff_routes.items()
                if run_state["track_routes"].get(track) in allowed
            ]
            if not approved_handoff_tracks:
                v2_blockers.append(
                    "No mechanical spec/handoff, schematic handoff, or PCB handoff route was approved."
                )

    lines = ["# Handoff Brief"]
    if is_v2:
        if v2_blockers:
            status_body = (
                "- Status: blocked\n"
                "- Maturity: draft\n"
                f"- Reason: {' '.join(v2_blockers)}"
            )
            if handoff_data is not None:
                status_body += (
                    f"\n- Design Pack binding: {inline(handoff_data['design_pack_ref'])}"
                )
        else:
            status_body = (
                "- Status: ready\n"
                "- Maturity: user-supplied\n"
                f"- Design Pack binding: {inline(handoff_data['design_pack_ref'])}"
            )
        section(lines, "Handoff status", status_body)
    section(lines, "Target", f"- Modeling or EDA target: {inline(modeling_target)}\n- Expected fidelity: {inline(fidelity)}")
    section(lines, "User-selected routes", render_list(selected_routes, "No route recorded; user selection is required before implementation."))
    section(lines, "Source artifacts", render_list(source_artifacts, "Record artifact IDs, revisions, and hashes."))
    section(lines, "Critical envelope and hard constraints", render_list(payload.get("hard_constraints", []), "Add hard constraints before downstream work."))
    section(lines, "Priority constraints", render_list(handoff.get("priority_constraints", []), "Separate must-preserve constraints from user-approved relaxations."))
    section(lines, "Suggested work split", render_list(handoff.get("suggested_work_split") or mounting.get("suggested_part_split", []), "Define the downstream work split."))
    section(lines, "Reference cases", render_list(payload.get("reference_cases", []), "No reference cases recorded."))
    section(lines, "Component requirements", render_list(payload.get("component_requirements", []), "No component requirements recorded."))
    section(lines, "Candidate components", render_list(payload.get("component_candidates", []), "No candidate components recorded."))
    section(lines, "Selected or assumed components", render_list(payload.get("selected_components", []), "No selected or user-approved provisional components recorded."))
    section(lines, "Component envelopes", render_list(payload.get("component_envelopes", []), "No component envelopes recorded."))
    section(lines, "Packaging constraints", render_list(payload.get("packaging_constraints", []), "No packaging constraints recorded."))
    section(lines, "Layout and mounting", render_list(payload.get("layout_zones", []), "No layout zones recorded."))
    section(lines, "Style features to preserve", render_list(payload.get("style_features", []), "No style features recorded."))
    section(lines, "Risks", render_list(combine_items(payload.get("manufacturing_risks"), payload.get("sourcing_risks")), "No risks recorded."))
    section(lines, "Forbidden features", render_list(payload.get("forbidden_features", []), "No forbidden features recorded."))
    section(lines, "Acceptance checks", render_list(payload.get("acceptance_checks", []), "No acceptance checks recorded."))
    section(lines, "Open decisions and questions", render_list(open_questions, "No open questions recorded."))
    section(lines, "Recovery and stale descendants", render_list(recovery_notes, "No recovery notes recorded."))
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
        handoff_data = (
            _loads_strict_json(args.handoff_data.read_text(encoding="utf-8"))
            if args.handoff_data is not None
            else None
        )
        rendered = build_brief(payload, run_state, handoff_data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
