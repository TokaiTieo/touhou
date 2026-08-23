import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.services.save_migrations import migrate_save_schema
from backend.services.save_upgrade_service import write_upgrade_artifacts
from backend.version import SAVE_SCHEMA_VERSION
from backend.world_manager import ensure_character_fields


class SaveMigrationTests(unittest.TestCase):
    def test_v1_through_v6_fixtures_upgrade_additively_and_idempotently(self):
        fixture_dir = Path(__file__).parent / "test_fixtures" / "saves"
        for version in range(1, 7):
            with self.subTest(version=version):
                character = json.loads((fixture_dir / f"v{version}.json").read_text(encoding="utf-8"))
                custom = copy.deepcopy(character["legacy_custom"])
                upgraded = ensure_character_fields(character)
                upgraded.pop("_migrated", None)
                self.assertEqual(upgraded["save_version"], SAVE_SCHEMA_VERSION)
                self.assertEqual(upgraded["legacy_custom"], custom)
                self.assertEqual(upgraded["world_id"], "world_touhou")
                self.assertIn("story_summary", upgraded)
                self.assertEqual(upgraded["story_director"]["exploration_policy"], "open")
                self.assertIn("npc_runtime", upgraded)
                self.assertIn("model_runtime", upgraded)
                self.assertIn("spellcard_loadout", upgraded)
                self.assertIn("progression_milestones", upgraded)
                stable = copy.deepcopy(upgraded)
                ensure_character_fields(upgraded).pop("_migrated", None)
                self.assertEqual(upgraded, stable)

    def test_upgrade_artifacts_preserve_source_and_report_added_fields(self):
        before = {
            "save_version": 3,
            "character_id": "artifact-test",
            "profile": {"name": "旧档"},
            "custom_mod": {"untouched": True},
        }
        after = copy.deepcopy(before)
        ensure_character_fields(after).pop("_migrated", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            report = write_upgrade_artifacts(Path(temp_dir), "artifact-test", before, after)
            artifact_dir = Path(temp_dir) / "_migrations" / "artifact-test"
            backups = list(artifact_dir.glob("*.backup.json"))
            reports = list(artifact_dir.glob("*.report.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(len(reports), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), before)
            self.assertEqual(report["removed_fields"], [])
            self.assertIn("story_summary", report["added_fields"])
            write_upgrade_artifacts(Path(temp_dir), "artifact-test", before, after)
            self.assertEqual(len(list(artifact_dir.glob("*.backup.json"))), 1)

    def test_v4_save_upgrades_additively_and_only_once(self):
        character = {
            "save_version": 4,
            "profile": {"name": "旧角色", "custom_field": "保留"},
            "incident_state": {"id": "touhou_rift", "status": "active"},
            "unknown_mod_data": {"enabled": True}
        }
        original_mod_data = copy.deepcopy(character["unknown_mod_data"])
        self.assertTrue(migrate_save_schema(character))
        self.assertEqual(character["save_version"], SAVE_SCHEMA_VERSION)
        self.assertEqual(character["unknown_mod_data"], original_mod_data)
        self.assertIn("skill_experience", character)
        self.assertIn("story_summary", character)
        self.assertIn("inventory_state", character)
        self.assertIn("usage_stats", character)
        self.assertEqual([item["version"] for item in character["migration_history"]], [5, 6, 7])
        self.assertFalse(migrate_save_schema(character))
        self.assertEqual(len(character["migration_history"]), 3)

    def test_legacy_conversation_messages_gain_rewrite_fields_additively(self):
        character = {
            "save_version": SAVE_SCHEMA_VERSION,
            "profile": {"name": "旧角色"},
            "conversation_history": [{
                "speaker": "旁白",
                "content": "原有剧情文本",
                "custom_message_data": {"keep": True},
            }],
        }
        upgraded = ensure_character_fields(character)
        message = upgraded["conversation_history"][0]
        self.assertTrue(message["message_id"].startswith("msg_"))
        self.assertEqual(message["rewrite_candidates"], [])
        self.assertEqual(message["custom_message_data"], {"keep": True})

    def test_partial_v6_save_is_repaired_without_overwriting_values(self):
        character = {"save_version": 6, "usage_stats": {"requests": 9}, "custom": "keep"}
        self.assertTrue(migrate_save_schema(character))
        self.assertEqual(character["usage_stats"], {"requests": 9})
        self.assertEqual(character["custom"], "keep")
        self.assertIn("event_flags", character)
        self.assertFalse(migrate_save_schema(character))


if __name__ == "__main__":
    unittest.main()
