#!/usr/bin/env python3
"""Validate and safely mutate Product Loop V2 run-state documents."""

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from adapter_contracts import (
    ContractError, ExecutionAuthorization, canonical_operation_digest, document_digest,
    verify_execution_authorization,
)
from validate_v2 import ValidationError, load_and_validate, validate_document


TRACKS = ("visualization", "mechanical", "schematic", "pcb")
ROUTES = {
    "visualization": ("skip", "image", "video", "image+video"),
    "mechanical": ("skip", "spec", "direct", "guided", "handoff"),
    "schematic": ("skip", "direct", "guided", "hybrid", "handoff"),
    "pcb": ("skip", "direct", "guided", "hybrid", "handoff"),
}
DECISION_REF_PATTERN = re.compile(
    r"^(?:chat-message|codex-message|approval-record):[A-Za-z0-9][A-Za-z0-9._:-]{7,}$"
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_decision_ref(decision_ref: str) -> str:
    if not isinstance(decision_ref, str) or not DECISION_REF_PATTERN.fullmatch(decision_ref.strip()):
        raise ValidationError(
            "decision reference must be a stable host reference such as "
            "chat-message:<stable-id>, codex-message:<stable-id>, or approval-record:<stable-id>"
        )
    return decision_ref.strip()


def _artifact_key(artifact_id: str, revision: int) -> Tuple[str, int]:
    return artifact_id, revision


def _artifact_ref(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "revision": artifact["revision"],
        "content_hash": artifact["content_hash"],
    }


def _dependency_revisions(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [_artifact_ref(item) for item in state["artifacts"]]


def _route_options(track: str) -> List[Dict[str, str]]:
    return [
        {
            "id": route,
            "label": route,
            "description": f"Set {track} route to {route}.",
            "impact": "Only this track is authorized; other unresolved tracks remain blocked on user choice.",
        }
        for route in ROUTES[track]
    ]


def _resolved_route_decision(
    state: Mapping[str, Any], track: str, route: str, decision_id: str,
    decided_at: str, decision_ref: str
) -> Dict[str, Any]:
    return {
        "decision_id": decision_id,
        "decision_type": "route_selection",
        "scope": [f"track:{track}"],
        "status": "resolved",
        "question": f"Which execution route should the {track} track use?",
        "options": _route_options(track),
        "recommendation": None,
        "recommendation_rationale": None,
        "impact": [
            f"The {track} track is explicitly authorized for route {route}.",
            "Changing this route later requires a new user decision; no fallback is inferred.",
        ],
        "selected_option": route,
        "decided_by": "user",
        "decided_at": decided_at,
        "decision_evidence": [
            {
                "evidence_id": f"evidence-{decision_id}",
                "type": "user_self_report",
                "source": "explicit user route selection",
                "captured_at": decided_at,
                "ref": decision_ref,
                "note": f"User explicitly selected {track}: {route}."
            }
        ],
        "dependency_revisions": _dependency_revisions(state),
    }


def _pending_route_gate(state: Mapping[str, Any], unresolved: Sequence[str]) -> Dict[str, Any]:
    labels = ", ".join(unresolved)
    return {
        "decision_id": "decision-track-routes-pending",
        "decision_type": "route_selection",
        "scope": [f"track:{track}" for track in unresolved],
        "status": "pending",
        "question": f"Select explicit routes for the unresolved tracks: {labels}.",
        "options": [
            {
                "id": "configure_routes",
                "label": "Configure unresolved tracks",
                "description": "Provide one explicit route for each remaining track.",
                "impact": "No unresolved track receives an implicit default.",
            }
        ],
        "recommendation": "configure_routes",
        "recommendation_rationale": "Explicit per-track choices prevent old modes or unavailable tools from becoming hidden defaults.",
        "impact": [
            "Unresolved track routes and route decision IDs remain null.",
            "The run remains waiting_user_decision until all four tracks are resolved.",
        ],
        "selected_option": None,
        "decided_by": None,
        "decided_at": None,
        "decision_evidence": [],
        "dependency_revisions": _dependency_revisions(state),
    }


def _decision_id(state: Mapping[str, Any], track: str) -> str:
    prefix = f"decision-route-{track}-"
    used = {
        item["decision_id"]
        for item in state["decision_ledger"]
        if item["decision_id"].startswith(prefix)
    }
    index = 1
    while f"{prefix}{index:03d}" in used:
        index += 1
    return f"{prefix}{index:03d}"


def _derived_run_status(state: Mapping[str, Any]) -> str:
    statuses = [item["status"] for item in state["artifacts"]]
    statuses.extend(item["status"] for item in state["operation_cards"])
    statuses.extend(item["status"] for item in state["cross_domain_checks"])
    if "waiting_user_decision" in statuses:
        return "waiting_user_decision"
    if "blocked" in statuses:
        return "blocked"
    if "stale" in statuses:
        return "stale"
    if "implemented-unverified" in statuses:
        return "implemented-unverified"
    return "planned"


def resolve_routes(
    state: Mapping[str, Any], selections: Mapping[str, Optional[str]], decision_ref: str
) -> Dict[str, Any]:
    """Resolve only explicitly supplied track routes and record user decisions."""
    validate_document(state, expected_kind="run-state")
    decision_ref = _validate_decision_ref(decision_ref)
    explicit = {track: route for track, route in selections.items() if route is not None}
    if not explicit:
        raise ValidationError("resolve-routes requires at least one explicit track route")
    unknown_tracks = set(explicit) - set(TRACKS)
    if unknown_tracks:
        raise ValidationError(f"unknown tracks: {sorted(unknown_tracks)}")
    pending = state["pending_decision_gate"]
    if pending is not None and pending["decision_type"] != "route_selection":
        raise ValidationError("cannot resolve routes while a non-route user decision is pending")

    updated = copy.deepcopy(state)
    decided_at = _now()
    changed = 0
    for track in TRACKS:
        if track not in explicit:
            continue
        route = explicit[track]
        if route not in ROUTES[track]:
            raise ValidationError(f"track {track!r} does not support route {route!r}")
        current = updated["track_routes"][track]
        if current is not None:
            if current == route:
                continue
            raise ValidationError(
                f"track {track!r} is already resolved as {current!r}; route changes require a separate change gate"
            )
        decision_id = _decision_id(updated, track)
        decision = _resolved_route_decision(
            updated, track, route, decision_id, decided_at, decision_ref
        )
        updated["decision_ledger"].append(decision)
        updated["track_routes"][track] = route
        updated["route_decision_ids"][track] = decision_id
        changed += 1

    if changed == 0:
        raise ValidationError("resolve-routes did not resolve any previously unresolved track")

    unresolved = [track for track in TRACKS if updated["track_routes"][track] is None]
    if unresolved:
        updated["pending_decision_gate"] = _pending_route_gate(updated, unresolved)
        updated["status"] = "waiting_user_decision"
    else:
        updated["pending_decision_gate"] = None
        updated["status"] = _derived_run_status(updated)
    validate_document(updated, expected_kind="run-state")
    return updated


def open_decision(state: Mapping[str, Any], gate: Mapping[str, Any]) -> Dict[str, Any]:
    """Open one non-route decision gate and bind it to current artifact revisions."""
    validate_document(state, expected_kind="run-state")
    if state["pending_decision_gate"] is not None:
        raise ValidationError("cannot open a decision while another user decision is pending")
    if not isinstance(gate, Mapping):
        raise ValidationError("decision gate must be a JSON object")
    updated_gate = copy.deepcopy(dict(gate))
    if updated_gate.get("decision_type") == "route_selection":
        raise ValidationError("route decisions must use resolve-routes")
    if updated_gate.get("decision_id") in {
        item["decision_id"] for item in state["decision_ledger"]
    }:
        raise ValidationError("decision_id is already present in the decision ledger")
    updated_gate.update(
        {
            "status": "pending",
            "selected_option": None,
            "decided_by": None,
            "decided_at": None,
            "decision_evidence": [],
            "dependency_revisions": _dependency_revisions(state),
        }
    )
    updated = copy.deepcopy(state)
    updated["pending_decision_gate"] = updated_gate
    updated["status"] = "waiting_user_decision"
    validate_document(updated, expected_kind="run-state")
    return updated


def resolve_pending_decision(
    state: Mapping[str, Any], selected_option: str, decision_ref: str
) -> Dict[str, Any]:
    """Resolve the single open non-route gate from an explicit user decision."""
    validate_document(state, expected_kind="run-state")
    decision_ref = _validate_decision_ref(decision_ref)
    pending = state["pending_decision_gate"]
    if pending is None:
        raise ValidationError("there is no pending decision to resolve")
    if pending["decision_type"] == "route_selection":
        raise ValidationError("route decisions must use resolve-routes")
    option_ids = {item["id"] for item in pending["options"]}
    if selected_option not in option_ids:
        raise ValidationError(f"selected option {selected_option!r} is not offered by the pending gate")
    updated = copy.deepcopy(state)
    resolved = copy.deepcopy(updated["pending_decision_gate"])
    decided_at = _now()
    resolved.update(
        {
            "status": "resolved",
            "selected_option": selected_option,
            "decided_by": "user",
            "decided_at": decided_at,
            "decision_evidence": [
                {
                    "evidence_id": f"evidence-{resolved['decision_id']}",
                    "type": "user_self_report",
                    "source": "explicit user decision",
                    "captured_at": decided_at,
                    "ref": decision_ref,
                    "note": f"User explicitly selected {selected_option}.",
                }
            ],
        }
    )
    updated["decision_ledger"].append(resolved)
    updated["pending_decision_gate"] = None
    if resolved["decision_type"] == "route_change" and any(
        item.startswith("recovery:") for item in resolved["scope"]
    ):
        step_scope = next(item for item in resolved["scope"] if item.startswith("step:"))
        track_scope = next(item for item in resolved["scope"] if item.startswith("track:"))
        step_id = step_scope.split(":", 1)[1]
        track = track_scope.split(":", 1)[1]
        card = next(item for item in updated["operation_cards"] if item["step_id"] == step_id)
        if selected_option == "pause":
            card["status"] = "blocked"
        else:
            card["status"] = "stale"
            if selected_option != "retry":
                if selected_option not in ROUTES[track]:
                    raise ValidationError("execution recovery selected an invalid replacement route")
                updated["track_routes"][track] = selected_option
                updated["route_decision_ids"][track] = resolved["decision_id"]
    updated["status"] = _derived_run_status(updated)
    validate_document(updated, expected_kind="run-state")
    return updated


def reserve_execution(
    state: Mapping[str, Any], authorization: ExecutionAuthorization
) -> Dict[str, Any]:
    """Reserve one exact adapter call and any high-risk approval in one state update."""
    validate_document(state, expected_kind="run-state")
    try:
        verify_execution_authorization(authorization, required_phase="authorized")
    except ContractError as exc:
        raise ValidationError(f"execution reservation requires a sealed authorization: {exc}") from exc
    if authorization.run_state_digest != document_digest(state):
        raise ValidationError("execution authorization was issued for a different run-state snapshot")
    if state["pending_decision_gate"] is not None or state["status"] in {
        "waiting_user_decision", "stale", "blocked"
    }:
        raise ValidationError("cannot reserve execution while the run is paused or invalid")
    cards = [item for item in state["operation_cards"] if item["step_id"] == authorization.step_id]
    if len(cards) != 1:
        raise ValidationError(f"expected one Operation Card for {authorization.step_id!r}")
    card = cards[0]
    exact = (
        state["run_id"], card["step_id"], card["call_id"], card["attempt_id"],
        card["parameter_digest"], card["route_decision_id"], card["adapter_id"],
        card["execution_capability_id"],
    )
    token_exact = (
        authorization.run_id, authorization.step_id, authorization.call_id,
        authorization.attempt_id, authorization.parameter_digest,
        authorization.route_decision_id, authorization.adapter_id,
        authorization.capability_id,
    )
    if exact != token_exact or card["status"] != "planned":
        raise ValidationError("execution authorization no longer matches the planned Operation Card")
    expected_inputs = tuple(
        f"{item['artifact_id']}@{item['revision']}:{item['content_hash']}"
        for item in card["depends_on"]
    )
    if (
        json.loads(authorization.parameters_json) != card["parameters"]
        or authorization.target_ids != tuple(card["target_ids"])
        or authorization.input_bindings != expected_inputs
        or authorization.operation_digest != canonical_operation_digest(card)
    ):
        raise ValidationError("execution authorization target or input binding is stale")
    matching_operations = [
        operation
        for report in state["capability_reports"]
        if report["track"] == card["track"]
        and report["adapter_id"] == card["adapter_id"]
        and report["status"] == "available"
        for operation in report["operations"]
        if operation["capability_id"] == authorization.capability_id
        and operation["status"] == "available"
    ]
    if len(matching_operations) != 1 or (
        matching_operations[0]["provider_operation"] != authorization.provider_operation
        or matching_operations[0]["risk_class"] != authorization.risk_class
    ):
        raise ValidationError("execution authorization provider binding is stale")
    if any(
        item["step_id"] == card["step_id"] and item["attempt_id"] == card["attempt_id"]
        for item in state["execution_reservations"]
    ):
        raise ValidationError("Operation Card attempt has already been reserved")

    high_risk_decision = None
    if card["risk_level"] in {"high", "destructive"}:
        required_scope = {
            f"run:{state['run_id']}", f"step:{card['step_id']}",
            f"call:{card['call_id']}", f"attempt:{card['attempt_id']}",
            f"parameters:{card['parameter_digest']}",
            f"operation:{canonical_operation_digest(card)}",
        }
        decisions = {
            item["decision_id"]: item for item in state["decision_ledger"]
        }
        candidates = [
            decisions[decision_id]
            for decision_id in card["authorization_decision_ids"]
            if decision_id in decisions
            and decisions[decision_id]["decision_type"] == "high_risk_write"
            and decisions[decision_id]["status"] == "resolved"
            and decisions[decision_id]["decided_by"] == "user"
            and decisions[decision_id]["selected_option"] == authorization.capability_id
            and required_scope.issubset(set(decisions[decision_id]["scope"]))
        ]
        if len(candidates) != 1:
            raise ValidationError("high-risk execution requires exactly one unambiguous approval")
        high_risk_decision = candidates[0]
        if any(
            item["decision_id"] == high_risk_decision["decision_id"]
            for item in state["authorization_consumptions"]
        ):
            raise ValidationError("high-risk authorization has already been consumed")

    updated = copy.deepcopy(state)
    timestamp = _now()
    updated["execution_reservations"].append(
        {
            "reservation_id": f"reservation-{card['attempt_id']}",
            "run_id": updated["run_id"],
            "step_id": card["step_id"],
            "call_id": card["call_id"],
            "attempt_id": card["attempt_id"],
            "parameter_digest": card["parameter_digest"],
            "operation_digest": canonical_operation_digest(card),
            "capability_id": authorization.capability_id,
            "provider_operation": authorization.provider_operation,
            "risk_class": authorization.risk_class,
            "reserved_at": timestamp,
            "status": "reserved",
            "result_fingerprint": None,
        }
    )
    if high_risk_decision is not None:
        updated["authorization_consumptions"].append(
            {
                "consumption_id": f"consumption-{high_risk_decision['decision_id']}",
                "decision_id": high_risk_decision["decision_id"],
                "run_id": updated["run_id"],
                "step_id": card["step_id"],
                "call_id": card["call_id"],
                "attempt_id": card["attempt_id"],
                "parameter_digest": card["parameter_digest"],
                "operation_digest": canonical_operation_digest(card),
                "capability_id": authorization.capability_id,
                "consumed_at": timestamp,
                "status": "reserved",
                "result_fingerprint": None,
            }
        )
    validate_document(updated, expected_kind="run-state")
    return updated


def record_execution_result(
    state: Mapping[str, Any], step_id: str, attempt_id: str,
    status: str, result_fingerprint: str,
) -> Dict[str, Any]:
    """Finalize a reserved call after mandatory provider readback."""
    validate_document(state, expected_kind="run-state")
    if status not in {"completed", "failed", "unknown"}:
        raise ValidationError("execution result status must be completed, failed, or unknown")
    if not isinstance(result_fingerprint, str) or not result_fingerprint.strip():
        raise ValidationError("execution result requires a non-empty readback fingerprint")
    matches = [
        item for item in state["execution_reservations"]
        if item["step_id"] == step_id and item["attempt_id"] == attempt_id
    ]
    if len(matches) != 1 or matches[0]["status"] != "reserved":
        raise ValidationError("expected one still-reserved execution attempt")
    updated = copy.deepcopy(state)
    for item in updated["execution_reservations"]:
        if item["step_id"] == step_id and item["attempt_id"] == attempt_id:
            item["status"] = status
            item["result_fingerprint"] = result_fingerprint.strip()
    for item in updated["authorization_consumptions"]:
        if item["step_id"] == step_id and item["attempt_id"] == attempt_id:
            item["status"] = status
            item["result_fingerprint"] = result_fingerprint.strip()
    if status in {"failed", "unknown"}:
        card = next(item for item in updated["operation_cards"] if item["step_id"] == step_id)
        card["status"] = "waiting_user_decision"
        track = card["track"]
        route_options = [
            route for route in ("guided", "hybrid", "handoff")
            if route in ROUTES[track] and route != updated["track_routes"][track]
        ]
        options = [
            {
                "id": "retry", "label": "Retry with a new attempt",
                "description": "Keep the approved route but create a new Operation Card after readback.",
                "impact": "The current attempt stays immutable and cannot be reused.",
            },
            *[
                {
                    "id": route, "label": f"Change route to {route}",
                    "description": f"Replace only the {track} execution route.",
                    "impact": "The old Operation Card remains stale audit history.",
                }
                for route in route_options
            ],
            {
                "id": "pause", "label": "Pause this branch",
                "description": "Do not issue another write attempt.",
                "impact": "The affected branch remains blocked.",
            },
        ]
        updated["pending_decision_gate"] = {
            "decision_id": f"decision-recovery-{attempt_id}",
            "decision_type": "route_change",
            "scope": [f"track:{track}", f"step:{step_id}", f"attempt:{attempt_id}",
                      f"recovery:{status}"],
            "status": "pending",
            "question": "The provider result is not safely reusable. Choose how this branch continues.",
            "options": options,
            "recommendation": "pause",
            "recommendation_rationale": "A fresh user choice prevents a hidden retry or route fallback.",
            "impact": [
                "The old attempt remains recorded with its readback fingerprint.",
                "No further provider write is authorized until this gate is resolved.",
            ],
            "selected_option": None, "decided_by": None, "decided_at": None,
            "decision_evidence": [], "dependency_revisions": copy.deepcopy(card["depends_on"]),
        }
        updated["status"] = "waiting_user_decision"
    validate_document(updated, expected_kind="run-state")
    return updated


def apply_route_change(
    state: Mapping[str, Any], track: str, decision_id: str
) -> Dict[str, Any]:
    """Apply a separately resolved user route-change decision; never infer fallback."""
    validate_document(state, expected_kind="run-state")
    if state["pending_decision_gate"] is not None:
        raise ValidationError("cannot change route while a user decision is pending")
    if track not in TRACKS:
        raise ValidationError(f"unknown track {track!r}")
    decision = next(
        (item for item in state["decision_ledger"] if item["decision_id"] == decision_id),
        None,
    )
    if (
        decision is None
        or decision["status"] != "resolved"
        or decision["decided_by"] != "user"
        or decision["decision_type"] != "route_change"
        or f"track:{track}" not in decision["scope"]
        or decision["selected_option"] not in ROUTES[track]
    ):
        raise ValidationError("route change requires an exact resolved user decision")
    new_route = decision["selected_option"]
    if state["track_routes"][track] == new_route:
        raise ValidationError("route change does not change the selected route")
    updated = copy.deepcopy(state)
    updated["track_routes"][track] = new_route
    updated["route_decision_ids"][track] = decision_id
    for card in updated["operation_cards"]:
        if card["track"] == track:
            card["status"] = "stale"
    updated["status"] = _derived_run_status(updated)
    validate_document(updated, expected_kind="run-state")
    return updated


def stale_descendants(
    state: Mapping[str, Any], artifact_id: str, revision: Optional[int], reason: str
) -> Tuple[Dict[str, Any], List[Tuple[str, int]]]:
    """Mark only transitive artifact descendants stale; never stale the source itself."""
    validate_document(state, expected_kind="run-state")
    if not reason:
        raise ValidationError("stale reason must be non-empty")
    artifacts = state["artifacts"]
    candidates = [item for item in artifacts if item["artifact_id"] == artifact_id]
    if not candidates:
        raise ValidationError(f"unknown artifact_id {artifact_id!r}")
    if revision is None:
        source = max(candidates, key=lambda item: item["revision"])
    else:
        matches = [item for item in candidates if item["revision"] == revision]
        if not matches:
            raise ValidationError(f"unknown artifact revision {artifact_id}@{revision}")
        source = matches[0]
    source_key = _artifact_key(source["artifact_id"], source["revision"])

    reverse: Dict[Tuple[str, int], Set[Tuple[str, int]]] = defaultdict(set)
    by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for artifact in artifacts:
        key = _artifact_key(artifact["artifact_id"], artifact["revision"])
        by_key[key] = artifact
        for dependency in artifact["depends_on"]:
            dependency_key = _artifact_key(dependency["artifact_id"], dependency["revision"])
            reverse[dependency_key].add(key)

    affected: List[Tuple[str, int]] = []
    seen: Set[Tuple[str, int]] = {source_key}
    queue = deque(sorted(reverse.get(source_key, set())))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        affected.append(current)
        for child in sorted(reverse.get(current, set())):
            if child not in seen:
                queue.append(child)

    updated = copy.deepcopy(state)
    updated_by_key = {
        _artifact_key(item["artifact_id"], item["revision"]): item
        for item in updated["artifacts"]
    }
    invalidation = {
        "source_artifact_id": source["artifact_id"],
        "source_revision": source["revision"],
        "reason": reason,
    }
    for key in affected:
        artifact = updated_by_key[key]
        artifact["status"] = "stale"
        if invalidation not in artifact["invalidation_reasons"]:
            artifact["invalidation_reasons"].append(copy.deepcopy(invalidation))

    affected_set = set(affected)
    for card in updated["operation_cards"]:
        referenced = {
            _artifact_key(item["artifact_id"], item["revision"])
            for field in ("depends_on", "produces")
            for item in card[field]
        }
        if referenced & affected_set:
            card["status"] = "stale"

    for check in updated["cross_domain_checks"]:
        referenced = {
            _artifact_key(item["artifact_id"], item["revision"])
            for item in (check["interface_ref"], check["cad_ref"], check["pcb_ref"])
            if item is not None
        }
        if referenced & affected_set:
            check["status"] = "stale"

    if updated["pending_decision_gate"] is None and updated["status"] != "blocked" and affected:
        updated["status"] = "stale"

    validate_document(updated, expected_kind="run-state")
    return updated, affected


def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _add_route_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--visualization", choices=ROUTES["visualization"])
    parser.add_argument("--mechanical", choices=ROUTES["mechanical"])
    parser.add_argument("--schematic", choices=ROUTES["schematic"])
    parser.add_argument("--pcb", choices=ROUTES["pcb"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage a Product Loop V2 run-state document.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate without mutation")
    validate_parser.add_argument("input", type=Path)

    resolve_parser = subparsers.add_parser("resolve-routes", help="Resolve explicitly supplied track routes")
    resolve_parser.add_argument("input", type=Path)
    resolve_parser.add_argument("output", type=Path)
    resolve_parser.add_argument(
        "--decision-ref", required=True,
        help="Stable reference to the explicit user message or approval record"
    )
    _add_route_arguments(resolve_parser)

    open_parser = subparsers.add_parser("open-decision", help="Open a non-route decision gate")
    open_parser.add_argument("input", type=Path)
    open_parser.add_argument("output", type=Path)
    open_parser.add_argument("--gate", required=True, type=Path, help="JSON file containing a Decision Gate")

    decide_parser = subparsers.add_parser("resolve-decision", help="Resolve the pending non-route decision")
    decide_parser.add_argument("input", type=Path)
    decide_parser.add_argument("output", type=Path)
    decide_parser.add_argument("--selected-option", required=True)
    decide_parser.add_argument("--decision-ref", required=True)

    result_parser = subparsers.add_parser(
        "record-execution",
        help="Record completed, failed, or unknown provider readback",
    )
    result_parser.add_argument("input", type=Path)
    result_parser.add_argument("output", type=Path)
    result_parser.add_argument("--step-id", required=True)
    result_parser.add_argument("--attempt-id", required=True)
    result_parser.add_argument("--status", required=True, choices=("completed", "failed", "unknown"))
    result_parser.add_argument("--result-fingerprint", required=True)

    change_parser = subparsers.add_parser(
        "change-route", help="Apply a resolved route_change decision"
    )
    change_parser.add_argument("input", type=Path)
    change_parser.add_argument("output", type=Path)
    change_parser.add_argument("--track", required=True, choices=TRACKS)
    change_parser.add_argument("--decision-id", required=True)

    stale_parser = subparsers.add_parser("stale", help="Mark transitive artifact descendants stale")
    stale_parser.add_argument("input", type=Path)
    stale_parser.add_argument("output", type=Path)
    stale_parser.add_argument("--artifact-id", required=True)
    stale_parser.add_argument("--revision", type=int)
    stale_parser.add_argument("--reason", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        state = load_and_validate(args.input, expected_kind="run-state")
        if args.command == "validate":
            print("valid: run_state")
            return 0
        if args.command == "resolve-routes":
            selections = {track: getattr(args, track) for track in TRACKS}
            updated = resolve_routes(state, selections, args.decision_ref)
            _atomic_write(args.output, updated)
            return 0
        if args.command == "open-decision":
            gate = json.loads(args.gate.read_text(encoding="utf-8"))
            updated = open_decision(state, gate)
            _atomic_write(args.output, updated)
            return 0
        if args.command == "resolve-decision":
            updated = resolve_pending_decision(state, args.selected_option, args.decision_ref)
            _atomic_write(args.output, updated)
            return 0
        if args.command == "record-execution":
            updated = record_execution_result(
                state, args.step_id, args.attempt_id,
                args.status, args.result_fingerprint,
            )
            _atomic_write(args.output, updated)
            return 0
        if args.command == "change-route":
            updated = apply_route_change(state, args.track, args.decision_id)
            _atomic_write(args.output, updated)
            return 0
        if args.command == "stale":
            updated, affected = stale_descendants(state, args.artifact_id, args.revision, args.reason)
            _atomic_write(args.output, updated)
            print(json.dumps([f"{artifact_id}@{revision}" for artifact_id, revision in affected]))
            return 0
        raise ValidationError(f"unsupported command {args.command!r}")
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"run-state error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
