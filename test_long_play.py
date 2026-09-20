import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.storage_paths import InvalidStoragePath, FutureSaveVersion, contained_path, require_identifier
from backend.services.save_health_service import inspect_character_payload
from backend.services.snapshot_service import snapshot_signature
from backend.version import SAVE_SCHEMA_VERSION
from backend import world_manager as storage


def character(name="测试"):
    return {"character_id": "test", "profile": {"name": name}, "save_version": SAVE_SCHEMA_VERSION,
            "conversation_history": [], "player_state": {"疲劳": 0}, "inventory_state": {"items": []}}


class StorageSafetyTests(unittest.TestCase):
    def test_ids_and_paths_reject_traversal_without_file_size_limit(self):
        for value in ("../outside", "..\\outside", "C:\\outside", "CON", "nul.txt", "test:stream", "bad\x00", "trailing."):
            with self.subTest(value=value), self.assertRaises(InvalidStoragePath):
                require_identifier(value)
        self.assertEqual(require_identifier("旧角色-01"), "旧角色-01")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(InvalidStoragePath):
                contained_path(directory, "..", "outside")
        self.assertNotEqual(inspect_character_payload({**character(), "large_custom": "x" * 2_000_000})["status"], "critical")

    def test_future_version_is_read_only_even_for_direct_writes(self):
        value = {**character(), "save_version": SAVE_SCHEMA_VERSION + 1}
        self.assertTrue(inspect_character_payload(value)["read_only"])
        with self.assertRaises(FutureSaveVersion):
            storage.ensure_character_fields(value)
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)):
            path = Path(directory) / "test.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            original = path.read_bytes()
            for operation in (lambda: storage.load_character("test"), lambda: storage.save_character("test", character()),
                              lambda: storage.save_turn_bundle("test", character(), {}), lambda: storage.save_tasks("test", {})):
                with self.assertRaises(FutureSaveVersion):
                    operation()
                self.assertEqual(path.read_bytes(), original)

    def test_import_remaps_id_and_preserves_original(self):
        from backend.routes.records import import_character
        value = {**character(), "character_id": "../outside", "custom": {"keep": True}}
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)), patch("backend.routes.records.get_characters_dir", return_value=Path(directory)):
            result = asyncio.run(import_character({"character_data": value}))
            loaded = storage.load_character(result["character_id"])
            self.assertEqual(loaded["custom"], value["custom"])
            self.assertEqual(loaded["import_origin"]["character_id"], "../outside")
            backups = list(Path(directory).glob("_migrations/*/*.backup.json"))
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), value)


class SnapshotConsistencyTests(unittest.TestCase):
    def test_signature_covers_attributes_inventory_tasks_and_old_message_edits(self):
        original = character()
        for key, value in (("player_state", {"疲劳": 80}), ("inventory_state", {"items": ["御札"]}), ("relationships_map", {"灵梦": "友好"})):
            self.assertNotEqual(snapshot_signature(original), snapshot_signature({**original, key: value}))
        self.assertNotEqual(snapshot_signature(original, {"active_tasks": []}), snapshot_signature(original, {"active_tasks": ["调查"]}))

    def test_restore_uses_recoverable_transaction_and_keeps_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)):
            old = character("之前")
            storage.save_turn_bundle("test", old, {"active_tasks": [{"id": "old"}]})
            snapshot = storage.list_character_snapshots("test")[0]["snapshot_id"]
            storage.save_turn_bundle("test", character("之后"), {"active_tasks": [{"id": "new"}]})
            storage.restore_character_snapshot("test", snapshot)
            self.assertEqual(storage.load_character("test")["profile"]["name"], "之前")
            self.assertEqual(storage.load_tasks("test")["active_tasks"][0]["id"], "old")
            self.assertTrue(any(item["label"] == "恢复前备份" for item in storage.list_character_snapshots("test")))

    def test_interrupted_restore_replays_both_files_and_changes_workflow_epoch(self):
        from backend.services.turn_models import TurnInput
        from backend.services.turn_orchestrator import TurnOrchestrator
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)):
            old = storage.ensure_character_fields(character("old"))
            storage.save_turn_bundle("test", old, {"active_tasks": [{"id": "old"}]})
            snapshot = storage.list_character_snapshots("test")[0]["snapshot_id"]
            storage.save_turn_bundle("test", storage.ensure_character_fields(character("new")), {"active_tasks": [{"id": "new"}]})
            writer = storage._atomic_json_write
            def fail_tasks(path, value):
                if path.name == "test_tasks.json":
                    raise OSError("simulated crash after character write")
                return writer(path, value)
            with patch.object(storage, "_atomic_json_write", side_effect=fail_tasks), self.assertRaises(OSError):
                storage.restore_character_snapshot("test", snapshot)
            restored = storage.load_character("test")
            self.assertEqual(restored["profile"]["name"], "old")
            self.assertEqual(storage.load_tasks("test")["active_tasks"][0]["id"], "old")
            self.assertFalse((Path(directory) / "_transactions" / "test.json").exists())
            turn = TurnInput(kind="environment", character_id="test", scene="博丽神社", player_name="old", turn_id="retry-before-restore")
            current = TurnOrchestrator().begin(turn)
            self.assertNotEqual(current.workflow_thread_id, TurnOrchestrator.workflow_thread_id(turn))
            self.assertTrue(current.workflow_thread_id.endswith(restored["timeline_epoch"]))


