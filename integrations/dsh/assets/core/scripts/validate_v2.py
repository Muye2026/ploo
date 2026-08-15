#!/usr/bin/env python3
"""Fail-closed validator for Ploo V2 machine documents.

Only the Python standard library is used.  The structural validator implements
the JSON Schema features used by the checked-in V2 schemas; semantic checks
then reject dangling references, cycles and contradictory run states.
"""

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from adapter_contracts import (
    ContractError, canonical_operation_digest, canonical_parameter_digest,
)


SCHEMA_FILES = {
    "design_pack": "design-pack.v2.schema.json",
    "run_state": "run-state.v2.schema.json",
    "electrical_pack": "electrical-pack.v2.schema.json",
    "interface_control": "interface-control.v2.schema.json",
}

KIND_ALIASES = {
    "design-pack": "design_pack",
    "design_pack": "design_pack",
    "run-state": "run_state",
    "run_state": "run_state",
    "electrical-pack": "electrical_pack",
    "electrical_pack": "electrical_pack",
    "interface-control": "interface_control",
    "interface_control": "interface_control",
}
DECISION_REF_PATTERN = re.compile(
    r"^(?:chat-message|codex-message|approval-record):[A-Za-z0-9][A-Za-z0-9._:-]{7,}$"
)
DANGEROUS_OPERATION_VERBS = (
    "delete", "remove", "purge", "clear", "destroy", "wipe", "erase",
    "drop", "truncate", "reset", "overwrite",
)


class ValidationError(ValueError):
    """Raised when a document is structurally or semantically invalid."""


