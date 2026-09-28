"""Read-only import of a vendor's exported Android forensic HTML report.

The export is a *derived report*, not a phone image or an application database.
Only HTML text, read-only export metadata, and references to existing attachments
are indexed. Vendor JavaScript and executables are never run or copied.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from ..config import get_data_root, get_project_root

IMPORT_ID = re.compile(r"[0-9a-f]{32}\Z")
CONTENT_PAGE = re.compile(r"content\d+\.html\Z", re.IGNORECASE)
DATE = re.compile(r"(?<!\d)(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})(?:日)?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
MAX_PAGES = 2000
MAX_PAGE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_PAGE_BYTES = 256 * 1024 * 1024
MAX_RECORD_CHARS = 32_000
MAX_ATTACHMENTS = 30
MAX_ATTACHMENT_HASH_BYTES = 128 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_HASH_BYTES = 512 * 1024 * 1024
MAX_PAGE_JS_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_EXPORT_DB_BYTES = 128 * 1024 * 1024
MAX_TABLES_PER_PAGE = 5000
MAX_ROWS_PER_PAGE = 200000
MAX_HTML_DEPTH = 256
MAX_SCAN_FILES = 100000
MAX_SCAN_DIRS = 10000
PARSER_VERSION = "external-html-report-v3.3"
SOURCE_TYPE = "external_html_report"
_ALLOWED_HTML_ENCODINGS = {"utf-8", "utf8", "gbk", "gb2312", "gb18030"}

_FIELD_ALIASES = {
    "发送人": "sender", "发件人": "sender", "sender": "sender",
    "接收人": "receiver", "收件人": "receiver", "receiver": "receiver",
    "消息内容": "content", "内容": "content", "message": "content",
    "时间": "timestamp", "日期": "timestamp", "timestamp": "timestamp",
    "账号": "account", "账户": "account", "account": "account",
    "文件路径": "file_path", "路径": "file_path", "file path": "file_path",
}


def _field_name(label: str) -> str | None:
    return _FIELD_ALIASES.get(" ".join(label.strip().casefold().split()))


def _application(labels: list[str]) -> str | None:
    # Only explicit navigation/section/table labels, never a record's value.
    for label in labels:
        value = label.strip().casefold()
        if "微信" in value or re.search(r"\bwechat\b", value):
            return "微信"
        if re.search(r"\bqq\b", value) or value.startswith("qq"):
            return "QQ"
    return None


def _warning(code: str, path: str | None = None, detail: str | None = None) -> dict:
    item = {"code": code}
    if path is not None:
        item["path"] = path
    if detail is not None:
        item["detail"] = detail
    return item


class InvalidReport(ValueError):
    """The selected directory is not a supported offline report export."""


def import_root() -> Path:
    return get_data_root() / "android_report_imports"


def candidate_root() -> Path:
    """The server-local inbox; defaults to the parent of the project checkout."""
    configured = os.environ.get("ANDROID_REPORT_SEARCH_ROOT")
    return Path(configured).expanduser().resolve() if configured else get_project_root().parent.resolve()


def list_candidates() -> list[dict]:
    """Discover report packages without exposing arbitrary filesystem browsing."""
    base = candidate_root()
    if not base.is_dir():
        return []
    existing = {}
    for item in list_imports():
        if item.get("parser_version") != PARSER_VERSION:
            continue
        existing.setdefault(item.get("source_path"), item.get("import_id"))
    candidates = []
    for entry in sorted(base.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if not (entry / "index.html").is_file() or not (entry / "report").is_dir():
            continue
        if not any((entry / "report").glob("*/export.db")):
            continue
        resolved = entry.resolve()
        if not resolved.is_relative_to(base):
            continue
        candidates.append({
            "id": hashlib.sha256(str(resolved).encode()).hexdigest()[:24],
            "name": entry.name,
            "existing_import_id": existing.get(str(resolved)),
        })
        if len(candidates) >= 200:
            break
    return candidates


def create_import_from_candidate(candidate_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{24}", candidate_id or ""):
        raise ValueError("invalid report selection")
    for candidate in list_candidates():
        if candidate["id"] != candidate_id:
            continue
        if candidate["existing_import_id"]:
            with closing(_connect(candidate["existing_import_id"])) as con:
                existing = _meta(con)
                if _source_still_matches(existing):
                    return existing
        source = candidate_root() / candidate["name"]
        if source.is_symlink() or not source.resolve(strict=True).is_relative_to(candidate_root()):
            raise InvalidReport("selected report escaped the configured candidate root")
        return create_import(str(source))
    raise InvalidReport("selected report is no longer available")


def _source_still_matches(meta: dict) -> bool:
    """Do not reuse a stale derived index after source files changed."""
    if meta.get("parser_version") != PARSER_VERSION or meta.get("status") == "FAILED":
        return False
    if meta.get("unhashed_attachment_count"):
        return False
    try:
        manifest = read_manifest(meta["import_id"])
        entries = manifest.get("source_files")
        if not isinstance(entries, list):
            return False
        root = _verified_import_root(meta)
        if (root / "report/page.js").is_file() != manifest.get("page_js_exists"):
            return False
        export_paths = sorted(path.relative_to(root).as_posix() for path in (root / "report").glob("*/export.db"))
        if export_paths != manifest.get("export_files"):
            return False
        landing_index_paths = sorted(path.relative_to(root).as_posix() for path in (root / "report").glob("*/index.html"))
        if landing_index_paths != manifest.get("landing_index_files"):
            return False
        pages, skipped, _ = _report_pages(root)
        current = {page.relative_to(root).as_posix() for page, _ in pages}
        current.update(item["path"] for item in skipped)
        if sorted(current) != manifest.get("discovered_content_pages"):
            return False
        current_data = sorted({(page.parent / "data.js").relative_to(root).as_posix()
                               for page, _ in pages if page.parent.name == "content" and (page.parent / "data.js").is_file()})
        if current_data != manifest.get("data_js_files"):
            return False
        indexed_paths = {item["path"] for item in entries}
        if (root / "report/page.js").is_file() and "report/page.js" not in indexed_paths:
            return False
        if any(path not in indexed_paths for path in current_data):
            return False
        if len(manifest.get("attachment_refs", [])) != manifest.get("attachment_ref_count"):
            return False
        if any(path not in indexed_paths and path not in meta.get("missing_attachment_paths", [])
               for path in manifest.get("attachment_refs", [])):
            return False
        for entry in entries:
            relative = entry["path"]
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                return False
            if _sha256(_safe_source(root, root / relative)) != entry["sha256"]:
                return False
        if any((root / path).exists() for path in meta.get("missing_attachment_paths", [])):
            return False
        return True
    except (OSError, ValueError, KeyError, InvalidReport):
        return False


def _import_dir(import_id: str) -> Path:
    if not IMPORT_ID.fullmatch(import_id):
        raise ValueError("invalid import ID")
    return import_root() / import_id


def _db_path(import_id: str) -> Path:
    path = _import_dir(import_id) / "records.db"
    if not path.is_file():
        raise FileNotFoundError("report import not found")
    return path


def _connect(import_id: str) -> sqlite3.Connection:
    path = _db_path(import_id)
    con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode_html(raw: bytes) -> str:
    header = raw[:4096].decode("ascii", errors="ignore")
    match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", header, re.IGNORECASE)
    encoding = (match.group(1).lower() if match else "utf-8")
    if encoding not in _ALLOWED_HTML_ENCODINGS:
        encoding = "utf-8"
    return raw.decode(encoding, errors="replace")


def _safe_source(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise InvalidReport("report file escapes the selected directory")
    return resolved


def _verified_import_root(meta: dict) -> Path:
    stored = Path(meta["source_path"])
    resolved = stored.resolve(strict=True)
    if resolved != stored or not resolved.is_dir():
        raise InvalidReport("report source root moved or became a symlink")
    return resolved


def _attachment(page: Path, root: Path, reference: str) -> dict | None:
    """Resolve a report-relative media link without allowing filesystem escape."""
    reference = reference.strip().replace("\\", "/")
    if not reference or reference.startswith(("#", "//")):
        return None
    try:
        parsed = urlsplit(reference)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    path_part = unquote(parsed.path)
    if "/resource/" not in path_part or path_part.endswith("/"):
        return None
    try:
        candidate = (page.parent / path_part).resolve(strict=False)
    except (ValueError, OSError):
        return None
    if not candidate.is_relative_to(root):
        return None
    return {
        "path": candidate.relative_to(root).as_posix(),
        "available": candidate.is_file(),
    }


def _category(heading: str) -> str:
    for label, keywords in (
        ("微信", ("微信", "wechat")),
        ("QQ", ("qq", "腾讯qq")),
        ("短信", ("短信", "短信息", "sms", "彩信")),
        ("通话", ("通话", "电话", "call")),
        ("联系人", ("联系人", "通讯录", "contact")),
        ("网盘", ("网盘", "云盘", "云存储")),
        ("浏览器", ("浏览器", "browser", "网页历史")),
        ("媒体", ("照片", "图片", "视频", "音频", "录音")),
        ("设备", ("设备", "手机信息", "系统信息")),
    ):
        if any(word in heading.lower() for word in keywords):
            return label
    return "其他"


def _section_category(path: list[str], heading: str) -> str:
    # The navigation tree identifies the report section; page headings may
    # describe a nested presentation element rather than the record category.
    for label in [*reversed(path), heading]:
        category = _category(label)
        if category != "其他":
            return category
    return "其他"


def _timestamp(text: str) -> str | None:
    match = DATE.search(text)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        value = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
    except ValueError:
        return None
    # The vendor report does not specify a reliable timezone. Do not add one.
    return value.isoformat(sep=" ") if hour else value.date().isoformat()


@dataclass
class _Row:
    table: "_Table"
    cells: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    header: bool = False
    cell_parts: list[str] | None = None
    start_line: int = 0
    start_col: int = 0


@dataclass
class _Table:
    index: int
    heading: str
    anchor: str
    category: str
    headers: list[str] = field(default_factory=list)
    row_index: int = 0


class _ReportPageParser(HTMLParser):
    """Extract displayed table rows; treat all report HTML as untrusted data."""

    def __init__(self, page: Path, root: Path, specimen: str, navigation: dict,
                 previous: tuple[list[str], str, str] | None = None):
        super().__init__(convert_charrefs=True)
        self.page = page
        self.root = root
        self.specimen = specimen
        self.section_path, self.heading, self.anchor = previous or ([], "报告概览", "")
        self.navigation = navigation
        self.heading_parts: list[str] | None = None
        self.tables: list[_Table] = []
        self.rows: list[_Row] = []
        self.records: list[dict] = []
        self.media: dict[str, dict] = {}
        self.table_index = 0
        self.skip_depth = 0
        self.depth = 0
        self.total_tables = 0
        self.total_rows = 0
        self.truncated_rows = 0
        self.unknown_fields = 0
        self.attachment_refs_truncated = 0
        self._line_offsets: list[int] = []
        self._source_text = ""

    def set_source_text(self, value: str) -> None:
        self._source_text = value
        self._line_offsets = [0]
        for match in re.finditer("\n", value):
            self._line_offsets.append(match.end())

    def _offset(self, line: int, col: int) -> int:
        return self._line_offsets[line - 1] + col if 0 < line <= len(self._line_offsets) else 0

    def _endtag_offset(self) -> int:
        start = self._offset(*self.getpos())
        close = self._source_text.find(">", start)
        return close + 1 if close >= start else start

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "iframe"):
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.depth += 1
            if self.depth > MAX_HTML_DEPTH:
                raise InvalidReport("HTML nesting exceeds supported limit")
        attrs_by_name = dict(attrs)
        for name in ("href", "src", "data-src"):
            value = attrs_by_name.get(name)
            if value:
                media = _attachment(self.page, self.root, value)
                if media:
                    self.media[media["path"]] = media
        if tag == "a" and attrs_by_name.get("id"):
            self.anchor = attrs_by_name["id"][:120]
            self.section_path = self.navigation.get((self.page.name, self.anchor), self.section_path)
        if tag in ("h2", "h3", "h4"):
            self.heading_parts = []
        if tag == "table":
            self.table_index += 1
            self.total_tables += 1
            if self.total_tables > MAX_TABLES_PER_PAGE:
                raise InvalidReport("table count exceeds supported limit")
            title = self.section_path[-1] if self.section_path else self.heading
            self.tables.append(_Table(
                self.table_index, title, self.anchor,
                _section_category(self.section_path, self.heading),
            ))
        elif tag == "tr" and self.tables:
            self.total_rows += 1
            if self.total_rows > MAX_ROWS_PER_PAGE:
                raise InvalidReport("row count exceeds supported limit")
            line, col = self.getpos()
            self.rows.append(_Row(self.tables[-1], start_line=line, start_col=col))
        elif tag in ("td", "th") and self.rows:
            self.rows[-1].cell_parts = []
            self.rows[-1].header = self.rows[-1].header or tag == "th"
        elif tag == "br" and self.rows and self.rows[-1].cell_parts is not None:
            self.rows[-1].cell_parts.append("\n")
        if self.rows and self.rows[-1].cell_parts is not None:
            for name in ("href", "src", "data-src"):
                value = attrs_by_name.get(name)
                if value:
                    self.rows[-1].links.append(value)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        if self.rows and self.rows[-1].cell_parts is not None:
            self.rows[-1].cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "iframe"):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.depth = max(0, self.depth - 1)
        if tag in ("h2", "h3", "h4") and self.heading_parts is not None:
            value = " ".join(" ".join(self.heading_parts).split())
            if value:
                self.heading = value[:240]
            self.heading_parts = None
        elif tag in ("td", "th") and self.rows and self.rows[-1].cell_parts is not None:
            value = " ".join(" ".join(self.rows[-1].cell_parts).split())
            self.rows[-1].cells.append(value)
            self.rows[-1].cell_parts = None
        elif tag == "tr" and self.rows:
            row = self.rows.pop()
            if row.header:
                row.table.headers = row.cells
            elif any(row.cells):
                row.table.row_index += 1
                rel = self.page.relative_to(self.root).as_posix()
                text = " | ".join(cell for cell in row.cells if cell)
                fields = {}
                for index, value in enumerate(row.cells):
                    label = row.table.headers[index] if index < len(row.table.headers) else f"column_{index + 1}"
                    key = label or f"column_{index + 1}"
                    if key in fields:
                        key = f"{key}_{index + 1}"
                    fields[key] = value
                normalized = {}
                for key, value in fields.items():
                    field = _field_name(key)
                    if field and field not in normalized and value:
                        normalized[field] = value
                    elif not field:
                        self.unknown_fields += 1
                timestamp = _timestamp(normalized["timestamp"]) if "timestamp" in normalized else None
                truncated = len(text) > MAX_RECORD_CHARS
                if truncated:
                    self.truncated_rows += 1
                attachments = []
                seen = set()
                for reference in row.links:
                    media = _attachment(self.page, self.root, reference)
                    if media and media["path"] not in seen:
                        seen.add(media["path"])
                        if len(attachments) < MAX_ATTACHMENTS:
                            attachments.append(media)
                        else:
                            self.attachment_refs_truncated += 1
                key = f"{rel}:{row.table.index}:{row.table.row_index}"
                self.records.append({
                    "id": hashlib.sha256(key.encode()).hexdigest()[:32],
                    "record_kind": "table_row",
                    "specimen": self.specimen,
                    "category": row.table.category,
                    "heading": row.table.heading,
                    "section_title": self.section_path[-1] if self.section_path else self.heading,
                    "table_title": self.heading,
                    "application": _application([*reversed(self.section_path), self.heading, row.table.heading]),
                    "content": normalized.get("content"),
                    "raw_text": text[:MAX_RECORD_CHARS],
                    "content_truncated": truncated,
                    "fields": fields,
                    "normalized": normalized,
                    "occurred_at": timestamp,
                    "source_file": rel,
                    "source_anchor": row.table.anchor,
                    "source_table": row.table.index,
                    "source_row": row.table.row_index,
                    "source_locator": f"{rel}#table-{row.table.index}-row-{row.table.row_index}",
                    "source_start_offset": self._offset(row.start_line, row.start_col),
                    "source_end_offset": self._endtag_offset(),
                    "attachments": attachments,
                })
        elif tag == "table" and self.tables:
            self.tables.pop()


class _ReportSectionParser(HTMLParser):
    """Conservatively index text-only report pages as sections, not app records."""

    def __init__(self, page: Path, root: Path, specimen: str, navigation: dict, source_text: str):
        super().__init__(convert_charrefs=True)
        self.page, self.root, self.specimen = page, root, specimen
        self.navigation, self.source_text = navigation, source_text
        self.records: list[dict] = []
        self.media: dict[str, dict] = {}
        self.truncated_rows = 0
        self.attachment_refs_truncated = 0
        self.skip_depth = 0
        self.anchor = ""
        self.current = None
        self.heading_parts = None
        self.section_index = 0
        self.line_offsets = [0]
        for match in re.finditer("\n", source_text):
            self.line_offsets.append(match.end())

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col if 0 < line <= len(self.line_offsets) else 0

    def handle_starttag(self, tag, attrs):
        if tag in {"head", "script", "style", "iframe", "template", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        values = dict(attrs)
        if tag == "a" and values.get("id"):
            self.anchor = values["id"][:120]
        if tag in {"h2", "h3", "h4"}:
            self._flush(self._offset())
            self.section_index += 1
            self.current = {"index": self.section_index, "start": self._offset(),
                            "anchor": self.anchor, "heading": "", "parts": [], "attachments": []}
            self.heading_parts = []
        if self.current:
            for attribute in ("href", "src", "data-src"):
                value = values.get(attribute)
                if value:
                    media = _attachment(self.page, self.root, value)
                    if media:
                        self.media[media["path"]] = media
                        if all(item["path"] != media["path"] for item in self.current["attachments"]):
                            self.current["attachments"].append(media)

    def handle_data(self, data):
        if self.skip_depth or not self.current:
            return
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        else:
            self.current["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in {"head", "script", "style", "iframe", "template", "svg"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in {"h2", "h3", "h4"} and self.heading_parts is not None and self.current:
            self.current["heading"] = " ".join(" ".join(self.heading_parts).split())[:240]
            self.heading_parts = None

    def close(self):
        super().close()
        self._flush(len(self.source_text))

    def _flush(self, end: int):
        section = self.current
        self.current = None
        if not section:
            return
        value = " ".join(" ".join(section["parts"]).split())
        if not value:
            return
        rel = self.page.relative_to(self.root).as_posix()
        heading = section["heading"] or "报告文本章节"
        nav = self.navigation.get((self.page.name, section["anchor"]), [])
        truncated = len(value) > MAX_RECORD_CHARS
        if truncated:
            self.truncated_rows += 1
        index = section["index"]
        if len(section["attachments"]) > MAX_ATTACHMENTS:
            self.attachment_refs_truncated += len(section["attachments"]) - MAX_ATTACHMENTS
        self.records.append({
            "id": hashlib.sha256(f"{rel}:section:{index}".encode()).hexdigest()[:32],
            "record_kind": "section_text", "specimen": self.specimen,
            "category": _section_category(nav, heading),
            "application": _application([*reversed(nav), heading]),
            "heading": heading, "section_title": heading, "table_title": None,
            "content": None, "raw_text": value[:MAX_RECORD_CHARS],
            "content_truncated": truncated, "fields": {}, "normalized": {},
            "occurred_at": None, "source_file": rel, "source_anchor": section["anchor"],
            "source_table": 0, "source_row": index,
            "source_locator": f"{rel}#section-{index}",
            "source_start_offset": section["start"], "source_end_offset": end,
            "attachments": section["attachments"][:MAX_ATTACHMENTS],
        })


def _report_pages(root: Path) -> tuple[list[tuple[Path, str]], list[dict], list[dict]]:
    if not (root / "index.html").is_file() or not (root / "report").is_dir():
        raise InvalidReport("expected index.html and report/ directory")
    pages = []
    skipped = []
    warnings = []
    total_bytes = 0
    scanned_files = scanned_dirs = 0
    for current, dirs, names in os.walk(root / "report", followlinks=False):
        scanned_dirs += 1
        if scanned_dirs > MAX_SCAN_DIRS:
            warnings.append(_warning("PAGE_SCAN_LIMIT", detail="directory limit"))
            break
        for directory in dirs:
            if (Path(current) / directory).is_symlink():
                warnings.append(_warning("SYMLINK_DIRECTORY_SKIPPED", (Path(current) / directory).relative_to(root).as_posix()))
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
        for name in sorted(names):
            scanned_files += 1
            if scanned_files > MAX_SCAN_FILES:
                warnings.append(_warning("PAGE_SCAN_LIMIT", detail="file limit"))
                break
            if not CONTENT_PAGE.fullmatch(name):
                continue
            candidate = Path(current) / name
            rel = candidate.relative_to(root).as_posix()
            if "assets" in candidate.relative_to(root).parts:
                continue
            try:
                path = _safe_source(root, candidate)
                size = path.stat().st_size
            except (InvalidReport, OSError):
                skipped.append({"path": rel, "reason": "UNSAFE_PAGE_PATH"})
                warnings.append(_warning("UNSAFE_PAGE_PATH", rel))
                continue
            if len(pages) >= MAX_PAGES or size > MAX_PAGE_BYTES or total_bytes + size > MAX_TOTAL_PAGE_BYTES:
                skipped.append({"path": rel, "reason": "PAGE_LIMIT"})
                warnings.append(_warning("PAGE_LIMIT", rel))
                continue
            specimen = path.parent.parent.parent.name if path.parent.name == "content" else "案件概览"
            pages.append((path, specimen))
            total_bytes += size
        if scanned_files > MAX_SCAN_FILES:
            break
    pages.sort(key=lambda item: (str(item[0].parent), int(item[0].stem[7:])))
    return pages, skipped, warnings


def _page_target(root: Path, base: Path, value: str) -> str | None:
    """Resolve one literal report-relative content path; no JS or URL loading."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        return None
    value = unquote(value).replace("\\", "/")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    parts = PurePosixPath(parsed.path).parts
    if not parts or value.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        return None
    target = (base / parsed.path).resolve(strict=False)
    if not target.is_relative_to(root) or not target.is_relative_to(root / "report") or not CONTENT_PAGE.fullmatch(target.name):
        return None
    return target.relative_to(root).as_posix()


