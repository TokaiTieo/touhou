"""Personality-aware proposals; affection never establishes a relationship."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from backend.services.npc_attribution_service import npc_identity
from backend.services.npc_identity_service import canonical_npc_name, resolve_npc


@lru_cache(maxsize=8)
def _load_content(path, modified):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def life_content():
    from backend.config import BASE_DIR, WORLDS_DIR, DEFAULT_WORLD_ID
    path = WORLDS_DIR / DEFAULT_WORLD_ID / "life_content.json"
    if not path.is_file():
        path = BASE_DIR / "worlds" / DEFAULT_WORLD_ID / "life_content.json"
    return _load_content(str(path), path.stat().st_mtime_ns)


def absolute_hour(character):
    time = character.get("time", {})
    return (max(1, int(time.get("current_day", 1) or 1)) - 1) * 24 + float(time.get("current_hour", 8) or 0)


def traits_for(name):
    name = canonical_npc_name(name)
    record = resolve_npc(name) or {}
    profile = record.get("profile", {})
    traits = dict(life_content()["npc_traits"].get(name, {}))
    personality = str(profile.get("personality", ""))
    traits.setdefault("style", "主动" if any(word in personality for word in ("外向", "主动", "直率")) else "含蓄")
    return traits


def relationship_dimensions(character, name):
    name = canonical_npc_name(name)
    state = character.setdefault("relationship_dimensions", {}).setdefault(name, {})
    score = character.get("relationship_progress", {}).get(name, {}).get("score", 0)
    defaults = {**npc_identity(name), "familiarity": max(0, min(100, float(score or 0))),
                "trust": 0, "closeness": 0, "romantic_interest": 0, "mood": 0,
                "status": "unconfirmed", "shared_events": 0, "receipts": [], "last_proposal_hour": -999}
    for key, value in defaults.items():
        state.setdefault(key, value)
    return state


def record_shared_experience(character, name, event_id, kind="shared"):
    state = relationship_dimensions(character, name)
    if event_id in state["receipts"]:
        return
    state["receipts"] = (state["receipts"] + [event_id])[-100:]
    state["shared_events"] += 1
    for key, gain in (("familiarity", 2), ("trust", 3), ("closeness", 2)):
        state[key] = min(100, state[key] + gain)
    state["mood"] = min(20, state["mood"] + 1)


def propose_relationship(character, names):
    hour = absolute_hour(character)
    proposals = character.setdefault("relationship_proposals", [])
    for raw in names:
        name = canonical_npc_name(raw)
        state = relationship_dimensions(character, name)
        boundary = character.get("relationship_boundaries", {}).get(name, {})
        if boundary.get("romance") == "closed" or float(boundary.get("cooldown_until_hour", -1)) >= hour:
            continue
        if any(item.get("npc_name") == name and item.get("status") == "pending" for item in proposals):
            continue
        if hour - state["last_proposal_hour"] < 24 or state["mood"] < -5:
            continue
        style = traits_for(name)["style"]
        score = max(float(character.get("relationship_progress", {}).get(name, {}).get("score", 0)), state["familiarity"])
        threshold = 65 if style == "主动" else 72 if style == "直率" else 80
        if score < threshold:
            continue
        state["romantic_interest"] = max(state["romantic_interest"], min(100, score - 20))
        if state["status"] in ("lover", "partner"):
            kind = "deepen" if state["shared_events"] >= 3 and state["closeness"] >= 8 else "invitation"
        elif state["shared_events"] >= (2 if style == "主动" else 3) and state["trust"] >= 6:
            kind = "confession"
        else:
            kind = "invitation"
        seed = f"{character.get('character_id')}|{name}|{hour}|{kind}"
        invitations = {
            "主动": f"{name}笑着向你发出邀请，想挑个时间和你一起出门。",
            "直率": f"{name}直接问你，今天是否愿意陪自己单独待一会儿。",
            "含蓄": f"{name}提起一个想去的地方，轻声问你是否有空同行。",
        }
        description = invitations.get(style, invitations["含蓄"])
        if kind == "confession":
            description = f"{name}认真地向你表达了超出朋友的心意，希望知道你是否愿意交往。"
        elif kind == "deepen":
            description = f"{name}与你商量今后更长久的相伴，等待你的回应。"
        proposal = {**npc_identity(name), "id": "rel_" + hashlib.sha256(seed.encode()).hexdigest()[:16],
                    "kind": kind, "style": style, "status": "pending", "hour": hour,
                    "title": {"invitation": "想和你单独相处", "confession": "想认真说出的心意", "deepen": "关于今后的约定"}[kind],
                    "description": description}
        proposals.append(proposal)
        character["relationship_proposals"] = proposals[-60:]
        state["last_proposal_hour"] = hour
        return proposal
    return None


def respond_relationship(character, proposal_id, choice):
    if choice not in ("accept", "decline", "friendship"):
        raise ValueError("请选择回应")
    proposal = next((item for item in character.get("relationship_proposals", []) if item.get("id") == proposal_id), None)
    if not proposal or proposal.get("status") != "pending":
        raise ValueError("这份心意已经回应或不在当前时间线")
    name = proposal["npc_name"]
    state = relationship_dimensions(character, name)
    proposal["status"] = {"accept": "accepted", "decline": "declined", "friendship": "friendship"}[choice]
    proposal["responded_hour"] = absolute_hour(character)
    boundary = character.setdefault("relationship_boundaries", {}).setdefault(name, {})
    if choice == "accept":
        record_shared_experience(character, name, proposal_id, "relationship_response")
        if proposal["kind"] in ("confession", "deepen"):
            state["status"] = "partner" if proposal["kind"] == "deepen" else "lover"
            boundary.update(romance="open", last_signal="consent")
            label = "伴侣" if state["status"] == "partner" else "恋人"
            character.setdefault("relationships_map", {})[name] = label
            character.setdefault("relationship_progress", {}).setdefault(name, {}).update(stage=label, attitude=label)
    else:
        boundary.update(cooldown_until_hour=absolute_hour(character) + 24, last_signal="refusal")
        if choice == "friendship":
            boundary["romance"] = "closed"
    # Accepting a date/relationship is never consent to a different intimate act.
    return proposal


def relationship_context(character, names):
    lines = ["高好感不是恋人确认。人物可按性格主动示好、邀约、告白或商量更长久的相伴；等待玩家回应，不替玩家接受。"]
    for name in dict.fromkeys(filter(None, names)):
        state = relationship_dimensions(character, name)
        lines.append(f"{name} [NPC ID: {state['npc_id'] or '未登记'}]：性格表达={traits_for(name)['style']}；"
                     f"熟悉={state['familiarity']}，信任={state['trust']}，亲近={state['closeness']}，"
                     f"恋爱意愿={state['romantic_interest']}，当前心情={state['mood']}；确认状态={state['status']}")
    for proposal in character.get("relationship_proposals", []):
        if proposal.get("status") == "pending" and proposal.get("npc_name") in names:
            lines.append(f"待回应心意：{proposal['npc_name']} {proposal['title']}；尚未接受。")
    return "\n".join(lines)


def respond_from_text(character, text, npc_name):
    """A selected addressee and explicit player response are required."""
    import re
    if not npc_name:
        return None
    name = canonical_npc_name(npc_name)
    pending = [item for item in character.get("relationship_proposals", [])
               if item.get("npc_name") == name and item.get("status") == "pending"]
    if len(pending) != 1:
        return None
    text = str(text or "")
    if any(word in text for word in ("如果", "假如", "是否", "能否", "她说", "他说")):
        return None
    if re.search(r"只做朋友|保持朋友|普通朋友", text):
        choice = "friendship"
    elif re.search(r"暂不接受|不接受|拒绝.*(?:邀约|告白)|还没准备好", text):
        choice = "decline"
    elif re.search(r"我也喜欢你|接受(?:你|这份|这次|这场)?(?:的)?(?:邀约|邀请|告白|心意)|我愿意(?:和你|与你|成为|做你)", text):
        choice = "accept"
    else:
        return None
    return respond_relationship(character, pending[0]["id"], choice)
