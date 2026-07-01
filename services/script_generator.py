"""脚本生成：基于选题内容卡与设置页人设，调用 LLM 生成口播脚本并入库（版本递增）。"""
from __future__ import annotations

import logging

from config import BASE_DIR
from repositories.scripts_repo import create_script, next_version
from repositories.topics_repo import get_topic_with_facts_and_articles, set_topic_status
from services.llm import LLMError, chat_json, get_profile_context, render_prompt

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "script_koubo.md"


def generate_script_for_topic(*, topic_id: int, platform: str, fmt: str, duration: int) -> int:
    """生成脚本并入库。返回 script_id。LLM 不可用抛 LLMError 供 job 标记失败。"""
    topic = get_topic_with_facts_and_articles(topic_id)
    if not topic:
        raise ValueError(f"topic {topic_id} 不存在")

    template = PROMPT_PATH.read_text(encoding="utf-8")
    facts_text = "\n".join(
        f"- {f['claim']}（来源：{f['source_url']}）" for f in topic.get("facts", [])
    ) or "（无）"

    prompt = render_prompt(
        template,
        profile=get_profile_context(),
        title=topic.get("title") or "",
        one_line_takeaway=topic.get("one_line_takeaway") or "",
        summary=topic.get("summary") or "",
        actionable_value=topic.get("actionable_value") or "",
        risk_notes=topic.get("risk_notes") or "",
        facts=facts_text,
        platform=platform,
        format=fmt,
        duration=duration,
    )

    data = chat_json([{"role": "user", "content": prompt}])

    version = next_version(topic_id, platform, fmt, duration)
    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]

    script_id = create_script(
        topic_id=topic_id,
        platform=platform,
        fmt=fmt,
        duration=duration,
        version=version,
        title=data.get("title"),
        hook=data.get("hook"),
        body=data.get("body") or "",
        cta=data.get("cta"),
        cover_text=data.get("cover_text"),
        description=data.get("description"),
        hashtags=[str(h) for h in hashtags],
    )
    logger.info("生成脚本 script_id=%s topic_id=%s v%s", script_id, topic_id, version)
    # 脚本生成成功后将选题标记为 scripted，便于选题库筛选"已写脚本"的选题
    set_topic_status(topic_id, "scripted")
    return script_id
