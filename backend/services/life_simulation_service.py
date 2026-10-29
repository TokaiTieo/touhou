"""Local life actions, sourced diaries, appointments and event lifecycles."""

import hashlib
from copy import deepcopy

from backend.services.action_resolution_service import performed_text
from backend.services.npc_attribution_service import npc_identity
from backend.services.relationship_dynamics_service import (
    absolute_hour, life_content, record_shared_experience,
)


def ensure_life_state(character):
    state = character.setdefault("life_state", {})
    for key, default in {"version": 1, "activities": [], "appointments": [], "events": {},
                         "diaries": {}, "shared_experiences": [], "known_preferences": {}, "npc_resources": {}}.items():
        state.setdefault(key, deepcopy(default))
    return state


def record_experience(character, event_id, title, names=(), scene="", detail="", visible=True, bond=True):
    state = ensure_life_state(character)
    if any(item.get("id") == event_id for item in state["shared_experiences"]):
        return
    participants = [npc_identity(name) for name in dict.fromkeys(names)]
    record = {"id": event_id, "title": title, "detail": detail, "scene": scene,
              "hour": absolute_hour(character), "participants": participants,
              "source": "server_rule", "attribution_status": "confirmed", "shared_with_player": visible}
    if visible:
        state["shared_experiences"] = (state["shared_experiences"] + [record])[-200:]
    for owner in participants:
        key = owner["npc_id"] or owner["npc_name"]
        diary = state["diaries"].setdefault(key, [])
        if not any(item.get("id") == event_id for item in diary):
            diary.append({**deepcopy(record), "owner": owner})
            state["diaries"][key] = diary[-100:]
        if visible and bond:
            record_shared_experience(character, owner["npc_name"], event_id)


def activity_preview(character, text, scene):
    effective = performed_text(text)
    for activity in life_content()["activities"]:
        if activity["title"] in effective:
            inventory = character.get("inventory_state", {}).get("items", [])
            needed = activity.get("input")
            enough = not needed or any(item.get("name") == needed and float(item.get("quantity", 0)) >= activity.get("input_quantity", 1)
                                       for item in inventory if isinstance(item, dict))
            return {**activity, "available": scene == activity["scene"] and enough,
                    "reason": "请先到达活动地点" if scene != activity["scene"] else "食材不足" if not enough else ""}
    return None


def apply_activity(character, result, text, scene, scene_npcs, turn_id):
    activity = activity_preview(character, text, scene)
    if not activity:
        return None
    state = ensure_life_state(character)
    identity = turn_id or "life_" + hashlib.sha256(f"{absolute_hour(character)}:{text}".encode()).hexdigest()[:20]
    if any(item.get("id") == identity for item in state["activities"]):
        return None
    result["activity_resolution"] = deepcopy(activity)
    result["inventory_updates"] = []
    result["reputation_updates"] = []
    if not activity["available"]:
        result.update(time_cost=0, description=activity["reason"])
        return activity
    inventory = character.setdefault("inventory_state", {})
    items = inventory.setdefault("items", [])
    if activity.get("input"):
        item = next(item for item in items if item.get("name") == activity["input"] and float(item.get("quantity", 0)) >= activity.get("input_quantity", 1))
        item["quantity"] -= activity.get("input_quantity", 1)
        if item["quantity"] <= 0:
            items.remove(item)
    output = activity.get("output")
    if output:
        item = next((item for item in items if item.get("name") == output), None)
        if item is None:
            item = {"name": output, "quantity": 0, "quality": "普通", "source": "life_activity"}
            items.append(item)
        item["quantity"] = float(item.get("quantity", 0)) + 1
    inventory["currency"] = float(inventory.get("currency", 0) or 0) + activity["currency"]
    experience = character.setdefault("skill_experience", {})
    skill = activity["skill"]
    experience[skill] = float(experience.get(skill, 0) or 0) + 8
    player = character.setdefault("player_state", {})
    level = float(player.get(skill, 0) or 0)
    while level < 999999 and experience[skill] >= 8 + min(level, 100) * 2:
        experience[skill] -= 8 + min(level, 100) * 2
        level += 1
    player[skill] = level
    old_fatigue = float(player.get("疲劳", 0) or 0)
    player["疲劳"] = min(100, old_fatigue + activity["fatigue"]) if not character.get("gm_mode") else old_fatigue
    result["_activity_fatigue_delta"] = player["疲劳"] - old_fatigue
    rewards = f"获得{output}×1" + (f"、报酬{activity['currency']}" if activity["currency"] else "")
    result.update(time_cost=activity["hours"], description=f"完成{activity['title']}，{rewards}，{skill}经验 +8。")
    record = {"id": identity, "activity_id": activity["id"], "title": activity["title"], "hour": absolute_hour(character), "rewards": rewards}
    state["activities"] = (state["activities"] + [record])[-100:]
    present = {item.get("name") for item in scene_npcs or []}
    names = [activity["npc"]] if activity.get("npc") in present else []
    record_experience(character, identity, activity["title"], names, scene, rewards)
    return activity


