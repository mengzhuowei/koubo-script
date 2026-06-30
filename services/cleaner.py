"""内容清洗：URL 规范化、content_hash 生成、去重判定。"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urldefrag, urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """规范化 URL：去 fragment、去常见跟踪参数、小写 host。"""
    if not url:
        return url
    url, _ = urldefrag(url)
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    # 去掉常见跟踪参数
    keep = []
    if parts.query:
        for kv in parts.query.split("&"):
            if "=" in kv:
                k = kv.split("=", 1)[0].lower()
            else:
                k = kv.lower()
            if k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "from"):
                continue
            keep.append(kv)
    query = "&".join(keep)
    return urlunsplit((scheme, netloc, path, query, ""))


def compute_content_hash(title: str, content_text: str) -> str:
    """normalize(title + content_text[:5000]) -> sha256。"""
    base = f"{title.strip()}\n{(content_text or '')[:5000]}"
    base = re.sub(r"\s+", " ", base).strip()
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    """压缩空白，用于摘要比对。"""
    return re.sub(r"\s+", " ", (text or "")).strip()
