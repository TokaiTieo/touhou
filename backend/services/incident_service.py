"""Deterministic Touhou incident lifecycle with legacy-save compatibility."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


INCIDENT_VERSION = 2
MAIN_INCIDENT_ID = "main_touhou_rift_01"
INVESTIGATION_WORDS = ("调查", "搜索", "观察", "线索", "结界", "裂隙", "追踪", "询问", "分析")
NEXT_INCIDENT_WORDS = ("新异变", "新的异变", "传闻", "下一次异变", "继续调查")
RESOLUTION_KEYWORDS = {
    "negotiation": ("交涉", "说服", "谈判", "和解", "请求", "合作"),
    "spellcard": ("符卡", "弹幕", "决斗", "战斗", "击败", "退治"),
    "ritual": ("仪式", "结界", "封印", "祈祷", "净化", "修复"),
    "investigation": ("调查", "推理", "分析", "线索", "真相", "追踪"),
}

FALLBACK_INCIDENTS = [{
    "id": "touhou_rift", "title": "结界裂隙异变", "completion_task_id": MAIN_INCIDENT_ID,
    "task_name": "稳定博丽大结界的裂隙", "task_description": "自由调查结界裂隙。",
    "rumor": "博丽神社附近出现了结界波纹。", "base_hours": 72,
    "rewards": {"灵力": 10, "结界共鸣": 10, "弹幕熟练度": 5, "异变污染": -15}
}]


def load_incident_definitions(path: Optional[Path] = None) -> list:
    if path is None:
        try:
            from backend.config import WORLDS_DIR, DEFAULT_WORLD_ID
            path = WORLDS_DIR / DEFAULT_WORLD_ID / "incidents.json"
        except ImportError:
            path = None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            incidents = json.load(handle).get("incidents", [])
        return incidents or FALLBACK_INCIDENTS
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return FALLBACK_INCIDENTS


def _definition(incident_id: str, definitions=None) -> Dict:
    definitions = definitions or load_incident_definitions()
    return next((item for item in definitions if item.get("id") == incident_id), definitions[0])


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=0.0, high=100.0) -> float:
    return max(low, min(high, _number(value)))


def _completed_ids(tasks_data: Optional[Dict]) -> set:
    return {
        str(task.get("id") or task.get("task_id"))
        for task in (tasks_data or {}).get("completed_tasks", [])
        if isinstance(task, dict) and (task.get("id") or task.get("task_id"))
    }


def _sync_legacy_time(character: Dict, incident: Dict) -> None:
    time_info = character.setdefault("time", {})
    if incident["status"] == "resolved":
        time_info["chapter_status"] = "resolved"
        time_info["anomaly_state"] = "waiting"
        time_info["chapter_node_name"] = "等待新的异变传闻"
        time_info["chapter_time_remaining"] = max(0, _number(time_info.get("chapter_time_remaining"), 0))
    else:
        time_info.setdefault("chapter_status", "active")
        time_info.setdefault("anomaly_state", "active")


def ensure_incident_state(character: Dict, tasks_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Add the incident model without deleting or renaming any legacy fields."""
    time_info = character.setdefault("time", {})
    completed = _completed_ids(tasks_data)
    definitions = load_incident_definitions()
    legacy_resolved = (
        MAIN_INCIDENT_ID in completed
        or time_info.get("chapter_status") == "resolved"
        or time_info.get("anomaly_state") == "waiting"
    )
    existing = character.get("incident_state")
    if not isinstance(existing, dict):
        remaining = _clamp(time_info.get("chapter_time_remaining", 72), 0, 72)
        existing = {
            "version": INCIDENT_VERSION,
            "id": definitions[0]["id"],
            "title": definitions[0]["title"],
            "sequence_index": 0,
            "completion_task_id": definitions[0].get("completion_task_id", MAIN_INCIDENT_ID),
            "status": "resolved" if legacy_resolved else "active",
            "stage": "aftermath" if legacy_resolved else "discovery",
            "investigation_progress": 100 if legacy_resolved else 0,
            "threat_progress": 100 if legacy_resolved else round((72 - remaining) / 72 * 100, 1),
            "clue_ids": sorted(completed - {MAIN_INCIDENT_ID}),
            "started_at": character.get("created_at") or datetime.now().isoformat(),
            "resolved_at": time_info.get("resolved_at") if legacy_resolved else None,
            # Old resolved saves must not receive or duplicate a new reward during migration.
            "rewards_claimed": bool(legacy_resolved),
            "resolution_summary": "旧存档已完成的异变" if legacy_resolved else "",
            "resolution_path": "legacy" if legacy_resolved else None,
            "resolution_path_title": "旧存档迁移" if legacy_resolved else "",
            "aftermath": "",
            "_migration_pending": True
        }
        character["incident_state"] = existing

    defaults = {
        "version": INCIDENT_VERSION,
        "id": definitions[0]["id"],
        "title": definitions[0]["title"],
        "sequence_index": 0,
        "completion_task_id": definitions[0].get("completion_task_id", MAIN_INCIDENT_ID),
        "status": "active",
        "stage": "discovery",
        "investigation_progress": 0,
        "threat_progress": 0,
        "clue_ids": [],
        "started_at": character.get("created_at") or datetime.now().isoformat(),
        "resolved_at": None,
        "rewards_claimed": False,
        "resolution_summary": "",
        "resolution_path": None,
        "resolution_path_title": "",
        "aftermath": ""
    }
    for key, value in defaults.items():
        existing.setdefault(key, value)
    existing["version"] = INCIDENT_VERSION
    current_definition = _definition(existing.get("id"), definitions)
    existing["title"] = current_definition.get("title", existing.get("title"))
    existing.setdefault("completion_task_id", current_definition.get("completion_task_id", MAIN_INCIDENT_ID))
    existing["related_locations"] = list(current_definition.get("related_locations", []) or [])
    existing["related_npcs"] = list(current_definition.get("related_npcs", []) or [])
    existing["available_incidents"] = [item.get("id") for item in definitions]
    if not isinstance(existing.get("clue_ids"), list):
        existing["clue_ids"] = []
    _sync_legacy_time(character, existing)
    return existing


