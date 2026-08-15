import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from adapter_contracts import canonical_parameter_digest, document_digest  # noqa: E402
from build_review_matrix import DEFAULT_CATEGORIES  # noqa: E402
from manage_run_state import reserve_execution, resolve_routes  # noqa: E402
from validate_bundle import (  # noqa: E402
    authorize_execute_step, authorize_reserved_execute_step, validate_bundle,
)
from validate_v2 import ValidationError, contract_hash, validate_document  # noqa: E402


EXAMPLES = ROOT / "examples" / "v2-orchestrator-demo"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def evidence(evidence_id, evidence_type="source_export"):
    return {
        "evidence_id": evidence_id,
        "type": evidence_type,
        "source": "synthetic reachability fixture",
        "captured_at": "2026-01-01T00:00:00Z",
        "ref": f"sha256:{evidence_id}",
        "note": "Synthetic reliable evidence.",
    }


def artifact_ref(artifact):
    return {
        "artifact_id": artifact["artifact_id"],
        "revision": artifact["revision"],
        "content_hash": artifact["content_hash"],
    }


def artifact_record(artifact_id, artifact_type, content_hash, path, depends_on=()):
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "revision": 1,
        "status": "verified",
        "path": path,
        "content_hash": content_hash,
        "source_hashes": {},
        "provenance": {
            "source": "synthetic reachability fixture",
            "producer": "unit test",
            "time": "2026-01-01T00:00:00Z",
            "hash": content_hash,
        },
        "evidence": [evidence(f"evidence-{artifact_id}")],
        "depends_on": [copy.deepcopy(item) for item in depends_on],
        "invalidation_reasons": [],
    }


def all_artifact_refs(state):
    return [artifact_ref(item) for item in state["artifacts"]]


def user_decision(state, decision_id, decision_type, scope, selected_option):
    decision = {
        "decision_id": decision_id,
        "decision_type": decision_type,
        "scope": list(scope),
        "status": "resolved",
        "question": f"Approve synthetic decision {decision_id}?",
        "options": [
            {
                "id": selected_option,
                "label": selected_option,
                "description": "Synthetic explicit user choice.",
                "impact": "Authorizes only the exact bound choice.",
            }
        ],
        "recommendation": selected_option,
        "recommendation_rationale": "Synthetic reachability fixture.",
        "impact": ["Bound to current artifact revisions."],
        "selected_option": selected_option,
        "decided_by": "user",
        "decided_at": "2026-01-01T00:00:00Z",
        "decision_evidence": [evidence(f"evidence-{decision_id}", "user_self_report")],
        "dependency_revisions": all_artifact_refs(state),
    }
    decision["decision_evidence"][0]["ref"] = f"approval-record:{decision_id}"
    return decision


def review_results_for(design):
    return {
        "schema_version": "2.0",
        "document_type": "review_results",
        "design_pack_ref": {
            "artifact_id": design["artifact_id"],
            "revision": design["revision"],
            "content_hash": contract_hash(design),
        },
        "categories": [
            {
                "category": category,
                "status": "pass",
                "evidence": [evidence(f"review-category-{index:02d}")],
                "blocking_issue": "",
                "next_action": "",
            }
            for index, category in enumerate(DEFAULT_CATEGORIES, start=1)
        ],
        "acceptance_results": [
            {
                "check_id": check["id"],
                "status": "pass",
                "evidence": [evidence(f"review-acceptance-{check['id']}", "screenshot")],
            }
            for check in design["acceptance_checks"]
        ],
    }


