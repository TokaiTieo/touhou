import copy
import json
import unittest
from pathlib import Path

from backend.services.incident_service import (
    MAIN_INCIDENT_ID,
    advance_incident_state,
    ensure_incident_state,
    sync_incident_from_tasks,
    start_next_incident,
    apply_resolution_path,
)


def legacy_character(resolved=False):
    return {
        "character_id": "legacy-character",
        "created_at": "2026-06-01T08:00:00",
        "time": {
            "current_day": 3,
            "current_hour": 12,
            "chapter_time_remaining": 40,
            "chapter_status": "resolved" if resolved else "active",
            "anomaly_state": "waiting" if resolved else "active",
        },
        "player_state": {
            "灵力": 50,
            "结界共鸣": 35,
            "弹幕熟练度": 10,
            "异变污染": 20,
        },
        "reputation": {},
    }


class IncidentServiceTests(unittest.TestCase):
    def test_bundled_incident_sequence_is_expanded_and_open(self):
        data = json.loads(
            (Path(__file__).parent / "worlds/world_touhou/incidents.json").read_text(encoding="utf-8-sig")
        )
        self.assertGreaterEqual(len(data["incidents"]), 12)
        self.assertFalse(any("locked_locations" in item for item in data["incidents"]))

    def test_unfinished_legacy_save_upgrades_without_deleting_fields(self):
        character = legacy_character()
        original_time = copy.deepcopy(character["time"])
        incident = ensure_incident_state(character)
        self.assertEqual(incident["status"], "active")
        self.assertEqual(character["time"]["current_day"], original_time["current_day"])
        self.assertEqual(character["time"]["chapter_time_remaining"], 40)

    def test_finished_legacy_save_does_not_receive_migration_reward(self):
        character = legacy_character()
        ensure_incident_state(character)
        before = copy.deepcopy(character["player_state"])
        tasks = {"completed_tasks": [{"id": MAIN_INCIDENT_ID}]}
        sync_incident_from_tasks(character, tasks)
        self.assertEqual(character["incident_state"]["status"], "resolved")
        self.assertEqual(character["player_state"], before)
        self.assertTrue(character["incident_state"]["rewards_claimed"])

    def test_new_completion_rewards_once_and_freezes_legacy_countdown(self):
        character = legacy_character()
        incident = ensure_incident_state(character)
        incident.pop("_migration_pending", None)
        tasks = {"completed_tasks": [{"id": MAIN_INCIDENT_ID}]}
        result = {"player_state_delta": {}}
        sync_incident_from_tasks(character, tasks, result)
        first_state = copy.deepcopy(character["player_state"])
        first_reputation = character["reputation"]["博丽神社"]
        remaining = character["time"]["chapter_time_remaining"]
        sync_incident_from_tasks(character, tasks, {})
        self.assertEqual(character["player_state"], first_state)
        self.assertEqual(character["reputation"]["博丽神社"], first_reputation)
        self.assertEqual(character["time"]["chapter_time_remaining"], remaining)
        self.assertEqual(character["time"]["anomaly_state"], "waiting")
        self.assertIn("incident_resolution", result)

    def test_investigation_advances_without_locking_exploration(self):
        character = legacy_character()
        ensure_incident_state(character).pop("_migration_pending", None)
        result = {"time_cost": 1, "task_updates": []}
        incident = advance_incident_state(character, result, "调查结界裂隙的线索", {"completed_tasks": []})
        self.assertGreater(incident["investigation_progress"], 0)
        self.assertEqual(incident["status"], "active")
        self.assertNotIn("locked_locations", incident)

    def test_resolved_incident_can_start_next_rumor_without_location_gates(self):
        character = legacy_character(resolved=True)
        incident = ensure_incident_state(character)
        incident["status"] = "resolved"
        incident["sequence_index"] = 0
        tasks = {"active_tasks": [], "completed_tasks": [{"id": MAIN_INCIDENT_ID}]}
        definition = start_next_incident(character, tasks)
        self.assertEqual(definition["id"], "scarlet_mist_echo")
        self.assertEqual(character["incident_state"]["status"], "active")
        self.assertTrue(any(task["id"] == "main_scarlet_mist_echo_01" for task in tasks["active_tasks"]))
        self.assertNotIn("locked_locations", character["incident_state"])

    def test_resolution_path_records_free_player_approach(self):
        character = legacy_character()
        incident = ensure_incident_state(character)
        incident.pop("_migration_pending", None)
        tasks = {"completed_tasks": [{"id": MAIN_INCIDENT_ID}]}
        result = {}
        sync_incident_from_tasks(character, tasks, result)
        resolution = apply_resolution_path(character, result, "我说服灵梦合作修复结界")
        self.assertEqual(resolution["path"], "negotiation")
        self.assertIn("共同", resolution["path_title"])
        self.assertNotIn("locked_locations", character["incident_state"])


if __name__ == "__main__":
    unittest.main()
