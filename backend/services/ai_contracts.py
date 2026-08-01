"""Validated contracts for state-changing AI responses."""

import json
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.utils.ai_json import clean_json_response


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class LocationChange(ContractModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["existing", "new"] = "existing"
    parent_id: Optional[str] = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="", max_length=8)


class TaskUpdate(ContractModel):
    action: Literal["add", "update", "complete", "update_priority"]
    task_id: Optional[str] = Field(default=None, max_length=160)
    name: Optional[str] = Field(default=None, max_length=160)
    task_name: Optional[str] = Field(default=None, max_length=160)
    info: str = Field(default="", max_length=3000)
    priority: int = Field(default=100, ge=1, le=1000)
    source: str = Field(default="ai", max_length=80)

    @model_validator(mode="after")
    def require_target(self):
        if self.action != "add" and not self.task_id:
            raise ValueError("task_id is required for non-add updates")
        return self


class MemoryUpdate(ContractModel):
    npc_name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=2000)
    tags: List[str] = Field(default_factory=list)
    importance: int = Field(default=5, ge=1, le=10)
    emotion: str = Field(default="中性", max_length=40)


class SpellcardResult(ContractModel):
    opponent: str = Field(default="当前对手", max_length=120)
    spellcard_name: str = Field(default="未命名符卡", max_length=160)
    outcome: str = Field(default="未裁定", max_length=80)
    summary: str = Field(default="", max_length=2000)
    cost: Any = ""


class InventoryUpdate(ContractModel):
    action: Literal["add", "remove", "use"] = "add"
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=999)
    category: str = Field(default="道具", max_length=60)
    description: str = Field(default="", max_length=500)


class ReputationUpdate(ContractModel):
    faction: str = Field(min_length=1, max_length=120)
    delta: float = Field(ge=-12, le=12)
    reason: str = Field(default="", max_length=500)

class WorldEffect(ContractModel):
    kind: Literal["location", "rumor", "flag"] = "location"
    target: str = Field(default="", max_length=160)
    effect: str = Field(min_length=1, max_length=1000)
    magnitude: float = Field(default=0, ge=-10, le=10)
    delay_hours: float = Field(default=0, ge=0, le=168)


class BaseTurnResult(ContractModel):
    description: str = Field(min_length=1, max_length=20000)
    relationship_update: Optional[str] = Field(default=None, max_length=2000)
    task_updates: List[TaskUpdate] = Field(default_factory=list)
    memory_updates: List[MemoryUpdate] = Field(default_factory=list)
    open_event: Optional[Dict[str, Any]] = None
    spellcard_result: Optional[SpellcardResult] = None
    time_cost: float = Field(default=0, ge=0, le=12)
    new_energy_state: Optional[str] = Field(default=None, max_length=80)
    player_state_delta: Dict[str, Any] = Field(default_factory=dict)
    inventory_updates: List[InventoryUpdate] = Field(default_factory=list)
    reputation_updates: List[ReputationUpdate] = Field(default_factory=list)
    world_effects: List[WorldEffect] = Field(default_factory=list)

    @field_validator("task_updates", "memory_updates", "inventory_updates", "reputation_updates", "world_effects", mode="before")
    @classmethod
    def list_or_empty(cls, value):
        return value if isinstance(value, list) else []


class EnvironmentTurnResult(BaseTurnResult):
    is_dead: bool = False
    new_location: Optional[LocationChange] = None


class DialogueTurnResult(BaseTurnResult):
    exit_dialogue: bool = False


def parse_turn_response(response: str, contract: Type[BaseTurnResult]) -> Dict[str, Any]:
    """Return a safe response. Invalid state changes are discarded, never persisted."""
    try:
        payload = json.loads(clean_json_response(response))
        validated = contract.model_validate(payload)
        result = validated.model_dump(mode="python")
        result["contract_valid"] = True
        return result
    except (TypeError, json.JSONDecodeError, ValidationError) as exc:
        raw = str(response or "").strip()
        if raw.startswith("【AI调用失败】") or raw.startswith("【系统提示】"):
            description = raw
        else:
            description = raw[:2000] or "AI 返回格式无效，本回合未写入游戏状态。"
        return {
            "description": description,
            "is_dead": False,
            "new_location": None,
            "exit_dialogue": False,
            "task_updates": [],
            "memory_updates": [],
            "relationship_update": None,
            "time_cost": 0,
            "contract_valid": False,
            "retryable": True,
            "contract_error": str(exc)[:300]
        }
