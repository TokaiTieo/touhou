"""Read-only save diagnostics and import preflight checks."""

import copy
import json
from pathlib import Path
from typing import Dict

from backend.services.save_migrations import LATEST_SAVE_VERSION


def inspect_character_payload(payload) -> Dict:
    errors = []
    warnings = []
    if not isinstance(payload, dict):
        return {
            "status": "critical",
            "errors": ["存档顶层不是 JSON 对象"],
            "warnings": [],
            "repairable": False,
        }
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        errors.append("缺少有效的 profile 对象")
    elif not str(profile.get("name") or "").strip():
        errors.append("角色资料缺少名称")
    if not str(payload.get("character_id") or "").strip():
        warnings.append("缺少 character_id，导入时将自动生成")
    for field in ("conversation_history", "spellcard_history", "open_events"):
        if field in payload and not isinstance(payload[field], list):
            warnings.append(f"{field} 类型异常，自动升级时将尝试修复")
    for field in ("status", "time", "player_state", "npc_memories"):
        if field in payload and not isinstance(payload[field], dict):
            warnings.append(f"{field} 类型异常，自动升级时将尝试修复")
    try:
        version = int(payload.get("save_version", 1) or 1)
    except (TypeError, ValueError):
        version = 1
        warnings.append("save_version 无效，将按旧版存档升级")
    if version < LATEST_SAVE_VERSION:
        warnings.append(f"旧版存档 v{version}，加载时将自动升级到 v{LATEST_SAVE_VERSION}")
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    return {
        "status": "critical" if errors else "warning" if warnings else "healthy",
        "errors": errors,
        "warnings": warnings,
        "repairable": not errors,
        "save_version": version,
        "target_save_version": LATEST_SAVE_VERSION,
        "history_count": len(payload.get("conversation_history", []))
        if isinstance(payload.get("conversation_history", []), list) else 0,
        "size_bytes": len(serialized.encode("utf-8")),
    }



REPAIRABLE_FIELD_DEFAULTS = {
    "conversation_history": [],
    "spellcard_history": [],
    "open_events": [],
    "status": {},
    "time": {},
    "player_state": {},
    "npc_memories": {},
}


def repair_character_payload_types(payload: Dict) -> Dict:
    """Repair known container types while preserving every invalid source value."""
    recovered = payload.setdefault("recovered_invalid_fields", {})
    repaired = []
    for field, default in REPAIRABLE_FIELD_DEFAULTS.items():
        value = payload.get(field)
        expected = list if isinstance(default, list) else dict
        if field not in payload or isinstance(value, expected):
            continue
        recovered.setdefault(field, copy.deepcopy(value))
        payload[field] = copy.deepcopy(default)
        repaired.append(field)
    if not recovered:
        payload.pop("recovered_invalid_fields", None)
    return {"payload": payload, "repaired_fields": repaired}


def inspect_character_file(path: Path) -> Dict:
    path = Path(path)
    report = {"path": path.name, "exists": path.exists()}
    if not path.exists():
        return {
            **report,
            "status": "critical",
            "errors": ["主存档文件不存在"],
            "warnings": [],
            "repairable": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            **report,
            "status": "critical",
            "errors": [f"主存档无法解析：{type(exc).__name__}"],
            "warnings": [],
            "repairable": False,
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }
    return {**report, **inspect_character_payload(payload), "payload": payload}
