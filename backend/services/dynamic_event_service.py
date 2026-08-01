"""Data-driven optional events. Events add hooks and never gate locations."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def load_event_definitions(path: Path) -> Dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def _tokens(value) -> List[str]:
    return [str(item) for item in (value or []) if str(item)]


def _absolute_hour(character: Dict) -> float:
    time_info = character.get("time", {}) or {}
    return (max(1, int(time_info.get("current_day", 1) or 1)) - 1) * 24 + float(time_info.get("current_hour", 0) or 0)


def _chain_ready(event: Dict, seen: Dict) -> bool:
    stage = int(event.get("stage", 1) or 1)
    if stage <= 1:
        return True
    chain = str(event.get("chain") or "")
    return any(
        isinstance(value, dict) and value.get("chain") == chain and int(value.get("stage", 0) or 0) == stage - 1
        for value in seen.values()
    )


def select_dynamic_event(
    character: Dict,
    events_path: Path,
    scene: str,
    action_text: str,
    scene_npcs: List[Dict] = None,
    npc_name: str = "",
) -> Optional[Dict]:
    data = load_event_definitions(events_path)
    flags = character.setdefault("event_flags", {})
    runtime = flags.setdefault("dynamic_events", {"seen": {}, "last_trigger_hour": -999})
    seen = runtime.setdefault("seen", {})
    now_hour = _absolute_hour(character)
    names = {str(npc.get("name") or "") for npc in (scene_npcs or []) if isinstance(npc, dict)}
    if npc_name:
        names.add(npc_name)
    text = f"{scene} {action_text} {npc_name}"
    candidates = []

    for event in data.get("personal_events", []) or []:
        if not isinstance(event, dict) or event.get("id") in seen or not _chain_ready(event, seen):
            continue
        event_npc = str(event.get("npc") or "")
        if event_npc not in names and event_npc not in text:
            continue
        scene_hits = [item for item in _tokens(event.get("scenes")) if item == scene]
        keyword_hits = [item for item in _tokens(event.get("keywords")) if item in text]
        score = 35 + len(scene_hits) * 18 + len(keyword_hits) * 8 + (20 if event_npc == npc_name else 0)
        candidates.append((score, "personal", event))

    for event in data.get("ambient_events", []) or []:
        if not isinstance(event, dict):
            continue
        previous = seen.get(event.get("id"), {})
        if previous and now_hour - float(previous.get("hour", -999)) < 48:
            continue
        scene_hits = [item for item in _tokens(event.get("scenes")) if item == scene]
        if not scene_hits:
            continue
        keyword_hits = [item for item in _tokens(event.get("keywords")) if item in text]
        score = 20 + len(keyword_hits) * 10
        candidates.append((score, "ambient", event))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], str(item[2].get("id", ""))))
    top_score = candidates[0][0]
    explicit = top_score >= 50
    if not explicit and now_hour - float(runtime.get("last_trigger_hour", -999)) < 3:
        return None
    seed = f"{character.get('character_id')}|{int(now_hour * 4)}|{scene}|{action_text}"
    roll = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    if not explicit and roll >= 40:
        return None

    _, kind, selected = candidates[0]
    event = {
        "id": selected.get("id"),
        "title": selected.get("title", "自由探索事件"),
        "type": "人物事件" if kind == "personal" else "地点偶遇",
        "scene": scene,
        "npc_name": selected.get("npc"),
        "description": selected.get("description", ""),
        "hooks": selected.get("hooks", []),
        "source": "dynamic_event_v1",
        "created_at": datetime.now().isoformat(),
    }
    seen[event["id"]] = {
        "hour": now_hour, "chain": selected.get("chain"), "stage": selected.get("stage", 0),
    }
    runtime["last_trigger_hour"] = now_hour
    return event


def select_npc_initiative(character: Dict, events_path: Path, scene: str, scene_npcs: List[Dict] = None) -> Optional[Dict]:
    """Create an occasional letter, invitation or clue from an off-screen NPC."""
    data = load_event_definitions(events_path)
    flags = character.setdefault("event_flags", {})
    runtime = flags.setdefault("npc_initiative", {"last_trigger_hour": -999, "seen": {}})
    now_hour = _absolute_hour(character)
    if now_hour - float(runtime.get("last_trigger_hour", -999)) < 8:
        return None
    present = {npc.get("name") for npc in (scene_npcs or []) if isinstance(npc, dict)}
    candidates = []
    related = set((character.get("incident_state", {}) or {}).get("related_npcs", []) or [])
    progress = character.get("relationship_progress", {}) or {}
    for event in data.get("personal_events", []) or []:
        if not isinstance(event, dict) or event.get("id") in runtime.get("seen", {}):
            continue
        npc = event.get("npc")
        relationship = progress.get(npc, {}) if isinstance(progress.get(npc), dict) else {}
        score = float(relationship.get("score", 0) or 0)
        if npc in present or (score < 30 and npc not in related):
            continue
        weight = score + (30 if npc in related else 0) - int(event.get("stage", 1) or 1) * 2
        candidates.append((weight, event))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    seed = f"initiative|{character.get('character_id')}|{int(now_hour // 8)}|{scene}"
    if int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100 >= 45:
        return None
    event = candidates[0][1]
    npc = event.get("npc")
    result = {
        "id": f"initiative_{event.get('id')}", "title": f"{npc}的主动邀约",
        "type": "来信与邀约", "scene": scene, "npc_name": npc,
        "description": f"{npc}主动送来消息，提到「{event.get('title')}」：{event.get('description', '')}",
        "hooks": event.get("hooks", []), "source": "npc_initiative_v1",
        "created_at": datetime.now().isoformat(),
    }
    runtime.setdefault("seen", {})[event.get("id")] = now_hour
    runtime["last_trigger_hour"] = now_hour
    return result
