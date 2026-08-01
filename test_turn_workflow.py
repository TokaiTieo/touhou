import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.services import turn_workflow


class TurnWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_contract_step_resumes_without_second_model_call(self):
        response = json.dumps({
            "description": "灵梦确认结界暂时稳定。",
            "time_cost": 0.5,
            "exit_dialogue": False,
            "task_updates": [],
            "memory_updates": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root) / "workflow.sqlite3"
            model = AsyncMock(return_value=response)
            original_parser = turn_workflow.parse_turn_response
            with patch.object(turn_workflow, "CHECKPOINT_PATH", checkpoint), patch.object(
                turn_workflow, "call_ai_async", new=model
            ), patch.object(
                turn_workflow,
                "parse_turn_response",
                side_effect=RuntimeError("simulated parser interruption"),
            ):
                with self.assertRaises(RuntimeError):
                    await turn_workflow.run_turn_workflow(
                        kind="npc_dialogue",
                        prompt="测试提示词",
                        thread_id="resume-thread",
                    )
                await turn_workflow.close_workflow_runtime(checkpoint)
            with patch.object(turn_workflow, "CHECKPOINT_PATH", checkpoint), patch.object(
                turn_workflow, "call_ai_async", new=model
            ), patch.object(turn_workflow, "parse_turn_response", original_parser):
                resumed = await turn_workflow.run_turn_workflow(
                    kind="npc_dialogue",
                    prompt="测试提示词",
                    thread_id="resume-thread",
                )
                self.assertEqual(resumed["result"]["description"], "灵梦确认结界暂时稳定。")
                await turn_workflow.clear_turn_checkpoint("resume-thread")
                await turn_workflow.close_workflow_runtime(checkpoint)

            self.assertEqual(model.await_count, 1)

    async def test_completed_workflow_survives_runtime_restart_until_commit(self):
        response = json.dumps({
            "description": "完成结果等待游戏状态提交。",
            "time_cost": 0,
            "is_dead": False,
            "task_updates": [],
            "memory_updates": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root) / "completed.sqlite3"
            model = AsyncMock(return_value=response)
            with patch.object(turn_workflow, "CHECKPOINT_PATH", checkpoint), patch.object(
                turn_workflow, "call_ai_async", new=model
            ):
                first = await turn_workflow.run_turn_workflow(
                    kind="environment",
                    prompt="待提交提示词",
                    thread_id="completed-thread",
                )
                await turn_workflow.close_workflow_runtime(checkpoint)
                resumed = await turn_workflow.run_turn_workflow(
                    kind="environment",
                    prompt="待提交提示词",
                    thread_id="completed-thread",
                )
                self.assertEqual(first["response"], resumed["response"])
                self.assertEqual(first["result"], resumed["result"])
                self.assertFalse(first["workflow_recovered"])
                self.assertTrue(resumed["workflow_recovered"])
                self.assertEqual(model.await_count, 1)
                await turn_workflow.clear_turn_checkpoint("completed-thread")
                await turn_workflow.close_workflow_runtime(checkpoint)

    async def test_reused_turn_id_rejects_changed_prompt(self):
        response = json.dumps({
            "description": "输入身份测试。",
            "time_cost": 0,
            "is_dead": False,
            "task_updates": [],
            "memory_updates": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root) / "identity.sqlite3"
            model = AsyncMock(return_value=response)
            with patch.object(turn_workflow, "CHECKPOINT_PATH", checkpoint), patch.object(
                turn_workflow, "call_ai_async", new=model
            ):
                try:
                    await turn_workflow.run_turn_workflow(
                        kind="environment",
                        prompt="原始提示词",
                        thread_id="identity-thread",
                    )
                    with self.assertRaises(turn_workflow.TurnInputConflictError):
                        await turn_workflow.run_turn_workflow(
                            kind="environment",
                            prompt="被替换的提示词",
                            thread_id="identity-thread",
                        )
                finally:
                    await turn_workflow.clear_turn_checkpoint("identity-thread")
                    await turn_workflow.close_workflow_runtime(checkpoint)

    async def test_missing_langgraph_dependency_uses_direct_generation(self):
        response = json.dumps({
            "description": "回退路径仍可运行。",
            "time_cost": 0,
            "is_dead": False,
            "task_updates": [],
            "memory_updates": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as root:
            checkpoint = Path(root) / "fallback.sqlite3"
            model = AsyncMock(return_value=response)
            with patch.object(turn_workflow, "CHECKPOINT_PATH", checkpoint), patch.object(
                turn_workflow, "call_ai_async", new=model
            ), patch.object(
                turn_workflow,
                "_load_runtime_dependencies",
                side_effect=turn_workflow.WorkflowUnavailableError("missing"),
            ):
                result = await turn_workflow.run_turn_workflow(
                    kind="environment",
                    prompt="回退提示词",
                    thread_id="fallback-thread",
                )
            self.assertTrue(result["workflow_fallback"])
            self.assertEqual(result["result"]["description"], "回退路径仍可运行。")
            self.assertEqual(model.await_count, 1)


if __name__ == "__main__":
    unittest.main()
