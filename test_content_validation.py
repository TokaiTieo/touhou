import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.services.content_validation_service import validate_world_content


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
