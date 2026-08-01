import unittest

from backend.services.story_summary_service import rebuild_story_summary


class StorySummaryTests(unittest.TestCase):
    def test_summary_collects_choices_tasks_events_and_relationships(self):
        character = {
            "conversation_history": [
                {"speaker": "玩家", "content": "我决定帮助灵梦完成结界调查", "message_id": "m1"},
                {"speaker": "旁白", "content": "结界恢复了平静", "message_id": "m2"},
            ],
            "open_events": [{"title": "神社来信", "description": "早苗送来邀请"}],
            "relationships_map": {"博丽灵梦": "友好(共同调查)"},
            "incident_state": {"status": "resolved", "title": "结界裂隙", "resolution_path_title": "共同修复"},
        }
        tasks = {
            "active_tasks": [{"name": "湖边传闻", "description": "调查红雾"}],
            "completed_tasks": [{"name": "稳定结界"}],
        }
        self.assertTrue(rebuild_story_summary(character, tasks, force=True))
        summary = character["story_summary"]
        self.assertIn("稳定结界", "".join(summary["key_events"]))
        self.assertIn("湖边传闻", "".join(summary["unresolved_threads"]))
        self.assertIn("博丽灵梦", "".join(summary["relationship_highlights"]))
        self.assertEqual(summary["last_message_id"], "m2")

    def test_force_rebuild_removes_future_branch_facts(self):
        character = {
            "conversation_history": [
                {"speaker": "玩家", "content": "先去神社", "message_id": "m1"},
                {"speaker": "旁白", "content": "未来秘密已经揭晓", "message_id": "m2"},
            ]
        }
        rebuild_story_summary(character, force=True)
        character["conversation_history"] = character["conversation_history"][:1]
        rebuild_story_summary(character, force=True)
        self.assertNotIn("未来秘密", character["story_summary"]["recent_arc"])


if __name__ == "__main__":
    unittest.main()
