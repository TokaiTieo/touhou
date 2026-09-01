"""Optional, save-resident onboarding that never gates exploration."""

from datetime import datetime
from typing import Dict


STEPS = (
    {
        "id": "first_action",
        "title": "先看看四周",
        "description": "从观察、调查或一次随意行动开始。所有地点始终可以自由前往。",
        "action": "观察博丽神社周围的结界波纹和来往人物",
    },
    {
        "id": "first_dialogue",
        "title": "与幻想乡住民交谈",
        "description": "选择当前人物开始对话。对话、关系与任务都不会成为地图通行条件。",
        "action": "",
    },
    {
        "id": "open_journal",
        "title": "翻阅角色档案",
        "description": "档案集中记录行囊、声望、关系和异变余波。",
        "action": "",
    },
)


def default_onboarding(*, enabled: bool = False) -> Dict:
    return {
        "version": 1,
        "enabled": bool(enabled),
        "dismissed": not enabled,
        "completed_steps": [],
        "current_step": STEPS[0]["id"] if enabled else None,
        "updated_at": None,
    }


def ensure_onboarding(character: Dict) -> Dict:
    state = character.get("onboarding")
    if not isinstance(state, dict):
        state = default_onboarding(enabled=False)
        character["onboarding"] = state
    defaults = default_onboarding(enabled=False)
    for key, value in defaults.items():
        state.setdefault(key, value)
    completed = state.get("completed_steps")
    if not isinstance(completed, list):
        completed = []
        state["completed_steps"] = completed
    _refresh_current_step(state)
    return state


def _refresh_current_step(state: Dict) -> None:
    if state.get("dismissed") or not state.get("enabled"):
        state["current_step"] = None
        return
    completed = set(state.get("completed_steps", []))
    state["current_step"] = next(
        (item["id"] for item in STEPS if item["id"] not in completed),
        None,
    )
    if state["current_step"] is None:
        state["enabled"] = False


def advance_onboarding(character: Dict, event: str) -> Dict:
    state = ensure_onboarding(character)
    if state.get("dismissed") or not state.get("enabled"):
        return state
    mapping = {
        "turn": "first_action",
        "dialogue": "first_dialogue",
        "journal": "open_journal",
    }
    step = mapping.get(str(event or ""))
    if step and step not in state["completed_steps"]:
        state["completed_steps"].append(step)
        state["updated_at"] = datetime.now().isoformat()
    _refresh_current_step(state)
    return state


def dismiss_onboarding(character: Dict) -> Dict:
    state = ensure_onboarding(character)
    state.update({
        "enabled": False,
        "dismissed": True,
        "current_step": None,
        "updated_at": datetime.now().isoformat(),
    })
    return state


def public_onboarding(character: Dict) -> Dict:
    state = ensure_onboarding(character)
    current = next((item for item in STEPS if item["id"] == state.get("current_step")), None)
    return {**state, "step": current, "total_steps": len(STEPS)}
