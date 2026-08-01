import unittest

from backend.services.turn_service import apply_task_updates, apply_time_progression


class TurnServiceTests(unittest.TestCase):
    def test_task_completion_is_idempotent(self):
        tasks = {"active_tasks": [{"id": "clue", "name": "线索", "priority": 10}], "completed_tasks": []}
        update = [{"task_id": "clue", "action": "complete", "info": "已经查明"}]
        self.assertTrue(apply_task_updates(tasks, update))
        self.assertFalse(apply_task_updates(tasks, update))
        self.assertEqual(len(tasks["completed_tasks"]), 1)

    def test_time_progression_crosses_midnight(self):
        character = {"time": {"current_day": 2, "current_hour": 23, "chapter_time_remaining": 20}}
        result = {"description": "赶路", "time_cost": 2}
        self.assertTrue(apply_time_progression(character, result))
        self.assertEqual(character["time"]["current_day"], 3)
        self.assertEqual(character["time"]["current_hour"], 1)
        self.assertEqual(character["time"]["chapter_time_remaining"], 18)

    def test_waiting_incident_has_no_countdown(self):
        character = {"time": {"current_day": 1, "current_hour": 8, "chapter_time_remaining": 7, "anomaly_state": "waiting"}}
        apply_time_progression(character, {"description": "休息", "time_cost": 4})
        self.assertEqual(character["time"]["chapter_time_remaining"], 7)


if __name__ == "__main__":
    unittest.main()
