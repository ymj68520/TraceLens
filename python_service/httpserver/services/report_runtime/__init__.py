"""Report planning / retrieval / frozen ReportContextPack runtime (P7A).

The report runtime is NOT a second investigation pipeline: it binds one
completed Investigation through its immutable FinalizationRecord, organizes
the already-accepted material into a versioned outline, plans bounded
retrieval, and freezes a per-chapter ReportContextPack.  P7A stops at the
frozen pack -- no chapter writer, no assertion ledger, no publication.
"""

from .canonical import canonical_dumps, digest_text, sha256_hex
from .report_template import (
    FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID,
    REPORT_TEMPLATE_CONTRACT_VERSION,
    TEMPLATE_STARTER_VERSION,
    DynamicChapterPolicyV1,
    ReportTemplateDefinitionV1,
    ReportTemplateRegistry,
    ReportTemplateSectionV1,
    build_starter_template,
    default_template_registry,
)
from .report_admission import (
    REPORT_RUNTIME_ADMISSION_VERSION,
    ReportRuntimeAdmissionError,
    ReportRuntimeAdmissionService,
    ReportRuntimeAdmissionV1,
)
from .report_outline import (
    DeterministicReportOutlineBuilder,
    ReportOutlinePlanV1,
    ReportPlanningContextBuilder,
    ReportPlanningContextV1,
    validate_outline_plan,
)
from .report_chapter import ChapterSpecV1, chapter_specs_from_outline
from .report_retrieval import (
    DeterministicReportRetrievalPlanner,
    ReportRetrievalPlanV1,
)
from .report_context_pack import (
    FrozenReportContextPackV1,
    build_citation_allowlist,
    validate_citation_allowlist,
)
from .report_retrieval_service import ReportRetrievalService
from .report_chapter_generation import (
    CHAPTER_GENERATION_INPUT_VERSION,
    CHAPTER_OUTPUT_CONTRACT_VERSION,
    ChapterDispatchError,
    ChapterGenerationInputV1,
    NarrativePolicyV1,
    build_starter_narrative_policy,
    commit_report_chapter_dispatch,
    new_chapter_generation_input,
)
from .report_chapter_draft import (
    ChapterDraftV1,
    ReportAssertionV1,
    WriterMetadataV1,
)
from .report_chapter_validation import (
    ChapterValidationError,
    ReportAssertionCeilingValidator,
    validate_chapter_draft,
)
from .report_chapter_writer import (
    ChapterWriter,
    DeterministicChapterRenderer,
    WriterOutputError,
)
from .report_chapter_executor import (
    ChapterExecutionError,
    ChapterGenerationExecutor,
    retry_chapter_generation,
)
from .report_ledger import (
    ChapterDigestV1,
    LedgerAssertionV1,
    ReportAssertionLedgerV1,
    ReportConsistencyReviewV1,
    SemanticConsistencyReviewer,
    build_assertion_ledger,
    build_chapter_digest,
    run_deterministic_consistency,
)
from .report_synthesis import (
    ReportConsistencyPolicy,
    SynthesisContextPackV1,
    build_synthesis_context_pack,
    validate_synthesis_assertion,
)
from .report_publication import (
    AgentAwareCitationV3,
    GenerationReportManifestV3,
    ManifestProvenanceV3,
    PrevalidatedReportPublicationAdapter,
)

__all__ = [
    "canonical_dumps",
    "digest_text",
    "sha256_hex",
    "FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID",
    "REPORT_TEMPLATE_CONTRACT_VERSION",
    "TEMPLATE_STARTER_VERSION",
    "DynamicChapterPolicyV1",
    "ReportTemplateDefinitionV1",
    "ReportTemplateRegistry",
    "ReportTemplateSectionV1",
    "build_starter_template",
    "default_template_registry",
    "REPORT_RUNTIME_ADMISSION_VERSION",
    "ReportRuntimeAdmissionError",
    "ReportRuntimeAdmissionService",
    "ReportRuntimeAdmissionV1",
    "DeterministicReportOutlineBuilder",
    "ReportOutlinePlanV1",
    "ReportPlanningContextBuilder",
    "ReportPlanningContextV1",
    "validate_outline_plan",
    "ChapterSpecV1",
    "chapter_specs_from_outline",
    "DeterministicReportRetrievalPlanner",
    "ReportRetrievalPlanV1",
    "FrozenReportContextPackV1",
    "build_citation_allowlist",
    "validate_citation_allowlist",
    "ReportRetrievalService",
    "CHAPTER_GENERATION_INPUT_VERSION",
    "CHAPTER_OUTPUT_CONTRACT_VERSION",
    "ChapterDispatchError",
    "ChapterGenerationInputV1",
    "NarrativePolicyV1",
    "build_starter_narrative_policy",
    "commit_report_chapter_dispatch",
    "new_chapter_generation_input",
    "ChapterDraftV1",
    "ReportAssertionV1",
    "WriterMetadataV1",
    "ChapterValidationError",
    "ReportAssertionCeilingValidator",
    "validate_chapter_draft",
    "ChapterWriter",
    "DeterministicChapterRenderer",
    "WriterOutputError",
    "ChapterExecutionError",
    "ChapterGenerationExecutor",
    "retry_chapter_generation",
    "ChapterDigestV1",
    "LedgerAssertionV1",
    "ReportAssertionLedgerV1",
    "ReportConsistencyReviewV1",
    "SemanticConsistencyReviewer",
    "build_assertion_ledger",
    "build_chapter_digest",
    "run_deterministic_consistency",
    "ReportConsistencyPolicy",
    "SynthesisContextPackV1",
    "build_synthesis_context_pack",
    "validate_synthesis_assertion",
    "AgentAwareCitationV3",
    "GenerationReportManifestV3",
    "ManifestProvenanceV3",
    "PrevalidatedReportPublicationAdapter",
]
