"""Explicit item effects; unknown custom items remain usable through narration."""

ITEMS = {
    "tea": {"names": ["茶", "红茶", "绿茶", "神社茶叶"], "use": {"疲劳": -12}, "tags": ["茶"]},
    "food": {"names": ["饭团", "便当", "点心"], "use": {"疲劳": -12}, "tags": ["食物"]},
    "medicine": {"names": ["恢复药", "急救药", "绷带", "伤药", "小恢复药"], "use": {"受伤": -20}, "tags": ["药品"]},
    "spirit": {"names": ["灵力药", "御神酒", "魔力药"], "use": {"灵力": 15}, "tags": ["灵力"]},
    "ofuda": {"names": ["御札", "灵符", "符纸", "护身符札"], "equip": {"battle_score": 8}, "tags": ["御札"]},
    "charm": {"names": ["御守", "护身符", "结界护符"], "equip": {"injury_reduction": 3}, "tags": ["御守"]},
    "boots": {"names": ["旅行鞋", "轻便木屐"], "equip": {"travel_reduction": 2}, "tags": ["旅行"]},
    "book": {"names": ["魔导书", "调查手册", "魔法书"], "equip": {"investigation_experience": 2}, "tags": ["书籍"]},
    "hakkero": {"names": ["八卦炉", "迷你八卦炉"], "equip": {"battle_score": 12, "spirit_reduction": 2}, "tags": ["魔法"]},
}
EFFECT_LABELS = {"battle_score": "符卡裁定", "injury_reduction": "战斗伤势减免",
                 "travel_reduction": "旅行疲劳减免", "investigation_experience": "调查经验",
                 "spirit_reduction": "符卡灵力消耗减免"}
PREFERENCES = {
    "博丽灵梦": ["御札", "御守"], "雾雨魔理沙": ["书籍", "魔法"],
    "帕秋莉": ["书籍", "茶"], "帕秋莉·诺蕾姬": ["书籍", "茶"],
    "十六夜咲夜": ["茶"], "西行寺幽幽子": ["食物"], "八意永琳": ["药品"],
    "爱丽丝": ["魔法"], "爱丽丝·玛格特罗依德": ["魔法"], "东风谷早苗": ["御守"],
}


def definition(item):
    name = item.get("name", "") if isinstance(item, dict) else str(item)
    return next(({"id": key, **value} for key, value in ITEMS.items() if name in value["names"]), {})


def equipment_effects(character):
    inventory = character.get("inventory_state", {}) or {}
    equipped = set(inventory.get("equipped", []) or [])
    effects, sources = {}, []
    for item in inventory.get("items", []):
        if not isinstance(item, dict) or item.get("name") not in equipped or float(item.get("quantity", 1) or 0) <= 0:
            continue
        for key, value in definition(item).get("equip", {}).items():
            effects[key] = min(40, effects.get(key, 0) + value)
            sources.append(f"{item['name']}：{EFFECT_LABELS[key]} +{value}")
    return {"effects": effects, "sources": sources}


def gift_response(character, npc_name, item):
    day = int(character.get("time", {}).get("current_day", 1) or 1)
    log = character.setdefault("gift_history", [])
    repeats = sum(1 for entry in log if entry.get("npc_name") == npc_name and entry.get("day") == day)
    preferred = bool(set(definition(item).get("tags", [])) & set(PREFERENCES.get(npc_name, [])))
    shared = bool(character.get("npc_agency", {}).get("npcs", {}).get(npc_name, {}).get("last_player_interaction"))
    amount = max(0, round((4 + 2 * preferred + int(shared)) / (1 + repeats))) if repeats < 5 else 0
    reason = "投其所好" if preferred else "赠礼心意"
    if shared:
        reason += "、已有共同经历"
    if repeats:
        reason += "、今日已多次赠礼"
    log.append({"npc_name": npc_name, "day": day, "item": item["name"], "delta": amount, "reason": reason})
    character["gift_history"] = log[-200:]
    return amount, reason