def _page_js(root: Path) -> tuple[dict[str, int], bool, list[dict], str | None]:
    path = root / "report" / "page.js"
    if not path.exists():
        return {}, False, [_warning("PAGE_JS_MISSING", "report/page.js")], None
    raw_hash = None
    try:
        path = _safe_source(root, path)
        if path.stat().st_size > MAX_PAGE_JS_BYTES:
            raise ValueError("page.js exceeds size limit")
        with path.open("rb") as source:
            raw = source.read(MAX_PAGE_JS_BYTES + 1)
        if len(raw) > MAX_PAGE_JS_BYTES:
            raise ValueError("page.js exceeds size limit")
        raw_hash = hashlib.sha256(raw).hexdigest()
        value = raw.decode("utf-8-sig", errors="strict").strip()
        match = re.fullmatch(r"var\s+page\s*=\s*(\{.*\})\s*;?", value, flags=re.DOTALL)
        if not match:
            raise ValueError("unsupported static page.js assignment")
        payload = json.loads(match.group(1))
        entries = payload.get("page") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or len(entries) > MAX_PAGES:
            raise ValueError("unsupported page list")
        result = {}
        used_numbers = set()
        warnings = []
        for entry in entries:
            number = entry.get("currentPage") if isinstance(entry, dict) else None
            target = _page_target(root, root / "report", entry.get("contenthtml")) if isinstance(entry, dict) else None
            if type(number) is not int or number < 1 or number > MAX_PAGES or target is None or number in used_numbers or target in result:
                warnings.append(_warning("UNSUPPORTED_PAGE_MAPPING", detail="invalid/duplicate page number or confined content path"))
                continue
            used_numbers.add(number)
            result[target] = number
        if not result:
            raise ValueError("no valid page mappings")
        if used_numbers != set(range(1, max(used_numbers) + 1)):
            warnings.append(_warning("PAGE_NUMBER_GAP"))
        return result, True, warnings, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, InvalidReport) as exc:
        return {}, True, [_warning("UNSUPPORTED_PAGE_JS", "report/page.js", str(exc)[:120])], raw_hash


