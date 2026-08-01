"""Shared deterministic state-changing portion of environment and NPC turns."""

from typing import Dict, List, Optional

from backend.services.game_rules import resolve_turn_rules
from backend.services.incident_service import advance_incident_state
from backend.services.progression_service import apply_progression_updates
from backend.services.turn_service import apply_time_progression
from backend.services.npc_simulation_service import simulate_offscreen_npcs


def apply_turn_resolution(
    character: Dict,
    result: Dict,
    action_text: str,
    scene: str,
    tasks_data: Dict,
    scene_npcs: Optional[List[Dict]] = None,
    npc_name: str = None,
    rule_preview: Dict = None,
    turn_id: str = None,
) -> Dict:
    applied_turns = character.setdefault("resolved_turn_ids", [])
    if turn_id and turn_id in applied_turns:
        return {
            "tasks_dirty": False,
            "state_delta": result.get("player_state_delta", {}),
            "progression_delta": result.get("progression_delta", {}),
            "incident_state": result.get("incident_state"),
            "offscreen_updates": result.get("offscreen_updates", []),
            "duplicate": True,
        }
    resolve_turn_rules(
        character, result, action_text, scene_npcs or [], npc_name=npc_name, preview=rule_preview
    )
    apply_progression_updates(character, result, scene, action_text)
    advance_incident_state(character, result, action_text, tasks_data, rule_preview)
    apply_time_progression(character, result)
    offscreen_updates = simulate_offscreen_npcs(character, result.get("time_cost", 0))
    result["offscreen_updates"] = offscreen_updates
    if turn_id:
        character["resolved_turn_ids"] = (applied_turns + [turn_id])[-100:]
    return {
        "tasks_dirty": bool(result.pop("tasks_dirty", False)),
        "state_delta": result.get("player_state_delta", {}),
        "progression_delta": result.get("progression_delta", {}),
        "incident_state": result.get("incident_state"),
        "offscreen_updates": offscreen_updates,
    }
