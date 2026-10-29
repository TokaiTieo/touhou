import copy
import unittest
from pathlib import Path

from backend.services.action_resolution_service import classify_action
from backend.services.dynamic_event_service import select_dynamic_event
from backend.services.game_rules import resolve_turn_rules, is_battle_action
from backend.services.item_effects import gift_response
from backend.services.life_simulation_service import (
    advance_calendar, advance_npc_plan, change_event, create_appointment, ensure_life_state,
    life_view, record_experience, register_event, sync_completed_events, update_appointment,
)
from backend.services.npc_schedule_service import scheduled_location
from backend.services.relationship_dynamics_service import (
    propose_relationship, record_shared_experience, relationship_dimensions,
    respond_from_text, respond_relationship,
)
from backend.services.relationship_service import apply_relationship_delta
from backend.services.save_migrations import migrate_save_schema
from backend.services.turn_resolution_service import apply_turn_resolution
from backend.version import SAVE_SCHEMA_VERSION


def character(scene="博丽神社"):
    return {"character_id": "life-test", "status": {"current_scene": scene},
            "time": {"current_day": 1, "current_hour": 8}, "profile": {"age": 25},
            "player_state": {"疲劳": 40, "受伤": 20, "灵力": 50},
            "inventory_state": {"items": [], "currency": 0}, "relationships_map": {}, "relationship_progress": {}}


class ActionResolutionTests(unittest.TestCase):
    def test_intentions_denials_and_quoted_speech_do_not_award_recovery(self):
        for text in ("准备休息", "没有休息", "我不休息", '"我正在休息"', "【语言】我去调查线索"):
            with self.subTest(text=text):
                value = character()
                result = {"time_cost": 0.25}
                resolve_turn_rules(value, result, text)
                self.assertGreaterEqual(value["player_state"]["疲劳"], 40)
                self.assertEqual(value["player_state"]["受伤"], 20)
                self.assertEqual(result["skill_progress_delta"], {})

    def test_negated_clause_does_not_suppress_separate_action(self):
        action = classify_action("没有休息，调查结界")
        self.assertNotIn("rest", action["kinds"])
        self.assertIn("investigate", action["kinds"])

    def test_negated_battle_never_starts_battle(self):
        self.assertFalse(is_battle_action("不进行符卡战"))
        self.assertFalse(is_battle_action('"进行符卡战"'))


class LifeActionTests(unittest.TestCase):
    def test_activity_rewards_time_growth_and_diary_commit_once(self):
        value = character()
        tasks = {}
        result = {"time_cost": 12, "inventory_updates": [{"action": "add", "name": "伪造奖励"}]}
        npcs = [{"id": "npc_reimu", "name": "博丽灵梦"}, {"id": "npc_marisa", "name": "雾雨魔理沙"}]
        apply_turn_resolution(value, result, "神社帮工", "博丽神社", tasks, npcs, turn_id="activity-one")
        self.assertEqual(value["time"]["current_hour"], 9)
        self.assertEqual(value["inventory_state"]["currency"], 15)
        self.assertEqual(value["player_state"]["交涉熟练度"], 1)
        self.assertEqual(value["player_state"]["疲劳"], 45)
        self.assertEqual(result["player_state_delta"]["疲劳"], 5)
        self.assertEqual([item["name"] for item in value["inventory_state"]["items"]], ["御札"])
        diaries = value["life_state"]["diaries"]
        self.assertIn("npc_reimu", diaries)
        self.assertNotIn("npc_marisa", diaries)
        after = copy.deepcopy(value)
        apply_turn_resolution(value, result, "神社帮工", "博丽神社", tasks, npcs, turn_id="activity-one")
        self.assertEqual(value, after)

    def test_cooking_requires_and_consumes_actual_ingredients(self):
        value = character("人间之里")
        blocked = {}
        apply_turn_resolution(value, blocked, "制作便当", "人间之里", {}, turn_id="no-food")
        self.assertFalse(blocked["activity_resolution"]["available"])
        self.assertEqual(value["inventory_state"]["items"], [])
        value["inventory_state"]["items"] = [{"name": "食材", "quantity": 1}]
        result = {}
        apply_turn_resolution(value, result, "制作便当", "人间之里", {}, turn_id="food")
        self.assertFalse(any(item["name"] == "食材" for item in value["inventory_state"]["items"]))
        self.assertEqual(value["inventory_state"]["items"][0]["name"], "便当")

    def test_private_npc_diary_is_not_exposed_as_player_knowledge(self):
        value = character()
        record_experience(value, "private", "私下研究", ["帕秋莉"], "红魔馆", "研究记录", visible=False)
        public = life_view(value)
        self.assertEqual(public["diaries"], {})
        self.assertEqual(public["experiences"], [])

    def test_gifts_reveal_only_observed_preferences(self):
        value = character()
        self.assertEqual(life_view(value)["known_preferences"], {})
        gain, reason = gift_response(value, "帕秋莉·诺蕾姬", {"name": "红茶"})
        self.assertGreater(gain, 0)
        self.assertIn("茶", life_view(value)["known_preferences"]["帕秋莉"]["likes"])
        self.assertNotIn("书籍", life_view(value)["known_preferences"]["帕秋莉"]["likes"])
        self.assertIn("npc_patchouli", value["life_state"]["diaries"])

    def test_disliked_gift_does_not_increase_shared_bond(self):
        value = character()
        gain, reason = gift_response(value, "帕秋莉", {"name": "喇叭", "tags": ["喧闹"]})
        self.assertLess(gain, 0)
        self.assertEqual(relationship_dimensions(value, "帕秋莉")["trust"], 0)