class _StaticLandingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames = []

    def handle_starttag(self, tag, attrs):
        if tag in {"frame", "iframe"}:
            value = dict(attrs).get("src")
            if value:
                self.frames.append(value)


def _landing_pages(root: Path) -> set[str]:
    """The sample's specimen index frames its own unnumbered content0 page."""
    result = set()
    candidates = [root / "index.html", *(root / "report").glob("*/index.html")]
    for candidate in candidates[:MAX_PAGES]:
        if not candidate.is_file():
            continue
        try:
            path = _safe_source(root, candidate)
            if path.stat().st_size > 1024 * 1024:
                continue
            parser = _StaticLandingParser()
            with path.open("rb") as source:
                raw = source.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                continue
            parser.feed(_decode_html(raw))
            for value in parser.frames:
                target = _page_target(root, path.parent, value)
                if target:
                    result.add(target)
        except (OSError, InvalidReport, ValueError):
            continue
    return result


def _metadata(root: Path) -> list[dict]:
    out = []
    for path in sorted((root / "report").glob("*/export.db")):
        path = _safe_source(root, path)
        if path.stat().st_size > MAX_EXPORT_DB_BYTES:
            raise InvalidReport("export.db exceeds supported size limit")
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "archiveInfo" not in tables:
                raise InvalidReport("unrecognized export.db schema")
            row = con.execute("SELECT softName, softVersion FROM archiveInfo LIMIT 1").fetchone()
            out.append({
                "specimen": path.parent.name,
                "software": row[0] if row else None,
                "version": row[1] if row else None,
                "metadata_file": path.relative_to(root).as_posix(),
                "metadata_sha256": _sha256(path),
            })
        except sqlite3.DatabaseError as exc:
            raise InvalidReport("invalid export.db") from exc
        finally:
            con.close()
    return out


