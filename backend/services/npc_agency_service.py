"""Persistent NPC goals, social ties, and rumor knowledge."""

import hashlib
from datetime import datetime
from typing import Dict, Iterable, List


GOALS_BY_LOCATION = {
    "博丽神社": "确认结界与异变传闻是否会影响自己的安排",
    "人间之里": "维护与人里的往来并交换可靠消息",
    "红魔馆": "处理红魔馆内部事务并观察外界变化",
    "永远亭": "维持竹林与永远亭的日常秩序",
    "守矢神社": "关注信仰、山中居民与新的愿望",
    "白玉楼": "照看冥界秩序与季节变化",
    "地灵殿": "留意旧地狱的热源和来访者",
}


def ensure_npc_agency(character: Dict) -> Dict:
    agency = character.setdefault("npc_agency", {})
    if not isinstance(agency, dict):
        agency = {}
        character["npc_agency"] = agency
    agency.setdefault("version", 1)
    agency.setdefault("npcs", {})
    agency.setdefault("social_graph", {})
    agency.setdefault("rumor_receipts", {})
    return agency


def _goal(name: str, location: str, incident: Dict) -> str:
    if name in set(incident.get("related_npcs", []) or []):
        return f"以自己的立场应对「{incident.get('title', '当前异变')}」"
    return GOALS_BY_LOCATION.get(location, "继续自己的日常计划，并判断是否介入玩家经历")


def record_npc_activity(character: Dict, event: Dict) -> Dict:
    agency = ensure_npc_agency(character)
    name = str(event.get("npc_name") or "").strip()
    if not name:
        return event
    location = str(event.get("location") or "幻想乡")
    incident = character.get("incident_state", {}) or {}
    npc = agency["npcs"].setdefault(name, {})
    npc.update({
        "current_goal": _goal(name, location, incident),
        "last_location": location,
        "last_activity": event.get("activity", ""),
        "updated_at": datetime.now().isoformat(),
    })

    rumors = (character.get("world_state", {}) or {}).get("rumors", []) or []
    if rumors:
        rumor = rumors[-1]
        key = rumor.get("key")
        receipts = agency["rumor_receipts"].setdefault(name, [])
        if key and key not in receipts:
            receipts.append(key)
            agency["rumor_receipts"][name] = receipts[-20:]
            npc["last_rumor"] = rumor.get("text", "")
            event["rumor"] = rumor.get("text", "")
    event["goal"] = npc["current_goal"]
    return event


def record_player_interaction(
    character: Dict,
    *,
    npc_name: str = "",
    scene_npcs: Iterable[Dict] = (),
    scene: str,
    action_text: str,
    outcome: str,
    turn_id: str = None,
) -> None:
    agency = ensure_npc_agency(character)
    names: List[str] = []
    if npc_name:
        names.append(npc_name)
    names.extend(
        str(item.get("name") or "") for item in scene_npcs or [] if isinstance(item, dict)
    )
    names = list(dict.fromkeys(name for name in names if name))[:5]
    now = datetime.now().isoformat()
    incident = character.get("incident_state", {}) or {}
    for name in names:
        state = agency["npcs"].setdefault(name, {})
        state.update({
            "current_goal": state.get("current_goal") or _goal(name, scene, incident),
            "last_player_interaction": str(action_text or "")[:180],
            "last_player_outcome": str(outcome or "")[:240],
            "last_turn_id": turn_id,
            "last_location": scene,
            "updated_at": now,
        })
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            pair = "|".join(sorted((left, right)))
            edge = agency["social_graph"].setdefault(pair, {
                "npcs": sorted((left, right)), "shared_scenes": 0, "last_scene": scene,
            })
            if edge.get("last_turn_id") != turn_id:
                edge["shared_scenes"] = int(edge.get("shared_scenes", 0) or 0) + 1
            edge.update({"last_scene": scene, "last_turn_id": turn_id, "updated_at": now})


def format_npc_agency_context(
    character: Dict, names: Iterable[str], scene: str = "", limit: int = 6
) -> str:
    agency = ensure_npc_agency(character)
    requested = list(dict.fromkeys(str(name) for name in names if name))
    lines = []
    for name in requested[:limit]:
        state = agency["npcs"].get(name, {})
        line = f"- {name}当前目标：{state.get('current_goal') or _goal(name, scene, character.get('incident_state', {}) or {})}"
        if state.get("last_player_interaction"):
            line += f"；上次与玩家：{state['last_player_interaction']}"
        if state.get("last_rumor"):
            line += f"；最近听闻：{state['last_rumor']}"
        lines.append(line)
    requested_set = set(requested)
    for edge in (agency.get("social_graph", {}) or {}).values():
        if not isinstance(edge, dict):
            continue
        edge_npcs = set(edge.get("npcs", []) or [])
        if len(edge_npcs & requested_set) < 1:
            continue
        names_text = "与".join(edge.get("npcs", []) or [])
        lines.append(
            f"- 人物往来：{names_text}曾在{edge.get('last_scene', '幻想乡')}共同出现"
            f"（共同场景{edge.get('shared_scenes', 0)}次）"
        )
        if len(lines) >= limit + 2:
            break
    return "\n".join(lines) if lines else "相关人物仍按自己的日程与目标行动。"
