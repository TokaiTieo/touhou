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
from backend.services.conversation_archive_service import hydrate_history, history_page, history_count, portable_character
from backend.services.character_commands import execute_character_command
from backend.services.incident_service import sync_incident_from_tasks
from backend.services.narrative_evaluation_service import (
    build_rated_samples,
    summarize_rated_samples,
)
from backend.services.progression_service import (
    ensure_progression_profile,
    perform_inventory_action,
    reputation_profile,
)
from backend.services.onboarding_service import (
    advance_onboarding,
    dismiss_onboarding,
    public_onboarding,
)
from backend.services.runtime_diagnostics_service import diagnostics_summary
from backend.services.relationship_service import get_current_relationships
from backend.services.save_health_service import (
    inspect_character_file,
    inspect_character_payload,
    repair_character_payload_types,
)
from backend.services.story_summary_service import rebuild_story_summary
from backend.utils.ai_json import safe_json_loads
from backend.version import DISPLAY_VERSION
from backend.services.storage_paths import safe_identifier, require_identifier, contained_path
from backend.services.save_upgrade_service import write_upgrade_artifacts
from backend.world_manager import (
    create_character_snapshot,
    ensure_character_fields,
    get_characters_dir,
    get_default_tasks,
    list_character_snapshots,
    inspect_character_snapshots,
    load_character,
    load_tasks,
    restore_character_snapshot,
    save_character,
    save_tasks,
    save_turn_bundle,
)

from backend.services.character_commands import serialize_character_access

router = APIRouter()


class CommandRequest(BaseModel):
    operation_id: Optional[str] = None


class AppendConversationRequest(CommandRequest):
    character_id: str
    speaker: str
    content: str
    scene: str
    is_dead: bool = False


class DeleteHistoryRequest(CommandRequest):
    character_id: str
    from_index: Optional[int] = None
    message_id: Optional[str] = None


class RateMessageRequest(CommandRequest):
    character_id: str
    message_index: Optional[int] = None
    message_id: Optional[str] = None
    rating: Optional[str] = None


class RewriteMessageRequest(CommandRequest):
    character_id: str
    message_id: Optional[str] = None
    message_index: Optional[int] = None
    instruction: Optional[str] = None


class RestoreSnapshotRequest(BaseModel):
    character_id: str
    snapshot_id: str
    branch: bool = False
    branch_name: Optional[str] = None


class SpellcardLoadoutRequest(CommandRequest):
    character_id: str
    spellcards: list[str]


class InventoryActionRequest(BaseModel):
    character_id: str
    action: str
    item_name: str
    npc_name: Optional[str] = None
    operation_id: Optional[str] = None


class OnboardingRequest(CommandRequest):
    character_id: str
    action: str


def _require_character(character_id: str):
    character = load_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return character


@router.post("/append_conversation")
async def append_conversation(request: AppendConversationRequest):
    async def change(character, tasks):
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
        rebuild_story_summary(character, tasks)
        return {
            "status": "ok",
            "message_id": message["message_id"],
            "message_index": history_count(character) - 1,
            "rewrite_candidates": [],
        }
    payload = request.model_dump(exclude={"operation_id"})
    return await execute_character_command(request.character_id, request.operation_id,
        {"command": "append_conversation", **payload}, change)


@router.post("/rewrite_message")
async def rewrite_message(request: RewriteMessageRequest):
    async def change(character, tasks):
        """Create a prose-only alternative without replaying game state."""
        history = hydrate_history(character)
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
        return {
            "status": "ok",
            "message_id": target.get("message_id"),
            "message_index": target_index,
            "original": target.get("content", ""),
            "rewrite_candidates": target["rewrite_candidates"],
            "active_candidate": len(target["rewrite_candidates"]) - 1,
            "model_runtime": runtime,
        }
    payload = request.model_dump(exclude={"operation_id"})
    return await execute_character_command(request.character_id, request.operation_id,
        {"command": "rewrite_message", **payload}, change)


