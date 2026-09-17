import asyncio
import copy
import hashlib
import json
import re
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import system
from backend.services.npc_identity_service import load_npc_document, normalize_npcs
from backend.services.npc_memory_service import get_npc_memory_text, record_npc_memories
from backend.services.relationship_service import apply_relationship_delta, parse_relationship_changes
from backend.services.save_migrations import migrate_save_schema
from backend.version import APP_VERSION, SAVE_SCHEMA_VERSION


ROOT = Path(__file__).parent
NAME = "帕秋莉"
ALIAS = "帕秋莉·诺蕾姬"


class StaticBoundaryTests(unittest.TestCase):
    def test_assets_and_legacy_urls_work_but_private_files_are_unreachable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("js", "css", "static", "avatars", "backend", "worlds", "logs", ".tmp", "config"):
                (root / folder).mkdir()
            for relative in (".env", "backend/api.py", "worlds/save.json", "logs/touhou.log", ".tmp/helper.py", "config/api_key.dat", "node.msi"):
                (root / relative).write_text("synthetic-private-marker", encoding="utf-8")
            for relative in ("static/touhou-favicon.svg", "avatars/npc_patchouli.png", "js/main.js", "css/app.css"):
                (root / relative).write_text("public-asset", encoding="utf-8")
            app = FastAPI()
            with patch.multiple(system, BASE_DIR=root, js_dir=root / "js", css_dir=root / "css", avatars_dir=root / "avatars"):
                system.mount_static_files(app)
            with TestClient(app) as client:
                for url in ("/static/touhou-favicon.svg", "/static/static/touhou-favicon.svg", "/avatars/npc_patchouli_n.png", "/js/main.js", "/css/app.css"):
                    self.assertEqual(client.get(url).text, "public-asset", url)
                for suffix in (".env", "backend/api.py", "worlds/save.json", "logs/touhou.log", ".tmp/helper.py", "config/api_key.dat", "node.msi"):
                    for prefix in ("/static/", "/static/static/", "/static/%2e%2e/", "/js/%2e%2e/", "/avatars/%2e%2e/"):
                        response = client.get(prefix + suffix)
                        self.assertEqual(response.status_code, 404, prefix + suffix)
                        self.assertNotIn("synthetic-private-marker", response.text)


