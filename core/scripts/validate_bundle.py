#!/usr/bin/env python3
"""Cross-document validator for a complete Product Loop V2 contract bundle."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from adapter_contracts import (
    ExecutionAuthorization, _issue_execution_authorization,
    canonical_operation_digest, document_digest,
)
from build_review_matrix import MANDATORY_REVIEW_CATEGORIES, validate_review_results
from validate_v2 import (
    ValidationError, _loads_strict_json, contract_hash, load_and_validate,
    validate_document,
)


def _artifact_key(artifact_id: str, revision: int) -> str:
    return f"{artifact_id}@{revision}"


def _require_run_artifact(
    run_artifacts: Mapping[str, Mapping[str, Any]], document: Mapping[str, Any]
) -> Mapping[str, Any]:
    key = _artifact_key(document["artifact_id"], document["revision"])
    if key not in run_artifacts:
        raise ValidationError(f"bundle: run state is missing artifact {key}")
    record = run_artifacts[key]
    if record["artifact_type"] != document["document_type"]:
        raise ValidationError(f"bundle: artifact type mismatch for {key}")
    expected_hash = contract_hash(document)
    if document["provenance"]["hash"] != expected_hash:
        raise ValidationError(f"bundle: document contract hash mismatch for {key}")
    if record["content_hash"] != expected_hash:
        raise ValidationError(f"bundle: content hash mismatch for {key}")
    if record["status"] != document["status"]:
        raise ValidationError(f"bundle: status mismatch for {key}")
    return record


def _require_user_decision(
    ledger: Mapping[str, Mapping[str, Any]],
    run_artifacts: Mapping[str, Mapping[str, Any]],
    decision_id: str,
    decision_type: str,
    scope: str,
    selected_option: str,
    artifact_id: str,
    revision: int,
) -> Mapping[str, Any]:
    decision = ledger.get(decision_id)
    if decision is None:
        raise ValidationError(f"bundle: unknown user decision {decision_id!r}")
    if (
        decision["status"] != "resolved"
        or decision["decided_by"] != "user"
        or decision["decision_type"] != decision_type
        or scope not in decision["scope"]
        or decision["selected_option"] != selected_option
    ):
        raise ValidationError(
            f"bundle: decision {decision_id!r} does not authorize {decision_type} for {scope}"
        )
    artifact_key = _artifact_key(artifact_id, revision)
    if artifact_key not in run_artifacts:
        raise ValidationError(f"bundle: decision target artifact {artifact_key} is missing from run state")
    expected_hash = run_artifacts[artifact_key]["content_hash"]
    dependencies = {
        _artifact_key(item["artifact_id"], item["revision"]): item["content_hash"]
        for item in decision["dependency_revisions"]
    }
    if dependencies.get(artifact_key) != expected_hash or expected_hash is None:
        raise ValidationError(
            f"bundle: decision {decision_id!r} is not bound to the current hash of {artifact_key}"
        )
    return decision


def _validate_dependency_refs(
    run_artifacts: Mapping[str, Mapping[str, Any]],
    references: list[Mapping[str, Any]],
    owner: str,
) -> None:
    for reference in references:
        key = _artifact_key(reference["artifact_id"], reference["revision"])
        record = run_artifacts.get(key)
        if record is None:
            raise ValidationError(f"bundle: {owner} depends on missing artifact {key}")
        if reference["content_hash"] != record["content_hash"] or reference["content_hash"] is None:
            raise ValidationError(f"bundle: {owner} dependency hash mismatch for {key}")


def _require_card_dependencies(
    card: Mapping[str, Any], required_documents: tuple[Mapping[str, Any], ...]
) -> None:
    references = {
        _artifact_key(item["artifact_id"], item["revision"]): item["content_hash"]
        for item in card["depends_on"]
    }
    missing = []
    for document in required_documents:
        key = _artifact_key(document["artifact_id"], document["revision"])
        if references.get(key) != contract_hash(document):
            missing.append(key)
    if missing:
        raise ValidationError(
            f"bundle: operation {card['step_id']} lacks current contract dependencies {missing}"
        )


def _require_review_gate(
    run_artifacts: Mapping[str, Mapping[str, Any]],
    design_pack: Mapping[str, Any],
    review_results: Optional[Mapping[str, Any]],
    freeze_decision: Mapping[str, Any],
) -> Mapping[str, Any]:
    if review_results is None:
        raise ValidationError("bundle: verified Design Pack requires hash-bound review results")
    try:
        categories, acceptance_results = validate_review_results(design_pack, review_results)
    except ValueError as exc:
        raise ValidationError(f"bundle: invalid review results: {exc}") from exc

    failed_categories = sorted(
        category
        for category, result in categories.items()
        if result["status"] not in {"pass", "not_applicable"}
        or (
            category in {item.casefold() for item in MANDATORY_REVIEW_CATEGORIES}
            and result["status"] != "pass"
        )
    )
    failed_must_checks = sorted(
        check["id"]
        for check in design_pack["acceptance_checks"]
        if check["priority"] == "must"
        and acceptance_results[check["id"]]["status"] != "pass"
    )
    if failed_categories or failed_must_checks:
        raise ValidationError(
            "bundle: review continuation gate is blocked: "
            f"categories={failed_categories}, must_checks={failed_must_checks}"
        )

    review_digest = document_digest(review_results)
    matches = [
        item for item in run_artifacts.values()
        if item["artifact_type"] == "review_results"
        and item["content_hash"] == review_digest
    ]
    if len(matches) != 1 or matches[0]["status"] != "verified":
        raise ValidationError(
            "bundle: review results require exactly one matching verified Run State artifact"
        )
    review_record = matches[0]
    review_key = _artifact_key(review_record["artifact_id"], review_record["revision"])
    design_key = _artifact_key(design_pack["artifact_id"], design_pack["revision"])
    review_dependencies = {
        _artifact_key(item["artifact_id"], item["revision"]): item["content_hash"]
        for item in review_record["depends_on"]
    }
    if review_dependencies.get(design_key) != contract_hash(design_pack):
        raise ValidationError("bundle: review results artifact is not bound to the current Design Pack")
    freeze_dependencies = {
        _artifact_key(item["artifact_id"], item["revision"]): item["content_hash"]
        for item in freeze_decision["dependency_revisions"]
    }
    if (
        f"review:{review_key}" not in freeze_decision["scope"]
        or freeze_dependencies.get(review_key) != review_digest
    ):
        raise ValidationError(
            "bundle: Design Pack freeze decision is not bound to the passing review results"
        )
    return review_record


def validate_bundle(
    run_state: Mapping[str, Any],
    design_pack: Mapping[str, Any],
    electrical_pack: Mapping[str, Any],
    interface_control: Mapping[str, Any],
    review_results: Optional[Mapping[str, Any]] = None,
) -> None:
    validate_document(run_state, expected_kind="run-state")
    validate_document(design_pack, expected_kind="design-pack")
    validate_document(electrical_pack, expected_kind="electrical-pack")
    validate_document(interface_control, expected_kind="interface-control")

    run_artifacts = {
        _artifact_key(item["artifact_id"], item["revision"]): item
        for item in run_state["artifacts"]
    }
    documents = (design_pack, electrical_pack, interface_control)
    documents_by_key = {
        _artifact_key(item["artifact_id"], item["revision"]): item for item in documents
    }
    for document in documents:
        _require_run_artifact(run_artifacts, document)
    _validate_dependency_refs(
        run_artifacts, electrical_pack["dependencies"], electrical_pack["artifact_id"]
    )
    _validate_dependency_refs(
        run_artifacts, interface_control["dependencies"], interface_control["artifact_id"]
    )

    ledger = {item["decision_id"]: item for item in run_state["decision_ledger"]}

    for item in electrical_pack["open_items"]:
        if item["status"] not in {"resolved", "accepted_provisional"}:
            continue
        _require_user_decision(
            ledger,
            run_artifacts,
            item["decision_id"],
            "open_item_resolution",
            f"open_item:{item['id']}",
            "resolve" if item["status"] == "resolved" else "accept_provisional",
            electrical_pack["artifact_id"],
            electrical_pack["revision"],
        )

    design_freeze_decision = None
    if design_pack["status"] == "verified":
        _require_user_decision(
            ledger,
            run_artifacts,
            design_pack["architecture_decision_id"],
            "architecture_selection",
            f"artifact:{design_pack['artifact_id']}@{design_pack['revision']}",
            "approve_architecture",
            design_pack["artifact_id"],
            design_pack["revision"],
        )
        freeze_decision = _require_user_decision(
            ledger,
            run_artifacts,
            design_pack["freeze_decision_id"],
            "freeze",
            f"artifact:{design_pack['artifact_id']}@{design_pack['revision']}",
            "freeze",
            design_pack["artifact_id"],
            design_pack["revision"],
        )
        design_freeze_decision = freeze_decision
        assumed_items = [
            f"hard_constraint:{item['id']}"
            for item in design_pack["hard_constraints"]
            if item.get("status") == "assumed"
        ] + [
            f"component_envelope:{item['id']}"
            for item in design_pack["component_envelopes"]
            if item["source_status"] == "assumed"
        ]
        missing_exceptions = [
            item for item in assumed_items if f"exception:{item}" not in freeze_decision["scope"]
        ]
        if missing_exceptions:
            raise ValidationError(
                f"bundle: design freeze decision does not record provisional exceptions {missing_exceptions}"
            )
        for component in design_pack["selected_components"]:
            _require_user_decision(
                ledger,
                run_artifacts,
                component["decision_id"],
                "component_selection",
                f"component:{component['id']}",
                component["selection"],
                design_pack["artifact_id"],
                design_pack["revision"],
            )

        _require_review_gate(
            run_artifacts, design_pack, review_results, design_freeze_decision
        )

    if interface_control["status"] == "verified":
        interface_freeze = _require_user_decision(
            ledger,
            run_artifacts,
            interface_control["freeze_decision_id"],
            "freeze",
            f"artifact:{interface_control['artifact_id']}@{interface_control['revision']}",
            "freeze",
            interface_control["artifact_id"],
            interface_control["revision"],
        )
        required_interface_scopes = {"constraint:pcb_geometry"}
        for collection in (
            "mounting_holes", "interface_features", "keepouts", "height_zones", "volumes"
        ):
            required_interface_scopes.update(
                f"constraint:{collection}:{item['id']}"
                for item in interface_control[collection]
                if item["status"] == "confirmed"
            )
        missing_scopes = required_interface_scopes - set(interface_freeze["scope"])
        if missing_scopes:
            raise ValidationError(
                f"bundle: Interface Control freeze omits material constraints {sorted(missing_scopes)}"
            )

    schematic = electrical_pack["schematic"]
    if schematic["status"] == "frozen":
        if design_pack["status"] != "verified":
            raise ValidationError(
                "bundle: frozen schematic requires a verified Design Pack and passing review gate"
            )
        _require_user_decision(
            ledger,
            run_artifacts,
            schematic["freeze_decision_id"],
            "freeze",
            f"artifact:{schematic['artifact_id']}@{schematic['revision']}",
            "freeze",
            schematic["artifact_id"],
            schematic["revision"],
        )
        schematic_record = run_artifacts.get(
            _artifact_key(schematic["artifact_id"], schematic["revision"])
        )
        if (
            not schematic["source_hash"]
            or schematic_record is None
            or schematic_record["artifact_type"] != "schematic"
            or schematic_record["status"] != "verified"
            or schematic_record["content_hash"] != schematic["source_hash"]
        ):
            raise ValidationError(
                "bundle: frozen schematic requires a verified Run State artifact matching source_hash"
            )
        for device in electrical_pack["selected_devices"]:
            _require_user_decision(
                ledger,
                run_artifacts,
                device["decision_id"],
                "component_selection",
                f"device:{device['id']}",
                device["manufacturer_part"],
                electrical_pack["artifact_id"],
                electrical_pack["revision"],
            )
        for binding in electrical_pack["component_bindings"]:
            _require_user_decision(
                ledger,
                run_artifacts,
                binding["decision_id"],
                "binding_confirmation",
                f"binding:{binding['id']}",
                "confirm_binding",
                electrical_pack["artifact_id"],
                electrical_pack["revision"],
            )

    pcb = electrical_pack["pcb"]
    if pcb["status"] in {"pcb_candidate", "waiting_evt"}:
        if design_pack["status"] != "verified":
            raise ValidationError(
                "bundle: PCB candidate requires a verified Design Pack and passing review gate"
            )
        _require_user_decision(
            ledger,
            run_artifacts,
            pcb["candidate_decision_id"],
            "candidate_selection",
            f"artifact:{pcb['artifact_id']}@{pcb['revision']}",
            "accept_candidate",
            pcb["artifact_id"],
            pcb["revision"],
        )
        pcb_record = run_artifacts.get(
            _artifact_key(pcb["artifact_id"], pcb["revision"])
        )
        if (
            not pcb["source_hash"]
            or pcb_record is None
            or pcb_record["artifact_type"] != "pcb"
            or pcb_record["status"] != "verified"
            or pcb_record["content_hash"] != pcb["source_hash"]
        ):
            raise ValidationError(
                "bundle: PCB candidate requires a verified Run State artifact matching source_hash"
            )
        if pcb["status"] == "waiting_evt":
            evt_ref = pcb["evt_plan_ref"]
            evt_record = None if evt_ref is None else run_artifacts.get(
                _artifact_key(evt_ref["artifact_id"], evt_ref["revision"])
            )
            pcb_key = _artifact_key(pcb["artifact_id"], pcb["revision"])
            evt_dependencies = {
                _artifact_key(item["artifact_id"], item["revision"]): item["content_hash"]
                for item in (evt_record or {}).get("depends_on", [])
            }
            if (
                evt_ref is None
                or evt_record is None
                or evt_record["artifact_type"] != "evt_plan"
                or evt_record["status"] != "verified"
                or evt_record["content_hash"] != evt_ref["content_hash"]
                or evt_dependencies.get(pcb_key) != pcb["source_hash"]
            ):
                raise ValidationError(
                    "bundle: waiting_evt requires a verified EVT plan bound to the current PCB candidate"
                )
        if interface_control["status"] != "verified":
            raise ValidationError("bundle: PCB candidate requires verified Interface Control")
        board_ref = pcb["board_constraint_ref"]
        if (
            board_ref["artifact_id"] != interface_control["artifact_id"]
            or board_ref["revision"] != interface_control["revision"]
            or board_ref["content_hash"] != contract_hash(interface_control)
        ):
            raise ValidationError("bundle: PCB board constraint does not match Interface Control")
        if pcb["schematic_source_hash"] != schematic["source_hash"]:
            raise ValidationError("bundle: PCB source does not match frozen schematic hash")
        _require_user_decision(
            ledger,
            run_artifacts,
            pcb["layer_count_decision_id"],
            "pcb_constraint",
            "pcb:layer_count",
            f"layers:{pcb['layer_count']}",
            electrical_pack["artifact_id"],
            electrical_pack["revision"],
        )
        interface_key = _artifact_key(
            interface_control["artifact_id"], interface_control["revision"]
        )
        pcb_key = _artifact_key(pcb["artifact_id"], pcb["revision"])
        matching_cross_checks = []
        for check in run_state["cross_domain_checks"]:
            if check["status"] != "verified":
                continue
            interface_ref = check["interface_ref"]
            pcb_ref = check["pcb_ref"]
            if (
                interface_ref is None or pcb_ref is None
                or _artifact_key(interface_ref["artifact_id"], interface_ref["revision"]) != interface_key
                or interface_ref["content_hash"] != contract_hash(interface_control)
                or _artifact_key(pcb_ref["artifact_id"], pcb_ref["revision"]) != pcb_key
                or pcb_ref["content_hash"] != pcb["source_hash"]
            ):
                continue
            if run_state["track_routes"]["mechanical"] != "skip":
                cad_ref = check["cad_ref"]
                if cad_ref is None:
                    continue
                cad_record = run_artifacts.get(
                    _artifact_key(cad_ref["artifact_id"], cad_ref["revision"])
                )
                if cad_record is None or cad_record["artifact_type"] != "cad_model" or cad_record["status"] != "verified":
                    continue
            matching_cross_checks.append(check)
        if not matching_cross_checks:
            raise ValidationError(
                "bundle: PCB candidate requires a verified cross-domain geometry check"
            )
        _require_user_decision(
            ledger,
            run_artifacts,
            pcb["stackup_decision_id"],
            "pcb_constraint",
            "pcb:stackup",
            pcb["stackup_source"],
            electrical_pack["artifact_id"],
            electrical_pack["revision"],
        )

    for card in run_state["operation_cards"]:
        if card["track"] == "mechanical":
            if design_pack["status"] != "verified" or interface_control["status"] != "verified":
                raise ValidationError(
                    f"bundle: mechanical operation {card['step_id']} requires frozen Design Pack "
                    "and verified Interface Control"
            )
            _require_card_dependencies(card, (design_pack, interface_control))
        elif card["track"] == "schematic":
            if design_pack["status"] != "verified" or electrical_pack["status"] != "verified":
                raise ValidationError(
                    f"bundle: schematic operation {card['step_id']} requires verified Design and "
                    "Electrical Packs"
                )
            _require_card_dependencies(card, (design_pack, electrical_pack))
        elif card["track"] == "pcb":
            if schematic["status"] != "frozen" or interface_control["status"] != "verified":
                raise ValidationError(
                    f"bundle: PCB operation {card['step_id']} requires frozen schematic "
                    "and verified Interface Control"
                )
            _require_card_dependencies(card, (electrical_pack, interface_control))

    design_refs = {
        (item["artifact_type"], item["artifact_id"], item["revision"]): item
        for item in design_pack.get("artifact_refs", [])
    }
    for key, reference in design_refs.items():
        run_key = _artifact_key(reference["artifact_id"], reference["revision"])
        record = run_artifacts.get(run_key)
        if record is None:
            raise ValidationError(f"bundle: Design Pack references missing artifact {run_key}")
        if record["artifact_type"] != reference["artifact_type"]:
            raise ValidationError(f"bundle: Design Pack reference type mismatch for {run_key}")
        if reference["content_hash"] != record["content_hash"] or reference["content_hash"] is None:
            raise ValidationError(f"bundle: Design Pack reference hash mismatch for {run_key}")
        if run_key in documents_by_key and reference["content_hash"] != contract_hash(documents_by_key[run_key]):
            raise ValidationError(f"bundle: Design Pack reference does not match document {run_key}")


def _require_executable_card_state(
    run_state: Mapping[str, Any],
    card: Mapping[str, Any],
    error_prefix: str,
) -> None:
    artifacts = {
        _artifact_key(item["artifact_id"], item["revision"]): item
        for item in run_state["artifacts"]
    }
    invalid_inputs = [
        key
        for key in (
            _artifact_key(item["artifact_id"], item["revision"])
            for item in card["depends_on"]
        )
        if artifacts[key]["status"] != "verified" or artifacts[key]["invalidation_reasons"]
    ]
    invalid_outputs = [
        key
        for key in (
            _artifact_key(item["artifact_id"], item["revision"])
            for item in card["produces"]
        )
        if artifacts[key]["status"] != "planned" or artifacts[key]["invalidation_reasons"]
    ]
    if invalid_inputs or invalid_outputs:
        raise ValidationError(
            f"{error_prefix}: invalid input dependencies {invalid_inputs} or outputs {invalid_outputs}"
        )


def authorize_execute_step(
    run_state: Mapping[str, Any],
    design_pack: Mapping[str, Any],
    electrical_pack: Mapping[str, Any],
    interface_control: Mapping[str, Any],
    step_id: str,
    attempt_id: str,
    review_results: Optional[Mapping[str, Any]] = None,
) -> ExecutionAuthorization:
    """Fail closed before any adapter write, including low-risk calls."""
    validate_bundle(
        run_state, design_pack, electrical_pack, interface_control, review_results
    )
    if run_state["pending_decision_gate"] is not None:
        raise ValidationError("execution gate: a user decision is pending")
    if run_state["status"] in {"waiting_user_decision", "stale", "blocked"}:
        raise ValidationError(f"execution gate: run status {run_state['status']} blocks writes")
    matches = [item for item in run_state["operation_cards"] if item["step_id"] == step_id]
    if len(matches) != 1:
        raise ValidationError(f"execution gate: expected one Operation Card for {step_id!r}")
    card = matches[0]
    if card["attempt_id"] != attempt_id:
        raise ValidationError("execution gate: attempt_id does not match the Operation Card")
    if card["status"] != "planned":
        raise ValidationError(f"execution gate: Operation Card status {card['status']} is not executable")
    _require_executable_card_state(run_state, card, "execution gate")
    if any(
        item["step_id"] == card["step_id"] and item["attempt_id"] == attempt_id
        for item in run_state["authorization_consumptions"]
    ):
        raise ValidationError("execution gate: this attempt has already consumed an authorization")
    if any(
        item["step_id"] == card["step_id"] and item["attempt_id"] == attempt_id
        for item in run_state["execution_reservations"]
    ):
        raise ValidationError("execution gate: this attempt has already been reserved")
    capability_id = card["execution_capability_id"]
    if capability_id is None:
        raise ValidationError("execution gate: Operation Card has no provider execution capability")
    operation_bindings = [
        operation
        for report in run_state["capability_reports"]
        if report["track"] == card["track"]
        and report["adapter_id"] == card["adapter_id"]
        and report["status"] == "available"
        for operation in report["operations"]
        if operation["capability_id"] == capability_id
        and operation["status"] == "available"
    ]
    if len(operation_bindings) != 1:
        raise ValidationError("execution gate: provider operation binding is not unique and available")
    operation = operation_bindings[0]
    bundle_digest = document_digest(
        {
            "run_state": run_state, "design_pack": design_pack,
            "electrical_pack": electrical_pack,
            "interface_control": interface_control, "review_results": review_results,
        }
    )
    return _issue_execution_authorization(
        run_id=run_state["run_id"],
        step_id=card["step_id"],
        call_id=card["call_id"],
        attempt_id=card["attempt_id"],
        parameter_digest=card["parameter_digest"],
        route_decision_id=card["route_decision_id"],
        adapter_id=card["adapter_id"] or "guided-user",
        capability_id=capability_id,
        provider_operation=operation["provider_operation"],
        risk_class=operation["risk_class"],
        operation_digest=canonical_operation_digest(card),
        parameters=card["parameters"],
        target_ids=card["target_ids"],
        input_bindings=[
            f"{item['artifact_id']}@{item['revision']}:{item['content_hash']}"
            for item in card["depends_on"]
        ],
        run_state_digest=document_digest(run_state),
        bundle_digest=bundle_digest,
        phase="authorized",
    )


def authorize_reserved_execute_step(
    run_state: Mapping[str, Any],
    design_pack: Mapping[str, Any],
    electrical_pack: Mapping[str, Any],
    interface_control: Mapping[str, Any],
    step_id: str,
    attempt_id: str,
    review_results: Optional[Mapping[str, Any]] = None,
) -> ExecutionAuthorization:
    """Issue a one-call lease only after the exact attempt is reserved in state."""
    validate_bundle(
        run_state, design_pack, electrical_pack, interface_control, review_results
    )
    if run_state["pending_decision_gate"] is not None or run_state["status"] in {
        "waiting_user_decision", "stale", "blocked"
    }:
        raise ValidationError("execution lease: the run is paused or invalid")
    cards = [item for item in run_state["operation_cards"] if item["step_id"] == step_id]
    if len(cards) != 1:
        raise ValidationError(f"execution lease: expected one Operation Card for {step_id!r}")
    card = cards[0]
    if card["attempt_id"] != attempt_id or card["status"] != "planned":
        raise ValidationError("execution lease: Operation Card attempt is not planned and exact")
    _require_executable_card_state(run_state, card, "execution lease")
    reservations = [
        item for item in run_state["execution_reservations"]
        if item["step_id"] == step_id and item["attempt_id"] == attempt_id
        and item["status"] == "reserved"
    ]
    if len(reservations) != 1:
        raise ValidationError("execution lease: expected one reserved execution attempt")
    reservation = reservations[0]
    capability_id = card["execution_capability_id"]
    operations = [
        operation
        for report in run_state["capability_reports"]
        if report["track"] == card["track"]
        and report["adapter_id"] == card["adapter_id"]
        and report["status"] == "available"
        for operation in report["operations"]
        if operation["capability_id"] == capability_id
        and operation["status"] == "available"
    ]
    if len(operations) != 1:
        raise ValidationError("execution lease: provider binding is not uniquely available")
    operation = operations[0]
    if (
        reservation["capability_id"] != capability_id
        or reservation["provider_operation"] != operation["provider_operation"]
        or reservation["risk_class"] != operation["risk_class"]
        or reservation["operation_digest"] != canonical_operation_digest(card)
    ):
        raise ValidationError("execution lease: reservation provider binding is stale")
    if card["risk_level"] in {"high", "destructive"}:
        consumptions = [
            item for item in run_state["authorization_consumptions"]
            if item["step_id"] == step_id and item["attempt_id"] == attempt_id
            and item["capability_id"] == capability_id and item["status"] == "reserved"
        ]
        if len(consumptions) != 1:
            raise ValidationError("execution lease: high-risk authorization is not reserved exactly once")
    return _issue_execution_authorization(
        run_id=run_state["run_id"], step_id=card["step_id"], call_id=card["call_id"],
        attempt_id=card["attempt_id"], parameter_digest=card["parameter_digest"],
        route_decision_id=card["route_decision_id"], adapter_id=card["adapter_id"],
        capability_id=capability_id, provider_operation=operation["provider_operation"],
        risk_class=operation["risk_class"],
        operation_digest=canonical_operation_digest(card), parameters=card["parameters"],
        target_ids=card["target_ids"],
        input_bindings=[
            f"{item['artifact_id']}@{item['revision']}:{item['content_hash']}"
            for item in card["depends_on"]
        ],
        run_state_digest=document_digest(run_state),
        bundle_digest=document_digest(
            {
                "run_state": run_state, "design_pack": design_pack,
                "electrical_pack": electrical_pack,
                "interface_control": interface_control, "review_results": review_results,
            }
        ),
        phase="reserved", reservation_id=reservation["reservation_id"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a complete Product Loop V2 bundle.")
    parser.add_argument("--run-state", required=True, type=Path)
    parser.add_argument("--design-pack", required=True, type=Path)
    parser.add_argument("--electrical-pack", required=True, type=Path)
    parser.add_argument("--interface-control", required=True, type=Path)
    parser.add_argument("--review-results", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_state = load_and_validate(args.run_state, expected_kind="run-state")
        design_pack = load_and_validate(args.design_pack, expected_kind="design-pack")
        electrical_pack = load_and_validate(args.electrical_pack, expected_kind="electrical-pack")
        interface_control = load_and_validate(args.interface_control, expected_kind="interface-control")
        review_results = (
            _loads_strict_json(args.review_results.read_text(encoding="utf-8"))
            if args.review_results is not None else None
        )
        validate_bundle(
            run_state, design_pack, electrical_pack, interface_control, review_results
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"invalid bundle: {exc}", file=sys.stderr)
        return 1
    print("valid: product_loop_v2_bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
