"""定时调度器：按配置周期检查到期来源并创建抓取任务入队。

设计要点：
1. 不直接执行业务，只创建 job 入队，由 worker 消费（与 technical-architecture 6.3 一致）。
2. 抓取调度按每个来源的 fetch_interval_minutes 判定是否到期，粒度细于"每天统一抓一次"。
3. 入队前查重：若该来源已有 pending/running 的 fetch_source 任务则跳过，避免任务堆积。
4. generate_topic 自动调度默认关闭——该任务消耗 LLM，遵循"LLM 调用手动触发"约束。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    """启动后台调度器。可重复调用，只启动一次。scheduler_enabled=False 时直接跳过。"""
    global _scheduler
    if _scheduler is not None:
        return
    if not settings.scheduler_enabled:
        logger.info("scheduler 已在配置中关闭（SCHEDULER_ENABLED=False），跳过启动")
        return

    sched = BackgroundScheduler(timezone="Asia/Shanghai")

    # 抓取调度：按间隔轮询到期源
    sched.add_job(
        _enqueue_due_sources,
        trigger=IntervalTrigger(minutes=settings.scheduler_fetch_check_interval_minutes),
        id="fetch_due_sources",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # 选题生成调度：默认关闭，开启后按 cron 触发（会消耗 LLM）
    if settings.scheduler_topic_enabled:
        try:
            trig = CronTrigger.from_crontab(settings.scheduler_topic_cron, timezone="Asia/Shanghai")
        except ValueError as e:
            logger.error("scheduler_topic_cron 配置非法 (%r)，跳过选题调度: %s",
                         settings.scheduler_topic_cron, e)
        else:
            sched.add_job(
                _enqueue_generate_topic,
                trigger=trig,
                id="generate_topic_daily",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("选题自动调度已开启，cron=%s", settings.scheduler_topic_cron)

    sched.start()
    _scheduler = sched
    logger.info("scheduler 已启动，抓取轮询间隔=%s 分钟", settings.scheduler_fetch_check_interval_minutes)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("scheduler shutdown error")
    _scheduler = None


# ---------- 调度回调：只入队，不执行业务 ----------
def _enqueue_due_sources() -> None:
    """找出到期来源，为每个未在队列中的来源创建 fetch_source 任务。"""
    from repositories.jobs_repo import list_active_jobs_by_type, enqueue
    from repositories.sources_repo import list_due_sources

    try:
        due = list_due_sources()
        if not due:
            return
        # 已在队列/执行中的 source_id 集合，避免重复入队
        active = list_active_jobs_by_type("fetch_source")
        active_ids = {j.get("payload", {}).get("source_id") for j in active}

        enqueued = 0
        for s in due:
            sid = s["id"]
            if sid in active_ids:
                continue
            enqueue("fetch_source", {"source_id": sid})
            enqueued += 1
            logger.info("调度入队 fetch_source：source_id=%s [%s]", sid, s.get("name"))
        if enqueued:
            logger.info("本轮调度共入队 %d 个抓取任务（到期 %d，跳过已排队 %d）",
                        enqueued, len(due), len(due) - enqueued)
    except Exception:
        logger.exception("调度器 _enqueue_due_sources 执行失败")


def _enqueue_generate_topic() -> None:
    """创建 generate_topic 任务（消耗 LLM，仅在配置开启时触发）。"""
    from repositories.jobs_repo import enqueue, list_active_jobs_by_type
    try:
        # 已有进行中的选题生成则跳过，避免重复消耗 token
        if list_active_jobs_by_type("generate_topic"):
            logger.info("已有 generate_topic 任务在进行中，跳过本次调度")
            return
        enqueue("generate_topic", {})
        logger.info("调度入队 generate_topic")
    except Exception:
        logger.exception("调度器 _enqueue_generate_topic 执行失败")
