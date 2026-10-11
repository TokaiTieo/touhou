"""Attribution-preserving history records shared by prompts and summaries."""

import json

from backend.services.npc_attribution_service import npc_identity


def select_history(server_history, client_history=()):
    # The browser sends a window, not a second authoritative timeline.
    return server_history if server_history else client_history


def format_history_record(item, content_limit=None):
    content = str(item.get("content") or item.get("text") or "").strip()
    if content_limit is not None and len(content) > content_limit:
        content = content[:content_limit] + "…"
    identity = npc_identity(item.get("speaker"), item.get("npc_id")) if item.get("npc_id") else None
    record = {
        "message_id": item.get("message_id"), "turn_id": item.get("turn_id"),
        "speaker": item.get("speaker") or item.get("role") or "未知",
        "role": item.get("role", "unknown"), "npc": identity,
        "scene": item.get("scene") or "未知",
        "participants": item.get("participants") or "归属未知，不得绑定当前人物",
        "visibility": item.get("visibility") or "未知，不代表在场所有人知晓",
        "content": content,
    }
    # One physical line is an indivisible budget unit, including escaped newlines.
    return json.dumps(record, ensure_ascii=False)


def format_history_for_ai(history, max_count=20):
    records, seen = [], set()
    for item in history or []:
        if not isinstance(item, dict) or not str(item.get("content") or item.get("text") or "").strip():
            continue
        identity = item.get("message_id")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        records.append(item)
    return "\n".join(format_history_record(item) for item in records[-max_count:]) if max_count > 0 and records else "（无历史记录）"
