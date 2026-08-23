"""Deterministic long-term player story summaries without an extra AI request."""

from datetime import datetime
from typing import Dict, Iterable, List


SUMMARY_INTERVAL = 12
IMPORTANT_WORDS = (
    "完成", "异变", "约定", "承诺", "背叛", "秘密", "符卡", "击败",
    "恋爱", "亲密", "死亡", "复活", "真相", "加入", "离开",
)


def default_story_summary() -> Dict:
    return {
        "version": 1,
        "recent_arc": "",
        "player_choices": [],
        "key_events": [],
        "unresolved_threads": [],
        "relationship_highlights": [],
        "last_message_id": None,
        "history_count": 0,
        "updated_at": None,
    }


def _compact(value, limit: int = 180) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _unique_recent(values: Iterable[str], limit: int) -> List[str]:
    result = []
    seen = set()
    for value in reversed([_compact(item) for item in values if _compact(item)]):
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return list(reversed(result))


def _speaker(entry: Dict) -> str:
    return str(entry.get("speaker") or entry.get("role") or "")


def _content(entry: Dict) -> str:
    return str(entry.get("content") or entry.get("text") or "")


def _needs_refresh(character: Dict, force: bool) -> bool:
    if force:
        return True
    history = character.get("conversation_history", []) or []
    if not history:
        return False
    summary = character.get("story_summary") or {}
    last_id = summary.get("last_message_id")
    current_id = history[-1].get("message_id") if isinstance(history[-1], dict) else None
    if current_id and current_id == last_id:
        return False
    previous_count = int(summary.get("history_count", 0) or 0)
    if len(history) - previous_count >= SUMMARY_INTERVAL or len(history) < previous_count:
        return True
    return any(word in _content(history[-1]) for word in IMPORTANT_WORDS)


def rebuild_story_summary(character: Dict, tasks_data: Dict = None, force: bool = False) -> bool:
    """Rebuild from current save state so restored branches cannot retain future facts."""
    if not _needs_refresh(character, force):
        return False
    history = [item for item in (character.get("conversation_history", []) or []) if isinstance(item, dict)]
    tasks_data = tasks_data or {}
    active_tasks = tasks_data.get("active_tasks", []) or character.get("active_tasks", []) or []
    completed_tasks = tasks_data.get("completed_tasks", []) or character.get("completed_tasks", []) or []

    narrative = [
        f"{_speaker(item) or '记录'}：{_compact(_content(item), 150)}"
        for item in history[-12:] if _content(item).strip()
    ]
    choices = [
        _content(item) for item in history[-40:]
        if _speaker(item) in ("玩家", "user", "你")
    ]
    completed = [
        f"完成线索「{item.get('name') or item.get('task_name') or item.get('id', '未命名')}」"
        for item in completed_tasks[-8:] if isinstance(item, dict)
    ]
    events = [
        f"{item.get('title', '事件')}：{item.get('description', '')}"
        for item in (character.get("open_events", []) or [])[-8:] if isinstance(item, dict)
    ]
    battles = [
        f"与{item.get('opponent', '对手')}的符卡战：{item.get('outcome', '未裁定')}"
        for item in (character.get("spellcard_history", []) or [])[-5:] if isinstance(item, dict)
    ]
    incident = character.get("incident_state", {}) or {}
    incident_events = []
    if incident.get("status") in ("resolved", "aftermath", "waiting"):
        title = incident.get("title") or incident.get("incident_title") or "异变"
        path = incident.get("resolution_path_title") or incident.get("resolution_path") or "自由解决"
        incident_events.append(f"{title}已通过「{path}」解决")

    unresolved = [
        f"{item.get('name') or item.get('task_name') or item.get('id', '未命名')}：{_compact(item.get('description') or item.get('info'), 120)}"
        for item in active_tasks[-10:] if isinstance(item, dict)
    ]
    relationships = character.get("relationships_map", {}) or {}
    relationship_lines = [f"{name}：{attitude}" for name, attitude in list(relationships.items())[-12:]]

    last_entry = history[-1] if history else {}
    new_summary = {
        "version": 1,
        "recent_arc": "\n".join(narrative[-8:]),
        "player_choices": _unique_recent(choices, 8),
        "key_events": _unique_recent(completed + events + battles + incident_events, 16),
        "unresolved_threads": _unique_recent(unresolved, 10),
        "relationship_highlights": _unique_recent(relationship_lines, 12),
        "last_message_id": last_entry.get("message_id") if isinstance(last_entry, dict) else None,
        "history_count": len(history),
        "updated_at": datetime.now().isoformat(),
    }
    character["story_summary"] = new_summary
    return True


def format_story_summary_for_ai(character: Dict) -> str:
    summary = character.get("story_summary") or {}
    if not summary.get("recent_arc") and not summary.get("key_events"):
        return "暂无长期剧情摘要"
    sections = []
    if summary.get("key_events"):
        sections.append("重要经历：\n- " + "\n- ".join(summary["key_events"][-12:]))
    if summary.get("player_choices"):
        sections.append("玩家近期选择：\n- " + "\n- ".join(summary["player_choices"][-6:]))
    if summary.get("unresolved_threads"):
        sections.append("尚未解决：\n- " + "\n- ".join(summary["unresolved_threads"][-8:]))
    if summary.get("relationship_highlights"):
        sections.append("关系要点：\n- " + "\n- ".join(summary["relationship_highlights"][-8:]))
    if summary.get("recent_arc"):
        sections.append("近期故事弧：\n" + summary["recent_arc"])
    return "\n\n".join(sections)


