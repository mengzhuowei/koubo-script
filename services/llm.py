"""LLM 封装：所有 LLM 调用都经过这里。读取 llm_settings 与 creator_profile，不写死人设与模型。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from repositories.settings_repo import get_api_key, get_llm_settings, get_profile

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用或解析错误。"""


_client_cache: tuple[str, OpenAI] | None = None


def _build_client() -> OpenAI:
    """复用 OpenAI client（按 api_key 缓存），避免每次调用都新建 HTTP 连接池。

    通过 OPENAI_BASE_URL 环境变量支持兼容接口；provider 非 openai 时也走 OpenAI SDK 兼容协议。"""
    global _client_cache
    api_key = get_api_key()
    if not api_key:
        raise LLMError("未配置 API Key，请在 .env 中设置环境变量后再调用 LLM。")
    if _client_cache and _client_cache[0] == api_key:
        return _client_cache[1]
    client = OpenAI(api_key=api_key)
    _client_cache = (api_key, client)
    return client


def chat(messages: list[dict], *, json_mode: bool = False) -> str:
    """调用一次 chat completion，返回文本内容。"""
    llm = get_llm_settings()
    client = _build_client()
    # max_tokens 上限兜底：部分模型接口要求 ≤ 32768，
    # DB 里若被设成超大的值会让请求 400，这里统一截断。
    max_tokens = max(1, min(int(llm["max_tokens"]), 32768))
    kwargs: dict[str, Any] = {
        "model": llm["model"],
        "temperature": float(llm["temperature"]),
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        raise LLMError(f"LLM 调用失败：{type(e).__name__}: {e}") from e
    return resp.choices[0].message.content or ""


def chat_json(messages: list[dict]) -> dict:
    """调用 LLM 并解析为 JSON。失败时尝试抽取 JSON 片段，仍失败则抛 LLMError。"""
    text = chat(messages, json_mode=True)
    return parse_json(text)


def parse_json(text: str) -> dict:
    """从模型输出中解析 JSON，兼容 ```json 代码块包裹。"""
    if not text:
        raise LLMError("LLM 返回空内容，无法解析 JSON。")
    s = text.strip()
    # 去掉代码块包裹
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 尝试抽取第一个 {...}
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM 输出 JSON 解析失败：{e}；原文片段：{m.group(0)[:200]}") from e
    raise LLMError(f"LLM 输出无法解析为 JSON；原文：{text[:300]}")


def render_prompt(template: str, **kwargs: Any) -> str:
    """安全渲染 prompt 模板：用 str.replace 替换 {name} 占位符。

    避免使用 str.format()，因为 prompt 模板天然包含大量 JSON 字面量大括号，
    会被 format 误判为占位符抛 KeyError。
    """
    out = template
    for key, val in kwargs.items():
        out = out.replace("{" + key + "}", "" if val is None else str(val))
    return out


def get_profile_context() -> str:
    """生成人设上下文文本，供 prompt 拼接。人设内容从数据库读取。"""
    p = get_profile()
    parts = [f"你是「{p.get('name', '')}」。"]
    if p.get("positioning"):
        parts.append(f"定位：{p['positioning']}")
    if p.get("target_audience"):
        parts.append(f"目标受众：{p['target_audience']}")
    if p.get("tone"):
        parts.append(f"语气：{p['tone']}")
    if p.get("content_boundary"):
        parts.append(f"内容边界：{p['content_boundary']}")
    if p.get("default_cta"):
        parts.append(f"默认 CTA：{p['default_cta']}")
    return "\n".join(parts)
