"""Pi 项目助手可调用的业务工具。参数进入 repository 前再次校验。"""

from datetime import date
from threading import Lock
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from repositories import articles_repo, jobs_repo, research_cards_repo, scripts_repo, sources_repo, topics_repo
from services.script_jobs import request_script


class ToolError(Exception):
    pass


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Limit(Params):
    limit: int = Field(default=5, ge=1, le=20)


class TopicList(Limit):
    q: str = Field(default="", max_length=120, description="标题或一句话结论中的关键词")
    status: Literal["", "new", "selected", "scripted", "archived"] = ""
    date_from: date | None = None
    date_to: date | None = None


class TopicID(Params):
    topic_id: PositiveInt


class TopicStatus(TopicID):
    status: Literal["selected", "archived"]


class ArticleSearch(Limit):
    q: str = Field(default="", max_length=120)
    source_id: int = Field(default=0, ge=0)


class SourceList(Limit):
    q: str = Field(default="", max_length=120, description="来源名称关键词")


class JobList(Limit):
    status: Literal["", "pending", "running", "done", "failed"] = ""


class JobID(Params):
    job_id: PositiveInt


class StartJob(Params):
    type: Literal["fetch_all_sources", "fetch_source", "generate_topic"]
    source_id: PositiveInt | None = Field(default=None, description="仅 fetch_source 时必填")


class ScriptRequest(TopicID):
    platform: Literal["douyin", "xiaohongshu"] = "douyin"
    format: Literal["热点解读", "工具教程", "观点拆解"] = "热点解读"
    duration: int = Field(default=90, ge=10, le=600, description="脚本秒数")


def _columns(row: dict, *fields: str) -> dict:
    return {field: row.get(field) for field in fields}


def _topic(topic_id: int) -> dict:
    topic = topics_repo.get_topic(topic_id)
    if not topic:
        raise ToolError(f"找不到选题 #{topic_id}。")
    return topic


def list_topics(p: TopicList) -> list[dict]:
    if p.date_from and p.date_to and p.date_from > p.date_to:
        raise ToolError("开始日期必须早于或等于结束日期。")
    rows = topics_repo.list_topics(
        status=p.status, q=p.q, limit=p.limit,
        date_from=p.date_from.isoformat() if p.date_from else "",
        date_to=p.date_to.isoformat() if p.date_to else "",
    )
    return [_columns(row, "id", "title", "one_line_takeaway", "score", "status", "created_at") for row in rows]


def get_topic(p: TopicID) -> dict:
    row = _topic(p.topic_id)
    card = research_cards_repo.get_latest_card_for_topic(p.topic_id)
    scripts = scripts_repo.list_scripts_for_topic(p.topic_id)[:10]
    return {
        **_columns(row, "id", "title", "one_line_takeaway", "score", "status", "category"),
        "summary": (row.get("summary") or "")[:1200],
        "research_card": _columns(card, "id", "version", "needs_refresh", "confidence") if card else None,
        "scripts": [_columns(s, "id", "title", "platform", "format", "duration", "version") for s in scripts],
    }


def set_topic_status(p: TopicStatus) -> dict:
    topic = _topic(p.topic_id)
    if topic["status"] != p.status:
        topics_repo.set_topic_status(p.topic_id, p.status)
    label = "已选用" if p.status == "selected" else "已归档"
    return {
        "status": p.status, "topic_id": p.topic_id,
        "label": f"选题 #{p.topic_id} {label}", "url": f"/topics/{p.topic_id}",
    }


def search_articles(p: ArticleSearch) -> list[dict]:
    rows = articles_repo.search_articles(q=p.q, source_id=p.source_id, limit=p.limit)
    return [_columns(row, "id", "title", "source_name", "published_at", "status") for row in rows]


def list_sources(p: SourceList) -> list[dict]:
    query = p.q.casefold()
    rows = [row for row in sources_repo.list_sources() if query in row["name"].casefold()]
    return [_columns(row, "id", "name", "type", "level", "enabled", "last_fetched_at") for row in rows[:p.limit]]


def list_jobs(p: JobList) -> list[dict]:
    return [_columns(row, "id", "type", "status", "created_at", "attempts", "max_attempts")
            for row in jobs_repo.list_jobs(p.limit, status=p.status)]


