import copy
import json
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "product-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from manage_run_state import (  # noqa: E402
    record_execution_result, reserve_execution, resolve_pending_decision, resolve_routes,
)
from adapter_contracts import (  # noqa: E402
    ExecutionAuthorization, _issue_execution_authorization,
    canonical_operation_digest, canonical_parameter_digest, document_digest,
)
from validate_bundle import authorize_execute_step, validate_bundle  # noqa: E402
from validate_v2 import (  # noqa: E402
    ValidationError, contract_hash, load_and_validate, validate_document,
)


EXAMPLES = ROOT / "examples" / "v2-orchestrator-demo"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def reliable_evidence(evidence_type="source_export"):
    return {
        "evidence_id": f"evidence-{evidence_type}-test",
        "type": evidence_type,
        "source": "synthetic test export",
        "captured_at": "2026-01-01T00:00:00Z",
        "ref": "sha256:test-evidence",
        "note": "Synthetic reliable evidence fixture.",
    }


class GoldenExampleTests(unittest.TestCase):
    def test_all_four_v2_golden_examples_validate(self):
        names = {
            "design-pack.v2.json": "design-pack",
            "run-state.v2.json": "run-state",
            "electrical-pack.v2.json": "electrical-pack",
            "interface-control.v2.json": "interface-control",
        }
        self.assertEqual({path.name for path in EXAMPLES.glob("*.json")}, set(names))
        for name, kind in names.items():
            validate_document(example(name), expected_kind=kind)

    def test_duplicate_json_keys_are_rejected_before_schema_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schema_version":"2.0","schema_version":"2.0","document_type":"run_state"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationError, "duplicate JSON object key"):
                load_and_validate(path, expected_kind="run-state")

    def test_non_finite_json_numbers_are_rejected_at_load_time(self):
        design = example("design-pack.v2.json")
        design["hard_constraints"][0]["value"] = float("inf")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "non-finite.json"
            path.write_text(json.dumps(design), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "non-finite JSON number"):
                load_and_validate(path, expected_kind="design-pack")

    def test_electrical_reference_root_example_matches_schema(self):
        reference = (
            ROOT / "product-loop" / "references" / "electrical-pack-schema.md"
        ).read_text(encoding="utf-8")
        match = re.search(r"```json\n(.*?)\n```", reference, flags=re.DOTALL)
        self.assertIsNotNone(match)
        validate_document(json.loads(match.group(1)), expected_kind="electrical-pack")


class DecisionAuthorityValidationTests(unittest.TestCase):
    def test_programmatic_non_finite_values_are_rejected_before_hashing(self):
        design = example("design-pack.v2.json")
        design["hard_constraints"][0]["value"] = float("nan")
        with self.assertRaisesRegex(ValidationError, "non-finite JSON number"):
            validate_document(design, expected_kind="design-pack")
        with self.assertRaisesRegex(ValidationError, "cannot hash non-JSON contract value"):
            contract_hash(design)

    def test_contract_hash_excludes_freeze_workflow_metadata_not_design_truth(self):
        design = example("design-pack.v2.json")
        before = contract_hash(design)
        design["status"] = "verified"
        design["freeze_decision_id"] = "decision-design-freeze-001"
        design["evidence"] = [reliable_evidence("screenshot")]
        self.assertEqual(contract_hash(design), before)
        design["product_goal"] = "A changed product goal."
        self.assertNotEqual(contract_hash(design), before)

    def test_route_without_user_decision_is_rejected(self):
        state = example("run-state.v2.json")
        state["track_routes"]["mechanical"] = "direct"
        with self.assertRaisesRegex(ValidationError, "requires a ledger decision"):
            validate_document(state, expected_kind="run-state")

    def test_verified_design_requires_architecture_and_component_decisions(self):
        design = example("design-pack.v2.json")
        design["status"] = "verified"
        design["freeze_decision_id"] = "decision-design-freeze"
        design["evidence"] = [reliable_evidence()]
        with self.assertRaisesRegex(ValidationError, "architecture decision"):
            validate_document(design, expected_kind="design-pack")
        design["architecture_decision_id"] = "decision-design-architecture"
        design["selected_components"] = [
            {
                "id": "selected-synthetic-sensor",
                "module": "sensor",
                "selection": "SYNTH-001",
                "selection_status": "user_confirmed",
                "decision_id": None,
                "why": "Synthetic fixture.",
                "fixed_constraints": "None in synthetic fixture.",
                "unverified": "None in synthetic fixture.",
            }
        ]
        with self.assertRaisesRegex(ValidationError, "missing component decisions"):
            validate_document(design, expected_kind="design-pack")

    def test_resume_cannot_bypass_pending_route_gate(self):
        state = example("run-state.v2.json")
        state["pending_decision_gate"] = None
        state["status"] = "planned"
        with self.assertRaisesRegex(ValidationError, "unresolved tracks require"):
            validate_document(state, expected_kind="run-state")

    def test_unresolved_routes_require_a_route_scoped_pending_gate(self):
        state = example("run-state.v2.json")
        state["pending_decision_gate"]["decision_type"] = "freeze"
        state["pending_decision_gate"]["scope"] = ["artifact:unrelated@1"]
        with self.assertRaisesRegex(ValidationError, "correctly scoped route gate"):
            validate_document(state, expected_kind="run-state")

    def test_dependency_content_hash_must_match_referenced_artifact(self):
        state = example("run-state.v2.json")
        state["artifacts"][1]["depends_on"][0]["content_hash"] = "sha256:wrong"
        with self.assertRaisesRegex(ValidationError, "content hash mismatch"):
            validate_document(state, expected_kind="run-state")

    def test_verified_claim_needs_more_than_user_self_report(self):
        design = example("design-pack.v2.json")
        design["status"] = "verified"
        design["architecture_decision_id"] = "decision-design-architecture"
        design["freeze_decision_id"] = "decision-design-freeze"
        design["evidence"] = [
            {
                "evidence_id": "evidence-user-self-report",
                "type": "user_self_report",
                "source": "user message",
                "captured_at": "2026-01-01T00:00:00Z",
                "ref": None,
                "note": "User said it is done."
            }
        ]
        with self.assertRaisesRegex(ValidationError, "requires api_readback"):
            validate_document(design, expected_kind="design-pack")

    def test_conflicting_geometry_cannot_be_hidden_by_verified_status(self):
        design = example("design-pack.v2.json")
        design["status"] = "verified"
        design["architecture_decision_id"] = "decision-design-architecture"
        design["freeze_decision_id"] = "decision-design-freeze"
        design["evidence"] = [reliable_evidence("screenshot")]
        design["component_envelopes"][0]["source_status"] = "conflict"
        with self.assertRaisesRegex(ValidationError, "envelopes"):
            validate_document(design, expected_kind="design-pack")

    def test_migration_unconfirmed_component_blocks_verified_status(self):
        design = example("design-pack.v2.json")
        design["status"] = "verified"
        design["architecture_decision_id"] = "decision-design-architecture"
        design["freeze_decision_id"] = "decision-design-freeze"
        design["evidence"] = [reliable_evidence()]
        design["selected_components"] = [
            {
                "id": "sc-legacy",
                "module": "controller",
                "selection": "Legacy controller",
                "selection_status": "needs_user_confirmation",
                "decision_id": None,
                "why": "Migrated",
                "fixed_constraints": "Unknown",
                "unverified": "No decision record"
            }
        ]
        with self.assertRaisesRegex(ValidationError, "unresolved selections"):
            validate_document(design, expected_kind="design-pack")


