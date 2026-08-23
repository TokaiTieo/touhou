import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from backend.version import SAVE_SCHEMA_VERSION

from backend.api import app
from backend.security import SESSION_TOKEN, TOKEN_HEADER


class APIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._client_context = TestClient(app)
        cls.client = cls._client_context.__enter__()
        cls.headers = {TOKEN_HEADER: SESSION_TOKEN}

    @classmethod
    def tearDownClass(cls):
        cls._client_context.__exit__(None, None, None)

    def test_index_injects_session_token_and_health_stays_public(self):
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn('name="touhou-session-token"', index.text)
        self.assertNotIn(SESSION_TOKEN, self.client.get("/api/health").text)
        version = self.client.get("/api/version")
        self.assertEqual(version.status_code, 200)
        self.assertEqual(version.json()["save_schema"], SAVE_SCHEMA_VERSION)

    def test_runtime_exposes_only_touhou_world(self):
        worlds = self.client.get("/api/worlds/list", headers=self.headers)
        self.assertEqual([item["id"] for item in worlds.json()["worlds"]], ["world_touhou"])
        rejected = self.client.post(
            "/api/world/select", headers=self.headers, json={"world_id": "world_other"}
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.client.post(
            "/api/world/create", headers=self.headers, json={"name": "other"}
        ).status_code, 404)

    def test_sensitive_api_rejects_missing_token(self):
        response = self.client.get("/api/ghost/locations/all")
        self.assertEqual(response.status_code, 403)

    def test_message_rewrite_adds_candidate_without_replaying_turn_state(self):
        with tempfile.TemporaryDirectory() as root:
            characters_dir = Path(root)
            with patch("backend.world_manager.get_characters_dir", return_value=characters_dir):
                created = self.client.post(
                    "/api/ghost/create_character",
                    headers=self.headers,
                    json={"profile": {
                        "name": "改写测试者",
                        "gender": "女",
                        "identity": "幻想乡原住民",
                        "appearance": "普通",
                        "personality": "谨慎",
                        "background": "居住在人间之里",
                    }},
                )
                character_id = created.json()["character_id"]
                for speaker, content in [
                    ("改写测试者", "【动作】调查神社"),
                    ("旁白", "你在石阶旁发现了一道淡淡的结界波纹。"),
                ]:
                    appended = self.client.post(
                        "/api/ghost/append_conversation",
                        headers=self.headers,
                        json={
                            "character_id": character_id,
                            "speaker": speaker,
                            "content": content,
                            "scene": "博丽神社",
                        },
                    )
                    self.assertEqual(appended.status_code, 200, appended.text)
                target = appended.json()
                before = json.loads(
                    (characters_dir / f"{character_id}.json").read_text(encoding="utf-8")
                )
                runtime = {
                    "requested_model": "deepseek-v4-flash",
                    "used_model": "deepseek-v4-pro",
                    "attempts": 2,
                    "fallback_used": True,
                }
                with patch(
                    "backend.routes.records.call_ai_async",
                    new=AsyncMock(return_value="淡银色波纹在石阶边缘一闪而过，留下细微的结界回响。"),
                ), patch("backend.routes.records.get_last_ai_runtime", return_value=runtime):
                    rewritten = self.client.post(
                        "/api/ghost/rewrite_message",
                        headers=self.headers,
                        json={
                            "character_id": character_id,
                            "message_id": target["message_id"],
                            "message_index": target["message_index"],
                        },
                    )
                self.assertEqual(rewritten.status_code, 200, rewritten.text)
                payload = rewritten.json()
                self.assertEqual(payload["original"], "你在石阶旁发现了一道淡淡的结界波纹。")
                self.assertEqual(len(payload["rewrite_candidates"]), 1)
                after = json.loads(
                    (characters_dir / f"{character_id}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(after["conversation_history"][-1]["content"], payload["original"])
                self.assertEqual(after["time"], before["time"])
                self.assertEqual(after["player_state"], before["player_state"])
                self.assertEqual(after["relationships_map"], before["relationships_map"])
                self.assertEqual(after.get("consequence_log"), before.get("consequence_log"))
                self.assertEqual(after["model_runtime"]["used_model"], "deepseek-v4-pro")

    def test_settings_status_never_returns_complete_key(self):
        response = self.client.get("/api/ghost/get_api_key", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.json())

    def test_settings_status_detects_system_environment_key_without_exposing_it(self):
        with patch("backend.routes.settings.load_secret", return_value=""), patch(
            "backend.routes.settings.DEEPSEEK_API_KEY", "system-test-key-not-real"
        ), patch(
            "backend.routes.settings.DEEPSEEK_API_KEY_SOURCE", "system_environment"
        ):
            response = self.client.get("/api/ghost/get_api_key", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["has_key"])
        self.assertEqual(response.json()["key_source"], "system_environment")
        self.assertNotIn("system-test-key-not-real", response.text)

    def test_create_load_turn_and_duplicate_turn_are_consistent(self):
        with tempfile.TemporaryDirectory() as root:
            characters_dir = Path(root)
            with patch("backend.world_manager.get_characters_dir", return_value=characters_dir):
                created = self.client.post(
                    "/api/ghost/create_character",
                    headers=self.headers,
                    json={"profile": {
                        "name": "集成测试者",
                        "gender": "女",
                        "identity": "幻想乡原住民",
                        "appearance": "普通",
                        "personality": "谨慎",
                        "background": "居住在人间之里"
                    }}
                )
                self.assertEqual(created.status_code, 200, created.text)
                character_id = created.json()["character_id"]
                loaded = self.client.post(
                    "/api/ghost/load_character",
                    headers=self.headers,
                    json={"character_id": character_id}
                )
                self.assertEqual(loaded.status_code, 200, loaded.text)
                self.assertIn("调查熟练度", loaded.json()["player_state"])
                self.assertEqual(loaded.json()["save_version"], SAVE_SCHEMA_VERSION)

                ai_result = json.dumps({
                    "description": "你调查了神社附近的结界波纹。",
                    "time_cost": 1,
                    "is_dead": False,
                    "task_updates": [],
                    "memory_updates": []
                }, ensure_ascii=False)
                request = {
                    "character_id": character_id,
                    "scene": "博丽神社",
                    "player_name": "集成测试者",
                    "user_input": {"action": "调查结界线索", "speech": ""},
                    "history": [],
                    "scene_npcs": [],
                    "turn_id": "integration-turn-1"
                }
                with patch(
                    "backend.services.turn_workflow.call_ai_async",
                    new=AsyncMock(return_value=ai_result),
                ):
                    first = self.client.post("/api/ghost/environment_interact", headers=self.headers, json=request)
                    second = self.client.post("/api/ghost/environment_interact", headers=self.headers, json=request)
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(first.json(), second.json())
                turn_status = self.client.get(
                    f"/api/ghost/turn_status/{character_id}/integration-turn-1",
                    headers=self.headers,
                )
                self.assertEqual(turn_status.status_code, 200, turn_status.text)
                self.assertEqual(turn_status.json()["state"], "committed")
                self.assertEqual(
                    turn_status.json()["result"]["description"],
                    first.json()["description"],
                )
                saved = json.loads((characters_dir / f"{character_id}.json").read_text(encoding="utf-8"))
                self.assertEqual(len(saved.get("turn_receipts", [])), 1)
                self.assertIn("skill_experience", saved)
                self.assertEqual(saved["usage_stats"]["requests"], 1)

                diagnostics = self.client.get(
                    f"/api/ghost/diagnostics?character_id={character_id}", headers=self.headers
                )
                self.assertEqual(diagnostics.status_code, 200)
                self.assertEqual(diagnostics.json()["usage"]["requests"], 1)

    def test_npc_dialogue_uses_workflow_and_commits_once(self):
        with tempfile.TemporaryDirectory() as root:
            characters_dir = Path(root)
            with patch("backend.world_manager.get_characters_dir", return_value=characters_dir):
                created = self.client.post(
                    "/api/ghost/create_character",
                    headers=self.headers,
                    json={"profile": {
                        "name": "对话测试者",
                        "gender": "女",
                        "identity": "幻想乡原住民",
                        "appearance": "普通",
                        "personality": "诚恳",
                        "background": "居住在人间之里",
                    }},
                )
                character_id = created.json()["character_id"]
                ai_result = json.dumps({
                    "description": "灵梦点头回应了你的问候。",
                    "time_cost": 0.25,
                    "exit_dialogue": False,
                    "relationship_update": "博丽灵梦:友好(礼貌问候)",
                    "task_updates": [],
                    "memory_updates": [{
                        "npc_name": "博丽灵梦",
                        "summary": "玩家礼貌地向灵梦问好。",
                    }],
                }, ensure_ascii=False)
                request = {
                    "character_id": character_id,
                    "scene": "博丽神社",
                    "player_name": "对话测试者",
                    "npc_id": "npc_reimu",
                    "npc_name": "博丽灵梦",
                    "user_input": "你好，灵梦。",
                    "history": [],
                    "scene_npcs": [],
                    "turn_id": "dialogue-turn-1",
                }
                model = AsyncMock(return_value=ai_result)
                with patch("backend.services.turn_workflow.call_ai_async", new=model):
                    first = self.client.post(
                        "/api/ghost/npc_dialogue", headers=self.headers, json=request
                    )
                    second = self.client.post(
                        "/api/ghost/npc_dialogue", headers=self.headers, json=request
                    )
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(first.json(), second.json())
                self.assertEqual(model.await_count, 1)
                saved = json.loads(
                    (characters_dir / f"{character_id}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(len(saved["relationships_history"]), 1)
                memories = saved["npc_memories"]["博丽灵梦"]
                self.assertEqual(len(memories), 2)
                self.assertTrue(all(
                    item.get("source_turn_id") == "dialogue-turn-1" for item in memories
                ))
                self.assertEqual(saved["relationship_turn_receipts"], ["dialogue-turn-1"])

    def test_legacy_save_auto_upgrades_through_load_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            characters_dir = Path(root)
            legacy = {
                "character_id": "legacy-http",
                "profile": {"name": "旧档"},
                "status": {"is_dead": False, "current_scene": "博丽神社"},
                "time": {"current_day": 2, "current_hour": 9, "chapter_time_remaining": 30},
                "conversation_history": []
            }
            (characters_dir / "legacy-http.json").write_text(
                json.dumps(legacy, ensure_ascii=False),
                encoding="utf-8"
            )
            (characters_dir / "legacy-http_tasks.json").write_text(
                json.dumps({"active_tasks": [], "completed_tasks": []}, ensure_ascii=False),
                encoding="utf-8"
            )
            with patch("backend.world_manager.get_characters_dir", return_value=characters_dir):
                response = self.client.post(
                    "/api/ghost/load_character",
                    headers=self.headers,
                    json={"character_id": "legacy-http"}
                )
            self.assertEqual(response.status_code, 200, response.text)
            upgraded = json.loads((characters_dir / "legacy-http.json").read_text(encoding="utf-8"))
            self.assertEqual(upgraded["save_version"], SAVE_SCHEMA_VERSION)
            self.assertIn("skill_experience", upgraded)
            self.assertIn("incident_state", upgraded)
            self.assertIn("story_summary", upgraded)
            self.assertIn("usage_stats", upgraded)


if __name__ == "__main__":
    unittest.main()
