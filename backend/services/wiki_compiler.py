"""Deterministic extractive compiler. No provider, save, or dialogue input."""
import json
from pathlib import Path

from backend.services.wiki_contracts import FILES, PILOT, POLICY, checksum


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def compile_world(root):
    tables = {}
    for kind, (file, collection, _) in FILES.items():
        rows = load(root / file)[collection]
        tables[kind] = {row["id"]: row for row in rows}
        if len(rows) != len(tables[kind]):
            raise ValueError(f"重复来源 ID: {file}")
    sources, pages, conflicts = {}, {}, []

    def source(kind, entity, field):
        file, collection, fields = FILES[kind]
        if field not in fields:
            raise ValueError("非公开字段")
        row = tables[kind][entity]
        # Never copy arbitrary nested objects or accept privately scoped variants.
        if (row.get("visibility", {"scope": "public"}) != {"scope": "public"}
                or row.get("truth_status", "confirmed") != "confirmed"
                or row.get("attribution_status", "confirmed") != "confirmed"
                or row.get("status") in ("pending", "draft", "revoked", "retracted", "withdrawn")
                or row.get("timeline_epoch") or row.get("owner_npc_id")):
            raise ValueError(f"来源非公开或未确认: {entity}")
        value = row
        for key in field.split("."):
            value = value[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 3000:
            raise ValueError(f"来源字段非法: {entity}.{field}")
        sid = f"{kind}:{entity}:{field}"
        sources[sid] = {"file": file, "selector": f"{collection}[id={entity}].{field}",
                        "kind": kind, "hash": checksum(value), "value": value}
        return sid, value

    for spec in PILOT:
        claims = []

        def claim(text, refs, links=()):
            claims.append({"text": text, "refs": list(refs), "links": list(links)})

        if spec.kind == "person":
            name, title = source("npc", spec.id, "name")
            identity, role = source("npc", spec.id, "profile.identity")
            home, location = source("npc", spec.id, "location_id")
            loc, place = source("place", location, "name")
            claim(f"{title}：{role}。", (name, identity))
            claim(f"{title}的设定地点是{place}（不是实时位置）。", (name, home, loc), (location,))
            if place != spec.scene:
                conflicts.append(f"{spec.id}: 地点 {place} 与试点设定 {spec.scene} 不符")
        elif spec.kind == "place":
            name, title = source("place", spec.id, "name")
            desc, description = source("place", spec.id, "description")
            claim(description.split("。")[0] + "。", (name, desc))
        if spec.book:
            heading, book_title = source("book", spec.book, "title")
            ref, content = source("book", spec.book, "content")
            claim(content, (heading, ref))
        if spec.kind in ("place", "person") and title != spec.title:
            conflicts.append(f"{spec.id}: 标题已更名")
        pages[spec.id] = {"type": spec.kind, "title": spec.title, "entity": spec.id,
                          "readers": list(spec.readers), "scene": spec.scene, "claims": claims}
    return {"policy": POLICY, "sources": sources, "pages": pages, "conflicts": conflicts}


def validate_draft(root, draft):
    expected = compile_world(root)
    if expected["conflicts"] or set(draft["pages"]) != set(expected["pages"]):
        raise ValueError("试点页面不完整或存在冲突")
    # Editors can omit redundant claims or shorten a quotation; provenance,
    # links, titles and ACLs always come from code, never from candidate prose.
    for key, page in expected["pages"].items():
        selected = draft["pages"][key]["claims"]
        if not isinstance(selected, list) or not selected:
            raise ValueError("页面不能没有结论")
        available = list(page["claims"])
        for item in selected:
            match = next((fact for fact in available if item["refs"] == fact["refs"]
                          and item["links"] == fact["links"] and set(item) == set(fact)
                          and isinstance(item["text"], str) and item["text"].strip()
                          and item["text"] in fact["text"]), None)
            if not match:
                raise ValueError("无有效来源的结论或关联")
            available.remove(match)
        page["claims"] = selected
    if draft != expected:
        raise ValueError("草稿与当前白名单来源／策略不一致或有冲突，请重建并审核")
    return checksum(draft)


def markdown(bundle, identity):
    page = bundle["pages"][identity]
    lines = ["# " + page["title"], "", f"类型：{page['type']}；实体：`{identity}`", ""]
    for claim in page["claims"]:
        lines.extend([claim["text"], ""])
        for ref in claim["refs"]:
            src = bundle["sources"][ref]
            lines.append(f"- 来源：`{src['file']}#{src['selector']}` · `{src['hash']}`")
        for target in claim["links"]:
            lines.append(f"- 关联：[{bundle['pages'][target]['title']}]({target}.md)")
        lines.append("")
    return "\n".join(lines)