def _apply_resolution_reward(character: Dict, incident: Dict) -> Dict[str, float]:
    if incident.get("rewards_claimed"):
        return {}
    player_state = character.setdefault("player_state", {})
    rewards = _definition(incident.get("id")).get("rewards", {})
    delta = {}
    for key, amount in rewards.items():
        old = _number(player_state.get(key), 0)
        high = 999999 if key in ("灵力", "结界共鸣", "弹幕熟练度") else 100
        new = max(0, min(high, old + amount))
        if new != old:
            player_state[key] = int(new) if new.is_integer() else round(new, 2)
            delta[key] = round(new - old, 2)
    reputation = character.setdefault("reputation", {})
    reputation["博丽神社"] = _number(reputation.get("博丽神社"), 0) + 5
    incident["rewards_claimed"] = True
    return delta


def sync_incident_from_tasks(character: Dict, tasks_data: Dict, result: Optional[Dict] = None) -> Dict[str, Any]:
    incident = ensure_incident_state(character, tasks_data)
    completed = _completed_ids(tasks_data)
    completion_task_id = incident.get("completion_task_id", MAIN_INCIDENT_ID)
    migration_pending = bool(incident.pop("_migration_pending", False))
    clue_ids = sorted(completed - {completion_task_id})
    incident["clue_ids"] = sorted(set(incident.get("clue_ids", [])) | set(clue_ids))
    incident["investigation_progress"] = max(
        _clamp(incident.get("investigation_progress")),
        min(95, len(incident["clue_ids"]) * 20)
    )
    reward_delta = {}
    if completion_task_id in completed and incident.get("status") != "resolved":
        incident.update({
            "status": "resolved",
            "stage": "aftermath",
            "investigation_progress": 100,
            "threat_progress": 100,
            "resolved_at": datetime.now().isoformat(),
            "resolution_summary": _definition(incident.get("id")).get(
                "resolution_summary",
                f"{incident.get('title', '异变')}已经解决，幻想乡进入余波阶段。"
            )
        })
        if migration_pending:
            incident["rewards_claimed"] = True
        else:
            reward_delta = _apply_resolution_reward(character, incident)
    _sync_legacy_time(character, incident)
    if result is not None:
        result["incident_state"] = dict(incident)
        if reward_delta:
            state_delta = result.setdefault("player_state_delta", {})
            for key, value in reward_delta.items():
                state_delta[key] = round(_number(state_delta.get(key), 0) + value, 2)
            result["incident_resolution"] = {
                "status": "resolved",
                "summary": incident["resolution_summary"],
                "rewards": reward_delta,
                "reputation": {"博丽神社": 5}
            }
    return incident


