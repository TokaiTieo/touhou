"""Read-only, identity-bound evidence views. Relevance never grants access."""

import copy
import hashlib
import json
import re

from backend.services.agent_contracts import Reader
from backend.services.conversation_archive_service import all_history
from backend.services.npc_identity_service import npc_registry, canonical_npc_id
from backend.services.npc_memory_service import recall_npc_memories_readonly


HOST = "@host"
PLAYER = "@player"
CONTEXT_POLICY_VERSION = 4


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def catalogue(character):
    records = copy.deepcopy(npc_registry()[0])
    # Save-local custom characters must have stable IDs and cannot shadow built-ins.
    custom = character.get("custom_npcs", [])
    for item in custom if isinstance(custom, list) else []:
        if isinstance(item, dict) and item.get("id") and item.get("name") and item["id"] not in records:
            records[item["id"]] = copy.deepcopy(item)
    return records


def storage_name(records, identity):
    name = records[identity]["name"]
    return name if sum(row.get("name") == name for row in records.values()) == 1 else "id:" + identity


class EvidenceContext:
    TOOLS = frozenset(("search_history", "recall_npc_memory", "search_world_info", "get_task_context", "get_npc_context"))

    def __init__(self, reader: Reader, character, tasks, scene, *, records=None, world_entries=(), present_ids=(), wiki=None):
        if reader.save_id != str(character.get("character_id")) or reader.epoch != str(character.get("timeline_epoch", "")):
            raise ValueError("Reader belongs to a different save or timeline")
        self.reader = reader
        self._character, self._tasks = copy.deepcopy(character), copy.deepcopy(tasks)
        self._records = copy.deepcopy(records if records is not None else catalogue(character))
        if reader.npc_id != HOST and reader.npc_id not in self._records:
            raise ValueError("Unknown stable NPC ID")
        self._world = copy.deepcopy(list(world_entries))
        self._wiki = wiki
        self.scene = scene
        self._present = frozenset(present_ids)
        self.usage = []

    def _ids(self, people):
        names = {npc.get("name"): key for key, npc in self._records.items()
                 if sum(row.get("name") == npc.get("name") for row in self._records.values()) == 1}
        result = set()
        for person in people if isinstance(people, list) else []:
            if isinstance(person, dict):
                person = person.get("npc_id") or person.get("npc_name")
            if isinstance(person, str):
                result.add(canonical_npc_id(names.get(person, person)))
        return result

    def _visible(self, record, *, owner=None, player_history=False, public_world=False):
        if record.get("timeline_epoch") not in (None, "", self.reader.epoch):
            return False
        if record.get("attribution_status") == "pending" or record.get("truth_status") in ("superseded", "retracted", "revoked"):
            return False
        visibility = record.get("visibility") or {}
        if not isinstance(visibility, dict):
            return False
        audience = self._ids(visibility.get("audience", []))
        identity = self.reader.npc_id
        if identity == HOST:
            # Host publication never receives another person's private notebook.
            return bool(PLAYER in audience or record.get("shared_with_player") is True
                        or (player_history and visibility.get("scope") == "interaction_only")
                        or (public_world and visibility.get("scope", "public") == "public"))
        if owner == identity:
            return True
        if identity in audience:
            return True
        return bool(public_world and visibility.get("scope", "public") == "public")

    def _select(self, rows, query="", limit=8, budget_chars=5000):
        terms = set(re.findall(r"[\w]+", str(query)))
        # Character bigrams support Chinese without a paid embedding request.
        terms.update(str(query)[index:index + 2] for index in range(max(0, len(str(query)) - 1)))
        scored = sorted(enumerate(rows), key=lambda pair: (
            -sum(term in json.dumps(pair[1], ensure_ascii=False) for term in terms), -pair[0]))
        result, used = [], 0
        for _, row in scored:
            bound = {**row, "scope": {"save_id": self.reader.save_id, "epoch": self.reader.epoch,
                                      "reader_id": self.reader.npc_id, "permission_version": self.reader.permission_version}}
            size = len(json.dumps(bound, ensure_ascii=False))
            if used + size <= min(12000, max(0, budget_chars)):
                result.append(copy.deepcopy(bound))
                used += size
            if len(result) >= min(30, max(1, limit)):
                break
        return result

    def search_history(self, query="", limit=8, budget_chars=5000):
        rows = []
        history = []
        for item in all_history(self._character):
            history.append(item)
            for part in item.get("agent_inputs", []) if isinstance(item, dict) else []:
                history.append({**item, "message_id": str(item.get("message_id")) + ":" + part["npc_id"],
                                "content": part["content"], "visibility": {"scope": "recipients", "audience": [PLAYER, part["npc_id"]]},
                                "participants": [part["npc_id"]], "agent_inputs": []})
        for item in history:
            if not isinstance(item, dict) or not self._visible(item, player_history=True):
                continue
            rows.append({"id": item.get("message_id") or digest(item), "kind": "history", "source": "recorded_utterance",
                         "truth_status": "speech_not_verified_fact", "speaker": item.get("speaker"),
                         "npc_id": item.get("npc_id"), "participants": item.get("participants", []),
                         "visibility": item.get("visibility"), "scene": item.get("scene"),
                         "content": item.get("content", "")})
        return self._select(rows, query, limit, budget_chars)

    def recall_npc_memory(self, query="", limit=8, budget_chars=5000):
        if self.reader.npc_id == HOST:
            # Player-shared experiences are a separate publication source.
            items = self._character.get("life_state", {}).get("shared_experiences", [])
            rows = [{"id": item.get("id") or digest(item), "kind": "shared_experience", **copy.deepcopy(item)}
                    for item in items if isinstance(item, dict) and self._visible(item)]
            return self._select(rows, query, limit, budget_chars)
        owner_key = storage_name(self._records, self.reader.npc_id)
        rows = []

        def eligible(item):
            return (item.get("owner_npc_id") in (None, "", self.reader.npc_id)
                    and self._visible(item, owner=self.reader.npc_id))

        # Filter before embedding, ranking and top-k, not just before publication.
        for item in recall_npc_memories_readonly(self._character, owner_key, query=query, limit=30, eligible=eligible):
            rows.append({**item, "id": item.get("id") or digest(item), "kind": "memory", "owner_npc_id": self.reader.npc_id})
        for item in self._character.get("life_state", {}).get("diaries", {}).get(self.reader.npc_id, []):
            if isinstance(item, dict) and self._visible(item, owner=self.reader.npc_id):
                rows.append({**copy.deepcopy(item), "id": item.get("id") or digest(item), "kind": "diary"})
        selected = self._select(rows, query, limit, budget_chars)
        self.usage.extend({"npc_name": owner_key, "memory_id": item["id"]} for item in selected if item["kind"] == "memory")
        return selected

    def search_world_info(self, query="", limit=6, budget_chars=2500, source="combined"):
        if source not in ("combined", "world_book"):
            raise ValueError("未知的世界知识来源")
        rows, excluded = [], set()
        if self._wiki:
            authorized = {entry.get("id") for entry in self._world if isinstance(entry, dict)
                          and self._visible(entry, public_world=True)
                          and entry.get("status") not in ("draft", "pending", "revoked", "retracted", "withdrawn")
                          and entry.get("truth_status") != "pending"}
            rows, excluded = self._wiki.rows(self.reader.npc_id, self.scene, query,
                                             original=source == "world_book", allowed_books=authorized)
        for item in self._world:
            if not isinstance(item, dict) or item.get("id") in excluded or not self._visible(item, public_world=True):
                continue
            if item.get("status") in ("draft", "pending", "revoked", "retracted", "withdrawn") or item.get("truth_status") == "pending":
                continue
            keywords = item.get("keywords", [])
            keywords = [keywords] if isinstance(keywords, str) else keywords
            if item.get("constant") or any(str(word) in query + self.scene for word in keywords):
                rows.append({"id": item.get("id") or digest(item), "kind": "world_info", "content": item.get("content"),
                             "visibility": item.get("visibility", {"scope": "public"}), "source": "world_book"})
        return self._select(rows, query, limit, budget_chars)

    def get_task_context(self, query="", limit=6, budget_chars=2500):
        rows = []
        for item in self._tasks.get("active_tasks", []):
            if not isinstance(item, dict):
                continue
            # Old player tasks are not public knowledge by default.
            if self.reader.npc_id == HOST and not item.get("visibility") or self._visible(item):
                rows.append({key: copy.deepcopy(value) for key, value in item.items()
                             if key in ("id", "name", "title", "description", "progress", "status", "visibility")})
        events = self._character.get("agent_state", {}).get("events", [])
        for item in events:
            if isinstance(item, dict) and item.get("status") == "pending" and self._visible(item):
                rows.append({**copy.deepcopy(item), "kind": "pending_event"})
        return self._select(rows, query, limit, budget_chars)

    def get_npc_context(self, npc_id=None, query="", limit=8, budget_chars=6000):
        identity = npc_id or self.reader.npc_id
        if identity == HOST:
            identities = sorted(self._present)
        else:
            identities = [identity]
        rows = []
        for key in identities:
            npc = self._records.get(key)
            if not npc or key != self.reader.npc_id and key not in self._present:
                continue
            name = npc["name"]
            row = {"id": key, "kind": "npc", "npc_id": key, "name": name}
            profile = npc.get("profile", {})
            if key == self.reader.npc_id:
                name = storage_name(self._records, key)
                row.update(profile=copy.deepcopy(profile),
                           state=copy.deepcopy(self._character.get("npc_runtime", {}).get(name, {})),
                           goals=copy.deepcopy(self._character.get("npc_agency", {}).get("npcs", {}).get(name, {})),
                           resources=copy.deepcopy(self._character.get("life_state", {}).get("npc_resources", {}).get(name, {})),
                           relationship=copy.deepcopy(self._character.get("relationship_progress", {}).get(name, {})),
                           relationship_dimensions=copy.deepcopy(self._character.get("relationship_dimensions", {}).get(name, {})),
                           boundaries=copy.deepcopy(self._character.get("relationship_boundaries", {}).get(name, {})))
            else:
                row["profile"] = {k: copy.deepcopy(profile[k]) for k in ("identity", "appearance") if k in profile}
                row["scene"] = self.scene
            rows.append(row)
        selected = self._select(rows, query, limit, budget_chars)
        if identity == self.reader.npc_id and identity != HOST and not selected:
            raise ValueError("人物本人资料超过上下文预算；请缩短自定义资料后重试，未发送人物请求")
        return selected

    def query(self, tool, arguments):
        if tool not in self.TOOLS:
            raise ValueError("Unknown evidence tool")
        allowed = {"query", "limit", "budget_chars"} | ({"npc_id"} if tool == "get_npc_context" else set())
        if tool == "search_world_info":
            allowed.add("source")
        if not isinstance(arguments, dict) or set(arguments) - allowed:
            raise ValueError("Evidence identity and permissions are server-bound")
        return getattr(self, tool)(**arguments)

    def assemble(self, action, budget_chars=15000):
        # Each section consists of complete, scoped records, never chopped identities.
        sections = {
            "identity": self.get_npc_context(budget_chars=5000),
            "memories": self.recall_npc_memory(action, budget_chars=3500),
            "history": self.search_history(action, budget_chars=3500),
            "world_info": self.search_world_info(action, budget_chars=1800),
            "tasks": self.get_task_context(action, budget_chars=1200),
        }
        used, result = 0, {}
        for section, rows in sections.items():
            result[section] = []
            for row in rows:
                size = len(json.dumps(row, ensure_ascii=False))
                if used + size <= budget_chars:
                    result[section].append(row)
                    used += size
        return result
