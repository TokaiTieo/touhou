"""Save records, tasks, snapshots, relationships, and feedback routes."""

import io
import json
import zipfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.ai_service import call_ai_async, get_last_ai_runtime
from backend.services.incident_service import sync_incident_from_tasks
from backend.services.relationship_service import get_current_relationships
from backend.services.story_summary_service import rebuild_story_summary
from backend.utils.ai_json import safe_json_loads
from backend.version import DISPLAY_VERSION
from backend.world_manager import (
    create_character_snapshot,
    list_character_snapshots,
    load_character,
    load_tasks,
    restore_character_snapshot,
    save_character,
    save_tasks,
)

router = APIRouter()


class AppendConversationRequest(BaseModel):
    character_id: str
    speaker: str
    content: str
    scene: str
    is_dead: bool = False


class DeleteHistoryRequest(BaseModel):
    character_id: str
    from_index: int


class RateMessageRequest(BaseModel):
    character_id: str
    message_index: int
    rating: Optional[str] = None


class RewriteMessageRequest(BaseModel):
    character_id: str
    message_id: Optional[str] = None
    message_index: Optional[int] = None
    instruction: Optional[str] = None


class RestoreSnapshotRequest(BaseModel):
    character_id: str
    snapshot_id: str
    branch: bool = False
    branch_name: Optional[str] = None


def _require_character(character_id: str):
    character = load_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return character


@router.post("/append_conversation")
async def append_conversation(request: AppendConversationRequest):
    character = _require_character(request.character_id)
    current_hour = character.get("time", {}).get("current_hour", 0)
    history = character.setdefault("conversation_history", [])
    message = {
        "message_id": f"msg_{datetime.now().timestamp()}_{len(history)}",
        "speaker": request.speaker,
        "content": request.content,
        "scene": request.scene,
        "is_dead": request.is_dead,
        "timestamp": datetime.now().isoformat(),
        "game_hour": current_hour,
        "rating": None,
        "reroll_of": None,
        "rewrite_candidates": [],
    }
    history.append(message)
    character["conversation_history"] = history[-500:]
    rebuild_story_summary(character, load_tasks(request.character_id))
    save_character(request.character_id, character)
    return {
        "status": "ok",
        "message_id": message["message_id"],
        "message_index": len(character["conversation_history"]) - 1,
        "rewrite_candidates": [],
    }


@router.post("/rewrite_message")
async def rewrite_message(request: RewriteMessageRequest):
    """Create a prose-only alternative without replaying game state."""
    character = _require_character(request.character_id)
    history = character.setdefault("conversation_history", [])
    target_index = None
    if request.message_id:
        target_index = next(
            (index for index, item in enumerate(history) if item.get("message_id") == request.message_id),
            None,
        )
    if target_index is None and request.message_index is not None:
        target_index = request.message_index
    if target_index is None or target_index < 0 or target_index >= len(history):
        raise HTTPException(status_code=400, detail="消息索引无效")

    target = history[target_index]
    player_name = character.get("profile", {}).get("name", "玩家")
    if target.get("speaker") in (player_name, "系统"):
        raise HTTPException(status_code=400, detail="仅可改写叙事或 NPC 回复")

    context_start = max(0, target_index - 5)
    context_lines = [
        f"{item.get('speaker', '未知')}: {item.get('content', '')}"
        for item in history[context_start:target_index]
    ]
    instruction = (request.instruction or "改善文风、节奏和角色语气").strip()[:500]
    prompt = f"""你是《东方异变录》的文字润色器。请为下方原回复生成一个不同措辞的候选版本。

硬性规则：
1. 只能改写叙事表达，不得改变已经发生的事实、胜负、伤势、物品、时间、地点、任务、关系、记忆或世界状态。
2. 不得增加新的行动结果、任务进度、奖励、惩罚或数值变化。
3. 保持原角色身份与语气，不要输出分析、标题、Markdown 代码块或 JSON。
4. 直接输出一段可替换原回复的完整中文文本。

改写偏好：{instruction}
最近上下文：
{chr(10).join(context_lines) or "无"}

原回复：
{target.get("content", "")}
"""
    rewritten = (await call_ai_async(prompt, temperature=0.85)).strip()
    parsed = safe_json_loads(rewritten, rewritten)
    if isinstance(parsed, dict):
        rewritten = str(parsed.get("description") or parsed.get("message") or "").strip()
    if not rewritten or rewritten.startswith(("【AI调用失败】", "【系统提示】")):
        raise HTTPException(status_code=502, detail=rewritten or "模型未返回有效改写")

    runtime = get_last_ai_runtime()
    candidate = {
        "candidate_id": f"rewrite_{datetime.now().timestamp()}_{len(target.get('rewrite_candidates', []))}",
        "content": rewritten,
        "created_at": datetime.now().isoformat(),
        "model": runtime.get("used_model") or runtime.get("requested_model"),
    }
    candidates = target.setdefault("rewrite_candidates", [])
    candidates.append(candidate)
    target["rewrite_candidates"] = candidates[-4:]
    character["model_runtime"] = runtime
    save_character(request.character_id, character)
    return {
        "status": "ok",
        "message_id": target.get("message_id"),
        "message_index": target_index,
        "original": target.get("content", ""),
        "rewrite_candidates": target["rewrite_candidates"],
        "active_candidate": len(target["rewrite_candidates"]) - 1,
        "model_runtime": runtime,
    }


