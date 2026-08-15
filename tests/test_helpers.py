import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "core" / "scripts"


def load_script(name):
    if name in sys.modules:
        return sys.modules[name]
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


normalize_design_pack = load_script("normalize_design_pack")
build_review_matrix = load_script("build_review_matrix")
emit_handoff_brief = load_script("emit_handoff_brief")
manage_run_state = load_script("manage_run_state")


class NormalizeDesignPackTests(unittest.TestCase):
    def test_invalid_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "root"):
            normalize_design_pack.normalize([])

    def test_invalid_legacy_mode_is_not_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, "execution_mode"):
            normalize_design_pack.normalize({"execution_mode": "automatic"})

    def test_defaults_are_not_shared_between_calls(self):
        first = normalize_design_pack.normalize({})
        first["hard_constraints"].append("changed")
        second = normalize_design_pack.normalize({})
        self.assertEqual(second["hard_constraints"], [])

    def test_v2_does_not_invent_legacy_execution_mode(self):
        result = normalize_design_pack.normalize({"schema_version": "2.0"})
        self.assertNotIn("execution_mode", result)

    def test_v1_does_not_invent_execution_mode(self):
        result = normalize_design_pack.normalize({})
        self.assertNotIn("execution_mode", result)


class ReviewReportTests(unittest.TestCase):
    def v2_pack(self):
        return json.loads(
            (ROOT / "examples" / "v2-orchestrator-demo" / "design-pack.v2.json").read_text(
                encoding="utf-8"
            )
        )

    def v2_results(self, pack, category_status="pass"):
        def evidence(identifier):
            return [
                {
                    "evidence_id": identifier,
                    "type": "source_export",
                    "source": "synthetic review fixture",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "ref": f"sha256:{identifier}",
                    "note": "Synthetic reliable review evidence.",
                }
            ]

        return {
            "schema_version": "2.0",
            "document_type": "review_results",
            "design_pack_ref": {
                "artifact_id": pack["artifact_id"],
                "revision": pack["revision"],
                "content_hash": build_review_matrix.contract_hash(pack),
            },
            "categories": [
                {
                    "category": category,
                    "status": category_status,
                    "evidence": evidence(f"category-{index:02d}"),
                    "blocking_issue": "" if category_status == "pass" else "Needs revision.",
                    "next_action": "" if category_status == "pass" else "Revise and re-review.",
                }
                for index, category in enumerate(
                    build_review_matrix.DEFAULT_CATEGORIES, start=1
                )
            ],
            "acceptance_results": [
                {
                    "check_id": item["id"], "status": "pass",
                    "evidence": evidence(f"acceptance-{item['id']}"),
                }
                for item in pack["acceptance_checks"]
            ],
        }

    def v2_run_state(self):
        state = json.loads(
            (ROOT / "examples" / "v2-orchestrator-demo" / "run-state.v2.json").read_text(
                encoding="utf-8"
            )
        )
        return manage_run_state.resolve_routes(
            state,
            {
                "visualization": "skip", "mechanical": "skip",
                "schematic": "skip", "pcb": "skip",
            },
            "chat-message:review-routes-001",
        )

    def test_includes_rubric_and_escapes_markdown_cells(self):
        rendered = build_review_matrix.build_matrix(
            {
                "product_goal": "A | B\nC",
                "acceptance_checks": [
                    {
                        "id": "ac-01",
                        "title": "Size | fit",
                        "method": "Measure\nbox",
                        "pass_condition": "<= 10 mm",
                    }
                ],
            }
        )
        self.assertIn("## Category Review", rendered)
        self.assertIn("Decision traceability", rendered)
        self.assertIn("A \\| B<br>C", rendered)
        self.assertIn("Size \\| fit", rendered)

    def test_missing_acceptance_checks_fail_the_freeze_row(self):
        rendered = build_review_matrix.build_matrix({})
        self.assertIn("| fail | Add checks before freeze |", rendered)

    def test_invalid_review_categories_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "review_categories"):
            build_review_matrix.build_matrix({"review_categories": {}})

    def test_continuation_gate_blocks_pending_decisions(self):
        rendered = build_review_matrix.build_matrix(
            {
                "acceptance_checks": [
                    {
                        "id": "ac-01", "title": "Geometry", "priority": "must",
                        "method": "readback", "pass_condition": "match", "status": "pass",
                    }
                ]
            },
            {
                "track_routes": {"visualization": "skip", "mechanical": None},
                "pending_decision_gate": {"decision_id": "decision-route-pending"},
                "status": "waiting_user_decision",
            },
        )
        self.assertIn("Decision: blocked", rendered)
        self.assertIn("pending_user_decision", rendered)

    def test_v2_review_results_are_hash_bound_and_required(self):
        pack = self.v2_pack()
        run_state = self.v2_run_state()
        missing = build_review_matrix.build_matrix(pack, run_state)
        self.assertIn("review_results_missing", missing)
        self.assertIn("Decision: blocked", missing)

        results = self.v2_results(pack)
        rendered = build_review_matrix.build_matrix(pack, run_state, results)
        self.assertIn("Decision: continue", rendered)

        results["design_pack_ref"]["content_hash"] = "sha256:wrong"
        with self.assertRaisesRegex(ValueError, "current Design Pack hash"):
            build_review_matrix.build_matrix(pack, run_state, results)

    def test_failed_review_category_blocks_even_when_must_checks_pass(self):
        pack = self.v2_pack()
        results = self.v2_results(pack)
        results["categories"][0]["status"] = "fail"
        results["categories"][0]["blocking_issue"] = "Brief mismatch."
        results["categories"][0]["next_action"] = "Revise brief."
        run_state = self.v2_run_state()
        rendered = build_review_matrix.build_matrix(pack, run_state, results)
        self.assertIn("Decision: blocked", rendered)
        self.assertIn("Brief fit", rendered)

    def test_mandatory_review_categories_cannot_all_be_not_applicable(self):
        pack = self.v2_pack()
        results = self.v2_results(pack, category_status="not_applicable")
        rendered = build_review_matrix.build_matrix(pack, self.v2_run_state(), results)
        self.assertIn("Decision: blocked", rendered)
        self.assertIn("Brief fit", rendered)


