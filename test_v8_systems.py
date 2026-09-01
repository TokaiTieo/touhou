import unittest
from unittest.mock import AsyncMock, patch

from backend.services.campaign_service import advance_campaign_state
from backend.services.live_narrative_evaluation_service import run_live_evaluation
from backend.services.memory_maintenance_service import maintain_memories
from backend.services.npc_agency_service import record_npc_activity, record_player_interaction
from backend.services.onboarding_service import advance_onboarding, default_onboarding, dismiss_onboarding
from backend.services.progression_service import perform_inventory_action, reputation_profile
from backend.services.runtime_diagnostics_service import build_diagnostic_bundle
from backend.services.save_migrations import migrate_save_schema


class V8MigrationTests(unittest.TestCase):
    def test_v7_save_upgrades_additively_and_idempotently(self):
        character = {
            "save_version": 7,
            "content_schema_version": 7,
            "created_at": "2026-01-01T00:00:00",
            "custom_extension": {"keep": True},
            "profile": {"adult_verified": True},
            "incident_state": {"id": "touhou_rift", "title": "结界裂隙异变", "status": "resolved"},
        }
        self.assertTrue(migrate_save_schema(character))
        self.assertEqual(character["save_version"], 8)
        self.assertTrue(character["custom_extension"]["keep"])
        self.assertTrue(character["profile"]["adult_verified"])
        first = list(character["migration_history"])
        self.assertFalse(migrate_save_schema(character))
        self.assertEqual(character["migration_history"], first)

    def test_v8_nested_fields_repair_without_touching_private_profile_data(self):
        character = {
            "save_version": 8,
            "content_schema_version": 8,
            "profile": {"adult_verified": True, "body_data": {"custom": "keep"}},
            "inventory_state": {"items": [], "equipped": "broken"},
            "campaign_state": None,
            "npc_agency": [],
            "memory_maintenance": "broken",
            "onboarding": None,
        }
        self.assertTrue(migrate_save_schema(character))
        self.assertEqual(character["inventory_state"]["equipped"], [])
        self.assertEqual(character["profile"]["body_data"], {"custom": "keep"})
        self.assertFalse(migrate_save_schema(character))


class V8ProgressionTests(unittest.TestCase):
    def test_inventory_use_gift_and_reputation_benefits_do_not_gate(self):
        character = {
            "inventory_state": {"items": [
                {"name": "伤药", "quantity": 1},
                {"name": "红茶", "quantity": 2},
            ], "capacity": 30, "currency": 0},
            "player_state": {"受伤": 30, "疲劳": 20},
            "relationships_map": {},
            "relationship_progress": {},
            "relationships_history": [],
            "time": {"current_hour": 8},
            "reputation": {"博丽神社": 55},
        }
        used = perform_inventory_action(character, action="use", item_name="伤药")
        self.assertEqual(character["player_state"]["受伤"], 10)
        self.assertEqual(used["player_state_delta"]["受伤"], -20)
        gifted = perform_inventory_action(character, action="gift", item_name="红茶", npc_name="博丽灵梦")
        self.assertEqual(gifted["relationship"]["delta"], 4)
        self.assertFalse(reputation_profile(character)["博丽神社"]["gates_exploration"])


class V8CampaignTests(unittest.TestCase):
    def test_last_incident_starts_repeat_cycle_with_unique_task(self):
        character = {
            "character_id": "tester",
            "incident_state": {
                "id": "four_season_bloom", "title": "四季同花异变", "status": "resolved",
                "sequence_index": 11, "resolution_path": "freeform", "aftermath_turns": 0,
            },
            "campaign_state": {"cycle": 1, "status": "roaming", "completed_incident_ids": [], "epilogues": []},
            "time": {},
        }
        tasks = {"active_tasks": [], "completed_tasks": [{"id": "main_four_season_01"}]}
        result = {}
        advance_campaign_state(character, result, "继续寻找新的异变传闻", tasks)
        self.assertEqual(character["campaign_state"]["cycle"], 2)
        self.assertEqual(character["incident_state"]["status"], "active")
        self.assertTrue(tasks["active_tasks"][0]["id"].endswith("_cycle_2"))


