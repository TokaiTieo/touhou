"""AI model and encrypted local credential settings."""

import logging

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from backend.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    ENV_PATH,
    SECRET_PATH,
)
from backend.services.ai_service import AVAILABLE_MODELS, ai_service
from backend.services.ai_diagnostics_service import public_usage_summary
from backend.services.memory_retrieval import semantic_backend_status
from backend.services.turn_workflow import (
    clear_all_turn_checkpoints,
    get_checkpoint_metrics,
)
from backend.utils.secret_store import load_secret, save_secret
from backend.world_manager import load_character


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/get_model")
async def get_model():
    return {"current_model": ai_service.model, "available_models": AVAILABLE_MODELS}


@router.get("/diagnostics")
async def diagnostics(character_id: str = ""):
    if not character_id:
        return {"usage": None, "message": "进入角色后将显示本存档的 AI 用量。"}
    character = load_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    result = {
        "usage": public_usage_summary(character),
        "message": "费用仅在开发者配置本地计费单价后估算。",
    }
    if character.get("gm_mode") is True:
        result["memory_backend"] = semantic_backend_status()
    return result


@router.get("/turn_recovery")
async def turn_recovery():
    """Expose only local cache counts; prompts and responses are never returned."""
    return await get_checkpoint_metrics()


@router.post("/clear_turn_recovery")
async def clear_turn_recovery():
    result = await clear_all_turn_checkpoints()
    return {
        "status": "ok",
        **result,
        "message": "本地回合恢复数据已清除，角色存档未受影响。",
    }


@router.post("/set_model")
async def set_model(request: dict):
    model_name = request.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="缺少 model 参数")
    if model_name not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的模型: {model_name}")
    if not ai_service.set_model(model_name):
        raise HTTPException(status_code=500, detail="模型切换失败")
    return {"status": "ok", "model": model_name, "message": f"已切换到 {model_name}"}


@router.post("/test_ai_with_key")
async def test_ai_with_key(request: dict):
    api_key = str(request.get("api_key") or "").strip()
    model = request.get("model", ai_service.model)
    if not api_key:
        return {"success": False, "message": "未提供 API Key"}
    if model not in AVAILABLE_MODELS:
        return {"success": False, "message": "不支持的模型"}
    try:
        client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=30, max_retries=1)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请回复：OK"}],
            temperature=0.2
        )
        success = bool(response.choices and response.choices[0].message.content)
        return {"success": success, "message": "连接成功" if success else "API 返回异常", "model": model}
    except Exception as exc:
        logger.warning("API Key connection test failed: %s", type(exc).__name__)
        return {"success": False, "message": "连接失败，请检查 Key、网络与模型设置"}


@router.get("/get_api_key")
async def get_api_key():
    api_key = load_secret(SECRET_PATH) or DEEPSEEK_API_KEY or ""
    if not api_key and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    if len(api_key) > 15:
        masked = api_key[:6] + "..." + api_key[-4:]
    elif api_key:
        masked = api_key[:3] + "***"
    else:
        masked = ""
    return {"has_key": bool(api_key), "masked_key": masked, "model": ai_service.model}


@router.post("/update_api_key")
async def update_api_key(request: dict):
    new_api_key = str(request.get("api_key") or "").strip()
    if not new_api_key:
        raise HTTPException(status_code=400, detail="缺少 API Key")
    save_secret(SECRET_PATH, new_api_key)
    lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if ENV_PATH.exists() else []
    lines = [line for line in lines if not line.startswith("DEEPSEEK_API_KEY=")]
    lines.insert(0, "DEEPSEEK_API_KEY=")
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ai_service.set_api_key(new_api_key)
    logger.info("Encrypted API Key updated")
    return {"status": "ok", "message": "API Key 已加密保存并生效"}
