"""Stable built-in NPC identities and lossless legacy-save reconciliation."""

import copy
import hashlib
import json
from pathlib import Path
from functools import lru_cache
from urllib.parse import quote


NAME_ALIASES = {"帕秋莉·诺蕾姬": "帕秋莉"}
ID_ALIASES = {"npc_patchouli_n": "npc_patchouli", "hakurei_reimu": "npc_reimu"}
KEY_ALIASES = {**NAME_ALIASES, "npc_patchouli_n": "帕秋莉", "npc_patchouli": "帕秋莉"}


@lru_cache(maxsize=8)
def _registry(path, modified):
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    records = {item["id"]: item for item in document.get("npcs", []) if isinstance(item, dict) and item.get("id")}
    names = {item["name"]: identity for identity, item in records.items() if item.get("name")}
    aliases = {**NAME_ALIASES, **document.get("aliases", {})}
    ids = {**ID_ALIASES, **document.get("id_aliases", {})}
    keys = {**aliases, **{identity: item["name"] for identity, item in records.items() if item.get("name")}}
    keys.update({alias: records[target]["name"] for alias, target in ids.items() if target in records})
    return records, names, keys, ids


def npc_registry():
    from backend.config import WORLDS_DIR, BASE_DIR, DEFAULT_WORLD_ID
    path = WORLDS_DIR / DEFAULT_WORLD_ID / "npcs" / "npc_index.json"
    if not path.is_file():
        path = BASE_DIR / "worlds" / DEFAULT_WORLD_ID / "npcs" / "npc_index.json"
    return _registry(str(path), path.stat().st_mtime_ns)


def canonical_npc_name(name):
    return npc_registry()[2].get(name, name) if isinstance(name, str) else name


def canonical_npc_id(identity):
    return npc_registry()[3].get(identity, identity) if isinstance(identity, str) else identity


def resolve_npc(identity):
    records, names, _, _ = npc_registry()
    key = canonical_npc_id(identity)
    key = key if key in records else names.get(canonical_npc_name(identity))
    if key not in records:
        return None
    result = copy.deepcopy(records[key])
    result["avatar_url"] = "/avatars/" + quote(key, safe="") + ".png"
    return result


def _merge(primary, secondary, *, text=False):
    if isinstance(primary, dict) and isinstance(secondary, dict):
        result = copy.deepcopy(primary)
        for key, value in secondary.items():
            result[key] = _merge(result[key], value, text=text) if key in result else copy.deepcopy(value)
        return result
    if isinstance(primary, list) and isinstance(secondary, list):
        result = copy.deepcopy(primary)
        for value in secondary:
            if value not in result:
                result.append(copy.deepcopy(value))
        return result
    if text and isinstance(primary, str) and isinstance(secondary, str) and secondary not in primary:
        return primary + "\n" + secondary
    return copy.deepcopy(secondary if primary is None or primary == "" else primary)


def normalize_npcs(npcs):
    """Only coalesce known built-in IDs, never unrelated player-created NPCs."""
    if not isinstance(npcs, list):
        return []
    result, positions = [], {}
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        item = copy.deepcopy(npc)
        identity = canonical_npc_id(item.get("id"))
        registered = resolve_npc(identity)
        if not registered:
            result.append(item)
            continue
        item.update(id=identity, name=registered["name"], avatar_url=registered["avatar_url"])
        if npc.get("id") != identity:
            item.setdefault("legacy_identity_records", []).append(copy.deepcopy(npc))
        if identity not in positions:
            positions[identity] = len(result)
            result.append(item)
        else:
            index = positions[identity]
            primary, secondary = (item, result[index]) if npc.get("id") == identity else (result[index], item)
            result[index] = _merge(primary, secondary)
    return result


def load_npc_document(path):
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        return {"npcs": []}
    document["npcs"] = normalize_npcs(document.get("npcs", []))
    return document


