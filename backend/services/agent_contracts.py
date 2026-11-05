"""Server-bound identities and a deliberately small NPC command vocabulary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PERMISSION_VERSION = 1
MAX_PARTICIPANTS = 6


class Reader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    save_id: str
    epoch: str
    npc_id: str
    task_id: str
    permission_version: int = PERMISSION_VERSION


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["speak", "invite", "accept", "reject", "reschedule", "wait", "plan", "investigate", "use", "offer", "transfer", "relationship"]
    text: str = Field(default="", max_length=1800)
    target_id: str = Field(default="", max_length=120)
    event_id: str = Field(default="", max_length=160)
    item: str = Field(default="", max_length=100)
    quantity: int = Field(default=1, ge=1, le=100)
    hour: float | int | None = Field(default=None, ge=0, le=1000000)
    scene: str = Field(default="", max_length=120)
    relationship_kind: Literal["invitation", "confession", "deepen"] = "invitation"
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def domain_fields(self):
        required = {
            "speak": ("text",), "invite": ("target_id", "scene"),
            "accept": ("event_id",), "reject": ("event_id",),
            "reschedule": ("event_id", "scene"), "plan": ("text",),
            "investigate": ("target_id",), "use": ("item",),
            "offer": ("item", "target_id"), "transfer": ("item", "target_id"),
            "relationship": ("text",),
        }
        for name in required.get(self.kind, ()):
            if not getattr(self, name).strip():
                raise ValueError(f"{self.kind} requires {name}")
        if self.kind in ("invite", "reschedule") and self.hour is None:
            raise ValueError("Appointments require an absolute game hour")
        allowed = {
            "speak": {"text", "target_id", "evidence_ids"},
            "invite": {"target_id", "hour", "scene", "text"},
            "accept": {"event_id"}, "reject": {"event_id", "text"},
            "reschedule": {"event_id", "hour", "scene", "text"},
            "wait": {"text"}, "plan": {"text"},
            "investigate": {"target_id", "evidence_ids"},
            "use": {"item", "quantity"}, "offer": {"item", "quantity", "target_id"},
            "transfer": {"item", "quantity", "target_id"},
            "relationship": {"text", "relationship_kind"},
        }
        defaults = {key: field.get_default(call_default_factory=True) for key, field in type(self).model_fields.items()}
        for key in self.model_fields_set - allowed[self.kind] - {"kind"}:
            if getattr(self, key) != defaults[key]:
                raise ValueError(f"{key} is not permitted for {self.kind}")
        return self


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    commands: list[Command] = Field(min_length=1, max_length=4)


class HostNarration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str = Field(min_length=1, max_length=6000)
    cited_event_ids: list[str] = Field(default_factory=list, max_length=60)


def proposal_schema():
    """Expose the domain-field validator to the model instead of a loose union."""
    schema = Proposal.model_json_schema()
    properties = schema["$defs"]["Command"]["properties"]
    fields = {
        "speak": (["text"], ["target_id", "evidence_ids"]),
        "invite": (["target_id", "hour", "scene"], ["text"]),
        "accept": (["event_id"], []), "reject": (["event_id"], ["text"]),
        "reschedule": (["event_id", "hour", "scene"], ["text"]),
        "wait": ([], ["text"]), "plan": (["text"], []),
        "investigate": (["target_id"], ["evidence_ids"]),
        "use": (["item"], ["quantity"]),
        "offer": (["item", "target_id"], ["quantity"]),
        "transfer": (["item", "target_id"], ["quantity"]),
        "relationship": (["text"], ["relationship_kind"]),
    }
    schema["$defs"]["Command"] = {"oneOf": [
        {"type": "object", "additionalProperties": False,
         "properties": {"kind": {"const": kind}, **{key: properties[key] for key in required + optional}},
         "required": ["kind", *required]} for kind, (required, optional) in fields.items()]}
    return schema


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concurrency: int = Field(default=3, ge=1, le=3)
    max_requests: int = Field(default=10, ge=1, le=20)
    max_tokens: int = Field(default=500000, ge=1000, le=1000000)
    max_output_tokens: int = Field(default=1800, ge=128, le=4096)
    timeout_seconds: int = Field(default=240, ge=30, le=600)


def default_agent_state():
    return {"version": 1, "mode": "legacy", "permission_version": PERMISSION_VERSION,
            "events": [], "consumed_events": [], "last_turn": {}}
