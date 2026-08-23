"""Save records, tasks, snapshots, relationships, and feedback routes."""

import io
import json
import zipfile
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.ai_service import call_ai_async, get_last_ai_runtime
from backend.services.incident_service import sync_incident_from_tasks
from backend.services.narrative_evaluation_service import (
    build_rated_samples,
    summarize_rated_samples,
)
from backend.services.progression_service import ensure_progression_profile
from backend.services.relationship_service import get_current_relationships
from backend.services.save_health_service import (
    inspect_character_file,
    inspect_character_payload,
    repair_character_payload_types,
)
from backend.services.story_summary_service import rebuild_story_summary
from backend.utils.ai_json import safe_json_loads
from backend.version import DISPLAY_VERSION
from backend.world_manager import (
    create_character_snapshot,
    ensure_character_fields,
    get_characters_dir,
    get_default_tasks,
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


class SpellcardLoadoutRequest(BaseModel):
    character_id: str
    spellcards: list[str]


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


@router.post("/spellcard_loadout")
async def set_spellcard_loadout(request: SpellcardLoadoutRequest):
    character = _require_character(request.character_id)
    spellcards = list(dict.fromkeys(str(name).strip() for name in request.spellcards if str(name).strip()))
    if len(spellcards) > 6:
        raise HTTPException(status_code=400, detail="符卡栏最多配置 6 张")
    if any(len(name) > 160 for name in spellcards):
        raise HTTPException(status_code=400, detail="符卡名称过长")
    character["spellcard_loadout"] = spellcards
    ensure_progression_profile(character)
    save_character(request.character_id, character)
    return {"status": "ok", "spellcard_loadout": character["spellcard_loadout"], "exploration_restricted": False}


@router.get("/character_journal")
async def get_character_journal(character_id: str):
    character = _require_character(character_id)
    ensure_progression_profile(character)
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
        "story_director": character.get("story_director", {}),
        "usage": character.get("usage_stats", {}),
        "npc_memories": character.get("npc_memories", {}),
        "npc_memory_summaries": character.get("npc_memory_summaries", {}),
        "open_events": character.get("open_events", []),
        "spellcard_history": character.get("spellcard_history", []),
        "spellcard_mastery": character.get("spellcard_mastery", {}),
        "spellcard_loadout": character.get("spellcard_loadout", []),
        "progression_milestones": character.get("progression_milestones", {}),
        "opponent_adaptation": character.get("opponent_adaptation", {}),
        "world_state": character.get("world_state", {}),
        "consequence_log": character.get("consequence_log", []),
        "deferred_consequences": character.get("deferred_consequences", []),
        "npc_simulation": character.get("npc_simulation", {}),
        "narrative_feedback": summarize_rated_samples(character),
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


@router.get("/save_health")
async def get_save_health(character_id: str):
    characters_dir = get_characters_dir()
    report = inspect_character_file(characters_dir / f"{character_id}.json")
    snapshots = list_character_snapshots(character_id)
    report["snapshot_count"] = len(snapshots)
    report["repairable"] = bool(report.get("repairable") or snapshots)
    report.pop("payload", None)
    return report


@router.post("/save_health/repair")
async def repair_save(request: dict):
    character_id = str(request.get("character_id") or "").strip()
    if not character_id:
        raise HTTPException(status_code=400, detail="缺少 character_id")
    characters_dir = get_characters_dir()
    report = inspect_character_file(characters_dir / f"{character_id}.json")
    if report.get("status") == "critical":
        snapshots = list_character_snapshots(character_id)
        if not snapshots:
            raise HTTPException(status_code=422, detail="主存档损坏且没有可用快照，无法自动修复")
        restored = restore_character_snapshot(character_id, snapshots[0]["snapshot_id"])
        repaired = inspect_character_file(characters_dir / f"{character_id}.json")
        repaired.pop("payload", None)
        return {"status": "restored_snapshot", "restored": restored, "health": repaired}
    character = report.get("payload") or {}
    create_character_snapshot(character_id, character, label="健康修复前", force=True)
    repair_result = repair_character_payload_types(character)
    character = ensure_character_fields(repair_result["payload"])
    character.pop("_migrated", None)
    save_character(character_id, character)
    repaired = inspect_character_file(characters_dir / f"{character_id}.json")
    repaired.pop("payload", None)
    return {"status": "repaired", "health": repaired, "repaired_fields": repair_result["repaired_fields"]}


@router.get("/export_character/{character_id}")
async def export_character(character_id: str):
    character = _require_character(character_id)
    exported = json.loads(json.dumps(character, ensure_ascii=False, default=str))
    exported["tasks_export"] = load_tasks(character_id)
    exported["export_metadata"] = {
        "app_version": DISPLAY_VERSION,
        "exported_at": datetime.now().isoformat(),
        "format": "touhou_character_v2",
    }
    return exported


@router.post("/import_character")
async def import_character(request: dict):
    payload = request.get("character_data")
    report = inspect_character_payload(payload)
    if report.get("status") == "critical":
        raise HTTPException(status_code=422, detail={
            "message": "角色存档预检未通过", "errors": report.get("errors", [])
        })
    character = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    characters_dir = get_characters_dir()
    source_id = str(character.get("character_id") or "").strip()
    target_id = source_id or str(uuid.uuid4())
    if (characters_dir / f"{target_id}.json").exists():
        target_id = str(uuid.uuid4())
        character["import_origin"] = {"character_id": source_id, "reason": "id_conflict"}
    character["character_id"] = target_id
    character["world_id"] = "world_touhou"
    character["imported_at"] = datetime.now().isoformat()
    character = ensure_character_fields(character)
    character.pop("_migrated", None)
    tasks = character.get("tasks_export") if isinstance(character.get("tasks_export"), dict) else get_default_tasks()
    save_character(target_id, character)
    save_tasks(target_id, tasks)
    return {"status": "ok", "character_id": target_id, "profile": character.get("profile", {}), "preflight": report}


@router.get("/storage_info")
async def storage_info():
    characters_dir = get_characters_dir()
    files = [path for path in characters_dir.rglob("*") if path.is_file()]
    return {
        "character_count": len([path for path in characters_dir.glob("*.json") if not path.stem.endswith("_tasks")]),
        "file_count": len(files),
        "size_bytes": sum(path.stat().st_size for path in files),
    }


@router.post("/archive_character")
async def archive_character(request: dict):
    character_id = str(request.get("character_id") or "").strip()
    _require_character(character_id)
    characters_dir = get_characters_dir()
    archive_dir = characters_dir / "_archived" / f"{character_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for path in (characters_dir / f"{character_id}.json", characters_dir / f"{character_id}_tasks.json"):
        if path.exists():
            destination = archive_dir / path.name
            path.replace(destination)
            moved.append(destination.name)
    return {"status": "ok", "archived_files": moved}


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
        "narrative_feedback": summarize_rated_samples(character),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("feedback.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr("character_snapshot.json", json.dumps(character, ensure_ascii=False, indent=2))
        archive.writestr("tasks.json", json.dumps(tasks, ensure_ascii=False, indent=2))
        archive.writestr(
            "narrative_evaluation.json",
            json.dumps(
                {
                    "summary": summarize_rated_samples(character),
                    "samples": build_rated_samples(character),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
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
    history[request.message_index]["rated_at"] = datetime.now().isoformat()
    character["narrative_feedback_summary"] = summarize_rated_samples(character)
    save_character(request.character_id, character)
    return {
        "status": "ok",
        "summary": character["narrative_feedback_summary"],
    }
