import asyncio
import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.services.history_context_service import format_history_record
from backend.services.npc_content_service import upgrade_installed_npcs, upgrade_npc_document
from backend.services.npc_identity_service import normalize_npcs, resolve_npc
from backend.services.npc_memory_service import get_npc_memory_text
from backend.services.save_migrations import migrate_save_schema
from backend.services.snapshot_service import prepare_restore_payload
from backend.services.turn_context_service import format_npcs_for_ai
from backend.version import SAVE_SCHEMA_VERSION


WORLD = Path(__file__).parent / "worlds/world_touhou"


def read_document(name):
    return json.loads((WORLD / "npcs" / name).read_text(encoding="utf-8-sig"))


def legacy_document():
    document = read_document("npc_index.json")
    corrections = read_document("canon_corrections.json")
    for item in document["npcs"]:
        correction = next((row for row in corrections["profiles"] if row["id"] == item["id"]), None)
        if not correction:
            continue
        for key, value in correction["fields"].items():
            if value["previous"]:
                item["profile"][key] = copy.deepcopy(value["previous"][0])
            else:
                item["profile"].pop(key, None)
        for key, value in corrections.get("record_fields", {}).get(item["id"], {}).items():
            item[key] = value["previous"][0]
    for alias, target in corrections["id_aliases"].items():
        duplicate = copy.deepcopy(next(item for item in document["npcs"] if item["id"] == target))
        duplicate["id"] = alias
        duplicate["name"] = next(name for name, full in corrections["aliases"].items() if full == duplicate["name"])
        document["npcs"].append(duplicate)
    document.pop("content_revision", None)
    document.pop("id_aliases", None)
    for alias in corrections["aliases"]:
        document["aliases"].pop(alias, None)
    return document


