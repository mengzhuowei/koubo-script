"""选题评分：优先调用 LLM 评分，失败时退化为规则评分。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

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
        published_at=_format_published(article.get("published_at")),
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


def _format_published(val) -> str:
    """把 published_at 格式化为 LLM 易读的日期字符串。无值返回 '未知'。"""
    if not val:
        return "未知"
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if not s:
        return "未知"
    # 截取日期部分即可，去掉时分秒
    return s[:10] if len(s) >= 10 else s


def _freshness_penalty(published_at) -> int:
    """按发布时间计算新鲜度扣分（规则评分用）。

    发布 7 天内不扣分，之后每 7 天扣 2 分，最多扣 10 分；缺日期扣 6 分。
    """
    if not published_at:
        return 6
    try:
        if isinstance(published_at, datetime):
            pub = published_at
        else:
            s = str(published_at).strip()[:19]
            pub = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        days_old = (datetime.now() - pub).days
    except (ValueError, TypeError):
        return 6
    if days_old <= 7:
        return 0
    return min(10, (days_old - 7) // 7 * 2)


def _rule_score(article: dict, card: dict) -> int:
    """可解释规则评分，作为 LLM 不可用时的兜底。

    维度对齐 prompt 但权重略压缩，避免满分溢出 100 导致新鲜度差异被截断：
    来源 20 + 新鲜度 20 + 摘要 12 + 实操 12 + 关键事实 15 + 反差 8 + 平台 8 + 人设 5 = 100。
    """
    score = 0
    level = (article.get("source_level") or "B").upper()
    score += {"S": 20, "A": 17, "B": 12, "C": 8}.get(level, 10)  # 来源权威度

    # 新鲜度 20 分：7 天内满分，之后每 7 天扣 2 分，最少 10 分；缺日期给 14 分
    score += max(10, 20 - _freshness_penalty(article.get("published_at")))

    summary = card.get("summary") or ""
    score += 12 if len(summary) >= 60 else 6  # 实操/信息量近似

    actionable = card.get("actionable_value") or ""
    score += 12 if len(actionable) >= 15 else 5  # 实操价值

    facts = card.get("key_facts") or []
    score += 15 if facts else 5  # 关键事实/可理解度

    risk = card.get("risk_notes") or ""
    score += 8 if risk else 3  # 反差/争议

    platform = card.get("recommended_platform") or ""
    score += 8 if platform in ("douyin", "xiaohongshu") else 4  # 平台适配

    score += 5  # 人设匹配（默认给满，规则难判定）
    return max(0, min(100, score))