@router.post("/delete_history")
async def delete_history(request: DeleteHistoryRequest):
    async def change(character, tasks):
        history = hydrate_history(character)
        index = request.from_index
        if request.message_id:
            index = next((i for i, item in enumerate(history) if item.get("message_id") == request.message_id), -1)
        if index is None or index < 0 or index > len(history):
            raise HTTPException(status_code=400, detail="无效的索引")
        deleted_count = len(history) - index
        character["conversation_history"] = history[:index]
        rebuild_story_summary(character, tasks, force=True)
        return {"status": "ok", "deleted_count": deleted_count}
    payload = request.model_dump(exclude={"operation_id"})
    return await execute_character_command(request.character_id, request.operation_id,
        {"command": "delete_history", **payload}, change)


@router.get("/tasks")
async def get_tasks(character_id: str):
    tasks_data = load_tasks(character_id)
    character = load_character(character_id)
    if character:
        sync_incident_from_tasks(character, tasks_data)
    return {
        "active_tasks": tasks_data.get("active_tasks", []),
        "completed_tasks": tasks_data.get("completed_tasks", []),
    }


@router.post("/add_task")
async def add_task(request: dict):
    async def change(character, tasks):
        character_id = request.get("character_id")
        task_info = request.get("task", {})
        if not character_id or not task_info:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        tasks_data = tasks
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
        return {"status": "ok", "task": new_task}
    payload = {key: value for key, value in request.items() if key != "operation_id"}
    return await execute_character_command(request.get("character_id"), request.get("operation_id"),
        {"command": "add_task", **payload}, change)


@router.post("/delete_task")
async def delete_task(request: dict):
    async def change(character, tasks):
        character_id = request.get("character_id")
        task_id = request.get("task_id")
        if not character_id or not task_id:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        tasks_data = tasks
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
        return {"status": "ok", "message": "任务已删除"}
    payload = {key: value for key, value in request.items() if key != "operation_id"}
    return await execute_character_command(request.get("character_id"), request.get("operation_id"),
        {"command": "delete_task", **payload}, change)


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
    async def change(character, tasks):
        spellcards = list(dict.fromkeys(str(name).strip() for name in request.spellcards if str(name).strip()))
        if len(spellcards) > 6:
            raise HTTPException(status_code=400, detail="符卡栏最多配置 6 张")
        if any(len(name) > 160 for name in spellcards):
            raise HTTPException(status_code=400, detail="符卡名称过长")
        character["spellcard_loadout"] = spellcards
        ensure_progression_profile(character)
        return {"status": "ok", "spellcard_loadout": character["spellcard_loadout"], "exploration_restricted": False}
    payload = request.model_dump(exclude={"operation_id"})
    return await execute_character_command(request.character_id, request.operation_id,
        {"command": "set_spellcard_loadout", **payload}, change)


@router.post("/inventory_action")
async def inventory_action(request: InventoryActionRequest):
    def change(character, tasks):
        try:
            result = perform_inventory_action(character, action=request.action,
                item_name=request.item_name, npc_name=request.npc_name or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "result": result, "inventory": character.get("inventory_state", {}),
                "relationships": character.get("relationships_map", {}), "player_state": character.get("player_state", {})}
    return await execute_character_command(request.character_id, request.operation_id,
        request.model_dump(exclude={"operation_id"}), change)


@router.post("/onboarding")
async def update_onboarding(request: OnboardingRequest):
    async def change(character, tasks):
        if request.action == "dismiss":
            state = dismiss_onboarding(character)
        elif request.action in ("turn", "dialogue", "journal"):
            state = advance_onboarding(character, request.action)
        else:
            raise HTTPException(status_code=400, detail="不支持的引导操作")
        return {"status": "ok", "onboarding": public_onboarding(character), "exploration_restricted": False}
    payload = request.model_dump(exclude={"operation_id"})
    return await execute_character_command(request.character_id, request.operation_id,
        {"command": "update_onboarding", **payload}, change)


