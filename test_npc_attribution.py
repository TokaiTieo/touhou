import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import app
from backend.routes.ghost import NPCDialogueRequest
from backend.security import SESSION_TOKEN, TOKEN_HEADER
from backend.services.context_budget_service import budget_context_sections
from backend.services.ai_service import compress_prompt
from backend.services.history_context_service import format_history_for_ai, select_history
from backend.services.npc_attribution_service import interaction_targets, prepare_model_memories
from backend.services.npc_agency_service import record_player_interaction
from backend.services.npc_memory_service import (
    apply_memory_corrections, build_auto_memory_updates, compress_npc_memory_bucket,
    delete_npc_memory, get_npc_memory_text, record_npc_memories,
)
from backend.services.save_migrations import migrate_save_schema
from backend.services.snapshot_service import prepare_restore_payload
from backend.services.story_summary_service import rebuild_story_summary
from backend.services.turn_context_service import format_npcs_for_ai
from backend.services.turn_history_service import append_turn_history
from backend.services.turn_models import TurnContext, TurnInput
from backend.services.turn_orchestrator import TurnOrchestrator
from backend.version import SAVE_SCHEMA_VERSION


A, B = "博丽灵梦", "雾雨魔理沙"
NPCS = [{"id": "npc_reimu", "name": A}, {"id": "npc_marisa", "name": B}]
ACTION = "只向博丽灵梦承诺明天赠送蓝色书签，不让魔理沙知晓。"
WRONG = "蓝色书签属于雾雨魔理沙"


def history_entry():
    return {"message_id": "a1", "speaker": "旁白", "role": "assistant", "scene": "博丽神社",
            "npc_id": "npc_reimu", "participants": [{"npc_id": "npc_reimu", "npc_name": A}],
            "visibility": {"scope": "private", "audience": ["npc_reimu"]}, "content": "她把书签藏进袖子。"}


