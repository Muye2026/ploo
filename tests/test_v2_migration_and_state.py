import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from manage_run_state import (  # noqa: E402
    apply_route_change,
    open_decision,
    resolve_pending_decision,
    resolve_routes,
    stale_descendants,
)
from migrate_v1_to_v2 import migrate  # noqa: E402
from validate_v2 import ValidationError, validate_document  # noqa: E402


def v1_pack(interaction_mode="checkpointed"):
    return {
        "product_goal": "Build a compact verified hardware accessory.",
        "execution_mode": "full",
        "interaction_mode": interaction_mode,
        "hard_constraints": [
            {"id": "hc-01", "category": "envelope", "rule": "Stay compact.", "priority": "must"}
        ],
        "component_envelopes": [
            {"name": "controller", "size_mm": [20, 15, 3], "placement_note": "internal"}
        ],
        "selected_components": [
            {
                "module": "controller",
                "selection": "provisional controller module",
                "why": "Fits the assumed envelope.",
                "fixed_constraints": "Reserve the module keep-out.",
                "unverified": "Supplier revision is not confirmed.",
            }
        ],
        "acceptance_checks": [
            {
                "id": "ac-01",
                "title": "Envelope",
                "method": "Measure",
                "pass_condition": "Fits target envelope",
                "priority": "must",
            }
        ],
    }


def artifact(artifact_id, revision=1, dependencies=()):
    return {
        "artifact_id": artifact_id,
        "artifact_type": "test_artifact",
        "revision": revision,
        "status": "planned",
        "path": f"artifacts/{artifact_id}.json",
        "content_hash": f"sha256:{artifact_id}-{revision}",
        "source_hashes": {},
        "provenance": {
            "source": "unit-test",
            "producer": "test_v2_migration_and_state",
            "time": None,
            "hash": f"sha256:{artifact_id}-{revision}",
        },
        "evidence": [
            {
                "evidence_id": f"evidence-{artifact_id}-{revision}",
                "type": "unverified",
                "source": "unit-test",
                "captured_at": None,
                "ref": None,
                "note": "Synthetic dependency fixture.",
            }
        ],
        "depends_on": [
            {
                "artifact_id": dependency[0],
                "revision": dependency[1],
                "content_hash": f"sha256:{dependency[0]}-{dependency[1]}",
            }
            for dependency in dependencies
        ],
        "invalidation_reasons": [],
    }