def register_event(character, event):
    if not event or not event.get("id"):
        return
    state = ensure_life_state(character)
    state["events"].setdefault(event["id"], {**deepcopy(event), "status": "discovered", "discovered_hour": absolute_hour(character)})


def upgrade_legacy_discoveries(character):
    from backend.config import BASE_DIR, DEFAULT_WORLD_ID
    from backend.services.dynamic_event_service import load_event_definitions
    data = load_event_definitions(BASE_DIR / "worlds" / DEFAULT_WORLD_ID / "events.json")
    definitions = {item["id"]: item for item in data.get("personal_events", []) + data.get("ambient_events", [])}
    seen = character.get("event_flags", {}).get("dynamic_events", {}).get("seen", {})
    for identity, metadata in seen.items():
        definition = definitions.get(identity, {})
        register_event(character, {"id": identity, "title": definition.get("title", "旧日探索线索"),
            "description": definition.get("description", "保留的旧探索记录，完成情况尚未确认。"),
            "scene": next(iter(definition.get("scenes", [])), "未知地点"),
            "npc_name": definition.get("npc"), "chain": definition.get("chain"), "stage": definition.get("stage", 0),
            "legacy_discovery": deepcopy(metadata), "source": "legacy_discovery"})


def change_event(character, event_id, choice):
    state = ensure_life_state(character)
    event = state["events"].get(event_id)
    if not event:
        raise ValueError("当前时间线没有这条事件")
    allowed = {"discovered": {"participate": "participating", "abandon": "abandoned"},
               "participating": {"complete": "completed", "abandon": "abandoned"},
               "abandoned": {"participate": "participating"}}
    target = allowed.get(event["status"], {}).get(choice)
    if not target:
        raise ValueError("当前事件状态不支持这项操作")
    if choice == "complete":
        raise ValueError("事件需要实际行动结果才能完成，不能仅凭按钮确认")
    event.update(status=target, updated_hour=absolute_hour(character))
    for item in character.get("open_events", []):
        if item.get("id") == event_id:
            item["status"] = target
    return event


def complete_linked_events(character, activity, participants, scene):
    """Only a matching, completed local action can finish a participating event."""
    state = ensure_life_state(character)
    for event in state["events"].values():
        if event.get("status") != "participating" or event.get("scene") != scene:
            continue
        # Explicit action binding prevents incidental keyword matches becoming facts.
        if event.get("activity_id") != activity.get("id"):
            continue
        event.update(status="completed", completed_hour=absolute_hour(character))
        record_experience(character, "event:" + event["id"], event["title"], participants, scene, "完成共同活动")


def sync_completed_events(character, tasks):
    completed = {item.get("id") for item in tasks.get("completed_tasks", [])}
    for event in ensure_life_state(character)["events"].values():
        if event.get("status") == "participating" and event.get("task_id") in completed:
            event.update(status="completed", completed_hour=absolute_hour(character), completion_source="accepted_task_result")
    for item in character.get("open_events", []):
        current = ensure_life_state(character)["events"].get(item.get("id"))
        if current:
            item["status"] = current["status"]


