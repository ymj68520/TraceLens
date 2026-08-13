"""Investigation Snapshot Foundation and public capture orchestration (Phase C4a/C3).

Public capture flow:
    task_id + evidence_key
      -> EvidenceResolver (task-scoped trust boundary)
      -> InvestigationCaptureService
      -> task-bound InvestigationRepository.capture_if_absent

The package still owns no HTTP route; routes live under ``httpserver.routes``.
No Secondary Analysis / Jobs / Claims tables are created here.
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
from .service import InvestigationCaptureService

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
    "InvestigationCaptureService",
]
