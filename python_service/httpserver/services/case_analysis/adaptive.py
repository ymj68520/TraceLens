"""Budget-driven adaptive bucket selection (SPEC event-cluster-analysis-redesign §5).

The LLM cost unit is the cluster, not the event: one LLM analysis per cluster.
This module scans candidate windows with pure SQL aggregates (no LLM calls)
and picks the smallest window whose cluster count fits the run budget, so an
initial analysis covers every event while staying inside a known cost bound.

The ladder is the analysis-side authority; the Timeline UI keeps its own
browsing ladder capped at 6 h (SPEC §4.3).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from ..investigation_evidence import PARENT_DIRECTORY_SQL

# Candidate windows in seconds: 1 min → 30 days (SPEC D4 cap = 2592000).
BUCKET_LADDER: List[int] = [60, 300, 900, 1800, 3600, 21600, 86400, 604800, 2592000]


def estimate_bucket(
    events_db: str,
    bucket_seconds: int,
    bucket_epoch_offset: int = 0,
    include_analyzed: bool = True,
) -> Dict[str, Any]:
    """Cluster count + largest member set for one candidate window (no LLM)."""
    where = "" if include_analyzed else "WHERE llm_analyzed_at IS NULL"
    sql = f"""
        SELECT COUNT(*) as cluster_count, MAX(n) as max_members
        FROM (
            SELECT COUNT(*) as n
            FROM events {where}
            GROUP BY {PARENT_DIRECTORY_SQL},
                     ((timestamp - ?) / {int(bucket_seconds)}),
                     event_type
        )
    """
    with sqlite3.connect(events_db, timeout=10) as conn:
        row = conn.execute(sql, (bucket_epoch_offset,)).fetchone()
    return {
        "bucket_seconds": int(bucket_seconds),
        "cluster_count": int(row[0] or 0),
        "max_members": int(row[1] or 0),
    }


def estimate_bucket_ladder(
    events_db: str,
    ladder: Optional[List[int]] = None,
    include_analyzed: bool = True,
) -> Dict[str, Any]:
    """Scan the ladder and recommend the run bucket (SPEC §5).

    Returns the per-candidate estimates plus the recommended bucket: the
    smallest window whose cluster count fits ``budget``; when every candidate
    exceeds the budget the largest window is recommended and ``warning``
    explains the overshoot.
    """
    from .schema import read_bucket_epoch_offset

    ladder = list(ladder or BUCKET_LADDER)
    offset = read_bucket_epoch_offset(events_db)
    estimates = [
        estimate_bucket(events_db, bucket, offset, include_analyzed)
        for bucket in sorted(set(ladder))
    ]
    return {
        "bucket_epoch_offset": offset,
        "estimates": estimates,
        "recommended_bucket_seconds": None,
        "warning": None,
    }


def choose_bucket(estimates: List[Dict[str, Any]], budget: int) -> Dict[str, Any]:
    """Pick the smallest candidate whose cluster count fits ``budget``."""
    fitting = [e for e in estimates if e["cluster_count"] <= budget]
    if fitting:
        chosen = min(fitting, key=lambda e: e["bucket_seconds"])
        return {"recommended_bucket_seconds": chosen["bucket_seconds"], "warning": None}
    largest = max(estimates, key=lambda e: e["bucket_seconds"])
    return {
        "recommended_bucket_seconds": largest["bucket_seconds"],
        "warning": (
            f"every candidate window exceeds the cluster budget ({budget}); "
            f"using the largest window {largest['bucket_seconds']}s which still "
            f"yields ~{largest['cluster_count']} clusters"
        ),
    }
