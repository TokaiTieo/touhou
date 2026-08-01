"""Deterministic lightweight NPC activity while the player is elsewhere."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from backend.services.npc_schedule_service import period_for_hour, scheduled_location


ACTIVITIES = {
    "博丽神社": ("检查结界的细微波动", "整理神社附近的异变传闻"),
    "人间之里": ("与里民交换消息", "处理自己的日常事务"),
    "红魔馆": ("处理红魔馆内的日常", "留意馆外的异常气息"),
    "魔法之森": ("采集带有魔力的素材", "研究森林里的异常"),
    "永远亭": ("整理药材与来访记录", "巡视竹林边缘"),
    "守矢神社": ("回应参拜者的愿望", "观察妖怪之山的信仰变化"),
    "妖怪之山": ("巡查山中的动静", "与山中居民交换情报"),
    "白玉楼": ("照看庭院与幽灵", "关注冥界边缘的变化"),
    "地灵殿": ("巡视旧地狱的热源", "处理地底居民带来的消息"),
    "命莲寺": ("参与寺内修行", "调解来访者之间的小冲突"),
    "神灵庙": ("观察欲望与灵气的流向", "整理道场事务"),
    "太阳花田": ("照料花田", "观察季节与妖力的变化"),
}
DEFAULT_ACTIVITIES = ("沿途收集新的见闻", "处理自己的日常计划")


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _absolute_hour(character: Dict) -> float:
    time_info = character.get("time", {}) or {}
    return (max(1, int(_number(time_info.get("current_day"), 1))) - 1) * 24 + _number(
        time_info.get("current_hour"), 0
    )


def _load_npcs(path: Optional[Path] = None) -> List[Dict]:
    if path is None:
        try:
            from backend.config import DEFAULT_WORLD_ID, WORLDS_DIR
            path = WORLDS_DIR / DEFAULT_WORLD_ID / "npcs" / "npc_index.json"
        except ImportError:
            return []
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return [
            item for item in document.get("npcs", [])
            if isinstance(item, dict) and item.get("active", True) and not item.get("dead", False)
        ]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _pick_activity(name: str, location: str, tick_hour: int) -> str:
    options = ACTIVITIES.get(location, DEFAULT_ACTIVITIES)
    digest = hashlib.sha256(f"{name}|{location}|{tick_hour}".encode("utf-8")).hexdigest()
    return options[int(digest[:4], 16) % len(options)]


def simulate_offscreen_npcs(
    character: Dict,
    elapsed_hours: float,
    npcs: Optional[List[Dict]] = None,
    npc_index_path: Optional[Path] = None,
    max_events_per_tick: int = 4,
) -> List[Dict]:
    """Advance crossed six-hour ticks and persist a bounded activity ledger."""
    elapsed = max(0, min(48, _number(elapsed_hours, 0)))
    current_hour = _absolute_hour(character)
    start_hour = max(0, current_hour - elapsed)
    simulation = character.setdefault("npc_simulation", {
        "last_simulated_hour": start_hour,
        "events": [],
    })
    simulation.setdefault("events", [])
    simulation["last_simulated_hour"] = max(
        _number(simulation.get("last_simulated_hour"), start_hour),
        start_hour,
    )
    if elapsed <= 0:
        simulation["last_simulated_hour"] = current_hour
        return []

    first_tick = int(start_hour // 6) + 1
    last_tick = int(current_hour // 6)
    candidates = npcs if npcs is not None else _load_npcs(npc_index_path)
    runtime = character.setdefault("npc_runtime", {})
    generated = []
    for tick in range(first_tick, last_tick + 1):
        tick_hour = tick * 6
        ranked = sorted(
            candidates,
            key=lambda npc: hashlib.sha256(
                f"{character.get('character_id')}|{tick_hour}|{npc.get('name')}".encode("utf-8")
            ).hexdigest(),
        )
        for npc in ranked[:max_events_per_tick]:
            name = str(npc.get("name") or "").strip()
            if not name:
                continue
            default_location = npc.get("location_name") or npc.get("location_id") or "幻想乡"
            location, _ = scheduled_location(name, tick_hour % 24, default_location)
            activity = _pick_activity(name, location, tick_hour)
            event_id = f"npcsim_{tick_hour}_{npc.get('id') or hashlib.sha1(name.encode()).hexdigest()[:8]}"
            if any(item.get("id") == event_id for item in simulation["events"]):
                continue
            event = {
                "id": event_id,
                "npc_id": npc.get("id"),
                "npc_name": name,
                "location": location,
                "activity": activity,
                "period": period_for_hour(tick_hour),
                "game_hour": tick_hour,
                "created_at": datetime.now().isoformat(),
            }
            generated.append(event)
            simulation["events"].append(event)
            runtime_state = runtime.setdefault(name, {})
            runtime_state["simulated_location"] = location
            runtime_state["simulated_activity"] = activity
            runtime_state["simulated_until_hour"] = tick_hour + 6
            runtime_state["last_simulated_at"] = event["created_at"]
    simulation["events"] = simulation["events"][-160:]
    simulation["last_simulated_hour"] = current_hour
    return generated


def format_npc_simulation_context(
    character: Dict,
    scene: str = "",
    npc_name: str = "",
    limit: int = 8,
) -> str:
    events = (character.get("npc_simulation", {}) or {}).get("events", [])
    relevant = [
        item for item in events
        if isinstance(item, dict)
        and (not scene or item.get("location") == scene or item.get("npc_name") == npc_name)
    ]
    if not relevant:
        relevant = [item for item in events if isinstance(item, dict)]
    lines = [
        f"- {item.get('npc_name')}在{item.get('location')}：{item.get('activity')}"
        for item in relevant[-limit:]
    ]
    return "\n".join(lines) if lines else "暂无新的离屏人物动向。"
