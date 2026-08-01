import unittest

from backend.services.relationship_policy_service import (
    mature_context_allowed,
    observe_relationship_boundaries,
    player_is_adult,
)
from backend.services.relationship_service import update_relationships


def make_character(age=20, gm=False):
    return {
        "profile": {"name": "关系测试者", "age": age, "adult_verified": age >= 18},
        "gm_mode": gm,
        "time": {"current_day": 1, "current_hour": 12},
        "relationships_map": {},
        "relationship_progress": {},
        "relationships_history": [],
        "relationship_boundaries": {},
    }


class RelationshipPolicyTests(unittest.TestCase):
    def test_relationship_cannot_jump_from_first_meeting_to_lover(self):
        character = make_character()
        delta = update_relationships(
            character,
            "八云紫:热恋(第一次见面便十分投缘)",
            12,
            interaction_text="和八云紫打招呼",
        )
        self.assertTrue(delta["八云紫"]["clamped"])
        self.assertLessEqual(delta["八云紫"]["score"], 8)
        self.assertEqual(delta["八云紫"]["stage"], "相识")

    def test_explicit_refusal_closes_boundary_and_reduces_progress(self):
        character = make_character()
        character["relationships_map"]["八云紫"] = "亲密(长期相处)"
        character["relationship_progress"]["八云紫"] = {
            "score": 76, "stage": "亲密", "attitude": "亲密(长期相处)"
        }
        observe_relationship_boundaries(character, "八云紫", "我不要继续亲密接触，只想保持普通朋友")
        delta = update_relationships(
            character,
            "八云紫:热恋(依然想要靠近)",
            13,
            interaction_text="我不要继续亲密接触，只想保持普通朋友",
        )
        self.assertEqual(character["relationship_boundaries"]["八云紫"]["romance"], "closed")
        self.assertLess(delta["八云紫"]["score"], 76)
        self.assertEqual(delta["八云紫"]["pacing_reason"], "explicit_refusal")

    def test_mature_context_requires_verified_player_and_allowlisted_npc(self):
        adult = make_character(25)
        minor = make_character(17)
        self.assertTrue(player_is_adult(adult))
        self.assertTrue(mature_context_allowed(adult, "八云紫"))
        self.assertFalse(mature_context_allowed(adult, "博丽灵梦"))
        self.assertFalse(mature_context_allowed(minor, "八云紫"))

    def test_producer_console_relationship_override_is_not_paced(self):
        character = make_character(gm=True)
        delta = update_relationships(
            character,
            "八云紫:热恋(制作人控制台)",
            12,
        )
        self.assertEqual(delta["八云紫"]["stage"], "恋人")
        self.assertFalse(delta["八云紫"]["clamped"])