def _navigation(content_dir: Path, root: Path) -> tuple[dict[tuple[str, str], list[str]], str | None]:
    """Read the export's JSON navigation *as data*, without executing data.js."""
    path = content_dir / "data.js"
    if not path.is_file():
        return {}, "DATA_JS_MISSING"
    try:
        path = _safe_source(root, path)
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}, "DATA_JS_LIMIT"
        with path.open("rb") as source:
            raw_bytes = source.read(2 * 1024 * 1024 + 1)
        if len(raw_bytes) > 2 * 1024 * 1024:
            return {}, "DATA_JS_LIMIT"
        raw = raw_bytes.decode("utf-8-sig", errors="strict").strip()
    except (OSError, UnicodeError, InvalidReport):
        return {}, "DATA_JS_INVALID"
    match = re.fullmatch(r"var\s+data\s*=\s*(\{.*\})\s*;?", raw, flags=re.DOTALL)
    if not match:
        return {}, "DATA_JS_UNSUPPORTED"
    try:
        nodes = json.loads(match.group(1)).get("list", [])
    except (json.JSONDecodeError, AttributeError):
        return {}, "DATA_JS_UNSUPPORTED"
    if not isinstance(nodes, list) or len(nodes) > 100_000:
        return {}, "DATA_JS_UNSUPPORTED"
    by_id = {str(node.get("a")): node for node in nodes if isinstance(node, dict)}
    result = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        target = str(node.get("f") or "")
        page, separator, anchor = target.partition("#")
        if not separator or not CONTENT_PAGE.fullmatch(page) or not anchor:
            continue
        labels = []
        seen = set()
        current = node
        while current and str(current.get("a")) not in seen and len(labels) < 20:
            seen.add(str(current.get("a")))
            labels.append(str(current.get("c") or "")[:240])
            current = by_id.get(str(current.get("b")))
        result[(page, anchor)] = list(reversed([value for value in labels if value]))
    return result, None