class AttributionTests(unittest.TestCase):
    def test_history_preserves_identity_scene_and_visibility(self):
        rendered = json.loads(format_history_for_ai([history_entry()]))
        self.assertEqual(rendered["npc"]["npc_id"], "npc_reimu")
        self.assertEqual(rendered["participants"], history_entry()["participants"])
        self.assertEqual(rendered["visibility"]["scope"], "private")
        self.assertEqual(rendered["scene"], "博丽神社")

    def test_missing_participants_do_not_inherit_current_npc(self):
        record = json.loads(format_history_for_ai([{"speaker": "旁白", "content": "她收下礼物。"}]))
        self.assertIn("归属未知", record["participants"])
        self.assertIsNone(record["npc"])

    def test_browser_window_cannot_overwrite_or_duplicate_server_records(self):
        server = [history_entry()]
        browser = [{**history_entry(), "npc_id": "npc_marisa"}]
        self.assertIs(select_history(server, browser), server)
        self.assertEqual(len(format_history_for_ai(server * 2).splitlines()), 1)
        self.assertEqual(select_history([], browser), browser)

    def test_budget_truncates_body_not_identity(self):
        record = {**history_entry(), "content": "她的秘密。\n" * 1200}
        sections, _ = budget_context_sections({"history_text": format_history_for_ai([record])}, total_chars=550)
        result = json.loads(sections["history_text"])
        self.assertEqual(result["npc"]["npc_id"], "npc_reimu")
        self.assertEqual(result["visibility"]["scope"], "private")
        self.assertLessEqual(len(sections["history_text"]), 550)

    def test_profile_snapshot_has_one_owner(self):
        character = {"npc_runtime": {A: {"state": "持有蓝色书签", "note": "只有本人知晓"}, B: {"state": "在研究魔法"}}}
        text = format_npcs_for_ai([NPCS[0]], character)
        self.assertIn("npc_reimu", text)
        self.assertIn("只有本人知晓", text)
        self.assertNotIn("在研究魔法", text)

    def test_final_prompt_compression_does_not_emit_orphaned_record_tail(self):
        record = {**history_entry(), "content": "秘密" * 3000 + "ORPHAN_END"}
        prompt = "规则\n" + format_history_for_ai([record]) + "\n当前行动\n"
        compact, _ = compress_prompt(prompt, max_chars=4000)
        self.assertNotIn("ORPHAN_END", compact)
        self.assertTrue(compact.endswith("当前行动\n"))

    def test_scene_identity_mismatch_is_rejected(self):
        with self.assertRaises(ValidationError):
            NPCDialogueRequest(character_id="test", scene="神社", player_name="玩家", user_input="问好",
                               npc_id="npc_reimu", npc_name=A, scene_npcs=[{"id": "npc_reimu", "name": B}])

    def test_dialogue_rejects_mismatched_id_and_keeps_legacy_aliases(self):
        base = {"character_id": "test", "scene": "神社", "player_name": "玩家", "user_input": "问好"}
        with self.assertRaises(ValidationError):
            NPCDialogueRequest(**base, npc_id="npc_reimu", npc_name=B)
        request = NPCDialogueRequest(**base, npc_id="hakurei_reimu", npc_name=A)
        self.assertEqual(request.npc_id, "npc_reimu")
        custom = NPCDialogueRequest(**base, npc_id="custom_one", npc_name="自定义人物")
        self.assertEqual(custom.npc_name, "自定义人物")

    def test_private_action_has_no_bystander_fallback(self):
        self.assertEqual(interaction_targets(ACTION, scene_npcs=NPCS), [A])
        for action in ("观察两人，想起她的秘密", "不向博丽灵梦赠送礼物", "提到博丽灵梦的约定"):
            self.assertEqual(interaction_targets(action, scene_npcs=NPCS), [])

    def test_auto_memory_quotes_action_without_promoting_model_outcome(self):
        updates = build_auto_memory_updates({}, {"description": WRONG, "dynamic_event": {"title": "秘密"}}, ACTION, "神社", "auto_environment", scene_npcs=NPCS)
        self.assertEqual([item["npc_name"] for item in updates], [A])
        self.assertNotIn(WRONG, updates[0]["summary"])
        self.assertIn("不证明结果已发生", updates[0]["summary"])

    def test_bystander_never_receives_plan_progress_or_private_interaction(self):
        character = {"npc_agency": {"npcs": {B: {"plan_progress": 1, "last_player_interaction": "旧活动"}}}}
        before = copy.deepcopy(character["npc_agency"]["npcs"][B])
        record_player_interaction(character, scene_npcs=NPCS, scene="神社", action_text=ACTION, outcome=WRONG, turn_id="t1")
        self.assertEqual(character["npc_agency"]["npcs"][B], before)
        self.assertNotIn("plan_progress", character["npc_agency"]["npcs"][A])

    def test_model_claim_cannot_override_confirmed_fact_or_be_recalled(self):
        character = {}
        record_npc_memories(character, [{"npc_name": B, "summary": "魔理沙没有收到书签", "fact_key": "bookmark"}], "producer_console")
        proposals = prepare_model_memories([{"npc_name": B, "npc_id": "npc_reimu", "summary": WRONG, "fact_key": "bookmark", "confidence": 1, "source": "system"}], ACTION, A, NPCS)
        record_npc_memories(character, proposals, "npc_dialogue")
        bucket = character["npc_memories"][B]
        self.assertEqual(bucket[0]["truth_status"], "accepted")
        self.assertEqual(bucket[1]["attribution_status"], "pending")
        self.assertEqual(bucket[1]["source"], "model_proposal")
        self.assertNotIn(WRONG, get_npc_memory_text(character, B, query="书签"))
        compress_npc_memory_bucket(character, B, keep_recent=1, force=True)
        self.assertNotIn(WRONG, character["npc_memory_summaries"][B])
        self.assertNotIn(WRONG, get_npc_memory_text(character, query="书签"))

    def test_legitimate_memory_about_another_person_is_preserved(self):
        character = {}
        record_npc_memories(character, [{"npc_name": B, "summary": "灵梦告诉魔理沙她自己保管蓝色书签"}], "producer_console")
        text = get_npc_memory_text(character, B, query="书签")
        self.assertIn("npc_marisa", text)
        self.assertIn("灵梦告诉魔理沙", text)
        self.assertIn("不等于事实主语", text)

    def test_relationship_reason_cannot_carry_foreign_facts(self):
        character = {}
        turn = TurnInput(kind="npc_dialogue", character_id="test", scene="神社", player_name="玩家", action_text=ACTION, npc_name=A)
        result = {"relationship_update": f"{A}:友好({WRONG}),{B}:亲密(已经收下秘密礼物)"}
        TurnOrchestrator._apply_relationship(character, result, turn)
        self.assertNotIn(B, character["relationships_map"])
        self.assertNotIn(WRONG, str(character["relationships_map"]))

    def test_negative_relationship_keeps_its_original_direction(self):
        character = {}
        turn = TurnInput(kind="npc_dialogue", character_id="test", scene="神社", player_name="玩家", action_text="威胁灵梦", npc_name=A)
        TurnOrchestrator._apply_relationship(character, {"relationship_update": f"{A}:警惕(收到威胁)"}, turn)
        self.assertLess(character["relationship_progress"][A]["score"], 0)

    def test_committed_history_and_summary_keep_participants(self):
        turn = TurnInput(kind="npc_dialogue", character_id="test", scene="神社", player_name="玩家", npc_id="npc_reimu", npc_name=A, action_text=ACTION, record_history=True, turn_id="test-turn")
        context = TurnContext(turn=turn, character={}, tasks={})
        append_turn_history(context, {"description": "她记住了约定。"})
        rebuild_story_summary(context.character, force=True)
        reply = context.character["conversation_history"][-1]
        self.assertEqual(reply["participants"], [{"npc_id": "npc_reimu", "npc_name": A}])
        self.assertEqual(reply["npc_id"], "npc_reimu")
        self.assertIn("npc_reimu", context.character["story_summary"]["recent_arc"])

    def test_all_old_versions_upgrade_without_losing_originals(self):
        for version in range(1, SAVE_SCHEMA_VERSION):
            old = {"id": "old", "summary": "旧私密约定", "custom": {"keep": True}}
            character = {"save_version": version, "custom": "keep", "profile": {"body_data": "keep"},
                         "npc_memories": {A: [copy.deepcopy(old)]}, "npc_memory_archive": {B: [copy.deepcopy(old)]},
                         "npc_memory_layers": {A: {"facts": [copy.deepcopy(old)]}},
                         "npc_memory_legacy_summaries": {A: "原始摘要"}, "story_summary": {"version": 1, "recent_arc": "她有秘密"}}
            migrate_save_schema(character)
            self.assertEqual(character["save_version"], SAVE_SCHEMA_VERSION)
            self.assertEqual(character["custom"], "keep")
            self.assertEqual(character["profile"]["body_data"], "keep")
            for field, name in (("npc_memories", A), ("npc_memory_archive", B)):
                self.assertEqual(character[field][name][0]["summary"], old["summary"])
                self.assertEqual(character[field][name][0]["attribution_status"], "legacy_unverified")
            self.assertEqual(character["npc_memory_layers"][A]["facts"][0]["custom"], old["custom"])
            self.assertEqual(character["attribution_legacy_story_summary"]["recent_arc"], "她有秘密")
            self.assertFalse(migrate_save_schema(character))

    def test_correction_survives_archive_and_snapshot_without_changing_backup(self):
        character = {}
        record_npc_memories(character, [{"id": "wrong", "npc_name": B, "summary": WRONG}])
        character["npc_memory_legacy_summaries"] = {B: WRONG}
        compress_npc_memory_bucket(character, B, force=True)
        snapshot = {"character": copy.deepcopy(character), "tasks": {}}
        original = copy.deepcopy(snapshot)
        self.assertGreater(delete_npc_memory(character, B, "wrong"), 0)
        for branch in (False, True):
            restored = prepare_restore_payload("test", snapshot, lambda value: value, dict, branch=branch,
                                               memory_corrections=character["npc_memory_corrections"])
            self.assertNotIn(WRONG, get_npc_memory_text(restored["character"], B))
        self.assertEqual(snapshot, original)

    def test_confirmed_replacement_of_same_text_is_not_suppressed(self):
        character = {}
        record_npc_memories(character, [{"id": "pending", "npc_name": A, "summary": "玩家问好", "attribution_status": "pending"}])
        delete_npc_memory(character, A, "pending")
        record_npc_memories(character, [{"id": "reviewed", "npc_name": A, "summary": "玩家问好"}], "producer_console")
        apply_memory_corrections(character)
        self.assertIn("玩家问好", get_npc_memory_text(character, A))


