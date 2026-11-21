"""启动 Pi 对话进程并在当前应用中执行项目工具。"""

import json
import logging
import subprocess
from collections.abc import Generator
from contextlib import closing
from datetime import date
from threading import BoundedSemaphore, Event, Timer
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from config import BASE_DIR, settings
from repositories.settings_repo import get_api_key, get_llm_settings, get_openai_base_url
from services.project_tools import ToolError, execute_tool, tool_specs

logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(4)
_agent_dir = BASE_DIR / "pi-agent"
CHAT_STREAM_TYPE = "application/x-ndjson"
_tool_labels = {
    "list_topics": "查询选题",
    "get_topic": "读取选题详情",
    "set_topic_status": "更新选题状态",
    "search_articles": "检索文章",
    "list_sources": "查询来源",
    "list_jobs": "查询后台任务",
    "get_job": "读取任务状态",
    "start_job": "提交后台任务",
    "generate_script": "提交脚本生成请求",
    "retry_job": "重试后台任务",
}
_errors = {
    "runtime_error": "项目助手未能启动，请检查 Node.js 和 Pi 依赖。",
    "auth_error": "模型接口拒绝了认证。请核对 .env 中的 API Key 和接口地址是否匹配。",
    "model_error": "模型未能完成回复，请检查设置中的模型、接口地址和工具调用支持。",
    "turn_limit": "本轮已达到处理次数上限，可以继续询问。",
    "timeout": "项目助手等待超时，可以查看任务列表后继续。",
}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


def _send(pipe, event: dict) -> None:
    pipe.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    pipe.flush()


def _reply_event(reply: str, *, ok: bool = False, receipts: list | None = None) -> dict:
    return {"type": "reply", "result": {"reply": reply, "ok": ok, "receipts": receipts or []}}


def _run_chat_events(payload: dict) -> Generator[dict, None, None]:
    receipts = []
    reply = ""
    error = "runtime_error"
    timed_out = Event()
    try:
        with subprocess.Popen(
            ["node", str(_agent_dir / "chat.mjs")],
            cwd=_agent_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as process:
            def kill_on_timeout():
                if process.poll() is None:
                    timed_out.set()
                    process.kill()

            timer = Timer(90, kill_on_timeout)
            timer.daemon = True
            timer.start()
            try:
                _send(process.stdin, payload)
                previous_actions = {}
                step_id = 0
                for line in process.stdout:
                    event = json.loads(line)
                    if event["type"] == "reply":
                        reply = event["reply"][:5000]
                        break
                    if event["type"] == "error":
                        error = event["code"]
                        break
                    if event["type"] != "tool":
                        raise ValueError("Invalid Pi event")

                    name, args = event["name"], event["args"]
                    step_id += 1
                    step = {"type": "tool", "id": step_id, "label": _tool_labels.get(name, "调用项目工具")}
                    yield {**step, "state": "running"}

                    action_key = json.dumps([name, args], sort_keys=True)
                    receipt = None
                    try:
                        value = previous_actions.get(action_key)
                        if value is None:
                            value = execute_tool(name, args)
                            if isinstance(value, dict) and "url" in value:
                                previous_actions[action_key] = value
                                receipt = {"label": value["label"], "url": value["url"]}
                                receipts.append(receipt)
                        result = {"value": value}
                    except ToolError as exc:
                        result = {"error": str(exc)}
                    except Exception:
                        logger.exception("Project agent tool failed: %s", name)
                        result = {"error": "项目操作失败。请在工作台检查后再试。"}

                    if "error" in result:
                        yield {**step, "state": "failed", "detail": result["error"]}
                    else:
                        detail = "已返回结果"
                        if isinstance(value, list):
                            detail = f"返回 {len(value)} 条记录"
                        elif isinstance(value, dict) and value.get("label"):
                            detail = value["label"]
                        finished = {**step, "state": "done", "detail": detail}
                        if receipt:
                            finished["receipt"] = receipt
                        yield finished
                    _send(process.stdin, result)
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
    except (OSError, ValueError, KeyError):
        logger.warning("Project agent subprocess could not finish")

    if timed_out.is_set():
        error = "timeout"
    yield _reply_event(reply or _errors.get(error, _errors["runtime_error"]), ok=bool(reply), receipts=receipts)


def _final_reply(events: Generator[dict, None, None]) -> dict:
    with closing(events):
        for event in events:
            if event["type"] == "reply":
                return event["result"]
    raise RuntimeError("Project agent ended without a reply")


def _run_chat(payload: dict) -> dict:
    return _final_reply(_run_chat_events(payload))


def _chat_events(request: ChatRequest) -> Generator[dict, None, None]:
    if not _slots.acquire(blocking=False):
        yield _reply_event("项目助手正在处理其他请求，请稍后再试。")
        return
    try:
        api_key = get_api_key()
        if not api_key:
            yield _reply_event("请在 .env 配置模型 API Key 后重启工作台。")
            return
        model = get_llm_settings()
        yield from _run_chat_events({
            **request.model_dump(),
            "tools": tool_specs(),
            "today": date.today().isoformat(),
            "settings": {
                "api_key": api_key,
                "base_url": get_openai_base_url(),
                "model": model.get("model") or settings.default_llm_model,
                "temperature": float(model.get("temperature", 0.4)),
                "max_tokens": max(1, min(int(model.get("max_tokens", 2000)), 4000)),
            },
        })
    finally:
        _slots.release()


def chat(request: ChatRequest) -> dict:
    return _final_reply(_chat_events(request))


def stream_chat(request: ChatRequest) -> Generator[str, None, None]:
    with closing(_chat_events(request)) as events:
        for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"
