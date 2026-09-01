"""Turn timing summaries and privacy-safe diagnostic bundles."""

import hashlib
from datetime import datetime
from typing import Any, Dict


SENSITIVE_KEYS = {
    "api_key", "authorization", "secret", "prompt_preview", "response_preview",
    "conversation_history", "npc_memories", "system_helper_history",
}


def phase_durations_ms(phase_timestamps: Dict[str, float]) -> Dict[str, float]:
    ordered = sorted(
        ((name, float(value)) for name, value in (phase_timestamps or {}).items()),
        key=lambda item: item[1],
    )
    result = {}
    for index, (name, started) in enumerate(ordered):
        ended = ordered[index + 1][1] if index + 1 < len(ordered) else started
        result[name] = round(max(0, ended - started) * 1000, 2)
    return result


def record_turn_diagnostics(character: Dict, status, model_runtime: Dict = None) -> Dict:
    timestamps = dict(getattr(status, "phase_timestamps", {}) or {})
    created = float(getattr(status, "created_at", 0) or 0)
    updated = float(getattr(status, "updated_at", created) or created)
    entry = {
        "turn_id": getattr(status, "turn_id", None),
        "kind": getattr(status, "kind", None),
        "state": getattr(status, "state", None),
        "total_ms": round(max(0, updated - created) * 1000, 2),
        "phases_ms": phase_durations_ms(timestamps),
        "model_ms": (model_runtime or {}).get("elapsed_ms"),
        "attempts": int((model_runtime or {}).get("attempts", 0) or 0),
        "fallback_used": bool((model_runtime or {}).get("fallback_used")),
        "error_code": (model_runtime or {}).get("error_code"),
        "recorded_at": datetime.now().isoformat(),
    }
    history = character.setdefault("turn_diagnostics_history", [])
    if not any(item.get("turn_id") == entry["turn_id"] for item in history if isinstance(item, dict)):
        history.append(entry)
        character["turn_diagnostics_history"] = history[-120:]
    return entry


def diagnostics_summary(character: Dict) -> Dict:
    items = [item for item in character.get("turn_diagnostics_history", []) if isinstance(item, dict)]
    totals = sorted(float(item.get("total_ms", 0) or 0) for item in items)

    def percentile(ratio: float):
        if not totals:
            return None
        return round(totals[min(len(totals) - 1, int((len(totals) - 1) * ratio))], 2)

    return {
        "turns": len(items),
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "fallbacks": sum(1 for item in items if item.get("fallback_used")),
        "failures": sum(1 for item in items if item.get("error_code")),
        "recent": items[-12:],
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[已清除]" if str(key).lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def build_diagnostic_bundle(character: Dict, tasks: Dict, app_version: str) -> Dict:
    character_id = str(character.get("character_id") or "")
    payload = {
        "generated_at": datetime.now().isoformat(),
        "app_version": app_version,
        "save_version": character.get("save_version"),
        "content_schema_version": character.get("content_schema_version"),
        "character_ref": hashlib.sha256(character_id.encode("utf-8")).hexdigest()[:12],
        "scene": character.get("status", {}).get("current_scene"),
        "usage": character.get("usage_stats", {}),
        "model_runtime": character.get("model_runtime", {}),
        "turns": diagnostics_summary(character),
        "memory_maintenance": character.get("memory_maintenance", {}),
        "save_counts": {
            "messages": len(character.get("conversation_history", []) or []),
            "memories": sum(len(items) for items in (character.get("npc_memories", {}) or {}).values() if isinstance(items, list)),
            "active_tasks": len(tasks.get("active_tasks", []) or []),
            "completed_tasks": len(tasks.get("completed_tasks", []) or []),
        },
    }
    return _redact(payload)
