"""Long-running incident cycles and aftermath records without exploration gates."""

from datetime import datetime
import hashlib
from typing import Dict, Optional

from backend.services.incident_service import NEXT_INCIDENT_WORDS, load_incident_definitions


def apply_incident_variant(character: Dict, definition: Dict, tasks_data: Dict) -> Dict:
    """Persist consequences of earlier choices as this incident's starting conditions."""
    incident = character["incident_state"]
    cycle = int(character.get("campaign_state", {}).get("cycle", 1) or 1)
    identity = f"{cycle}:{incident['id']}"
    previous = next((item for item in reversed(character.get("incident_history", [])) if isinstance(item, dict)), {})
    if not previous:
        return {}
    if incident.get("variant", {}).get("identity") == identity:
        return incident["variant"]
    candidates = definition.get("related_npcs", []) or []
    progress = character.get("relationship_progress", {}) or {}
    def affinity(name):
        value = progress.get(name, {})
        return float(value.get("score", 0) or 0) if isinstance(value, dict) else 0
    requester = max(candidates, key=affinity) if candidates else "当地居民"
    path = str(previous.get("path") or "freeform")
    peaceful = any(word in path for word in ("diplom", "negoti", "peace", "social"))
    investigative = "invest" in path
    kind = "旧日协约" if peaceful else "旧线索的新证据" if investigative else "异变留下的回响"
    summary = f"{requester}提起你此前以「{previous.get('path_title') or '自己的方式'}」处理「{previous.get('title', '异变')}」的经历。"
    world = character.get("world_state", {}).get("locations", {}) or {}
    pressures = [float(world.get(name, {}).get("pressure", 0) or 0) for name in definition.get("related_locations", [])]
    pressure = max(pressures, default=0)
    bonus = 3 if affinity(requester) >= 30 or peaceful or investigative else 0
    variant = {"identity": identity, "kind": kind, "requester": requester, "previous_key": previous.get("key"),
               "previous_path": path, "summary": summary, "investigation_bonus": bonus,
               "local_pressure": pressure, "gates_exploration": False,
               "seed": hashlib.sha256(f"{identity}:{path}:{requester}:{pressure}".encode()).hexdigest()[:12]}
    incident["variant"] = variant
    incident["investigation_progress"] = min(100, float(incident.get("investigation_progress", 0) or 0) + bonus)
    incident["threat_progress"] = max(float(incident.get("threat_progress", 0) or 0), min(20, max(0, pressure)))
    for task in tasks_data.get("active_tasks", []):
        if task.get("id") == incident.get("completion_task_id"):
            task["description"] = f"{summary} {task.get('description', '')}"
            task["variant"] = dict(variant)
    return variant


def ensure_campaign(character: Dict) -> Dict:
    campaign = character.setdefault("campaign_state", {})
    if not isinstance(campaign, dict):
        campaign = {}
        character["campaign_state"] = campaign
    campaign.setdefault("version", 1)
    campaign.setdefault("cycle", 1)
    campaign.setdefault("status", "active")
    campaign.setdefault("completed_incident_ids", [])
    campaign.setdefault("epilogues", [])
    campaign.setdefault("started_at", character.get("created_at") or datetime.now().isoformat())
    character.setdefault("incident_history", [])
    return campaign


def finalize_incident_history(character: Dict, result: Optional[Dict] = None) -> Optional[Dict]:
    incident = character.get("incident_state", {}) or {}
    if incident.get("status") != "resolved" or not incident.get("resolution_path"):
        return None
    campaign = ensure_campaign(character)
    cycle = max(1, int(campaign.get("cycle", 1) or 1))
    key = f"{cycle}:{incident.get('id')}"
    history = character["incident_history"]
    if any(item.get("key") == key or (item.get("id") == incident.get("id") and item.get("cycle", 1) == cycle) for item in history if isinstance(item, dict)):
        return None
    entry = {
        "key": key,
        "id": incident.get("id"),
        "title": incident.get("title", "幻想乡异变"),
        "cycle": cycle,
        "sequence_index": incident.get("sequence_index", 0),
        "path": incident.get("resolution_path"),
        "path_title": incident.get("resolution_path_title", "自由解决"),
        "summary": incident.get("resolution_summary", ""),
        "aftermath": incident.get("aftermath", ""),
        "variant": incident.get("variant", {}),
        "resolved_at": incident.get("resolved_at") or datetime.now().isoformat(),
    }
    history.append(entry)
    character["incident_history"] = history[-80:]
    completed = campaign["completed_incident_ids"]
    if key not in completed:
        completed.append(key)
    campaign["completed_incident_ids"] = completed[-80:]
    campaign["status"] = "roaming"
    if result is not None:
        resolution = result.setdefault("incident_resolution", {})
        resolution["history_entry"] = entry
    return entry


