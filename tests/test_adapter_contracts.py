import unittest
from itertools import count

from test_helpers import load_script


contracts = load_script("adapter_contracts")
TOKEN_COUNTER = count(1)


def execution_token(
    step_id, call_id, attempt_id, parameter_digest, adapter_id="fusion-mcp",
    capability_id="cad.tool.create_sketch", provider_operation="create_sketch",
    risk_class="reversible_write", parameters=None, phase="reserved",
):
    return contracts._issue_execution_authorization(
        run_id="run-1",
        step_id=step_id,
        call_id=call_id,
        attempt_id=attempt_id,
        parameter_digest=parameter_digest,
        route_decision_id="decision-route-001",
        adapter_id=adapter_id,
        capability_id=capability_id,
        provider_operation=provider_operation,
        risk_class=risk_class,
        operation_digest="sha256:synthetic-operation",
        parameters=parameters or {"synthetic": True},
        target_ids=("synthetic-target",),
        input_bindings=("synthetic@1:sha256:input",),
        run_state_digest="sha256:synthetic-state",
        bundle_digest="sha256:synthetic-bundle",
        phase=phase,
        reservation_id=(
            f"reservation-synthetic-{next(TOKEN_COUNTER)}" if phase == "reserved" else ""
        ),
    )


def reserved_consumption(
    decision_id, step_id, call_id, attempt_id, parameter_digest, capability_id
):
    return {
        "decision_id": decision_id, "run_id": "run-1", "step_id": step_id,
        "call_id": call_id, "attempt_id": attempt_id,
        "parameter_digest": parameter_digest, "capability_id": capability_id,
        "operation_digest": "sha256:synthetic-operation",
        "status": "reserved",
    }


class UnitBoundaryTests(unittest.TestCase):
    def test_fusion_mm_cm_roundtrip(self):
        for value in (0, 1, 12.5, 240):
            self.assertAlmostEqual(
                contracts.fusion_cm_to_mm(contracts.fusion_mm_to_cm(value)),
                value,
            )

    def test_easyeda_unit_roundtrips(self):
        for value in (0.0254, 1, 10, 42.7):
            self.assertAlmostEqual(
                contracts.pcb_mil_to_mm(contracts.pcb_mm_to_mil(value)),
                value,
            )
            self.assertAlmostEqual(
                contracts.schematic_native_to_mm(
                    contracts.schematic_mm_to_native(value)
                ),
                value,
            )

    def test_ten_x_scale_anomaly_is_blocked(self):
        self.assertTrue(contracts.has_order_of_magnitude_error(10, 100))
        self.assertTrue(contracts.has_order_of_magnitude_error(10, 1))
        self.assertFalse(contracts.has_order_of_magnitude_error(10, 10.02))


