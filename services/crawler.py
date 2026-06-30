"""抓取服务：支持 RSS 与普通网页。返回标准化的文章条目列表。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 20
HEADERS = {"User-Agent": settings.fetch_user_agent}


@dataclass
class FetchItem:
    title: str
    url: str
    canonical_url: str | None
    author: str | None
    published_at: str | None
    source_item_id: str | None
    raw_html: str | None
    content_text: str
    language: str | None


def fetch_source(source: dict) -> list[FetchItem]:
    """根据 source.type 抓取，返回 FetchItem 列表。manual 类型返回空。"""
    stype = source.get("type")
    if stype == "rss":
        return _fetch_rss(source)
    if stype == "webpage":
        return _fetch_webpage(source)
    if stype == "manual":
        return []
    raise ValueError(f"不支持的来源类型：{stype}")


def _fetch_rss(source: dict) -> list[FetchItem]:
    url = source["url"]
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    items: list[FetchItem] = []
    for entry in feed.entries:
        link = entry.get("link") or ""
        if not link:
            continue
        title = (entry.get("title") or "").strip() or link
        raw_html = entry.get("content", [{}])[0].get("value") if entry.get("content") else entry.get("summary")
        content_text = _extract_text(raw_html or "")
        canonical = _extract_canonical(link, raw_html)
        items.append(FetchItem(
            title=title,
            url=link,
            canonical_url=canonical,
            author=entry.get("author"),
            published_at=_parse_published(entry),
            source_item_id=entry.get("id") or entry.get("guid") or link,
            raw_html=raw_html,
            content_text=content_text,
            language=feed.feed.get("language"),
        ))
    return items


def _fetch_webpage(source: dict) -> list[FetchItem]:
    url = source["url"]
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    title = (soup.title.string.strip() if soup.title and soup.title.string else url)
    canonical = _extract_canonical(url, html)
    content_text = _extract_main_text(soup)
    items = [FetchItem(
        title=title,
        url=url,
        canonical_url=canonical,
        author=_meta(soup, "author"),
        published_at=_meta(soup, "article:published_time") or _meta(soup, "date"),
        source_item_id=canonical or url,
        raw_html=html,
        content_text=content_text,
        language=_meta(soup, "language") or _lang_from_html(soup),
    )]
    return items


def _extract_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)


def _extract_main_text(soup: BeautifulSoup) -> str:
    """简单正文提取：去掉脚本/样式/导航后取 body 文本。"""
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return main.get_text(separator="\n", strip=True)


def _extract_canonical(fallback_url: str, html: str | None) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        return urljoin(fallback_url, link["href"].strip())
    return None


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return tag.get("content").strip() if tag and tag.get("content") else None


def _lang_from_html(soup: BeautifulSoup) -> str | None:
    html = soup.find("html")
    return html.get("lang") if html else None


def _parse_published(entry) -> str | None:
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            if isinstance(val, list):
                return val[0]
            return str(val)
    return None
