"""MySQL 连接与初始化。所有 repository 共用 get_conn()。

使用 pymysql + DictCursor，autocommit=True 匹配原有 sqlite3 的 isolation_level=None 行为。
get_conn() 返回一个轻量包装 _Conn，提供 conn.execute(sql, args) -> cursor 的便捷接口，
让 repository 层沿用原 sqlite3 的 conn.execute(...).fetchone() 写法，无需逐处改造。
显式事务（claim_next_job）用 conn.begin() / conn.commit() / conn.rollback() 包裹。
"""
import logging

import pymysql
from pymysql.cursors import DictCursor

from config import BASE_DIR, settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = BASE_DIR / "migrations"

# MySQL "已存在"错误码，重复执行 migration 时跳过这些错误实现幂等。
# 1050: Table already exists / 1060: Column already exists / 1061: Duplicate key name
# 1091: Can't DROP (索引/列不存在) / 1054: Unknown column（防御性兜底）
_IDEMPOTENT_ERRNOS = {1050, 1060, 1061, 1091}


class _Conn:
    """pymysql 连接的轻量包装。

    - execute(sql, args=None): 创建 cursor、执行、返回 cursor，匹配 sqlite3 conn.execute 用法
    - begin/commit/rollback: 透传事务控制
    - 其他属性（close 等）通过 __getattr__ 透传给底层连接
    """

    def __init__(self, conn: pymysql.connections.Connection):
        self._conn = conn

    def execute(self, sql: str, args=None) -> DictCursor:
        cur = self._conn.cursor()
        cur.execute(sql, args)
        return cur  # type: ignore[return-value]

    def cursor(self) -> DictCursor:
        return self._conn.cursor()

    def begin(self) -> None:
        self._conn.begin()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def get_conn() -> _Conn:
    """返回一个启用 DictCursor 与 autocommit 的连接包装。调用方负责关闭。

    - autocommit=True：单条语句自动提交，匹配原 sqlite3 isolation_level=None 语义
    - DictCursor：返回 dict，匹配原 sqlite3.Row 的列名访问
    - time_zone='+00:00'：会话时区设为 UTC，让 CURRENT_TIMESTAMP 返回 UTC，匹配原 SQLite 行为
    """
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=DictCursor,
    )
    with conn.cursor() as cur:
        # 统一用 UTC 存时间，与原 SQLite CURRENT_TIMESTAMP 行为一致
        cur.execute("SET SESSION time_zone = '+00:00'")
        # 锁等待超时 30s，对应原 sqlite3 timeout=30
        cur.execute("SET SESSION innodb_lock_wait_timeout = 30")
    return _Conn(conn)


def _split_sql_statements(sql: str) -> list[str]:
    """把 migration SQL 按 ';' 拆成单条语句。

    pymysql 没有 executescript，需逐条执行。简单处理：按 ; 拆分，
    跳过空语句和 -- 注释行。不处理字符串内的分号（migration 文件不涉及）。
    """
    # 先按行去掉 -- 注释
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        # 保留行内 -- 之前的内容
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    text = "\n".join(lines)
    # 按 ; 拆分
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def init_db() -> None:
    """按版本执行 migrations 下的 SQL。可重复执行（幂等）。

    通过 schema_migrations 表记录已应用版本。即便某次执行中途失败导致版本未记录，
    重试时也会对 1050/1060/1061/1091 等"已存在/不存在"错误逐条跳过，
    不会因 CREATE INDEX 重复而崩溃。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
            )
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = sql_file.stem
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
                )
                if cur.fetchone():
                    continue
                logger.info("执行 migration: %s", version)
                for stmt in _split_sql_statements(sql_file.read_text(encoding="utf-8")):
                    try:
                        cur.execute(stmt)
                    except pymysql.err.OperationalError as e:
                        # 幂等保护：表/列/索引已存在或不存在时跳过，其余错误正常抛出
                        if e.args and e.args[0] in _IDEMPOTENT_ERRNOS:
                            logger.debug("migration %s 跳过已存在对象: %s", version, e.args[1])
                            continue
                        raise
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                )
                logger.info("migration %s 完成", version)
    finally:
        conn.close()
