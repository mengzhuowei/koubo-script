"""Tavily Search API 封装：search + extract + credit 计算。

V0.3 只实现 Tavily，保留 provider 抽象方便后续扩展。
所有调用都经过 web_search_repo 的预算检查，超预算抛 WebSearchBudgetExceeded。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from config import settings
from repositories import web_search_repo

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


class WebSearchError(Exception):
    """联网搜索基础异常。"""


class WebSearchDisabled(WebSearchError):
    """联网搜索未开启或未配置 API Key。"""


class WebSearchBudgetExceeded(WebSearchError):
    """超出月度或单选题 credit 预算。"""


@dataclass
class SearchResult:
    url: str
    title: str
    content: str  # 摘要
    score: float
    raw_content: str | None = None


@dataclass
class ExtractResult:
    url: str
    raw_content: str
    failed: bool = False


def is_web_search_available() -> bool:
    """联网搜索是否可用：开关开启 + API Key 已配置。"""
    return bool(settings.web_search_enabled and settings.tavily_api_key)


def _credits_for_search(depth: str) -> int:
    """搜索消耗的 credit：basic=1，advanced=2。"""
    return 2 if depth == "advanced" else 1


def _credits_for_extract(url_count: int) -> int:
    """Extract 消耗的 credit：每 5 个 URL 约 1 credit，向上取整。"""
    return max(1, math.ceil(url_count / 5))


def search_for_topic(topic_id: int, query: str) -> list[SearchResult]:
    """为选题执行一次联网搜索，自动记账 credit。

    超预算/未开启/无 Key 都会抛异常，调用方按需捕获。
    """
    if not is_web_search_available():
        raise WebSearchDisabled("联网搜索未开启或未配置 TAVILY_API_KEY")

    depth = settings.tavily_search_depth
    max_results = settings.tavily_max_results
    credit = _credits_for_search(depth)

    # 预算检查（先查后扣，避免并发超扣——单 worker 场景足够）
    if not web_search_repo.check_budget(topic_id, credit):
        monthly_used = web_search_repo.monthly_credits_used()
        topic_used = web_search_repo.topic_credits_used(topic_id)
        raise WebSearchBudgetExceeded(
            f"预算不足：月度已用 {monthly_used}/{settings.tavily_monthly_credit_budget}，"
            f"本选题已用 {topic_used}/{settings.tavily_per_topic_credit_budget}，本次需 {credit}"
        )

    # 调 Tavily Search API
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": depth,
        "max_results": max_results,
        "include_raw_content": False,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(TAVILY_SEARCH_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise WebSearchError(f"Tavily Search 调用失败：{e}") from e

    results = [
        SearchResult(
            url=r.get("url", ""),
            title=r.get("title", ""),
            content=r.get("content", ""),
            score=float(r.get("score", 0)),
        )
        for r in data.get("results", [])
        if r.get("url")
    ]

    # 记账（即使结果为 0 也扣 credit，因为 API 已调用）
    web_search_repo.record_usage(
        topic_id=topic_id, query_text=query, credits_used=credit,
        results_count=len(results), search_depth=depth,
    )
    logger.info("Tavily search topic=%s query=%s results=%d credits=%d",
                topic_id, query[:60], len(results), credit)
    return results


def extract_for_topic(topic_id: int, urls: list[str]) -> list[ExtractResult]:
    """对搜索结果 URL 提取正文。受 extract_max_urls 限制，超预算抛异常。"""
    if not is_web_search_available():
        raise WebSearchDisabled("联网搜索未开启或未配置 TAVILY_API_KEY")
    if not urls:
        return []

    max_urls = settings.tavily_extract_max_urls
    urls = urls[:max_urls]
    credit = _credits_for_extract(len(urls))

    if not web_search_repo.check_budget(topic_id, credit):
        raise WebSearchBudgetExceeded(f"Extract 预算不足：本次需 {credit} credits")

    payload = {
        "api_key": settings.tavily_api_key,
        "urls": urls,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(TAVILY_EXTRACT_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise WebSearchError(f"Tavily Extract 调用失败：{e}") from e

    results = []
    failed_urls = data.get("failed_results", [])
    failed_set = {f.get("url") for f in failed_urls}
    for r in data.get("results", []):
        url = r.get("url", "")
        if not url:
            continue
        results.append(ExtractResult(
            url=url,
            raw_content=r.get("raw_content", "")[:3000],  # 每个结果最多 3000 字
            failed=url in failed_set,
        ))

    web_search_repo.record_usage(
        topic_id=topic_id, query_text=f"extract:{len(urls)}urls",
        credits_used=credit, results_count=len(results), search_depth="extract",
    )
    logger.info("Tavily extract topic=%s urls=%d success=%d credits=%d",
                topic_id, len(urls), len([r for r in results if not r.failed]), credit)
    return results


def get_host(url: str) -> str:
    """提取 URL 的 host，用于来源分级。"""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""
