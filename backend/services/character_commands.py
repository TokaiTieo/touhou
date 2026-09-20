"""Durable, idempotent character commands sharing the player turn queue."""

import hashlib
import inspect
import json
import uuid
from functools import wraps

from fastapi import HTTPException
from backend.services.turn_coordinator import turn_coordinator
from backend.services.storage_paths import require_identifier
from backend.services.character_view_service import command_result


def serialize_character_access(handler):
    """Queue one existing lifecycle handler without changing its storage logic."""
    @wraps(handler)
    async def wrapped(*args, **kwargs):
        request = args[0] if args else kwargs.get("request", kwargs.get("character_id"))
        owner = request.get("character_id") if isinstance(request, dict) else getattr(request, "character_id", request if isinstance(request, str) else None)
        if not owner:
            return await handler(*args, **kwargs)
        require_identifier(owner)
        return await turn_coordinator.execute(character_id=str(owner), turn_id=f"access:{uuid.uuid4()}",
            kind="command", operation=lambda: handler(*args, **kwargs))
    return wrapped


async def execute_character_command(character_id, operation_id, payload, change):
    require_identifier(character_id)
    from backend import world_manager as storage

    identity = str(operation_id or uuid.uuid4())
    if len(identity) > 160:
        raise HTTPException(400, "操作标识过长")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    async def execute():
        character = storage.load_character(character_id)
        if not character:
            raise HTTPException(404, "角色不存在")
        for item in character.get("command_receipts", []):
            if item["id"] == identity:
                if item["fingerprint"] != fingerprint:
                    raise HTTPException(409, "操作标识已用于其他内容，请刷新后重试")
                return command_result(item["result"])
        tasks = storage.load_tasks(character_id)
        char_revision, task_revision = character.get("state_revision", 0), tasks.get("state_revision", 0)
        result = change(character, tasks)
        if inspect.isawaitable(result):
            result = await result
        result = command_result(result)
        receipts = character.setdefault("command_receipts", [])
        receipts.append({"id": identity, "fingerprint": fingerprint, "result": result})
        character["command_receipts"] = receipts[-60:]
        try:
            storage.save_turn_bundle(character_id, character, tasks,
                                     expected_character_revision=char_revision,
                                     expected_tasks_revision=task_revision)
        except storage.StaleTurnError as exc:
            raise HTTPException(409, "存档已更新，本次操作未覆盖新状态，请刷新后重试") from exc
        return result

    try:
        return await turn_coordinator.execute(character_id=character_id,
            turn_id=f"command:{uuid.uuid4()}", kind="command", operation=execute)
    except TimeoutError as exc:
        raise HTTPException(409, "上一操作仍在执行，请稍后以原操作标识重试") from exc
