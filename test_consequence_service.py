import unittest

from backend.services.consequence_service import (
    advance_due_consequences,
    format_consequence_context,
    record_turn_consequence,
)


class ConsequenceServiceTests(unittest.TestCase):
    def character(self):
        return {
            "character_id": "consequence-test",
            "time": {"current_day": 2, "current_hour": 10},
        }

    def test_records_direct_and_delayed_effects_without_location_gates(self):
        character = self.character()
        result = {
            "player_state_delta": {"疲劳": 3},
            "task_updates": [{
                "task_id": "task_rift",
                "action": "complete",
                "info": "结界裂隙已经稳定",
            }],
            "world_effects": [{
                "kind": "rumor",
                "target": "博丽神社",
                "effect": "巫女开始整理这次异变的记录。",
                "delay_hours": 2,
            }],
        }
        record = record_turn_consequence(
            character,
            result,
            "帮助灵梦修复并稳定结界",
            "博丽神社",
            "environment",
            turn_id="turn-1",
        )
        self.assertEqual(len(character["consequence_log"]), 1)
        self.assertEqual(len(character["deferred_consequences"]), 2)
        self.assertIn("task_completed:task_rift", character["world_state"]["flags"])
        self.assertNotIn("locked_locations", character["world_state"])
        self.assertTrue(record["direct_effects"])
        self.assertTrue(any("后续回响" in item for item in result["consequence_summary"]))

        record_turn_consequence(
            character, result, "重复请求", "博丽神社", "environment", turn_id="turn-1"
        )
        self.assertEqual(len(character["consequence_log"]), 1)
        self.assertEqual(len(character["deferred_consequences"]), 2)

    def test_due_effect_becomes_rumor_and_context(self):
        character = self.character()
        result = {
            "world_effects": [{
                "kind": "rumor",
                "target": "人间之里",
                "effect": "里民开始谈论昨夜的弹幕。",
                "delay_hours": 1,
            }],
        }
        record_turn_consequence(
            character, result, "进行符卡决斗", "人间之里", "environment", turn_id="turn-2"
        )
        character["time"]["current_hour"] = 12
        resolved = advance_due_consequences(character)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertTrue(character["world_state"]["rumors"])
        self.assertIn("人间之里", format_consequence_context(character))