class CapabilityAndOperationTests(unittest.TestCase):
    def complete_routes(self):
        state = example("run-state.v2.json")
        return resolve_routes(
            state,
            {
                "visualization": "skip",
                "mechanical": "direct",
                "schematic": "skip",
                "pcb": "skip",
            },
            "chat-message:all-route-choices",
        )

    def add_mechanical_operation(self, state):
        source = state["artifacts"][0]
        output = copy.deepcopy(source)
        output.update(
            {
                "artifact_id": "cad-model-001",
                "artifact_type": "cad_model",
                "path": "cad/model.f3d",
                "content_hash": "sha256:cad-model-001",
                "depends_on": [
                    {
                        "artifact_id": source["artifact_id"],
                        "revision": source["revision"],
                        "content_hash": source["content_hash"],
                    }
                ],
            }
        )
        output["provenance"]["hash"] = output["content_hash"]
        state["artifacts"].append(output)
        source_ref = {
            "artifact_id": source["artifact_id"],
            "revision": source["revision"],
            "content_hash": source["content_hash"],
        }
        output_ref = {
            "artifact_id": output["artifact_id"],
            "revision": output["revision"],
            "content_hash": output["content_hash"],
        }
        state["operation_cards"] = [
            {
                "step_id": "cad-step-001",
                "goal": "Create one parameterized enclosure body.",
                "track": "mechanical",
                "route": "direct",
                "adapter_id": "fusion-mcp",
                "route_decision_id": state["route_decision_ids"]["mechanical"],
                "authorization_decision_ids": [],
                "ownership": "agent",
                "risk_level": "low",
                "call_id": "call-cad-step-001",
                "attempt_id": "attempt-cad-step-001",
                "parameters": {"width_mm": 70, "height_mm": 45, "depth_mm": 24},
                "parameter_digest": canonical_parameter_digest(
                    {"width_mm": 70, "height_mm": 45, "depth_mm": 24}
                ),
                "status": "planned",
                "required_capabilities": ["cad.create_parametric_body"],
                "execution_capability_id": "cad.create_parametric_body",
                "preconditions": ["Approved mechanical route"],
                "target_ids": ["body-main"],
                "expected_delta": {"bodies_created": 1},
                "do_not_touch": ["existing-components"],
                "rollback": {
                    "method": "undo to F3D baseline",
                    "checkpoint_ref": "baseline.f3d",
                    "limitations": []
                },
                "acceptance_checks": ["Read back body-main"],
                "evidence_required": ["api_readback"],
                "evidence": [],
                "depends_on": [source_ref],
                "produces": [output_ref]
            }
        ]

    def enable_mechanical_capabilities(self, state, capability_ids):
        report = next(
            item for item in state["capability_reports"] if item["track"] == "mechanical"
        )
        report.update(
            {
                "adapter_id": "fusion-mcp",
                "status": "available",
                "checked_at": "2026-01-01T00:00:00Z",
                "tool_schema_digest": "sha256:fusion-schema",
                "capabilities": {
                    "read": True, "write": True, "verify": True,
                    "export": True, "rollback": True, "render": True,
                },
                "operations": [
                    {
                        "capability_id": capability_id,
                        "provider_operation": (
                            "cam_" + capability_id.removeprefix("cad.cam.")
                            if capability_id.startswith("cad.cam.")
                            else capability_id.removeprefix("cad.")
                        ),
                        "risk_class": (
                            "destructive_write"
                            if capability_id.startswith(("cad.execute", "cad.cam.", "cad.delete."))
                            else "reversible_write"
                        ),
                        "status": "available",
                        "schema_digest": f"sha256:{capability_id}-schema",
                        "limitations": [],
                        "route_options_if_unavailable": ["retry", "guided", "handoff", "pause"],
                        "evidence": [
                            {
                                **reliable_evidence("api_readback"),
                                "evidence_id": f"evidence-{capability_id}-available",
                            }
                        ],
                    }
                    for capability_id in capability_ids
                ],
                "units": {"public": "mm", "native": "cm"},
                "evidence": [reliable_evidence("api_readback")],
            }
        )

    def high_risk_decision(self, state, decision_id, capability):
        card = state["operation_cards"][0]
        return {
            "decision_id": decision_id,
            "decision_type": "high_risk_write",
            "scope": [
                f"run:{state['run_id']}", f"step:{card['step_id']}",
                f"call:{card['call_id']}", f"parameters:{card['parameter_digest']}",
                f"attempt:{card['attempt_id']}",
                f"operation:{canonical_operation_digest(card)}",
            ],
            "status": "resolved",
            "question": f"Authorize {capability} for this exact call?",
            "options": [
                {
                    "id": capability, "label": capability,
                    "description": "Authorize this capability once.",
                    "impact": "The exact bound high-risk call may execute.",
                },
                {
                    "id": "reject", "label": "Reject",
                    "description": "Do not execute it.",
                    "impact": "The operation remains blocked.",
                },
            ],
            "recommendation": "reject",
            "recommendation_rationale": "High-risk writes are denied unless explicitly needed.",
            "impact": ["Authorization is bound to one run, step, call, and parameter digest."],
            "selected_option": capability,
            "decided_by": "user",
            "decided_at": "2026-01-01T00:00:00Z",
            "decision_evidence": [
                {
                    "evidence_id": f"evidence-{decision_id}",
                    "type": "user_self_report", "source": "explicit user decision",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "ref": f"approval-record:{decision_id}", "note": "Synthetic approval.",
                }
            ],
            "dependency_revisions": [
                {
                    "artifact_id": item["artifact_id"], "revision": item["revision"],
                    "content_hash": item["content_hash"],
                }
                for item in state["artifacts"]
            ],
        }

    def test_direct_operation_is_blocked_when_mcp_is_not_available(self):
        state = self.complete_routes()
        self.add_mechanical_operation(state)
        with self.assertRaisesRegex(ValidationError, "lacks one available provider binding"):
            validate_document(state, expected_kind="run-state")

    def test_direct_operation_accepts_evidence_backed_capability(self):
        state = self.complete_routes()
        self.add_mechanical_operation(state)
        self.enable_mechanical_capabilities(state, ["cad.create_parametric_body"])
        validate_document(state, expected_kind="run-state")

    def test_direct_card_rejects_empty_checkpoint_and_wrong_ownership(self):
        state = self.complete_routes()
        self.add_mechanical_operation(state)
        self.enable_mechanical_capabilities(state, ["cad.create_parametric_body"])
        state["operation_cards"][0]["rollback"]["checkpoint_ref"] = ""
        with self.assertRaisesRegex(ValidationError, "recovery checkpoint"):
            validate_document(state, expected_kind="run-state")
        state["operation_cards"][0]["rollback"]["checkpoint_ref"] = "baseline.f3d"
        state["operation_cards"][0]["ownership"] = "handoff"
        with self.assertRaisesRegex(ValidationError, "incompatible with route"):
            validate_document(state, expected_kind="run-state")

    def test_operation_card_rejects_multiple_mutating_provider_calls(self):
        state = self.complete_routes()
        self.add_mechanical_operation(state)
        card = state["operation_cards"][0]
        card.update(
            {
                "risk_level": "high",
                "call_id": "call-dangerous-001",
                "attempt_id": "attempt-dangerous-001",
                "parameters": {"code": "synthetic", "setup": "test"},
                "parameter_digest": canonical_parameter_digest(
                    {"code": "synthetic", "setup": "test"}
                ),
                "required_capabilities": ["cad.execute_code", "cad.cam.generate_toolpath"],
                "execution_capability_id": "cad.execute_code",
            }
        )
        self.enable_mechanical_capabilities(state, card["required_capabilities"])
        with self.assertRaisesRegex(ValidationError, "only one mutating provider call"):
            validate_document(state, expected_kind="run-state")

    def test_high_risk_authorization_and_execution_reservation_are_one_time(self):
        state = self.complete_routes()
        self.add_mechanical_operation(state)
        card = state["operation_cards"][0]
        parameters = {"code": "synthetic"}
        card.update(
            {
                "risk_level": "high",
                "call_id": "call-dangerous-001",
                "attempt_id": "attempt-dangerous-001",
                "parameters": parameters,
                "parameter_digest": canonical_parameter_digest(parameters),
                "required_capabilities": ["cad.execute_code"],
                "execution_capability_id": "cad.execute_code",
            }
        )
        self.enable_mechanical_capabilities(state, card["required_capabilities"])
        decision = self.high_risk_decision(
            state, "decision-dangerous-code", "cad.execute_code"
        )
        state["decision_ledger"].append(decision)
        card["authorization_decision_ids"] = [decision["decision_id"]]
        validate_document(state, expected_kind="run-state")

        changed_scope = copy.deepcopy(state)
        changed_card = changed_scope["operation_cards"][0]
        changed_card["target_ids"] = ["all-components"]
        changed_card["expected_delta"] = {"deleted_all": True}
        changed_card["do_not_touch"] = ["nothing"]
        with self.assertRaisesRegex(ValidationError, "per-call authorization"):
            validate_document(changed_scope, expected_kind="run-state")

        duplicate = copy.deepcopy(decision)
        duplicate["decision_id"] = "decision-dangerous-code-duplicate"
        duplicate["decision_evidence"][0]["evidence_id"] = "evidence-dangerous-duplicate"
        duplicate["decision_evidence"][0]["ref"] = "approval-record:dangerous-duplicate"
        state["decision_ledger"].append(duplicate)
        card["authorization_decision_ids"].append(duplicate["decision_id"])
        with self.assertRaisesRegex(ValidationError, "exactly one per-call authorization"):
            validate_document(state, expected_kind="run-state")
        state["decision_ledger"].pop()
        card["authorization_decision_ids"].pop()

        token = _issue_execution_authorization(
            run_id=state["run_id"], step_id=card["step_id"], call_id=card["call_id"],
            attempt_id=card["attempt_id"], parameter_digest=card["parameter_digest"],
            route_decision_id=card["route_decision_id"], adapter_id=card["adapter_id"],
            capability_id="cad.execute_code", provider_operation="execute_code",
            risk_class="destructive_write",
            operation_digest=canonical_operation_digest(card),
            parameters=card["parameters"], target_ids=card["target_ids"],
            input_bindings=[
                f"{item['artifact_id']}@{item['revision']}:{item['content_hash']}"
                for item in card["depends_on"]
            ],
            run_state_digest=document_digest(state), bundle_digest="sha256:test-bundle",
            phase="authorized",
        )
        forged = replace(token, signature="0" * 64)
        with self.assertRaisesRegex(ValidationError, "signature is invalid"):
            reserve_execution(state, forged)
        reserved = reserve_execution(state, token)
        self.assertEqual(reserved["execution_reservations"][0]["status"], "reserved")
        self.assertEqual(reserved["authorization_consumptions"][0]["status"], "reserved")
        missing_consumption = copy.deepcopy(reserved)
        missing_consumption["authorization_consumptions"] = []
        with self.assertRaisesRegex(ValidationError, "requires exactly one authorization consumption"):
            validate_document(missing_consumption, expected_kind="run-state")
        mismatched_consumption = copy.deepcopy(reserved)
        mismatched_consumption["authorization_consumptions"][0]["status"] = "failed"
        mismatched_consumption["authorization_consumptions"][0]["result_fingerprint"] = "sha256:other"
        with self.assertRaisesRegex(ValidationError, "must mirror reservation"):
            validate_document(mismatched_consumption, expected_kind="run-state")
        with self.assertRaisesRegex(ValidationError, "different run-state snapshot"):
            reserve_execution(reserved, token)
        refreshed_token = _issue_execution_authorization(
            run_id=reserved["run_id"], step_id=card["step_id"], call_id=card["call_id"],
            attempt_id=card["attempt_id"], parameter_digest=card["parameter_digest"],
            route_decision_id=card["route_decision_id"], adapter_id=card["adapter_id"],
            capability_id="cad.execute_code", provider_operation="execute_code",
            risk_class="destructive_write", parameters=card["parameters"],
            operation_digest=canonical_operation_digest(card),
            target_ids=card["target_ids"],
            input_bindings=[
                f"{item['artifact_id']}@{item['revision']}:{item['content_hash']}"
                for item in card["depends_on"]
            ],
            run_state_digest=document_digest(reserved), bundle_digest="sha256:test-bundle",
            phase="authorized",
        )
        with self.assertRaisesRegex(ValidationError, "already been reserved"):
            reserve_execution(reserved, refreshed_token)
        completed = record_execution_result(
            reserved, card["step_id"], card["attempt_id"],
            "completed", "sha256:scene-readback-after-call",
        )
        self.assertEqual(completed["execution_reservations"][0]["status"], "completed")
        self.assertEqual(completed["authorization_consumptions"][0]["status"], "completed")

    def test_failed_or_unknown_execution_requires_user_recovery_choice(self):
        def reserved_state():
            state = self.complete_routes()
            self.add_mechanical_operation(state)
            self.enable_mechanical_capabilities(state, ["cad.create_parametric_body"])
            card = state["operation_cards"][0]
            token = _issue_execution_authorization(
                run_id=state["run_id"], step_id=card["step_id"], call_id=card["call_id"],
                attempt_id=card["attempt_id"], parameter_digest=card["parameter_digest"],
                route_decision_id=card["route_decision_id"], adapter_id=card["adapter_id"],
                capability_id="cad.create_parametric_body",
                provider_operation="create_parametric_body", risk_class="reversible_write",
                operation_digest=canonical_operation_digest(card),
                parameters=card["parameters"], target_ids=card["target_ids"],
                input_bindings=[
                    f"{item['artifact_id']}@{item['revision']}:{item['content_hash']}"
                    for item in card["depends_on"]
                ],
                run_state_digest=document_digest(state), bundle_digest="sha256:test-bundle",
                phase="authorized",
            )
            return reserve_execution(state, token), card

        for result_status in ("failed", "unknown"):
            with self.subTest(result_status=result_status):
                reserved, card = reserved_state()
                paused = record_execution_result(
                    reserved, card["step_id"], card["attempt_id"], result_status,
                    f"sha256:{result_status}-readback",
                )
                self.assertEqual(paused["status"], "waiting_user_decision")
                self.assertEqual(
                    paused["operation_cards"][0]["status"], "waiting_user_decision"
                )
                self.assertEqual(paused["pending_decision_gate"]["decision_type"], "route_change")
                self.assertIn(
                    "retry",
                    {item["id"] for item in paused["pending_decision_gate"]["options"]},
                )
                with self.assertRaisesRegex(ValidationError, "paused or invalid"):
                    refreshed = _issue_execution_authorization(
                        run_id=paused["run_id"], step_id=card["step_id"],
                        call_id=card["call_id"], attempt_id=card["attempt_id"],
                        parameter_digest=card["parameter_digest"],
                        route_decision_id=card["route_decision_id"], adapter_id=card["adapter_id"],
                        capability_id="cad.create_parametric_body",
                        provider_operation="create_parametric_body", risk_class="reversible_write",
                        operation_digest=canonical_operation_digest(card),
                        parameters=card["parameters"], target_ids=card["target_ids"],
                        input_bindings=[], run_state_digest=document_digest(paused),
                        bundle_digest="sha256:test-bundle", phase="authorized",
                    )
                    reserve_execution(paused, refreshed)

        paused, card = reserved_state()
        paused = record_execution_result(
            paused, card["step_id"], card["attempt_id"], "unknown",
            "sha256:unknown-route-change",
        )
        changed = resolve_pending_decision(
            paused, "guided", "approval-record:recovery-guided-001"
        )
        self.assertEqual(changed["track_routes"]["mechanical"], "guided")
        self.assertEqual(changed["operation_cards"][0]["route"], "direct")
        self.assertEqual(changed["operation_cards"][0]["status"], "stale")
        validate_document(changed, expected_kind="run-state")

    def test_available_capability_without_evidence_is_rejected(self):
        state = example("run-state.v2.json")
        report = state["capability_reports"][0]
        report["status"] = "available"
        report["checked_at"] = "2026-01-01T00:00:00Z"
        report["tool_schema_digest"] = "sha256:visualization-schema"
        report["evidence"] = []
        with self.assertRaisesRegex(ValidationError, "reliable evidence"):
            validate_document(state, expected_kind="run-state")

    def test_dangerous_provider_operation_cannot_be_downclassified(self):
        for provider_operation in (
            "delete_component", "deleteComponent", "executeCode", "removeFeature",
            "wipe_all", "erase_body", "reset_scene",
        ):
            with self.subTest(provider_operation=provider_operation):
                state = self.complete_routes()
                self.add_mechanical_operation(state)
                card = state["operation_cards"][0]
                capability = f"cad.tool.{provider_operation}"
                card["required_capabilities"] = [capability]
                card["execution_capability_id"] = capability
                self.enable_mechanical_capabilities(state, card["required_capabilities"])
                report_operation = next(
                    report for report in state["capability_reports"]
                    if report["track"] == "mechanical"
                )["operations"][0]
                report_operation["provider_operation"] = provider_operation
                with self.assertRaisesRegex(ValidationError, "classified destructive_write"):
                    validate_document(state, expected_kind="run-state")

    def test_verified_run_cannot_hide_non_skip_track_without_operations(self):
        state = resolve_routes(
            example("run-state.v2.json"),
            {
                "visualization": "skip",
                "mechanical": "direct",
                "schematic": "skip",
                "pcb": "skip",
            },
            "chat-message:verified-run-routes",
        )
        state["status"] = "verified"
        for item in state["artifacts"]:
            item["status"] = "verified"
            item["evidence"] = [
                {
                    **reliable_evidence(),
                    "evidence_id": f"evidence-{item['artifact_id']}-verified"
                }
            ]
        with self.assertRaisesRegex(ValidationError, "uncovered tracks"):
            validate_document(state, expected_kind="run-state")


