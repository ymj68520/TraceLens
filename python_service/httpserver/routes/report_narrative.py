"""Strict task-scoped narrative report Viewer read (Phase R2d).

One exact published narrative version for the Viewer. The A-chain
``/{report_id}`` read routes stay untouched (they predate R2 and have no
task scope); this façade is the only read surface that may serve R2c
``llm_generation`` versions, and every identity check is task-scoped with
opaque misses (a cross-task report id is indistinguishable from a missing
one). The response reflects the persisted version row plus the persisted
manifest only -- no envelope bytes, no system prompt, no provider data,
no filesystem paths.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ..services.evidence.exceptions import EvidenceStoreError
from ..services.forensic_report.models import (
    CitationManifestEntry,
    ReportStatus,
    StructuredReportSection,
)
from ..services.forensic_report.narrative_reader import (
    read_narrative_version_strict,
)
from .report_generation import _report_root

router = APIRouter()


class NarrativeReportResponse(BaseModel):
    """The persisted contract of one published narrative report version."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    report_id: str
    version: int
    status: str
    generation_id: str
    title: str
    created_at: str
    model: str
    prompt_version: str
    input_hash: str
    sections: tuple[StructuredReportSection, ...]
    citations: tuple[CitationManifestEntry, ...]


@router.get(
    "/narrative/versions/{report_id}", response_model=NarrativeReportResponse
)
async def get_narrative_report_version(
    report_id: str,
    task_id: str = Query(min_length=1, max_length=256),
):
    """Exact-ID, task-scoped strict read of one narrative report version."""
    try:
        result = read_narrative_version_strict(
            _report_root() / "reports.db", _report_root(), task_id, report_id
        )
    except EvidenceStoreError as exc:
        raise HTTPException(
            status_code=503, detail="report narrative record is unavailable"
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="report not found")
    version, manifest = result
    return NarrativeReportResponse(
        task_id=manifest.task_id,
        report_id=manifest.report_id,
        version=version.version,
        status=ReportStatus(version.status).value,
        generation_id=manifest.generation_id,
        title=manifest.title,
        created_at=manifest.generated_at,
        model=manifest.model,
        prompt_version=manifest.prompt_version,
        input_hash=manifest.input_hash,
        sections=manifest.sections,
        citations=manifest.citations,
    )
