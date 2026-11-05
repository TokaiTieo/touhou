import asyncio
import copy
import json
import tempfile
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
    async def test_six_parallel_npcs_share_functional_checkpoints_and_replay_without_calls(self):
        from backend.services import turn_workflow
        ctx, _ = context()
        records = {f'npc_test_{i}': {'id': f'npc_test_{i}', 'name': f'访客{i}', 'profile': {'identity': '旅客'}} for i in range(6)}
        ctx.turn.action_text = '向' + '、'.join(row['name'] for row in records.values()) + '问好'
        calls, running, maximum = [], 0, 0
        async def generate(prompt, temperature):
            nonlocal running, maximum
            calls.append(prompt)
            running += 1
            maximum = max(maximum, running)
            try:
                await asyncio.sleep(.03)
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


if __name__ == "__main__":
    unittest.main()
