# backend/routes/location.py
# 地点管理相关路由

import logging
from fastapi import APIRouter, HTTPException
from backend.world_manager import get_locations_dir, get_current_world_path
from backend.location_manager import get_location_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/locations/tree")  # 移除 /ghost 前缀
async def get_locations_tree(character_id: str, chapter_index: int = 1):
    """获取地点树。所有地点自由开放，unlocked_locations 仅作为到访记录。"""
    from backend.routes.character import load_character
    
    character = load_character(character_id)
    unlocked_locations = character.get("unlocked_locations", {}) if character else {}
    
    unlocked_names = list(unlocked_locations.keys())
    print(f"已到访地点名称: {unlocked_names}")
    
    lm = get_location_manager(get_locations_dir())
    all_locations = lm.get_all_locations()
    
    location_info = {}
    for loc_id, loc in all_locations.items():
        if hasattr(loc, 'name'):
            name = loc.name
            loc_type = loc.type
            parent = loc.parent
            icon = loc.icon
            description = loc.description
        else:
            name = loc.get('name')
            loc_type = loc.get('type')
            parent = loc.get('parent')
            icon = loc.get('icon', '📍')
            description = loc.get('description', '')
        
        location_info[name] = {
            "id": loc_id,
            "type": loc_type,
            "parent": parent,
            "icon": icon,
            "description": description,
            "danger_level": getattr(loc, "metadata", {}).get("danger_level", "未知") if hasattr(loc, "metadata") else loc.get("danger_level", "未知"),
            "danger_note": getattr(loc, "metadata", {}).get("danger_note", "") if hasattr(loc, "metadata") else loc.get("danger_note", ""),
            "main_rewards": getattr(loc, "metadata", {}).get("main_rewards", "") if hasattr(loc, "metadata") else loc.get("main_rewards", "")
        }
    
    regions = {}
    for name, info in location_info.items():
        if info["type"] == "region":
            regions[name] = info
    
    if not regions:
        regions = {"可探索区域": {"id": "default", "icon": "📍"}}
    
    tree = []
    for region_name, region_info in regions.items():
        region_tree = {
            "id": region_info.get("id"),
            "name": region_name,
            "icon": region_info.get("icon", "📁"),
            "locations": []
        }
        
        for loc_name, loc_info in location_info.items():
            if loc_info["type"] != "scene":
                continue
            
            parent_name = loc_info.get("parent")
            if parent_name == region_name or (parent_name and parent_name == region_info.get("id")):
                visit_record = unlocked_locations.get(loc_name, {})
                region_tree["locations"].append({
                    "id": loc_info["id"],
                    "name": loc_name,
                    "description": loc_info.get("description", ""),
                    "icon": loc_info.get("icon", "📍"),
                    "danger_level": loc_info.get("danger_level", "未知"),
                    "danger_note": loc_info.get("danger_note", ""),
                    "main_rewards": loc_info.get("main_rewards", ""),
                    "visited": loc_name in unlocked_locations,
                    "unlock_status": visit_record.get("status", "open")
                })
        
        if region_tree["locations"]:
            tree.append(region_tree)
    
    print(f"📍 返回地点树: {len(tree)} 个区域")
    return {"tree": tree}


@router.get("/locations/all")  # 移除 /ghost 前缀
async def get_all_locations_endpoint():
    """获取所有地点（用于前端构建地点树）"""
    lm = get_location_manager(get_locations_dir())
    all_locations = lm.get_all_locations()
    
    regions = []
    scenes = []
    
    for loc_id, loc in all_locations.items():
        if hasattr(loc, 'type'):
            loc_type = loc.type
            name = loc.name
            parent = loc.parent
            icon = loc.icon
            description = loc.description
        else:
            loc_type = loc.get('type')
            name = loc.get('name')
            parent = loc.get('parent')
            icon = loc.get('icon', '📍')
            description = loc.get('description', '')
        
        if loc_type == 'region':
            regions.append({
                "id": loc_id,
                "name": name,
                "icon": icon,
                "description": description
            })
        else:
            scenes.append({
                "id": loc_id,
                "name": name,
                "parent": parent,
                "icon": icon,
                "description": description,
                "danger_level": loc.metadata.get("danger_level", "未知") if hasattr(loc, "metadata") else loc.get("danger_level", "未知"),
                "danger_note": loc.metadata.get("danger_note", "") if hasattr(loc, "metadata") else loc.get("danger_note", ""),
                "main_rewards": loc.metadata.get("main_rewards", "") if hasattr(loc, "metadata") else loc.get("main_rewards", "")
            })
    
    return {"regions": regions, "locations": scenes}


