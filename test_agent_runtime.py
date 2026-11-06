import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.agent_contracts import AgentLimits, Reader, Proposal, proposal_schema
from backend.services.npc_agent_runtime import AgentBudgetError, AgentDecisionError, BudgetLedger, NPCRuntime


class BudgetTests(unittest.TestCase):
    def test_ledger_initializes_shared_wal_before_parallel_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "shared.db", "turn", 1000, 3)
            with ledger.connect() as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_replacement_only_releases_obsolete_pending_slots_in_same_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replacement.db"
            ledger = BudgetLedger(path, "turn", 1200, 4)
            other = BudgetLedger(path, "other-turn", 1000, 4)
            other.reserve({"other-host": 700})
            ledger.reserve({"shared": 200, "obsolete": 300, "failed": 300, "running": 200})
            request = ledger.start("failed", 300)
            ledger.finish(request, {}, success=False)
            ledger.start("running", 200)
            with ledger.connect() as connection:
                old_calls = connection.execute("SELECT * FROM agent_calls ORDER BY id").fetchall()
            ledger.reserve({"shared": 200, "new-host": 400}, replace_pending=True)
            resumed = BudgetLedger(path, "turn", 1200, 4)
            self.assertEqual(resumed.summary()["charged_tokens"], 500)
            self.assertEqual(resumed.summary()["unknown_requests"], 2)
            self.assertEqual(resumed.summary()["reserved_and_charged"], 1100)
            self.assertEqual(other.summary()["reserved_and_charged"], 700)
            with resumed.connect() as connection:
                self.assertEqual(connection.execute("SELECT * FROM agent_calls ORDER BY id").fetchall(), old_calls)
                states = dict(connection.execute("SELECT job,status FROM agent_jobs WHERE scope='turn'"))
            self.assertEqual(states, {"shared": "planned", "obsolete": "unused", "failed": "failed",
                                      "running": "running", "new-host": "planned"})
            with self.assertRaises(AgentBudgetError):
                resumed.start("obsolete", 300)
            resumed.reserve({"shared": 200, "new-host": 400}, replace_pending=True)
            self.assertEqual(resumed.summary()["reserved_and_charged"], 1100)

    def test_failed_replacement_rolls_back_and_sent_requests_still_limit_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "atomic.db", "turn", 1000, 2)
            ledger.reserve({"npc": 300, "old-host": 400})
            request = ledger.start("npc", 300)
            ledger.finish(request, {"total_tokens": 80}, success=False)
            with ledger.connect() as connection:
                before_jobs = connection.execute("SELECT * FROM agent_jobs ORDER BY job").fetchall()
                before_calls = connection.execute("SELECT * FROM agent_calls ORDER BY id").fetchall()
            for jobs in ({"expensive": 1000}, {"new-npc": 200, "new-host": 200}):
                with self.subTest(jobs=jobs), self.assertRaises(AgentBudgetError):
                    ledger.reserve(jobs, replace_pending=True)
                with ledger.connect() as connection:
                    self.assertEqual(connection.execute("SELECT * FROM agent_jobs ORDER BY job").fetchall(), before_jobs)
                    self.assertEqual(connection.execute("SELECT * FROM agent_calls ORDER BY id").fetchall(), before_calls)

    def test_replacing_unsent_retry_keeps_charge_from_previous_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "retry.db", "turn", 1000, 3)
            ledger.reserve({"npc": 200})
            request = ledger.start("npc", 200)
            ledger.finish(request, {}, success=False)
            ledger.reserve({"npc": 200})
            ledger.reserve({"new-npc": 200, "new-host": 200}, replace_pending=True)
            self.assertEqual(ledger.summary()["charged_tokens"], 200)
            self.assertEqual(ledger.summary()["reserved_and_charged"], 600)
            self.assertEqual(ledger.summary()["requests"], 1)

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
