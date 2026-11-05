"""Deterministic proposal validation on one candidate state, never last-writer-wins."""

import copy

from backend.services.agent_contracts import Proposal, default_agent_state
from backend.services.agent_context_service import PLAYER, digest, storage_name
from backend.services.life_simulation_service import absolute_hour, ensure_life_state
from backend.services.npc_memory_service import record_npc_memories


class ProposalRejected(ValueError):
    pass


def advance_agent_calendar(character):
    """Lightweight consequences of already agreed NPC meetings; no decisions or AI."""
    hour = absolute_hour(character)
    diaries = ensure_life_state(character)["diaries"]
    for event in character.get("agent_state", {}).get("events", []):
        participants = [event.get("actor_id"), event.get("target_id")]
        if event.get("kind") != "invite" or event.get("status") != "accepted" or PLAYER in participants:
            continue
        if hour < event["hour"]:
            continue
        event["status"] = "completed" if hour <= event["hour"] + 2 else "missed"
        for owner in participants:
            bucket = diaries.setdefault(owner, [])
            if not any(item.get("id") == event["id"] for item in bucket):
                bucket.append({"id": event["id"], "title": "如约相见" if event["status"] == "completed" else "错过约定",
                    "source": "server_rule", "scene": event["scene"], "hour": hour, "owner_npc_id": owner,
                    "timeline_epoch": character.get("timeline_epoch", ""), "participants": participants,
                    "visibility": {"scope": "recipients", "audience": participants}, "attribution_status": "confirmed"})


