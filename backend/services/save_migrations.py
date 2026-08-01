"""Explicit additive save migrations. Existing fields are never removed."""

from datetime import datetime
from typing import Dict
from backend.version import SAVE_SCHEMA_VERSION


LATEST_SAVE_VERSION = SAVE_SCHEMA_VERSION


def migrate_save_schema(character: Dict) -> bool:
    changed = False
    try:
        version = int(character.get("save_version", 1) or 1)
    except (TypeError, ValueError):
        version = 1

    if version < 5:
        experience = character.setdefault("skill_experience", {})
        for name in ("弹幕熟练度", "调查熟练度", "交涉熟练度", "生存熟练度"):
            experience.setdefault(name, 0)
        incident = character.get("incident_state")
        if isinstance(incident, dict):
            incident.setdefault("resolution_path", None)
            incident.setdefault("resolution_path_title", "")
            incident.setdefault("aftermath", "")
        history = character.setdefault("migration_history", [])
        if not any(item.get("version") == 5 for item in history if isinstance(item, dict)):
            history.append({
                "version": 5,
                "applied_at": datetime.now().isoformat(),
                "summary": "成长经验、异变解决路径与安全运行数据升级"
            })
        character["content_schema_version"] = max(
            2,
            int(character.get("content_schema_version", 1) or 1)
        )
        character["save_version"] = 5
        changed = True
        version = 5

    if version < 6:
        from backend.services.story_summary_service import default_story_summary

        character.setdefault("story_summary", default_story_summary())
        character.setdefault("inventory_state", {"items": [], "capacity": 30, "currency": 0})
        character.setdefault("reputation_history", [])
        character.setdefault("relationship_progress", {})
        character.setdefault("npc_runtime", {})
        character.setdefault("event_flags", {})
        character.setdefault("usage_stats", {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_tokens": 0,
            "last_error": None,
        })
        history = character.setdefault("migration_history", [])
        if not any(item.get("version") == 6 for item in history if isinstance(item, dict)):
            history.append({
                "version": 6,
                "applied_at": datetime.now().isoformat(),
                "summary": "长期剧情摘要、物品声望关系闭环、动态事件与用量诊断升级",
            })
        try:
            content_version = int(character.get("content_schema_version", 1) or 1)
        except (TypeError, ValueError):
            content_version = 1
        character["content_schema_version"] = max(6, content_version)
        character["save_version"] = 6
        changed = True
        version = 6

    if version < 7:
        character.setdefault("world_state", {
            "flags": {}, "locations": {}, "factions": {}, "rumors": [],
        })
        character.setdefault("consequence_log", [])
        character.setdefault("deferred_consequences", [])
        character.setdefault("relationship_boundaries", {})
        character.setdefault("memory_index_meta", {})
        character.setdefault("semantic_memory_index", {})
        character.setdefault("model_runtime", {})
        character.setdefault("spellcard_mastery", {})
        character.setdefault("opponent_adaptation", {})
        character.setdefault("npc_simulation", {"last_simulated_hour": 0, "events": []})
        history = character.setdefault("migration_history", [])
        if not any(item.get("version") == 7 for item in history if isinstance(item, dict)):
            history.append({
                "version": 7,
                "applied_at": datetime.now().isoformat(),
                "summary": "世界后果链、离屏人物、语义记忆、关系边界与符卡成长升级",
            })
        try:
            content_version = int(character.get("content_schema_version", 1) or 1)
        except (TypeError, ValueError):
            content_version = 1
        character["content_schema_version"] = max(7, content_version)
        character["save_version"] = 7
        changed = True

    # Early V6 development saves may carry the version flag while missing a
    # newly introduced optional field. Keep this repair additive and idempotent.
    from backend.services.story_summary_service import default_story_summary
    v6_defaults = {
        "state_revision": 0,
        "story_summary": default_story_summary(),
        "inventory_state": {"items": [], "capacity": 30, "currency": 0},
        "reputation_history": [],
        "relationship_progress": {},
        "npc_runtime": {},
        "event_flags": {},
        "usage_stats": {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_tokens": 0,
            "last_error": None,
            "estimated_cost": None,
            "cost_currency": None,
        },
        "world_state": {"flags": {}, "locations": {}, "factions": {}, "rumors": []},
        "consequence_log": [],
        "deferred_consequences": [],
        "relationship_boundaries": {},
        "memory_index_meta": {},
        "semantic_memory_index": {},
        "model_runtime": {},
        "spellcard_mastery": {},
        "opponent_adaptation": {},
        "npc_simulation": {"last_simulated_hour": 0, "events": []},
        "relationship_turn_receipts": [],
        "resolved_turn_ids": [],
    }
    for key, default in v6_defaults.items():
        if key not in character:
            character[key] = default
            changed = True
    return changed
