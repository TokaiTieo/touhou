import copy
import json
import unittest

from pydantic import ValidationError

from backend.services.agent_contracts import Command, Proposal, Reader
from backend.services.agent_context_service import EvidenceContext, HOST
from backend.services.npc_memory_service import commit_memory_usage


class AgentContextTests(unittest.TestCase):
    def setUp(self):
        self.records = {"a": {"id": "a", "name": "甲", "profile": {"identity": "访客", "secret": "甲的设定秘密"}},
                        "b": {"id": "b", "name": "乙", "profile": {"secret": "乙的设定秘密"}}}
        self.character = {"character_id": "save", "timeline_epoch": "one", "conversation_history": [
            {"message_id": "private", "content": "甲乙密约", "participants": ["a", "b"],
             "visibility": {"scope": "recipients", "audience": ["a"]}},
            {"message_id": "unknown", "content": "她把钥匙藏了起来"},
        ], "npc_memories": {"甲": [
            {"id": "m1", "summary": "听说乙拥有蓝色钥匙", "source_npc": "乙", "knowledge_type": "reported",
             "owner_npc_id": "a", "truth_status": "accepted", "attribution_status": "confirmed"},
            {"id": "m2", "summary": "待确认的密码", "attribution_status": "pending"},
            {"id": "m3", "summary": "旧时间线密码", "timeline_epoch": "two"},
        ]}, "life_state": {"diaries": {"a": [{"id": "diary", "detail": "甲的私人札记"}]}}}

    def context(self, who):
        return EvidenceContext(Reader(save_id="save", epoch="one", npc_id=who, task_id="turn:1"),
                               self.character, {}, "神社", records=self.records, present_ids=["a", "b"])

    def test_no_cross_person_secrets_or_unknown_pronouns(self):
        rendered = json.dumps(self.context("b").assemble("甲的秘密"), ensure_ascii=False)
        for secret in ("甲乙密约", "钥匙藏", "私人札记", "甲的设定秘密", "蓝色钥匙"):
            self.assertNotIn(secret, rendered)

    def test_oversized_custom_identity_is_not_silently_removed(self):
        self.records['a']['profile']['background'] = '长资料' * 5000
        with self.assertRaisesRegex(ValueError, '本人资料超过'):
            self.context('a').assemble('你好')

    def test_hearsay_retains_provenance_without_promoting_truth(self):
        result = self.context("a").recall_npc_memory()
        self.assertEqual([item["id"] for item in result if item["kind"] == "memory"], ["m1"])
        self.assertEqual(result[-1].get("source_npc", result[0].get("source_npc")), "乙")
        self.assertIn('"knowledge_type": "reported"', json.dumps(result))

    def test_no_write_until_commit(self):
        before = copy.deepcopy(self.character)
        context = self.context("a")
        context.assemble("钥匙")
        self.assertEqual(self.character, before)
        commit_memory_usage(self.character, context.usage)
        self.assertEqual(self.character["npc_memories"]["甲"][0]["used_count"], 1)

    def test_host_publication_excludes_private_notes_and_other_private_speech(self):
        rendered = json.dumps(self.context(HOST).assemble("甲的秘密"), ensure_ascii=False)
        for secret in ("甲乙密约", "甲的私人札记", "设定秘密", "蓝色钥匙"):
            self.assertNotIn(secret, rendered)

    def test_tool_reader_cannot_be_overridden(self):
        with self.assertRaises(ValueError):
            self.context("b").query("recall_npc_memory", {"npc_id": "a"})
        with self.assertRaises(ValueError):
            EvidenceContext(Reader(save_id="another", epoch="one", npc_id="a", task_id="x"), self.character, {}, "x")

    def test_custom_duplicate_names_do_not_share_legacy_state(self):
        self.records["b"]["name"] = "甲"
        self.character["npc_runtime"] = {"甲": {"note": "无法归属的旧秘密"}, "id:a": {"note": "甲一的秘密"}}
        rendered = json.dumps(self.context("b").assemble("秘密"), ensure_ascii=False)
        self.assertNotIn("甲一的秘密", rendered)
        self.assertNotIn("无法归属的旧秘密", rendered)
        self.assertNotIn("蓝色钥匙", rendered)
        self.character["conversation_history"][0]["visibility"]["audience"] = ["甲"]
        self.assertNotIn("甲乙密约", json.dumps(self.context("b").assemble("秘密"), ensure_ascii=False))

    def test_snapshot_rebinds_only_retained_evidence(self):
        from backend.services.snapshot_service import prepare_restore_payload
        self.character["npc_memories"]["甲"][0]["timeline_epoch"] = "one"
        snapshot = {"character": copy.deepcopy(self.character), "tasks": {}}
        for branch in (False, True):
            restored = prepare_restore_payload("save", snapshot, lambda value: value, dict, branch=branch)["character"]
            reader = Reader(save_id=restored["character_id"], epoch=restored["timeline_epoch"], npc_id="a", task_id="new")
            view = EvidenceContext(reader, restored, {}, "神社", records=self.records)
            text = json.dumps(view.recall_npc_memory(), ensure_ascii=False)
            self.assertIn("蓝色钥匙", text)
            self.assertNotIn("旧时间线密码", text)
        self.assertEqual(snapshot["character"], self.character)

    def test_corrections_excluded_before_ranking(self):
        self.character["npc_memory_corrections"] = {"甲": [{"memory_id": "m1", "summaries": []}]}
        self.assertNotIn("蓝色钥匙", json.dumps(self.context("a").assemble("钥匙"), ensure_ascii=False))

    def test_world_keyword_is_not_permission(self):
        context = self.context("b")
        context._world = [{"id": "secret", "keywords": ["钥匙"], "content": "世界书密码",
                           "visibility": {"scope": "private", "audience": ["a"]}}]
        self.assertEqual(context.search_world_info("钥匙"), [])

    def test_contract_rejects_state_patches_and_actor_spoofing(self):
        for payload in ({"commands": [{"kind": "wait"}], "npc_id": "b"},
                        {"commands": [{"kind": "speak", "text": "你好", "state": {"b": "同意"}}]},
                        {"commands": [{"kind": "wait", "target_id": "b"}]}):
            with self.assertRaises(ValidationError):
                Proposal.model_validate(payload)
        self.assertEqual(Command(kind="speak", text="我拒绝").kind, "speak")


if __name__ == "__main__":
    unittest.main()
