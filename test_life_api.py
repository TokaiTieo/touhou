import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.api import app
from backend.security import SESSION_TOKEN, TOKEN_HEADER
from backend import world_manager as storage
from backend.services.life_simulation_service import register_event
from backend.services.relationship_dynamics_service import propose_relationship, record_shared_experience


class LifeAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()
        cls.headers = {TOKEN_HEADER: SESSION_TOKEN}

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory_patch = patch("backend.world_manager.get_characters_dir", return_value=Path(self.temp.name))
        self.directory_patch.start()
        self.addCleanup(self.directory_patch.stop)
        result = self.client.post("/api/ghost/create_character", headers=self.headers,
            json={"profile": {"name": "日常接口测试", "identity": "幻想乡原住民", "age": 25,
                               "background": "居住在博丽神社", "starting_location": "博丽神社"}})
        self.assertEqual(result.status_code, 200, result.text)
        self.identity = result.json()["character_id"]
        value = storage.load_character(self.identity)
        value["status"]["current_scene"] = "博丽神社"
        storage.save_character(self.identity, value)

    def command(self, **payload):
        return self.client.post("/api/ghost/life_command", headers=self.headers,
            json={"character_id": self.identity, **payload})

    def test_activity_duplicate_command_preserves_exact_rewards(self):
        payload = {"command": "activity", "target": "shrine_work", "operation_id": "same-activity"}
        first = self.command(**payload)
        self.assertEqual(first.status_code, 200, first.text)
        before = copy.deepcopy(storage.load_character(self.identity))
        second = self.command(**payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(storage.load_character(self.identity), before)
        self.assertEqual(first.json()["life"]["experiences"], second.json()["life"]["experiences"])
        wrong = self.command(**{**payload, "target": "fishing"})
        self.assertEqual(wrong.status_code, 409)

    def test_wrong_location_and_missing_materials_leave_state_unchanged(self):
        before = storage.load_character(self.identity)
        blocked = self.command(command="activity", target="cooking", operation_id="wrong-place")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(storage.load_character(self.identity), before)

    def test_event_abandon_and_resume_moves_only_its_own_task(self):
        value = storage.load_character(self.identity)
        register_event(value, {"id": "event-api", "title": "神社来访", "scene": "博丽神社"})
        storage.save_character(self.identity, value)
        joined = self.command(command="event", target="event-api", choice="participate", operation_id="join")
        self.assertEqual(joined.status_code, 200, joined.text)
        tasks = storage.load_tasks(self.identity)
        task_id = joined.json()["life"]["events"][0]["task_id"]
        self.assertIn(task_id, {item["id"] for item in tasks["active_tasks"]})
        self.command(command="event", target="event-api", choice="abandon", operation_id="pause")
        tasks = storage.load_tasks(self.identity)
        self.assertNotIn(task_id, {item["id"] for item in tasks["active_tasks"]})
        self.assertIn(task_id, {item["id"] for item in tasks["suspended_tasks"]})
        self.command(command="event", target="event-api", choice="participate", operation_id="resume")
        tasks = storage.load_tasks(self.identity)
        self.assertEqual(sum(item["id"] == task_id for item in tasks["active_tasks"]), 1)

    def test_relationship_acceptance_is_durable_and_idempotent(self):
        value = storage.load_character(self.identity)
        value["relationship_progress"]["雾雨魔理沙"] = {"score": 95, "stage": "亲密"}
        for identity in ("a", "b", "c"):
            record_shared_experience(value, "雾雨魔理沙", identity)
        proposal = propose_relationship(value, ["雾雨魔理沙"])
        storage.save_character(self.identity, value)
        accepted = self.command(command="relationship", target=proposal["id"], choice="accept", operation_id="accept")
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["character"]["relationships_map"]["雾雨魔理沙"], "恋人")
        repeated = self.command(command="relationship", target=proposal["id"], choice="accept", operation_id="accept")
        self.assertEqual(repeated.status_code, 200)
        saved = storage.load_character(self.identity)
        self.assertNotEqual(saved["relationship_boundaries"]["雾雨魔理沙"].get("mature"), "open")

    def test_branch_restore_does_not_copy_future_activity_rewards(self):
        value = storage.load_character(self.identity)
        snapshot = storage.create_character_snapshot(self.identity, value, label="日常前", force=True)
        self.command(command="activity", target="shrine_work", operation_id="after-snapshot")
        original = storage.load_character(self.identity)
        restored = self.client.post("/api/ghost/snapshots/restore", headers=self.headers, json={
            "character_id": self.identity, "snapshot_id": snapshot["snapshot_id"], "branch": True})
        self.assertEqual(restored.status_code, 200, restored.text)
        branch_id = restored.json()["character_id"]
        branch = storage.load_character(branch_id)
        self.assertEqual(branch["life_state"]["activities"], [])
        self.assertNotEqual(branch["inventory_state"]["currency"], original["inventory_state"]["currency"])
        self.assertEqual(storage.load_character(self.identity)["life_state"], original["life_state"])

    def test_life_endpoints_require_session_and_validate_numbers(self):
        self.assertEqual(self.client.get(f"/api/ghost/life?character_id={self.identity}").status_code, 403)
        result = self.command(command="appointment", target="博丽灵梦", scene="博丽神社", day=0, hour=24)
        self.assertEqual(result.status_code, 422)


if __name__ == "__main__":
    unittest.main()