_SCHEMA = """
CREATE TABLE report_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE pages (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
  page_number INTEGER, table_count INTEGER NOT NULL, row_count INTEGER NOT NULL);
CREATE TABLE records (
  id TEXT PRIMARY KEY, record_id TEXT NOT NULL UNIQUE, import_id TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK(source_type='external_html_report'),
  source_vendor TEXT, record_kind TEXT NOT NULL, specimen TEXT NOT NULL,
  category TEXT NOT NULL, application TEXT,
  section_title TEXT, table_title TEXT, heading TEXT NOT NULL,
  timestamp TEXT, occurred_at TEXT, sender TEXT, receiver TEXT, account TEXT,
  content TEXT, file_path TEXT, raw_fields_json TEXT NOT NULL, fields_json TEXT NOT NULL,
  raw_text TEXT NOT NULL, content_truncated INTEGER NOT NULL,
  source_file TEXT NOT NULL, source_page INTEGER,
  source_table_index INTEGER NOT NULL, source_row_index INTEGER NOT NULL,
  source_table INTEGER NOT NULL, source_row INTEGER NOT NULL,
  source_anchor TEXT NOT NULL, source_locator TEXT NOT NULL UNIQUE,
  source_hash TEXT NOT NULL, source_start_offset INTEGER NOT NULL,
  source_end_offset INTEGER NOT NULL, attachments_json TEXT NOT NULL,
  FOREIGN KEY(source_file) REFERENCES pages(path)
);
CREATE INDEX records_category ON records(category);
CREATE INDEX records_date ON records(occurred_at);
CREATE INDEX records_source ON records(source_file, source_table, source_row);
CREATE INDEX records_application ON records(application);
"""