class CrossDomainStateTests(unittest.TestCase):
    def test_verified_cross_domain_check_requires_all_five_groups_to_match(self):
        state = example("run-state.v2.json")
        design = next(
            item for item in state["artifacts"] if item["artifact_type"] == "design_pack"
        )
        design["status"] = "verified"
        design["evidence"] = [
            {**reliable_evidence("source_export"), "evidence_id": "evidence-design-verified"}
        ]
        interface = next(
            item for item in state["artifacts"] if item["artifact_type"] == "interface_control"
        )
        interface["status"] = "verified"
        interface["evidence"] = [
            {**reliable_evidence("source_export"), "evidence_id": "evidence-interface-verified"}
        ]
        pcb = {
            "artifact_id": "pcb-cross-check-001", "artifact_type": "pcb", "revision": 1,
            "status": "verified", "path": "pcb/candidate.json",
            "content_hash": "sha256:pcb-cross-check-001", "source_hashes": {},
            "provenance": {
                "source": "synthetic PCB export", "producer": "unit test",
                "time": "2026-01-01T00:00:00Z", "hash": "sha256:pcb-cross-check-001",
            },
            "evidence": [
                {**reliable_evidence("source_export"), "evidence_id": "evidence-pcb-verified"}
            ],
            "depends_on": [
                {
                    "artifact_id": interface["artifact_id"], "revision": interface["revision"],
                    "content_hash": interface["content_hash"],
                }
            ],
            "invalidation_reasons": [],
        }
        state["artifacts"].append(pcb)
        state["cross_domain_checks"] = [
            {
                "check_id": "cross-check-001", "status": "verified",
                "interface_ref": {
                    "artifact_id": interface["artifact_id"], "revision": interface["revision"],
                    "content_hash": interface["content_hash"],
                },
                "cad_ref": None,
                "pcb_ref": {
                    "artifact_id": pcb["artifact_id"], "revision": pcb["revision"],
                    "content_hash": pcb["content_hash"],
                },
                "groups": {
                    "pcb_thickness": "match", "mounting_holes": "match",
                    "connectors": "match", "height_zones": "mismatch",
                    "antenna_keepouts": "match",
                },
                "evidence": [
                    {**reliable_evidence("api_readback"), "evidence_id": "evidence-cross-check"}
                ],
            }
        ]
        with self.assertRaisesRegex(ValidationError, "unmatched groups"):
            validate_document(state, expected_kind="run-state")
        state["cross_domain_checks"][0]["groups"]["height_zones"] = "match"
        validate_document(state, expected_kind="run-state")