class CanonContentTests(unittest.TestCase):
    def test_all_corrections_match_the_shipped_profiles(self):
        document = read_document("npc_index.json")
        registry = {item["id"]: item for item in document["npcs"]}
        corrections = read_document("canon_corrections.json")
        self.assertEqual(len(document["npcs"]), 94)
        self.assertEqual(len(registry), 94)
        for correction in corrections["profiles"]:
            record = registry[correction["id"]]
            self.assertEqual(record["name"], correction["name"])
            for field, value in correction["fields"].items():
                self.assertEqual(record["profile"][field], value["value"], (record["name"], field))
                self.assertNotIn(field, ("measurements", "romance_adult_hook"))
                marker = {"background": "至今保持", "personality": "面对拥有独特魅力的玩家"}.get(field)
                if marker:
                    for old in value["previous"]:
                        suffix = old.partition(marker)[2]
                        # Correct factual props, not the relationship preference.
                        suffix = suffix.replace("愿意加入劲牙组吗", "愿意加入鬼杰组吗")
                        suffix = suffix.replace("她会推推眼镜", "她会整理讲义")
                        self.assertEqual(value["value"].partition(marker)[2], suffix)
        self.assertEqual(upgrade_npc_document(document, corrections), document)

    def test_verified_identity_ability_and_appearance_are_in_the_model_context(self):
        expected = {
            "npc_yachie": ("鬼杰组", "剥夺反抗意志"),
            "npc_zanmu": ("人鬼", "操纵虚无"),
            "npc_hisami": ("黄泉丑女", "令目标无处可逃"),
            "npc_sonbit": ("山犬", "操纵陷阱"),
            "npc_tobiko": ("猿神", "操纵野生猿猴"),
            "npc_junko": ("神灵", "纯化"),
            "npc_chen": ("猫又", "使用妖术"),
            "npc_tenma": ("管狐", "抓住灵魂弱点"),
            "npc_shou": ("虎", "招财进宝"),
            "npc_futo": ("尸解仙", "操纵风水"),
        }
        for identity, facts in expected.items():
            text = format_npcs_for_ai([{"id": identity}])
            for fact in facts:
                self.assertIn(fact, text)
        for identity, phrase in (("npc_hata", "粉色及腰长发"), ("npc_rin", "红色头发"),
                                 ("npc_koishi", "第三只眼位于身前"), ("npc_kagerou", "棕色及腰长发"),
                                 ("npc_reisen", "棕色皮鞋和白袜")):
            self.assertIn(phrase, resolve_npc(identity)["profile"]["description"])
        self.assertNotIn("候补", resolve_npc("npc_sanae")["profile"]["identity"])

    def test_legacy_names_and_ids_resolve_to_one_person_not_guessed_transliterations(self):
        for alias, short, target, full in (("npc_chiyoda", "千亦", "npc_takane", "天弓千亦"),
                                           ("npc_hisami_c", "日狭美", "npc_hisami", "豫母都日狭美")):
            for key in (alias, short, target, full):
                self.assertEqual(resolve_npc(key)["id"], target)
                self.assertEqual(resolve_npc(key)["name"], full)
            records = normalize_npcs([{"id": alias, "name": short}, {"id": target, "name": full}])
            self.assertEqual(len(records), 1)
        self.assertEqual(resolve_npc("npc_enoko")["name"], "天独铭")
        self.assertEqual(resolve_npc("npc_biten")["name"], "天肱")

    def test_old_content_merges_duplicates_preserves_mods_and_is_idempotent(self):
        document = legacy_document()
        primary = next(item for item in document["npcs"] if item["id"] == "npc_takane")
        primary["profile"]["measurements"] = "player-body"
        primary["profile"]["romance_adult_hook"] = "player-romance"
        primary["profile"]["description"] = "玩家定制的礼服"
        primary["custom"] = {"keep": True}
        alias = next(item for item in document["npcs"] if item["id"] == "npc_chiyoda")
        alias["profile"]["unknown_mod"] = "keep too"
        custom = {"id": "custom_chimata", "name": "千亦", "profile": {"identity": "玩家原创"}}
        document["npcs"].append(custom)
        before = copy.deepcopy(document)
        corrected = upgrade_npc_document(document, read_document("canon_corrections.json"))
        self.assertEqual(document, before)
        current = next(item for item in corrected["npcs"] if item["id"] == "npc_takane")
        self.assertEqual(current["location_id"], "loc_market")
        for field, value in (("measurements", "player-body"), ("romance_adult_hook", "player-romance"),
                             ("description", "玩家定制的礼服"), ("unknown_mod", "keep too")):
            self.assertEqual(current["profile"][field], value)
        self.assertIn(custom, corrected["npcs"])
        self.assertFalse(any(item["id"] in ("npc_chiyoda", "npc_hisami_c") for item in corrected["npcs"]))
        self.assertIn(alias, corrected["npc_content_archive"]["2026-10-29"]["npcs"])
        self.assertEqual(upgrade_npc_document(corrected, read_document("canon_corrections.json")), corrected)

    def test_custom_romance_suffix_survives_a_known_background_prefix_correction(self):
        document = legacy_document()
        npc = next(item for item in document["npcs"] if item["id"] == "npc_junko")
        npc["profile"]["background"] = npc["profile"]["background"].partition("至今保持")[0] + "至今保持玩家定制背景。"
        upgraded = upgrade_npc_document(document, read_document("canon_corrections.json"))
        current = next(item for item in upgraded["npcs"] if item["id"] == "npc_junko")
        self.assertIn("神灵", current["profile"]["background"])
        self.assertTrue(current["profile"]["background"].endswith("至今保持玩家定制背景。"))

    def test_installed_content_is_backed_up_once_and_concurrent_startup_is_safe(self):
        from backend.world_manager import _atomic_json_write
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory)
            path = installed / "npcs/npc_index.json"
            path.parent.mkdir()
            original = b"\xef\xbb\xbf" + json.dumps(legacy_document(), ensure_ascii=False, indent=2).encode("utf-8")
            path.write_bytes(original)
            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(lambda _: upgrade_installed_npcs(WORLD, installed, _atomic_json_write), range(3)))
            self.assertEqual(results.count(True), 1)
            backups = list((path.parent / "_migrations").glob("*.backup.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            first = path.read_bytes()
            self.assertFalse(upgrade_installed_npcs(WORLD, installed, _atomic_json_write))
            self.assertEqual(path.read_bytes(), first)

    def test_scene_api_has_one_chimata_at_market(self):
        from backend.routes.location import get_npcs_by_scene
        result = asyncio.run(get_npcs_by_scene("虹龙洞集市"))
        matches = [npc for npc in result["npcs"] if npc["name"] in ("千亦", "天弓千亦")]
        self.assertEqual([npc["id"] for npc in matches], ["npc_takane"])

    def test_startup_upgrades_the_existing_install_not_only_the_bundle(self):
        from backend import world_manager
        with tempfile.TemporaryDirectory() as directory:
            worlds = Path(directory) / "worlds"
            installed = worlds / "world_touhou"
            for relative in ("locations/location_base.json", "timeline.json", "worldview.txt"):
                target = installed / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((WORLD / relative).read_bytes())
            (worlds / "worlds_index.json").write_text("{}", encoding="utf-8")
            path = installed / "npcs/npc_index.json"
            path.parent.mkdir()
            path.write_text(json.dumps(legacy_document(), ensure_ascii=False), encoding="utf-8")
            with patch.object(world_manager, "WORLDS_DIR", worlds):
                world_manager.ensure_worlds_available()
                first = path.read_bytes()
                world_manager.ensure_worlds_available()
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.read_bytes(), first)
            self.assertEqual(len(document["npcs"]), 94)
            self.assertEqual(document["id_aliases"]["npc_hisami_c"], "npc_hisami")
            self.assertEqual(len(list((path.parent / "_migrations").glob("*.backup.json"))), 1)

    def test_identity_alias_validation_rejects_dangling_or_ambiguous_ids(self):
        from backend.services.content_validation_service import validate_editable_content
        document = read_document("npc_index.json")
        document["id_aliases"]["npc_hisami"] = "missing"
        result = validate_editable_content(WORLD, "npcs/npc_index.json", document)
        self.assertFalse(result["valid"])
        self.assertTrue(any("npc id alias collides" in error for error in result["errors"]))
        self.assertTrue(any("npc id alias target does not exist" in error for error in result["errors"]))

    def test_related_market_description_upgrades_but_custom_text_is_preserved(self):
        from backend.world_manager import _atomic_json_write
        field = read_document("canon_corrections.json")["location_fields"]["loc_market"]["fields"]["description"]
        for description in (field["previous"][0], "玩家定制的集市场景"):
            with tempfile.TemporaryDirectory() as directory:
                installed = Path(directory)
                npc_path = installed / "npcs/npc_index.json"
                npc_path.parent.mkdir()
                npc_path.write_bytes((WORLD / "npcs/npc_index.json").read_bytes())
                location_path = installed / "locations/location_base.json"
                location_path.parent.mkdir()
                location_path.write_text(json.dumps({"locations": [{"id": "loc_market", "name": "虹龙洞集市", "description": description}]}), encoding="utf-8")
                original = location_path.read_bytes()
                changed = upgrade_installed_npcs(WORLD, installed, _atomic_json_write)
                self.assertEqual(changed, description == field["previous"][0])
                current = json.loads(location_path.read_text(encoding="utf-8"))["locations"][0]
                self.assertEqual(current["description"], field["value"] if changed else description)
                if changed:
                    backup = next((location_path.parent / "_migrations").glob("*.backup.json"))
                    self.assertEqual(backup.read_bytes(), original)
                self.assertFalse(upgrade_installed_npcs(WORLD, installed, _atomic_json_write))


class CanonSaveTests(unittest.TestCase):
    def legacy_save(self, version=SAVE_SCHEMA_VERSION):
        alias, full = "千亦", "天弓千亦"
        return {"character_id": "canon-save", "save_version": version, "profile": {"name": "测试", "measurements": "keep"},
                "custom_mod": {"npc_id": "npc_chiyoda", "name": alias},
                "npc_memories": {alias: [{"id": "old", "summary": "一起在集市赏月", "owner_npc_id": "npc_chiyoda", "owner_npc_name": alias,
                                         "attribution_status": "confirmed", "truth_status": "accepted", "source": "producer_console"}],
                                 full: [{"id": "new", "summary": "一起经营集市", "attribution_status": "confirmed", "truth_status": "accepted"}]},
                "npc_memory_corrections": {alias: [{"memory_id": "wrong", "summaries": ["过期错误"], "originals": [{"owner_npc_id": "npc_chiyoda"}]}]},
                "npc_runtime": {"npc_chiyoda": {"state": "与玩家同行", "outfit": "定制服装"}},
                "relationship_progress": {alias: {"score": 85, "stage": "恋人", "attitude": "恋人", "updated_at": "2026-09-01"},
                                          full: {"score": 20, "attitude": "友好", "updated_at": "2026-08-01"}},
                "relationship_dimensions": {alias: {"status": "lover", "npc_id": "npc_chiyoda", "npc_name": alias}, full: {"status": "unconfirmed"}},
                "relationship_proposals": [{"id": "p", "npc_id": "npc_chiyoda", "npc_name": alias, "status": "pending"}],
                "life_state": {"diaries": {"npc_chiyoda": [{"id": "d", "owner": {"npc_id": "npc_chiyoda", "npc_name": alias}}]},
                               "known_preferences": {alias: {"likes": ["茶"]}}, "npc_resources": {alias: {"currency": 12}},
                               "appointments": [{"id": "a", "npc_id": "npc_chiyoda", "npc_name": alias}]},
                "conversation_history": [{"message_id": "msg", "speaker": alias, "npc_id": "npc_chiyoda", "content": "她仍穿着旧衣服。",
                                          "participants": [{"npc_id": "npc_chiyoda", "npc_name": alias}], "visibility": {"audience": ["npc_chiyoda"]}}]}

    def test_every_save_version_merges_without_resetting_romance_state_or_custom_fields(self):
        for version in range(1, SAVE_SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                character = self.legacy_save(version)
                before = copy.deepcopy(character)
                self.assertTrue(migrate_save_schema(character))
                full = "天弓千亦"
                self.assertEqual(character["save_version"], SAVE_SCHEMA_VERSION)
                self.assertEqual(character["custom_mod"], before["custom_mod"])
                self.assertEqual(character["profile"], before["profile"])
                self.assertEqual(character["conversation_history"], before["conversation_history"])
                self.assertEqual(len(character["npc_memories"][full]), 2)
                self.assertEqual(character["npc_memories"][full][1]["owner_npc_id"], "npc_takane")
                self.assertEqual(character["relationship_progress"][full]["score"], 85)
                self.assertIn(character["relationship_dimensions"][full]["status"], ("lover", "legacy_confirmed"))
                self.assertEqual(character["npc_runtime"][full]["outfit"], "定制服装")
                self.assertIn("npc_takane", character["life_state"]["diaries"])
                self.assertEqual(character["life_state"]["known_preferences"][full]["likes"], ["茶"])
                self.assertEqual(character["life_state"]["appointments"][0]["npc_id"], "npc_takane")
                self.assertEqual(character["npc_memory_corrections"][full][0]["originals"], [{"owner_npc_id": "npc_chiyoda"}])
                current = copy.deepcopy(character)
                self.assertFalse(migrate_save_schema(character))
                self.assertEqual(character, current)

    def test_legacy_history_metadata_normalizes_without_rewriting_archive_content(self):
        old = self.legacy_save()["conversation_history"][0]
        before = copy.deepcopy(old)
        record = json.loads(format_history_record(old))
        self.assertEqual(record["npc"], {"npc_id": "npc_takane", "npc_name": "天弓千亦"})
        self.assertEqual(record["participants"][0]["npc_id"], "npc_takane")
        self.assertEqual(record["visibility"]["audience"], ["npc_takane"])
        self.assertEqual(record["content"], old["content"])
        self.assertEqual(old, before)
        record = json.loads(format_history_record({**old, "participants": ["千亦", "npc_chiyoda"]}))
        self.assertEqual(record["participants"], ["天弓千亦", "npc_takane"])

    def test_rollback_and_branch_keep_identity_merge_and_inherited_corrections(self):
        from backend.world_manager import ensure_character_fields
        character = self.legacy_save()
        character["npc_memories"]["千亦"].append({"id": "wrong", "summary": "过期错误", "attribution_status": "confirmed"})
        payload = {"character": character, "tasks": {"active_tasks": []}}
        original = copy.deepcopy(payload)
        for branch in (False, True):
            restored = prepare_restore_payload("canon-save", payload, ensure_character_fields, dict, branch=branch,
                                               memory_corrections=character["npc_memory_corrections"])["character"]
            self.assertNotIn("千亦", restored["npc_memories"])
            self.assertNotIn("过期错误", get_npc_memory_text(restored, "千亦"))
            self.assertEqual(restored["relationship_progress"]["天弓千亦"]["score"], 85)
        self.assertEqual(payload, original)

    def test_old_api_ids_are_accepted_but_cross_person_id_mismatches_are_not(self):
        from backend.routes.ghost import NPCDialogueRequest
        from pydantic import ValidationError
        base = {"character_id": "canon-save", "scene": "虹龙洞集市", "player_name": "测试", "user_input": "问好"}
        request = NPCDialogueRequest(**base, npc_id="npc_chiyoda", npc_name="千亦")
        self.assertEqual((request.npc_id, request.npc_name), ("npc_takane", "天弓千亦"))
        with self.assertRaises(ValidationError):
            NPCDialogueRequest(**base, npc_id="npc_chiyoda", npc_name="豫母都日狭美")

    def test_alias_memory_collisions_keep_both_originals_and_deduplicate_ids(self):
        character = self.legacy_save()
        character["npc_memories"]["天弓千亦"][0]["id"] = "old"
        before = copy.deepcopy(character["npc_memories"])
        migrate_save_schema(character)
        records = character["npc_memories"]["天弓千亦"]
        self.assertEqual({item["summary"] for item in records}, {"一起在集市赏月", "一起经营集市"})
        self.assertEqual(len({item["id"] for item in records}), 2)
        self.assertEqual(character["npc_identity_archive"]["npc_memories"], before)
        self.assertFalse(migrate_save_schema(character))

    def test_loading_a_current_save_also_persists_identity_upgrade_once(self):
        from backend.world_manager import load_character
        before = self.legacy_save()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "canon-save.json"
            path.write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
            with patch("backend.world_manager.get_characters_dir", return_value=root):
                loaded = load_character("canon-save")
                self.assertIn("天弓千亦", loaded["npc_memories"])
                first = path.read_bytes()
                load_character("canon-save")
                self.assertEqual(path.read_bytes(), first)
            backups = list((root / "_migrations").rglob("*.backup.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), before)

    def test_v13_story_summary_is_archived_without_replacing_the_current_summary(self):
        character = self.legacy_save(13)
        summary = {"version": 1, "recent_arc": "她有秘密", "custom": "keep"}
        character["story_summary"] = copy.deepcopy(summary)
        migrate_save_schema(character)
        self.assertEqual(character["attribution_legacy_story_summary"], summary)
        self.assertEqual(character["story_summary"], summary)
        self.assertFalse(migrate_save_schema(character))


if __name__ == "__main__":
    unittest.main()
