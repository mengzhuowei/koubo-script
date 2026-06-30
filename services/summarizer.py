"""文章级摘要：调用 LLM 生成 summary 与 key_points，供选题生成复用。"""
from __future__ import annotations

import logging

from services.llm import LLMError, chat_json

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """请为以下文章生成摘要和关键点，用于后续选题生成。

文章标题：{title}
正文（截断）：
{content}

只输出 JSON：
{{
  "summary": "80-150 字中文摘要",
  "key_points": ["关键点1", "关键点2", "关键点3"]
}}
"""


def summarize_article(article: dict) -> tuple[str, list[str]]:
    """返回 (summary, key_points)。LLM 不可用时退化为截取正文。"""
    title = article.get("title") or ""
    content = (article.get("content_text") or "")[:4000]
    if not content:
        return ("", [])

    try:
        data = chat_json([{
            "role": "user",
            "content": _SUMMARY_PROMPT.format(title=title, content=content),
        }])
        summary = (data.get("summary") or "").strip()
        key_points = data.get("key_points") or []
        if isinstance(key_points, str):
            key_points = [key_points]
        return summary, [str(k) for k in key_points][:8]
    except LLMError as e:
        logger.warning("summarize_article LLM 失败，退化截取：%s", e)
        return content[:150], []
