"""Deterministic turn resolution for player state and spell-card battles."""

import hashlib
import re
from typing import Any, Dict, List, Optional


BATTLE_WORDS = ("战斗", "符卡", "弹幕", "决斗", "挑战", "退治", "攻击", "开战")
REST_WORDS = ("休息", "睡觉", "睡眠", "喝茶", "用餐", "治疗", "疗伤", "沐浴")
TRAVEL_WORDS = ("赶路", "奔跑", "搜索", "调查", "潜入", "飞行", "探索")
PREPARE_WORDS = ("观察", "准备", "分析", "防御", "闪避", "练习", "布置")
INVESTIGATION_WORDS = ("调查", "搜索", "观察", "分析", "追踪", "线索", "询问")
SOCIAL_WORDS = ("交涉", "说服", "安慰", "邀请", "聊天", "道歉", "谈判", "请教")
SURVIVAL_WORDS = ("赶路", "探索", "潜入", "闪避", "防御", "治疗", "露营", "飞行")


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _energy(fatigue: float) -> str:
    if fatigue >= 90:
        return "灵力枯竭"
    if fatigue >= 70:
        return "疲惫不堪"
    if fatigue >= 45:
        return "感到疲倦"
    if fatigue >= 20:
        return "略有疲惫"
    return "精力充沛"


def _skill_tier(value: float) -> str:
    if value >= 80:
        return "大师"
    if value >= 50:
        return "精通"
    if value >= 25:
        return "熟练"
    if value >= 10:
        return "入门"
    return "初学"


def is_battle_action(action_text: str, result: Optional[Dict] = None) -> bool:
    return any(word in str(action_text or "") for word in BATTLE_WORDS) or isinstance((result or {}).get("spellcard_result"), dict)


def _find_opponent(action_text: str, scene_npcs: List[Dict], explicit_name: str = None) -> Dict:
    if explicit_name:
        for npc in scene_npcs or []:
            if npc.get("name") == explicit_name:
                return npc
        return {"name": explicit_name, "profile": {}}
    text = str(action_text or "")
    for npc in scene_npcs or []:
        if npc.get("name") and npc.get("name") in text:
            return npc
    return (scene_npcs or [{}])[0]


def _difficulty(npc: Dict) -> float:
    profile = npc.get("profile", {}) if isinstance(npc, dict) else {}
    tier = str(profile.get("encounter_tier") or profile.get("power_level") or "")
    mapping = {
        "日常": 24, "普通": 32, "自由探索": 36, "注意": 44,
        "危险": 58, "高危": 72, "极危": 86, "贤者": 92, "顶级": 94
    }
    for label, score in mapping.items():
        if label in tier:
            return score
    identity = str(profile.get("identity") or "")
    if any(word in identity for word in ("贤者", "神明", "最强", "吸血鬼", "鬼王")):
        return 88
    return 48


def _stable_variance(character: Dict, action_text: str) -> int:
    seed = f"{character.get('character_id', '')}|{action_text}|{len(character.get('spellcard_history', []))}"
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return (value % 17) - 8


def _spellcard_name(action_text: str, result: Optional[Dict] = None) -> str:
    existing = (result or {}).get("spellcard_result")
    if isinstance(existing, dict) and str(existing.get("spellcard_name") or "").strip():
        return str(existing["spellcard_name"]).strip()[:160]
    match = re.search(r"(?:符卡|符名|Spell\s*Card)\s*[：:]?\s*[「『【\"']([^」』】\"']+)", str(action_text or ""), re.I)
    return match.group(1).strip()[:160] if match else "无名幻想符"


def _mastery_tier(level: int) -> str:
    if level >= 12:
        return "幻想级"
    if level >= 8:
        return "宗师"
    if level >= 5:
        return "精通"
    if level >= 2:
        return "熟练"
    return "初学"


def _mastery_traits(level: int) -> List[str]:
    traits = []
    if level >= 2:
        traits.append("稳定展开")
    if level >= 5:
        traits.append("灵力节制")
    if level >= 8:
        traits.append("强敌适应")
    if level >= 12:
        traits.append("幻想收束")
    return traits


