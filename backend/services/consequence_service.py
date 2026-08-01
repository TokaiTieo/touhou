"""Persistent cause/effect chains that never gate player exploration."""

import hashlib
from datetime import datetime
from typing import Dict, List, Optional


HELPFUL_WORDS = ("帮助", "修复", "稳定", "救助", "保护", "调停", "归还", "道歉")
HARMFUL_WORDS = ("破坏", "纵火", "偷窃", "抢夺", "袭击无辜", "欺骗居民")


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _absolute_hour(character: Dict) -> float:
    time_info = character.get("time", {}) or {}
    day = max(1, int(_number(time_info.get("current_day"), 1)))
    return (day - 1) * 24 + _number(time_info.get("current_hour"), 0)


def ensure_world_state(character: Dict) -> Dict:
    state = character.setdefault("world_state", {})
    if not isinstance(state, dict):
        state = {}
        character["world_state"] = state
    state.setdefault("flags", {})
    state.setdefault("locations", {})
    state.setdefault("factions", {})
    state.setdefault("rumors", [])
    character.setdefault("consequence_log", [])
    character.setdefault("deferred_consequences", [])
    return state


def _change_location_state(state: Dict, scene: str, effect: str, magnitude: float) -> Dict:
    locations = state.setdefault("locations", {})
    location = locations.setdefault(scene, {"pressure": 0, "history": []})
    old = _number(location.get("pressure"), 0)
    new = max(-100, min(100, old + magnitude))
    location["pressure"] = round(new, 2)
    location["last_effect"] = effect
    location["updated_at"] = datetime.now().isoformat()
    history = location.setdefault("history", [])
    history.append({"effect": effect, "magnitude": magnitude, "created_at": location["updated_at"]})
    location["history"] = history[-30:]
    return {"target": scene, "effect": effect, "magnitude": magnitude, "value": location["pressure"]}


def _add_rumor(state: Dict, text: str, scene: str, source_id: str) -> Optional[Dict]:
    text = str(text or "").strip()
    if not text:
        return None
    rumors = state.setdefault("rumors", [])
    key = hashlib.sha256(f"{scene}|{text}".encode("utf-8")).hexdigest()[:12]
    if any(item.get("key") == key for item in rumors if isinstance(item, dict)):
        return None
    rumor = {
        "key": key,
        "text": text[:300],
        "scene": scene,
        "source_consequence_id": source_id,
        "created_at": datetime.now().isoformat(),
    }
    rumors.append(rumor)
    state["rumors"] = rumors[-80:]
    return rumor


def advance_due_consequences(character: Dict) -> List[Dict]:
    ensure_world_state(character)
    current_hour = _absolute_hour(character)
    resolved = []
    for item in character.get("deferred_consequences", []):
        if not isinstance(item, dict) or item.get("status") != "pending":
            continue
        if _number(item.get("due_hour"), current_hour + 1) > current_hour:
            continue
        item["status"] = "resolved"
        item["resolved_at"] = datetime.now().isoformat()
        resolved.append(item)
        _add_rumor(
            character["world_state"],
            item.get("effect", "此前行动产生了新的回响。"),
            item.get("scene", "幻想乡"),
            item.get("source_consequence_id", ""),
        )
    return resolved


