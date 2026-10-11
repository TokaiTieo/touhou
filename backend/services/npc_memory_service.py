"""NPC memory capture, compression, retrieval and turn record persistence."""

import re
import copy
import hashlib
import json
import uuid
from datetime import datetime
from typing import Dict, List

from backend.services.memory_retrieval import rank_memories
from backend.services.npc_identity_service import canonical_npc_name
from backend.services.npc_attribution_service import interaction_targets, npc_identity, npc_label


def _number(value, default=0):
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return default


KNOWLEDGE_LABELS = {
    "direct": "亲历",
    "reported": "听闻",
    "inferred": "推测",
    "system": "既定事实",
}
TRUTH_LABELS = {"accepted": "有效", "disputed": "存疑", "superseded": "已更新"}


def _default_knowledge_type(source: str, source_npc: str = None) -> str:
    source = str(source or "")
    if source.startswith(("producer", "system", "migration")):
        return "system"
    if source_npc:
        return "reported"
    if source.startswith("inference"):
        return "inferred"
    return "direct"


def _default_confidence(knowledge_type: str) -> float:
    return {"direct": 0.9, "reported": 0.62, "inferred": 0.45, "system": 0.98}.get(knowledge_type, 0.75)


def upgrade_npc_memory_metadata(character: Dict) -> bool:
    """Add provenance metadata to old memories without replacing their content."""
    changed = False
    buckets = []
    for field in ("npc_memories", "npc_memory_archive"):
        mapping = character.get(field) or {}
        if not isinstance(mapping, dict):
            continue
        if field == "npc_memory_archive":
            for items in mapping.values():
                for item in items if isinstance(items, list) else []:
                    if isinstance(item, dict) and "archive_identity" not in item:
                        item["archive_identity"] = memory_identity(item)
                        changed = True
        buckets.extend(mapping.items())
    layer_mapping = character.get("npc_memory_layers") or {}
    for name, layers in (layer_mapping if isinstance(layer_mapping, dict) else {}).items():
        if isinstance(layers, dict):
            buckets.extend((name, items) for items in layers.values())
    for name, items in buckets:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            knowledge_type = item.get("knowledge_type") or _default_knowledge_type(
                item.get("source", "migrated"), item.get("source_npc")
            )
            defaults = {
                "knowledge_type": knowledge_type,
                "source_npc": None,
                "confidence": _default_confidence(knowledge_type),
                "truth_status": "accepted",
                "fact_key": None,
                "superseded_by": None,
                "owner_npc_id": npc_identity(name)["npc_id"],
                "owner_npc_name": canonical_npc_name(name),
                "attribution_status": "legacy_unverified",
            }
            for key, value in defaults.items():
                if key not in item:
                    item[key] = value
                    changed = True
    return changed


def _memory_line(item: Dict) -> str:
    kind = KNOWLEDGE_LABELS.get(item.get("knowledge_type"), "记忆")
    status = TRUTH_LABELS.get(item.get("truth_status"), "有效")
    confidence = round(max(0, min(1, float(item.get("confidence", 0.85) or 0.85))) * 100)
    source_npc = f"·来自{item.get('source_npc')}" if item.get("source_npc") else ""
    attribution = {"confirmed": "来源明确，主语以原文为准", "pending": "待核实，不作事实", "legacy_unverified": "旧记录归属未核实"}.get(item.get("attribution_status"), "归属未核实")
    summary = json.dumps(str(item.get('summary', '')), ensure_ascii=False)
    confidence_label = "旧标注置信度" if item.get("attribution_status") == "legacy_unverified" else "可信"
    return f"- [{kind}{source_npc}·{confidence_label}{confidence}%·{status}·{attribution}] {summary}"


def _recalled(character, name, item):
    if not isinstance(item, dict) or item.get("attribution_status") == "pending" or item.get("truth_status") == "superseded":
        return False
    return not _is_corrected(character, name, item)


def _is_corrected(character, name, item):
    for correction in character.get("npc_memory_corrections", {}).get(name, []):
        if str(item.get("id")) == correction.get("memory_id"):
            return True
        if item.get("summary") in correction.get("summaries", []) and not (
            item.get("attribution_status") == "confirmed" and str(item.get("source", "")).startswith("producer")
        ):
            return True
    return False


