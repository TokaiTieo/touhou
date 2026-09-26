"""Read-only release inventory; versions alone never certify an executable."""

import argparse
import json
from pathlib import Path

from build_identity import build_identity, digest


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _artifact(path, identity, receipt, manifest=None):
    if not path.is_file():
        return {"status": "missing", "verified": False}
    sha = digest(path)
    verified = sha.lower() == str(receipt.get("sha256", "")).lower()
    metadata = receipt if verified else (manifest or {})
    build_id = metadata.get("build_id")
    status = "unverified"
    if build_id and build_id != identity["build_id"]:
        status = "outdated"
    elif verified and build_id == identity["build_id"]:
        status = "current"
    return {"status": status, "verified": verified, "version": metadata.get("version"),
            "build_id": build_id, "sha256": sha}


def release_status(root):
    root = Path(root).resolve()
    identity = build_identity(root, source_worlds=True)
    release = root / "release"
    package = release / "touhou-test-package.zip"
    manifest = _read(package.with_suffix(".zip.manifest.json"))
    # Associate the metadata only with the exact archive it describes.
    entries = manifest.get("files", [])
    entries = entries if isinstance(entries, list) else []
    if not package.is_file() or not any(
        isinstance(item, dict) and item.get("path") == package.name
        and str(item.get("sha256", "")).lower() == digest(package)
        for item in entries
    ):
        manifest = {}
    return {
        "source": {"version": identity["version"], "build_id": identity["build_id"]},
        "prepared_build_id": _read(release / "build-info.json").get("build_id"),
        "exe": _artifact(root / "touhou.exe", identity, _read(release / "verified-exe.json")),
        "zip": _artifact(package, identity, _read(release / "verified-package.json"), manifest),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = release_status(Path(__file__).parent)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
