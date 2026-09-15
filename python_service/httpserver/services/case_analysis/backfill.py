"""Backfill ``event_cluster_analyses`` from per-event ``llm_*`` data (SPEC §3.3).

Historical analyses live only as per-event columns; the actual bucket used by
past timeline analyses is unrecoverable, so 60 s / offset 0 is the only
defensible reconstruction granularity. Reconstructed rows are marked
``trigger_source='migrated'`` so they remain distinguishable from live
analyses, and their member fingerprint is recomputed from current members —
rows whose true bucket differed will honestly surface as stale.

Idempotent: a database with any existing analysis rows is skipped untouched.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List

from ..investigation_evidence import parent_directory_of, trunc_div
from .schema import ensure_cluster_analysis_schema, members_fingerprint

logger = logging.getLogger(__name__)


def _pick_analysis_source(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Latest-analyzed member carrying text; falls back to the first member."""

    def sort_key(row: Dict[str, Any]):
        return (row.get("llm_analyzed_at") or 0, row.get("id") or 0)

    ordered = sorted(members, key=sort_key, reverse=True)
    for row in ordered:
        if (row.get("llm_summary") or row.get("llm_description")):
            return row
    return ordered[0]


def backfill_events_db(events_db: str, task_id: str = "") -> Dict[str, Any]:
    """Reconstruct migrated analysis rows for one ``_events.db``.

    Returns a summary dict: ``status`` is ``backfilled`` or ``skipped``.
    """
    ensure_cluster_analysis_schema(events_db)

    with sqlite3.connect(events_db, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT COUNT(*) FROM event_cluster_analyses"
        ).fetchone()[0]
        if existing:
            return {"status": "skipped", "existing": int(existing)}

        rows = conn.execute(
            "SELECT id, timestamp, event_type, file_path, llm_summary, "
            "llm_description, llm_keywords, llm_analyzed_at, llm_model_used "
            "FROM events WHERE llm_analyzed_at IS NOT NULL"
        ).fetchall()

        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in rows:
            member = dict(row)
            coordinate = (
                trunc_div(int(member["timestamp"] or 0), 60),
                member["event_type"] or "UNKNOWN",
                parent_directory_of(member["file_path"] or ""),
            )
            groups.setdefault(coordinate, []).append(member)

        inserted = 0
        for (bucket_index, event_type, parent_directory), members in sorted(groups.items()):
            fingerprint = members_fingerprint([int(m["id"]) for m in members])
            source = _pick_analysis_source(members)
            description = source.get("llm_description") or ""
            summary = source.get("llm_summary") or description[:200]
            conn.execute(
                """
                INSERT INTO event_cluster_analyses (
                    task_id, bucket_epoch_offset, bucket_seconds, bucket_index,
                    event_type, parent_directory, member_count, member_min_id,
                    member_max_id, members_hash, summary, description, keywords,
                    model, trigger_source, analysis_id_upstream, created_at, ingested_at
                ) VALUES (?, 0, 60, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'migrated',
                          NULL, ?, NULL)
                """,
                (
                    task_id,
                    bucket_index,
                    event_type,
                    parent_directory,
                    fingerprint["member_count"],
                    fingerprint["member_min_id"],
                    fingerprint["member_max_id"],
                    fingerprint["members_hash"],
                    summary,
                    description,
                    source.get("llm_keywords") or "",
                    source.get("llm_model_used") or "unknown",
                    int(source.get("llm_analyzed_at") or 0),
                ),
            )
            inserted += 1
        conn.commit()

    logger.info(f"Backfilled {inserted} migrated cluster analyses into {events_db}")
    return {"status": "backfilled", "rows": inserted}
