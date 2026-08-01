"""Run deterministic gameplay scenarios without calling an AI provider."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.turn_evaluation import run_turn_evaluation


def main() -> int:
    report = run_turn_evaluation()
    for result in report["results"]:
        marker = "PASS" if result["passed"] else "FAIL"
        print(f"[{marker}] {result['title']}")
        for failure in result["failures"]:
            print(f"  - {failure}")
    print(
        f"\nTurn evaluation: {report['passed']}/{report['total']} passed, "
        f"{report['failed']} failed"
    )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
