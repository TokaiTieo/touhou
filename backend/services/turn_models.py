"""Serializable contracts shared by HTTP routes and turn workflows."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TurnKind = Literal["environment", "npc_dialogue"]


class TurnInput(BaseModel):
    """Stable, JSON-serializable input for one player turn."""

    model_config = ConfigDict(extra="ignore")

    kind: TurnKind
    character_id: str
    scene: str
    player_name: str
    action_text: str = ""
    turn_id: Optional[str] = None
    npc_id: Optional[str] = None
    npc_name: Optional[str] = None
    scene_npcs: List[Dict[str, Any]] = Field(default_factory=list)


class TurnContext(BaseModel):
    """Mutable in-memory state for one transaction; never used as a save format."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    turn: TurnInput
    character: Dict[str, Any]
    tasks: Dict[str, Any]
    cached_response: Optional[Dict[str, Any]] = None
    workflow_thread_id: str = ""
    base_character_revision: int = 0
    base_tasks_revision: int = 0
    pending_world_changes: Dict[str, Any] = Field(default_factory=dict)


class TurnOutcome(BaseModel):
    """Result returned by the orchestrator after settlement and commit."""

    result: Dict[str, Any]
    duplicate: bool = False
    committed: bool = False
    workflow_thread_id: str = ""