class ElectricalValidationTests(unittest.TestCase):
    def test_reliable_evidence_reference_cannot_be_null(self):
        electrical = example("electrical-pack.v2.json")
        electrical["evidence"] = [
            {
                **reliable_evidence("screenshot"),
                "evidence_id": "evidence-null-ref",
                "ref": None,
            }
        ]
        electrical["net_contracts"] = [
            {
                "id": "net-power", "name": "VCC", "net_class": "power",
                "expected_endpoints": ["J1.1", "U1.VCC"],
                "actual_endpoints": ["J1.1", "U1.VCC"],
                "allow_branches": False, "layout_constraints": [],
                "compare_status": "match", "evidence_refs": ["evidence-null-ref"],
            }
        ]
        with self.assertRaisesRegex(ValidationError, "unreliable evidence"):
            validate_document(electrical, expected_kind="electrical-pack")
    def test_swapped_d_plus_d_minus_endpoint_claim_is_rejected(self):
        electrical = example("electrical-pack.v2.json")
        electrical["net_contracts"] = [
            {
                "id": "net-usb-dp",
                "name": "USB_DP",
                "net_class": "differential_signal",
                "expected_endpoints": ["J1.A6", "U1.DP"],
                "actual_endpoints": ["J1.A7", "U1.DM"],
                "allow_branches": False,
                "layout_constraints": ["Pair with USB_DM"],
                "compare_status": "match",
                "evidence_refs": ["api-net-readback"]
            }
        ]
        with self.assertRaisesRegex(ValidationError, "contradicts endpoint sets"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_incomplete_pin_pad_mapping_is_rejected(self):
        electrical = example("electrical-pack.v2.json")
        electrical["selected_devices"] = [
            {
                "id": "device-j1",
                "role": "connector",
                "manufacturer_part": "Synthetic connector",
                "selection_status": "user_confirmed",
                "electrical_constraints": [],
                "package_requirement": "2-pad footprint",
                "decision_id": "decision-device-j1",
                "source_refs": ["decision-device-j1"]
            }
        ]
        electrical["component_bindings"] = [
            {
                "id": "binding-j1",
                "refdes": "J1",
                "device_id": "device-j1",
                "symbol_pins": ["1", "2"],
                "footprint": {
                    "id": "fp-j1",
                    "version": "1",
                    "pads": ["1", "2"],
                    "pin1_marker": "triangle"
                },
                "pin_pad_map": [{"symbol_pin": "1", "pcb_pad": "1"}],
                "polarity": "not_applicable",
                "fpc_orientation": None,
                "status": "provisional",
                "decision_id": None,
                "evidence_refs": []
            }
        ]
        with self.assertRaisesRegex(ValidationError, "incomplete"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_unknown_pin1_or_fpc_blocks_confirmed_binding(self):
        electrical = example("electrical-pack.v2.json")
        electrical["selected_devices"] = [
            {
                "id": "device-fpc",
                "role": "fpc connector",
                "manufacturer_part": "Synthetic FPC",
                "selection_status": "user_confirmed",
                "electrical_constraints": [],
                "package_requirement": "Verified orientation",
                "decision_id": "decision-device-fpc",
                "source_refs": ["decision-fpc"]
            }
        ]
        electrical["component_bindings"] = [
            {
                "id": "binding-fpc",
                "refdes": "J1",
                "device_id": "device-fpc",
                "symbol_pins": ["1"],
                "footprint": {"id": "fp-fpc", "version": "1", "pads": ["1"], "pin1_marker": None},
                "pin_pad_map": [{"symbol_pin": "1", "pcb_pad": "1"}],
                "polarity": "confirmed",
                "fpc_orientation": {
                    "contact_side": "unknown",
                    "insertion_direction": "rear",
                    "pin1_direction": "left"
                },
                "status": "confirmed",
                "decision_id": "decision-binding-fpc",
                "evidence_refs": ["photo-fpc"]
            }
        ]
        with self.assertRaisesRegex(ValidationError, "lacks version, orientation"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_confirmed_fpc_binding_requires_explicit_orientation(self):
        electrical = example("electrical-pack.v2.json")
        electrical["evidence"] = [
            {
                **reliable_evidence("source_export"),
                "evidence_id": "evidence-fpc-binding",
            }
        ]
        electrical["selected_devices"] = [
            {
                "id": "device-fpc", "role": "FPC connector",
                "manufacturer_part": "Synthetic FPC", "selection_status": "user_confirmed",
                "electrical_constraints": [], "package_requirement": "0.5 mm FFC/FPC",
                "decision_id": "decision-device-fpc", "source_refs": ["decision-device-fpc"],
            }
        ]
        electrical["component_bindings"] = [
            {
                "id": "binding-fpc", "refdes": "J1", "device_id": "device-fpc",
                "symbol_pins": ["1"],
                "footprint": {
                    "id": "fp-fpc", "version": "1", "pads": ["1"],
                    "pin1_marker": "triangle",
                },
                "pin_pad_map": [{"symbol_pin": "1", "pcb_pad": "1"}],
                "polarity": "confirmed", "fpc_orientation": None,
                "status": "confirmed", "decision_id": "decision-binding-fpc",
                "evidence_refs": ["evidence-fpc-binding"],
            }
        ]
        with self.assertRaisesRegex(ValidationError, "lacks version, orientation"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_pass_result_must_supply_every_required_evidence_type(self):
        electrical = example("electrical-pack.v2.json")
        electrical["evidence"] = [
            {
                **reliable_evidence("screenshot"),
                "evidence_id": "evidence-only-screenshot",
            }
        ]
        electrical["verification_requirements"] = [
            {
                "id": "verify-net-readback", "stage": "schematic_freeze",
                "method": "Read back the critical net.", "pass_condition": "Endpoints match.",
                "priority": "must", "evidence_required": ["api_readback"],
            }
        ]
        electrical["verification_results"] = [
            {
                "id": "result-net-readback", "requirement_id": "verify-net-readback",
                "status": "pass", "evidence_refs": ["evidence-only-screenshot"],
            }
        ]
        with self.assertRaisesRegex(ValidationError, "lacks required evidence types"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_open_item_resolution_requires_user_decision_and_waiver_permission(self):
        electrical = example("electrical-pack.v2.json")
        electrical["open_items"] = [
            {
                "id": "open-connector", "question": "Which connector orientation?",
                "status": "resolved", "blocking_stage": "schematic_freeze",
                "impact": "Changes pin and opening orientation.", "waivable": False,
                "decision_id": None,
            }
        ]
        with self.assertRaisesRegex(ValidationError, "requires a user decision"):
            validate_document(electrical, expected_kind="electrical-pack")

        electrical["open_items"][0].update(
            {
                "status": "accepted_provisional",
                "decision_id": "decision-open-connector",
            }
        )
        with self.assertRaisesRegex(ValidationError, "non-waivable"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_frozen_schematic_cannot_vacuously_accept_empty_contracts(self):
        electrical = example("electrical-pack.v2.json")
        electrical["evidence"] = [
            {
                **reliable_evidence("source_export"),
                "evidence_id": "evidence-schematic-source",
            },
            {
                **reliable_evidence("screenshot"),
                "evidence_id": "evidence-schematic-drc",
            },
        ]
        electrical["schematic"].update(
            {
                "artifact_id": "schematic-empty", "revision": 1, "status": "frozen",
                "freeze_decision_id": "decision-freeze-empty",
                "source_hash": "sha256:empty-schematic",
                "strict_drc": {
                    "ruleset_ref": "strict", "fatal": 0, "error": 0, "warning": 0,
                    "exemptions": [], "evidence_refs": ["evidence-schematic-drc"],
                },
                "critical_net_result_ids": [], "library_revisions": [],
                "evidence_refs": ["evidence-schematic-source"],
            }
        )
        with self.assertRaisesRegex(ValidationError, "requires electrical requirements"):
            validate_document(electrical, expected_kind="electrical-pack")

    def test_pcb_candidate_requires_frozen_schematic_and_zero_drc(self):
        electrical = example("electrical-pack.v2.json")
        electrical["evidence"] = [
            {
                **reliable_evidence("source_export"),
                "evidence_id": "pcb-source-export"
            },
            {
                **reliable_evidence("screenshot"),
                "evidence_id": "pcb-drc"
            }
        ]
        electrical["pcb"].update(
            {
                "status": "pcb_candidate",
                "candidate_decision_id": "decision-pcb-candidate",
                "source_hash": "sha256:pcb",
                "schematic_source_hash": "sha256:schematic",
                "board_constraint_ref": {
                    "artifact_id": "interface-control-demo-001",
                    "revision": 1,
                    "content_hash": "sha256:demo-interface-control-v1"
                },
                "layer_count": 2,
                "layer_count_decision_id": "decision-pcb-layers",
                "stackup_source": "synthetic-stackup",
                "stackup_decision_id": "decision-pcb-stackup",
                "evt_plan_ref": None,
                "evidence_refs": ["pcb-source-export"],
                "drc": {
                    "ruleset_ref": "strict",
                    "fatal": 0,
                    "error": 0,
                    "warning": 1,
                    "exemptions": [],
                    "evidence_refs": ["pcb-drc"]
                }
            }
        )
        with self.assertRaisesRegex(ValidationError, "frozen schematic|zero fatal"):
            validate_document(electrical, expected_kind="electrical-pack")


class InterfaceValidationTests(unittest.TestCase):
    def test_verified_interface_requires_complete_height_and_geometry_values(self):
        interface = example("interface-control.v2.json")
        interface["status"] = "verified"
        interface["freeze_decision_id"] = "decision-interface-freeze"
        interface["evidence"] = [reliable_evidence()]
        interface["pcb"]["status"] = "confirmed"
        interface["pcb"]["outline_points_mm"] = [
            [5, 5, 3], [65, 5, 3], [65, 40, 3], [5, 40, 3]
        ]
        interface["pcb"]["board_origin_mm"] = [5, 5, 3]
        interface["pcb"]["thickness_mm"] = 1.6
        interface["pcb"]["source_refs"] = ["decision-pcb-geometry"]
        interface["height_zones"] = [
            {
                "id": "height-zone-1",
                "pose": {"position_mm": [0, 0, 0], "rotation_deg": [0, 0, 0]},
                "size_mm": [20, 20, 8],
                "side": "top",
                "max_height_mm": None,
                "status": "confirmed",
                "source_refs": ["decision-height-zone"]
            }
        ]
        with self.assertRaisesRegex(ValidationError, "complete canonical values|height limits"):
            validate_document(interface, expected_kind="interface-control")

    def test_missing_and_conflict_geometry_do_not_require_fake_coordinates(self):
        interface = example("interface-control.v2.json")
        validate_document(interface, expected_kind="interface-control")

        fabricated = copy.deepcopy(interface)
        fabricated["pcb"]["outline_points_mm"] = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
        with self.assertRaisesRegex(ValidationError, "must not contain canonical values"):
            validate_document(fabricated, expected_kind="interface-control")

        assumed = copy.deepcopy(interface)
        assumed["pcb"]["status"] = "assumed"
        assumed["pcb"]["source_refs"] = ["assumption-record:pcb-envelope"]
        with self.assertRaisesRegex(ValidationError, "requires complete canonical values"):
            validate_document(assumed, expected_kind="interface-control")

        conflict = copy.deepcopy(interface)
        conflict["pcb"]["status"] = "conflict"
        conflict["pcb"]["source_refs"] = ["source:mechanical", "source:electrical"]
        validate_document(conflict, expected_kind="interface-control")


class BundleValidationTests(unittest.TestCase):
    def test_zero_provider_planning_bundle_remains_valid_after_user_routes(self):
        run_state = example("run-state.v2.json")
        for report in run_state["capability_reports"]:
            report["adapter_id"] = "none"
            report["status"] = "unavailable"
            report["limitations"] = ["No optional provider is installed."]
        run_state = resolve_routes(
            run_state,
            {
                "visualization": "skip",
                "mechanical": "spec",
                "schematic": "handoff",
                "pcb": "handoff",
            },
            "chat-message:zero-provider-routes",
        )
        validate_bundle(
            run_state,
            example("design-pack.v2.json"),
            example("electrical-pack.v2.json"),
            example("interface-control.v2.json"),
        )
        self.assertEqual(run_state["status"], "planned")
        self.assertEqual(run_state["operation_cards"], [])
        self.assertEqual(run_state["execution_reservations"], [])
        self.assertTrue(
            all(report["status"] == "unavailable" for report in run_state["capability_reports"])
        )

    def test_execution_gateway_rejects_pending_decision_before_card_lookup(self):
        with self.assertRaisesRegex(ValidationError, "user decision is pending"):
            authorize_execute_step(
                example("run-state.v2.json"),
                example("design-pack.v2.json"),
                example("electrical-pack.v2.json"),
                example("interface-control.v2.json"),
                "nonexistent-step",
                "attempt-001",
            )

    def test_mechanical_operation_cannot_start_before_design_and_interface_freeze(self):
        run_state = resolve_routes(
            example("run-state.v2.json"),
            {
                "visualization": "skip", "mechanical": "guided",
                "schematic": "skip", "pcb": "skip",
            },
            "chat-message:mechanical-guided-route",
        )
        design = example("design-pack.v2.json")
        interface = example("interface-control.v2.json")
        source_refs = []
        for document in (design, interface):
            source_refs.append(
                {
                    "artifact_id": document["artifact_id"],
                    "revision": document["revision"],
                    "content_hash": contract_hash(document),
                }
            )
        output = {
            "artifact_id": "cad-guided-output-001",
            "artifact_type": "cad_model",
            "revision": 1,
            "status": "planned",
            "path": "cad/guided-output.f3d",
            "content_hash": "sha256:cad-guided-output-001",
            "source_hashes": {},
            "provenance": {
                "source": "synthetic operation", "producer": "unit test",
                "time": None, "hash": "sha256:cad-guided-output-001",
            },
            "evidence": [],
            "depends_on": copy.deepcopy(source_refs),
            "invalidation_reasons": [],
        }
        run_state["artifacts"].append(output)
        run_state["operation_cards"] = [
            {
                "step_id": "cad-guided-step-001",
                "goal": "Guide one enclosure operation.",
                "track": "mechanical", "route": "guided", "adapter_id": None,
                "route_decision_id": run_state["route_decision_ids"]["mechanical"],
                "authorization_decision_ids": [], "ownership": "user",
                "risk_level": "low", "call_id": "call-guided-001",
                "attempt_id": "attempt-guided-001",
                "parameters": {"width_mm": 70},
                "parameter_digest": canonical_parameter_digest({"width_mm": 70}),
                "status": "planned", "required_capabilities": [],
                "execution_capability_id": None,
                "preconditions": ["Design and interface freeze"],
                "target_ids": ["body-main"], "expected_delta": {"bodies_created": 1},
                "do_not_touch": ["PCB envelope"],
                "rollback": {"method": "Undo", "checkpoint_ref": None, "limitations": []},
                "acceptance_checks": ["Screenshot body-main"],
                "evidence_required": ["screenshot"], "evidence": [],
                "depends_on": source_refs,
                "produces": [
                    {
                        "artifact_id": output["artifact_id"], "revision": 1,
                        "content_hash": output["content_hash"],
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(ValidationError, "requires frozen Design Pack"):
            validate_bundle(
                run_state, design, example("electrical-pack.v2.json"), interface
            )

    def test_golden_bundle_validates(self):
        validate_bundle(
            example("run-state.v2.json"),
            example("design-pack.v2.json"),
            example("electrical-pack.v2.json"),
            example("interface-control.v2.json"),
        )

    def test_fake_interface_freeze_id_is_rejected_without_run_decision(self):
        from tests.test_bundle_reachability import build_bundle

        run_state, design, electrical, interface, review_results = build_bundle("schematic")
        interface["freeze_decision_id"] = "decision-does-not-exist"

        with self.assertRaisesRegex(ValidationError, "unknown user decision"):
            validate_bundle(
                run_state, design, electrical, interface, review_results,
            )


if __name__ == "__main__":
    unittest.main()