class FusionRecoveryTests(unittest.TestCase):
    def test_dangerous_tools_need_exact_authorization(self):
        with self.assertRaisesRegex(contracts.ContractError, "validated bundle"):
            contracts.guard_fusion_tool("execute_code")
        decision = {
            "decision_id": "decision-dangerous-1",
            "decision_type": "high_risk_write",
            "scope": [
                "run:run-1", "step:cad-step-1", "call:call-1",
                "attempt:attempt-1",
                "parameters:" + contracts.canonical_parameter_digest({"code": "x=1"}),
                "operation:sha256:synthetic-operation",
            ],
            "status": "resolved",
            "selected_option": "cad.execute_code",
            "decided_by": "user",
            "decision_evidence": [
                {"type": "user_self_report", "ref": "chat-message:dangerous-approval"}
            ],
        }
        contracts.guard_fusion_tool(
            "execute_code",
            run_id="run-1", step_id="cad-step-1", call_id="call-1",
            attempt_id="attempt-1", parameters={"code": "x=1"},
            parameter_digest=contracts.canonical_parameter_digest({"code": "x=1"}),
            authorization_decision_ids={"decision-dangerous-1"},
            decision_ledger=[decision],
            authorization_consumptions=[
                reserved_consumption(
                    "decision-dangerous-1", "cad-step-1", "call-1", "attempt-1",
                    contracts.canonical_parameter_digest({"code": "x=1"}),
                    "cad.execute_code",
                )
            ],
            tool_classification="destructive_write", target_ids=("synthetic-target",),
            execution_authorization=execution_token(
                "cad-step-1", "call-1", "attempt-1",
                contracts.canonical_parameter_digest({"code": "x=1"}),
                capability_id="cad.execute_code", provider_operation="execute_code",
                risk_class="destructive_write",
                parameters={"code": "x=1"},
            ),
        )
        with self.assertRaisesRegex(contracts.ContractError, "separate user authorization"):
            contracts.guard_fusion_tool(
                "execute_code",
                run_id="run-1", step_id="cad-step-1", call_id="call-1",
                attempt_id="attempt-1", parameters={"code": "x=1"},
                parameter_digest=contracts.canonical_parameter_digest({"code": "x=1"}),
                authorization_decision_ids={"decision-dangerous-1"},
                decision_ledger=[decision],
                authorization_consumptions=[{"decision_id": "decision-dangerous-1"}],
                tool_classification="destructive_write", target_ids=("synthetic-target",),
                execution_authorization=execution_token(
                    "cad-step-1", "call-1", "attempt-1",
                    contracts.canonical_parameter_digest({"code": "x=1"}),
                    capability_id="cad.execute_code", provider_operation="execute_code",
                    risk_class="destructive_write",
                    parameters={"code": "x=1"},
                ),
            )
        with self.assertRaisesRegex(contracts.ContractError, "validated bundle"):
            contracts.guard_fusion_tool("cam_generate_toolpath")
        with self.assertRaisesRegex(contracts.ContractError, "validated bundle"):
            contracts.guard_fusion_tool("create_sketch")
        sketch_digest = contracts.canonical_parameter_digest({"plane": "XY"})
        contracts.guard_fusion_tool(
            "create_sketch",
            run_id="run-1", step_id="cad-step-safe", call_id="call-safe",
            attempt_id="attempt-safe", parameters={"plane": "XY"},
            parameter_digest=sketch_digest,
            tool_classification="reversible_write", target_ids=("synthetic-target",),
            execution_authorization=execution_token(
                "cad-step-safe", "call-safe", "attempt-safe", sketch_digest,
                parameters={"plane": "XY"},
            ),
        )
        with self.assertRaisesRegex(contracts.ContractError, "target IDs do not match"):
            contracts.guard_fusion_tool(
                "create_sketch",
                run_id="run-1", step_id="cad-step-target", call_id="call-target",
                attempt_id="attempt-target", parameters={"plane": "XY"},
                parameter_digest=sketch_digest,
                tool_classification="reversible_write", target_ids=("other-target",),
                execution_authorization=execution_token(
                    "cad-step-target", "call-target", "attempt-target", sketch_digest,
                    parameters={"plane": "XY"},
                ),
            )
        with self.assertRaisesRegex(contracts.ContractError, "not the provider operation"):
            contracts.guard_fusion_tool(
                "extrude_profile",
                run_id="run-1", step_id="cad-step-safe", call_id="call-safe",
                attempt_id="attempt-safe", parameters={"plane": "XY"},
                parameter_digest=sketch_digest, tool_classification="reversible_write",
                target_ids=("synthetic-target",),
                execution_authorization=execution_token(
                    "cad-step-safe", "call-safe", "attempt-safe", sketch_digest,
                    parameters={"plane": "XY"},
                ),
            )
        with self.assertRaisesRegex(contracts.ContractError, "authorized digest"):
            contracts.guard_fusion_tool(
                "execute_code", run_id="run-1", step_id="cad-step-1", call_id="call-1",
                attempt_id="attempt-1", parameters={"code": "x=2"},
                parameter_digest=contracts.canonical_parameter_digest({"code": "x=1"}),
                authorization_decision_ids={"decision-dangerous-1"}, decision_ledger=[decision],
                tool_classification="destructive_write", target_ids=("synthetic-target",),
                execution_authorization=execution_token(
                    "cad-step-1", "call-1", "attempt-1",
                    contracts.canonical_parameter_digest({"code": "x=1"}),
                    capability_id="cad.execute_code", provider_operation="execute_code",
                    risk_class="destructive_write",
                    parameters={"code": "x=1"},
                ),
            )
        for tool_name in (
            "delete_component", "deleteComponent", "delete_body", "remove_feature",
            "fusion_delete_all",
        ):
            parameters = {"target": "synthetic-object"}
            digest = contracts.canonical_parameter_digest(parameters)
            with self.assertRaisesRegex(contracts.ContractError, "separate user authorization"):
                contracts.guard_fusion_tool(
                    tool_name, run_id="run-1", step_id="delete-step", call_id="delete-call",
                    attempt_id="delete-attempt", parameters=parameters,
                    parameter_digest=digest,
                    tool_classification="reversible_write", target_ids=("synthetic-target",),
                    execution_authorization=execution_token(
                        "delete-step", "delete-call", "delete-attempt", digest,
                        capability_id=contracts.fusion_capability_id(tool_name),
                        provider_operation=tool_name,
                        parameters=parameters,
                    ),
                )

    def test_export_outside_artifact_root_needs_exact_authorization(self):
        safe_parameters = {
            "format": "f3d", "output_path": "models/a.f3d",
            "artifact_root": "/tmp/artifacts",
        }
        safe_digest = contracts.canonical_parameter_digest(safe_parameters)
        contracts.guard_fusion_tool(
            "export_f3d", run_id="run-1", step_id="export-safe", call_id="call-safe",
            attempt_id="attempt-safe", parameters=safe_parameters,
            parameter_digest=safe_digest,
            tool_classification="export", target_ids=("synthetic-target",),
            output_path="models/a.f3d", artifact_root="/tmp/artifacts",
            execution_authorization=execution_token(
                "export-safe", "call-safe", "attempt-safe", safe_digest,
                capability_id="cad.export.f3d", provider_operation="export_f3d",
                risk_class="export",
                parameters=safe_parameters,
            ),
        )

        alias_parameters = {
            "format": "f3d", "output_path": "/tmp/outside/alias.f3d",
            "artifact_root": "/tmp/artifacts",
        }
        alias_digest = contracts.canonical_parameter_digest(alias_parameters)
        with self.assertRaisesRegex(contracts.ContractError, "separate user authorization"):
            contracts.guard_fusion_tool(
                "saveAs", run_id="run-1", step_id="export-alias", call_id="call-alias",
                attempt_id="attempt-alias", parameters=alias_parameters,
                parameter_digest=alias_digest, tool_classification="export",
                target_ids=("synthetic-target",),
                execution_authorization=execution_token(
                    "export-alias", "call-alias", "attempt-alias", alias_digest,
                    capability_id="cad.export.f3d", provider_operation="saveAs",
                    risk_class="export", parameters=alias_parameters,
                ),
            )
        with self.assertRaisesRegex(contracts.ContractError, "output_path is not bound"):
            contracts.guard_fusion_tool(
                "saveAs", run_id="run-1", step_id="export-alias-2", call_id="call-alias-2",
                attempt_id="attempt-alias-2", parameters=alias_parameters,
                parameter_digest=alias_digest, tool_classification="export",
                target_ids=("synthetic-target",),
                output_path="models/redirected.f3d",
                execution_authorization=execution_token(
                    "export-alias-2", "call-alias-2", "attempt-alias-2", alias_digest,
                    capability_id="cad.export.f3d", provider_operation="saveAs",
                    risk_class="export", parameters=alias_parameters,
                ),
            )
        outside_parameters = {
            "format": "f3d", "output_path": "/tmp/outside/a.f3d",
            "artifact_root": "/tmp/artifacts",
        }
        outside_digest = contracts.canonical_parameter_digest(outside_parameters)
        with self.assertRaisesRegex(contracts.ContractError, "separate user authorization"):
            contracts.guard_fusion_tool(
                "export_f3d", run_id="run-1", step_id="cad-step-2", call_id="call-2",
                attempt_id="attempt-2", parameters=outside_parameters,
                parameter_digest=outside_digest,
                tool_classification="export", target_ids=("synthetic-target",),
                output_path="/tmp/outside/a.f3d", artifact_root="/tmp/artifacts",
                execution_authorization=execution_token(
                    "cad-step-2", "call-2", "attempt-2", outside_digest,
                    capability_id="cad.export.f3d", provider_operation="export_f3d",
                    risk_class="export",
                    parameters=outside_parameters,
                ),
            )
        decision = {
            "decision_id": "decision-external-export-1",
            "decision_type": "high_risk_write",
            "scope": [
                "run:run-1", "step:cad-step-2", "call:call-2",
                "attempt:attempt-2",
                "parameters:" + outside_digest,
                "operation:sha256:synthetic-operation",
                "output:" + contracts._resolved_export_path(
                    "/tmp/outside/a.f3d", "/tmp/artifacts"
                ),
            ],
            "status": "resolved",
            "selected_option": "cad.export.f3d",
            "decided_by": "user",
            "decision_evidence": [
                {"type": "user_self_report", "ref": "chat-message:external-export-approval"}
            ],
        }
        contracts.guard_fusion_tool(
            "export_f3d", run_id="run-1", step_id="cad-step-2", call_id="call-2",
            attempt_id="attempt-2", parameters=outside_parameters,
            parameter_digest=outside_digest,
            tool_classification="export", target_ids=("synthetic-target",),
            authorization_decision_ids={"decision-external-export-1"}, decision_ledger=[decision],
            authorization_consumptions=[
                reserved_consumption(
                    "decision-external-export-1", "cad-step-2", "call-2", "attempt-2",
                    outside_digest, "cad.export.f3d",
                )
            ],
            output_path="/tmp/outside/a.f3d", artifact_root="/tmp/artifacts",
            execution_authorization=execution_token(
                "cad-step-2", "call-2", "attempt-2",
                outside_digest,
                capability_id="cad.export.f3d", provider_operation="export_f3d",
                risk_class="export",
                parameters=outside_parameters,
            ),
        )

    def test_no_change_partial_write_timeout_and_undo_states(self):
        self.assertEqual(
            contracts.classify_fusion_write("success", "a", "a", True),
            "blocked_no_change",
        )
        self.assertEqual(
            contracts.classify_fusion_write("success", "a", "b", False),
            "rollback_required",
        )
        self.assertEqual(
            contracts.classify_fusion_write("timeout", "a", "b", False),
            "rollback_required",
        )
        self.assertEqual(
            contracts.classify_fusion_write("timeout", "a", "b", False, "a"),
            "recovered_waiting_user_decision",
        )
        self.assertEqual(
            contracts.classify_fusion_write("error", "a", "a", False),
            "failed_no_change",
        )


