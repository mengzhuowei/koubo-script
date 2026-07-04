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
        # 用 INSERT IGNORE 让数据库原子判定，避免 SELECT-then-INSERT 的竞态。
        cur = conn.execute(
            """INSERT IGNORE INTO articles
               (source_id, source_item_id, title, url, canonical_url, author, published_at,
                raw_html, content_text, content_hash, language, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new')""",
            (source_id, source_item_id, title, url, canonical, author, published_at,
             raw_html, content_text, content_hash, language),
        )
        return cur.lastrowid if cur.rowcount == 1 else None
    finally:
        conn.close()


def search_articles(*, q: str = "", source_id: int = 0, no_content: bool = False,
                     limit: int = 50, offset: int = 0) -> list[dict]:
    """按标题/正文关键词与来源筛选。no_content=True 时只返回正文为空的记录。

    关键词搜索优先用 FULLTEXT（ngram 解析器，支持中文，按相关度排序）。
    查询长度 < 2 时 FULLTEXT 无法匹配（ngram 最小 token=2），回退到 LIKE。
    分页：limit 单页条数，offset 偏移（与 ORDER BY/LIMIT 配合）。
    """
    q = q.strip()
    use_fulltext = bool(q) and len(q) >= 2
    if use_fulltext:
        # BOOLEAN MODE 下 +、-、*、(、)、~、" 等会被当作操作符。
        # 用双引号把整个查询包成短语匹配，使其中的特殊字符按字面处理（如 "C++"、"GPT-4"）。
        # 先去掉查询自带的半角双引号，避免破坏短语包裹结构。
        fulltext_q = '"' + q.replace('"', '') + '"'
    select_cols = "a.*, s.name AS source_name, s.level AS source_level"
    if use_fulltext:
        # relevance 仅用于排序，SELECT 中需带 AGAINST(%s)
        select_cols += ", MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE) AS relevance"
    sql = f"SELECT {select_cols} FROM articles a LEFT JOIN sources s ON a.source_id = s.id WHERE 1=1"
    params: list = []
    if use_fulltext:
        params.append(fulltext_q)  # SELECT 中的 relevance
        sql += " AND MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE)"
        params.append(fulltext_q)  # WHERE 中的匹配
    elif q:
        sql += " AND (a.title LIKE %s OR a.content_text LIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    if source_id:
        sql += " AND a.source_id = %s"
        params.append(source_id)
    if no_content:
        # 正文为空或仅含失败提示文本（以"（正文获取失败"开头）
        sql += " AND (a.content_text IS NULL OR a.content_text = '' OR a.content_text LIKE %s)"
        params.append("（正文获取失败%")
    if use_fulltext:
        # 搜索时相关度优先，同分按发布时间倒序，再按来源层级排序
        sql += " ORDER BY relevance DESC, a.published_at DESC, FIELD(s.level, 'S', 'A', 'B', 'C')"
    else:
        # 文章池按发布时间倒序（最新排前），同时间按来源层级排序
        sql += " ORDER BY a.published_at DESC, FIELD(s.level, 'S', 'A', 'B', 'C')"
    sql += " LIMIT %s OFFSET %s"
    params += [limit, offset]

    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def count_articles(*, q: str = "", source_id: int = 0, no_content: bool = False) -> int:
    """统计搜索结果总数，与 search_articles 共享同一组 WHERE 条件。"""
    q = q.strip()
    use_fulltext = bool(q) and len(q) >= 2
    if use_fulltext:
        fulltext_q = '"' + q.replace('"', '') + '"'
    sql = "SELECT COUNT(*) AS n FROM articles a WHERE 1=1"
    params: list = []
    if use_fulltext:
        sql += " AND MATCH(a.title, a.content_text) AGAINST(%s IN BOOLEAN MODE)"
        params.append(fulltext_q)
    elif q:
        sql += " AND (a.title LIKE %s OR a.content_text LIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    if source_id:
        sql += " AND a.source_id = %s"
        params.append(source_id)
    if no_content:
        sql += " AND (a.content_text IS NULL OR a.content_text = '' OR a.content_text LIKE %s)"
        params.append("（正文获取失败%")
    conn = get_conn()
    try:
        return int(conn.execute(sql, params).fetchone()["n"])
    finally:
        conn.close()


def bulk_ignore_articles(article_ids: list[int]) -> int:
    """批量忽略文章，返回受影响行数。"""
    if not article_ids:
        return 0
    conn = get_conn()
    try:
        placeholders = ",".join(["%s"] * len(article_ids))
        cur = conn.execute(
            f"UPDATE articles SET status='ignored' WHERE id IN ({placeholders})",
            tuple(article_ids),
        )
        return cur.rowcount
    finally:
        conn.close()


def get_article(article_id: int) -> dict | None:
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT a.*, s.name AS source_name FROM articles a "
            "LEFT JOIN sources s ON a.source_id = s.id WHERE a.id = %s",
            (article_id,),
        ).fetchone()
        return _row(r)
    finally:
        conn.close()


def ignore_article(article_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE articles SET status='ignored' WHERE id = %s", (article_id,))
    finally:
        conn.close()


def update_article_content(article_id: int, *, title: str, content_text: str) -> None:
    """人工补充/修正正文。只改 title 与 content_text，不动 status / content_hash：
    content_hash 仅用于入库去重（INSERT IGNORE），事后改不影响去重判定；
    status 保持原值，避免误改流程状态（如把 ignored 直接翻成 new）。
    """
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE articles SET title=%s, content_text=%s WHERE id=%s",
            (title, content_text, article_id),
        )
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
            "SELECT COUNT(*) AS c FROM articles WHERE DATE(fetched_at) = %s", (today,)
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
            "WHERE a.status = 'new' ORDER BY a.published_at DESC LIMIT %s",
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
            "UPDATE articles SET summary = %s, key_points = %s WHERE id = %s",
            (summary, json.dumps(key_points, ensure_ascii=False) if key_points else None, article_id),
        )
    finally:
        conn.close()


def mark_processed(article_id: int) -> None:
    """文章生成 topic 成功后标记为 processed。"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE articles SET status='processed', processed_at=CURRENT_TIMESTAMP WHERE id = %s",
            (article_id,),
        )
    finally:
        conn.close()


def reset_to_new(article_id: int) -> None:
    """重置文章为未处理状态，清空旧摘要让 summarizer 用新正文重新跑。
    保留 content_text（人工补充的正文）与 status 流程不直接翻成 processed。
    """
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE articles SET status='new', summary=NULL, key_points=NULL, processed_at=NULL WHERE id = %s",
            (article_id,),
        )
    finally:
        conn.close()
