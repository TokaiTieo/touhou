"""NPC memory capture, compression, retrieval and turn record persistence."""

import re
from datetime import datetime
from typing import Dict, List

from backend.services.memory_retrieval import rank_memories


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
    memories = character.get("npc_memories", {})
    if not isinstance(memories, dict):
        return False
    for items in memories.values():
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
    return f"- [{kind}{source_npc}·可信{confidence}%·{status}] {item.get('summary', '')}"


def _resolve_fact_conflicts(bucket: List[Dict], new_entry: Dict) -> None:
    fact_key = new_entry.get("fact_key")
    if not fact_key:
        return
    new_confidence = float(new_entry.get("confidence", 0.75) or 0.75)
    for previous in bucket:
        if not isinstance(previous, dict) or previous.get("fact_key") != fact_key:
            continue
        if previous.get("truth_status", "accepted") == "superseded":
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
    memories = character.setdefault("npc_memories", {})
    upgrade_npc_memory_metadata(character)
    summaries = character.setdefault("npc_memory_summaries", {})
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
            memories.get(npc_name, []),
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
        lines = [f"长期印象：{summaries[npc_name]}"] if summaries.get(npc_name) else []
        lines.extend(_memory_line(item) for item in selected)
        return "\n".join(lines) if lines else f"{npc_name}: 暂无关键记忆"
    lines = []
    for name, items in memories.items():
        diagnostics_start = len(retrieval_diagnostics)
        selected = rank_memories(
            items,
            query,
            2,
            index_root.setdefault(name, {}),
            meta_root.setdefault(name, {}),
            retrieval_diagnostics,
        )
        for item in retrieval_diagnostics[diagnostics_start:]:
            item["npc_name"] = name
        touch(selected)
        recent = [_memory_line(item).removeprefix("- ") for item in selected if item.get("summary")]
        if summaries.get(name):
            recent.insert(0, f"长期印象：{summaries[name]}")
        if recent:
            lines.append(f"{name}: " + "；".join(recent))
    character["_last_memory_retrieval"] = retrieval_diagnostics
    return "\n".join(lines[-limit:]) if lines else "暂无关键NPC记忆"


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


def compress_npc_memory_bucket(character: Dict, npc_name: str, keep_recent: int = 24, force: bool = False) -> bool:
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
    important = sorted(old_items, key=lambda item: _number(item.get("importance"), 5), reverse=True)[:6]
    fragments = [summaries.get(npc_name, "")] + [item.get("summary", "") for item in important]
    summaries[npc_name] = "；".join(item for item in fragments if item)[:900]
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
        name = str(item.get("npc_name") or item.get("name") or "").strip()
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
            "id": item.get("id") or f"mem_{int(datetime.now().timestamp() * 1000)}_{len(bucket)}",
            "summary": summary[:300], "tags": tags, "source": source_name,
            "importance": estimate_memory_importance(summary, tags, source_name, item.get("importance")),
            "emotion": item.get("emotion") or infer_memory_emotion(summary, tags),
            "created_at": item.get("created_at") or now, "last_used_at": item.get("last_used_at"),
            "used_count": _number(item.get("used_count"), 0),
            "source_turn_id": turn_id or item.get("source_turn_id"),
            "knowledge_type": knowledge_type,
            "source_npc": item.get("source_npc"),
            "confidence": max(0, min(1, float(item.get("confidence", _default_confidence(knowledge_type))))),
            "truth_status": item.get("truth_status", "accepted"),
            "fact_key": item.get("fact_key"),
            "superseded_by": item.get("superseded_by"),
        }
        _resolve_fact_conflicts(bucket, entry)
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
    updates, targets = [], []
    if npc_name:
        targets.append(npc_name)
    for name in _relationship_names(relationship_update or result.get("relationship_update")):
        if name not in targets:
            targets.append(name)
    if not targets:
        targets.extend([npc.get("name") for npc in (scene_npcs or [])[:2] if npc.get("name")])

    def add(target, summary, tags, importance, fact_key=None):
        if target and summary:
            updates.append({"npc_name": target, "summary": summary[:300], "tags": tags, "importance": importance, "source": source, "knowledge_type": "direct", "confidence": 0.9, "fact_key": fact_key})

    if relationship_update:
        for name in _relationship_names(relationship_update):
            add(name, f"关系变化记录：{relationship_update}", ["关系"], 8, f"relationship:{name}")
    battle = result.get("spellcard_result")
    if isinstance(battle, dict) and any(battle.get(key) for key in ("opponent", "outcome", "summary", "spellcard_name")):
        target = str(battle.get("opponent") or npc_name or (targets[0] if targets else ""))
        add(target, f"符卡/战斗记忆：{battle.get('summary') or battle.get('outcome', '未裁定')}", ["符卡", "战斗"], 8)
    for task in task_updates or result.get("task_updates") or []:
        if isinstance(task, dict) and task.get("action") in ("update", "complete"):
            label = "完成" if task.get("action") == "complete" else "推进"
            for target in targets[:2]:
                add(target, f"线索{label}：{task.get('info') or task.get('name') or task.get('task_id')}", ["线索"], 6)
    event = result.get("dynamic_event") or result.get("open_event")
    if isinstance(event, dict) and (event.get("title") or event.get("description")):
        for target in targets[:2]:
            add(target, f"共同经历事件：{event.get('title', '自由探索')} - {event.get('description', '')}", ["事件"], 6)
    combined = f"{user_input_text}\n{result.get('description', '')}"
    if any(word in combined for word in ("承诺", "约定", "保证", "背叛", "救", "赠送", "礼物", "秘密", "称呼", "亲密", "喜欢", "威胁", "羞辱")):
        for target in targets[:2]:
            add(target, f"值得记住的互动：玩家在{scene}中{str(user_input_text).strip()[:80]}；后续结果：{str(result.get('description', ''))[:120]}", ["互动"], 7)
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
