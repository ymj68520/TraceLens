"""Report planning / retrieval / frozen ReportContextPack runtime (P7A).

The report runtime is NOT a second investigation pipeline: it binds one
completed Investigation through its immutable FinalizationRecord, organizes
the already-accepted material into a versioned outline, plans bounded
retrieval, and freezes a per-chapter ReportContextPack.  P7A stops at the
frozen pack -- no chapter writer, no assertion ledger, no publication.
"""

from .report_template import (
    FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID,
    REPORT_TEMPLATE_CONTRACT_VERSION,
    TEMPLATE_STARTER_VERSION,
    DynamicChapterPolicyV1,
    ReportTemplateDefinitionV1,
    ReportTemplateRegistry,
    ReportTemplateSectionV1,
    build_starter_template,
)
from .report_admission import (
    REPORT_RUNTIME_ADMISSION_VERSION,
    ReportRuntimeAdmissionError,
    ReportRuntimeAdmissionService,
    ReportRuntimeAdmissionV1,
)

__all__ = [
    "FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID",
    "REPORT_TEMPLATE_CONTRACT_VERSION",
    "TEMPLATE_STARTER_VERSION",
    "DynamicChapterPolicyV1",
    "ReportTemplateDefinitionV1",
    "ReportTemplateRegistry",
    "ReportTemplateSectionV1",
    "build_starter_template",
    "REPORT_RUNTIME_ADMISSION_VERSION",
    "ReportRuntimeAdmissionError",
    "ReportRuntimeAdmissionService",
    "ReportRuntimeAdmissionV1",
]
