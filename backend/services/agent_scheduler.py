"""Bounded activation, isolated decisions and one candidate/commit turn pipeline."""

import asyncio
import copy
import json
import re

from backend.services.action_resolution_service import performed_text
from backend.services.agent_contracts import AgentLimits, HostNarration, MAX_PARTICIPANTS, Reader, default_agent_state
from backend.services.agent_context_service import CONTEXT_POLICY_VERSION, EvidenceContext, HOST, PLAYER, catalogue, digest
from backend.services.agent_rules_service import ProposalMerger
from backend.services.life_simulation_service import absolute_hour
from backend.services.npc_agent_runtime import HOST_RESULT_POLICY_VERSION, NPCRuntime, npc_prompt, ledger_io, record_agent_usage
from backend.services.npc_identity_service import resolve_npc
from backend.services.npc_memory_service import commit_memory_usage
from backend.services.wiki_store import freeze as freeze_wiki


CALL_ENVELOPE_BYTES = 62000
_MODIFIERS = r"(?:(?:然后|随后|接着|同时|另外|转而|转头|转身|先|再|并且|并|只|悄悄|单独|私下|低声|分别|一起|共同)\s*)*"
_ADDRESS = re.compile(r"(?:我\s*)?" + _MODIFIERS + r"(?:我\s*)?(?P<lead>向|对着|对|与|和|跟|朝|给|询问|邀请|请教|帮助|协助|告诉|告知|拜托|提醒|安慰|感谢|答复|回应|问候|问)\s*")
_INTERACTION = re.compile(_MODIFIERS + r"(?:说|问好|问候|打招呼|问|告诉|告知|承诺|聊|交谈|对话|交流|商量|讨论|交涉|谈|交易|交换|递|转交|赠送|交给|提供|邀请|请教|帮助|协助|安慰|道歉|拜托|约定|请求|求助|询问|回应|答复|握手|挥手|点头|切磋|挑战|决斗|拥抱|亲吻|调查)")
_NOT_INTERACTING = re.compile(r"(?:我\s*)?" + _MODIFIERS + r"(?:不|没|未|别|拒绝|无法|不能|打算|计划|准备|想|如果|假如|听说|提到|独自)")
_PRIVATE_ASIDE = re.compile(r"(?:我\s*)?" + _MODIFIERS + r"(?:私下|悄悄|单独|低声|耳语)")
_SELF_PAUSE = re.compile(r"(?:我\s*)?(?:想了想|思考片刻|沉思片刻|停顿片刻|稍作停顿|独自坐下|坐下|沉默片刻)")
_CONNECTOR = re.compile(r"(?:然后|随后|接着|同时|另外|转而|转头|转身|再|并且|并|后)\s*(?=(?:我)?" + _MODIFIERS + r"(?:向|对|与|和|跟|朝|给|询问|邀请|请教|告诉|告知))")


def _unquoted_positions(text):
    pairs, stack, outside = {'"': '"', "'": "'", '“': '”', '‘': '’', '「': '」', '『': '』'}, [], set()
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and stack:
            index += 2
            continue
        apostrophe = (char == "'" and 0 < index < len(text) - 1
                      and text[index - 1:index + 2:2].isascii()
                      and text[index - 1].isalnum() and text[index + 1].isalnum())
        if stack and char == stack[-1] and not apostrophe:
            stack.pop()
        elif char in pairs and not apostrophe:
            stack.append(pairs[char])
        elif not stack:
            if char in ("”", "’", "」", "』"):
                raise ValueError("对话引号未配对，请明确每段互动的对象")
            outside.add(index)
        index += 1
    if stack:
        raise ValueError("对话引号未闭合，请明确每段互动的对象")
    return outside


def _input_sections(text):
    """Keep the UI's action/speech boundary instead of flattening both to prose."""
    text = text.strip()
    outside = _unquoted_positions(text)
    if text.startswith("（动作："):
        depth, end = 1, None
        for index in range(4, len(text)):
            if index not in outside:
                continue
            depth += (text[index] == "（") - (text[index] == "）")
            if depth == 0:
                end = index
                break
        if end is None:
            raise ValueError("动作括号未闭合，请明确每段互动的对象")
        tail = text[end + 1:].strip()
        return [("action", text[4:end]), ("speech" if _quoted_continuation(tail) else "raw", tail)]
    markers = [match for match in re.finditer(r"【(?:动作|语言)】", text) if match.start() in outside]
    if not markers:
        return [("raw", text)]
    sections = [("raw", text[:markers[0].start()].strip())]
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        sections.append(("speech" if marker[0] == "【语言】" else "action", text[marker.end():end].strip()))
    return sections


