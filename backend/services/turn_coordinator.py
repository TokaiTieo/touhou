"""In-process coordination and status tracking for player turns."""

import asyncio
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple


TurnOperation = Callable[[], Awaitable[Dict[str, Any]]]


@dataclass
class TurnStatus:
    character_id: str
    turn_id: str
    kind: str
    state: str = "queued"
    created_at: float = 0.0
    updated_at: float = 0.0
    recovered: bool = False
    shared_waiters: int = 0
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    phase_timestamps: Dict[str, float] = field(default_factory=dict)

    def public_dict(self, *, include_result: bool = False) -> Dict[str, Any]:
        payload = asdict(self)
        from backend.services.runtime_diagnostics_service import phase_durations_ms

        payload["duration_ms"] = round(max(0, self.updated_at - self.created_at) * 1000, 2)
        payload["phase_durations_ms"] = phase_durations_ms(self.phase_timestamps)
        if not include_result:
            payload.pop("result", None)
        return payload


class TurnCoordinator:
    """Serialize turns per character and share duplicate in-flight requests."""

    def __init__(self) -> None:
        self._guards: Dict[int, asyncio.Lock] = {}
        self._character_locks: Dict[Tuple[int, str], asyncio.Lock] = {}
        self._inflight: Dict[Tuple[int, str, str], asyncio.Task] = {}
        self._statuses: Dict[Tuple[str, str], TurnStatus] = {}
        self.lock_timeout = max(10.0, min(600.0, float(os.environ.get("TOUHOU_TURN_LOCK_TIMEOUT", "120") or 120)))

    @staticmethod
    def ensure_turn_id(value: Optional[str]) -> str:
        return str(value or uuid.uuid4())

    def _loop_id(self) -> int:
        return id(asyncio.get_running_loop())

    def _guard(self) -> asyncio.Lock:
        loop_id = self._loop_id()
        guard = self._guards.get(loop_id)
        if guard is None:
            guard = asyncio.Lock()
            self._guards[loop_id] = guard
        return guard

    async def execute(
        self,
        *,
        character_id: str,
        turn_id: str,
        kind: str,
        operation: TurnOperation,
    ) -> Dict[str, Any]:
        loop_id = self._loop_id()
        inflight_key = (loop_id, character_id, turn_id)
        status_key = (character_id, turn_id)
        async with self._guard():
            task = self._inflight.get(inflight_key)
            if task is None:
                now = time.time()
                status = TurnStatus(
                    character_id=character_id,
                    turn_id=turn_id,
                    kind=kind,
                    created_at=now,
                    updated_at=now,
                    phase_timestamps={"queued": now},
                )
                self._statuses[status_key] = status
                character_key = (loop_id, character_id)
                lock = self._character_locks.setdefault(character_key, asyncio.Lock())
                task = asyncio.create_task(
                    self._run_serialized(lock, status, operation),
                    name=f"turn:{character_id}:{turn_id}",
                )
                self._inflight[inflight_key] = task
                task.add_done_callback(
                    lambda completed, key=inflight_key: self._finish_inflight(key, completed)
                )
            else:
                status = self._statuses.get(status_key)
                if status is not None:
                    status.shared_waiters += 1
                    status.recovered = True
                    status.updated_at = time.time()

        # A disconnected SSE client must not cancel the authoritative turn. A
        # retry with the same turn_id can join this task and receive its result.
        return await asyncio.shield(task)

    async def _run_serialized(
        self,
        lock: asyncio.Lock,
        status: TurnStatus,
        operation: TurnOperation,
    ) -> Dict[str, Any]:
        try:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=self.lock_timeout)
            except asyncio.TimeoutError as exc:
                status.state = "failed"
                status.error = "等待上一回合结束超时"
                status.updated_at = time.time()
                status.phase_timestamps["lock_timeout"] = status.updated_at
                raise TimeoutError("等待上一回合结束超时，请检查网络或重新载入角色") from exc
            try:
                status.state = "running"
                status.updated_at = time.time()
                status.phase_timestamps["running"] = status.updated_at
                result = await operation()
                status.result = result
                status.state = "committed"
                status.updated_at = time.time()
                status.phase_timestamps["committed"] = status.updated_at
                return result
            finally:
                lock.release()
        except asyncio.CancelledError:
            status.state = "cancelled"
            status.updated_at = time.time()
            status.phase_timestamps["cancelled"] = status.updated_at
            raise
        except Exception as exc:
            status.state = "failed"
            status.error = str(exc)[:500]
            status.updated_at = time.time()
            status.phase_timestamps["failed"] = status.updated_at
            raise

    def _finish_inflight(self, key: Tuple[int, str, str], task: asyncio.Task) -> None:
        current = self._inflight.get(key)
        if current is task:
            self._inflight.pop(key, None)
        self._prune_statuses()

    def _prune_statuses(self, *, max_entries: int = 300) -> None:
        if len(self._statuses) <= max_entries:
            return
        ordered = sorted(self._statuses.items(), key=lambda item: item[1].updated_at)
        for key, status in ordered[: len(self._statuses) - max_entries]:
            if status.state not in ("queued", "running"):
                self._statuses.pop(key, None)

    def get_status(self, character_id: str, turn_id: str) -> Optional[TurnStatus]:
        return self._statuses.get((character_id, turn_id))

    async def cancel(self, character_id: str, turn_id: str) -> bool:
        loop_id = self._loop_id()
        key = (loop_id, character_id, turn_id)
        async with self._guard():
            task = self._inflight.get(key)
            status = self._statuses.get((character_id, turn_id))
            if task is None or task.done():
                return False
            if status is not None:
                status.state = "cancelling"
                status.updated_at = time.time()
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    def set_state(self, character_id: str, turn_id: str, state: str, **updates: Any) -> None:
        status = self.get_status(character_id, turn_id)
        if status is None:
            return
        status.state = state
        status.updated_at = time.time()
        status.phase_timestamps[state] = status.updated_at
        for key, value in updates.items():
            if hasattr(status, key):
                setattr(status, key, value)

    def recent_statuses(self, character_id: str, limit: int = 10) -> list:
        statuses = [
            status for (owner, _), status in self._statuses.items()
            if owner == character_id
        ]
        statuses.sort(key=lambda item: item.updated_at, reverse=True)
        return [status.public_dict() for status in statuses[:limit]]

    def endpoint(self, kind: str):
        """Wrap an existing FastAPI turn handler without changing its schema."""

        def decorator(handler):
            @wraps(handler)
            async def wrapped(request, *args, **kwargs):
                turn_id = self.ensure_turn_id(getattr(request, "turn_id", None))
                request.turn_id = turn_id
                return await self.execute(
                    character_id=str(request.character_id),
                    turn_id=turn_id,
                    kind=kind,
                    operation=lambda: handler(request, *args, **kwargs),
                )

            return wrapped

        return decorator


turn_coordinator = TurnCoordinator()