def build_bundle(stage="schematic"):
    if stage not in {"schematic", "pcb", "evt"}:
        raise ValueError(stage)
    state = example("run-state.v2.json")
    design = example("design-pack.v2.json")
    electrical = example("electrical-pack.v2.json")
    interface = example("interface-control.v2.json")

    design.update(
        {
            "status": "verified",
            "architecture_decision_id": "decision-design-architecture",
            "freeze_decision_id": "decision-design-freeze",
            "evidence": [evidence("evidence-design-verified")],
        }
    )
    design["component_envelopes"][0]["source_status"] = "confirmed"
    design_hash = contract_hash(design)
    design["provenance"]["hash"] = design_hash

    interface.update(
        {
            "status": "verified",
            "freeze_decision_id": "decision-interface-freeze",
            "evidence": [evidence("evidence-interface-verified")],
            "dependencies": [
                {
                    "artifact_id": design["artifact_id"],
                    "revision": design["revision"],
                    "content_hash": design_hash,
                }
            ],
        }
    )
    interface["pcb"].update(
        {
            "outline_points_mm": [[5, 5, 3], [65, 5, 3], [65, 40, 3], [5, 40, 3]],
            "thickness_mm": 1.6,
            "board_origin_mm": [5, 5, 3],
            "status": "confirmed",
            "source_refs": ["decision-interface-freeze"],
        }
    )
    interface_hash = contract_hash(interface)
    interface["provenance"]["hash"] = interface_hash

    electrical.update(
        {
            "status": "verified",
            "evidence": [evidence("evidence-electrical-verified")],
            "dependencies": [
                {
                    "artifact_id": design["artifact_id"],
                    "revision": design["revision"],
                    "content_hash": design_hash,
                    "facets": ["architecture", "product envelope"],
                    "on_change": "review",
                },
                {
                    "artifact_id": interface["artifact_id"],
                    "revision": interface["revision"],
                    "content_hash": interface_hash,
                    "facets": ["pcb geometry", "connectors"],
                    "on_change": "rebuild",
                },
            ],
            "electrical_requirements": {
                "functional_blocks": [
                    {
                        "id": "req-controller",
                        "statement": "Provide one synthetic controller block.",
                        "status": "confirmed",
                        "source_refs": ["decision-design-architecture"],
                    }
                ],
                "supply_inputs": [],
                "power_budget": [],
                "environmental_constraints": [],
                "safety_constraints": [],
                "assumptions": [],
            },
            "selected_devices": [
                {
                    "id": "device-u1",
                    "role": "controller",
                    "manufacturer_part": "SYNTH-U1",
                    "selection_status": "user_confirmed",
                    "electrical_constraints": ["3.3 V"],
                    "package_requirement": "2-pad synthetic package",
                    "decision_id": "decision-device-u1",
                    "source_refs": ["decision-device-u1"],
                }
            ],
            "power_domains": [
                {
                    "id": "power-3v3",
                    "name": "3V3",
                    "nominal_voltage": {
                        "value": 3.3, "unit": "V", "status": "confirmed",
                        "source_refs": ["decision-design-architecture"],
                    },
                    "source_domain_ids": [],
                    "sink_device_ids": ["device-u1"],
                    "current_requirement": {
                        "value": 0.1, "unit": "A", "status": "confirmed",
                        "source_refs": ["decision-design-architecture"],
                    },
                    "sequencing_constraints": [],
                    "protection_constraints": ["Current limited source"],
                    "status": "confirmed",
                    "source_refs": ["decision-design-architecture"],
                }
            ],
            "interfaces": [
                {
                    "id": "interface-power",
                    "type": "power",
                    "endpoint_a": "J1",
                    "endpoint_b": "U1",
                    "signals": ["VCC"],
                    "electrical_constraints": ["3.3 V"],
                    "shared_interface_ids": [],
                    "status": "confirmed",
                    "source_refs": ["decision-design-architecture"],
                }
            ],
            "component_bindings": [
                {
                    "id": "binding-u1",
                    "refdes": "U1",
                    "device_id": "device-u1",
                    "symbol_pins": ["VCC", "GND"],
                    "footprint": {
                        "id": "SYNTH-FP-U1", "version": "1",
                        "pads": ["1", "2"], "pin1_marker": "triangle",
                    },
                    "pin_pad_map": [
                        {"symbol_pin": "VCC", "pcb_pad": "1"},
                        {"symbol_pin": "GND", "pcb_pad": "2"},
                    ],
                    "polarity": "not_applicable",
                    "fpc_orientation": None,
                    "status": "confirmed",
                    "decision_id": "decision-binding-u1",
                    "evidence_refs": ["evidence-binding-u1"],
                }
            ],
            "net_contracts": [
                {
                    "id": "net-vcc", "name": "VCC", "net_class": "power",
                    "expected_endpoints": ["J1.VCC", "U1.VCC"],
                    "actual_endpoints": ["J1.VCC", "U1.VCC"],
                    "allow_branches": False,
                    "layout_constraints": ["Keep short"],
                    "compare_status": "match",
                    "evidence_refs": ["evidence-net-vcc"],
                }
            ],
            "rule_requirements": [
                {
                    "id": "rule-power", "category": "power",
                    "rule": "VCC must connect only the approved endpoints.",
                    "source": "synthetic rule set", "status": "confirmed",
                }
            ],
            "verification_requirements": [
                {
                    "id": "verify-vcc", "stage": "schematic_freeze",
                    "method": "API endpoint readback", "pass_condition": "Endpoint sets match",
                    "priority": "must", "evidence_required": ["api_readback"],
                }
            ],
            "verification_results": [
                {
                    "id": "result-vcc", "requirement_id": "verify-vcc",
                    "status": "pass", "evidence_refs": ["evidence-net-vcc"],
                }
            ],
            "open_items": [],
            "evidence": [
                evidence("evidence-electrical-verified"),
                evidence("evidence-binding-u1"),
                evidence("evidence-net-vcc", "api_readback"),
                evidence("evidence-schematic-source"),
                evidence("evidence-schematic-drc", "screenshot"),
            ],
        }
    )
    electrical["schematic"].update(
        {
            "artifact_id": "schematic-demo-001", "revision": 1,
            "status": "frozen", "freeze_decision_id": "decision-schematic-freeze",
            "source_hash": "sha256:schematic-demo-001",
            "strict_drc": {
                "ruleset_ref": "strict", "fatal": 0, "error": 0, "warning": 0,
                "exemptions": [], "evidence_refs": ["evidence-schematic-drc"],
            },
            "critical_net_result_ids": ["result-vcc"],
            "nc_whitelist": [],
            "library_revisions": ["synthetic-library@1"],
            "evidence_refs": ["evidence-schematic-source"],
        }
    )

    pcb_hash = None
    if stage in {"pcb", "evt"}:
        electrical["evidence"].extend(
            [
                evidence("evidence-pcb-source"),
                evidence("evidence-pcb-drc", "screenshot"),
                evidence("evidence-pcb-check", "api_readback"),
            ]
        )
        electrical["verification_requirements"].append(
            {
                "id": "verify-pcb", "stage": "pcb_candidate",
                "method": "PCB rule readback", "pass_condition": "Rules and DRC pass",
                "priority": "must", "evidence_required": ["api_readback"],
            }
        )
        electrical["verification_results"].append(
            {
                "id": "result-pcb", "requirement_id": "verify-pcb",
                "status": "pass", "evidence_refs": ["evidence-pcb-check"],
            }
        )
        pcb_hash = "sha256:pcb-demo-001"
        electrical["pcb"].update(
            {
                "artifact_id": "pcb-demo-001", "revision": 1,
                "status": "pcb_candidate",
                "candidate_decision_id": "decision-pcb-candidate",
                "source_hash": pcb_hash,
                "schematic_source_hash": electrical["schematic"]["source_hash"],
                "board_constraint_ref": {
                    "artifact_id": interface["artifact_id"],
                    "revision": interface["revision"],
                    "content_hash": interface_hash,
                },
                "layer_count": 2,
                "layer_count_decision_id": "decision-pcb-layers",
                "stackup_source": "synthetic-stackup@1",
                "stackup_decision_id": "decision-pcb-stackup",
                "evt_plan_ref": None,
                "drc": {
                    "ruleset_ref": "strict", "fatal": 0, "error": 0, "warning": 0,
                    "exemptions": [], "evidence_refs": ["evidence-pcb-drc"],
                },
                "evidence_refs": ["evidence-pcb-source"],
            }
        )
    if stage == "evt":
        electrical["pcb"]["status"] = "waiting_evt"
        electrical["pcb"]["evt_plan_ref"] = {
            "artifact_id": "evt-plan-demo-001",
            "revision": 1,
            "content_hash": "sha256:evt-plan-demo-001",
        }

    electrical_hash = contract_hash(electrical)
    electrical["provenance"]["hash"] = electrical_hash

    core_by_id = {item["artifact_id"]: item for item in state["artifacts"]}
    core_by_id[design["artifact_id"]].update(
        {
            "status": "verified", "content_hash": design_hash,
            "evidence": [evidence("evidence-run-design")],
            "depends_on": [],
        }
    )
    core_by_id[design["artifact_id"]]["provenance"]["hash"] = design_hash
    core_by_id[interface["artifact_id"]].update(
        {
            "status": "verified", "content_hash": interface_hash,
            "evidence": [evidence("evidence-run-interface")],
            "depends_on": [artifact_ref(core_by_id[design["artifact_id"]])],
        }
    )
    core_by_id[interface["artifact_id"]]["provenance"]["hash"] = interface_hash
    core_by_id[electrical["artifact_id"]].update(
        {
            "status": "verified", "content_hash": electrical_hash,
            "evidence": [evidence("evidence-run-electrical")],
            "depends_on": [
                artifact_ref(core_by_id[design["artifact_id"]]),
                artifact_ref(core_by_id[interface["artifact_id"]]),
            ],
        }
    )
    core_by_id[electrical["artifact_id"]]["provenance"]["hash"] = electrical_hash

    schematic_record = artifact_record(
        electrical["schematic"]["artifact_id"], "schematic",
        electrical["schematic"]["source_hash"], "eda/schematic.json",
        [artifact_ref(core_by_id[electrical["artifact_id"]])],
    )
    state["artifacts"].append(schematic_record)

    review_results = review_results_for(design)
    review_record = artifact_record(
        "review-results-design-001", "review_results",
        document_digest(review_results), "reviews/design-review-results.json",
        [artifact_ref(core_by_id[design["artifact_id"]])],
    )
    state["artifacts"].append(review_record)

    pcb_record = None
    if stage in {"pcb", "evt"}:
        pcb_record = artifact_record(
            electrical["pcb"]["artifact_id"], "pcb", pcb_hash, "eda/pcb.json",
            [
                artifact_ref(core_by_id[electrical["artifact_id"]]),
                artifact_ref(schematic_record),
                artifact_ref(core_by_id[interface["artifact_id"]]),
            ],
        )
        state["artifacts"].append(pcb_record)
        state["cross_domain_checks"] = [
            {
                "check_id": "cross-domain-pcb-001", "status": "verified",
                "interface_ref": artifact_ref(core_by_id[interface["artifact_id"]]),
                "cad_ref": None, "pcb_ref": artifact_ref(pcb_record),
                "groups": {
                    "pcb_thickness": "match", "mounting_holes": "match",
                    "connectors": "match", "height_zones": "match",
                    "antenna_keepouts": "match",
                },
                "evidence": [evidence("evidence-cross-domain", "screenshot")],
            }
        ]
    if stage == "evt":
        state["artifacts"].append(
            artifact_record(
                "evt-plan-demo-001", "evt_plan", "sha256:evt-plan-demo-001",
                "evt/validation-plan.json", [artifact_ref(pcb_record)],
            )
        )

    routes = {
        "visualization": "skip",
        "mechanical": "skip",
        "schematic": "guided",
        "pcb": "skip" if stage == "schematic" else "guided",
    }
    state["pending_decision_gate"]["dependency_revisions"] = all_artifact_refs(state)
    state = resolve_routes(state, routes, "chat-message:reachability-routes-001")

    design_scope = [
        f"artifact:{design['artifact_id']}@{design['revision']}",
        f"review:{review_record['artifact_id']}@{review_record['revision']}",
    ]
    decisions = [
        user_decision(
            state, "decision-design-architecture", "architecture_selection",
            [f"artifact:{design['artifact_id']}@{design['revision']}"],
            "approve_architecture",
        ),
        user_decision(state, "decision-design-freeze", "freeze", design_scope, "freeze"),
        user_decision(
            state, "decision-interface-freeze", "freeze",
            [
                f"artifact:{interface['artifact_id']}@{interface['revision']}",
                "constraint:pcb_geometry",
            ],
            "freeze",
        ),
        user_decision(
            state, "decision-schematic-freeze", "freeze",
            [
                f"artifact:{electrical['schematic']['artifact_id']}@"
                f"{electrical['schematic']['revision']}"
            ],
            "freeze",
        ),
        user_decision(
            state, "decision-device-u1", "component_selection",
            ["device:device-u1"], "SYNTH-U1",
        ),
        user_decision(
            state, "decision-binding-u1", "binding_confirmation",
            ["binding:binding-u1"], "confirm_binding",
        ),
    ]
    if stage in {"pcb", "evt"}:
        decisions.extend(
            [
                user_decision(
                    state, "decision-pcb-candidate", "candidate_selection",
                    [f"artifact:{electrical['pcb']['artifact_id']}@{electrical['pcb']['revision']}"],
                    "accept_candidate",
                ),
                user_decision(
                    state, "decision-pcb-layers", "pcb_constraint",
                    ["pcb:layer_count"], "layers:2",
                ),
                user_decision(
                    state, "decision-pcb-stackup", "pcb_constraint",
                    ["pcb:stackup"], "synthetic-stackup@1",
                ),
            ]
        )
    state["decision_ledger"].extend(decisions)
    validate_document(state, expected_kind="run-state")
    return state, design, electrical, interface, review_results


