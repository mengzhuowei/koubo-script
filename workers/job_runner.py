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
        update_fetch_state(source_id, last_error="来源已停用，跳过")
        return

    items = fetch_source(source)
    inserted = 0
    last_seen = None
    for it in items:
        new_id = insert_article(
            source_id=source_id, title=it.title, url=it.url, canonical_url=it.canonical_url,
            author=it.author, published_at=it.published_at, raw_html=it.raw_html,
            content_text=it.content_text, source_item_id=it.source_item_id, language=it.language,
        )
        if new_id:
            inserted += 1
        if it.source_item_id:
            last_seen = it.source_item_id
    update_fetch_state(source_id, last_error=None, last_seen_item_id=last_seen)


def _handle_fetch_all_sources(job_id: int) -> None:
    """对每个启用来源创建独立的 fetch_source 任务，便于并发与错误隔离。"""
    for s in list_enabled_sources():
        jobs_repo.enqueue("fetch_source", {"source_id": s["id"]})


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
