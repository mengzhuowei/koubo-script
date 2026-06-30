"""选题评分：优先调用 LLM 评分，失败时退化为规则评分。"""
from __future__ import annotations

import logging

from config import BASE_DIR
from services.llm import LLMError, chat_json, get_profile_context, render_prompt

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "topic_score.md"
_prompt_cache: str | None = None


def _load_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        _prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_cache


def score_topic(article: dict, card: dict) -> int:
    """对内容卡打分，返回 0-100。LLM 失败时退化为规则评分。"""
    try:
        return _llm_score(article, card)
    except LLMError as e:
        logger.warning("LLM 评分失败，退化规则评分：%s", e)
        return _rule_score(article, card)


def _llm_score(article: dict, card: dict) -> int:
    template = _load_prompt()
    facts_count = len(card.get("key_facts") or [])
    prompt = render_prompt(
        template,
        profile=get_profile_context(),
        title=card.get("title") or "",
        summary=card.get("summary") or "",
        source_level=article.get("source_level") or "-",
        actionable_value=card.get("actionable_value") or "",
        risk_notes=card.get("risk_notes") or "",
        facts_count=facts_count,
    )
    data = chat_json([{"role": "user", "content": prompt}])
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        score = _rule_score(article, card)
    return max(0, min(100, score))


def _rule_score(article: dict, card: dict) -> int:
    """可解释规则评分，作为 LLM 不可用时的兜底。"""
    score = 0
    level = (article.get("source_level") or "B").upper()
    score += {"S": 20, "A": 17, "B": 12, "C": 8}.get(level, 10)  # 来源权威度

    summary = card.get("summary") or ""
    score += 18 if len(summary) >= 60 else 10  # 实操/信息量近似

    actionable = card.get("actionable_value") or ""
    score += 18 if len(actionable) >= 15 else 8  # 实操价值

    facts = card.get("key_facts") or []
    score += 15 if facts else 5  # 关键事实/可理解度

    risk = card.get("risk_notes") or ""
    score += 8 if risk else 3  # 反差/争议

    platform = card.get("recommended_platform") or ""
    score += 8 if platform in ("douyin", "xiaohongshu") else 4  # 平台适配

    score += 5  # 人设匹配（默认给满，规则难判定）
    return max(0, min(100, score))