def _address_list_prefix(text, names):
    head = _ADDRESS.match(text.strip())
    if not head:
        return False
    rest = text.strip()[head.end():]
    while rest:
        name = next((name for name in names if rest.startswith(name)), None)
        if name is None:
            return False
        rest = rest[len(name):].lstrip()
        if not rest:
            return True
        separator = re.match(r"^(?:、|和|与|及|,|，)\s*", rest)
        if not separator:
            return False
        rest = rest[separator.end():]
    return False


def _interaction_clauses(text, names):
    """Split unquoted sentences, keeping only address-list commas together."""
    outside = _unquoted_positions(text)
    start, index, clauses = 0, 0, []
    while index < len(text):
        if index in outside:
            char, tail = text[index], text[index + 1:].lstrip()
            separator = char in "。；;！!？?\n" or (char == "." and not (index and text[index - 1].isdigit() and tail[:1].isdigit()))
            separator = separator or (char in "，,、" and
                (bool(_ADDRESS.match(tail)) or not _address_list_prefix(text[start:index], names)))
            connector = _CONNECTOR.match(text, index)
            if separator or connector:
                if text[start:index].strip():
                    clauses.append(text[start:index].strip())
                start = index + 1 if separator else connector.end()
                index = start
                continue
        index += 1
    if text[start:].strip():
        clauses.append(text[start:].strip())
    return clauses


def _quoted_continuation(text):
    body = re.sub(r"^(?:我)?(?:继续说|接着说|补充道|说道|说)\s*[:：]?\s*", "", text).strip()
    return bool(body and body[0] in ('"', "'", '“', '‘', '「', '『')
                and all(body[index].isspace() for index in _unquoted_positions(body)))


def _clause_targets(clause, names, preferred):
    head = _ADDRESS.match(clause)
    if not head:
        return None
    rest, targets = clause[head.end():], []
    while rest:
        name = next((name for name in names if rest.startswith(name)), None)
        if name is None:
            if targets:
                raise ValueError("互动名单中存在无法确定的人物，请使用完整姓名或分别发送")
            return []
        identities = names[name]
        if len(identities) > 1:
            identities = [identity for identity in identities if identity in preferred]
            if len(identities) != 1:
                raise ValueError("人物姓名重复，请先选择唯一的 NPC 再发送互动")
        targets.append(identities[0])
        rest = rest[len(name):].lstrip()
        separator = re.match(r"^(?:、|和|与|及|,|，)\s*", rest)
        if not separator:
            break
        following = rest[separator.end():]
        if separator[0].strip() in (",", "，") and not any(following.startswith(name) for name in names):
            rest = following
            break
        rest = following
        if not rest:
            raise ValueError("互动名单不完整，请明确每段互动的对象")
    if not targets or rest.startswith("的"):
        return []
    # After a speech verb (e.g. "tell A"), negation belongs to the payload.
    if head["lead"] in ("向", "对着", "对", "与", "和", "跟", "朝", "给") and (
            _NOT_INTERACTING.match(rest) or not _INTERACTION.match(rest)):
        return []
    for index in _unquoted_positions(rest):
        nested = _ADDRESS.match(rest, index)
        if index and nested and any(rest[nested.end():].startswith(name) for name in names):
            raise ValueError("同一段存在多个可能的互动对象，请分句写明；转述的话请加引号")
    return list(dict.fromkeys(targets))


def server_presence(character, records, scene):
    from backend.location_manager import get_location_manager
    from backend.world_manager import get_locations_dir
    from backend.services.npc_schedule_service import scheduled_location
    manager = get_location_manager(get_locations_dir())
    location = manager.get_location_by_name(scene)
    aliases = {scene, location.id if location else scene}
    if location:
        aliases.add(location.parent)
        if location.type == "region":
            for child in manager.get_all_locations().values():
                if hasattr(child, "parent") and child.parent == location.id:
                    aliases.update((child.id, child.name))
    result = []
    hour = character.get("time", {}).get("current_hour", 8)
    snapshot = copy.deepcopy(character)
    for key, npc in records.items():
        default = npc.get("location_name") or npc.get("location_id") or ""
        actual, _ = scheduled_location(npc["name"], hour, default, snapshot)
        if actual in aliases:
            result.append(key)
    return result


