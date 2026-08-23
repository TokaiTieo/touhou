"""Run local narrative quality fixtures or optional configured-model probes."""

import argparse
import asyncio
import json
from pathlib import Path

from backend.services.ai_service import call_ai_async
from backend.services.narrative_evaluation_service import (
    DEFAULT_CASES_PATH,
    evaluate_narrative_text,
    run_narrative_evaluation,
)


async def run_live(source: Path):
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    results = []
    for case in payload.get("cases", []):
        prompt = str(case.get("live_prompt") or "").strip()
        if not prompt:
            continue
        response = await call_ai_async(prompt, temperature=0.7)
        results.append({
            "id": case.get("id"),
            "response": response,
            "evaluation": evaluate_narrative_text(
                response,
                expected_terms=case.get("expected_terms"),
                forbidden_terms=case.get("forbidden_terms"),
                required_facts=case.get("required_facts"),
            ),
        })
    return {"mode": "live", "total": len(results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_live(args.cases)) if args.live else run_narrative_evaluation(args.cases)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if not report.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
