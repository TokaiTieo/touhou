"""Relationship consent, pacing context, and mature-content eligibility."""

import re
from datetime import datetime
from typing import Dict, Iterable


CLEARLY_ADULT_NPCS = {
    "八云紫", "西行寺幽幽子", "八意永琳", "蓬莱山辉夜", "八坂神奈子",
    "风见幽香", "圣白莲", "小野冢小町", "四季映姬·亚玛萨那度",
    "茨木华扇", "霍青娥", "纯狐", "赫卡提亚·拉碧斯拉祖利",
}
RELATIONSHIP_WORDS = ("恋爱", "喜欢", "爱", "约会", "暧昧", "亲密", "接吻", "拥抱", "伴侣")
MATURE_CUES = ("成人", "性爱", "做爱", "裸体", "性行为", "上床")
REFUSAL_WORDS = ("不要", "拒绝", "停下", "不愿意", "不接受", "保持朋友", "普通朋友", "离我远点")
CONSENT_WORDS = ("愿意", "同意", "接受", "我也喜欢", "可以继续", "成为恋人")


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


def profile_age(profile: Dict):
    raw = profile.get("age")
    if raw is not None and str(raw).strip():
        match = re.search(r"\d{1,3}", str(raw))
        if match:
            return int(match.group())
    text = f"{profile.get('appearance', '')} {profile.get('background', '')}"
    match = re.search(r"(\d{2})\s*岁", text)
    if match:
        return int(match.group(1))
    if any(word in text for word in ("二十出头", "二十多岁", "成年人", "成年男性", "成年女性")):
        return 20
    return None


def player_is_adult(character: Dict) -> bool:
    profile = character.get("profile", {}) or {}
    if profile.get("adult_verified") is False:
        return False
    age = profile_age(profile)
    return bool(profile.get("adult_verified") is True or (age is not None and age >= 18))


def npc_allows_mature_context(npc_name: str, npc_profile: Dict = None) -> bool:
    profile = npc_profile or {}
    if profile.get("adult_content_allowed") is not None:
        return profile.get("adult_content_allowed") is True
    return npc_name in CLEARLY_ADULT_NPCS


def mature_context_allowed(character: Dict, npc_name: str, npc_profile: Dict = None) -> bool:
    boundary = character.setdefault("relationship_boundaries", {}).get(npc_name, {})
    return (
        player_is_adult(character)
        and npc_allows_mature_context(npc_name, npc_profile)
        and boundary.get("mature") != "closed"
        and _number(boundary.get("cooldown_until_hour"), -1) < _absolute_hour(character)
    )


def observe_relationship_boundaries(character: Dict, npc_name: str, interaction_text: str) -> Dict:
    text = str(interaction_text or "")
    boundaries = character.setdefault("relationship_boundaries", {})
    boundary = boundaries.setdefault(npc_name, {
        "romance": "undecided",
        "mature": "undecided",
        "cooldown_until_hour": 0,
    })
    relationship_context = any(word in text for word in RELATIONSHIP_WORDS + MATURE_CUES)
    if relationship_context and any(word in text for word in REFUSAL_WORDS):
        boundary["romance"] = "closed"
        boundary["mature"] = "closed"
        boundary["cooldown_until_hour"] = _absolute_hour(character) + 24
        boundary["last_signal"] = "refusal"
        boundary["updated_at"] = datetime.now().isoformat()
    elif relationship_context and any(word in text for word in CONSENT_WORDS):
        boundary["romance"] = "open"
        if any(word in text for word in MATURE_CUES) and player_is_adult(character):
            boundary["mature"] = "open"
        boundary["last_signal"] = "consent"
        boundary["updated_at"] = datetime.now().isoformat()
    return boundary


def relationship_update_policy(
    character: Dict,
    npc_name: str,
    old_score: float,
    requested_score: float,
    interaction_text: str,
) -> Dict:
    boundary = character.setdefault("relationship_boundaries", {}).get(npc_name, {})
    text = str(interaction_text or "")
    if character.get("gm_mode"):
        return {"score": requested_score, "clamped": False, "reason": "producer_override"}
    if boundary.get("last_signal") == "refusal" and _number(boundary.get("cooldown_until_hour"), 0) >= _absolute_hour(character):
        return {
            "score": max(-100, min(requested_score, old_score - 15)),
            "clamped": True,
            "reason": "explicit_refusal",
        }
    if requested_score <= old_score:
        return {
            "score": max(-100, max(requested_score, old_score - 30)),
            "clamped": requested_score < old_score - 30,
            "reason": "negative_change",
        }
    explicit = any(word in text for word in CONSENT_WORDS + ("承诺", "告白"))
    maximum_gain = 18 if explicit else 12
    if requested_score >= 70 and not any(word in text for word in RELATIONSHIP_WORDS):
        maximum_gain = 8
    score = min(requested_score, old_score + maximum_gain)
    return {
        "score": score,
        "clamped": score != requested_score,
        "reason": "paced_progression" if score != requested_score else "accepted",
    }


def format_relationship_policy_context(
    character: Dict,
    npc_names: Iterable[str],
    profiles: Dict[str, Dict] = None,
) -> str:
    profiles = profiles or {}
    names = [name for name in npc_names if name]
    adult = player_is_adult(character)
    lines = [
        "关系推进必须尊重本回合明确表达和既有阶段，不得从初识直接跳到恋人。",
        "拒绝、停下或只做朋友必须立即生效；没有明确同意时只能描写暧昧或普通亲近。",
        f"玩家角色成年校验：{'已通过' if adult else '未通过；仅允许普通交往与恋爱叙事，不得生成成熟关系内容'}。",
    ]
    for name in names:
        boundary = character.setdefault("relationship_boundaries", {}).get(name, {})
        mature = mature_context_allowed(character, name, profiles.get(name, {}))
        lines.append(
            f"- {name}：恋爱边界={boundary.get('romance', 'undecided')}；"
            f"成熟关系上下文={'允许' if mature else '禁用'}；"
            f"最近信号={boundary.get('last_signal', '无')}"
        )
    return "\n".join(lines)
