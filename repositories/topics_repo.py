"""选题库 repository：topics / topic_facts / topic_articles 的读写。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from repositories.db import get_conn


def _row(r):
    return dict(r) if r else None


def create_topic(*, title: str, one_line_takeaway: str, summary: str, category: str | None,
                 audience: list[str], recommended_column: str | None, recommended_platform: str | None,
                 recommended_duration: int | None, score: int, source_level: str | None,
                 actionable_value: str, risk_notes: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO topics
               (title, one_line_takeaway, summary, category, audience, recommended_column,
                recommended_platform, recommended_duration, score, source_level,
                actionable_value, risk_notes, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new')""",
            (title, one_line_takeaway, summary, category,
             json.dumps(audience, ensure_ascii=False) if audience else None,
             recommended_column, recommended_platform, recommended_duration, score,
             source_level, actionable_value, risk_notes),
        )
        return cur.lastrowid
    finally:
        conn.close()


def add_topic_fact(topic_id: int, claim: str, source_url: str, confidence: str = "medium") -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO topic_facts (topic_id, claim, source_url, confidence) VALUES (%s, %s, %s, %s)",
            (topic_id, claim, source_url, confidence),
        )
    finally:
        conn.close()


def link_article(topic_id: int, article_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT IGNORE INTO topic_articles (topic_id, article_id) VALUES (%s, %s)",
            (topic_id, article_id),
        )
    finally:
        conn.close()


def add_article_to_topic(topic_id: int, article_id: int) -> None:
    link_article(topic_id, article_id)


def update_score(topic_id: int, score: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE topics SET score = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (int(score), topic_id),
        )
    finally:
        conn.close()


def set_topic_status(topic_id: int, status: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE topics SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, topic_id),
        )
    finally:
        conn.close()


def list_topics(*, status: str = "", category: str = "", limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM topics WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = %s"
        params.append(status)
    if category:
        sql += " AND (recommended_column = %s OR category = %s)"
        params += [category, category]
    sql += " ORDER BY score DESC, id DESC LIMIT %s"
    params.append(limit)
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def list_top_topics(limit: int = 10) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM topics ORDER BY score DESC, id DESC LIMIT %s", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_topic(topic_id: int) -> dict | None:
    conn = get_conn()
    try:
        return _row(conn.execute("SELECT * FROM topics WHERE id = %s", (topic_id,)).fetchone())
    finally:
        conn.close()


def get_topic_facts(topic_id: int) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM topic_facts WHERE topic_id = %s ORDER BY id ASC", (topic_id,)
        ).fetchall()]
    finally:
        conn.close()


def get_topic_articles(topic_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT a.* FROM topic_articles ta JOIN articles a ON ta.article_id = a.id "
            "WHERE ta.topic_id = %s ORDER BY a.id ASC",
            (topic_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_topic_with_facts_and_articles(topic_id: int) -> dict | None:
    topic = get_topic(topic_id)
    if not topic:
        return None
    if topic.get("audience"):
        try:
            topic["audience_list"] = json.loads(topic["audience"])
        except (json.JSONDecodeError, TypeError):
            topic["audience_list"] = []
    else:
        topic["audience_list"] = []
    topic["facts"] = get_topic_facts(topic_id)
    topic["articles"] = get_topic_articles(topic_id)
    return topic


def count_topics_today() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM topics WHERE DATE(created_at) = %s", (today,)
        ).fetchone()
        return r["c"] if r else 0
    finally:
        conn.close()


def list_recent_topic_titles(days: int = 7, limit: int = 500) -> list[dict]:
    """返回最近 N 天内非 archived 选题的 id 与 title，供生成时去重比对。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title FROM topics "
            "WHERE status != 'archived' AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
            "ORDER BY id DESC LIMIT %s",
            (days, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
