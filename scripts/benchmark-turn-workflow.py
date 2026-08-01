"""Compare legacy parsing with the local LangGraph orchestration overhead."""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routes import ghost
from backend.services import turn_workflow
from backend.services.ai_contracts import EnvironmentTurnResult


RESPONSE = json.dumps({
    "description": "结界波纹逐渐恢复稳定。",
    "time_cost": 0.5,
    "is_dead": False,
    "task_updates": [],
    "memory_updates": [],
}, ensure_ascii=False)


async def fake_ai(prompt: str, temperature: float = 0.8) -> str:
    return RESPONSE


async def measure(count: int = 30):
    ghost.call_ai_async = fake_ai
    turn_workflow.call_ai_async = fake_ai
    prompt = "本地工作流性能测试"

    os.environ["TOUHOU_LANGGRAPH"] = "0"
    started = time.perf_counter()
    legacy_results = []
    for index in range(count):
        _, result = await ghost.execute_turn_generation(
            "environment",
            prompt,
            f"legacy-{index}",
            EnvironmentTurnResult,
        )
        legacy_results.append(result)
    legacy_ms = (time.perf_counter() - started) * 1000

    with tempfile.TemporaryDirectory() as root:
        checkpoint = Path(root) / "benchmark.sqlite3"
        turn_workflow.CHECKPOINT_PATH = checkpoint
        os.environ["TOUHOU_LANGGRAPH"] = "1"

        cold_started = time.perf_counter()
        _, cold_result = await ghost.execute_turn_generation(
            "environment",
            prompt,
            "graph-cold",
            EnvironmentTurnResult,
        )
        cold_ms = (time.perf_counter() - cold_started) * 1000
        await turn_workflow.clear_turn_checkpoint("graph-cold")

        started = time.perf_counter()
        graph_results = []
        for index in range(count):
            thread_id = f"graph-{index}"
            _, result = await ghost.execute_turn_generation(
                "environment",
                prompt,
                thread_id,
                EnvironmentTurnResult,
            )
            graph_results.append(result)
            await turn_workflow.clear_turn_checkpoint(thread_id)
        graph_ms = (time.perf_counter() - started) * 1000
        await turn_workflow.close_workflow_runtime(checkpoint)

    comparable_keys = (
        "description", "time_cost", "is_dead", "task_updates",
        "memory_updates", "contract_valid",
    )
    parity = all(
        {key: left.get(key) for key in comparable_keys}
        == {key: right.get(key) for key in comparable_keys}
        for left, right in zip(legacy_results, graph_results)
    ) and all(
        cold_result.get(key) == legacy_results[0].get(key) for key in comparable_keys
    )
    return {
        "iterations": count,
        "result_parity": parity,
        "legacy_total_ms": round(legacy_ms, 2),
        "legacy_mean_ms": round(legacy_ms / count, 3),
        "langgraph_cold_ms": round(cold_ms, 2),
        "langgraph_total_ms": round(graph_ms, 2),
        "langgraph_mean_ms": round(graph_ms / count, 3),
        "local_overhead_mean_ms": round((graph_ms - legacy_ms) / count, 3),
        "note": "Mock model latency excluded; measures local orchestration and SQLite only.",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(measure()), ensure_ascii=False, indent=2))

