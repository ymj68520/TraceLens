"""Pydantic models for Investigation Evidence Snapshots (Phase C4a).

A Snapshot is the immutable Initial-state of an Evidence frozen at first
capture. ``FileSnapshotPayload`` / ``ClusterSnapshotPayload`` are the typed
payloads stored (deterministically serialized) in ``evidence_snapshots.snapshot_json``.
Missing source fields are NULL -- a Snapshot never generates data (no LLM).
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict


class FileSnapshotPayload(BaseModel):
    """Frozen initial state of a file Evidence (read from files.db at capture)."""

    model_config = ConfigDict(frozen=True)

    evidence_type: Literal["file"] = "file"
    normalized_path: str
    name: Optional[str] = None
    extension: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    size: Optional[int] = None
    md5: Optional[str] = None
    mtime: Optional[int] = None
    ctime: Optional[int] = None
    is_deleted: Optional[int] = None
    # Initial Analysis, frozen as-is (never generated)
    initial_summary: Optional[str] = None
    initial_description: Optional[str] = None
    initial_keywords: Optional[str] = None
    initial_model: Optional[str] = None
    initial_analyzed_at: Optional[int] = None
    scene_type: Optional[str] = None
    scene_priority: Optional[int] = None
    scene_relevant: Optional[int] = None


class ClusterSnapshotPayload(BaseModel):
    """Frozen initial state of a cluster Evidence (recomputed from events.db at capture).

    Initial AI fields are None in C4a: cluster identity is the 2-part
    ``(unix_minute, event_type)``, but cluster LLM analysis is written at 3-part
    granularity (with parent_directory), so a cluster-level AI value cannot be
    determined deterministically -- empty rather than fabricated (S7).
    """

    model_config = ConfigDict(frozen=True)

    evidence_type: Literal["cluster"] = "cluster"
    unix_minute: int
    event_type: str
    cluster_start: Optional[int] = None
    cluster_end: Optional[int] = None
    event_count: Optional[int] = None
    representative_timestamp: Optional[int] = None
    initial_summary: Optional[str] = None
    initial_description: Optional[str] = None
    initial_keywords: Optional[str] = None


SnapshotPayload = Union[FileSnapshotPayload, ClusterSnapshotPayload]


class SnapshotCandidate(BaseModel):
    """Fully-built, immutable snapshot ready to INSERT (constructed outside the
    write transaction)."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    evidence_type: Literal["file", "cluster"]
    captured_at: int
    payload: SnapshotPayload
    # identity / index columns (must satisfy the table CHECK)
    normalized_path: Optional[str] = None
    unix_minute: Optional[int] = None
    event_type: Optional[str] = None


class EvidenceSnapshot(BaseModel):
    """A captured (or re-read) immutable Evidence Snapshot."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    evidence_type: Literal["file", "cluster"]
    captured_at: int
    payload: SnapshotPayload
