"""Single in-memory transaction for environment and NPC dialogue turns."""

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional

from backend.location_manager import get_location_manager
from backend.services import npc_memory_service as memory_runtime
from backend.services.consequence_service import record_turn_consequence
from backend.services.dynamic_event_service import select_dynamic_event, select_npc_initiative
from backend.services.incident_service import apply_resolution_path, sync_incident_from_tasks
from backend.services.relationship_service import update_relationships
from backend.services.story_summary_service import rebuild_story_summary
from backend.services.turn_models import TurnContext, TurnInput, TurnOutcome
from backend.services.turn_resolution_service import apply_turn_resolution
from backend.services.turn_service import apply_task_updates
from backend.world_manager import (
    get_current_world_path,
    get_locations_dir,
    get_turn_receipt,
    load_character,
    load_tasks,
    record_turn_receipt,
    save_turn_bundle,
)


class CharacterNotFoundError(LookupError):
    pass


class TurnOrchestrator:
    """Coordinates state mutation and performs one durable commit per turn."""

    def begin(self, turn: TurnInput) -> TurnContext:
        character = load_character(turn.character_id)
        if not character:
            raise CharacterNotFoundError(turn.character_id)
        cached = get_turn_receipt(character, turn.turn_id)
        tasks = load_tasks(turn.character_id)
        rebuild_story_summary(character, tasks)
        thread_id = self.workflow_thread_id(turn)
        return TurnContext(
            turn=turn,
            character=character,
            tasks=tasks,
            cached_response=cached,
            workflow_thread_id=thread_id,
            base_character_revision=int(character.get("state_revision", 0) or 0),
            base_tasks_revision=int(tasks.get("state_revision", 0) or 0),
        )

    @staticmethod
    def workflow_thread_id(turn: TurnInput) -> str:
        identity = turn.turn_id or f"ephemeral-{datetime.now().timestamp():.6f}"
        return f"{turn.character_id}:{turn.kind}:{identity}"

    def settle(
        self,
        context: TurnContext,
        result: Dict,
        *,
        rule_preview: Optional[Dict] = None,
    ) -> TurnOutcome:
        if context.cached_response is not None:
            return TurnOutcome(
                result=context.cached_response,
                duplicate=True,
                committed=False,
                workflow_thread_id=context.workflow_thread_id,
            )

        turn = context.turn
        character = context.character
        tasks = context.tasks
        apply_turn_resolution(
            character,
            result,
            turn.action_text,
            turn.scene,
            tasks,
            scene_npcs=turn.scene_npcs,
            npc_name=turn.npc_name,
            rule_preview=rule_preview,
            turn_id=turn.turn_id,
        )
        self._apply_life_state(character, result, turn.kind)
        relationship_update = self._apply_relationship(character, result, turn)
        self._apply_memories_and_events(character, result, turn, relationship_update)
        self._apply_tasks(character, tasks, result, turn)
        if turn.kind == "environment":
            self._apply_location(context, result, turn)
        self._record_consequence(character, result, turn)

        final_result = self._public_result(turn.kind, result)
        record_turn_receipt(character, turn.turn_id, final_result)
        save_turn_bundle(
            turn.character_id,
            character,
            tasks,
            expected_character_revision=context.base_character_revision,
            expected_tasks_revision=context.base_tasks_revision,
            world_changes=context.pending_world_changes,
        )
        return TurnOutcome(
            result=final_result,
            committed=True,
            workflow_thread_id=context.workflow_thread_id,
        )

    def commit_contract_failure(self, context: TurnContext, result: Dict) -> TurnOutcome:
        """Persist diagnostics once without applying gameplay mutations."""
        record_turn_receipt(context.character, context.turn.turn_id, result)
        save_turn_bundle(
            context.turn.character_id,
            context.character,
            context.tasks,
            expected_character_revision=context.base_character_revision,
            expected_tasks_revision=context.base_tasks_revision,
            world_changes=context.pending_world_changes,
        )
        return TurnOutcome(
            result=result,
            committed=True,
            workflow_thread_id=context.workflow_thread_id,
        )

    @staticmethod
    def _apply_life_state(character: Dict, result: Dict, kind: str) -> None:
        if kind != "environment":
            return
        status = character.setdefault("status", {})
        if result.get("is_dead") is True:
            status["is_dead"] = True
            status["death_cause"] = result.get("description", "未知原因")
        elif result.get("is_dead") is False and status.get("is_dead"):
            status["is_dead"] = False
            status["death_cause"] = ""

    @staticmethod
    def _apply_relationship(character: Dict, result: Dict, turn: TurnInput) -> str:
        relationship_update = result.get("relationship_update")
        if not isinstance(relationship_update, str):
            return ""
        relationship_update = relationship_update.strip()
        if ":" not in relationship_update or len(relationship_update) <= 2:
            return ""
        current_hour = character.get("time", {}).get("current_hour", 0)
        result["relationship_progress_delta"] = update_relationships(
            character,
            relationship_update,
            current_hour,
            interaction_text=turn.action_text,
            turn_id=turn.turn_id,
        )
        return relationship_update

    @staticmethod
    def _apply_memories_and_events(
        character: Dict,
        result: Dict,
        turn: TurnInput,
        relationship_update: str,
    ) -> None:
        source = turn.kind
        memory_runtime.record_npc_memories(
            character,
            result.get("memory_updates"),
            source,
            turn_id=turn.turn_id,
        )
        auto_updates = memory_runtime.build_auto_memory_updates(
            character,
            result,
            turn.action_text,
            turn.scene,
            f"auto_{source}",
            npc_name=turn.npc_name,
            scene_npcs=turn.scene_npcs,
            relationship_update=relationship_update,
            task_updates=result.get("task_updates", []),
        )
        if auto_updates:
            result["memory_updates"] = (result.get("memory_updates") or []) + auto_updates
            memory_runtime.record_npc_memories(
                character,
                auto_updates,
                f"auto_{source}",
                turn_id=turn.turn_id,
            )

        memory_runtime.record_open_event(
            character,
            result.get("open_event"),
            turn.scene,
            turn_id=turn.turn_id,
        )
        dynamic_event = select_dynamic_event(
            character,
            get_current_world_path() / "events.json",
            turn.scene,
            turn.action_text,
            scene_npcs=turn.scene_npcs,
            npc_name=turn.npc_name,
        )
        if dynamic_event:
            result["dynamic_event"] = dynamic_event
            memory_runtime.record_open_event(
                character,
                dynamic_event,
                turn.scene,
                turn_id=turn.turn_id,
            )
        else:
            initiative = select_npc_initiative(
                character,
                get_current_world_path() / "events.json",
                turn.scene,
                turn.scene_npcs,
            )
            if initiative:
                result["dynamic_event"] = initiative
                memory_runtime.record_open_event(
                    character,
                    initiative,
                    turn.scene,
                    turn_id=turn.turn_id,
                )
        memory_runtime.record_spellcard_result(
            character,
            result.get("spellcard_result"),
            turn.scene,
            turn_id=turn.turn_id,
        )

    @staticmethod
    def _apply_tasks(character: Dict, tasks: Dict, result: Dict, turn: TurnInput) -> None:
        if apply_task_updates(
            tasks,
            result.get("task_updates", []),
            turn.kind,
            turn_id=turn.turn_id,
        ):
            sync_incident_from_tasks(character, tasks, result)
            apply_resolution_path(character, result, turn.action_text)

    @staticmethod
    def _apply_location(context: TurnContext, result: Dict, turn: TurnInput) -> None:
        character = context.character
        location_data = result.get("new_location")
        if not isinstance(location_data, dict):
            result["new_location"] = None
            return
        name = str(location_data.get("name") or "").strip()
        if not name or name == turn.scene:
            result["new_location"] = None
            return

        manager = get_location_manager(get_locations_dir())
        existing = manager.get_location_by_name(name)
        location_id = None
        if not existing and location_data.get("type", "existing") == "new":
            parent_id = location_data.get("parent_id")
            if parent_id:
                parent = manager.get_location(parent_id) or manager.get_location_by_name(parent_id)
                parent_id = parent.id if parent and hasattr(parent, "id") else None
            identity_seed = f"{turn.character_id}:{turn.turn_id}:{name}"
            location_id = f"dynamic_{hashlib.sha256(identity_seed.encode('utf-8')).hexdigest()[:16]}"
            pending = context.pending_world_changes.setdefault("dynamic_locations", [])
            pending.append({
                "id": location_id,
                "name": name,
                "parent": parent_id,
                "type": "scene",
                "description": location_data.get(
                    "description", f"在{turn.scene}发现的地点"
                ),
                "icon": location_data.get("icon", "地点"),
                "danger_level": location_data.get("danger_level", "未知"),
                "danger_note": location_data.get("danger_note", ""),
                "main_rewards": location_data.get("main_rewards", ""),
                "discovered_from": turn.scene,
                "discovered_at": datetime.now().isoformat(),
                "discovered_by": turn.character_id,
            })
        elif existing:
            location_id = existing.id if hasattr(existing, "id") else existing.get("id")
        else:
            location_id = name

        character.setdefault("status", {})["current_scene"] = name
        character.setdefault("unlocked_locations", {}).setdefault(name, {
            "status": "entered",
            "first_visited": datetime.now().isoformat(),
            "location_id": location_id,
        })
        result["new_location"] = name

    @staticmethod
    def _record_consequence(character: Dict, result: Dict, turn: TurnInput) -> None:
        record_turn_consequence(
            character,
            result,
            turn.action_text,
            turn.scene,
            turn.kind,
            npc_name=turn.npc_name,
            turn_id=turn.turn_id,
        )

    @staticmethod
    def _public_result(kind: str, result: Dict) -> Dict:
        if kind == "environment":
            return result
        description = result.get("description", "")
        exit_dialogue = result.get("exit_dialogue", False)
        if description and description.strip().startswith("{") and '"description"' in description:
            try:
                inner = json.loads(description)
                description = inner.get("description", description)
                exit_dialogue = inner.get("exit_dialogue", exit_dialogue)
            except (TypeError, ValueError):
                pass
        return {
            "description": description,
            "exit_dialogue": exit_dialogue,
            "relationship_update": result.get("relationship_update"),
            "task_updates": result.get("task_updates", []),
            "memory_updates": result.get("memory_updates", []),
            "open_event": result.get("open_event"),
            "dynamic_event": result.get("dynamic_event"),
            "spellcard_result": result.get("spellcard_result"),
            "player_state_delta": result.get("player_state_delta", {}),
            "inventory_updates": result.get("inventory_updates", []),
            "reputation_updates": result.get("reputation_updates", []),
            "progression_delta": result.get("progression_delta", {}),
            "relationship_progress_delta": result.get("relationship_progress_delta", {}),
            "incident_state": result.get("incident_state"),
            "incident_resolution": result.get("incident_resolution"),
            "new_incident": result.get("new_incident"),
            "world_effects": result.get("world_effects", []),
            "offscreen_updates": result.get("offscreen_updates", []),
            "consequence_record_id": result.get("consequence_record_id"),
            "consequence_summary": result.get("consequence_summary", []),
        }


turn_orchestrator = TurnOrchestrator()