class NPCIdentityTests(unittest.TestCase):
    def legacy_save(self):
        return {
            "save_version": 9,
            "custom_mod": {"name": ALIAS, "power": 999},
            "profile": {"measurements": "custom-body", "romance_adult_hook": "custom-romance"},
            "npc_memories": {NAME: [{"id": "same", "summary": "一起研究火符"}], ALIAS: [{"id": "same", "summary": "一起阅读水符"}]},
            "npc_memory_archive": {ALIAS: [{"id": "old", "archive_id": "archived", "summary": "旧日图书馆约定"}]},
            "npc_memory_summaries": {NAME: "火符印象", ALIAS: "水符印象"},
            "relationships_map": {NAME: "友好", ALIAS: "信赖"},
            "relationship_progress": {
                NAME: {"score": 30, "attitude": "友好", "updated_at": "2026-01-01", "custom": 1},
                ALIAS: {"score": 60, "attitude": "信赖", "updated_at": "2026-02-01", "legacy_custom": 2},
            },
            "npc_runtime": {"npc_patchouli_n": {"temporary_location": "博丽神社"}},
            "npc_agency": {"npcs": {ALIAS: {"plan_progress": 2}}, "rumor_receipts": {NAME: ["a"], ALIAS: ["b"]},
                           "social_graph": {"old": {"npcs": [ALIAS, "博丽灵梦"], "shared_scenes": 2}}},
            "open_events": [{"npc_name": ALIAS, "title": "图书馆约定"}],
            "semantic_memory_index": {NAME: {"old": True}, ALIAS: {"old": True}},
            "conversation_history": [{"message_id": "stable", "speaker": ALIAS, "content": "旧对话保留原文"}],
        }

    def test_v9_merge_is_lossless_non_additive_and_idempotent(self):
        character = self.legacy_save()
        before = copy.deepcopy(character)
        self.assertTrue(migrate_save_schema(character))
        self.assertEqual(character["save_version"], SAVE_SCHEMA_VERSION)
        self.assertEqual(character["custom_mod"], before["custom_mod"])
        self.assertEqual(character["profile"], before["profile"])
        self.assertEqual(character["conversation_history"], before["conversation_history"])
        memories = character["npc_memories"][NAME]
        self.assertEqual(len(memories), 2)
        self.assertEqual(len({item["id"] for item in memories}), 2)
        self.assertNotIn(ALIAS, character["npc_memories"])
        self.assertEqual(character["npc_identity_archive"]["npc_memories"], before["npc_memories"])
        self.assertEqual(character["relationship_progress"][NAME]["score"], 60)
        self.assertEqual(character["relationship_progress"][NAME]["custom"], 1)
        self.assertEqual(character["relationship_progress"][NAME]["legacy_custom"], 2)
        self.assertEqual(character["relationships_map"][NAME], "信赖")
        self.assertEqual(character["npc_agency"]["rumor_receipts"][NAME], ["a", "b"])
        self.assertEqual(character["open_events"][0]["npc_name"], NAME)
        self.assertEqual(character["semantic_memory_index"], {})
        stable = copy.deepcopy(character)
        self.assertFalse(migrate_save_schema(character))
        self.assertEqual(character, stable)
        text = get_npc_memory_text(character, ALIAS, limit=10, query="图书馆")
        for phrase in ("火符", "水符", "旧日图书馆约定"):
            self.assertIn(phrase, text)

    def test_all_old_versions_and_alias_only_saves_upgrade(self):
        for version in range(1, SAVE_SCHEMA_VERSION + 1):
            character = {"save_version": version, "npc_memories": {ALIAS: ["旧格式记忆"]}}
            migrate_save_schema(character)
            self.assertEqual(character["npc_memories"][NAME], ["旧格式记忆"])
            self.assertFalse(migrate_save_schema(character))

    def test_runtime_writes_and_legacy_requests_use_canonical_identity(self):
        from backend.routes.ghost import NPCDialogueRequest
        request = NPCDialogueRequest(character_id="test", scene="红魔馆", player_name="测试", npc_id="npc_patchouli_n", npc_name=ALIAS, user_input="问好")
        self.assertEqual((request.npc_id, request.npc_name), ("npc_patchouli", NAME))
        character = {}
        record_npc_memories(character, [{"npc_name": ALIAS, "summary": "一同研究魔法"}])
        self.assertEqual(list(character["npc_memories"]), [NAME])
        apply_relationship_delta(character, ALIAS, 2, "问好")
        self.assertEqual(list(character["relationship_progress"]), [NAME])
        self.assertEqual(parse_relationship_changes(ALIAS + ":友好"), {NAME: "友好"})

    def test_loading_old_save_persists_upgrade_and_keeps_original_backup_once(self):
        from backend.world_manager import load_character
        before = self.legacy_save()
        before["character_id"] = "patchouli-upgrade-test"
        before["profile"]["name"] = "迁移测试者"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / (before["character_id"] + ".json")
            path.write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
            with patch("backend.world_manager.get_characters_dir", return_value=root):
                loaded = load_character(before["character_id"])
                self.assertEqual(loaded["save_version"], SAVE_SCHEMA_VERSION)
                first = path.read_bytes()
                load_character(before["character_id"])
                self.assertEqual(path.read_bytes(), first)
            backups = list((root / "_migrations").rglob("*.backup.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), before)

    def test_old_npc_index_is_normalized_in_both_orders_without_mod_loss(self):
        primary = {"id": "npc_patchouli", "name": NAME, "profile": {"custom": "primary"}}
        legacy = {"id": "npc_patchouli_n", "name": ALIAS, "profile": {"custom": "legacy", "mod_field": 3}}
        custom = {"id": "npc_player_created", "name": NAME}
        for records in ([primary, legacy, custom], [legacy, primary, custom]):
            original = copy.deepcopy(records)
            merged = normalize_npcs(records)
            self.assertEqual(len(merged), 2)
            self.assertEqual(merged[0]["profile"], {"custom": "primary", "mod_field": 3})
            self.assertIn(legacy, merged[0]["legacy_identity_records"])
            self.assertEqual(records, original)
            self.assertEqual(normalize_npcs(merged), merged)

    def test_scene_api_normalizes_legacy_installed_content(self):
        from backend.routes.location import get_npcs_by_scene
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "npc_index.json"
            records = [{"id": identity, "name": name, "location_id": "loc_scarlet"}
                       for identity, name in (("npc_patchouli", NAME), ("npc_patchouli_n", ALIAS))]
            path.write_text(json.dumps({"npcs": records}), encoding="utf-8")
            with patch("backend.world_manager.get_npcs_dir", return_value=Path(directory)):
                result = asyncio.run(get_npcs_by_scene("红魔馆"))
            self.assertEqual([item["id"] for item in result["npcs"]], ["npc_patchouli"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["npcs"], records)


class AssetConsistencyTests(unittest.TestCase):
    def test_content_has_no_duplicate_json_keys_or_legacy_npc_records(self):
        def no_duplicate_keys(pairs):
            result = {}
            for key, value in pairs:
                self.assertNotIn(key, result, key)
                result[key] = value
            return result
        for path in (ROOT / "worlds/world_touhou").rglob("*.json"):
            if "sessions" not in path.parts:
                json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=no_duplicate_keys)
        document = load_npc_document(ROOT / "worlds/world_touhou/npcs/npc_index.json")
        records = [item for item in document["npcs"] if item["id"] == "npc_patchouli"]
        self.assertEqual(len(records), 1)
        self.assertNotIn("legacy_identity_records", records[0])
        self.assertEqual(document["aliases"][ALIAS], NAME)
        self.assertFalse((ROOT / "avatars/npc_patchouli_n.png").exists())

    def test_branding_hashes_and_icon_sizes_match(self):
        manifest = json.loads((ROOT / "static/branding.json").read_text(encoding="utf-8"))
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)
        data = (ROOT / "static/touhou.ico").read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 7))
        for index, size in enumerate(manifest["sizes"]):
            width, height, _, _, planes, bits, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
            self.assertEqual((width or 256, height or 256, planes, bits), (size, size, 1, 32))
            image = data[offset:offset + length]
            self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack_from(">II", image, 16), (size, size))
        self.assertIn("'static' / 'touhou.ico'", (ROOT / "api_release.spec").read_text(encoding="utf-8"))

    def test_documentation_and_public_branding_match_current_version(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"当前版本：`v{APP_VERSION}`", readme)
        self.assertIn(f"存档结构：`V{SAVE_SCHEMA_VERSION}`", readme)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(re.search(r"^## v(\S+)", changelog, re.M)[1], APP_VERSION)
        self.assertIn("verify-test-package.ps1", readme)
        for path in [ROOT / "index.html", *ROOT.glob("js/**/*.js"), *ROOT.glob("css/*.css")]:
            content = path.read_text(encoding="utf-8")
            self.assertNotRegex(content.lower(), r"lazy?noodle|laztnoodle|/static/static/")
        self.assertFalse(list(ROOT.glob("*.msi")))


if __name__ == "__main__":
    unittest.main()
