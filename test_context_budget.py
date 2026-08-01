import unittest

from backend.services.context_budget_service import budget_context_sections


class ContextBudgetTests(unittest.TestCase):
    def test_total_and_section_limits_are_never_exceeded(self):
        budgeted, diagnostics = budget_context_sections(
            {
                "rule_context": "R" * 20,
                "history_text": "H" * 100,
                "npc_memories": "M" * 100,
            },
            total_chars=25,
            limits={
                "rule_context": 20,
                "history_text": 3,
                "npc_memories": 2,
            },
            protected=("rule_context",),
        )
        self.assertLessEqual(sum(map(len, budgeted.values())), 25)
        self.assertEqual(len(budgeted["history_text"]), 3)
        self.assertEqual(len(budgeted["npc_memories"]), 2)
        self.assertLessEqual(diagnostics["used_chars"], 25)

    def test_history_keeps_recent_tail_when_truncated(self):
        budgeted, _ = budget_context_sections(
            {"history_text": "old---recent"},
            total_chars=6,
            limits={"history_text": 6},
        )
        self.assertEqual(budgeted["history_text"], "recent")


if __name__ == "__main__":
    unittest.main()
