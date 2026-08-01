"""Auditable, idempotent artifacts for automatic save upgrades."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable


def _version(data: Dict) -> int:
    try:
        return int(data.get("save_version", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _field_paths(data, prefix: str = "") -> Iterable[str]:
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        yield path
        if isinstance(value, dict):
            yield from _field_paths(value, path)


def _write_once(path: Path, data: Dict) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_upgrade_artifacts(
    characters_dir: Path,
    character_id: str,
    before: Dict,
    after: Dict,
) -> Dict:
    """Write one immutable backup/report pair for a distinct source payload."""
    canonical = json.dumps(before, ensure_ascii=False, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    source_version = _version(before)
    target_version = _version(after)
    artifact_dir = characters_dir / "_migrations" / character_id
    stem = f"v{source_version}_to_v{target_version}_{fingerprint}"
    backup_path = artifact_dir / f"{stem}.backup.json"
    report_path = artifact_dir / f"{stem}.report.json"

    before_paths = set(_field_paths(before))
    after_paths = set(_field_paths(after))
    before_history = before.get("migration_history", [])
    after_history = after.get("migration_history", [])
    added_history = [
        item for item in after_history
        if isinstance(item, dict) and item not in before_history
    ]
    report = {
        "report_version": 1,
        "character_id": character_id,
        "source_save_version": source_version,
        "target_save_version": target_version,
        "source_fingerprint": fingerprint,
        "created_at": datetime.now().isoformat(),
        "backup_file": backup_path.name,
        "added_fields": sorted(after_paths - before_paths),
        "removed_fields": sorted(before_paths - after_paths),
        "preserved_source_fields": sorted(before_paths & after_paths),
        "migration_history_added": added_history,
    }
    _write_once(backup_path, before)
    _write_once(report_path, report)
    return report