def _unique_object_pairs(pairs: Sequence[Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _loads_strict_json(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValidationError(f"non-finite JSON number {value!r} is not allowed")

    return json.loads(
        text,
        object_pairs_hook=_unique_object_pairs,
        parse_constant=reject_constant,
    )


def _reject_nonfinite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError(f"{path}: non-finite JSON number is not allowed")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nonfinite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nonfinite(item, f"{path}[{index}]")


def _normalize_operation_name(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower().replace("-", "_")


def _is_named_dangerous_capability(capability: str) -> bool:
    normalized = _normalize_operation_name(capability)
    return (
        normalized in {
            "cad.execute_code", "cad.delete_all", "cad.delete_parameter", "cad.set_design_type"
        }
        or normalized.startswith("cad.cam.")
        or normalized == "cad.export.outside_artifact_root"
        or normalized in {"constraints.relax", "project.switch"}
        or re.search(
            rf"(?:^|[._/])(?:{'|'.join(DANGEROUS_OPERATION_VERBS)})(?:[._/]|$)",
            normalized,
        ) is not None
    )


def _provider_operation_is_dangerous(provider_operation: str) -> bool:
    normalized = _normalize_operation_name(provider_operation)
    return (
        normalized in {"execute_code", "set_design_type"}
        or normalized.startswith("cam_")
        or "toolpath" in normalized
        or "post_process" in normalized
        or re.search(
            rf"(?:^|[._/])(?:{'|'.join(DANGEROUS_OPERATION_VERBS)})(?:[._/]|$)",
            normalized,
        ) is not None
    )


def contract_hash(document: Mapping[str, Any]) -> str:
    """Hash provider-neutral contract truth while excluding volatile provenance."""
    normalized = copy.deepcopy(dict(document))
    for volatile_key in (
        "provenance", "evidence", "migration", "status", "freeze_decision_id"
    ):
        normalized.pop(volatile_key, None)

    def strip_decision_pointers(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_decision_pointers(item)
                for key, item in value.items()
                if not key.endswith("decision_id") and not key.endswith("decision_ids")
            }
        if isinstance(value, list):
            return [strip_decision_pointers(item) for item in value]
        return value

    normalized = strip_decision_pointers(normalized)
    try:
        encoded = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"cannot hash non-JSON contract value: {exc}") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _schema_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas"


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _resolve_ref(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ValidationError(f"unsupported external schema reference: {reference}")
    current: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValidationError(f"unresolvable schema reference: {reference}")
        current = current[part]
    if not isinstance(current, dict):
        raise ValidationError(f"schema reference is not an object: {reference}")
    return current


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"cannot canonicalize non-JSON value: {exc}") from exc


def _validate_schema(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str) -> None:
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(root, schema["$ref"]), root, path)
        return

    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path}: value {value!r} is not in the allowed enum")

    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate_schema(value, option, root, path)
                matches += 1
            except ValidationError:
                pass
        if matches != 1:
            raise ValidationError(f"{path}: expected exactly one matching schema, got {matches}")

    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _validate_schema(value, option, root, path)
                break
            except ValidationError:
                continue
        else:
            raise ValidationError(f"{path}: no anyOf option matched")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(expected_types, list) or not all(isinstance(item, str) for item in expected_types):
            raise ValidationError(f"{path}: malformed schema type declaration")
        if not any(_json_type_matches(value, item) for item in expected_types):
            raise ValidationError(f"{path}: expected type {expected_types}, got {type(value).__name__}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise ValidationError(f"{path}: missing required properties {missing}")
        properties = schema.get("properties", {})
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            raise ValidationError(f"{path}: expected at least {schema['minProperties']} properties")
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                _validate_schema(item, properties[key], root, child_path)
            elif additional is False:
                raise ValidationError(f"{path}: unknown property {key!r}")
            elif isinstance(additional, dict):
                _validate_schema(item, additional, root, child_path)

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ValidationError(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValidationError(f"{path}: expected at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            serialized = [_canonical(item) for item in value]
            if len(serialized) != len(set(serialized)):
                raise ValidationError(f"{path}: array items must be unique")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_schema(item, schema["items"], root, f"{path}[{index}]")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValidationError(f"{path}: string is shorter than {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValidationError(f"{path}: string does not match {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValidationError(f"{path}: value is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValidationError(f"{path}: value is above maximum {schema['maximum']}")


def _require_unique_ids(items: Sequence[Mapping[str, Any]], path: str) -> Set[str]:
    ids: List[str] = []
    for index, item in enumerate(items):
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValidationError(f"{path}[{index}].id: missing non-empty id")
        ids.append(identifier)
    if len(ids) != len(set(ids)):
        raise ValidationError(f"{path}: duplicate ids are not allowed")
    return set(ids)


def _require_unique_values(items: Sequence[Mapping[str, Any]], key: str, path: str) -> Set[str]:
    values: List[str] = []
    for index, item in enumerate(items):
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"{path}[{index}].{key}: missing non-empty value")
        values.append(value)
    if len(values) != len(set(values)):
        raise ValidationError(f"{path}: duplicate {key} values are not allowed")
    return set(values)


def _index_evidence(
    evidence: Sequence[Mapping[str, Any]], path: str
) -> Dict[str, Mapping[str, Any]]:
    _require_unique_values(evidence, "evidence_id", path)
    return {item["evidence_id"]: item for item in evidence}


def _require_evidence_refs(
    references: Sequence[str],
    registry: Mapping[str, Mapping[str, Any]],
    path: str,
    reliable: bool = False,
) -> None:
    unknown = set(references) - set(registry)
    if unknown:
        raise ValidationError(f"{path}: unknown evidence references {sorted(unknown)}")
    if reliable:
        unreliable = [
            reference
            for reference in references
            if registry[reference]["type"] not in {"api_readback", "source_export", "screenshot"}
            or not registry[reference]["ref"]
            or not registry[reference]["captured_at"]
        ]
        if unreliable:
            raise ValidationError(f"{path}: unreliable evidence references {unreliable}")


def _assert_acyclic(graph: Mapping[str, Iterable[str]], path: str) -> None:
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValidationError(f"{path}: dependency cycle includes {node!r}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, []):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _validate_design_pack(document: Mapping[str, Any]) -> None:
    for key in (
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
    ):
        _require_unique_ids(document[key], f"$.{key}")
    _index_evidence(document["evidence"], "$.evidence")
    artifact_refs = document.get("artifact_refs", [])
    artifact_keys = [
        f"{item['artifact_type']}:{item['artifact_id']}@{item['revision']}"
        for item in artifact_refs
    ]
    if len(artifact_keys) != len(set(artifact_keys)):
        raise ValidationError("$.artifact_refs: duplicate artifact references are not allowed")
    if document["status"] == "verified":
        if document["architecture_decision_id"] is None:
            raise ValidationError(
                "$.architecture_decision_id: verified design pack requires a user architecture decision"
            )
        if document["freeze_decision_id"] is None:
            raise ValidationError("$.freeze_decision_id: verified design pack requires a user freeze decision")
        if not any(
            item["priority"] == "must" for item in document["acceptance_checks"]
        ):
            raise ValidationError(
                "$.acceptance_checks: verified design pack requires at least one must acceptance check"
            )
        unresolved = [
            item["id"]
            for item in document["selected_components"]
            if item["selection_status"] == "needs_user_confirmation"
        ]
        missing_component_decisions = [
            item["id"]
            for item in document["selected_components"]
            if item["selection_status"] in {"user_confirmed", "user_approved_provisional"}
            and not item["decision_id"]
        ]
        conflicts = [
            item["id"]
            for item in document["component_envelopes"]
            if item["source_status"] in {"missing", "conflict"}
        ]
        unresolved_constraints = [
            item["id"]
            for item in document["hard_constraints"]
            if item.get("status") in {None, "missing", "conflict"}
        ]
        if unresolved or conflicts or unresolved_constraints or missing_component_decisions:
            raise ValidationError(
                f"$: verified design pack has unresolved selections {unresolved}, envelopes {conflicts}, "
                f"hard constraints {unresolved_constraints}, or missing component decisions "
                f"{missing_component_decisions}"
            )
    _validate_evidence_status(document["status"], document["evidence"], "$")


def _artifact_key(reference: Mapping[str, Any]) -> str:
    return f"{reference['artifact_id']}@{reference['revision']}"


def _validate_artifact_refs(
    references: Sequence[Mapping[str, Any]],
    artifacts_by_key: Mapping[str, Mapping[str, Any]],
    path: str,
) -> None:
    for reference in references:
        key = _artifact_key(reference)
        if key not in artifacts_by_key:
            raise ValidationError(f"{path}: unknown artifact revision {key}")
        if reference["content_hash"] != artifacts_by_key[key]["content_hash"]:
            raise ValidationError(f"{path}: content hash mismatch for {key}")


def _validate_evidence_status(status: str, evidence: Sequence[Mapping[str, Any]], path: str) -> None:
    if status in {"verified", "implemented-unverified"}:
        reliable_types = {"api_readback", "source_export", "screenshot"}
        if not any(
            item["type"] in reliable_types and item["ref"] and item["captured_at"]
            for item in evidence
        ):
            raise ValidationError(
                f"{path}: {status} requires api_readback, source_export, or screenshot evidence"
            )
        if any(item["type"] == "unverified" for item in evidence):
            raise ValidationError(f"{path}: {status} cannot include unverified evidence")


def _validate_gate(gate: Mapping[str, Any], path: str) -> None:
    _index_evidence(gate["decision_evidence"], f"{path}.decision_evidence")
    option_ids = _require_unique_ids(gate["options"], f"{path}.options")
    selected = gate["selected_option"]
    if gate["status"] == "pending":
        if selected is not None or gate["decided_by"] is not None or gate["decided_at"] is not None:
            raise ValidationError(f"{path}: pending decision must not contain a selection or decision metadata")
    elif gate["status"] == "resolved":
        if selected not in option_ids:
            raise ValidationError(f"{path}: resolved decision requires a valid selected_option")
        if gate["decided_by"] != "user" or gate["decided_at"] is None:
            raise ValidationError(f"{path}: resolved decision must be decided by user with a timestamp")
        if not any(
            item["type"] == "user_self_report"
            and isinstance(item["ref"], str)
            and DECISION_REF_PATTERN.fullmatch(item["ref"])
            and item["captured_at"]
            for item in gate["decision_evidence"]
        ):
            raise ValidationError(f"{path}: resolved decision requires an explicit user-decision reference")
    elif selected is not None and selected not in option_ids:
        raise ValidationError(f"{path}: selected_option is not one of the declared options")
    recommendation = gate["recommendation"]
    if recommendation is not None and recommendation not in option_ids:
        raise ValidationError(f"{path}: recommendation is not one of the declared options")
    if recommendation is not None and not gate["recommendation_rationale"]:
        raise ValidationError(f"{path}: recommendation requires a rationale")


def _validate_run_state(document: Mapping[str, Any]) -> None:
    reports = document["capability_reports"]
    _require_unique_values(reports, "report_id", "$.capability_reports")
    report_pairs = [(item["track"], item["adapter_id"]) for item in reports]
    if len(report_pairs) != len(set(report_pairs)):
        raise ValidationError("$.capability_reports: duplicate track/adapter_id pairs are not allowed")
    report_tracks = {item["track"] for item in reports}
    expected_tracks = {"visualization", "mechanical", "schematic", "pcb"}
    missing_tracks = expected_tracks - report_tracks
    if missing_tracks:
        raise ValidationError(f"$.capability_reports: missing reports for {sorted(missing_tracks)}")
    for report in reports:
        _index_evidence(report["evidence"], f"$.capability_reports[{report['report_id']}].evidence")
        _require_unique_values(
            report["operations"], "capability_id",
            f"$.capability_reports[{report['report_id']}].operations"
        )
        _require_unique_values(
            report["operations"], "provider_operation",
            f"$.capability_reports[{report['report_id']}].operations"
        )
        for operation in report["operations"]:
            operation_path = (
                f"$.capability_reports[{report['report_id']}].operations"
                f"[{operation['capability_id']}]"
            )
            _index_evidence(
                operation["evidence"],
                f"{operation_path}.evidence"
            )
            if (
                _is_named_dangerous_capability(operation["capability_id"])
                or _provider_operation_is_dangerous(operation["provider_operation"])
            ) and operation["risk_class"] != "destructive_write":
                raise ValidationError(
                    f"{operation_path}: dangerous operation must be classified destructive_write"
                )
            required_flag = {
                "read": "read",
                "reversible_write": "write",
                "destructive_write": "write",
                "export": "export",
                "render": "render",
                "verify": "verify",
                "rollback": "rollback",
            }[operation["risk_class"]]
            if operation["status"] == "available" and not report["capabilities"][required_flag]:
                raise ValidationError(
                    f"{operation_path}: available operation contradicts report capability flags"
                )
            if operation["status"] == "available" and not any(
                item["type"] in {"api_readback", "source_export", "screenshot"} and item["ref"]
                and item["captured_at"]
                for item in operation["evidence"]
            ):
                raise ValidationError(
                    f"{operation_path}: "
                    "available operation requires reliable evidence"
                )
        if report["status"] == "available":
            if report["checked_at"] is None:
                raise ValidationError(
                    f"$.capability_reports[{report['report_id']}]: available capability requires checked_at"
                )
            if report["tool_schema_digest"] is None:
                raise ValidationError(
                    f"$.capability_reports[{report['report_id']}]: available capability requires tool schema digest"
                )
            if not any(
                item["type"] in {"api_readback", "source_export", "screenshot"} and item["ref"]
                and item["captured_at"]
                for item in report["evidence"]
            ):
                raise ValidationError(
                    f"$.capability_reports[{report['report_id']}]: available capability requires reliable evidence"
                )
            missing_operation_digests = [
                operation["capability_id"]
                for operation in report["operations"]
                if operation["status"] == "available" and operation["schema_digest"] is None
            ]
            if missing_operation_digests:
                raise ValidationError(
                    f"$.capability_reports[{report['report_id']}]: available operations lack schema digests "
                    f"{missing_operation_digests}"
                )

    artifacts = document["artifacts"]
    artifact_keys = [_artifact_key(item) for item in artifacts]
    if len(artifact_keys) != len(set(artifact_keys)):
        raise ValidationError("$.artifacts: duplicate artifact_id/revision pairs are not allowed")
    known_artifacts = set(artifact_keys)
    artifacts_by_key = {_artifact_key(item): item for item in artifacts}
    artifact_graph: Dict[str, List[str]] = {}
    for artifact in artifacts:
        key = _artifact_key(artifact)
        dependencies = [_artifact_key(item) for item in artifact["depends_on"]]
        missing = set(dependencies) - known_artifacts
        if missing:
            raise ValidationError(f"$.artifacts[{key}]: unknown dependency revisions {sorted(missing)}")
        if key in dependencies:
            raise ValidationError(f"$.artifacts[{key}]: artifact cannot depend on itself")
        artifact_graph[key] = dependencies
        _validate_artifact_refs(
            artifact["depends_on"], artifacts_by_key, f"$.artifacts[{key}].depends_on"
        )
        _validate_evidence_status(artifact["status"], artifact["evidence"], f"$.artifacts[{key}]")
        _index_evidence(artifact["evidence"], f"$.artifacts[{key}].evidence")
        if artifact["content_hash"] is not None or artifact["provenance"]["hash"] is not None:
            if artifact["provenance"]["hash"] != artifact["content_hash"]:
                raise ValidationError(
                    f"$.artifacts[{key}]: provenance hash must equal the artifact content hash"
                )
        if artifact["status"] in {"implemented-unverified", "verified"}:
            if not artifact["path"] or not artifact["content_hash"] or not artifact["provenance"]["hash"]:
                raise ValidationError(
                    f"$.artifacts[{key}]: implemented artifacts require path, content hash, and provenance hash"
                )
            unready_dependencies = [
                dependency
                for dependency in dependencies
                if artifacts_by_key[dependency]["status"] != "verified"
            ]
            if unready_dependencies:
                raise ValidationError(
                    f"$.artifacts[{key}]: implemented artifact has unverified dependencies "
                    f"{unready_dependencies}"
                )
        path = artifact["path"]
        if isinstance(path, str) and (path.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", path)):
            raise ValidationError(f"$.artifacts[{key}].path: use an artifact-root-relative path")
        if isinstance(path, str) and ".." in path.replace("\\", "/").split("/"):
            raise ValidationError(f"$.artifacts[{key}].path: parent traversal is not allowed")
        for reason in artifact["invalidation_reasons"]:
            source = f"{reason['source_artifact_id']}@{reason['source_revision']}"
            if source not in known_artifacts:
                raise ValidationError(f"$.artifacts[{key}]: unknown invalidation source {source}")
        if artifact["status"] == "stale" and not artifact["invalidation_reasons"]:
            raise ValidationError(f"$.artifacts[{key}]: stale artifact requires an invalidation reason")
    _assert_acyclic(artifact_graph, "$.artifacts")

    cross_domain_checks = document["cross_domain_checks"]
    _require_unique_values(cross_domain_checks, "check_id", "$.cross_domain_checks")
    for check in cross_domain_checks:
        path = f"$.cross_domain_checks[{check['check_id']}]"
        references = [
            item for item in (check["interface_ref"], check["cad_ref"], check["pcb_ref"])
            if item is not None
        ]
        _validate_artifact_refs(references, artifacts_by_key, path)
        _index_evidence(check["evidence"], f"{path}.evidence")
        _validate_evidence_status(check["status"], check["evidence"], path)
        expected_types = {
            "interface_ref": "interface_control",
            "cad_ref": "cad_model",
            "pcb_ref": "pcb",
        }
        wrong_types = [
            field
            for field, expected_type in expected_types.items()
            if check[field] is not None
            and artifacts_by_key[_artifact_key(check[field])]["artifact_type"] != expected_type
        ]
        if wrong_types:
            raise ValidationError(f"{path}: cross-domain refs have wrong artifact types {wrong_types}")
        stale_refs = [
            _artifact_key(item) for item in references
            if artifacts_by_key[_artifact_key(item)]["status"] == "stale"
        ]
        if stale_refs and check["status"] not in {"stale", "blocked"}:
            raise ValidationError(f"{path}: active cross-domain check references stale artifacts {stale_refs}")
        if check["status"] == "verified":
            if check["interface_ref"] is None or check["pcb_ref"] is None:
                raise ValidationError(f"{path}: verified check requires Interface Control and PCB refs")
            mismatches = [
                name for name, status in check["groups"].items() if status != "match"
            ]
            if mismatches:
                raise ValidationError(f"{path}: verified check has unmatched groups {mismatches}")
            unverified_refs = [
                _artifact_key(item) for item in references
                if artifacts_by_key[_artifact_key(item)]["status"] != "verified"
            ]
            if unverified_refs:
                raise ValidationError(f"{path}: verified check has unverified refs {unverified_refs}")

    cards = document["operation_cards"]
    _require_unique_values(cards, "step_id", "$.operation_cards")
    _require_unique_values(cards, "call_id", "$.operation_cards")
    _require_unique_values(cards, "attempt_id", "$.operation_cards")
    for card in cards:
        try:
            actual_parameter_digest = canonical_parameter_digest(card["parameters"])
        except ContractError as exc:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}].parameters: {exc}"
            ) from exc
        if card["parameter_digest"] != actual_parameter_digest:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: parameter_digest does not match canonical parameters"
            )
        for field in ("depends_on", "produces"):
            missing = {_artifact_key(item) for item in card[field]} - known_artifacts
            if missing:
                raise ValidationError(f"$.operation_cards[{card['step_id']}].{field}: unknown refs {sorted(missing)}")
            _validate_artifact_refs(
                card[field], artifacts_by_key,
                f"$.operation_cards[{card['step_id']}].{field}"
            )
        dependency_keys = {_artifact_key(item) for item in card["depends_on"]}
        produced_keys = {_artifact_key(item) for item in card["produces"]}
        overlap = dependency_keys & produced_keys
        if overlap:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: input and output revisions must differ {sorted(overlap)}"
            )
        for produced_key in produced_keys:
            output_dependencies = {
                _artifact_key(item) for item in artifacts_by_key[produced_key]["depends_on"]
            }
            if dependency_keys != output_dependencies:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: produced artifact {produced_key} "
                    "must declare exactly the Operation Card input lineage"
                )
        _validate_evidence_status(card["status"], card["evidence"], f"$.operation_cards[{card['step_id']}]")
        _index_evidence(card["evidence"], f"$.operation_cards[{card['step_id']}].evidence")
        selected_route = document["track_routes"][card["track"]]
        if selected_route is None and card["status"] != "stale":
            raise ValidationError(f"$.operation_cards[{card['step_id']}]: cannot exist on an unresolved track")
        if selected_route == "skip" and card["status"] != "stale":
            raise ValidationError(f"$.operation_cards[{card['step_id']}]: skipped tracks cannot have operations")
        if card["route"] != selected_route and card["status"] != "stale":
            raise ValidationError(f"$.operation_cards[{card['step_id']}]: route does not match track route")
        execution_capability = card["execution_capability_id"]
        adapter_execution = (
            card["route"] == "direct"
            or card["track"] == "visualization" and card["route"] in {"image", "video", "image+video"}
            or card["route"] == "hybrid" and card["ownership"] in {"agent", "shared"}
        )
        if adapter_execution and execution_capability is None:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: adapter execution requires one execution_capability_id"
            )
        if execution_capability is not None:
            if execution_capability not in card["required_capabilities"]:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: execution capability is not required by the card"
                )
            matching_operations = [
                operation
                for report in reports
                if report["track"] == card["track"]
                and report["adapter_id"] == card["adapter_id"]
                and report["status"] == "available"
                for operation in report["operations"]
                if operation["capability_id"] == execution_capability
                and operation["status"] == "available"
            ]
            if len(matching_operations) != 1:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: execution capability lacks one available provider binding"
                )
            if matching_operations[0]["risk_class"] == "read":
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: read-only capability cannot be a write execution"
                )
            mutating_capabilities = {
                operation["capability_id"]
                for report in reports
                if report["track"] == card["track"]
                and report["adapter_id"] == card["adapter_id"]
                and report["status"] == "available"
                for operation in report["operations"]
                if operation["status"] == "available"
                and operation["capability_id"] in card["required_capabilities"]
                and operation["risk_class"] in {
                    "reversible_write", "destructive_write", "export", "render"
                }
            }
            if len(mutating_capabilities) > 1 or (
                mutating_capabilities and execution_capability not in mutating_capabilities
            ):
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: one Operation Card may bind only one mutating provider call"
                )
        elif card["adapter_id"] is not None and card["required_capabilities"]:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: provider capabilities require an execution_capability_id"
            )
        if adapter_execution and card["track"] in {"schematic", "pcb"}:
            identity_fields = {"window_id", "project_uuid", "document_uuid", "document_type"}
            missing_identity = identity_fields - set(card["parameters"])
            if missing_identity:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: EasyEDA parameters lack target identity "
                    f"{sorted(missing_identity)}"
                )
            if card["parameters"]["document_type"] != card["track"]:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: EasyEDA document type does not match track"
                )
            required_targets = {
                f"window:{card['parameters']['window_id']}",
                f"project:{card['parameters']['project_uuid']}",
                f"document:{card['parameters']['document_uuid']}",
                f"document_type:{card['parameters']['document_type']}",
            }
            if not required_targets.issubset(set(card["target_ids"])):
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: EasyEDA target IDs are not bound to parameters"
                )
            if card["track"] == "pcb":
                pcb_freeze_fields = {
                    "schematic_freeze_decision_id", "schematic_hash",
                    "interface_freeze_decision_id", "interface_hash",
                }
                missing_freezes = pcb_freeze_fields - set(card["parameters"])
                if missing_freezes:
                    raise ValidationError(
                        f"$.operation_cards[{card['step_id']}]: PCB call lacks frozen source bindings "
                        f"{sorted(missing_freezes)}"
                    )
        stale_dependencies = [
            _artifact_key(item)
            for item in card["depends_on"]
            if artifacts_by_key[_artifact_key(item)]["status"] == "stale"
        ]
        if stale_dependencies and card["status"] not in {"stale", "blocked"}:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: active card depends on stale artifacts {stale_dependencies}"
            )
        stale_output_dependencies = sorted({
            dependency_key
            for produced_key in produced_keys
            for dependency_key in (
                _artifact_key(item) for item in artifacts_by_key[produced_key]["depends_on"]
            )
            if artifacts_by_key[dependency_key]["status"] == "stale"
        })
        if stale_output_dependencies and card["status"] not in {"stale", "blocked"}:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: output lineage contains stale artifacts "
                f"{stale_output_dependencies}"
            )
        if card["status"] in {"implemented-unverified", "verified"}:
            present_evidence = {item["type"] for item in card["evidence"]}
            missing_evidence = set(card["evidence_required"]) - present_evidence
            if missing_evidence:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: missing required evidence {sorted(missing_evidence)}"
                )
        if not set(card["evidence_required"]) & {"api_readback", "source_export", "screenshot"}:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: evidence_required must include reliable evidence"
            )
        if card["status"] == "verified":
            unverified_inputs = [
                key for key in dependency_keys if artifacts_by_key[key]["status"] != "verified"
            ]
            unverified_outputs = [
                key for key in produced_keys if artifacts_by_key[key]["status"] != "verified"
            ]
            if unverified_inputs or unverified_outputs:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: verified card requires verified inputs "
                    f"{unverified_inputs} and outputs {unverified_outputs}"
                )
        elif card["status"] == "implemented-unverified":
            invalid_outputs = [
                key for key in produced_keys
                if artifacts_by_key[key]["status"] not in {"implemented-unverified", "verified"}
            ]
            if invalid_outputs:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: implemented card has non-implemented outputs "
                    f"{invalid_outputs}"
                )
        allowed_ownership = {
            "direct": {"agent", "shared"},
            "guided": {"user", "shared"},
            "hybrid": {"agent", "user", "shared"},
            "handoff": {"handoff"},
            "spec": {"agent", "handoff"},
            "image": {"agent", "shared"},
            "video": {"agent", "shared"},
            "image+video": {"agent", "shared"},
        }.get(card["route"])
        if allowed_ownership is None or card["ownership"] not in allowed_ownership:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: ownership {card['ownership']!r} "
                f"is incompatible with route {card['route']!r}"
            )
        if card["route"] == "direct":
            if not card["required_capabilities"]:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: direct execution requires operation-level capabilities"
                )
            if card["adapter_id"] is None:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: direct execution requires a selected adapter"
                )
            checkpoint = card["rollback"]["checkpoint_ref"]
            if not card["target_ids"] or not isinstance(checkpoint, str) or not checkpoint.strip():
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: direct execution requires targets and a recovery checkpoint"
                )
            required_flags = {"read", "write", "verify", "export", "rollback"}
            if card["track"] == "mechanical":
                required_flags.add("render")
            direct_reports = [
                item for item in reports
                if item["track"] == card["track"]
                and item["adapter_id"] == card["adapter_id"]
                and item["status"] == "available"
                and all(item["capabilities"][flag] for flag in required_flags)
            ]
            if not direct_reports:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: direct execution lacks required verified capabilities"
                )
            units = direct_reports[0]["units"]
            required_units = {
                "mechanical": {"public": "mm", "native": "cm"},
                "schematic": {"public": "mm", "native": "0.01 inch"},
                "pcb": {"public": "mm", "native": "mil"},
            }.get(card["track"], {})
            if any(units.get(key) != value for key, value in required_units.items()):
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: adapter unit contract is missing or incompatible"
                )
            available_operations = {
                operation["capability_id"]
                for report in direct_reports
                for operation in report["operations"]
                if operation["status"] == "available"
            }
            missing_operations = set(card["required_capabilities"]) - available_operations
            if missing_operations:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: unavailable operation capabilities "
                    f"{sorted(missing_operations)}"
                )
        if card["route"] == "hybrid" and card["ownership"] in {"agent", "shared"}:
            if card["adapter_id"] is None or not card["required_capabilities"]:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: agent/shared hybrid work requires a selected adapter and capabilities"
                )
            hybrid_reports = [
                report for report in reports
                if report["track"] == card["track"]
                and report["adapter_id"] == card["adapter_id"]
                and report["status"] == "available"
                and report["capabilities"]["read"]
                and report["capabilities"]["verify"]
            ]
            available_operations = {
                operation["capability_id"]
                for report in hybrid_reports
                for operation in report["operations"]
                if operation["status"] == "available"
            }
            if not hybrid_reports or set(card["required_capabilities"]) - available_operations:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: hybrid execution lacks verified operation capability"
                )
        if card["track"] == "visualization" and card["route"] in {"image", "video", "image+video"}:
            if card["adapter_id"] is None:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: visualization execution requires a selected adapter"
                )
            visual_reports = [
                item for item in reports
                if item["track"] == "visualization"
                and item["adapter_id"] == card["adapter_id"]
                and item["status"] == "available"
                and item["capabilities"]["render"]
            ]
            available_operations = {
                operation["capability_id"]
                for report in visual_reports
                for operation in report["operations"]
                if operation["status"] == "available"
            }
            if not card["required_capabilities"] or set(card["required_capabilities"]) - available_operations:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: visualization execution lacks verified operation capability"
                )

    ledger = document["decision_ledger"]
    _require_unique_values(ledger, "decision_id", "$.decision_ledger")
    for index, gate in enumerate(ledger):
        _validate_gate(gate, f"$.decision_ledger[{index}]")
        if gate["status"] == "pending":
            raise ValidationError("$.decision_ledger: pending decisions belong in pending_decision_gate")
        missing = {_artifact_key(item) for item in gate["dependency_revisions"]} - known_artifacts
        if missing:
            raise ValidationError(f"$.decision_ledger[{index}]: unknown dependency revisions {sorted(missing)}")
        _validate_artifact_refs(
            gate["dependency_revisions"], artifacts_by_key,
            f"$.decision_ledger[{index}].dependency_revisions"
        )

    ledger_by_id = {item["decision_id"]: item for item in ledger}
    selected_route_decision_ids = [
        document["route_decision_ids"][track]
        for track, route in document["track_routes"].items()
        if route is not None
    ]
    if len(selected_route_decision_ids) != len(set(selected_route_decision_ids)):
        raise ValidationError("$.route_decision_ids: each track requires its own route decision")
    for track, route in document["track_routes"].items():
        decision_id = document["route_decision_ids"][track]
        if route is None:
            if decision_id is not None:
                raise ValidationError(f"$.route_decision_ids.{track}: unresolved route must have null decision id")
            continue
        if decision_id is None or decision_id not in ledger_by_id:
            raise ValidationError(f"$.route_decision_ids.{track}: selected route requires a ledger decision")
        gate = ledger_by_id[decision_id]
        if gate["status"] != "resolved" or gate["decided_by"] != "user":
            raise ValidationError(f"$.route_decision_ids.{track}: route decision is not user-resolved")
        if gate["decision_type"] not in {"route_selection", "route_change"} or f"track:{track}" not in gate["scope"]:
            raise ValidationError(f"$.route_decision_ids.{track}: decision scope does not authorize this track")
        if gate["selected_option"] != route:
            raise ValidationError(f"$.track_routes.{track}: route does not match selected decision option")

    for card in cards:
        if (
            card["status"] != "stale"
            and card["route_decision_id"] != document["route_decision_ids"][card["track"]]
        ):
            raise ValidationError(f"$.operation_cards[{card['step_id']}]: route_decision_id mismatch")
        missing_authorizations = set(card["authorization_decision_ids"]) - set(ledger_by_id)
        if missing_authorizations:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: unknown authorization decisions {sorted(missing_authorizations)}"
            )
        invalid_authorizations = [
            decision_id
            for decision_id in card["authorization_decision_ids"]
            if ledger_by_id[decision_id]["status"] != "resolved"
            or ledger_by_id[decision_id]["decided_by"] != "user"
        ]
        if invalid_authorizations:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: authorization decisions are not user-resolved"
            )
        if card["route"] == "hybrid":
            ownership_decisions = [
                ledger_by_id[decision_id]
                for decision_id in card["authorization_decision_ids"]
                if ledger_by_id[decision_id]["decision_type"] == "ownership"
                and f"step:{card['step_id']}" in ledger_by_id[decision_id]["scope"]
                and ledger_by_id[decision_id]["selected_option"] == card["ownership"]
            ]
            if not ownership_decisions:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: hybrid ownership requires a scoped user decision"
                )
        if card["ownership"] == "shared" and not any(
            ledger_by_id[decision_id]["decision_type"] == "ownership"
            and f"step:{card['step_id']}" in ledger_by_id[decision_id]["scope"]
            and ledger_by_id[decision_id]["selected_option"] == "shared"
            for decision_id in card["authorization_decision_ids"]
        ):
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: shared ownership requires a scoped user decision"
            )
        reported_dangerous_capabilities = {
            operation["capability_id"]
            for report in reports
            if report["track"] == card["track"] and report["adapter_id"] == card["adapter_id"]
            for operation in report["operations"]
            if operation["risk_class"] == "destructive_write"
        }
        dangerous_capabilities = {
            card["execution_capability_id"]
        } if card["execution_capability_id"] is not None and (
            _is_named_dangerous_capability(card["execution_capability_id"])
            or card["execution_capability_id"] in reported_dangerous_capabilities
        ) else set()
        if dangerous_capabilities and card["risk_level"] not in {"high", "destructive"}:
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: dangerous capability requires high/destructive risk level"
            )
        if card["risk_level"] in {"high", "destructive"}:
            scopes = {
                f"run:{document['run_id']}",
                f"step:{card['step_id']}",
                f"call:{card['call_id']}",
                f"attempt:{card['attempt_id']}",
                f"parameters:{card['parameter_digest']}",
                f"operation:{canonical_operation_digest(card)}",
            }
            capabilities_to_authorize = dangerous_capabilities or {
                card["execution_capability_id"] or f"manual:{card['step_id']}"
            }
            invalid_high_risk_authorizations = []
            for capability in sorted(capabilities_to_authorize):
                matches = [
                    decision_id
                    for decision_id in card["authorization_decision_ids"]
                    if (
                    ledger_by_id[decision_id]["decision_type"] == "high_risk_write"
                    and ledger_by_id[decision_id]["selected_option"] == capability
                    and scopes.issubset(set(ledger_by_id[decision_id]["scope"]))
                    )
                ]
                if len(matches) != 1:
                    invalid_high_risk_authorizations.append(
                        {"capability": capability, "matching_decisions": matches}
                    )
            if invalid_high_risk_authorizations:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: high-risk write requires exactly one "
                    f"per-call authorization {invalid_high_risk_authorizations}"
                )
        eligible_adapters = {
            report["adapter_id"]
            for report in reports
            if report["track"] == card["track"] and report["status"] == "available"
        }
        if card["adapter_id"] is not None and len(eligible_adapters) > 1:
            adapter_decisions = [
                ledger_by_id[decision_id]
                for decision_id in card["authorization_decision_ids"]
                if ledger_by_id[decision_id]["decision_type"] == "adapter_selection"
                and f"step:{card['step_id']}" in ledger_by_id[decision_id]["scope"]
                and ledger_by_id[decision_id]["selected_option"] == card["adapter_id"]
            ]
            if not adapter_decisions:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: multiple adapters require a scoped user selection"
                )

    cards_by_id = {item["step_id"]: item for item in cards}
    reservations = document["execution_reservations"]
    _require_unique_values(reservations, "reservation_id", "$.execution_reservations")
    reservation_attempts = [
        (item["step_id"], item["attempt_id"]) for item in reservations
    ]
    if len(reservation_attempts) != len(set(reservation_attempts)):
        raise ValidationError(
            "$.execution_reservations: one Operation Card attempt can be reserved only once"
        )
    for index, reservation in enumerate(reservations):
        path = f"$.execution_reservations[{index}]"
        card = cards_by_id.get(reservation["step_id"])
        if card is None:
            raise ValidationError(f"{path}: reservation references an unknown Operation Card")
        exact_fields = {
            "run_id": document["run_id"],
            "call_id": card["call_id"],
            "attempt_id": card["attempt_id"],
            "parameter_digest": card["parameter_digest"],
            "operation_digest": canonical_operation_digest(card),
            "capability_id": card["execution_capability_id"],
        }
        if any(reservation[key] != value for key, value in exact_fields.items()):
            raise ValidationError(f"{path}: reservation does not match the exact Operation Card call")
        matching_operations = [
            operation
            for report in reports
            if report["track"] == card["track"]
            and report["adapter_id"] == card["adapter_id"]
            and report["status"] == "available"
            for operation in report["operations"]
            if operation["capability_id"] == reservation["capability_id"]
            and operation["status"] == "available"
        ]
        if len(matching_operations) != 1 or any(
            reservation[key] != matching_operations[0][key]
            for key in ("provider_operation", "risk_class")
        ):
            raise ValidationError(f"{path}: provider binding no longer matches the capability report")
        if reservation["status"] == "reserved" and reservation["result_fingerprint"] is not None:
            raise ValidationError(f"{path}: reserved call cannot already have a result fingerprint")
        if reservation["status"] != "reserved" and not reservation["result_fingerprint"]:
            raise ValidationError(f"{path}: terminal call requires a readback result fingerprint")

    reservations_by_attempt = {
        (item["step_id"], item["attempt_id"]): item for item in reservations
    }
    for card in cards:
        if card["status"] not in {"implemented-unverified", "verified"}:
            continue
        if card["execution_capability_id"] is None:
            continue
        reservation = reservations_by_attempt.get((card["step_id"], card["attempt_id"]))
        if reservation is None or reservation["status"] != "completed":
            raise ValidationError(
                f"$.operation_cards[{card['step_id']}]: implemented adapter call lacks a completed execution reservation"
            )

    consumptions = document["authorization_consumptions"]
    _require_unique_values(consumptions, "consumption_id", "$.authorization_consumptions")
    consumed_decision_ids = _require_unique_values(
        consumptions, "decision_id", "$.authorization_consumptions"
    )
    for index, consumption in enumerate(consumptions):
        path = f"$.authorization_consumptions[{index}]"
        decision = ledger_by_id.get(consumption["decision_id"])
        card = cards_by_id.get(consumption["step_id"])
        if decision is None or decision["decision_type"] != "high_risk_write":
            raise ValidationError(f"{path}: consumption requires a high-risk decision")
        if card is None or consumption["decision_id"] not in card["authorization_decision_ids"]:
            raise ValidationError(f"{path}: consumption is not attached to its Operation Card")
        if consumption["run_id"] != document["run_id"]:
            raise ValidationError(f"{path}: run_id mismatch")
        exact_fields = {
            "call_id": card["call_id"],
            "attempt_id": card["attempt_id"],
            "parameter_digest": card["parameter_digest"],
            "operation_digest": canonical_operation_digest(card),
        }
        if any(consumption[key] != value for key, value in exact_fields.items()):
            raise ValidationError(f"{path}: call, attempt, or parameter binding mismatch")
        if (
            consumption["capability_id"] != decision["selected_option"]
            or consumption["capability_id"] != card["execution_capability_id"]
        ):
            raise ValidationError(f"{path}: capability binding mismatch")
        required_scope = {
            f"run:{document['run_id']}", f"step:{card['step_id']}",
            f"call:{card['call_id']}", f"attempt:{card['attempt_id']}",
            f"parameters:{card['parameter_digest']}",
        }
        if not required_scope.issubset(set(decision["scope"])):
            raise ValidationError(f"{path}: decision scope no longer matches the consumed call")
        reservation = reservations_by_attempt.get(
            (consumption["step_id"], consumption["attempt_id"])
        )
        if reservation is None:
            raise ValidationError(f"{path}: authorization consumption lacks an execution reservation")
        if (
            consumption["status"] != reservation["status"]
            or consumption["result_fingerprint"] != reservation["result_fingerprint"]
        ):
            raise ValidationError(
                f"{path}: authorization consumption must mirror reservation status and fingerprint"
            )

    for card in cards:
        if card["risk_level"] not in {"high", "destructive"}:
            continue
        if card["execution_capability_id"] is None:
            continue
        reported_dangerous_capabilities = {
            operation["capability_id"]
            for report in reports
            if report["track"] == card["track"] and report["adapter_id"] == card["adapter_id"]
            for operation in report["operations"]
            if operation["risk_class"] == "destructive_write"
        }
        dangerous_capabilities = {
            card["execution_capability_id"]
        } if card["execution_capability_id"] is not None and (
            _is_named_dangerous_capability(card["execution_capability_id"])
            or card["execution_capability_id"] in reported_dangerous_capabilities
        ) else set()
        capabilities_to_consume = dangerous_capabilities or {card["execution_capability_id"]}
        reservation = reservations_by_attempt.get((card["step_id"], card["attempt_id"]))
        if reservation is not None:
            matching_consumptions = [
                item for item in consumptions
                if item["step_id"] == card["step_id"]
                and item["attempt_id"] == card["attempt_id"]
                and item["capability_id"] in capabilities_to_consume
            ]
            if len(matching_consumptions) != 1:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: reserved high-risk call requires "
                    "exactly one authorization consumption"
                )
        if card["status"] in {"implemented-unverified", "verified"}:
            completed_capabilities = {
                item["capability_id"]
                for item in consumptions
                if item["step_id"] == card["step_id"]
                and item["attempt_id"] == card["attempt_id"]
                and item["status"] == "completed"
            }
            missing_consumptions = capabilities_to_consume - completed_capabilities
            if missing_consumptions:
                raise ValidationError(
                    f"$.operation_cards[{card['step_id']}]: implemented high-risk call lacks "
                    f"authorization consumption {sorted(missing_consumptions)}"
                )

    pending = document["pending_decision_gate"]
    unresolved_routes = [track for track, route in document["track_routes"].items() if route is None]
    if pending is not None:
        _validate_gate(pending, "$.pending_decision_gate")
        if pending["status"] != "pending" or pending["selected_option"] is not None:
            raise ValidationError("$.pending_decision_gate: pending gate must have null selected_option")
        if document["status"] != "waiting_user_decision":
            raise ValidationError("$.status: null selected_option requires waiting_user_decision")
        if pending["decision_id"] in {item["decision_id"] for item in ledger}:
            raise ValidationError("$.pending_decision_gate: decision_id is already in the ledger")
        missing = {_artifact_key(item) for item in pending["dependency_revisions"]} - known_artifacts
        if missing:
            raise ValidationError(f"$.pending_decision_gate: unknown dependency revisions {sorted(missing)}")
        _validate_artifact_refs(
            pending["dependency_revisions"], artifacts_by_key,
            "$.pending_decision_gate.dependency_revisions"
        )
    elif document["status"] == "waiting_user_decision":
        raise ValidationError("$.status: waiting_user_decision requires pending_decision_gate")
    waiting_children = [
        _artifact_key(item) for item in artifacts if item["status"] == "waiting_user_decision"
    ] + [
        item["step_id"] for item in cards if item["status"] == "waiting_user_decision"
    ] + [
        item["check_id"] for item in cross_domain_checks
        if item["status"] == "waiting_user_decision"
    ]
    if waiting_children and pending is None:
        raise ValidationError(
            f"$.status: waiting child records require a pending decision gate {waiting_children}"
        )
    if unresolved_routes and (pending is None or document["status"] != "waiting_user_decision"):
        raise ValidationError(f"$.track_routes: unresolved tracks require a pending user decision: {unresolved_routes}")
    if unresolved_routes and (
        pending["decision_type"] != "route_selection"
        or not all(f"track:{track}" in pending["scope"] for track in unresolved_routes)
    ):
        raise ValidationError("$.pending_decision_gate: unresolved routes require a correctly scoped route gate")
    if pending is None and document["status"] != "verified":
        derived_statuses = (
            [item["status"] for item in artifacts]
            + [item["status"] for item in cards]
            + [item["status"] for item in cross_domain_checks]
        )
        expected_status = "planned"
        if "blocked" in derived_statuses:
            expected_status = "blocked"
        elif "stale" in derived_statuses:
            expected_status = "stale"
        elif "implemented-unverified" in derived_statuses:
            expected_status = "implemented-unverified"
        if document["status"] != expected_status:
            raise ValidationError(
                f"$.status: root status {document['status']!r} must reflect child status {expected_status!r}"
            )
    if document["status"] == "verified":
        if unresolved_routes or pending is not None:
            raise ValidationError("$.status: verified run cannot have unresolved routes or a pending gate")
        incomplete_cards = [card["step_id"] for card in cards if card["status"] != "verified"]
        if incomplete_cards:
            raise ValidationError(f"$.status: verified run has unverified operation cards {incomplete_cards}")
        uncovered_tracks = [
            track
            for track, route in document["track_routes"].items()
            if route != "skip" and not any(card["track"] == track for card in cards)
        ]
        unverified_artifacts = [
            _artifact_key(artifact) for artifact in artifacts if artifact["status"] != "verified"
        ]
        unverified_cross_checks = [
            item["check_id"] for item in cross_domain_checks if item["status"] != "verified"
        ]
        if uncovered_tracks or unverified_artifacts or unverified_cross_checks:
            raise ValidationError(
                f"$.status: verified run has uncovered tracks {uncovered_tracks} or "
                f"unverified artifacts {unverified_artifacts} or cross checks {unverified_cross_checks}"
            )


