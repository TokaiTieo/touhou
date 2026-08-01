"""Shared lifecycle for coordinated environment and NPC turns."""

from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import HTTPException

from backend.services.turn_coordinator import turn_coordinator
from backend.services.turn_models import TurnContext, TurnInput
from backend.services.turn_orchestrator import (
    CharacterNotFoundError,
    turn_orchestrator,
)
from backend.services.turn_workflow import (
    TurnInputConflictError,
    clear_turn_checkpoint,
)
from backend.world_manager import StaleTurnError


class TurnRunner:
    """Own coordination, replay, settlement, commit and checkpoint cleanup."""

    def endpoint(self, kind: str):
        def decorator(handler):
            @wraps(handler)
            async def wrapped(request, *args, **kwargs):
                turn_id = turn_coordinator.ensure_turn_id(
                    getattr(request, "turn_id", None)
                )
                request.turn_id = turn_id
                try:
                    return await turn_coordinator.execute(
                        character_id=str(request.character_id),
                        turn_id=turn_id,
                        kind=kind,
                        operation=lambda: handler(request, *args, **kwargs),
                    )
                except TurnInputConflictError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                except StaleTurnError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=f"{exc}。请刷新角色状态后重新行动。",
                    ) from exc

            return wrapped

        return decorator

    async def begin(self, turn: TurnInput) -> Tuple[TurnContext, Optional[Dict[str, Any]]]:
        turn_coordinator.set_state(turn.character_id, turn.turn_id, "preparing")
        try:
            context = turn_orchestrator.begin(turn)
        except CharacterNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色不存在") from exc
        if context.cached_response is not None:
            turn_coordinator.set_state(
                turn.character_id,
                turn.turn_id,
                "committed",
                recovered=True,
            )
            await clear_turn_checkpoint(context.workflow_thread_id)
            return context, context.cached_response
        return context, None

    def mark(self, context: TurnContext, state: str) -> None:
        turn_coordinator.set_state(
            context.turn.character_id,
            context.turn.turn_id,
            state,
        )

    async def finalize(
        self,
        context: TurnContext,
        result: Dict[str, Any],
        *,
        rule_preview: Optional[Dict[str, Any]] = None,
        on_contract_failure: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        self.mark(context, "settling")
        if not result.get("contract_valid"):
            if on_contract_failure is not None:
                on_contract_failure(context.character)
            outcome = turn_orchestrator.commit_contract_failure(context, result)
        else:
            outcome = turn_orchestrator.settle(
                context,
                result,
                rule_preview=rule_preview,
            )
        self.mark(context, "checkpoint_cleanup")
        await clear_turn_checkpoint(context.workflow_thread_id)
        self.mark(context, "committed")
        return outcome.result


turn_runner = TurnRunner()