def interaction_segments(turn, records):
    """Route each utterance independently, including explicit UI dialogue targets."""
    selected = [key for key in turn.interaction_npc_ids if key in records]
    if turn.npc_id:
        npc = resolve_npc(turn.npc_id)
        identity = npc["id"] if npc else turn.npc_id
        selected = [identity] if identity in records else []
    if turn.is_continue:
        if turn.kind != "npc_dialogue" or not turn.npc_id or len(selected) != 1:
            raise ValueError("继续对话需要明确选择当前 NPC")
        return {selected[0]: "玩家等待你继续当前对话，没有新的发言或动作。"}
    names = {}
    for key, npc in records.items():
        names.setdefault(npc["name"], []).append(key)
    names = dict(sorted(names.items(), key=lambda pair: -len(pair[0])))
    output, current = {}, list(selected)
    # None means UI-default; [] means blocked. Explicit targets survive only
    # known self pauses, never an unknown action that might change the audience.
    speech_audience = None

    def distribute(clause, audience):
        for key in audience:
            output[key] = (output.get(key, "") + "\n" + clause).strip()

    for kind, text in _input_sections(turn.action_text):
        if not text:
            continue
        if kind == "speech":
            if speech_audience == []:
                raise ValueError("后续发言的对象不明确，请在动作中重新写明接收者")
            current = list(selected) if speech_audience is None else list(speech_audience)
            distribute(text, current)
            continue
        for clause in _interaction_clauses(text, names):
            targets = _clause_targets(clause, names, selected)
            if targets is not None:
                current = targets
                speech_audience = list(targets)
                distribute(clause, current)
            elif _quoted_continuation(clause):
                distribute(clause, current)
            else:
                if _PRIVATE_ASIDE.match(clause) and len(current) != 1:
                    raise ValueError("私下互动的对象不明确，请单独写出接收者")
                nonverbal_refusal = any(re.fullmatch(
                    r"(?:我)?(?:不|没有)(?:向|朝|对着)" + re.escape(name) + r"(?:挥手|点头|问好|打招呼)", clause)
                    for name in names)
                if (speech_audience is not None or selected) and not _SELF_PAUSE.fullmatch(clause) and not nonverbal_refusal:
                    speech_audience = []
                # An unparsed action proves no audience. Do not attach its body
                # or a following quote to the last (or UI-selected) recipient.
                current = []
    return output


def activation_plan(turn, character, records, *, present_ids=None):
    inputs = interaction_segments(turn, records)
    ordered = list(inputs)
    events = character.get("agent_state", {}).get("events", [])
    # Pending dependencies matter only after a relevant player interaction starts.
    for event in sorted(events, key=lambda item: (-int(item.get("priority", 0)), item.get("id", ""))):
        if event.get("status") == "pending" and event.get("actor_id") in ordered:
            target = event.get("target_id")
            if target in records and target not in ordered:
                ordered.append(target)
    present = set(records if present_ids is None else present_ids)
    active = [key for key in ordered if key in present][:MAX_PARTICIPANTS]
    return active, [key for key in ordered if key not in active], inputs


def _world_entries():
    from backend.world_manager import get_current_world_path
    path = get_current_world_path() / "world_info.json"
    return json.loads(path.read_text(encoding="utf-8-sig")).get("entries", []) if path.is_file() else []


def sync_legacy_appointments(character, records):
    state = character.setdefault("agent_state", default_agent_state())
    names = {row["name"]: identity for identity, row in records.items()}
    for item in character.get("life_state", {}).get("appointments", []):
        identity = names.get(item.get("npc_name"))
        if not identity:
            continue
        old = next((event for event in state["events"] if event["id"] == item["id"]), None)
        if item.get("status") == "proposed":
            event = {"id": item["id"], "actor_id": PLAYER, "target_id": identity, "kind": "invite", "status": "pending",
                     "hour": item["hour"], "scene": item["scene"], "priority": 100,
                     "visibility": {"scope": "recipients", "audience": [PLAYER, identity]}, "source": "life_appointment"}
            if old:
                old.update(event)
            else:
                state["events"].append(event)
        elif old and item.get("status") in ("cancelled", "missed", "completed"):
            old["status"] = item["status"]