def create_import(source_path: str) -> dict:
    """Index only derived report rows; never mutate the selected export."""
    source = Path(source_path).expanduser()
    if not source.is_absolute():
        source = get_project_root() / source
    root = source.resolve(strict=True)
    if not root.is_dir() or not (root / "report").is_dir():
        raise InvalidReport("report path must contain a report/ directory")
    index = _safe_source(root, root / "index.html")
    if index.stat().st_size > MAX_INDEX_BYTES:
        raise InvalidReport("index.html exceeds supported size limit")
    import_id = uuid.uuid4().hex
    destination = _import_dir(import_id)
    destination.mkdir(parents=True, exist_ok=False)
    db = destination / "records.db"
    con = sqlite3.connect(db)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(_SCHEMA)
        warnings: list[dict] = []
        skipped_pages: list[dict] = []
        failed_pages: list[dict] = []
        pages, skipped_pages, page_warnings = _report_pages(root)
        warnings.extend(page_warnings)
        try:
            metadata = _metadata(root)
        except (InvalidReport, OSError, sqlite3.Error) as exc:
            metadata = []
            warnings.append(_warning("EXPORT_DB_INVALID", detail=str(exc)[:120]))
        if not metadata:
            warnings.append(_warning("EXPORT_DB_MISSING"))
        mapped_pages, page_js_present, js_warnings, page_js_hash = _page_js(root)
        warnings.extend(js_warnings)
        landing_pages = _landing_pages(root)
        found_paths = {page.relative_to(root).as_posix() for page, _ in pages}
        found_paths.update(item["path"] for item in skipped_pages)
        for path in sorted(set(mapped_pages) - found_paths):
            warnings.append(_warning("MISSING_PAGE", path))
            failed_pages.append({"path": path, "reason": "MISSING_PAGE"})
        for path in sorted(found_paths - set(mapped_pages) - landing_pages):
            warnings.append(_warning("UNDECLARED_PAGE", path))
        if not pages:
            warnings.append(_warning("NO_CONTENT_PAGES"))
        source_entries = [{"path": "index.html", "sha256": _sha256(index)}]
        source_entries.extend({"path": item["metadata_file"], "sha256": item["metadata_sha256"]} for item in metadata)
        landing_index_files = []
        for candidate in sorted((root / "report").glob("*/index.html")):
            relative = candidate.relative_to(root).as_posix()
            landing_index_files.append(relative)
            try:
                nested_index = _safe_source(root, candidate)
                if nested_index.stat().st_size > MAX_INDEX_BYTES:
                    raise InvalidReport("nested index.html exceeds supported size limit")
                source_entries.append({"path": relative, "sha256": _sha256(nested_index)})
            except (InvalidReport, OSError):
                warnings.append(_warning("UNSAFE_LANDING_INDEX", relative))
        if page_js_hash:
            source_entries.append({"path": "report/page.js", "sha256": page_js_hash})
        meta = {
            "import_id": import_id,
            "source_path": str(root),
            "source_type": SOURCE_TYPE,
            "parser_version": PARSER_VERSION,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "specimens": metadata,
            "page_count": len(pages),
            "task_ids": [],
        }
        total_records = 0
        missing_attachments = set()
        all_attachment_refs = set()
        navigation_cache = {}
        section_cache = {}
        attachment_cache = {}
        hashed_attachment_bytes = 0
        total_tables = total_rows = truncated_rows = unknown_fields = unsupported_parsed_pages = attachment_refs_truncated = 0
        parsed_pages = []
        data_js_paths = set()
        vendor_by_specimen = {item["specimen"]: item.get("software") for item in metadata}
        actual_page_bytes = 0
        if metadata:
            for page, specimen in pages:
                rel = page.relative_to(root).as_posix()
                con.execute("SAVEPOINT report_page")
                try:
                    page = _safe_source(root, page)
                    with page.open("rb") as source:
                        raw = source.read(MAX_PAGE_BYTES + 1)
                    if len(raw) > MAX_PAGE_BYTES:
                        raise InvalidReport("page grew beyond supported size limit")
                    if actual_page_bytes + len(raw) > MAX_TOTAL_PAGE_BYTES:
                        raise InvalidReport("total page bytes grew beyond supported limit")
                    page_hash = hashlib.sha256(raw).hexdigest()
                    if page.parent.name == "content" and page.parent not in navigation_cache:
                        nav, code = _navigation(page.parent, root)
                        navigation_cache[page.parent] = nav
                        data_path = page.parent / "data.js"
                        if data_path.is_file():
                            try:
                                data_file = _safe_source(root, data_path)
                                if data_file.stat().st_size <= 2 * 1024 * 1024:
                                    source_entries.append({"path": data_path.relative_to(root).as_posix(),
                                                           "sha256": _sha256(data_file)})
                            except (InvalidReport, OSError):
                                pass  # DATA_JS_INVALID already records the bounded parse failure.
                        if code:
                            warnings.append(_warning(code, data_path.relative_to(root).as_posix()))
                        else:
                            data_js_paths.add(data_path.relative_to(root).as_posix())
                    parser = _ReportPageParser(
                        page, root, specimen, navigation_cache.get(page.parent, {}),
                        section_cache.get(page.parent),
                    )
                    header = raw[:4096].decode("ascii", errors="ignore")
                    charset_match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", header, re.IGNORECASE)
                    encoding = charset_match.group(1).lower() if charset_match else "utf-8"
                    if encoding not in _ALLOWED_HTML_ENCODINGS:
                        encoding = "utf-8"
                    try:
                        raw.decode(encoding, errors="strict")
                    except UnicodeDecodeError:
                        warnings.append(_warning("MALFORMED_ENCODING", rel))
                    decoded = _decode_html(raw)
                    parser.set_source_text(decoded)
                    parser.feed(decoded)
                    parser.close()
                    if parser.total_tables == 0:
                        sections = _ReportSectionParser(
                            page, root, specimen, navigation_cache.get(page.parent, {}), decoded,
                        )
                        sections.feed(decoded)
                        sections.close()
                        parser.records.extend(sections.records)
                        parser.media.update(sections.media)
                        parser.truncated_rows += sections.truncated_rows
                        parser.attachment_refs_truncated += sections.attachment_refs_truncated
                    con.execute("INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?)",
                                (rel, page_hash, len(raw), mapped_pages.get(rel), parser.total_tables, parser.total_rows))
                    for record in parser.records:
                        for attachment in record["attachments"]:
                            media_path = attachment["path"]
                            if media_path not in attachment_cache:
                                try:
                                    media = _safe_source(root, root / media_path) if (root / media_path).exists() else None
                                except (InvalidReport, OSError):
                                    media = None
                                if media:
                                    size = media.stat().st_size
                                    should_hash = size <= MAX_ATTACHMENT_HASH_BYTES and hashed_attachment_bytes + size <= MAX_TOTAL_ATTACHMENT_HASH_BYTES
                                    attachment_cache[media_path] = {"available": True, "size": size, "sha256": _sha256(media) if should_hash else None}
                                    if should_hash:
                                        hashed_attachment_bytes += size
                                else:
                                    attachment_cache[media_path] = {"available": False, "size": None, "sha256": None}
                            attachment.update(attachment_cache[media_path])
                        norm = record["normalized"]
                        values = {
                            "id": record["id"], "record_id": record["id"], "import_id": import_id,
                            "source_type": SOURCE_TYPE, "source_vendor": vendor_by_specimen.get(specimen) or (metadata[0].get("software") if metadata else None),
                            "record_kind": record["record_kind"],
                            "specimen": record["specimen"], "category": record["category"], "application": record["application"],
                            "section_title": record["section_title"], "table_title": record["table_title"], "heading": record["heading"],
                            "timestamp": norm.get("timestamp"), "occurred_at": record["occurred_at"],
                            "sender": norm.get("sender"), "receiver": norm.get("receiver"), "account": norm.get("account"),
                            "content": record["content"], "file_path": norm.get("file_path"),
                            "raw_fields_json": json.dumps(record["fields"], ensure_ascii=False),
                            "fields_json": json.dumps(record["fields"], ensure_ascii=False), "raw_text": record["raw_text"],
                            "content_truncated": int(record["content_truncated"]), "source_file": rel,
                            "source_page": mapped_pages.get(rel), "source_table_index": record["source_table"],
                            "source_row_index": record["source_row"], "source_table": record["source_table"],
                            "source_row": record["source_row"], "source_anchor": record["source_anchor"],
                            "source_locator": record["source_locator"], "source_hash": page_hash,
                            "source_start_offset": record["source_start_offset"], "source_end_offset": record["source_end_offset"],
                            "attachments_json": json.dumps(record["attachments"], ensure_ascii=False),
                        }
                        columns = list(values)
                        con.execute(f"INSERT INTO records ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                    [values[key] for key in columns])
                    con.execute("RELEASE SAVEPOINT report_page")
                    if parser.total_tables == 0 and not parser.records:
                        warnings.append(_warning("UNSUPPORTED_PAGE_STRUCTURE", rel, "no supported table"))
                        unsupported_parsed_pages += 1
                    section_cache[page.parent] = (parser.section_path, parser.heading, "")
                    source_entries.append({"path": rel, "sha256": page_hash})
                    parsed_pages.append(rel)
                    actual_page_bytes += len(raw)
                    total_tables += parser.total_tables
                    total_rows += parser.total_rows
                    total_records += len(parser.records)
                    truncated_rows += parser.truncated_rows
                    unknown_fields += parser.unknown_fields
                    attachment_refs_truncated += parser.attachment_refs_truncated
                    missing_attachments.update(path for path, media in parser.media.items() if not media["available"])
                    all_attachment_refs.update(parser.media)
                    all_attachment_refs.update(a["path"] for record in parser.records for a in record["attachments"])
                    missing_attachments.update(a["path"] for record in parser.records for a in record["attachments"] if not a["available"])
                except (OSError, UnicodeError, ValueError, InvalidReport, sqlite3.Error) as exc:
                    con.execute("ROLLBACK TO SAVEPOINT report_page")
                    con.execute("RELEASE SAVEPOINT report_page")
                    failed_pages.append({"path": rel, "reason": "PAGE_PARSE_FAILED"})
                    warnings.append(_warning("PAGE_PARSE_FAILED", rel, str(exc)[:120]))
                    # A failed page must not lend navigation context to its successor.
                    section_cache.pop(page.parent, None)
        # Include references outside tables (e.g. an image in a text-only page)
        # in the bounded attachment integrity inventory, not only in warnings.
        for media_path in sorted(all_attachment_refs):
            if media_path in attachment_cache:
                continue
            try:
                media = _safe_source(root, root / media_path)
                size = media.stat().st_size
                should_hash = size <= MAX_ATTACHMENT_HASH_BYTES and hashed_attachment_bytes + size <= MAX_TOTAL_ATTACHMENT_HASH_BYTES
                attachment_cache[media_path] = {
                    "available": True, "size": size,
                    "sha256": _sha256(media) if should_hash else None,
                }
                if should_hash:
                    hashed_attachment_bytes += size
            except (FileNotFoundError, InvalidReport, OSError):
                attachment_cache[media_path] = {"available": False, "size": None, "sha256": None}
                missing_attachments.add(media_path)
        source_entries.extend({"path": path, "sha256": item["sha256"]}
                              for path, item in attachment_cache.items() if item["available"] and item["sha256"])
        for path in sorted(missing_attachments):
            warnings.append(_warning("MISSING_ATTACHMENT", path))
        if len(all_attachment_refs) > 10000:
            warnings.append(_warning("ATTACHMENT_LIST_TRUNCATED", detail=str(len(all_attachment_refs))))
        if attachment_refs_truncated:
            warnings.append(_warning("ATTACHMENT_REF_LIMIT", detail=str(attachment_refs_truncated)))
        if truncated_rows:
            warnings.append(_warning("TRUNCATED_ROW", detail=str(truncated_rows)))
        for item in attachment_cache.values():
            if item["available"] and not item["sha256"]:
                warnings.append(_warning("UNHASHED_ATTACHMENT"))
                break
        source_entries.sort(key=lambda item: item["path"])
        source_sha256 = hashlib.sha256(json.dumps(source_entries, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        status = "FAILED" if total_records == 0 else "PARTIAL" if warnings else "COMPLETE"
        manifest = {
            "import_id": import_id, "source_root": str(root), "source_sha256": source_sha256,
            "hash_scope": "SHA-256 of sorted indexed source path/hash pairs; not a whole-directory or original-device hash",
            "index_html_exists": True,
            "export_db_exists": any((root / "report").glob("*/export.db")),
            "export_db_valid": bool(metadata),
            "data_js_exists": any(page.parent.name == "content" and (page.parent / "data.js").is_file() for page, _ in pages),
            "data_js_files": sorted({(page.parent / "data.js").relative_to(root).as_posix()
                                     for page, _ in pages if page.parent.name == "content" and (page.parent / "data.js").is_file()}),
            "parsed_data_js": sorted(data_js_paths), "page_js_exists": page_js_present,
            "declared_page_count": len(mapped_pages) + len(landing_pages - set(mapped_pages)),
            "page_js_declared_page_count": len(mapped_pages),
            "landing_pages": sorted(landing_pages - set(mapped_pages)),
            "landing_index_files": landing_index_files,
            "export_files": sorted(path.relative_to(root).as_posix() for path in (root / "report").glob("*/export.db")),
            "page_mapping": [{"page": number, "source_file": path} for path, number in sorted(mapped_pages.items(), key=lambda item: item[1])],
            "discovered_content_pages": sorted(found_paths), "parsed_content_pages": parsed_pages,
            "skipped_pages": skipped_pages, "failed_pages": failed_pages,
            "total_tables": total_tables, "total_rows": total_rows,
            "attachment_refs": sorted(all_attachment_refs)[:10000], "attachment_ref_count": len(all_attachment_refs),
            "source_files": source_entries,
            "warnings": warnings, "parser_version": PARSER_VERSION, "status": status,
        }
        category_counts = dict(con.execute("SELECT category, COUNT(*) FROM records GROUP BY category").fetchall())
        application_counts = dict(con.execute("SELECT COALESCE(application, 'UNKNOWN'), COUNT(*) FROM records GROUP BY COALESCE(application, 'UNKNOWN')").fetchall())
        source_counts = dict(con.execute("SELECT source_file, COUNT(*) FROM records GROUP BY source_file").fetchall())
        coverage = {
            "import_id": import_id, "status": status,
            "total_pages": len(found_paths), "declared_pages": manifest["declared_page_count"],
            "successful_pages": len(parsed_pages), "failed_pages": len(failed_pages),
            "tables": total_tables, "total_records": total_records,
            "category_counts": category_counts, "application_counts": application_counts,
            "source_file_counts": source_counts, "unknown_fields": unknown_fields,
            "truncated_rows": truncated_rows, "unsupported_pages": len(skipped_pages) + unsupported_parsed_pages,
            "attachment_refs_truncated": attachment_refs_truncated,
            "missing_attachments": len(missing_attachments), "warning_count": len(warnings),
        }
        meta.update(
            record_count=total_records,
            missing_attachment_count=len(missing_attachments),
            missing_attachment_paths=sorted(missing_attachments)[:100],
            unhashed_attachment_count=sum(
                item["available"] and not item["sha256"] for item in attachment_cache.values()
            ),
            status=status, warning_count=len(warnings), declared_page_count=manifest["declared_page_count"],
            source_sha256=source_sha256,
        )
        for key, value in meta.items():
            con.execute("INSERT INTO report_meta VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))
        (destination / "report_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "report_import_coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
        con.commit()
        return meta
    except Exception:
        con.close()
        # The destination contains only a newly created index, never source evidence.
        db.unlink(missing_ok=True)
        (destination / "report_manifest.json").unlink(missing_ok=True)
        (destination / "report_import_coverage.json").unlink(missing_ok=True)
        destination.rmdir()
        raise
    finally:
        con.close()


def _meta(con: sqlite3.Connection) -> dict:
    return {row["key"]: json.loads(row["value"]) for row in con.execute("SELECT key, value FROM report_meta")}


def list_imports(task_id: str | None = None) -> list[dict]:
    root = import_root()
    if not root.is_dir():
        return []
    imports = []
    for path in root.iterdir():
        if not path.is_dir() or not IMPORT_ID.fullmatch(path.name):
            continue
        try:
            with closing(_connect(path.name)) as con:
                meta = _meta(con)
                if task_id is None or task_id in meta.get("task_ids", []):
                    imports.append(meta)
        except (sqlite3.DatabaseError, FileNotFoundError):
            continue
    return sorted(imports, key=lambda item: item.get("imported_at", ""), reverse=True)


def set_task_link(import_id: str, task_id: str, *, linked: bool) -> dict:
    """Persist an explicit administrative association, never an evidence claim."""
    if not isinstance(task_id, str) or not task_id or len(task_id) > 128 or "/" in task_id:
        raise ValueError("invalid task ID")
    con = sqlite3.connect(_db_path(import_id), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT value FROM report_meta WHERE key='task_ids'").fetchone()
        task_ids = set(json.loads(row["value"])) if row else set()
        if linked:
            task_ids.add(task_id)
        else:
            task_ids.discard(task_id)
        con.execute(
            "INSERT INTO report_meta(key,value) VALUES ('task_ids',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(sorted(task_ids)),),
        )
        con.commit()
        return _meta(con)
    finally:
        con.close()


def overview(import_id: str) -> dict:
    with closing(_connect(import_id)) as con:
        meta = _meta(con)
        categories = [dict(row) for row in con.execute(
            "SELECT category, COUNT(*) AS count FROM records GROUP BY category ORDER BY count DESC"
        )]
        days = [dict(row) for row in con.execute(
            "SELECT SUBSTR(occurred_at,1,10) AS day, COUNT(*) AS count FROM records "
            "WHERE occurred_at IS NOT NULL GROUP BY day ORDER BY day LIMIT 1000"
        )]
        try:
            coverage = read_coverage(import_id)
            warnings = read_manifest(import_id).get("warnings", [])
        except FileNotFoundError:
            coverage = None  # Older indexes are unverified, never silently COMPLETE.
            warnings = []
        return {"import": meta, "categories": categories, "days": days,
                "coverage": coverage, "warnings": warnings}


def read_manifest(import_id: str) -> dict:
    return json.loads((_import_dir(import_id) / "report_manifest.json").read_text(encoding="utf-8"))


def read_coverage(import_id: str) -> dict:
    return json.loads((_import_dir(import_id) / "report_import_coverage.json").read_text(encoding="utf-8"))


def records(import_id: str, *, query: str = "", category: str = "", page: int = 1, page_size: int = 50) -> dict:
    with closing(_connect(import_id)) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(records)")}
        search_column = "raw_text" if "raw_text" in columns else "content"
        kind_column = "record_kind" if "record_kind" in columns else "'table_row' AS record_kind"
        clauses = []
        args: list = []
        if category:
            clauses.append("category = ?")
            args.append(category)
        if query:
            clauses.append(f"({search_column} LIKE ? ESCAPE '\\' OR heading LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.extend([f"%{escaped}%", f"%{escaped}%"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = con.execute("SELECT COUNT(*) FROM records" + where, args).fetchone()[0]
        rows = con.execute(
            f"SELECT id, specimen, category, heading, {kind_column}, SUBSTR({search_column},1,500) AS excerpt, "
            "occurred_at, source_file, source_anchor, source_table, source_row "
            "FROM records" + where + " ORDER BY rowid LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size],
        ).fetchall()
        return {"total": total, "page": page, "page_size": page_size, "records": [dict(row) for row in rows]}


def record_detail(import_id: str, record_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", record_id):
        raise ValueError("invalid record ID")
    with closing(_connect(import_id)) as con:
        row = con.execute("SELECT r.*, p.sha256 AS source_sha256 FROM records r "
                          "JOIN pages p ON p.path = r.source_file WHERE r.id = ?", (record_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("report record not found")
        item = dict(row)
        item["fields"] = json.loads(item.pop("fields_json"))
        item["raw_fields"] = json.loads(item["raw_fields_json"]) if "raw_fields_json" in item else item["fields"]
        if "raw_text" not in item:
            item["raw_text"] = item["content"]
        item["attachments"] = json.loads(item.pop("attachments_json"))
        item["content_truncated"] = bool(item["content_truncated"])
        meta = _meta(con)
        try:
            root = _verified_import_root(meta)
        except (FileNotFoundError, InvalidReport):
            item["source_matches_import"] = False
            return item
        try:
            source = _safe_source(root, root / item["source_file"])
            item["source_matches_import"] = _sha256(source) == item["source_sha256"]
        except (FileNotFoundError, InvalidReport):
            item["source_matches_import"] = False
        return item


def source_location_html(import_id: str, record_id: str) -> str:
    """Inert, escaped excerpt of the *unchanged* source HTML around one row."""
    item = record_detail(import_id, record_id)
    if "source_start_offset" not in item or "source_end_offset" not in item:
        raise InvalidReport("legacy index has no verified row offsets; re-import this report")
    if not item["source_matches_import"]:
        raise InvalidReport("source page changed after import")
    source = source_page_file(import_id, item["source_file"])
    value = _decode_html(source.read_bytes())
    start, end = item["source_start_offset"], item["source_end_offset"]
    if not (0 <= start < end <= len(value)):
        raise InvalidReport("indexed row offsets do not match the source page")
    prefix = html.escape(value[max(0, start - 500):start])
    target = html.escape(value[start:min(end, start + 50000)])
    suffix = html.escape(value[end:min(len(value), end + 500)])
    locator = html.escape(item["source_locator"])
    return ("<!doctype html><html lang='zh'><meta charset='utf-8'><title>原始报告位置</title>"
            "<style>body{font:16px/1.6 sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fb;padding:1rem}"
            "mark{background:#fff0a6;display:inline}</style>"
            "<h1>原始报告位置（仅转义文本，不执行报告代码）</h1>"
            f"<p>来源：<code>{locator}</code></p><pre>{prefix}<mark id='source-row'>{target}</mark>{suffix}</pre></html>")


def source_page_file(import_id: str, relative_path: str) -> Path:
    """Return an indexed, unchanged HTML page to download as inert text."""
    with closing(_connect(import_id)) as con:
        relative = Path(relative_path)
        if relative.is_absolute() or re.match(r"^[A-Za-z]:", relative_path) or ".." in relative.parts or not relative.parts or "\\" in relative_path:
            raise ValueError("invalid source page path")
        row = con.execute("SELECT sha256 FROM pages WHERE path = ?", (relative_path,)).fetchone()
        if row is None:
            raise ValueError("page was not indexed")
        root = _verified_import_root(_meta(con))
        try:
            page = _safe_source(root, root / relative_path)
        except FileNotFoundError as exc:
            raise FileNotFoundError("report page is missing") from exc
        if _sha256(page) != row["sha256"]:
            raise InvalidReport("report page changed after import")
        return page


def attachment_file(import_id: str, relative_path: str) -> Path:
    """Only serve files that were referenced by an indexed report record."""
    with closing(_connect(import_id)) as con:
        meta = _meta(con)
        root = _verified_import_root(meta)
        relative_path = unquote(relative_path).replace("\\", "/")
        relative = Path(relative_path)
        if relative.is_absolute() or re.match(r"^[A-Za-z]:", relative_path) or ".." in relative.parts or not relative.parts:
            raise ValueError("invalid attachment path")
        target = (root / relative).resolve(strict=False)
        if not target.is_relative_to(root):
            raise ValueError("invalid attachment path")
        if not target.is_file():
            raise FileNotFoundError("attachment is missing from the report")
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mp3", ".wav", ".pdf", ".xls", ".xlsx", ".doc", ".docx"}:
            raise ValueError("unsupported attachment type")
        # JSON string match is safe here because the path came from an exact,
        # canonicalised report-relative reference during import.
        indexed = None
        for row in con.execute("SELECT attachments_json FROM records WHERE attachments_json LIKE ?", (f"%{target.name}%",)):
            indexed = next((a for a in json.loads(row[0]) if a["path"] == relative_path), None)
            if indexed:
                break
        if not indexed:
            raise ValueError("attachment was not indexed")
        if not indexed.get("available"):
            raise InvalidReport("attachment was missing at import time")
        if indexed.get("sha256") and _sha256(target) != indexed["sha256"]:
            raise InvalidReport("attachment changed after import")
        return target
