"""Opt-in production-pipeline evaluation on an isolated, continuous save copy."""

import copy
import hashlib
import uuid
from datetime import datetime

from backend.services.ai_service import call_ai_async, get_last_ai_error, get_last_ai_runtime, get_last_ai_usage
from backend.services.evaluation_context import EvaluationContext, evaluation_context
from backend.services.narrative_evaluation_service import evaluate_narrative_text


LIVE_CASES = (
    {"id": "reimu_continuity", "title": "灵梦与既有经历", "action": "询问灵梦，接下来如何共同修复结界", "npc": True},
    {"id": "open_agency", "title": "搁置异变与自由出行", "action": "暂时放下异变调查，前往人间之里闲逛", "forbidden_terms": ("必须返回", "禁止前往")},
    {"id": "state_feedback", "title": "带伤符卡与确定性结算", "action": "带伤准备一场符卡挑战，观察对手弹幕"},
    {"id": "turn_contract", "title": "后续对话承接状态与记忆", "action": "向灵梦说明刚才的经历，询问她还记得我们的约定吗", "npc": True},
)


async def run_live_evaluation(character=None, tasks=None):
    from backend.routes import ghost
    from backend.world_manager import ensure_character_fields, get_default_tasks
    from backend.services.game_rules import preview_turn_ruling

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
    context = EvaluationContext(safe, copy.deepcopy(tasks or get_default_tasks()), call_ai_async)
    token = evaluation_context.set(context)
    results = []
    try:
        for case in LIVE_CASES:
            owner = context.character
            before = copy.deepcopy(owner.get("player_state", {}))
            npcs = [{"id": "hakurei_reimu", "name": "博丽灵梦", "profile": {"identity": "博丽巫女"}}]
            scene = owner.get("status", {}).get("current_scene", "博丽神社")
            turn_id = str(uuid.uuid4())
            ruling = preview_turn_ruling(owner, case["action"], npcs)
            error = None
            try:
                common = dict(character_id=owner["character_id"], scene=scene,
                              player_name=owner["profile"]["name"], scene_npcs=npcs, turn_id=turn_id)
                if case.get("npc"):
                    request = ghost.NPCDialogueRequest(**common, npc_id="hakurei_reimu",
                        npc_name="博丽灵梦", user_input=case["action"])
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
                for ok, code in ((contract_ok, "contract"), (state_ok, "settlement")):
                    if not ok:
                        evaluation["issues"].append({"code": code, "message": "回合契约或确定性结算不一致"})
                context.character.setdefault("conversation_history", []).extend([
                    {"message_id": str(uuid.uuid4()), "speaker": owner["profile"]["name"], "content": case["action"]},
                    {"message_id": str(uuid.uuid4()), "speaker": "博丽灵梦" if case.get("npc") else "旁白", "content": text},
                ])
            except Exception as exc:
                error = type(exc).__name__
                evaluation = {"passed": False, "score": 0, "dimensions": {}, "issues": [{"code": "pipeline_error", "message": error}]}
            results.append({
                "id": case["id"], "title": case["title"], "passed": evaluation["passed"], "evaluation": evaluation,
                "runtime": get_last_ai_runtime(), "usage": get_last_ai_usage(), "error": error or get_last_ai_error() or None,
                "state_before": before, "state_after": copy.deepcopy(context.character.get("player_state", {})),
                "memory_count": sum(len(v) for v in context.character.get("npc_memories", {}).values() if isinstance(v, list)),
                "prompt_fingerprint": context.prompt_fingerprints[-1] if context.prompt_fingerprints else None,
                "context_sections": list((context.character.get("_last_context_budget") or {}).get("sections", {})),
            })
    finally:
        evaluation_context.reset(token)
    return {
        "mode": "real_provider_opt_in", "prompt_version": 2, "pipeline": "production_handlers_dry_run",
        "mutated_save": False, "continuous_turns": True,
        "context_fingerprint": hashlib.sha256(repr(character).encode()).hexdigest()[:16],
        "total": len(results), "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens", 0) or 0) for item in results),
        "total_elapsed_ms": round(sum(float((item.get("runtime") or {}).get("elapsed_ms", 0) or 0) for item in results), 2),
        "models": sorted({str((item.get("runtime") or {}).get("used_model") or "unknown") for item in results}),
        "results": results, "completed_at": datetime.now().isoformat(),
    }
