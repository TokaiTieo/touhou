"""Character snapshot storage kept independent from world orchestration."""

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def snapshot_signature(data: Dict) -> str:
    history = data.get("conversation_history", []) or []
    if not isinstance(history, list):
        history = []
    status = data.get("status", {}) or {}
    if not isinstance(status, dict):
        status = {}
    marker = {
        "history_count": len(history),
        "last_message": history[-1] if history else None,
        "scene": status.get("current_scene"),
        "is_dead": status.get("is_dead"),
    }
    raw = json.dumps(marker, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def create_snapshot(
    character_id: str,
    data: Dict,
    snapshots_dir: Path,
    tasks: Dict,
    atomic_write: Callable[[Path, Any], None],
    *,
    save_version: int,
    max_snapshots: int = 40,
    label: Optional[str] = None,
    force: bool = False,
) -> Optional[Dict]:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    signature = snapshot_signature(data)
    existing = sorted(
        snapshots_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    if existing and not force:
        try:
            with open(existing[0], "r", encoding="utf-8") as handle:
                if json.load(handle).get("metadata", {}).get("signature") == signature:
                    return None
        except (OSError, json.JSONDecodeError):
            pass

    now = datetime.now()
    snapshot_id = now.strftime("%Y%m%d_%H%M%S_%f")
    history = data.get("conversation_history", []) or []
    if not isinstance(history, list):
        history = []
    status = data.get("status", {}) or {}
    if not isinstance(status, dict):
        status = {}
    payload = {
        "metadata": {
            "snapshot_id": snapshot_id,
            "character_id": character_id,
            "created_at": now.isoformat(),
            "label": label or f"对话节点 {len(history)}",
            "history_count": len(history),
            "scene": status.get("current_scene", "未知"),
            "signature": signature,
            "save_version": data.get("save_version", save_version),
        },
        "character": data,
        "tasks": tasks,
    }
    atomic_write(snapshots_dir / f"{snapshot_id}.json", payload)
    for old_path in existing[max(0, max_snapshots - 1):]:
        try:
            old_path.unlink()
        except OSError:
            pass
    return payload["metadata"]


def list_snapshots(snapshots_dir: Path) -> List[Dict]:
    snapshots = []
    for path in snapshots_dir.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle).get("metadata", {})
            if metadata:
                snapshots.append(metadata)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(snapshots, key=lambda item: item.get("created_at", ""), reverse=True)


def load_snapshot(snapshots_dir: Path, snapshot_id: str) -> Dict:
    snapshot_path = snapshots_dir / f"{snapshot_id}.json"
    if not snapshot_path.exists():
        raise FileNotFoundError("存档快照不存在")
    with open(snapshot_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload.get("character"), dict):
        raise ValueError("存档快照缺少角色数据")
    return payload


def prepare_restore_payload(
    character_id: str,
    payload: Dict,
    ensure_fields: Callable[[Dict], Dict],
    default_tasks: Callable[[], Dict],
    *,
    branch: bool = False,
    branch_name: Optional[str] = None,
    snapshot_id: str = "",
) -> Dict:
    character = ensure_fields(payload.get("character", {}))
    tasks = payload.get("tasks") or default_tasks()
    target_id = character_id
    if branch:
        target_id = str(uuid.uuid4())
        character["character_id"] = target_id
        profile = character.setdefault("profile", {})
        profile["name"] = str(branch_name or f"{profile.get('name', '角色')} · 分支").strip()
        character["created_at"] = datetime.now().isoformat()
        character["branch_origin"] = {
            "character_id": character_id,
            "snapshot_id": snapshot_id,
        }
    character.pop("_migrated", None)
    tasks["last_updated"] = datetime.now().isoformat()
    return {"target_id": target_id, "character": character, "tasks": tasks}
