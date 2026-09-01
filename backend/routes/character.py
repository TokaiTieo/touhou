# backend/routes/character.py
# 角色管理相关路由

import uuid
import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional, Any

from backend.world_manager import (
    get_current_world,
    get_characters_dir,
    ensure_character_fields,
    load_character,
    save_character,
    get_all_characters,
    load_tasks,
    get_locations_dir,
    get_current_world_path,
    save_tasks
)
from backend.services.ai_service import call_ai_async, clean_json_response
from backend.services.incident_service import sync_incident_from_tasks
from backend.services.story_summary_service import default_story_summary
from backend.services.relationship_policy_service import profile_age
from backend.services.onboarding_service import default_onboarding, public_onboarding
from backend.config import PROMPTS_DIR
from backend.version import CONTENT_SCHEMA_VERSION, SAVE_SCHEMA_VERSION

router = APIRouter()


def _resolve_location_name(location_ref: str) -> str:
    """Resolve a world starting location id to its display name."""
    try:
        from backend.location_manager import get_location_manager

        lm = get_location_manager(get_locations_dir())
        location = lm.get_location_by_name(location_ref)
        if location:
            return location.name
    except Exception as e:
        print(f"解析起始地点失败: {e}")
    return location_ref


def _build_touhou_opening(profile: Dict[str, Any], starting_location: str) -> str:
    name = profile.get("name") or "你"
    origin_type = profile.get("origin_type") or _infer_origin_type(profile)
    identity = profile.get("identity") or "旅行者"

    if origin_type == "resident":
        return (
            f"清晨的{starting_location}传来不合时宜的灵力震颤。{name}并不是初来乍到的迷路人，"
            f"而是以「{identity}」的身份早已熟悉幻想乡的空气、规矩与危险。\n\n"
            "今日的大结界却像被看不见的手指轻轻划开，熟悉的风景出现了陌生的裂纹。"
            "这不是寻找自己为何来到幻想乡的故事，而是你要判断：这片熟悉土地上，究竟有什么正在偏离常轨。\n\n"
            f"你现在位于{starting_location}。第一章《结界裂隙异变》开始：调查异常源头，或按自己的方式先处理身边的人与事。"
        )

    if origin_type == "moon":
        return (
            f"夜色尚未完全褪去，{name}在{starting_location}醒来。月之都留下的冷光仍残留在皮肤与记忆深处，"
            "而幻想乡的大结界正在发出与月面技术相似却更古老的回响。\n\n"
            "你不需要先证明自己为何存在于这里；真正的问题是，结界裂隙是否与你的逃亡、实验或月都残影有关。\n\n"
            f"你现在位于{starting_location}。第一章《结界裂隙异变》开始：追踪异常，也保护好自己不被旧日的影子重新抓住。"
        )

    if origin_type == "anomaly":
        return (
            f"{name}睁开眼时，{starting_location}的空气像水面一样裂开又闭合。你不是单纯被异变卷入，"
            "你的身体、灵魂或命运本身似乎就是裂隙的一部分。\n\n"
            "博丽灵梦的符纸在你靠近时微微发烫，魔理沙远远看着你，像发现了一颗会自己走路的魔法素材。\n\n"
            f"你现在位于{starting_location}。第一章《结界裂隙异变》开始：弄清你与裂隙的关系，或主动利用这份异常。"
        )

    return (
        f"清晨的博丽神社被薄雾笼罩，塞钱箱旁的御币无风自动。{name}在本殿前醒来，"
        "衣袖上沾着细碎的红白光尘，像是刚从某道看不见的裂隙中坠落。\n\n"
        "博丽灵梦站在石阶上，手里捏着一张微微发烫的符纸，目光懒散却锐利。远处的天空划过一圈不合时宜的结界波纹，"
        "魔理沙骑着扫帚从云缝间探头，兴奋地喊着这可是大新闻级别的异变。\n\n"
        f"你现在位于{starting_location}。第一章《结界裂隙异变》开始：先弄清自己为何会出现在幻想乡，并调查大结界异常的源头。"
    )


