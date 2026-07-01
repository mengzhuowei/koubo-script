"""jobs 队列 repository：入队、抢占、心跳、完成/失败、恢复超时任务。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from config import settings
from repositories.db import get_conn

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"


def _row(r):
    return dict(r) if r else None


def enqueue(job_type: str, payload: dict | None = None, max_attempts: int = 3) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO jobs (type, payload_json, status, max_attempts, available_at)
               VALUES (%s, %s, 'pending', %s, CURRENT_TIMESTAMP)""",
            (job_type, json.dumps(payload, ensure_ascii=False) if payload else None, max_attempts),
        )
        return cur.lastrowid
    finally:
        conn.close()


def claim_next_job() -> dict | None:
    """原子抢占一条 pending 任务。

    用 SELECT ... FOR UPDATE SKIP LOCKED 在事务内锁定选中行，保证多 worker 并发安全。
    SKIP LOCKED 让被其他 worker 锁住的行自动跳过，不阻塞。MySQL 8.0+ 支持。
    """
    conn = get_conn()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM jobs
                   WHERE status = 'pending' AND available_at <= CURRENT_TIMESTAMP
                   ORDER BY id ASC
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED"""
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            cur.execute(
                """UPDATE jobs
                   SET status = 'running', locked_by = %s, started_at = CURRENT_TIMESTAMP,
                       heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s""",
                (WORKER_ID, row["id"]),
            )
        conn.commit()
        job = dict(row)
        job["status"] = "running"
        job["locked_by"] = WORKER_ID
        job["payload"] = json.loads(job["payload_json"]) if job["payload_json"] else {}
        return job
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def complete_job(job_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE jobs
               SET status = 'done', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                   error = NULL, locked_by = NULL
               WHERE id = %s""",
            (job_id,),
        )
    finally:
        conn.close()


def fail_job(job_id: int, error: str) -> None:
    """失败：attempts+1。未超 max_attempts 则重新置 pending 等待重试，否则 failed。

    SELECT-then-UPDATE 用事务 + FOR UPDATE 包裹，与 claim_next_job 保持一致的并发严谨度，
    避免（未来多 worker 时）读到的 attempts 在写回前被其他 worker 改写。
    """
    conn = get_conn()
    try:
        conn.begin()
        job = _row(conn.execute(
            "SELECT * FROM jobs WHERE id = %s FOR UPDATE", (job_id,)
        ).fetchone())
        if not job:
            conn.rollback()
            return
        attempts = job["attempts"] + 1
        if attempts < job["max_attempts"]:
            # 指数退避：每次重试等待 attempts*30 秒，避免 LLM 配额/网络抖动时快速耗尽 max_attempts
            backoff = attempts * 30
            conn.execute(
                """UPDATE jobs
                   SET status = 'pending', attempts = %s, error = %s, locked_by = NULL,
                       available_at = DATE_ADD(NOW(), INTERVAL %s SECOND),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s""",
                (attempts, error[:500], backoff, job_id),
            )
        else:
            conn.execute(
                """UPDATE jobs
                   SET status = 'failed', attempts = %s, error = %s, finished_at = CURRENT_TIMESTAMP,
                       locked_by = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s""",
                (attempts, error[:500], job_id),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def recover_stale_jobs() -> int:
    """启动时把所有 running 任务恢复为 pending。

    单 worker 架构：进程重启意味着上一个 worker 已死，它持有的所有 running 任务
    都失去了执行者，必须立即恢复为 pending 让新 worker 重新捡起。
    不依赖心跳超时判断——那会导致重启后 5 分钟内任务一直卡死。
    """
    conn = get_conn()
    try:
        cur = conn.execute(
            """UPDATE jobs
               SET status = 'pending', locked_by = NULL, updated_at = CURRENT_TIMESTAMP,
                   error = CONCAT(COALESCE(CONCAT(error, ' | '), ''), 'recovered from stale running')
               WHERE status = 'running'""",
        )
        return cur.rowcount
    finally:
        conn.close()


def retry_job(job_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE jobs
               SET status = 'pending', attempts = 0, error = NULL, locked_by = NULL,
                   available_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (job_id,),
        )
    finally:
        conn.close()


def list_jobs(limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT %s", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_active_jobs_by_type(job_type: str) -> list[dict]:
    """返回某类型所有 pending/running 任务（含 payload 解析）。供调度器去重使用。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE type = %s AND status IN ('pending', 'running')",
            (job_type,),
        ).fetchall()
        jobs = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload_json"]) if d["payload_json"] else {}
            jobs.append(d)
        return jobs
    finally:
        conn.close()


def list_recent_jobs(limit: int = 10) -> list[dict]:
    return list_jobs(limit)


def get_job(job_id: int) -> dict | None:
    conn = get_conn()
    try:
        return _row(conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone())
    finally:
        conn.close()


def latest_job_by_payload(job_type: str, payload_key: str, payload_value) -> dict | None:
    """返回某类型且 payload 中含指定 key=value 的最新一条 job（任意状态）。

    用于页面跟踪"这个 topic/script 的生成任务进展"。payload_json 是 JSON 文本，
    用 JSON_EXTRACT 提取字段比较，匹配失败（字段不存在/类型不符）不会命中。
    """
    conn = get_conn()
    try:
        return _row(conn.execute(
            """SELECT * FROM jobs
               WHERE type = %s AND JSON_EXTRACT(payload_json, %s) = %s
               ORDER BY id DESC LIMIT 1""",
            (job_type, f"$.{payload_key}", payload_value),
        ).fetchone())
    finally:
        conn.close()
