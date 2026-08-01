"""Deterministic scenario evaluation for the core Touhou turn loop."""

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from backend.services.ai_contracts import (
    DialogueTurnResult,
    EnvironmentTurnResult,
    parse_turn_response,
)
from backend.services.turn_resolution_service import apply_turn_resolution


DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "turn_evaluation_cases.json"
)


def _merge(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def _base_character(case_id: str) -> Dict[str, Any]:
    return {
        "character_id": f"evaluation-{case_id}",
        "profile": {"name": "评测角色", "adult_verified": True},
        "gm_mode": False,
        "status": {"is_dead": False, "current_scene": "博丽神社"},
        "time": {
            "current_day": 1,
            "current_hour": 8,
            "chapter_time_remaining": 72,
            "chapter_status": "active",
            "anomaly_state": "active",
        },
        "player_state": {
            "灵力": 60,
            "结界共鸣": 35,
            "弹幕熟练度": 35,
            "调查熟练度": 0,
            "交涉熟练度": 0,
            "生存熟练度": 0,
            "疲劳": 10,
            "受伤": 0,
            "异变污染": 5,
        },
        "skill_experience": {},
        "spellcard_history": [],
        "spellcard_mastery": {},
        "opponent_adaptation": {},
        "npc_simulation": {"last_simulated_hour": 8, "events": []},
        "resolved_turn_ids": [],
    }


def _read_path(payload: Dict[str, Any], path: str) -> Any:
    current: Any = payload
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise KeyError(path)
        current = current[segment]
    return current


def _check_assertion(payload: Dict[str, Any], assertion: Dict[str, Any]) -> str:
    path = str(assertion["path"])
    operation = str(assertion.get("op", "eq"))
    expected = assertion.get("value")
    try:
        actual = _read_path(payload, path)
    except KeyError:
        return f"{path}: 字段不存在"
    comparisons = {
        "eq": lambda: actual == expected,
        "ne": lambda: actual != expected,
        "gt": lambda: actual > expected,
        "gte": lambda: actual >= expected,
        "lt": lambda: actual < expected,
        "lte": lambda: actual <= expected,
        "contains": lambda: expected in actual,
        "truthy": lambda: bool(actual),
    }
    comparison = comparisons.get(operation)
    if comparison is None:
        return f"{path}: 未知断言 {operation}"
    passed = comparison()
    if not passed:
        return f"{path}: 实际值 {actual!r} 未满足 {operation} {expected!r}"
    return ""


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    case_id = str(case.get("id") or "unnamed")
    character = _merge(_base_character(case_id), case.get("character", {}))
    tasks = copy.deepcopy(case.get("tasks") or {
        "active_tasks": [],
        "completed_tasks": [],
        "applied_turn_ids": [],
    })
    contract = (
        DialogueTurnResult
        if case.get("kind") == "npc_dialogue"
        else EnvironmentTurnResult
    )
    response = case.get("model_response")
    if isinstance(response, dict):
        response = json.dumps(response, ensure_ascii=False)
    result = parse_turn_response(str(response or ""), contract)
    before = copy.deepcopy(character)
    if result.get("contract_valid"):
        apply_turn_resolution(
            character,
            result,
            str(case.get("action_text") or ""),
            str(case.get("scene") or "博丽神社"),
            tasks,
            scene_npcs=copy.deepcopy(case.get("scene_npcs") or []),
            npc_name=case.get("npc_name"),
            turn_id=f"evaluation:{case_id}",
        )
    payload = {
        "character": character,
        "tasks": tasks,
        "result": result,
        "before": before,
    }
    failures = [
        message
        for message in (
            _check_assertion(payload, assertion)
            for assertion in case.get("assertions", [])
        )
        if message
    ]
    return {
        "id": case_id,
        "title": case.get("title", case_id),
        "passed": not failures,
        "failures": failures,
    }


def run_turn_evaluation(path: Path = None) -> Dict[str, Any]:
    source = Path(path or DEFAULT_CASES_PATH)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    results = [evaluate_case(case) for case in data.get("cases", [])]
    return {
        "source": str(source),
        "total": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "failed": sum(1 for result in results if not result["passed"]),
        "results": results,
    }
