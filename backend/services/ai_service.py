# backend/services/ai_service.py
# AI 调用服务 - 封装所有 AI 相关操作

import asyncio
import contextvars
import json
import os
import time
from dataclasses import dataclass
from functools import partial
from threading import Event, local
from typing import Callable, Optional
from openai import OpenAI
from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEFAULT_TEMPERATURE
from backend.utils.ai_json import clean_json_response, safe_json_loads
from backend.services.ai_diagnostics_service import classify_ai_error, missing_key_error
from backend.services.ai_provider_service import (
    DEFAULT_MODELS,
    normalize_base_url,
    normalize_models,
    provider_descriptor,
)

# AI 调用超时（秒）
AI_TIMEOUT = 60
E2E_MOCK_AI = os.environ.get("TOUHOU_E2E_MOCK_AI", "").lower() in ("1", "true", "yes")

# 支持默认列表与本地配置的兼容模型
_configured_models = os.environ.get("TOUHOU_AI_MODELS", "").strip()
AVAILABLE_MODELS = normalize_models(
    _configured_models.split(",") if _configured_models else DEFAULT_MODELS,
    DEEPSEEK_MODEL,
)


@dataclass
class AIStreamContext:
    on_chunk: Callable[[str], None]
    cancelled: Event


_stream_context = contextvars.ContextVar("ai_stream_context", default=None)
_last_usage_context = contextvars.ContextVar("last_ai_usage", default={})
_last_error_context = contextvars.ContextVar("last_ai_error", default={})
_last_runtime_context = contextvars.ContextVar("last_ai_runtime", default={})


def compress_prompt(prompt: str, max_chars: int = None):
    """Deterministically compact oversized prompts while preserving instructions."""
    text = str(prompt or "")
    limit = max_chars or int(os.environ.get("TOUHOU_MAX_PROMPT_CHARS", "48000") or 48000)
    limit = max(4000, limit)
    if len(text) <= limit:
        return text, {"compressed": False, "original_chars": len(text), "prompt_chars": len(text)}
    head_size = int(limit * 0.32)
    tail_size = int(limit * 0.56)
    middle_budget = max(200, limit - head_size - tail_size - 120)
    middle = text[head_size: len(text) - tail_size]
    anchors = [
        line.strip() for line in middle.splitlines()
        if line.strip().startswith(("##", "- ID:", "重要经历：", "尚未解决：", "关系要点："))
    ]
    anchor_text = "\n".join(anchors)
    if len(anchor_text) > middle_budget:
        anchor_text = anchor_text[:middle_budget]
    marker = "\n\n[中段上下文已由本地压缩，保留章节标题和关键索引]\n"
    compacted = text[:head_size] + marker + anchor_text + "\n\n" + text[-tail_size:]
    compacted = compacted[:limit]
    return compacted, {
        "compressed": True,
        "original_chars": len(text),
        "prompt_chars": len(compacted),
    }


def _mock_response(prompt: str) -> str:
    is_dialogue = "## 当前NPC信息" in prompt
    completes_incident = "完成结界裂隙" in prompt or "稳定博丽大结界" in prompt
    payload = {
        "description": "灵力沿着御札纹路稳定下来，周围的结界波纹逐渐恢复平静。",
        "time_cost": 0.5,
        "relationship_update": "博丽灵梦:友好(共同稳定结界)" if is_dialogue else None,
        "task_updates": ([{
            "action": "complete",
            "task_id": "main_touhou_rift_01",
            "info": "结界裂隙已经通过自由行动稳定。"
        }] if completes_incident else []),
        "memory_updates": ([{
            "npc_name": "博丽灵梦",
            "summary": "玩家与灵梦共同稳定了博丽神社附近的结界。",
            "tags": ["异变", "合作"],
            "importance": 8,
            "emotion": "信任"
        }] if is_dialogue else []),
        "open_event": None,
        "spellcard_result": None,
        "player_state_delta": {},
    }
    if is_dialogue:
        payload["exit_dialogue"] = False
        payload["description"] = "（灵梦收起御札，确认结界已经稳定）‘这次做得不错。之后有新动静，我会告诉你。’"
    else:
        payload["is_dead"] = False
        payload["new_location"] = None
    return json.dumps(payload, ensure_ascii=False)


def set_stream_context(on_chunk: Callable[[str], None], cancelled: Event):
    return _stream_context.set(AIStreamContext(on_chunk=on_chunk, cancelled=cancelled))


