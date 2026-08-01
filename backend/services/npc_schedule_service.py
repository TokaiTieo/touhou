"""Data-driven deterministic NPC schedules; exploration always remains open."""

import json
import hashlib
from pathlib import Path
from typing import Optional, Tuple


FALLBACK_SCHEDULES = {
    "博丽灵梦": {"morning": "博丽神社", "day": "博丽神社", "evening": "人间之里", "night": "博丽神社"},
    "雾雨魔理沙": {"morning": "雾雨魔法店", "day": "魔法之森", "evening": "博丽神社", "night": "雾雨魔法店"},
    "东风谷早苗": {"morning": "守矢神社", "day": "妖怪之山", "evening": "守矢神社", "night": "守矢神社"},
    "上白泽慧音": {"morning": "人间之里", "day": "人间之里", "evening": "人间之里", "night": "迷途竹林"},
    "射命丸文": {"morning": "妖怪之山", "day": "人间之里", "evening": "博丽神社", "night": "妖怪之山"},
    "十六夜咲夜": {"morning": "红魔馆", "day": "红魔馆", "evening": "红魔馆", "night": "雾之湖"},
    "魂魄妖梦": {"morning": "白玉楼", "day": "白玉楼", "evening": "人间之里", "night": "白玉楼"},
    "藤原妹红": {"morning": "迷途竹林", "day": "人间之里", "evening": "迷途竹林", "night": "迷途竹林"},
}

LOCATION_ALIASES = {
    "迷途竹林": "永远亭",
    "旧地狱": "地灵殿",
}


def load_schedules(path: Path = None) -> dict:
    if path is None:
        try:
            from backend.config import WORLDS_DIR, DEFAULT_WORLD_ID
            path = WORLDS_DIR / DEFAULT_WORLD_ID / "npc_schedules.json"
        except ImportError:
            path = None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        schedules = data.get("schedules", {})
        return schedules if isinstance(schedules, dict) and schedules else FALLBACK_SCHEDULES
    except (OSError, TypeError, json.JSONDecodeError, AttributeError):
        return FALLBACK_SCHEDULES


def period_for_hour(hour: float) -> str:
    hour = float(hour or 0) % 24
    if 5 <= hour < 10:
        return "morning"
    if 10 <= hour < 17:
        return "day"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def _absolute_hour(character: dict) -> float:
    time_info = (character or {}).get("time", {})
    return (max(1, int(time_info.get("current_day", 1) or 1)) - 1) * 24 + float(time_info.get("current_hour", 0) or 0)


def scheduled_location(name: str, hour: float, default_location: str, character: dict = None) -> Tuple[str, Optional[str]]:
    schedule = load_schedules().get(name)
    if not schedule:
        return default_location, None
    period = period_for_hour(hour)
    location = schedule.get(period, default_location)
    labels = {"morning": "清晨", "day": "白天", "evening": "黄昏", "night": "夜间"}
    note = f"{labels[period]}通常在{location}活动"
    if character:
        runtime = character.setdefault("npc_runtime", {}).get(name, {})
        if (
            runtime.get("simulated_location")
            and _absolute_hour(character) <= float(runtime.get("simulated_until_hour", -1))
        ):
            return runtime["simulated_location"], str(runtime.get("simulated_activity") or "正在处理自己的事务")
        if runtime.get("temporary_location") and _absolute_hour(character) <= float(runtime.get("until_hour", -1)):
            temporary = runtime["temporary_location"]
            return LOCATION_ALIASES.get(temporary, temporary), str(runtime.get("reason") or "临时外出")

        # A current personal event can move its NPC to the recorded event scene.
        for event in reversed(character.get("open_events", []) or []):
            if isinstance(event, dict) and event.get("npc_name") == name and event.get("source") == "dynamic_event_v1":
                event_scene = event.get("scene") or location
                return LOCATION_ALIASES.get(event_scene, event_scene), f"正在关注「{event.get('title', '个人事件')}」"

        incident = character.get("incident_state", {}) or {}
        if name in (incident.get("related_npcs") or []) and incident.get("stage") in ("investigation", "confrontation"):
            related = incident.get("related_locations") or []
            if related:
                index = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:4], 16) % len(related)
                incident_scene = related[index]
                return LOCATION_ALIASES.get(incident_scene, incident_scene), f"正在调查「{incident.get('title', '当前异变')}」"

        progress = (character.get("relationship_progress", {}) or {}).get(name, {})
        score = float(progress.get("score", 0) or 0) if isinstance(progress, dict) else 0
        player_scene = character.get("status", {}).get("current_scene")
        if score >= 55 and player_scene:
            seed = f"{character.get('character_id')}|{name}|{int(_absolute_hour(character) // 6)}"
            if int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6], 16) % 100 < 18:
                return player_scene, "因与你的关系主动前来"
    return LOCATION_ALIASES.get(location, location), note


def place_scheduled_npcs(npcs: list, scene_name: str, hour: float, static_matches: list = None, character: dict = None) -> list:
    static_matches = static_matches or []
    schedules = load_schedules()
    placed = [dict(npc) for npc in static_matches if npc.get("name") not in schedules]
    for npc in npcs:
        default = npc.get("location_name") or npc.get("location_id") or ""
        location, note = scheduled_location(npc.get("name", ""), hour, default, character)
        if location == scene_name:
            item = dict(npc)
            if note:
                item["schedule_status"] = note
            if not any(existing.get("id") == item.get("id") for existing in placed):
                placed.append(item)
    # Never leave a previously populated scene empty because of schedule metadata.
    return placed or static_matches