class AttributionAPITests(unittest.TestCase):
    def test_persisted_correction_is_carried_into_restored_and_branched_saves(self):
        from backend.world_manager import create_character_snapshot, get_character_snapshots_dir, load_character
        with tempfile.TemporaryDirectory() as root, patch("backend.world_manager.get_characters_dir", return_value=Path(root)), TestClient(app) as client:
            headers = {TOKEN_HEADER: SESSION_TOKEN}
            created = client.post("/api/ghost/create_character", headers=headers, json={"profile": {"name": "回档归属测试", "gm_mode": True}})
            self.assertEqual(created.status_code, 200, created.text)
            character_id = created.json()["character_id"]
            added = client.post("/api/ghost/producer_console/upsert_npc_memory", headers=headers,
                                json={"character_id": character_id, "npc_name": B, "summary": WRONG})
            self.assertEqual(added.status_code, 200, added.text)
            memory_id = added.json()["memories"][-1]["id"]
            character = load_character(character_id)
            metadata = create_character_snapshot(character_id, character, label="纠错前", force=True)
            path = get_character_snapshots_dir(character_id) / f"{metadata['snapshot_id']}.json"
            original = path.read_bytes()
            deleted = client.post("/api/ghost/producer_console/delete_npc_memory", headers=headers,
                                  json={"character_id": character_id, "npc_name": B, "memory_id": memory_id})
            self.assertEqual(deleted.status_code, 200, deleted.text)
            for branch in (False, True):
                response = client.post("/api/ghost/snapshots/restore", headers=headers,
                                       json={"character_id": character_id, "snapshot_id": metadata["snapshot_id"], "branch": branch})
                self.assertEqual(response.status_code, 200, response.text)
                restored = load_character(response.json()["character_id"])
                self.assertNotIn(WRONG, get_npc_memory_text(restored, B))
                self.assertTrue(restored["npc_memory_corrections"][B])
            self.assertEqual(path.read_bytes(), original)

    def test_wrong_model_attribution_is_not_recalled_after_reload_or_npc_switch(self):
        with tempfile.TemporaryDirectory() as root, patch("backend.world_manager.get_characters_dir", return_value=Path(root)), TestClient(app) as client:
            headers = {TOKEN_HEADER: SESSION_TOKEN}
            created = client.post("/api/ghost/create_character", headers=headers, json={"profile": {"name": "归属回归测试", "identity": "幻想乡原住民"}})
            self.assertEqual(created.status_code, 200, created.text)
            character_id = created.json()["character_id"]
            request = {"character_id": character_id, "scene": "博丽神社", "player_name": "归属回归测试", "scene_npcs": NPCS, "record_history": True,
                       "npc_id": "npc_reimu", "npc_name": A, "user_input": ACTION, "turn_id": "private-one"}
            response = {"description": "灵梦悄悄记住了约定。", "memory_updates": [{"npc_name": B, "npc_id": "npc_marisa", "summary": WRONG, "confidence": 1}],
                        "relationship_update": f"{A}:友好(听到约定),{B}:亲密(收下书签)", "time_cost": 0}
            model = AsyncMock(return_value=json.dumps(response, ensure_ascii=False))
            with patch("backend.services.turn_workflow.call_ai_async", new=model):
                first = client.post("/api/ghost/npc_dialogue", headers=headers, json=request)
                repeated = client.post("/api/ghost/npc_dialogue", headers=headers, json=request)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json(), repeated.json())
            self.assertEqual(model.await_count, 1)
            saved = json.loads((Path(root) / f"{character_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["npc_memories"][B][0]["attribution_status"], "pending")
            self.assertNotIn(WRONG, get_npc_memory_text(saved, B, query="书签"))
            self.assertNotIn(B, saved["relationships_map"])
            self.assertNotIn("last_player_interaction", saved["npc_agency"]["npcs"].get(B, {}))
            self.assertEqual(saved["conversation_history"][-1]["npc_id"], "npc_reimu")
            with patch("backend.services.turn_workflow.call_ai_async", new=AsyncMock(return_value=json.dumps({"description": "魔理沙继续研究魔法。", "time_cost": 0}, ensure_ascii=False))) as next_model:
                second = client.post("/api/ghost/npc_dialogue", headers=headers, json={**request, "npc_id": "npc_marisa", "npc_name": B, "user_input": "今天过得如何？", "turn_id": "public-two"})
            self.assertEqual(second.status_code, 200, second.text)
            prompt = str(next_model.call_args)
            self.assertIn("npc_reimu", prompt)
            self.assertIn("npc_marisa", prompt)
            self.assertNotIn(WRONG, prompt)
            mismatch = client.post("/api/ghost/npc_dialogue", headers=headers, json={**request, "npc_name": B, "turn_id": "bad-id"})
            self.assertEqual(mismatch.status_code, 422)


if __name__ == "__main__":
    unittest.main()