class ProposalMerger:
    def __init__(self, character, records, turn_id, scene, present_ids):
        self.character, self.records = character, records
        self.turn_id, self.scene, self.present = turn_id, scene, set(present_ids)
        self.state = character.setdefault("agent_state", default_agent_state())
        self.results = []

    def _person(self, identity):
        if identity == PLAYER:
            return self.character.get("profile", {}).get("name", "玩家")
        if identity not in self.records:
            raise ProposalRejected("目标没有稳定身份")
        return self.records[identity]["name"]

    def _reachable(self, actor, target):
        self._person(target)
        if actor not in self.present or target != PLAYER and target not in self.present:
            raise ProposalRejected("不在当前可接触范围，互动保留待以后处理")

    def _resources(self, identity):
        if identity == PLAYER:
            raise ProposalRejected("NPC 不能直接支配玩家背包")
        return ensure_life_state(self.character)["npc_resources"].setdefault(storage_name(self.records, identity), {})

    def _available(self, identity, item, quantity):
        if int(self._resources(identity).get(item, 0)) < quantity:
            raise ProposalRejected("本人持有物品不足，不能转移或复制他人资源")

    def _transfer(self, source, target, item, quantity):
        self._reachable(source, target)
        self._available(source, item, quantity)
        if target == PLAYER:
            from backend.services.progression_service import ensure_inventory_state
            inventory = ensure_inventory_state(self.character)
            owned = next((row for row in inventory["items"] if row.get("name") == item), None)
            if not owned and len(inventory["items"]) >= inventory["capacity"]:
                raise ProposalRejected("接收者行囊已满")
            if owned:
                owned["quantity"] = int(owned.get("quantity", 0)) + quantity
            else:
                inventory["items"].append({"name": item, "quantity": quantity, "category": "转交物品"})
        else:
            resources = self._resources(target)
            resources[item] = int(resources.get(item, 0)) + quantity
        self._resources(source)[item] -= quantity

    def _event(self, actor, event_id):
        event = next((e for e in self.state["events"] if e["id"] == event_id), None)
        if not event or event.get("target_id") != actor or event.get("status") != "pending":
            raise ProposalRejected("不是本人收到的待处理事件，或事件已经处理")
        return event

    def _calendar_available(self, actors, hour, scene, exclude=""):
        if hour <= absolute_hour(self.character):
            raise ProposalRejected("邀约时间已经过去")
        for event in self.state["events"]:
            if event["id"] == exclude or event.get("kind") != "invite" or event.get("status") != "accepted":
                continue
            if set(actors) & {event.get("actor_id"), event.get("target_id")} and abs(event["hour"] - hour) < 2:
                raise ProposalRejected("已有同一时段约定，需要本人改期")
        for appointment in self.character.get("life_state", {}).get("appointments", []):
            if appointment.get("id") == exclude or appointment.get("status") != "scheduled":
                continue
            if (PLAYER in actors or appointment.get("npc_name") in {self._person(actor) for actor in actors}) and abs(appointment["hour"] - hour) < 2:
                raise ProposalRejected("与已有日程冲突")

    def _remember_speech(self, actor, recipients, text, event_id):
        for owner in dict.fromkeys([actor, *recipients]):
            if owner == PLAYER:
                continue
            owner_key = storage_name(self.records, owner)
            record_npc_memories(self.character, [{
                "id": event_id + ":" + owner, "npc_name": owner_key,
                "summary": f"{self._person(actor)} [{actor}]说：{text}", "source_npc": self._person(actor),
                "knowledge_type": "reported", "source": "system_agent_speech", "truth_status": "disputed",
                "attribution_status": "confirmed", "evidence_text": "仅确认发言与接收，不证明内容为真",
            }], source="system_agent_speech", turn_id=self.turn_id)
            bucket = self.character["npc_memories"][owner_key]
            entry = next(item for item in bucket if item["id"] == event_id + ":" + owner)
            entry.update(owner_npc_id=owner, owner_npc_name=self._person(owner), source_npc_id=actor, visibility={"scope": "recipients", "audience": [actor, *recipients]},
                         timeline_epoch=self.character.get("timeline_epoch", ""), source_event_id=event_id)

    def merge(self, actor, proposal, evidence_ids=()):
        if actor not in self.records and actor != PLAYER:
            raise ProposalRejected("执行者未登记")
        proposal = Proposal.model_validate(proposal)
        if actor == PLAYER and any(cmd.kind not in ("accept", "reject", "reschedule") for cmd in proposal.commands):
            raise ProposalRejected("此入口仅供玩家回应已有互动")
        emitted = []
        for index, command in enumerate(proposal.commands):
            event_id = "agent_" + digest([self.character.get("timeline_epoch", ""), self.turn_id, actor, index])[:28]
            if event_id in self.state["consumed_events"]:
                continue
            result = {"id": event_id, "actor_id": actor, "npc_name": self._person(actor), "kind": command.kind,
                      "visibility": {"scope": "recipients", "audience": [actor, PLAYER]},
                      "status": "accepted", "turn_id": self.turn_id, "scene": self.scene}
            # Reject each command atomically; successful earlier commands remain candidates.
            before = copy.deepcopy(self.character)
            try:
                if set(command.evidence_ids) - set(evidence_ids):
                    raise ProposalRejected("引用不在本人获准证据中")
                self._apply(actor, command, result)
            except ProposalRejected as exc:
                self.character.clear()
                self.character.update(before)
                self.state = self.character["agent_state"]
                result.update(status="rejected", reason=str(exc))
            self.state["consumed_events"].append(event_id)
            emitted.append(result)
        self.results.extend(emitted)
        return emitted

    def _apply(self, actor, command, result):
        name, kind = self._person(actor), command.kind
        if kind == "speak":
            target = command.target_id or PLAYER
            self._reachable(actor, target)
            result.update(text=command.text, target_id=target, truth_status="speech_not_verified_fact",
                          visibility={"scope": "recipients", "audience": [actor, target]})
            self._remember_speech(actor, [target], command.text, result["id"])
        elif kind in ("invite", "offer", "transfer"):
            self._reachable(actor, command.target_id)
            if actor == command.target_id:
                raise ProposalRejected("不能向自己提出交接或邀约")
            if kind == "invite":
                self._calendar_available([actor], command.hour, command.scene)
            else:
                self._available(actor, command.item, command.quantity)
            signature = [actor, command.target_id, "offer" if kind == "transfer" else kind, command.hour, command.scene, command.item]
            if any(e.get("signature") == signature and e.get("status") == "pending" for e in self.state["events"]):
                raise ProposalRejected("相同互动已经在等待回应")
            event = {**result, **command.model_dump(), "actor_id": actor, "status": "pending", "signature": signature,
                     "priority": 50, "created_hour": absolute_hour(self.character),
                     "visibility": {"scope": "recipients", "audience": [actor, command.target_id]}}
            if kind == "transfer":
                event["kind"] = "offer"
            self.state["events"].append(event)
            result.update(target_id=command.target_id, pending_event=copy.deepcopy(event),
                          visibility=event["visibility"], text="已发出邀约，等待对方决定" if kind == "invite" else "已提出提供物品，等待接收者决定")
        elif kind in ("accept", "reject", "reschedule"):
            event = self._event(actor, command.event_id)
            source = event["actor_id"]
            if kind == "accept":
                if event["kind"] == "invite":
                    self._calendar_available([source, actor], event["hour"], event["scene"], event["id"])
                elif event["kind"] == "offer":
                    self._transfer(source, actor, event["item"], event["quantity"])
                else:
                    raise ProposalRejected("这个事件不是可以接受的邀约或物品提议")
                event["status"] = "accepted"
                if event["kind"] == "invite" and PLAYER in (source, actor):
                    appointments = ensure_life_state(self.character)["appointments"]
                    old = next((item for item in appointments if item["id"] == event["id"]), None)
                    if old:
                        old["status"] = "scheduled"
                    else:
                        appointments.append({"id": event["id"], "npc_name": name if actor != PLAYER else self._person(source),
                            "title": "约定相见", "hour": event["hour"], "scene": event["scene"], "status": "scheduled"})
            elif kind == "reject":
                event["status"] = "rejected"
                for old in ensure_life_state(self.character)["appointments"]:
                    if old["id"] == event["id"]:
                        old["status"] = "cancelled"
            else:
                if event["kind"] != "invite":
                    raise ProposalRejected("只有邀约可以改期")
                self._calendar_available([actor], command.hour, command.scene)
                event["status"] = "rescheduled"
                self._apply(actor, type(command)(kind="invite", target_id=source, hour=command.hour, scene=command.scene), result)
            result.update(target_id=source, source_event_id=event["id"], text=command.text or {"accept": "接受", "reject": "拒绝", "reschedule": "提出改期"}[kind],
                          visibility={"scope": "recipients", "audience": [actor, source]})
        elif kind == "relationship":
            from backend.services.relationship_dynamics_service import relationship_dimensions
            own_key = storage_name(self.records, actor)
            dimensions = relationship_dimensions(self.character, own_key)
            dimensions.update(npc_id=actor, npc_name=name)
            boundary = self.character.get("relationship_boundaries", {}).get(own_key, {})
            if boundary.get("romance") == "closed" or float(boundary.get("cooldown_until_hour", -1)) >= absolute_hour(self.character):
                raise ProposalRejected("玩家已表达关系边界或暂不接受，不能重复推进")
            proposals = self.character.setdefault("relationship_proposals", [])
            if any((item.get("npc_id") == actor or not item.get("npc_id") and item.get("npc_name") == own_key)
                   and item.get("status") == "pending" for item in proposals):
                raise ProposalRejected("已有尚待回应的心意")
            if command.relationship_kind == "deepen" and dimensions["status"] not in ("lover", "partner", "legacy_confirmed"):
                raise ProposalRejected("尚未确认交往关系")
            proposal = {"id": result["id"], "npc_id": actor, "npc_name": name, "npc_storage_key": own_key, "kind": command.relationship_kind,
                        "style": "本人表达", "status": "pending", "hour": absolute_hour(self.character),
                        "title": "想对你说的话", "description": command.text}
            proposals.append(proposal)
            dimensions["last_proposal_hour"] = absolute_hour(self.character)
            result.update(text=command.text, relationship_proposal=proposal, target_id=PLAYER)
        elif kind == "use":
            from backend.services.item_effects import definition
            effects = definition(command.item).get("use", {})
            if not effects:
                raise ProposalRejected("此物品没有已登记的使用效果")
            self._available(actor, command.item, command.quantity)
            runtime = self.character.setdefault("npc_runtime", {}).setdefault(storage_name(self.records, actor), {})
            attributes = runtime.setdefault("attributes", {})
            for key, amount in effects.items():
                attributes[key] = max(0, min(100, attributes.get(key, 0) + amount * command.quantity))
            self._resources(actor)[command.item] -= command.quantity
            result.update(item=command.item, quantity=command.quantity, text=f"使用 {command.item} × {command.quantity}")
        elif kind == "plan":
            state = self.character.setdefault("npc_agency", {}).setdefault("npcs", {}).setdefault(storage_name(self.records, actor), {})
            state.update(current_goal=command.text, plan_progress=0, goal_source="npc_agent", goal_status="planned")
            result.update(text="调整了本人的计划", visibility={"scope": "recipients", "audience": [actor]})
        elif kind == "investigate":
            if command.target_id != self.scene and command.target_id not in command.evidence_ids:
                self._reachable(actor, command.target_id)
            result.update(text="进行观察；没有因此获知隐藏事实", target_id=command.target_id)
        else:
            result["text"] = command.text or "等待"
