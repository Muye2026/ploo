"""Contract checks for the host integration layers under integrations/.

These tests pin the package formats each host expects so a refactor cannot
silently break DeepSeek Harness, WorkBuddy, or CLI installation.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS = ROOT / "integrations"


class DshPluginContractTests(unittest.TestCase):
    def setUp(self):
        self.pkg_dir = INTEGRATIONS / "dsh"

    def test_package_manifest_shape(self):
        pkg = json.loads((self.pkg_dir / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["name"], "dsh-product-loop")
        self.assertEqual(pkg["type"], "module")
        self.assertEqual(pkg["main"], "lib/index.js")
        self.assertEqual(pkg["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertIn("./cordis.patch.yml", pkg["exports"])
        self.assertIn("assets", pkg["files"])

    def test_patch_row_names_package(self):
        patch = (self.pkg_dir / "cordis.patch.yml").read_text(encoding="utf-8")
        self.assertIn("insert:", patch)
        self.assertIn("name: dsh-product-loop", patch)

    def test_plugin_entry_exports(self):
        entry = (self.pkg_dir / "lib" / "index.js").read_text(encoding="utf-8")
        for symbol in ("apply", "inject", "name"):
            self.assertRegex(entry, rf"export \{{[^}}]*\b{symbol}\b[^}}]*\}}")
        self.assertIn("'tools'", entry)
        self.assertIn("'skills'", entry)

    def test_assets_snapshot_tracked(self):
        for rel in ("SKILL.md", "scripts/validate_v2.py", "schemas/run-state.v2.schema.json"):
            self.assertTrue((self.pkg_dir / "assets" / "core" / rel).is_file(), rel)

    def test_profile_preset_bundles(self):
        preset = json.loads(
            (self.pkg_dir / "profile" / "product-loop" / "package.json").read_text(encoding="utf-8")
        )
        bundles = preset["dsh"]["profile"]["bundles"]
        self.assertIn("dsh-product-loop", bundles)


class WorkbuddySkillContractTests(unittest.TestCase):
    def setUp(self):
        self.text = (INTEGRATIONS / "workbuddy" / "SKILL.md").read_text(encoding="utf-8")

    def test_frontmatter_fields(self):
        match = re.match(r"^---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(match)
        keys = [line.split(":", 1)[0] for line in match.group(1).splitlines() if ":" in line]
        for key in ("name", "description", "description_zh", "description_en", "version", "allowed-tools"):
            self.assertIn(key, keys)

    def test_points_at_core_skill(self):
        self.assertIn("core/SKILL.md", self.text)
        self.assertIn("Route Gate 0", self.text)


class CliPackageContractTests(unittest.TestCase):
    def test_pyproject_console_script(self):
        pyproject = (INTEGRATIONS / "cli" / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('ploo = "product_loop_cli.cli:main"', pyproject)
        self.assertIn('name = "product-loop-cli"', pyproject)


if __name__ == "__main__":
    unittest.main()
