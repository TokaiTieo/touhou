import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.services.agent_contracts import default_agent_state
from backend.services.agent_rules_service import ProposalMerger
from backend.services.agent_scheduler import activation_plan, interaction_segments, run_agent_turn
from backend.services.npc_agent_runtime import NPCRuntime
from backend.services.turn_models import TurnContext, TurnInput


def fixture(count=7):
    return {f"npc_custom_{i}": {"id": f"npc_custom_{i}", "name": f"访客{i}", "profile": {"identity": "独立访客"}} for i in range(count)}


class ActivationTests(unittest.TestCase):
    def test_mention_and_copresence_are_not_interaction(self):
        records = fixture()
        for action in ("独自休息", "想起访客0", "听说访客0最近来了", "不向访客0说话"):
            turn = TurnInput(kind="environment", character_id="s", scene="神社", player_name="p", action_text=action,
                             scene_npcs=list(records.values()))
            self.assertEqual(activation_plan(turn, {}, records)[0], [])

    def test_seven_are_deferred_and_whispers_not_shared(self):
        records = fixture()
        turn = TurnInput(kind="environment", character_id="s", scene="神社", player_name="p",
                         action_text="向" + "、".join(row["name"] for row in records.values()) + "问好")
        active, deferred, _ = activation_plan(turn, {}, records)
        self.assertEqual((len(active), len(deferred)), (6, 1))
        turn.action_text = "向访客0私下说蓝色密码；向访客1问好"
        segments = interaction_segments(turn, records)
        self.assertNotIn("密码", segments["npc_custom_1"])


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.records = fixture(3)
        self.state = {"time": {"current_day": 1, "current_hour": 8}, "agent_state": default_agent_state(),
                      "life_state": {"npc_resources": {"访客0": {"药材": 1}}}}
        self.merger = ProposalMerger(self.state, self.records, "turn", "神社", self.records)

    def test_serialized_proposal_roundtrip_and_player_calendar_conflict(self):
        from backend.services.agent_contracts import Proposal
        invite = Proposal(commands=[{"kind": "invite", "target_id": "@player", "hour": 40, "scene": "神社"}])
        issued = self.merger.merge("npc_custom_0", invite.model_dump())[0]["pending_event"]
        self.state["life_state"]["appointments"] = [{"id": "existing", "npc_name": "访客2", "hour": 40, "status": "scheduled"}]
        response = self.merger.merge("@player", {"commands": [{"kind": "accept", "event_id": issued["id"]}]})
        self.assertEqual(response[0]["status"], "rejected")
        self.assertEqual(self.state["agent_state"]["events"][0]["status"], "pending")

    def test_duplicate_does_not_replay_and_recipient_decides(self):
        proposal = {"commands": [{"kind": "offer", "target_id": "npc_custom_1", "item": "药材"}]}
        first = self.merger.merge("npc_custom_0", proposal)
        self.assertEqual(self.merger.merge("npc_custom_0", proposal), [])
        self.assertEqual(self.state["life_state"]["npc_resources"]["访客0"]["药材"], 1)
        event_id = first[0]["pending_event"]["id"]
        bad = self.merger.merge("npc_custom_2", {"commands": [{"kind": "accept", "event_id": event_id}]})
        self.assertEqual(bad[0]["status"], "rejected")
        good = self.merger.merge("npc_custom_1", {"commands": [{"kind": "accept", "event_id": event_id}]})
        self.assertEqual(good[0]["status"], "accepted")
        self.assertEqual(self.state["life_state"]["npc_resources"]["访客1"]["药材"], 1)
        self.assertEqual(self.state["life_state"]["npc_resources"]["访客0"]["药材"], 0)

    def test_two_offers_cannot_duplicate_last_item(self):
        offers = self.merger.merge("npc_custom_0", {"commands": [
            {"kind": "offer", "target_id": "npc_custom_1", "item": "药材"},
            {"kind": "offer", "target_id": "npc_custom_2", "item": "药材"}]})
        for index in (1, 2):
            answer = self.merger.merge(f"npc_custom_{index}", {"commands": [
                {"kind": "accept", "event_id": offers[index - 1]["pending_event"]["id"]}]})
            self.assertEqual(answer[0]["status"], "accepted" if index == 1 else "rejected")

    def test_accepted_npc_meeting_advances_once_without_public_diary(self):
        from backend.services.agent_rules_service import advance_agent_calendar
        invite = self.merger.merge("npc_custom_0", {"commands": [{"kind": "invite", "target_id": "npc_custom_1", "scene": "神社", "hour": 12}]})[0]["pending_event"]
        answer = self.merger.merge("npc_custom_1", {"commands": [{"kind": "accept", "event_id": invite["id"]}]})
        self.assertEqual(answer[0]["status"], "accepted")
        self.state["time"]["current_hour"] = 12
        advance_agent_calendar(self.state)
        advance_agent_calendar(self.state)
        self.assertEqual(self.state["agent_state"]["events"][0]["status"], "completed")
        self.assertEqual(len(self.state["life_state"]["diaries"]["npc_custom_0"]), 1)
        self.assertEqual(self.state["life_state"]["shared_experiences"], [])


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_chain_cannot_wake_seventh_npc(self):
        records = fixture(8)
        turn = TurnInput(kind="environment", character_id="s", scene="博丽神社", player_name="p",
                         turn_id="chain", action_text="向访客0问好")
        character = {"character_id": "s", "profile": {"name": "p"}, "status": {"current_scene": "博丽神社"},
                     "time": {"current_day": 1, "current_hour": 8}, "agent_state": default_agent_state()}
        calls = []
        async def generate(prompt, temperature):
            if "独立的人物" not in prompt:
                return '{"description":"有些互动尚待回应。","cited_event_ids":[]}'
            identity = json.loads(prompt.splitlines()[-1])["binding"]["npc_id"]
            calls.append(identity)
            target = "npc_custom_" + str(int(identity.rsplit('_', 1)[1]) + 1)
            return json.dumps({"commands": [{"kind": "invite", "target_id": target, "hour": 40, "scene": "博丽神社"}]})
        with tempfile.TemporaryDirectory() as directory:
            runtime = NPCRuntime("chain", path=Path(directory) / "run.db", generate=generate, checkpoint=False)
            result, candidate = await run_agent_turn(TurnContext(turn=turn, character=character, tasks={}), runtime=runtime,
                records=records, present_ids=list(records), world_entries=[], persist=False)
            self.assertEqual(calls, list(records)[:6])
            self.assertIn('npc_custom_6', result['agent_turn']['deferred'])
            self.assertTrue(any(event['target_id'] == 'npc_custom_6' and event['status'] == 'pending'
                                for event in candidate.character['agent_state']['events']))

    async def test_settlement_never_copies_other_addressees_private_input(self):
        from backend.services.agent_context_service import EvidenceContext
        from backend.services.agent_contracts import Reader
        records = fixture(2)
        character = {"character_id": "s", "timeline_epoch": "one", "profile": {"name": "p"},
                     "status": {"current_scene": "博丽神社"}, "time": {"current_day": 1, "current_hour": 8},
                     "agent_state": {**default_agent_state(), "mode": "collaborative"}}
        turn = TurnInput(kind="environment", character_id="s", scene="博丽神社", player_name="p", turn_id="private",
                         action_text="向访客0私下承诺蓝色书签的秘密；向访客1问好")
        async def generate(prompt, temperature):
            return '{"commands":[{"kind":"wait"}]}' if "独立的人物" in prompt else '{"description":"庭院静谧。","cited_event_ids":[]}'
        with tempfile.TemporaryDirectory() as directory:
            runtime = NPCRuntime("private", path=Path(directory) / "run.db", generate=generate, checkpoint=False)
            _, candidate = await run_agent_turn(TurnContext(turn=turn, character=character, tasks={}), runtime=runtime,
                records=records, present_ids=list(records), world_entries=[], persist=False)
            for identity, expected in (("npc_custom_0", True), ("npc_custom_1", False)):
                view = EvidenceContext(Reader(save_id="s", epoch="one", npc_id=identity, task_id="next"),
                                       candidate.character, {}, turn.scene, records=records, present_ids=list(records))
                self.assertEqual("蓝色书签" in json.dumps(view.assemble("秘密"), ensure_ascii=False), expected)

    async def test_zero_one_three_six_and_seven_have_exact_call_counts(self):
        for count in (0, 1, 3, 6, 7):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                records = fixture()
                ids = list(records)[:count]
                turn = TurnInput(kind="environment", character_id="s", scene="博丽神社", player_name="p",
                    turn_id="turn", action_text="向" + "、".join(records[key]["name"] for key in ids) + "问好" if count else "独自休息")
                character = {"character_id": "s", "profile": {"name": "p"}, "status": {"current_scene": "博丽神社"},
                             "time": {"current_day": 1, "current_hour": 8, "chapter_time_remaining": 72},
                             "agent_state": {**default_agent_state(), "mode": "collaborative"}}
                before = copy.deepcopy(character)
                context = TurnContext(turn=turn, character=character, tasks={"active_tasks": [], "completed_tasks": []})
                calls = []
                async def generate(prompt, temperature):
                    calls.append(prompt)
                    if "独立的人物" in prompt:
                        return json.dumps({"commands": [{"kind": "speak", "text": "你好，我自己决定如何回应。"}]})
                    if count == 0:
                        self.assertEqual(json.loads(prompt.splitlines()[-1])["schema"]["properties"]["cited_event_ids"]["maxItems"], 0)
                    return json.dumps({"description": "神社庭院安静如常。", "cited_event_ids": []})
                runtime = NPCRuntime("scope", path=Path(directory) / "run.db", generate=generate, checkpoint=False)
                result, candidate = await run_agent_turn(context, runtime=runtime, records=records, present_ids=list(records), world_entries=[], persist=False)
                self.assertEqual(len(calls), min(count, 6) + 1)
                self.assertEqual(len(result["agent_turn"]["participants"]), min(count, 6))
                self.assertEqual(character, before)
                if count == 7:
                    self.assertIn("尚待回应", result["description"])
                    self.assertTrue(candidate.character["agent_state"]["events"])


if __name__ == "__main__":
    unittest.main()
