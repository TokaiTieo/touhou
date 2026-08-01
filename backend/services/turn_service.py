"""Deterministic state changes shared by environment and dialogue routes."""

from datetime import datetime
from typing import Dict, Iterable


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def format_time_cost(cost: float) -> str:
    minutes = max(0, round(_number(cost) * 60))
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def apply_time_progression(character: Dict, result: Dict) -> bool:
    time_cost = max(0, min(12, _number(result.get("time_cost"), 0)))
    if time_cost <= 0:
        return False
    time_info = character.setdefault("time", {})
    current_hour = _number(time_info.get("current_hour"), 8)
    current_day = int(_number(time_info.get("current_day"), 1))
    total_hour = current_hour + time_cost
    time_info["current_day"] = current_day + int(total_hour // 24)
    time_info["current_hour"] = total_hour % 24
    if time_info.get("anomaly_state") != "waiting":
        remaining = _number(time_info.get("chapter_time_remaining"), 72)
        time_info["chapter_time_remaining"] = max(0, remaining - time_cost)
    result["time_cost"] = time_cost
    result["description"] = f"{result.get('description', '')}\n\n⏰ 过了{format_time_cost(time_cost)}"
    return True


def apply_task_updates(
    tasks_data: Dict,
    updates: Iterable[Dict],
    default_source: str = "ai",
    turn_id: str = None,
) -> bool:
    applied_turns = tasks_data.setdefault("applied_turn_ids", [])
    if turn_id and turn_id in applied_turns:
        return False
    active = tasks_data.setdefault("active_tasks", [])
    completed = tasks_data.setdefault("completed_tasks", [])
    changed = False
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        task_id = update.get("task_id")
        action = update.get("action")
        info = str(update.get("info") or "")
        task = next((item for item in active if item.get("id") == task_id), None)
        if action in ("update", "complete") and task:
            task["description"] = info
            changed = True
            if action == "complete":
                active.remove(task)
                task["completed_at"] = datetime.now().isoformat()
                task["completion_description"] = info
                if not any(item.get("id") == task.get("id") for item in completed):
                    completed.append(task)
        elif action == "add":
            new_id = task_id or f"task_{int(datetime.now().timestamp() * 1000)}_{len(active)}"
            if any(item.get("id") == new_id for item in active + completed):
                continue
            active.append({
                "id": new_id,
                "name": update.get("name") or update.get("task_name") or "新线索",
                "description": info,
                "priority": max(1, min(1000, int(update.get("priority", 100)))),
                "created_at": datetime.now().isoformat(),
                "source": update.get("source") or default_source
            })
            changed = True
        elif action == "update_priority" and task:
            task["priority"] = max(1, min(1000, int(update.get("priority", 100))))
            changed = True
    if changed:
        active.sort(key=lambda item: item.get("priority", 100))
    if turn_id:
        tasks_data["applied_turn_ids"] = (applied_turns + [turn_id])[-100:]
    return changed