def _battle_metrics(character: Dict, ruling: Dict, spell_name: str) -> Dict:
    state = character.get("player_state", {}) or {}
    margin = _number(ruling.get("score_margin"), 80 if character.get("gm_mode") else 0)
    skill = _number(state.get("弹幕熟练度"), 10)
    fatigue = _number(state.get("疲劳"), 0)
    seed = f"{character.get('character_id')}|{spell_name}|{ruling.get('opponent')}|{len(character.get('spellcard_history', []))}"
    variance = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6], 16) % 9 - 4
    if character.get("gm_mode"):
        accuracy, grazes, misses = 100.0, 99, 0
    else:
        accuracy = round(_clamp(54 + margin * 0.65 + skill * 0.12 - fatigue * 0.08 + variance, 5, 99), 1)
        grazes = max(0, round(6 + skill * 0.18 - fatigue * 0.08 + max(0, -margin) * 0.12))
        misses = max(0, round(100 - accuracy))
    return {
        "accuracy": accuracy,
        "graze_count": grazes,
        "miss_rate": misses,
        "capture_rate": 100.0 if character.get("gm_mode") else round(_clamp(accuracy + margin * 0.25, 0, 100), 1),
    }


def _update_spellcard_mastery(character: Dict, result: Dict, ruling: Dict, spell_name: str) -> Dict:
    mastery = character.setdefault("spellcard_mastery", {})
    entry = mastery.setdefault(spell_name, {
        "level": 1,
        "experience": 0,
        "uses": 0,
        "wins": 0,
        "current_streak": 0,
        "best_streak": 0,
        "traits": [],
    })
    old_level = int(_number(entry.get("level"), 1))
    outcome = str(ruling.get("outcome") or "")
    won = "胜利" in outcome or outcome == "轻松胜利"
    if character.get("gm_mode"):
        entry.update({
            "level": 999999,
            "experience": 999999,
            "uses": int(_number(entry.get("uses"), 0)) + 1,
            "wins": int(_number(entry.get("wins"), 0)) + 1,
            "current_streak": 999999,
            "best_streak": 999999,
            "traits": ["稳定展开", "灵力节制", "强敌适应", "幻想收束", "绝对压制"],
        })
        experience_gained = 999999
    else:
        experience_gained = {"low": 18, "medium": 26, "high": 34}.get(ruling.get("cost_level"), 22)
        if won:
            experience_gained += 8
        entry["experience"] = round(_number(entry.get("experience"), 0) + experience_gained, 2)
        entry["uses"] = int(_number(entry.get("uses"), 0)) + 1
        entry["wins"] = int(_number(entry.get("wins"), 0)) + (1 if won else 0)
        entry["current_streak"] = int(_number(entry.get("current_streak"), 0)) + 1 if won else 0
        entry["best_streak"] = max(int(_number(entry.get("best_streak"), 0)), entry["current_streak"])
        level = max(1, int((entry["experience"] / 60) ** 0.5) + 1)
        entry["level"] = level
        entry["traits"] = _mastery_traits(level)
    entry["tier"] = "制作人" if character.get("gm_mode") else _mastery_tier(entry["level"])
    entry["last_used_at"] = datetime_now()

    opponent = str(ruling.get("opponent") or "当前对手")
    adaptation = character.setdefault("opponent_adaptation", {}).setdefault(opponent, {
        "battles": 0, "player_wins": 0, "last_outcome": "",
    })
    adaptation["battles"] = int(_number(adaptation.get("battles"), 0)) + 1
    adaptation["player_wins"] = int(_number(adaptation.get("player_wins"), 0)) + (1 if won else 0)
    adaptation["last_outcome"] = outcome
    adaptation["adaptation_bonus"] = min(12, adaptation["battles"] * 1.5)
    adaptation["updated_at"] = entry["last_used_at"]

    progress = {
        "spellcard_name": spell_name,
        "experience_gained": experience_gained,
        "level_before": old_level,
        "level": entry["level"],
        "tier": entry["tier"],
        "new_traits": [trait for trait in entry["traits"] if trait not in _mastery_traits(old_level)],
        "uses": entry["uses"],
        "wins": entry["wins"],
        "best_streak": entry["best_streak"],
    }
    result["spellcard_mastery_delta"] = progress
    return progress


def datetime_now() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


