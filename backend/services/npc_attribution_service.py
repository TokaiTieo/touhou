"""Identity and evidence boundaries; presence alone never proves participation."""

import json
import re

from backend.services.npc_identity_service import canonical_npc_name, npc_registry, resolve_npc


ATTRIBUTION_RULES = """## 人物归属与知识边界
姓名与 NPC ID 必须一致；记忆持有人不等于记忆中事实的主语。
历史中的场景、参与者、说话者及可见范围仅对该条记录有效；归属未知时不得把旧的“她/他”绑定到当前人物。
在场不等于听见、参与或知情。私下承诺、礼物、秘密不得复制给旁观者。
逐人绑定的当前记录优先于旧旁白；历史摘录、旧摘要和待核实叙述不是新增事实的证据。
memory_updates 是待核实提议，不能凭生成旁白或模型自报的置信度证明事实归属。
本规则不限制玩家探索、交往或行动，只限制无依据的事实写入。
"""


def npc_identity(name=None, npc_id=None):
    record = resolve_npc(npc_id or name)
    if record:
        return {"npc_id": record["id"], "npc_name": record["name"]}
    return {"npc_id": npc_id or None, "npc_name": canonical_npc_name(name) or "未知"}


def npc_label(name=None, npc_id=None):
    identity = npc_identity(name, npc_id)
    return f"{identity['npc_name']} [NPC ID: {identity['npc_id'] or '未登记'}]"


def validate_scene_npcs(npcs):
    result = []
    for npc in npcs:
        by_id, by_name = resolve_npc(npc.get("id")), resolve_npc(npc.get("name"))
        if by_id and npc.get("name") and by_id["name"] != canonical_npc_name(npc["name"]):
            raise ValueError("场景 NPC 名称与 ID 不一致，请刷新人物列表")
        if by_name and npc.get("id") and by_name["id"] != (by_id or {}).get("id"):
            raise ValueError("场景 NPC 名称与 ID 不一致，请刷新人物列表")
        result.append(by_id or by_name or npc)
    return result


def interaction_targets(action_text, npc_name=None, scene_npcs=()):
    """Use the selected dialogue target or an explicit affirmative action address.

    This is deliberately not a pronoun resolver. Ambiguous/group/quoted mentions
    remain narrative context instead of receiving irreversible personal updates.
    """
    if npc_name:
        return [canonical_npc_name(npc_name)]
    action = str(action_text or "").split("【语言】", 1)[0]
    if action.startswith("语言:") or action.startswith("语言："):
        return []
    action = action.replace("【动作】", "").removeprefix("动作:").removeprefix("动作：").strip()
    candidates = {canonical_npc_name(item.get("name")) for item in scene_npcs or () if isinstance(item, dict) and item.get("name")}
    aliases = npc_registry()[2]
    targets = []
    for name in sorted(candidates):
        forms = [name, *(alias for alias, target in aliases.items() if target == name and not alias.startswith("npc_"))]
        pattern = r"^(?:我)?(?:只|悄悄|单独)?(?:向|对|给|与|和|帮助|协助|赠送|拥抱|询问)\s*(?:" + "|".join(re.escape(form) for form in forms) + r")(?=\W|$|[\u4e00-\u9fff])"
        if re.search(pattern, action):
            targets.append(name)
    return targets


def format_current_npc_snapshot(character, name, npc_id=None):
    identity = npc_identity(name, npc_id)
    name = identity["npc_name"]
    runtime = character.get("npc_runtime", {}).get(name, {}) or {}
    agency = character.get("npc_agency", {}).get("npcs", {}).get(name, {}) or {}
    snapshot = {**identity, "记录范围": "仅此人物；不向其他人物转移"}
    for field in ("location", "simulated_location", "temporary_location", "state", "note", "outfit"):
        if field in runtime:
            snapshot[field] = runtime[field]
    for field in ("current_goal", "plan_progress", "last_location"):
        if field in agency:
            snapshot[field] = agency[field]
    snapshot["关系"] = character.get("relationships_map", {}).get(name, "未记录")
    corrections = character.get("npc_memory_corrections", {}).get(name, [])
    if corrections:
        snapshot["已撤回的旧记录（禁止作为事实引用）"] = [text for item in corrections[-5:] for text in item.get("summaries", [])]
    snapshot["说明"] = "持久记录；旧叙述未经语义核实，不把旧旁白当作当前状态变更"
    return json.dumps(snapshot, ensure_ascii=False)


def prepare_model_memories(updates, action_text, npc_name=None, scene_npcs=()):
    """Quarantine generated claims without losing their original text for review."""
    targets = set(interaction_targets(action_text, npc_name, scene_npcs))
    prepared = []
    for item in updates or []:
        if not isinstance(item, dict):
            continue
        name = canonical_npc_name(item.get("npc_name") or item.get("name"))
        registered = resolve_npc(item.get("npc_id")) if item.get("npc_id") else None
        reason = "模型叙述尚未核实事实主语及知情依据"
        if item.get("npc_id") and (not registered or registered["name"] != name):
            reason = "姓名与 NPC ID 不一致"
        elif name not in targets:
            reason = "没有明确的本回合互动对象依据"
        prepared.append({**item, "npc_name": name, "npc_id": npc_identity(name)["npc_id"],
                         "source": "model_proposal", "knowledge_type": "inferred",
                         "truth_status": "disputed", "confidence": min(float(item.get("confidence", 0.45)), 0.45),
                         "attribution_status": "pending", "attribution_reason": reason,
                         "proposed_npc_id": item.get("npc_id")})
    return prepared
