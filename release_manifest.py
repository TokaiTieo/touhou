"""Create a credential-free SHA-256 manifest for release artifacts."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.version import VERSION_MANIFEST


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_manifest(root: Path, artifacts=None) -> dict:
    root = Path(root).resolve()
    paths = (
        sorted(path for path in root.iterdir() if path.is_file())
        if artifacts is None else [Path(path).resolve() for path in artifacts]
    )
    files = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.name
        files.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": file_digest(path),
        })
    return {
        "manifest_version": 1,
        "product": "TouHou · 东方异变录",
        "version": VERSION_MANIFEST.get("version"),
        "display_version": VERSION_MANIFEST.get("display_version"),
        "save_schema": VERSION_MANIFEST.get("save_schema"),
        "content_schema": VERSION_MANIFEST.get("content_schema"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("artifacts", nargs="*")
    args = parser.parse_args()
    manifest = build_release_manifest(Path(args.root), args.artifacts or None)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output), "files": len(manifest["files"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
