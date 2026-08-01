import unittest
from unittest.mock import patch

from backend.services.npc_memory_service import (
    record_npc_memories,
    record_open_event,
    record_spellcard_result,
)
from backend.services.relationship_service import update_relationships
from backend.services.turn_models import TurnContext, TurnInput
from backend.services.turn_orchestrator import TurnOrchestrator
from backend.services.turn_service import apply_task_updates


class TurnContractTests(unittest.TestCase):
    def test_contracts_are_json_serializable(self):
        turn = TurnInput(
            kind="npc_dialogue",
            character_id="char-1",
            scene="博丽神社",
            player_name="测试者",
            action_text="向灵梦问好",
            turn_id="turn-1",
            npc_name="博丽灵梦",
        )
        context = TurnContext(turn=turn, character={"profile": {}}, tasks={})
        payload = context.model_dump(mode="json")
        self.assertEqual(payload["turn"]["kind"], "npc_dialogue")
        self.assertEqual(payload["turn"]["turn_id"], "turn-1")


class TurnIdempotencyTests(unittest.TestCase):
    def test_relationship_memory_event_battle_and_tasks_ignore_replay(self):
        character = {
            "relationships_map": {},
            "relationship_progress": {},
            "relationships_history": [],
        }
        first = update_relationships(
            character,
            "博丽灵梦:友好(共同调查)",
            8,
            interaction_text="共同调查",
            turn_id="same-turn",
        )
        second = update_relationships(
            character,
            "博丽灵梦:亲密(重复请求)",
            8,
            interaction_text="重复请求",
            turn_id="same-turn",
        )
        self.assertTrue(first)
        self.assertEqual(second, {})
        self.assertEqual(len(character["relationships_history"]), 1)

        memories = [{"npc_name": "博丽灵梦", "summary": "共同调查了结界。"}]
        self.assertTrue(record_npc_memories(character, memories, turn_id="same-turn"))
        self.assertFalse(record_npc_memories(character, memories, turn_id="same-turn"))
        self.assertTrue(record_open_event(
            character,
            {"title": "结界波纹", "description": "出现了新的波纹。"},
            "博丽神社",
            turn_id="same-turn",
        ))
        self.assertFalse(record_open_event(
            character,
            {"title": "结界波纹", "description": "出现了新的波纹。"},
            "博丽神社",
            turn_id="same-turn",
        ))
        battle = {"opponent": "博丽灵梦", "outcome": "胜利"}
        self.assertTrue(record_spellcard_result(
            character, battle, "博丽神社", turn_id="same-turn"
        ))
        self.assertFalse(record_spellcard_result(
            character, battle, "博丽神社", turn_id="same-turn"
        ))

        tasks = {"active_tasks": [], "completed_tasks": []}
        update = [{"action": "add", "task_id": "clue-1", "info": "调查结界"}]
        self.assertTrue(apply_task_updates(tasks, update, turn_id="same-turn"))
        self.assertFalse(apply_task_updates(tasks, update, turn_id="same-turn"))
        self.assertEqual(len(tasks["active_tasks"]), 1)


class TurnCommitTests(unittest.TestCase):
    def test_orchestrator_commits_character_and_tasks_once(self):
        turn = TurnInput(
            kind="environment",
            character_id="char-1",
            scene="博丽神社",
            player_name="测试者",
            action_text="观察结界",
            turn_id="commit-turn",
        )
        character = {
            "character_id": "char-1",
            "profile": {"name": "测试者"},
            "status": {"is_dead": False, "current_scene": "博丽神社"},
            "time": {"current_day": 1, "current_hour": 8, "chapter_time_remaining": 72},
            "relationships_map": {},
            "relationship_progress": {},
            "relationships_history": [],
        }
        context = TurnContext(
            turn=turn,
            character=character,
            tasks={"active_tasks": [], "completed_tasks": []},
            workflow_thread_id="thread",
        )
        result = {
            "description": "结界保持稳定。",
            "time_cost": 0,
            "is_dead": False,
            "task_updates": [],
            "memory_updates": [],
        }
        orchestrator = TurnOrchestrator()
        with patch(
            "backend.services.turn_orchestrator.apply_turn_resolution",
            return_value={},
        ), patch.object(
            orchestrator, "_apply_memories_and_events"
        ), patch.object(
            orchestrator, "_record_consequence"
        ), patch(
            "backend.services.turn_orchestrator.save_turn_bundle"
        ) as commit:
            outcome = orchestrator.settle(context, result)
        self.assertTrue(outcome.committed)
        commit.assert_called_once_with(
            "char-1",
            context.character,
            context.tasks,
            expected_character_revision=0,
            expected_tasks_revision=0,
            world_changes={},
        )


if __name__ == "__main__":
    unittest.main()