def _validate_electrical_pack(document: Mapping[str, Any]) -> None:
    evidence_registry = _index_evidence(document["evidence"], "$.evidence")
    for key in (
        "power_domains",
        "interfaces",
        "selected_devices",
        "component_bindings",
        "net_contracts",
        "rule_requirements",
        "verification_requirements",
        "verification_results",
        "open_items",
    ):
        _require_unique_ids(document[key], f"$.{key}")
    for key, items in document["electrical_requirements"].items():
        _require_unique_ids(items, f"$.electrical_requirements.{key}")

    dependency_keys = [
        f"{item['artifact_id']}@{item['revision']}" for item in document["dependencies"]
    ]
    if len(dependency_keys) != len(set(dependency_keys)):
        raise ValidationError("$.dependencies: duplicate artifact revisions are not allowed")

    device_ids = {item["id"] for item in document["selected_devices"]}
    domain_ids = {item["id"] for item in document["power_domains"]}
    for domain in document["power_domains"]:
        unknown_sources = set(domain["source_domain_ids"]) - domain_ids
        unknown_sinks = set(domain["sink_device_ids"]) - device_ids
        if unknown_sources or unknown_sinks:
            raise ValidationError(
                f"$.power_domains[{domain['id']}]: unknown source domains {sorted(unknown_sources)} "
                f"or sink devices {sorted(unknown_sinks)}"
            )
        for field in ("nominal_voltage", "current_requirement"):
            quantity = domain[field]
            if quantity["status"] == "confirmed" and quantity["value"] is None:
                raise ValidationError(
                    f"$.power_domains[{domain['id']}].{field}: confirmed quantity requires a value"
                )

    requirements_by_id = {
        item["id"]: item for item in document["verification_requirements"]
    }
    requirement_ids = set(requirements_by_id)
    results_by_id = {item["id"]: item for item in document["verification_results"]}
    results_by_requirement: Dict[str, List[Mapping[str, Any]]] = {}
    for result in document["verification_results"]:
        if result["requirement_id"] not in requirement_ids:
            raise ValidationError(f"$.verification_results[{result['id']}]: unknown requirement_id")
        results_by_requirement.setdefault(result["requirement_id"], []).append(result)
        if result["status"] == "pass" and not result["evidence_refs"]:
            raise ValidationError(
                f"$.verification_results[{result['id']}]: pass requires evidence references"
            )
        if result["status"] == "pass":
            present_types = {
                evidence_registry[reference]["type"]
                for reference in result["evidence_refs"]
                if reference in evidence_registry
            }
            missing_types = (
                set(requirements_by_id[result["requirement_id"]]["evidence_required"])
                - present_types
            )
            if missing_types:
                raise ValidationError(
                    f"$.verification_results[{result['id']}]: pass lacks required evidence "
                    f"types {sorted(missing_types)}"
                )
        _require_evidence_refs(
            result["evidence_refs"], evidence_registry,
            f"$.verification_results[{result['id']}].evidence_refs",
            reliable=result["status"] == "pass",
        )

    for binding in document["component_bindings"]:
        if binding["device_id"] not in device_ids:
            raise ValidationError(
                f"$.component_bindings[{binding['id']}]: unknown device_id {binding['device_id']!r}"
            )
        pins = set(binding["symbol_pins"])
        pads = set(binding["footprint"]["pads"])
        mapped_pins = [item["symbol_pin"] for item in binding["pin_pad_map"]]
        mapped_pads = [item["pcb_pad"] for item in binding["pin_pad_map"]]
        if len(mapped_pins) != len(set(mapped_pins)) or len(mapped_pads) != len(set(mapped_pads)):
            raise ValidationError(f"$.component_bindings[{binding['id']}]: duplicate pin-pad mapping")
        if set(mapped_pins) != pins or not set(mapped_pads).issubset(pads):
            raise ValidationError(f"$.component_bindings[{binding['id']}]: incomplete or unknown pin-pad mapping")
        if binding["status"] == "confirmed":
            fpc = binding["fpc_orientation"]
            device = next(item for item in document["selected_devices"] if item["id"] == binding["device_id"])
            fpc_required = any(
                marker in f"{device['role']} {device['package_requirement']}".casefold()
                for marker in ("fpc", "ffc", "flex")
            )
            if (
                not binding["footprint"]["version"]
                or not binding["footprint"]["pin1_marker"]
                or binding["polarity"] in {"unknown", "conflict"}
                or (fpc is not None and fpc["contact_side"] == "unknown")
                or fpc_required and (
                    fpc is None
                    or fpc["contact_side"] not in {"top", "bottom"}
                    or not fpc["insertion_direction"].strip()
                    or not fpc["pin1_direction"].strip()
                )
                or not binding["evidence_refs"]
                or not binding["decision_id"]
            ):
                raise ValidationError(
                    f"$.component_bindings[{binding['id']}]: confirmed binding lacks version, orientation, or evidence"
                )
        _require_evidence_refs(
            binding["evidence_refs"], evidence_registry,
            f"$.component_bindings[{binding['id']}].evidence_refs",
            reliable=binding["status"] == "confirmed",
        )

    for item in document["open_items"]:
        if item["status"] in {"resolved", "accepted_provisional"} and not item["decision_id"]:
            raise ValidationError(
                f"$.open_items[{item['id']}]: resolved/provisional item requires a user decision"
            )
        if item["status"] == "accepted_provisional" and not item["waivable"]:
            raise ValidationError(
                f"$.open_items[{item['id']}]: non-waivable item cannot be accepted provisionally"
            )

    for net in document["net_contracts"]:
        endpoints_match = set(net["expected_endpoints"]) == set(net["actual_endpoints"])
        if net["compare_status"] == "match" and not endpoints_match:
            raise ValidationError(
                f"$.net_contracts[{net['id']}]: match status contradicts endpoint sets"
            )
        if net["compare_status"] == "match" and not net["evidence_refs"]:
            raise ValidationError(
                f"$.net_contracts[{net['id']}]: match requires evidence references"
            )
        _require_evidence_refs(
            net["evidence_refs"], evidence_registry,
            f"$.net_contracts[{net['id']}].evidence_refs",
            reliable=net["compare_status"] == "match",
        )

    schematic = document["schematic"]
    _require_evidence_refs(
        schematic["strict_drc"]["evidence_refs"], evidence_registry,
        "$.schematic.strict_drc.evidence_refs",
        reliable=schematic["status"] == "frozen",
    )
    _require_evidence_refs(
        schematic["evidence_refs"], evidence_registry,
        "$.schematic.evidence_refs",
        reliable=schematic["status"] == "frozen",
    )
    if schematic["status"] == "frozen":
        drc = schematic["strict_drc"]
        electrical_requirement_count = sum(
            len(items) for items in document["electrical_requirements"].values()
        )
        schematic_must_requirements = [
            item for item in document["verification_requirements"]
            if item["stage"] == "schematic_freeze" and item["priority"] == "must"
        ]
        if schematic["freeze_decision_id"] is None:
            raise ValidationError("$.schematic.freeze_decision_id: frozen schematic requires user decision")
        if any(drc[name] != 0 for name in ("fatal", "error", "warning")):
            raise ValidationError("$.schematic.strict_drc: frozen schematic requires zero fatal/error/warning")
        if not drc["evidence_refs"] or not schematic["source_hash"]:
            raise ValidationError("$.schematic: frozen schematic requires source hash and DRC evidence")
        if (
            electrical_requirement_count == 0
            or not document["power_domains"]
            or not document["interfaces"]
            or not document["selected_devices"]
            or not document["component_bindings"]
            or not document["net_contracts"]
            or not document["rule_requirements"]
            or not schematic_must_requirements
            or not schematic["critical_net_result_ids"]
            or not schematic["library_revisions"]
        ):
            raise ValidationError(
                "$.schematic: frozen schematic requires electrical requirements, power and interface "
                "contracts, devices, bindings, nets, rules, library revisions, and must-pass critical checks"
            )
        unresolved_bindings = [
            item["id"] for item in document["component_bindings"] if item["status"] != "confirmed"
        ]
        unbound_devices = sorted(device_ids - {item["device_id"] for item in document["component_bindings"]})
        undecided_devices = [
            item["id"] for item in document["selected_devices"] if not item["decision_id"]
        ]
        mismatched_nets = [
            item["id"] for item in document["net_contracts"] if item["compare_status"] != "match"
        ]
        bad_critical_results = [
            result_id
            for result_id in schematic["critical_net_result_ids"]
            if result_id not in results_by_id or results_by_id[result_id]["status"] != "pass"
        ]
        missing_schematic_results = [
            requirement["id"]
            for requirement in document["verification_requirements"]
            if requirement["priority"] == "must"
            and requirement["stage"] == "schematic_freeze"
            and not any(
                result["status"] == "pass" and result["evidence_refs"]
                for result in results_by_requirement.get(requirement["id"], [])
            )
        ]
        if (
            unresolved_bindings or unbound_devices or undecided_devices
            or mismatched_nets or bad_critical_results or missing_schematic_results
        ):
            raise ValidationError(
                "$.schematic: frozen schematic has unresolved bindings, devices, nets, or critical results: "
                f"{unresolved_bindings}, {unbound_devices}, {undecided_devices}, "
                f"{mismatched_nets}, {bad_critical_results}, {missing_schematic_results}"
            )

    pcb = document["pcb"]
    pcb_is_candidate = pcb["status"] in {"pcb_candidate", "waiting_evt"}
    _require_evidence_refs(
        pcb["drc"]["evidence_refs"], evidence_registry,
        "$.pcb.drc.evidence_refs", reliable=pcb_is_candidate,
    )
    _require_evidence_refs(
        pcb["evidence_refs"], evidence_registry,
        "$.pcb.evidence_refs", reliable=pcb_is_candidate,
    )
    if pcb["status"] in {"pcb_candidate", "waiting_evt"}:
        if pcb["candidate_decision_id"] is None:
            raise ValidationError("$.pcb.candidate_decision_id: PCB candidate requires user decision")
        if (
            pcb["board_constraint_ref"] is None
            or pcb["layer_count"] is None
            or pcb["layer_count_decision_id"] is None
            or pcb["stackup_source"] is None
            or pcb["stackup_decision_id"] is None
        ):
            raise ValidationError("$.pcb: candidate requires board constraints, layer count, and stackup source")
        if schematic["status"] != "frozen":
            raise ValidationError("$.pcb: candidate requires a frozen schematic")
        if pcb["schematic_source_hash"] != schematic["source_hash"]:
            raise ValidationError("$.pcb.schematic_source_hash: candidate does not match frozen schematic")
        board_ref_key = _artifact_key(pcb["board_constraint_ref"])
        matching_dependencies = [
            item for item in document["dependencies"]
            if _artifact_key(item) == board_ref_key
            and item["content_hash"] == pcb["board_constraint_ref"]["content_hash"]
        ]
        if not matching_dependencies:
            raise ValidationError("$.pcb.board_constraint_ref: interface constraint is not a matching dependency")
        if pcb["source_hash"] is None or not pcb["drc"]["evidence_refs"] or not pcb["evidence_refs"]:
            raise ValidationError("$.pcb: candidate requires source hash, DRC evidence, and source evidence")
        if any(pcb["drc"][name] != 0 for name in ("fatal", "error", "warning")):
            raise ValidationError("$.pcb.drc: PCB candidate requires zero fatal/error/warning")
        unresolved_bindings = [item["id"] for item in document["component_bindings"] if item["status"] != "confirmed"]
        mismatched_nets = [item["id"] for item in document["net_contracts"] if item["compare_status"] != "match"]
        if unresolved_bindings or mismatched_nets:
            raise ValidationError(
                f"$.pcb: candidate has unresolved bindings {unresolved_bindings} or nets {mismatched_nets}"
            )
        missing_must_results = []
        for requirement in document["verification_requirements"]:
            if requirement["priority"] != "must" or requirement["stage"] == "evt":
                continue
            results = results_by_requirement.get(requirement["id"], [])
            if not any(item["status"] == "pass" and item["evidence_refs"] for item in results):
                missing_must_results.append(requirement["id"])
        blocking_items = [
            item["id"] for item in document["open_items"]
            if item["status"] == "open" and item["blocking_stage"] is not None
        ]
        unresolved_requirements = [
            item["id"]
            for items in document["electrical_requirements"].values()
            for item in items
            if item["status"] in {"missing", "conflict"}
        ]
        unresolved_domains = [
            item["id"] for item in document["power_domains"]
            if item["status"] != "confirmed"
            or item["nominal_voltage"]["status"] != "confirmed"
            or item["current_requirement"]["status"] != "confirmed"
        ]
        unresolved_interfaces = [
            item["id"] for item in document["interfaces"] if item["status"] != "confirmed"
        ]
        unresolved_devices = [
            item["id"] for item in document["selected_devices"]
            if item["selection_status"] != "user_confirmed" or not item["decision_id"]
        ]
        unresolved_rules = [
            item["id"] for item in document["rule_requirements"]
            if item["status"] != "confirmed"
        ]
        if (
            missing_must_results or blocking_items or unresolved_requirements
            or unresolved_domains or unresolved_interfaces or unresolved_devices or unresolved_rules
        ):
            raise ValidationError(
                "$.pcb: candidate has unresolved inputs: "
                f"must_results={missing_must_results}, blockers={blocking_items}, "
                f"requirements={unresolved_requirements}, domains={unresolved_domains}, "
                f"interfaces={unresolved_interfaces}, devices={unresolved_devices}, rules={unresolved_rules}"
            )
    if pcb["status"] == "waiting_evt":
        if pcb["evt_plan_ref"] is None or pcb["evt_plan_ref"]["content_hash"] is None:
            raise ValidationError(
                "$.pcb.evt_plan_ref: waiting_evt requires a hashed EVT validation plan"
            )
    elif pcb["evt_plan_ref"] is not None:
        raise ValidationError(
            "$.pcb.evt_plan_ref: only waiting_evt may reference an EVT validation plan"
        )
    _validate_evidence_status(document["status"], document["evidence"], "$")


