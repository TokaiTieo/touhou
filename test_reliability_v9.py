import asyncio
import copy
import json
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock

from fastapi import HTTPException
from backend.services.character_commands import execute_character_command
from backend.services.turn_coordinator import turn_coordinator
from backend.services.npc_memory_service import compress_npc_memory_bucket, get_npc_memory_text, memory_identity, restore_archived_memory


class MemoryRetentionTests(unittest.TestCase):
    def test_v9_migration_preserves_custom_data_and_stabilizes_message_ids(self):
        from backend.services.save_migrations import migrate_save_schema
        character = {"save_version": 8, "custom": {"body": [1, 2, 3], "romance": "keep"},
                     "npc_memory_archive": {"灵梦": [{"summary": "原文"}]},
                     "conversation_history": [{"content": "旧记录"}, {"message_id": "same"}, {"message_id": "same"}]}
        custom = copy.deepcopy(character["custom"])
        migrate_save_schema(character)
        self.assertEqual(character["save_version"], 9)
        self.assertEqual(character["custom"], custom)
        self.assertEqual(len({m["message_id"] for m in character["conversation_history"]}), 3)
        self.assertFalse(migrate_save_schema(character))

    def test_rumor_needs_local_witness_contact_and_delay(self):
        from backend.services.npc_agency_service import record_npc_activity, ensure_npc_agency
        character = {"world_state": {"rumors": [{"key": "news", "text": "结界已修复", "scene": "博丽神社", "game_hour": 0}]}}
        def activity(name, location, hour):
            return record_npc_activity(character, {"npc_name": name, "location": location, "game_hour": hour})
        self.assertIn("rumor", activity("博丽灵梦", "博丽神社", 1))
        self.assertNotIn("rumor", activity("雾雨魔理沙", "魔法之森", 2))
        agency = ensure_npc_agency(character)
        agency["social_graph"]["tie"] = {"npcs": ["博丽灵梦", "雾雨魔理沙"]}
        self.assertNotIn("rumor", activity("雾雨魔理沙", "魔法之森", 6))
        self.assertIn("rumor", activity("雾雨魔理沙", "魔法之森", 7))
        self.assertEqual(agency["npcs"]["雾雨魔理沙"]["last_rumor_source"], "博丽灵梦")
        self.assertTrue(agency["npcs"]["雾雨魔理沙"]["goal_history"])

    def test_variants_preserve_choice_and_do_not_reapply_bonus(self):
        from backend.services.campaign_service import apply_incident_variant
        character = {"incident_state": {"id": "next", "completion_task_id": "task"},
            "campaign_state": {"cycle": 2}, "incident_history": [{"title": "旧异变", "path": "negotiation", "path_title": "协商"}]}
        tasks = {"active_tasks": [{"id": "task", "description": "调查"}]}
        definition = {"related_npcs": ["博丽灵梦"], "related_locations": ["博丽神社"]}
        variant = apply_incident_variant(character, definition, tasks)
        self.assertEqual(variant["kind"], "旧日协约")
        self.assertEqual(variant["investigation_bonus"], 3)
        apply_incident_variant(character, definition, tasks)
        self.assertEqual(character["incident_state"]["investigation_progress"], 3)
        self.assertFalse(variant["gates_exploration"])

    def test_next_incident_does_not_count_previous_completed_clues(self):
        from backend.services.incident_service import start_next_incident, sync_incident_from_tasks
        character = {"incident_state": {"id": "touhou_rift", "status": "resolved", "sequence_index": 0, "resolution_path": "negotiation"}}
        tasks = {"completed_tasks": [{"id": f"old-{i}"} for i in range(8)], "active_tasks": []}
        start_next_incident(character, tasks)
        before = character["incident_state"]["investigation_progress"]
        sync_incident_from_tasks(character, tasks)
        self.assertEqual(character["incident_state"]["investigation_progress"], before)
        self.assertEqual(character["incident_state"]["clue_ids"], [])

    def test_gift_preference_and_repeat_diminishing(self):
        from backend.services.item_effects import gift_response
        character = {}
        values = [gift_response(character, "西行寺幽幽子", {"name": "点心"})[0] for _ in range(6)]
        self.assertEqual(values[0], 6)
        self.assertGreater(values[0], values[1])
        self.assertEqual(values[-1], 0)

    def test_memory_maintenance_continues_after_history_reaches_cap(self):
        from backend.services.memory_maintenance_service import maintain_memories
        character = {"conversation_history": [{}] * 500}
        self.assertTrue(maintain_memories(character)["ran"])
        for _ in range(11):
            self.assertFalse(maintain_memories(character)["ran"])
        self.assertTrue(maintain_memories(character)["ran"])

    def test_archive_identity_survives_retrieval_and_legacy_summary_is_recalled(self):
        character = {"npc_memory_archive": {"灵梦": [{"id": "one", "summary": "秋祭御守"}]},
                     "npc_memory_legacy_summaries": {"灵梦": "旧日与玩家约定调查银色铃铛"}}
        item = character["npc_memory_archive"]["灵梦"][0]
        key = memory_identity(item)
        self.assertIn("银色铃铛", get_npc_memory_text(character, "灵梦", query="银色铃铛"))
        self.assertEqual(key, memory_identity(item))

    def test_equipment_gifts_and_legacy_consumption_have_real_effects(self):
        from backend.services.progression_service import ensure_inventory_state, perform_inventory_action
        from backend.services.game_rules import preview_turn_ruling
        character = {"character_id": "effects", "resources": {"道具": ["红茶", "御札"]},
                     "player_state": {"疲劳": 30}, "time": {"current_day": 1}}
        ensure_inventory_state(character)
        before = preview_turn_ruling(character, "符卡挑战")
        perform_inventory_action(character, action="equip", item_name="御札")
        after = preview_turn_ruling(character, "符卡挑战")
        self.assertAlmostEqual(after["score_margin"] - before["score_margin"], 8)
        perform_inventory_action(character, action="use", item_name="红茶")
        self.assertEqual(character["player_state"]["疲劳"], 18)
        self.assertNotIn("红茶", [i["name"] for i in ensure_inventory_state(character)["items"]])

    def test_full_old_summary_does_not_discard_new_fact_or_provenance(self):
        old = [{"id": str(i), "summary": f"事件{i}", "importance": 5} for i in range(40)]
        old[15].update(summary="新承诺：秋祭归还红色御守", importance=10, fact_key="promise",
                       knowledge_type="reported", source_npc="魔理沙", truth_status="disputed")
        character = {"npc_memories": {"灵梦": old}, "npc_memory_summaries": {"灵梦": "旧" * 900}}
        self.assertTrue(compress_npc_memory_bucket(character, "灵梦"))
        self.assertIn("秋祭", get_npc_memory_text(character, "灵梦", query="秋祭御守"))
        archive = character["npc_memory_archive"]["灵梦"]
        self.assertEqual(archive[15]["truth_status"], "disputed")
        self.assertEqual(len(archive) + len(character["npc_memories"]["灵梦"]), 40)
        key = memory_identity(archive[15])
        restored = restore_archived_memory(character, "灵梦", key)
        self.assertEqual(restored["source_npc"], "魔理沙")
        self.assertEqual(character["npc_memory_legacy_summaries"]["灵梦"], "旧" * 900)


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluation_runs_continuous_production_prompts_without_writes(self):
        from backend.services.live_narrative_evaluation_service import run_live_evaluation
        prompts = []
        async def generate(prompt, **kwargs):
            prompts.append(prompt)
            return json.dumps({"description": "灵梦收好那枚绯色御守，确认约定仍然有效。你可以继续调查，也可以自由前往人间之里。", "time_cost": 1})
        original = {"profile": {"name": "评测旅人"}, "status": {"current_scene": "博丽神社"}}
        before = copy.deepcopy(original)
        with patch("backend.services.live_narrative_evaluation_service.call_ai_async", side_effect=generate), \
             patch("backend.services.turn_orchestrator.save_turn_bundle") as saved, \
             patch("backend.routes.ghost.run_turn_workflow") as checkpoint:
            report = await run_live_evaluation(original)
        saved.assert_not_called()
        checkpoint.assert_not_called()
        self.assertEqual(original, before)
        self.assertEqual(len(prompts), 4, report)
        self.assertFalse(any(item["error"] for item in report["results"]), report)
        self.assertIn("绯色御守", prompts[1])
        self.assertTrue(all(item["evaluation"]["dimensions"]["contract"] == 100 for item in report["results"]), report)
        self.assertNotEqual(report["results"][2]["state_before"], report["results"][2]["state_after"])

    async def test_system_helper_can_run_in_queue_without_nested_lock(self):
        from backend.routes.ghost import SystemHelperRequest, system_helper
        from backend.services.character_commands import serialize_character_access
        request = SystemHelperRequest(character_id="helper-test", query="附近有什么线索", player_name="test",
            player_identity="旅人", current_scene="博丽神社", extra_context={"worldview": "幻想乡", "locations": {"博丽神社": {}}, "npcs": [{"name": "灵梦"}]})
        handler = serialize_character_access(getattr(system_helper, "__wrapped__", system_helper))
        with patch("backend.routes.ghost.load_character", return_value={"profile": {"name": "test"}}), \
             patch("backend.routes.ghost.load_tasks", return_value={}), \
             patch("backend.routes.ghost.save_character") as saved, \
             patch("backend.routes.ghost.call_ai_async", new=AsyncMock(return_value='{"description":"可自由调查神社","task_generated":false}')):
            result = await asyncio.wait_for(handler(request), timeout=3)
            self.assertIn("神社", result["description"])
            saved.assert_called_once()

    async def test_producer_state_command_persists_and_is_idempotent(self):
        from backend.routes.producer import set_player_state
        character = {"character_id": "producer-command", "profile": {"name": "test"},
                     "gm_mode": True, "player_state": {"疲劳": 10}, "state_revision": 0}
        committed = []

        def commit(owner, updated, tasks, **kwargs):
            committed.append(copy.deepcopy(updated))
            character.clear()
            character.update(copy.deepcopy(updated))

        with patch("backend.world_manager.load_character", side_effect=lambda _: copy.deepcopy(character)), \
             patch("backend.routes.producer.load_character", side_effect=lambda _: copy.deepcopy(character)), \
             patch("backend.world_manager.load_tasks", return_value={"state_revision": 0}), \
             patch("backend.world_manager.save_turn_bundle", side_effect=commit), \
             patch("backend.routes.producer.save_character", side_effect=lambda owner, updated: commit(owner, updated, {})):
            result = await set_player_state({"character_id": "producer-command", "updates": {"疲劳": 0}, "operation_id": "set-once"})
            self.assertEqual(result["player_state"]["疲劳"], 0)
            self.assertEqual(committed[-1]["player_state"]["疲劳"], 0)

    async def test_retry_changes_inventory_once_and_rejects_different_payload(self):
        character = {"profile": {"name": "test"}, "character_id": "command-test", "count": 2, "state_revision": 0}
        tasks = {"state_revision": 0}

        def commit(owner, updated, updated_tasks, **kwargs):
            self.assertEqual(kwargs["expected_character_revision"], character["state_revision"])
            character.clear()
            character.update(copy.deepcopy(updated))
            character["state_revision"] += 1

        def change(char, task):
            char["count"] -= 1
            return {"count": char["count"]}

        with patch("backend.world_manager.load_character", side_effect=lambda _: copy.deepcopy(character)), \
             patch("backend.world_manager.load_tasks", side_effect=lambda _: copy.deepcopy(tasks)), \
             patch("backend.world_manager.save_turn_bundle", side_effect=commit):
            results = await asyncio.gather(*[execute_character_command("command-test", "gift-once", {"gift": "tea"}, change) for _ in range(3)])
            self.assertEqual(results, [{"count": 1}] * 3)
            self.assertEqual(character["count"], 1)
            with self.assertRaises(HTTPException):
                await execute_character_command("command-test", "gift-once", {"gift": "wine"}, change)

    async def test_command_waits_for_the_active_turn(self):
        entered, release = asyncio.Event(), asyncio.Event()
        order = []

        async def turn():
            entered.set()
            await release.wait()
            order.append("turn")
            return {}

        active = asyncio.create_task(turn_coordinator.execute(character_id="queue-test", turn_id="turn", kind="environment", operation=turn))
        await entered.wait()
        with patch("backend.world_manager.load_character", return_value={}), patch("backend.world_manager.load_tasks", return_value={}):
            command = asyncio.create_task(execute_character_command("queue-test", "command", {}, lambda c, t: {}))
            await asyncio.sleep(0)
            self.assertFalse(command.done())
            release.set()
            await active
            with self.assertRaises(HTTPException):
                await command
        self.assertEqual(order, ["turn"])
