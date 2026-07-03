"""联网搜索结果来源分级：S/A/B/C 四级 + 广告/营销页过滤。

分级白名单基于 PRD §8.2.4。host 匹配采用子串包含，避免 www 前缀差异。
"""
from __future__ import annotations

from urllib.parse import urlparse

# S 级：官方源（AI 厂商官方博客/文档/GitHub）
S_LEVEL_HOSTS = [
    "openai.com", "anthropic.com", "ai.google", "deepmind.google", "google.com/ai",
    "microsoft.com/ai", "ai.meta.com", "huggingface.co", "modelcontextprotocol.io",
    "github.com/openai", "github.com/anthropics", "github.com/google", "github.com/microsoft",
    "github.com/meta", "github.com/huggingface", "developers.googleblog.com",
]

# A 级：框架/工具官方源
A_LEVEL_HOSTS = [
    "langchain.com", "python.langchain.com", "llamaindex.ai", "docs.llamaindex.ai",
    "crewai.com", "docs.crewai.com", "microsoft.github.io/autogen", "autogen.ai",
    "sdk.vercel.ai", "ai-sdk.dev", "github.com/langchain-ai", "github.com/run-llama",
    "github.com/crewAIInc", "github.com/microsoft/autogen", "huggingface.co/blog",
    "blog.langchain.dev", "blog.llamaindex.ai",
]

# B 级：研究与开发者社区
B_LEVEL_HOSTS = [
    "arxiv.org", "paperswithcode.com", "news.ycombinator.com", "hn.algolia.com",
    "reddit.com/r/", "tldr.tech", "github.com",  # 通用 GitHub（非官方组织的仓库）
    "stackoverflow.com", "dev.to", "medium.com",
]

# C 级：中文二次传播源
C_LEVEL_HOSTS = [
    "jiqizhixin.com", "qbitai.com", "infoq.cn", "sspai.com", "juejin.cn",
    "36kr.com", "ithome.com", "cnblogs.com", "csdn.net", "zhihu.com",
]

# 黑名单：广告/营销/聚合页，直接过滤
BLACKLIST_HOSTS = [
    "pinterest.com", "facebook.com", "tiktok.com", "instagram.com",
    "amazon.com", "ebay.com", "aliexpress.com",
]

# 黑名单关键词（URL 或标题包含则过滤）
BLACKLIST_KEYWORDS = [
    "buy-now", "discount", "coupon", "deal", "sale", "pricing-plans",
    "affiliate", "sponsored", "广告", "优惠", "折扣",
]


def classify_source(url: str, title: str = "") -> tuple[str, bool]:
    """对联网搜索结果分级。

    返回 (level, should_keep)：
    - level: S/A/B/C/U（U=未识别）
    - should_keep: False 表示应过滤掉（广告/营销/黑名单）
    """
    host = _get_host(url)
    url_lower = url.lower()
    title_lower = (title or "").lower()

    # 黑名单过滤
    if any(b in host for b in BLACKLIST_HOSTS):
        return "U", False
    if any(k in url_lower or k in title_lower for k in BLACKLIST_KEYWORDS):
        return "U", False

    # 分级匹配（S > A > B > C，从高到低）
    if any(h in host for h in S_LEVEL_HOSTS):
        return "S", True
    if any(h in host for h in A_LEVEL_HOSTS):
        return "A", True
    if any(h in host for h in B_LEVEL_HOSTS):
        return "B", True
    if any(h in host for h in C_LEVEL_HOSTS):
        return "C", True

    return "U", True  # 未识别但不过滤，让 LLM 判断质量


def _get_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_official_source(level: str) -> bool:
    """S/A 级视为官方/一手源。"""
    return level in ("S", "A")
