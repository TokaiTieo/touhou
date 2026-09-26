"""Fingerprint only release inputs, never local credentials or player data."""

import hashlib
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def build_identity(root, *, source_worlds=False):
    root = Path(root).resolve()
    files = {}
    for name in ("version.json", "index.html", "api_release.spec", "build_identity.py", "requirements.txt"):
        files[name] = digest(root / name)
    for name in ("backend", "js", "css", "static", "avatars", "prompts"):
        for path in sorted((root / name).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.name.startswith(".") or path.suffix in {".pyc", ".log", ".dat"}:
                continue
            if name == "backend" and path.suffix not in {".py", ".json"}:
                continue
            files[path.relative_to(root).as_posix()] = digest(path)
    world_root = root / "worlds" if source_worlds else root / "release" / "build_worlds_clean"
    if not world_root.exists():
        raise ValueError("Prepare clean release worlds before building")
    for path in sorted(world_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(world_root)
        if source_worlds and "sessions" in relative.parts:
            continue
        if "sessions" in relative.parts or path.name.startswith("."):
            raise ValueError("Release world contains runtime files")
        files["worlds/" + relative.as_posix()] = digest(path)
    version = json.loads((root / "version.json").read_text(encoding="utf-8-sig"))
    identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"build_id": identity, "version": version["version"], "files": files}


def write_build_identity(root):
    root = Path(root)
    output = root / "release" / "build-info.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_identity(root), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(output)


if __name__ == "__main__":
    print(build_identity(Path(__file__).parent)["build_id"])
