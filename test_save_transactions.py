import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.world_manager import (
    StaleTurnError,
    get_turn_receipt,
    load_character,
    record_turn_receipt,
    save_turn_bundle,
)


class SaveTransactionTests(unittest.TestCase):
    def test_turn_receipt_is_idempotent_and_bounded(self):
        character = {}
        for index in range(40):
            record_turn_receipt(character, f"turn-{index}", {"value": index})
        self.assertIsNone(get_turn_receipt(character, "turn-0"))
        self.assertEqual(get_turn_receipt(character, "turn-39"), {"value": 39})
        self.assertEqual(len(character["turn_receipts"]), 30)

    def test_bundle_commit_writes_both_files_and_clears_journal(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            character = {"character_id": "test", "world_id": "world_touhou", "profile": {"name": "测试"}, "conversation_history": []}
            tasks = {"active_tasks": [], "completed_tasks": []}
            with patch("backend.world_manager.get_characters_dir", return_value=root):
                save_turn_bundle("test", character, tasks)
            self.assertEqual(json.loads((root / "test.json").read_text(encoding="utf-8"))["character_id"], "test")
            self.assertTrue((root / "test_tasks.json").exists())
            self.assertFalse((root / "_transactions/test.json").exists())
            self.assertEqual(character["state_revision"], 1)
            self.assertEqual(tasks["state_revision"], 1)

    def test_stale_revision_does_not_overwrite_newer_save(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            persisted = {
                "character_id": "test",
                "world_id": "world_touhou",
                "profile": {"name": "新版"},
                "state_revision": 3,
            }
            (root / "test.json").write_text(
                json.dumps(persisted, ensure_ascii=False), encoding="utf-8"
            )
            (root / "test_tasks.json").write_text(
                json.dumps({"state_revision": 2}), encoding="utf-8"
            )
            with patch("backend.world_manager.get_characters_dir", return_value=root):
                with self.assertRaises(StaleTurnError):
                    save_turn_bundle(
                        "test",
                        {**persisted, "profile": {"name": "旧版"}},
                        {"state_revision": 2},
                        expected_character_revision=2,
                        expected_tasks_revision=2,
                    )
            loaded = json.loads((root / "test.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["profile"]["name"], "新版")
            self.assertEqual(loaded["state_revision"], 3)

    def test_dynamic_location_is_committed_with_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            characters = root / "characters"
            locations = root / "locations"
            character = {
                "character_id": "test",
                "world_id": "world_touhou",
                "profile": {"name": "测试"},
                "conversation_history": [],
            }
            tasks = {"active_tasks": [], "completed_tasks": []}
            addition = {
                "id": "dynamic-test",
                "name": "测试地点",
                "parent": "region-test",
                "type": "scene",
                "description": "事务地点",
                "icon": "地点",
            }
            with patch(
                "backend.world_manager.get_characters_dir", return_value=characters
            ), patch(
                "backend.world_manager.get_locations_dir", return_value=locations
            ):
                save_turn_bundle(
                    "test",
                    character,
                    tasks,
                    world_changes={"dynamic_locations": [addition]},
                )
            world_data = json.loads(
                (locations / "location_dynamic.json").read_text(encoding="utf-8")
            )
            self.assertEqual(world_data["locations"][0]["id"], "dynamic-test")
            self.assertFalse((characters / "_transactions/test.json").exists())


if __name__ == "__main__":
    unittest.main()
