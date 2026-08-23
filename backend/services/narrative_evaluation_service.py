"""Local narrative quality checks and player-rated evaluation samples."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_CASES_PATH = (
    Path(__file__).with_name("narrative_evaluation_cases.json")
)
INTERNAL_ID_PATTERN = re.compile(
    r"\b(?:main|free|npc|loc|event|incident|turn|task)_touhou_[a-z0-9_]+\b",
    re.IGNORECASE,
)
SYSTEM_LEAK_PATTERNS = (
    "system prompt",
    "developer message",
    "memory_updates",
    "task_updates",
    "player_state_delta",
    "contract_valid",
)
COERCIVE_PATTERNS = ("你只能", "你必须立刻", "无法前往其他", "禁止探索", "唯一选择")


def _sentences(text: str) -> List[str]:
    return [item.strip() for item in re.split(r"[。！？!?\n]+", text) if item.strip()]


def _repetition_ratio(text: str) -> float:
    sentences = _sentences(text)
    if len(sentences) < 2:
        return 0.0
    normalized = [re.sub(r"\s+", "", sentence) for sentence in sentences]
    counts = Counter(normalized)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    return repeated / max(1, len(normalized))


def _history_overlap(text: str, history: Iterable[str]) -> float:
    current = set(_sentences(text))
    previous = set()
    for item in history or []:
        previous.update(_sentences(str(item or "")))
    if not current or not previous:
        return 0.0
    return len(current & previous) / len(current)


def evaluate_narrative_text(
    text: str,
    *,
    expected_terms: Optional[Iterable[str]] = None,
    forbidden_terms: Optional[Iterable[str]] = None,
    required_facts: Optional[Iterable[str]] = None,
    recent_responses: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Score prose without calling an external judge or mutating game state."""
    content = str(text or "").strip()
    expected = [str(item) for item in expected_terms or [] if str(item)]
    forbidden = [str(item) for item in forbidden_terms or [] if str(item)]
    facts = [str(item) for item in required_facts or [] if str(item)]
    issues: List[Dict[str, str]] = []

    if not content:
        return {
            "score": 0,
            "passed": False,
            "dimensions": {
                "readability": 0,
                "persona": 0,
                "continuity": 0,
                "agency": 0,
                "cleanliness": 0,
            },
            "issues": [{"code": "empty", "message": "模型未返回叙事文本"}],
        }

    readability = 100
    if len(content) < 24:
        readability -= 28
        issues.append({"code": "too_short", "message": "回复过短，缺少可感知的场景反馈"})
    if len(content) > 5000:
        readability -= 18
        issues.append({"code": "too_long", "message": "单回合文本过长"})
    repetition = max(
        _repetition_ratio(content),
        _history_overlap(content, recent_responses or []),
    )
    if repetition > 0:
        readability -= min(45, round(repetition * 100))
        issues.append({"code": "repetition", "message": "存在重复句或与近期回复高度重合"})

    persona = 100
    missing_expected = [term for term in expected if term not in content]
    if expected and len(missing_expected) == len(expected):
        persona -= 35
        issues.append({"code": "persona_anchor_missing", "message": "未体现本场景要求的人物锚点"})
    present_forbidden = [term for term in forbidden if term in content]
    if present_forbidden:
        persona -= min(70, 25 * len(present_forbidden))
        issues.append({"code": "persona_conflict", "message": "出现与人物或场景冲突的表述"})

    continuity = 100
    missing_facts = [fact for fact in facts if fact not in content]
    if missing_facts:
        continuity -= min(60, 20 * len(missing_facts))
        issues.append({"code": "continuity_missing", "message": "未承接必须保留的既有事实"})

    agency = 100
    coercive = [pattern for pattern in COERCIVE_PATTERNS if pattern in content]
    if coercive:
        agency -= min(75, 25 * len(coercive))
        issues.append({"code": "agency_restricted", "message": "叙事无必要地限制了自由探索"})

    cleanliness = 100
    if INTERNAL_ID_PATTERN.search(content):
        cleanliness -= 55
        issues.append({"code": "internal_id", "message": "向玩家泄漏了内部内容编号"})
    lower = content.lower()
    if any(pattern in lower for pattern in SYSTEM_LEAK_PATTERNS):
        cleanliness -= 60
        issues.append({"code": "system_leak", "message": "向玩家泄漏了提示词或响应契约字段"})
    if "```" in content or content.startswith("{"):
        cleanliness -= 25
        issues.append({"code": "format_leak", "message": "叙事包含代码块或原始结构化响应"})

    dimensions = {
        "readability": max(0, readability),
        "persona": max(0, persona),
        "continuity": max(0, continuity),
        "agency": max(0, agency),
        "cleanliness": max(0, cleanliness),
    }
    score = round(sum(dimensions.values()) / len(dimensions), 1)
    blocking = {"internal_id", "system_leak"}
    return {
        "score": score,
        "passed": score >= 75 and not any(item["code"] in blocking for item in issues),
        "dimensions": dimensions,
        "issues": issues,
    }