def _start_repeat_cycle(character: Dict, tasks_data: Dict) -> Dict:
    definitions = load_incident_definitions()
    campaign = ensure_campaign(character)
    previous_cycle = max(1, int(campaign.get("cycle", 1) or 1))
    epilogue = {
        "cycle": previous_cycle,
        "title": f"第 {previous_cycle} 轮异变记录完成",
        "summary": "；".join(f"{item.get('title')}：{item.get('path_title', '自由解决')}" for item in character.get("incident_history", []) if item.get("cycle", 1) == previous_cycle)[-1500:] or "幻想乡暂时恢复日常。",
        "created_at": datetime.now().isoformat(),
    }
    if not any(item.get("cycle") == previous_cycle for item in campaign["epilogues"] if isinstance(item, dict)):
        campaign["epilogues"].append(epilogue)
    campaign["epilogues"] = campaign["epilogues"][-12:]
    campaign["cycle"] = previous_cycle + 1
    campaign["status"] = "active"

    definition = definitions[0]
    cycle = campaign["cycle"]
    base_task_id = definition.get("completion_task_id") or f"main_{definition['id']}_01"
    completion_task_id = f"{base_task_id}_cycle_{cycle}"
    incident = character.setdefault("incident_state", {})
    incident.update({
        "id": definition["id"],
        "title": definition["title"],
        "sequence_index": 0,
        "completion_task_id": completion_task_id,
        "status": "active",
        "stage": "discovery",
        "investigation_progress": 0,
        "threat_progress": 0,
        "clue_ids": [],
        "task_baseline_ids": [str(item.get("id") or item.get("task_id")) for item in tasks_data.get("completed_tasks", []) if isinstance(item, dict)],
        "started_at": datetime.now().isoformat(),
        "resolved_at": None,
        "rewards_claimed": False,
        "resolution_summary": "",
        "resolution_path": None,
        "resolution_path_title": "",
        "aftermath": "",
        "aftermath_turns": 0,
        "related_locations": list(definition.get("related_locations", []) or []),
        "related_npcs": list(definition.get("related_npcs", []) or []),
    })
    character.setdefault("time", {}).update({
        "chapter_status": "active",
        "anomaly_state": "active",
        "chapter_node_name": definition["title"],
        "chapter_time_remaining": float(definition.get("base_hours", 72) or 72),
    })
    active = tasks_data.setdefault("active_tasks", [])
    if not any(item.get("id") == completion_task_id for item in active if isinstance(item, dict)):
        active.append({
            "id": completion_task_id,
            "name": definition.get("task_name", definition["title"]),
            "description": definition.get("task_description", definition.get("rumor", "")),
            "priority": 20,
            "source": "新一轮异变传闻",
            "incident_id": definition["id"],
            "campaign_cycle": cycle,
            "created_at": datetime.now().isoformat(),
        })
    apply_incident_variant(character, definition, tasks_data)
    return definition


def advance_campaign_state(character: Dict, result: Dict, action_text: str, tasks_data: Dict) -> Dict:
    campaign = ensure_campaign(character)
    incident = character.get("incident_state", {}) or {}
    if incident.get("status") != "resolved":
        campaign["status"] = "active"
        return campaign

    campaign["status"] = "roaming"
    incident["aftermath_turns"] = int(incident.get("aftermath_turns", 0) or 0) + 1
    definitions = load_incident_definitions()
    definition = next((item for item in definitions if item.get("id") == incident.get("id")), {})
    aftermaths = definition.get("aftermaths", []) or []
    if aftermaths and incident["aftermath_turns"] <= len(aftermaths):
        result["incident_aftermath"] = {
            "title": f"{incident.get('title', '异变')}的余波",
            "description": aftermaths[incident["aftermath_turns"] - 1],
            "turn": incident["aftermath_turns"],
            "gates_exploration": False,
        }

    is_last = int(incident.get("sequence_index", 0) or 0) >= len(definitions) - 1
    asks_next = any(word in str(action_text or "") for word in NEXT_INCIDENT_WORDS)
    if is_last and asks_next and not result.get("new_incident"):
        next_definition = _start_repeat_cycle(character, tasks_data)
        result["new_incident"] = {
            "id": next_definition["id"],
            "title": next_definition["title"],
            "rumor": next_definition.get("rumor", ""),
            "cycle": campaign["cycle"],
        }
        result["tasks_dirty"] = True
        result["incident_state"] = dict(character["incident_state"])
    return campaign
