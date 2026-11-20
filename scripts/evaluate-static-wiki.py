"""Paired public-fixture retrieval turns; no production save or Wiki publication."""
import argparse
import asyncio
import json
import importlib
import os
from pathlib import Path
import sys
import shutil
import tempfile
import time
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports/static-wiki-pilot"
CAP = 10_000_000
CASES = (
    ("place", "我想找风祝早苗。她的设定地点是哪座神社？这能证明她此刻一定在那里吗？", ("守矢", "此刻")),
    ("faction", "红魔馆成员中谁决策、谁管理、谁守门？请区分这三个职责。", ("蕾米莉亚", "咲夜", "美铃")),
    ("rule", "我想不打架就解决异变。符卡决斗和协商撤退是否冲突？", ("符卡", "协商")),
)


async def run(root, live):
    os.environ["TOUHOU_DATA_DIR"] = str(root / "data")
    for relative in ("worlds_index.json", "world_touhou/timeline.json", "world_touhou/worldview.txt",
                     "world_touhou/locations/location_base.json", "world_touhou/npcs/npc_index.json"):
        target = root / "data/worlds" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "worlds" / relative, target)
    if live and (not os.getenv("DEEPSEEK_API_KEY") or os.getenv("TOUHOU_E2E_MOCK_AI") == "1"):
        raise SystemExit("需要操作系统 Key 且不能启用模拟 AI")
    from backend.services import agent_scheduler, wiki_store
    ai_service = importlib.import_module("backend.services.ai_service")
    from backend.services.agent_contracts import default_agent_state
    from backend.services.evaluation_context import EvaluationContext, evaluation_context
    from backend.services.npc_agent_runtime import BudgetLedger
    from backend.services.turn_models import TurnContext, TurnInput
    from backend.services.wiki_compiler import load
    from backend.services.wiki_contracts import checksum, SPECS
    from backend.services.wiki_store import Store, write_json
    if live and (urlparse(ai_service.ai_service.base_url).hostname != "api.deepseek.com"
                 or urlparse(ai_service.ai_service.base_url).scheme != "https" or ai_service.E2E_MOCK_AI):
        raise SystemExit("真实评测仅允许官方 HTTPS DeepSeek 接口")
    world = ROOT / "worlds/world_touhou"
    store = Store(world, root / "test-only")
    draft = load(OUT / "draft.json")
    version = store.publish(draft, checksum(draft), "isolated-evaluation-fixture")
    book_ids = {page.book for page in SPECS.values() if page.book}
    book = [row for row in load(world / "world_info.json")["entries"] if row["id"] in book_ids]
    # Both arms see the same reviewed raw world book and no private NPC profiles.
    mode = "live" if live else "offline"
    report_path = OUT / (mode + "-ab-v2.json")
    if report_path.exists():
        raise SystemExit(f"已存在的评测不覆盖: {report_path}")
    ledger = BudgetLedger(OUT / "live-budget.sqlite3" if live else root / "offline-budget.db",
                          "wiki-ab-nov20", CAP, 6)
    results = []
    model = ai_service.ai_service.model if live else "offline-fixture"
    for idx, (case, question, rubric) in enumerate(CASES):
        for enabled in ((False, True) if idx % 2 == 0 else (True, False)):
            base = {"character_id": "wiki-ab", "timeline_epoch": "one", "profile": {"name": "测试旅人"},
                    "status": {"current_scene": "人间之里"}, "time": {"current_day": 1, "current_hour": 8},
                    "agent_state": {**default_agent_state(), "mode": "retrieval"}}
            turn = TurnInput(kind="environment", scene="人间之里", player_name="测试旅人", character_id="wiki-ab",
                             action_text=question, turn_id="wiki-ab-" + case)
            context = TurnContext(turn=turn, character=base, tasks={})
            row = {"case": case, "enabled": enabled, "question": question, "save_hash": checksum(base)}

            async def generate(prompt, temperature):
                evidence = json.loads(prompt.splitlines()[-1])["evidence"]["world_info"]
                row.update(prompt_hash=checksum(prompt), evidence=evidence, request_chars=len(prompt),
                           evidence_terms={term: any(term in e["content"] for e in evidence) for term in rubric})
                if not live:
                    return '{"description":"离线测试回执。"}'
                job = f"{case}:{enabled}"
                bound = len(prompt.encode()) + 512 + 1024
                ledger.reserve({job: bound})
                call = ledger.start(job, bound)
                usage, ok = {}, False
                try:
                    ai_service.reset_ai_diagnostics()
                    response = await ai_service.call_ai_async(prompt, temperature=temperature, max_output_tokens=1024,
                                                              single_attempt=True, structured=True)
                    usage = ai_service.get_last_ai_usage()
                    err = ai_service.get_last_ai_error()
                    if err:
                        raise RuntimeError("provider_" + str(err["code"]))
                    ok = True
                    return response
                finally:
                    row["usage"] = usage
                    ledger.finish(call, usage, success=ok)

            token = evaluation_context.set(EvaluationContext(base, {}, generate))
            started = time.monotonic()
            try:
                # Separate checkpoint DB per arm, identical turn ID, snapshot and model.
                with patch.object(wiki_store, "configured_store", return_value=store if enabled else None), \
                        patch("backend.services.turn_workflow.CHECKPOINT_PATH", root / f"{enabled}.db"), \
                        patch.object(agent_scheduler, "server_presence", return_value=[]), \
                        patch.object(agent_scheduler, "catalogue", return_value={}), \
                        patch.object(agent_scheduler, "_world_entries", return_value=book):
                    result = await agent_scheduler.run_retrieval_turn(context)
                    row.update(answer=result["description"], calls=result["agent_turn"]["budget"]["requests"])
            except Exception as exc:
                row["error"] = str(exc.__cause__ or exc)[:250]
            finally:
                evaluation_context.reset(token)
                row["seconds"] = round(time.monotonic() - started, 3)
                results.append(row)
                write_json(report_path, {"edition": version, "model": model, "results": results,
                                         "cap": CAP, "budget": ledger.summary()})
            print(case, enabled, "failed" if "error" in row else "ok", row["seconds"], flush=True)
            if "error" in row:
                raise SystemExit("保留失败和收费；评测停止，无自动重试")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="touhou-wiki-ab-") as tmp:
        asyncio.run(run(Path(tmp), args.live))
