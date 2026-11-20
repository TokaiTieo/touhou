import asyncio
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.agent_contracts import AgentLimits, default_agent_state
from backend.services.agent_scheduler import run_agent_turn
from backend.services.npc_agent_runtime import NPCRuntime, AgentDecisionError, persisted_agent_status
from backend.services.turn_models import TurnInput, TurnContext


def context():
    records = {f"npc_test_{i}": {"id": f"npc_test_{i}", "name": f"访客{i}", "profile": {"identity": "旅客"}} for i in range(3)}
    turn = TurnInput(kind="environment", character_id="test", scene="博丽神社", player_name="测试",
                     action_text="向访客0、访客1、访客2问好", turn_id="same", record_history=True)
    character = {"character_id": "test", "timeline_epoch": "one", "profile": {"name": "测试"},
                 "status": {"current_scene": "博丽神社"}, "time": {"current_day": 1, "current_hour": 8, "chapter_time_remaining": 72},
                 "agent_state": {**default_agent_state(), "mode": "collaborative"}}
    return TurnContext(turn=turn, character=character, tasks={"active_tasks": [], "completed_tasks": []}), records


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_host_citation_retries_host_only_after_restart(self):
        await self.check_citation_recovery()

    async def test_empty_public_events_reject_stale_citations_before_checkpoint(self):
        await self.check_citation_recovery(solo=True)

    async def test_old_successful_invalid_host_cache_is_bypassed_by_host_policy(self):
        await self.check_citation_recovery(old_cache=True)

    async def check_citation_recovery(self, *, solo=False, old_cache=False):
        from contextlib import nullcontext
        from backend.services import agent_scheduler, npc_agent_runtime, turn_workflow
        from backend.services.turn_orchestrator import turn_orchestrator
        ctx, records = context()
        ctx.turn.action_text = "独自休息" if solo else "向访客0问好"
        original, calls = copy.deepcopy(ctx.character), []

        async def generate(prompt, temperature):
            if "独立的人物" in prompt:
                calls.append("npc")
                return '{"commands":[{"kind":"speak","target_id":"@player","text":"你好。"}]}'
            calls.append("host")
            public = json.loads(prompt.splitlines()[-1])["publication"]["npc_decisions"]
            cited = ["private-or-nonexistent"] if calls.count("host") == 1 else [item["id"] for item in public]
            return json.dumps({"description": "庭院安静。", "cited_event_ids": cited}, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "citations.db"
            with patch.object(turn_workflow, "CHECKPOINT_PATH", path), \
                    patch.object(turn_orchestrator, "settle", wraps=turn_orchestrator.settle) as settle, \
                    patch.object(npc_agent_runtime, "get_last_ai_usage", return_value={}):
                runtime = NPCRuntime("citations", path=path, generate=generate)
                kwargs = dict(records=records, present_ids=list(records), world_entries=[], persist=False)
                try:
                    policy = patch.object(agent_scheduler, "HOST_RESULT_POLICY_VERSION", 1) if old_cache else nullcontext()
                    validation = patch.object(npc_agent_runtime, "_validate_host_citations") if old_cache else nullcontext()
                    with policy, validation, self.assertRaises(ValueError if old_cache else AgentDecisionError):
                        await run_agent_turn(ctx, runtime=runtime, **kwargs)
                    self.assertEqual(ctx.character, original)
                    self.assertEqual(calls.count("host"), 1)
                    before = runtime.ledger.summary()
                    self.assertEqual(before["calls"][-1]["status"], "complete" if old_cache else "failed")
                    self.assertEqual(persisted_agent_status(path, "test", "same", "one")["state"], "interrupted")
                    await turn_workflow.close_workflow_runtime(path)
                    runtime = NPCRuntime("citations", path=path, generate=generate)
                    result, candidate = await run_agent_turn(ctx, runtime=runtime, **kwargs)
                    await run_agent_turn(ctx, runtime=runtime, **kwargs)
                    self.assertEqual(calls, ["host", "host"] if solo else ["npc", "host", "host"])
                    self.assertEqual(settle.call_count, 1)
                    self.assertEqual(candidate.character["time"]["current_hour"], 8.5 if solo else 8.25)
                    self.assertEqual(len(result["agent_events"]), 0 if solo else 1)
                    after = runtime.ledger.summary()
                    self.assertEqual(after["calls"][:len(before["calls"])], before["calls"])
                    self.assertEqual(after["requests"], len(calls))
                    self.assertGreater(after["charged_tokens"], before["charged_tokens"])
                finally:
                    await turn_workflow.close_workflow_runtime(path)

    async def test_cancelled_runtime_initialization_closes_unregistered_connection(self):
        from backend.services import turn_workflow
        entered, connections = asyncio.Event(), []

        async def interrupted_configuration(connection):
            connections.append(connection)
            entered.set()
            await asyncio.sleep(20)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "initializing.db"
            with patch.object(turn_workflow, "CHECKPOINT_PATH", path), patch.object(turn_workflow, "_configure_connection", interrupted_configuration):
                task = asyncio.create_task(turn_workflow._get_runtime("environment"))
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                with self.assertRaises(ValueError):
                    await connections[0].execute("SELECT 1")

    async def test_policy_upgrade_releases_unsent_slots_but_preserves_failed_charge(self):
        from backend.services import agent_scheduler, turn_workflow
        ctx, records = context()
        ctx.turn.action_text = "向访客0问好"
        calls = []

        async def generate(prompt, temperature):
            calls.append(prompt)
            if len(calls) == 1:
                raise RuntimeError("interrupted first request")
            return ('{"commands":[{"kind":"wait"}]}' if "独立的人物" in prompt
                    else '{"description":"庭院安静。","cited_event_ids":[]}')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy-budget.db"
            limits = AgentLimits(max_tokens=500000, max_requests=10, concurrency=1)
            with patch.object(turn_workflow, "CHECKPOINT_PATH", path), patch("backend.services.npc_agent_runtime.get_last_ai_usage", return_value={}):
                runtime = NPCRuntime("policy-budget", limits, path=path, generate=generate)
                try:
                    with self.assertRaises(AgentDecisionError):
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    before = runtime.ledger.summary()
                    self.assertEqual(before["requests"], 1)
                    self.assertEqual(before["unknown_requests"], 1)
                    with runtime.ledger.connect() as connection:
                        old_calls = connection.execute("SELECT * FROM agent_calls").fetchall()
                        old_planned = [row[0] for row in connection.execute("SELECT job FROM agent_jobs WHERE status='planned'")]
                    self.assertEqual(len(old_planned), 6)
                    # Reopen the ledger to exercise upgrade after process restart.
                    runtime = NPCRuntime("policy-budget", limits, path=path, generate=generate)
                    with patch.object(agent_scheduler, "CONTEXT_POLICY_VERSION", agent_scheduler.CONTEXT_POLICY_VERSION + 1):
                        result, _ = await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(result["agent_turn"]["budget"]["requests"], 3)
                    after = runtime.ledger.summary()
                    self.assertEqual(after["calls"][0], before["calls"][0])
                    self.assertGreater(after["charged_tokens"], before["charged_tokens"])
                    with runtime.ledger.connect() as connection:
                        self.assertEqual(connection.execute("SELECT * FROM agent_calls WHERE id=?", (old_calls[0][0],)).fetchall(), old_calls)
                        for job in old_planned:
                            self.assertEqual(connection.execute("SELECT status FROM agent_jobs WHERE job=?", (job,)).fetchone()[0], "unused")
                finally:
                    await turn_workflow.close_workflow_runtime(path)

    async def test_six_parallel_npcs_share_functional_checkpoints_and_replay_without_calls(self):
        from backend.services import turn_workflow
        ctx, _ = context()
        records = {f'npc_test_{i}': {'id': f'npc_test_{i}', 'name': f'访客{i}', 'profile': {'identity': '旅客'}} for i in range(6)}
        ctx.turn.action_text = '向' + '、'.join(row['name'] for row in records.values()) + '问好'
        calls, running, maximum = [], 0, 0
        first_batch = asyncio.Event()
        async def generate(prompt, temperature):
            nonlocal running, maximum
            calls.append(prompt)
            running += 1
            maximum = max(maximum, running)
            try:
                if running == 3:
                    first_batch.set()
                await asyncio.wait_for(first_batch.wait(), timeout=5)
                return '{"commands":[{"kind":"wait"}]}' if '独立的人物' in prompt else '{"description":"庭院安静。","cited_event_ids":[]}'
            finally:
                running -= 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'parallel.db'
            with patch.object(turn_workflow, 'CHECKPOINT_PATH', path):
                runtime = NPCRuntime('parallel', path=path, generate=generate)
                try:
                    for _ in range(2):
                        result, _candidate = await run_agent_turn(ctx, runtime=runtime, records=records,
                            present_ids=list(records), world_entries=[], persist=False)
                        self.assertEqual(len(result['agent_turn']['participants']), 6)
                    self.assertEqual(len(calls), 7)
                    self.assertGreaterEqual(maximum, 2)
                    self.assertLessEqual(maximum, 3)
                finally:
                    await turn_workflow.close_workflow_runtime(path)

    async def test_host_retry_reuses_candidate_and_permission_change_invalidates_npc(self):
        from backend.services import turn_workflow
        from backend.services.turn_orchestrator import turn_orchestrator
        ctx, records = context()
        ctx.turn.action_text = "向访客0问好"
        calls, fail = [], True
        async def generate(prompt, temperature):
            nonlocal fail
            if "独立的人物" in prompt:
                calls.append("npc")
                return '{"commands":[{"kind":"wait"}]}'
            calls.append("host")
            if fail:
                fail = False
                raise RuntimeError("host interrupted")
            return '{"description":"庭院安静。","cited_event_ids":[]}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "host.db"
            with patch.object(turn_workflow, "CHECKPOINT_PATH", path), patch.object(turn_orchestrator, "settle", wraps=turn_orchestrator.settle) as settle:
                runtime = NPCRuntime("host-retry", AgentLimits(max_tokens=1000000, max_requests=20), path=path, generate=generate)
                try:
                    with self.assertRaises(AgentDecisionError):
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    self.assertEqual(calls, ["npc", "host", "host"])
                    self.assertEqual(settle.call_count, 1)
                    ctx.character["agent_state"]["permission_version"] += 1
                    await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    self.assertEqual(calls.count("npc"), 2)
                    self.assertEqual(settle.call_count, 2)
                    changes = [lambda: setattr(ctx, 'base_character_revision', ctx.base_character_revision + 1),
                               lambda: ctx.character.update(timeline_epoch='new-branch'),
                               lambda: ctx.character.update(memory_corrections=[{'id': 'corrected-fact', 'status': 'retracted'}])]
                    for expected, change in enumerate(changes, start=3):
                        change()
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                        self.assertEqual(calls.count('npc'), expected)
                        self.assertEqual(settle.call_count, expected)
                    # A deployment policy change must invalidate candidates too,
                    # even when the save, turn and rendered prompt are unchanged.
                    from backend.services import agent_scheduler
                    with patch.object(agent_scheduler, 'CONTEXT_POLICY_VERSION', agent_scheduler.CONTEXT_POLICY_VERSION + 1):
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                        self.assertEqual(calls.count('npc'), 6)
                        self.assertEqual(settle.call_count, 6)
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                        self.assertEqual(calls.count('npc'), 6)
                        self.assertEqual(settle.call_count, 6)
                finally:
                    await turn_workflow.close_workflow_runtime(path)

    async def test_partial_npc_completion_resumes_without_duplicate_calls(self):
        from backend.services import turn_workflow
        ctx, records = context()
        calls, failed = [], False
        async def generate(prompt, temperature):
            nonlocal failed
            if "独立的人物" in prompt:
                identity = json.loads(prompt.splitlines()[-1])["binding"]["npc_id"]
                calls.append(identity)
                if identity == "npc_test_1" and not failed:
                    failed = True
                    raise RuntimeError("provider interrupted")
                return '{"commands":[{"kind":"speak","text":"你好"}]}'
            calls.append("host")
            return '{"description":"庭院安静。","cited_event_ids":[]}'
        before = copy.deepcopy(ctx.character)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recover.db"
            with patch.object(turn_workflow, "CHECKPOINT_PATH", path):
                runtime = NPCRuntime("turn", AgentLimits(concurrency=1), path=path, generate=generate)
                try:
                    with self.assertRaises(AgentDecisionError):
                        await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    self.assertEqual(ctx.character, before)
                    self.assertEqual(persisted_agent_status(path, "test", "same", "one")["state"], "interrupted")
                    result, candidate = await run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                    self.assertEqual(calls.count("npc_test_0"), 1)
                    self.assertEqual(calls.count("npc_test_1"), 2)
                    self.assertEqual(calls.count("npc_test_2"), 1)
                    self.assertEqual(calls.count("host"), 1)
                    self.assertEqual(candidate.character["time"]["current_hour"], 8.25)
                    self.assertEqual(len(result["agent_events"]), 3)
                finally:
                    await turn_workflow.close_workflow_runtime(path)

    async def test_cancelled_late_response_does_not_mutate_state(self):
        ctx, records = context()
        entered = asyncio.Event()
        async def generate(prompt, temperature):
            entered.set()
            try:
                await asyncio.sleep(20)
            except asyncio.CancelledError:
                return '{"commands":[{"kind":"speak","text":"迟到的响应"}]}'
        before = copy.deepcopy(ctx.character)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cancel.db"
            runtime = NPCRuntime("turn", path=path, generate=generate, checkpoint=False)
            task = asyncio.create_task(run_agent_turn(ctx, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(ctx.character, before)
            self.assertEqual(persisted_agent_status(path, "test", "same", "one")["state"], "cancelled")

    async def test_cancellation_waits_for_all_sibling_ledger_cleanup(self):
        ctx, records = context()
        entered, count = asyncio.Event(), 0
        blocked, release, lock = threading.Event(), threading.Event(), threading.Lock()
        finished = []

        async def generate(prompt, temperature):
            nonlocal count
            count += 1
            if count == 3:
                entered.set()
            await asyncio.sleep(20)

        with tempfile.TemporaryDirectory() as directory:
            runtime = NPCRuntime("cancel-cleanup", path=Path(directory) / "cancel.db", generate=generate, checkpoint=False)
            finish = runtime.ledger.finish

            def controlled_finish(*args, **kwargs):
                with lock:
                    finished.append(args[0])
                    must_wait = len(finished) > 1
                if must_wait:
                    blocked.set()
                    if not release.wait(5):
                        raise TimeoutError("test ledger cleanup was not released")
                return finish(*args, **kwargs)

            with patch.object(runtime.ledger, "finish", controlled_finish):
                task = asyncio.create_task(run_agent_turn(ctx, runtime=runtime, records=records,
                    present_ids=list(records), world_entries=[], persist=False))
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    task.cancel()
                    self.assertTrue(await asyncio.to_thread(blocked.wait, 3))
                    done, _ = await asyncio.wait({task}, timeout=.1)
                    self.assertFalse(done, "turn must wait for sibling ledger cleanup")
                finally:
                    release.set()
                    if not task.done() and not task.cancelling():
                        task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(len(finished), 3)
                self.assertEqual(runtime.ledger.summary()["requests"], 3)


if __name__ == "__main__":
    unittest.main()
