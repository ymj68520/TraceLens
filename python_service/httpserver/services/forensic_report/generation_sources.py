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
from ..extractors.base import BaseExtractor, DocumentContentUnavailableError, validate_extracted_text

MAX_FILE_BYTES = 256 * 1024 * 1024
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
             status="unavailable", limitations=(), provenance=None):
    excerpt = text[:TEXT_LIMIT]
    notes = list(limitations)
    if len(text) > len(excerpt):
        notes.append("FIRST_4000_PARSED_CHARACTERS_ONLY")
        status = "partial"
    return NeutralMaterial(
        material_id=identity, evidence_key=key, kind=kind, text=excerpt,
        media_base64=media, source_sha256=source_hash,
        content_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        original_characters=len(text), status=status, limitations=tuple(notes), source_provenance=provenance,
    )


def _connect(path):
    return sqlite3.connect(f"file:{quote(str(Path(path).resolve()), safe='/')}?mode=ro", uri=True)


def _file_bytes(task, item):
    """Compatibility wrapper around the shared source reader."""
    from ..source_reading import resolve_source
    payload=item.snapshot.payload
    bundle=resolve_source(task,payload.normalized_path,getattr(payload,"source_id",None),payload)
    with bundle.snapshot(max_bytes=MAX_FILE_BYTES) as (copy,hashes,_provenance):
        return bundle.path,copy.read_bytes(),hashes['md5'],list(bundle.limitations)


def _transcript(task, key, md5):
    from ..evidence.keys import parse_evidence_key
    from ..source_identity import analysis_reference
    parsed=parse_evidence_key(key)
    with closing(_connect(task["output_files_db"])) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='audio_transcripts'").fetchone():
            return None
        row = db.execute(
            "SELECT * FROM audio_transcripts WHERE task_id=? AND file_path=? AND md5=? "
            "AND status IN ('complete','partial') ORDER BY id DESC LIMIT 1",
            (task["id"], analysis_reference(parsed.normalized_path,parsed.source_id), md5),
        ).fetchone()
    return dict(row) if row else None


