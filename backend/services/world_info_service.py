"""Budgeted keyword and scope based World Info injection."""

import json
from pathlib import Path
from typing import Dict, List


def _tokens(value) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in (value or []) if str(item)]


def build_world_info_context(
    world_info_path: Path,
    query: str,
    scene: str = "",
    npc_name: str = "",
    budget_chars: int = 1800,
    limit: int = 6
) -> Dict:
    diagnostics = {
        "total_entries": 0,
        "matched_entries": 0,
        "excluded_entries": [],
        "invalid_entries": [],
        "group_conflicts": [],
        "budget_exhausted": False,
    }
    try:
        data = json.loads(world_info_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, AttributeError):
        diagnostics["load_error"] = True
        return {
            "text": "", "entries": [], "budget_chars": budget_chars,
            "used_chars": 0, "diagnostics": diagnostics
        }

    haystack = f"{scene} {npc_name} {query}"
    candidates = []
    entries = data.get("entries", [])
    diagnostics["total_entries"] = len(entries) if isinstance(entries, list) else 0
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict) or not str(entry.get("content") or "").strip():
            diagnostics["invalid_entries"].append(
                entry.get("id", f"index:{index}") if isinstance(entry, dict) else f"index:{index}"
            )
            continue
        keywords = _tokens(entry.get("keywords"))
        scenes = _tokens(entry.get("scenes"))
        npcs = _tokens(entry.get("npcs"))
        excludes = _tokens(entry.get("exclude_keywords"))
        exclude_hits = [token for token in excludes if token in haystack]
        if exclude_hits:
            diagnostics["excluded_entries"].append({"id": entry.get("id"), "hits": exclude_hits})
            continue
        keyword_hits = [token for token in keywords if token in haystack]
        scene_hits = [token for token in scenes if token == scene or token in scene]
        npc_hits = [token for token in npcs if token == npc_name or token in npc_name]
        if not (entry.get("constant") or keyword_hits or scene_hits or npc_hits):
            continue
        score = (
            len(keyword_hits) * 12
            + len(scene_hits) * 18
            + len(npc_hits) * 20
            + (8 if entry.get("constant") else 0)
            - int(entry.get("priority", 100)) * 0.05
        )
        candidates.append((score, int(entry.get("priority", 100)), entry, keyword_hits + scene_hits + npc_hits))
    diagnostics["matched_entries"] = len(candidates)
    candidates.sort(key=lambda item: (-item[0], item[1], str(item[2].get("id", ""))))

    selected = []
    groups = set()
    used = 0
    lines = []
    for score, priority, entry, hits in candidates:
        group = entry.get("exclusive_group")
        if group and group in groups:
            diagnostics["group_conflicts"].append({"id": entry.get("id"), "group": group})
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        line = f"【{entry.get('title', '世界书')}】{content}"
        remaining = max(0, budget_chars - used)
        if remaining <= 0:
            diagnostics["budget_exhausted"] = True
            break
        truncated = len(line) > remaining
        emitted = line[:remaining]
        lines.append(emitted)
        used += len(emitted)
        selected.append({
            "id": entry.get("id"),
            "title": entry.get("title", "世界书"),
            "hits": hits,
            "priority": priority,
            "score": round(score, 2),
            "chars": len(emitted),
            "truncated": truncated
        })
        if group:
            groups.add(group)
        if len(selected) >= limit or truncated:
            diagnostics["budget_exhausted"] = truncated or used >= budget_chars
            break
    return {
        "text": "\n".join(lines),
        "entries": selected,
        "budget_chars": budget_chars,
        "used_chars": used,
        "content_version": data.get("content_version", 1),
        "diagnostics": diagnostics,
    }
