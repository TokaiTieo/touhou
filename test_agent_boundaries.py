"""Regression cases for recipient scope, activation and pre-ranking permissions."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.agent_context_service import EvidenceContext
from backend.services.agent_contracts import Reader, default_agent_state
from backend.services.agent_scheduler import activation_plan, interaction_segments, run_agent_turn
from backend.services.memory_retrieval import rank_memories
from backend.services.npc_agent_runtime import NPCRuntime
from backend.services.turn_models import TurnContext, TurnInput


def records(count=2):
    return {f"test_{i}": {"id": f"test_{i}", "name": ("甲", "乙")[i] if i < 2 else f"访客{i}",
                          "profile": {"identity": "访客"}} for i in range(count)}


def turn(text, **kwargs):
    return TurnInput(kind=kwargs.pop("kind", "environment"), character_id="s", scene="博丽神社", player_name="测试",
                     turn_id="boundary", action_text=text, **kwargs)


def character():
    return {"character_id": "s", "timeline_epoch": "one", "profile": {"name": "测试"},
            "status": {"current_scene": "博丽神社"}, "time": {"current_day": 1, "current_hour": 8},
            "agent_state": {**default_agent_state(), "mode": "collaborative"}}


class RecipientBoundaryTests(unittest.TestCase):
    def test_explicit_redirect_survives_self_pause_without_ui_fallback(self):
        for pause in ("想了想", "独自坐下", "思考片刻", "我停顿片刻"):
            for text in (f'【动作】向乙私下说。{pause}\n【语言】"蓝色密码"',
                         f'（动作：向乙私下说。{pause}）"蓝色密码"'):
                with self.subTest(text=text):
                    result = interaction_segments(turn(text, npc_id="test_0"), records())
                    self.assertEqual(set(result), {"test_1"})
                    self.assertIn("蓝色密码", result["test_1"])
        result = interaction_segments(turn('【动作】向甲、乙说。想了想\n【语言】"大家好"', npc_id="test_0"), records())
        self.assertTrue(all("大家好" in text for text in result.values()))

    def test_uncertain_redirect_blocks_ui_speech_instead_of_falling_back(self):
        for prefix in ("", "向乙私下说。"):
            for action in ("把话悄悄告诉乙", "翻开私密札记", "向未知人物说", "向甲的方向独自走去"):
                with self.subTest(prefix=prefix, action=action), self.assertRaises(ValueError):
                    interaction_segments(turn(f'【动作】{prefix}{action}。想了想\n【语言】"蓝色密码"', npc_id="test_0"), records())
        result = interaction_segments(turn('【动作】向乙说。翻开札记。向甲说\n【语言】"你好"', npc_id="test_1"), records())
        self.assertIn("你好", result["test_0"])
        self.assertNotIn("你好", result["test_1"])

    def test_continue_intent_is_bound_to_selected_npc_not_placeholder_text(self):
        for text in ("[玩家没有说话，等待NPC继续]", "", "向乙私下说蓝色密码"):
            result = interaction_segments(turn(text, kind="npc_dialogue", npc_id="test_0", is_continue=True), records())
            self.assertEqual(set(result), {"test_0"})
            self.assertNotIn("蓝色密码", result["test_0"])
        for selection in ({}, {"kind": "environment", "npc_id": "test_0"},
                          {"kind": "npc_dialogue", "npc_id": "unknown"}, {"kind": "npc_dialogue", "interaction_npc_ids": ["test_0"]}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                interaction_segments(turn("", is_continue=True, **selection), records())
        self.assertFalse(TurnInput.model_validate(turn("").model_dump(exclude={"is_continue"})).is_continue)
        self.assertEqual(interaction_segments(turn("[玩家没有说话，等待NPC继续]", npc_id="test_0"), records()), {})

    def test_solo_action_and_speech_do_not_require_an_npc_audience(self):
        self.assertEqual(interaction_segments(turn('【动作】独自休息\n【语言】"今天真安静"'), records()), {})

    def test_unknown_actions_never_inherit_previous_or_selected_audience(self):
        for separator in ("。", "；", "\n", "，", ",", "、"):
            for selection in ({}, {"npc_id": "test_0"}, {"interaction_npc_ids": ["test_0", "test_1"]}):
                text = "向甲问好" + separator + "把蓝色密码悄悄告诉乙"
                with self.subTest(text=text, selection=selection):
                    result = interaction_segments(turn(text, **selection), records())
                    self.assertEqual(set(result), {"test_0"})
                    self.assertNotIn("蓝色密码", result["test_0"])
        self.assertEqual(interaction_segments(turn("把蓝色密码悄悄告诉乙", npc_id="test_0"), records()), {})
        for text in ("（动作：向甲问好）把蓝色密码悄悄告诉乙", "【动作】向甲问好。把蓝色密码悄悄告诉乙"):
            result = interaction_segments(turn(text, npc_id="test_0"), records())
            self.assertEqual(set(result), {"test_0"})
            self.assertNotIn("蓝色密码", result["test_0"])

    def test_independent_ui_speech_rebinds_selected_target_after_noninteraction(self):
        for action, speech in (("想了想", "不知道"), ("独自坐下", "你好"), ("不向甲挥手", "不要担心")):
            for text in (f'（动作：{action}）"{speech}"', f'【动作】{action}\n【语言】"{speech}"'):
                for selection in ({"npc_id": "test_0"}, {"interaction_npc_ids": ["test_0"]}):
                    with self.subTest(text=text, selection=selection):
                        result = interaction_segments(turn(text, **selection), records())
                        self.assertEqual(result, {"test_0": f'"{speech}"'})
                self.assertEqual(interaction_segments(turn(text), records()), {})

    def test_direct_speech_verb_does_not_negate_its_payload(self):
        for text in ("告诉甲不要担心", "告知甲不知道密码", "询问甲不愿回答的原因"):
            with self.subTest(text=text):
                self.assertEqual(interaction_segments(turn(text), records()), {"test_0": text})
        for text in ("不告诉甲密码", "想告诉甲密码", "告诉甲的信仍在包里"):
            self.assertEqual(interaction_segments(turn(text), records()), {})

    def test_only_explicit_quoted_continuation_inherits_audience(self):
        for continuation in ('"我不知道"', '继续说：“我不知道”'):
            result = interaction_segments(turn("向甲问好。" + continuation), records())
            self.assertIn("我不知道", result["test_0"])
        for unknown in ("把密码告诉乙", "转身翻开私密札记", "低头记下蓝色密码"):
            result = interaction_segments(turn('向甲问好。' + unknown + '。“这个秘密不能给甲”'), records())
            self.assertNotIn("秘密", result["test_0"])
            self.assertNotIn("密码", result["test_0"])
        result = interaction_segments(turn('向甲、乙问好。"大家好"'), records())
        self.assertTrue(all("大家好" in value for value in result.values()))

    def test_private_aside_is_not_broadcast(self):
        for separator in ("。", "！", "？", ". ", ";", "；", "\n", "，", ", ", "、", "，然后", "然后", "后", "。然后我"):
            for greeting in ("向甲问好", "向甲、乙共同问好"):
                for selection in ({}, {"npc_id": "test_0"}, {"interaction_npc_ids": ["test_0", "test_1"]}):
                    text = greeting + separator + "向乙私下说蓝色密码"
                    with self.subTest(text=text, selection=selection):
                        result = interaction_segments(turn(text, **selection), records())
                        self.assertEqual(set(result), {"test_0", "test_1"})
                        self.assertNotIn("密码", result["test_0"])
                        self.assertIn("蓝色密码", result["test_1"])

    def test_action_and_speech_wrappers_keep_the_final_recipient(self):
        for text in ('（动作：向甲问好。向乙私下说）"蓝色密码"',
                     '（动作：向甲说“符号）与【语言】”；向乙私下说）"蓝色密码"',
                     '【动作】向甲问好。向乙私下说\n【语言】"蓝色密码"'):
            with self.subTest(text=text):
                result = interaction_segments(turn(text, npc_id="test_0"), records())
                self.assertNotIn("密码", result["test_0"])
                self.assertIn("蓝色密码", result["test_1"])

    def test_quoted_addresses_are_not_new_recipients(self):
        for opening, closing in (("“", "”"), ('"', '"'), ("'", "'"), ("「", "」")):
            with self.subTest(opening=opening):
                result = interaction_segments(turn(f'向甲说：{opening}我曾向乙说密码。向乙问好。{closing}'), records())
                self.assertEqual(set(result), {"test_0"})
                self.assertIn("向乙说密码", result["test_0"])

    def test_common_private_address_prefixes(self):
        for phrase in ("跟乙私下说蓝色密码", "对着乙低声说蓝色密码", "转头对乙私下说蓝色密码"):
            result = interaction_segments(turn("向甲问好，" + phrase), records())
            self.assertNotIn("密码", result["test_0"])
            self.assertIn("蓝色密码", result["test_1"])

    def test_speech_negation_is_not_action_negation(self):
        for text in ("向甲说我不知道", "向甲说不要担心", '向甲说：“我不会答应。”', "询问甲是否知道线索"):
            with self.subTest(text=text):
                self.assertEqual(activation_plan(turn(text), {}, records())[0], ["test_0"])
        for text in ("向甲的方向独自走去", "向甲走去", "与甲无关，我独自休息", "给甲的信留在包里",
                     "向甲提到的地点走去", "不向甲说话", "向甲不说话", "想向甲问好", "如果向甲问好"):
            with self.subTest(text=text):
                self.assertEqual(activation_plan(turn(text), {}, records())[0], [])

    def test_selected_target_does_not_override_explicit_exclusion(self):
        for text in ("不向甲说话", "向甲的方向独自走去"):
            self.assertEqual(interaction_segments(turn(text, interaction_npc_ids=["test_0"]), records()), {})
        self.assertEqual(interaction_segments(turn('【语言】"你好"', npc_id="test_0"), records()),
                         {"test_0": '"你好"'})

    def test_ambiguous_private_audience_and_quotes_fail_closed(self):
        for text in ('向甲问好。向乙私下说“蓝色密码', "向甲、乙问好，私下说蓝色密码", "向甲、未知人物说密码",
                     "向甲问好向乙私下说蓝色密码", "向甲说我向乙说了密码"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                interaction_segments(turn(text), records())

    def test_duplicate_names_need_an_unambiguous_identity(self):
        people = records()
        people["test_1"]["name"] = "甲"
        with self.assertRaises(ValueError):
            interaction_segments(turn("向甲说密码"), people)
        self.assertEqual(set(interaction_segments(turn("向甲说密码", npc_id="test_1"), people)), {"test_1"})

    def test_presence_filter_preserves_order_and_whole_turn_limit(self):
        people = records(9)
        addressed = turn("向" + "、".join(row["name"] for row in people.values()) + "问好")
        active, deferred, _ = activation_plan(addressed, {}, people, present_ids=list(people)[2:])
        self.assertEqual(active, list(people)[2:8])
        self.assertEqual(deferred, ["test_0", "test_1", "test_8"])
        self.assertEqual(activation_plan(addressed, {}, people, present_ids=[])[0], [])


class MemoryEligibilityTests(unittest.TestCase):
    def test_ineligible_memories_cannot_starve_legal_recall_or_enter_ranker(self):
        for field in ("npc_memories", "npc_memory_archive"):
            for invalid in ({"timeline_epoch": "other"}, {"owner_npc_id": "test_1"},
                            {"attribution_status": "pending"}, {"truth_status": "retracted"},
                            {"visibility": "invalid"}):
                with self.subTest(field=field, invalid=invalid):
                    state = character()
                    legal = {"id": "legal", "summary": "我见过蓝色钥匙", "owner_npc_id": "test_0",
                             "attribution_status": "confirmed", "timeline_epoch": "one", "importance": 1}
                    denied = [{**legal, "id": f"denied_{i}", "summary": f"秘密钥匙密码{i}", "importance": 10,
                               **invalid} for i in range(45)]
                    state[field] = {"甲": [*denied, legal]}
                    original = copy.deepcopy(state)
                    view = EvidenceContext(Reader(save_id="s", epoch="one", npc_id="test_0", task_id="recall"),
                                           state, {}, "博丽神社", records=records())
                    with patch("backend.services.npc_memory_service.rank_memories", wraps=rank_memories) as rank:
                        result = view.recall_npc_memory("秘密钥匙密码", limit=1)
                    self.assertEqual([item["id"] for item in result], ["legal"])
                    self.assertEqual([item["id"] for item in rank.call_args.args[0]], ["legal"])
                    self.assertEqual(state, original)
                    self.assertEqual(view.usage, [{"npc_name": "甲", "memory_id": "legal"}])


class SchedulerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_pause_secret_stays_out_of_original_npc_request_and_memory(self):
        text = '【动作】向乙私下说。想了想\n【语言】"蓝色密码"'
        result, candidate, calls = await self.run_turn(text, selection={"npc_id": "test_0"})
        self.assertEqual(set(calls), {"test_1"})
        self.assertIn("蓝色密码", calls["test_1"])
        self.assertEqual([part["npc_id"] for part in result["agent_inputs"]], ["test_1"])
        candidate.character.setdefault("conversation_history", []).append({
            "message_id": "redirect-input", "speaker": "player", "content": text,
            "visibility": {"scope": "interaction_only", "audience": ["@player"]}, "agent_inputs": result["agent_inputs"]})
        for identity, expected in (("test_0", False), ("test_1", True)):
            view = EvidenceContext(Reader(save_id="s", epoch="one", npc_id=identity, task_id="next"),
                                   candidate.character, {}, "博丽神社", records=records())
            self.assertEqual("蓝色密码" in json.dumps(view.assemble("密码"), ensure_ascii=False), expected)

    async def test_continue_calls_selected_npc_without_inventing_player_speech(self):
        result, candidate, calls = await self.run_turn("[玩家没有说话，等待NPC继续]",
            selection={"kind": "npc_dialogue", "npc_id": "test_0", "is_continue": True})
        self.assertEqual(set(calls), {"test_0"})
        self.assertEqual(json.loads(calls["test_0"].splitlines()[-1])["task"]["intent"], "continue_dialogue")
        self.assertEqual(result["agent_inputs"], [])
        self.assertEqual(result["agent_turn"]["budget"]["requests"], 2)
        self.assertNotIn("玩家等待你", json.dumps(candidate.character.get("npc_memories", {}), ensure_ascii=False))
        result, _, calls = await self.run_turn("", present=["test_1"],
            selection={"kind": "npc_dialogue", "npc_id": "test_0", "is_continue": True})
        self.assertEqual(calls, {})
        self.assertEqual(result["agent_turn"]["deferred"], ["test_0"])

    async def test_unknown_action_is_absent_from_request_history_and_memory(self):
        for text in ("向甲问好。把蓝色密码悄悄告诉乙", "向甲问好，把蓝色密码悄悄告诉乙"):
            with self.subTest(text=text):
                result, candidate, calls = await self.run_turn(text)
                self.assertEqual(set(calls), {"test_0"})
                self.assertNotIn("蓝色密码", calls["test_0"])
                self.assertNotIn("蓝色密码", json.dumps(result["agent_inputs"], ensure_ascii=False))
                candidate.character.setdefault("conversation_history", []).append({
                    "message_id": "turn-input", "speaker": "player", "content": text,
                    "visibility": {"scope": "interaction_only", "audience": ["@player"]},
                    "agent_inputs": result["agent_inputs"],
                })
                for identity in records():
                    view = EvidenceContext(Reader(save_id="s", epoch="one", npc_id=identity, task_id="next"),
                                           candidate.character, {}, "博丽神社", records=records())
                    self.assertNotIn("蓝色密码", json.dumps(view.assemble("密码"), ensure_ascii=False))

    async def test_noninteraction_action_with_ui_speech_still_calls_selected_npc(self):
        for text in ('（动作：想了想）"不知道"', '【动作】独自坐下\n【语言】"你好"', "告诉甲不要担心"):
            with self.subTest(text=text):
                _, _, calls = await self.run_turn(text, selection={"npc_id": "test_0"})
                self.assertEqual(set(calls), {"test_0"})

    async def run_turn(self, text, *, people=None, present=None, selection=None):
        people = people or records()
        calls = {}

        async def generate(prompt, temperature):
            if "独立的人物" in prompt:
                identity = json.loads(prompt.splitlines()[-1])["binding"]["npc_id"]
                calls[identity] = prompt
                return '{"commands":[{"kind":"wait"}]}'
            return '{"description":"庭院安静。","cited_event_ids":[]}'

        with tempfile.TemporaryDirectory() as directory:
            runtime = NPCRuntime("boundaries", path=Path(directory) / "run.db", generate=generate, checkpoint=False)
            result, candidate = await run_agent_turn(TurnContext(turn=turn(text, **(selection or {})),
                character=character(), tasks={}), runtime=runtime, records=people,
                present_ids=list(people) if present is None else present, world_entries=[], persist=False)
        return result, candidate, calls

    async def test_private_input_stays_isolated_in_requests_and_future_recall(self):
        for text in ("向甲问好。向乙私下说蓝色密码", "向甲、乙问好，随后向乙私下说蓝色密码"):
            with self.subTest(text=text):
                result, candidate, calls = await self.run_turn(text)
                self.assertEqual(set(calls), {"test_0", "test_1"})
                self.assertNotIn("蓝色密码", calls["test_0"])
                self.assertIn("蓝色密码", calls["test_1"])
                parts = {part["npc_id"]: part["content"] for part in result["agent_inputs"]}
                self.assertNotIn("蓝色密码", parts["test_0"])
                for identity, expected in (("test_0", False), ("test_1", True)):
                    view = EvidenceContext(Reader(save_id="s", epoch="one", npc_id=identity, task_id="next"),
                                           candidate.character, {}, "博丽神社", records=records())
                    self.assertEqual("蓝色密码" in json.dumps(view.assemble("密码"), ensure_ascii=False), expected)

    async def test_absent_first_target_does_not_consume_one_of_six_slots(self):
        people = records(7)
        present = list(people)[1:]
        result, candidate, calls = await self.run_turn("向" + "、".join(row["name"] for row in people.values()) + "问好",
                                                      people=people, present=present)
        self.assertEqual(set(calls), set(present))
        self.assertEqual(result["agent_turn"]["deferred"], ["test_0"])
        self.assertTrue(any(event.get("target_id") == "test_0" and event.get("status") == "pending"
                            for event in candidate.character["agent_state"]["events"]))

    async def test_real_interaction_only_changes_npc_call_count(self):
        for text, expected in (("向甲的方向独自走去", set()), ("向甲说我不知道", {"test_0"})):
            with self.subTest(text=text):
                _, _, calls = await self.run_turn(text)
                self.assertEqual(set(calls), expected)


if __name__ == "__main__":
    unittest.main()