# The director is stored beside the deterministic summary because both are
# compact, save-resident long-story context and require no extra model call.
DIRECTOR_VERSION = 1


def default_story_director() -> Dict:
    return {
        "version": DIRECTOR_VERSION,
        "exploration_policy": "open",
        "current_arc": {
            "title": "幻想乡自由巡游",
            "status": "roaming",
            "focus": "依照玩家当前选择自然展开",
        },
        "beats": [],
        "unresolved_threads": [],
        "world_clocks": {},
        "suggested_focus": [],
        "applied_turn_ids": [],
        "updated_at": None,
    }


def ensure_story_director(character: Dict) -> Dict:
    director = character.get("story_director")
    if not isinstance(director, dict):
        director = default_story_director()
        character["story_director"] = director
    for key, value in default_story_director().items():
        director.setdefault(key, value)
    director["version"] = DIRECTOR_VERSION
    director["exploration_policy"] = "open"
    return director


def _task_threads(tasks_data: Dict) -> List[Dict]:
    threads = []
    for task in (tasks_data or {}).get("active_tasks", []) or []:
        if not isinstance(task, dict):
            continue
        threads.append({
            "id": str(task.get("id") or ""),
            "title": str(task.get("name") or task.get("task_name") or "未命名线索"),
            "summary": _compact(task.get("description") or task.get("info"), 120),
            "priority": task.get("priority", 100),
            "status": "open",
        })
    return threads[:12]


def update_story_director(
    character: Dict,
    result: Dict,
    action_text: str,
    scene: str,
    tasks_data: Dict,
    npc_name: str = None,
    turn_id: str = None,
) -> Dict:
    """Record continuity hints without creating progression gates."""
    director = ensure_story_director(character)
    applied = director.setdefault("applied_turn_ids", [])
    if turn_id and turn_id in applied:
        return director

    incident = character.get("incident_state", {}) or {}
    incident_status = str(incident.get("status") or "active")
    incident_title = str(incident.get("title") or "幻想乡异变")
    if incident_status in ("resolved", "aftermath", "waiting"):
        director["current_arc"] = {
            "title": "幻想乡自由巡游",
            "status": "roaming",
            "focus": "异变告一段落，等待玩家选择新的方向",
        }
    else:
        director["current_arc"] = {
            "title": incident_title,
            "status": incident_status,
            "focus": f"留意{incident.get('stage') or '当前阶段'}产生的世界变化",
        }
    director["unresolved_threads"] = _task_threads(tasks_data)

    incident_id = str(incident.get("id") or "current_incident")
    director.setdefault("world_clocks", {})[f"incident:{incident_id}"] = {
        "label": incident_title,
        "value": incident.get("threat_progress", 0),
        "stage": incident.get("stage", "discovery"),
        "status": incident_status,
        "updated_at": datetime.now().isoformat(),
        "gates_exploration": False,
    }
    focus = []
    if npc_name:
        focus.append(f"延续与{npc_name}的当前互动")
    if director["unresolved_threads"]:
        focus.append(f"可继续追查「{director['unresolved_threads'][0]['title']}」")
    if incident_status in ("resolved", "aftermath", "waiting"):
        focus.append("也可完全离开当前线索，自由旅行或发展关系")
    else:
        focus.append("可随时转向其他地点、人物或个人目标")
    director["suggested_focus"] = focus[:3]

    time_info = character.get("time", {}) or {}
    beat = {
        "turn_id": turn_id,
        "day": time_info.get("current_day", 1),
        "hour": time_info.get("current_hour", 8),
        "scene": scene,
        "npc_name": npc_name,
        "player_action": _compact(action_text, 120),
        "outcome": _compact(result.get("description"), 180),
        "recorded_at": datetime.now().isoformat(),
    }
    director["beats"] = (director.get("beats", []) + [beat])[-32:]
    if turn_id:
        director["applied_turn_ids"] = (applied + [turn_id])[-100:]
    director["updated_at"] = datetime.now().isoformat()
    result["story_direction"] = {
        "current_arc": director["current_arc"],
        "suggested_focus": director["suggested_focus"],
        "exploration_policy": "open",
    }
    return director


def format_story_director_for_ai(character: Dict) -> str:
    director = ensure_story_director(character)
    arc = director.get("current_arc", {})
    lines = [
        "以下内容仅用于保持长篇叙事连贯，绝不能作为地点、人物或行动的开放条件。",
        "探索政策：完全开放；玩家可以忽略建议并转向任何合理目标。",
        f"当前故事弧：{arc.get('title', '自由巡游')}（{arc.get('status', 'roaming')}）",
        f"当前焦点：{arc.get('focus', '依照玩家选择展开')}",
    ]
    threads = director.get("unresolved_threads", []) or []
    if threads:
        lines.append("未解线索：" + "；".join(item.get("title", "线索") for item in threads[:6]))
    suggestions = director.get("suggested_focus", []) or []
    if suggestions:
        lines.append("可选延续方向：" + "；".join(suggestions[:3]))
    return "\n".join(lines)
