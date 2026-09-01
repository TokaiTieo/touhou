"""Bounded, deterministic maintenance for save-resident NPC memories."""

import re
from datetime import datetime
from typing import Dict

from backend.services.memory_retrieval import semantic_backend_status
from backend.services.npc_memory_service import compress_npc_memory_bucket, upgrade_npc_memory_metadata


def _fingerprint(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


def maintain_memories(character: Dict, *, force: bool = False) -> Dict:
    memories = character.setdefault("npc_memories", {})
    if not isinstance(memories, dict):
        memories = {}
        character["npc_memories"] = memories
    maintenance = character.setdefault("memory_maintenance", {})
    if not isinstance(maintenance, dict):
        maintenance = {}
        character["memory_maintenance"] = maintenance
    history_count = len(character.get("conversation_history", []) or [])
    previous_count = int(maintenance.get("last_history_count", 0) or 0)
    total_before = sum(len(items) for items in memories.values() if isinstance(items, list))
    if not force and total_before < 40 and history_count - previous_count < 24:
        return {"ran": False, "reason": "interval_not_reached", "total_memories": total_before}

    upgrade_npc_memory_metadata(character)
    duplicates_removed = 0
    compressed_npcs = []
    for npc_name, items in list(memories.items()):
        if not isinstance(items, list):
            memories[npc_name] = []
            continue
        deduplicated = []
        seen = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = _fingerprint(item.get("summary"))
            if key and key in seen:
                previous = seen[key]
                previous["importance"] = max(
                    int(previous.get("importance", 5) or 5),
                    int(item.get("importance", 5) or 5),
                )
                previous["used_count"] = int(previous.get("used_count", 0) or 0) + int(
                    item.get("used_count", 0) or 0
                )
                duplicates_removed += 1
                continue
            deduplicated.append(item)
            if key:
                seen[key] = item
        memories[npc_name] = deduplicated
        if len(deduplicated) > 36 and compress_npc_memory_bucket(character, npc_name, keep_recent=24):
            compressed_npcs.append(npc_name)

    backend = semantic_backend_status()
    index_meta = character.setdefault("memory_index_meta", {})
    if not isinstance(index_meta, dict):
        index_meta = {}
        character["memory_index_meta"] = index_meta
    semantic_index = character.setdefault("semantic_memory_index", {})
    if not isinstance(semantic_index, dict):
        semantic_index = {}
        character["semantic_memory_index"] = semantic_index
    invalidated_indexes = 0
    for npc_name, meta in list(index_meta.items()):
        if not isinstance(meta, dict):
            continue
        if meta.get("backend") and (
            meta.get("backend") != backend.get("backend") or meta.get("model") != backend.get("model")
        ):
            semantic_index[npc_name] = {}
            invalidated_indexes += 1
        meta.update({"backend": backend.get("backend"), "model": backend.get("model")})

    total_after = sum(len(items) for items in memories.values() if isinstance(items, list))
    report = {
        "ran": True,
        "duplicates_removed": duplicates_removed,
        "compressed_npcs": compressed_npcs,
        "invalidated_indexes": invalidated_indexes,
        "total_before": total_before,
        "total_after": total_after,
        "backend": backend,
        "ran_at": datetime.now().isoformat(),
    }
    maintenance.update({
        "version": 1,
        "runs": int(maintenance.get("runs", 0) or 0) + 1,
        "last_run_at": report["ran_at"],
        "last_report": report,
        "last_history_count": history_count,
    })
    return report