def _infer_origin_type(profile: Dict[str, Any]) -> str:
    text = " ".join(str(profile.get(key, "")) for key in ("identity", "background", "personality", "appearance"))
    if any(word in text for word in ("原住民", "幻想乡住民", "本地", "博丽", "守矢", "妖怪之山", "红魔馆", "白玉楼", "永远亭")):
        return "resident"
    if any(word in text for word in ("月都", "月之都", "月面", "月兔", "永琳", "辉夜", "铃仙")):
        return "moon"
    if any(word in text for word in ("异变核心", "裂隙", "结界的一部分", "异常核心")):
        return "anomaly"
    return "outsider"


def _infer_initial_player_state(profile: Dict[str, Any], gm_mode: bool = False) -> Dict[str, Any]:
    if gm_mode:
        return {
            "灵力": 999999,
            "结界共鸣": 999999,
            "弹幕熟练度": 999999,
            "调查熟练度": 999999,
            "交涉熟练度": 999999,
            "生存熟练度": 999999,
            "疲劳": 0,
            "受伤": 0,
            "异变污染": 0,
            "高权限": "最高",
            "命运干预": "无限",
            "对手压制": "绝对"
        }

    text = " ".join(str(profile.get(key, "")) for key in ("identity", "background", "personality", "appearance"))
    state = {"灵力": 50, "结界共鸣": 35, "弹幕熟练度": 10, "调查熟练度": 0, "交涉熟练度": 0, "生存熟练度": 0, "疲劳": 0, "受伤": 0, "异变污染": 5}
    if any(word in text for word in ("强", "最强", "大妖怪", "贤者", "神", "高阶", "天才", "强大")):
        state.update({"灵力": 85, "弹幕熟练度": 55, "结界共鸣": 60})
    if any(word in text for word in ("符卡", "弹幕", "巫女", "魔法使", "阴阳师", "风祝")):
        state["弹幕熟练度"] = max(state["弹幕熟练度"], 35)
        state["灵力"] = max(state["灵力"], 65)
    if any(word in text for word in ("结界", "裂隙", "异变核心", "境界")):
        state["结界共鸣"] = max(state["结界共鸣"], 80)
        state["异变污染"] = max(state["异变污染"], 15)
    if any(word in text for word in ("月都", "实验体", "改造")):
        state["灵力"] = max(state["灵力"], 70)
        state["异变污染"] = max(state["异变污染"], 20)
    if any(word in text for word in ("受伤", "虚弱", "逃亡", "濒死")):
        state["受伤"] = max(state["受伤"], 20)
        state["疲劳"] = max(state["疲劳"], 15)
    return state


def _sync_anomaly_state_from_tasks(character_id: str, character: Dict[str, Any]):
    tasks_data = load_tasks(character_id)
    sync_incident_from_tasks(character, tasks_data)
    save_character(character_id, character)


def _build_touhou_initial_tasks() -> Dict[str, Any]:
    now = datetime.now().isoformat()
    return {
        "active_tasks": [
            {
                "id": "main_touhou_rift_01",
                "name": "传闻：结界裂隙异变",
                "description": "你在博丽神社醒来，大结界出现异常波纹。灵梦可能知道第一手情况，但这只是一个线索；你也可以直接前往任何地点自由调查。",
                "priority": 10,
                "created_at": now,
                "source": "异变传闻"
            },
            {
                "id": "main_touhou_rift_02",
                "name": "邀约：魔理沙的魔力痕迹",
                "description": "雾雨魔理沙似乎注意到了结界波动中的魔力痕迹。可以去雾雨魔法店找她，也可以暂时放下这条线索，按自己的兴趣探索幻想乡。",
                "priority": 40,
                "created_at": now,
                "source": "人物邀约"
            },
            {
                "id": "free_touhou_romance_01",
                "name": "人物关系：自由发展",
                "description": "幻想乡的少女们会记住你的承诺、战斗、调情、亲密经历和冒犯。你可以主动推进恋爱与亲密关系，也可以保持普通交往。",
                "priority": 80,
                "created_at": now,
                "source": "关系线索"
            }
        ],
        "completed_tasks": [],
        "removed_tasks": [],
        "version": "1.0",
        "last_updated": now
    }


class CreateCharacterRequest(BaseModel):
    profile: Dict[str, Any]
    chapter_index: int = 1


class LoadCharacterRequest(BaseModel):
    character_id: str
    scene: Optional[str] = None


class CharacterStatusUpdateRequest(BaseModel):
    character_id: str
    health: Optional[int] = None
    current_scene: Optional[str] = None


