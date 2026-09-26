"""Measure synthetic save IO and response sizes without loading player saves."""

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import world_manager as storage
from backend.services.conversation_archive_service import history_page
from backend.services.character_view_service import character_state, command_result


def benchmark(count):
    value = storage.ensure_character_fields({"character_id": "benchmark", "profile": {"name": "性能测试"},
        "conversation_history": [{"message_id": f"msg_{i}", "speaker": "旁白", "content": "合成剧情测试。" * 80} for i in range(count)]})
    inline_bytes = len(json.dumps(value, ensure_ascii=False).encode())
    with tempfile.TemporaryDirectory(prefix="touhou-benchmark-") as folder, patch.object(storage, "get_characters_dir", return_value=Path(folder)):
        started = time.perf_counter()
        storage.save_turn_bundle("benchmark", value, {})
        initial_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        loaded = storage.load_character("benchmark")
        load_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        page = history_page(loaded, limit=80)
        page_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        history_page(loaded, query="合成剧情", limit=30)
        index_build_ms = (time.perf_counter() - started) * 1000
        search_times = []
        for _ in range(5):
            started = time.perf_counter()
            history_page(loaded, before_id=f"msg_{count // 2}", query="合成剧情", limit=30)
            search_times.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        storage.save_turn_bundle("benchmark", loaded, {})
        save_ms = (time.perf_counter() - started) * 1000
        return {"messages": count, "inline_bytes": inline_bytes, "main_file_bytes": (Path(folder) / "benchmark.json").stat().st_size,
            "initial_archive_ms": round(initial_ms, 2), "load_ms": round(load_ms, 2), "subsequent_save_ms": round(save_ms, 2),
            "page_ms": round(page_ms, 2), "page_bytes": len(json.dumps(page, ensure_ascii=False).encode()),
            "index_build_ms": round(index_build_ms, 2), "warm_search_ms": round(sum(search_times) / len(search_times), 2),
            "state_bytes": len(json.dumps(character_state(loaded), ensure_ascii=False).encode()),
            "receipt_bytes": len(json.dumps(command_result({"character": loaded}), ensure_ascii=False).encode())}


if __name__ == "__main__":
    print(json.dumps({"synthetic_only": True, "results": [benchmark(count) for count in (1000, 10000)]}, ensure_ascii=False, indent=2))
