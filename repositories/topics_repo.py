"""选题库 repository：topics / topic_facts / topic_articles 的读写。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from repositories.db import get_conn


def _row(r):
    return _with_score_breakdown(dict(r)) if r else None


def _with_score_breakdown(row: dict) -> dict:
    raw = row.get("score_breakdown")
    if isinstance(raw, dict):
        row["score_breakdown_data"] = raw
    elif raw:
        try:
            row["score_breakdown_data"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            row["score_breakdown_data"] = {}
    else:
        row["score_breakdown_data"] = {}
    return row


def create_topic(*, title: str, one_line_takeaway: str, summary: str, category: str | None,
                 audience: list[str], recommended_column: str | None, recommended_platform: str | None,
                 recommended_duration: int | None, score: int, source_level: str | None,
                 actionable_value: str, risk_notes: str,
                 score_breakdown: dict | None = None, score_method: str | None = None,
                 score_version: str | None = None, score_confidence: str | None = None,
                 score_stage: str | None = None) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO topics
               (title, one_line_takeaway, summary, category, audience, recommended_column,
                recommended_platform, recommended_duration, score, source_level,
                actionable_value, risk_notes, score_breakdown, score_method, score_version,
                score_confidence, score_stage, scored_at, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 'new')""",
            (title, one_line_takeaway, summary, category,
             json.dumps(audience, ensure_ascii=False) if audience else None,
             recommended_column, recommended_platform, recommended_duration, score,
             source_level, actionable_value, risk_notes,
             json.dumps(score_breakdown, ensure_ascii=False) if score_breakdown else None,
             score_method, score_version, score_confidence, score_stage),
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


def update_score(
    topic_id: int,
    score: int,
    *,
    breakdown: dict | None = None,
    method: str | None = None,
    version: str | None = None,
    confidence: str | None = None,
    stage: str | None = None,
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE topics
               SET score = %s, score_breakdown = %s, score_method = %s,
                   score_version = %s, score_confidence = %s, score_stage = %s,
                   scored_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (
                int(score),
                json.dumps(breakdown, ensure_ascii=False) if breakdown else None,
                method,
                version,
                confidence,
                stage,
                topic_id,
            ),
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


def list_topics(*, status: str = "", category: str = "", date_from: str = "",
                date_to: str = "", limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM topics WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = %s"
        params.append(status)
    if category:
        sql += " AND (recommended_column = %s OR category = %s)"
        params += [category, category]
    if date_from:
        sql += " AND DATE(created_at) >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND DATE(created_at) <= %s"
        params.append(date_to)
    # 排序：当天创建的选题优先排前，再按分数倒序，最后按 id 倒序
    sql += " ORDER BY CASE WHEN DATE(created_at) = CURDATE() THEN 0 ELSE 1 END, score DESC, id DESC LIMIT %s"
    params.append(limit)
    conn = get_conn()
    try:
        return [_with_score_breakdown(dict(r)) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def list_top_topics(limit: int = 10) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM topics ORDER BY score DESC, id DESC LIMIT %s", (limit,)
        ).fetchall()
        return [_with_score_breakdown(dict(r)) for r in rows]
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
            "SELECT a.*, s.level AS source_level, s.name AS source_name "
            "FROM topic_articles ta JOIN articles a ON ta.article_id = a.id "
            "LEFT JOIN sources s ON s.id = a.source_id "
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


def list_topic_ids_for_article(article_id: int) -> list[int]:
    """返回与文章关联的所有 topic_id。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT topic_id FROM topic_articles WHERE article_id = %s", (article_id,)
        ).fetchall()
        return [r["topic_id"] for r in rows]
    finally:
        conn.close()


def list_topics_for_article(article_id: int) -> list[dict]:
    """返回与文章关联的选题列表（id/title/status/score），供文章详情页跳转。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT t.id, t.title, t.status, t.score FROM topic_articles ta "
            "JOIN topics t ON ta.topic_id = t.id WHERE ta.article_id = %s "
            "ORDER BY t.id DESC",
            (article_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def unlink_article_from_topics(article_id: int) -> list[int]:
    """解除文章与所有 topic 的关联，返回被解除的 topic_id 列表。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT topic_id FROM topic_articles WHERE article_id = %s", (article_id,)
        ).fetchall()
        topic_ids = [r["topic_id"] for r in rows]
        if topic_ids:
            conn.execute(
                "DELETE FROM topic_articles WHERE article_id = %s", (article_id,)
            )
        return topic_ids
    finally:
        conn.close()


def count_articles_for_topic(topic_id: int) -> int:
    """统计选题仍关联的文章数（排除刚解除的那篇）。"""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM topic_articles WHERE topic_id = %s", (topic_id,)
        ).fetchone()
        return r["c"] if r else 0
    finally:
        conn.close()


def delete_topic(topic_id: int) -> None:
    """删除选题及其 facts 与 article 关联。仅用于无脚本且无其他文章关联的孤立旧选题。"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM topic_facts WHERE topic_id = %s", (topic_id,))
        conn.execute("DELETE FROM topic_articles WHERE topic_id = %s", (topic_id,))
        conn.execute("DELETE FROM topics WHERE id = %s", (topic_id,))
    finally:
        conn.close()