def delete_npc_memory(character, npc_name, memory_id):
    """Explicit corrections persist across archive compression and old snapshots."""
    name = canonical_npc_name(npc_name)
    originals = [copy.deepcopy(item) for field in ("npc_memories", "npc_memory_archive")
                 for item in character.get(field, {}).get(name, []) if str(item.get("id")) == str(memory_id)]
    if not originals:
        return 0
    character.setdefault("npc_memory_corrections", {}).setdefault(name, []).append({
        "memory_id": str(memory_id), "summaries": list(dict.fromkeys(item.get("summary", "") for item in originals)),
        "originals": originals, "corrected_at": datetime.now().isoformat(),
    })
    apply_memory_corrections(character)
    return len(originals)


def apply_memory_corrections(character, inherited=None):
    corrections = character.setdefault("npc_memory_corrections", {})
    for name, records in (inherited or {}).items():
        bucket = corrections.setdefault(canonical_npc_name(name), [])
        bucket.extend(copy.deepcopy(item) for item in records if item not in bucket)
    for name in corrections:
        for field in ("npc_memories", "npc_memory_archive"):
            bucket = character.get(field, {}).get(name)
            if bucket is not None:
                # Pending proposals are retained for review, not implicitly deleted.
                character[field][name] = [item for item in bucket if not isinstance(item, dict) or not _is_corrected(character, name, item)]
        for field in ("npc_memory_layers", "semantic_memory_index", "memory_index_meta"):
            character.get(field, {}).pop(name, None)
        # Keep unstructured legacy summaries as originals, but do not recall them
        # after a correction: there is no safe way to subtract their source facts.
        if character.get("npc_memory_summaries", {}).get(name):
            character.setdefault("npc_memory_legacy_summaries", {}).setdefault(name, character["npc_memory_summaries"][name])
            character["npc_memory_summaries"][name] = ""


def _resolve_fact_conflicts(bucket: List[Dict], new_entry: Dict) -> None:
    if new_entry.get("attribution_status") == "pending":
        return
    fact_key = new_entry.get("fact_key")
    if not fact_key:
        return
    new_confidence = float(new_entry.get("confidence", 0.75) or 0.75)
    for previous in bucket:
        if not isinstance(previous, dict) or previous.get("fact_key") != fact_key:
            continue
        if previous.get("truth_status", "accepted") == "superseded" or previous.get("attribution_status") == "pending":
            continue
        old_confidence = float(previous.get("confidence", 0.75) or 0.75)
        if abs(new_confidence - old_confidence) <= 0.15:
            previous["truth_status"] = "disputed"
            new_entry["truth_status"] = "disputed"
        elif new_confidence > old_confidence:
            previous["truth_status"] = "superseded"
            previous["superseded_by"] = new_entry.get("id")
        else:
            new_entry["truth_status"] = "disputed"


