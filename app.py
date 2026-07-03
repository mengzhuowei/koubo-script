"""口播雷达 MVP 入口。启动命令：python app.py"""
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import BASE_DIR, settings
from repositories.db import init_db
from repositories.jobs_repo import recover_stale_jobs
from repositories.settings_repo import ensure_defaults
from workers.job_runner import start_worker
from workers.scheduler import start_scheduler, stop_scheduler

# 配置 root logger：默认 INFO，可通过环境变量 LOG_LEVEL 调成 DEBUG 看详细抓取日志
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化数据库、恢复卡死任务、写入默认人设/模型、拉起 worker 与调度器。"""
    init_db()
    ensure_defaults()
    recover_stale_jobs()
    start_worker()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="口播雷达", lifespan=lifespan)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def render(request: Request, name: str, ctx: dict | None = None) -> HTMLResponse:
    context = {"active": ""}
    if ctx:
        context.update(ctx)
    return templates.TemplateResponse(request, name, context)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    from repositories.articles_repo import count_articles_today
    from repositories.topics_repo import count_topics_today, list_top_topics
    from repositories.scripts_repo import list_recent_scripts
    from repositories.jobs_repo import list_recent_jobs

    ctx = {
        "active": "dashboard",
        "articles_today": count_articles_today(),
        "topics_today": count_topics_today(),
        "top_topics": list_top_topics(10),
        "recent_scripts": list_recent_scripts(5),
        "recent_jobs": list_recent_jobs(10),
    }
    return render(request, "dashboard.html", ctx)


# ---------- 来源库 ----------
@app.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request):
    from repositories.sources_repo import list_sources
    return render(request, "sources.html", {"active": "sources", "sources": list_sources()})


@app.get("/sources/new", response_class=HTMLResponse)
def source_new(request: Request):
    return render(request, "source_form.html", {"active": "sources", "source": None, "errors": {}})


@app.post("/sources")
def source_create(name: str = Form(...), url: str = Form(...), type: str = Form(...),
                  level: str = Form("B"), keywords: str = Form(""), enabled: int = Form(1)):
    from repositories.sources_repo import create_source
    create_source(name=name, url=url, type=type, level=level, keywords=keywords, enabled=enabled)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/fetch-all")
def sources_fetch_all():
    from repositories.jobs_repo import enqueue
    enqueue("fetch_all_sources", {})
    return RedirectResponse(url="/jobs", status_code=303)


@app.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def source_edit(request: Request, source_id: int):
    from repositories.sources_repo import get_source
    return render(request, "source_form.html", {"active": "sources", "source": get_source(source_id), "errors": {}})


@app.post("/sources/{source_id}")
def source_update(source_id: int, name: str = Form(...), url: str = Form(...), type: str = Form(...),
                  level: str = Form("B"), keywords: str = Form(""), enabled: int = Form(1)):
    from repositories.sources_repo import update_source
    update_source(source_id, name=name, url=url, type=type, level=level, keywords=keywords, enabled=enabled)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_id}/toggle")
def source_toggle(source_id: int):
    from repositories.sources_repo import toggle_source
    toggle_source(source_id)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_id}/fetch")
def source_fetch(source_id: int):
    from repositories.jobs_repo import enqueue
    enqueue("fetch_source", {"source_id": source_id})
    return RedirectResponse(url="/jobs", status_code=303)


# ---------- 文章池 ----------
PAGE_SIZE = 50  # 文章池每页条数

@app.get("/articles", response_class=HTMLResponse)
def articles_page(request: Request, q: str = "", source_id: int = 0,
                  no_content: int = 0, page: int = 1):
    from repositories.articles_repo import search_articles, count_articles, list_sources_for_filter
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    articles = search_articles(q=q, source_id=source_id, no_content=bool(no_content),
                               limit=PAGE_SIZE, offset=offset)
    total = count_articles(q=q, source_id=source_id, no_content=bool(no_content))
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render(request, "articles.html", {
        "active": "articles",
        "articles": articles,
        "q": q,
        "source_id": source_id,
        "no_content": bool(no_content),
        "sources": list_sources_for_filter(),
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": total_pages,
    })


@app.post("/articles/bulk-ignore")
def articles_bulk_ignore(request: Request, article_ids: list[int] = Form(default=[])):
    """批量忽略文章。article_ids 来自表单复选框。"""
    from repositories.articles_repo import bulk_ignore_articles
    # 从 query 保留筛选状态，跳回列表时仍能看到同样的筛选结果（被忽略的会消失）
    n = bulk_ignore_articles(article_ids)
    referer = request.headers.get("referer", "/articles")
    return RedirectResponse(url=referer, status_code=303)


@app.get("/articles/{article_id}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int):
    from repositories.articles_repo import get_article
    return render(request, "article_detail.html", {"active": "articles", "article": get_article(article_id)})


@app.post("/articles/{article_id}/ignore")
def article_ignore(article_id: int):
    from repositories.articles_repo import ignore_article
    ignore_article(article_id)
    return RedirectResponse(url="/articles", status_code=303)


@app.post("/articles/{article_id}/edit")
def article_edit(article_id: int, title: str = Form(...), content_text: str = Form("")):
    """人工补充/修正正文。保存后回到详情页。"""
    from repositories.articles_repo import update_article_content
    update_article_content(article_id, title=title, content_text=content_text)
    return RedirectResponse(url=f"/articles/{article_id}", status_code=303)


@app.post("/articles/{article_id}/add-to-topic")
def article_add_to_topic(article_id: int, topic_id: int = Form(...)):
    from repositories.topics_repo import add_article_to_topic
    add_article_to_topic(topic_id, article_id)
    return RedirectResponse(url=f"/topics/{topic_id}", status_code=303)


# ---------- 选题库 ----------
@app.get("/topics", response_class=HTMLResponse)
def topics_page(request: Request, status: str = "", category: str = "",
                date_from: str = "", date_to: str = ""):
    from repositories.topics_repo import list_topics
    return render(request, "topics.html", {
        "active": "topics",
        "topics": list_topics(status=status, category=category, date_from=date_from, date_to=date_to),
        "status": status,
        "category": category,
        "date_from": date_from,
        "date_to": date_to,
    })


@app.get("/topics/{topic_id}", response_class=HTMLResponse)
def topic_detail(request: Request, topic_id: int):
    from repositories.topics_repo import get_topic_with_facts_and_articles
    return render(request, "topic_detail.html", {
        "active": "topics",
        "topic": get_topic_with_facts_and_articles(topic_id),
    })


@app.post("/topics/generate")
def topics_generate():
    from repositories.jobs_repo import enqueue
    enqueue("generate_topic", {})
    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/topics/{topic_id}/select")
def topic_select(topic_id: int):
    from repositories.topics_repo import set_topic_status
    set_topic_status(topic_id, "selected")
    return RedirectResponse(url=f"/topics/{topic_id}", status_code=303)


@app.post("/topics/{topic_id}/archive")
def topic_archive(topic_id: int):
    from repositories.topics_repo import set_topic_status
    set_topic_status(topic_id, "archived")
    return RedirectResponse(url="/topics", status_code=303)


# ---------- 脚本 ----------
@app.get("/topics/{topic_id}/scripts/compare", response_class=HTMLResponse)
def script_compare(request: Request, topic_id: int, a: int = 0, b: int = 0):
    """脚本版本对比：选择两个版本，展示正文 unified diff 与逐项对比。"""
    import difflib
    from repositories.topics_repo import get_topic_with_facts_and_articles
    from repositories.scripts_repo import list_scripts_for_topic, get_script
    scripts = list_scripts_for_topic(topic_id)
    sa = get_script(a) if a else None
    sb = get_script(b) if b else None
    diff = None
    if sa and sb and sa["id"] != sb["id"]:
        diff = list(difflib.unified_diff(
            (sb.get("body") or "").splitlines(),
            (sa.get("body") or "").splitlines(),
            fromfile=f"v{sb['version']}", tofile=f"v{sa['version']}", lineterm="",
        ))
    return render(request, "script_compare.html", {
        "active": "topics",
        "topic": get_topic_with_facts_and_articles(topic_id),
        "scripts": scripts, "a": a, "b": b, "sa": sa, "sb": sb, "diff": diff,
    })


@app.get("/topics/{topic_id}/scripts", response_class=HTMLResponse)
def script_editor(request: Request, topic_id: int, job: int = 0):
    from repositories.topics_repo import get_topic_with_facts_and_articles
    from repositories.scripts_repo import list_scripts_for_topic
    from repositories.assets_repo import list_assets_for_scripts
    scripts = list_scripts_for_topic(topic_id)
    assets_map = list_assets_for_scripts([s["id"] for s in scripts])
    return render(request, "script_editor.html", {
        "active": "topics",
        "topic": get_topic_with_facts_and_articles(topic_id),
        "scripts": scripts,
        "assets_map": assets_map,
        "tracking_job_id": job,
    })


@app.post("/topics/{topic_id}/scripts")
def script_generate(topic_id: int, platform: str = Form(...), format: str = Form(...), duration: int = Form(...)):
    from repositories.jobs_repo import enqueue
    job_id = enqueue("generate_script", {"topic_id": topic_id, "platform": platform, "format": format, "duration": duration})
    return RedirectResponse(url=f"/topics/{topic_id}/scripts?job={job_id}", status_code=303)


@app.post("/scripts/{script_id}")
def script_save(script_id: int, title: str = Form(""), hook: str = Form(""), body: str = Form(...),
                cta: str = Form(""), cover_text: str = Form(""), description: str = Form(""), hashtags: str = Form("")):
    from repositories.scripts_repo import get_script, update_script
    existing = get_script(script_id)
    update_script(script_id, title=title, hook=hook, body=body, cta=cta,
                  cover_text=cover_text, description=description, hashtags=hashtags)
    # 保存后回到该选题的脚本列表页，避免丢失上下文
    topic_id = existing.get("topic_id") if existing else None
    target = f"/topics/{topic_id}/scripts" if topic_id else "/topics"
    return RedirectResponse(url=target, status_code=303)


@app.post("/scripts/{script_id}/assets")
def script_generate_assets(script_id: int):
    """生成发布素材包（消耗 LLM，手动触发）。入队后跳回脚本编辑页并带 job 参数跟踪进度。"""
    from repositories.jobs_repo import enqueue
    from repositories.scripts_repo import get_script
    job_id = enqueue("generate_assets", {"script_id": script_id})
    existing = get_script(script_id)
    topic_id = existing.get("topic_id") if existing else None
    target = f"/topics/{topic_id}/scripts?job={job_id}" if topic_id else f"/jobs"
    return RedirectResponse(url=target, status_code=303)


# ---------- 设置 ----------
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    from repositories.settings_repo import get_profile, get_llm_settings, is_api_key_configured
    return render(request, "settings.html", {
        "active": "settings",
        "profile": get_profile(),
        "llm": get_llm_settings(),
        "api_key_configured": is_api_key_configured(),
        "saved": False,
    })


@app.post("/settings/profile")
def settings_profile(name: str = Form(...), positioning: str = Form(...), target_audience: str = Form(""),
                     tone: str = Form(""), content_boundary: str = Form(""), default_cta: str = Form("")):
    from repositories.settings_repo import update_profile
    update_profile(name=name, positioning=positioning, target_audience=target_audience,
                   tone=tone, content_boundary=content_boundary, default_cta=default_cta)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.post("/settings/model")
def settings_model(provider: str = Form(...), model: str = Form(...), temperature: float = Form(0.4),
                   max_tokens: int = Form(2000)):
    from repositories.settings_repo import update_llm_settings
    update_llm_settings(provider=provider, model=model, temperature=temperature, max_tokens=max_tokens)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ---------- 任务 ----------
@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, partial: int = 0):
    from repositories.jobs_repo import list_jobs
    jobs = list_jobs()
    if partial:
        return render(request, "jobs_table.html", {"jobs": jobs})
    return render(request, "jobs.html", {"active": "jobs", "jobs": jobs})


@app.post("/jobs/{job_id}/retry")
def job_retry(job_id: int):
    from repositories.jobs_repo import retry_job
    retry_job(job_id)
    return RedirectResponse(url="/jobs", status_code=303)


@app.get("/jobs/{job_id}/status")
def job_status(job_id: int):
    """轻量 job 状态查询，供前端轮询进度。返回 status/error/started_at/finished_at。"""
    from repositories.jobs_repo import get_job
    job = get_job(job_id)
    if not job:
        return {"status": "not_found"}
    return {
        "status": job["status"],
        "type": job["type"],
        "started_at": str(job["started_at"]) if job["started_at"] else None,
        "finished_at": str(job["finished_at"]) if job["finished_at"] else None,
        "error": (job["error"] or "")[:300],
        "attempts": job["attempts"],
        "max_attempts": job["max_attempts"],
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("app:app", host=settings.app_host, port=settings.app_port, reload=False)