def build_direct_operation_bundle():
    state, design, electrical, interface, review_results = build_bundle("schematic")
    route_id = state["route_decision_ids"]["mechanical"]
    route_decision = next(
        item for item in state["decision_ledger"] if item["decision_id"] == route_id
    )
    route_decision["selected_option"] = "direct"
    state["track_routes"]["mechanical"] = "direct"

    design_record = next(
        item for item in state["artifacts"] if item["artifact_type"] == "design_pack"
    )
    interface_record = next(
        item for item in state["artifacts"] if item["artifact_type"] == "interface_control"
    )
    snapshot = artifact_record(
        "scene-snapshot-001", "cad_scene_snapshot", "sha256:scene-snapshot-001",
        "cad/scene-snapshot.json",
    )
    inputs = [artifact_ref(design_record), artifact_ref(interface_record), artifact_ref(snapshot)]
    output = artifact_record(
        "cad-model-direct-001", "cad_model", "sha256:cad-model-direct-001",
        "cad/model.f3d", inputs,
    )
    output["status"] = "planned"
    output["evidence"] = []
    state["artifacts"].extend([snapshot, output])

    report = next(
        item for item in state["capability_reports"] if item["track"] == "mechanical"
    )
    report.update(
        {
            "adapter_id": "fusion-mcp", "adapter_version": "synthetic-1",
            "status": "available", "checked_at": "2026-01-01T00:00:00Z",
            "tool_schema_digest": "sha256:fusion-schema",
            "capabilities": {
                "read": True, "write": True, "verify": True,
                "export": True, "rollback": True, "render": True,
            },
            "operations": [
                {
                    "capability_id": "cad.create_parametric_body",
                    "provider_operation": "create_parametric_body",
                    "risk_class": "reversible_write", "status": "available",
                    "schema_digest": "sha256:create-body-schema", "limitations": [],
                    "route_options_if_unavailable": ["retry", "guided", "handoff", "pause"],
                    "evidence": [evidence("evidence-create-body-capability", "api_readback")],
                }
            ],
            "units": {"public": "mm", "native": "cm"},
            "limitations": [],
            "evidence": [evidence("evidence-fusion-capability", "api_readback")],
        }
    )
    parameters = {"width_mm": 70, "height_mm": 45, "depth_mm": 24}
    state["operation_cards"] = [
        {
            "step_id": "cad-direct-step-001", "goal": "Create one synthetic enclosure body.",
            "track": "mechanical", "route": "direct", "adapter_id": "fusion-mcp",
            "route_decision_id": route_id, "authorization_decision_ids": [],
            "ownership": "agent", "risk_level": "low",
            "call_id": "call-cad-direct-001", "attempt_id": "attempt-cad-direct-001",
            "parameters": parameters,
            "parameter_digest": canonical_parameter_digest(parameters),
            "status": "planned", "required_capabilities": ["cad.create_parametric_body"],
            "execution_capability_id": "cad.create_parametric_body",
            "preconditions": ["Design and Interface Control are verified."],
            "target_ids": ["body-main"], "expected_delta": {"bodies_created": 1},
            "do_not_touch": ["existing-components"],
            "rollback": {
                "method": "Undo to the synthetic F3D baseline.",
                "checkpoint_ref": "cad/baseline.f3d", "limitations": [],
            },
            "acceptance_checks": ["Read back body-main."],
            "evidence_required": ["api_readback"], "evidence": [],
            "depends_on": inputs, "produces": [artifact_ref(output)],
        }
    ]
    validate_document(state, expected_kind="run-state")
    return state, design, electrical, interface, review_results


