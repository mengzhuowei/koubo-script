"""脚本生成：基于选题内容卡、资料卡与设置页人设，调用 LLM 生成口播脚本并入库（版本递增）。"""
from __future__ import annotations

import logging

from config import BASE_DIR
from repositories.scripts_repo import create_script, next_version
from repositories.topics_repo import get_topic_with_facts_and_articles, set_topic_status
from repositories.research_cards_repo import get_latest_card_for_topic
from services.llm import LLMError, chat_json, get_profile_context, render_prompt

logger = logging.getLogger(__name__)

PROMPT_PATH = BASE_DIR / "prompts" / "script_koubo.md"
_prompt_cache: str | None = None
_prompt_mtime: float = 0


def _load_prompt() -> str:
    global _prompt_cache, _prompt_mtime
    mtime = PROMPT_PATH.stat().st_mtime
    if _prompt_cache is None or mtime > _prompt_mtime:
        _prompt_cache = PROMPT_PATH.read_text(encoding="utf-8")
        _prompt_mtime = mtime
    return _prompt_cache


def generate_script_for_topic(*, topic_id: int, platform: str, fmt: str, duration: int) -> int:
    """生成脚本并入库。返回 script_id。LLM 不可用抛 LLMError 供 job 标记失败。

    优先使用资料卡作为脚本上下文（core_facts / efficiency_angle / workflow_example / risk_notes），
    资料卡不存在时兜底走原流程（仅用选题内容卡 + facts）。
    """
    topic = get_topic_with_facts_and_articles(topic_id)
    if not topic:
        raise ValueError(f"topic {topic_id} 不存在")

    template = _load_prompt()
    facts_text = "\n".join(
        f"- {f['claim']}（来源：{f['source_url']}）" for f in topic.get("facts", [])
    ) or "（无）"

    # 读取最新资料卡，拼接资料卡上下文
    research_card = get_latest_card_for_topic(topic_id)
    research_context = _build_research_context(research_card) if research_card else "（无资料卡，仅基于选题内容卡生成）"
    research_card_id = research_card["id"] if research_card else None

    prompt = render_prompt(
        template,
        profile=get_profile_context(),
        title=topic.get("title") or "",
        one_line_takeaway=topic.get("one_line_takeaway") or "",
        summary=topic.get("summary") or "",
        actionable_value=topic.get("actionable_value") or "",
        risk_notes=topic.get("risk_notes") or "",
        facts=facts_text,
        research_context=research_context,
        platform=platform,
        format=fmt,
        duration=duration,
        word_count_min=duration * 4,
        word_count_max=duration * 5,
    )

    data = chat_json([{"role": "user", "content": prompt}])

    version = next_version(topic_id, platform, fmt, duration)
    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]

    # 生成后校验：body 字数是否在目标范围内
    body_text = data.get("body") or ""
    hook_text = data.get("hook") or ""
    cta_text = data.get("cta") or ""
    total_chars = len(body_text) + len(hook_text) + len(cta_text)
    word_count_min = duration * 4
    word_count_max = duration * 5
    if total_chars < word_count_min:
        logger.warning("脚本 body+hook+cta 共 %d 字，低于目标 %d～%d 字（duration=%ds），视频会偏短",
                       total_chars, word_count_min, word_count_max, duration)
    elif total_chars > word_count_max:
        logger.warning("脚本 body+hook+cta 共 %d 字，超过目标 %d～%d 字（duration=%ds），视频会偏长",
                       total_chars, word_count_min, word_count_max, duration)

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
        research_card_id=research_card_id,
    )
    logger.info("生成脚本 script_id=%s topic_id=%s v%s research_card_id=%s",
                script_id, topic_id, version, research_card_id)
    # 脚本生成成功后将选题标记为 scripted，便于选题库筛选"已写脚本"的选题
    set_topic_status(topic_id, "scripted")
    return script_id


def _build_research_context(card: dict) -> str:
    """把资料卡关键字段拼成脚本 prompt 用的文本块。"""
    c = card.get("card") or {}
    parts = []
    if c.get("research_summary"):
        parts.append(f"资料摘要：{c['research_summary']}")
    core_facts = c.get("core_facts") or []
    if core_facts:
        lines = [f"- {f.get('claim', '')}（来源：{f.get('source_url', '-')}，置信度：{f.get('confidence', '-')}）"
                 for f in core_facts]
        parts.append("关键事实：\n" + "\n".join(lines))
    if c.get("efficiency_angle"):
        parts.append(f"效率角度：{c['efficiency_angle']}")
    if c.get("workflow_example"):
        parts.append(f"工作流案例：{c['workflow_example']}")
    risk = c.get("risk_notes") or []
    if risk:
        parts.append("风险提醒：\n- " + "\n- ".join(risk))
    hooks = c.get("script_hooks") or []
    if hooks:
        parts.append("开头钩子参考：\n- " + "\n- ".join(hooks))
    if c.get("copyable_prompt"):
        parts.append(f"可复制提示词：{c['copyable_prompt']}")
    sq = c.get("source_quality") or {}
    if sq:
        parts.append(f"来源质量：本地 {sq.get('local_source_count', 0)} 篇，"
                     f"联网 {sq.get('web_source_count', 0)} 篇，"
                     f"含官方源 {'是' if sq.get('has_official_source') else '否'}，"
                     f"整体置信度 {sq.get('overall_confidence', '-')}")
    return "\n\n".join(parts) if parts else "（资料卡字段为空）"
