"""人设与模型设置 repository。所有 LLM 调用与脚本生成都从这里读取当前配置。"""
from __future__ import annotations

import os

from config import settings as app_settings
from repositories.db import get_conn


def _row(r):
    return dict(r) if r else None


def ensure_defaults() -> None:
    """首次启动时写入默认人设与模型配置。已存在则不覆盖。"""
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM creator_profile LIMIT 1").fetchone():
            conn.execute(
                """INSERT INTO creator_profile
                   (name, positioning, target_audience, tone, content_boundary, default_cta)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    "AI效率教练",
                    "把复杂 AI Agent 技术拆成普通人也能跑通的效率工作流",
                    "内容创作者、知识博主、独立开发者、小团队老板、AI工具新手",
                    "直接、实用、教练式、有步骤感",
                    "不做空泛新闻，不做参数堆砌，不制造焦虑",
                    "关注我，我会继续把复杂 AI Agent 技术拆成你能直接用的效率工作流",
                ),
            )
        if not conn.execute("SELECT 1 FROM llm_settings LIMIT 1").fetchone():
            conn.execute(
                """INSERT INTO llm_settings (provider, model, temperature, max_tokens, api_key_env_var)
                   VALUES (%s, %s, 0.4, 2000, 'OPENAI_API_KEY')""",
                (app_settings.default_llm_provider, app_settings.default_llm_model or "gpt-4o-mini"),
            )
    finally:
        conn.close()


def get_profile() -> dict:
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM creator_profile ORDER BY id ASC LIMIT 1").fetchone()
        return _row(r) or {}
    finally:
        conn.close()


def update_profile(*, name: str, positioning: str, target_audience: str, tone: str,
                   content_boundary: str, default_cta: str) -> None:
    conn = get_conn()
    try:
        existing = conn.execute("SELECT id FROM creator_profile ORDER BY id ASC LIMIT 1").fetchone()
        if existing:
            conn.execute(
                """UPDATE creator_profile
                   SET name=%s, positioning=%s, target_audience=%s, tone=%s, content_boundary=%s, default_cta=%s,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=%s""",
                (name, positioning, target_audience, tone, content_boundary, default_cta, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO creator_profile
                   (name, positioning, target_audience, tone, content_boundary, default_cta)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (name, positioning, target_audience, tone, content_boundary, default_cta),
            )
    finally:
        conn.close()


def get_llm_settings() -> dict:
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM llm_settings ORDER BY id ASC LIMIT 1").fetchone()
        return _row(r) or {}
    finally:
        conn.close()


def update_llm_settings(*, provider: str, model: str, temperature: float, max_tokens: int) -> None:
    conn = get_conn()
    try:
        existing = conn.execute("SELECT id FROM llm_settings ORDER BY id ASC LIMIT 1").fetchone()
        if existing:
            conn.execute(
                """UPDATE llm_settings
                   SET provider=%s, model=%s, temperature=%s, max_tokens=%s, updated_at=CURRENT_TIMESTAMP
                   WHERE id=%s""",
                (provider, model, float(temperature), int(max_tokens), existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO llm_settings (provider, model, temperature, max_tokens, api_key_env_var)
                   VALUES (%s, %s, %s, %s, 'OPENAI_API_KEY')""",
                (provider, model, float(temperature), int(max_tokens)),
            )
    finally:
        conn.close()


def is_api_key_configured() -> bool:
    llm = get_llm_settings()
    env_var = llm.get("api_key_env_var") or "OPENAI_API_KEY"
    return bool(os.environ.get(env_var))


def get_api_key() -> str:
    llm = get_llm_settings()
    env_var = llm.get("api_key_env_var") or "OPENAI_API_KEY"
    return os.environ.get(env_var, "")