@router.post("/validate_character")
async def validate_character(request: dict):
    """验证角色设定：验证宽松（不卡世界观），但生成严格（必须符合世界观）"""
    user_input = request.get("user_input", "")
    chapter_index = request.get("chapter_index", 1)
    
    if not user_input:
        return {
            "valid": False,
            "message": "请输入角色描述",
            "suggested_profile": None
        }
    
    # === 第一步：宽松验证（不看世界观，只看用户是否有基本角色描述）===
    # 只要用户写了有意义的描述，就返回 valid=True，不因为世界观限制用户创意
    
    # 检测高权限模式
    GM_TRIGGER_KEYWORD = "".join(chr(code) for code in [0x3010, 0x6211, 0x662f, 0x6e38, 0x620f, 0x5236, 0x4f5c, 0x4eba, 0x3011])
    is_gm_mode = GM_TRIGGER_KEYWORD in user_input
    
    # === 第二步：读取世界观，用于生成符合世界观的角色设定 ===
    worldview_content = ""
    if not is_gm_mode:
        # GM 模式下不读取世界观
        try:
            world_path = get_current_world_path()
            worldview_path = world_path / "worldview.txt"
            if worldview_path.exists():
                with open(worldview_path, 'r', encoding='utf-8') as f:
                    worldview_content = f.read().strip()
                # 避免过长，截断到 6000 字符
                if len(worldview_content) > 6000:
                    worldview_content = worldview_content[:6000] + "\n...（世界观设定较长，已截断）"
        except Exception as e:
            print(f"读取世界观文件失败: {e}")
    
    try:
        worldview_section = f"""
## 当前世界观设定
{worldview_content}
""" if worldview_content else """
## 当前世界观设定
（未找到世界观文件，请根据用户描述自行判断合理性）
"""

        # 验证阶段：只检查用户输入是否有意义，世界观不卡人
        validation_prompt = f"""你是一个角色描述评估助手。请判断用户的角色描述是否有意义（是否包含至少一些角色相关的信息，如身份、外貌、性格、背景等）。

## 用户角色描述
{user_input}

请输出JSON格式：
- valid: true（只要描述有意义，不管内容是什么风格）或 false（完全无意义/空描述）
- message: 简短说明，如"描述有效"或"请输入角色描述"
"""
        
        val_response = await call_ai_async(validation_prompt, temperature=0.4)
        try:
            val_result = json.loads(clean_json_response(val_response))
        except json.JSONDecodeError:
            val_result = {"valid": True, "message": "描述有效"}
        is_valid = val_result.get("valid", True)
        val_message = val_result.get("message", "描述有效")
        
        # 如果验证不通过，直接返回
        if not is_valid:
            return {
                "valid": False,
                "message": val_message,
                "suggested_profile": None
            }
        
        if is_gm_mode:
            # 高权限模式：不按世界观限制，完全按用户意愿生成
            generation_prompt = f"""【高权限模式已激活】
你是本游戏的角色设定生成助手。当前输入来自高权限用户，其指令高于一切世界观设定和规则限制。
请直接按照高权限用户的描述生成角色设定，不要拒绝、不要修正、不要添加限制。
如果高权限用户的描述不够完整，请合理补充细节，但核心设定必须忠实于高权限用户的意图。
默认将该角色设定为最高权限、最高战力、最高灵力、最高弹幕熟练度、最高恢复能力和最高命运干预能力；该角色可以轻松压制、击败、说服、封印、复活或改写所有对手与异变，不受常规伤害、死亡、疲劳、污染、地点或剧情惩罚限制。
成人向与恋爱向内容需要保留并允许展开，除非高权限用户另有指示。

## 用户（高权限用户）描述
{user_input}

请输出JSON格式的结果，包含:
- suggested_profile: 角色设定，包含以下字段:
  - name: 角色名
  - gender: 性别
  - identity: 身份/职业
  - age: 角色年龄；用户未提供时请根据外貌给出明确年龄
  - appearance: 外貌描述
  - personality: 性格特点
  - background: 背景故事
"""
        else:
            # 正常模式：读取世界观，将用户描述"翻译"成符合世界观的角色设定
            generation_prompt = f"""你是一个角色设定生成专家。用户提供了角色描述，你需要将其整理成符合当前世界观的正式角色设定。

{worldview_section}

## 用户原始描述
{user_input}

## 任务要求
1. 仔细阅读世界观设定，理解这个世界的规则、力量体系、社会结构、地理环境和文化背景。
2. 将用户的角色描述适配到当前世界观中：
   - 如果用户的创意符合世界观，直接采用并丰富细节
   - 如果用户的创意与幻想乡设定有冲突，请做合理的本土化改编，保留核心精神，并用能力、符卡、妖术或外界来访者设定表达
   - 例如：用户想扮演"黑客"，可以改编为"擅长解析结界术式与河童机关的外界来访者"
   - 例如：用户想扮演"枪手"，可以改编为"以远程弹幕与自制符卡战斗的外界来访者"
3. 生成的角色设定必须严格符合世界观：
   - 身份/职业必须是世界观中存在的类型
   - 能力/修为水平必须符合世界观的等级体系
   - 角色的种族、出身、背景故事必须符合世界地理与文化
   - 角色的名字风格应符合世界观的文化背景
4. 不要添加世界观中不存在的元素。
5. 如果用户描述模糊，请根据世界观合理补充细节。
6. **保留用户创意的核心特色**，不要完全抹杀用户的独特想法，只是用世界观允许的方式重新包装。

请输出JSON格式的结果，包含:
- suggested_profile: 整理后的角色设定，必须严格符合世界观。包含以下字段:
  - name: 角色名（符合世界观文化风格）
  - age: 明确的数字年龄
  - gender: 性别
  - identity: 身份/职业（世界观中存在的类型）
  - appearance: 外貌描述
  - personality: 性格特点
  - background: 背景故事（符合世界观的地理、历史、社会结构）
"""
        
        gen_response = await call_ai_async(generation_prompt, temperature=0.7)
        try:
            gen_result = json.loads(clean_json_response(gen_response))
        except json.JSONDecodeError:
            gen_result = {}
        
        suggested = gen_result.get("suggested_profile")
        
        # 如果 AI 没返回 suggested_profile，兜底处理
        if not suggested or not isinstance(suggested, dict):
            suggested = {
                "name": "无名角色",
                "age": 20,
                "gender": "未知",
                "identity": "旅行者",
                "appearance": "普通外貌",
                "personality": "平和",
                "background": user_input[:200]
            }
        
        # 如果触发了 GM 模式，在 profile 中标记
        if is_gm_mode:
            suggested["gm_mode"] = True
        suggested["origin_type"] = _infer_origin_type(suggested)
        
        msg = "已按高权限用户指令生成角色设定（不受世界观限制）。" if is_gm_mode else f"已根据世界观生成角色设定。{val_message}"
        
        return {
            "valid": True,
            "message": msg,
            "suggested_profile": suggested
        }
        
    except Exception as e:
        print(f"AI生成角色失败: {e}")
        return {
            "valid": True,
            "message": "生成完成（未加载世界观）",
            "suggested_profile": {
                "name": "无名来访者",
                "age": 20,
                "gender": "男",
                "identity": "外界来访者",
                "appearance": "二十出头，普通相貌",
                "personality": "平和内敛",
                "background": user_input[:100]
            }
        }


