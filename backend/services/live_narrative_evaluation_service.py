"""Opt-in production-pipeline evaluation on an isolated, continuous save copy."""

import copy
import hashlib
import math
import uuid
from datetime import datetime

from backend.services.ai_service import call_ai_async, get_last_ai_error, get_last_ai_runtime, get_last_ai_usage, reset_ai_diagnostics
from backend.services.evaluation_context import EvaluationContext, evaluation_context
from backend.services.narrative_evaluation_service import evaluate_narrative_text
from backend.services.npc_identity_service import resolve_npc


LIVE_CASES = (
    {"id": "reimu_continuity", "title": "灵梦与既有经历", "action": "询问灵梦，接下来如何共同修复结界", "npc": True},
    {"id": "open_agency", "title": "搁置异变与自由出行", "action": "暂时放下异变调查，前往人间之里闲逛", "forbidden_terms": ("必须返回", "禁止前往")},
    {"id": "state_feedback", "title": "带伤符卡与确定性结算", "action": "带伤准备一场符卡挑战，观察对手弹幕"},
    {"id": "turn_contract", "title": "后续对话承接状态与记忆", "action": "向灵梦说明刚才的经历，询问她还记得我们的约定吗", "npc": True},
)

LONG_CASES = tuple({**case, "scene": "博丽神社"} for case in LIVE_CASES) + (
    {"id": "marisa_daily", "title": "魔理沙的日常", "scene": "雾雨魔法店", "npc": "雾雨魔理沙", "action": "请魔理沙介绍店里的日常，暂时不追查异变"},
    {"id": "alice_relationship", "title": "爱丽丝关系自然发展", "scene": "魔法之森", "npc": "爱丽丝", "action": "帮爱丽丝整理人偶材料，并邀请她改天一起喝茶；她也可以拒绝"},
    {"id": "patchouli_secret", "title": "图书馆中的私下约定", "scene": "红魔馆", "npc": "帕秋莉", "action": "私下向帕秋莉确认那条关于琥珀之匣的记录", "expected_fact": "evaluation_private"},
    {"id": "boundary", "title": "保持普通交往", "scene": "魔法之森", "npc": "爱丽丝", "action": "说明希望保持普通朋友关系，不推进亲密关系", "expected_boundary": "closed"},
    {"id": "free_route", "title": "搁置线索后自由游历", "scene": "人间之里", "action": "放下所有线索，闲逛后在路边休息", "forbidden_terms": ("禁止探索", "必须先完成")},
    {"id": "return_promise", "title": "跨地点返回后的承诺", "scene": "博丽神社", "npc": "博丽灵梦", "action": "回到神社，询问我们之前关于修复结界的约定", "expected_fact": "evaluation_promise"},
    {"id": "recovery", "title": "带伤休息后的状态", "scene": "博丽神社", "action": "暂时不战斗，在神社休息一小时恢复体力"},
    {"id": "relationship_followup", "title": "关系边界的后续承接", "scene": "魔法之森", "npc": "爱丽丝", "action": "以普通朋友身份再次问候爱丽丝，询问她今天的计划", "expected_boundary": "closed"},
)


class EvaluationBudgetReached(Exception):
    pass