def get_npc_memory_text(character: Dict, npc_name: str = None, limit: int = 8, query: str = "") -> str:
    npc_name = canonical_npc_name(npc_name)
    memories = character.setdefault("npc_memories", {})
    archives = character.setdefault("npc_memory_archive", {})
    upgrade_npc_memory_metadata(character)
    summaries = character.setdefault("npc_memory_summaries", {})
    legacy = character.get("npc_memory_legacy_summaries", {})
    def candidates(name):
        items = [item for item in archives.get(name, []) + memories.get(name, []) if _recalled(character, name, item)]
        old_summary = legacy.get(name) or (summaries.get(name) if not character.get("npc_memory_layers", {}).get(name) else "")
        if old_summary and not character.get("npc_memory_corrections", {}).get(name):
            items = items + [{"id": f"legacy-summary:{name}", "summary": old_summary,
                              "importance": 7, "source": "legacy_summary", "knowledge_type": "reported",
                              "confidence": 0.6, "truth_status": "disputed", "attribution_status": "legacy_unverified"}]
        return items
    index_root = character.setdefault("semantic_memory_index", {})
    meta_root = character.setdefault("memory_index_meta", {})
    retrieval_diagnostics = []

    def touch(items):
        now = datetime.now().isoformat()
        for item in items:
            item["last_used_at"] = now
            item["used_count"] = _number(item.get("used_count"), 0) + 1

    if npc_name:
        selected = rank_memories(
            candidates(npc_name),
            query,
            limit,
            index_root.setdefault(npc_name, {}),
            meta_root.setdefault(npc_name, {}),
            retrieval_diagnostics,
        )
        for item in retrieval_diagnostics:
            item["npc_name"] = npc_name
        character["_last_memory_retrieval"] = retrieval_diagnostics
        touch(selected)
        lines = [f"记忆持有人 {npc_label(npc_name)}（不等于事实主语）：{_memory_line(item)}" for item in selected]
        return "\n".join(lines) if lines else f"{npc_label(npc_name)}: 暂无已确认关键记忆"
    ranked = []
    for name in sorted(set([*archives, *memories, *legacy, *summaries])):
        items = candidates(name)
        diagnostics = []
        selected = rank_memories(
            items,
            query,
            limit,
            index_root.setdefault(name, {}),
            meta_root.setdefault(name, {}),
            diagnostics,
        )
        for item, diagnostic in zip(selected, diagnostics):
            diagnostic["npc_name"] = name
            if name and name in query:
                diagnostic["score"] += 6
                diagnostic["reasons"].append("当前提及人物")
            ranked.append((diagnostic["score"], name, diagnostic["memory_id"], item, diagnostic))
    ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    chosen = ranked[:max(0, limit)]
    touch([entry[3] for entry in chosen])
    character["_last_memory_retrieval"] = [entry[4] for entry in chosen]
    lines = [f"记忆持有人 {npc_label(name)}（不等于事实主语）：{_memory_line(item)}" for _, name, _, item, _ in chosen]
    return "\n".join(lines) if lines else "暂无关键NPC记忆"


def estimate_memory_importance(summary: str, tags=None, source: str = "interaction", explicit=None) -> int:
    if explicit is not None:
        return max(1, min(10, int(_number(explicit, 5))))
    combined = f"{summary} {' '.join(str(tag) for tag in (tags or []))}"
    score = 4
    score += sum(2 for word in ("承诺", "约定", "背叛", "救", "死亡", "战斗", "符卡", "亲密", "秘密", "异变", "完成", "热恋", "敌对", "仇恨") if word in combined)
    score += sum(1 for word in ("赠礼", "帮助", "调查", "同行", "称呼", "邀约", "关系", "信任", "警惕") if word in combined)
    if source.startswith(("auto_relationship", "auto_battle")):
        score += 2
    if source.startswith("producer"):
        score += 1
    return max(1, min(10, score))


def infer_memory_emotion(summary: str, tags=None) -> str:
    text = f"{summary} {' '.join(str(tag) for tag in (tags or []))}"
    if any(word in text for word in ("热恋", "亲密", "暧昧", "喜欢", "信任", "救", "帮助")):
        return "亲近"
    if any(word in text for word in ("背叛", "敌对", "仇恨", "威胁", "羞辱", "攻击")):
        return "负面"
    if any(word in text for word in ("战斗", "符卡", "挑战", "击败", "失败")):
        return "竞争"
    if any(word in text for word in ("秘密", "羞耻", "隐藏")):
        return "隐秘"
    return "中性"


def memory_identity(item: Dict) -> str:
    if item.get("archive_identity"):
        return item["archive_identity"]
    stable = {key: value for key, value in item.items() if key not in {"used_count", "access_count", "retrieval_count", "last_accessed_at", "last_recalled_at", "last_used_at"}}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


def archive_memories(character: Dict, npc_name: str, items: List[Dict]) -> None:
    npc_name = canonical_npc_name(npc_name)
    archive = character.setdefault("npc_memory_archive", {}).setdefault(npc_name, [])
    known = {memory_identity(item) for item in archive}
    for item in items:
        key = memory_identity(item)
        if key not in known:
            archive.append(copy.deepcopy(item))
            known.add(key)


def restore_archived_memory(character: Dict, npc_name: str, archive_id: str) -> Dict:
    npc_name = canonical_npc_name(npc_name)
    archive = character.setdefault("npc_memory_archive", {}).get(npc_name, [])
    item = next((item for item in archive if memory_identity(item) == archive_id), None)
    if item is None:
        raise ValueError("找不到这条记忆档案，请刷新后重试")
    bucket = character.setdefault("npc_memories", {}).setdefault(npc_name, [])
    bucket.append(copy.deepcopy(item))
    archive.remove(item)
    return item