def get_job(p: JobID) -> dict:
    row = jobs_repo.get_job(p.job_id)
    if not row:
        raise ToolError(f"找不到任务 #{p.job_id}。")
    return _columns(row, "id", "type", "status", "started_at", "finished_at", "attempts", "max_attempts")


_start_job_lock = Lock()
_job_labels = {
    "fetch_all_sources": "抓取所有启用来源",
    "fetch_source": "抓取指定来源",
    "generate_topic": "生成选题",
}


def start_job(p: StartJob) -> dict:
    if p.type == "fetch_source":
        source = sources_repo.get_source(p.source_id) if p.source_id else None
        if not source or not source["enabled"]:
            raise ToolError("请选择一个存在且已启用的来源 ID。")
    elif p.source_id is not None:
        raise ToolError("只有抓取指定来源时需要来源 ID。")

    payload = {"source_id": p.source_id} if p.source_id else {}
    with _start_job_lock:
        for job in jobs_repo.list_active_jobs_by_type(p.type):
            if job["payload"] == payload:
                return {"status": job["status"], "job_id": job["id"], "url": "/jobs",
                        "label": f"{_job_labels[p.type]} · 已有任务 #{job['id']}"}
        job_id = jobs_repo.enqueue(p.type, payload)
    return {"status": "queued", "job_id": job_id, "url": "/jobs",
            "label": f"{_job_labels[p.type]} · 任务 #{job_id} 已入队"}


def generate_script(p: ScriptRequest) -> dict:
    _topic(p.topic_id)
    state, job_id = request_script(p.topic_id, p.platform, p.format, p.duration)
    url = f"/topics/{p.topic_id}/scripts"
    labels = {
        "script_queued": f"脚本任务 #{job_id} 已入队",
        "script_active": f"已有脚本任务 #{job_id} 在队列中",
        "research_queued": f"资料卡任务 #{job_id} 已入队",
        "research_active": "已有资料卡任务在队列中",
    }
    if state.startswith("script_"):
        url += f"?job={job_id}"
    return {"status": state, "job_id": job_id, "topic_id": p.topic_id, "label": labels[state], "url": url,
            "platform": p.platform, "format": p.format, "duration": p.duration}


def retry_job(p: JobID) -> dict:
    if not jobs_repo.retry_job(p.job_id, failed_only=True):
        raise ToolError(f"任务 #{p.job_id} 不存在或当前状态无法重试，只有失败任务可以重试。")
    return {"status": "queued", "job_id": p.job_id, "label": f"任务 #{p.job_id} 已重新入队", "url": "/jobs"}


TOOLS: dict[str, tuple[str, type[Params], Callable]] = {
    "list_topics": ("查询选题，可按日期、状态或标题关键词筛选。当日选题优先，同日按得分排序。", TopicList, list_topics),
    "get_topic": ("查看一个选题的摘要、资料卡状态和脚本版本。", TopicID, get_topic),
    "set_topic_status": ("按用户明确指令，将指定选题标记为选用或归档。", TopicStatus, set_topic_status),
    "search_articles": ("按关键词或来源查询文章池，关键词可留空。", ArticleSearch, search_articles),
    "list_sources": ("查看来源库和抓取状态，可以按名称筛选。", SourceList, list_sources),
    "list_jobs": ("查询最近的后台任务，可按状态筛选。", JobList, list_jobs),
    "get_job": ("按 ID 查看一个后台任务的最新状态。", JobID, get_job),
    "start_job": ("按用户明确指令，提交抓取或生成今日选题的后台任务。", StartJob, start_job),
    "generate_script": ("按用户明确指令提交指定选题的脚本任务。缺资料卡时只准备资料卡。", ScriptRequest, generate_script),
    "retry_job": ("按用户明确指令重试指定失败任务。", JobID, retry_job),
}


def tool_specs() -> list[dict]:
    return [{"name": name, "description": description, "parameters": params.model_json_schema()}
            for name, (description, params, _) in TOOLS.items()]


def execute_tool(name: str, args: dict):
    if name not in TOOLS:
        raise ToolError("该工具不可用。")
    _, params, handler = TOOLS[name]
    try:
        validated = params.model_validate(args)
    except ValidationError as exc:
        fields = "、".join(str(error["loc"][0]) for error in exc.errors() if error["loc"])
        raise ToolError(f"工具参数不合法。请检查 {fields or '输入'}。") from exc
    return handler(validated)
