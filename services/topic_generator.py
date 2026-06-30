"""选题生成：对未处理文章生成内容卡，入库 topics / topic_facts / topic_articles，并评分。"""
from __future__ import annotations

import logging

from config import BASE_DIR
from repositories.articles_repo import list_unprocessed_articles, mark_processed, update_article_summary
from repositories.topics_repo import (
    add_topic_fact, create_topic, link_article, update_score,
)
from services.llm import LLMError, chat_json, get_profile_context, render_prompt
from services.scorer import score_topic
from services.summarizer import summarize_article

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "content_card.md"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def generate_topics_from_unprocessed(limit: int = 20) -> int:
    """对未生成选题的新文章逐篇生成内容卡。返回生成的选题数。

    若有待处理文章但全部失败，抛出最后一个异常让 job 标记 failed，
    避免静默返回 0 误导用户。单篇失败仍允许 continue 以最大化产出。
    """
    articles = list_unprocessed_articles(limit=limit)
    if not articles:
        logger.info("没有待生成选题的新文章")
        return 0

    template = _load_prompt()
    profile = get_profile_context()
    count = 0
    failures = 0
    last_error: Exception | None = None
    for article in articles:
        try:
            # 先补摘要（若尚无）
            if not article.get("summary"):
                summary, key_points = summarize_article(article)
                update_article_summary(article["id"], summary=summary, key_points=key_points)
                article["summary"] = summary
                article["key_points"] = key_points

            card = _generate_card(article, template, profile)
            topic_id = _persist_card(article, card)
            count += 1
            logger.info("生成选题 topic_id=%s 来自 article_id=%s", topic_id, article["id"])
        except Exception as e:
            failures += 1
            last_error = e
            logger.warning("文章 %s 生成内容卡失败：%s", article["id"], e, exc_info=not isinstance(e, LLMError))
            continue

    if count == 0 and failures > 0 and last_error is not None:
        raise last_error
    return count


def _generate_card(article: dict, template: str, profile: str) -> dict:
    content = (article.get("summary") or article.get("content_text") or "")[:3000]
    prompt = render_prompt(
        template,
        profile=profile,
        title=article.get("title") or "",
        source_name=article.get("source_name") or "-",
        source_level=article.get("source_level") or "-",
        published_at=article.get("published_at") or "-",
        content=content,
        article_url=article.get("url") or "",
    )
    return chat_json([{"role": "user", "content": prompt}])


def _persist_card(article: dict, card: dict) -> int:
    audience = card.get("audience") or []
    if isinstance(audience, str):
        audience = [audience]
    score = score_topic(article, card)

    topic_id = create_topic(
        title=card.get("title") or article.get("title") or "未命名选题",
        one_line_takeaway=card.get("one_line_takeaway") or "",
        summary=card.get("summary") or "",
        category=card.get("category"),
        audience=[str(a) for a in audience],
        recommended_column=card.get("recommended_column"),
        recommended_platform=card.get("recommended_platform"),
        recommended_duration=_int_or_none(card.get("recommended_duration")),
        score=score,
        source_level=article.get("source_level"),
        actionable_value=card.get("actionable_value") or "",
        risk_notes=card.get("risk_notes") or "",
    )

    # 关键事实入库
    for f in (card.get("key_facts") or []):
        claim = (f.get("claim") or "").strip()
        source_url = (f.get("source_url") or article.get("url") or "").strip()
        if claim:
            add_topic_fact(topic_id, claim, source_url)

    # 关联来源文章
    link_article(topic_id, article["id"])
    # topic 生成成功后才标记文章为 processed，避免中途失败导致文章永远无法重试
    mark_processed(article["id"])
    return topic_id


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
