"""Storage for audio/video-track transcripts in the task files DB.

Design (2026-09-19, agreed): full transcripts live in the task's own
``_files.db`` (same lifecycle as the task, same md5 keying as
``file_analyses``), in an append-only ``audio_transcripts`` table with
latest-wins semantics. ``llm_description`` only carries the analysis plus
duration-banded key excerpts — never the full transcript. ``status``/
``coverage``/``note`` make future backfill a query instead of a wish:
``status != 'complete' OR coverage < threshold``.

C++ never needs to know this table exists — same pattern as
``ensure_file_analysis_schema``.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT    NOT NULL,
    file_path       TEXT    NOT NULL,
    md5             TEXT    NOT NULL DEFAULT '',
    source          TEXT    NOT NULL DEFAULT 'audio',
    language        TEXT    NOT NULL DEFAULT '',
    engine          TEXT    NOT NULL DEFAULT '',
    duration_sec    REAL    NOT NULL DEFAULT 0,
    transcribed_sec REAL    NOT NULL DEFAULT 0,
    coverage        REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'complete',
    note            TEXT    NOT NULL DEFAULT '',
    segments_json   TEXT    NOT NULL DEFAULT '[]',
    full_text       TEXT    NOT NULL DEFAULT '',
    trigger_source  TEXT    NOT NULL DEFAULT 'pipeline',
    created_at      INTEGER NOT NULL
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_at_path_md5 ON audio_transcripts(file_path, md5, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_at_status  ON audio_transcripts(status)",
)

TRANSCRIPT_STATUSES = ("complete", "partial", "pending_backfill", "failed")


def ensure_audio_transcript_schema(db_path: str) -> None:
    """Idempotently create the append-only transcript table and indexes."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SCHEMA)
        for index in INDEXES:
            conn.execute(index)
        conn.commit()
    finally:
        conn.close()


def save_transcript(db_path: str, record: Dict[str, Any]) -> int:
    """Append one transcript row; returns the new row id (append-only)."""
    status = record.get("status", "complete")
    if status not in TRANSCRIPT_STATUSES:
        raise ValueError(f"invalid transcript status: {status!r}")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO audio_transcripts (
                task_id, file_path, md5, source, language, engine,
                duration_sec, transcribed_sec, coverage, status, note,
                segments_json, full_text, trigger_source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("task_id", ""),
                record.get("file_path", ""),
                record.get("md5", ""),
                record.get("source", "audio"),
                record.get("language", ""),
                record.get("engine", ""),
                float(record.get("duration_sec", 0.0)),
                float(record.get("transcribed_sec", 0.0)),
                float(record.get("coverage", 0.0)),
                status,
                record.get("note", ""),
                json.dumps(record.get("segments", []), ensure_ascii=False),
                record.get("full_text", ""),
                record.get("trigger_source", "pipeline"),
                int(record.get("created_at", 0)),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def latest_transcript(
    db_path: str, file_path: str, md5: str = "", source: str = "audio"
) -> Optional[Dict[str, Any]]:
    """Newest row for (file_path, md5, source); ``md5=''`` matches any.

    Backfill-friendly: callers decide whether the latest row is good enough
    (``status == 'complete'`` etc.) — this helper never filters by quality.
    """
    if not db_path:
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if md5:
            row = conn.execute(
                """
                SELECT * FROM audio_transcripts
                WHERE file_path = ? AND md5 = ? AND source = ?
                ORDER BY id DESC LIMIT 1
                """,
                (file_path, md5, source),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM audio_transcripts
                WHERE file_path = ? AND source = ?
                ORDER BY id DESC LIMIT 1
                """,
                (file_path, source),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        try:
            record["segments"] = json.loads(record.get("segments_json") or "[]")
        except json.JSONDecodeError:
            record["segments"] = []
        return record
    finally:
        conn.close()


def segments_to_timeline(segments: List[Dict[str, Any]], limit_chars: int = 60000) -> str:
    """Render transcript segments as a timestamped timeline for synthesis.

    Timestamps are ``[mm:ss]`` (``[hh:mm:ss]`` past one hour) so the LLM can
    cite excerpts precisely; ``limit_chars`` bounds pathological inputs.
    """
    lines: List[str] = []
    used = 0
    for segment in segments:
        start = float(segment.get("s", 0.0))
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        m, s = divmod(int(start), 60)
        h, m = divmod(m, 60)
        stamp = f"[{h:d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"
        line = f"{stamp} {text}"
        if used + len(line) > limit_chars:
            lines.append("…(转写过长,已截断)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
