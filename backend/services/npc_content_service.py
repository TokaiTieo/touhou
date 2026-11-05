"""Patch known erroneous built-in fields without replacing player-authored data."""

import copy
import hashlib
import json
from pathlib import Path
import threading


_UPGRADE_LOCK = threading.RLock()


def _patch_fields(record, fields):
    for key, patch in fields.items():
        if key not in record or record[key] in patch["previous"]:
            record[key] = copy.deepcopy(patch["value"])
            continue
        # Romance text is a separate suffix, including in customized installs.
        marker = {"background": "至今保持", "personality": "面对拥有独特魅力的玩家"}.get(key)
        if not marker or not isinstance(record[key], str):
            continue
        new_prefix, found, _ = str(patch["value"]).partition(marker)
        if not found:
            continue
        for old in patch["previous"]:
            if not isinstance(old, str):
                continue
            prefix, found, _ = old.partition(marker)
            if found and record[key].startswith(prefix + marker):
                record[key] = new_prefix + record[key][len(prefix):]
                break


def upgrade_npc_document(document, corrections):
    """Return a detached upgraded document, archiving every changed original."""
    from backend.services.npc_identity_service import _merge

    result = copy.deepcopy(document)
    originals = []
    by_id = {item["id"]: item for item in corrections["profiles"]}
    id_aliases = corrections["id_aliases"]
    aliases = corrections["aliases"]
    records, positions = [], {}
    for record in result.get("npcs", []):
        if not isinstance(record, dict):
            records.append(record)
            continue
        before = copy.deepcopy(record)
        identity = record.get("id")
        target = id_aliases.get(identity, identity)
        patch = by_id.get(target)
        # An unknown/custom identity is not inferred from transliteration or ID.
        if not patch or aliases.get(record.get("name"), record.get("name")) != patch["name"]:
            records.append(record)
            continue
        record.update(id=target, name=patch["name"])
        if isinstance(record.get("profile"), dict):
            _patch_fields(record["profile"], patch["fields"])
        _patch_fields(record, corrections.get("record_fields", {}).get(target, {}))
        if target in positions:
            index = positions[target]
            primary, secondary = (record, records[index]) if identity == target else (records[index], record)
            records[index] = _merge(primary, secondary)
            originals.append(before)
        else:
            positions[target] = len(records)
            records.append(record)
            if record != before:
                originals.append(before)
    result["npcs"] = records
    for key in ("aliases", "id_aliases"):
        mapping = result.setdefault(key, {})
        for alias, target in corrections[key].items():
            if alias in mapping and mapping[alias] != target:
                result.setdefault("npc_content_archive", {}).setdefault(corrections["revision"], {}).setdefault(key, {})[alias] = mapping[alias]
            mapping[alias] = target
    if originals:
        archive = result.setdefault("npc_content_archive", {}).setdefault(corrections["revision"], {}).setdefault("npcs", [])
        archive.extend(item for item in originals if item not in archive)
    result["content_revision"] = corrections["revision"]
    return result


def upgrade_installed_npcs(bundled_world: Path, installed_world: Path, atomic_write):
    with _UPGRADE_LOCK:
        return _upgrade_installed_npcs(bundled_world, installed_world, atomic_write)


def _upgrade_installed_npcs(bundled_world, installed_world, atomic_write):
    path = installed_world / "npcs" / "npc_index.json"
    patch_path = bundled_world / "npcs" / "canon_corrections.json"
    if not path.is_file() or not patch_path.is_file() or bundled_world.resolve() == installed_world.resolve():
        return False
    corrections = json.loads(patch_path.read_text(encoding="utf-8-sig"))
    location_changed = _upgrade_related_locations(installed_world, corrections, atomic_write)
    original_bytes = path.read_bytes()
    original = json.loads(original_bytes.decode("utf-8-sig"))
    if original.get("content_revision") == corrections["revision"]:
        return location_changed
    updated = upgrade_npc_document(original, corrections)
    _persist_upgrade(path, original_bytes, updated, corrections["revision"], atomic_write)
    return True


def _upgrade_related_locations(installed_world, corrections, atomic_write):
    path = installed_world / "locations" / "location_base.json"
    if not path.is_file() or not corrections.get("location_fields"):
        return False
    original_bytes = path.read_bytes()
    original = json.loads(original_bytes.decode("utf-8-sig"))
    updated = copy.deepcopy(original)
    for record in updated.get("locations", []):
        patch = corrections["location_fields"].get(record.get("id"))
        if patch and record.get("name") == patch["name"]:
            _patch_fields(record, patch["fields"])
    if updated == original:
        return False
    _persist_upgrade(path, original_bytes, updated, corrections["revision"], atomic_write)
    return True


def _persist_upgrade(path, original_bytes, updated, revision, atomic_write):
    fingerprint = hashlib.sha256(original_bytes).hexdigest()[:16]
    backup = path.parent / "_migrations" / f"{revision}_{path.stem}_{fingerprint}.backup.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        # Preserve the exact original bytes, not only a parsed approximation.
        try:
            with backup.open("xb") as handle:
                handle.write(original_bytes)
        except FileExistsError:
            pass
    atomic_write(path, updated)