@router.get("/character_journal")
async def get_character_journal(character_id: str, view: str = "full"):
    character = _require_character(character_id)
    ensure_progression_profile(character)
    result = {
        "profile": character.get("profile", {}),
        "status": character.get("status", {}),
        "player_state": character.get("player_state", {}),
        "resources": character.get("resources", {}),
        "inventory": character.get("inventory_state", {}),
        "reputation": character.get("reputation", {}),
        "reputation_profile": reputation_profile(character),
        "reputation_history": character.get("reputation_history", []),
        "relationships": character.get("relationships_map", {}),
        "relationship_progress": character.get("relationship_progress", {}),
        "relationship_boundaries": character.get("relationship_boundaries", {}),
        "story_summary": character.get("story_summary", {}),
        "story_director": character.get("story_director", {}),
        "campaign_state": character.get("campaign_state", {}),
        "incident_history": character.get("incident_history", []),
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
        "npc_agency": character.get("npc_agency", {}),
        "memory_maintenance": character.get("memory_maintenance", {}),
        "turn_diagnostics": diagnostics_summary(character),
        "onboarding": public_onboarding(character),
        "narrative_feedback": summarize_rated_samples(character),
        "gm_mode": character.get("gm_mode", False),
    }
    if view == "summary":
        for key in ("npc_memories", "npc_memory_summaries", "turn_diagnostics", "memory_maintenance", "npc_agency", "world_state"):
            result.pop(key, None)
        for key in ("open_events", "spellcard_history", "consequence_log", "reputation_history", "incident_history"):
            result[key] = result[key][-20:]
    return result


@router.get("/snapshots")
async def get_character_snapshots(character_id: str):
    character = _require_character(character_id)
    snapshots = list_character_snapshots(character_id)
    if not snapshots:
        create_character_snapshot(character_id, character, label="旧存档初始节点", force=True)
        snapshots = list_character_snapshots(character_id)
    return {"snapshots": snapshots}


@router.post("/snapshots/restore")
@serialize_character_access
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
    report = inspect_character_file(contained_path(characters_dir, f"{require_identifier(character_id)}.json"))
    snapshots = inspect_character_snapshots(character_id)
    report["snapshot_count"] = len(snapshots)
    report["recoverable_snapshot_count"] = sum(item["recoverable"] for item in snapshots)
    report["snapshot_health"] = snapshots
    report["repairable"] = not report.get("read_only", False) and bool(report.get("repairable") or report["recoverable_snapshot_count"])
    report.pop("payload", None)
    return report


