import unittest

from backend.services.npc_simulation_service import (
    format_npc_simulation_context,
    simulate_offscreen_npcs,
)


class NPCSimulationTests(unittest.TestCase):
    def setUp(self):
        self.npcs = [
            {"id": "npc_reimu", "name": "博丽灵梦", "location_name": "博丽神社", "active": True},
            {"id": "npc_marisa", "name": "雾雨魔理沙", "location_name": "雾雨魔法店", "active": True},
            {"id": "npc_sanae", "name": "东风谷早苗", "location_name": "守矢神社", "active": True},
        ]
        self.character = {
            "character_id": "npc-sim-test",
            "time": {"current_day": 1, "current_hour": 13},
            "npc_runtime": {},
        }

    def test_crossed_time_tick_generates_bounded_deterministic_activity(self):
        events = simulate_offscreen_npcs(
            self.character,
            elapsed_hours=7,
            npcs=self.npcs,
            max_events_per_tick=2,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(len(self.character["npc_simulation"]["events"]), 2)
        self.assertTrue(all(item["location"] for item in events))
        self.assertNotIn("locked_locations", self.character)
        repeated = simulate_offscreen_npcs(
            self.character,
            elapsed_hours=0,
            npcs=self.npcs,
            max_events_per_tick=2,
        )
        self.assertEqual(repeated, [])
        self.assertIn(events[0]["npc_name"], format_npc_simulation_context(self.character))

    def test_small_time_step_without_period_boundary_is_quiet(self):
        self.character["time"]["current_hour"] = 11
        events = simulate_offscreen_npcs(self.character, elapsed_hours=1, npcs=self.npcs)
        self.assertEqual(events, [])
