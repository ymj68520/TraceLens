"""Task-scoped Report Evidence binding orchestration (Phase R1).

The Evidence itself (canonical ``(task_id, evidence_key)`` of a captured
snapshot) is always the report source.  ``analysis_id`` is an OPTIONAL frozen
binding to one accepted Secondary Analysis of the SAME evidence, chosen and
re-chosen only by explicit analyst actions -- never a "latest accepted"
pointer, and never changed implicitly when newer versions are accepted later.

Reads go through the strictly read-only ``InvestigationGraphReader`` (C10
§14/E13 semantics: a missing store is "no report evidence", a corrupt or
unsupported store fails closed).  Writes run on the write-capable repository
inside one BEGIN IMMEDIATE transaction that performs the R1 §7 triple check
(same task, same evidence, status accepted) before touching the row.
"""

from __future__ import annotations

import asyncio
import json
import time
import sqlite3
from pathlib import Path

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.resolver import EvidenceResolver
from ..investigation_persistence import InvestigationPersistence
from .graph_reader import InvestigationGraphReader
from .models import ReportEvidenceItem
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository


class ReportEvidenceService:
    """Explicit analyst Report Evidence actions for one task."""

    def __init__(self, cpp_backend):
        self._cpp_backend = cpp_backend

    async def _resolve_task_db(self, task_id: str) -> Path:
        """Current-task lookup + trusted investigation.db destination.

        Raises ``EvidenceNotFoundError`` when the task does not exist or has
        no trusted database path (fail-closed, never a default location).
        """
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        if not task.get("output_files_db") and not task.get("output_events_db"):
            raise EvidenceNotFoundError("task not found")
        return investigation_db_path_for_task(task)

    async def list(self, task_id: str) -> list[ReportEvidenceItem]:
        """Every report_evidence row of the task (exact frozen bindings)."""
        db_path = await self._resolve_task_db(task_id)
        if not db_path.exists():
            # A task without an investigation.db has no report evidence; the
            # GET never creates or migrates the store (C10 §14).
            return []
        reader = InvestigationGraphReader(db_path, task_id)
        return await asyncio.to_thread(reader.list_report_evidence)

    async def add(
        self,
        task_id: str,
        evidence_key: str,
        *,
        report_status: str,
        analysis_id: str | None = None,
        added_by: str,
    ) -> ReportEvidenceItem:
        """Add one captured evidence to the report (main/appendix, optional
        explicit accepted-analysis binding).

        MVP (mvp-phase1-acceptance §6): with event seeding disabled there is
        no workbench event chain to capture the snapshot through, so a plain
        ``file:`` evidence is snapshotted here on first sight — the capture
        stays immutable (first-write-wins), exactly as on the event path.
        """
        db_path = await self._resolve_task_db(task_id)
        if evidence_key.startswith("file:"):
            try:
                resolved = await EvidenceResolver(self._cpp_backend).resolve_evidence(
                    task_id, evidence_key
                )
                path = resolved.normalized_path or ""
                with sqlite3.connect(
                    f"file:{resolved.source_db}?mode=ro", uri=True
                ) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT * FROM files WHERE path = ?", (path,)
                    ).fetchone()
                row_dict = dict(row) if row is not None else {}
                snapshot_json = json.dumps(
                    {
                        "evidence_type": "file",
                        "normalized_path": path,
                        "name": row_dict.get("name"),
                        "extension": row_dict.get("extension"),
                        "category": row_dict.get("category"),
                        "type": row_dict.get("type"),
                        "size": row_dict.get("size"),
                        "md5": row_dict.get("md5"),
                        "mtime": row_dict.get("mtime"),
                        "ctime": row_dict.get("ctime"),
                        "is_deleted": row_dict.get("is_deleted"),
                        "initial_summary": row_dict.get("llm_summary"),
                        "initial_description": row_dict.get("llm_description"),
                        "initial_keywords": row_dict.get("llm_keywords"),
                        "initial_model": row_dict.get("llm_model_used"),
                        "initial_analyzed_at": row_dict.get("llm_analyzed_at"),
                        "scene_type": row_dict.get("scene_type"),
                        "scene_priority": row_dict.get("scene_priority"),
                        "scene_relevant": row_dict.get("scene_relevant"),
                    },
                    ensure_ascii=False,
                )
                # Insert straight into the repository-v7 evidence_snapshots
                # table (columns: id, task_id, evidence_key, evidence_type,
                # normalized_path, snapshot_json, captured_at) — first write
                # wins, immutable afterwards.
                with sqlite3.connect(str(db_path), timeout=30) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "INSERT OR IGNORE INTO evidence_snapshots "
                        "(task_id, evidence_key, evidence_type, "
                        " normalized_path, snapshot_json, captured_at) "
                        "VALUES (?, ?, 'file', ?, ?, ?)",
                        (
                            task_id,
                            resolved.evidence_key,
                            path,
                            snapshot_json,
                            int(time.time()),
                        ),
                    )
                    conn.commit()
            except EvidenceNotFoundError:
                raise
            except Exception as exc:
                raise EvidenceStoreError(
                    f"cannot capture evidence snapshot: {exc}"
                ) from exc
        if not db_path.exists():
            raise EvidenceNotFoundError(
                "evidence snapshot not captured for this task"
            )
        try:
            repository = InvestigationRepository(db_path, task_id)
            await asyncio.to_thread(
                repository.add_report_evidence,
                evidence_key,
                report_status=report_status,
                analysis_id=analysis_id,
                added_by=added_by,
            )
            item = await asyncio.to_thread(
                InvestigationGraphReader(db_path, task_id).get_report_evidence,
                evidence_key,
            )
            if item is None:  # pragma: no cover - same transaction just inserted it
                raise EvidenceStoreError("report evidence readback failed")
            return item
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation database is unavailable"
            ) from exc

    async def update(
        self,
        task_id: str,
        evidence_key: str,
        *,
        report_status: str | None = None,
        analysis_id: str | None = None,
        bind_analysis: bool = False,
        updated_by: str,
    ) -> ReportEvidenceItem:
        """Explicitly set report_status and/or (re)bind the frozen analysis."""
        db_path = await self._resolve_task_db(task_id)
        if not db_path.exists():
            raise EvidenceNotFoundError("report evidence not found")
        try:
            repository = InvestigationRepository(db_path, task_id)
            await asyncio.to_thread(
                repository.update_report_evidence,
                evidence_key,
                report_status=report_status,
                analysis_id=analysis_id,
                bind_analysis=bind_analysis,
                updated_by=updated_by,
            )
            item = await asyncio.to_thread(
                InvestigationGraphReader(db_path, task_id).get_report_evidence,
                evidence_key,
            )
            if item is None:  # pragma: no cover - row was just updated
                raise EvidenceStoreError("report evidence readback failed")
            return item
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation database is unavailable"
            ) from exc

    async def list_file_candidates(
        self,
        task_id: str,
        *,
        search: str = "",
        status: str = "all",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """File-centric adjudication read model for the evidence review page.

        One read-only pass over the task's ``files`` table LEFT JOINed (via
        ATTACH) with this task's ``report_evidence`` rows, so each file row
        carries its current judgment: ``report_status`` is ``null`` for files
        never judged and main/appendix/excluded mirror R1 exactly. The report
        evidence row for a ``file:<path>`` key uses the same canonical path
        space as ``files.path`` (the R1 resolver reads that column directly).
        Read-only: a missing investigation.db simply means nothing is judged.
        """
        db_path = await self._resolve_task_db(task_id)
        task = await self._cpp_backend.get_task(task_id)
        files_db = (task or {}).get("output_files_db") or ""
        empty = {
            "total": 0,
            "page": page,
            "page_size": page_size,
            "status_counts": {"main": 0, "appendix": 0, "excluded": 0, "unjudged": 0},
            "items": [],
        }
        if not files_db or not Path(files_db).exists():
            return empty

        def _read() -> dict:
            conn = sqlite3.connect(f"file:{files_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                has_re_table = False
                if db_path.exists():
                    try:
                        conn.execute(
                            "ATTACH DATABASE ? AS inv", (f"file:{db_path}?mode=ro",)
                        )
                        has_re_table = conn.execute(
                            "SELECT 1 FROM inv.sqlite_master "
                            "WHERE type='table' AND name='report_evidence'"
                        ).fetchone() is not None
                    except sqlite3.Error:
                        has_re_table = False

                join_sql = ""
                if has_re_table:
                    join_sql = (
                        "LEFT JOIN inv.report_evidence re ON re.task_id = ? "
                        "AND re.evidence_key = 'file:' || f.path "
                        "AND re.evidence_key LIKE 'file:%'"
                    )

                # Global judgment counts (independent of the search filter).
                counts = {"main": 0, "appendix": 0, "excluded": 0, "unjudged": 0}
                if has_re_table:
                    for row in conn.execute(
                        f"SELECT COALESCE(re.report_status, 'unjudged') AS s, "
                        f"COUNT(*) AS c FROM files f {join_sql} GROUP BY s",
                        (task_id,),
                    ):
                        if row["s"] in counts:
                            counts[row["s"]] = int(row["c"])
                else:
                    counts["unjudged"] = int(
                        conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                    )

                where_status = ""
                join_params: list = []
                if has_re_table:
                    join_params.append(task_id)
                filter_params: list = []
                if search:
                    where_status += " AND f.path LIKE ?"
                    filter_params.append(f"%{search}%")
                if status != "all":
                    where_status += (
                        " AND COALESCE(re.report_status, 'unjudged') = ?"
                    )
                    filter_params.append(status)

                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM files f {join_sql} "
                        f"WHERE 1=1 {where_status}",
                        [*join_params, *filter_params],
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    f"SELECT f.path, f.name, f.extension, f.category, f.size, "
                    f"f.mtime, f.ctime, f.md5, f.is_deleted, f.llm_summary, "
                    f"f.llm_analyzed_at, f.scene_relevant, "
                    f"re.report_status AS re_status, re.analysis_id AS re_analysis, "
                    f"re.updated_at AS re_updated "
                    f"FROM files f {join_sql} WHERE 1=1 {where_status} "
                    f"ORDER BY f.path LIMIT ? OFFSET ?",
                    [
                        *join_params,
                        *filter_params,
                        page_size,
                        (page - 1) * page_size,
                    ],
                ).fetchall()
                items = []
                for row in rows:
                    report_status = row["re_status"] if has_re_table else None
                    items.append({
                        "path": row["path"],
                        "name": row["name"],
                        "extension": row["extension"],
                        "category": row["category"],
                        "size": row["size"],
                        "mtime": row["mtime"],
                        "ctime": row["ctime"],
                        "md5": row["md5"],
                        "is_deleted": row["is_deleted"],
                        "llm_summary": row["llm_summary"],
                        "llm_analyzed_at": row["llm_analyzed_at"],
                        "scene_relevant": row["scene_relevant"],
                        "evidence_key": f"file:{row['path']}",
                        "report_status": report_status,
                        "analysis_id": row["re_analysis"] if has_re_table else None,
                        "updated_at": row["re_updated"] if has_re_table else None,
                    })
                return {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "status_counts": counts,
                    "items": items,
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_read)


__all__ = ["ReportEvidenceService"]