@router.post("/delete_history")
async def delete_history(request: DeleteHistoryRequest):
    character = _require_character(request.character_id)
    history = character.setdefault("conversation_history", [])
    if request.from_index < 0 or request.from_index > len(history):
        raise HTTPException(status_code=400, detail="无效的索引")
    deleted_count = len(history) - request.from_index
    character["conversation_history"] = history[:request.from_index]
    rebuild_story_summary(character, load_tasks(request.character_id), force=True)
    save_character(request.character_id, character)
    return {"status": "ok", "deleted_count": deleted_count}


@router.get("/tasks")
async def get_tasks(character_id: str):
    tasks_data = load_tasks(character_id)
    character = load_character(character_id)
    if character:
        sync_incident_from_tasks(character, tasks_data)
        save_character(character_id, character)
    return {
        "active_tasks": tasks_data.get("active_tasks", []),
        "completed_tasks": tasks_data.get("completed_tasks", []),
    }


@router.post("/add_task")
async def add_task(request: dict):
    character_id = request.get("character_id")
    task_info = request.get("task", {})
    if not character_id or not task_info:
        raise HTTPException(status_code=400, detail="缺少必要参数")
    tasks_data = load_tasks(character_id)
    active_tasks = tasks_data.get("active_tasks", [])
    priority = max(1, min(1000, task_info.get("priority", 100)))
    new_task = {
        "id": f"task_{int(datetime.now().timestamp())}_{len(active_tasks)}",
        "name": task_info.get("name", "新任务"),
        "description": task_info.get("description", ""),
        "priority": priority,
        "created_at": datetime.now().isoformat(),
        "source": task_info.get("source", "system_helper"),
    }
    active_tasks.append(new_task)
    active_tasks.sort(key=lambda item: item.get("priority", 100))
    tasks_data["active_tasks"] = active_tasks
    save_tasks(character_id, tasks_data)
    return {"status": "ok", "task": new_task}


@router.post("/delete_task")
async def delete_task(request: dict):
    character_id = request.get("character_id")
    task_id = request.get("task_id")
    if not character_id or not task_id:
        raise HTTPException(status_code=400, detail="缺少必要参数")
    tasks_data = load_tasks(character_id)
    active_tasks = tasks_data.get("active_tasks", [])
    removed_tasks = tasks_data.get("removed_tasks", [])
    removed_task = next((item for item in active_tasks if item.get("id") == task_id), None)
    if not removed_task:
        raise HTTPException(status_code=404, detail="任务不存在")
    active_tasks.remove(removed_task)
    removed_task["removed_at"] = datetime.now().isoformat()
    removed_task["removed_reason"] = "user_deleted"
    removed_tasks.append(removed_task)
    tasks_data["active_tasks"] = active_tasks
    tasks_data["removed_tasks"] = removed_tasks
    save_tasks(character_id, tasks_data)
    return {"status": "ok", "message": "任务已删除"}


@router.get("/relationships")
async def get_relationships(character_id: str):
    character = _require_character(character_id)
    get_current_relationships(character)
    return {
        "relationships": character.get("relationships_map", {}),
        "progress": character.get("relationship_progress", {}),
        "history": character.get("relationships_history", []),
    }


