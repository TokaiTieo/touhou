"""Persistent NPC goals, social ties, and rumor knowledge."""

from datetime import datetime
from typing import Dict, Iterable, List
from backend.services.npc_identity_service import canonical_npc_name


GOALS_BY_LOCATION = {
    "博丽神社": "确认结界与异变传闻是否会影响自己的安排",
    "人间之里": "维护与人里的往来并交换可靠消息",
    "红魔馆": "处理红魔馆内部事务并观察外界变化",
    "永远亭": "维持竹林与永远亭的日常秩序",
    "守矢神社": "关注信仰、山中居民与新的愿望",
    "白玉楼": "照看冥界秩序与季节变化",
    "地灵殿": "留意旧地狱的热源和来访者",
}

PERSONAL_PLANS = {
    "博丽灵梦": ["检查御札与结界节点", "安排神社扫除与参拜接待", "核实异变线索并决定是否出面"],
    "雾雨魔理沙": ["采集魔法素材", "试验新的弹幕配方", "交换魔法研究的发现"],
    "东风谷早苗": ["回应参拜者的愿望", "走访山中居民", "准备守矢神社的祭仪"],
    "十六夜咲夜": ["安排红魔馆事务", "确认来访者的需求", "为大小姐准备茶会"],
    "帕秋莉": ["核对魔导书中的异常记录", "研究元素魔法", "整理研究笔记"],
    "爱丽丝": ["调整人偶机关", "准备人偶演出", "记录观众的反应"],
    "八意永琳": ["核对药材库存", "接待病患", "分析异常症状"],
    "风见幽香": ["照看花田", "观察季节变化", "安排来访者的茶点"],
    "西行寺幽幽子": ["观察庭院与幽灵", "寻找当季点心", "与妖梦商量庭院事务"],
    "古明地觉": ["了解地底居民的烦恼", "照顾地灵殿的伙伴", "整理来访记录"],
}


def _hour(character):
    clock = character.get("time", {}) or {}
    return (max(1, int(clock.get("current_day", 1) or 1)) - 1) * 24 + float(clock.get("current_hour", 0) or 0)


def _plan(name, location, profile=None):
    for identity, plan in PERSONAL_PLANS.items():
        if name == identity or name.startswith(identity + "·"):
            return plan
    profile = profile or {}
    hook = str(profile.get("story_hook") or "").strip()
    return [hook[:180] or f"{name}：{GOALS_BY_LOCATION.get(location, '处理自己的日常计划')}",
            f"{name}核实自己关心的消息", f"{name}安排下一次会面"]


def _receive_rumor(character, name, location, hour, agency, npc):
    receipts = agency["rumor_receipts"].setdefault(name, [])
    knowledge = npc.setdefault("rumor_knowledge", {})
    rumors = character.get("world_state", {}).get("rumors", []) or []
    for rumor in reversed(rumors):
        if not isinstance(rumor, dict) or not rumor.get("key") or rumor["key"] in receipts:
            continue
        key = rumor["key"]
        born = agency.setdefault("rumor_first_seen", {}).setdefault(key, rumor.get("game_hour", hour))
        age = hour - float(born)
        if age < 0 or age > 168:
            continue
        audience = rumor.get("audience", [])
        if audience and name not in audience:
            continue
        local = rumor.get("scene") in (None, "", location)
        source = rumor.get("source_npc") or "当地传闻"
        confidence = float(rumor.get("confidence", 0.62) or 0.62)
        if not local:
            if age < 6:
                continue
            contacts = [other for edge in agency["social_graph"].values() if name in edge.get("npcs", [])
                        for other in edge.get("npcs", []) if other != name]
            holder = next((other for other in contacts if key in agency["npcs"].get(other, {}).get("rumor_knowledge", {})
                           and hour - agency["npcs"][other]["rumor_knowledge"][key]["received_hour"] >= 6), None)
            if not holder:
                continue
            source = holder
            confidence = agency["npcs"][holder]["rumor_knowledge"][key]["confidence"] * 0.8
        knowledge[key] = {"source": source, "received_hour": hour, "confidence": round(confidence, 2), "text": rumor.get("text", "")}
        npc["last_rumor"] = rumor.get("text", "")
        npc["last_rumor_source"] = source
        npc["last_rumor_confidence"] = round(confidence, 2)
        agency["rumor_receipts"][name] = (receipts + [key])[-80:]
        npc["rumor_knowledge"] = dict(list(knowledge.items())[-80:])
        return rumor.get("text", "")
    return None


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
    return _plan(name, location)[0]


def record_npc_activity(character: Dict, event: Dict) -> Dict:
    agency = ensure_npc_agency(character)
    name = canonical_npc_name(str(event.get("npc_name") or "").strip())
    event["npc_name"] = name
    if not name:
        return event
    location = str(event.get("location") or "幻想乡")
    npc = agency["npcs"].setdefault(name, {})
    plan = _plan(name, location, event.get("profile"))
    index = int(npc.get("plan_index", 0) or 0)
    tick_id = event.get("id") or f"{event.get('game_hour', _hour(character))}:{name}"
    if npc.get("last_activity_id") != tick_id:
        progress = int(npc.get("plan_progress", 0) or 0) + 1
        if progress >= 3:
            history = npc.setdefault("goal_history", [])
            history.append({"goal": plan[index % len(plan)], "completed_hour": event.get("game_hour", _hour(character))})
            npc["goal_history"] = history[-20:]
            index, progress = index + 1, 0
        npc.update(plan_index=index, plan_progress=progress, last_activity_id=tick_id)
    event["activity"] = plan[index % len(plan)]
    npc.update({
        "current_goal": event["activity"],
        "last_location": location,
        "last_activity": event.get("activity", ""),
        "updated_at": datetime.now().isoformat(),
    })

    rumor = _receive_rumor(character, name, location, float(event.get("game_hour", _hour(character))), agency, npc)
    if rumor:
        event["rumor"] = rumor
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
    names = list(dict.fromkeys(canonical_npc_name(name) for name in names if name))[:5]
    now = datetime.now().isoformat()
    incident = character.get("incident_state", {}) or {}
    for name in names:
        state = agency["npcs"].setdefault(name, {})
        if state.get("last_turn_id") != turn_id and any(word in action_text for word in ("帮助", "协助", "承诺", "约定")):
            state["plan_progress"] = min(2, int(state.get("plan_progress", 0) or 0) + 1)
            state["last_shared_milestone"] = str(action_text)[:180]
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
    requested = list(dict.fromkeys(canonical_npc_name(str(name)) for name in names if name))
    lines = ["人物只知道其亲历、记忆和下列已接收的消息；远方世界回响不能自动视为本人已经知晓。"]
    for name in requested[:limit]:
        state = agency["npcs"].get(name, {})
        line = f"- {name}当前目标：{state.get('current_goal') or _goal(name, scene, character.get('incident_state', {}) or {})}"
        if state.get("last_player_interaction"):
            line += f"；上次与玩家：{state['last_player_interaction']}"
        if state.get("last_rumor"):
            line += f"；最近听闻（来自{state.get('last_rumor_source', '旧日见闻')}，可信度{state.get('last_rumor_confidence', 0.5)}）：{state['last_rumor']}"
        line += f"；计划进度：{state.get('plan_progress', 0)}/3"
        if state.get("last_shared_milestone"):
            line += f"；共同经历：{state['last_shared_milestone']}"
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
