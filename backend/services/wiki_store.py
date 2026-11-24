"""Reviewed immutable editions; only the publication index is replaced."""
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from backend.services.wiki_compiler import load, markdown, validate_draft
from backend.services.wiki_contracts import SPECS, checksum


INVALID = (ValueError, OSError, TypeError, KeyError, AttributeError, IndexError)


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8", newline="\n")
    try:
        with temp:
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp.name, path)
    finally:
        Path(temp.name).unlink(missing_ok=True)


def write_json(path, data):
    atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def release_files(store):
    """One projection for release staging and the source-side build fingerprint."""
    index = store.index()
    key = index["active"]
    files = {}
    manifest = {"active": key, "approved": {}, "withdrawn": [], "revoked_sources": index.get("revoked_sources", {})}
    if key:
        _, bundle = store.read(key)
        manifest["approved"][key] = index["approved"][key]
        prefix = f"versions/{key}/"
        files[prefix + "bundle.json"] = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
        files.update({prefix + entity + ".md": markdown(bundle, entity) for entity in bundle["pages"]})
    files["published.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    return files


@dataclass(frozen=True)
class Store:
    root: Path
    packages: Path

    def index(self):
        return load(self.packages / "published.json")

    @contextmanager
    def writer(self):
        self.packages.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.packages / ".writer.sqlite3")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield

    def publish(self, draft, reviewed_hash, reviewer):
        with self.writer():
            version = validate_draft(self.root, draft)
            if version != reviewed_hash or not reviewer.strip():
                raise ValueError("必须提供本份草稿的审核哈希和审核人")
            index = self.index() if (self.packages / "published.json").exists() else {
                "active": "", "approved": {}, "withdrawn": []}
            if version in index["withdrawn"]:
                raise ValueError("已撤回版本不能再次发布")
            for ref, hashes in index.get("revoked_sources", {}).items():
                if draft["sources"].get(ref, {}).get("hash") in hashes:
                    raise ValueError("已撤回来源不能再次发布")
            folder = self.packages / "versions" / version
            path = folder / "bundle.json"
            if path.exists() and load(path) != draft:
                raise ValueError("不可变版本内容不符")
            if not path.exists():
                write_json(path, draft)
            for key in draft["pages"]:
                atomic(folder / (key + ".md"), markdown(draft, key))
            index["approved"].setdefault(version, reviewer.strip())
            index["active"] = version
            write_json(self.packages / "published.json", index)
            return version

    def withdraw(self, version):
        with self.writer():
            index = self.index()
            del index["approved"][version]
            index["withdrawn"].append(version)
            if index["active"] == version:
                index["active"] = ""
            write_json(self.packages / "published.json", index)

    def withdraw_source(self, ref):
        with self.writer():
            index = self.index()
            hashes = set(index.get("revoked_sources", {}).get(ref, []))
            for version in list(index["approved"]):
                if not re.fullmatch("[a-f0-9]{64}", version):
                    raise ValueError("非法版本键")
                bundle = load(self.packages / "versions" / version / "bundle.json")
                if ref in bundle["sources"]:
                    hashes.add(bundle["sources"][ref]["hash"])
                    del index["approved"][version]
                    index["withdrawn"].append(version)
            if not hashes:
                raise ValueError("找不到已发布来源")
            index.setdefault("revoked_sources", {})[ref] = sorted(hashes)
            if index["active"] not in index["approved"]:
                index["active"] = ""
            write_json(self.packages / "published.json", index)

    def reviewed_copy(self, version=None):
        """For editorial diff only: prior approved text may now have stale sources."""
        index = self.index()
        key = index["active"] if version is None else version
        if not re.fullmatch("[a-f0-9]{64}", key) or not index["approved"].get(key) or key in index["withdrawn"]:
            raise ValueError("版本未发布或已撤回")
        bundle = load(self.packages / "versions" / key / "bundle.json")
        if checksum(bundle) != key:
            raise ValueError("审核包哈希不符")
        return key, bundle

    def read(self, version=None):
        key, bundle = self.reviewed_copy(version)
        if validate_draft(self.root, bundle) != key:
            raise ValueError("Wiki 来源或包哈希失效")
        return key, bundle


@dataclass
class Snapshot:
    store: Store
    version: str
    bundle: dict
    revoked: tuple = ()

    @property
    def fingerprint(self):
        return checksum([self.version, self.revoked])

    def check(self):
        try:
            if self.version:
                self.store.read(self.version)
            if revoked_books(self.store) != self.revoked:
                raise ValueError("撤回清单变化")
        except INVALID as exc:
            raise ValueError("本回合 Wiki 证据已被纠正、撤回或失效；请手动恢复") from exc

    def rows(self, reader, scene, query, *, original=False, allowed_books=None):
        self.check()
        rows, excluded = [], set(self.revoked)
        if not self.bundle:
            return rows, excluded
        pages = self.bundle["pages"]
        permitted = {key for key, spec in SPECS.items() if spec.permits(reader, scene)}
        for key, page in pages.items():
            spec = SPECS[key]
            if key not in permitted:
                if spec.book:
                    excluded.add(spec.book)
                continue
            if original:
                continue
            aliases = (page["title"], page["title"][-2:]) if spec.kind == "person" else (page["title"],)
            for i, fact in enumerate(page["claims"]):
                if any(target not in permitted for target in fact["links"]):
                    continue
                related = [pages[target]["title"] for target in fact["links"]]
                terms = [*aliases, *related, *{"spellcard": ("符卡", "弹幕", "决斗"),
                         "incident": ("异变",), "outsider": ("外来者", "外界人"),
                         "moriya": ("守矢",), "scarlet": ("红魔馆",)}.get(key, ())]
                if not (any(word in query for word in terms) or page["title"] == scene):
                    continue
                if any(ref.startswith("book:") for ref in fact["refs"]):
                    if allowed_books is not None and spec.book not in allowed_books:
                        continue
                    excluded.add(spec.book)
                rows.append({"id": f"wiki:{key}:{i}", "kind": "wiki", "title": page["title"],
                             "content": fact["text"], "links": related, "refs": fact["refs"],
                             "source": self.version})
        return rows, excluded


def configured_store():
    from backend.config import BASE_DIR, DEFAULT_WORLD_ID, WORLDS_DIR, _get_setting
    if _get_setting("TOUHOU_STATIC_WIKI", "0").lower() not in ("1", "true", "on"):
        return None
    return Store(WORLDS_DIR / DEFAULT_WORLD_ID, BASE_DIR / "worlds" / DEFAULT_WORLD_ID / "wiki")


def revoked_books(store):
    refs = store.index().get("revoked_sources", {})
    return tuple(sorted({ref.split(":")[1] for ref in refs if ref.startswith("book:")}))


def freeze(ledger):
    """Pin even an absent edition. An ordinary publish cannot change a resumed turn."""
    store = configured_store()
    with ledger.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS wiki_pins(scope TEXT PRIMARY KEY, edition TEXT NOT NULL)")
        row = db.execute("SELECT edition FROM wiki_pins WHERE scope=?", (ledger.scope,)).fetchone()
        version, bundle = "", {}
        if store and (row is None or row[0]):
            try:
                version, bundle = store.read(row[0] if row else None)
            except INVALID:
                pass  # Fail closed to the existing world-book source.
        if row is None or row[0] != version:
            db.execute("INSERT OR REPLACE INTO wiki_pins VALUES (?,?)", (ledger.scope, version))
    try:
        revoked = revoked_books(store) if store else ()
    except INVALID:
        revoked = ()
    return Snapshot(store, version, bundle, revoked) if version or revoked else None
