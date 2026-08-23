"""Offline hybrid vector retrieval for NPC long-term memories."""

import math
import os
import re
from collections import Counter
from datetime import datetime
from typing import Dict, List


CONCEPT_GROUPS = {
    "promise": ("承诺", "约定", "保证", "答应", "誓言"),
    "trust": ("信任", "相信", "依赖", "托付", "可靠"),
    "romance": ("喜欢", "爱", "恋爱", "热恋", "暧昧", "亲密", "约会"),
    "conflict": ("敌对", "仇恨", "威胁", "攻击", "背叛", "冲突", "争吵"),
    "battle": ("战斗", "符卡", "弹幕", "挑战", "决斗", "退治", "胜利", "失败"),
    "rescue": ("救助", "拯救", "帮助", "保护", "治疗", "援助"),
    "secret": ("秘密", "隐瞒", "羞耻", "真相", "私密"),
    "gift": ("赠送", "礼物", "馈赠", "归还", "交换"),
    "incident": ("异变", "结界", "裂隙", "调查", "线索", "任务"),
}

_DENSE_PROVIDER = None
_DENSE_PROVIDER_CHECKED = False
_DENSE_STATUS = {"backend": "local_ngram", "model": None, "reason": "not_configured"}


def configure_dense_provider(provider=None, model_name: str = "test-provider"):
    """Inject a provider in tests or reset lazy discovery with provider=None."""
    global _DENSE_PROVIDER, _DENSE_PROVIDER_CHECKED, _DENSE_STATUS
    _DENSE_PROVIDER = provider
    _DENSE_PROVIDER_CHECKED = provider is not None
    _DENSE_STATUS = {
        "backend": "sentence_transformer" if provider is not None else "local_ngram",
        "model": model_name if provider is not None else None,
        "reason": "injected" if provider is not None else "reset",
    }


def _dense_provider():
    global _DENSE_PROVIDER, _DENSE_PROVIDER_CHECKED, _DENSE_STATUS
    if _DENSE_PROVIDER_CHECKED:
        return _DENSE_PROVIDER
    _DENSE_PROVIDER_CHECKED = True
    model_name = os.environ.get("TOUHOU_EMBEDDING_MODEL", "").strip()
    if not model_name:
        _DENSE_STATUS = {"backend": "local_ngram", "model": None, "reason": "not_configured"}
        return None
    allow_download = os.environ.get("TOUHOU_ALLOW_MODEL_DOWNLOAD", "").lower() in ("1", "true", "yes")
    if not allow_download and not os.path.exists(model_name):
        _DENSE_STATUS = {"backend": "local_ngram", "model": model_name, "reason": "local_model_missing"}
        return None
    try:
        from sentence_transformers import SentenceTransformer
        kwargs = {} if allow_download else {"local_files_only": True}
        _DENSE_PROVIDER = SentenceTransformer(model_name, **kwargs)
        _DENSE_STATUS = {"backend": "sentence_transformer", "model": model_name, "reason": "ready"}
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        _DENSE_PROVIDER = None
        _DENSE_STATUS = {
            "backend": "local_ngram",
            "model": model_name,
            "reason": f"fallback:{type(exc).__name__}",
        }
    return _DENSE_PROVIDER


def semantic_backend_status() -> Dict:
    _dense_provider()
    return dict(_DENSE_STATUS)