async def freeze_materials(task, items, *, cpp_backend=None):
    from ..source_reading import ensure_source
    from ..document_extractor import get_document_extractor_locator
    result, image_bytes, text_chars = [], 0, 0
    for index, item in enumerate(sorted(items, key=lambda i: i.evidence_key), 1):
        identity,key=f"m{index:04}",item.evidence_key
        known_hash="";provenance=None
        value=material(identity,key,limitations=("NEUTRAL_SOURCE_UNAVAILABLE",))
        try:
            if item.snapshot.evidence_type=='windows_artifact':
                from ..windows_activity_reader import render
                payload=item.snapshot.payload;known_hash=payload.record_hash
                provenance={'result_set_id':payload.result_set_id,'record_id':payload.record_id,
                    'record_hash':known_hash,'hash_scope':'immutable_windows_record','source_revision':payload.source_revision,
                    **payload.provenance,'coverage':payload.coverage}
                text=render(payload)
                if not text:raise ValueError('WINDOWS_RECORD_NO_READABLE_CONTENT')
                if text_chars+min(len(text),TEXT_LIMIT)>MAX_TEXT_TOTAL:raise ValueError('TEXT_FREEZE_BUDGET_EXCEEDED')
                text_chars+=min(len(text),TEXT_LIMIT)
                value=material(identity,key,kind='windows_record',text=text,source_hash=known_hash,
                    status='partial' if payload.warnings else 'ready',limitations=payload.warnings,provenance=provenance)
            elif item.snapshot.evidence_type == "android_artifact":
                payload=item.snapshot.payload
                known_hash=payload.record_hash
                text=json.dumps(payload.record_fields,ensure_ascii=False,sort_keys=True) if payload.record_fields else ""
                value=material(identity,key,kind="android_record",text=text,source_hash=known_hash,
                    status="ready" if text else "unavailable",limitations=("DERIVED_RECORD_NOT_ORIGINAL_DATABASE_ROW",))
            else:
                payload=item.snapshot.payload
                bundle=await ensure_source(task,payload.normalized_path,getattr(payload,"source_id",None),payload,cpp_backend)
                notes=list(bundle.limitations)
                if not re.fullmatch(r"[a-fA-F0-9]{32}",payload.md5 or ""):
                    notes.append("ORIGINAL_HASH_UNAVAILABLE")
                with bundle.snapshot(max_bytes=MAX_FILE_BYTES) as (copy,hashes,provenance):
                    known_hash=hashes['sha256']
                    ext=copy.suffix.lower()
                    if ext in IMAGE_EXTENSIONS:
                        if hashes['size']>MAX_IMAGE_BYTES or image_bytes+hashes['size']>MAX_IMAGE_TOTAL:
                            raise ValueError("IMAGE_FREEZE_BUDGET_EXCEEDED")
                        raw=copy.read_bytes();image_bytes+=len(raw)
                        value=material(identity,key,kind="image",source_hash=known_hash,
                            media=base64.b64encode(raw).decode('ascii'),status="partial" if notes else "ready",
                            limitations=notes,provenance=provenance)
                    else:
                        extractor=get_document_extractor_locator().get_extractor(str(copy))
                        if ext in MEDIA_EXTENSIONS:
                            transcript=await asyncio.to_thread(_transcript,task,key,hashes['md5'])
                            if not transcript or not transcript.get('full_text'):raise ValueError('NEUTRAL_TRANSCRIPT_UNAVAILABLE')
                            text=transcript['full_text'];kind='audio_transcript';notes.append('MACHINE_TRANSCRIPT_NOT_VERIFIED_SPEECH')
                        elif extractor is not None:
                            if isinstance(extractor,BaseExtractor):
                                parsed=await extractor.extract_result(str(copy));text=parsed.require_content()
                                notes.extend(parsed.diagnostics)
                                provenance.update(parser=parsed.parser,parser_version=parsed.parser_version,coverage=parsed.coverage)
                            else:
                                text,_method=await extractor.extract_to_markdown_detailed(str(copy));validate_extracted_text(text)
                                provenance.update(parser=_method)
                            kind='parsed_text'
                        elif ext in TEXT_EXTENSIONS or not ext:
                            with copy.open('rb') as stream:raw=stream.read(2*1024*1024)
                            if b'\x00' in raw[:8192] and not raw.startswith((b'\xff\xfe',b'\xfe\xff')):raise ValueError('BINARY_TEXT_NOT_READABLE')
                            try:text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
                            except UnicodeError:text=raw.decode('gb18030');notes.append('TEXT_ENCODING_INFERRED_GB18030')
                            if hashes['size']>len(raw):notes.append('TEXT_BYTES_SAMPLED')
                            kind='text';provenance.update(parser='bounded_text',parser_version='1')
                        else:raise ValueError('NEUTRAL_FORMAT_NOT_SUPPORTED')
                        if not text.strip():raise ValueError('SOURCE_HAS_NO_READABLE_TEXT')
                        if text_chars+min(len(text),TEXT_LIMIT)>MAX_TEXT_TOTAL:raise ValueError('TEXT_FREEZE_BUDGET_EXCEEDED')
                        text_chars+=min(len(text),TEXT_LIMIT)
                        value=material(identity,key,kind=kind,text=text,source_hash=known_hash,
                            status='partial' if notes else 'ready',limitations=notes,provenance=provenance)
        except Exception as error:
            code=getattr(error,'code',str(error))
            value=material(identity,key,source_hash=known_hash,provenance=provenance,
                limitations=(code if re.fullmatch(r'[A-Z0-9_]+',code) else 'NEUTRAL_SOURCE_READ_FAILED',))
        result.append(value)
    return tuple(result)
