"""可解释的选题混合评分：LLM 评内容价值，代码评来源、证据与新鲜度。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from config import BASE_DIR
from services.llm import LLMError, chat_json, get_profile_context, render_prompt

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "topic_score.md"
SCORE_VERSION = "hybrid-v2"
_prompt_cache: str | None = None
_prompt_mtime: float = 0

QUALITATIVE_DIMENSIONS = (
    "audience_value",
    "actionability",
    "hook_tension",
    "clarity",
    "platform_fit",
    "persona_fit",
)
DETERMINISTIC_DIMENSIONS = ("evidence_strength", "source_authority", "freshness")

# 每套权重总和均为 100。栏目不同，选题价值的定义也不同。
WEIGHT_PROFILES: dict[str, dict[str, int]] = {
    "AI效率快报": {
        "audience_value": 15, "actionability": 15, "hook_tension": 15,
        "clarity": 5, "platform_fit": 10, "persona_fit": 5,
        "evidence_strength": 10, "source_authority": 10, "freshness": 15,
    },
    "一人工作流": {
        "audience_value": 20, "actionability": 25, "hook_tension": 10,
        "clarity": 10, "platform_fit": 5, "persona_fit": 5,
        "evidence_strength": 12, "source_authority": 8, "freshness": 5,
    },
    "Agent实战课": {
        "audience_value": 20, "actionability": 25, "hook_tension": 10,
        "clarity": 10, "platform_fit": 5, "persona_fit": 5,
        "evidence_strength": 15, "source_authority": 7, "freshness": 3,
    },
    "避坑诊断室": {
        "audience_value": 20, "actionability": 20, "hook_tension": 20,
        "clarity": 10, "platform_fit": 5, "persona_fit": 5,
        "evidence_strength": 10, "source_authority": 7, "freshness": 3,
    },
    "前沿变白话": {
        "audience_value": 20, "actionability": 10, "hook_tension": 10,
        "clarity": 20, "platform_fit": 5, "persona_fit": 5,
        "evidence_strength": 15, "source_authority": 10, "freshness": 5,
    },
}
DEFAULT_WEIGHTS = {
    "audience_value": 20, "actionability": 20, "hook_tension": 10,
    "clarity": 10, "platform_fit": 5, "persona_fit": 5,
    "evidence_strength": 15, "source_authority": 10, "freshness": 5,
}

LEVEL_RATINGS = {"S": 5.0, "A": 4.0, "B": 3.0, "C": 2.0, "U": 1.0}
RISK_PENALTIES = {0: 0, 1: 3, 2: 8, 3: 15}
VALID_PLATFORMS = {"douyin", "xiaohongshu"}
VALID_CATEGORIES = set(WEIGHT_PROFILES)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class QualitativeRatings(BaseModel):
    audience_value: float = Field(ge=0, le=5)
    actionability: float = Field(ge=0, le=5)
    hook_tension: float = Field(ge=0, le=5)
    clarity: float = Field(ge=0, le=5)
    platform_fit: float = Field(ge=0, le=5)
    persona_fit: float = Field(ge=0, le=5)


class QualitativeAssessment(BaseModel):
    ratings: QualitativeRatings
    risk_level: int = Field(ge=0, le=3)
    reason: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class ScoreResult:
    score: int
    breakdown: dict[str, Any]
    method: str
    version: str
    confidence: str
    stage: str


def _load_prompt() -> str:
    global _prompt_cache, _prompt_mtime
    mtime = PROMPT_PATH.stat().st_mtime
    if _prompt_cache is None or mtime > _prompt_mtime:
        _prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
        _prompt_mtime = mtime
    return _prompt_cache


def score_topic(
    article: dict,
    card: dict,
    *,
    stage: str = "provisional",
    sources: list[dict] | None = None,
) -> ScoreResult:
    """计算可解释的混合分数。LLM 失败时使用保守规则，不再给字段齐全的内容自动高分。"""
    try:
        assessment = _llm_assessment(article, card)
        method = "hybrid_llm"
    except LLMError as exc:
        logger.warning("LLM 定性评分失败，使用保守规则：%s", exc)
        assessment = _fallback_assessment(card)
        method = "hybrid_rule"
    return _compose_score(
        article=article,
        card=card,
        assessment=assessment,
        method=method,
        stage=stage,
        sources=sources or [],
    )


def _llm_assessment(article: dict, card: dict) -> QualitativeAssessment:
    prompt = render_prompt(
        _load_prompt(),
        current_date=datetime.now(timezone.utc).date().isoformat(),
        profile=get_profile_context(),
        title=card.get("title") or "",
        one_line_takeaway=card.get("one_line_takeaway") or "",
        summary=card.get("summary") or "",
        category=card.get("category") or card.get("recommended_column") or "未分类",
        audience=_format_audience(card.get("audience")),
        recommended_platform=card.get("recommended_platform") or "未指定",
        recommended_duration=card.get("recommended_duration") or "未指定",
        actionable_value=card.get("actionable_value") or "",
        risk_notes=_format_risk_notes(card.get("risk_notes")),
        source_level=article.get("source_level") or "U",
        published_at=_format_published(article.get("published_at")),
        facts=_format_facts(_facts_from_card(card)),
        research_context=_format_research_context(card),
    )
    try:
        data = chat_json([
            {
                "role": "system",
                "content": (
                    "你负责评估短视频选题。必须按锚点独立打分，不计算总分，"
                    "不要因为文本完整或篇幅长而给高分。"
                ),
            },
            {"role": "user", "content": prompt},
        ], temperature=0.0)
        return QualitativeAssessment.model_validate(data)
    except (ValidationError, TypeError, AttributeError) as exc:
        raise LLMError(f"定性评分输出结构不合格：{exc}") from exc


def _fallback_assessment(card: dict) -> QualitativeAssessment:
    """LLM 不可用时给保守的 0～3 分评价，避免兜底分数饱和。"""
    title = str(card.get("title") or "")
    summary = str(card.get("summary") or "")
    actionable = str(card.get("actionable_value") or "")
    takeaway = str(card.get("one_line_takeaway") or "")
    audience = card.get("audience") or []
    platform = card.get("recommended_platform") or ""
    category = card.get("category") or card.get("recommended_column") or ""
    risk_text = _format_risk_notes(card.get("risk_notes"))

    audience_rating = 3 if audience and takeaway else (2 if takeaway else 1)
    action_rating = 3 if len(actionable) >= 20 else (2 if actionable else 1)
    hook_rating = 3 if re.search(r"[？?]|\d|不是|却|总是|为什么", title) else 2
    clarity_rating = 3 if 60 <= len(summary) <= 220 else (2 if summary else 1)
    platform_rating = 3 if platform in VALID_PLATFORMS else 1
    persona_rating = 3 if category in VALID_CATEGORIES else 2
    severe_terms = ("无法核实", "证据不足", "存在争议", "严重", "高风险", "营销")
    risk_level = 2 if any(x in risk_text for x in severe_terms) else (1 if risk_text else 0)

    return QualitativeAssessment(
        ratings=QualitativeRatings(
            audience_value=audience_rating,
            actionability=action_rating,
            hook_tension=hook_rating,
            clarity=clarity_rating,
            platform_fit=platform_rating,
            persona_fit=persona_rating,
        ),
        risk_level=risk_level,
        reason="LLM 不可用，采用保守规则评分",
    )


def _compose_score(
    *,
    article: dict,
    card: dict,
    assessment: QualitativeAssessment,
    method: str,
    stage: str,
    sources: list[dict],
) -> ScoreResult:
    category = card.get("category") or card.get("recommended_column") or ""
    weights = WEIGHT_PROFILES.get(category, DEFAULT_WEIGHTS)
    ratings = assessment.ratings.model_dump()
    deterministic = {
        "evidence_strength": _evidence_rating(card, sources),
        "source_authority": _source_authority_rating(article, sources),
        "freshness": _freshness_rating(article, sources),
    }
    all_ratings = {**ratings, **deterministic}

    dimensions: dict[str, dict[str, float | int]] = {}
    subtotal = 0
    for name, weight in weights.items():
        rating = float(all_ratings[name])
        points = round(rating / 5 * weight)
        dimensions[name] = {"rating": rating, "points": points, "max": weight}
        subtotal += points

    risk_penalty = RISK_PENALTIES.get(assessment.risk_level, 15)
    total = max(0, min(100, subtotal - risk_penalty))
    evidence_rating = deterministic["evidence_strength"]
    confidence = _score_confidence(method, evidence_rating, sources)
    breakdown = {
        "dimensions": dimensions,
        "subtotal": subtotal,
        "risk_level": assessment.risk_level,
        "risk_penalty": risk_penalty,
        "reason": assessment.reason,
        "weight_profile": category or "default",
    }
    return ScoreResult(
        score=total,
        breakdown=breakdown,
        method=method,
        version=SCORE_VERSION,
        confidence=confidence,
        stage=stage,
    )


def _evidence_rating(card: dict, sources: list[dict]) -> float:
    facts = _facts_from_card(card)
    if not facts:
        return 0.0
    valid_fact_urls = {
        str(f.get("source_url") or "").strip()
        for f in facts
        if URL_RE.match(str(f.get("source_url") or "").strip())
    }
    source_urls = {
        str(s.get("source_url") or s.get("url") or "").strip()
        for s in sources
        if URL_RE.match(str(s.get("source_url") or s.get("url") or "").strip())
    }
    levels = {
        str(s.get("source_level") or "U").upper()
        for s in sources
    }
    rating = 1.0  # 至少有一条事实
    if len(valid_fact_urls) == len(facts):
        rating += 1.0
    if len(facts) >= 2:
        rating += 1.0
    if len(valid_fact_urls | source_urls) >= 2:
        rating += 1.0
    if levels & {"S", "A"}:
        rating += 1.0
    return min(5.0, rating)


def _source_authority_rating(article: dict, sources: list[dict]) -> float:
    levels = [
        str(s.get("source_level") or "U").upper()
        for s in sources
        if s.get("source_level")
    ]
    if not levels:
        levels = [str(article.get("source_level") or "U").upper()]
    return max(LEVEL_RATINGS.get(level, 1.0) for level in levels)


def _freshness_rating(article: dict, sources: list[dict]) -> float:
    values = [s.get("published_at") for s in sources if s.get("published_at")]
    if article.get("published_at"):
        values.append(article.get("published_at"))
    dates = [d for d in (_parse_datetime(v) for v in values) if d is not None]
    if not dates:
        return 1.0
    latest = max(dates)
    now = datetime.now(latest.tzinfo) if latest.tzinfo else datetime.now()
    days = max(0, (now - latest).days)
    if days <= 3:
        return 5.0
    if days <= 7:
        return 4.5
    if days <= 14:
        return 3.5
    if days <= 30:
        return 2.0
    return 0.5


def _score_confidence(method: str, evidence_rating: float, sources: list[dict]) -> str:
    if method != "hybrid_llm":
        return "low"
    if evidence_rating >= 4 and len(sources) >= 2:
        return "high"
    if evidence_rating >= 2:
        return "medium"
    return "low"


def rescore_topic(
    topic_id: int,
    *,
    research_card_id: int | None = None,
    stage: str | None = None,
) -> ScoreResult:
    """使用当前选题、关联来源和最新资料卡重算分数并写回数据库。"""
    from repositories.research_cards_repo import (
        get_card,
        get_latest_card_for_topic,
        get_sources_for_card,
    )
    from repositories.topics_repo import get_topic_with_facts_and_articles, update_score

    topic = get_topic_with_facts_and_articles(topic_id)
    if not topic:
        raise ValueError(f"topic {topic_id} 不存在")
    research_card = (
        get_card(research_card_id)
        if research_card_id
        else get_latest_card_for_topic(topic_id)
    )
    sources = (
        get_sources_for_card(research_card["id"])
        if research_card
        else [_article_as_source(a) for a in topic.get("articles", [])]
    )
    card = _topic_to_score_card(topic, research_card)
    article = _representative_article(topic, sources)
    result = score_topic(
        article,
        card,
        stage=stage or ("final" if research_card else "provisional"),
        sources=sources,
    )
    update_score(
        topic_id,
        result.score,
        breakdown=result.breakdown,
        method=result.method,
        version=result.version,
        confidence=result.confidence,
        stage=result.stage,
    )
    return result


def _topic_to_score_card(topic: dict, research_card: dict | None) -> dict:
    research = (research_card or {}).get("card") or {}
    core_facts = research.get("core_facts") or topic.get("facts") or []
    risk_notes = research.get("risk_notes") or topic.get("risk_notes") or ""
    return {
        "title": topic.get("title") or "",
        "one_line_takeaway": topic.get("one_line_takeaway") or "",
        "summary": topic.get("summary") or "",
        "category": topic.get("category") or topic.get("recommended_column") or "",
        "recommended_column": topic.get("recommended_column") or "",
        "audience": topic.get("audience_list") or [],
        "recommended_platform": topic.get("recommended_platform") or "",
        "recommended_duration": topic.get("recommended_duration") or "",
        "actionable_value": topic.get("actionable_value") or "",
        "risk_notes": risk_notes,
        "key_facts": core_facts,
        "research_summary": research.get("research_summary") or "",
        "audience_value": research.get("audience_value") or "",
        "workflow_example": research.get("workflow_example") or "",
        "talking_points": research.get("talking_points") or [],
    }


def _representative_article(topic: dict, sources: list[dict]) -> dict:
    best_level = str(topic.get("source_level") or "U").upper()
    best_rating = LEVEL_RATINGS.get(best_level, 1.0)
    latest = None
    for source in sources:
        level = str(source.get("source_level") or "U").upper()
        if LEVEL_RATINGS.get(level, 1.0) > best_rating:
            best_level = level
            best_rating = LEVEL_RATINGS[level]
        parsed = _parse_datetime(source.get("published_at"))
        if parsed is not None and (latest is None or parsed > latest):
            latest = parsed
    return {"source_level": best_level, "published_at": latest}


def _article_as_source(article: dict) -> dict:
    return {
        "source_level": article.get("source_level"),
        "published_at": article.get("published_at"),
        "source_url": article.get("url"),
    }


def _facts_from_card(card: dict) -> list[dict]:
    facts = card.get("key_facts") or card.get("core_facts") or []
    return [f for f in facts if isinstance(f, dict)]


def _format_facts(facts: list[dict]) -> str:
    if not facts:
        return "（无）"
    return "\n".join(
        f"- {f.get('claim', '')}（来源：{f.get('source_url', '缺失')}）"
        for f in facts
    )


def _format_audience(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(x) for x in value) or "未指定"
    return str(value or "未指定")


def _format_risk_notes(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(x) for x in value)
    return str(value or "")


def _format_research_context(card: dict) -> str:
    parts = []
    for key, label in (
        ("research_summary", "研究摘要"),
        ("audience_value", "观众价值"),
        ("workflow_example", "工作流"),
    ):
        if card.get(key):
            parts.append(f"{label}：{card[key]}")
    if card.get("talking_points"):
        parts.append("观点素材：" + "；".join(str(x) for x in card["talking_points"]))
    return "\n".join(parts) or "（无资料卡补充）"


def _format_published(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else "未知"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    # 数据库时间通常无时区，联网来源可能带时区；统一成 UTC 无时区，避免比较时报错。
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed
