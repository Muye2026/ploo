#!/usr/bin/env python3
"""Migrate a V1 design pack into a V2 design-pack/run-state bundle."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from validate_v2 import ValidationError, contract_hash, validate_document


V1_FIELDS = {
    "product_goal",
    "execution_mode",
    "interaction_mode",
    "auto",
    "route",
    "track_routes",
    "hard_constraints",
    "component_envelopes",
    "reference_cases",
    "component_requirements",
    "component_candidates",
    "selected_components",
    "packaging_constraints",
    "sourcing_risks",
    "layout_zones",
    "mounting_strategy",
    "style_features",
    "manufacturing_risks",
    "forbidden_features",
    "acceptance_checks",
}

TRACK_ROUTE_VALUES = {
    "visualization": {None, "skip", "image", "video", "image+video"},
    "mechanical": {None, "skip", "spec", "direct", "guided", "handoff"},
    "schematic": {None, "skip", "direct", "guided", "hybrid", "handoff"},
    "pcb": {None, "skip", "direct", "guided", "hybrid", "handoff"},
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected object")
    return value


def _reject_unknown(item: Mapping[str, Any], allowed: Sequence[str], path: str) -> None:
    unknown = set(item) - set(allowed)
    if unknown:
        raise ValidationError(f"{path}: unknown V1 properties {sorted(unknown)}")


def _text(value: Any, path: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValidationError(f"{path}: expected {'non-empty ' if not allow_empty else ''}string")
    return value


def _size(value: Any, path: str) -> List[float]:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise ValidationError(f"{path}: expected one to three dimensions")
    if any(not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0 for item in value):
        raise ValidationError(f"{path}: dimensions must be non-negative numbers")
    return list(value)


def _identifier(item: Mapping[str, Any], prefix: str, index: int) -> str:
    value = item.get("id", f"{prefix}-{index:02d}")
    return _text(value, f"{prefix}[{index}].id", allow_empty=False)


def _records(items: Any, path: str, converter) -> List[Dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValidationError(f"{path}: expected array")
    return [converter(item, index + 1) for index, item in enumerate(items)]


def _hard_constraint(item: Any, index: int) -> Dict[str, Any]:
    if isinstance(item, str):
        return {"id": f"hc-{index:02d}", "category": "legacy", "rule": item, "priority": "must"}
    value = _require_mapping(item, f"hard_constraints[{index}]")
    _reject_unknown(value, ("id", "category", "rule", "priority"), f"hard_constraints[{index}]")
    return {
        "id": _identifier(value, "hc", index),
        "category": _text(value.get("category", "legacy"), "category", False),
        "rule": _text(value.get("rule"), "rule", False),
        "priority": _text(value.get("priority", "must"), "priority", False),
    }


def _component_envelope(item: Any, index: int) -> Dict[str, Any]:
    value = _require_mapping(item, f"component_envelopes[{index}]")
    _reject_unknown(value, ("id", "name", "size_mm", "placement_note", "source_status"), f"component_envelopes[{index}]")
    return {
        "id": _identifier(value, "ce", index),
        "name": _text(value.get("name"), "name", False),
        "size_mm": _size(value.get("size_mm"), "size_mm"),
        "placement_note": _text(value.get("placement_note", ""), "placement_note"),
        "source_status": "assumed",
    }


def _reference_case(item: Any, index: int) -> Dict[str, Any]:
    value = _require_mapping(item, f"reference_cases[{index}]")
    allowed = ("id", "case", "lesson", "design_implication", "source_note")
    _reject_unknown(value, allowed, f"reference_cases[{index}]")
    return {
        "id": _identifier(value, "rc", index),
        "case": _text(value.get("case"), "case", False),
        "lesson": _text(value.get("lesson", ""), "lesson"),
        "design_implication": _text(value.get("design_implication", ""), "design_implication"),
        "source_note": _text(value.get("source_note", ""), "source_note"),
    }


def _component_requirement(item: Any, index: int) -> Dict[str, Any]:
    value = _require_mapping(item, f"component_requirements[{index}]")
    allowed = ("id", "module", "requirement", "envelope_target_mm", "design_implication")
    _reject_unknown(value, allowed, f"component_requirements[{index}]")
    result = {
        "id": _identifier(value, "cr", index),
        "module": _text(value.get("module"), "module", False),
        "requirement": _text(value.get("requirement"), "requirement", False),
        "design_implication": _text(value.get("design_implication", ""), "design_implication"),
    }
    if "envelope_target_mm" in value:
        result["envelope_target_mm"] = _size(value["envelope_target_mm"], "envelope_target_mm")
    return result


def _component_candidate(item: Any, index: int) -> Dict[str, Any]:
    value = _require_mapping(item, f"component_candidates[{index}]")
    allowed = ("id", "module", "candidate", "approx_envelope_mm", "interface_or_mounting", "visible_design_impact", "risk")
    _reject_unknown(value, allowed, f"component_candidates[{index}]")
    result = {
        "id": _identifier(value, "cc", index),
        "module": _text(value.get("module"), "module", False),
        "candidate": _text(value.get("candidate"), "candidate", False),
        "interface_or_mounting": _text(value.get("interface_or_mounting", ""), "interface_or_mounting"),
        "visible_design_impact": _text(value.get("visible_design_impact", ""), "visible_design_impact"),
        "risk": _text(value.get("risk", ""), "risk"),
    }
    if "approx_envelope_mm" in value:
        result["approx_envelope_mm"] = _size(value["approx_envelope_mm"], "approx_envelope_mm")
    return result


def _selected_component(item: Any, index: int) -> Dict[str, Any]:
    value = _require_mapping(item, f"selected_components[{index}]")
    allowed = (
        "id", "module", "selection", "selection_status", "why", "fixed_constraints",
        "unverified", "fallback_envelope_mm", "decision_id"
    )
    _reject_unknown(value, allowed, f"selected_components[{index}]")
    result = {
        "id": _identifier(value, "sc", index),
        "module": _text(value.get("module"), "module", False),
        "selection": _text(value.get("selection"), "selection", False),
        "selection_status": "needs_user_confirmation",
        "decision_id": None,
        "why": _text(value.get("why", ""), "why"),
        "fixed_constraints": _text(value.get("fixed_constraints", ""), "fixed_constraints"),
        "unverified": _text(value.get("unverified", ""), "unverified"),
    }
    if "fallback_envelope_mm" in value:
        result["fallback_envelope_mm"] = _size(value["fallback_envelope_mm"], "fallback_envelope_mm")
    return result


def _text_record(prefix: str):
    def convert(item: Any, index: int) -> Dict[str, Any]:
        if isinstance(item, str):
            return {"id": f"{prefix}-{index:02d}", "text": item}
        value = _require_mapping(item, f"{prefix}[{index}]")
        _reject_unknown(value, ("id", "text"), f"{prefix}[{index}]")
        return {"id": _identifier(value, prefix, index), "text": _text(value.get("text"), "text", False)}
    return convert


def _layout_zone(item: Any, index: int) -> Dict[str, Any]:
    value = _require_mapping(item, f"layout_zones[{index}]")
    _reject_unknown(value, ("id", "name", "surface", "purpose", "priority"), f"layout_zones[{index}]")
    return {
        "id": _identifier(value, "lz", index), "name": _text(value.get("name"), "name", False),
        "surface": _text(value.get("surface"), "surface", False),
        "purpose": _text(value.get("purpose"), "purpose", False),
        "priority": _text(value.get("priority", "should"), "priority", False),
    }


def _style_feature(item: Any, index: int) -> Dict[str, Any]:
    if isinstance(item, str):
        return {"id": f"sf-{index:02d}", "name": item, "rule": item}
    value = _require_mapping(item, f"style_features[{index}]")
    _reject_unknown(value, ("id", "name", "rule"), f"style_features[{index}]")
    return {
        "id": _identifier(value, "sf", index), "name": _text(value.get("name"), "name", False),
        "rule": _text(value.get("rule"), "rule", False),
    }


def _acceptance_check(item: Any, index: int) -> Dict[str, Any]:
    if isinstance(item, str):
        return {"id": f"ac-{index:02d}", "title": item, "method": "TBD", "pass_condition": "TBD", "priority": "should"}
    value = _require_mapping(item, f"acceptance_checks[{index}]")
    allowed = ("id", "title", "method", "pass_condition", "priority")
    _reject_unknown(value, allowed, f"acceptance_checks[{index}]")
    return {
        "id": _identifier(value, "ac", index), "title": _text(value.get("title"), "title", False),
        "method": _text(value.get("method", "TBD"), "method", False),
        "pass_condition": _text(value.get("pass_condition", "TBD"), "pass_condition", False),
        "priority": _text(value.get("priority", "should"), "priority", False),
    }


def _mounting_strategy(value: Any) -> Dict[str, Any]:
    if value is None:
        value = {}
    data = _require_mapping(value, "mounting_strategy")
    allowed = ("type", "contact_points", "support_logic", "service_access_notes", "suggested_part_split")
    _reject_unknown(data, allowed, "mounting_strategy")
    split = data.get("suggested_part_split", [])
    if not isinstance(split, list) or any(not isinstance(item, str) or not item for item in split):
        raise ValidationError("mounting_strategy.suggested_part_split: expected non-empty strings")
    return {
        "type": _text(data.get("type", ""), "mounting_strategy.type"),
        "contact_points": _text(data.get("contact_points", ""), "mounting_strategy.contact_points"),
        "support_logic": _text(data.get("support_logic", ""), "mounting_strategy.support_logic"),
        "service_access_notes": _text(data.get("service_access_notes", ""), "mounting_strategy.service_access_notes"),
        "suggested_part_split": list(split),
    }


def _interaction_mode(source: Mapping[str, Any]) -> Tuple[Optional[str], str]:
    explicit = source.get("interaction_mode")
    auto_flag = source.get("auto")
    if explicit is not None and explicit not in {"auto", "checkpointed"}:
        raise ValidationError("interaction_mode: expected auto or checkpointed")
    if auto_flag is not None and not isinstance(auto_flag, bool):
        raise ValidationError("auto: expected boolean")
    derived = "auto" if auto_flag else "checkpointed" if auto_flag is not None else None
    if explicit is not None and derived is not None and explicit != derived:
        raise ValidationError("interaction_mode and auto flag conflict")
    source_mode = explicit or derived
    cadence = "continuous_within_approved_route" if source_mode == "auto" else "stepwise"
    return source_mode, cadence


def _track_routes(source: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """Never carry V1 route claims into V2 execution authorization."""
    raw = source.get("track_routes", source.get("route"))
    if raw is not None:
        data = _require_mapping(raw, "track_routes")
        _reject_unknown(data, tuple(TRACK_ROUTE_VALUES), "track_routes")
        for track, allowed in TRACK_ROUTE_VALUES.items():
            if track in data and data[track] not in allowed:
                raise ValidationError(f"track_routes.{track}: unsupported legacy route {data[track]!r}")
    return {track: None for track in TRACK_ROUTE_VALUES}


def _decision_gate(artifact_id: str, content_hash: str) -> Dict[str, Any]:
    return {
        "decision_id": "decision-track-routes-001",
        "decision_type": "route_selection",
        "scope": [f"track:{track}" for track in TRACK_ROUTE_VALUES],
        "status": "pending",
        "question": "请选择 visualization、mechanical、schematic、pcb 四条轨道的执行路线。",
        "options": [
            {
                "id": "configure_routes", "label": "逐轨明确路线",
                "description": "分别选择四条轨道，不从旧 execution_mode 推断。",
                "impact": "只有显式选择的轨道会获得用户决策记录。"
            }
        ],
        "recommendation": "configure_routes",
        "recommendation_rationale": "Recording each track separately is the only path that grants no implicit route authority.",
        "impact": ["未决轨道保持 null。", "未完成四轨选择前 run 保持 waiting_user_decision。"],
        "selected_option": None,
        "decided_by": None,
        "decided_at": None,
        "decision_evidence": [],
        "dependency_revisions": [{"artifact_id": artifact_id, "revision": 1, "content_hash": content_hash}],
    }


def migrate(source: Mapping[str, Any], source_name: str = "v1-input") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    unknown = set(source) - V1_FIELDS
    if unknown:
        raise ValidationError(f"$: unknown V1 properties {sorted(unknown)}")
    goal = _text(source.get("product_goal"), "product_goal", allow_empty=False)
    execution_mode = source.get("execution_mode")
    if execution_mode is not None and execution_mode not in {"full", "spec-only", "handoff"}:
        raise ValidationError("execution_mode: expected full, spec-only, or handoff")
    source_interaction_mode, cadence = _interaction_mode(source)
    routes = _track_routes(source)
    migrated_at = _now()
    source_digest = _hash(source)
    artifact_id = "design-pack-" + source_digest.removeprefix("sha256:")[:12]

    design_pack: Dict[str, Any] = {
        "schema_version": "2.0",
        "document_type": "design_pack",
        "artifact_id": artifact_id,
        "revision": 1,
        "status": "planned",
        "architecture_decision_id": None,
        "freeze_decision_id": None,
        "provenance": {"source": source_name, "producer": "migrate_v1_to_v2.py", "time": migrated_at, "hash": None},
        "evidence": [{"evidence_id": "evidence-v1-migration", "type": "unverified", "source": source_name, "captured_at": migrated_at, "ref": None, "note": "Migrated structure; source claims were not independently verified."}],
        "product_goal": goal,
        "hard_constraints": _records(source.get("hard_constraints", []), "hard_constraints", _hard_constraint),
        "component_envelopes": _records(source.get("component_envelopes", []), "component_envelopes", _component_envelope),
        "reference_cases": _records(source.get("reference_cases", []), "reference_cases", _reference_case),
        "component_requirements": _records(source.get("component_requirements", []), "component_requirements", _component_requirement),
        "component_candidates": _records(source.get("component_candidates", []), "component_candidates", _component_candidate),
        "selected_components": _records(source.get("selected_components", []), "selected_components", _selected_component),
        "packaging_constraints": _records(source.get("packaging_constraints", []), "packaging_constraints", _text_record("pc")),
        "sourcing_risks": _records(source.get("sourcing_risks", []), "sourcing_risks", _text_record("sr")),
        "layout_zones": _records(source.get("layout_zones", []), "layout_zones", _layout_zone),
        "mounting_strategy": _mounting_strategy(source.get("mounting_strategy")),
        "style_features": _records(source.get("style_features", []), "style_features", _style_feature),
        "manufacturing_risks": _records(source.get("manufacturing_risks", []), "manufacturing_risks", _text_record("mr")),
        "forbidden_features": _records(source.get("forbidden_features", []), "forbidden_features", _text_record("ff")),
        "acceptance_checks": _records(source.get("acceptance_checks", []), "acceptance_checks", _acceptance_check),
        "migration": {
            "source_schema": "design-pack.v1",
            "source_execution_mode": execution_mode,
            "source_interaction_mode": source_interaction_mode,
            "migrated_at": migrated_at,
        },
    }
    design_pack["provenance"]["hash"] = contract_hash(design_pack)

    content_hash = design_pack["provenance"]["hash"]
    pending_gate = _decision_gate(artifact_id, content_hash)
    run_state = {
        "schema_version": "2.0",
        "document_type": "run_state",
        "run_id": "run-" + hashlib.sha256((artifact_id + cadence).encode("utf-8")).hexdigest()[:12],
        "status": "waiting_user_decision",
        "decision_authority": "user",
        "confirmation_policy": "material_decisions",
        "execution_cadence": cadence,
        "track_routes": routes,
        "route_decision_ids": {track: None for track in TRACK_ROUTE_VALUES},
        "pending_decision_gate": pending_gate,
        "decision_ledger": [],
        "capability_reports": [
            {
                "report_id": f"capability-{track}-unknown",
                "track": track,
                "adapter_id": "unknown",
                "adapter_version": None,
                "status": "unknown",
                "checked_at": migrated_at,
                "tool_schema_digest": None,
                "capabilities": {
                    "read": False, "write": False, "verify": False,
                    "export": False, "rollback": False, "render": False
                },
                "operations": [],
                "units": {},
                "limitations": ["V1 input did not contain a verified capability report."],
                "evidence": [{"evidence_id": f"evidence-capability-{track}-unknown", "type": "unverified", "source": source_name, "captured_at": migrated_at, "ref": None, "note": "Capability not checked during migration."}],
            }
            for track in ("visualization", "mechanical", "schematic", "pcb")
        ],
        "artifacts": [
            {
                "artifact_id": artifact_id,
                "artifact_type": "design_pack",
                "revision": 1,
                "status": design_pack["status"],
                "path": "design-pack.v2.json",
                "content_hash": content_hash,
                "source_hashes": {"v1_input": source_digest},
                "provenance": design_pack["provenance"],
                "evidence": design_pack["evidence"],
                "depends_on": [],
                "invalidation_reasons": [],
            }
        ],
        "operation_cards": [],
        "execution_reservations": [],
        "authorization_consumptions": [],
        "cross_domain_checks": [],
    }
    validate_document(design_pack, expected_kind="design-pack")
    validate_document(run_state, expected_kind="run-state")
    return design_pack, run_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate a V1 design pack to a V2 migration bundle.")
    parser.add_argument("input", type=Path, help="V1 design-pack JSON")
    parser.add_argument("output", nargs="?", type=Path, help="New V2 migration bundle JSON")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="New directory for design-pack.v2.json, run-state.v2.json, and migration-bundle.v2.json",
    )
    parser.add_argument(
        "--source-ref",
        help="Portable logical source reference; defaults to the input filename only",
    )
    args = parser.parse_args()
    if (args.output is None) == (args.output_dir is None):
        parser.error("provide exactly one of OUTPUT or --output-dir")
    return args


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _write_new_atomic(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically publish a new file without overwriting an existing path."""
    if os.path.lexists(path):
        raise ValidationError(f"output already exists: {path}")
    if not path.parent.is_dir():
        raise ValidationError(f"output parent directory does not exist: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_json_text(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ValidationError(f"output already exists: {path}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_split_directory(path: Path, bundle: Mapping[str, Any]) -> None:
    if os.path.lexists(path):
        raise ValidationError(f"output directory already exists: {path}")
    if not path.parent.is_dir():
        raise ValidationError(f"output parent directory does not exist: {path.parent}")
    path.mkdir()
    _write_new_atomic(path / "design-pack.v2.json", bundle["design_pack"])
    _write_new_atomic(path / "run-state.v2.json", bundle["run_state"])
    _write_new_atomic(path / "migration-bundle.v2.json", bundle)


def main() -> int:
    args = parse_args()
    try:
        if args.output is not None and args.input.resolve() == args.output.resolve():
            raise ValidationError("input and output must be different paths")
        source = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            raise ValidationError("$: V1 input must be an object")
        source_ref = args.source_ref if args.source_ref is not None else args.input.name
        if not source_ref:
            raise ValidationError("source reference must be non-empty")
        design_pack, run_state = migrate(source, source_name=source_ref)
        bundle = {
            "schema_version": "2.0",
            "document_type": "migration_bundle",
            "design_pack": design_pack,
            "run_state": run_state,
        }
        if args.output is not None:
            _write_new_atomic(args.output, bundle)
        else:
            _write_split_directory(args.output_dir, bundle)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