class MigrationTests(unittest.TestCase):
    def test_migration_never_authorizes_routes(self):
        source = v1_pack()
        source["component_envelopes"][0]["source_status"] = "confirmed"
        source["selected_components"][0]["selection_status"] = "user_confirmed"
        design_pack, run_state = migrate(source, source_name="fixture.json")

        self.assertEqual(design_pack["schema_version"], "2.0")
        self.assertEqual(design_pack["product_goal"], v1_pack()["product_goal"])
        self.assertEqual(design_pack["component_envelopes"][0]["source_status"], "assumed")
        self.assertEqual(
            design_pack["selected_components"][0]["selection_status"],
            "needs_user_confirmation",
        )
        self.assertEqual(run_state["status"], "waiting_user_decision")
        self.assertTrue(all(value is None for value in run_state["track_routes"].values()))
        self.assertTrue(all(value is None for value in run_state["route_decision_ids"].values()))
        self.assertEqual(run_state["pending_decision_gate"]["status"], "pending")
        self.assertEqual(
            {(report["track"], report["adapter_id"]) for report in run_state["capability_reports"]},
            {
                ("visualization", "unknown"),
                ("mechanical", "unknown"),
                ("schematic", "unknown"),
                ("pcb", "unknown"),
            },
        )
        validate_document(design_pack, expected_kind="design-pack")
        validate_document(run_state, expected_kind="run-state")

        second_design, second_run = migrate(source, source_name="another-path.json")
        self.assertEqual(second_design["artifact_id"], design_pack["artifact_id"])
        self.assertEqual(second_run["run_id"], run_state["run_id"])
        changed_source = copy.deepcopy(source)
        changed_source["product_goal"] = "A materially different synthetic product."
        changed_design, changed_run = migrate(changed_source, source_name="fixture.json")
        self.assertNotEqual(changed_design["artifact_id"], design_pack["artifact_id"])
        self.assertNotEqual(changed_run["run_id"], run_state["run_id"])

    def test_checkpointed_and_auto_only_change_cadence(self):
        _, checkpointed = migrate(v1_pack("checkpointed"))
        _, automatic = migrate(v1_pack("auto"))

        self.assertEqual(checkpointed["execution_cadence"], "stepwise")
        self.assertEqual(automatic["execution_cadence"], "continuous_within_approved_route")
        self.assertEqual(checkpointed["confirmation_policy"], "material_decisions")
        self.assertEqual(automatic["confirmation_policy"], "material_decisions")
        for state in (checkpointed, automatic):
            self.assertEqual(state["status"], "waiting_user_decision")
            self.assertTrue(all(value is None for value in state["track_routes"].values()))

    def test_cli_writes_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "v1.json"
            output = Path(directory) / "bundle.json"
            source.write_text(json.dumps(v1_pack()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "migrate_v1_to_v2.py"), str(source), str(output)],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            bundle = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(set(bundle), {"schema_version", "document_type", "design_pack", "run_state"})
            self.assertEqual(bundle["design_pack"]["provenance"]["source"], source.name)
            self.assertNotIn(directory, output.read_text(encoding="utf-8"))
            validate_document(bundle["design_pack"], expected_kind="design-pack")
            validate_document(bundle["run_state"], expected_kind="run-state")

    def test_cli_refuses_same_path_and_existing_output_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "v1.json"
            original = json.dumps(v1_pack())
            source.write_text(original, encoding="utf-8")
            same_path = subprocess.run(
                [sys.executable, str(SCRIPTS / "migrate_v1_to_v2.py"), str(source), str(source)],
                cwd=str(ROOT), text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(same_path.returncode, 0)
            self.assertIn("input and output must be different", same_path.stderr)
            self.assertEqual(source.read_text(encoding="utf-8"), original)

            output = Path(directory) / "existing.json"
            output.write_text("do not replace", encoding="utf-8")
            existing = subprocess.run(
                [sys.executable, str(SCRIPTS / "migrate_v1_to_v2.py"), str(source), str(output)],
                cwd=str(ROOT), text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(existing.returncode, 0)
            self.assertIn("output already exists", existing.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "do not replace")

    def test_cli_output_dir_emits_standard_v2_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "v1.json"
            output_dir = Path(directory) / "v2-migration"
            source.write_text(json.dumps(v1_pack()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "migrate_v1_to_v2.py"), str(source),
                    "--output-dir", str(output_dir),
                ],
                cwd=str(ROOT), text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {"design-pack.v2.json", "run-state.v2.json", "migration-bundle.v2.json"},
            )
            validate_document(
                json.loads((output_dir / "design-pack.v2.json").read_text(encoding="utf-8")),
                expected_kind="design-pack",
            )
            state = json.loads((output_dir / "run-state.v2.json").read_text(encoding="utf-8"))
            validate_document(state, expected_kind="run-state")
            self.assertEqual(state["status"], "waiting_user_decision")
            before = {
                path.name: path.read_text(encoding="utf-8") for path in output_dir.iterdir()
            }
            repeated = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "migrate_v1_to_v2.py"), str(source),
                    "--output-dir", str(output_dir),
                ],
                cwd=str(ROOT), text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("output directory already exists", repeated.stderr)
            self.assertEqual(
                {path.name: path.read_text(encoding="utf-8") for path in output_dir.iterdir()},
                before,
            )


