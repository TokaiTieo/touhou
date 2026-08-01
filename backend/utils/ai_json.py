"""Shared cleanup helpers for model responses."""

import json
import re
from typing import Any


def clean_json_response(response: str) -> str:
    if not response:
        return "{}"
    cleaned = str(response).lstrip("\ufeff").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        cleaned = cleaned[first_brace:last_brace + 1]
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)


def safe_json_loads(response: str, default: Any = None):
    try:
        return json.loads(clean_json_response(response))
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default
