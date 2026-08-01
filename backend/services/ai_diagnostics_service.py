"""Player-safe AI failure classification and local usage summaries."""

import os
from datetime import datetime
from typing import Any, Dict


ERROR_MESSAGES = {
    "missing_key": "尚未配置 API Key，请在设置中填写后重试。",
    "authentication": "API Key 无效或已失效，请在设置中重新填写。",
    "rate_limit": "请求过于频繁，服务暂时限流，请稍后重试。",
    "quota": "API 账户额度不足，请检查服务商账户余额。",
    "timeout": "AI 响应超时，请检查网络后重试。",
    "network": "无法连接 AI 服务，请检查网络与代理设置。",
    "model": "当前模型暂不可用，请在设置中切换模型。",
    "response_format": "AI 返回格式异常，本次行动未写入存档，请重试。",
    "unknown": "AI 服务暂时不可用，请稍后重试。",
}


def classify_ai_error(error: Any) -> Dict[str, str]:
    """Map provider exceptions to stable, non-sensitive player messages."""
    text = str(error or "").strip()
    lower = text.lower()
    if not text:
        code = "unknown"
    elif any(word in lower for word in ("api key", "api_key", "unauthorized", "authentication", "401")):
        code = "authentication"
    elif any(word in lower for word in ("insufficient", "balance", "quota", "billing", "402")):
        code = "quota"
    elif any(word in lower for word in ("rate limit", "too many requests", "429")):
        code = "rate_limit"
    elif any(word in lower for word in ("timeout", "timed out", "deadline")):
        code = "timeout"
    elif any(word in lower for word in ("connection", "network", "dns", "proxy", "ssl", "socket")):
        code = "network"
    elif any(word in lower for word in ("model", "not found", "404")):
        code = "model"
    else:
        code = "unknown"
    return {"code": code, "message": ERROR_MESSAGES[code]}


def missing_key_error() -> Dict[str, str]:
    return {"code": "missing_key", "message": ERROR_MESSAGES["missing_key"]}


def response_format_error() -> Dict[str, str]:
    return {"code": "response_format", "message": ERROR_MESSAGES["response_format"]}


def update_usage_stats(
    character: Dict,
    usage: Dict[str, Any],
    estimated_tokens: int,
    model: str,
    error: Dict[str, str] | None = None,
) -> Dict:
    stats = character.setdefault("usage_stats", {})
    stats["requests"] = int(stats.get("requests", 0) or 0) + 1
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        stats[key] = int(stats.get(key, 0) or 0) + int(usage.get(key, 0) or 0)
    stats["estimated_tokens"] = int(stats.get("estimated_tokens", 0) or 0) + max(0, int(estimated_tokens or 0))
    stats["last_error"] = error or None
    stats["last_model"] = model
    stats["last_request_at"] = datetime.now().isoformat()

    def price(name: str) -> float:
        try:
            return max(0.0, float(os.environ.get(name, "0") or 0))
        except (TypeError, ValueError):
            return 0.0

    input_price = price("TOUHOU_INPUT_PRICE_PER_MILLION")
    output_price = price("TOUHOU_OUTPUT_PRICE_PER_MILLION")
    if input_price > 0 or output_price > 0:
        stats["estimated_cost"] = round(
            stats["prompt_tokens"] * input_price / 1_000_000
            + stats["completion_tokens"] * output_price / 1_000_000,
            6,
        )
        stats["cost_currency"] = os.environ.get("TOUHOU_COST_CURRENCY", "CNY")
    else:
        stats["estimated_cost"] = None
        stats["cost_currency"] = None
    return stats


def public_usage_summary(character: Dict) -> Dict:
    stats = dict(character.get("usage_stats", {}) or {})
    return {
        "requests": int(stats.get("requests", 0) or 0),
        "prompt_tokens": int(stats.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(stats.get("completion_tokens", 0) or 0),
        "total_tokens": int(stats.get("total_tokens", 0) or 0),
        "estimated_tokens": int(stats.get("estimated_tokens", 0) or 0),
        "estimated_cost": stats.get("estimated_cost"),
        "cost_currency": stats.get("cost_currency"),
        "last_model": stats.get("last_model", ""),
        "last_request_at": stats.get("last_request_at"),
        "last_error": stats.get("last_error"),
    }
