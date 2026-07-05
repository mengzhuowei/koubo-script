"""选题生成：对未处理文章生成内容卡，入库 topics / topic_facts / topic_articles，并评分。"""
from __future__ import annotations

import logging
import re

from config import BASE_DIR
from repositories.articles_repo import list_unprocessed_articles, mark_processed, update_article_summary
from repositories.topics_repo import (
    add_topic_fact, create_topic, link_article, list_recent_topic_titles, update_score,
)
from services.llm import LLMError, chat_json, get_profile_context, render_prompt
from services.scorer import score_topic
from services.summarizer import summarize_article

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "content_card.md"
_prompt_cache: str | None = None

# 选题去重：近 7 天标题 Jaccard 相似度阈值，超过则合并到已有选题而非新建。
# 用轻量字符 2-gram 集合近似中文相似度，避免额外 LLM 消耗。
DEDUP_WINDOW_DAYS = 7
DEDUP_THRESHOLD = 0.6


def _tokenize(text: str) -> set[str]:
    """简单分词：提取连续的汉字/字母数字块，再生成 2-gram 提升中文相似度判定。"""
    if not text:
        return set()
    tokens: set[str] = set()
    for block in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]+", text.lower()):
        if len(block) >= 2:
            for i in range(len(block) - 1):
                tokens.add(block[i:i + 2])
        tokens.add(block)
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _find_similar_topic(title: str, recent: list[dict]) -> int | None:
    """返回与 title 相似度达标的近期选题 id，无则 None。"""
    tset = _tokenize(title)
    if not tset:
        return None
    for r in recent:
        if _jaccard(tset, _tokenize(r.get("title") or "")) >= DEDUP_THRESHOLD:
            return r["id"]
    return None


# ---------- prompt 加载（支持热更新）----------
_prompt_cache: str | None = None
_prompt_mtime: float = 0


def _load_prompt() -> str:
    global _prompt_cache, _prompt_mtime
    mtime = PROMPT_PATH.stat().st_mtime
    if _prompt_cache is None or mtime > _prompt_mtime:
        _prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
        _prompt_mtime = mtime
    return _prompt_cache


def generate_topics_from_unprocessed(limit: int = 20) -> int:
    """对未生成选题的新文章逐篇生成内容卡。返回生成的选题数。

    若有待处理文章但全部失败，抛出最后一个异常让 job 标记 failed，
    避免静默返回 0 误导用户。单篇失败仍允许 continue 以最大化产出。
    """
    # 清理上次崩溃留下的傀儡 processing 文章（超时 > 10 分钟的先恢复为 new）
    from repositories.articles_repo import reset_stale_processing
    stale = reset_stale_processing()
    if stale:
        logger.info("清理了 %d 篇僵尸 processing 文章（恢复为 new）", stale)

    articles = list_unprocessed_articles(limit=limit)
    if not articles:
        logger.info("没有待生成选题的新文章")
        return 0

    template = _load_prompt()
    profile = get_profile_context()
    # 一次性加载近 7 天选题标题用于去重；批内新建/合并的选题增量加入，避免同批次重复
    recent_titles: list[dict] = list_recent_topic_titles(days=DEDUP_WINDOW_DAYS)
    count = 0
    deduped = 0
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
            topic_id, is_new = _persist_card(article, card, recent_titles)
            if is_new:
                count += 1
                logger.info("生成选题 topic_id=%s 来自 article_id=%s", topic_id, article["id"])
            else:
                deduped += 1
                logger.info("文章 %s 选题与已有 topic_id=%s 相似（Jaccard≥%s），合并去重",
                            article["id"], topic_id, DEDUP_THRESHOLD)
        except Exception as e:
            failures += 1
            last_error = e
            logger.warning("文章 %s 生成内容卡失败：%s", article["id"], e, exc_info=not isinstance(e, LLMError))
            # 失败时恢复为 new，便于下次重试
            from repositories.articles_repo import revert_to_new
            revert_to_new(article["id"])
            continue

    if count == 0 and failures > 0 and last_error is not None:
        raise last_error
    logger.info("本轮选题生成：新增 %d，去重合并 %d，失败 %d", count, deduped, failures)
    return count