class EasyEdaPreflightTests(unittest.TestCase):
    def valid_context(self):
        return {
            "run_id": "run-easyeda",
            "adapter_id": "easyeda-api",
            "bridge_service": "easyeda-bridge",
            "window_ids": ["window-1"],
            "project_uuid": "project-1",
            "document_uuid": "document-1",
            "document_type": "pcb",
            "has_unsaved_changes": False,
            "api_signature_verified": True,
            "enums_verified": True,
            "write_permission": True,
            "baseline_ref": "snapshot-1",
            "validated_route_decision_id": "decision-route-pcb-001",
            "validated_operation_step_id": "pcb-step-001",
            "validated_call_id": "call-pcb-001",
            "validated_attempt_id": "attempt-pcb-001",
            "readback_input_bindings": ["electrical@1:sha256:electrical"],
            "validated_schematic_freeze_decision_id": "decision-freeze-schematic-001",
            "readback_schematic_hash": "sha256:schematic-001",
            "validated_interface_freeze_decision_id": "decision-freeze-interface-001",
            "readback_interface_hash": "sha256:interface-001",
        }

    def expected(self):
        return {
            "window_id": "window-1",
            "project_uuid": "project-1",
            "document_uuid": "document-1",
            "document_type": "pcb",
            "route_decision_id": "decision-route-pcb-001",
            "operation_step_id": "pcb-step-001",
            "schematic_freeze_decision_id": "decision-freeze-schematic-001",
            "schematic_hash": "sha256:schematic-001",
            "interface_freeze_decision_id": "decision-freeze-interface-001",
            "interface_hash": "sha256:interface-001",
        }

    def token(self, *, phase="authorized", parameters=None, provider_operation="pcb_move_components"):
        parameters = parameters or self.expected()
        return contracts._issue_execution_authorization(
            run_id="run-easyeda", step_id="pcb-step-001", call_id="call-pcb-001",
            attempt_id="attempt-pcb-001",
            parameter_digest=contracts.canonical_parameter_digest(parameters),
            route_decision_id="decision-route-pcb-001", adapter_id="easyeda-api",
            capability_id="pcb.move_components", provider_operation=provider_operation,
            risk_class="reversible_write",
            operation_digest="sha256:synthetic-easyeda-operation",
            parameters=parameters,
            target_ids=(
                f"window:{parameters.get('window_id')}",
                f"project:{parameters.get('project_uuid')}",
                f"document:{parameters.get('document_uuid')}",
                f"document_type:{parameters.get('document_type')}",
            ),
            input_bindings=("electrical@1:sha256:electrical",),
            run_state_digest="sha256:state", bundle_digest="sha256:bundle",
            phase=phase,
            reservation_id=(
                f"reservation-pcb-{next(TOKEN_COUNTER)}" if phase == "reserved" else ""
            ),
        )

    def test_valid_preflight(self):
        self.assertEqual(
            contracts.easyeda_preflight(self.valid_context(), self.token()), []
        )

    def test_multi_window_wrong_document_and_permission_are_blockers(self):
        context = self.valid_context()
        context["window_ids"] = ["window-1", "window-2"]
        context["document_type"] = "schematic"
        context["write_permission"] = False
        blockers = contracts.easyeda_preflight(context, self.token())
        self.assertNotIn("multiple_windows_require_user_choice", blockers)
        self.assertIn("wrong_document_type", blockers)
        self.assertIn("write_permission_unavailable", blockers)

    def test_preflight_requires_full_bundle_authorization(self):
        blockers = contracts.easyeda_preflight(self.valid_context())
        self.assertIn("bundle_execution_not_authorized", blockers)

    def test_project_document_run_and_adapter_redirection_are_blocked(self):
        context = self.valid_context()
        context.update(
            {
                "run_id": "run-other", "adapter_id": "easyeda-other",
                "project_uuid": "project-other", "document_uuid": "document-other",
                "readback_input_bindings": ["electrical@1:sha256:redirected"],
            }
        )
        blockers = contracts.easyeda_preflight(context, self.token())
        self.assertIn("wrong_run", blockers)
        self.assertIn("wrong_adapter", blockers)
        self.assertIn("wrong_project", blockers)
        self.assertIn("wrong_document", blockers)
        self.assertIn("input_hash_mismatch", blockers)

    def test_actual_easyeda_call_is_exact_and_one_time(self):
        parameters = self.expected()
        token = self.token(phase="reserved", parameters=parameters)
        contracts.guard_easyeda_operation(
            "pcb_move_components", parameters=parameters,
            execution_authorization=token,
        )
        with self.assertRaisesRegex(contracts.ContractError, "already been used"):
            contracts.guard_easyeda_operation(
                "pcb_move_components", parameters=parameters,
                execution_authorization=token,
            )

    def test_easyeda_call_cannot_change_operation_or_parameters(self):
        parameters = self.expected()
        with self.assertRaisesRegex(contracts.ContractError, "does not match"):
            contracts.guard_easyeda_operation(
                "deleteAll", parameters=parameters,
                execution_authorization=self.token(
                    phase="reserved", parameters=parameters,
                ),
            )
        changed = dict(parameters, document_uuid="document-other")
        with self.assertRaisesRegex(contracts.ContractError, "parameters do not match"):
            contracts.guard_easyeda_operation(
                "pcb_move_components", parameters=changed,
                execution_authorization=self.token(
                    phase="reserved", parameters=parameters,
                ),
            )