def build_rated_samples(character: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
    """Build a local, bounded dataset from explicit player ratings."""
    history = character.get("conversation_history", []) or []
    samples = []
    for index, message in enumerate(history):
        rating = message.get("rating") if isinstance(message, dict) else None
        if rating not in ("up", "down"):
            continue
        context = [
            {
                "speaker": str(item.get("speaker") or ""),
                "content": str(item.get("content") or "")[:1200],
            }
            for item in history[max(0, index - 4):index]
            if isinstance(item, dict)
        ]
        content = str(message.get("content") or "")[:4000]
        samples.append({
            "sample_id": str(message.get("message_id") or f"history-{index}"),
            "rating": rating,
            "speaker": str(message.get("speaker") or ""),
            "scene": str(message.get("scene") or ""),
            "content": content,
            "context": context,
            "model": message.get("model")
            or character.get("model_runtime", {}).get("used_model"),
            "rated_at": message.get("rated_at"),
            "automatic_evaluation": evaluate_narrative_text(
                content,
                recent_responses=[item["content"] for item in context],
            ),
        })
    safe_limit = max(1, min(500, int(limit or 100)))
    return samples[-safe_limit:]


def summarize_rated_samples(character: Dict[str, Any]) -> Dict[str, Any]:
    samples = build_rated_samples(character, limit=500)
    issue_counts = Counter(
        issue["code"]
        for sample in samples
        for issue in sample["automatic_evaluation"].get("issues", [])
    )
    return {
        "rated_messages": len(samples),
        "positive": sum(1 for item in samples if item["rating"] == "up"),
        "negative": sum(1 for item in samples if item["rating"] == "down"),
        "average_automatic_score": round(
            sum(item["automatic_evaluation"]["score"] for item in samples)
            / len(samples),
            1,
        )
        if samples
        else None,
        "common_issues": [
            {"code": code, "count": count}
            for code, count in issue_counts.most_common(8)
        ],
    }


def run_narrative_evaluation(path: Path = None) -> Dict[str, Any]:
    source = Path(path or DEFAULT_CASES_PATH)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    results = []
    for case in payload.get("cases", []):
        evaluation = evaluate_narrative_text(
            case.get("response", ""),
            expected_terms=case.get("expected_terms"),
            forbidden_terms=case.get("forbidden_terms"),
            required_facts=case.get("required_facts"),
            recent_responses=case.get("recent_responses"),
        )
        minimum_value = case.get("minimum_score")
        minimum = float(minimum_value) if minimum_value is not None else None
        maximum = case.get("maximum_score")
        passed = minimum is None or evaluation["score"] >= minimum
        if maximum is not None:
            passed = passed and evaluation["score"] <= float(maximum)
        if case.get("expected_pass") is not None:
            passed = passed and evaluation["passed"] is bool(case["expected_pass"])
        issue_codes = {item["code"] for item in evaluation.get("issues", [])}
        passed = passed and all(
            str(code) in issue_codes
            for code in case.get("required_issue_codes", [])
        )
        results.append({
            "id": str(case.get("id") or "unnamed"),
            "title": str(case.get("title") or case.get("id") or "未命名"),
            "passed": passed,
            "minimum_score": minimum,
            "maximum_score": maximum,
            "evaluation": evaluation,
        })
    return {
        "source": str(source),
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "results": results,
    }
