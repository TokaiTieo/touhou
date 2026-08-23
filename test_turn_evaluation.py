import unittest

from backend.services.turn_evaluation import run_turn_evaluation
from backend.services.narrative_evaluation_service import (
    build_rated_samples,
    evaluate_narrative_text,
    run_narrative_evaluation,
    summarize_rated_samples,
)


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

    def test_narrative_quality_scenarios_pass(self):
        report = run_narrative_evaluation()
        self.assertGreaterEqual(report["total"], 5)
        self.assertEqual(report["failed"], 0, report["results"])

    def test_internal_ids_and_agency_restrictions_are_reported(self):
        result = evaluate_narrative_text(
            "你必须立刻推进 main_touhou_rift_01，无法前往其他地点。"
        )
        codes = {item["code"] for item in result["issues"]}
        self.assertIn("internal_id", codes)
        self.assertIn("agency_restricted", codes)
        self.assertFalse(result["passed"])

    def test_player_ratings_form_a_local_evaluation_dataset(self):
        character = {
            "conversation_history": [
                {"speaker": "玩家", "content": "调查结界", "scene": "博丽神社"},
                {
                    "message_id": "msg-1", "speaker": "博丽灵梦",
                    "content": "灵梦举起御币检查结界。", "scene": "博丽神社",
                    "rating": "up", "rated_at": "2026-08-23T10:00:00",
                },
            ],
            "model_runtime": {"used_model": "test-model"},
        }
        samples = build_rated_samples(character)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["context"][0]["content"], "调查结界")
        self.assertEqual(summarize_rated_samples(character)["positive"], 1)


if __name__ == "__main__":
    unittest.main()