def reset_stream_context(token):
    _stream_context.reset(token)


class AIService:
    """AI 服务单例"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._usage_local = local()
        self._error_local = local()
        self._runtime_local = local()
        self._api_key = DEEPSEEK_API_KEY
        self._has_key = bool(self._api_key)
        self._base_url = normalize_base_url(DEEPSEEK_BASE_URL)
        self._available_models = list(AVAILABLE_MODELS)
        self.client = self._make_client()
        self._model = DEEPSEEK_MODEL if DEEPSEEK_MODEL in self._available_models else self._available_models[0]

    @property
    def last_usage(self):
        return dict(getattr(self._usage_local, "value", {}) or {})

    def _remember_usage(self, usage=None):
        if not usage:
            self._usage_local.value = {}
            return
        self._usage_local.value = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0)
        }

    @property
    def last_error(self):
        return dict(getattr(self._error_local, "value", {}) or {})

    def _remember_error(self, error=None):
        self._error_local.value = dict(error or {})

    @property
    def last_runtime(self):
        return dict(getattr(self._runtime_local, "value", {}) or {})

    def _remember_runtime(self, runtime=None):
        self._runtime_local.value = dict(runtime or {})
    
    def _make_client(self):
        if not self._has_key:
            return None
        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=AI_TIMEOUT,
            max_retries=0,
        )

    @property
    def model(self):
        return self._model

    @property
    def base_url(self):
        return getattr(self, "_base_url", normalize_base_url(DEEPSEEK_BASE_URL))

    @property
    def available_models(self):
        return list(getattr(self, "_available_models", AVAILABLE_MODELS))

    @property
    def provider(self):
        return provider_descriptor(self.base_url, self.available_models, self.model)

    def set_provider(self, base_url: str, models, model_name: str = "") -> bool:
        normalized_url = normalize_base_url(base_url)
        normalized_models = normalize_models(models, model_name or self.model)
        selected = str(model_name or self.model).strip()
        if selected not in normalized_models:
            selected = normalized_models[0]
        self._base_url = normalized_url
        self._available_models = normalized_models
        self._model = selected
        self.client = self._make_client()
        return True

    def set_model(self, model_name: str) -> bool:
        """动态切换模型"""
        if model_name in self.available_models:
            self._model = model_name
            print(f"🔄 AI 模型已切换为: {model_name}")
            return True
        print(f"⚠️ 不支持的模型: {model_name}，可用模型: {self.available_models}")
        return False
    
    def set_api_key(self, api_key: str) -> bool:
        """动态设置 API Key"""
        if api_key:
            self._api_key = api_key
            self._has_key = True
            self.client = self._make_client()
            print("🔄 API Key 已更新")
            return True
        return False
    
    def call(self, prompt: str, temperature: float = DEFAULT_TEMPERATURE) -> str:
        """调用 AI API（同步阻塞）"""
        if E2E_MOCK_AI:
            self._remember_error()
            result = _mock_response(prompt)
            self._usage_local.value = {
                "prompt_tokens": max(1, len(prompt) // 3),
                "completion_tokens": max(1, len(result) // 3),
                "total_tokens": max(2, (len(prompt) + len(result)) // 3),
            }
            self._remember_runtime({
                "requested_model": self.model,
                "used_model": self.model,
                "attempts": 1,
                "fallback_used": False,
                "compressed": False,
                "original_chars": len(prompt),
                "prompt_chars": len(prompt),
            })
            return result
        if not self.client:
            self._remember_usage()
            error = missing_key_error()
            self._remember_error(error)
            self._remember_runtime({"attempts": 0, "fallback_used": False, "error_code": error["code"]})
            return f"【系统提示】{error['message']}"
        compacted, compression = compress_prompt(prompt)
        requested_model = self.model
        configured_fallback = os.environ.get("DEEPSEEK_FALLBACK_MODEL", "").strip()
        fallbacks = [configured_fallback] if configured_fallback in self.available_models else []
        fallbacks.extend(model for model in self.available_models if model != requested_model and model not in fallbacks)
        models = [requested_model] + fallbacks
        max_attempts = max(1, min(4, int(os.environ.get("TOUHOU_AI_MAX_ATTEMPTS", "2") or 2)))
        attempts = []
        final_error = None
        for model_index, model_name in enumerate(models):
            for attempt in range(1, max_attempts + 1):
                try:
                    self._remember_error()
                    response = self.client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": compacted}],
                        temperature=temperature,
                        timeout=AI_TIMEOUT,
                    )
                    self._remember_usage(getattr(response, "usage", None))
                    attempts.append({"model": model_name, "attempt": attempt, "status": "ok"})
                    self._remember_runtime({
                        **compression,
                        "requested_model": requested_model,
                        "used_model": model_name,
                        "attempts": len(attempts),
                        "attempt_log": attempts,
                        "fallback_used": model_index > 0,
                    })
                    return response.choices[0].message.content
                except Exception as exc:
                    final_error = classify_ai_error(exc)
                    attempts.append({
                        "model": model_name,
                        "attempt": attempt,
                        "status": "error",
                        "code": final_error["code"],
                    })
                    retryable = final_error["code"] in ("rate_limit", "timeout", "network", "unknown")
                    if retryable and attempt < max_attempts:
                        time.sleep(min(1.5, 0.25 * (2 ** (attempt - 1))))
                        continue
                    break
            if final_error and final_error["code"] in ("authentication", "quota", "missing_key"):
                break
        self._remember_usage()
        final_error = final_error or classify_ai_error("unknown")
        self._remember_error(final_error)
        self._remember_runtime({
            **compression,
            "requested_model": requested_model,
            "used_model": attempts[-1]["model"] if attempts else requested_model,
            "attempts": len(attempts),
            "attempt_log": attempts,
            "fallback_used": any(item["model"] != requested_model for item in attempts),
            "error_code": final_error["code"],
        })
        print(f"AI调用失败: {final_error['code']} ({len(attempts)} attempts)")
        return f"【AI调用失败】{final_error['message']}"
    
    def call_json(self, prompt: str, temperature: float = DEFAULT_TEMPERATURE, default=None):
        """调用 AI 并返回 JSON 对象"""
        response = self.call(prompt, temperature)
        return safe_json_loads(response, default)

    def stream(self, prompt: str, temperature: float = DEFAULT_TEMPERATURE):
        """流式调用 AI API，逐块返回文本。"""
        if E2E_MOCK_AI:
            self._remember_error()
            result = _mock_response(prompt)
            self._usage_local.value = {
                "prompt_tokens": max(1, len(prompt) // 3),
                "completion_tokens": max(1, len(result) // 3),
                "total_tokens": max(2, (len(prompt) + len(result)) // 3),
            }
            for index in range(0, len(result), 24):
                yield result[index:index + 24]
            self._remember_runtime({
                "requested_model": self.model, "used_model": self.model,
                "attempts": 1, "fallback_used": False, "compressed": False,
                "original_chars": len(prompt), "prompt_chars": len(prompt),
            })
            return
        if not self.client:
            self._remember_usage()
            error = missing_key_error()
            self._remember_error(error)
            self._remember_runtime({
                "requested_model": self.model,
                "used_model": None,
                "attempts": 0,
                "fallback_used": False,
                "error_code": error["code"],
            })
            yield f"【系统提示】{error['message']}"
            return
        compacted, compression = compress_prompt(prompt)
        requested_model = self.model
        configured_fallback = os.environ.get("DEEPSEEK_FALLBACK_MODEL", "").strip()
        fallbacks = [configured_fallback] if configured_fallback in self.available_models else []
        fallbacks.extend(model for model in self.available_models if model != requested_model and model not in fallbacks)
        models = [requested_model] + fallbacks
        max_attempts = max(1, min(4, int(os.environ.get("TOUHOU_AI_MAX_ATTEMPTS", "2") or 2)))
        attempts = []
        error = classify_ai_error("unknown")
        partial_output = False
        for model_index, model_name in enumerate(models):
            for attempt in range(1, max_attempts + 1):
                emitted = False
                try:
                    self._remember_usage()
                    self._remember_error()
                    request_options = {
                        "model": model_name,
                        "messages": [{"role": "user", "content": compacted}],
                        "temperature": temperature,
                        "timeout": AI_TIMEOUT,
                        "stream": True,
                    }
                    try:
                        response = self.client.chat.completions.create(
                            **request_options,
                            stream_options={"include_usage": True},
                        )
                    except Exception as exc:
                        if "stream_options" not in str(exc).lower():
                            raise
                        response = self.client.chat.completions.create(**request_options)
                    for chunk in response:
                        if getattr(chunk, "usage", None):
                            self._remember_usage(chunk.usage)
                        delta = chunk.choices[0].delta.content if chunk.choices else ""
                        if delta:
                            emitted = True
                            yield delta
                    attempts.append({"model": model_name, "attempt": attempt, "status": "ok"})
                    self._remember_runtime({
                        **compression,
                        "requested_model": requested_model,
                        "used_model": model_name,
                        "attempts": len(attempts),
                        "attempt_log": attempts,
                        "fallback_used": model_index > 0,
                    })
                    return
                except Exception as exc:
                    error = classify_ai_error(exc)
                    attempts.append({
                        "model": model_name,
                        "attempt": attempt,
                        "status": "error",
                        "code": error["code"],
                    })
                    if emitted:
                        partial_output = True
                        break
                    retryable = error["code"] in ("rate_limit", "timeout", "network", "unknown")
                    if retryable and attempt < max_attempts:
                        time.sleep(min(1.5, 0.25 * (2 ** (attempt - 1))))
                        continue
                    break
            if partial_output or error["code"] in ("authentication", "quota", "missing_key"):
                break
        self._remember_usage()
        self._remember_error(error)
        self._remember_runtime({
            **compression,
            "requested_model": requested_model,
            "used_model": attempts[-1]["model"] if attempts else requested_model,
            "attempts": len(attempts),
            "attempt_log": attempts,
            "fallback_used": any(item["model"] != requested_model for item in attempts),
            "error_code": error["code"],
            "partial_output": partial_output,
        })
        if not partial_output:
            yield f"【AI调用失败】{error['message']}"

    def call_streaming(
        self,
        prompt: str,
        temperature: float,
        on_chunk: Callable[[str], None],
        cancelled: Optional[Event] = None
    ) -> str:
        """Stream model output to a callback while retaining the complete response."""
        parts = []
        for chunk in self.stream(prompt, temperature):
            if cancelled and cancelled.is_set():
                break
            parts.append(chunk)
            on_chunk(chunk)
        return "".join(parts)
    
    def clean_json(self, response: str) -> str:
        """清理 JSON 响应"""
        return clean_json_response(response)


# 全局单例
ai_service = AIService()


def call_ai(prompt: str, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """便捷函数：调用 AI（同步）"""
    return ai_service.call(prompt, temperature)


async def call_ai_async(prompt: str, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """便捷函数：异步调用 AI（在线程池中执行，不阻塞事件循环，带总超时保护）"""
    loop = asyncio.get_event_loop()
    stream_context = _stream_context.get()
    caller = ai_service.call
    args = (prompt, temperature)
    if stream_context:
        caller = partial(
            ai_service.call_streaming,
            on_chunk=stream_context.on_chunk,
            cancelled=stream_context.cancelled
        )
    def call_and_capture():
        result = caller(*args)
        return result, ai_service.last_usage, ai_service.last_error, ai_service.last_runtime

    try:
        result, usage, error, runtime = await asyncio.wait_for(
            loop.run_in_executor(None, call_and_capture),
            timeout=AI_TIMEOUT + 5
        )
    except asyncio.TimeoutError:
        usage = {}
        error = classify_ai_error("timeout")
        runtime = {"attempts": 1, "error_code": "timeout"}
        result = f"【AI调用失败】{error['message']}"
    _last_usage_context.set(usage)
    _last_error_context.set(error)
    _last_runtime_context.set(runtime)
    return result


def get_last_ai_usage():
    """Return usage for the most recent AI call in the current request context."""
    return dict(_last_usage_context.get() or {})


def get_last_ai_error():
    """Return the classified error for the most recent AI call."""
    return dict(_last_error_context.get() or {})


def get_last_ai_runtime():
    return dict(_last_runtime_context.get() or {})


def call_ai_json(prompt: str, temperature: float = DEFAULT_TEMPERATURE, default=None):
    """便捷函数：调用 AI 并返回 JSON"""
    return ai_service.call_json(prompt, temperature, default)


def stream_ai(prompt: str, temperature: float = DEFAULT_TEMPERATURE):
    """便捷函数：流式调用 AI"""
    return ai_service.stream(prompt, temperature)


# 注意：这里不要重复定义 clean_json_response，使用上面的函数即可
