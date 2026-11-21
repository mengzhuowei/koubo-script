"""项目助手的附件读取插件与临时附件。"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from io import BytesIO
from itertools import islice
from pathlib import PurePosixPath
from threading import BoundedSemaphore, Lock
from time import monotonic
from uuid import uuid4
from zipfile import ZipFile

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 6
_TEXT_LIMIT = 80_000
_PART_SIZE = 4_000
_STORE_LIMIT = 48
_TTL_SECONDS = 2 * 60 * 60
_parse_slots = BoundedSemaphore(2)
_lock = Lock()


class AttachmentError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Reader:
    label: str
    guidance: str
    extract: Callable[[bytes], tuple[str, bool]]


@dataclass(frozen=True)
class Attachment:
    id: str
    name: str
    extension: str
    size: int
    text: str
    truncated: bool
    expires: float

    def metadata(self) -> dict:
        return {
            "name": self.name, "format": self.extension, "size": self.size,
            "parts": (len(self.text) + _PART_SIZE - 1) // _PART_SIZE,
            "truncated": self.truncated, "plugin": READERS[self.extension].label,
        }

    def read(self, part: int) -> dict:
        meta = self.metadata()
        if part > meta["parts"]:
            raise AttachmentError(f"附件共 {meta['parts']} 段，请选择范围内的段号。")
        offset = (part - 1) * _PART_SIZE
        return {
            **meta, "part": part, "text": self.text[offset:offset + _PART_SIZE],
            "reading_guidance": READERS[self.extension].guidance,
        }

    def search(self, keyword: str) -> list[dict]:
        matches = re.finditer(re.escape(keyword), self.text, flags=re.IGNORECASE)
        return [{"part": match.start() // _PART_SIZE + 1,
                 "excerpt": self.text[max(0, match.start() - 100):match.end() + 160]}
                for match in islice(matches, 4)]


def _collect(sections: Iterable[str]) -> tuple[str, bool]:
    parts = []
    remaining = _TEXT_LIMIT
    for section in sections:
        if not section:
            continue
        if parts:
            section = "\n" + section
        parts.append(section[:remaining])
        if len(section) > remaining:
            return "".join(parts), True
        remaining -= len(section)
    return "".join(parts), False


def _plain(raw: bytes) -> tuple[str, bool]:
    try:
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
    if "\x00" in text:
        raise AttachmentError("文件中包含二进制内容，请上传文本文件。")
    return text[:_TEXT_LIMIT], len(text) > _TEXT_LIMIT


def _check_office_archive(raw: bytes) -> None:
    with ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 2000 or sum(member.file_size for member in members) > 24 * 1024 * 1024:
            raise AttachmentError("文档解压内容过大，请拆分后上传。", 413)


def _word(raw: bytes) -> tuple[str, bool]:
    from docx import Document
    from docx.text.paragraph import Paragraph

    _check_office_archive(raw)
    document = Document(BytesIO(raw))

    def sections():
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                yield item.text
            else:
                for row in item.rows:
                    yield "\t".join(cell.text for cell in row.cells)

    return _collect(sections())


def _pdf(raw: bytes) -> tuple[str, bool]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(raw))
    if reader.is_encrypted:
        raise AttachmentError("请先解除 PDF 的密码保护，再上传。")
    sections = (f"[第 {index} 页]\n{text}" for index, page in enumerate(islice(reader.pages, 40), 1)
                if (text := page.extract_text().strip()))
    text, truncated = _collect(sections)
    if not text:
        raise AttachmentError("PDF 中没有可提取的文字。扫描件请先做 OCR 或转成文本。")
    return text, truncated or len(reader.pages) > 40


def _sheet(raw: bytes) -> tuple[str, bool]:
    from openpyxl import load_workbook

    _check_office_archive(raw)
    book = load_workbook(BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    selected = book.worksheets[:8]
    sampled = len(book.worksheets) > len(selected)

    def sections():
        nonlocal sampled
        for sheet in selected:
            yield f"[工作表 {sheet.title}]"
            sampled = sampled or (sheet.max_row or 0) > 400 or (sheet.max_column or 0) > 32
            for number, row in enumerate(sheet.iter_rows(max_row=401, max_col=33, values_only=True), 1):
                if number > 400:
                    sampled = sampled or any(value is not None for value in row)
                    break
                sampled = sampled or row[-1] is not None
                if any(value is not None for value in row[:32]):
                    values = ["" if value is None else str(value) for value in row[:32]]
                    yield f"{number}\t" + "\t".join(values).rstrip("\t")

    try:
        text, truncated = _collect(sections())
    finally:
        book.close()
    return text, truncated or sampled


_note = Reader("文本读取", "用文件中的事实回答，引用关键原文，明确文件中缺失的信息。", _plain)
_text_table = Reader("分隔表格读取", "先识别表头和分隔符，按列核对单位及空值，再计算或总结。", _plain)
READERS = {
    ".txt": _note, ".md": _note, ".json": _note,
    ".csv": _text_table, ".tsv": _text_table,
    ".pdf": Reader("PDF 文字提取", "引用结论时标注提取文本中的页码。", _pdf),
    ".docx": Reader("Word 文档读取", "保留段落与表格的语义，提炼要点时标明依据。", _word),
    ".xlsx": Reader("Excel 表格读取", "先核对工作表、行号、表头与单位，说明统计覆盖的范围。", _sheet),
}
_stored: dict[str, Attachment] = {}


def _remove_expired() -> None:
    now = monotonic()
    for attachment in tuple(_stored.values()):
        if attachment.expires <= now:
            del _stored[attachment.id]


def store_attachment(name: str, raw: bytes) -> Attachment:
    name = PurePosixPath(name.replace("\\", "/")).name.strip()
    extension = PurePosixPath(name).suffix.lower()
    if extension not in READERS:
        raise AttachmentError("请上传 TXT、Markdown、JSON、CSV、TSV、PDF、DOCX 或 XLSX 文件。", 415)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AttachmentError("每个附件最多 5 MB。", 413)
    if not _parse_slots.acquire(blocking=False):
        raise AttachmentError("附件正在处理中，请稍后再试。", 503)
    try:
        text, truncated = READERS[extension].extract(raw)
    except AttachmentError:
        raise
    except Exception:
        raise AttachmentError("文件内容无法读取，请确认格式正确且文件完整。") from None
    finally:
        _parse_slots.release()
    text = text.strip()
    if not text:
        raise AttachmentError("附件没有可读取的内容。")
    item = Attachment(uuid4().hex, name[:180], extension, len(raw), text, truncated, monotonic() + _TTL_SECONDS)
    with _lock:
        _remove_expired()
        if len(_stored) >= _STORE_LIMIT:
            del _stored[next(iter(_stored))]
        _stored[item.id] = item
    return item


def resolve_attachments(ids: list[str]) -> tuple[dict[str, Attachment], list[str]]:
    with _lock:
        _remove_expired()
        found = {key: _stored[key] for key in dict.fromkeys(ids) if key in _stored}
    return {f"file{index}": item for index, item in enumerate(found.values(), 1)}, [key for key in ids if key not in found]
