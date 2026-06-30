"""文章池 repository：入库、去重、检索、状态流转。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from repositories.db import get_conn
from services.cleaner import compute_content_hash, normalize_url


def _row(r):
    return dict(r) if r else None


def insert_article(*, source_id: int, title: str, url: str, canonical_url: str | None,
                   author: str | None, published_at: str | None, raw_html: str | None,
                   content_text: str, source_item_id: str | None, language: str | None) -> int | None:
    """插入文章，重复时返回 None。去重基于 content_hash / source_item_id / canonical_url。"""
    content_hash = compute_content_hash(title, content_text or "")
    canonical = normalize_url(canonical_url) if canonical_url else normalize_url(url)

    conn = get_conn()
    try:
        # 去重依赖 UNIQUE INDEX（content_hash / source_item_id / canonical_url），
        # 用 INSERT OR IGNORE 让数据库原子判定，避免 SELECT-then-INSERT 的竞态。
        cur = conn.execute(
            """INSERT OR IGNORE INTO articles
               (source_id, source_item_id, title, url, canonical_url, author, published_at,
                raw_html, content_text, content_hash, language, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
            (source_id, source_item_id, title, url, canonical, author, published_at,
             raw_html, content_text, content_hash, language),
        )
        return cur.lastrowid if cur.rowcount == 1 else None
    finally:
        conn.close()


def search_articles(*, q: str = "", source_id: int = 0, limit: int = 200) -> list[dict]:
    """按标题/正文关键词与来源筛选。"""
    sql = ("SELECT a.*, s.name AS source_name, s.level AS source_level "
           "FROM articles a LEFT JOIN sources s ON a.source_id = s.id WHERE 1=1")
    params: list = []
    if q:
        sql += " AND (a.title LIKE ? OR a.content_text LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if source_id:
        sql += " AND a.source_id = ?"
        params.append(source_id)
    sql += " ORDER BY a.fetched_at DESC LIMIT ?"
    params.append(limit)

    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_article(article_id: int) -> dict | None:
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT a.*, s.name AS source_name FROM articles a "
            "LEFT JOIN sources s ON a.source_id = s.id WHERE a.id = ?",
            (article_id,),
        ).fetchone()
        return _row(r)
    finally:
        conn.close()


def ignore_article(article_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE articles SET status='ignored' WHERE id = ?", (article_id,))
    finally:
        conn.close()


def list_sources_for_filter() -> list[dict]:
    from repositories.sources_repo import list_sources
    return list_sources()


def count_articles_today() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM articles WHERE substr(fetched_at, 1, 10) = ?", (today,)
        ).fetchone()
        return r["c"] if r else 0
    finally:
        conn.close()


def list_unprocessed_articles(limit: int = 50) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT a.*, s.name AS source_name, s.level AS source_level "
            "FROM articles a LEFT JOIN sources s ON a.source_id = s.id "
            "WHERE a.status = 'new' ORDER BY a.fetched_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_article_summary(article_id: int, *, summary: str, key_points: list[str] | None) -> None:
    """只更新摘要字段，不改 status。status 由 topic 生成成功后 mark_processed 标记，
    避免摘要成功但 topic 失败时文章被过早标记 processed 而无法重试。"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE articles SET summary = ?, key_points = ? WHERE id = ?",
            (summary, json.dumps(key_points, ensure_ascii=False) if key_points else None, article_id),
        )
    finally:
        conn.close()


def mark_processed(article_id: int) -> None:
    """文章生成 topic 成功后标记为 processed。"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE articles SET status='processed', processed_at=CURRENT_TIMESTAMP WHERE id = ?",
            (article_id,),
        )
    finally:
        conn.close()