class RelationshipDynamicsTests(unittest.TestCase):
    def test_producer_character_does_not_auto_confirm_a_model_romance_label(self):
        from backend.services.relationship_service import update_relationships
        value = character()
        value["gm_mode"] = True
        update_relationships(value, "博丽灵梦:热恋", 8)
        self.assertEqual(value["relationship_progress"]["博丽灵梦"]["stage"], "亲密")
        self.assertEqual(relationship_dimensions(value, "博丽灵梦")["status"], "unconfirmed")

    def high_affection(self, name="雾雨魔理沙"):
        value = character()
        value["relationship_progress"][name] = {"score": 90, "stage": "亲密"}
        value["relationships_map"][name] = "亲密"
        return value

    def test_high_affection_never_automatically_creates_romance(self):
        value = self.high_affection()
        apply_relationship_delta(value, "雾雨魔理沙", 10, "共同经历")
        self.assertEqual(value["relationship_progress"]["雾雨魔理沙"]["stage"], "亲密")
        self.assertEqual(relationship_dimensions(value, "雾雨魔理沙")["status"], "unconfirmed")

    def test_personality_affects_initiative_threshold(self):
        outgoing = self.high_affection()
        outgoing["relationship_progress"]["雾雨魔理沙"]["score"] = 70
        reserved = self.high_affection("帕秋莉")
        reserved["relationship_progress"]["帕秋莉"]["score"] = 70
        self.assertIsNotNone(propose_relationship(outgoing, ["雾雨魔理沙"]))
        self.assertIsNone(propose_relationship(reserved, ["帕秋莉"]))

    def test_accepting_invitation_is_not_romance_or_intimate_consent(self):
        value = self.high_affection()
        proposal = propose_relationship(value, ["雾雨魔理沙"])
        self.assertEqual(proposal["kind"], "invitation")
        respond_relationship(value, proposal["id"], "accept")
        self.assertEqual(relationship_dimensions(value, "雾雨魔理沙")["status"], "unconfirmed")
        self.assertNotEqual(value.get("relationship_boundaries", {}).get("雾雨魔理沙", {}).get("mature"), "open")

    def test_confession_needs_experiences_and_explicit_response(self):
        value = self.high_affection()
        for event in ("one", "two", "three"):
            record_shared_experience(value, "雾雨魔理沙", event)
        proposal = propose_relationship(value, ["雾雨魔理沙"])
        self.assertEqual(proposal["kind"], "confession")
        self.assertEqual(relationship_dimensions(value, "雾雨魔理沙")["status"], "unconfirmed")
        self.assertIsNone(respond_from_text(value, "如果我接受你的告白", "雾雨魔理沙"))
        self.assertIsNone(respond_from_text(value, "我也喜欢你", "帕秋莉"))
        respond_from_text(value, "我也喜欢你", "雾雨魔理沙")
        self.assertEqual(relationship_dimensions(value, "雾雨魔理沙")["status"], "lover")
        self.assertEqual(value["relationships_map"]["雾雨魔理沙"], "恋人")

    def test_friendship_choice_stops_further_proposals(self):
        value = self.high_affection()
        proposal = propose_relationship(value, ["雾雨魔理沙"])
        respond_relationship(value, proposal["id"], "friendship")
        value["time"]["current_day"] = 10
        self.assertIsNone(propose_relationship(value, ["雾雨魔理沙"]))

    def test_declined_proposal_is_not_repeated_or_double_accepted(self):
        value = self.high_affection()
        proposal = propose_relationship(value, ["雾雨魔理沙"])
        self.assertIsNone(propose_relationship(value, ["雾雨魔理沙"]))
        respond_relationship(value, proposal["id"], "decline")
        with self.assertRaises(ValueError):
            respond_relationship(value, proposal["id"], "accept")

    def test_partner_progression_still_requires_player_acceptance(self):
        value = self.high_affection()
        dims = relationship_dimensions(value, "雾雨魔理沙")
        dims.update(status="lover", shared_events=5, closeness=15)
        proposal = propose_relationship(value, ["雾雨魔理沙"])
        self.assertEqual(proposal["kind"], "deepen")
        self.assertEqual(dims["status"], "lover")
        respond_relationship(value, proposal["id"], "accept")
        self.assertEqual(dims["status"], "partner")


