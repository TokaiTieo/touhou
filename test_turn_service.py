import unittest

from backend.services.turn_service import apply_task_updates, apply_time_progression
from backend.services.story_summary_service import (
    format_story_director_for_ai,
    update_story_director,
)


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

    def test_story_director_is_idempotent_and_never_gates_exploration(self):
        character = {
            "time": {"current_day": 2, "current_hour": 9},
            "incident_state": {"id": "rift", "title": "结界裂隙", "status": "active", "stage": "investigation", "threat_progress": 35},
        }
        tasks = {"active_tasks": [{"id": "clue", "name": "追查结界波纹", "description": "询问目击者"}]}
        result = {"description": "你在林间发现了新的痕迹。"}
        update_story_director(character, result, "调查林间痕迹", "魔法森林", tasks, turn_id="turn-1")
        update_story_director(character, result, "调查林间痕迹", "魔法森林", tasks, turn_id="turn-1")
        director = character["story_director"]
        self.assertEqual(len(director["beats"]), 1)
        self.assertEqual(director["exploration_policy"], "open")
        self.assertFalse(director["world_clocks"]["incident:rift"]["gates_exploration"])
        self.assertIn("完全开放", format_story_director_for_ai(character))


if __name__ == "__main__":
    unittest.main()
