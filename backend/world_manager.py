# backend/world_manager.py

import os
import sys
import json
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

# ========== 配置 ==========
# 从 config 导入路径配置，确保用户数据保存在持久化目录
from backend.config import BASE_DIR, WORLDS_DIR, DATA_DIR, DEFAULT_WORLD_ID as CONFIG_DEFAULT_WORLD_ID
from backend.services.save_migrations import LATEST_SAVE_VERSION, migrate_save_schema
from backend.services.save_upgrade_service import write_upgrade_artifacts
from backend.services.snapshot_service import (
    create_snapshot,
    list_snapshots,
    load_snapshot,
    prepare_restore_payload,
)

WORLDS_INDEX_FILE = WORLDS_DIR / "worlds_index.json"

# 默认世界 ID
DEFAULT_WORLD_ID = CONFIG_DEFAULT_WORLD_ID
CURRENT_SAVE_VERSION = LATEST_SAVE_VERSION
MAX_CHARACTER_SNAPSHOTS = 40
_CHARACTER_LOCKS = {}
_CHARACTER_LOCKS_GUARD = threading.Lock()


class StaleTurnError(RuntimeError):
    """Raised when a turn tries to commit over newer persisted state."""


def _lock_key(character_id: str, world_id: str = None) -> str:
    return f"{world_id or DEFAULT_WORLD_ID}:{character_id}"


def get_character_lock(character_id: str, world_id: str = None):
    key = _lock_key(character_id, world_id)
    with _CHARACTER_LOCKS_GUARD:
        return _CHARACTER_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def character_write_lock(character_id: str, world_id: str = None):
    lock = get_character_lock(character_id, world_id)
    with lock:
        yield