def migrate_npc_identities(character):
    """Archive conflicting originals; union memories, prefer latest dated state."""
    changed = False
    affected = set()

    def references(value):
        if isinstance(value, list):
            return [references(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in ("npc_name", "source_npc", "opponent"):
                result[key] = canonical_npc_name(item)
            elif key == "npc_id":
                result[key] = canonical_npc_id(item)
            elif key in ("related_npcs", "audience") and isinstance(item, list):
                result[key] = list(dict.fromkeys(canonical_npc_name(name) for name in item if isinstance(name, str)))
            else:
                result[key] = references(item)
        return result

    def reconcile(mapping, path, *, text=False):
        nonlocal changed
        if not isinstance(mapping, dict):
            return
        for alias, name in npc_registry()[2].items():
            if alias == name:
                continue
            if alias not in mapping:
                continue
            affected.add(name)
            snapshots = character.setdefault("npc_identity_archive", {})
            snapshots.setdefault(path, copy.deepcopy(mapping))
            old = mapping.pop(alias)
            if name not in mapping:
                mapping[name] = old
            else:
                primary, secondary = mapping[name], old
                if isinstance(primary, dict) and isinstance(secondary, dict):
                    # Missing timestamps do not override the canonical record.
                    if str(secondary.get("updated_at") or "") > str(primary.get("updated_at") or ""):
                        primary, secondary = secondary, primary
                mapping[name] = _merge(primary, secondary, text=text)
            changed = True

    for field in (
        "relationships", "relationships_map", "relationship_progress", "relationship_boundaries",
        "npc_memories", "npc_memory_archive", "npc_memory_layers", "npc_memory_summaries",
        "npc_memory_legacy_summaries", "npc_runtime", "opponent_adaptation",
    ):
        reconcile(character.get(field), field, text=field in ("npc_memory_summaries", "npc_memory_legacy_summaries"))
    agency = character.get("npc_agency", {})
    if isinstance(agency, dict):
        for field in ("npcs", "rumor_receipts"):
            reconcile(agency.get(field), "npc_agency." + field)
        graph = agency.get("social_graph", {})
        if isinstance(graph, dict):
            for key, edge in list(graph.items()):
                if not isinstance(edge, dict) or not isinstance(edge.get("npcs"), list):
                    continue
                names = list(dict.fromkeys(canonical_npc_name(name) for name in edge["npcs"]))
                if names != edge["npcs"]:
                    character.setdefault("npc_identity_archive", {}).setdefault("npc_agency.social_graph", copy.deepcopy(graph))
                    updated = copy.deepcopy(edge)
                    updated["npcs"] = names
                    del graph[key]
                    new_key = "|".join(sorted(names))
                    if len(names) > 1:
                        graph[new_key] = _merge(graph[new_key], updated) if new_key in graph else updated
                    changed = True
    for field in ("open_events", "deferred_consequences", "npc_simulation", "world_state", "incident_state", "incident_history"):
        original = character.get(field)
        normalized = references(original)
        if normalized != original:
            character.setdefault("npc_identity_archive", {}).setdefault(field, copy.deepcopy(original))
            character[field] = normalized
            changed = True
    if changed:
        for field in ("npc_memories", "npc_memory_archive"):
            mapping = character.get(field)
            for bucket in mapping.values() if isinstance(mapping, dict) else []:
                seen = {"id": set(), "archive_id": set()}
                for item in bucket if isinstance(bucket, list) else []:
                    if not isinstance(item, dict):
                        continue
                    for key, identities in seen.items():
                        identity = item.get(key)
                        if not isinstance(identity, str) or not identity:
                            continue
                        if identity in identities:
                            digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
                            item[key] = identity + "_merged_" + digest
                        identities.add(item[key])
        progress_map = character.get("relationship_progress")
        for name, progress in progress_map.items() if isinstance(progress_map, dict) else []:
            if name in affected and isinstance(progress, dict) and progress.get("attitude"):
                character.setdefault("relationships_map", {})[name] = progress["attitude"]
        for field in ("semantic_memory_index", "memory_index_meta"):
            mapping = character.get(field, {})
            if isinstance(mapping, dict):
                for key in (*npc_registry()[2], *npc_registry()[1]):
                    mapping.pop(key, None)
    return changed
