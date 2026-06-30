"""SQLite 连接与初始化。所有 repository 共用 get_conn()。"""
import sqlite3
from pathlib import Path

from config import BASE_DIR, settings

MIGRATIONS_DIR = BASE_DIR / "migrations"


def get_conn() -> sqlite3.Connection:
    """返回一个启用外键与 Row 工厂的连接。调用方负责关闭。"""
    conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """创建数据目录并按版本执行 migrations 下的 SQL。可重复执行。

    通过 schema_migrations 表记录已应用版本，避免将来引入 ALTER 类迁移时重复执行。
    首次引入版本表时，已有的 001_init.sql 因全部使用 IF NOT EXISTS 仍可安全重跑。"""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_file.stem
            if conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            ).fetchone():
                continue
            conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
    finally:
        conn.close()
