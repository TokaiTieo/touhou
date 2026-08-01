import unittest

from backend.services.npc_schedule_service import period_for_hour, place_scheduled_npcs, scheduled_location


class NPCScheduleTests(unittest.TestCase):
    def test_sanae_uses_moriya_schedule(self):
        location, note = scheduled_location("东风谷早苗", 8, "博丽神社")
        self.assertEqual(location, "守矢神社")
        self.assertIn("清晨", note)

    def test_period_boundaries(self):
        self.assertEqual(period_for_hour(9.99), "morning")
        self.assertEqual(period_for_hour(10), "day")
        self.assertEqual(period_for_hour(18), "evening")
        self.assertEqual(period_for_hour(23), "night")

    def test_schedule_never_erases_a_populated_scene(self):
        sanae = {"id": "sanae", "name": "东风谷早苗", "location_name": "博丽神社"}
        placed = place_scheduled_npcs([sanae], "博丽神社", 8, [sanae])
        self.assertEqual([item["id"] for item in placed], ["sanae"])

    def test_temporary_and_personal_event_locations_override_schedule(self):
        character = {
            "time": {"current_day": 1, "current_hour": 8},
            "npc_runtime": {"东风谷早苗": {
                "temporary_location": "人间之里", "until_hour": 12, "reason": "赴约"
            }},
        }
        location, note = scheduled_location("东风谷早苗", 8, "守矢神社", character)
        self.assertEqual(location, "人间之里")
        self.assertEqual(note, "赴约")

        character["time"]["current_hour"] = 13
        character["open_events"] = [{
            "npc_name": "东风谷早苗", "scene": "博丽神社",
            "source": "dynamic_event_v1", "title": "约定",
        }]
        location, note = scheduled_location("东风谷早苗", 13, "守矢神社", character)
        self.assertEqual(location, "博丽神社")
        self.assertIn("约定", note)


if __name__ == "__main__":
    unittest.main()
