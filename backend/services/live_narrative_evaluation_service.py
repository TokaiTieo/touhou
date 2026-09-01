"""Opt-in real-provider narrative regression without gameplay-state mutation."""

import copy
import hashlib
from datetime import datetime
from typing import Dict, List

from backend.services.ai_service import (
    call_ai_async,
    get_last_ai_error,
    get_last_ai_runtime,
    get_last_ai_usage,
)
from backend.services.narrative_evaluation_service import evaluate_narrative_text
from backend.services.ai_contracts import EnvironmentTurnResult, parse_turn_response


LIVE_CASES = (
    {
        "id": "reimu_continuity",
        "title": "灵梦人物与状态连续性",
        "prompt": "你是东方同人文字游戏的叙事模型。玩家在博丽神社帮灵梦修复结界后再次见面。用80至180字承接这项事实，保持灵梦务实直接的语气，不限制玩家下一步行动，只输出叙事正文。",
        "expected_terms": ("灵梦", "结界"),
        "required_facts": ("修复",),
    },
    {
        "id": "open_agency",
        "title": "开放探索表达",
        "prompt": "玩家决定暂时不调查异变，转而去人间之里闲逛。用80至180字描述世界回应，明确行动成立，不要求玩家返回主线，只输出叙事正文。",
        "expected_terms": ("人间之里",),
        "forbidden_terms": ("必须返回", "无法前往"),
    },
    {
        "id": "state_feedback",
        "title": "行动与状态反馈",
        "prompt": "玩家带伤完成一场符卡战并获胜。用80至180字同时体现胜利、身体负担和后续可选择方向，不输出JSON或内部编号。",
        "expected_terms": ("胜利", "伤"),
    },
    {
        "id": "turn_contract",
        "title": "结构化回合契约",
        "prompt": "返回一个JSON对象，description用80至180字描述玩家在博丽神社调查结界，is_dead为false，time_cost为1，task_updates、memory_updates、inventory_updates、reputation_updates和world_effects均为空数组。不要输出代码块或额外说明。",
        "contract": "environment",
    },
)


def _context_fingerprint(character: Dict) -> str:
    snapshot = {
        "identity": (character.get("profile", {}) or {}).get("identity"),
        "scene": (character.get("status", {}) or {}).get("current_scene"),
        "incident": (character.get("incident_state", {}) or {}).get("title"),
        "save_version": character.get("save_version"),
    }
    return hashlib.sha256(repr(sorted(snapshot.items())).encode("utf-8")).hexdigest()[:16]


async def run_live_evaluation(character: Dict = None) -> Dict:
    safe_character = copy.deepcopy(character or {})
    results: List[Dict] = []
    for case in LIVE_CASES:
        response = await call_ai_async(case["prompt"], temperature=0.3)
        if case.get("contract") == "environment":
            parsed = parse_turn_response(response, EnvironmentTurnResult)
            valid = bool(parsed.get("contract_valid"))
            evaluation = {
                "score": 100 if valid else 0,
                "passed": valid,
                "dimensions": {"contract": 100 if valid else 0},
                "issues": [] if valid else [{
                    "code": "turn_contract_invalid",
                    "message": "模型未满足结构化回合契约",
                }],
            }
        else:
            evaluation = evaluate_narrative_text(
                response,
                expected_terms=case.get("expected_terms"),
                forbidden_terms=case.get("forbidden_terms"),
                required_facts=case.get("required_facts"),
            )
        results.append({
            "id": case["id"],
            "title": case["title"],
            "passed": evaluation["passed"],
            "evaluation": evaluation,
            "response_preview": response[:500],
            "runtime": get_last_ai_runtime(),
            "usage": get_last_ai_usage(),
            "error": get_last_ai_error() or None,
        })
    return {
        "mode": "real_provider_opt_in",
        "prompt_version": 1,
        "mutated_save": False,
        "context_fingerprint": _context_fingerprint(safe_character),
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens", 0) or 0) for item in results),
        "total_elapsed_ms": round(sum(float((item.get("runtime") or {}).get("elapsed_ms", 0) or 0) for item in results), 2),
        "models": sorted({
            str((item.get("runtime") or {}).get("used_model") or (item.get("runtime") or {}).get("requested_model") or "unknown")
            for item in results
        }),
        "results": results,
        "completed_at": datetime.now().isoformat(),
    }