class RunStateManagementTests(unittest.TestCase):
    def setUp(self):
        _, self.state = migrate(v1_pack())

    def test_resolve_routes_records_only_explicit_user_choices(self):
        partial = resolve_routes(
            self.state,
            {"visualization": "image", "mechanical": "direct", "schematic": None, "pcb": None},
            "chat-message:route-choice-1",
        )
        self.assertEqual(partial["track_routes"]["visualization"], "image")
        self.assertEqual(partial["track_routes"]["mechanical"], "direct")
        self.assertIsNone(partial["track_routes"]["schematic"])
        self.assertIsNone(partial["route_decision_ids"]["pcb"])
        self.assertEqual(partial["status"], "waiting_user_decision")
        self.assertIsNotNone(partial["pending_decision_gate"])
        self.assertEqual(len(partial["decision_ledger"]), 2)
        self.assertTrue(all(item["decided_by"] == "user" for item in partial["decision_ledger"]))

        complete = resolve_routes(
            partial,
            {"visualization": None, "mechanical": None, "schematic": "guided", "pcb": "hybrid"},
            "chat-message:route-choice-2",
        )
        self.assertEqual(complete["status"], "planned")
        self.assertIsNone(complete["pending_decision_gate"])
        self.assertTrue(all(complete["track_routes"][track] is not None for track in complete["track_routes"]))
        self.assertTrue(all(complete["route_decision_ids"][track] for track in complete["route_decision_ids"]))
        self.assertEqual(len(complete["decision_ledger"]), 4)
        validate_document(complete, expected_kind="run-state")

    def test_resolve_routes_rejects_implicit_defaults(self):
        with self.assertRaises(ValidationError):
            resolve_routes(
                self.state,
                {track: None for track in self.state["track_routes"]},
                "chat-message:no-routes",
            )

    def test_open_and_resolve_non_route_decision(self):
        routed = resolve_routes(
            self.state,
            {"visualization": "skip", "mechanical": "skip", "schematic": "skip", "pcb": "skip"},
            "chat-message:route-choice-all",
        )
        gate = {
            "decision_id": "decision-freeze-design-001",
            "decision_type": "freeze",
            "scope": [f"artifact:{routed['artifacts'][0]['artifact_id']}@1"],
            "status": "resolved",
            "question": "Freeze the current synthetic Design Pack?",
            "options": [
                {"id": "freeze", "label": "Freeze", "description": "Freeze this revision.", "impact": "Downstream work may rely on it."},
                {"id": "revise", "label": "Revise", "description": "Keep editing.", "impact": "Downstream work stays blocked."},
            ],
            "recommendation": "freeze",
            "recommendation_rationale": "Synthetic acceptance checks are ready.",
            "impact": ["This revision becomes a downstream dependency."],
            "selected_option": "freeze",
            "decided_by": "agent",
            "decided_at": "2026-01-01T00:00:00Z",
            "decision_evidence": [{"fabricated": True}],
            "dependency_revisions": [],
        }
        opened = open_decision(routed, gate)
        self.assertEqual(opened["status"], "waiting_user_decision")
        self.assertEqual(opened["pending_decision_gate"]["status"], "pending")
        self.assertIsNone(opened["pending_decision_gate"]["selected_option"])
        self.assertEqual(
            len(opened["pending_decision_gate"]["dependency_revisions"]),
            len(routed["artifacts"]),
        )
        resolved = resolve_pending_decision(
            opened, "freeze", "approval-record:freeze-design-001"
        )
        self.assertIsNone(resolved["pending_decision_gate"])
        self.assertEqual(resolved["decision_ledger"][-1]["selected_option"], "freeze")
        self.assertEqual(resolved["decision_ledger"][-1]["decided_by"], "user")
        validate_document(resolved, expected_kind="run-state")

    def test_route_change_requires_a_separate_resolved_user_gate(self):
        routed = resolve_routes(
            self.state,
            {"visualization": "skip", "mechanical": "direct", "schematic": "skip", "pcb": "skip"},
            "chat-message:initial-direct-route",
        )
        gate = {
            "decision_id": "decision-change-mechanical-001",
            "decision_type": "route_change",
            "scope": ["track:mechanical"],
            "status": "pending",
            "question": "Fusion is unavailable. Which mechanical route should replace direct?",
            "options": [
                {"id": "guided", "label": "Guided", "description": "User models with steps.", "impact": "Ownership moves to the user."},
                {"id": "handoff", "label": "Handoff", "description": "Prepare an external package.", "impact": "No local model write occurs."},
            ],
            "recommendation": "guided",
            "recommendation_rationale": "It preserves in-session progress without an MCP write.",
            "impact": ["Existing mechanical execution cards become stale."],
            "selected_option": None, "decided_by": None, "decided_at": None,
            "decision_evidence": [], "dependency_revisions": [],
        }
        opened = open_decision(routed, gate)
        resolved = resolve_pending_decision(
            opened, "guided", "approval-record:mechanical-route-change-001"
        )
        changed = apply_route_change(
            resolved, "mechanical", "decision-change-mechanical-001"
        )
        self.assertEqual(changed["track_routes"]["mechanical"], "guided")
        self.assertEqual(
            changed["route_decision_ids"]["mechanical"],
            "decision-change-mechanical-001",
        )
        validate_document(changed, expected_kind="run-state")

    def test_decision_reference_must_have_stable_host_shape(self):
        with self.assertRaisesRegex(ValidationError, "stable host reference"):
            resolve_routes(
                self.state,
                {"visualization": "skip"},
                "fabricated:true",
            )

    def test_manage_cli_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run-state.json"
            path.write_text(json.dumps(self.state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "manage_run_state.py"), "validate", str(path)],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "valid: run_state")

    def test_stale_marks_only_transitive_descendants(self):
        state = resolve_routes(
            copy.deepcopy(self.state),
            {"visualization": "skip", "mechanical": "skip", "schematic": "skip", "pcb": "skip"},
            "chat-message:stale-test-routes",
        )
        state["artifacts"].extend(
            [
                artifact("upstream"),
                artifact("mechanical-interface", dependencies=(("upstream", 1),)),
                artifact("mechanical-cad", dependencies=(("mechanical-interface", 1),)),
                artifact("schematic", dependencies=(("upstream", 1),)),
                artifact(
                    "pcb",
                    dependencies=(("mechanical-interface", 1), ("schematic", 1)),
                ),
                artifact("unrelated"),
            ]
        )
        validate_document(state, expected_kind="run-state")

        updated, affected = stale_descendants(
            state, "mechanical-interface", 1, "Board outline changed."
        )
        self.assertEqual(set(affected), {("mechanical-cad", 1), ("pcb", 1)})
        statuses = {
            (item["artifact_id"], item["revision"]): item["status"]
            for item in updated["artifacts"]
        }
        self.assertEqual(statuses[("mechanical-interface", 1)], "planned")
        self.assertEqual(statuses[("mechanical-cad", 1)], "stale")
        self.assertEqual(statuses[("pcb", 1)], "stale")
        self.assertEqual(statuses[("schematic", 1)], "planned")
        self.assertEqual(statuses[("upstream", 1)], "planned")
        self.assertEqual(statuses[("unrelated", 1)], "planned")
        for item in updated["artifacts"]:
            if item["artifact_id"] in {"mechanical-cad", "pcb"}:
                self.assertEqual(
                    item["invalidation_reasons"],
                    [
                        {
                            "source_artifact_id": "mechanical-interface",
                            "source_revision": 1,
                            "reason": "Board outline changed.",
                        }
                    ],
                )
        validate_document(updated, expected_kind="run-state")

        updated["status"] = "planned"
        with self.assertRaisesRegex(ValidationError, "must reflect child status"):
            validate_document(updated, expected_kind="run-state")

    def test_route_change_recovery_without_step_and_track_scope_fails_cleanly(self):
        routed = resolve_routes(
            self.state,
            {"visualization": "skip", "mechanical": "direct", "schematic": "skip", "pcb": "skip"},
            "chat-message:recovery-scope-routes",
        )
        gate = {
            "decision_id": "decision-recovery-missing-scope-001",
            "decision_type": "route_change",
            "scope": ["recovery:capability-lost"],
            "status": "pending",
            "question": "The provider vanished mid-run. How should execution recover?",
            "options": [
                {"id": "pause", "label": "Pause", "description": "Stop here.", "impact": "The card is blocked."},
            ],
            "recommendation": "pause",
            "recommendation_rationale": "No replacement route was probed.",
            "impact": ["The affected execution card is blocked."],
            "selected_option": None, "decided_by": None, "decided_at": None,
            "decision_evidence": [], "dependency_revisions": [],
        }
        opened = open_decision(routed, gate)
        with self.assertRaisesRegex(ValidationError, "step: and track:"):
            resolve_pending_decision(
                opened, "pause", "approval-record:recovery-missing-scope-001"
            )

    def test_manage_cli_rejects_same_input_and_output_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run-state.json"
            path.write_text(json.dumps(self.state), encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "manage_run_state.py"),
                    "resolve-routes",
                    str(path),
                    str(path),
                    "--decision-ref", "chat-message:same-path-routes",
                    "--visualization", "skip",
                    "--mechanical", "skip",
                    "--schematic", "skip",
                    "--pcb", "skip",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("never overwrite", result.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