def _atomic_json_write(path: Path, data: Any):
    """Write JSON through a sibling temporary file, then atomically replace it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _apply_world_changes(world_changes: Dict, world_id: str = None) -> None:
    """Apply idempotent world-file additions recorded in a turn journal."""
    if not isinstance(world_changes, dict):
        return
    additions = world_changes.get("dynamic_locations")
    if not isinstance(additions, list) or not additions:
        return
    dynamic_path = get_locations_dir(world_id) / "location_dynamic.json"
    data = {
        "version": 1,
        "last_updated": datetime.now().isoformat(),
        "regions": [],
        "locations": [],
    }
    if dynamic_path.exists():
        try:
            with open(dynamic_path, "r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                data.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    locations = data.setdefault("locations", [])
    known_ids = {
        str(item.get("id"))
        for item in locations
        if isinstance(item, dict) and item.get("id")
    }
    known_names = {
        str(item.get("name"))
        for item in locations
        if isinstance(item, dict) and item.get("name")
    }
    changed = False
    for addition in additions:
        if not isinstance(addition, dict):
            continue
        identity = str(addition.get("id") or "")
        name = str(addition.get("name") or "")
        if not identity or not name or identity in known_ids or name in known_names:
            continue
        locations.append(addition)
        known_ids.add(identity)
        known_names.add(name)
        changed = True
    if changed:
        data["last_updated"] = datetime.now().isoformat()
        _atomic_json_write(dynamic_path, data)


def get_character_snapshots_dir(character_id: str, world_id: str = None) -> Path:
    path = get_characters_dir(world_id) / "_snapshots" / character_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_character_snapshot(character_id: str, data: Dict, world_id: str = None, label: str = None, force: bool = False):
    snapshots_dir = get_character_snapshots_dir(character_id, world_id)
    tasks_path = get_tasks_path(character_id, world_id)
    tasks = get_default_tasks()
    if tasks_path.exists():
        try:
            with open(tasks_path, "r", encoding="utf-8") as handle:
                tasks = json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass
    return create_snapshot(
        character_id,
        data,
        snapshots_dir,
        tasks,
        _atomic_json_write,
        save_version=CURRENT_SAVE_VERSION,
        max_snapshots=MAX_CHARACTER_SNAPSHOTS,
        label=label,
        force=force,
    )


def list_character_snapshots(character_id: str, world_id: str = None) -> List[Dict]:
    return list_snapshots(get_character_snapshots_dir(character_id, world_id))


def restore_character_snapshot(character_id: str, snapshot_id: str, branch: bool = False, branch_name: str = None, world_id: str = None) -> Dict:
    payload = load_snapshot(get_character_snapshots_dir(character_id, world_id), snapshot_id)
    restored = prepare_restore_payload(
        character_id,
        payload,
        ensure_character_fields,
        get_default_tasks,
        branch=branch,
        branch_name=branch_name,
        snapshot_id=snapshot_id,
    )
    target_id = restored["target_id"]
    character = restored["character"]
    tasks = restored["tasks"]
    _atomic_json_write(get_characters_dir(world_id) / f"{target_id}.json", character)
    _atomic_json_write(get_tasks_path(target_id, world_id), tasks)
    create_character_snapshot(target_id, character, world_id, label="分支起点" if branch else "恢复点", force=True)
    return {"character_id": target_id, "branched": branch, "profile": character.get("profile", {})}


# ========== 世界数据结构 ==========

def _merge_bundled_content(relative_path: Path, collection_key: str, item_key: str = "id") -> bool:
    """Add official content missing from an existing install without replacing edits."""
    bundled_file = BASE_DIR / "worlds" / relative_path
    target_file = WORLDS_DIR / relative_path
    if not bundled_file.exists() or bundled_file.resolve() == target_file.resolve():
        return False
    if not target_file.exists():
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_file, target_file)
        return True
    try:
        bundled = json.loads(bundled_file.read_text(encoding="utf-8-sig"))
        target = json.loads(target_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return False
    bundled_version = int(bundled.get("content_version", bundled.get("version", 1)) or 1)
    target_version = int(target.get("content_version", target.get("version", 1)) or 1)
    if target_version > bundled_version:
        return False

    source_collection = bundled.get(collection_key)
    target_collection = target.get(collection_key)
    changed = False
    if isinstance(source_collection, list):
        if not isinstance(target_collection, list):
            target_collection = []
            target[collection_key] = target_collection
        known = {
            str(item.get(item_key)) for item in target_collection
            if isinstance(item, dict) and item.get(item_key) is not None
        }
        for item in source_collection:
            identity = str(item.get(item_key)) if isinstance(item, dict) else ""
            if identity and identity not in known:
                target_collection.append(item)
                known.add(identity)
                changed = True
    elif isinstance(source_collection, dict):
        if not isinstance(target_collection, dict):
            target_collection = {}
            target[collection_key] = target_collection
        for key, value in source_collection.items():
            if key not in target_collection:
                target_collection[key] = value
                changed = True
    if target_version != bundled_version:
        target["content_version"] = bundled_version
        changed = True
    if changed:
        _atomic_json_write(target_file, target)
    return changed


def ensure_worlds_available():
    """Initialize bundled world data and add new content files to existing installs."""
    bundled_worlds = BASE_DIR / "worlds"
    required_files = [
        WORLDS_DIR / "worlds_index.json",
        WORLDS_DIR / DEFAULT_WORLD_ID / "locations" / "location_base.json",
        WORLDS_DIR / DEFAULT_WORLD_ID / "npcs" / "npc_index.json",
        WORLDS_DIR / DEFAULT_WORLD_ID / "timeline.json",
        WORLDS_DIR / DEFAULT_WORLD_ID / "worldview.txt",
    ]
    missing_required = any(not path.exists() for path in required_files)

    if missing_required and bundled_worlds.exists() and bundled_worlds.resolve() != WORLDS_DIR.resolve():
        WORLDS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled_worlds, WORLDS_DIR, dirs_exist_ok=True)
        print(f"📦 已初始化世界数据: {WORLDS_DIR}")

    # Content packs are merged by stable identity. Existing entries and mod fields
    # win; only missing official entries are appended during an upgrade.
    _merge_bundled_content(Path(DEFAULT_WORLD_ID) / "world_info.json", "entries")
    _merge_bundled_content(Path(DEFAULT_WORLD_ID) / "incidents.json", "incidents")
    _merge_bundled_content(Path(DEFAULT_WORLD_ID) / "npc_schedules.json", "schedules", "name")
    _merge_bundled_content(Path(DEFAULT_WORLD_ID) / "events.json", "personal_events")
    _merge_bundled_content(Path(DEFAULT_WORLD_ID) / "events.json", "ambient_events")

    WORLDS_DIR.mkdir(parents=True, exist_ok=True)

def get_worlds_dir() -> Path:
    """获取世界根目录"""
    ensure_worlds_available()
    return WORLDS_DIR


def get_world_path(world_id: str = DEFAULT_WORLD_ID) -> Path:
    """Return the fixed Touhou world directory."""
    ensure_worlds_available()
    world_path = WORLDS_DIR / DEFAULT_WORLD_ID
    world_path.mkdir(parents=True, exist_ok=True)
    return world_path


def get_world_index() -> Dict:
    """获取世界索引"""
    ensure_worlds_available()
    if WORLDS_INDEX_FILE.exists():
        with open(WORLDS_INDEX_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return {
        "worlds": [],
        "current_world": DEFAULT_WORLD_ID,
        "version": "1.0"
    }


def save_world_index(index: Dict):
    """保存世界索引"""
    with open(WORLDS_INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def register_world(world_id: str, world_name: str, description: str = ""):
    """注册新世界"""
    index = get_world_index()
    
    for w in index["worlds"]:
        if w["id"] == world_id:
            return False
    
    index["worlds"].append({
        "id": world_id,
        "name": world_name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "last_played": None
    })
    save_world_index(index)
    return True


def set_current_world(world_id: str) -> bool:
    """Persist the only supported runtime world."""
    if world_id != DEFAULT_WORLD_ID:
        return False
    index = get_world_index()
    touhou = next((item for item in index.get("worlds", []) if item.get("id") == DEFAULT_WORLD_ID), None)
    index["worlds"] = [touhou or {
        "id": DEFAULT_WORLD_ID,
        "name": "TouHou",
        "description": "东方异变录",
        "created_at": datetime.now().isoformat(),
        "last_played": None,
    }]
    index["current_world"] = DEFAULT_WORLD_ID
    save_world_index(index)
    return True


def get_current_world() -> str:
    """Return the fixed Touhou runtime world, including for old indexes."""
    return DEFAULT_WORLD_ID


def get_current_world_path() -> Path:
    """获取当前世界的目录路径"""
    return get_world_path(get_current_world())


# ========== 世界初始化检测 ==========

def is_world_initialized(world_id: str = None) -> bool:
    """检查世界是否已初始化（有地点库、NPC、时间线）"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    
    locations_base = world_path / "locations" / "location_base.json"
    npc_index = world_path / "npcs" / "npc_index.json"
    timeline = world_path / "timeline.json"
    
    # 三个文件都必须存在才算初始化
    print(f"🔍 检查世界初始化: {world_path}")
    return locations_base.exists() and npc_index.exists() and timeline.exists()


