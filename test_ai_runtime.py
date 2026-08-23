import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.ai_service import AIService, compress_prompt
from backend.services.ai_provider_service import normalize_base_url, normalize_models


class _FakeCompletions:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responder(kwargs, len(self.calls))


def _response(content="完成"):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _stream_response(*parts):
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=part))],
            usage=None,
        )
        for part in parts
    ]
    chunks.append(SimpleNamespace(choices=[], usage=SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=4,
        total_tokens=14,
    )))
    return chunks


def _service(responder):
    service = object.__new__(AIService)
    service._initialized = True
    service._usage_local = __import__("threading").local()
    service._error_local = __import__("threading").local()
    service._runtime_local = __import__("threading").local()
    service._has_key = True
    service._api_key = "test-key"
    service._base_url = "https://api.deepseek.com"
    service._available_models = ["deepseek-v4-flash", "deepseek-v4-pro"]
    completions = _FakeCompletions(responder)
    service.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    service._model = "deepseek-v4-flash"
    return service, completions


class AIRuntimeTests(unittest.TestCase):
    def test_prompt_compression_preserves_instructions_and_recent_tail(self):
        prompt = "开头规则\n" + ("中段资料\n" * 1800) + "最近行动与硬性输出规则"
        compacted, report = compress_prompt(prompt, max_chars=5000)
        self.assertTrue(report["compressed"])
        self.assertLessEqual(len(compacted), 5000)
        self.assertTrue(compacted.startswith("开头规则"))
        self.assertIn("中段上下文已由本地压缩", compacted)
        self.assertTrue(compacted.endswith("最近行动与硬性输出规则"))

    def test_retry_keeps_requested_model_when_second_attempt_succeeds(self):
        def responder(_kwargs, call_number):
            if call_number == 1:
                raise TimeoutError("request timeout")
            return _response("重试成功")

        service, calls = _service(responder)
        with patch.dict(os.environ, {"TOUHOU_AI_MAX_ATTEMPTS": "2"}, clear=False), patch(
            "backend.services.ai_service.time.sleep"
        ):
            result = service.call("测试")
        self.assertEqual(result, "重试成功")
        self.assertEqual(len(calls.calls), 2)
        self.assertEqual(service.last_runtime["attempts"], 2)
        self.assertFalse(service.last_runtime["fallback_used"])

    def test_fallback_model_is_recorded_without_losing_usage(self):
        def responder(kwargs, _call_number):
            if kwargs["model"] == "deepseek-v4-flash":
                raise ValueError("model not found")
            return _response("备用模型成功")

        service, calls = _service(responder)
        with patch.dict(os.environ, {"TOUHOU_AI_MAX_ATTEMPTS": "1"}, clear=False):
            result = service.call("测试")
        self.assertEqual(result, "备用模型成功")
        self.assertEqual([item["model"] for item in calls.calls], [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ])
        self.assertEqual(service.last_runtime["used_model"], "deepseek-v4-pro")
        self.assertTrue(service.last_runtime["fallback_used"])
        self.assertEqual(service.last_usage["total_tokens"], 14)

    def test_stream_retries_before_any_text_is_emitted(self):
        def responder(_kwargs, call_number):
            if call_number == 1:
                raise TimeoutError("request timeout")
            return _stream_response("流式", "成功")

        service, calls = _service(responder)
        with patch.dict(os.environ, {"TOUHOU_AI_MAX_ATTEMPTS": "2"}, clear=False), patch(
            "backend.services.ai_service.time.sleep"
        ):
            result = "".join(service.stream("测试"))
        self.assertEqual(result, "流式成功")
        self.assertEqual(len(calls.calls), 2)
        self.assertEqual(service.last_runtime["attempts"], 2)
        self.assertFalse(service.last_runtime["fallback_used"])


    def test_provider_rejects_control_character_injection(self):
        from backend.services.ai_provider_service import provider_descriptor

        with self.assertRaises(ValueError):
            provider_descriptor("https://api.example.com\nINJECTED=1", ["model-a"], "model-a")
        with self.assertRaises(ValueError):
            provider_descriptor("https://api.example.com", ["model-a\nINJECTED=1"], "model-a")

    def test_provider_validation_and_dynamic_model_selection(self):
        self.assertEqual(normalize_base_url("https://example.test/v1/"), "https://example.test/v1")
        self.assertEqual(normalize_models(["model-a", "model-a"], "model-b"), ["model-b", "model-a"])
        with self.assertRaises(ValueError):
            normalize_base_url("file:///tmp/model")
        service, _calls = _service(lambda _kwargs, _count: _response())
        with patch("backend.services.ai_service.OpenAI", return_value=service.client):
            self.assertTrue(service.set_provider("https://example.test/v1", ["model-a", "model-b"], "model-b"))
        self.assertEqual(service.model, "model-b")
        self.assertEqual(service.available_models, ["model-a", "model-b"])
        self.assertTrue(service.provider["is_custom"])


if __name__ == "__main__":
    unittest.main()
