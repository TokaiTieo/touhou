"""Dependency-free JSON Schema subset and cross-reference validation."""

import json
from pathlib import Path
from typing import Any, Dict, List


SCHEMA_FILES = {
    "locations/location_base.json": "locations.schema.json",
    "npcs/npc_index.json": "npcs.schema.json",
    "npc_schedules.json": "schedules.schema.json",
    "events.json": "events.schema.json",
    "incidents.json": "incidents.schema.json",
    "world_info.json": "world-info.schema.json",
}


def _load(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_ref(root_schema: Dict, reference: str) -> Dict:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {reference}")
    current: Any = root_schema
    for part in reference[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    return current


def _matches_type(value: Any, expected: str) -> bool:
    types = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return expected in types and types[expected](value)


def _validate_schema(
    value: Any,
    schema: Dict,
    root_schema: Dict,
    path: str,
    errors: List[str],
) -> None:
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(root_schema, schema["$ref"]), root_schema, path, errors)
        return
    expected = schema.get("type")
    if expected and not _matches_type(value, expected):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in the allowed enum")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: string is shorter than minLength")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array is shorter than minItems")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, root_schema, f"{path}[{index}]", errors)
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}: missing required field '{required}'")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], root_schema, f"{path}.{key}", errors)
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate_schema(
                    item,
                    schema["additionalProperties"],
                    root_schema,
                    f"{path}.{key}",
                    errors,
                )


def _duplicates(values: List[str]) -> List[str]:
    seen = set()
    duplicates = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _check_aliases(
    aliases: Dict[str, str],
    canonical: set,
    label: str,
    errors: List[str],
) -> None:
    for alias, target in aliases.items():
        if alias in canonical:
            errors.append(f"{label} alias collides with canonical name: {alias}")
        if target not in canonical:
            errors.append(f"{label} alias target does not exist: {alias} -> {target}")


EDITABLE_CONTENT_FILES = {
    "world.json": "世界资料",
    "world_info.json": "动态世界书",
    "events.json": "事件池",
    "incidents.json": "异变库",
    "npc_schedules.json": "NPC 日程",
    "locations/location_base.json": "地点库",
    "npcs/npc_index.json": "NPC 名册",
}


def _editable_path(world_root: Path, relative: str) -> Path:
    normalized = str(relative or "").replace("\\", "/").strip("/")
    if normalized not in EDITABLE_CONTENT_FILES:
        raise ValueError("该内容文件不在制作人编辑白名单中")
    root = Path(world_root).resolve()
    target = (root / normalized).resolve()
    if root != target and root not in target.parents:
        raise ValueError("内容路径超出当前世界")
    return target


def list_editable_content(world_root: Path) -> List[Dict]:
    root = Path(world_root)
    return [
        {"path": relative, "label": label, "exists": (root / relative).exists()}
        for relative, label in EDITABLE_CONTENT_FILES.items()
    ]


def read_editable_content(world_root: Path, relative: str) -> Dict:
    path = _editable_path(world_root, relative)
    document = _load(path)
    return {
        "path": relative,
        "label": EDITABLE_CONTENT_FILES[relative],
        "content": document,
        "formatted": json.dumps(document, ensure_ascii=False, indent=2),
    }


def validate_editable_content(
    world_root: Path, relative: str, document: Dict, schemas_root: Path = None
) -> Dict:
    import shutil
    import tempfile

    _editable_path(world_root, relative)
    if not isinstance(document, dict):
        return {"valid": False, "errors": ["JSON 顶层必须是对象"], "counts": {}}
    if relative not in SCHEMA_FILES:
        return {"valid": True, "errors": [], "counts": {}, "mode": "object"}
    with tempfile.TemporaryDirectory(prefix="touhou-content-preview-") as temp_dir:
        preview_root = Path(temp_dir) / "world_touhou"
        shutil.copytree(world_root, preview_root)
        target = preview_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        result = validate_world_content(preview_root, schemas_root)
    result["mode"] = "schema_and_references"
    return result


def save_editable_content(
    world_root: Path,
    backup_root: Path,
    relative: str,
    document: Dict,
    schemas_root: Path = None,
) -> Dict:
    import os
    import shutil
    from datetime import datetime

    path = _editable_path(world_root, relative)
    validation = validate_editable_content(world_root, relative, document, schemas_root)
    if not validation.get("valid"):
        return {"saved": False, "validation": validation, "backup": None}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_name = relative.replace("/", "__")
    backup_path = Path(backup_root) / f"{timestamp}__{safe_name}"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, backup_path)
    temp_path = path.with_suffix(path.suffix + ".producer.tmp")
    temp_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)
    return {
        "saved": True,
        "validation": validation,
        "backup": str(backup_path) if backup_path.exists() else None,
        "path": relative,
    }