@router.get("/locations/by_name/{location_name}")  # 移除 /ghost 前缀
async def get_location_by_name(location_name: str):
    """根据名称获取地点信息"""
    print(f"🔍 获取地点信息: {location_name}")
    
    lm = get_location_manager(get_locations_dir())
    location = lm.get_location_by_name(location_name)
    if location:
        if hasattr(location, 'id'):
            return {
                "id": location.id,
                "name": location.name,
                "description": location.description,
                "icon": location.icon,
                "parent": location.parent,
                "danger_level": location.metadata.get("danger_level", "未知"),
                "danger_note": location.metadata.get("danger_note", ""),
                "main_rewards": location.metadata.get("main_rewards", "")
            }
        return {
            "id": location.get("id"),
            "name": location.get("name"),
            "description": location.get("description", ""),
            "icon": location.get("icon", "📍"),
            "parent": location.get("parent"),
            "danger_level": location.get("danger_level", "未知"),
            "danger_note": location.get("danger_note", ""),
            "main_rewards": location.get("main_rewards", "")
        }
    
    return {
        "id": location_name,
        "name": location_name,
        "description": f"在{location_name}发现的地点",
        "icon": "📍",
        "parent": None
    }


@router.get("/npcs/by_scene/{scene_name}")  # 移除 /ghost 前缀
async def get_npcs_by_scene(scene_name: str, character_id: str = None):
    """获取指定场景的 NPC 列表"""
    logger.debug("Loading NPCs for scene %s", scene_name)
    
    lm = get_location_manager(get_locations_dir())
    location = lm.get_location_by_name(scene_name)
    location_id = location.id if location and hasattr(location, 'id') else scene_name
    candidate_location_ids = {scene_name, location_id}
    all_locations = lm.get_all_locations()
    for loc_id, loc in all_locations.items():
        loc_name = loc.name if hasattr(loc, 'name') else loc.get("name")
        loc_parent = loc.parent if hasattr(loc, 'parent') else loc.get("parent")
        loc_type = loc.type if hasattr(loc, 'type') else loc.get("type")
        if loc_name == scene_name or loc_id == scene_name:
            candidate_location_ids.add(loc_id)
            candidate_location_ids.add(loc_name)
            if loc_type == "region":
                for child_id, child in all_locations.items():
                    child_parent = child.parent if hasattr(child, 'parent') else child.get("parent")
                    if child_parent == loc_id:
                        candidate_location_ids.add(child_id)
        if loc_parent == scene_name:
            candidate_location_ids.add(loc_id)
    
    from backend.world_manager import get_npcs_dir
    import json
    
    npc_index_path = get_npcs_dir() / "npc_index.json"
    npcs = []
    
    if npc_index_path.exists():
        try:
            with open(npc_index_path, 'r', encoding='utf-8-sig') as f:
                npc_index = json.load(f)
            
            if not isinstance(npc_index, dict):
                logger.warning("NPC index is not an object")
                return {"npcs": []}
            
            npcs_list = npc_index.get("npcs", [])
            if not isinstance(npcs_list, list):
                logger.warning("NPC index field 'npcs' is not a list")
                return {"npcs": []}
            
            for idx, npc in enumerate(npcs_list):
                try:
                    if not isinstance(npc, dict):
                        logger.debug("Skipping malformed NPC at index %s", idx)
                        continue
                    
                    npc_loc_id = npc.get("location_id")
                    # 尝试多种匹配方式：精确匹配、场景名称匹配、区域名称匹配
                    match = False
                    if npc_loc_id in candidate_location_ids:
                        match = True
                    elif location and hasattr(location, 'parent') and npc_loc_id == location.parent:
                        match = True
                    
                    if match:
                        npcs.append(npc)
                except Exception as e:
                    logger.warning("Failed to process NPC at index %s: %s", idx, type(e).__name__)
            
            if character_id:
                from backend.world_manager import load_character
                from backend.services.npc_schedule_service import place_scheduled_npcs
                character = load_character(character_id)
                hour = (character or {}).get("time", {}).get("current_hour", 8)
                npcs = place_scheduled_npcs(npcs_list, scene_name, hour, npcs, character)
            npcs.sort(key=lambda n: n.get("profile", {}).get("appearance_weight", 0), reverse=True)
            logger.debug("Matched %s NPCs for %s", len(npcs), scene_name)
        except json.JSONDecodeError as e:
            logger.error("NPC index JSON is invalid")
            return {"npcs": []}
        except Exception as e:
            logger.exception("Failed to load NPC index")
            return {"npcs": []}
    else:
        logger.warning("NPC index does not exist: %s", npc_index_path)
    
    return {"npcs": npcs}


@router.post("/update_scene")  # 移除 /ghost 前缀
async def update_scene(request: dict):
    """更新角色场景"""
    from backend.routes.character import load_character, save_character
    from datetime import datetime
    
    character_id = request.get("character_id")
    scene = request.get("scene")
    
    if not character_id or not scene:
        raise HTTPException(status_code=400, detail="需要提供 character_id 和 scene")
    
    character = load_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    old_scene = character["status"].get("current_scene")
    character["status"]["current_scene"] = scene
    character["last_played"] = datetime.now().isoformat()
    
    unlocked = character.setdefault("unlocked_locations", {})
    if scene not in unlocked:
        unlocked[scene] = {
            "status": "entered",
            "first_visited": datetime.now().isoformat()
        }
    
    save_character(character_id, character)
    
    return {"status": "ok", "current_scene": scene, "old_scene": old_scene}
