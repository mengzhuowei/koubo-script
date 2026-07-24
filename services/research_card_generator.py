"""选题资料卡生成：本地文章库检索 + 联网搜索补充 + LLM 整理资料卡。

V0.2.1 本地资料卡 + V0.3 联网搜索补充。
- 先本地检索，判断资料充分性；
- 不足且允许联网时，执行 Tavily 搜索补充；
- 合并本地+联网资料，调 LLM 生成资料卡。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from config import BASE_DIR, settings
from repositories.articles_repo import search_articles
from repositories.research_cards_repo import add_research_source, create_research_card
from repositories.topics_repo import get_topic_with_facts_and_articles
from services.llm import chat_json, get_profile_context, render_prompt
from services.source_classifier import classify_source
from services.web_search import (
    ExtractResult, SearchResult, WebSearchBudgetExceeded,
    WebSearchError, extract_for_topic, get_host, is_web_search_available, search_for_topic,
)

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "topic_research_card.md"
_prompt_cache: str | None = None

# 本地检索参数
LOCAL_SEARCH_LIMIT = 8
OFFICIAL_LEVELS = {"S", "A"}
FRESH_DAYS = 14
STALE_DAYS = 30
MIN_LOCAL_SOURCES = 3


def _load_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        _prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_cache

# 时间敏感词触发联网
TIME_SENSITIVE_KEYWORDS = ["最新", "发布", "升级", "刚刚", "新模型", "新功能", "更新", "上线", "推出"]
# 版本/价格/API 类选题触发联网
VERSION_PATTERN = re.compile(r"\b(v?\d+\.\d+|\d{4}年|GPT-\d|Claude-\d|API\b|价格|price|\$\d)", re.IGNORECASE)


def generate_research_card(topic_id: int) -> int:
    """为选题生成资料卡（本地 + 可选联网）。返回 research_card_id。"""
    topic = get_topic_with_facts_and_articles(topic_id)
    if not topic:
        raise ValueError(f"topic {topic_id} 不存在")

    title = topic.get("title") or ""

    # 1. 本地检索
    local_articles = _search_local(topic, title)

    # 2. 资料充分性判断
    sufficiency = assess_local_sufficiency(topic, local_articles)

    # 3. 联网补充（条件触发）
    web_results: list[dict] = []
    if sufficiency["needs_web"]:
        web_results = _search_web(topic_id, title, sufficiency["reason"])

    # 4. 拼接资料文本
    local_sources_text = _format_local_sources(local_articles)
    web_sources_text = _format_web_sources(web_results) if web_results else "（无联网补充资料）"

    # 5. 生成 prompt
    template = _load_prompt()
    facts_text = "\n".join(
        f"- {f['claim']}（来源：{f['source_url']}）" for f in topic.get("facts", [])
    ) or "（无）"

    prompt = render_prompt(
        template,
        profile=get_profile_context(),
        title=title,
        one_line_takeaway=topic.get("one_line_takeaway") or "",
        summary=topic.get("summary") or "",
        actionable_value=topic.get("actionable_value") or "",
        risk_notes=topic.get("risk_notes") or "",
        facts=facts_text,
        local_sources=local_sources_text + "\n\n## 联网搜索补充资料\n\n" + web_sources_text,
    )

    # 6. 调 LLM 生成资料卡
    card_data = chat_json([{"role": "user", "content": prompt}])

    # 7. 提取字段并落库
    sq = card_data.get("source_quality") or {}
    local_count = len(local_articles)
    web_count = len(web_results)
    has_official = any(
        (a.get("source_level") or "").upper() in OFFICIAL_LEVELS for a in local_articles
    ) or any(w.get("source_level") in OFFICIAL_LEVELS for w in web_results)
    confidence = _normalize_confidence(sq.get("overall_confidence"))

    card_id = create_research_card(
        topic_id=topic_id,
        title=card_data.get("research_title") or title,
        summary=card_data.get("research_summary") or "",
        card_json=card_data,
        confidence=confidence,
        local_source_count=local_count,
        web_source_count=web_count,
        has_official_source=has_official,
        generated_by="llm",
    )

    # 落库本地来源
    for a in local_articles:
        add_research_source(
            research_card_id=card_id,
            article_id=a["id"],
            source_url=a.get("url") or "",
            source_title=a.get("title") or "",
            source_name=a.get("source_name"),
            source_level=a.get("source_level"),
            published_at=a.get("published_at"),
            source_type="local",
            excerpt=(a.get("summary") or (a.get("content_text") or "")[:200]) or None,
        )

    # 落库联网来源
    for w in web_results:
        add_research_source(
            research_card_id=card_id,
            article_id=None,
            source_url=w["url"],
            source_title=w["title"],
            source_name=w["source_name"],
            source_level=w["source_level"],
            published_at=w.get("published_at"),
            source_type="web",
            excerpt=w.get("excerpt"),
        )

    logger.info("生成资料卡 card_id=%s topic_id=%s 本地 %d 联网 %d confidence=%s",
                card_id, topic_id, local_count, web_count, confidence)
    try:
        # 资料卡完成后，使用更完整的证据与来源把初评升级为终评。
        from services.scorer import rescore_topic
        rescore_topic(topic_id, research_card_id=card_id, stage="final")
    except Exception:
        # 资料卡已落库；评分异常不应让任务失败并重复生成资料卡。
        logger.warning(
            "资料卡完成后重评分失败 topic_id=%s card_id=%s",
            topic_id,
            card_id,
            exc_info=True,
        )
    return card_id


def _search_local(topic: dict, title: str) -> list[dict]:
    """本地 FULLTEXT 检索，去掉已关联文章，按等级+时间排序。"""
    if not title:
        return []
    local_articles = search_articles(q=title, limit=LOCAL_SEARCH_LIMIT)
    linked_ids = {a["id"] for a in topic.get("articles", [])}
    local_articles = [a for a in local_articles if a["id"] not in linked_ids]

    # 稳定排序：先按时间降序，再按等级降序
    local_articles.sort(
        key=lambda a: a.get("published_at") or a.get("fetched_at") or "",
        reverse=True,
    )
    local_articles.sort(
        key=lambda a: {"S": 4, "A": 3, "B": 2, "C": 1}.get((a.get("source_level") or "C").upper(), 0),
        reverse=True,
    )
    return local_articles


def assess_local_sufficiency(topic: dict, local_articles: list[dict]) -> dict:
    """判断本地资料是否充分。返回 {sufficient, needs_web, reason}。

    充分条件（PRD §6.1）：≥3 篇 + 至少 1 篇 S/A 级或 2 篇 B 级 + 14 天内有 1 篇 + 覆盖核心实体。
    需要联网条件（PRD §6.2）：<3 篇 / >30 天 / 时间敏感词 / 版本价格类 / 仅中文二次传播源。
    """
    title = topic.get("title") or ""
    count = len(local_articles)

    # 需要联网的条件（满足任一即建议联网）
    reasons = []
    if count < MIN_LOCAL_SOURCES:
        reasons.append(f"本地仅 {count} 篇（少于 {MIN_LOCAL_SOURCES}）")

    # 时效性：最新文章是否超过 14 天
    has_recent = False
    has_stale = True
    cutoff_recent = datetime.now() - timedelta(days=FRESH_DAYS)
    cutoff_stale = datetime.now() - timedelta(days=STALE_DAYS)
    for a in local_articles:
        pub_str = a.get("published_at") or a.get("fetched_at") or ""
        if not pub_str:
            continue
        try:
            pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub >= cutoff_recent:
                has_recent = True
            if pub >= cutoff_stale:
                has_stale = False
        except (ValueError, TypeError):
            continue
    if local_articles and not has_recent:
        reasons.append(f"最近 {FRESH_DAYS} 天无相关资料")
    if local_articles and not has_stale:
        pass  # 30 天内有资料
    elif local_articles:
        reasons.append(f"最新资料超过 {STALE_DAYS} 天")

    # 时间敏感词
    if any(k in title for k in TIME_SENSITIVE_KEYWORDS):
        reasons.append("标题含时间敏感词")

    # 版本/价格/API 类
    if VERSION_PATTERN.search(title):
        reasons.append("选题涉及版本/价格/API")

    # 仅 C 级来源（中文二次传播）
    levels = {(a.get("source_level") or "C").upper() for a in local_articles}
    if local_articles and levels and levels.issubset({"C"}):
        reasons.append("仅有中文二次传播源，无官方/一手源")

    needs_web = bool(reasons)
    return {
        "sufficient": not needs_web,
        "needs_web": needs_web,
        "reason": "；".join(reasons) if reasons else "本地资料充分",
        "local_count": count,
        "has_recent": has_recent,
        "has_official": bool(levels & OFFICIAL_LEVELS),
    }


def _search_web(topic_id: int, title: str, reason: str) -> list[dict]:
    """执行联网搜索补充。受开关/API Key/预算限制，失败时静默返回空列表。"""
    if not is_web_search_available():
        logger.info("联网搜索不可用（开关关闭或无 API Key），topic_id=%s", topic_id)
        return []

    queries = _build_search_queries(title)
    all_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for q in queries:
        try:
            results = search_for_topic(topic_id, q)
            for r in results:
                if r.url and r.url not in seen_urls:
                    all_results.append(r)
                    seen_urls.add(r.url)
            if len(all_results) >= 15:  # 够了就不再查
                break
        except WebSearchBudgetExceeded as e:
            logger.warning("联网搜索超预算，停止：topic_id=%s %s", topic_id, e)
            break
        except WebSearchError as e:
            logger.warning("联网搜索失败，跳过此查询：topic_id=%s query=%s %s", topic_id, q[:40], e)
            continue

    if not all_results:
        return []

    # 提取正文（取前 extract_max_urls 条）
    top_urls = [r.url for r in all_results[:settings.tavily_extract_max_urls]]
    extracts: list[ExtractResult] = []
    try:
        extracts = extract_for_topic(topic_id, top_urls)
    except (WebSearchBudgetExceeded, WebSearchError) as e:
        logger.warning("Extract 失败，仅用搜索摘要：topic_id=%s %s", topic_id, e)

    extract_map = {e.url: e.raw_content for e in extracts if not e.failed}

    # 分级过滤，保留前 5 条进入资料卡
    enriched = []
    for r in all_results:
        level, keep = classify_source(r.url, r.title)
        if not keep:
            continue
        enriched.append({
            "url": r.url,
            "title": r.title,
            "excerpt": (extract_map.get(r.url) or r.content)[:500],
            "source_level": level,
            "source_name": _extract_source_name(r.url),
            "score": r.score,
        })
    # 排序：S>A>B>C>U，同等级按 score 降序
    level_order = {"S": 5, "A": 4, "B": 3, "C": 2, "U": 1}
    enriched.sort(key=lambda x: (level_order.get(x["source_level"], 0), x["score"]), reverse=True)
    return enriched[:5]


def _build_search_queries(title: str) -> list[str]:
    """生成最多 5 条搜索查询词（PRD §8.2.4）。"""
    # 简化实体提取：取标题前 30 字作为核心实体
    entity = title[:30].strip()
    return [
        f"{entity} AI Agent",
        f"{entity} agent AI workflow release",
        f"{entity} docs blog announcement",
        f"{entity} GitHub Hacker News",
        f"{entity} limitation issue risk",
    ]


def _extract_source_name(url: str) -> str:
    """从 URL 提取来源名（host 去掉 www 前缀）。"""
    host = get_host(url)
    return host.replace("www.", "") if host else "web"


def _normalize_confidence(value: str | None) -> str:
    if not value:
        return "medium"
    c = value.lower()
    return c if c in ("high", "medium", "low") else "medium"


def _format_local_sources(articles: list[dict]) -> str:
    if not articles:
        return "（本地资料库未检索到相关文章，请基于选题已有信息生成资料卡，并在 risk_notes 中标注资料不足。）"
    lines = []
    for i, a in enumerate(articles, 1):
        level = (a.get("source_level") or "-").upper()
        pub = a.get("published_at") or a.get("fetched_at") or "-"
        lines.append(
            f"{i}. [{level}级] {a.get('title') or '（无标题）'}\n"
            f"   来源：{a.get('source_name') or '-'} ｜ 发布：{pub} ｜ URL：{a.get('url') or ''}\n"
            f"   摘要：{(a.get('summary') or (a.get('content_text') or '')[:200]) or ''}"[:300]
        )
    return "\n".join(lines)


def _format_web_sources(results: list[dict]) -> str:
    if not results:
        return "（联网搜索未补充到资料，或已关闭/超预算）"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. [{r['source_level']}级] {r['title']}\n"
            f"   来源：{r['source_name']} ｜ URL：{r['url']}\n"
            f"   摘要：{r['excerpt'][:300]}"
        )
    return "\n".join(lines)
