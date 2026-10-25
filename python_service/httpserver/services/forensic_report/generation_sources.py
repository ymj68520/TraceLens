"""Freeze context-free source projections for the existing report admission.

No AI summaries, graph results, file-analysis cache, writes to evidence DBs,
or host-path fallback. Phase B reuses phase A's frozen bytes/records.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .models import NeutralMaterial, EnvelopeEvidenceItemV3

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_TOTAL = 8 * 1024 * 1024
MAX_TEXT_TOTAL = 2_000_000
TEXT_LIMIT = 4000
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".log",
                   ".md", ".ini", ".cfg", ".yaml", ".yml", ".sql", ".py", ".js", ".sh", ".ps1"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf", ".odt",
                       ".db", ".sqlite", ".sqlite3", ".eml", ".msg", ".lnk", ".evtx", ".reg",
                       # Forensic artifacts with a dedicated extractor. This set
                       # gates the neutral freeze: an extension outside every set
                       # raises NEUTRAL_FORMAT_NOT_SUPPORTED and the material is
                       # frozen as unavailable. Prefetch was missing here, so all
                       # 26 .pf files in a PC.E01 report carried zero characters
                       # even though PrefetchExtractor parses them fine.
                       ".pf", ".hve", ".edb", ".pfx",
                       ".automaticdestinations-ms", ".customdestinations-ms",
                       ".journal", ".wtmp", ".btmp", ".ab", ".pcap", ".pcapng",
                       ".psd", ".ai", ".heic", ".heif", ".dmp", ".raw", ".mem", ".lime"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MEDIA_EXTENSIONS = {".mp3", ".wav", ".m4a", ".amr", ".ogg", ".flac", ".mp4", ".avi", ".mkv", ".mov"}
DERIVED_FIELDS = ("initial_summary", "initial_description", "initial_keywords", "initial_model",
                  "initial_analyzed_at", "scene_type", "scene_priority", "scene_relevant")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def sanitize_items(items):
    """Strip context-derived fields without changing stored evidence snapshots."""
    result = []
    for item in items:
        value = item.model_dump(mode="json")
        value["bound_analysis"] = None
        payload = value["snapshot"]["payload"]
        for key in DERIVED_FIELDS:
            if key in payload:
                payload[key] = None
        result.append(EnvelopeEvidenceItemV3.model_validate(value))
    return tuple(result)


def material(identity, key, *, kind="unavailable", text="", source_hash="", media="",
             status="unavailable", limitations=()):
    excerpt = text[:TEXT_LIMIT]
    notes = list(limitations)
    if len(text) > len(excerpt):
        notes.append("FIRST_4000_PARSED_CHARACTERS_ONLY")
        status = "partial"
    return NeutralMaterial(
        material_id=identity, evidence_key=key, kind=kind, text=excerpt,
        media_base64=media, source_sha256=source_hash,
        content_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        original_characters=len(text), status=status, limitations=tuple(notes),
    )


def _connect(path):
    return sqlite3.connect(f"file:{quote(str(Path(path).resolve()), safe='/')}?mode=ro", uri=True)


def _file_bytes(task, item):
    """Resolve a unique same-task DB row and a confined extracted copy."""
    db_path = Path(task["output_files_db"])
    path = item.snapshot.payload.normalized_path
    with closing(_connect(db_path)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchmany(2)
    if len(rows) != 1:
        raise ValueError("SOURCE_PATH_MISSING_OR_AMBIGUOUS")
    row = dict(rows[0])
    from ..extraction_layout import candidate_roots
    recorded = Path(task.get("extraction_directory") or db_path.parent / "extracted_files")
    roots = [r.resolve() for r in candidate_roots(recorded)
             if not r.is_symlink() and r.resolve().is_relative_to(db_path.parent.resolve())]
    if task.get("android_source") == "dir" and task.get("image_path"):
        logical_root = Path(task["image_path"])
        if logical_root.is_dir() and not logical_root.is_symlink():
            roots.append(logical_root.resolve())
    relative = path.replace("\\", "/")
    if ".." in Path(relative).parts:
        raise ValueError("SOURCE_PATH_OUTSIDE_EXTRACTION_ROOT")
    candidates = set()
    direct = Path(relative)
    if direct.is_absolute() and direct.is_file() and any(direct.resolve().is_relative_to(root) for root in roots):
        candidates.add(direct.resolve())
    direct_found = bool(candidates)
    for root in roots:
        if direct_found:
            break
        for value in (root / relative.lstrip("/"),):
            resolved = value.resolve()
            if resolved.is_relative_to(root) and resolved.is_file():
                candidates.add(resolved)
    if len(candidates) != 1:
        raise ValueError("EXTRACTED_SOURCE_MISSING_OR_AMBIGUOUS")
    resolved = candidates.pop()
    before = resolved.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("SOURCE_EXCEEDS_READ_BUDGET")
    with resolved.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    after = resolved.stat()
    if len(raw) > MAX_FILE_BYTES or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(raw) != before.st_size:
        raise ValueError("SOURCE_CHANGED_DURING_READ")
    actual_md5 = hashlib.md5(raw).hexdigest()
    expected = item.snapshot.payload.md5
    current_md5 = str(row.get("md5") or "")
    for value in (expected, current_md5):
        if value and re.fullmatch(r"[a-fA-F0-9]{32}", value) and value.lower() != actual_md5:
            raise ValueError("SOURCE_HASH_CHANGED")
    notes = [] if expected and re.fullmatch(r"[a-fA-F0-9]{32}", expected) else ["ORIGINAL_HASH_UNAVAILABLE"]
    if item.snapshot.payload.size is not None and item.snapshot.payload.size != len(raw):
        raise ValueError("SOURCE_SIZE_CHANGED")
    return resolved, raw, actual_md5, notes


def _transcript(task, key, md5):
    with closing(_connect(task["output_files_db"])) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='audio_transcripts'").fetchone():
            return None
        row = db.execute(
            "SELECT * FROM audio_transcripts WHERE task_id=? AND file_path=? AND md5=? "
            "AND status IN ('complete','partial') ORDER BY id DESC LIMIT 1",
            (task["id"], key[5:], md5),
        ).fetchone()
    return dict(row) if row else None


async def freeze_materials(task, items):
    result, image_bytes, text_chars = [], 0, 0
    for index, item in enumerate(sorted(items, key=lambda i: i.evidence_key), 1):
        identity, key = f"m{index:04}", item.evidence_key
        known_hash = ""
        value = material(identity, key, limitations=("NEUTRAL_SOURCE_UNAVAILABLE",))
        try:
            if item.snapshot.evidence_type == "android_artifact":
                payload = item.snapshot.payload
                known_hash = payload.record_hash
                text = json.dumps(payload.record_fields, ensure_ascii=False, sort_keys=True) if payload.record_fields else ""
                value = material(identity, key, kind="android_record", text=text,
                    source_hash=payload.record_hash, status="ready" if text else "unavailable",
                    limitations=("DERIVED_RECORD_NOT_ORIGINAL_DATABASE_ROW",))
            else:
                source, raw, md5, notes = await asyncio.to_thread(_file_bytes, task, item)
                source_hash = hashlib.sha256(raw).hexdigest()
                known_hash = source_hash
                ext = source.suffix.lower()
                if ext in IMAGE_EXTENSIONS:
                    if len(raw) > MAX_IMAGE_BYTES or image_bytes + len(raw) > MAX_IMAGE_TOTAL:
                        raise ValueError("IMAGE_FREEZE_BUDGET_EXCEEDED")
                    image_bytes += len(raw)
                    value = material(identity, key, kind="image", source_hash=source_hash,
                        media=base64.b64encode(raw).decode("ascii"), status="ready", limitations=notes)
                else:
                    kind, text = "text", ""
                    if ext in TEXT_EXTENSIONS or not ext:
                        if b"\x00" in raw[:8192] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                            raise ValueError("BINARY_TEXT_NOT_READABLE")
                        try:
                            text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
                        except UnicodeError:
                            try:
                                text = raw.decode("gb18030")
                                notes.append("TEXT_ENCODING_INFERRED_GB18030")
                            except UnicodeError:
                                raise ValueError("TEXT_ENCODING_UNSUPPORTED") from None
                    elif ext in DOCUMENT_EXTENSIONS:
                        if ext in (".db", ".sqlite", ".sqlite3"):
                            from ..extractors.relational_db import SQLiteExtractor
                            extractor = SQLiteExtractor()
                            notes.extend(("SQLITE_SCHEMA_AND_FIRST_50_ROWS_ONLY", "COMPANION_WAL_NOT_READ"))
                        else:
                            from ..document_extractor import get_document_extractor_locator
                            extractor = get_document_extractor_locator().get_extractor(str(source))
                        if extractor is None:
                            raise ValueError("DOCUMENT_PARSER_UNAVAILABLE")
                        # Parse captured bytes in isolation; legacy parsers cannot
                        # alter the evidence copy or read adjacent task artifacts.
                        with tempfile.TemporaryDirectory(prefix="tracelens-neutral-") as directory:
                            copy = Path(directory) / ("material" + ext)
                            copy.write_bytes(raw)
                            text, _method = await extractor.extract_to_markdown_detailed(str(copy))
                        if text.strip().startswith("[No content extracted from "):
                            raise ValueError("DOCUMENT_HAS_NO_READABLE_TEXT")
                        if hashlib.sha256(await asyncio.to_thread(source.read_bytes)).hexdigest() != source_hash:
                            raise ValueError("SOURCE_CHANGED_DURING_PARSE")
                        kind = "parsed_text"
                    elif ext in MEDIA_EXTENSIONS:
                        transcript = await asyncio.to_thread(_transcript, task, key, md5)
                        if not transcript or not transcript.get("full_text"):
                            raise ValueError("NEUTRAL_TRANSCRIPT_UNAVAILABLE")
                        text, kind = transcript["full_text"], "audio_transcript"
                        notes.append("MACHINE_TRANSCRIPT_NOT_VERIFIED_SPEECH")
                        if transcript["status"] != "complete" or transcript.get("coverage", 0) < 1:
                            notes.append("PARTIAL_TRANSCRIPT")
                    else:
                        raise ValueError("NEUTRAL_FORMAT_NOT_SUPPORTED")
                    if not text.strip():
                        raise ValueError("SOURCE_HAS_NO_READABLE_TEXT")
                    if text_chars + min(len(text), TEXT_LIMIT) > MAX_TEXT_TOTAL:
                        raise ValueError("TEXT_FREEZE_BUDGET_EXCEEDED")
                    text_chars += min(len(text), TEXT_LIMIT)
                    value = material(identity, key, kind=kind, text=text, source_hash=source_hash,
                        status="partial" if notes else "ready", limitations=notes)
        except Exception as error:
            code = str(error)
            value = material(identity, key, source_hash=known_hash, limitations=(
                code if re.fullmatch(r"[A-Z0-9_]+", code) else "NEUTRAL_SOURCE_READ_FAILED",
            ))
        result.append(value)
    return tuple(result)
