"""Validation and display metadata for OpenAI-compatible providers."""

from typing import Iterable, List
from urllib.parse import urlparse


DEFAULT_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]


def normalize_base_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if any(ord(character) < 32 for character in url):
        raise ValueError("接口地址不能包含控制字符")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("接口地址必须是有效的 HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("接口地址中不能包含账号或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("接口地址中不能包含查询参数或片段")
    return url


def normalize_models(values: Iterable[str], current_model: str = "") -> List[str]:
    if isinstance(values, str):
        values = values.replace("，", ",").split(",")
    models = []
    for value in values or []:
        name = str(value or "").strip()
        if not name or name in models:
            continue
        if any(ord(character) < 32 for character in name):
            raise ValueError("模型名称不能包含控制字符")
        if len(name) > 160:
            raise ValueError("模型名称不能超过 160 个字符")
        models.append(name)
    current = str(current_model or "").strip()
    if current and current not in models:
        models.insert(0, current)
    if not models:
        raise ValueError("至少需要配置一个模型")
    return models[:20]


def provider_descriptor(base_url: str, models: Iterable[str], current_model: str) -> dict:
    normalized_url = normalize_base_url(base_url)
    normalized_models = normalize_models(models, current_model)
    host = (urlparse(normalized_url).hostname or "").lower()
    selected_model = str(current_model or "").strip()
    if selected_model not in normalized_models:
        selected_model = normalized_models[0]
    return {
        "name": "DeepSeek" if host.endswith("deepseek.com") else "自定义兼容服务",
        "protocol": "openai_compatible",
        "base_url": normalized_url,
        "models": normalized_models,
        "current_model": selected_model,
        "is_custom": not host.endswith("deepseek.com"),
    }
