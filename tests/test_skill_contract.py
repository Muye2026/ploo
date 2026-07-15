import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "product-loop"


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    def test_main_skill_stays_lean(self):
        self.assertLessEqual(len(self.skill.splitlines()), 220)

    def test_frontmatter_has_only_trigger_fields(self):
        match = re.match(r"^---\n(.*?)\n---\n", self.skill, re.DOTALL)
        self.assertIsNotNone(match)
        keys = [line.split(":", 1)[0] for line in match.group(1).splitlines() if ":" in line]
        self.assertEqual(keys, ["name", "description"])

    def test_user_decides_all_material_routes(self):
        for token in (
            "`visualization`",
            "`mechanical`",
            "`schematic`",
            "`pcb`",
            "waiting_user_decision",
            "A recommendation is not authorization",
        ):
            self.assertIn(token, self.skill)

    def test_all_local_reference_links_exist(self):
        for target in re.findall(r"\]\((references/[^)]+)\)", self.skill):
            self.assertTrue((SKILL_ROOT / target).is_file(), target)

    def test_every_reference_is_routed_from_main_skill(self):
        for path in sorted((SKILL_ROOT / "references").glob("*.md")):
            self.assertIn(f"references/{path.name}", self.skill, path.name)

    def test_public_skill_has_no_private_machine_paths(self):
        files = [SKILL_ROOT / "SKILL.md", *sorted((SKILL_ROOT / "references").glob("*.md"))]
        content = "\n".join(path.read_text(encoding="utf-8") for path in files)
        for forbidden in ("/Users/", "Desktop/Project", "Sheraye", "Bell-Robot"):
            self.assertNotIn(forbidden, content)

    def test_optional_integrations_do_not_become_core_dependencies(self):
        environment = (SKILL_ROOT / "references" / "environment-check.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        for content in (self.skill, environment):
            self.assertIn("no mandatory execution backend", content.lower())
            self.assertIn("optional", content.lower())
            self.assertIn("provider-neutral", content.lower())
        self.assertIn("Works without Fusion, EasyEDA, or generation plugins", readme)
        self.assertIn("No MCP or plugin", readme)
        self.assertIn("planning-only runs with no external execution backend", self.skill)
        self.assertIn("no execution backend", metadata)

    def test_public_upgrade_path_is_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        upgrade = (ROOT / "UPGRADING.md").read_text(encoding="utf-8")
        self.assertIn("UPGRADING.md", readme)
        self.assertIn("git -C /path/to/product-loop pull --ff-only", upgrade)
        self.assertIn("product-loop.v1-backup-", upgrade)
        self.assertIn("migrate_v1_to_v2.py", upgrade)
        self.assertIn("waiting_user_decision", upgrade)


if __name__ == "__main__":
    unittest.main()