def compress_npc_memory_bucket(character: Dict, npc_name: str, keep_recent: int = 24, force: bool = False) -> bool:
    npc_name = canonical_npc_name(npc_name)
    memories = character.setdefault("npc_memories", {})
    bucket = memories.get(npc_name, [])
    if (not force and len(bucket) <= 30) or (force and not bucket):
        return False
    old_items, recent = bucket[:-keep_recent], bucket[-keep_recent:]
    if force and not old_items:
        old_items, recent = bucket, bucket[-min(len(bucket), keep_recent):]
    if not old_items:
        return False
    summaries = character.setdefault("npc_memory_summaries", {})
    legacy = character.setdefault("npc_memory_legacy_summaries", {})
    legacy.setdefault(npc_name, summaries.get(npc_name, ""))
    archive_memories(character, npc_name, old_items)
    all_items = character["npc_memory_archive"][npc_name] + recent
    layers = {"facts": [], "relationships": [], "events": []}
    for item in all_items:
        if not _recalled(character, npc_name, item):
            continue
        layer = "facts" if item.get("fact_key") else (
            "relationships" if any(word in str(item.get("tags", [])) + str(item.get("summary", ""))
                                   for word in ("承诺", "约定", "关系", "赠礼", "亲密")) else "events")
        layers[layer].append(item)
    rendered = []
    for key, items in layers.items():
        selected = sorted(enumerate(items), key=lambda pair: (_number(pair[1].get("importance"), 5), pair[0]), reverse=True)[:3]
        layers[key] = [copy.deepcopy(item) for _, item in selected]
        rendered.extend(_memory_line(item)[:100] for _, item in selected)
    character.setdefault("npc_memory_layers", {})[npc_name] = layers
    summaries[npc_name] = "\n".join(rendered)[:1000]
    memories[npc_name] = recent
    return True


def record_npc_memories(
    character: Dict,
    updates,
    source: str = "interaction",
    turn_id: str = None,
) -> bool:
    if not isinstance(updates, list):
        return False
    memories = character.setdefault("npc_memories", {})
    now = datetime.now().isoformat()
    changed = False
    for item in updates:
        if not isinstance(item, dict):
            continue
        name = canonical_npc_name(str(item.get("npc_name") or item.get("name") or "").strip())
        summary = str(item.get("summary") or item.get("memory") or "").strip()
        if not name or not summary:
            continue
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [part.strip() for part in re.split(r"[、,，]", tags) if part.strip()]
        bucket = memories.setdefault(name, [])
        if turn_id and any(
            entry.get("source_turn_id") == turn_id and entry.get("summary") == summary[:300]
            for entry in bucket if isinstance(entry, dict)
        ):
            continue
        source_name = str(item.get("source", source))
        knowledge_type = item.get("knowledge_type") or _default_knowledge_type(source_name, item.get("source_npc"))
        entry = {
            "id": item.get("id") or f"mem_{uuid.uuid4().hex}",
            "summary": summary[:300], "tags": tags, "source": source_name,
            "importance": estimate_memory_importance(summary, tags, source_name, item.get("importance")),
            "emotion": item.get("emotion") or infer_memory_emotion(summary, tags),
            "created_at": item.get("created_at") or now, "last_used_at": item.get("last_used_at"),
            "used_count": _number(item.get("used_count"), 0),
            "source_turn_id": turn_id or item.get("source_turn_id"),
            "knowledge_type": knowledge_type,
            "source_npc": canonical_npc_name(item.get("source_npc")),
            "confidence": max(0, min(1, float(item.get("confidence", _default_confidence(knowledge_type))))),
            "truth_status": item.get("truth_status", "accepted"),
            "fact_key": item.get("fact_key"),
            "superseded_by": item.get("superseded_by"),
            "owner_npc_id": npc_identity(name)["npc_id"],
            "owner_npc_name": name,
            "attribution_status": item.get("attribution_status", "confirmed" if source_name.startswith(("producer", "system")) else "legacy_unverified"),
            "attribution_reason": item.get("attribution_reason", ""),
            "proposed_npc_id": item.get("proposed_npc_id"),
            "evidence_text": item.get("evidence_text"),
        }
        _resolve_fact_conflicts(character.get("npc_memory_archive", {}).get(name, []) + bucket, entry)
        bucket.append(entry)
        compress_npc_memory_bucket(character, name)
        changed = True
    return changed


