import unittest

from backend.services.progression_service import apply_progression_updates, ensure_inventory_state
from backend.services.relationship_service import ensure_relationship_progress


class ProgressionTests(unittest.TestCase):
    def test_legacy_inventory_is_indexed_and_consumable(self):
        character = {
            "inventory": ["伤药"],
            "resources": {"道具": ["御札"]},
            "player_state": {"受伤": 35, "疲劳": 10, "灵力": 20},
        }
        state = ensure_inventory_state(character)
        self.assertEqual({item["name"] for item in state["items"]}, {"伤药", "御札"})
        result = {"inventory_updates": [{"action": "use", "name": "伤药", "quantity": 1}]}
        apply_progression_updates(character, result, "博丽神社", "使用伤药")
        self.assertEqual(character["player_state"]["受伤"], 15)
        self.assertFalse(any(item["name"] == "伤药" for item in state["items"]))

    def test_reputation_and_relationship_migrate_additively(self):
        character = {"reputation": {}, "relationships_map": {"博丽灵梦": "友好(共同调查)"}}
        result = {"task_updates": [{"action": "complete"}], "reputation_updates": []}
        delta = apply_progression_updates(character, result, "博丽神社", "完成调查")
        self.assertEqual(character["reputation"]["博丽神社"], 3)
        self.assertTrue(delta["reputation"])
        progress = ensure_relationship_progress(character)
        self.assertEqual(progress["博丽灵梦"]["stage"], "友好")


if __name__ == "__main__":
    unittest.main()