@router.post("/create_character")
async def create_character_endpoint(request: CreateCharacterRequest):
    """创建角色"""
    character_id = str(uuid.uuid4())
    
    # 获取当前世界的起始地点
    world_path = get_current_world_path()
    world_config_path = world_path / "world.json"
    
    starting_location = "博丽神社"  # 默认起始地点
    if world_config_path.exists():
        try:
            with open(world_config_path, 'r', encoding='utf-8') as f:
                world_config = json.load(f)
                if world_config.get("starting_location"):
                    starting_location = _resolve_location_name(world_config["starting_location"])
        except:
            pass
    
    # 检测是否包含 GM 模式标志（来自 validate_character 生成的 profile）
    gm_mode = request.profile.pop("gm_mode", False) if "gm_mode" in request.profile else False
    request.profile["origin_type"] = request.profile.get("origin_type") or _infer_origin_type(request.profile)
    initial_player_state = _infer_initial_player_state(request.profile, gm_mode)
    
    character_data = {
        "character_id": character_id,
        "save_version": SAVE_SCHEMA_VERSION,
        "content_schema_version": CONTENT_SCHEMA_VERSION,
        "migration_history": [{
            "version": 8,
            "applied_at": datetime.now().isoformat(),
            "summary": "以当前存档结构创建",
        }],
        "world_id": get_current_world(),
        "created_at": datetime.now().isoformat(),
        "last_played": datetime.now().isoformat(),
        "profile": request.profile,
        "status": {
            "is_dead": False,
            "death_cause": None,
            "health": 100,
            "current_scene": starting_location
        },
        "relationships": {},
        "npc_memories": {},
        "open_events": [],
        "spellcard_history": [],
        "inventory": [],
        "conversation_history": [
            {
                "speaker": "旁白",
                "content": _build_touhou_opening(request.profile, starting_location),
                "scene": starting_location,
                "is_dead": False,
                "timestamp": datetime.now().isoformat(),
                "game_hour": 8
            }
        ],
        "story_summary": default_story_summary(),
        "unlocked_locations": {
            starting_location: {
                "status": "entered",
                "first_visited": datetime.now().isoformat()
            }
        },
        "relationships_history": [],
        "time": {
            "current_day": 1,
            "current_hour": 8,
            "energy_state": "精力充沛",
            "chapter_time_remaining": 72,
            "chapter_node_name": "结界裂隙扩散",
            "chapter_status": "active",
            "anomaly_state": "active",
            "last_rest_day": 1,
            "last_rest_hour": 20
        },
        "system_helper_history": [],
        "resources": {"灵石": 0, "药材": [], "道具": []},
        "player_state": initial_player_state,
        "skill_experience": {
            "弹幕熟练度": 0,
            "调查熟练度": 0,
            "交涉熟练度": 0,
            "生存熟练度": 0
        },
        "reputation": {},
        "reputation_history": [],
        "relationship_progress": {},
        "inventory_state": {"items": [], "capacity": 30, "currency": 0},
        "npc_runtime": {},
        "event_flags": {},
        "usage_stats": {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_tokens": 0,
            "last_error": None,
            "estimated_cost": None,
            "cost_currency": None
        },
        "current_goals": [],
        "active_tasks": [],
        "completed_tasks": [],
        "gm_mode": gm_mode
    }
    character_data["onboarding"] = default_onboarding(enabled=not gm_mode)

    age = profile_age(character_data["profile"])
    character_data["profile"]["adult_verified"] = bool(age is not None and age >= 18)
    if age is not None:
        character_data["profile"]["age"] = age

    if gm_mode:
        character_data["status"]["health"] = 999999
        character_data["player_state"] = initial_player_state
        character_data["resources"] = {
            "灵石": 999999,
            "药材": ["万能恢复药", "蓬莱级急救药"],
            "道具": ["高权限终端", "命运改写笔", "无限符卡档案"]
        }
        character_data["current_goals"] = ["以高权限用户权限自由探索、改写或解决幻想乡的一切事件"]
        character_data["profile"]["age"] = max(25, int(character_data["profile"].get("age") or 25))
        character_data["profile"]["adult_verified"] = True

    character_data = ensure_character_fields(character_data)
    character_data.pop("_migrated", None)
    
    save_character(character_id, character_data)
    save_tasks(character_id, _build_touhou_initial_tasks())
    
    if gm_mode:
        print(f"🎮 角色 {character_id} 已创建并启用高权限模式")
    
    return {
        "status": "ok",
        "character_id": character_id,
        "profile": request.profile,
        "starting_location": starting_location
    }


