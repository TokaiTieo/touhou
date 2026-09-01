"""Producer-mode API isolated from ordinary player turn routes."""

import io
import json
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.config import DATA_DIR, DEFAULT_WORLD_ID, WORLDS_DIR
from backend.world_manager import load_character, save_character
from backend.services.content_validation_service import (
    list_editable_content,
    read_editable_content,
    save_editable_content,
    list_content_backups,
    restore_content_backup,
    validate_editable_content,
)
from backend.services.relationship_service import update_relationships
from backend.services import npc_memory_service as memory_runtime
from backend.services.turn_coordinator import turn_coordinator
from backend.services.turn_workflow import (
    get_checkpoint_metrics,
    get_workflow_diagnostic,
    workflow_enabled,
)
from backend.services.live_narrative_evaluation_service import run_live_evaluation
from backend.services.memory_maintenance_service import maintain_memories
from backend.services.runtime_diagnostics_service import (
    build_diagnostic_bundle,
    diagnostics_summary,
)
from backend.version import DISPLAY_VERSION
from backend.world_manager import load_tasks


router = APIRouter()


def _character(character_id: str):
    character = load_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    if not character.get("gm_mode", False):
        raise HTTPException(status_code=403, detail="需要高权限模式")
    return character


def _number(value, default=0):
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return default


@router.get("/producer_console/state")
async def state(character_id: str):
    character = _character(character_id)
    checkpoint_metrics = await get_checkpoint_metrics()
    return {
        "status": character.get("status", {}),
        "time": character.get("time", {}),
        "player_state": character.get("player_state", {}),
        "resources": character.get("resources", {}),
        "relationships": character.get("relationships_map", {}),
        "relationship_progress": character.get("relationship_progress", {}),
        "npc_memories": character.get("npc_memories", {}),
        "npc_memory_summaries": character.get("npc_memory_summaries", {}),
        "open_events": character.get("open_events", []),
        "current_goals": character.get("current_goals", []),
        "usage_stats": character.get("usage_stats", {}),
        "model_runtime": character.get("model_runtime", {}),
        "debug_last_ai": character.get("debug_last_ai", {}),
        "turn_runtime": {
            "langgraph_enabled": workflow_enabled(),
            "workflow": get_workflow_diagnostic(),
            "checkpoints": checkpoint_metrics,
            "recent_turns": turn_coordinator.recent_statuses(character_id),
        },
        "turn_diagnostics": diagnostics_summary(character),
        "memory_maintenance": character.get("memory_maintenance", {}),
    }


