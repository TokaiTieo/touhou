"""Read-only single-world API for TouHou."""

from fastapi import APIRouter, HTTPException

from backend.config import DEFAULT_WORLD_ID
from backend.world_manager import (
    ensure_worlds_available,
    get_current_world_path,
    get_locations_dir,
    get_npcs_dir,
    get_world_worldview,
    is_world_initialized,
    set_current_world,
)


router = APIRouter()
WORLD_INFO = {
    "id": DEFAULT_WORLD_ID,
    "name": "幻想乡 - 东方Project",
    "description": "东方Project同人自由叙事世界",
}


@router.get("/worlds/list")
async def list_worlds():
    return {"worlds": [WORLD_INFO]}


@router.get("/world/current")
async def current_world():
    ensure_worlds_available()
    return {
        "world_id": DEFAULT_WORLD_ID,
        "world_name": WORLD_INFO["name"],
        "initialized": is_world_initialized(),
        "worldview_preview": get_world_worldview()[:200],
    }


@router.get("/world/status")
async def world_status():
    ensure_worlds_available()
    return {
        "world_id": DEFAULT_WORLD_ID,
        "initialized": is_world_initialized(),
        "locations_exist": (get_locations_dir() / "location_base.json").exists(),
        "npcs_exist": (get_npcs_dir() / "npc_index.json").exists(),
        "timeline_exist": (get_current_world_path() / "timeline.json").exists(),
    }


@router.post("/world/init")
async def initialize_world():
    ensure_worlds_available()
    set_current_world(DEFAULT_WORLD_ID)
    return {"status": "ok", "message": "幻想乡世界数据已就绪", "initialized": is_world_initialized()}


@router.post("/world/select")
async def select_world(request: dict):
    world_id = request.get("world_id") or DEFAULT_WORLD_ID
    if world_id != DEFAULT_WORLD_ID:
        raise HTTPException(status_code=400, detail="正式版仅支持 TouHou 世界")
    set_current_world(DEFAULT_WORLD_ID)
    return {"status": "ok", "world_id": DEFAULT_WORLD_ID}


@router.get("/world/worldview")
async def full_worldview():
    return {"content": get_world_worldview()}