@router.get("/character_journal")
async def get_character_journal(character_id: str):
    character = _require_character(character_id)
    return {
        "profile": character.get("profile", {}),
        "status": character.get("status", {}),
        "player_state": character.get("player_state", {}),
        "resources": character.get("resources", {}),
        "inventory": character.get("inventory_state", {}),
        "reputation": character.get("reputation", {}),
        "reputation_history": character.get("reputation_history", []),
        "relationships": character.get("relationships_map", {}),
        "relationship_progress": character.get("relationship_progress", {}),
        "relationship_boundaries": character.get("relationship_boundaries", {}),
        "story_summary": character.get("story_summary", {}),
        "usage": character.get("usage_stats", {}),
        "npc_memories": character.get("npc_memories", {}),
        "npc_memory_summaries": character.get("npc_memory_summaries", {}),
        "open_events": character.get("open_events", []),
        "spellcard_history": character.get("spellcard_history", []),
        "spellcard_mastery": character.get("spellcard_mastery", {}),
        "opponent_adaptation": character.get("opponent_adaptation", {}),
        "world_state": character.get("world_state", {}),
        "consequence_log": character.get("consequence_log", []),
        "deferred_consequences": character.get("deferred_consequences", []),
        "npc_simulation": character.get("npc_simulation", {}),
        "gm_mode": character.get("gm_mode", False),
    }


@router.get("/snapshots")
async def get_character_snapshots(character_id: str):
    character = _require_character(character_id)
    snapshots = list_character_snapshots(character_id)
    if not snapshots:
        create_character_snapshot(character_id, character, label="旧存档初始节点", force=True)
        snapshots = list_character_snapshots(character_id)
    return {"snapshots": snapshots}


@router.post("/snapshots/restore")
async def restore_snapshot(request: RestoreSnapshotRequest):
    _require_character(request.character_id)
    try:
        return restore_character_snapshot(
            request.character_id,
            request.snapshot_id,
            branch=request.branch,
            branch_name=request.branch_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/npc_memories")
async def get_npc_memories(character_id: str, npc_name: Optional[str] = None):
    character = _require_character(character_id)
    memories = character.get("npc_memories", {})
    summaries = character.get("npc_memory_summaries", {})
    if npc_name:
        return {
            "npc_name": npc_name,
            "summary": summaries.get(npc_name, ""),
            "memories": memories.get(npc_name, []),
        }
    return {"memories": memories, "summaries": summaries}


@router.get("/export_feedback")
async def export_feedback(character_id: str):
    character = _require_character(character_id)
    tasks = load_tasks(character_id)
    payload = {
        "exported_at": datetime.now().isoformat(),
        "app_version": DISPLAY_VERSION,
        "character_id": character_id,
        "profile": character.get("profile", {}),
        "status": character.get("status", {}),
        "time": character.get("time", {}),
        "player_state": character.get("player_state", {}),
        "debug_last_ai": character.get("debug_last_ai", {}),
        "recent_conversation": character.get("conversation_history", [])[-30:],
        "tasks": tasks,
        "relationships": character.get("relationships_map", {}),
        "open_events": character.get("open_events", [])[-20:],
        "spellcard_history": character.get("spellcard_history", [])[-20:],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("feedback.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr("character_snapshot.json", json.dumps(character, ensure_ascii=False, indent=2))
        archive.writestr("tasks.json", json.dumps(tasks, ensure_ascii=False, indent=2))
        archive.writestr(
            "README.txt",
            "TouHou feedback package. It may contain save data and recent AI debug context.\n",
        )
    buffer.seek(0)
    filename = f"touhou_feedback_{character_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/end_session")
async def end_session(request: dict):
    character_id = request.get("character_id")
    if not character_id:
        raise HTTPException(status_code=400, detail="缺少 character_id")
    character = _require_character(character_id)
    character["last_played"] = datetime.now().isoformat()
    save_character(character_id, character)
    return {"status": "ok", "message": "会话已结束，数据已保存"}


@router.post("/rate_message")
async def rate_message(request: RateMessageRequest):
    character = _require_character(request.character_id)
    history = character.get("conversation_history", [])
    if request.message_index < 0 or request.message_index >= len(history):
        raise HTTPException(status_code=400, detail="消息索引无效")
    history[request.message_index]["rating"] = request.rating
    save_character(request.character_id, character)
    return {"status": "ok"}
