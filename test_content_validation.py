import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.services.content_validation_service import (
    list_editable_content,
    read_editable_content,
    save_editable_content,
    validate_editable_content,
    validate_world_content,
)


class ContentValidationTests(unittest.TestCase):
    @property
    def world_root(self):
        return Path(__file__).parent / "worlds" / "world_touhou"

    def test_bundled_content_matches_schemas_and_references(self):
        result = validate_world_content(self.world_root)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["counts"]["locations"], 20)
        self.assertGreaterEqual(result["counts"]["npcs"], 90)
        self.assertGreaterEqual(result["counts"]["world_info_entries"], 60)

    def test_duplicate_and_broken_reference_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for relative in (
                "locations/location_base.json",
                "npcs/npc_index.json",
                "npc_schedules.json",
                "events.json",
                "incidents.json",
                "world_info.json",
            ):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((self.world_root / relative).read_bytes())
            npc_path = temp_root / "npcs" / "npc_index.json"
            document = json.loads(npc_path.read_text(encoding="utf-8-sig"))
            duplicate = copy.deepcopy(document["npcs"][0])
            duplicate["location_id"] = "missing_location"
            document["npcs"].append(duplicate)
            npc_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = validate_world_content(temp_root)
            self.assertFalse(result["valid"])
            self.assertTrue(any("duplicate npc id" in error for error in result["errors"]))
            self.assertTrue(any("npc location does not exist" in error for error in result["errors"]))

    def test_content_editor_whitelist_validation_and_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir) / "world"
            backup_root = Path(temp_dir) / "backups"
            for relative in (
                "world.json", "locations/location_base.json", "npcs/npc_index.json",
                "npc_schedules.json", "events.json", "incidents.json", "world_info.json",
            ):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((self.world_root / relative).read_bytes())
            files = list_editable_content(temp_root)
            self.assertTrue(any(item["path"] == "npcs/npc_index.json" for item in files))
            document = read_editable_content(temp_root, "world_info.json")["content"]
            self.assertTrue(validate_editable_content(temp_root, "world_info.json", document)["valid"])
            document["content_editor_test"] = True
            saved = save_editable_content(temp_root, backup_root, "world_info.json", document)
            self.assertTrue(saved["saved"])
            self.assertTrue(Path(saved["backup"]).exists())
            saved_document = json.loads((temp_root / "world_info.json").read_text(encoding="utf-8"))
            self.assertTrue(saved_document["content_editor_test"])
            with self.assertRaises(ValueError):
                read_editable_content(temp_root, "../sessions/characters/player.json")
