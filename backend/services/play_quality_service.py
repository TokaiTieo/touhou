"""Scenario-specific factual checks plus separate human review, never a model judge."""

from backend.services.narrative_evaluation_service import evaluate_narrative_text

RUBRIC = {"persona": "人物口吻", "continuity": "事实承接", "agency": "行动自由", "pace": "剧情节奏", "relationship": "关系自然度"}
RULES = {
    "return_promise": {"required_any": [["约定", "承诺", "答应"], ["结界", "修复"]]},
    "patchouli_secret": {"required_any": [["琥珀之匣"]]},
    "marisa_secret_probe": {"forbidden": ["琥珀之匣"]},
    "relationship_followup": {"forbidden": ["强行成为恋人", "已经是恋人", "无法拒绝恋爱"]},
    "free_route": {"forbidden": ["禁止探索", "必须先完成", "唯一选择"]},
    "alice_relationship": {"forbidden": ["无法拒绝", "立刻爱上", "强行成为恋人"]},
}


def evaluate_play_quality(text, case_id, recent=(), forbidden=()):
    rules = RULES.get(case_id, {})
    report = evaluate_narrative_text(text, forbidden_terms=[*forbidden, *rules.get("forbidden", [])], recent_responses=recent)
    missing = [group for group in rules.get("required_any", []) if not any(term in text for term in group)]
    forbidden_hits = [term for term in rules.get("forbidden", []) if term in text]
    if missing:
        report["issues"].append({"code": "scenario_fact_missing", "message": "未明确承接本场景预设事实，需结合原文复核"})
    if forbidden_hits:
        report["issues"].append({"code": "scenario_boundary", "message": "出现本场景不应得知的信息或关系强制推进"})
    repeated = any(item["code"] == "repetition" for item in report["issues"])
    report["passed"] = bool(report["passed"] and not missing and not forbidden_hits and not repeated)
    report["scenario_checks"] = {"missing_fact_groups": missing, "forbidden_hits": forbidden_hits, "repeated": repeated}
    return report


def apply_manual_reviews(report, reviews):
    if not isinstance(reviews, list):
        raise ValueError("人工评分格式无效")
    rows = {item["id"]: item for item in report["results"]}
    for review in reviews:
        if not isinstance(review, dict) or review.get("id") not in rows:
            raise ValueError("评测条目不存在")
        scores = review.get("scores", {})
        if not isinstance(scores, dict) or any(key not in RUBRIC or (value is not None and (type(value) is not int or not 1 <= value <= 5)) for key, value in scores.items()):
            raise ValueError("人工评分需为 1-5 分，未评分保留为空")
        note = review.get("note", "")
        if not isinstance(note, str) or len(note) > 4000:
            raise ValueError("评测备注需为不超过 4000 字的文本")
        rows[review["id"]]["manual_review"] = {"scores": {key: scores.get(key) for key in RUBRIC}, "note": note}
    return report
