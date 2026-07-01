"""后台 worker：轮询 jobs 表并执行。所有业务 handler 在此分发。"""
from __future__ import annotations

import logging
import threading
import time
import traceback

from config import settings
from repositories import jobs_repo
from repositories.sources_repo import get_source, list_enabled_sources, update_fetch_state

logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_stop = threading.Event()


def start_worker() -> None:
    """在后台守护线程中启动 worker loop。可重复调用，只启动一次。"""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop.clear()
    _worker_thread = threading.Thread(target=_loop, name="job-worker", daemon=True)
    _worker_thread.start()
    logger.info("job worker started")


def stop_worker() -> None:
    _stop.set()


def _loop() -> None:
    while not _stop.is_set():
        try:
            job = jobs_repo.claim_next_job()
            if not job:
                time.sleep(settings.job_poll_interval_seconds)
                continue
            _run_job(job)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(settings.job_poll_interval_seconds)


def _run_job(job: dict) -> None:
    job_id = job["id"]
    jtype = job["type"]
    payload = job.get("payload") or {}
    try:
        _dispatch(jtype, payload, job_id)
        jobs_repo.complete_job(job_id)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        logger.exception("job %s failed", jtype)
        jobs_repo.fail_job(job_id, err)


def _dispatch(jtype: str, payload: dict, job_id: int) -> None:
    if jtype == "fetch_source":
        _handle_fetch_source(payload)
    elif jtype == "fetch_all_sources":
        _handle_fetch_all_sources(job_id)
    elif jtype == "process_article":
        _handle_process_article(payload)
    elif jtype == "generate_topic":
        _handle_generate_topic(job_id)
    elif jtype == "generate_script":
        _handle_generate_script(payload)
    elif jtype == "generate_assets":
        _handle_generate_assets(payload)
    else:
        raise ValueError(f"未知 job type: {jtype}")


# ---------- 抓取 ----------
def _handle_fetch_source(payload: dict) -> None:
    from services.crawler import fetch_source
    from repositories.articles_repo import insert_article

    source_id = payload["source_id"]
    source = get_source(source_id)
    if not source:
        raise ValueError(f"source {source_id} 不存在")
    if not source["enabled"]:
        logger.info("来源 %s(%s) 已停用，跳过抓取", source.get("name"), source_id)
        update_fetch_state(source_id, last_error="来源已停用，跳过")
        return

    logger.info("开始抓取来源 [%s] id=%s type=%s url=%s",
                source.get("name"), source_id, source.get("type"), source.get("url"))
    items = fetch_source(source)
    logger.info("来源 [%s] 获取条目 %d 条，开始入库去重", source.get("name"), len(items))

    inserted = 0
    deduped = 0
    empty_content = 0
    last_seen = None
    for it in items:
        # 正文为空时，用 fetch_error 生成提示文本，避免用户看到无信息的"无正文"
        content_text = it.content_text
        if not content_text and it.fetch_error:
            content_text = f"（正文获取失败：{it.fetch_error}）"
        if not content_text:
            empty_content += 1
        new_id = insert_article(
            source_id=source_id, title=it.title, url=it.url, canonical_url=it.canonical_url,
            author=it.author, published_at=it.published_at, raw_html=it.raw_html,
            content_text=content_text, source_item_id=it.source_item_id, language=it.language,
        )
        if new_id:
            inserted += 1
            logger.debug("新增文章 id=%s title=%s", new_id, it.title[:50])
        else:
            deduped += 1
        if it.source_item_id:
            last_seen = it.source_item_id
    update_fetch_state(source_id, last_error=None, last_seen_item_id=last_seen)
    logger.info("来源 [%s] 抓取完成：新增 %d 篇，去重跳过 %d 篇，正文为空 %d 篇",
                source.get("name"), inserted, deduped, empty_content)


def _handle_fetch_all_sources(job_id: int) -> None:
    """对每个启用来源创建独立的 fetch_source 任务，便于并发与错误隔离。"""
    enabled = list_enabled_sources()
    logger.info("fetch_all_sources job=%s：共 %d 个启用来源，将创建抓取子任务", job_id, len(enabled))
    for s in enabled:
        jobs_repo.enqueue("fetch_source", {"source_id": s["id"]})
        logger.debug("已入队 fetch_source job：source_id=%s [%s]", s["id"], s.get("name"))


# ---------- 文章处理 ----------
def _handle_process_article(payload: dict) -> None:
    from services.summarizer import summarize_article
    from repositories.articles_repo import get_article, update_article_summary

    article_id = payload["article_id"]
    article = get_article(article_id)
    if not article:
        raise ValueError(f"article {article_id} 不存在")
    summary, key_points = summarize_article(article)
    update_article_summary(article_id, summary=summary, key_points=key_points)


# ---------- 选题生成 ----------
def _handle_generate_topic(job_id: int) -> None:
    from services.topic_generator import generate_topics_from_unprocessed
    n = generate_topics_from_unprocessed()
    logger.info("generated %s topics for job %s", n, job_id)


# ---------- 脚本生成 ----------
def _handle_generate_script(payload: dict) -> None:
    from services.script_generator import generate_script_for_topic
    generate_script_for_topic(
        topic_id=payload["topic_id"],
        platform=payload["platform"],
        fmt=payload["format"],
        duration=payload["duration"],
    )


# ---------- 发布素材包 ----------
def _handle_generate_assets(payload: dict) -> None:
    from services.assets_generator import generate_assets_for_script
    generate_assets_for_script(script_id=payload["script_id"])
