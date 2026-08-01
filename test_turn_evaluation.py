import unittest

from backend.services.turn_evaluation import run_turn_evaluation


class TurnEvaluationTests(unittest.TestCase):
    def test_fixed_turn_scenarios_pass(self):
        report = run_turn_evaluation()
        failures = {
            result["id"]: result["failures"]
            for result in report["results"]
            if not result["passed"]
        }
        self.assertGreaterEqual(report["total"], 6)
        self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