def preview_turn_ruling(character: Dict, action_text: str, scene_npcs=None, npc_name: str = None) -> Dict[str, Any]:
    """Return a deterministic ruling that can be injected before narrative generation."""
    if not is_battle_action(action_text):
        return {"is_battle": False}
    opponent = _find_opponent(action_text, scene_npcs or [], npc_name)
    opponent_name = opponent.get("name") or npc_name or "当前对手"
    spell_name = _spellcard_name(action_text)
    if character.get("gm_mode"):
        return {
            "is_battle": True,
            "opponent": opponent_name,
            "outcome": "轻松胜利",
            "cost_level": "none",
            "spellcard_name": spell_name,
            "score_margin": 999999,
            "instruction": f"后端确定性裁定：玩家以绝对优势轻松战胜{opponent_name}，不得改写为失败、苦战或受伤。"
        }

    state = character.get("player_state", {}) or {}
    spirit = min(_number(state.get("灵力"), 50), 140)
    skill = min(_number(state.get("弹幕熟练度"), 10), 140)
    fatigue = _clamp(_number(state.get("疲劳"), 0))
    injury = _clamp(_number(state.get("受伤"), 0))
    investigation_skill = min(_number(state.get("调查熟练度"), 0), 100)
    mastery = character.get("spellcard_mastery", {}).get(spell_name, {}) or {}
    mastery_level = min(20, _number(mastery.get("level"), 1))
    adaptation = character.get("opponent_adaptation", {}).get(opponent_name, {}) or {}
    adaptation_bonus = min(12, _number(adaptation.get("adaptation_bonus"), 0))
    preparation = (10 + investigation_skill * 0.08) if any(word in str(action_text) for word in PREPARE_WORDS) else 0
    player_score = spirit * 0.34 + skill * 0.66 + preparation - fatigue * 0.32 - injury * 0.42
    margin = player_score + mastery_level * 1.8 - _difficulty(opponent) - adaptation_bonus + _stable_variance(character, action_text)
    if margin >= 28:
        outcome, cost = "压制胜利", "low"
    elif margin >= 8:
        outcome, cost = "胜利", "medium"
    elif margin >= -8:
        outcome, cost = "平局", "medium"
    elif margin >= -28:
        outcome, cost = "惜败", "high"
    else:
        outcome, cost = "失败", "high"
    return {
        "is_battle": True,
        "opponent": opponent_name,
        "outcome": outcome,
        "cost_level": cost,
        "spellcard_name": spell_name,
        "score_margin": round(margin, 1),
        "instruction": f"后端确定性裁定：对{opponent_name}的符卡战结果为「{outcome}」。叙事必须遵守该结果，可以丰富过程但不得反转胜负。"
    }


def format_ruling_for_prompt(ruling: Dict[str, Any]) -> str:
    if not ruling.get("is_battle"):
        return "本回合没有预先锁定的符卡胜负，由叙事正常回应。"
    return str(ruling.get("instruction") or "")