@router.post("/save_health/repair")
@serialize_character_access
async def repair_save(request: dict):
    character_id = str(request.get("character_id") or "").strip()
    if not character_id:
        raise HTTPException(status_code=400, detail="缺少 character_id")
    characters_dir = get_characters_dir()
    report = inspect_character_file(contained_path(characters_dir, f"{require_identifier(character_id)}.json"))
    if report.get("read_only"):
        raise HTTPException(409, "请使用更新版本的程序读取此存档；原文件未修改")
    if report.get("status") == "critical":
        snapshots = [item for item in inspect_character_snapshots(character_id) if item["recoverable"]]
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
    exported = portable_character(character)
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
    if character.get("conversation_archive", {}).get("chunks"):
        raise HTTPException(422, "该文件引用外部剧情档案，请在原游戏中使用导出角色后重新导入")
    characters_dir = get_characters_dir()
    source_id = str(character.get("character_id") or "")
    target_id = source_id if safe_identifier(source_id) else str(uuid.uuid4())
    reason = "invalid_id" if target_id != source_id else None
    if contained_path(characters_dir, f"{target_id}.json").exists() or contained_path(characters_dir, f"{target_id}_tasks.json").exists():
        target_id = str(uuid.uuid4())
        reason = "id_conflict"
    if reason:
        if not isinstance(character.get("import_origin_history", []), list):
            character.setdefault("recovered_invalid_fields", {})["import_origin_history"] = character["import_origin_history"]
            character["import_origin_history"] = []
        character.setdefault("import_origin_history", []).append({"character_id": source_id, "reason": reason})
        character.setdefault("import_origin", {"character_id": source_id, "reason": reason})
    character["character_id"] = target_id
    character["world_id"] = "world_touhou"
    character["imported_at"] = datetime.now().isoformat()
    character = ensure_character_fields(repair_character_payload_types(character)["payload"])
    character.pop("_migrated", None)
    tasks = character.get("tasks_export") if isinstance(character.get("tasks_export"), dict) else get_default_tasks()
    write_upgrade_artifacts(characters_dir, target_id, payload, character)
    save_turn_bundle(target_id, character, tasks, expected_character_revision=0, expected_tasks_revision=0)
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
@serialize_character_access
async def archive_character(request: dict):
    character_id = str(request.get("character_id") or "").strip()
    _require_character(character_id)
    characters_dir = get_characters_dir()
    archive_dir = contained_path(characters_dir, "_archived", f"{character_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for path in (contained_path(characters_dir, f"{character_id}.json"), contained_path(characters_dir, f"{character_id}_tasks.json")):
        if path.exists():
            destination = archive_dir / path.name
            path.replace(destination)
            moved.append(destination.name)
    return {"status": "ok", "archived_files": moved}


@router.get("/npc_memories")
async def get_npc_memories(character_id: str, npc_name: Optional[str] = None, offset: int = 0, limit: Optional[int] = None):
    character = _require_character(character_id)
    memories = character.get("npc_memories", {})
    summaries = character.get("npc_memory_summaries", {})
    if npc_name:
        from backend.services.npc_identity_service import canonical_npc_name
        npc_name = canonical_npc_name(npc_name)
        items = memories.get(npc_name, [])
        start = max(0, offset)
        count = len(items) if limit is None else max(1, min(200, limit))
        return {
            "npc_name": npc_name,
            "summary": summaries.get(npc_name, ""),
            "memories": list(reversed(items))[start:start + count],
            "total": len(items), "offset": start, "has_more": start + count < len(items),
        }
    return {"memories": memories, "summaries": summaries}


@router.get("/conversation_history")
async def conversation_page(character_id: str, before_id: Optional[str] = None, limit: int = 80, query: str = ""):
    character = _require_character(character_id)
    try:
        return history_page(character, before_id, limit, query)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/export_feedback")
async def export_feedback(character_id: str):
    character = portable_character(_require_character(character_id))
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
    async def change(character, tasks):
        character_id = request.get("character_id")
        if not character_id:
            raise HTTPException(status_code=400, detail="缺少 character_id")
        character["last_played"] = datetime.now().isoformat()
        return {"status": "ok", "message": "会话已结束，数据已保存"}
    payload = {key: value for key, value in request.items() if key != "operation_id"}
    return await execute_character_command(request.get("character_id"), request.get("operation_id"),
        {"command": "end_session", **payload}, change)


@router.post("/rate_message")
async def rate_message(request: RateMessageRequest):
    async def change(character, tasks):
        history = hydrate_history(character)
        index = request.message_index
        if request.message_id:
            index = next((i for i, item in enumerate(history) if item.get("message_id") == request.message_id), -1)
        if index is None or index < 0 or index >= len(history):
            raise HTTPException(status_code=400, detail="消息索引无效")
        history[index]["rating"] = request.rating
        history[index]["rated_at"] = datetime.now().isoformat()
        character["narrative_feedback_summary"] = summarize_rated_samples(character)
        return {
            "status": "ok",
            "summary": character["narrative_feedback_summary"],
        }
    payload = request.model_dump(exclude={"operation_id"})
    return await execute_character_command(request.character_id, request.operation_id,
        {"command": "rate_message", **payload}, change)
