"""抓取服务：支持 RSS 与普通网页。返回标准化的文章条目列表。"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 20
HEADERS = {
    "User-Agent": settings.fetch_user_agent,
    # 带 Accept-Language 提高对国际站的命中率，部分站点无此头会返回精简页
    "Accept-Language": "en,zh-CN;q=0.8,zh;q=0.6",
}

# 摘要短于此长度判定为"RSS 没带全文"，需要回抓原文网页
_MIN_SUMMARY_LEN = 200

# 已知反爬站点黑名单：这些 host 的 RSS 条目跳过回抓，直接用摘要入库。
# 实测换 UA 无效，WAF 基于 TLS 指纹/JS challenge，回抓只会产生 403 噪音。
_REFETCH_SKIP_HOSTS = {
    "openai.com",  # 旧博客 /index/ 和新 /blog/ 均返回 403
}

# 429/5xx 重试配置：指数退避，避免被反爬限流直接放弃
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_MAX = 3
_RETRY_BASE_SLEEP = 3  # 首次重试等 3s，之后 6s、12s

# 全局按 host 限速：同一域名两次请求间至少间隔这么多秒，避免触发反爬
_HOST_MIN_INTERVAL = 1.5  # 秒
_host_last_request: dict[str, float] = {}
_host_lock = threading.Lock()


def _throttle_for_host(url: str) -> None:
    """对同一 host 的请求做最小间隔控制，避免高频触发反爬限流。"""
    host = urlparse(url).netloc
    if not host:
        return
    with _host_lock:
        last = _host_last_request.get(host)
        now = time.monotonic()
        if last is not None:
            elapsed = now - last
            if elapsed < _HOST_MIN_INTERVAL:
                wait = _HOST_MIN_INTERVAL - elapsed
                logger.debug("限速等待 %.2fs（host=%s）", wait, host)
                time.sleep(wait)
        _host_last_request[host] = time.monotonic()


def _http_get(url: str) -> requests.Response:
    """带退避重试 + 全局限速的 GET。仅对 429/5xx 重试，遵守 Retry-After 头。"""
    last_exc: Exception | None = None
    resp: requests.Response | None = None
    for attempt in range(_RETRY_MAX + 1):
        _throttle_for_host(url)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code in _RETRY_STATUSES and attempt < _RETRY_MAX:
                # 优先用服务器给的 Retry-After，否则指数退避
                wait = _parse_retry_after(resp) or (_RETRY_BASE_SLEEP * (2 ** attempt))
                logger.warning("HTTP %s 触发重试：%s（第 %d/%d 次，等待 %.1fs）",
                               resp.status_code, url, attempt + 1, _RETRY_MAX, wait)
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt < _RETRY_MAX:
                wait = _RETRY_BASE_SLEEP * (2 ** attempt)
                logger.warning("请求异常 %s：%s（第 %d/%d 次重试，等待 %.1fs）",
                               url, e, attempt + 1, _RETRY_MAX, wait)
                time.sleep(wait)
                continue
            raise
    if last_exc:
        raise last_exc
    assert resp is not None
    return resp


def _parse_retry_after(resp: requests.Response) -> float | None:
    """解析 Retry-After 头（秒数或 HTTP 日期）。失败返回 None。"""
    val = resp.headers.get("Retry-After")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        # HTTP 日期格式，简化处理：固定退避，不解析具体时间
        return None


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
    fetch_error: str | None = None  # 回抓失败原因，供入库时填充提示文本


def fetch_source(source: dict) -> list[FetchItem]:
    """根据 source.type 抓取，返回 FetchItem 列表。manual 类型返回空。"""
    stype = source.get("type")
    if stype == "rss":
        return _fetch_rss(source)
    if stype == "webpage":
        return _fetch_webpage(source)
    if stype == "webpage_list":
        return _fetch_webpage_list(source)
    if stype == "manual":
        return []
    raise ValueError(f"不支持的来源类型：{stype}")


def _fetch_rss(source: dict) -> list[FetchItem]:
    url = source["url"]
    logger.info("RSS 抓取开始：[%s] %s", source.get("name"), url)
    resp = _http_get(url)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    entry_count = len(feed.entries)
    logger.info("RSS 解析完成：[%s] 共 %d 条 entry", source.get("name"), entry_count)
    if feed.bozo:
        logger.warning("RSS [%s] 解析有警告：%s", source.get("name"), feed.bozo_exception)

    items: list[FetchItem] = []
    refetch_count = 0
    consecutive_fail = 0  # 连续回抓失败计数，用于熔断
    _FAIL_CIRCUIT = 5     # 连续失败到此阈值后停止该来源的回抓
    skip_refetch = False  # 熔断标志
    for entry in feed.entries:
        link = entry.get("link") or ""
        if not link:
            continue
        title = (entry.get("title") or "").strip() or link
        raw_html = entry.get("content", [{}])[0].get("value") if entry.get("content") else entry.get("summary")
        content_text = _extract_text(raw_html or "")

        fetch_error: str | None = None
        # RSS 摘要过短（如 HN/GitHub 只给"点击查看原文"），回抓原文网页提正文
        if len(content_text) < _MIN_SUMMARY_LEN:
            link_host = urlparse(link).netloc.lower()
            host_skip = any(link_host == h or link_host.endswith("." + h) for h in _REFETCH_SKIP_HOSTS)
            if host_skip:
                # 已知反爬站点，直接跳过回抓，保留摘要入库
                fetch_error = "跳过回抓：源站已知反爬"
            elif skip_refetch:
                # 已熔断，直接用短摘要入库，不再回抓
                fetch_error = "熔断：同源连续多次回抓失败"
            else:
                logger.debug("[%s] 摘要过短(%d字)，回抓原文：%s", source.get("name"), len(content_text), link)
                fetched, err = _fetch_article_page_with_error(link)
                if fetched:
                    # 网页正文优先于过短的 RSS 摘要
                    content_text = fetched.content_text
                    raw_html = fetched.raw_html or raw_html
                    refetch_count += 1
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1
                    fetch_error = err or "回抓失败"
                    logger.warning("[%s] 回抓原文失败(%d/%d)，保留短摘要：%s",
                                   source.get("name"), consecutive_fail, _FAIL_CIRCUIT, link)
                    if consecutive_fail >= _FAIL_CIRCUIT:
                        skip_refetch = True
                        logger.warning("[%s] 连续 %d 次回抓失败，触发熔断，后续条目不再回抓原文",
                                       source.get("name"), _FAIL_CIRCUIT)

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
            fetch_error=fetch_error,
        ))
    logger.info("RSS [%s] 处理完成：%d 条有效条目，其中 %d 条回抓了原文网页",
                source.get("name"), len(items), refetch_count)
    return items


def _fetch_webpage(source: dict) -> list[FetchItem]:
    url = source["url"]
    logger.info("网页抓取开始：[%s] %s", source.get("name"), url)
    item = _fetch_article_page(url)
    if not item:
        logger.warning("[%s] trafilatura 提取失败，退回 BeautifulSoup 兜底", source.get("name"))
        # 抓取失败兜底：用旧逻辑避免空结果
        resp = _http_get(url)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string.strip() if soup.title and soup.title.string else url)
        return [FetchItem(
            title=title, url=url, canonical_url=_extract_canonical(url, html),
            author=_meta(soup, "author"),
            published_at=_meta(soup, "article:published_time") or _meta(soup, "date"),
            source_item_id=_extract_canonical(url, html) or url, raw_html=html,
            content_text=_fallback_text(soup),
            language=_meta(soup, "language") or _lang_from_html(soup),
        )]
    # 单网页来源用 source.url 作为 url，避免抓到分页/推荐链接
    item.url = url
    logger.info("网页 [%s] 抓取完成：正文 %d 字符", source.get("name"), len(item.content_text))
    return [item]


def _fetch_webpage_list(source: dict) -> list[FetchItem]:
    """列表型网页：先抓列表页提取文章链接，再逐篇抓正文。

    适用于无 RSS 但有固定列表页结构的来源（如 anthropic.com/engineering、anthropic.com/news）。
    链接提取规则：取 source.url 的 path 前缀作为基准，匹配同前缀的内部链接。
    例如 source.url = https://www.anthropic.com/engineering，
    则匹配所有 /engineering/{slug} 的链接作为文章页。
    复用 RSS 的熔断机制：连续 _FAIL_CIRCUIT 次回抓失败则停止。
    """
    url = source["url"]
    logger.info("列表网页抓取开始：[%s] %s", source.get("name"), url)

    # 解析列表页
    try:
        resp = _http_get(url)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("列表页抓取失败 %s: %s", url, e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    # 基准 path：去掉尾部文件名，保留目录前缀
    # 例如 https://www.anthropic.com/engineering -> /engineering
    from urllib.parse import urlsplit, urljoin
    base_path = urlsplit(url).path.rstrip("/")
    if not base_path:
        logger.warning("[%s] 无法从 URL 提取基准 path：%s", source.get("name"), url)
        return []

    # 收集同前缀的文章链接（去重保序）
    seen: set[str] = set()
    article_links: list[tuple[str, str]] = []  # (url, title_hint)
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href:
            continue
        abs_url = urljoin(url, href)
        link_path = urlsplit(abs_url).path
        # 必须是 base_path 的下级路径（如 /engineering/xxx），且不是 base_path 本身
        if not link_path.startswith(base_path + "/"):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        title_hint = a.get_text(" ", strip=True)[:120]
        article_links.append((abs_url, title_hint))

    logger.info("[%s] 列表页解析出 %d 个候选文章链接", source.get("name"), len(article_links))
    if not article_links:
        return []

    items: list[FetchItem] = []
    refetch_count = 0
    consecutive_fail = 0
    skip_refetch = False
    for abs_url, title_hint in article_links:
        if skip_refetch:
            break
        fetched = _fetch_article_page(abs_url)
        if fetched:
            # title_hint 通常更接近卡片标题，但 trafilatura 提取的 title 更准确；
            # 优先用 trafilatura 的，空时退回 title_hint
            if not fetched.title:
                fetched.title = title_hint or abs_url
            items.append(fetched)
            refetch_count += 1
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            logger.warning("[%s] 文章页抓取失败(%d/%d)：%s",
                           source.get("name"), consecutive_fail, _FAIL_CIRCUIT, abs_url)
            if consecutive_fail >= _FAIL_CIRCUIT:
                skip_refetch = True
                logger.warning("[%s] 连续 %d 次抓取失败，触发熔断，停止后续文章",
                               source.get("name"), _FAIL_CIRCUIT)

    logger.info("列表网页 [%s] 抓取完成：%d 篇文章，其中 %d 篇成功提取正文",
                source.get("name"), len(items), refetch_count)
    return items


def _fetch_article_page(url: str) -> FetchItem | None:
    """抓取单篇文章网页并用 trafilatura 提取正文。失败返回 None。"""
    item, _err = _fetch_article_page_with_error(url)
    return item


def _fetch_article_page_with_error(url: str) -> tuple[FetchItem | None, str | None]:
    """同 _fetch_article_page，但额外返回失败原因字符串（成功时为 None）。

    供调用方在回抓失败、content_text 为空时，把原因写入 fetch_error 字段，
    入库时由 worker 填充提示文本，避免用户看到无信息的"无正文"。
    """
    try:
        resp = _http_get(url)
        resp.raise_for_status()
        html = resp.text
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        reason = f"源站返回 HTTP {status}" if status else f"请求失败：{type(e).__name__}"
        logger.warning("抓取文章页失败 %s: %s", url, reason)
        return None, reason
    except Exception as e:
        reason = f"请求异常：{type(e).__name__}"
        logger.warning("抓取文章页失败 %s: %s", url, reason)
        return None, reason

    title, content_text, canonical, lang = _extract_with_trafilatura(html, url)
    if not content_text:
        logger.debug("trafilatura 提取为空，退回 BeautifulSoup：%s", url)
        # trafilatura 提取失败，退回 BeautifulSoup 兜底
        soup = BeautifulSoup(html, "lxml")
        title = title or (soup.title.string.strip() if soup.title and soup.title.string else url)
        content_text = _fallback_text(soup)
        canonical = canonical or _extract_canonical(url, html)
        lang = lang or _meta(soup, "language") or _lang_from_html(soup)

    if not content_text:
        logger.warning("正文提取彻底失败，返回空：%s", url)
        return None, "正文提取失败（trafilatura 与 BeautifulSoup 均为空）"

    logger.debug("文章页提取成功：%s 正文 %d 字符", url, len(content_text))
    return FetchItem(
        title=title or url,
        url=url,
        canonical_url=canonical,
        author=None,
        published_at=None,
        source_item_id=canonical or url,
        raw_html=html,
        content_text=content_text,
        language=lang,
    ), None


def _extract_with_trafilatura(html: str, source_url: str) -> tuple[str | None, str, str | None, str | None]:
    """用 trafilatura 提取正文、标题、canonical、语言。失败返回空串。"""
    import trafilatura
    try:
        content_text = trafilatura.extract(
            html, url=source_url, include_comments=False, include_tables=True,
            favor_precision=True, output_format="txt",
        ) or ""
    except Exception as e:
        logger.warning("trafilatura 提取失败 %s: %s", source_url, e)
        content_text = ""

    title: str | None = None
    canonical: str | None = None
    lang: str | None = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=source_url)
        if meta:
            title = meta.title
            canonical = meta.url or source_url
            lang = meta.language
    except Exception:
        pass
    return title, content_text, canonical, lang


def _extract_text(html: str) -> str:
    """从 HTML 片段（RSS content/summary）提取纯文本。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)


def _fallback_text(soup: BeautifulSoup) -> str:
    """trafilatura 失败时的兜底正文提取：去脚本/样式/导航后取 body。"""
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