def _relationship_names(value: str) -> List[str]:
    names = []
    for part in re.split(r"[,，、]\s*", str(value or "")):
        separator = ":" if ":" in part else "：" if "：" in part else None
        if separator:
            name = part.split(separator, 1)[0].strip()
            if name and name not in names:
                names.append(name)
    return names


def build_auto_memory_updates(character: Dict, result: Dict, user_input_text: str, scene: str, source: str, npc_name: str = None, scene_npcs: List[Dict] = None, relationship_update: str = None, task_updates=None) -> List[Dict]:
    updates = []
    targets = interaction_targets(user_input_text, npc_name, scene_npcs)

    def add(target, summary, tags, importance, fact_key=None):
        if target and summary:
            updates.append({"npc_name": target, "summary": summary[:300], "tags": tags, "importance": importance, "source": source, "knowledge_type": "direct", "confidence": 0.9, "fact_key": fact_key, "attribution_status": "confirmed", "evidence_text": str(user_input_text)})

    if relationship_update:
        for part in re.split(r"[,，、]\s*", relationship_update):
            names = _relationship_names(part)
            if names and canonical_npc_name(names[0]) in targets:
                add(canonical_npc_name(names[0]), f"关系变化记录：{part}", ["关系"], 8, f"relationship:{canonical_npc_name(names[0])}")
    battle = result.get("spellcard_result")
    if isinstance(battle, dict) and any(battle.get(key) for key in ("opponent", "outcome", "summary", "spellcard_name")):
        target = canonical_npc_name(str(battle.get("opponent") or npc_name or ""))
        if target in targets and battle.get("rule_source"):
            add(target, f"规则结算：与玩家的符卡战，结果 {battle.get('outcome', '未裁定')}", ["符卡", "战斗"], 8)
    if any(word in str(user_input_text) for word in ("承诺", "约定", "保证", "背叛", "救", "赠送", "礼物", "秘密", "称呼", "亲密", "喜欢", "威胁", "羞辱")):
        for target in targets:
            add(target, f"玩家向{target}表达的行动/话语（不证明结果已发生）：{str(user_input_text).strip()}", ["互动", "玩家原文"], 7)
    return updates


def record_open_event(character: Dict, event, scene: str, turn_id: str = None) -> bool:
    if not isinstance(event, dict) or not (event.get("title") or event.get("description")):
        return False
    events = character.setdefault("open_events", [])
    event_id = event.get("id")
    if event_id and any(item.get("id") == event_id for item in events if isinstance(item, dict)):
        return False
    if turn_id and any(
        item.get("source_turn_id") == turn_id
        and item.get("title") == (event.get("title") or "自由探索事件")
        for item in events if isinstance(item, dict)
    ):
        return False
    events.append({
        "id": event_id, "title": event.get("title") or "自由探索事件",
        "type": event.get("type", "自由探索"), "scene": event.get("scene") or scene,
        "npc_name": event.get("npc_name"), "description": event.get("description", ""),
        "hooks": event.get("hooks", []), "source": event.get("source", "ai"),
        "source_turn_id": turn_id,
        "created_at": event.get("created_at") or datetime.now().isoformat(),
    })
    character["open_events"] = events[-80:]
    return True


def record_spellcard_result(character: Dict, result, scene: str, turn_id: str = None) -> bool:
    if not isinstance(result, dict) or not any(result.get(key) for key in ("opponent", "outcome", "summary", "spellcard_name")):
        return False
    battles = character.setdefault("spellcard_history", [])
    if turn_id and any(
        item.get("source_turn_id") == turn_id for item in battles if isinstance(item, dict)
    ):
        return False
    battles.append({
        "scene": scene, "opponent": result.get("opponent", "未知对手"),
        "spellcard_name": result.get("spellcard_name", "未命名符卡"),
        "outcome": result.get("outcome", "未裁定"), "summary": result.get("summary", ""),
        "cost": result.get("cost", ""),
        "metrics": result.get("metrics", {}),
        "mastery": result.get("mastery", {}),
        "rule_source": result.get("rule_source"),
        "source_turn_id": turn_id,
        "created_at": datetime.now().isoformat(),
    })
    character["spellcard_history"] = battles[-50:]
    return True