def _dense_vectors(texts: List[str]):
    provider = _dense_provider()
    if provider is None:
        return None
    try:
        encoded = provider.encode(texts, normalize_embeddings=True)
        return [
            [float(value) for value in (row.tolist() if hasattr(row, "tolist") else row)]
            for row in encoded
        ]
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _dense_cosine(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def local_embedding(text: str) -> Dict[str, float]:
    """Create a sparse local embedding using Chinese n-grams and concept expansion."""
    normalized = _normalize(text)
    features = Counter()
    for size, weight in ((1, 0.25), (2, 1.0), (3, 0.7)):
        for index in range(max(0, len(normalized) - size + 1)):
            features[f"g{size}:{normalized[index:index + size]}"] += weight
    for concept, words in CONCEPT_GROUPS.items():
        hits = sum(1 for word in words if word in normalized)
        if hits:
            features[f"concept:{concept}"] += 2.5 + hits
    norm = math.sqrt(sum(value * value for value in features.values())) or 1.0
    return {key: value / norm for key, value in features.items()}


def cosine_similarity(left: Dict[str, float], right: Dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def _keyword_overlap(text: str, query: str) -> float:
    query_tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", str(query or "")))
    return sum(min(len(token), 6) for token in query_tokens if token in str(text or ""))


def _recency_score(item: Dict) -> float:
    raw = item.get("created_at")
    if not raw:
        return 0.0
    try:
        timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
        age_days = max(0.0, (now - timestamp).total_seconds() / 86400)
        return max(0.0, 3.0 - age_days / 30.0)
    except (TypeError, ValueError):
        return 0.0


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def rank_memories(
    items: List[Dict],
    query: str,
    limit: int = 8,
    semantic_index: Dict = None,
    index_meta: Dict = None,
    diagnostics: List[Dict] = None,
) -> List[Dict]:
    """Hybrid rank with relevance, importance, use history, recency and diversity."""
    if not items:
        return []
    query_vector = local_embedding(query)
    dense_query = None
    semantic_index = semantic_index if isinstance(semantic_index, dict) else {}
    valid_keys = {
        str(item.get("id") or hashlib_key(str(item.get("summary") or "")))
        for item in items
    }
    for key in list(semantic_index):
        if key not in valid_keys:
            semantic_index.pop(key, None)
    if query and _dense_provider() is not None:
        missing = []
        missing_keys = []
        for item in items:
            key = str(item.get("id") or hashlib_key(str(item.get("summary") or "")))
            if not isinstance(semantic_index.get(key), list):
                missing.append(str(item.get("summary") or ""))
                missing_keys.append(key)
        vectors = _dense_vectors([query] + missing)
        if vectors:
            dense_query = vectors[0]
            for key, vector in zip(missing_keys, vectors[1:]):
                semantic_index[key] = vector
            if isinstance(index_meta, dict):
                index_meta.update({
                    **semantic_backend_status(),
                    "vector_count": len(semantic_index),
                    "dimensions": len(dense_query),
                    "updated_at": datetime.now().isoformat(),
                })
    if dense_query is None and isinstance(index_meta, dict):
        index_meta.update({**semantic_backend_status(), "vector_count": len(semantic_index)})
    scored = []
    for index, item in enumerate(items):
        summary = str(item.get("summary") or "")
        vector_score = cosine_similarity(query_vector, local_embedding(summary)) if query else 0.0
        key = str(item.get("id") or hashlib_key(summary))
        dense_score = _dense_cosine(dense_query, semantic_index.get(key, [])) if dense_query else 0.0
        keyword_score = _keyword_overlap(summary, query)
        importance = max(1.0, min(10.0, _number(item.get("importance"), 5)))
        used_count = min(10.0, _number(item.get("used_count"), 0))
        confidence = max(0.0, min(1.0, _number(item.get("confidence"), 0.85)))
        truth_adjustment = {"accepted": 1.5, "disputed": -2.0, "superseded": -8.0}.get(
            str(item.get("truth_status") or "accepted"), 0.0
        )
        score = (
            vector_score * 24
            + dense_score * 18
            + keyword_score * 3.5
            + importance * 1.6
            + used_count * 0.35
            + _recency_score(item)
            + confidence * 2.0
            + truth_adjustment
        )
        if not query:
            score += index / max(len(items), 1) * 4
        reasons = []
        if keyword_score > 0:
            reasons.append("关键词")
        if vector_score > 0.08:
            reasons.append("本地语义")
        if dense_score > 0.08:
            reasons.append("向量语义")
        if importance >= 8:
            reasons.append("高重要度")
        if _recency_score(item) >= 2:
            reasons.append("近期")
        scored.append({
            "item": item,
            "score": score,
            "embedding": local_embedding(summary),
            "reasons": reasons or ["基础相关度"],
            "memory_id": key,
        })

    selected = []
    while scored and len(selected) < limit:
        best = max(
            scored,
            key=lambda entry: entry["score"] - max(
                [cosine_similarity(entry["embedding"], chosen["embedding"]) * 5 for chosen in selected] or [0]
            )
        )
        selected.append(best)
        scored.remove(best)
    if diagnostics is not None:
        diagnostics.extend({
            "memory_id": entry["memory_id"],
            "score": round(entry["score"], 3),
            "reasons": entry["reasons"],
            "chars": len(str(entry["item"].get("summary") or "")),
        } for entry in selected)
    return [entry["item"] for entry in selected]


def hashlib_key(text: str) -> str:
    import hashlib
    return "summary_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