class CalendarAndPlanTests(unittest.TestCase):
    def test_appointment_proposal_reschedule_attendance_and_completion(self):
        value = character()
        value["relationship_progress"]["博丽灵梦"] = {"score": 55}
        appointment = create_appointment(value, "博丽灵梦", 1, 10, "人间之里")
        self.assertEqual(appointment["status"], "proposed")
        update_appointment(value, appointment["id"], "reschedule", 1, 11)
        advance_calendar(value, "博丽神社", [])
        self.assertEqual(appointment["status"], "scheduled")
        value["time"]["current_hour"] = 11
        self.assertEqual(scheduled_location("博丽灵梦", 11, "博丽神社", value)[0], "人间之里")
        advance_calendar(value, "人间之里", ["博丽灵梦"])
        self.assertEqual(appointment["status"], "completed")
        self.assertEqual(len(life_view(value)["experiences"]), 1)
        advance_calendar(value, "人间之里", ["博丽灵梦"])
        self.assertEqual(len(life_view(value)["experiences"]), 1)

    def test_missed_appointment_never_changes_location_access(self):
        value = character()
        item = create_appointment(value, "博丽灵梦", 1, 10, "博丽神社")
        value["time"]["current_hour"] = 14
        advance_calendar(value, "人间之里", [])
        self.assertEqual(item["status"], "missed")
        self.assertNotIn("locked_locations", value)

    def test_invalid_appointment_does_not_invent_an_npc(self):
        with self.assertRaises(ValueError):
            create_appointment(character(), "不存在的角色", 2, 10, "博丽神社")
        with self.assertRaises(ValueError):
            create_appointment(character(), "博丽灵梦", 1, 7, "博丽神社")

    def test_npc_plan_has_real_resources_and_idempotent_results(self):
        value = character()
        event = {"id": "plan-one", "npc_name": "八意永琳", "location": "永远亭", "game_hour": 12}
        advance_npc_plan(value, event, "日常")
        self.assertEqual(value["life_state"]["npc_resources"]["八意永琳"]["药材"], 2)
        before = copy.deepcopy(value)
        advance_npc_plan(value, event, "日常")
        self.assertEqual(value, before)
        self.assertTrue(value["life_state"]["events"])

    def test_sleep_and_wrong_location_pause_plan_without_rewards(self):
        for location, hour in (("永远亭", 0), ("人间之里", 12)):
            value = character()
            advance_npc_plan(value, {"id": "pause", "npc_name": "八意永琳", "location": location, "game_hour": hour}, "日常")
            self.assertEqual(value["life_state"]["npc_resources"], {})