def apply_resolution_path(character: Dict, result: Dict, action_text: str) -> Optional[Dict]:
    """Record how an incident was solved without restricting the available approach."""
    incident = character.get("incident_state")
    if not isinstance(incident, dict) or incident.get("status") != "resolved":
        return None
    if incident.get("resolution_path") not in (None, ""):
        return None
    text = str(action_text or "")
    path_id = next(
        (name for name, words in RESOLUTION_KEYWORDS.items() if any(word in text for word in words)),
        "freeform"
    )
    definition = _definition(incident.get("id"))
    paths = definition.get("resolution_paths", {})
    selected = paths.get(path_id) or paths.get("freeform") or {
        "title": "自由解决",
        "summary": "你用自己的方式结束了这场异变。"
    }
    aftermaths = definition.get("aftermaths", [])
    aftermath = aftermaths[0] if aftermaths else "幻想乡开始消化这次异变留下的影响。"
    incident["resolution_path"] = path_id
    incident["resolution_path_title"] = selected.get("title", "自由解决")
    incident["resolution_summary"] = selected.get("summary", incident.get("resolution_summary", ""))
    incident["aftermath"] = aftermath
    result["incident_resolution"] = {
        **(result.get("incident_resolution") or {}),
        "status": "resolved",
        "path": path_id,
        "path_title": incident["resolution_path_title"],
        "summary": incident["resolution_summary"],
        "aftermath": aftermath
    }
    return result["incident_resolution"]


def start_next_incident(character: Dict, tasks_data: Dict) -> Optional[Dict[str, Any]]:
    definitions = load_incident_definitions()
    incident = ensure_incident_state(character, tasks_data)
    next_index = int(incident.get("sequence_index", 0)) + 1
    if next_index >= len(definitions):
        return None
    definition = definitions[next_index]
    completion_task_id = definition.get("completion_task_id") or f"main_{definition['id']}_01"
    incident.update({
        "version": INCIDENT_VERSION,
        "id": definition["id"],
        "title": definition["title"],
        "sequence_index": next_index,
        "completion_task_id": completion_task_id,
        "status": "active",
        "stage": "discovery",
        "investigation_progress": 0,
        "threat_progress": 0,
        "clue_ids": [],
        "started_at": datetime.now().isoformat(),
        "resolved_at": None,
        "rewards_claimed": False,
        "resolution_summary": "",
        "resolution_path": None,
        "resolution_path_title": "",
        "aftermath": "",
        "related_locations": list(definition.get("related_locations", []) or []),
        "related_npcs": list(definition.get("related_npcs", []) or []),
    })
    time_info = character.setdefault("time", {})
    time_info.update({
        "chapter_status": "active", "anomaly_state": "active",
        "chapter_node_name": definition["title"],
        "chapter_time_remaining": _number(definition.get("base_hours"), 96)
    })
    active = tasks_data.setdefault("active_tasks", [])
    if not any(task.get("id") == completion_task_id for task in active):
        active.append({
            "id": completion_task_id,
            "name": definition.get("task_name", definition["title"]),
            "description": definition.get("task_description", definition.get("rumor", "")),
            "priority": 20,
            "source": "异变传闻",
            "incident_id": definition["id"],
            "created_at": datetime.now().isoformat()
        })
    return definition


def advance_incident_state(
    character: Dict,
    result: Dict,
    action_text: str,
    tasks_data: Optional[Dict] = None,
    battle_ruling: Optional[Dict] = None
) -> Dict[str, Any]:
    """Advance investigation and threat from a resolved turn without gating exploration."""
    incident = ensure_incident_state(character, tasks_data)
    if incident.get("status") == "resolved":
        if any(word in str(action_text or "") for word in NEXT_INCIDENT_WORDS):
            next_definition = start_next_incident(character, tasks_data or {})
            if next_definition:
                result["new_incident"] = {
                    "id": next_definition["id"], "title": next_definition["title"],
                    "rumor": next_definition.get("rumor", "")
                }
                result["tasks_dirty"] = True
                result["incident_state"] = dict(character["incident_state"])
                return character["incident_state"]
        result["incident_state"] = dict(incident)
        return incident

    text = str(action_text or "")
    investigation_gain = 0
    if any(word in text for word in INVESTIGATION_WORDS):
        skill = _number(character.get("player_state", {}).get("调查熟练度"), 0)
        investigation_gain += 6 + min(6, skill / 20)
    for update in result.get("task_updates") or []:
        if isinstance(update, dict) and update.get("action") in ("add", "update", "complete"):
            investigation_gain += 4
    if (battle_ruling or {}).get("is_battle") and "胜利" in str((battle_ruling or {}).get("outcome")):
        investigation_gain += 8

    incident["investigation_progress"] = _clamp(
        _number(incident.get("investigation_progress")) + min(investigation_gain, 14)
    )
    time_info = character.setdefault("time", {})
    remaining_after_turn = _clamp(
        _number(time_info.get("chapter_time_remaining"), 72) - _number(result.get("time_cost"), 0),
        0,
        72
    )
    incident["threat_progress"] = max(
        _clamp(incident.get("threat_progress")),
        round((72 - remaining_after_turn) / 72 * 100, 1)
    )
    progress = _number(incident.get("investigation_progress"))
    incident["stage"] = "confrontation" if progress >= 70 else "investigation" if progress >= 20 else "discovery"
    sync_incident_from_tasks(character, tasks_data or {}, result)
    return incident
