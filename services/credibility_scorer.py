"""来源可信度评分（V0.4）：给资料卡来源算 0-100 分。

评分维度：
- 来源等级（S/A/B/C/U）：40 分
- 来源类型（官方/框架/研究/中文传播/未识别）：25 分
- 时效性（14 天内/30 天内/更旧）：20 分
- 是否官方源（S/A 级）：15 分
"""
from __future__ import annotations

from datetime import datetime, timedelta

from services.source_classifier import is_official_source

LEVEL_SCORES = {"S": 40, "A": 32, "B": 22, "C": 12, "U": 8}
TYPE_SCORES = {"local": 15, "web": 20, "manual": 10}  # 联网源经过筛选，略高于本地

FRESH_DAYS = 14
RECENT_DAYS = 30


def score_source(*, source_level: str | None, source_type: str = "local",
                 published_at: str | None, url: str = "") -> int:
    """给单个来源打可信度分数（0-100）。"""
    level = (source_level or "U").upper()
    score = LEVEL_SCORES.get(level, 8)

    # 来源类型分
    score += TYPE_SCORES.get(source_type, 10)

    # 官方源加分
    if is_official_source(level):
        score += 15

    # 时效性
    score += _freshness_score(published_at)

    return max(0, min(100, score))


def _freshness_score(published_at: str | None) -> int:
    """时效性得分：14 天内 20，30 天内 12，更旧 5，无日期 8。"""
    if not published_at:
        return 8
    try:
        pub = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
        now = datetime.now(pub.tzinfo) if pub.tzinfo else datetime.now()
        days = (now - pub).days
        if days <= FRESH_DAYS:
            return 20
        if days <= RECENT_DAYS:
            return 12
        return 5
    except (ValueError, TypeError):
        return 8


def score_research_card(card: dict, sources: list[dict]) -> dict:
    """给整张资料卡算可信度摘要。

    返回 {avg_score, source_scores, has_conflict_risk, recommendation}
    """
    if not sources:
        return {"avg_score": 0, "source_scores": [], "has_conflict_risk": False,
                "recommendation": "无来源，无法评估可信度"}

    scored = []
    for s in sources:
        sc = score_source(
            source_level=s.get("source_level"),
            source_type=s.get("source_type", "local"),
            published_at=s.get("published_at"),
            url=s.get("source_url", ""),
        )
        scored.append({"source_id": s.get("id"), "url": s.get("source_url"),
                       "title": s.get("source_title"), "level": s.get("source_level"),
                       "score": sc})

    avg = sum(s["score"] for s in scored) // len(scored)
    has_official = any(s["level"] in ("S", "A") for s in scored)

    # 推荐建议
    if avg >= 70 and has_official:
        rec = "可信度较高，可放心引用"
    elif avg >= 50:
        rec = "可信度中等，建议核对关键事实"
    else:
        rec = "可信度较低，建议补充官方源后再生成本脚本"

    return {
        "avg_score": avg,
        "source_scores": scored,
        "has_official_source": has_official,
        "recommendation": rec,
    }
