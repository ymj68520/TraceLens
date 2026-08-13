"""Investigation Snapshot Foundation (Phase C4a).

Public API:
    investigation_db_path_for_task(task) -> Path
    InvestigationRepository(db_path, task_id)
        .get_snapshot(evidence_key) -> Optional[EvidenceSnapshot]
        .capture_if_absent(resolved: ResolvedEvidence) -> EvidenceSnapshot
    build_snapshot_candidate(resolved) -> SnapshotCandidate

No service_manager registration and no routes here (C3 wires those). The
repository is task-scoped, fail-closed, and only persists immutable Evidence
Snapshots captured at first sight of a resolved Evidence.
"""

from .acquisition import build_snapshot_candidate, canonical_json
from .models import (
    ClusterSnapshotPayload,
    EvidenceSnapshot,
    FileSnapshotPayload,
    SnapshotCandidate,
)
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository, SUPPORTED_SCHEMA_VERSION

__all__ = [
    "investigation_db_path_for_task",
    "InvestigationRepository",
    "SUPPORTED_SCHEMA_VERSION",
    "build_snapshot_candidate",
    "canonical_json",
    "EvidenceSnapshot",
    "SnapshotCandidate",
    "FileSnapshotPayload",
    "ClusterSnapshotPayload",
]
