#!/usr/bin/env python3
"""Pure, backend-independent safety helpers for CAD and EDA adapters.

These helpers do not call Fusion 360 or EasyEDA. They make the unit boundary,
failure classification, preflight checks, and shared-geometry comparison
deterministic enough to test before a live adapter is used.
"""

import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


class ContractError(ValueError):
    """Raised when an adapter operation violates a V2 safety contract."""


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Immutable result of validating one Operation Card against a full bundle."""

    run_id: str
    step_id: str
    call_id: str
    attempt_id: str
    parameter_digest: str
    route_decision_id: str
    adapter_id: str
    capability_id: str
    provider_operation: str
    risk_class: str
    operation_digest: str
    parameters_json: str
    target_ids: tuple
    input_bindings: tuple
    run_state_digest: str
    bundle_digest: str
    phase: str
    reservation_id: str
    signature: str


_AUTHORIZATION_SECRET = secrets.token_bytes(32)
_USED_EXECUTION_SIGNATURES = set()


def document_digest(document: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(document), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_operation_digest(card: Mapping[str, Any]) -> str:
    """Hash the material, user-visible scope of an Operation Card."""
    fields = (
        "step_id", "goal", "track", "route", "adapter_id", "route_decision_id",
        "ownership", "risk_level", "call_id", "attempt_id", "parameters",
        "parameter_digest", "required_capabilities", "execution_capability_id",
        "preconditions", "target_ids", "expected_delta", "do_not_touch", "rollback",
        "acceptance_checks", "evidence_required", "depends_on", "produces",
    )
    missing = [field for field in fields if field not in card]
    if missing:
        raise ContractError(f"Operation Card material digest lacks fields {missing}")
    return document_digest({field: card[field] for field in fields})


def _authorization_payload(values: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(values), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _issue_execution_authorization(
    *, run_id: str, step_id: str, call_id: str, attempt_id: str,
    parameter_digest: str, route_decision_id: str, adapter_id: str,
    capability_id: str, provider_operation: str, risk_class: str,
    operation_digest: str,
    parameters: Mapping[str, Any], target_ids: Sequence[str],
    input_bindings: Sequence[str], run_state_digest: str,
    bundle_digest: str, phase: str, reservation_id: str = "",
) -> ExecutionAuthorization:
    """Issue an in-process capability token after full-bundle validation."""
    if phase not in {"authorized", "reserved"}:
        raise ContractError("execution authorization phase is invalid")
    parameters_json = json.dumps(
        dict(parameters), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    values = {
        "run_id": run_id, "step_id": step_id, "call_id": call_id,
        "attempt_id": attempt_id, "parameter_digest": parameter_digest,
        "route_decision_id": route_decision_id, "adapter_id": adapter_id,
        "capability_id": capability_id, "provider_operation": provider_operation,
        "risk_class": risk_class, "parameters_json": parameters_json,
        "operation_digest": operation_digest,
        "target_ids": tuple(target_ids), "input_bindings": tuple(input_bindings),
        "run_state_digest": run_state_digest, "bundle_digest": bundle_digest,
        "phase": phase, "reservation_id": reservation_id,
    }
    signature = hmac.new(
        _AUTHORIZATION_SECRET, _authorization_payload(values), hashlib.sha256
    ).hexdigest()
    return ExecutionAuthorization(**values, signature=signature)


def verify_execution_authorization(
    authorization: ExecutionAuthorization, *, required_phase: str = ""
) -> None:
    if not isinstance(authorization, ExecutionAuthorization):
        raise ContractError("validated bundle execution authorization is required")
    values = {
        field: getattr(authorization, field)
        for field in (
            "run_id", "step_id", "call_id", "attempt_id", "parameter_digest",
            "route_decision_id", "adapter_id", "capability_id", "provider_operation",
            "risk_class", "parameters_json", "target_ids", "input_bindings",
            "operation_digest", "run_state_digest", "bundle_digest", "phase", "reservation_id",
        )
    }
    expected = hmac.new(
        _AUTHORIZATION_SECRET, _authorization_payload(values), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, authorization.signature):
        raise ContractError("execution authorization signature is invalid")
    if required_phase and authorization.phase != required_phase:
        raise ContractError(f"execution authorization must be in {required_phase} phase")
    try:
        parameters = json.loads(authorization.parameters_json)
    except json.JSONDecodeError as exc:
        raise ContractError("execution authorization parameters are invalid") from exc
    if canonical_parameter_digest(parameters) != authorization.parameter_digest:
        raise ContractError("execution authorization parameter binding is invalid")


FUSION_DANGEROUS_TOOLS = {
    "execute_code",
    "delete_all",
    "delete_parameter",
    "set_design_type",
    "cam_create_setup",
    "cam_generate_toolpath",
    "cam_post_process",
}

FUSION_TOOL_CAPABILITIES = {
    "execute_code": "cad.execute_code",
    "delete_all": "cad.delete_all",
    "delete_parameter": "cad.delete_parameter",
    "set_design_type": "cad.set_design_type",
    "cam_create_setup": "cad.cam.create_setup",
    "cam_generate_toolpath": "cad.cam.generate_toolpath",
    "cam_post_process": "cad.cam.post_process",
}
DECISION_REF_PATTERN = re.compile(
    r"^(?:chat-message|codex-message|approval-record):[A-Za-z0-9][A-Za-z0-9._:-]{7,}$"
)
DANGEROUS_OPERATION_VERBS = (
    "delete", "remove", "purge", "clear", "destroy", "wipe", "erase",
    "drop", "truncate", "reset", "overwrite",
)


def _finite_number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ContractError(f"{name} must be a finite number")
    return float(value)


def canonical_parameter_digest(parameters: Mapping[str, Any]) -> str:
    """Digest the exact provider call parameters with stable JSON semantics."""
    if not isinstance(parameters, Mapping) or not parameters:
        raise ContractError("parameters must be a non-empty object")
    try:
        encoded = json.dumps(
            dict(parameters), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"parameters are not canonical JSON: {exc}") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def fusion_mm_to_cm(value_mm: float) -> float:
    return _finite_number(value_mm, "value_mm") * 0.1


def fusion_cm_to_mm(value_cm: float) -> float:
    return _finite_number(value_cm, "value_cm") * 10.0


def pcb_mm_to_mil(value_mm: float) -> float:
    return _finite_number(value_mm, "value_mm") / 0.0254


def pcb_mil_to_mm(value_mil: float) -> float:
    return _finite_number(value_mil, "value_mil") * 0.0254


def schematic_mm_to_native(value_mm: float) -> float:
    """Convert mm to EasyEDA schematic native units of 0.01 inch."""
    return _finite_number(value_mm, "value_mm") / 0.254


def schematic_native_to_mm(value_native: float) -> float:
    return _finite_number(value_native, "value_native") * 0.254


def has_order_of_magnitude_error(expected_mm: float, observed_mm: float) -> bool:
    """Detect a likely 10x/0.1x unit-boundary mistake."""
    expected = abs(_finite_number(expected_mm, "expected_mm"))
    observed = abs(_finite_number(observed_mm, "observed_mm"))
    if expected == 0:
        return observed != 0
    ratio = observed / expected
    return ratio >= 8.0 or ratio <= 0.125


def _normalize_operation_name(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower().replace("-", "_")


def _is_dangerous_fusion_tool(tool_name: str) -> bool:
    normalized = _normalize_operation_name(tool_name)
    return (
        normalized in FUSION_DANGEROUS_TOOLS
        or normalized.startswith("cam_")
        or "toolpath" in normalized
        or "post_process" in normalized
        or re.search(
            rf"(?:^|[._/])(?:{'|'.join(DANGEROUS_OPERATION_VERBS)})(?:[._/]|$)",
            normalized,
        ) is not None
    )


def fusion_capability_id(tool_name: str) -> str:
    """Map a provider tool name to the capability ID used by Operation Cards."""
    normalized = _normalize_operation_name(tool_name)
    if normalized in FUSION_TOOL_CAPABILITIES:
        return FUSION_TOOL_CAPABILITIES[normalized]
    if normalized.startswith("cam_"):
        return "cad.cam." + normalized[4:]
    if "toolpath" in normalized or "post_process" in normalized:
        return "cad.cam." + normalized
    if re.search(
        rf"(?:^|[._/])(?:{'|'.join(DANGEROUS_OPERATION_VERBS)})(?:[._/]|$)",
        normalized,
    ):
        return "cad.delete." + normalized
    return "cad.tool." + normalized


def _resolved_export_path(output_path: str, artifact_root: str) -> str:
    root = Path(artifact_root).expanduser().resolve(strict=False)
    output = Path(output_path).expanduser()
    if not output.is_absolute():
        output = root / output
    return str(output.resolve(strict=False))


def _export_escapes_artifact_root(output_path: str, artifact_root: str) -> bool:
    if not output_path or not artifact_root:
        return True
    root = Path(artifact_root).expanduser().resolve(strict=False)
    output = Path(_resolved_export_path(output_path, artifact_root))
    try:
        output.relative_to(root)
    except ValueError:
        return True
    return False


def guard_fusion_tool(
    tool_name: str,
    *,
    run_id: str = "",
    step_id: str = "",
    call_id: str = "",
    attempt_id: str = "",
    parameters: Mapping[str, Any] = None,
    parameter_digest: str = "",
    authorization_decision_ids: Iterable[str] = (),
    decision_ledger: Sequence[Mapping[str, Any]] = (),
    authorization_consumptions: Sequence[Mapping[str, Any]] = (),
    execution_authorization: ExecutionAuthorization = None,
    target_ids: Sequence[str] = (),
    tool_classification: str = "",
    output_path: str = "",
    artifact_root: str = "",
) -> None:
    """Reject dangerous Fusion calls and exports outside the artifact root.

    The selected option uses the same provider-neutral capability ID as an
    Operation Card. One decision binds one run, step, call and canonical
    parameter digest; a generic prior approval cannot authorize a later call.
    """
    verify_execution_authorization(execution_authorization, required_phase="reserved")
    if execution_authorization.signature in _USED_EXECUTION_SIGNATURES:
        raise ContractError(f"{tool_name} execution lease has already been used")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (run_id, step_id, call_id, attempt_id, parameter_digest)
    ):
        raise ContractError(f"{tool_name} requires run, step, call, attempt, and parameter binding")
    actual_parameter_digest = canonical_parameter_digest(parameters)
    if actual_parameter_digest != parameter_digest:
        raise ContractError(f"{tool_name} parameters do not match the authorized digest")
    token_binding = (
        execution_authorization.run_id,
        execution_authorization.step_id,
        execution_authorization.call_id,
        execution_authorization.attempt_id,
        execution_authorization.parameter_digest,
    )
    actual_binding = (run_id, step_id, call_id, attempt_id, parameter_digest)
    if token_binding != actual_binding:
        raise ContractError(f"{tool_name} does not match the validated Operation Card")
    if tool_name != execution_authorization.provider_operation:
        raise ContractError(f"{tool_name} is not the provider operation authorized by the Operation Card")
    if tuple(target_ids) != execution_authorization.target_ids:
        raise ContractError(f"{tool_name} target IDs do not match the validated Operation Card")
    if not execution_authorization.capability_id.startswith("cad."):
        raise ContractError(f"{tool_name} is not authorized by a CAD capability")
    if tool_classification not in {
        "reversible_write", "destructive_write", "export", "render", "verify", "rollback"
    }:
        raise ContractError(f"{tool_name} lacks an execution-safe tool classification")
    if tool_classification != execution_authorization.risk_class:
        raise ContractError(f"{tool_name} classification does not match the capability report")
    parameter_output_path = parameters.get("output_path")
    parameter_artifact_root = parameters.get("artifact_root")
    if output_path and output_path != parameter_output_path:
        raise ContractError(f"{tool_name} output_path is not bound to the authorized parameters")
    if artifact_root and artifact_root != parameter_artifact_root:
        raise ContractError(f"{tool_name} artifact_root is not bound to the authorized parameters")
    is_file_export = tool_classification == "export" or (
        tool_classification == "render" and parameter_output_path is not None
    )
    if is_file_export and (
        not isinstance(parameter_output_path, str)
        or not isinstance(parameter_artifact_root, str)
    ):
        raise ContractError(f"{tool_name} export paths must be present in canonical parameters")
    outside_export = is_file_export and _export_escapes_artifact_root(
        parameter_output_path, parameter_artifact_root
    )
    if (
        tool_classification != "destructive_write"
        and not _is_dangerous_fusion_tool(tool_name)
        and not outside_export
    ):
        _USED_EXECUTION_SIGNATURES.add(execution_authorization.signature)
        return
    decision_capability_id = execution_authorization.capability_id
    required_scope = {
        f"run:{run_id}",
        f"step:{step_id}",
        f"call:{call_id}",
        f"attempt:{attempt_id}",
        f"parameters:{parameter_digest}",
        f"operation:{execution_authorization.operation_digest}",
    }
    if outside_export:
        resolved_output = _resolved_export_path(
            parameter_output_path, parameter_artifact_root
        )
        required_scope.add(f"output:{resolved_output}")
    decisions = {
        item.get("decision_id"): item
        for item in decision_ledger
        if item.get("decision_id") in set(authorization_decision_ids)
    }
    consumptions = {
        item.get("decision_id"): item for item in authorization_consumptions
    }
    valid = [
        item
        for item in decisions.values()
        if item.get("status") == "resolved"
        and item.get("decided_by") == "user"
        and item.get("decision_type") == "high_risk_write"
        and item.get("selected_option") == decision_capability_id
        and required_scope.issubset(set(item.get("scope", [])))
        and any(
            evidence.get("type") == "user_self_report"
            and isinstance(evidence.get("ref"), str)
            and DECISION_REF_PATTERN.fullmatch(evidence["ref"])
            for evidence in item.get("decision_evidence", [])
        )
        and item.get("decision_id") in consumptions
        and consumptions[item.get("decision_id")].get("run_id") == run_id
        and consumptions[item.get("decision_id")].get("step_id") == step_id
        and consumptions[item.get("decision_id")].get("call_id") == call_id
        and consumptions[item.get("decision_id")].get("attempt_id") == attempt_id
        and consumptions[item.get("decision_id")].get("parameter_digest") == parameter_digest
        and consumptions[item.get("decision_id")].get("operation_digest")
        == execution_authorization.operation_digest
        and consumptions[item.get("decision_id")].get("capability_id") == decision_capability_id
        and consumptions[item.get("decision_id")].get("status") == "reserved"
    ]
    if not valid:
        raise ContractError(f"{tool_name} requires separate user authorization")
    _USED_EXECUTION_SIGNATURES.add(execution_authorization.signature)


def classify_fusion_write(
    call_status: str,
    before_fingerprint: str,
    after_fingerprint: str,
    expected_delta_matches: bool,
    rollback_readback_fingerprint: str = "",
) -> str:
    """Classify a write only after scene readback.

    The caller must perform the readback represented by ``after_fingerprint``.
    The result never instructs an automatic retry or route fallback.
    """
    if call_status not in {"success", "error", "timeout"}:
        raise ContractError("call_status must be success, error, or timeout")
    changed = before_fingerprint != after_fingerprint
    if call_status in {"error", "timeout"}:
        if not changed:
            return "failed_no_change"
        return (
            "recovered_waiting_user_decision"
            if rollback_readback_fingerprint == before_fingerprint
            else "rollback_required"
        )
    if not changed:
        return "blocked_no_change"
    if not expected_delta_matches:
        return "rollback_required"
    return "ready_for_verification"


def easyeda_preflight(
    context: Mapping[str, Any],
    execution_authorization: ExecutionAuthorization = None,
) -> List[str]:
    """Return fail-closed blockers for an EasyEDA write preflight.

    The sealed authorization carries IDs and hashes from the validated
    Operation Card; ``context`` carries independent bridge/API readback.
    """
    blockers: List[str] = []
    try:
        verify_execution_authorization(execution_authorization, required_phase="authorized")
    except ContractError:
        blockers.append("bundle_execution_not_authorized")
        return blockers
    try:
        expected = json.loads(execution_authorization.parameters_json)
    except json.JSONDecodeError:
        blockers.append("bundle_execution_binding_mismatch")
        return blockers
    if not execution_authorization.capability_id.startswith(("eda.", "schematic.", "pcb.")):
        blockers.append("wrong_adapter_capability")
    if context.get("run_id") != execution_authorization.run_id:
        blockers.append("wrong_run")
    if context.get("adapter_id") != execution_authorization.adapter_id:
        blockers.append("wrong_adapter")
    if context.get("bridge_service") != "easyeda-bridge":
        blockers.append("bridge_unavailable")

    if not execution_authorization.route_decision_id or (
        context.get("validated_route_decision_id")
        != execution_authorization.route_decision_id
    ):
        blockers.append("route_not_authorized")
    if context.get("validated_operation_step_id") != execution_authorization.step_id:
        blockers.append("operation_card_not_validated")
    if context.get("validated_call_id") != execution_authorization.call_id or (
        context.get("validated_attempt_id") != execution_authorization.attempt_id
    ):
        blockers.append("operation_attempt_not_validated")
    if tuple(context.get("readback_input_bindings", ())) != execution_authorization.input_bindings:
        blockers.append("input_hash_mismatch")

    windows = context.get("window_ids")
    selected_window = expected.get("window_id")
    if not isinstance(windows, list) or not windows:
        blockers.append("no_window")
    elif selected_window is None and len(windows) > 1:
        blockers.append("multiple_windows_require_user_choice")
    elif not selected_window or selected_window not in windows:
        blockers.append("wrong_window")

    expected_targets = {
        f"window:{selected_window}",
        f"project:{expected.get('project_uuid')}",
        f"document:{expected.get('document_uuid')}",
        f"document_type:{expected.get('document_type')}",
    }
    if None in {
        selected_window, expected.get("project_uuid"), expected.get("document_uuid"),
        expected.get("document_type"),
    } or not expected_targets.issubset(set(execution_authorization.target_ids)):
        blockers.append("authorization_target_mismatch")

    if not expected.get("project_uuid") or not context.get("project_uuid"):
        blockers.append("project_not_identified")
    elif context.get("project_uuid") != expected.get("project_uuid"):
        blockers.append("wrong_project")
    if not expected.get("document_uuid") or not context.get("document_uuid"):
        blockers.append("document_not_identified")
    elif context.get("document_uuid") != expected.get("document_uuid"):
        blockers.append("wrong_document")
    if expected.get("document_type") not in {"schematic", "pcb"} or not context.get("document_type"):
        blockers.append("document_type_not_identified")
    elif context.get("document_type") != expected.get("document_type"):
        blockers.append("wrong_document_type")
    if context.get("has_unsaved_changes") is not False:
        blockers.append("unsaved_state_not_clear")
    if context.get("api_signature_verified") is not True:
        blockers.append("api_signature_unverified")
    if context.get("enums_verified") is not True:
        blockers.append("api_enums_unverified")
    if context.get("write_permission") is not True:
        blockers.append("write_permission_unavailable")
    if context.get("baseline_ref") in {None, ""}:
        blockers.append("missing_recovery_baseline")
    if expected.get("document_type") == "pcb":
        if not expected.get("schematic_freeze_decision_id") or (
            context.get("validated_schematic_freeze_decision_id")
            != expected.get("schematic_freeze_decision_id")
        ):
            blockers.append("schematic_not_frozen")
        if not expected.get("schematic_hash") or (
            context.get("readback_schematic_hash") != expected.get("schematic_hash")
        ):
            blockers.append("schematic_hash_mismatch")
        if not expected.get("interface_freeze_decision_id") or (
            context.get("validated_interface_freeze_decision_id")
            != expected.get("interface_freeze_decision_id")
        ):
            blockers.append("interface_not_frozen")
        if not expected.get("interface_hash") or (
            context.get("readback_interface_hash") != expected.get("interface_hash")
        ):
            blockers.append("interface_hash_mismatch")
    return blockers


def guard_easyeda_operation(
    provider_operation: str,
    *,
    parameters: Mapping[str, Any],
    execution_authorization: ExecutionAuthorization,
) -> None:
    """Bind the actual EasyEDA API call to a reserved one-call lease."""
    verify_execution_authorization(execution_authorization, required_phase="reserved")
    if execution_authorization.signature in _USED_EXECUTION_SIGNATURES:
        raise ContractError(f"{provider_operation} execution lease has already been used")
    if not execution_authorization.capability_id.startswith(("eda.", "schematic.", "pcb.")):
        raise ContractError("execution lease is not an EasyEDA capability")
    if provider_operation != execution_authorization.provider_operation:
        raise ContractError("EasyEDA provider operation does not match the reserved call")
    if canonical_parameter_digest(parameters) != execution_authorization.parameter_digest:
        raise ContractError("EasyEDA parameters do not match the reserved call")
    dangerous = _is_dangerous_fusion_tool(provider_operation)
    if dangerous and execution_authorization.risk_class != "destructive_write":
        raise ContractError("dangerous EasyEDA operation was not classified destructive_write")
    if execution_authorization.risk_class not in {
        "reversible_write", "destructive_write", "export", "render", "verify", "rollback"
    }:
        raise ContractError("EasyEDA operation lacks an execution-safe classification")
    _USED_EXECUTION_SIGNATURES.add(execution_authorization.signature)


def _values_equal(expected: Any, actual: Any, tolerance_mm: float) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not math.isfinite(float(expected)):
            raise ContractError("shared geometry contract values must be finite")
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isfinite(float(actual))
            and math.isclose(float(expected), float(actual), abs_tol=tolerance_mm)
        )
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        return (
            isinstance(actual, Sequence)
            and not isinstance(actual, (str, bytes))
            and len(expected) == len(actual)
            and all(_values_equal(left, right, tolerance_mm) for left, right in zip(expected, actual))
        )
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and set(expected) == set(actual) and all(
            _values_equal(value, actual[key], tolerance_mm) for key, value in expected.items()
        )
    return expected == actual


def compare_shared_geometry(
    contract: Mapping[str, Any],
    cad_readback: Mapping[str, Any],
    pcb_readback: Mapping[str, Any],
    tolerance_mm: float = 0.01,
) -> List[str]:
    """Compare the five mandatory CAD/PCB shared-geometry groups.

    Inputs are flat provider-neutral projections with these keys:
    ``pcb_thickness_mm``, ``mounting_holes``, ``connectors``,
    ``height_zones``, and ``antenna_keepouts``.
    """
    tolerance = _finite_number(tolerance_mm, "tolerance_mm")
    if tolerance < 0:
        raise ContractError("tolerance_mm must be non-negative")
    required = (
        "pcb_thickness_mm",
        "mounting_holes",
        "connectors",
        "height_zones",
        "antenna_keepouts",
    )
    mismatches: List[str] = []
    for key in required:
        if key not in contract:
            raise ContractError(f"shared geometry contract is missing {key}")
        for consumer_name, consumer in (("cad", cad_readback), ("pcb", pcb_readback)):
            if key not in consumer or not _values_equal(contract[key], consumer[key], tolerance):
                mismatches.append(f"{consumer_name}.{key}")
    return mismatches