@router.get("/producer_console/content")
async def get_content(character_id: str, path: str = ""):
    _character(character_id)
    world_root = WORLDS_DIR / DEFAULT_WORLD_ID
    if not path:
        return {"files": list_editable_content(world_root)}
    try:
        return read_editable_content(world_root, path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/producer_console/content/validate")
async def validate_content(request: dict):
    _character(request.get("character_id"))
    try:
        result = validate_editable_content(
            WORLDS_DIR / DEFAULT_WORLD_ID, request.get("path"), request.get("content")
        )
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/producer_console/content/save")
async def save_content(request: dict):
    _character(request.get("character_id"))
    try:
        result = save_editable_content(
            WORLDS_DIR / DEFAULT_WORLD_ID,
            DATA_DIR / "content_backups" / DEFAULT_WORLD_ID,
            request.get("path"),
            request.get("content"),
        )
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("saved"):
        raise HTTPException(status_code=422, detail={
            "message": "内容校验未通过，未写入文件",
            "errors": result.get("validation", {}).get("errors", []),
        })
    return result


@router.get("/producer_console/content/backups")
async def content_backups(character_id: str, path: str):
    _character(character_id)
    return {
        "backups": list_content_backups(
            DATA_DIR / "content_backups" / DEFAULT_WORLD_ID, path
        )
    }


@router.post("/producer_console/content/restore_backup")
async def content_restore_backup(request: dict):
    _character(request.get("character_id"))
    try:
        result = restore_content_backup(
            WORLDS_DIR / DEFAULT_WORLD_ID,
            DATA_DIR / "content_backups" / DEFAULT_WORLD_ID,
            request.get("path"),
            request.get("backup_id"),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("restored"):
        raise HTTPException(status_code=422, detail=result)
    return result


@router.post("/producer_console/evaluation/run")
async def run_evaluation(request: dict):
    character = _character(request.get("character_id"))
    report = await run_live_evaluation(character)
    path = DATA_DIR / "evaluations" / f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


@router.post("/producer_console/memory/maintain")
async def maintain_memory(request: dict):
    character_id = request.get("character_id")
    character = _character(character_id)
    report = maintain_memories(character, force=True)
    save_character(character_id, character)
    return {"status": "ok", "report": report}


@router.get("/producer_console/diagnostic_bundle")
async def diagnostic_bundle(character_id: str):
    character = _character(character_id)
    payload = build_diagnostic_bundle(character, load_tasks(character_id), DISPLAY_VERSION)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr(
            "README.txt",
            "TouHou privacy-safe diagnostics. API keys, prompts, responses, conversations and NPC memory bodies are excluded.\n",
        )
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="touhou_diagnostics.zip"'},
    )


@router.post("/producer_console/restore")
async def restore(request: dict):
    character = _character(request.get("character_id"))
    character.setdefault("status", {}).update({"is_dead": False, "death_cause": None, "health": 999999})
    character["player_state"] = {
        "灵力": 999999, "结界共鸣": 999999, "弹幕熟练度": 999999,
        "调查熟练度": 999999, "交涉熟练度": 999999, "生存熟练度": 999999,
        "疲劳": 0, "受伤": 0, "异变污染": 0, "高权限": "最高",
        "命运干预": "无限", "对手压制": "绝对",
    }
    resources = character.setdefault("resources", {})
    resources["灵石"] = 999999
    resources["道具"] = list(set(resources.get("道具", [])) | {"高权限终端", "命运改写笔", "无限符卡档案"})
    save_character(request.get("character_id"), character)
    return {"status": "ok", "character": character}


@router.post("/producer_console/teleport")
async def teleport(request: dict):
    character_id, scene = request.get("character_id"), str(request.get("scene") or "").strip()
    character = _character(character_id)
    if not scene:
        raise HTTPException(status_code=400, detail="缺少地点名称")
    character.setdefault("status", {})["current_scene"] = scene
    character.setdefault("unlocked_locations", {}).setdefault(scene, {"status": "entered", "first_visited": datetime.now().isoformat()})
    save_character(character_id, character)
    return {"status": "ok", "current_scene": scene}


@router.post("/producer_console/set_relationship")
async def set_relationship(request: dict):
    character_id = request.get("character_id")
    character = _character(character_id)
    npc_name = str(request.get("npc_name") or "").strip()
    attitude = str(request.get("attitude") or "").strip()
    if not npc_name or not attitude:
        raise HTTPException(status_code=400, detail="缺少 NPC 名称或关系")
    relation = f"{npc_name}:{attitude}({str(request.get('reason') or '高权限指令').strip()})"
    update_relationships(character, relation, character.get("time", {}).get("current_hour", 0))
    memory_runtime.record_npc_memories(character, [{
        "npc_name": npc_name, "summary": f"制作人控制台改写关系：{relation}",
        "tags": ["关系", "制作人控制台"], "importance": 8,
    }], "producer_relationship")
    save_character(character_id, character)
    return {"status": "ok", "relationships": character.get("relationships_map", {})}


@router.post("/producer_console/upsert_npc_memory")
async def upsert_memory(request: dict):
    character_id = request.get("character_id")
    character = _character(character_id)
    npc_name = str(request.get("npc_name") or "").strip()
    summary = str(request.get("summary") or "").strip()
    memory_id = str(request.get("memory_id") or "").strip()
    tags = request.get("tags", [])
    if not npc_name or not summary:
        raise HTTPException(status_code=400, detail="缺少 NPC 名称或记忆内容")
    if isinstance(tags, str):
        tags = [item.strip() for item in re.split(r"[、,，]", tags) if item.strip()]
    bucket = character.setdefault("npc_memories", {}).setdefault(npc_name, [])
    item = next((entry for entry in bucket if str(entry.get("id")) == memory_id), None) if memory_id else None
    if item:
        item.update({
            "summary": summary[:300], "tags": tags,
            "importance": memory_runtime.estimate_memory_importance(summary, tags, "producer_console", request.get("importance")),
            "emotion": memory_runtime.infer_memory_emotion(summary, tags), "updated_at": datetime.now().isoformat(),
        })
    else:
        memory_runtime.record_npc_memories(character, [{
            "npc_name": npc_name, "summary": summary, "tags": tags,
            "importance": request.get("importance"), "source": "producer_console",
        }], "producer_console")
    save_character(character_id, character)
    return {"status": "ok", "npc_name": npc_name, "memories": character["npc_memories"][npc_name], "summary": character.get("npc_memory_summaries", {}).get(npc_name, "")}


@router.post("/producer_console/delete_npc_memory")
async def delete_memory(request: dict):
    character_id = request.get("character_id")
    character = _character(character_id)
    npc_name, memory_id = str(request.get("npc_name") or "").strip(), str(request.get("memory_id") or "").strip()
    if not npc_name or not memory_id:
        raise HTTPException(status_code=400, detail="缺少 NPC 名称或记忆 ID")
    bucket = character.setdefault("npc_memories", {}).setdefault(npc_name, [])
    character["npc_memories"][npc_name] = [item for item in bucket if str(item.get("id")) != memory_id]
    save_character(character_id, character)
    return {"status": "ok", "deleted": len(bucket) - len(character["npc_memories"][npc_name]), "memories": character["npc_memories"][npc_name]}


@router.post("/producer_console/compress_npc_memory")
async def compress_memory(request: dict):
    character_id, npc_name = request.get("character_id"), str(request.get("npc_name") or "").strip()
    character = _character(character_id)
    if not npc_name:
        raise HTTPException(status_code=400, detail="缺少 NPC 名称")
    changed = memory_runtime.compress_npc_memory_bucket(character, npc_name, keep_recent=12, force=True)
    save_character(character_id, character)
    return {"status": "ok", "changed": changed, "summary": character.get("npc_memory_summaries", {}).get(npc_name, ""), "memories": character.get("npc_memories", {}).get(npc_name, [])}


@router.post("/producer_console/set_player_state")
async def set_player_state(request: dict):
    character_id = request.get("character_id")
    character = _character(character_id)
    updates = request.get("updates", {})
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="updates 必须是对象")
    character.setdefault("player_state", {}).update({str(key).strip(): value for key, value in updates.items() if str(key).strip()})
    save_character(character_id, character)
    return {"status": "ok", "player_state": character["player_state"]}