def regenerate_topic_for_article(article_id: int) -> int:
    """针对单篇文章重新生成选题，覆盖旧选题内容。返回新 topic_id。

    流程：
    1. 解除该文章与所有旧 topic 的 topic_articles 关联；
    2. 删除其中无脚本、且无其他文章关联的孤立旧 topic（含 facts）；
       有脚本的旧 topic 保留，避免误删用户已写的脚本；
    3. 重置文章为 new 并清空旧摘要（让 summarizer 用新正文重新跑）；
    4. 针对单篇文章重新生成内容卡并落库。

    与批量 generate_topics_from_unprocessed 不同，本函数只处理这一篇，
    便于人工补充正文后定点重生成，不影响其他待处理文章。
    """
    from repositories.articles_repo import get_article, reset_to_new, update_article_summary
    from repositories.topics_repo import (
        list_topic_ids_for_article, unlink_article_from_topics,
        delete_topic, count_articles_for_topic,
    )
    from repositories.scripts_repo import count_scripts_for_topic

    article = get_article(article_id)
    if not article:
        raise ValueError(f"article {article_id} 不存在")

    # 1. 解除旧关联
    old_topic_ids = list_topic_ids_for_article(article_id)
    if old_topic_ids:
        unlink_article_from_topics(article_id)
        deleted = 0
        kept = 0
        for tid in old_topic_ids:
            # 有脚本或仍有其他文章关联的旧 topic 保留
            if count_scripts_for_topic(tid) > 0 or count_articles_for_topic(tid) > 0:
                kept += 1
            else:
                delete_topic(tid)
                deleted += 1
        logger.info("文章 %s 旧选题：删除孤立 %d 个，保留 %d 个（有脚本或仍有其他文章关联）",
                    article_id, deleted, kept)

    # 2. 重置文章状态，清空旧摘要让 summarizer 用新正文重新跑
    reset_to_new(article_id)
    article = get_article(article_id)  # 取重置后的最新数据

    # 3. 重新生成
    template = _load_prompt()
    profile = get_profile_context()
    recent_titles: list[dict] = list_recent_topic_titles(days=DEDUP_WINDOW_DAYS)

    if not article.get("summary"):
        summary, key_points = summarize_article(article)
        update_article_summary(article_id, summary=summary, key_points=key_points)
        article["summary"] = summary
        article["key_points"] = key_points

    card = _generate_card(article, template, profile)
    topic_id, is_new = _persist_card(article, card, recent_titles)
    logger.info("文章 %s 重新生成选题 topic_id=%s (新建=%s)", article_id, topic_id, is_new)
    return topic_id


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


def _persist_card(article: dict, card: dict, recent_titles: list[dict]) -> tuple[int, bool]:
    """落库内容卡。返回 (topic_id, is_new)。

    若标题与近 7 天已有选题高度相似，则合并：关联文章到已有选题并标记 processed，
    不新建选题，避免同一事件多篇文章产生重复选题。
    """
    title = card.get("title") or article.get("title") or "未命名选题"

    dup_id = _find_similar_topic(title, recent_titles)
    if dup_id:
        link_article(dup_id, article["id"])
        mark_processed(article["id"])
        return dup_id, False

    audience = card.get("audience") or []
    if isinstance(audience, str):
        audience = [audience]
    score = score_topic(article, card)

    topic_id = create_topic(
        title=title,
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
    # 增量加入去重池，捕获同批次内重复
    recent_titles.append({"id": topic_id, "title": title})
    # 新建选题后自动入队资料卡生成，无需用户进选题页再触发
    _enqueue_research_card(topic_id)
    return topic_id, True


def _enqueue_research_card(topic_id: int) -> None:
    """新建选题后入队资料卡生成任务。已有 pending/running 任务时跳过避免重复。"""
    from repositories.jobs_repo import enqueue
    from repositories.research_cards_repo import has_active_research_job
    if has_active_research_job(topic_id):
        return
    enqueue("generate_research_card", {"topic_id": topic_id})


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
