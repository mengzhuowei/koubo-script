"""来源库 CRUD。"""
from repositories.db import get_conn


def _row(r):
    return dict(r) if r else None


def list_sources() -> list[dict]:
    conn = get_conn()
    try:
        # 排序：启用排前（enabled DESC），再按层级（S<A<B<C，用 FIELD 固定顺序），最后 id 兜底
        rows = conn.execute(
            """SELECT * FROM sources
               ORDER BY enabled DESC,
                        FIELD(level, 'S', 'A', 'B', 'C') ASC,
                        id ASC"""
        ).fetchall()
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


def list_due_sources() -> list[dict]:
    """返回已启用且到达抓取间隔的来源。

    判定条件：last_fetched_at 为空（从未抓过），或距上次抓取已超过 fetch_interval_minutes。
    每个源可独立配置间隔，默认 1440 分钟（24h）。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM sources
               WHERE enabled = 1
                 AND (last_fetched_at IS NULL
                      OR last_fetched_at < DATE_SUB(NOW(), INTERVAL fetch_interval_minutes MINUTE))
               ORDER BY FIELD(level, 'S', 'A', 'B', 'C') ASC, id ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_source(source_id: int) -> dict | None:
    conn = get_conn()
    try:
        return _row(conn.execute("SELECT * FROM sources WHERE id = %s", (source_id,)).fetchone())
    finally:
        conn.close()


def create_source(*, name: str, url: str, type: str, level: str = "B",
                  keywords: str = "", enabled: int = 1) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO sources (name, url, type, level, keywords, enabled)
               VALUES (%s, %s, %s, %s, %s, %s)""",
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
               SET name=%s, url=%s, type=%s, level=%s, keywords=%s, enabled=%s, updated_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (name, url, type, level, keywords or None, 1 if enabled else 0, source_id),
        )
    finally:
        conn.close()


def toggle_source(source_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE sources SET enabled = 1 - enabled, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
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
                   last_error = %s,
                   last_cursor = COALESCE(%s, last_cursor),
                   last_seen_item_id = COALESCE(%s, last_seen_item_id),
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (last_error, last_cursor, last_seen_item_id, source_id),
        )
    finally:
        conn.close()
