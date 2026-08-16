"""Strict read-only narrative report version access (Phase R2d).

The R2 narrative Viewer must never read through a repository constructor
(that would CREATE/migrate/self-heal) and never through the A-chain
``/{report_id}/manifest`` route (no task scope, and its layout check only
understands deterministic snapshots). This reader is the single strict
façade for one exact published narrative version:

- ``mode=ro`` + ``PRAGMA query_only``: no create, no migration, no heal;
- identity is the pair (``task_id``, ``report_id``) — a report id that
  exists under another task, or a deterministic snapshot id, is an opaque
  miss (None), never a hint about other tasks;
- the persisted manifest is resolved through the writer's confined layout
  and re-validated against the persisted schema, so a Viewer response can
  never expose a body whose manifest diverged from the version row;
- corruption fails closed with ``EvidenceStoreError`` (route maps to 503).

The manifest alone answers the citation traceback identity; live
Investigation reads are a separate optional enrichment the frontend does
through the C9a/C9b exact APIs, never through this reader.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from ..evidence.exceptions import EvidenceStoreError
from .generation_writer import GenerationReportWriter
from .models import GenerationReportManifest, ReportVersion
from .repository import ReportRepository

__all__ = ["read_narrative_version_strict"]


def _read_version_row(conn: sqlite3.Connection, report_id: str):
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_versions'"
    ).fetchone()
    if table is None:
        return None
    return conn.execute(
        "SELECT * FROM report_versions WHERE report_id = ?", (report_id,)
    ).fetchone()


def read_narrative_version_strict(
    db_path, report_root, task_id: str, report_id: str
) -> tuple[ReportVersion, GenerationReportManifest] | None:
    """Exact strict read of one published narrative report version.

    ``None`` means "no such narrative version for this task" (missing
    store/table/row, foreign task scope, or a deterministic snapshot id).
    Anything that exists but cannot be trusted raises ``EvidenceStoreError``.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    uri = f"file:{quote(str(path))}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only = ON")
            row = _read_version_row(conn, report_id)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise EvidenceStoreError("report store is unreadable") from exc
    if row is None:
        return None
    if "report_kind" not in row.keys():
        # Pre-R2d schema (never opened by an R2d repository): no row can
        # carry the narrative marker, so every exact read is a plain miss.
        return None
    if (
        row["scope_type"] != "task"
        or row["scope_id"] != task_id
        or row["report_kind"] != "llm_generation"
    ):
        # Opaque miss: cross-task ids and deterministic snapshot ids look
        # exactly like "not found" -- no scope information is disclosed.
        return None

    version = ReportRepository._to_model(row)
    writer = GenerationReportWriter(report_root)
    try:
        manifest_payload = writer.read_manifest(task_id, report_id)
        manifest = GenerationReportManifest.model_validate(manifest_payload)
    except (OSError, ValueError, KeyError) as exc:
        raise EvidenceStoreError("report narrative record is unavailable") from exc
    if (
        manifest.report_id != report_id
        or manifest.task_id != task_id
        or manifest.scope_id != task_id
    ):
        raise EvidenceStoreError("report narrative record is unavailable")
    return version, manifest
