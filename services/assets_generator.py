"""发布素材包生成：基于脚本生成标题/封面/简介/标签/评论引导/置顶评论。手动触发，消耗 LLM。"""
from __future__ import annotations

import logging

from config import BASE_DIR
from repositories.assets_repo import upsert_assets
from repositories.scripts_repo import get_script
from services.llm import LLMError, chat_json, get_profile_context, render_prompt

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "assets.md"
_prompt_cache: str | None = None
_prompt_mtime: float = 0


def _load_prompt() -> str:
    global _prompt_cache, _prompt_mtime
    mtime = PROMPT_PATH.stat().st_mtime
    if _prompt_cache is None or mtime > _prompt_mtime:
        _prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
        _prompt_mtime = mtime
    return _prompt_cache


def generate_assets_for_script(script_id: int) -> int:
    """为脚本生成发布素材包并覆盖入库。返回 script_id。LLM 不可用抛 LLMError 供 job 标记失败。"""
    script = get_script(script_id)
    if not script:
        raise ValueError(f"script {script_id} 不存在")

    template = _load_prompt()
    prompt = render_prompt(
        template,
        profile=get_profile_context(),
        title=script.get("title") or "",
        platform=script.get("platform") or "",
        format=script.get("format") or "",
        duration=script.get("duration") or 0,
        body=script.get("body") or "",
    )

    data = chat_json([{"role": "user", "content": prompt}], temperature=0.9)

    def _as_list(v):
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v] if v else []

    upsert_assets(
        script_id=script_id,
        titles=_as_list(data.get("titles")),
        cover_texts=_as_list(data.get("cover_texts")),
        description=data.get("description") or "",
        hashtags=_as_list(data.get("hashtags")),
        comment_questions=_as_list(data.get("comment_questions")),
        pinned_comment=data.get("pinned_comment") or "",
    )
    logger.info("生成素材包 script_id=%s", script_id)
    return script_id