async def run_live_evaluation(character=None, tasks=None, *, turn_count=4, token_budget=400000,
                              max_output_tokens=2048, price_per_million=None, cost_budget=None, cancelled=None):
    from backend.routes import ghost
    from backend.world_manager import ensure_character_fields, get_default_tasks
    from backend.services.game_rules import preview_turn_ruling

    turn_count = max(1, min(60, int(turn_count)))
    token_budget = max(1, min(10_000_000, int(token_budget)))
    max_output_tokens = max(128, min(8192, int(max_output_tokens)))
    if cost_budget is not None and (price_per_million is None or float(price_per_million) <= 0):
        raise ValueError("使用费用上限时需填写每百万 Token 的保守单价")
    price = max(0, float(price_per_million or 0))
    if not math.isfinite(price) or (cost_budget is not None and not math.isfinite(float(cost_budget))):
        raise ValueError("评测费用参数必须是有限数字")
    if cost_budget is not None:
        token_budget = min(token_budget, max(0, int(float(cost_budget) / price * 1_000_000)))
    spent = 0
    calls = []

    async def bounded_generate(prompt, temperature=0.8):
        nonlocal spent
        # UTF-8 bytes deliberately overestimate typical tokenized input.
        reservation = len(prompt.encode("utf-8")) + 128 + max_output_tokens
        if spent + reservation > token_budget:
            raise EvaluationBudgetReached()
        spent += reservation
        reset_ai_diagnostics()
        try:
            response = await call_ai_async(prompt, temperature=temperature,
                                           max_output_tokens=max_output_tokens, single_attempt=True)
        except Exception:
            calls.append({"usage": {}, "runtime": {}, "budget_tokens": reservation, "estimated": True,
                          "error": {"code": "provider_call_error"}})
            raise
        usage = get_last_ai_usage()
        actual = int(usage.get("total_tokens", 0) or 0)
        charged = actual or reservation
        spent += charged - reservation
        calls.append({"usage": usage, "runtime": get_last_ai_runtime(), "budget_tokens": charged,
                      "estimated": not bool(actual), "error": get_last_ai_error() or None})
        return response

    source = copy.deepcopy(character or {})
    source.setdefault("profile", {}).setdefault("name", "评测旅人")
    source.setdefault("character_id", str(uuid.uuid4()))
    safe = ensure_character_fields(source)
    safe.pop("_migrated", None)
    safe["gm_mode"] = False
    safe["status"]["is_dead"] = False
    safe["status"]["current_scene"] = "博丽神社"
    safe.setdefault("player_state", {})["受伤"] = 30
    safe.setdefault("npc_memories", {}).setdefault("博丽灵梦", []).append({
        "id": "evaluation-promise", "summary": "玩家与灵梦约定共同修复结界",
        "importance": 10, "knowledge_type": "direct", "truth_status": "accepted",
        "confidence": 0.9, "fact_key": "evaluation_promise",
    })
    safe.setdefault("npc_memories", {}).setdefault("帕秋莉", []).append({
        "id": "evaluation-private", "summary": "帕秋莉私下确认琥珀之匣的记录，仅她与玩家知道",
        "importance": 10, "knowledge_type": "direct", "truth_status": "accepted", "fact_key": "evaluation_private",
    })
    context = EvaluationContext(safe, copy.deepcopy(tasks or get_default_tasks()), bounded_generate)
    token = evaluation_context.set(context)
    results = []
    stopped_reason = None
    cases = LIVE_CASES if turn_count <= 4 else LONG_CASES
    try:
        for index in range(turn_count):
            if cancelled is not None and await cancelled():
                stopped_reason = "cancelled"
                break
            case = cases[index % len(cases)]
            call_start = len(calls)
            owner = context.character
            if case.get("scene"):
                owner.setdefault("status", {})["current_scene"] = case["scene"]
            before = copy.deepcopy(owner.get("player_state", {}))
            npc_name = case.get("npc") if isinstance(case.get("npc"), str) else "博丽灵梦"
            npc = resolve_npc(npc_name)
            if not npc or not npc.get("profile"):
                raise ValueError("评测角色身份未能匹配正式设定")
            npcs = [npc]
            scene = owner.get("status", {}).get("current_scene", "博丽神社")
            turn_id = str(uuid.uuid4())
            ruling = preview_turn_ruling(owner, case["action"], npcs)
            error = None
            try:
                common = dict(character_id=owner["character_id"], scene=scene,
                              player_name=owner["profile"]["name"], scene_npcs=npcs, turn_id=turn_id)
                if case.get("npc"):
                    request = ghost.NPCDialogueRequest(**common, npc_id=npc["id"],
                        npc_name=npc["name"], user_input=case["action"])
                    result = await ghost.npc_dialogue.__wrapped__(request)
                else:
                    request = ghost.EnvironmentInteractRequest(**common, user_input={"action": case["action"]})
                    result = await ghost.environment_interact.__wrapped__(request)
                text = result.get("description", "")
                evaluation = evaluate_narrative_text(text, forbidden_terms=case.get("forbidden_terms"))
                contract_ok = bool(result.get("contract_valid", bool(case.get("npc"))))
                state_ok = not ruling.get("is_battle") or result.get("spellcard_result", {}).get("outcome") == ruling.get("outcome")
                evaluation["passed"] = bool(evaluation["passed"] and contract_ok and state_ok)
                evaluation["dimensions"].update(contract=100 if contract_ok else 0, settlement=100 if state_ok else 0)
                if case.get("expected_fact"):
                    wanted = case["expected_fact"].replace("_", "-")
                    recalled = any(item.get("memory_id") == wanted for item in context.character.get("_last_memory_retrieval", []))
                    evaluation["dimensions"]["memory_recall"] = 100 if recalled else 0
                    if not recalled:
                        evaluation["passed"] = False
                        evaluation["issues"].append({"code": "memory_recall", "message": "指定人物的约定未进入本回合召回"})
                if case.get("expected_boundary"):
                    boundary_ok = context.character.get("relationship_boundaries", {}).get(npc["name"], {}).get("romance") == case["expected_boundary"]
                    evaluation["dimensions"]["relationship_boundary"] = 100 if boundary_ok else 0
                    if not boundary_ok:
                        evaluation["passed"] = False
                        evaluation["issues"].append({"code": "relationship_boundary", "message": "关系边界未按玩家表达保留"})
                for ok, code in ((contract_ok, "contract"), (state_ok, "settlement")):
                    if not ok:
                        evaluation["issues"].append({"code": code, "message": "回合契约或确定性结算不一致"})
                context.character.setdefault("conversation_history", []).extend([
                    {"message_id": str(uuid.uuid4()), "speaker": owner["profile"]["name"], "content": case["action"]},
                    {"message_id": str(uuid.uuid4()), "speaker": npc["name"] if case.get("npc") else "旁白", "content": text},
                ])
            except EvaluationBudgetReached:
                stopped_reason = "budget_reached"
                break
            except Exception as exc:
                error = type(exc).__name__
                evaluation = {"passed": False, "score": 0, "dimensions": {}, "issues": [{"code": "pipeline_error", "message": error}]}
            results.append({
                "id": f"{case['id']}:{index + 1}", "case_id": case["id"], "title": case["title"], "passed": evaluation["passed"], "evaluation": evaluation,
                "scene": scene, "npc_id": npc["id"] if case.get("npc") else None,
                "runtime": calls[-1]["runtime"] if len(calls) > call_start else {},
                "usage": calls[-1]["usage"] if len(calls) > call_start else {},
                "error": error or (calls[-1]["error"] if len(calls) > call_start else None),
                "state_before": before, "state_after": copy.deepcopy(context.character.get("player_state", {})),
                "memory_count": sum(len(v) for v in context.character.get("npc_memories", {}).values() if isinstance(v, list)),
                "prompt_fingerprint": context.prompt_fingerprints[-1] if context.prompt_fingerprints else None,
                "context_sections": list((context.character.get("_last_context_budget") or {}).get("sections", {})),
                "relationship_after": copy.deepcopy(context.character.get("relationship_progress", {}).get(npc["name"], {})),
            })
            if len(calls) > call_start and calls[-1]["error"]:
                stopped_reason = "provider_error"
                break
    finally:
        evaluation_context.reset(token)
    return {
        "mode": "real_provider_opt_in", "prompt_version": 3, "pipeline": "production_handlers_dry_run",
        "requested_turns": turn_count, "stopped_reason": stopped_reason, "token_budget": token_budget,
        "budget_tokens_used": spent, "usage_estimated": any(item["estimated"] for item in calls),
        "estimated_cost": round(spent * price / 1_000_000, 6) if price else None,
        "scene_setup": "scenario_fixture", "grading": "heuristic_and_state_assertions",
        "mutated_save": False, "continuous_turns": True,
        "context_fingerprint": hashlib.sha256(repr(character).encode()).hexdigest()[:16],
        "total": len(results), "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens", 0) or 0) for item in results),
        "total_elapsed_ms": round(sum(float((item.get("runtime") or {}).get("elapsed_ms", 0) or 0) for item in results), 2),
        "models": sorted({str((item.get("runtime") or {}).get("used_model") or "unknown") for item in results}),
        "results": results, "completed_at": datetime.now().isoformat(),
    }
