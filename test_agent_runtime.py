import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.agent_contracts import AgentLimits, Reader, Proposal, proposal_schema
from backend.services.npc_agent_runtime import AgentBudgetError, AgentDecisionError, BudgetLedger, NPCRuntime


class BudgetTests(unittest.TestCase):
    def test_published_schema_matches_domain_specific_field_boundaries(self):
        variants = proposal_schema()['$defs']['Command']['oneOf']
        relationship = next(row for row in variants if row['properties']['kind']['const'] == 'relationship')
        self.assertNotIn('target_id', relationship['properties'])
        self.assertFalse(relationship['additionalProperties'])
        with self.assertRaises(ValueError):
            Proposal(commands=[{'kind': 'relationship', 'text': 'hello', 'target_id': 'someone_else'}])
        proposal = Proposal(commands=[{'kind': 'speak', 'text': '普通朋友', 'target_id': '@player'}])
        self.assertEqual(Proposal.model_validate(proposal.model_dump()), proposal)

    def test_unknown_usage_survives_restart_and_requires_retry_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            first = BudgetLedger(path, "turn", 1000, 3)
            first.reserve({"a": 400, "host": 400})
            request = first.start("a", 400)
            first.finish(request, {}, success=False)
            resumed = BudgetLedger(path, "turn", 1000, 3)
            self.assertEqual(resumed.summary()["charged_tokens"], 400)
            with self.assertRaises(AgentBudgetError):
                resumed.reserve({"a": 400})
            self.assertEqual(resumed.summary()["reserved_and_charged"], 800)

    def test_known_usage_releases_unused_reservation_but_counts_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "x.db", "turn", 1000, 2)
            ledger.reserve({"npc": 400, "host": 400})
            request = ledger.start("npc", 400)
            ledger.finish(request, {"total_tokens": 50}, success=False)
            with self.assertRaises(AgentBudgetError):
                ledger.reserve({"npc": 400})
            self.assertEqual(ledger.summary()["actual_tokens"], 50)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_functional_checkpoint_reuses_completed_npc_without_call(self):
        from backend.services import turn_workflow
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoints.db"
            calls = []
            async def generate(prompt, temperature):
                calls.append(prompt)
                return json.dumps({"commands": [{"kind": "speak", "text": "由本人决定"}]})
            with patch.object(turn_workflow, "CHECKPOINT_PATH", path):
                runtime = NPCRuntime("test", path=path, generate=generate)
                reader = Reader(save_id="s", epoch="e", npc_id="custom_123", task_id="t")
                runtime.ledger.reserve({"job": 10000})
                try:
                    first = await runtime.invoke(reader, "独立决策", {}, "job")
                    second = await runtime.invoke(reader, "独立决策", {}, "job")
                    self.assertEqual(first, second)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(runtime.ledger.summary()["requests"], 1)
                finally:
                    await turn_workflow.close_workflow_runtime(path)

    async def test_invalid_decision_is_not_success_or_automatic_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            async def generate(prompt, temperature):
                return '{"npc_id":"another","commands":[{"kind":"wait"}]}'
            runtime = NPCRuntime("test", path=Path(directory) / "x.db", generate=generate, checkpoint=False)
            runtime.ledger.reserve({"job": 10000})
            reader = Reader(save_id="s", epoch="e", npc_id="a", task_id="t")
            with self.assertRaises(AgentDecisionError):
                await runtime.invoke(reader, "prompt", {}, "job")
            self.assertEqual(runtime.ledger.summary()["requests"], 1)


if __name__ == "__main__":
    unittest.main()