class EventAndMigrationTests(unittest.TestCase):
    def test_life_content_schema_rejects_unreachable_and_invalid_activities(self):
        from backend.services.content_validation_service import validate_editable_content
        from backend.services.relationship_dynamics_service import life_content
        root = Path(__file__).parent / "worlds/world_touhou"
        for change in ({"scene": "不存在的地点"}, {"hours": -1}, {"npc": "不存在的角色"}):
            content = copy.deepcopy(life_content())
            content["activities"][0].update(change)
            result = validate_editable_content(root, "life_content.json", content)
            self.assertFalse(result["valid"])

    def test_zero_quantity_item_cannot_produce_gift_relationship_rewards(self):
        from backend.services.progression_service import perform_inventory_action
        value = character()
        value["inventory_state"]["items"] = [{"name": "红茶", "quantity": 0}]
        with self.assertRaises(ValueError):
            perform_inventory_action(value, action="gift", item_name="红茶", npc_name="博丽灵梦")
        self.assertEqual(value["relationships_map"], {})

    def test_legacy_seen_event_can_be_revisited_without_invented_completion(self):
        value = {"save_version": 12, "event_flags": {"dynamic_events": {"seen": {"pe_reimu_1": {"chain": "reimu", "stage": 1}}}}}
        migrate_save_schema(value)
        event = value["life_state"]["events"]["pe_reimu_1"]
        self.assertEqual(event["status"], "discovered")
        self.assertNotEqual(event["title"], "pe_reimu_1")
        change_event(value, "pe_reimu_1", "participate")
        self.assertEqual(event["status"], "participating")

    def test_discovery_does_not_complete_chain(self):
        value = character()
        path = Path(__file__).parent / "worlds/world_touhou/events.json"
        event = select_dynamic_event(value, path, "博丽神社", "御札", [{"name": "博丽灵梦"}], "博丽灵梦")
        self.assertEqual(value["life_state"]["events"][event["id"]]["status"], "discovered")
        second = select_dynamic_event(value, path, "博丽神社", "御札", [{"name": "博丽灵梦"}], "博丽灵梦")
        self.assertFalse(second and second.get("chain") == event.get("chain") and second.get("stage") == 2)

    def test_event_requires_participation_and_real_task_result(self):
        value = character()
        register_event(value, {"id": "event-one", "title": "小事件", "scene": "博丽神社"})
        event = change_event(value, "event-one", "participate")
        event["task_id"] = "event-task"
        with self.assertRaises(ValueError):
            change_event(value, "event-one", "complete")
        sync_completed_events(value, {"completed_tasks": [{"id": "other-task"}]})
        self.assertEqual(event["status"], "participating")
        sync_completed_events(value, {"completed_tasks": [{"id": "event-task"}]})
        self.assertEqual(event["status"], "completed")

    def test_v1_through_v12_migrate_without_rewriting_old_values(self):
        for version in range(1, 13):
            value = {"save_version": version, "profile": {"measurements": "keep", "romance": {"custom": True}},
                     "custom": {"untouched": [1, 2]}, "relationships_map": {"八云紫": "恋人"},
                     "open_events": [{"id": "old", "title": "旧事件"}]}
            original = copy.deepcopy(value)
            migrate_save_schema(value)
            self.assertEqual(value["save_version"], SAVE_SCHEMA_VERSION)
            self.assertEqual(value["profile"], original["profile"])
            self.assertEqual(value["custom"], original["custom"])
            self.assertEqual(value["relationships_map"], original["relationships_map"])
            self.assertEqual(value["relationship_dimensions"]["八云紫"]["status"], "legacy_confirmed")
            self.assertEqual(value["life_state"]["events"]["old"]["status"], "discovered")
            stable = copy.deepcopy(value)
            self.assertFalse(migrate_save_schema(value))
            self.assertEqual(value, stable)


if __name__ == "__main__":
    unittest.main()