def _initial_result(context):
    from backend.location_manager import get_location_manager
    from backend.world_manager import get_locations_dir
    result = {"description": "", "contract_valid": True, "time_cost": 0.25,
              "task_updates": [], "memory_updates": [], "is_dead": False, "new_location": None}
    action = performed_text(context.turn.action_text)
    duration = re.search(r"(\d+(?:\.\d+)?)\s*(小时|分钟)", action)
    if duration:
        result["time_cost"] = min(12, float(duration[1]) / (60 if duration[2] == "分钟" else 1))
    if context.turn.kind == "environment":
        locations = get_location_manager(get_locations_dir()).get_all_locations()
        for location in locations.values():
            name = location.name if hasattr(location, "name") else location.get("name", "")
            if name and re.search(r"(?:前往|走向|到达|返回|去)\s*" + re.escape(name), action):
                result["new_location"] = {"name": name, "type": "existing"}
                break
    return result


def narration_audit(text, events):
    citations = {item["id"] for item in events}
    return {"kind": "structural_not_semantic", "semantic_consistency": "unverified",
            "canonical_event_ids": sorted(citations), "narration_hash": digest(text),
            "note": "人物决定以独立原文与规则结果为准；自由叙事仍可能存在语义矛盾"}


async def run_agent_turn(context, *, runtime=None, records=None, present_ids=None, world_entries=None, persist=True):
    from backend.services.turn_orchestrator import turn_orchestrator
    from backend.services.turn_runner import turn_runner
    from backend.services.evaluation_context import evaluation_context
    evaluation = evaluation_context.get()
    candidate = context.model_copy(deep=True)
    snapshot = copy.deepcopy(context.character)
    records = catalogue(snapshot) if records is None else copy.deepcopy(records)
    sync_legacy_appointments(snapshot, records)
    sync_legacy_appointments(candidate.character, records)
    scene = snapshot.get("status", {}).get("current_scene") or context.turn.scene
    if context.turn.scene != scene:
        raise ValueError("当前场景已变化，请刷新后重试")
    present = server_presence(snapshot, records, scene) if present_ids is None else list(present_ids)
    entries = _world_entries() if world_entries is None else world_entries
    active, deferred, inputs = activation_plan(context.turn, snapshot, records, present_ids=present)
    # The whole-turn set only grows, and never exceeds six, even across batches.
    selected, completed, access = list(active), {}, []
    state = candidate.character.setdefault("agent_state", default_agent_state())
    state["mode"] = "collaborative"
    scope = "npc-turn:" + digest([context.turn.character_id, snapshot.get("timeline_epoch", ""), context.turn.turn_id])
    runtime = runtime or await ledger_io(NPCRuntime, scope, AgentLimits.model_validate(state.get("limits", {})),
                                         generate=evaluation.generate if evaluation else None, checkpoint=evaluation is None)
    wiki = await ledger_io(freeze_wiki, runtime.ledger)
    runtime.evidence_guard = wiki.check if wiki else None
    fingerprint = digest({**({"wiki": wiki.fingerprint} if wiki else {}), "context_policy": CONTEXT_POLICY_VERSION,
                          "revision": context.base_character_revision, "tasks_revision": context.base_tasks_revision,
                          "epoch": snapshot.get("timeline_epoch", ""), "permissions": state.get("permission_version", 1),
                          "turn": context.turn.model_dump(), "snapshot": {k: v for k, v in snapshot.items()
                            if k not in ("story_summary", "last_played", "_last_context_budget")}, "records": records, "world": entries})
    slots = {"host": digest([fingerprint, "host", HOST_RESULT_POLICY_VERSION])}
    slots.update({str(index): digest([fingerprint, "npc", index]) for index in range(MAX_PARTICIPANTS) if active})
    bound = CALL_ENVELOPE_BYTES + runtime.limits.max_output_tokens + 256
    await ledger_io(runtime.ledger.reserve, {job: bound for job in slots.values()}, replace_pending=True)
    merger = ProposalMerger(candidate.character, records, context.turn.turn_id, scene, present)

    def reader(identity):
        return Reader(save_id=context.turn.character_id, epoch=str(snapshot.get("timeline_epoch", "")), npc_id=identity,
                      task_id=str(context.turn.turn_id), permission_version=int(state.get("permission_version", 1)))

    def view(identity):
        source = copy.deepcopy(snapshot)
        source.setdefault("agent_state", {})["events"] = copy.deepcopy(merger.state["events"])
        return EvidenceContext(reader(identity), source, context.tasks, scene,
                               records=records, world_entries=entries, present_ids=present, wiki=wiki)

    await ledger_io(runtime.ledger.register_turn, reader(HOST), fingerprint)

    async def decide(identity):
        if wiki:
            await ledger_io(wiki.check)
        evidence_view = view(identity)
        action = inputs.get(identity, "回应本人收到且尚未处理的互动；未向你披露的玩家指令不可推测")
        evidence = evidence_view.assemble(action)
        intent = "continue_dialogue" if context.turn.is_continue and identity in inputs else "interaction"
        prompt = npc_prompt(reader(identity), evidence, action, [PLAYER, *present], absolute_hour(snapshot), intent=intent)
        if len(prompt.encode("utf-8")) > CALL_ENVELOPE_BYTES:
            raise ValueError("人物上下文超过预留预算，尚未发送请求")
        checkpoint_job = runtime.job(reader(identity), fingerprint, prompt)
        outcome = await runtime.invoke(reader(identity), prompt, evidence, checkpoint_job, billing_job=slots[str(selected.index(identity))])
        return identity, outcome, evidence_view.usage

    async def workflow():
        nonlocal candidate
        turn_runner.mark(context, "npc_deciding")
        waiting = list(active)
        while waiting:
            batch = waiting[:runtime.limits.concurrency]
            waiting = waiting[len(batch):]
            # Dependencies on already pending senders are resolved before recipients.
            for event in merger.state["events"]:
                source, target = event.get("actor_id"), event.get("target_id")
                if event.get("status") == "pending" and source in batch and target in batch and source != target:
                    batch.remove(target)
                    waiting.insert(0, target)
            jobs = [asyncio.create_task(decide(identity)) for identity in batch]
            try:
                outcomes = await asyncio.gather(*jobs)
            except BaseException:
                for task in jobs:
                    # gather already cancels siblings on parent cancellation. A
                    # second cancel would interrupt their ledger cleanup await.
                    if not task.done() and not task.cancelling():
                        task.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
                raise
            for identity, outcome, usage in outcomes:
                if asyncio.current_task().cancelling():
                    raise asyncio.CancelledError()
                completed[identity] = outcome
                access.extend(usage)
                evidence_ids = [item["id"] for rows in outcome["evidence"].values() for item in rows if item.get("id")]
                results = merger.merge(identity, outcome["result"], evidence_ids)
                for old_event in merger.state["events"]:
                    if old_event.get("target_id") == identity and old_event.get("kind") == "player_interaction" and old_event.get("status") == "pending":
                        old_event["status"] = "processed"
                for event in results:
                    pending = event.get("pending_event")
                    target = (pending or {}).get("target_id")
                    if target not in records or target in selected:
                        continue
                    if len(selected) < MAX_PARTICIPANTS and target in present:
                        selected.append(target)
                        waiting.append(target)
                    elif target not in deferred:
                        deferred.append(target)

        # Deferred requests survive in the formal candidate, never as invented decisions.
        for identity in deferred:
            event_id = "deferred_" + digest([context.turn.turn_id, identity])[:24]
            if not any(item["id"] == event_id for item in merger.state["events"]):
                merger.state["events"].append({"id": event_id, "kind": "player_interaction", "actor_id": PLAYER,
                    "target_id": identity, "status": "pending", "priority": 100, "text": inputs.get(identity, "待处理互动"),
                    "visibility": {"scope": "recipients", "audience": [PLAYER, identity]}, "turn_id": context.turn.turn_id})
        candidate.turn.scene_npcs = [records[key] for key in selected]
        turn_runner.mark(context, "candidate_settlement")
        def prepare():
            initial = _initial_result(candidate)
            initial["agent_inputs"] = [] if context.turn.is_continue else [
                {"npc_id": key, "content": value} for key, value in inputs.items() if key in selected]
            for part in initial["agent_inputs"]:
                merger._remember_speech(PLAYER, [part["npc_id"]], part["content"], "input_" + digest([fingerprint, part["npc_id"]])[:24])
            turn_orchestrator.settle(candidate, initial, persist=False)
            return candidate.model_dump(mode="json")
        from backend.services.turn_models import TurnContext
        prepared = await runtime.candidate(digest([fingerprint, "candidate"]), prepare)
        candidate = TurnContext.model_validate(prepared)
        result = candidate.prepared_result
        public_events = [copy.deepcopy(event) for event in merger.results if PLAYER in event.get("visibility", {}).get("audience", [])]
        host_view = view(HOST).assemble(context.turn.action_text)
        public_settlement = {key: result.get(key) for key in ("player_state_delta", "progression_delta", "time_cost", "new_location",
                                                              "spellcard_result", "activity_resolution", "task_updates", "inventory_updates")}
        publication = {"scene": scene, "player_input": context.turn.action_text, "evidence": host_view,
                       "verified_results": public_settlement, "npc_decisions": public_events,
                       "deferred_npcs": [records[key]["name"] for key in deferred]}
        schema = HostNarration.model_json_schema()
        if public_events:
            schema["properties"]["cited_event_ids"]["items"]["enum"] = [event["id"] for event in public_events]
        else:
            schema["properties"]["cited_event_ids"]["maxItems"] = 0
        prompt = ("你是东方异变录的主持人。只用以下玩家可见资料组织自然叙事，不访问秘密。\n"
                  "NPC 的发言和决定由本人产生并会单独原文展示；不得替他们同意、拒绝、改口或新增行动。\n"
                  "规则结果已结算，不能更改时间、资源、奖励和人物决定；待处理互动明确尚未处理。\n"
                  "不重复转述整段人物发言，着重描写环境与已验证效果。引用只选 npc_decisions 的完整 id，不确定可返回空列表。\n"
                  "尊重玩家自由探索和交往，保持角色设定。只输出 schema 规定的 JSON。\n" +
                  json.dumps({"publication": publication, "schema": schema}, ensure_ascii=False))
        if len(prompt.encode("utf-8")) > CALL_ENVELOPE_BYTES:
            raise ValueError("发布上下文超过预留预算，尚未提交回合")
        turn_runner.mark(context, "host_narrating")
        if wiki:
            await ledger_io(wiki.check)
        valid_ids = {event["id"] for event in public_events}
        host_job = runtime.job(reader(HOST), [fingerprint, "host", HOST_RESULT_POLICY_VERSION], prompt)
        host = await runtime.invoke(reader(HOST), prompt, host_view, host_job,
                                    kind="host", billing_job=slots["host"], allowed_event_ids=sorted(valid_ids))
        if set(host["result"]["cited_event_ids"]) - valid_ids:
            raise ValueError("主持人引用了不存在或无权公开的事件，本回合保留待恢复")
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError()
        result["description"] = host["result"]["description"]
        await ledger_io(runtime.ledger.release_unused)
        result["agent_events"] = public_events
        result["agent_inputs"] = [] if context.turn.is_continue else [
            {"npc_id": key, "content": value} for key, value in inputs.items() if key in selected]
        result["agent_turn"] = {"mode": "collaborative", "participants": selected, "deferred": deferred,
                                "budget": await ledger_io(runtime.ledger.summary), "status": "settled", "audit": narration_audit(result["description"], public_events)}
        if deferred:
            result["description"] += "\n\n尚待回应：" + "、".join(records[key]["name"] for key in deferred) + "。这些互动尚未处理。"
        commit_memory_usage(candidate.character, access)
        record_agent_usage(candidate.character, result["agent_turn"]["budget"], host["runtime"].get("used_model", "unknown"))
        candidate.character["agent_state"]["last_turn"] = copy.deepcopy(result["agent_turn"])
        candidate.prepared_result = result
        if wiki:
            wiki.check()
        if evaluation is not None or not persist:
            if evaluation:
                evaluation.character, evaluation.tasks = candidate.character, candidate.tasks
            return result, candidate
        turn_runner.mark(context, "settling")
        turn_orchestrator.commit_candidate(candidate)
        await ledger_io(runtime.ledger.set_status, "committed")
        try:
            await runtime.cleanup()
        except Exception:
            # A successful formal commit must not be reported as a failed turn.
            import logging
            logging.getLogger(__name__).exception("Agent checkpoint cleanup deferred")
        turn_runner.mark(context, "committed")
        return result, candidate

    try:
        async with asyncio.timeout(runtime.limits.timeout_seconds):
            return await workflow()
    except asyncio.CancelledError:
        await ledger_io(runtime.ledger.set_status, "cancelled")
        raise
    except BaseException:
        await ledger_io(runtime.ledger.set_status, "interrupted")
        raise


