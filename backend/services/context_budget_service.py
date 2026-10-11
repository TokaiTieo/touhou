"""Allocate prompt context by semantic section with local diagnostics."""

import math
import json
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


def _truncate_records(text: str, limit: int, *, tail: bool = False) -> str:
    if len(text) <= limit:
        return text
    lines, selected, used = text.splitlines(), [], 0
    for line in reversed(lines) if tail else lines:
        cost = len(line) + bool(selected)
        if used + cost > limit:
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(record, dict) or "content" not in record:
                continue
            content = str(record["content"])
            record["content"] = "…（正文按预算截断，归属保留）"
            remaining = limit - used - bool(selected) - len(json.dumps(record, ensure_ascii=False))
            if remaining < 1:
                continue
            record["content"] = content[:remaining] + record["content"]
            line = json.dumps(record, ensure_ascii=False)
            while len(line) + used + bool(selected) > limit:
                record["content"] = record["content"][:-1]
                line = json.dumps(record, ensure_ascii=False)
            cost = len(line) + bool(selected)
        selected.append(line)
        used += cost
    return "\n".join(reversed(selected) if tail else selected)


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
        truncate = _truncate_records if key in {"history_text", "npc_memories"} else _truncate
        value = truncate(original, allowed, tail=key in TAIL_SECTIONS) if allowed else ""
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
