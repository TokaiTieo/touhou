import json
import tempfile
import unittest
from pathlib import Path

from backend.services.world_info_service import build_world_info_context


class WorldInfoServiceTests(unittest.TestCase):
    def test_budget_priority_scope_and_exclusive_group(self):
        entries = {
            "entries": [
                {"id": "a", "title": "神社", "keywords": ["结界"], "scenes": ["博丽神社"], "priority": 10, "exclusive_group": "place", "content": "A" * 80},
                {"id": "b", "title": "旧神社", "keywords": ["结界"], "priority": 20, "exclusive_group": "place", "content": "B" * 80},
                {"id": "c", "title": "符卡", "keywords": ["战斗"], "priority": 5, "content": "C" * 80}
            ]
        }
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "world_info.json"
            path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
            result = build_world_info_context(path, "调查结界并准备战斗", "博丽神社", budget_chars=140)
        ids = [item["id"] for item in result["entries"]]
        self.assertIn("a", ids)
        self.assertNotIn("b", ids)
        self.assertLessEqual(result["used_chars"], 140)
        self.assertEqual(result["diagnostics"]["total_entries"], 3)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "world_info.json"
            path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
            roomy = build_world_info_context(path, "调查结界并准备战斗", "博丽神社", budget_chars=300)
        self.assertTrue(roomy["diagnostics"]["group_conflicts"])

    def test_bundled_world_book_has_broad_touhou_coverage(self):
        path = Path(__file__).parent / "worlds/world_touhou/world_info.json"
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertGreaterEqual(data["content_version"], 6)
        self.assertGreaterEqual(len(data["entries"]), 60)
        ids = {item["id"] for item in data["entries"]}
        for expected in ("wi_npc_reimu", "wi_npc_patchouli", "wi_loc_hakurei", "wi_spellcard_rules"):
            self.assertIn(expected, ids)


if __name__ == "__main__":
    unittest.main()
