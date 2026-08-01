"""Deterministic inventory and faction reputation progression."""

from datetime import datetime
from typing import Dict, Iterable, List


SCENE_FACTIONS = {
    "博丽神社": "博丽神社", "人间之里": "人间之里", "红魔馆": "红魔馆",
    "雾之湖": "红魔馆周边", "永远亭": "永远亭", "迷途竹林": "竹林居民",
    "白玉楼": "白玉楼", "守矢神社": "守矢神社", "妖怪之山": "妖怪之山",
    "地灵殿": "地灵殿", "旧地狱": "旧地狱", "命莲寺": "命莲寺",
    "神灵庙": "神灵庙", "太阳花田": "太阳花田", "地狱": "是非曲直厅",
    "虹龙洞集市": "虹龙洞集市", "月之都": "月之都", "畜生界": "畜生界",
}
HELPFUL_WORDS = ("帮助", "救助", "修复", "稳定", "调停", "保护", "完成", "归还", "道歉")
HARMFUL_WORDS = ("破坏", "偷窃", "抢夺", "袭击无辜", "欺骗居民", "纵火")


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=-100, high=100):
    return max(low, min(high, value))


def _item_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "").strip()
    return str(value or "").strip()


def ensure_inventory_state(character: Dict) -> Dict:
    state = character.setdefault("inventory_state", {"items": [], "capacity": 30, "currency": 0})
    if not isinstance(state, dict):
        state = {"items": [], "capacity": 30, "currency": 0}
        character["inventory_state"] = state
    items = state.setdefault("items", [])
    state.setdefault("capacity", 30)
    state.setdefault("currency", 0)
    known = {_item_name(item) for item in items if _item_name(item)}
    legacy_values: List = list(character.get("inventory", []) or [])
    resources = character.get("resources", {}) or {}
    legacy_values.extend(resources.get("道具", []) or [])
    legacy_values.extend(resources.get("药材", []) or [])
    for value in legacy_values:
        name = _item_name(value)
        if not name or name in known:
            continue
        if isinstance(value, dict):
            item = {**value}
            item.setdefault("name", name)
            item.setdefault("quantity", 1)
        else:
            item = {"name": name, "quantity": 1, "category": "旧版物品", "description": "从旧存档自动索引"}
        items.append(item)
        known.add(name)
    return state


def _find_item(items: Iterable[Dict], name: str):
    return next((item for item in items if isinstance(item, dict) and _item_name(item) == name), None)


def _apply_known_item_effect(character: Dict, name: str, result: Dict) -> None:
    state = character.setdefault("player_state", {})
    delta = result.setdefault("player_state_delta", {})

    def change(key, amount, ceiling=100):
        old = _number(state.get(key), 0)
        new = max(0, min(ceiling, old + amount))
        if new != old:
            state[key] = int(new) if float(new).is_integer() else round(new, 2)
            delta[key] = round(_number(delta.get(key), 0) + new - old, 2)

    if any(word in name for word in ("恢复药", "急救药", "绷带", "伤药")):
        change("受伤", -20)
    if any(word in name for word in ("茶", "便当", "饭团", "点心")):
        change("疲劳", -12)
    if any(word in name for word in ("灵力", "御神酒", "魔力药")):
        change("灵力", 15, 999999)


def _apply_inventory_updates(character: Dict, updates: List[Dict], result: Dict) -> List[Dict]:
    state = ensure_inventory_state(character)
    items = state["items"]
    applied = []
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        action = str(update.get("action") or "add")
        name = _item_name(update)
        quantity = max(1, min(999, int(_number(update.get("quantity"), 1))))
        if not name:
            continue
        existing = _find_item(items, name)
        if action == "add":
            if existing:
                existing["quantity"] = int(_number(existing.get("quantity"), 1)) + quantity
            elif character.get("gm_mode") or len(items) < int(_number(state.get("capacity"), 30)):
                items.append({
                    "name": name,
                    "quantity": quantity,
                    "category": str(update.get("category") or "道具"),
                    "description": str(update.get("description") or ""),
                    "acquired_at": datetime.now().isoformat(),
                })
            else:
                applied.append({"action": "rejected", "name": name, "reason": "行囊已满"})
                continue
        elif action in ("remove", "use"):
            if not existing or _number(existing.get("quantity"), 0) < quantity:
                applied.append({"action": "rejected", "name": name, "reason": "数量不足"})
                continue
            existing["quantity"] = int(_number(existing.get("quantity"), 0)) - quantity
            if action == "use":
                _apply_known_item_effect(character, name, result)
            if existing["quantity"] <= 0:
                items.remove(existing)
        applied.append({"action": action, "name": name, "quantity": quantity})
    return applied


