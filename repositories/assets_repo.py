"""发布素材包 repository：每个脚本一条素材记录，重新生成覆盖。"""
from __future__ import annotations

import json

from repositories.db import get_conn


def _parse_json_field(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        v = json.loads(val)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _row(r) -> dict | None:
    if not r:
        return None
    d = dict(r)
    d["titles_list"] = _parse_json_field(d.get("titles"))
    d["cover_texts_list"] = _parse_json_field(d.get("cover_texts"))
    d["hashtags_list"] = _parse_json_field(d.get("hashtags"))
    d["comment_questions_list"] = _parse_json_field(d.get("comment_questions"))
    return d


def upsert_assets(*, script_id: int, titles: list, cover_texts: list, description: str,
                  hashtags: list, comment_questions: list, pinned_comment: str) -> int:
    """写入素材包，同一脚本重复生成则覆盖。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO script_assets
               (script_id, titles, cover_texts, description, hashtags, comment_questions, pinned_comment)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 titles=VALUES(titles), cover_texts=VALUES(cover_texts),
                 description=VALUES(description), hashtags=VALUES(hashtags),
                 comment_questions=VALUES(comment_questions), pinned_comment=VALUES(pinned_comment),
                 updated_at=CURRENT_TIMESTAMP""",
            (script_id,
             json.dumps(titles, ensure_ascii=False) if titles else None,
             json.dumps(cover_texts, ensure_ascii=False) if cover_texts else None,
             description or None,
             json.dumps(hashtags, ensure_ascii=False) if hashtags else None,
             json.dumps(comment_questions, ensure_ascii=False) if comment_questions else None,
             pinned_comment or None),
        )
        return cur.lastrowid
    finally:
        conn.close()


def get_assets(script_id: int) -> dict | None:
    conn = get_conn()
    try:
        return _row(conn.execute(
            "SELECT * FROM script_assets WHERE script_id = %s", (script_id,)
        ).fetchone())
    finally:
        conn.close()


def list_assets_for_scripts(script_ids: list[int]) -> dict[int, dict]:
    """批量取多个脚本的素材，返回 {script_id: assets}。"""
    if not script_ids:
        return {}
    conn = get_conn()
    try:
        placeholders = ",".join(["%s"] * len(script_ids))
        rows = conn.execute(
            f"SELECT * FROM script_assets WHERE script_id IN ({placeholders})",
            tuple(script_ids),
        ).fetchall()
        return {r["script_id"]: _row(r) for r in rows}
    finally:
        conn.close()
