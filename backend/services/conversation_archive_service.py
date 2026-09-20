"""Immutable history chunks; only the manifest participates in save commits."""

import copy
import hashlib
import json
import re
import threading

from backend.services.storage_paths import contained_path

CHUNK_SIZE = 200
RECENT_MESSAGES = 200
_chunk_lock = threading.RLock()


def _root(root=None):
    if root is None:
        from backend.world_manager import get_characters_dir
        root = get_characters_dir()
    return root


def _read(chunk, root):
    identity = chunk.get("id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("剧情档案标识无效")
    path = contained_path(root, "_history", identity + ".json")
    try:
        raw = path.read_text(encoding="utf-8").encode("utf-8")
    except OSError as exc:
        raise ValueError("剧情档案缺失，请恢复完整备份或重新导入导出的角色文件") from exc
    if hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError("剧情档案校验失败，请恢复备份")
    messages = json.loads(raw)
    if not isinstance(messages, list) or len(messages) != chunk.get("count"):
        raise ValueError("剧情档案条目不完整")
    return messages


def history_count(character):
    return sum(chunk["count"] for chunk in character.get("conversation_archive", {}).get("chunks", [])) + len(character.get("conversation_history", []))


def compact_history(character, root=None):
    history = character.get("conversation_history", [])
    if len(history) <= RECENT_MESSAGES:
        return
    root = _root(root)
    from backend.world_manager import _atomic_json_write
    manifest = copy.deepcopy(character.get("conversation_archive") or {"version": 1, "chunks": []})
    archived = (len(history) - RECENT_MESSAGES) // CHUNK_SIZE * CHUNK_SIZE
    if not archived:
        return
    for start in range(0, archived, CHUNK_SIZE):
        messages = history[start:min(start + CHUNK_SIZE, archived)]
        # Match the shared atomic writer's serialization exactly.
        raw = json.dumps(messages, ensure_ascii=False, indent=2).encode("utf-8")
        identity = hashlib.sha256(raw).hexdigest()
        path = contained_path(root, "_history", identity + ".json")
        with _chunk_lock:
            if not path.exists():
                _atomic_json_write(path, messages)
        manifest["chunks"].append({"id": identity, "count": len(messages)})
    character["conversation_archive"] = manifest
    character["conversation_history"] = history[archived:]


def all_history(character, root=None):
    if not character.get("conversation_archive", {}).get("chunks"):
        return list(character.get("conversation_history", []))
    root = _root(root)
    result = []
    for chunk in character.get("conversation_archive", {}).get("chunks", []):
        result.extend(_read(chunk, root))
    return result + character.get("conversation_history", [])


def hydrate_history(character, root=None):
    character["conversation_history"] = all_history(character, root)
    character["conversation_archive"] = {"version": 1, "chunks": []}
    return character["conversation_history"]


def portable_character(character, root=None):
    result = copy.deepcopy(character)
    hydrate_history(result, root)
    return result


def history_page(character, before_id=None, limit=80, query="", root=None):
    root = _root(root)
    limit = max(1, min(200, limit))
    total = history_count(character)
    position = total
    chunks = list(reversed(character.get("conversation_archive", {}).get("chunks", [])))
    batches = [None] + chunks
    found = not before_id
    matches = []
    needle = query.strip().casefold()
    for chunk in batches:
        messages = character.get("conversation_history", []) if chunk is None else _read(chunk, root)
        for message in reversed(messages):
            position -= 1
            if not found:
                found = message.get("message_id") == before_id
                continue
            if needle and needle not in (str(message.get("speaker", "")) + " " + str(message.get("content", ""))).casefold():
                continue
            matches.append((position, message))
            if len(matches) == limit:
                break
        if len(matches) == limit:
            break
    if not found:
        raise ValueError("剧情记录已改变，请重新加载角色")
    matches.reverse()
    start = matches[0][0] if matches else 0
    return {"messages": [message for _, message in matches], "indices": [index for index, _ in matches],
            "start": start, "total": total, "has_more": start > 0}