def record_turn_consequence(
    character: Dict,
    result: Dict,
    action_text: str,
    scene: str,
    source: str,
    npc_name: str = None,
    turn_id: str = None,
) -> Dict:
    state = ensure_world_state(character)
    advance_due_consequences(character)
    log = character.setdefault("consequence_log", [])
    if turn_id:
        existing = next((item for item in log if item.get("source_turn_id") == turn_id), None)
        if existing:
            result["consequence_record_id"] = existing["id"]
            result["consequence_summary"] = existing.get("summary", [])
            return existing

    absolute_hour = _absolute_hour(character)
    seed = f"{character.get('character_id')}|{turn_id}|{absolute_hour}|{action_text}|{len(log)}"
    consequence_id = f"cfx_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    direct: List[Dict] = []
    delayed: List[Dict] = []
    summary: List[str] = []

    for key, delta in (result.get("player_state_delta") or {}).items():
        if _number(delta):
            direct.append({"type": "player_state", "target": key, "delta": delta})
    for update in result.get("task_updates", []) or []:
        if not isinstance(update, dict):
            continue
        label = {"add": "新增线索", "update": "推进线索", "complete": "完成线索"}.get(update.get("action"))
        if label:
            name = update.get("name") or update.get("task_name") or update.get("info") or update.get("task_id")
            direct.append({"type": "task", "action": update.get("action"), "target": str(name)[:180]})
            summary.append(f"{label}：{str(name)[:60]}")
            if update.get("action") == "complete":
                delayed.append({
                    "effect": f"关于「{str(name)[:80]}」已经完成的消息开始在相关人物之间传开。",
                    "delay_hours": 6,
                })
                state["flags"][f"task_completed:{update.get('task_id') or name}"] = True

    relationship_delta = result.get("relationship_progress_delta") or {}
    for name, update in relationship_delta.items():
        direct.append({"type": "relationship", "target": name, "change": update})
    for update in (result.get("progression_delta") or {}).get("reputation", []):
        direct.append({"type": "reputation", **update})
        state["factions"][update.get("faction", "未知势力")] = update.get("value")
    if result.get("new_location"):
        direct.append({"type": "movement", "target": result.get("new_location")})
    if result.get("spellcard_result"):
        battle = result["spellcard_result"]
        direct.append({
            "type": "spellcard",
            "target": battle.get("opponent"),
            "outcome": battle.get("outcome"),
        })
        summary.append(f"符卡结果：{battle.get('outcome', '已裁定')}")
    if result.get("incident_resolution"):
        incident = result["incident_resolution"]
        state["flags"][f"incident_resolved:{incident.get('id') or incident.get('title')}"] = True
        summary.append(f"异变结算：{incident.get('summary') or incident.get('title')}")
    if result.get("offscreen_updates"):
        direct.append({
            "type": "npc_offscreen",
            "count": len(result["offscreen_updates"]),
            "event_ids": [item.get("id") for item in result["offscreen_updates"]],
        })
        summary.append(f"记录了 {len(result['offscreen_updates'])} 条人物动向")

    action = str(action_text or "")
    deterministic_magnitude = 0
    deterministic_effect = ""
    if any(word in action for word in HARMFUL_WORDS):
        deterministic_magnitude = 3
        deterministic_effect = "公开的破坏性行动使当地气氛更加紧张"
        delayed.append({"effect": f"{scene}开始流传关于这次危险行动的议论。", "delay_hours": 4})
    elif any(word in action for word in HELPFUL_WORDS):
        deterministic_magnitude = -1
        deterministic_effect = "主动协助让当地局势稍微安定"
    if deterministic_effect:
        direct.append({"type": "location", **_change_location_state(
            state, scene, deterministic_effect, deterministic_magnitude
        )})
        summary.append(deterministic_effect)

    for effect in result.get("world_effects", []) or []:
        if not isinstance(effect, dict):
            continue
        target = str(effect.get("target") or scene).strip()
        text = str(effect.get("effect") or "").strip()
        magnitude = max(-10, min(10, _number(effect.get("magnitude"), 0)))
        delay = max(0, min(168, _number(effect.get("delay_hours"), 0)))
        kind = effect.get("kind", "location")
        if delay:
            delayed.append({"effect": text, "delay_hours": delay, "scene": target})
        elif kind == "rumor":
            rumor = _add_rumor(state, text, target, consequence_id)
            if rumor:
                direct.append({"type": "rumor", **rumor})
        elif kind == "flag":
            state["flags"][target] = text or True
            direct.append({"type": "flag", "target": target, "value": state["flags"][target]})
        else:
            direct.append({"type": "location", **_change_location_state(state, target, text, magnitude)})

    deferred_store = character.setdefault("deferred_consequences", [])
    for index, item in enumerate(delayed):
        deferred = {
            "id": f"{consequence_id}_later_{index}",
            "source_consequence_id": consequence_id,
            "scene": item.get("scene") or scene,
            "effect": item.get("effect", "此前行动产生了新的回响。")[:300],
            "due_hour": round(absolute_hour + _number(item.get("delay_hours"), 1), 2),
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }
        deferred_store.append(deferred)
    character["deferred_consequences"] = deferred_store[-120:]

    if delayed:
        summary.append(f"留下 {len(delayed)} 项后续回响")
    if not summary and direct:
        summary.append(f"记录了 {len(direct)} 项状态变化")
    record = {
        "id": consequence_id,
        "source_turn_id": turn_id,
        "source": source,
        "cause": str(action_text or "")[:500],
        "scene": scene,
        "npc_name": npc_name,
        "game_day": character.get("time", {}).get("current_day", 1),
        "game_hour": character.get("time", {}).get("current_hour", 0),
        "direct_effects": direct,
        "deferred_effect_ids": [
            item["id"] for item in character["deferred_consequences"]
            if item.get("source_consequence_id") == consequence_id
        ],
        "summary": summary[:8],
        "created_at": datetime.now().isoformat(),
    }
    log.append(record)
    character["consequence_log"] = log[-200:]
    result["consequence_record_id"] = consequence_id
    result["consequence_summary"] = record["summary"]
    return record


def format_consequence_context(character: Dict, limit: int = 8) -> str:
    ensure_world_state(character)
    log = character.get("consequence_log", [])[-limit:]
    pending = [
        item for item in character.get("deferred_consequences", [])
        if isinstance(item, dict) and item.get("status") == "pending"
    ][-5:]
    lines = []
    for item in log:
        joined = "；".join(item.get("summary", [])) or "状态已记录"
        lines.append(f"- {item.get('scene', '幻想乡')}：{joined}")
    for item in pending:
        lines.append(f"- 待发生：{item.get('effect')}（不限制玩家行动）")
    return "\n".join(lines) if lines else "暂无需要延续的世界回响。"