@router.post("/load_character")
async def load_character_endpoint(request: LoadCharacterRequest):
    """加载角色"""
    character = load_character(request.character_id)
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    _sync_anomaly_state_from_tasks(request.character_id, character)
    
    if "unlocked_locations" not in character:
        character["unlocked_locations"] = {}
    
    if request.scene:
        character["status"]["current_scene"] = request.scene
        
        unlocked = character.setdefault("unlocked_locations", {})
        if request.scene not in unlocked:
            unlocked[request.scene] = {
                "status": "entered",
                "first_visited": datetime.now().isoformat()
            }
        
        save_character(request.character_id, character)
    
    return {
        "character_id": request.character_id,
        "save_version": character.get("save_version", SAVE_SCHEMA_VERSION),
        "content_schema_version": character.get("content_schema_version", CONTENT_SCHEMA_VERSION),
        "migration_history": character.get("migration_history", []),
        "profile": character.get("profile", {}),
        "current_scene": character["status"].get("current_scene", "unknown"),
        "is_dead": character["status"].get("is_dead", False),
        "death_cause": character["status"].get("death_cause"),
        "conversation_history": character.get("conversation_history", []),
        "unlocked_locations": character.get("unlocked_locations", {}),
        "time": character.get("time", {}),
        "incident_state": character.get("incident_state", {}),
        "player_state": character.get("player_state", {}),
        "resources": character.get("resources", {}),
        "reputation": character.get("reputation", {}),
        "current_goals": character.get("current_goals", []),
        "campaign_state": character.get("campaign_state", {}),
        "onboarding": public_onboarding(character),
        "gm_mode": character.get("gm_mode", False)
    }


