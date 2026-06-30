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
               VALUES (?, ?, 'pending', ?, CURRENT_TIMESTAMP)""",
            (job_type, json.dumps(payload, ensure_ascii=False) if payload else None, max_attempts),
        )
        return cur.lastrowid
    finally:
        conn.close()


def claim_next_job() -> dict | None:
    """原子抢占一条 pending 任务。利用 SQLite 单写特性保证单 worker 安全。"""
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM jobs
               WHERE status = 'pending' AND available_at <= CURRENT_TIMESTAMP
               ORDER BY id ASC LIMIT 1""",
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return None
        conn.execute(
            """UPDATE jobs
               SET status = 'running', locked_by = ?, started_at = CURRENT_TIMESTAMP,
                   heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (WORKER_ID, row["id"]),
        )
        conn.execute("COMMIT")
        job = dict(row)
        job["status"] = "running"
        job["locked_by"] = WORKER_ID
        job["payload"] = json.loads(job["payload_json"]) if job["payload_json"] else {}
        return job
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def heartbeat(job_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE jobs SET heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id,),
        )
    finally:
        conn.close()


def complete_job(job_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE jobs
               SET status = 'done', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                   error = NULL, locked_by = NULL
               WHERE id = ?""",
            (job_id,),
        )
    finally:
        conn.close()


def fail_job(job_id: int, error: str) -> None:
    """失败：attempts+1。未超 max_attempts 则重新置 pending 等待重试，否则 failed。"""
    conn = get_conn()
    try:
        job = _row(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
        if not job:
            return
        attempts = job["attempts"] + 1
        if attempts < job["max_attempts"]:
            # 指数退避：每次重试等待 attempts*30 秒，避免 LLM 配额/网络抖动时快速耗尽 max_attempts
            backoff = str(attempts * 30)
            conn.execute(
                """UPDATE jobs
                   SET status = 'pending', attempts = ?, error = ?, locked_by = NULL,
                       available_at = datetime('now', '+' || ? || ' seconds'),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (attempts, error[:500], backoff, job_id),
            )
        else:
            conn.execute(
                """UPDATE jobs
                   SET status = 'failed', attempts = ?, error = ?, finished_at = CURRENT_TIMESTAMP,
                       locked_by = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (attempts, error[:500], job_id),
            )
    finally:
        conn.close()


def recover_stale_jobs() -> int:
    """启动时把超时 running 任务恢复为 pending。"""
    conn = get_conn()
    try:
        timeout = settings.job_heartbeat_timeout_seconds
        cur = conn.execute(
            """UPDATE jobs
               SET status = 'pending', locked_by = NULL, updated_at = CURRENT_TIMESTAMP,
                   error = COALESCE(error || ' | ', '') || 'recovered from stale running'
               WHERE status = 'running'
                 AND heartbeat_at IS NOT NULL
                 AND CAST(strftime('%s', 'now') - strftime('%s', heartbeat_at) AS INTEGER) > ?""",
            (timeout,),
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
               WHERE id = ?""",
            (job_id,),
        )
    finally:
        conn.close()


def list_jobs(limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_recent_jobs(limit: int = 10) -> list[dict]:
    return list_jobs(limit)


def get_job(job_id: int) -> dict | None:
    conn = get_conn()
    try:
        return _row(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
    finally:
        conn.close()