def _validate_interface_control(document: Mapping[str, Any]) -> None:
    _index_evidence(document["evidence"], "$.evidence")
    all_ids: List[str] = []
    for key in ("mounting_holes", "interface_features", "keepouts", "height_zones", "volumes"):
        all_ids.extend(_require_unique_ids(document[key], f"$.{key}"))
    if len(all_ids) != len(set(all_ids)):
        raise ValidationError("$: interface item ids must be unique across geometry collections")

    dependency_keys = [
        f"{item['artifact_id']}@{item['revision']}" for item in document["dependencies"]
    ]
    if len(dependency_keys) != len(set(dependency_keys)):
        raise ValidationError("$.dependencies: duplicate artifact revisions are not allowed")

    axes = [
        document["coordinate_system"]["x_axis"],
        document["coordinate_system"]["y_axis"],
        document["coordinate_system"]["z_axis"],
    ]
    for index, axis in enumerate(axes):
        magnitude = math.sqrt(sum(value * value for value in axis))
        if not math.isclose(magnitude, 1.0, abs_tol=1e-6):
            raise ValidationError(f"$.coordinate_system: axis {index} is not a unit vector")
    for left in range(3):
        for right in range(left + 1, 3):
            dot = sum(axes[left][index] * axes[right][index] for index in range(3))
            if not math.isclose(dot, 0.0, abs_tol=1e-6):
                raise ValidationError("$.coordinate_system: axes are not orthogonal")

    if document["pcb"]["thickness_mm"] is not None and document["pcb"]["thickness_mm"] <= 0:
        raise ValidationError("$.pcb.thickness_mm: thickness must be positive")
    for item in document["mounting_holes"]:
        if item["diameter_mm"] is not None and item["diameter_mm"] <= 0:
            raise ValidationError(f"$.mounting_holes[{item['id']}].diameter_mm: must be positive")

    geometry_items = [
        ("$.product_envelope", "envelope", document["product_envelope"]),
        ("$.pcb", "pcb", document["pcb"]),
    ]
    geometry_items.extend(
        (f"$.mounting_holes[{item['id']}]", "hole", item)
        for item in document["mounting_holes"]
    )
    geometry_items.extend(
        (f"$.{key}[{item['id']}]", key, item)
        for key in ("interface_features", "keepouts", "height_zones", "volumes")
        for item in document[key]
    )
    for path, kind, item in geometry_items:
        status = item["status"]
        if status in {"confirmed", "assumed"} and not item["source_refs"]:
            raise ValidationError(f"{path}: {status} geometry requires source_refs")
        if status == "conflict" and len(item["source_refs"]) < 2:
            raise ValidationError(f"{path}: conflict geometry requires at least two source_refs")

        if kind == "envelope":
            complete = item["size_mm"] is not None and all(value > 0 for value in item["size_mm"])
            empty = item["size_mm"] is None
        elif kind == "pcb":
            complete = (
                len(item["outline_points_mm"]) >= 3
                and item["board_origin_mm"] is not None
                and item["thickness_mm"] is not None
            )
            empty = (
                item["outline_points_mm"] == []
                and item["board_origin_mm"] is None
                and item["thickness_mm"] is None
            )
        elif kind == "hole":
            complete = item["position_mm"] is not None and item["diameter_mm"] is not None
            empty = item["position_mm"] is None and item["diameter_mm"] is None
        else:
            complete = (
                item["pose"] is not None and item["size_mm"] is not None
                and all(value > 0 for value in item["size_mm"])
            )
            empty = item["pose"] is None and item["size_mm"] is None
            if kind == "height_zones":
                complete = complete and item["max_height_mm"] is not None and item["max_height_mm"] > 0
                empty = empty and item["max_height_mm"] is None
        if status in {"confirmed", "assumed"} and not complete:
            raise ValidationError(f"{path}: {status} geometry requires complete canonical values")
        if status in {"missing", "conflict"} and not empty:
            raise ValidationError(f"{path}: {status} geometry must not contain canonical values")

    if document["status"] == "verified":
        if document["freeze_decision_id"] is None:
            raise ValidationError("$.freeze_decision_id: verified interface control requires a user freeze decision")
        root_items = [document["product_envelope"], document["pcb"]]
        nested_items = [
            item
            for key in ("mounting_holes", "interface_features", "keepouts", "height_zones", "volumes")
            for item in document[key]
        ]
        invalid = [item.get("id", "root") for item in root_items + nested_items if item["status"] != "confirmed"]
        if invalid:
            raise ValidationError(f"$: verified interface control contains non-confirmed items {invalid}")
        if document["pcb"]["thickness_mm"] is None:
            raise ValidationError("$.pcb.thickness_mm: verified interface control requires board thickness")
        if any(value is None for value in document["product_envelope"]["size_mm"]):
            raise ValidationError("$.product_envelope.size_mm: verified envelope cannot contain null dimensions")
        sized_items = [document["product_envelope"]] + [
            item
            for key in ("interface_features", "keepouts", "height_zones", "volumes")
            for item in document[key]
        ]
        invalid_sizes = [
            item.get("id", "product_envelope")
            for item in sized_items
            if any(value is None or value <= 0 for value in item["size_mm"])
        ]
        invalid_holes = [
            item["id"] for item in document["mounting_holes"]
            if item["diameter_mm"] is None
        ]
        invalid_heights = [
            item["id"] for item in document["height_zones"]
            if item["max_height_mm"] is None or item["max_height_mm"] <= 0
        ]
        if invalid_sizes or invalid_holes or invalid_heights:
            raise ValidationError(
                f"$: verified interface has invalid sizes {invalid_sizes}, holes {invalid_holes}, "
                f"or height limits {invalid_heights}"
            )
    _validate_evidence_status(document["status"], document["evidence"], "$")