class LongHistoryTests(unittest.TestCase):
    def test_archived_rating_is_still_in_feedback_samples(self):
        from backend.services.narrative_evaluation_service import summarize_rated_samples
        value = storage.ensure_character_fields(character())
        value["conversation_history"] = [{"message_id": f"m{i}", "speaker": "旁白", "content": "你沿着石阶自由行走。", "rating": "up" if i == 3 else None} for i in range(700)]
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)):
            storage.save_turn_bundle("test", value, {})
            self.assertEqual(summarize_rated_samples(storage.load_character("test"))["positive"], 1)

    def test_archive_paging_search_export_rating_and_branch_are_lossless(self):
        from backend.services.conversation_archive_service import all_history, history_page, hydrate_history, portable_character
        from backend.routes.records import import_character
        original = character()
        original["conversation_history"] = [{"message_id": f"m{i}", "speaker": "旁白", "content": f"往事{i}"} for i in range(1200)]
        original = storage.ensure_character_fields(original)
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)), patch("backend.routes.records.get_characters_dir", return_value=Path(directory)):
            storage.save_turn_bundle("test", original, {})
            self.assertEqual(len(original["conversation_history"]), 200)
            self.assertEqual(len(all_history(original)), 1200)
            latest = history_page(original, limit=80)
            self.assertEqual(latest["start"], 1120)
            self.assertEqual(history_page(original, before_id="m201", limit=80)["messages"][-1]["message_id"], "m200")
            self.assertEqual(history_page(original, query="往事13")["messages"][0]["message_id"], "m13")
            snapshot = storage.list_character_snapshots("test")[0]["snapshot_id"]
            branch = storage.restore_character_snapshot("test", snapshot, branch=True)
            branch_id = branch["character_id"]
            forked = storage.load_character(branch_id)
            hydrate_history(forked)[0]["rating"] = "good"
            storage.save_turn_bundle(branch_id, forked, {})
            self.assertIsNone(all_history(storage.load_character("test"))[0].get("rating"))
            self.assertEqual(all_history(storage.load_character(branch_id))[0]["rating"], "good")
            exported = portable_character(original)
            self.assertFalse(exported["conversation_archive"]["chunks"])
            imported = asyncio.run(import_character({"character_data": exported}))
            self.assertEqual(all_history(storage.load_character(imported["character_id"])), exported["conversation_history"])

    def test_archive_write_does_not_commit_a_failed_transaction(self):
        from backend.services.conversation_archive_service import history_count
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "get_characters_dir", return_value=Path(directory)):
            old = storage.ensure_character_fields(character())
            storage.save_turn_bundle("test", old, {})
            newer = copy.deepcopy(old)
            newer["conversation_history"] = [{"message_id": f"m{i}", "content": "内容"} for i in range(700)]
            writer = storage._atomic_json_write
            def fail_journal(path, value):
                if "_transactions" in path.parts:
                    raise OSError("simulated crash")
                return writer(path, value)
            with patch.object(storage, "_atomic_json_write", side_effect=fail_journal), self.assertRaises(OSError):
                storage.save_turn_bundle("test", newer, {})
            self.assertEqual(history_count(storage.load_character("test")), 0)