def get_world_worldview(world_id: str = None) -> str:
    """获取世界观设定"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    worldview_path = world_path / "worldview.txt"
    
    if worldview_path.exists():
        with open(worldview_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    return """幻想乡是被博丽大结界隔离的秘境，人类、妖怪、神明与妖精共同生活。异变通常通过调查、交涉与符卡规则解决，玩家可以自由选择探索方式。"""


def save_world_worldview(content: str, world_id: str = None):
    """保存世界观设定"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    worldview_path = world_path / "worldview.txt"
    
    with open(worldview_path, 'w', encoding='utf-8') as f:
        f.write(content)


# ========== 世界数据访问 ==========

def get_locations_dir(world_id: str = None) -> Path:
    """获取地点目录"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    locations_dir = world_path / "locations"
    locations_dir.mkdir(parents=True, exist_ok=True)
    return locations_dir


def get_npcs_dir(world_id: str = None) -> Path:
    """获取 NPC 目录"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    npcs_dir = world_path / "npcs"
    npcs_dir.mkdir(parents=True, exist_ok=True)
    return npcs_dir


def get_sessions_dir(world_id: str = None) -> Path:
    """获取会话目录"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    sessions_dir = world_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_characters_dir(world_id: str = None) -> Path:
    """获取角色目录"""
    sessions_dir = get_sessions_dir(world_id)
    characters_dir = sessions_dir / "characters"
    characters_dir.mkdir(parents=True, exist_ok=True)
    return characters_dir


def get_timeline_path(world_id: str = None) -> Path:
    """获取时间线文件路径"""
    world_path = get_world_path(world_id) if world_id else get_current_world_path()
    return world_path / "timeline.json"


def load_timeline(world_id: str = None) -> Dict:
    """加载时间线"""
    timeline_path = get_timeline_path(world_id)
    if timeline_path.exists():
        with open(timeline_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return {
        "version": "1.0",
        "milestones": [
            {
                "id": "milestone_1",
                "name": "结界来客",
                "order": 1,
                "description": "玩家开始在幻想乡自由行动",
                "default_time_remaining": 72
            }
        ],
        "current_milestone": "milestone_1"
    }


def save_timeline(timeline: Dict, world_id: str = None):
    """保存时间线"""
    timeline_path = get_timeline_path(world_id)
    with open(timeline_path, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)


# ========== 默认数据（fallback） ==========

def get_default_locations() -> Dict:
    """获取默认地点数据（AI 生成失败时的 fallback）"""
    return {
        "regions": [
            {
                "id": "region_hakurei",
                "name": "博丽神社周边",
                "description": "大结界边缘与通往人间之里的参道",
                "icon": "社"
            },
            {
                "id": "region_village",
                "name": "人间之里",
                "description": "幻想乡人类主要聚居地",
                "icon": "里"
            }
        ],
        "locations": [
            {
                "id": "loc_hakurei",
                "name": "博丽神社",
                "parent": "region_hakurei",
                "description": "位于幻想乡边缘、由博丽巫女守护的神社",
                "icon": "社"
            },
            {
                "id": "loc_village",
                "name": "人间之里",
                "parent": "region_village",
                "description": "商店、寺子屋与居民街道集中的村落",
                "icon": "里"
            },
            {
                "id": "loc_magic_forest",
                "name": "魔法森林",
                "parent": "region_hakurei",
                "description": "魔法使与妖怪出没的迷雾森林",
                "icon": "森"
            }
        ]
    }


def get_default_npcs() -> Dict:
    """获取默认 NPC 数据（AI 生成失败时的 fallback）"""
    return {
        "npcs": [
            {
                "id": "npc_reimu",
                "name": "博丽灵梦",
                "gender": "女",
                "profile": {
                    "identity": "博丽巫女",
                    "description": "红白巫女服、白袜与黑色小皮鞋",
                    "personality_traits": ["从容", "直率"],
                    "background": "维护博丽大结界并解决幻想乡异变"
                },
                "location_id": "loc_hakurei",
                "active": True,
                "dead": False
            },
            {
                "id": "npc_marisa",
                "name": "雾雨魔理沙",
                "gender": "女",
                "profile": {
                    "identity": "普通的魔法使",
                    "description": "金发、黑白魔法使装束，常携迷你八卦炉",
                    "personality_traits": ["爽朗", "好奇"],
                    "background": "居住在魔法森林并热衷魔法研究"
                },
                "location_id": "loc_magic_forest",
                "active": True,
                "dead": False
            }
        ]
    }


def get_default_timeline() -> Dict:
    """获取默认时间线（AI 生成失败时的 fallback）"""
    return {
        "version": "1.0",
        "milestones": [
            {
                "id": "milestone_1",
                "name": "结界来客",
                "order": 1,
                "description": "开始探索幻想乡与结界裂隙",
                "default_time_remaining": 72
            },
            {
                "id": "milestone_2",
                "name": "异变调查",
                "order": 2,
                "description": "结识幻想乡居民并追踪异变线索",
                "default_time_remaining": 120
            },
            {
                "id": "milestone_3",
                "name": "异变余波",
                "order": 3,
                "description": "异变解决后继续自由探索新的故事",
                "default_time_remaining": 168
            }
        ],
        "current_milestone": "milestone_1"
    }


# ========== 迁移 V3 数据 ==========

def migrate_v3_data():
    """将 V3 数据迁移到 default 世界"""
    print("📦 开始迁移 V3 数据...")
    
    default_path = get_world_path(DEFAULT_WORLD_ID)
    
    # 迁移 worldview
    old_worldview = DATA_DIR / "worldview_setting.txt"
    if old_worldview.exists():
        new_worldview = default_path / "worldview.txt"
        shutil.copy(old_worldview, new_worldview)
        print(f"  ✅ 迁移 worldview.txt")
    
    # 迁移 chapters
    old_chapters = DATA_DIR / "chapters"
    if old_chapters.exists():
        new_chapters = default_path / "chapters"
        if new_chapters.exists():
            shutil.rmtree(new_chapters)
        shutil.copytree(old_chapters, new_chapters)
        print(f"  ✅ 迁移 chapters/")
    
    # 迁移 locations
    old_locations = DATA_DIR / "locations"
    if old_locations.exists():
        new_locations = default_path / "locations"
        new_locations.mkdir(parents=True, exist_ok=True)
        
        for file in ["location_base.json", "location_dynamic.json"]:
            old_file = old_locations / file
            if old_file.exists():
                shutil.copy(old_file, new_locations / file)
                print(f"  ✅ 迁移 locations/{file}")
    
    # 迁移 npcs
    old_npcs = DATA_DIR / "npcs"
    if old_npcs.exists():
        new_npcs = default_path / "npcs"
        new_npcs.mkdir(parents=True, exist_ok=True)
        
        old_npc_index = old_npcs / "npc_index.json"
        if old_npc_index.exists():
            shutil.copy(old_npc_index, new_npcs / "npc_index.json")
            print(f"  ✅ 迁移 npcs/npc_index.json")
    
    # 迁移角色存档
    old_characters = DATA_DIR / "sessions" / "ghost" / "characters"
    if old_characters.exists():
        new_characters = default_path / "sessions" / "characters"
        new_characters.mkdir(parents=True, exist_ok=True)
        
        for file in old_characters.iterdir():
            if file.suffix == '.json':
                shutil.copy(file, new_characters / file.name)
        print(f"  ✅ 迁移 sessions/characters/")
    
    register_world(DEFAULT_WORLD_ID, "默认世界", "V3 迁移的默认世界")
    
    print("📦 V3 数据迁移完成！")

# ========== 角色管理函数（从 api.py 迁移） ==========

def _energy_from_fatigue(fatigue) -> str:
    fatigue = parse_number_local(fatigue, 0)
    if fatigue >= 90:
        return "灵力枯竭"
    if fatigue >= 70:
        return "疲惫不堪"
    if fatigue >= 45:
        return "感到疲倦"
    if fatigue >= 20:
        return "略有疲惫"
    return "精力充沛"


def parse_number_local(value, default=0):
    try:
        if isinstance(value, str) and value.strip() == "":
            return default
        num = float(value)
        return int(num) if num.is_integer() else num
    except (TypeError, ValueError):
        return default


def ensure_character_fields(character: Dict) -> Dict:
    """确保角色 JSON 包含所有必要字段（向前兼容）"""
    
    migrated = migrate_save_schema(character)
    from backend.services.relationship_policy_service import profile_age
    profile = character.setdefault("profile", {})
    if "adult_verified" not in profile:
        age = profile_age(profile)
        profile["adult_verified"] = bool(age is not None and age >= 18)
        migrated = True

    if not character.get("world_id"):
        character["world_id"] = DEFAULT_WORLD_ID
        migrated = True

    if character.get("save_version", 0) < CURRENT_SAVE_VERSION:
        character["save_version"] = CURRENT_SAVE_VERSION
        migrated = True

    if "status" not in character:
        character["status"] = {
            "is_dead": False,
            "death_cause": None,
            "health": 100,
            "current_scene": "unknown"
        }
        migrated = True
    else:
        if "is_dead" not in character["status"]:
            character["status"]["is_dead"] = False
        if "death_cause" not in character["status"]:
            character["status"]["death_cause"] = None
        if "health" not in character["status"]:
            character["status"]["health"] = 100
        if "current_scene" not in character["status"]:
            character["status"]["current_scene"] = "unknown"
    
    if "unlocked_locations" not in character:
        character["unlocked_locations"] = {}
    
    if "relationships" not in character:
        character["relationships"] = {}

    if "npc_memories" not in character:
        character["npc_memories"] = {}
    if "npc_memory_summaries" not in character:
        character["npc_memory_summaries"] = {}
        migrated = True
    for npc_name, items in list(character.get("npc_memories", {}).items()):
        if not isinstance(items, list):
            character["npc_memories"][npc_name] = []
            migrated = True
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                items[idx] = {
                    "id": f"mem_migrated_{idx}",
                    "summary": str(item),
                    "tags": [],
                    "source": "migrated",
                    "importance": 5,
                    "emotion": "中性",
                    "created_at": datetime.now().isoformat(),
                    "last_used_at": None,
                    "used_count": 0
                }
                migrated = True
                continue
            if "id" not in item:
                item["id"] = f"mem_migrated_{idx}_{len(str(item))}"
                migrated = True
            if "importance" not in item:
                item["importance"] = 5
                migrated = True
            if "emotion" not in item:
                item["emotion"] = "中性"
                migrated = True
            if "last_used_at" not in item:
                item["last_used_at"] = None
                migrated = True
            if "used_count" not in item:
                item["used_count"] = 0
                migrated = True
    from backend.services.npc_memory_service import upgrade_npc_memory_metadata
    if upgrade_npc_memory_metadata(character):
        migrated = True

    if "open_events" not in character:
        character["open_events"] = []
        migrated = True

    if "spellcard_history" not in character:
        character["spellcard_history"] = []
        migrated = True
    
    if "inventory" not in character:
        character["inventory"] = []
    
    if "conversation_history" not in character:
        character["conversation_history"] = []
        migrated = True

    for msg in character.get("conversation_history", []):
        if isinstance(msg, dict):
            if "message_id" not in msg:
                msg["message_id"] = f"msg_{datetime.now().timestamp()}_{len(str(msg))}"
                migrated = True
            if "rating" not in msg:
                msg["rating"] = None
                migrated = True
            if "reroll_of" not in msg:
                msg["reroll_of"] = None
                migrated = True
            if not isinstance(msg.get("rewrite_candidates"), list):
                msg["rewrite_candidates"] = []
                migrated = True

    if not isinstance(character.get("model_runtime"), dict):
        character["model_runtime"] = {}
        migrated = True
    
    # 时间系统字段
    if "time" not in character:
        character["time"] = {
            "current_day": 1,
            "current_hour": 8,
            "energy_state": "精力充沛",
            "chapter_time_remaining": 72,
            "chapter_node_name": "下个关键节点",
            "last_rest_day": 1,
            "last_rest_hour": 20,
            "chapter_status": "active",
            "anomaly_state": "active"
        }
        migrated = True
    else:
        if "current_day" not in character["time"]:
            character["time"]["current_day"] = 1
        if "current_hour" not in character["time"]:
            character["time"]["current_hour"] = 8
        if "energy_state" not in character["time"]:
            character["time"]["energy_state"] = "精力充沛"
        if "chapter_time_remaining" not in character["time"]:
            character["time"]["chapter_time_remaining"] = 72
            migrated = True
        if "chapter_node_name" not in character["time"]:
            character["time"]["chapter_node_name"] = "结界裂隙扩散"
            migrated = True
        if "chapter_status" not in character["time"]:
            character["time"]["chapter_status"] = "active"
            migrated = True
        if "anomaly_state" not in character["time"]:
            character["time"]["anomaly_state"] = "active"
            migrated = True
    
    # T3 预留字段
    if "system_helper_history" not in character:
        character["system_helper_history"] = []
    
    if "resources" not in character:
        character["resources"] = {
            "灵石": 0,
            "药材": [],
            "道具": []
        }

    if "player_state" not in character:
        character["player_state"] = {
            "灵力": 50,
            "结界共鸣": 35,
            "弹幕熟练度": 10,
            "调查熟练度": 0,
            "交涉熟练度": 0,
            "生存熟练度": 0,
            "疲劳": 0,
            "受伤": 0,
            "异变污染": 5
        }
        migrated = True
    else:
        defaults = {"灵力": 50, "结界共鸣": 35, "弹幕熟练度": 10, "调查熟练度": 0, "交涉熟练度": 0, "生存熟练度": 0, "疲劳": 0, "受伤": 0, "异变污染": 5}
        for key, value in defaults.items():
            if key not in character["player_state"]:
                character["player_state"][key] = value
                migrated = True
        if character.get("gm_mode"):
            for key in ("调查熟练度", "交涉熟练度", "生存熟练度"):
                if character["player_state"].get(key) != 999999:
                    character["player_state"][key] = 999999
                    migrated = True

    character["time"]["energy_state"] = _energy_from_fatigue(character.get("player_state", {}).get("疲劳", 0))

    if not isinstance(character.get("skill_experience"), dict):
        character["skill_experience"] = {}
        migrated = True
    for skill_name in ("弹幕熟练度", "调查熟练度", "交涉熟练度", "生存熟练度"):
        if skill_name not in character["skill_experience"]:
            character["skill_experience"][skill_name] = 0
            migrated = True
    
    if "reputation" not in character:
        character["reputation"] = {}
    
    if "current_goals" not in character:
        character["current_goals"] = []
    
    if "active_tasks" not in character:
        character["active_tasks"] = []
    
    if "completed_tasks" not in character:
        character["completed_tasks"] = []
    
    # 关系历史字段
    if "relationships_history" not in character:
        character["relationships_history"] = []
        migrated = True
    
    if "relationships_map" not in character:
        if character.get("relationships_history"):
            from backend.services.relationship_service import get_current_relationships
            get_current_relationships(character)
        else:
            character["relationships_map"] = {}
            migrated = True
    
    # 高权限模式
    if "gm_mode" not in character:
        character["gm_mode"] = False
        migrated = True

    if "world_info_hits" not in character:
        character["world_info_hits"] = {}
        migrated = True

    incident_before = json.dumps(character.get("incident_state"), ensure_ascii=False, sort_keys=True, default=str)
    from backend.services.incident_service import ensure_incident_state
    ensure_incident_state(character)
    incident_after = json.dumps(character.get("incident_state"), ensure_ascii=False, sort_keys=True, default=str)
    if incident_before != incident_after:
        migrated = True

    character["_migrated"] = migrated
    
    return character


def load_character(character_id: str, world_id: str = None) -> Optional[Dict]:
    """加载角色数据（自动补全缺失字段）"""
    characters_dir = get_characters_dir(world_id)
    char_path = characters_dir / f"{character_id}.json"
    transaction_path = characters_dir / "_transactions" / f"{character_id}.json"
    with character_write_lock(character_id, world_id):
        if transaction_path.exists():
            try:
                with open(transaction_path, "r", encoding="utf-8") as handle:
                    pending = json.load(handle)
                _apply_world_changes(pending.get("world_changes", {}), world_id)
                if isinstance(pending.get("character"), dict):
                    _atomic_json_write(char_path, pending["character"])
                if isinstance(pending.get("tasks"), dict):
                    _atomic_json_write(get_tasks_path(character_id, world_id), pending["tasks"])
                transaction_path.unlink(missing_ok=True)
                print(f"✅ 已恢复未完成存档事务: {character_id}")
            except (OSError, json.JSONDecodeError) as exc:
                print(f"⚠️ 存档事务恢复失败: {exc}")
    
    if char_path.exists():
        try:
            with open(char_path, 'r', encoding='utf-8') as f:
                character = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"⚠️ 主存档读取失败，尝试从快照恢复: {exc}")
            snapshots = list_character_snapshots(character_id, world_id)
            if not snapshots:
                return None
            restore_character_snapshot(character_id, snapshots[0]["snapshot_id"], world_id=world_id)
            with open(char_path, 'r', encoding='utf-8') as f:
                character = json.load(f)
        if character:
            # 验证是否为有效的角色数据
            if character.get("character_id") and character.get("profile"):
                before_upgrade = json.loads(json.dumps(character, ensure_ascii=False, default=str))
                character = ensure_character_fields(character)
                migrated = character.pop("_migrated", False)
                if migrated or character != before_upgrade:
                    write_upgrade_artifacts(characters_dir, character_id, before_upgrade, character)
                    save_character(character_id, character, world_id)
                return character
            else:
                print(f"⚠️ 文件 {char_path.name} 不是有效的角色数据")
                return None
    
    # 兼容旧格式：遍历查找（如果直接路径不存在）
    for filename in characters_dir.iterdir():
        if filename.suffix == '.json' and filename.stem == character_id:
            with open(filename, 'r', encoding='utf-8') as f:
                character = json.load(f)
                if (character.get("character_id") and 
                    character.get("world_id") and 
                    character.get("profile")):
                    before_upgrade = json.loads(json.dumps(character, ensure_ascii=False, default=str))
                    character = ensure_character_fields(character)
                    migrated = character.pop("_migrated", False)
                    if migrated or character != before_upgrade:
                        write_upgrade_artifacts(characters_dir, character_id, before_upgrade, character)
                        save_character(character_id, character, world_id)
                    return character
            break
    
    return None

def save_character(character_id: str, data: Dict, world_id: str = None):
    """保存角色数据（确保是有效的角色数据）"""
    characters_dir = get_characters_dir(world_id)
    
    # 验证必要字段
    if not data.get("character_id") or not data.get("profile"):
        print(f"警告：尝试保存无效的角色数据 {character_id}")
        return
    
    char_path = characters_dir / f"{character_id}.json"
    with character_write_lock(character_id, world_id):
        current_revision = 0
        if char_path.exists():
            try:
                with open(char_path, "r", encoding="utf-8") as handle:
                    current_revision = int(json.load(handle).get("state_revision", 0) or 0)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                current_revision = int(data.get("state_revision", 0) or 0)
        data["state_revision"] = current_revision + 1
        data["last_saved_at"] = datetime.now().isoformat()
        _atomic_json_write(char_path, data)
        create_character_snapshot(character_id, data, world_id)


def get_all_characters(world_id: str = None) -> List[Dict]:
    """获取所有角色列表（通过验证数据结构识别角色文件）"""
    characters = []
    
    if world_id:
        # 获取指定世界的角色
        characters_dir = get_characters_dir(world_id)
        print(f"🔍 加载get_all_characters - 指定世界: {world_id}, 目录: {characters_dir}")
        if characters_dir.exists():
            characters = _load_characters_from_dir(characters_dir)
    else:
        # 获取所有世界的角色
        print("🔍 加载get_all_characters - 遍历所有世界")
        worlds_dir = get_worlds_dir()
        if worlds_dir.exists():
            for world_folder in worlds_dir.iterdir():
                if world_folder.is_dir() and not world_folder.name.startswith('_'):
                    world_id = world_folder.name
                    try:
                        characters_dir = get_characters_dir(world_id)
                        if characters_dir.exists():
                            world_chars = _load_characters_from_dir(characters_dir)
                            characters.extend(world_chars)
                            print(f"🔍 世界 {world_id} 找到 {len(world_chars)} 个角色")
                    except Exception as e:
                        print(f"❌ 读取世界 {world_id} 角色失败: {e}")
    
    print(f"🔍 最终找到的角色数量: {len(characters)}")
    return characters


def _load_characters_from_dir(characters_dir: Path) -> List[Dict]:
    """从指定目录加载角色"""
    chars = []
    for filename in characters_dir.iterdir():
        if filename.suffix == '.json' and not filename.name.startswith('_'):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 验证是否为有效的角色数据
                has_char_id = data.get("character_id")
                has_world_id = data.get("world_id")
                has_profile = data.get("profile")
                profile_is_dict = isinstance(data.get("profile"), dict)
                
                if has_char_id and has_world_id and has_profile and profile_is_dict:
                    chars.append({
                        "character_id": data.get("character_id"),
                        "profile": data.get("profile", {}),
                        "current_scene": data.get("status", {}).get("current_scene", "unknown"),
                        "is_dead": data.get("status", {}).get("is_dead", False),
                        "created_at": data.get("created_at"),
                        "last_played": data.get("last_played"),
                        "unlocked_locations": data.get("unlocked_locations", {})
                    })
            except Exception as e:
                print(f"❌ 读取文件失败 {filename}: {e}")
    return chars

# ========== 任务数据管理 ==========

def get_tasks_path(character_id: str, world_id: str = None) -> Path:
    """获取任务文件路径"""
    characters_dir = get_characters_dir(world_id)
    return characters_dir / f"{character_id}_tasks.json"


def load_tasks(character_id: str, world_id: str = None) -> Dict:
    """加载任务数据"""
    tasks_path = get_tasks_path(character_id, world_id)
    
    if tasks_path.exists():
        with character_write_lock(character_id, world_id):
            with open(tasks_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data.setdefault("state_revision", 0)
                return data
    
    return get_default_tasks()


def save_tasks(character_id: str, data: Dict, world_id: str = None):
    """保存任务数据"""
    tasks_path = get_tasks_path(character_id, world_id)
    
    with character_write_lock(character_id, world_id):
        current_revision = 0
        if tasks_path.exists():
            try:
                with open(tasks_path, "r", encoding="utf-8") as handle:
                    current_revision = int(json.load(handle).get("state_revision", 0) or 0)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                current_revision = int(data.get("state_revision", 0) or 0)
        data["state_revision"] = current_revision + 1
        data["last_updated"] = datetime.now().isoformat()
        _atomic_json_write(tasks_path, data)


def save_turn_bundle(
    character_id: str,
    character: Dict,
    tasks: Dict,
    world_id: str = None,
    *,
    expected_character_revision: int = None,
    expected_tasks_revision: int = None,
    world_changes: Dict = None,
):
    """Commit character and task state as a recoverable two-file transaction."""
    characters_dir = get_characters_dir(world_id)
    transaction_path = characters_dir / "_transactions" / f"{character_id}.json"
    with character_write_lock(character_id, world_id):
        char_path = characters_dir / f"{character_id}.json"
        tasks_path = get_tasks_path(character_id, world_id)
        persisted_character_revision = 0
        persisted_tasks_revision = 0
        if char_path.exists():
            with open(char_path, "r", encoding="utf-8") as handle:
                persisted_character_revision = int(
                    json.load(handle).get("state_revision", 0) or 0
                )
        if tasks_path.exists():
            with open(tasks_path, "r", encoding="utf-8") as handle:
                persisted_tasks_revision = int(
                    json.load(handle).get("state_revision", 0) or 0
                )
        if (
            expected_character_revision is not None
            and persisted_character_revision != expected_character_revision
        ):
            raise StaleTurnError(
                f"角色状态已从 revision {expected_character_revision} 更新为 "
                f"{persisted_character_revision}，本回合未覆盖新存档"
            )
        if (
            expected_tasks_revision is not None
            and persisted_tasks_revision != expected_tasks_revision
        ):
            raise StaleTurnError(
                f"任务状态已从 revision {expected_tasks_revision} 更新为 "
                f"{persisted_tasks_revision}，本回合未覆盖新存档"
            )

        character["state_revision"] = persisted_character_revision + 1
        tasks["state_revision"] = persisted_tasks_revision + 1
        character["last_saved_at"] = datetime.now().isoformat()
        tasks["last_updated"] = datetime.now().isoformat()
        transaction = {
            "transaction_version": 2,
            "character_id": character_id,
            "created_at": datetime.now().isoformat(),
            "character": character,
            "tasks": tasks,
            "world_changes": world_changes or {},
        }
        _atomic_json_write(transaction_path, transaction)
        _apply_world_changes(transaction["world_changes"], world_id)
        _atomic_json_write(char_path, character)
        _atomic_json_write(tasks_path, tasks)
        transaction_path.unlink(missing_ok=True)
        create_character_snapshot(character_id, character, world_id)


def get_turn_receipt(character: Dict, turn_id: str):
    if not turn_id:
        return None
    for item in reversed(character.get("turn_receipts", [])):
        if item.get("turn_id") == turn_id:
            return item.get("response")
    return None


def record_turn_receipt(character: Dict, turn_id: str, response: Dict):
    if not turn_id:
        return
    receipts = [item for item in character.setdefault("turn_receipts", []) if item.get("turn_id") != turn_id]
    receipts.append({"turn_id": turn_id, "created_at": datetime.now().isoformat(), "response": response})
    character["turn_receipts"] = receipts[-30:]


def get_default_tasks() -> Dict:
    """返回默认任务数据结构"""
    return {
        "active_tasks": [],
        "completed_tasks": [],
        "removed_tasks": [],
        "applied_turn_ids": [],
        "state_revision": 0,
        "version": "1.0",
        "last_updated": None
    }

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate_v3_data()
