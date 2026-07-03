"""联网搜索预算追踪：月度 + 单选题 credit 双重限制。

每次搜索/提取记一行，通过 SUM 聚合查询当月/当选题已用 credit。
"""
from __future__ import annotations

from datetime import datetime

from config import settings
from repositories.db import get_conn


def record_usage(*, topic_id: int, query_text: str, credits_used: int,
                 results_count: int, search_depth: str) -> None:
    """记录一次联网搜索消耗。"""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO web_search_usage
               (topic_id, query_text, credits_used, results_count, search_depth)
               VALUES (%s, %s, %s, %s, %s)""",
            (topic_id, query_text[:500], credits_used, results_count, search_depth),
        )
    finally:
        conn.close()


def monthly_credits_used() -> int:
    """本月已消耗的总 credit。用日期范围替代 YEAR()/MONTH() 以命中 created_at 索引。"""
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 下月初
    if now.month == 12:
        month_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        month_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT COALESCE(SUM(credits_used), 0) AS c FROM web_search_usage "
            "WHERE created_at >= %s AND created_at < %s",
            (month_start, month_end),
        ).fetchone()
        return int(r["c"]) if r else 0
    finally:
        conn.close()


def topic_credits_used(topic_id: int) -> int:
    """单个选题已消耗的总 credit。"""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT COALESCE(SUM(credits_used), 0) AS c FROM web_search_usage WHERE topic_id = %s",
            (topic_id,),
        ).fetchone()
        return int(r["c"]) if r else 0
    finally:
        conn.close()


def check_budget(topic_id: int, credits_needed: int) -> bool:
    """检查本次消耗是否在月度和单选题预算内。"""
    if monthly_credits_used() + credits_needed > settings.tavily_monthly_credit_budget:
        return False
    if topic_credits_used(topic_id) + credits_needed > settings.tavily_per_topic_credit_budget:
        return False
    return True


def get_budget_status(topic_id: int | None = None) -> dict:
    """返回预算使用状态，供 UI 展示。"""
    monthly = monthly_credits_used()
    return {
        "enabled": settings.web_search_enabled,
        "configured": bool(settings.tavily_api_key),
        "available": bool(settings.web_search_enabled and settings.tavily_api_key),
        "monthly_used": monthly,
        "monthly_budget": settings.tavily_monthly_credit_budget,
        "monthly_remaining": max(0, settings.tavily_monthly_credit_budget - monthly),
        "topic_used": topic_credits_used(topic_id) if topic_id else 0,
        "topic_budget": settings.tavily_per_topic_credit_budget if topic_id else 0,
    }