SEMANTIC_VALIDATORS = {
    "design_pack": _validate_design_pack,
    "run_state": _validate_run_state,
    "electrical_pack": _validate_electrical_pack,
    "interface_control": _validate_interface_control,
}


def validate_document(document: Any, schema_dir: Path = None, expected_kind: str = None) -> None:
    if not isinstance(document, dict):
        raise ValidationError("$: document must be an object")
    _reject_nonfinite(document)
    document_type = document.get("document_type")
    if document_type not in SCHEMA_FILES:
        raise ValidationError(f"$.document_type: unsupported or missing document type {document_type!r}")
    if expected_kind is not None:
        normalized_kind = KIND_ALIASES.get(expected_kind)
        if normalized_kind is None:
            raise ValidationError(f"unsupported validation kind {expected_kind!r}")
        if document_type != normalized_kind:
            raise ValidationError(
                f"$.document_type: expected {normalized_kind!r} for kind {expected_kind!r}, got {document_type!r}"
            )
    directory = schema_dir or _schema_dir()
    schema_path = directory / SCHEMA_FILES[document_type]
    try:
        schema = _loads_strict_json(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load schema {schema_path}: {exc}") from exc
    _validate_schema(document, schema, schema, "$")
    SEMANTIC_VALIDATORS[document_type](document)


def load_and_validate(path: Path, schema_dir: Path = None, expected_kind: str = None) -> Dict[str, Any]:
    try:
        document = _loads_strict_json(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON document {path}: {exc}") from exc
    validate_document(document, schema_dir=schema_dir, expected_kind=expected_kind)
    return document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Ploo V2 JSON document.")
    parser.add_argument("kind", choices=sorted(KIND_ALIASES), help="Document kind")
    parser.add_argument("input", type=Path, help="V2 JSON document")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        document = load_and_validate(args.input, expected_kind=args.kind)
    except ValidationError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"valid: {document['document_type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
