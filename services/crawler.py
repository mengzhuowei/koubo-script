"""抓取服务：支持 RSS 与普通网页。返回标准化的文章条目列表。"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlsplit

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
    "qbitai.com",  # 量子位：RSS 摘要仅导语，回抓文章页必被 RemoteDisconnected 拒绝
    "huggingface.co",  # HF：feed 无 summary，/blog/ 路径持续 429 限流，回抓必失败
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
    if stype == "spa_list":
        return _fetch_spa_list(source)
    if stype == "github_topics":
        return _fetch_github_topics(source)
    if stype == "bilibili_search":
        return _fetch_bilibili_search(source)
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
            published_at=_normalize_datetime(_meta(soup, "article:published_time") or _meta(soup, "date")),
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


# ---------- GitHub Topics 抓取 ----------
# GitHub Topics 页面（如 https://github.com/topics/ai-agents）以 <article> 卡片列出项目，
# 每张卡片含仓库名（owner/repo）、描述、Stars、语言、标签。直接从列表页提取即可，
# 无需回抓每个 repo 页面（topics 页已含核心信息，且回抓会触发 GitHub 反爬）。
def _fetch_github_topics(source: dict) -> list[FetchItem]:
    """抓取 GitHub Topics 列表页，提取每个项目卡片的名称、描述、Stars 等。"""
    url = source["url"]
    logger.info("GitHub Topics 抓取开始：[%s] %s", source.get("name"), url)

    try:
        resp = _http_get(url)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("GitHub Topics 列表页抓取失败 %s: %s", url, e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    articles = soup.find_all("article")
    if not articles:
        logger.warning("[%s] 未找到 <article> 项目卡片，页面结构可能已变更", source.get("name"))
        return []

    items: list[FetchItem] = []
    for art in articles:
        # 仓库名：h3 里有两个 a 标签，第一个是 owner，第二个是 repo
        h3 = art.find("h3")
        if not h3:
            continue
        repo_link = None
        owner_name = ""
        repo_name = ""
        links = h3.find_all("a", href=True)
        if len(links) >= 2:
            owner_name = links[0].get_text(strip=True)
            repo_link = links[1]
            repo_name = repo_link.get_text(strip=True)
        elif len(links) == 1:
            repo_link = links[0]
            repo_name = repo_link.get_text(strip=True)
        if not repo_link:
            continue

        repo_path = repo_link["href"]  # 如 /affaan-m/ECC
        repo_url = urljoin("https://github.com", repo_path)
        title = f"{owner_name}/{repo_name}" if owner_name else repo_name or repo_url

        # 项目描述
        desc_p = art.find("p")
        description = desc_p.get_text(" ", strip=True) if desc_p else ""

        # Stars（a[href*="stargazers"]）
        star_text = ""
        star_link = art.find("a", href=re.compile(r"stargazers"))
        if star_link:
            star_text = star_link.get_text(strip=True)

        # 编程语言
        lang_text = ""
        lang_el = art.select_one("[itemprop='programmingLanguage']")
        if lang_el:
            lang_text = lang_el.get_text(strip=True)

        # Topic 标签
        tag_links = art.find_all("a", href=re.compile(r"^/topics/"))
        tags = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # 组合正文
        parts = []
        if description:
            parts.append(description)
        meta_bits = []
        if lang_text:
            meta_bits.append(f"语言：{lang_text}")
        if star_text:
            meta_bits.append(f"Stars：{star_text}")
        if tags:
            meta_bits.append(f"标签：{', '.join(tags[:8])}")
        if meta_bits:
            parts.append(" | ".join(meta_bits))
        content_text = "\n".join(parts)

        items.append(FetchItem(
            title=title,
            url=repo_url,
            canonical_url=repo_url,
            author=owner_name or None,
            published_at=None,  # GitHub Topics 列表页无发布时间
            source_item_id=repo_url,
            raw_html=None,
            content_text=content_text,
            language=lang_text or None,
        ))

    logger.info("GitHub Topics [%s] 抓取完成：%d 个项目", source.get("name"), len(items))
    return items



# ---------- SPA 列表抓取（Playwright 渲染） ----------
# 适用于纯 JS 渲染的站点（如机器之心 jiqizhixin.com）：SSR 不返回文章链接和正文，
# 必须执行 JS 才能拿到内容。用 Playwright 启动无头 Chromium 渲染页面。
# 复用熔断机制：连续 _FAIL_CIRCUIT 次渲染/提取失败则停止该来源后续抓取。
def _spa_goto(page, url: str, min_text_len: int = 0) -> str:
    """Playwright 页面导航通用等待：domcontentloaded + networkidle（容忍超时）+ 正文/渲染缓冲。

    min_text_len>0 时，等待 body 纯文本长度达标（适用于正文异步加载的文章页），
    达标或超时（8s）后返回；min_text_len=0 时用固定 2s 缓冲（适用于列表页）。
    """
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        # 部分站点持续有长轮询/埋点请求，networkidle 永远达不到，忽略后靠固定延时兜底
        pass
    if min_text_len > 0:
        try:
            page.wait_for_function(
                f"() => document.body && document.body.innerText.length >= {min_text_len}",
                timeout=8000,
            )
        except Exception:
            # 超时仍未达标，再给一点缓冲后放弃等待
            page.wait_for_timeout(1000)
    else:
        page.wait_for_timeout(2000)
    return page.content()


def _fetch_spa_list(source: dict) -> list[FetchItem]:
    """SPA 列表抓取分派器：按 host 选择抓取策略。

    不同 SPA 站点结构差异大，按 host 分派到专用实现。新增 SPA 站点时在此加分支。
    """
    return _fetch_spa_list_dom(source)


def _fetch_spa_list_dom(source: dict) -> list[FetchItem]:
    """通用 SPA 列表渲染：Playwright 渲染列表页，提取 <a href> 文章链接，逐篇渲染抓正文。

    一个浏览器实例完成列表页 + 所有文章页渲染，避免反复启动浏览器的开销。
    文章链接匹配规则：同 host 且 path 以 /articles/ 开头。
    """
    from playwright.sync_api import sync_playwright

    url = source["url"]
    logger.info("SPA 列表抓取开始：[%s] %s", source.get("name"), url)

    items: list[FetchItem] = []
    try:
        pw = sync_playwright().start()
    except Exception as e:
        logger.error("Playwright 启动失败，SPA 抓取中止：%s", e)
        return []
    browser = None
    try:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=settings.fetch_user_agent)
        page.set_extra_http_headers({"Accept-Language": "en,zh-CN;q=0.8,zh;q=0.6"})

        # 1. 渲染列表页
        try:
            list_html = _spa_goto(page, url)
        except Exception as e:
            logger.warning("SPA 列表页渲染失败 %s: %s", url, e)
            return []

        soup = BeautifulSoup(list_html, "lxml")
        base_host = urlsplit(url).netloc.lower()
        seen: set[str] = set()
        article_links: list[tuple[str, str]] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            abs_url = urljoin(url, href)
            parts = urlsplit(abs_url)
            # 同 host + path 以 /articles/ 开头（排除 /articles 列表页本身）
            if parts.netloc.lower() != base_host:
                continue
            if not parts.path.startswith("/articles/"):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)
            title_hint = a.get_text(" ", strip=True)[:120]
            article_links.append((abs_url, title_hint))

        logger.info("[%s] SPA 列表页解析出 %d 个候选文章链接", source.get("name"), len(article_links))
        if not article_links:
            return []

        # 2. 逐篇渲染抓正文
        consecutive_fail = 0
        for abs_url, title_hint in article_links:
            if consecutive_fail >= _FAIL_CIRCUIT:
                logger.warning("[%s] 连续 %d 次渲染抓取失败，触发熔断，停止后续文章",
                               source.get("name"), _FAIL_CIRCUIT)
                break
            try:
                article_html = _spa_goto(page, abs_url)
            except Exception as e:
                consecutive_fail += 1
                logger.warning("[%s] SPA 文章页渲染失败(%d/%d)：%s %s",
                               source.get("name"), consecutive_fail, _FAIL_CIRCUIT, abs_url, e)
                continue
            item = _extract_item_from_html(abs_url, article_html, title_hint)
            if item and len(item.content_text) >= _MIN_SUMMARY_LEN:
                if not item.title:
                    item.title = title_hint or abs_url
                items.append(item)
                consecutive_fail = 0
                logger.debug("[%s] SPA 文章提取成功：%s 正文 %d 字符",
                             source.get("name"), abs_url, len(item.content_text))
            else:
                consecutive_fail += 1
                logger.warning("[%s] SPA 文章正文提取失败/过短(%d/%d)：%s",
                               source.get("name"), consecutive_fail, _FAIL_CIRCUIT, abs_url)
    except Exception as e:
        logger.warning("[%s] SPA 抓取过程异常，已抓 %d 篇：%s", source.get("name"), len(items), e)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        pw.stop()

    logger.info("SPA 列表 [%s] 抓取完成：%d 篇文章成功提取正文",
                source.get("name"), len(items))
    return items


# ---------- B站搜索（wbi 签名） ----------
# B站搜索结果是 SPA 动态渲染的，直接抓 HTML 拿不到数据。
# 通过 wbi 签名调官方搜索 API 获取结果。
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 36, 25, 24, 11, 44, 26, 4, 20, 21, 16, 34, 6, 48, 7, 40,
    22, 17, 30, 1, 51, 57, 52, 0, 55, 54, 60, 59, 61, 56, 63, 62,
]
_WBI_STRIP_CHARS = str.maketrans("", "", "!'()*_")
_WBI_KEYS_TTL = 3600  # wbi keys 缓存 1 小时
_wbi_keys_cache: tuple[str, str, float] | None = None  # (img_key, sub_key, expire_ts)

BILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/wbi/search/type"
BILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"

_bili_session: requests.Session | None = None


def _get_bili_session() -> requests.Session:
    """获取带 cookie 的 B站 session（缓存）。

    B站搜索 API 在无 cookie 时返回空结果，需要先访问首页获取 buvid3 等 cookie。
    """
    global _bili_session
    if _bili_session is not None:
        return _bili_session
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://search.bilibili.com",
        "Origin": "https://search.bilibili.com",
    })
    try:
        _throttle_for_host("https://www.bilibili.com")
        sess.get("https://www.bilibili.com", timeout=TIMEOUT)
        logger.debug("B站 cookie 获取成功：%s", list(sess.cookies.keys()))
    except Exception as e:
        logger.warning("B站首页访问失败，无 cookie 继续：%s", e)
    _bili_session = sess
    return sess


def _get_wbi_keys() -> tuple[str, str]:
    """获取 B站 wbi 签名密钥（img_key + sub_key），缓存 1 小时。"""
    global _wbi_keys_cache
    now = time.time()
    if _wbi_keys_cache and now < _wbi_keys_cache[2]:
        return _wbi_keys_cache[0], _wbi_keys_cache[1]
    resp = _http_get(BILI_NAV_API)
    resp.raise_for_status()
    wbi_img = resp.json().get("data", {}).get("wbi_img", {})
    img_key = (wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = (wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    if not img_key or not sub_key:
        if _wbi_keys_cache:
            return _wbi_keys_cache[0], _wbi_keys_cache[1]
        raise ValueError("nav API 未返回有效的 wbi keys")
    _wbi_keys_cache = (img_key, sub_key, now + _WBI_KEYS_TTL)
    return img_key, sub_key


def _get_mixin_key(orig: str) -> str:
    """用固定的重排表从 img_key+sub_key 生成 32 位 mixin_key。"""
    return "".join(orig[i] for i in _MIXIN_KEY_ENC_TAB)[:32]


def _enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """对请求参数做 wbi 签名，返回附加了 wts 和 w_rid 的参数字典。"""
    mixin_key = _get_mixin_key(img_key + sub_key)
    params = {k: str(v).translate(_WBI_STRIP_CHARS) for k, v in params.items()}
    params["wts"] = str(round(time.time()))
    params = dict(sorted(params.items()))
    query = urlencode(params)
    params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params


def _fetch_bilibili_search(source: dict) -> list[FetchItem]:
    """B站搜索：通过 wbi 签名调官方搜索 API，返回视频结果列表。

    source.url 格式如 https://search.bilibili.com/all?keyword=AI%20Agent，
    从 query 参数提取搜索关键词，调搜索 API 获取结果。
    """
    url = source["url"]
    keyword = parse_qs(urlsplit(url).query).get("keyword", [""])[0]
    if not keyword:
        kw_field = source.get("keywords") or ""
        keyword = kw_field.split(",")[0].strip() if kw_field else ""
    if not keyword:
        logger.warning("[%s] 无法提取搜索关键词，URL=%s", source.get("name"), url)
        return []

    logger.info("B站搜索开始：[%s] keyword=%s", source.get("name"), keyword)

    img_key, sub_key = _get_wbi_keys()
    # order/length/tids 即使为默认值也需显式传递，否则 B站 API 可能返回空结果
    params = _enc_wbi(
        {"search_type": "video", "keyword": keyword, "page": 1, "page_size": 20,
         "order": "", "length": 4, "tids": 0},
        img_key, sub_key,
    )
    full_url = f"{BILI_SEARCH_API}?{urlencode(params)}"
    sess = _get_bili_session()
    _throttle_for_host(full_url)
    resp = sess.get(full_url, timeout=TIMEOUT)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        logger.warning("[%s] B站搜索 API 返回错误：%s", source.get("name"), body.get("message"))
        return []

    data = body.get("data", {})
    results = data.get("result") or []
    if not results and "v_voucher" in data:
        logger.warning("[%s] B站触发人机验证（v_voucher），可能因请求频率过高被风控", source.get("name"))
    items: list[FetchItem] = []
    for r in results:
        # 清理 title 中的 <em> 高亮标签
        title = re.sub(r"<[^>]+>", "", r.get("title") or "").strip() or r.get("title") or ""
        bvid = r.get("bvid") or ""
        arcurl = r.get("arcurl") or (f"https://www.bilibili.com/video/{bvid}" if bvid else "")
        desc = (r.get("description") or "").strip()
        pubdate = r.get("pubdate")
        published_at = _normalize_datetime(pubdate) if pubdate else None
        items.append(FetchItem(
            title=title,
            url=arcurl,
            canonical_url=arcurl,
            author=r.get("author"),
            published_at=published_at,
            source_item_id=bvid or arcurl,
            raw_html=None,
            content_text=desc,
            language="zh",
            fetch_error=None if desc else "视频无简介",
        ))
    logger.info("B站搜索 [%s] 完成：%d 条结果", source.get("name"), len(items))
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

    item = _extract_item_from_html(url, html)
    if not item:
        logger.warning("正文提取彻底失败，返回空：%s", url)
        return None, "正文提取失败（trafilatura 与 BeautifulSoup 均为空）"
    logger.debug("文章页提取成功：%s 正文 %d 字符", url, len(item.content_text))
    return item, None


def _extract_item_from_html(url: str, html: str, title_hint: str | None = None) -> FetchItem | None:
    """从已抓到的 HTML 提取 FetchItem（trafilatura 优先，BS4 兜底）。提取失败返回 None。

    供 _fetch_article_page_with_error（HTTP 抓取）和 _fetch_spa_list（Playwright 渲染）
    复用，避免正文提取逻辑重复。
    """
    title, content_text, canonical, lang, date = _extract_with_trafilatura(html, url)
    if not content_text:
        logger.debug("trafilatura 提取为空，退回 BeautifulSoup：%s", url)
        soup = BeautifulSoup(html, "lxml")
        title = title or (soup.title.string.strip() if soup.title and soup.title.string else url)
        content_text = _fallback_text(soup)
        canonical = canonical or _extract_canonical(url, html)
        lang = lang or _meta(soup, "language") or _lang_from_html(soup)
        # BS4 兜底时也从 meta 标签补一次发布时间
        date = date or _meta(soup, "article:published_time") or _meta(soup, "date")

    if not content_text:
        return None
    return FetchItem(
        title=(title or title_hint or url),
        url=url,
        canonical_url=canonical,
        author=None,
        published_at=_normalize_datetime(date),
        source_item_id=canonical or url,
        raw_html=html,
        content_text=content_text,
        language=lang,
    )


def _extract_with_trafilatura(html: str, source_url: str) -> tuple[str | None, str, str | None, str | None, str | None]:
    """用 trafilatura 提取正文、标题、canonical、语言、发布日期。失败返回空串。"""
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
    date: str | None = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=source_url)
        if meta:
            title = meta.title
            canonical = meta.url or source_url
            lang = meta.language
            date = meta.date
    except Exception:
        pass
    return title, content_text, canonical, lang, date


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


def _normalize_datetime(val) -> str | None:
    """把各种日期格式归一化为 MySQL DATETIME 格式 YYYY-MM-DD HH:MM:SS。

    MySQL DATETIME 不接受 ISO8601 的 T 分隔符和时区后缀，也不接受 RFC822 格式，
    非严格 SQL mode 下无法解析的日期会被存成 0000-00-00 00:00:00。
    支持：time.struct_time / datetime / ISO8601 / RFC822 / unix timestamp / 已合格格式。
    """
    if not val:
        return None
    # time.struct_time（feedparser 的 *_parsed 字段）
    if isinstance(val, time.struct_time):
        return time.strftime("%Y-%m-%d %H:%M:%S", val)
    # datetime 对象
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    s = str(val).strip()
    if not s:
        return None
    # 已经是 MySQL DATETIME 格式
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", s):
        return s
    # 已经是 MySQL DATE 格式
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return f"{s} 00:00:00"
    # ISO8601（带 T 和时区，如 2024-01-01T00:00:00+00:00 或 ...Z）
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    # RFC822（如 Mon, 01 Jan 2024 00:00:00 +0000）
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        pass
    # unix timestamp（字符串或数字）
    try:
        return datetime.fromtimestamp(float(s), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        pass
    logger.debug("无法解析的日期格式，已置空：%r", s)
    return None


def _parse_published(entry) -> str | None:
    # 优先用 feedparser 解析好的 *_parsed（time.struct_time），格式最可靠；
    # 回退到原始字符串字段，再由 _normalize_datetime 统一转 MySQL DATETIME。
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        val = entry.get(key)
        if val:
            return _normalize_datetime(val)
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            if isinstance(val, list):
                val = val[0]
            return _normalize_datetime(val)
    return None
