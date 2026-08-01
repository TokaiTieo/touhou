import unittest

from backend.services.ai_contracts import DialogueTurnResult, EnvironmentTurnResult, parse_turn_response


class AIContractTests(unittest.TestCase):
    def test_valid_environment_result_is_normalized(self):
        result = parse_turn_response(
            '{"description":"调查继续","time_cost":1,"task_updates":[{"action":"complete","task_id":"main"}]}',
            EnvironmentTurnResult,
        )
        self.assertTrue(result["contract_valid"])
        self.assertEqual(result["time_cost"], 1)
        self.assertEqual(result["task_updates"][0]["action"], "complete")

    def test_invalid_state_change_becomes_retryable_without_updates(self):
        result = parse_turn_response(
            '{"description":"内容","time_cost":999,"task_updates":[{"action":"complete"}]}',
            EnvironmentTurnResult,
        )
        self.assertFalse(result["contract_valid"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["task_updates"], [])

    def test_dialogue_contract_ignores_unknown_fields(self):
        result = parse_turn_response(
            '{"description":"回应","exit_dialogue":true,"unexpected":"ignored"}',
            DialogueTurnResult,
        )
        self.assertTrue(result["contract_valid"])
        self.assertTrue(result["exit_dialogue"])
        self.assertNotIn("unexpected", result)


if __name__ == "__main__":
    unittest.main()