@router.post("/producer_console/set_resource")
async def set_resource(request: dict):
    character_id, resource = request.get("character_id"), str(request.get("resource") or "").strip()
    character = _character(character_id)
    if not resource:
        raise HTTPException(status_code=400, detail="缺少资源名")
    character.setdefault("resources", {})[resource] = request.get("value")
    save_character(character_id, character)
    return {"status": "ok", "resources": character["resources"]}


@router.post("/producer_console/set_anomaly")
async def set_anomaly(request: dict):
    character_id = request.get("character_id")
    character = _character(character_id)
    time_info = character.setdefault("time", {})
    if request.get("chapter_time_remaining") is not None:
        time_info["chapter_time_remaining"] = max(0, _number(request["chapter_time_remaining"], 72))
    if request.get("chapter_node_name"):
        time_info["chapter_node_name"] = str(request["chapter_node_name"]).strip()
    save_character(character_id, character)
    return {"status": "ok", "time": time_info}


@router.post("/producer_console/create_event")
async def create_event(request: dict):
    character_id, event = request.get("character_id"), request.get("event", {})
    character = _character(character_id)
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="event 必须是对象")
    memory_runtime.record_open_event(character, event, character.get("status", {}).get("current_scene", "未知地点"))
    save_character(character_id, character)
    return {"status": "ok", "open_events": character.get("open_events", [])}