def validate_world_content(world_root: Path, schemas_root: Path = None) -> Dict:
    world_root = Path(world_root)
    schemas_root = schemas_root or Path(__file__).resolve().parents[2] / "content_schemas"
    errors: List[str] = []
    documents: Dict[str, Dict] = {}

    for relative, schema_name in SCHEMA_FILES.items():
        content_path = world_root / relative
        schema_path = schemas_root / schema_name
        try:
            document = _load(content_path)
            schema = _load(schema_path)
            documents[relative] = document
            _validate_schema(document, schema, schema, relative, errors)
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            errors.append(f"{relative}: unable to validate ({exc})")

    required = set(SCHEMA_FILES)
    if set(documents) != required:
        return {"valid": False, "errors": errors, "counts": {}}

    locations = documents["locations/location_base.json"]
    npcs_document = documents["npcs/npc_index.json"]
    schedules = documents["npc_schedules.json"].get("schedules", {})
    events_document = documents["events.json"]
    incidents = documents["incidents.json"].get("incidents", [])
    world_info = documents["world_info.json"].get("entries", [])

    region_ids = {item.get("id") for item in locations.get("regions", [])}
    location_items = locations.get("locations", [])
    location_ids = {item.get("id") for item in location_items}
    location_names = {item.get("name") for item in location_items}
    location_aliases = locations.get("aliases", {})
    valid_scenes = location_names | set(location_aliases)
    _check_aliases(location_aliases, location_names, "location", errors)

    npc_items = npcs_document.get("npcs", [])
    npc_names = {item.get("name") for item in npc_items}
    npc_aliases = npcs_document.get("aliases", {})
    valid_npcs = npc_names | set(npc_aliases)
    _check_aliases(npc_aliases, npc_names, "npc", errors)

    duplicate_groups = {
        "location id": _duplicates([item.get("id") for item in location_items]),
        "location name": _duplicates([item.get("name") for item in location_items]),
        "npc id": _duplicates([item.get("id") for item in npc_items]),
        "npc name": _duplicates([item.get("name") for item in npc_items]),
        "event id": _duplicates([
            item.get("id")
            for key in ("personal_events", "ambient_events")
            for item in events_document.get(key, [])
        ]),
        "incident id": _duplicates([item.get("id") for item in incidents]),
        "incident task id": _duplicates([item.get("completion_task_id") for item in incidents]),
        "world info id": _duplicates([item.get("id") for item in world_info]),
    }
    for label, duplicates in duplicate_groups.items():
        for value in duplicates:
            errors.append(f"duplicate {label}: {value}")

    for location in location_items:
        if location.get("parent") not in region_ids | location_ids:
            errors.append(f"location parent does not exist: {location.get('name')} -> {location.get('parent')}")
    for npc in npc_items:
        if npc.get("location_id") not in location_ids:
            errors.append(f"npc location does not exist: {npc.get('name')} -> {npc.get('location_id')}")
    for npc_name, periods in schedules.items():
        if npc_name not in valid_npcs:
            errors.append(f"schedule npc does not exist: {npc_name}")
        for period, scene in periods.items():
            if scene not in valid_scenes:
                errors.append(f"schedule scene does not exist: {npc_name}.{period} -> {scene}")
    for kind in ("personal_events", "ambient_events"):
        for event in events_document.get(kind, []):
            if event.get("npc") and event.get("npc") not in valid_npcs:
                errors.append(f"event npc does not exist: {event.get('id')} -> {event.get('npc')}")
            for scene in event.get("scenes", []):
                if scene not in valid_scenes:
                    errors.append(f"event scene does not exist: {event.get('id')} -> {scene}")
    for incident in incidents:
        for npc_name in incident.get("related_npcs", []):
            if npc_name not in valid_npcs:
                errors.append(f"incident npc does not exist: {incident.get('id')} -> {npc_name}")
        for scene in incident.get("related_locations", []):
            if scene not in valid_scenes:
                errors.append(f"incident scene does not exist: {incident.get('id')} -> {scene}")
    for entry in world_info:
        for npc_name in entry.get("npcs", []):
            if npc_name not in valid_npcs:
                errors.append(f"world info npc does not exist: {entry.get('id')} -> {npc_name}")
        for scene in entry.get("scenes", []):
            if scene not in valid_scenes:
                errors.append(f"world info scene does not exist: {entry.get('id')} -> {scene}")

    counts = {
        "locations": len(location_items),
        "location_aliases": len(location_aliases),
        "npcs": len(npc_items),
        "npc_aliases": len(npc_aliases),
        "schedules": len(schedules),
        "events": sum(len(events_document.get(key, [])) for key in ("personal_events", "ambient_events")),
        "incidents": len(incidents),
        "world_info_entries": len(world_info),
    }
    return {"valid": not errors, "errors": errors, "counts": counts}
