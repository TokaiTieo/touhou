"""Offline developer CLI. Drafts and accounting never live in the world tree."""
import argparse
import difflib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.wiki_compiler import compile_world, load, markdown, validate_draft
from backend.services.wiki_contracts import checksum
from backend.services.wiki_store import Store, atomic, release_files, write_json


def run(args):
    world, work = args.world.resolve(), args.work.resolve()
    if work.is_relative_to(world):
        raise ValueError("草稿目录不能位于游戏世界资源目录内")
    store = Store(world, world / "wiki")
    draft = work / "draft.json"
    if args.command == "scan":
        return compile_world(world)["sources"]
    if args.command == "draft":
        bundle = compile_world(world)
        write_json(draft, bundle)
        for key in bundle["pages"]:
            atomic(work / "pages" / (key + ".md"), markdown(bundle, key))
        return {"draft": str(draft), "hash": checksum(bundle), "conflicts": bundle["conflicts"]}
    if args.command == "validate":
        return {"hash": validate_draft(world, load(draft))}
    if args.command == "diff":
        left = store.reviewed_copy()[1] if (store.packages / "published.json").exists() and store.index()["active"] else {}
        lines = lambda obj: json.dumps(obj, ensure_ascii=False, indent=2).splitlines()
        return "\n".join(difflib.unified_diff(lines(left), lines(load(draft)), "published", "draft", lineterm=""))
    if args.command == "publish":
        return store.publish(load(draft), args.hash, args.reviewer)
    if args.command == "withdraw":
        store.withdraw(args.hash)
        return "withdrawn"
    if args.command == "withdraw-source":
        store.withdraw_source(args.source)
        return "source withdrawn"
    if args.command == "export":
        if not args.destination or args.destination.exists():
            raise ValueError("需要独立且不存在的发布目标目录")
        for relative, content in release_files(store).items():
            atomic(args.destination / relative, content)
        return "exported reviewed edition"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["scan", "draft", "validate", "diff", "publish", "withdraw", "withdraw-source", "export"])
    parser.add_argument("--world", type=Path, default=ROOT / "worlds/world_touhou")
    parser.add_argument("--work", type=Path, default=ROOT / "reports/static-wiki-pilot")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--hash", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--source", default="")
    args = parser.parse_args()
    try:
        result = run(args)
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        # All compiler paths, including failures and rebuilds, have no model client.
        if args.command in {"scan", "draft", "validate", "publish"} and not args.work.resolve().is_relative_to(args.world.resolve()):
            args.work.mkdir(exist_ok=True, parents=True)
            with (args.work / "builds.jsonl").open("a", encoding="utf-8") as audit:
                print(json.dumps({"operation": args.command, "success": sys.exc_info()[0] is None,
                                  "requests": 0, "tokens": 0}), file=audit)