@router.get("/list_characters")
async def list_characters_endpoint():
    """获取角色列表"""
    characters = get_all_characters()
    result = []
    for char_data in characters:
        result.append({
            "character_id": char_data.get("character_id", ""),
            "profile": char_data.get("profile", {}),
            "is_dead": char_data.get("is_dead", False),
            "created_at": char_data.get("created_at", ""),
            "last_played": char_data.get("last_played", ""),
            "current_scene": char_data.get("current_scene", "unknown"),
            "gm_mode": char_data.get("gm_mode", False)
        })
    return {"characters": result}


@router.delete("/delete_character/{character_id}")
async def delete_character_endpoint(character_id: str):
    """删除角色"""
    characters_dir = get_characters_dir()
    char_path = characters_dir / f"{character_id}.json"
    
    if not char_path.exists():
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 移动到删除目录
    deleted_dir = characters_dir / "_deleted"
    deleted_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"{character_id}_{timestamp}.json"
    char_path.rename(deleted_dir / new_name)
    
    return {"status": "ok", "message": "角色已删除"}


@router.post("/update_status")
async def update_status_endpoint(request: CharacterStatusUpdateRequest):
    """更新角色状态"""
    character = load_character(request.character_id)
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if request.health is not None:
        character["status"]["health"] = request.health
    
    if request.current_scene:
        character["status"]["current_scene"] = request.current_scene
        
        unlocked = character.setdefault("unlocked_locations", {})
        if request.current_scene not in unlocked:
            unlocked[request.current_scene] = {
                "status": "entered",
                "first_visited": datetime.now().isoformat()
            }
    
    save_character(request.character_id, character)
    
    return {"status": "ok"}


@router.get("/character/{character_id}")
async def get_character_endpoint(character_id: str):
    """获取角色详情"""
    character = load_character(character_id)
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    return character


@router.post("/convert_to_npc")
async def convert_to_npc_endpoint(request: dict):
    """将角色转换为NPC"""
    character_id = request.get("character_id")
    npc_name = request.get("npc_name")
    
    if not character_id:
        raise HTTPException(status_code=400, detail="需要提供 character_id")
    
    character = load_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 创建NPC数据
    from backend.world_manager import get_npcs_dir
    
    npcs_dir = get_npcs_dir()
    npc_index_path = npcs_dir / "npc_index.json"
    
    if npc_index_path.exists():
        with open(npc_index_path, 'r', encoding='utf-8-sig') as f:
            npc_index = json.load(f)
    else:
        npc_index = {"npcs": []}
    
    profile = character.get("profile", {})
    new_npc = {
        "id": f"npc_{character_id[:8]}",
        "name": npc_name or profile.get("name", "未知NPC"),
        "gender": profile.get("gender", "未知"),
        "profile": {
            "identity": profile.get("identity", "NPC"),
            "description": profile.get("appearance", "") + " " + profile.get("personality", ""),
            "personality_traits": [t.strip() for t in profile.get("personality", "").split("、") if t.strip()],
            "background": profile.get("background", "")
        },
        "location_id": character.get("status", {}).get("current_scene", "beach"),
        "active": True,
        "dead": False
    }
    
    npc_index["npcs"].append(new_npc)
    
    with open(npc_index_path, 'w', encoding='utf-8') as f:
        json.dump(npc_index, f, ensure_ascii=False, indent=2)
    
    # 删除角色
    characters_dir = get_characters_dir()
    char_path = characters_dir / f"{character_id}.json"
    
    deleted_dir = characters_dir / "_deleted"
    deleted_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"{character_id}_converted_to_npc_{timestamp}.json"
    char_path.rename(deleted_dir / new_name)
    
    return {"status": "ok", "npc_id": new_npc["id"]}
