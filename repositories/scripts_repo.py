"""脚本 repository：版本递增、保存、列表。"""
from __future__ import annotations

import json

from repositories.db import get_conn


def _row(r):
    return dict(r) if r else None


def next_version(topic_id: int, platform: str, fmt: str, duration: int) -> int:
    """计算同 topic/platform/format/duration 下的下一个版本号。"""
    conn = get_conn()
    try:
        r = conn.execute(
            """SELECT MAX(version) AS v FROM scripts
               WHERE topic_id=%s AND platform=%s AND format=%s AND duration=%s""",
            (topic_id, platform, fmt, duration),
        ).fetchone()
        return (r["v"] or 0) + 1
    finally:
        conn.close()


def create_script(*, topic_id: int, platform: str, fmt: str, duration: int, version: int,
                  title: str | None, hook: str | None, body: str, cta: str | None,
                  cover_text: str | None, description: str | None,
                  hashtags: list[str] | None) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO scripts
               (topic_id, platform, format, duration, version, title, hook, body, cta,
                cover_text, description, hashtags)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (topic_id, platform, fmt, duration, version, title, hook, body, cta,
             cover_text, description,
             json.dumps(hashtags, ensure_ascii=False) if hashtags else None),
        )
        return cur.lastrowid
    finally:
        conn.close()


def update_script(script_id: int, *, title: str, hook: str, body: str, cta: str,
                  cover_text: str, description: str, hashtags: str) -> None:
    """保存编辑后的脚本（hashtags 表单传字符串，按换行/逗号切分后存 JSON）。"""
    tags = _parse_tags(hashtags)
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE scripts
               SET title=%s, hook=%s, body=%s, cta=%s, cover_text=%s, description=%s,
                   hashtags=%s, updated_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (title or None, hook or None, body, cta or None, cover_text or None,
             description or None,
             json.dumps(tags, ensure_ascii=False) if tags else None, script_id),
        )
    finally:
        conn.close()


def _parse_tags(text: str) -> list[str]:
    if not text:
        return []
    parts = [t.strip().lstrip("#") for t in text.replace("\n", ",").split(",")]
    return [p for p in parts if p]


def get_script(script_id: int) -> dict | None:
    conn = get_conn()
    try:
        s = _row(conn.execute("SELECT * FROM scripts WHERE id = %s", (script_id,)).fetchone())
        if s and s.get("hashtags"):
            try:
                s["hashtags_list"] = json.loads(s["hashtags"])
            except (json.JSONDecodeError, TypeError):
                s["hashtags_list"] = []
        else:
            s["hashtags_list"] = [] if s else []
        return s
    finally:
        conn.close()


def list_scripts_for_topic(topic_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM scripts WHERE topic_id = %s ORDER BY version DESC", (topic_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("hashtags"):
                try:
                    d["hashtags_list"] = json.loads(d["hashtags"])
                except (json.JSONDecodeError, TypeError):
                    d["hashtags_list"] = []
            else:
                d["hashtags_list"] = []
            result.append(d)
        return result
    finally:
        conn.close()


def count_scripts_for_topic(topic_id: int) -> int:
    """统计选题下的脚本数，用于判断旧选题是否可安全删除。"""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM scripts WHERE topic_id = %s", (topic_id,)
        ).fetchone()
        return r["c"] if r else 0
    finally:
        conn.close()


def list_recent_scripts(limit: int = 5) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT s.*, t.title AS topic_title
               FROM scripts s LEFT JOIN topics t ON s.topic_id = t.id
               ORDER BY s.updated_at DESC LIMIT %s""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
