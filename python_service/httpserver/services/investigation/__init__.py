"""Investigation Snapshot Foundation and Secondary Analysis execution (Phase C4a/C3/C4b-1/C4b-2).

Public capture flow:
    task_id + evidence_key
      -> EvidenceResolver (task-scoped trust boundary)
      -> InvestigationCaptureService
      -> task-bound InvestigationRepository.capture_if_absent

Secondary Analysis execution:
    task_id + evidence_key
      -> SecondaryAnalysisExecutor.submit
      -> capture snapshot -> create_analysis(queued) -> background LLM execution
      -> queued -> running -> review_pending / failed
"""

from .acquisition import build_snapshot_candidate, canonical_json
from .event import InvestigationEventService
from .execution import SecondaryAnalysisExecutor
from .structured import StructuredOutputError, parse_structured_analysis_response
from .grounding import (
    GroundingValidator,
    compute_analysis_grounding,
    derive_allowed_evidence_ids,
)
from .models import (
    SECONDARY_TRANSITIONS,
    TERMINAL_SECONDARY_STATUSES,
    AnalysisClaim,
    AnalysisGroundingStatus,
    AnalysisInputEnvelopeV1,
    AnalysisInputEnvelopeV2,
    AnalysisReviewDecision,
    ClaimCandidate,
    ClaimGroundingStatus,
    ClaimType,
    ClusterSnapshotPayload,
    EvidenceSnapshot,
    EventEvidenceLink,
    EventRefresh,
    EventRefreshAcceptedAnalysisV1,
    EventRefreshClaimV1,
    EventRefreshEnvelopeV1,
    EventRefreshLinkV1,
    EventRefreshStatus,
    FileSnapshotPayload,
    InvestigationEvent,
    InvestigationEventVersion,
    RelatedEvidenceEntry,
    SecondaryAnalysis,
    SecondaryAnalysisStatus,
    StructuredAnalysisResponse,
    SnapshotCandidate,
    ValidatedClaim,
    parse_analysis_input_envelope,
)
from .paths import investigation_db_path_for_task
from .prompts import (
    CURRENT_PROMPT_VERSION,
    ENVELOPE_PROMPT_COMPAT,
    PROMPT_OUTPUT_CONTRACT,
    PROMPT_REGISTRY,
    get_prompt,
)
from .repository import (
    AnalysisReviewConflictError,
    InvestigationEventConflictError,
    InvestigationRepository,
    SUPPORTED_SCHEMA_VERSION,
)
from .review import AnalysisReviewConflictError, InvestigationReviewService
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
    "AnalysisInputEnvelopeV1",
    "AnalysisInputEnvelopeV2",
    "AnalysisReviewDecision",
    "RelatedEvidenceEntry",
    "parse_analysis_input_envelope",
    "SECONDARY_TRANSITIONS",
    "TERMINAL_SECONDARY_STATUSES",
    "InvestigationCaptureService",
    "InvestigationReviewService",
    "InvestigationEventService",
    "AnalysisReviewConflictError",
    "InvestigationEventConflictError",
    "EvidenceSnapshot",
    "EventEvidenceLink",
    "EventRefresh",
    "EventRefreshStatus",
    "EventRefreshClaimV1",
    "EventRefreshAcceptedAnalysisV1",
    "EventRefreshLinkV1",
    "EventRefreshEnvelopeV1",
    "InvestigationEvent",
    "InvestigationEventVersion",
    "SecondaryAnalysisExecutor",
    "CURRENT_PROMPT_VERSION",
    "ENVELOPE_PROMPT_COMPAT",
    "PROMPT_OUTPUT_CONTRACT",
    "PROMPT_REGISTRY",
    "get_prompt",
    "ClaimType",
    "ClaimGroundingStatus",
    "AnalysisGroundingStatus",
    "ClaimCandidate",
    "ValidatedClaim",
    "AnalysisClaim",
    "GroundingValidator",
    "derive_allowed_evidence_ids",
    "compute_analysis_grounding",
    "StructuredAnalysisResponse",
    "StructuredOutputError",
    "parse_structured_analysis_response",
]
