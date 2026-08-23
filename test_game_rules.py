import unittest

from backend.services.game_rules import preview_turn_ruling, resolve_turn_rules
from backend.services.progression_service import apply_progression_updates, ensure_progression_profile


def make_character(gm=False):
    return {
        "character_id": "test-character",
        "gm_mode": gm,
        "player_state": {
            "灵力": 60,
            "弹幕熟练度": 35,
            "疲劳": 10,
            "受伤": 0
        },
        "time": {},
        "spellcard_history": []
    }


class GameRulesTests(unittest.TestCase):
    def test_spellcard_ruling_is_deterministic(self):
        character = make_character()
        npcs = [{"name": "博丽灵梦", "profile": {"encounter_tier": "高危"}}]
        first = preview_turn_ruling(character, "向博丽灵梦发起符卡挑战", npcs)
        second = preview_turn_ruling(character, "向博丽灵梦发起符卡挑战", npcs)
        self.assertEqual(first, second)
        self.assertTrue(first["is_battle"])

    def test_producer_mode_always_wins_without_injury(self):
        character = make_character(gm=True)
        result = {"description": "AI说玩家失败", "is_dead": True, "time_cost": 1}
        preview = preview_turn_ruling(character, "挑战八云紫进行符卡战", [], "八云紫")
        resolve_turn_rules(character, result, "挑战八云紫进行符卡战", [], "八云紫", preview)
        self.assertFalse(result["is_dead"])
        self.assertEqual(result["spellcard_result"]["outcome"], "轻松胜利")
        self.assertEqual(character["player_state"]["受伤"], 0)

    def test_battle_updates_state_and_energy_from_rules(self):
        character = make_character()
        result = {"description": "交战", "is_dead": False, "time_cost": 1}
        resolve_turn_rules(character, result, "进行符卡战", [])
        self.assertEqual(result["rule_resolution"]["version"], "deterministic_v2")
        self.assertTrue(result["player_state_delta"])
        self.assertEqual(result["new_energy_state"], character["time"]["energy_state"])

    def test_rest_recovers_fatigue_and_injury(self):
        character = make_character()
        character["player_state"]["疲劳"] = 70
        character["player_state"]["受伤"] = 20
        result = {"description": "休息", "time_cost": 0.25}
        resolve_turn_rules(character, result, "在神社喝茶休息", [])
        self.assertLess(character["player_state"]["疲劳"], 70)
        self.assertLess(character["player_state"]["受伤"], 20)
        self.assertGreaterEqual(result["time_cost"], 0.5)

    def test_actions_grow_matching_long_term_skills(self):
        character = make_character()
        result = {"description": "行动", "time_cost": 1}
        resolve_turn_rules(character, result, "调查线索并和村民交涉后探索山路", [])
        self.assertEqual(character["player_state"]["调查熟练度"], 1)
        self.assertEqual(character["player_state"]["交涉熟练度"], 1)
        self.assertEqual(character["player_state"]["生存熟练度"], 1)

    def test_survival_skill_reduces_travel_fatigue(self):
        novice = make_character()
        expert = make_character()
        expert["player_state"]["生存熟练度"] = 100
        resolve_turn_rules(novice, {"description": "", "time_cost": 2}, "探索并赶路", [])
        resolve_turn_rules(expert, {"description": "", "time_cost": 2}, "探索并赶路", [])
        self.assertLess(expert["player_state"]["疲劳"], novice["player_state"]["疲劳"])

    def test_spellcard_mastery_metrics_and_opponent_adaptation_persist(self):
        character = make_character()
        result = {
            "description": "交战",
            "is_dead": False,
            "time_cost": 1,
            "spellcard_result": {"spellcard_name": "梦符「结界星屑」"},
        }
        resolve_turn_rules(character, result, "使用符卡「结界星屑」进行弹幕决斗", [])
        battle = result["spellcard_result"]
        self.assertEqual(battle["rule_source"], "deterministic_v2")
        self.assertIn("accuracy", battle["metrics"])
        self.assertIn("graze_count", battle["metrics"])
        self.assertTrue(any("结界星屑" in name for name in character["spellcard_mastery"]))
        self.assertEqual(character["opponent_adaptation"]["当前对手"]["battles"], 1)
        self.assertGreater(result["spellcard_mastery_delta"]["experience_gained"], 0)

    def test_producer_spellcard_mastery_is_maximum(self):
        character = make_character(gm=True)
        result = {"description": "绝对胜利", "time_cost": 1}
        resolve_turn_rules(character, result, "使用符卡「制作人终章」挑战八云紫", [], "八云紫")
        mastery = character["spellcard_mastery"]["制作人终章"]
        self.assertEqual(mastery["level"], 999999)
        self.assertIn("绝对压制", mastery["traits"])
        self.assertEqual(result["spellcard_result"]["metrics"]["accuracy"], 100.0)
        self.assertEqual(result["spellcard_result"]["cost"]["灵力"], 0)


    def test_progression_feedback_adds_loadout_and_milestones(self):
        character = make_character()
        result = {"description": "交战", "time_cost": 1, "spellcard_result": {"spellcard_name": "梦符「结界星屑」"}}
        resolve_turn_rules(character, result, "使用符卡「结界星屑」进行弹幕决斗", [])
        apply_progression_updates(character, result, "博丽神社", "完成调查并帮助灵梦")
        self.assertIn("结界星屑", "".join(character["spellcard_loadout"]))
        self.assertTrue(character["progression_milestones"])
        self.assertTrue(result["progression_notifications"])

    def test_reputation_tier_crossing_is_reported_once(self):
        character = make_character()
        character["reputation"] = {"博丽神社": 19}
        result = {"inventory_updates": [], "reputation_updates": [{"faction": "博丽神社", "delta": 2, "reason": "协助修复结界"}]}
        apply_progression_updates(character, result, "博丽神社", "帮助修复结界")
        titles = [item["title"] for item in result["progression_notifications"]]
        self.assertIn("博丽神社声望：友善", titles)
        second = {"inventory_updates": [], "reputation_updates": []}
        apply_progression_updates(character, second, "博丽神社", "休息")
        self.assertEqual(second["progression_notifications"], [])

    def test_loadout_is_additive_limited_and_deduplicated(self):
        character = {"spellcard_loadout": ["梦符", "梦符", "灵符", "A", "B", "C", "D"]}
        ensure_progression_profile(character)
        self.assertEqual(character["spellcard_loadout"], ["梦符", "灵符", "A", "B", "C", "D"])


if __name__ == "__main__":
    unittest.main()