class BundleReachabilityTests(unittest.TestCase):
    def test_frozen_schematic_bundle_is_reachable(self):
        validate_bundle(*build_bundle("schematic"))

    def test_pcb_candidate_bundle_is_reachable(self):
        validate_bundle(*build_bundle("pcb"))

    def test_waiting_evt_bundle_requires_a_verified_plan_bound_to_current_pcb(self):
        bundle = build_bundle("evt")
        validate_bundle(*bundle)
        state, design, electrical, interface, review = copy.deepcopy(bundle)
        evt_record = next(
            item for item in state["artifacts"] if item["artifact_type"] == "evt_plan"
        )
        evt_record["depends_on"][0]["content_hash"] = "sha256:wrong-pcb"
        with self.assertRaisesRegex(ValidationError, "content hash mismatch|bound to the current PCB"):
            validate_bundle(state, design, electrical, interface, review)

    def test_design_freeze_cannot_bypass_review_results(self):
        state, design, electrical, interface, review = build_bundle("schematic")
        with self.assertRaisesRegex(ValidationError, "requires hash-bound review results"):
            validate_bundle(state, design, electrical, interface)
        review["categories"][0].update(
            {
                "status": "fail", "blocking_issue": "Synthetic blocker.",
                "next_action": "Resolve and repeat review.",
            }
        )
        with self.assertRaisesRegex(ValidationError, "continuation gate is blocked"):
            validate_bundle(state, design, electrical, interface, review)

    def test_verified_design_requires_a_must_acceptance_check(self):
        _, design, _, _, _ = build_bundle("schematic")
        design["acceptance_checks"] = []
        with self.assertRaisesRegex(ValidationError, "at least one must acceptance check"):
            validate_document(design, expected_kind="design-pack")

    def test_reserved_lease_rechecks_input_and_output_readiness(self):
        bundle = build_direct_operation_bundle()
        state, design, electrical, interface, review = bundle
        token = authorize_execute_step(
            state, design, electrical, interface,
            "cad-direct-step-001", "attempt-cad-direct-001", review,
        )
        reserved = reserve_execution(state, token)
        authorize_reserved_execute_step(
            reserved, design, electrical, interface,
            "cad-direct-step-001", "attempt-cad-direct-001", review,
        )

        changed_input = copy.deepcopy(reserved)
        next(
            item for item in changed_input["artifacts"]
            if item["artifact_id"] == "scene-snapshot-001"
        )["status"] = "planned"
        with self.assertRaisesRegex(ValidationError, "invalid input dependencies"):
            authorize_reserved_execute_step(
                changed_input, design, electrical, interface,
                "cad-direct-step-001", "attempt-cad-direct-001", review,
            )

        changed_output = copy.deepcopy(reserved)
        output = next(
            item for item in changed_output["artifacts"]
            if item["artifact_id"] == "cad-model-direct-001"
        )
        output["status"] = "implemented-unverified"
        output["evidence"] = [evidence("evidence-output-changed", "api_readback")]
        changed_output["status"] = "implemented-unverified"
        with self.assertRaisesRegex(ValidationError, "outputs"):
            authorize_reserved_execute_step(
                changed_output, design, electrical, interface,
                "cad-direct-step-001", "attempt-cad-direct-001", review,
            )

    def test_verified_artifacts_require_verified_parents_and_matching_provenance(self):
        state = example("run-state.v2.json")
        interface = next(
            item for item in state["artifacts"] if item["artifact_type"] == "interface_control"
        )
        interface["status"] = "verified"
        interface["evidence"] = [evidence("evidence-interface-parent-test")]
        with self.assertRaisesRegex(ValidationError, "unverified dependencies"):
            validate_document(state, expected_kind="run-state")

        mismatch = example("run-state.v2.json")
        mismatch["artifacts"][0]["provenance"]["hash"] = "sha256:different"
        with self.assertRaisesRegex(ValidationError, "provenance hash"):
            validate_document(mismatch, expected_kind="run-state")

    def test_evt_reference_is_forbidden_before_waiting_evt(self):
        electrical = example("electrical-pack.v2.json")
        electrical["pcb"]["evt_plan_ref"] = {
            "artifact_id": "evt-plan-floating", "revision": 1,
            "content_hash": "sha256:floating",
        }
        with self.assertRaisesRegex(ValidationError, "only waiting_evt"):
            validate_document(electrical, expected_kind="electrical-pack")


if __name__ == "__main__":
    unittest.main()