class CrossDomainTests(unittest.TestCase):
    def shared(self):
        return {
            "pcb_thickness_mm": 1.6,
            "mounting_holes": {"H1": [5, 5, 2.5]},
            "connectors": {"J1": [30, 0, 4, 0]},
            "height_zones": {"HZ1": [20, 20, 8]},
            "antenna_keepouts": {"KO1": [10, 8, 5]},
        }

    def test_holes_connector_thickness_height_and_antenna_are_compared(self):
        contract = self.shared()
        cad = self.shared()
        pcb = self.shared()
        self.assertEqual(contracts.compare_shared_geometry(contract, cad, pcb), [])

        pcb["mounting_holes"] = {"H1": [6, 5, 2.5]}
        pcb["connectors"] = {"J1": [31, 0, 4, 0]}
        pcb["pcb_thickness_mm"] = 2.0
        cad["height_zones"] = {"HZ1": [20, 20, 6]}
        cad["antenna_keepouts"] = {"KO1": [8, 8, 5]}
        self.assertEqual(
            set(contracts.compare_shared_geometry(contract, cad, pcb)),
            {
                "pcb.pcb_thickness_mm",
                "pcb.mounting_holes",
                "pcb.connectors",
                "cad.height_zones",
                "cad.antenna_keepouts",
            },
        )

    def test_non_finite_geometry_is_rejected(self):
        contract = self.shared()
        contract["pcb_thickness_mm"] = float("nan")
        with self.assertRaisesRegex(contracts.ContractError, "finite"):
            contracts.compare_shared_geometry(contract, self.shared(), self.shared())


if __name__ == "__main__":
    unittest.main()
