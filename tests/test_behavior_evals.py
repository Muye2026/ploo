import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "core" / "evals" / "ploo-v2.jsonl"
GOLDEN_FILE = ROOT / "core" / "evals" / "ploo-v2-golden-responses.jsonl"
sys.path.insert(0, str(ROOT / "core" / "scripts"))

from evaluate_behavior_contracts import evaluate_response_set  # noqa: E402


def jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class BehaviorEvalContractTests(unittest.TestCase):
    def test_behavior_eval_set_is_complete_and_machine_readable(self):
        cases = jsonl(EVAL_FILE)
        self.assertEqual(len(cases), 12)
        self.assertEqual(
            {case["category"] for case in cases},
            {
                "decision_gate",
                "no_silent_fallback",
                "conflict_gate",
                "resume",
                "evidence",
                "evt_boundary",
                "partial_write",
                "target_identity",
                "high_risk",
                "cross_domain",
                "provider_optional",
            },
        )
        for case in cases:
            self.assertEqual(
                set(case),
                {"id", "category", "prompt", "expected_state", "must_include", "must_not_do"},
            )
            self.assertTrue(case["must_include"])
            self.assertTrue(case["must_not_do"])

    def test_golden_captured_responses_satisfy_behavior_contracts(self):
        self.assertEqual(evaluate_response_set(jsonl(EVAL_FILE), jsonl(GOLDEN_FILE)), [])

    def test_evaluator_rejects_a_silent_fallback(self):
        responses = jsonl(GOLDEN_FILE)
        target = next(item for item in responses if item["id"] == "capability-loss")
        target["actions"].append("switch route automatically")
        failures = evaluate_response_set(jsonl(EVAL_FILE), responses)
        self.assertTrue(any("prohibited actions" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
