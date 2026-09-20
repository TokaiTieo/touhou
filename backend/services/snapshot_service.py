"""Character snapshot storage kept independent from world orchestration."""

import hashlib
import json
import uuid
import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from backend.services.storage_paths import contained_path, require_identifier, require_supported_save
from backend.services.conversation_archive_service import history_count


def snapshot_signature(data: Dict, tasks: Dict = None) -> str:
    ignored = {"last_saved_at", "last_played", "command_receipts", "_migrated"}
    marker = {"character": {key: value for key, value in data.items() if key not in ignored},
              "tasks": {key: value for key, value in (tasks or {}).items() if key != "last_updated"}}
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
    require_supported_save(data)
    signature = snapshot_signature(data, tasks)
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
            "label": label or f"对话节点 {history_count(data)}",
            "history_count": history_count(data),
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
    snapshot_path = contained_path(snapshots_dir, f"{require_identifier(snapshot_id)}.json")
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
    character = ensure_fields(copy.deepcopy(payload.get("character", {})))
    tasks = copy.deepcopy(payload.get("tasks") or default_tasks())
    target_id = character_id
    character["character_id"] = character_id
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
    character["command_receipts"] = []
    character["resolved_turn_ids"] = []
    character["turn_receipts"] = []
    character["timeline_epoch"] = uuid.uuid4().hex
    tasks["last_updated"] = datetime.now().isoformat()
    return {"target_id": target_id, "character": character, "tasks": tasks}
