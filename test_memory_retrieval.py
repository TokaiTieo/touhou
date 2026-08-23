import unittest
from datetime import datetime, timedelta, timezone

from backend.services.npc_memory_service import get_npc_memory_text, record_npc_memories, upgrade_npc_memory_metadata
from backend.services.memory_retrieval import (
    _recency_score,
    configure_dense_provider,
    cosine_similarity,
    local_embedding,
    rank_memories,
)


class MemoryRetrievalTests(unittest.TestCase):
    def tearDown(self):
        configure_dense_provider(None)

    def test_optional_dense_index_is_persisted_and_reported(self):
        class FakeProvider:
            def encode(self, texts, normalize_embeddings=True):
                return [
                    [1.0, 0.0] if "结界" in text else [0.0, 1.0]
                    for text in texts
                ]

        configure_dense_provider(FakeProvider(), "fake-local-model")
        items = [
            {"id": "mem_barrier", "summary": "一起修复博丽大结界", "importance": 5},
            {"id": "mem_tea", "summary": "在人间之里喝茶", "importance": 5},
        ]
        index = {}
        meta = {}
        ranked = rank_memories(items, "结界发生了什么", 1, index, meta)
        self.assertEqual(ranked[0]["id"], "mem_barrier")
        self.assertEqual(set(index), {"mem_barrier", "mem_tea"})
        self.assertEqual(meta["backend"], "sentence_transformer")
        self.assertEqual(meta["dimensions"], 2)

    def test_related_concepts_have_vector_overlap(self):
        score = cosine_similarity(local_embedding("答应以后保护灵梦"), local_embedding("曾经作出保护的承诺"))
        self.assertGreater(score, 0.05)

    def test_hybrid_rank_prefers_relevant_important_memory(self):
        items = [
            {"summary": "一起在神社喝茶", "importance": 3, "used_count": 0},
            {"summary": "玩家答应帮助灵梦调查结界裂隙", "importance": 9, "used_count": 1},
            {"summary": "在雾之湖捡到石头", "importance": 5, "used_count": 0},
        ]
        ranked = rank_memories(items, "我对灵梦调查异变的承诺", 2)
        self.assertIn("结界裂隙", ranked[0]["summary"])

    def test_rank_is_stable_and_limited(self):
        items = [{"summary": f"记忆{i}", "importance": i % 10 + 1} for i in range(20)]
        first = rank_memories(items, "记忆", 5)
        second = rank_memories(items, "记忆", 5)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)

    def test_real_timestamped_memory_can_be_ranked(self):
        items = [
            {
                "summary": "玩家答应帮助灵梦调查结界裂隙",
                "importance": 9,
                "created_at": datetime.now().isoformat(),
            }
        ]
        self.assertEqual(rank_memories(items, "调查异变", 1), items)

    def test_recency_accepts_timezone_and_z_suffix(self):
        recent = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        self.assertGreater(_recency_score({"created_at": recent}), 2.9)
        self.assertEqual(_recency_score({"created_at": old}), 0.0)

    def test_recency_handles_invalid_and_future_dates(self):
        future = (datetime.now() + timedelta(days=2)).isoformat()
        self.assertEqual(_recency_score({"created_at": "not-a-date"}), 0.0)
        self.assertEqual(_recency_score({}), 0.0)
        self.assertEqual(_recency_score({"created_at": future}), 3.0)


    def test_old_memories_upgrade_additively_with_provenance(self):
        character = {"npc_memories": {"灵梦": [{"summary": "一起调查过结界", "custom": "keep"}]}}
        self.assertTrue(upgrade_npc_memory_metadata(character))
        memory = character["npc_memories"]["灵梦"][0]
        self.assertEqual(memory["knowledge_type"], "direct")
        self.assertEqual(memory["truth_status"], "accepted")
        self.assertEqual(memory["custom"], "keep")
        self.assertFalse(upgrade_npc_memory_metadata(character))

    def test_conflicting_fact_keeps_history_and_marks_superseded_entry(self):
        character = {}
        record_npc_memories(character, [{
            "npc_name": "灵梦", "summary": "裂隙位于神社后山",
            "fact_key": "rift_location", "confidence": 0.55, "knowledge_type": "reported",
        }])
        record_npc_memories(character, [{
            "npc_name": "灵梦", "summary": "裂隙实际位于参道尽头",
            "fact_key": "rift_location", "confidence": 0.95, "knowledge_type": "direct",
        }])
        memories = character["npc_memories"]["灵梦"]
        self.assertEqual(len(memories), 2)
        self.assertEqual(memories[0]["truth_status"], "superseded")
        self.assertEqual(memories[0]["superseded_by"], memories[1]["id"])
        self.assertIn("亲历", get_npc_memory_text(character, "灵梦", query="裂隙"))


if __name__ == "__main__":
    unittest.main()