def create_appointment(character, name, day, hour, scene):
    from backend.services.npc_identity_service import resolve_npc, canonical_npc_name
    name = canonical_npc_name(name)
    if not resolve_npc(name) and name not in character.get("relationships_map", {}):
        raise ValueError("请选择已认识的人物")
    day, hour = int(day), float(hour)
    when = (day - 1) * 24 + hour
    if day < 1 or not 0 <= hour < 24 or when <= absolute_hour(character) or not scene.strip():
        raise ValueError("请选择未来的日期、时间和地点")
    state = ensure_life_state(character)
    if sum(item["status"] in ("proposed", "scheduled") for item in state["appointments"]) >= 30:
        raise ValueError("请先处理现有约定")
    identity = "appointment_" + hashlib.sha256(f"{name}|{when}|{scene}".encode()).hexdigest()[:16]
    if any(item["id"] == identity for item in state["appointments"]):
        raise ValueError("已有相同邀约")
    # The player proposes a time; the NPC has not accepted it yet.
    item = {**npc_identity(name), "id": identity, "title": f"与{name}的邀约", "hour": when,
            "scene": scene.strip(), "status": "proposed"}
    state["appointments"] = (state["appointments"] + [item])[-100:]
    return item


def update_appointment(character, identity, choice, day=None, hour=None):
    state = ensure_life_state(character)
    item = next((item for item in state["appointments"] if item["id"] == identity), None)
    if not item or item["status"] not in ("proposed", "scheduled"):
        raise ValueError("这项约定已经结束或不存在")
    if choice == "cancel":
        item["status"] = "cancelled"
    elif choice == "reschedule":
        when = (int(day) - 1) * 24 + float(hour)
        if int(day) < 1 or not 0 <= float(hour) < 24 or when <= absolute_hour(character):
            raise ValueError("请选择未来的时间")
        item.update(hour=when, status="proposed")
    else:
        raise ValueError("不支持的约定操作")
    return item


def advance_calendar(character, scene, present_names):
    state = ensure_life_state(character)
    hour = absolute_hour(character)
    for item in state["appointments"]:
        if item["status"] == "proposed" and item["hour"] + 2 >= hour:
            # Acceptance is a deterministic NPC decision, not a player-side fact.
            from backend.services.relationship_dynamics_service import relationship_dimensions
            relation = relationship_dimensions(character, item["npc_name"])
            boundary = character.get("relationship_boundaries", {}).get(item["npc_name"], {})
            if relation["familiarity"] >= 30 and item["hour"] > float(boundary.get("cooldown_until_hour", -1)):
                item["status"] = "scheduled"
        if item["status"] == "scheduled" and item["hour"] <= hour <= item["hour"] + 2:
            if item["scene"] == scene and item["npc_name"] in present_names:
                item["status"] = "completed"
                record_experience(character, item["id"], "如约相见", [item["npc_name"]], scene, "双方在约定时段见面")
        if item["status"] in ("proposed", "scheduled") and hour > item["hour"] + 2:
            item["status"] = "missed"