class V8MemoryAndAgencyTests(unittest.TestCase):
    def test_memory_maintenance_deduplicates_and_agency_tracks_rumor(self):
        character = {
            "conversation_history": [{}] * 30,
            "npc_memories": {"博丽灵梦": [
                {"id": "a", "summary": "玩家答应修复结界", "importance": 6},
                {"id": "b", "summary": "玩家答应修复结界。", "importance": 8},
            ]},
            "world_state": {"rumors": [{"key": "r1", "text": "红雾重新出现"}]},
            "incident_state": {"title": "红雾残响异变", "related_npcs": ["博丽灵梦"]},
        }
        report = maintain_memories(character, force=True)
        self.assertEqual(report["duplicates_removed"], 1)
        event = {"npc_name": "博丽灵梦", "location": "博丽神社", "activity": "检查结界"}
        record_npc_activity(character, event)
        record_player_interaction(
            character, npc_name="博丽灵梦", scene_npcs=[{"name": "雾雨魔理沙"}],
            scene="博丽神社", action_text="询问红雾", outcome="交换线索", turn_id="t1",
        )
        self.assertEqual(event["rumor"], "红雾重新出现")
        self.assertTrue(character["npc_agency"]["social_graph"])


class V8EvaluationAndPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_evaluation_does_not_mutate_character(self):
        character = {"save_version": 8, "profile": {"identity": "巫女"}, "status": {"current_scene": "博丽神社"}}
        before = repr(character)
        replies = [
            "灵梦看了眼已经修复的结界，确认波纹稳定后，让你自行决定接下来去哪里。",
            "你暂时放下调查，沿路来到人间之里。街市照常热闹，接下来做什么仍由你决定。",
            "符卡战以胜利告终，但伤处随呼吸发痛。你可以休息、求助，也可以继续追查。",
            '{"description":"你在博丽神社沿着结界边缘逐段检查，确认波纹仍在缓慢扩散。风掠过赛钱箱前的落叶，留下几处可继续追踪的灵力痕迹。","is_dead":false,"time_cost":1,"task_updates":[],"memory_updates":[],"inventory_updates":[],"reputation_updates":[],"world_effects":[]}',
        ]
        with patch(
            "backend.services.live_narrative_evaluation_service.call_ai_async",
            new=AsyncMock(side_effect=replies),
        ):
            report = await run_live_evaluation(character)
        self.assertEqual(report["total"], 4)
        self.assertFalse(report["mutated_save"])
        self.assertEqual(repr(character), before)

    def test_diagnostic_bundle_excludes_story_and_secret_bodies(self):
        character = {
            "character_id": "private-id",
            "save_version": 8,
            "conversation_history": [{"content": "private story"}],
            "npc_memories": {"灵梦": [{"summary": "private memory"}]},
            "debug_last_ai": {"prompt_preview": "secret prompt"},
            "usage_stats": {},
        }
        bundle = build_diagnostic_bundle(character, {"active_tasks": [], "completed_tasks": []}, "v-test")
        text = repr(bundle)
        self.assertNotIn("private story", text)
        self.assertNotIn("private memory", text)
        self.assertNotIn("secret prompt", text)
        self.assertNotIn("private-id", text)


class V8OnboardingTests(unittest.TestCase):
    def test_onboarding_is_optional_and_never_a_gate(self):
        character = {"onboarding": default_onboarding(enabled=True)}
        self.assertEqual(character["onboarding"]["current_step"], "first_action")
        advance_onboarding(character, "turn")
        self.assertEqual(character["onboarding"]["current_step"], "first_dialogue")
        dismiss_onboarding(character)
        self.assertTrue(character["onboarding"]["dismissed"])
        self.assertIsNone(character["onboarding"]["current_step"])


if __name__ == "__main__":
    unittest.main()
