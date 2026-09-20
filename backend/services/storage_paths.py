"""Storage identities are filenames, never caller-supplied paths."""

from pathlib import Path


class InvalidStoragePath(ValueError):
    pass


class FutureSaveVersion(ValueError):
    pass


def safe_identifier(value):
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value in (".", "..") or value.endswith(".") or value.startswith("_"):
        return False
    if any(ord(char) < 32 or char in '/\\:*?"<>|' for char in value):
        return False
    stem = value.split(".", 1)[0].upper()
    return stem not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def require_identifier(value):
    if not safe_identifier(value):
        raise InvalidStoragePath("存档标识无效，请通过导入功能迁移旧存档")
    return value


def contained_path(root, *parts):
    root = Path(root).resolve()
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root) or target == root:
        raise InvalidStoragePath("存档路径超出允许目录")
    return target


def require_supported_save(payload):
    from backend.version import SAVE_SCHEMA_VERSION
    try:
        version = int(payload.get("save_version", 1) or 1)
    except (ValueError, TypeError):
        version = 1
    if version > SAVE_SCHEMA_VERSION:
        raise FutureSaveVersion(f"这是 V{version} 存档，当前程序仅支持至 V{SAVE_SCHEMA_VERSION}；请升级程序，原文件未修改")
