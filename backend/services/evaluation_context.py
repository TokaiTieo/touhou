"""Task-local dry-run state for the production turn handlers."""

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class EvaluationContext:
    character: dict
    tasks: dict
    generate: object
    prompt_fingerprints: list = field(default_factory=list)


evaluation_context = ContextVar("evaluation_context", default=None)
