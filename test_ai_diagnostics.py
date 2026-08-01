import unittest
from unittest.mock import patch

from backend.services.ai_diagnostics_service import classify_ai_error, public_usage_summary, update_usage_stats


class AIDiagnosticsTests(unittest.TestCase):
    def test_provider_errors_are_classified_without_leaking_raw_text(self):
        failure = classify_ai_error("401 invalid api key sk-sensitive-value")
        self.assertEqual(failure["code"], "authentication")
        self.assertNotIn("sk-sensitive-value", failure["message"])
        self.assertEqual(classify_ai_error("429 rate limit")["code"], "rate_limit")
        self.assertEqual(classify_ai_error("connection timeout")["code"], "timeout")

    def test_usage_accumulates_and_cost_is_optional(self):
        character = {}
        with patch.dict("os.environ", {
            "TOUHOU_INPUT_PRICE_PER_MILLION": "1",
            "TOUHOU_OUTPUT_PRICE_PER_MILLION": "2",
            "TOUHOU_COST_CURRENCY": "CNY",
        }):
            update_usage_stats(character, {
                "prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500,
            }, 1800, "model", None)
        summary = public_usage_summary(character)
        self.assertEqual(summary["requests"], 1)
        self.assertEqual(summary["total_tokens"], 1500)
        self.assertEqual(summary["estimated_cost"], 0.002)


if __name__ == "__main__":
    unittest.main()