async def run_retrieval_turn(context):
    from backend.services.ai_contracts import EnvironmentTurnResult
    from backend.services.evaluation_context import evaluation_context
    from backend.services.turn_runner import turn_runner
    evaluation = evaluation_context.get()
    records = catalogue(context.character)
    present = server_presence(context.character, records, context.turn.scene)
    reader = Reader(save_id=context.turn.character_id, epoch=str(context.character.get("timeline_epoch", "")),
                    npc_id=HOST, task_id=str(context.turn.turn_id),
                    permission_version=int(context.character.get("agent_state", {}).get("permission_version", 1)))
    scope = "retrieval-turn:" + digest([reader.save_id, reader.epoch, reader.task_id])
    runtime = await ledger_io(NPCRuntime, scope, generate=evaluation.generate if evaluation else None, checkpoint=evaluation is None)
    wiki = await ledger_io(freeze_wiki, runtime.ledger)
    runtime.evidence_guard = wiki.check if wiki else None
    view = EvidenceContext(reader, context.character, context.tasks, context.turn.scene, records=records,
                           present_ids=present, world_entries=_world_entries(), wiki=wiki)
    evidence = view.assemble(context.turn.action_text)
    profiles = [{"id": key, "name": records[key]["name"], "profile": {field: records[key].get("profile", {}).get(field)
                 for field in ("identity", "personality", "description", "spellcard_style")}} for key in present]
    prompt = ("你是东方异变录主持人，使用检索到的有权限证据回应玩家行动。区分事实、传闻和未知归属，不能传播秘密。"
              "用自然的场景与对话呈现，不要列出事实/传闻/未知归属审计表；不确定的内容自然表达为尚不清楚。"
              "保持角色口吻，尊重自由探索和普通或恋爱交往，提议的数值与动作由后端规则裁定。只输出 schema JSON。\n" +
              json.dumps({"scene": context.turn.scene, "player_action": context.turn.action_text, "evidence": evidence,
                          "npcs": profiles, "selected_npc": context.turn.npc_id, "schema": EnvironmentTurnResult.model_json_schema()}, ensure_ascii=False))
    fingerprint = digest([context.base_character_revision, context.base_tasks_revision, context.character.get("agent_state", {}), prompt,
                          *([wiki.fingerprint] if wiki else [])])
    job = runtime.job(reader, fingerprint, prompt)
    await ledger_io(runtime.ledger.reserve, {job: runtime.reservation(prompt)}, replace_pending=True)
    await ledger_io(runtime.ledger.register_turn, reader, fingerprint)
    try:
        async with asyncio.timeout(runtime.limits.timeout_seconds):
            if wiki:
                await ledger_io(wiki.check)
            generated = await runtime.invoke(reader, prompt, evidence, job, kind="retrieval")
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError()
            result = generated["result"]
            result["contract_valid"] = True
            result["agent_turn"] = {"mode": "retrieval", "participants": [], "budget": await ledger_io(runtime.ledger.summary)}
            record_agent_usage(context.character, result["agent_turn"]["budget"], generated["runtime"].get("used_model", "unknown"))
            if wiki:
                wiki.check()
            final = await turn_runner.finalize(context, result)
            await ledger_io(runtime.ledger.set_status, "committed")
    except asyncio.CancelledError:
        await ledger_io(runtime.ledger.set_status, "cancelled")
        raise
    except BaseException:
        await ledger_io(runtime.ledger.set_status, "interrupted")
        raise
    try:
        await runtime.cleanup()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Retrieval checkpoint cleanup deferred")
    return final


async def maybe_agent_turn(context):
    from fastapi import HTTPException
    from backend.services.npc_agent_runtime import AgentBudgetError, AgentDecisionError
    mode = context.character.get("agent_state", {}).get("mode", "legacy")
    if mode == "legacy":
        return None
    try:
        if mode == "retrieval":
            return await run_retrieval_turn(context)
        if mode == "collaborative":
            result, _ = await run_agent_turn(context)
            return result
        raise ValueError("存档的叙事模式不受当前版本支持")
    except (AgentBudgetError, AgentDecisionError, TimeoutError) as exc:
        raise HTTPException(503, "协作回合尚未提交，请手动恢复。" + str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