def advance_npc_plan(character, event, fallback):
    state = ensure_life_state(character)
    name = event["npc_name"]
    plan = life_content()["plans"].get(name)
    if not plan:
        return fallback
    npc = character.setdefault("npc_agency", {}).setdefault("npcs", {}).setdefault(name, {})
    now = float(event.get("game_hour", absolute_hour(character)))
    receipt = event.get("id") or f"plan:{name}:{now}"
    if "plan_last_hour" in npc and now <= float(npc["plan_last_hour"]):
        return npc.get("last_activity", plan["title"])
    if npc.get("plan_activity_receipt") == receipt:
        return npc.get("last_activity", plan["title"])
    start = max(0, now - 6, float(npc.get("plan_last_hour", now - 6)))
    elapsed = sum(max(0, min(now, day * 24 + 22) - max(start, day * 24 + 6))
                  for day in range(int(start // 24), int(now // 24) + 1))
    npc.update(plan_last_hour=now, plan_activity_receipt=receipt, plan_required_hours=plan["hours"])
    if now % 24 < 6 or now % 24 >= 22:
        return "休息，暂缓日常计划"
    if event.get("location") != plan["scene"]:
        return "外出处理事务，日常计划暂缓"
    progress = float(npc.get("plan_hours", 0)) + elapsed
    if progress >= plan["hours"]:
        stock = state["npc_resources"].setdefault(name, {})
        stock[plan["resource"]] = stock.get(plan["resource"], 0) + plan["amount"]
        event["plan_result"] = {"resource": plan["resource"], "quantity": plan["amount"]}
        title = f"{name}完成{plan['title']}"
        history = npc.setdefault("goal_history", [])
        history.append({"goal": plan["title"], "completed_hour": now, "result": deepcopy(event["plan_result"])})
        npc["goal_history"] = history[-20:]
        record_experience(character, receipt, title, [name], event["location"], f"{plan['resource']} +{plan['amount']}", visible=False)
        hook = {"id": receipt + ":followup", "title": title, "scene": event["location"], "npc_name": name,
                "description": "人物的日常计划已有成果，可以前去了解近况。", "source": "npc_plan"}
        register_event(character, hook)
        progress %= plan["hours"]
    npc["plan_hours"] = progress
    npc["plan_progress"] = round(progress / plan["hours"] * 3, 2)
    return plan["title"]


def life_view(character):
    state = ensure_life_state(character)
    now = absolute_hour(character)
    today = int(now // 24) + 1
    festivals = []
    for definition in life_content()["festivals"]:
        day = definition["day"] + max(0, (today - definition["day"] + definition["period"] - 1) // definition["period"]) * definition["period"]
        festivals.append({**definition, "day": day})
    scene = character.get("status", {}).get("current_scene", "")
    return {"scene": scene, "day": today, "hour": now % 24,
            "activities": [{**item, **activity_preview(character, item["title"], scene)} for item in life_content()["activities"]],
            "appointments": deepcopy(state["appointments"][-30:]), "festivals": festivals,
            "events": [deepcopy(item) for item in list(state["events"].values())[-50:]],
            "experiences": deepcopy(state["shared_experiences"][-40:]),
            "diaries": {key: [deepcopy(entry) for entry in entries if entry.get("shared_with_player")]
                        for key, entries in state["diaries"].items() if any(entry.get("shared_with_player") for entry in entries)},
            "known_preferences": deepcopy(state["known_preferences"]),
            "proposals": [deepcopy(item) for item in character.get("relationship_proposals", []) if item.get("status") == "pending"],
            "relationships": deepcopy(character.get("relationship_dimensions", {}))}


def life_context(character, scene):
    state = ensure_life_state(character)
    relevant = [item for item in state["appointments"] if item.get("status") in ("proposed", "scheduled")]
    return "日常约定（proposed仅为提议，不代表对方答应）：" + str(relevant[-5:]) + "；当前地点：" + scene


def sync_event_task(event, tasks):
    active = tasks.setdefault("active_tasks", [])
    suspended = tasks.setdefault("suspended_tasks", [])
    task_id = event.get("task_id")
    if event["status"] == "abandoned":
        for task in list(active):
            if task.get("id") == task_id:
                active.remove(task)
                suspended.append(task)
    elif event["status"] == "participating":
        for task in list(suspended):
            if task.get("id") == task_id:
                suspended.remove(task)
                active.append(task)


def format_life_action_preview(character, text, scene):
    activity = activity_preview(character, text, scene)
    return "日常活动预裁定：" + str(activity) + "。若活动可用，严格按其耗时、产物和消耗叙事；不可用不能凭空获得产物。" if activity else ""
