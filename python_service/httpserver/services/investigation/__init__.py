"""Investigation Snapshot Foundation and public capture orchestration (Phase C4a/C3/C4b-1).

Public capture flow:
    task_id + evidence_key
      -> EvidenceResolver (task-scoped trust boundary)
      -> InvestigationCaptureService
      -> task-bound InvestigationRepository.capture_if_absent

The package still owns no HTTP route for Secondary Analysis; routes live under
``httpserver.routes``.  Secondary Analysis persistence (create/transition/query)
is available via ``InvestigationRepository`` but not yet wired to LLM/Job/route.
"""

from .acquisition import build_snapshot_candidate, canonical_json
from .models import (
    SECONDARY_TRANSITIONS,
    TERMINAL_SECONDARY_STATUSES,
    AnalysisInputEnvelope,
    ClusterSnapshotPayload,
    EvidenceSnapshot,
    FileSnapshotPayload,
    SecondaryAnalysis,
    SecondaryAnalysisStatus,
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
    "SecondaryAnalysis",
    "SecondaryAnalysisStatus",
    "AnalysisInputEnvelope",
    "SECONDARY_TRANSITIONS",
    "TERMINAL_SECONDARY_STATUSES",
    "InvestigationCaptureService",
]
