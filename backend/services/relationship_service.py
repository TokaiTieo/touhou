"""Incremental NPC relationships with V6 numeric stages and legacy strings."""

from datetime import datetime
from typing import Dict
from backend.services.relationship_policy_service import relationship_update_policy


ATTITUDE_SCORES = (
    (("不共戴天", "死敌"), -100, "死敌"),
    (("仇恨", "敌对"), -75, "敌对"),
    (("蔑视", "轻视", "警惕"), -30, "疏离"),
    (("热恋", "深爱", "伴侣"), 90, "恋人"),
    (("亲密", "两肋插刀"), 70, "亲密"),
    (("崇拜", "信任"), 55, "信赖"),
    (("友好", "熟悉"), 30, "友好"),
    (("中立",), 0, "相识"),
)


def parse_relationship_changes(content: str) -> Dict[str, str]:
    result = {}
    if not content or content.strip() in ("", "null", "None"):
        return result
    for part in [value.strip() for value in content.split(",")]:
        if ":" not in part:
            continue
        name, attitude = part.split(":", 1)
        if name.strip() and attitude.strip():
            result[name.strip()] = attitude.strip()
    return result


def build_relationship_string(rel_map: Dict[str, str]) -> str:
    return ",".join(f"{name}:{attitude}" for name, attitude in (rel_map or {}).items())


def _progress_for_attitude(attitude: str):
    for words, score, stage in ATTITUDE_SCORES:
        if any(word in str(attitude or "") for word in words):
            return score, stage
    return 10, "相识"


def _stage_for_score(score: float) -> str:
    if score <= -75:
        return "死敌"
    if score <= -40:
        return "敌对"
    if score < 0:
        return "疏离"
    if score < 25:
        return "相识"
    if score < 50:
        return "友好"
    if score < 70:
        return "信赖"
    if score < 88:
        return "亲密"
    return "恋人"


def ensure_relationship_progress(character: Dict) -> Dict:
    progress = character.setdefault("relationship_progress", {})
    for name, attitude in (character.get("relationships_map", {}) or {}).items():
        if name not in progress:
            score, stage = _progress_for_attitude(attitude)
            progress[name] = {
                "score": score, "stage": stage, "attitude": attitude,
                "reason": "从旧关系记录自动索引", "updated_at": None,
            }
    return progress


def get_current_relationships(character: Dict) -> str:
    rel_map = character.get("relationships_map")
    if rel_map is None:
        history = character.get("relationships_history", [])
        if history:
            latest = sorted(history, key=lambda item: item.get("hour", 0), reverse=True)[0]
            rel_map = parse_relationship_changes(latest.get("content", ""))
        else:
            rel_map = {}
        character["relationships_map"] = rel_map
    ensure_relationship_progress(character)
    return build_relationship_string(rel_map)


def update_relationships(
    character: Dict,
    new_content: str,
    current_hour: int,
    max_history: int = 20,
    interaction_text: str = "",
    turn_id: str = None,
):
    if not new_content or new_content.strip() in ("", "null", "None"):
        return {}
    applied_turns = character.setdefault("relationship_turn_receipts", [])
    if turn_id and turn_id in applied_turns:
        return {}
    get_current_relationships(character)
    rel_map = character["relationships_map"]
    progress = ensure_relationship_progress(character)
    accepted = {}
    for name, attitude in parse_relationship_changes(new_content).items():
        old_attitude = rel_map.get(name, "")
        if "(" in old_attitude and "(" not in attitude:
            print(f"⛔ 关系更新被拒绝（旧有原因未提供新依据）：{name}: {old_attitude} → {attitude}")
            continue
        requested_score, requested_stage = _progress_for_attitude(attitude)
        old_progress = progress.get(name, {})
        old_score = old_progress.get("score", 0)
        policy = relationship_update_policy(
            character, name, old_score, requested_score, interaction_text
        )
        score = policy["score"]
        stage = _stage_for_score(score)
        reason = attitude.split("(", 1)[1].rstrip(")") if "(" in attitude else "本回合关系变化"
        effective_attitude = attitude
        if policy["clamped"]:
            effective_attitude = f"{stage}({reason}；关系按既有经历逐步发展)"
        rel_map[name] = effective_attitude
        progress[name] = {
            "score": score, "stage": stage, "attitude": effective_attitude,
            "reason": reason, "updated_at": datetime.now().isoformat(),
            "requested_stage": requested_stage,
            "pacing_reason": policy["reason"],
        }
        accepted[name] = {
            "attitude": effective_attitude,
            "score": score,
            "stage": stage,
            "requested_stage": requested_stage,
            "clamped": policy["clamped"],
            "pacing_reason": policy["reason"],
        }

    full_content = build_relationship_string(rel_map)
    history = character.get("relationships_history", [])
    history.append({"hour": current_hour, "content": full_content, "timestamp": datetime.now().isoformat()})
    history.sort(key=lambda item: item.get("hour", 0), reverse=True)
    character["relationships_history"] = history[:max_history]
    if turn_id:
        character["relationship_turn_receipts"] = (applied_turns + [turn_id])[-80:]
    return accepted


def rollback_relationships_to_hour(character: Dict, target_hour: int):
    history = character.get("relationships_history", [])
    if not history:
        character["relationships_map"] = {}
        character["relationship_progress"] = {}
        return
    sorted_history = sorted(history, key=lambda item: item.get("hour", 0), reverse=True)
    target = next((item for item in sorted_history if item.get("hour", 0) <= target_hour), None)
    if target:
        character["relationships_history"] = [
            item for item in sorted_history if item.get("hour", 0) <= target_hour
        ]
        character["relationships_map"] = parse_relationship_changes(target.get("content", ""))
    else:
        character["relationships_history"] = []
        character["relationships_map"] = {}
    character["relationship_progress"] = {}
    ensure_relationship_progress(character)
    print(f"🔄 关系已回滚到游戏时间 {target_hour}，保留 {len(character.get('relationships_history', []))} 条记录，字典含 {len(character.get('relationships_map', {}))} 个NPC")
