"""Allocate prompt context by semantic section with local diagnostics."""

import math
from typing import Dict, Iterable, Tuple


DEFAULT_LIMITS = {
    "world_setting": 7600,
    "player_background": 2600,
    "player_info": 3000,
    "npc_info": 4200,
    "scene_npcs": 3000,
    "history_text": 4200,
    "story_summary": 2200,
    "progression_context": 1800,
    "existing_locations": 2600,
    "current_relationships": 2400,
    "active_tasks": 2600,
    "npc_memories": 3000,
    "consequences": 1800,
    "npc_simulation": 1600,
    "relationship_policy": 2200,
    "rule_context": 1800,
}

TAIL_SECTIONS = {"history_text", "npc_memories", "npc_simulation", "consequences"}


def _truncate(text: str, limit: int, *, tail: bool = False) -> str:
    if len(text) <= limit:
        return text
    marker = "\n…（上下文已按预算截断）\n"
    if limit <= len(marker):
        return text[-limit:] if tail and limit else text[:limit]
    keep = max(0, limit - len(marker))
    if tail:
        return marker + text[-keep:]
    return text[:keep] + marker


def budget_context_sections(
    sections: Dict[str, object],
    *,
    total_chars: int = 24000,
    limits: Dict[str, int] = None,
    protected: Iterable[str] = (),
) -> Tuple[Dict[str, str], Dict]:
    """Return budgeted text and diagnostics; insertion order defines priority."""
    section_limits = {**DEFAULT_LIMITS, **(limits or {})}
    protected = set(protected)
    normalized = {key: str(value or "") for key, value in sections.items()}
    allocated: Dict[str, str] = {}
    diagnostics = {
        "total_budget_chars": total_chars,
        "original_chars": sum(len(value) for value in normalized.values()),
        "used_chars": 0,
        "estimated_tokens": 0,
        "sections": [],
    }
    remaining = max(0, total_chars)
    ordered_keys = list(normalized)
    ordered_keys.sort(key=lambda key: (key not in protected, list(normalized).index(key)))
    for key in ordered_keys:
        original = normalized[key]
        own_limit = max(0, int(section_limits.get(key, len(original))))
        allowed = min(own_limit, remaining)
        value = _truncate(original, allowed, tail=key in TAIL_SECTIONS) if allowed else ""
        allocated[key] = value
        used = len(value)
        remaining -= used
        diagnostics["sections"].append({
            "name": key,
            "original_chars": len(original),
            "used_chars": used,
            "estimated_tokens": math.ceil(used / 2),
            "truncated": used < len(original),
            "priority": "protected" if key in protected else "normal",
        })
    diagnostics["used_chars"] = sum(len(value) for value in allocated.values())
    diagnostics["estimated_tokens"] = math.ceil(diagnostics["used_chars"] / 2)
    diagnostics["budget_exhausted"] = remaining <= 0
    return allocated, diagnostics
