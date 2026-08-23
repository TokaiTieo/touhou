"""Formatting helpers used to assemble deterministic turn context."""

from pathlib import Path
from typing import Dict, List, Optional

from backend.location_manager import get_location_manager
from backend.services.relationship_policy_service import mature_context_allowed
from backend.services.world_info_service import build_world_info_context


def format_player_state_for_ai(character: Dict) -> str:
    player_state = character.get("player_state", {}) or {}
    if not player_state:
        return "未记录"

    lines = [f"- {key}: {value}" for key, value in player_state.items()]
    fatigue = float(player_state.get("疲劳", 0) or 0)
    injury = float(player_state.get("受伤", 0) or 0)
    spell = float(player_state.get("符卡熟练度", 0) or 0)
    tips = []
    if fatigue >= 60:
        tips.append("疲劳较高，长距离移动、弹幕回避和精细施法应更容易失误")
    if injury >= 40:
        tips.append("伤势会影响爆发力、持续战斗和危险动作的成功率")
    if spell >= 50:
        tips.append("符卡熟练度较高，允许更稳定地使用弹幕、结界和回避技巧")
    elif spell <= 15:
        tips.append("符卡熟练度偏低，面对强者时更依赖环境、交涉或退让")
    if tips:
        lines.append("叙事裁定参考：" + "；".join(tips))
    return "\n".join(lines)


def get_world_info_context(
    world_path: Path,
    query: str,
    scene: str = "",
    npc_name: str = "",
    limit: int = 6,
) -> Dict:
    return build_world_info_context(
        Path(world_path) / "world_info.json", query, scene, npc_name, limit=limit
    )


def format_history_for_ai(history: List[Dict], max_count: int = 20) -> str:
    if not history:
        return "（无历史记录）"
    return "\n".join(
        f"{item.get('speaker', '未知')}: {item.get('content', '')}"
        for item in history[-max_count:]
    )


def format_locations_for_ai(locations_dir: Path) -> str:
    all_locations = get_location_manager(Path(locations_dir)).get_all_locations()
    regions = []
    scenes = []
    for loc_id, location in all_locations.items():
        if hasattr(location, "name"):
            name = location.name
            location_type = location.type
            parent = location.parent
        else:
            name = location.get("name")
            location_type = location.get("type")
            parent = location.get("parent")
        if location_type == "region":
            regions.append(f"  - {name} ({loc_id})")
        else:
            scenes.append(f"  - {name} ({loc_id})，父级={parent}")
    return "\n".join(
        ["【区域】", *(regions or ["  （暂无区域）"]), "【场景】", *(scenes or ["  （暂无场景）"])]
    )


def format_npcs_for_ai(npcs: List[Dict], character: Optional[Dict] = None) -> str:
    if not npcs:
        return "（没有其他人在场）"

    lines = []
    for npc in npcs:
        profile = npc.get("profile", {})
        lines.append(f"- {npc.get('name')}：{profile.get('identity', '普通人')}")
        field_labels = (
            ("description", "外貌性格"),
            ("personality", "行为风格"),
            ("initial_attitude", "初始态度"),
            ("story_hook", "可触发事件"),
            ("spellcard_style", "符卡倾向"),
            ("encounter_tier", "登场层级"),
        )
        for field, label in field_labels:
            if profile.get(field):
                lines.append(f"  {label}：{profile[field]}")
        if (
            profile.get("romance_adult_hook")
            and character
            and mature_context_allowed(character, npc.get("name", ""), profile)
        ):
            lines.append(f"  恋爱/成人互动倾向：{profile['romance_adult_hook']}")
    return "\n".join(lines)
