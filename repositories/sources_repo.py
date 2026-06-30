"""来源库 CRUD。"""
from repositories.db import get_conn


def _row(r):
    return dict(r) if r else None


def list_sources() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM sources ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_enabled_sources() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY level ASC, id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_source(source_id: int) -> dict | None:
    conn = get_conn()
    try:
        return _row(conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone())
    finally:
        conn.close()


def create_source(*, name: str, url: str, type: str, level: str = "B",
                  keywords: str = "", enabled: int = 1) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO sources (name, url, type, level, keywords, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, url, type, level, keywords or None, 1 if enabled else 0),
        )
        return cur.lastrowid
    finally:
        conn.close()


def update_source(source_id: int, *, name: str, url: str, type: str, level: str = "B",
                  keywords: str = "", enabled: int = 1) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE sources
               SET name=?, url=?, type=?, level=?, keywords=?, enabled=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (name, url, type, level, keywords or None, 1 if enabled else 0, source_id),
        )
    finally:
        conn.close()


def toggle_source(source_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE sources SET enabled = 1 - enabled, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (source_id,),
        )
    finally:
        conn.close()


def update_fetch_state(source_id: int, *, last_error: str | None = None,
                       last_cursor: str | None = None, last_seen_item_id: str | None = None) -> None:
    """每次抓取后刷新状态：last_fetched_at 始终更新为当前时间。"""
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE sources
               SET last_fetched_at = CURRENT_TIMESTAMP,
                   last_error = ?,
                   last_cursor = COALESCE(?, last_cursor),
                   last_seen_item_id = COALESCE(?, last_seen_item_id),
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (last_error, last_cursor, last_seen_item_id, source_id),
        )
    finally:
        conn.close()