class GlobalRecallTests(unittest.TestCase):
    def test_relevant_first_npc_wins_independent_of_insertion_order(self):
        from backend.services.npc_memory_service import get_npc_memory_text
        entries = {"博丽灵梦": [{"id": "same", "summary": "共同修复结界的承诺", "importance": 10}]}
        entries.update({f"路人{i}": [{"id": "same", "summary": "路边闲聊", "importance": 1}] for i in range(12)})
        first, second = {"npc_memories": copy.deepcopy(entries)}, {"npc_memories": dict(reversed(list(copy.deepcopy(entries).items())))}
        left = get_npc_memory_text(first, limit=1, query="修复结界承诺")
        self.assertEqual(left, get_npc_memory_text(second, limit=1, query="修复结界承诺"))
        self.assertIn("博丽灵梦", left)
        self.assertEqual(len(first["_last_memory_retrieval"]), 1)
        self.assertEqual(first["npc_memories"]["路人0"][0].get("used_count", 0), 0)

    def test_registry_matches_official_aliases_ids_and_avatars(self):
        from backend.services.npc_identity_service import resolve_npc, canonical_npc_name, canonical_npc_id
        self.assertEqual(canonical_npc_name("爱丽丝·玛格特洛依德"), "爱丽丝")
        self.assertEqual(canonical_npc_id("hakurei_reimu"), "npc_reimu")
        self.assertEqual(resolve_npc("npc_patchouli_n")["avatar_url"], "/avatars/npc_patchouli.png")
        self.assertTrue(resolve_npc("博丽灵梦")["profile"].get("personality"))


class LongEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_24_turns_cover_multiple_npcs_scenes_and_boundaries_without_writes(self):
        from backend.services.live_narrative_evaluation_service import run_live_evaluation
        prompts = []
        async def generate(prompt, **kwargs):
            prompts.append(prompt)
            self.assertTrue(kwargs["single_attempt"])
            self.assertEqual(kwargs["max_output_tokens"], 2048)
            return json.dumps({"description": "你们确认先前的修复结界约定仍然有效，随后平静地交流各自的日常。接下来去哪里，以及是否继续调查，都由你自己决定。", "time_cost": 1})
        original = character()
        before = copy.deepcopy(original)
        with patch("backend.services.live_narrative_evaluation_service.call_ai_async", side_effect=generate), patch("backend.services.turn_orchestrator.save_turn_bundle") as saved, patch("backend.routes.ghost.run_turn_workflow") as workflow:
            report = await run_live_evaluation(original, turn_count=24, token_budget=10_000_000)
        self.assertEqual(report["total"], 24, report)
        self.assertEqual(len(prompts), 24)
        self.assertGreaterEqual(len({row["npc_id"] for row in report["results"] if row["npc_id"]}), 4)
        self.assertGreaterEqual(len({row["scene"] for row in report["results"]}), 4)
        self.assertTrue(all(not row["error"] for row in report["results"]), report)
        boundaries = [row for row in report["results"] if row["case_id"] in ("boundary", "relationship_followup")]
        self.assertTrue(all(row["evaluation"]["dimensions"]["relationship_boundary"] == 100 for row in boundaries))
        self.assertEqual(original, before)
        saved.assert_not_called()
        workflow.assert_not_called()

    async def test_budget_and_disconnect_stop_before_provider_call(self):
        from backend.services.live_narrative_evaluation_service import run_live_evaluation
        from unittest.mock import AsyncMock
        with patch("backend.services.live_narrative_evaluation_service.call_ai_async", new_callable=AsyncMock) as model:
            report = await run_live_evaluation(character(), turn_count=60, token_budget=1)
            self.assertEqual(report["stopped_reason"], "budget_reached")
            model.assert_not_awaited()
            report = await run_live_evaluation(character(), cancelled=AsyncMock(return_value=True))
            self.assertEqual(report["stopped_reason"], "cancelled")
            model.assert_not_awaited()

    async def test_unexpected_provider_failure_is_charged_and_not_retried(self):
        from backend.services.live_narrative_evaluation_service import run_live_evaluation
        from unittest.mock import AsyncMock
        with patch("backend.services.live_narrative_evaluation_service.call_ai_async", new=AsyncMock(side_effect=OSError("provider offline"))) as model:
            report = await run_live_evaluation(character(), turn_count=24)
        self.assertEqual(model.await_count, 1)
        self.assertEqual(report["stopped_reason"], "provider_error")
        self.assertGreater(report["budget_tokens_used"], 0)


class StateResponseTests(unittest.TestCase):
    def test_receipts_do_not_nest_full_character_or_private_history(self):
        from backend.services.character_view_service import command_result
        large = {**character(), "conversation_history": [{"content": "private" * 1000}] * 1000,
                 "command_receipts": [{"result": {"character": character()}}], "npc_memory_archive": {"灵梦": ["private"]}}
        result = command_result({"character": large})
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("command_receipts", result["character"])
        self.assertEqual(result["character"]["history_total"], 1000)
        self.assertEqual(large["npc_memory_archive"], {"灵梦": ["private"]})