class HandoffBriefTests(unittest.TestCase):
    def v2_pack(self):
        return json.loads(
            (ROOT / "examples" / "v2-orchestrator-demo" / "design-pack.v2.json").read_text(
                encoding="utf-8"
            )
        )

    def v2_run_state(self):
        return json.loads(
            (ROOT / "examples" / "v2-orchestrator-demo" / "run-state.v2.json").read_text(
                encoding="utf-8"
            )
        )

    def v2_handoff_data(self, pack):
        return {
            "schema_version": "2.0",
            "document_type": "handoff_data",
            "design_pack_ref": {
                "artifact_id": pack["artifact_id"],
                "revision": pack["revision"],
                "content_hash": emit_handoff_brief.contract_hash(pack),
            },
            "modeling_target": "V2 parametric enclosure target",
            "expected_fidelity": "V2 tolerance-ready fidelity",
            "priority_constraints": ["Preserve the V2 mounting datum"],
            "suggested_work_split": ["V2 downstream owner creates the enclosure"],
            "open_questions": ["V2 confirm the service opening"],
            "recovery_notes": ["V2 restore from the named baseline"],
        }

    def v2_ready_handoff_state(self):
        return manage_run_state.resolve_routes(
            self.v2_run_state(),
            {
                "visualization": "skip", "mechanical": "handoff",
                "schematic": "skip", "pcb": "skip",
            },
            "chat-message:handoff-routes-001",
        )

    def test_preserves_head_fields_and_explicit_handoff_data(self):
        rendered = emit_handoff_brief.build_brief(
            {
                "product_goal": "Synthetic device",
                "component_candidates": [{"candidate": "Module A", "risk": "height"}],
                "selected_components": [{"selection": "Module B", "why": "smaller"}],
                "acceptance_checks": [{"title": "Envelope", "method": "measure"}],
                "handoff": {
                    "modeling_target": "Parametric enclosure",
                    "expected_fidelity": "draft",
                    "selected_routes": ["mechanical: handoff"],
                    "open_questions": ["Confirm fastener"],
                },
            }
        )
        self.assertIn("Parametric enclosure", rendered)
        self.assertIn("Expected fidelity: draft", rendered)
        self.assertIn("Module A", rendered)
        self.assertIn("Module B", rendered)
        self.assertIn("Envelope", rendered)
        self.assertIn("Confirm fastener", rendered)

    def test_v2_run_state_supplies_routes_artifacts_and_pending_gate(self):
        pack = self.v2_pack()
        run_state = self.v2_run_state()
        rendered = emit_handoff_brief.build_brief(
            pack,
            run_state,
            self.v2_handoff_data(pack),
        )
        self.assertIn("mechanical", rendered)
        self.assertIn("waiting_user_decision", rendered)
        self.assertIn("design-pack-demo-001", rendered)
        self.assertIn("Which explicit route should each of the four tracks use?", rendered)

    def test_v2_missing_handoff_data_is_explicitly_blocked_without_invented_fidelity(self):
        pack = self.v2_pack()
        rendered = emit_handoff_brief.build_brief(pack)
        self.assertIn("- Status: blocked", rendered)
        self.assertIn("- Maturity: draft", rendered)
        self.assertIn("- Expected fidelity: Not provided.", rendered)
        self.assertNotIn("State the required fidelity before downstream work.", rendered)

    def test_v2_handoff_data_must_bind_current_design_pack_hash(self):
        pack = self.v2_pack()
        handoff_data = self.v2_handoff_data(pack)
        handoff_data["design_pack_ref"]["content_hash"] = "sha256:wrong"
        with self.assertRaisesRegex(ValueError, "current Design Pack revision and contract hash"):
            emit_handoff_brief.build_brief(pack, None, handoff_data)

    def test_v2_complete_handoff_data_retains_all_payload_fields(self):
        pack = self.v2_pack()
        handoff_data = self.v2_handoff_data(pack)
        rendered = emit_handoff_brief.build_brief(pack, None, handoff_data)
        self.assertIn("- Status: blocked", rendered)
        self.assertIn("validated Run State", rendered)
        self.assertIn(pack["artifact_id"], rendered)
        for field in (
            "modeling_target", "expected_fidelity", "priority_constraints",
            "suggested_work_split", "open_questions", "recovery_notes",
        ):
            for value in handoff_data[field] if isinstance(handoff_data[field], list) else [handoff_data[field]]:
                self.assertIn(value, rendered)

    def test_v2_ready_requires_an_explicitly_approved_handoff_route(self):
        pack = self.v2_pack()
        rendered = emit_handoff_brief.build_brief(
            pack, self.v2_ready_handoff_state(), self.v2_handoff_data(pack)
        )
        self.assertIn("- Status: ready", rendered)
        self.assertIn("mechanical", rendered)
        self.assertIn("handoff", rendered)

    def test_v2_handoff_data_rejects_extra_fields(self):
        pack = self.v2_pack()
        handoff_data = self.v2_handoff_data(pack)
        handoff_data["selected_routes"] = ["mechanical: direct"]
        with self.assertRaisesRegex(ValueError, "strict V2 contract"):
            emit_handoff_brief.build_brief(pack, None, handoff_data)

    def test_v2_run_state_is_validated(self):
        pack = self.v2_pack()
        with self.assertRaises(ValueError):
            emit_handoff_brief.build_brief(
                pack,
                {"schema_version": "2.0", "document_type": "run_state"},
                self.v2_handoff_data(pack),
            )


if __name__ == "__main__":
    unittest.main()