def resolve_turn_rules(
    character: Dict,
    result: Dict,
    action_text: str,
    scene_npcs=None,
    npc_name: str = None,
    preview: Dict = None
) -> Dict[str, Any]:
    """Apply deterministic state costs and overwrite AI battle outcomes."""
    state = character.setdefault("player_state", {})
    defaults = {"灵力": 50, "结界共鸣": 35, "弹幕熟练度": 10, "调查熟练度": 0, "交涉熟练度": 0, "生存熟练度": 0, "疲劳": 0, "受伤": 0, "异变污染": 5}
    for key, value in defaults.items():
        state.setdefault(key, value)
    delta = {}
    skill_experience = character.setdefault("skill_experience", {})
    skill_progress_delta = {}

    def add(key, amount, ceiling=100):
        old = _number(state.get(key), defaults.get(key, 0))
        new = _clamp(old + amount, 0, ceiling)
        if new != old:
            state[key] = int(new) if float(new).is_integer() else round(new, 2)
            delta[key] = round(new - old, 2)

    def award_skill(key, experience):
        if character.get("gm_mode"):
            return
        level = max(0, _number(state.get(key), 0))
        old_experience = max(0, _number(skill_experience.get(key), 0))
        current_experience = old_experience + max(0, experience)
        gained = 0
        while level < 999999:
            threshold = 8 + min(level, 100) * 2
            if current_experience < threshold:
                break
            current_experience -= threshold
            level += 1
            gained += 1
        skill_experience[key] = round(current_experience, 2)
        if gained:
            add(key, gained, 999999)
        skill_progress_delta[key] = {
            "experience_gained": round(max(0, experience), 2),
            "experience": round(current_experience, 2),
            "next_level": round(8 + min(level, 100) * 2, 2),
            "tier": _skill_tier(level)
        }

    text = str(action_text or "")
    time_cost = _clamp(_number(result.get("time_cost"), 0), 0, 12)
    base_experience = 6 + min(6, time_cost * 2)
    if any(word in text for word in INVESTIGATION_WORDS):
        award_skill("调查熟练度", base_experience)
    if any(word in text for word in SOCIAL_WORDS):
        award_skill("交涉熟练度", base_experience)
    if any(word in text for word in SURVIVAL_WORDS):
        award_skill("生存熟练度", base_experience)
    survival_reduction = min(0.5, _number(state.get("生存熟练度"), 0) / 200)
    if any(word in text for word in REST_WORDS):
        time_cost = max(time_cost, 0.5)
        add("疲劳", -18)
        add("受伤", -8)
        add("灵力", 8, 999999)
    else:
        add("疲劳", max(1, round(time_cost * 2.5 * (1 - survival_reduction))))
    if any(word in text for word in TRAVEL_WORDS):
        add("疲劳", max(1, round(4 * (1 - survival_reduction))))

    ruling = preview or preview_turn_ruling(character, text, scene_npcs or [], npc_name)
    if ruling.get("is_battle"):
        existing = result.get("spellcard_result") if isinstance(result.get("spellcard_result"), dict) else {}
        spell_name = _spellcard_name(text, result)
        mastery_before = character.get("spellcard_mastery", {}).get(spell_name, {}) or {}
        cost_reduction = 1 if _number(mastery_before.get("level"), 1) >= 5 else 0
        spirit_cost = max(0, {"none": 0, "low": 3, "medium": 7, "high": 12}.get(ruling.get("cost_level"), 6) - cost_reduction)
        fatigue_cost = max(0, {"none": 0, "low": 5, "medium": 9, "high": 14}.get(ruling.get("cost_level"), 8) - cost_reduction * 2)
        injury_cost = 0
        if not character.get("gm_mode") and "胜利" not in str(ruling.get("outcome")) and ruling.get("outcome") != "平局":
            injury_cost = 8
        metrics = _battle_metrics(character, ruling, spell_name)
        result["spellcard_result"] = {
            **existing,
            "opponent": ruling.get("opponent"),
            "spellcard_name": spell_name,
            "outcome": ruling.get("outcome"),
            "summary": existing.get("summary") or ruling.get("instruction", ""),
            "cost": {
                "level": ruling.get("cost_level"),
                "灵力": -spirit_cost,
                "疲劳": fatigue_cost,
                "受伤": injury_cost,
            },
            "metrics": metrics,
            "rule_source": "deterministic_v2"
        }
        if not character.get("gm_mode"):
            add("疲劳", fatigue_cost)
            add("灵力", -spirit_cost, 999999)
            if "胜利" in str(ruling.get("outcome")):
                award_skill("弹幕熟练度", 18)
            elif ruling.get("outcome") == "平局":
                award_skill("弹幕熟练度", 13)
            else:
                award_skill("弹幕熟练度", 9)
                add("受伤", injury_cost)
        mastery_progress = _update_spellcard_mastery(character, result, ruling, spell_name)
        result["spellcard_result"]["mastery"] = mastery_progress

    if result.get("is_dead") is True and not character.get("gm_mode"):
        add("受伤", 100)
    elif character.get("gm_mode"):
        result["is_dead"] = False

    result["time_cost"] = time_cost
    time_info = character.setdefault("time", {})
    time_info["energy_state"] = _energy(_number(state.get("疲劳"), 0))
    result["new_energy_state"] = time_info["energy_state"]
    result["player_state_delta"] = delta
    result["skill_progress_delta"] = skill_progress_delta
    result["rule_resolution"] = {
        "version": "deterministic_v2",
        "battle": ruling if ruling.get("is_battle") else None,
        "state_delta": delta
    }
    return result["rule_resolution"]
