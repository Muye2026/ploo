import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CORE = REPO / "core"
EXAMPLES = REPO / "examples" / "v2-orchestrator-demo"
sys.path.insert(0, str(REPO / "integrations" / "cli" / "src"))

from ploo_cli.cli import find_core, main  # noqa: E402


class PlooCliTests(unittest.TestCase):
    def test_find_core_resolves_explicit_checkout(self):
        core = find_core(str(CORE))
        self.assertTrue((core / "scripts" / "validate_v2.py").is_file())

    def test_validate_design_pack(self):
        rc = main(
            ["--core", str(CORE), "validate", "design-pack", str(EXAMPLES / "design-pack.v2.json")]
        )
        self.assertEqual(rc, 0)

    def test_validate_electrical_pack(self):
        rc = main(
            [
                "--core",
                str(CORE),
                "validate",
                "electrical-pack",
                str(EXAMPLES / "electrical-pack.v2.json"),
            ]
        )
        self.assertEqual(rc, 0)

    def test_run_state_passthrough(self):
        rc = main(
            ["--core", str(CORE), "run-state", "validate", str(EXAMPLES / "run-state.v2.json")]
        )
        self.assertEqual(rc, 0)

    def test_validate_bundle_passthrough_with_flags(self):
        rc = main(
            [
                "--core",
                str(CORE),
                "validate-bundle",
                "--run-state",
                str(EXAMPLES / "run-state.v2.json"),
                "--design-pack",
                str(EXAMPLES / "design-pack.v2.json"),
                "--electrical-pack",
                str(EXAMPLES / "electrical-pack.v2.json"),
                "--interface-control",
                str(EXAMPLES / "interface-control.v2.json"),
            ]
        )
        self.assertEqual(rc, 0)

    def test_unknown_kind_exits_nonzero(self):
        rc = main(["--core", str(CORE), "validate", "no-such-kind", "x.json"])
        self.assertNotEqual(rc, 0)

    def test_missing_core_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            main(["--core", "/nonexistent-ploo-core", "validate", "design-pack", "x.json"])

    def test_version_flag(self):
        self.assertEqual(main(["--version"]), 0)

    def test_help_lists_subcommands(self):
        self.assertEqual(main(["--help"]), 0)


if __name__ == "__main__":
    unittest.main()
