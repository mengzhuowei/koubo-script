"""选题资料卡 repository：资料卡与来源的读写。

资料卡是选题与脚本之间的中间产物，整理本地文章库相关资料供脚本生成引用。
card_json 用 TEXT 存 json.dumps 字符串，读取时手动 json.loads，与 audience/hashtags 风格一致。
"""
from __future__ import annotations

import json

from repositories.db import get_conn


def _row(r):
    return dict(r) if r else None


def _parse_card(card: dict) -> dict:
    """把 DB 行的 card_json 字段解析为 dict，并补齐派生字段供前端使用。"""
    if not card:
        return card
    raw = card.get("card_json")
    if raw:
        try:
            card["card"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            card["card"] = {}
    else:
        card["card"] = {}
    return card


def create_research_card(*, topic_id: int, title: str, summary: str, card_json: dict,
                         confidence: str = "medium", local_source_count: int = 0,
                         web_source_count: int = 0, has_official_source: bool = False,
                         generated_by: str = "llm") -> int:
    """新建一份资料卡（新版本）。返回 research_card_id。"""
    conn = get_conn()
    try:
        # 同一选题历史版本数 + 1 作为新版本号
        v = conn.execute(
            "SELECT COUNT(*) AS c FROM topic_research_cards WHERE topic_id = %s", (topic_id,)
        ).fetchone()["c"] + 1
        cur = conn.execute(
            """INSERT INTO topic_research_cards
               (topic_id, title, summary, card_json, confidence, local_source_count,
                web_source_count, has_official_source, generated_by, version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (topic_id, title, summary, json.dumps(card_json, ensure_ascii=False),
             confidence, local_source_count, web_source_count,
             1 if has_official_source else 0, generated_by, v),
        )
        return cur.lastrowid
    finally:
        conn.close()


def add_research_source(*, research_card_id: int, article_id: int | None, source_url: str,
                        source_title: str | None, source_name: str | None,
                        source_level: str | None, published_at: str | None,
                        source_type: str = "local", excerpt: str | None) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO topic_research_sources
               (research_card_id, article_id, source_url, source_title, source_name,
                source_level, published_at, source_type, excerpt)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (research_card_id, article_id, source_url, source_title, source_name,
             source_level, published_at, source_type, excerpt),
        )
    finally:
        conn.close()


def get_latest_card_for_topic(topic_id: int) -> dict | None:
    """返回选题最新的资料卡（含解析后的 card 字段）。无则 None。"""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT * FROM topic_research_cards WHERE topic_id = %s ORDER BY version DESC LIMIT 1",
            (topic_id,),
        ).fetchone()
        return _parse_card(_row(r))
    finally:
        conn.close()


def get_card(research_card_id: int) -> dict | None:
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT * FROM topic_research_cards WHERE id = %s", (research_card_id,)
        ).fetchone()
        return _parse_card(_row(r))
    finally:
        conn.close()


def get_sources_for_card(research_card_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM topic_research_sources WHERE research_card_id = %s ORDER BY id ASC",
            (research_card_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_card_content(research_card_id: int, *, title: str, summary: str,
                        card_json: dict, confidence: str) -> None:
    """人工编辑资料卡：只改内容字段，不动版本与来源。
    generated_by 标记为 manual，表示用户改过，后续自动刷新默认不覆盖。
    """
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE topic_research_cards
               SET title=%s, summary=%s, card_json=%s, confidence=%s, generated_by='manual',
                   needs_refresh=0, updated_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (title, summary, json.dumps(card_json, ensure_ascii=False), confidence, research_card_id),
        )
    finally:
        conn.close()


def mark_needs_refresh(topic_id: int) -> None:
    """选题新增关联文章后，把最新资料卡标记为"建议刷新"。"""
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE topic_research_cards SET needs_refresh=1, updated_at=updated_at
               WHERE id = (SELECT id FROM (
                   SELECT id FROM topic_research_cards WHERE topic_id = %s
                   ORDER BY version DESC LIMIT 1
               ) AS t)""",
            (topic_id,),
        )
    finally:
        conn.close()


def has_active_research_job(topic_id: int) -> bool:
    """是否已有 pending/running 的资料卡生成任务，避免重复入队。"""
    conn = get_conn()
    try:
        r = conn.execute(
            """SELECT 1 FROM jobs
               WHERE type IN ('generate_research_card', 'refresh_research_card')
                 AND status IN ('pending', 'running')
                 AND JSON_EXTRACT(payload_json, '$.topic_id') = %s
               LIMIT 1""",
            (topic_id,),
        ).fetchone()
        return r is not None
    finally:
        conn.close()


def is_card_expired(card: dict, hours: int = 24) -> bool:
    """资料卡是否超过有效期。默认 24 小时。"""
    if not card or not card.get("updated_at"):
        return True
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT TIMESTAMPDIFF(HOUR, %s, CURRENT_TIMESTAMP) AS h",
            (card["updated_at"],),
        ).fetchone()
        return (r["h"] if r else 0) >= hours
    finally:
        conn.close()
