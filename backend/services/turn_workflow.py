"""LangGraph Functional API adapter for resumable model generation."""

import asyncio
import hashlib
import importlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Type

from pydantic import BaseModel

from backend.config import DATA_DIR
from backend.services.ai_contracts import (
    DialogueTurnResult,
    EnvironmentTurnResult,
    parse_turn_response,
)
from backend.services.ai_service import ai_service, call_ai_async


os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

logger = logging.getLogger(__name__)

CHECKPOINT_PATH = Path(DATA_DIR) / "runtime" / "turn_checkpoints.sqlite3"
WORKFLOW_VERSION = 2
PROMPT_CONTRACT_VERSION = 1
CHECKPOINT_RETENTION_HOURS = int(os.environ.get("TOUHOU_CHECKPOINT_RETENTION_HOURS", "72"))
MAX_CHECKPOINT_THREADS = int(os.environ.get("TOUHOU_MAX_CHECKPOINT_THREADS", "200"))

_RUNTIMES: Dict[str, Dict[str, Any]] = {}
_RUNTIME_GUARDS: Dict[str, asyncio.Lock] = {}
_LAST_DIAGNOSTIC: Dict[str, Any] = {
    "enabled": False,
    "fallback": False,
    "recovered": False,
    "cleanup_error": None,
    "last_error": None,
}


class WorkflowUnavailableError(RuntimeError):
    """Checkpoint runtime cannot be used, but the legacy path remains available."""


class TurnInputConflictError(RuntimeError):
    """A turn id was reused with different generation input."""


def _runtime_thread_id(thread_id: str) -> str:
    return f"turn-v{WORKFLOW_VERSION}:{thread_id}"


def _runtime_key(path: Path = None) -> str:
    target = Path(path or CHECKPOINT_PATH).resolve()
    return f"{target}|loop:{id(asyncio.get_running_loop())}"


def _runtime_guard(path: Path = None) -> asyncio.Lock:
    key = _runtime_key(path)
    guard = _RUNTIME_GUARDS.get(key)
    if guard is None:
        guard = asyncio.Lock()
        _RUNTIME_GUARDS[key] = guard
    return guard


def _contract_for_kind(kind: str) -> Type[BaseModel]:
    return DialogueTurnResult if kind == "npc_dialogue" else EnvironmentTurnResult


def _input_identity(kind: str, prompt: str, temperature: float) -> Dict[str, str]:
    payload = {
        "kind": kind,
        "prompt": prompt,
        "temperature": round(float(temperature), 6),
        "workflow_version": WORKFLOW_VERSION,
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "model": str(getattr(ai_service, "model", "") or ""),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "input_hash": hashlib.sha256(encoded).hexdigest(),
        "model": payload["model"],
    }


def _load_runtime_dependencies() -> Dict[str, Any]:
    try:
        aiosqlite = importlib.import_module("aiosqlite")
        sqlite_module = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        func_module = importlib.import_module("langgraph.func")
        types_module = importlib.import_module("langgraph.types")
    except (ImportError, ModuleNotFoundError) as exc:
        raise WorkflowUnavailableError(f"LangGraph 运行依赖不可用: {exc}") from exc
    return {
        "aiosqlite": aiosqlite,
        "AsyncSqliteSaver": sqlite_module.AsyncSqliteSaver,
        "entrypoint": func_module.entrypoint,
        "task": func_module.task,
        "RetryPolicy": types_module.RetryPolicy,
    }


