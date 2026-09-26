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
]
