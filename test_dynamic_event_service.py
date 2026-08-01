import json
import unittest
from pathlib import Path

from backend.services.dynamic_event_service import select_dynamic_event


class DynamicEventTests(unittest.TestCase):
    def test_bundled_event_pack_has_personal_and_ambient_coverage(self):
        path = Path(__file__).parent / "worlds/world_touhou/events.json"
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertGreaterEqual(len(data["personal_events"]), 40)
        self.assertGreaterEqual(len(data["ambient_events"]), 15)
        self.assertFalse(any("locked_locations" in item for item in data["personal_events"] + data["ambient_events"]))

    def test_explicit_personal_event_triggers_and_is_not_repeated(self):
        path = Path(__file__).parent / "worlds/world_touhou/events.json"
        character = {"character_id": "events", "time": {"current_day": 1, "current_hour": 8}}
        event = select_dynamic_event(
            character, path, "博丽神社", "帮灵梦调查御札和赛钱箱",
            [{"name": "博丽灵梦"}], "博丽灵梦",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event["source"], "dynamic_event_v1")
        repeated = select_dynamic_event(
            character, path, "博丽神社", "帮灵梦调查御札和赛钱箱",
            [{"name": "博丽灵梦"}], "博丽灵梦",
        )
        self.assertNotEqual(repeated and repeated.get("id"), event["id"])


if __name__ == "__main__":
    unittest.main()