def _change_reputation(character: Dict, faction: str, delta: float, reason: str, source: str) -> Dict:
    reputation = character.setdefault("reputation", {})
    old = _number(reputation.get(faction), 0)
    new = _clamp(old + delta)
    reputation[faction] = int(new) if float(new).is_integer() else round(new, 2)
    record = {
        "faction": faction, "delta": round(new - old, 2), "value": reputation[faction],
        "reason": reason, "source": source, "created_at": datetime.now().isoformat(),
    }
    history = character.setdefault("reputation_history", [])
    history.append(record)
    character["reputation_history"] = history[-80:]
    return record


def apply_progression_updates(character: Dict, result: Dict, scene: str, action_text: str) -> Dict:
    """Validate and apply model updates plus a small deterministic local reputation effect."""
    inventory_delta = _apply_inventory_updates(character, result.get("inventory_updates", []), result)
    reputation_delta = []
    for update in result.get("reputation_updates", []) or []:
        if not isinstance(update, dict):
            continue
        faction = str(update.get("faction") or "").strip()
        delta = _clamp(_number(update.get("delta"), 0), -12, 12)
        if faction and delta:
            reputation_delta.append(_change_reputation(
                character, faction, delta, str(update.get("reason") or "本回合行为"), "ai_validated"
            ))

    faction = SCENE_FACTIONS.get(scene)
    text = str(action_text or "")
    deterministic = 0
    reason = ""
    if faction and any(item.get("action") == "complete" for item in result.get("task_updates", []) if isinstance(item, dict)):
        deterministic, reason = 3, "在当地完成重要线索"
    elif faction and any(word in text for word in HARMFUL_WORDS):
        deterministic, reason = -2, "公开行为损害当地利益"
    elif faction and any(word in text for word in HELPFUL_WORDS):
        deterministic, reason = 1, "主动帮助当地居民"
    if deterministic and not any(item.get("faction") == faction for item in reputation_delta):
        reputation_delta.append(_change_reputation(character, faction, deterministic, reason, "deterministic"))

    progression = {"inventory": inventory_delta, "reputation": reputation_delta}
    result["progression_delta"] = progression
    return progression


def format_progression_for_ai(character: Dict) -> str:
    inventory = ensure_inventory_state(character)
    item_lines = [
        f"{item.get('name')}×{int(_number(item.get('quantity'), 1))}"
        for item in inventory.get("items", [])[-12:] if isinstance(item, dict)
    ]
    reputation = character.get("reputation", {}) or {}
    relation_progress = character.get("relationship_progress", {}) or {}
    spellcards = character.get("spellcard_mastery", {}) or {}
    relations = [
        f"{name}:{value.get('stage', '未定')}({value.get('score', 0)})"
        for name, value in list(relation_progress.items())[-10:] if isinstance(value, dict)
    ]
    return "\n".join([
        "持有物品：" + ("、".join(item_lines) if item_lines else "无"),
        "势力声望：" + ("、".join(f"{name}:{value}" for name, value in reputation.items()) if reputation else "尚未建立"),
        "关系阶段：" + ("、".join(relations) if relations else "尚未建立"),
        "符卡熟练：" + (
            "、".join(
                f"{name}:{value.get('tier', '初学')}Lv.{value.get('level', 1)}"
                for name, value in list(spellcards.items())[-8:]
                if isinstance(value, dict)
            )
            if spellcards else "尚未形成个人符卡记录"
        ),
    ])