def _build_workflow(saver: Any, kind: str, dependencies: Dict[str, Any]):
    task = dependencies["task"]
    entrypoint = dependencies["entrypoint"]
    RetryPolicy = dependencies["RetryPolicy"]

    @task(
        name="generate_turn_response",
        timeout=75,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    async def generate_turn_response(payload: Dict) -> str:
        return await call_ai_async(
            str(payload.get("prompt") or ""),
            temperature=float(payload.get("temperature", 0.8)),
        )

    @task(name="parse_turn_contract")
    def parse_turn_contract(payload: Dict) -> Dict:
        return parse_turn_response(
            str(payload.get("response") or ""),
            _contract_for_kind(str(payload.get("kind") or kind)),
        )

    @entrypoint(
        checkpointer=saver,
        name=f"{kind}_turn_v{WORKFLOW_VERSION}",
        timeout=95,
    )
    async def workflow(inputs: Dict) -> Dict:
        response = await generate_turn_response({
            "prompt": inputs["prompt"],
            "temperature": inputs.get("temperature", 0.8),
        })
        result = await parse_turn_contract({
            "kind": inputs["kind"],
            "response": response,
        })
        return {"response": response, "result": result}

    return workflow


async def _configure_connection(connection: Any) -> None:
    await connection.execute("PRAGMA journal_mode=WAL")
    await connection.execute("PRAGMA synchronous=NORMAL")
    await connection.execute("PRAGMA busy_timeout=5000")
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS touhou_turn_threads (
            thread_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            workflow_version INTEGER NOT NULL,
            prompt_contract_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            recovered INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await connection.commit()


def _quarantine_checkpoint(path: Path) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not candidate.exists():
            continue
        target = candidate.with_name(f"{candidate.name}.corrupt-{stamp}")
        try:
            candidate.replace(target)
        except OSError:
            logger.exception("Unable to quarantine checkpoint file %s", candidate)


async def _open_runtime(kind: str, *, retry_corrupt: bool = True) -> Dict[str, Any]:
    path = Path(CHECKPOINT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    dependencies = _load_runtime_dependencies()
    connection = None
    try:
        connection = await dependencies["aiosqlite"].connect(str(path.resolve()))
        await _configure_connection(connection)
        saver = dependencies["AsyncSqliteSaver"](connection)
        await saver.setup()
        runtime = {
            "connection": connection,
            "saver": saver,
            "workflows": {},
            "dependencies": dependencies,
            "last_gc": 0.0,
        }
        runtime["workflows"][kind] = _build_workflow(saver, kind, dependencies)
        await _garbage_collect(runtime, force=True)
        return runtime
    except WorkflowUnavailableError:
        if connection is not None:
            await connection.close()
        raise
    except Exception as exc:
        if connection is not None:
            try:
                await connection.close()
            except Exception:
                pass
        message = str(exc).lower()
        corrupt = any(
            marker in message
            for marker in ("not a database", "malformed", "disk image is malformed")
        )
        if corrupt and retry_corrupt:
            logger.error("Checkpoint database is corrupt; rebuilding it: %s", exc)
            _quarantine_checkpoint(path)
            return await _open_runtime(kind, retry_corrupt=False)
        raise WorkflowUnavailableError(f"检查点数据库不可用: {exc}") from exc


async def _get_runtime(kind: str) -> Dict[str, Any]:
    key = _runtime_key()
    runtime = _RUNTIMES.get(key)
    if runtime is not None:
        if kind not in runtime["workflows"]:
            runtime["workflows"][kind] = _build_workflow(
                runtime["saver"], kind, runtime["dependencies"]
            )
        await _garbage_collect(runtime)
        return runtime
    async with _runtime_guard():
        runtime = _RUNTIMES.get(key)
        if runtime is None:
            runtime = await _open_runtime(kind)
            _RUNTIMES[key] = runtime
        elif kind not in runtime["workflows"]:
            runtime["workflows"][kind] = _build_workflow(
                runtime["saver"], kind, runtime["dependencies"]
            )
    return runtime


async def _garbage_collect(runtime: Dict[str, Any], *, force: bool = False) -> None:
    now = time.time()
    if not force and now - float(runtime.get("last_gc", 0)) < 3600:
        return
    runtime["last_gc"] = now
    connection = runtime["connection"]
    cutoff = now - max(1, CHECKPOINT_RETENTION_HOURS) * 3600
    cursor = await connection.execute(
        """
        SELECT thread_id FROM touhou_turn_threads
        WHERE updated_at < ?
        ORDER BY updated_at ASC
        """,
        (cutoff,),
    )
    expired = [row[0] for row in await cursor.fetchall()]
    cursor = await connection.execute(
        """
        SELECT thread_id FROM touhou_turn_threads
        ORDER BY updated_at DESC
        LIMIT -1 OFFSET ?
        """,
        (max(1, MAX_CHECKPOINT_THREADS),),
    )
    overflow = [row[0] for row in await cursor.fetchall()]
    for thread_id in dict.fromkeys(expired + overflow):
        await runtime["saver"].adelete_thread(thread_id)
        await connection.execute(
            "DELETE FROM touhou_turn_threads WHERE thread_id = ?", (thread_id,)
        )
    if expired or overflow:
        await connection.commit()
        await connection.execute("PRAGMA wal_checkpoint(PASSIVE)")


async def _prepare_thread(
    runtime: Dict[str, Any],
    *,
    runtime_thread_id: str,
    kind: str,
    identity: Dict[str, str],
) -> bool:
    connection = runtime["connection"]
    cursor = await connection.execute(
        """
        SELECT input_hash, workflow_version, prompt_contract_version
        FROM touhou_turn_threads WHERE thread_id = ?
        """,
        (runtime_thread_id,),
    )
    row = await cursor.fetchone()
    config = {"configurable": {"thread_id": runtime_thread_id}}
    checkpoint = await runtime["saver"].aget_tuple(config)
    now = time.time()

    # V1 checkpoints did not carry request identity. Discarding an unfinished
    # legacy checkpoint is safer than resuming it against an unverified prompt.
    if checkpoint is not None and row is None:
        await runtime["saver"].adelete_thread(runtime_thread_id)
        checkpoint = None

    if row is not None:
        if (
            row[0] != identity["input_hash"]
            or int(row[1]) != WORKFLOW_VERSION
            or int(row[2]) != PROMPT_CONTRACT_VERSION
        ):
            raise TurnInputConflictError(
                "相同 turn_id 已用于不同的回合输入，请生成新的 turn_id"
            )
        await connection.execute(
            """
            UPDATE touhou_turn_threads
            SET status = ?, updated_at = ?, recovered = ?
            WHERE thread_id = ?
            """,
            ("recovering" if checkpoint is not None else "starting", now, int(checkpoint is not None), runtime_thread_id),
        )
    else:
        await connection.execute(
            """
            INSERT INTO touhou_turn_threads (
                thread_id, kind, input_hash, model, workflow_version,
                prompt_contract_version, status, created_at, updated_at, recovered
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                runtime_thread_id,
                kind,
                identity["input_hash"],
                identity["model"],
                WORKFLOW_VERSION,
                PROMPT_CONTRACT_VERSION,
                "starting",
                now,
                now,
            ),
        )
    await connection.commit()
    return checkpoint is not None


async def _set_thread_status(runtime: Dict[str, Any], thread_id: str, status: str) -> None:
    await runtime["connection"].execute(
        "UPDATE touhou_turn_threads SET status = ?, updated_at = ? WHERE thread_id = ?",
        (status, time.time(), thread_id),
    )
    await runtime["connection"].commit()


async def _legacy_generation(kind: str, prompt: str, temperature: float) -> Dict:
    response = await call_ai_async(prompt, temperature=temperature)
    return {
        "response": response,
        "result": parse_turn_response(response, _contract_for_kind(kind)),
        "workflow_fallback": True,
    }


async def run_turn_workflow(
    *,
    kind: str,
    prompt: str,
    thread_id: str,
    temperature: float = 0.8,
) -> Dict:
    """Run or resume generation without making gameplay-state writes."""
    _LAST_DIAGNOSTIC.update({
        "enabled": True,
        "fallback": False,
        "recovered": False,
        "cleanup_error": None,
        "last_error": None,
    })
    try:
        runtime = await _get_runtime(kind)
    except WorkflowUnavailableError as exc:
        logger.warning("%s; using direct generation for this turn", exc)
        _LAST_DIAGNOSTIC.update({"fallback": True, "last_error": str(exc)})
        return await _legacy_generation(kind, prompt, temperature)

    runtime_id = _runtime_thread_id(thread_id)
    identity = _input_identity(kind, prompt, temperature)
    recovered = await _prepare_thread(
        runtime,
        runtime_thread_id=runtime_id,
        kind=kind,
        identity=identity,
    )
    _LAST_DIAGNOSTIC["recovered"] = recovered
    workflow = runtime["workflows"][kind]
    config = {"configurable": {"thread_id": runtime_id}}
    workflow_input = None if recovered else {
        "kind": kind,
        "prompt": prompt,
        "temperature": temperature,
    }
    await _set_thread_status(runtime, runtime_id, "generating")
    started_at = time.perf_counter()
    try:
        result = await workflow.ainvoke(workflow_input, config=config)
    except Exception as exc:
        await _set_thread_status(runtime, runtime_id, "interrupted")
        _LAST_DIAGNOSTIC["last_error"] = str(exc)
        raise
    await _set_thread_status(runtime, runtime_id, "parsed")
    _LAST_DIAGNOSTIC["workflow_ms"] = round(
        (time.perf_counter() - started_at) * 1000, 2
    )
    result["workflow_recovered"] = recovered
    return result


async def clear_turn_checkpoint(thread_id: str, *, strict: bool = False) -> bool:
    """Best-effort cleanup after a durable game-state commit."""
    if not CHECKPOINT_PATH.exists():
        return True
    try:
        runtime = await _get_runtime("environment")
        runtime_id = _runtime_thread_id(thread_id)
        await runtime["saver"].adelete_thread(runtime_id)
        await runtime["connection"].execute(
            "DELETE FROM touhou_turn_threads WHERE thread_id = ?", (runtime_id,)
        )
        await runtime["connection"].commit()
        _LAST_DIAGNOSTIC["cleanup_error"] = None
        return True
    except Exception as exc:
        _LAST_DIAGNOSTIC["cleanup_error"] = str(exc)
        logger.exception("Checkpoint cleanup failed for %s", thread_id)
        if strict:
            raise
        return False


async def clear_all_turn_checkpoints() -> Dict[str, Any]:
    """Delete all recovery threads without touching character save files."""
    if not CHECKPOINT_PATH.exists():
        return {"cleared": 0}
    try:
        runtime = await _get_runtime("environment")
    except WorkflowUnavailableError:
        cleared = 0
        for candidate in (
            CHECKPOINT_PATH,
            Path(f"{CHECKPOINT_PATH}-wal"),
            Path(f"{CHECKPOINT_PATH}-shm"),
        ):
            if candidate.exists():
                candidate.unlink(missing_ok=True)
                cleared += 1
        return {"cleared": cleared}
    cursor = await runtime["connection"].execute(
        "SELECT thread_id FROM touhou_turn_threads"
    )
    thread_ids = [row[0] for row in await cursor.fetchall()]
    try:
        cursor = await runtime["connection"].execute(
            "SELECT DISTINCT thread_id FROM checkpoints"
        )
        thread_ids.extend(row[0] for row in await cursor.fetchall())
    except Exception:
        pass
    thread_ids = list(dict.fromkeys(thread_ids))
    for thread_id in thread_ids:
        await runtime["saver"].adelete_thread(thread_id)
    await runtime["connection"].execute("DELETE FROM touhou_turn_threads")
    await runtime["connection"].commit()
    return {"cleared": len(thread_ids)}


async def get_checkpoint_metrics() -> Dict[str, Any]:
    if not CHECKPOINT_PATH.exists():
        return {
            "active_threads": 0,
            "oldest_age_seconds": 0,
            "database_bytes": 0,
        }
    try:
        runtime = await _get_runtime("environment")
        cursor = await runtime["connection"].execute(
            "SELECT COUNT(*), MIN(created_at) FROM touhou_turn_threads"
        )
        count, oldest = await cursor.fetchone()
        return {
            "active_threads": int(count or 0),
            "oldest_age_seconds": max(0, int(time.time() - oldest)) if oldest else 0,
            "database_bytes": CHECKPOINT_PATH.stat().st_size,
        }
    except Exception as exc:
        return {
            "active_threads": 0,
            "oldest_age_seconds": 0,
            "database_bytes": CHECKPOINT_PATH.stat().st_size if CHECKPOINT_PATH.exists() else 0,
            "error": str(exc),
        }


async def get_persisted_turn_status(character_id: str, turn_id: str) -> Dict[str, Any]:
    """Read recovery state after a process restart without exposing prompt data."""
    if not CHECKPOINT_PATH.exists():
        return {"state": "unknown"}
    try:
        runtime = await _get_runtime("environment")
        candidates = [
            _runtime_thread_id(f"{character_id}:{kind}:{turn_id}")
            for kind in ("environment", "npc_dialogue")
        ]
        placeholders = ",".join("?" for _ in candidates)
        cursor = await runtime["connection"].execute(
            f"""
            SELECT kind, status, updated_at, recovered
            FROM touhou_turn_threads
            WHERE thread_id IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            tuple(candidates),
        )
        row = await cursor.fetchone()
        if row is None:
            return {"state": "unknown"}
        return {
            "state": str(row[1]),
            "kind": str(row[0]),
            "updated_at": float(row[2]),
            "recovered": bool(row[3]),
            "persisted": True,
        }
    except Exception as exc:
        return {"state": "unknown", "error": str(exc)}


def get_workflow_diagnostic() -> Dict[str, Any]:
    return dict(_LAST_DIAGNOSTIC)


async def close_workflow_runtime(path: Path = None) -> None:
    """Close SQLite workers during tests and application shutdown."""
    if path is None:
        keys = list(_RUNTIMES)
    else:
        path_key = str(Path(path).resolve())
        keys = [key for key in _RUNTIMES if key.startswith(f"{path_key}|loop:")]
    for key in keys:
        runtime = _RUNTIMES.pop(key, None)
        _RUNTIME_GUARDS.pop(key, None)
        if runtime is not None:
            await runtime["connection"].close()


def workflow_enabled() -> bool:
    return os.environ.get("TOUHOU_LANGGRAPH", "1").lower() not in ("0", "false", "no")
