from __future__ import annotations

import json

from repositories.db import get_conn

COMMON_KEYWORDS = (
    "AI Agent,agentic AI,multi-agent,tool use,computer use,workflow agent,"
    "coding agent,browser agent,research agent,MCP,Agents SDK,ADK,LangGraph,"
    "LlamaIndex,CrewAI,AutoGen,memory,planning,tool calling,evaluation,"
    "guardrails,prompt injection,智能体,多智能体,工具调用,Agent工作流,AI自动化"
)


def source_config(note: str, auto_quality: str = "normal") -> str:
    return json.dumps(
        {"seed": "product-design", "note": note, "auto_quality": auto_quality},
        ensure_ascii=False,
    )


def kw(extra: str) -> str:
    return f"{COMMON_KEYWORDS},{extra}"


SOURCES = [
    # S 官方源
    {
        "name": "OpenAI News RSS",
        "url": "https://openai.com/news/rss.xml",
        "type": "rss",
        "level": "S",
        "enabled": 1,
        "keywords": kw("OpenAI,Codex,Agents SDK,Responses API"),
        "note": "产品设计官方源：OpenAI。稳定 RSS。",
    },
    {
        "name": "OpenAI Agents Docs",
        "url": "https://developers.openai.com/api/docs/guides/agents",
        "type": "manual",
        "level": "S",
        "enabled": 0,
        "keywords": kw("OpenAI,Agents SDK,tool calling,tracing,guardrails"),
        "note": "产品设计官方源：OpenAI。该文档对普通请求可能返回 403，先停用手动跟踪。",
    },
    {
        "name": "Anthropic News",
        "url": "https://www.anthropic.com/news",
        "type": "webpage_list",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Anthropic,Claude,computer use,MCP"),
        "note": "产品设计官方源：Anthropic。列表型网页，抓取 /news/{slug} 文章页。",
    },
    {
        "name": "Anthropic Engineering",
        "url": "https://www.anthropic.com/engineering",
        "type": "webpage_list",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Anthropic,Claude,agent,engineering,MCP"),
        "note": "产品设计官方源：Anthropic Engineering。列表型网页，抓取 /engineering/{slug} 文章页。",
    },
    {
        "name": "Google AI Blog RSS",
        "url": "https://blog.google/innovation-and-ai/technology/ai/rss/",
        "type": "rss",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Google,Gemini,ADK,agent"),
        "note": "产品设计官方源：Google。AI 分类 RSS。",
    },
    {
        "name": "Google Research Blog RSS",
        "url": "https://research.google/blog/rss/",
        "type": "rss",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Google Research,agent,AI research,benchmark"),
        "note": "产品设计官方源：Google Research。",
    },
    {
        "name": "Google ADK Docs",
        "url": "https://adk.dev/",
        "type": "webpage",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Google ADK,Agent Development Kit,agent framework"),
        "note": "产品设计官方源：Google ADK。",
    },
    {
        "name": "Microsoft Cloud Blog RSS",
        "url": "https://www.microsoft.com/en-us/microsoft-cloud/blog/feed/",
        "type": "rss",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Microsoft,Azure AI,agent,AI Foundry,Copilot"),
        "note": "产品设计官方源：Microsoft。官方云与 AI 博客 RSS。",
    },
    {
        "name": "Model Context Protocol Docs",
        "url": "https://modelcontextprotocol.io/docs/getting-started/intro",
        "type": "webpage",
        "level": "S",
        "enabled": 1,
        "keywords": kw("Model Context Protocol,MCP,tools,connectors"),
        "note": "产品设计官方源：MCP Docs。",
    },
    {
        "name": "Model Context Protocol Releases",
        "url": "https://github.com/modelcontextprotocol/modelcontextprotocol/releases.atom",
        "type": "rss",
        "level": "S",
        "enabled": 1,
        "keywords": kw("MCP,Model Context Protocol,release,protocol"),
        "note": "MCP 官方 GitHub release feed，补充文档更新。",
    },
    # A 框架源
    {
        "name": "LangChain Blog RSS",
        "url": "https://www.langchain.com/blog/rss.xml",
        "type": "rss",
        "level": "A",
        "enabled": 1,
        "keywords": kw("LangChain,LangGraph,agent framework,RAG"),
        "note": "产品设计框架源：LangChain。稳定 RSS。",
    },
    {
        "name": "LlamaIndex Blog",
        "url": "https://www.llamaindex.ai/blog",
        "type": "webpage",
        "level": "A",
        "enabled": 1,
        "keywords": kw("LlamaIndex,RAG,workflow agent,data agent"),
        "note": "产品设计框架源：LlamaIndex。",
    },
    {
        "name": "CrewAI Blog",
        "url": "https://crewai.com/blog",
        "type": "webpage",
        "level": "A",
        "enabled": 1,
        "keywords": kw("CrewAI,multi-agent,agent workflow,crew"),
        "note": "产品设计框架源：CrewAI。",
    },
    {
        "name": "Microsoft AutoGen Releases",
        "url": "https://github.com/microsoft/autogen/releases.atom",
        "type": "rss",
        "level": "A",
        "enabled": 1,
        "keywords": kw("AutoGen,Microsoft,multi-agent,agent framework"),
        "note": "产品设计框架源：AutoGen。GitHub releases Atom feed。",
    },
    {
        "name": "Hugging Face Blog RSS",
        "url": "https://huggingface.co/blog/feed.xml",
        "type": "rss",
        "level": "A",
        "enabled": 0,
        "keywords": kw("Hugging Face,agents,transformers,smolagents"),
        "note": "产品设计框架源：Hugging Face。feed 无 summary，文章页 /blog/ 路径持续 429 限流无法回抓，停用待代理方案。",
    },
    # B 研究源
    {
        "name": "arXiv cs.AI RSS",
        "url": "https://export.arxiv.org/rss/cs.AI",
        "type": "rss",
        "level": "B",
        "enabled": 1,
        "keywords": kw("arXiv,AI research,agent benchmark,planning"),
        "note": "产品设计研究源：arXiv。cs.AI RSS。",
    },
    {
        "name": "arXiv cs.CL RSS",
        "url": "https://export.arxiv.org/rss/cs.CL",
        "type": "rss",
        "level": "B",
        "enabled": 1,
        "keywords": kw("arXiv,LLM,language agents,tool use"),
        "note": "产品设计研究源：arXiv。补充 LLM/Agent 论文常见分类。",
    },
    {
        "name": "Papers with Code / Hugging Face Papers Trending",
        "url": "https://paperswithcode.com/",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("Papers with Code,Hugging Face Papers,AI papers,benchmark"),
        "note": "产品设计研究源：Papers with Code。当前页面会跳转到 Hugging Face Papers Trending。",
    },
    {
        "name": "SWE-bench Benchmark",
        "url": "https://www.swebench.com/",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("SWE-bench,coding agent,software engineering benchmark"),
        "note": "产品设计研究源：benchmark 项目。代表性 coding agent benchmark。",
    },
    {
        "name": "WebArena Benchmark",
        "url": "https://webarena.dev/",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("WebArena,browser agent,web agent,benchmark"),
        "note": "产品设计研究源：benchmark 项目。代表性 browser/web agent benchmark。",
    },
    {
        "name": "GAIA Benchmark",
        "url": "https://huggingface.co/spaces/gaia-benchmark/leaderboard",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("GAIA,agent benchmark,reasoning,tool use"),
        "note": "产品设计研究源：benchmark 项目。代表性通用助手/Agent benchmark。",
    },
    # B 开发者社区
    {
        "name": "GitHub Topics: AI Agents",
        "url": "https://github.com/topics/ai-agents",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("GitHub,ai-agents,open source"),
        "note": "产品设计开发者社区源：GitHub。",
    },
    {
        "name": "GitHub Topics: MCP",
        "url": "https://github.com/topics/mcp",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("GitHub,MCP,Model Context Protocol"),
        "note": "产品设计开发者社区源：GitHub MCP topic。",
    },
    {
        "name": "GitHub Topics: Agent Framework",
        "url": "https://github.com/topics/agent-framework",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("GitHub,agent framework,open source"),
        "note": "产品设计开发者社区源：GitHub agent-framework topic。",
    },
    {
        "name": "GitHub Topics: Coding Agent",
        "url": "https://github.com/topics/coding-agent",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("GitHub,coding agent,code agent"),
        "note": "产品设计开发者社区源：GitHub coding-agent topic。",
    },
    {
        "name": "Hacker News Algolia: AI Agents",
        "url": "https://hn.algolia.com/?q=ai%20agents",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("Hacker News,HN,AI agents,developer discussion"),
        "note": "产品设计开发者社区源：Hacker News。当前以搜索页网页抓取。",
    },
    {
        "name": "Reddit LocalLLaMA Agent Search",
        "url": "https://www.reddit.com/r/LocalLLaMA/search/?q=agent&restrict_sr=1&sort=new",
        "type": "manual",
        "level": "B",
        "enabled": 0,
        "keywords": kw("Reddit,LocalLLaMA,agent discussion"),
        "note": "产品设计开发者社区源：Reddit。搜索页反爬和动态内容较多，先停用手动跟踪。",
    },
    {
        "name": "TLDR Tech",
        "url": "https://tldr.tech/",
        "type": "webpage",
        "level": "B",
        "enabled": 1,
        "keywords": kw("TLDR,tech newsletter,AI,Dev,Data,Infosec,agent,coding agent"),
        "note": "补充源：TLDR Tech。每日技术 newsletter 聚合，适合发现 AI、Agent、开发者工具和安全趋势。",
    },
    # C 中文传播源
    {
        "name": "机器之心",
        "url": "https://www.jiqizhixin.com/",
        "type": "manual",
        "level": "C",
        "enabled": 0,
        "keywords": kw("机器之心,AI Agent,智能体,大模型"),
        "note": "中文传播源：机器之心。站点已改版为付费数据服务（RSS/MCP/AI Skills），文章不再公开可抓取，停用待替代方案。",
    },
    {
        "name": "量子位 RSS",
        "url": "https://www.qbitai.com/feed",
        "type": "rss",
        "level": "C",
        "enabled": 1,
        "keywords": kw("量子位,AI Agent,智能体,大模型"),
        "note": "产品设计中文传播源：量子位。稳定 RSS。",
    },
    {
        "name": "InfoQ 中文 RSS",
        "url": "https://www.infoq.cn/feed.xml",
        "type": "rss",
        "level": "C",
        "enabled": 1,
        "keywords": kw("InfoQ,AI,智能体,大模型,开发者"),
        "note": "产品设计中文传播源：InfoQ。",
    },
    {
        "name": "少数派 RSS",
        "url": "https://sspai.com/feed",
        "type": "rss",
        "level": "C",
        "enabled": 1,
        "keywords": kw("少数派,AI工具,效率,自动化"),
        "note": "产品设计中文传播源：少数派。",
    },
    {
        "name": "掘金 RSS",
        "url": "https://juejin.cn/rss",
        "type": "rss",
        "level": "C",
        "enabled": 1,
        "keywords": kw("掘金,AI,智能体,开发者,自动化"),
        "note": "产品设计中文传播源：掘金。",
    },
    # C 平台竞品
    {
        "name": "抖音 AI Agent 搜索",
        "url": "https://www.douyin.com/search/AI%20Agent",
        "type": "manual",
        "level": "C",
        "enabled": 0,
        "keywords": kw("抖音,AI Agent,短视频,竞品"),
        "note": "产品设计平台竞品源：抖音。同类账号/搜索结果需人工或专用采集，先停用。",
    },
    {
        "name": "小红书 AI Agent 搜索",
        "url": "https://www.xiaohongshu.com/search_result?keyword=AI%20Agent",
        "type": "manual",
        "level": "C",
        "enabled": 0,
        "keywords": kw("小红书,AI Agent,笔记,竞品"),
        "note": "产品设计平台竞品源：小红书。同类账号/搜索结果需人工或专用采集，先停用。",
    },
    {
        "name": "B站 AI Agent 搜索",
        "url": "https://search.bilibili.com/all?keyword=AI%20Agent",
        "type": "bilibili_search",
        "level": "C",
        "enabled": 1,
        "keywords": kw("B站,Bilibili,AI Agent,视频,竞品"),
        "note": "平台竞品源：B站。通过 wbi 签名调官方搜索 API 获取视频结果。",
    },
]


def seed() -> None:
    conn = get_conn()
    try:
        conn.begin()
        inserted = 0
        updated = 0
        for source in SOURCES:
            existing = conn.execute(
                "SELECT id FROM sources WHERE url = %s OR name = %s ORDER BY id LIMIT 1",
                (source["url"], source["name"]),
            ).fetchone()
            values = (
                source["name"],
                source["url"],
                source["type"],
                source["level"],
                source["keywords"],
                source_config(source["note"]),
                1 if source["enabled"] else 0,
                720 if source["type"] == "rss" else 1440,
            )
            if existing:
                conn.execute(
                    """UPDATE sources
                       SET name=%s, url=%s, type=%s, level=%s, keywords=%s, config_json=%s,
                           enabled=%s, fetch_interval_minutes=%s, updated_at=CURRENT_TIMESTAMP
                       WHERE id=%s""",
                    (*values, existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO sources
                         (name, url, type, level, keywords, config_json, enabled, fetch_interval_minutes)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    values,
                )
                inserted += 1
        conn.commit()
        print(json.dumps({"inserted": inserted, "updated": updated, "total_seed_sources": len(SOURCES)}, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
