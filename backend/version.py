"""Canonical application version loaded from the bundled version manifest."""

import json
from pathlib import Path


_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "version.json"


def load_version_manifest():
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {
            "version": "0.0.0",
            "display_version": "dev",
            "save_schema": 7,
            "content_schema": 7,
        }


VERSION_MANIFEST = load_version_manifest()
APP_VERSION = str(VERSION_MANIFEST["version"])
DISPLAY_VERSION = str(VERSION_MANIFEST.get("display_version") or f"v{APP_VERSION}")
SAVE_SCHEMA_VERSION = int(VERSION_MANIFEST.get("save_schema", 7))
CONTENT_SCHEMA_VERSION = int(VERSION_MANIFEST.get("content_schema", 7))
