"""Bounded, case-independent reading of task-registered files."""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from ..forensic_report.generation_sources import (
    _file_bytes, _transcript, TEXT_EXTENSIONS, DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, MEDIA_EXTENSIONS,
)
from .models import MAX_TEXT, digest, stable_id


def catalog(task, limit):
    value = task.get("output_files_db")
    if not value or not Path(value).is_file():
        raise ValueError("任务尚无可读取的文件目录")
    with closing(sqlite3.connect(f"file:{quote(str(Path(value).resolve()), safe='/')}?mode=ro",
                                uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        columns = {r[1] for r in db.execute("PRAGMA table_info(files)")}
        if "path" not in columns:
            raise ValueError("任务文件目录结构不可用")
        size = "MIN(size)" if "size" in columns else "NULL"
        md5 = "MIN(md5)" if "md5" in columns else "NULL"
        total = db.execute("SELECT COUNT(DISTINCT path) FROM files WHERE path IS NOT NULL AND path!=''").fetchone()[0]
        rows = [dict(row) for row in db.execute(
            f"SELECT path,{size} AS size,{md5} AS md5,COUNT(*) AS copies FROM files "
            "WHERE path IS NOT NULL AND path!='' GROUP BY path ORDER BY path LIMIT ?", (limit,))]
    return rows, total, digest([rows, total])


def file_stamp(path):
    file = Path(path)
    if not file.is_file() or file.is_symlink():
        return None
    s = file.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]


def source_changes(task, result):
    try:
        _, _, revision = catalog(task, result["coverage"]["file_limit"])
    except (ValueError, sqlite3.Error, OSError):
        return True
    if revision != result["catalog_revision"]:
        return True
    return any(m.get("_path") and file_stamp(m["_path"]) != m.get("_stamp") for m in result["materials"])


async def read_materials(task, limit, llm, progress):
    rows, total, revision = await asyncio.to_thread(catalog, task, limit)
    materials, models, remaining, images = [], set(), MAX_TEXT, 0
    for index, row in enumerate(rows):
        material = {"id": stable_id("mat", task["id"], row["path"]), "evidence_key": f"file:{row['path']}",
                    "path": row["path"], "text": "", "source_hash": "", "text_hash": "",
                    "kind": "unavailable", "status": "unavailable", "limitations": [],
                    "original_characters": 0, "processed_characters": 0}
        try:
            if remaining <= 0:
                raise ValueError("TOTAL_TEXT_BUDGET")
            if row["copies"] != 1:
                raise ValueError("AMBIGUOUS_REGISTERED_PATH")
            item = SimpleNamespace(snapshot=SimpleNamespace(payload=SimpleNamespace(
                normalized_path=row["path"], md5=row["md5"], size=row["size"])))
            source, raw, md5, notes = await asyncio.to_thread(_file_bytes, task, item)
            material.update(source_hash=hashlib.sha256(raw).hexdigest(), _path=str(source), _stamp=file_stamp(source))
            ext, kind, text = source.suffix.lower(), "text", ""
            partial = False
            if ext in TEXT_EXTENSIONS or not ext:
                if b"\x00" in raw[:8192] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                    raise ValueError("UNREADABLE_BINARY")
                try:
                    text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
                except UnicodeError:
                    text = raw.decode("gb18030")
                    notes.append("INFERRED_TEXT_ENCODING")
            elif ext in DOCUMENT_EXTENSIONS:
                from ..document_extractor import get_document_extractor_locator
                if ext in (".db", ".sqlite", ".sqlite3"):
                    from ..extractors.relational_db import SQLiteExtractor
                    parser = SQLiteExtractor()
                    partial = True
                    notes.extend(("DATABASE_FIRST_50_ROWS_ONLY", "COMPANION_WAL_NOT_READ"))
                else:
                    parser = get_document_extractor_locator().get_extractor(str(source))
                if parser is None:
                    raise ValueError("PARSER_UNAVAILABLE")
                with tempfile.TemporaryDirectory(prefix="tracelens-people-") as directory:
                    copy = Path(directory) / ("material" + ext)
                    copy.write_bytes(raw)
                    text, _ = await parser.extract_to_markdown_detailed(str(copy))
                kind = "parsed_text"
                # Parsers expose a projection, not a full original-page coverage proof.
                partial = True
                notes.append("PARSED_PROJECTION_COVERAGE_UNVERIFIED")
            elif ext in MEDIA_EXTENSIONS:
                transcript = await asyncio.to_thread(_transcript, task, material["evidence_key"], md5)
                if not transcript or not transcript.get("full_text"):
                    raise ValueError("TRANSCRIPT_UNAVAILABLE")
                text, kind, partial = transcript["full_text"], "machine_transcript", True
                notes.append("MACHINE_TRANSCRIPT_UNVERIFIED")
            elif ext in IMAGE_EXTENSIONS:
                if len(raw) > 2 * 1024 * 1024 or images >= 5:
                    raise ValueError("IMAGE_READING_BUDGET")
                images += 1
                response = await llm.analyze_image(image_data=raw, prompt=(
                    "只转写图片中可以看清的文字，保留人名与上下文。看不清写[不清晰]。"
                    "不要识别人脸、推测人物身份或添加案情解释。最多1500字。"))
                if response.get("success") is False:
                    raise ValueError("IMAGE_TEXT_UNAVAILABLE")
                text = (response.get("analysis") or {}).get("description") or ""
                kind, partial = "machine_visual_text", True
                models.add(response.get("model") or "vision-model-unrecorded")
                notes.append("MACHINE_VISUAL_TEXT_UNVERIFIED")
            else:
                raise ValueError("UNSUPPORTED_FORMAT")
            if not text.strip() or text.strip().startswith(("[No content extracted", "Error:")):
                raise ValueError("NO_READABLE_TEXT")
            captured = text[:min(100_000, remaining)]
            if len(captured) < len(text):
                partial = True
                notes.append("TEXT_TRUNCATED")
            if file_stamp(source) != material["_stamp"]:
                raise ValueError("SOURCE_CHANGED_DURING_READ")
            material.update(text=captured, text_hash=digest(captured), kind=kind,
                            status="partial" if partial else "complete", limitations=notes,
                            original_characters=len(text))
            remaining -= len(captured)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = str(error)
            material["limitations"] = [code if code.isupper() and len(code) < 100 else "SOURCE_READ_FAILED"]
        materials.append(material)
        await progress("reading_materials", 5 + int(25 * (index + 1) / max(1, len(rows))))
    _, _, after = await asyncio.to_thread(catalog, task, limit)
    if revision != after:
        raise ValueError("文件目录在读取期间变化，请重新分析")
    return materials, {
        "registered_files": total, "selected_files": len(rows), "file_limit": limit,
        "unprocessed_files": max(0, total - len(rows)), "text_budget": MAX_TEXT,
        "scope": "当前任务登记文件；不按案情关联度或入报状态筛除",
    }, revision, sorted(models)
