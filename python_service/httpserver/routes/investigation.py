"""Investigation Workbench routes (二次调查分析工作台).

Thin HTTP layer over ``InvestigationService``. All investigation state is
stored in the per-task ``investigation.db``; the initial pipeline databases
remain read-only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..services.investigation_errors import ClaimProvenanceNotFound, PublicationReadError, VersionConflict
from ..services.investigation_service import InvestigationService
from ..services.report_rendering import SectionRenderBlocked
from ..services.report_final_validation import ReportRenderCandidateNotFound
from ..services.final_report_assembly import FinalReportAssemblyRequest
from ..services.final_report_presentation import (
    FINAL_REPORT_PRESENTATION_VERSION,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_service: Optional[InvestigationService] = None


def get_investigation_service() -> InvestigationService:
    """Lazily construct the investigation service on the shared service manager."""
    global _service
    if _service is not None:
        return _service
    from ..services import get_service_manager

    sm = get_service_manager()
    _service = InvestigationService(
        cpp_backend=getattr(sm, "cpp_backend", None),
        llm_service=getattr(sm, "llm_service", None),
        graphiti_service=getattr(sm, "graphiti_service", None),
    )
    return _service


def _map_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, ClaimProvenanceNotFound):
        return HTTPException(status_code=404, detail="claim provenance not found")
    if isinstance(exc, (VersionConflict, SectionRenderBlocked)):
        detail = exc.errors if isinstance(exc, SectionRenderBlocked) else str(exc)
        return HTTPException(status_code=409, detail=detail)
    if isinstance(exc, ReportRenderCandidateNotFound):
        return HTTPException(status_code=404, detail="render candidate not found")
    if isinstance(exc, KeyError):
        detail = exc.args[0] if exc.args else str(exc)
        return HTTPException(status_code=404, detail=detail)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    logger.error("[Investigation] unhandled error: %s", exc, exc_info=True)
    return HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class BootstrapRequest(BaseModel):
    mode: str = Field(default="cluster_seed")
    generate_llm_summaries: bool = Field(default=False)


class LinkEvidenceRequest(BaseModel):
    evidence_key: str = Field(..., min_length=1)
    role: str = Field(default="supporting")
    rationale: Optional[str] = None


class UnlinkEvidenceRequest(BaseModel):
    evidence_key: str = Field(..., min_length=1)


class NoteRequest(BaseModel):
    target_type: str = Field(..., pattern="^(evidence|investigation_event)$")
    target_key: str = Field(..., min_length=1)
    content: str = Field(default="")
    author: Optional[str] = None


class AnalyzeRequest(BaseModel):
    evidence_key: str = Field(..., min_length=1)
    analyst_note: Optional[str] = None
    event_id: Optional[str] = None
    include_case_context: bool = True
    include_related_evidence: bool = True


class AcceptRequest(BaseModel):
    acknowledge_warnings: bool = False


class EventReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(draft|review_pending|confirmed|rejected)$")


class EventRefreshRequest(BaseModel):
    analyst_note: Optional[str] = None
    include_related_evidence: bool = True
    include_review_pending_analyses: bool = False


class ReportEvidenceRequest(BaseModel):
    evidence_key: str = Field(..., min_length=1)
    usage: str = Field(..., pattern="^(main|appendix)$")
    role: Optional[str] = None
    report_note: Optional[str] = None


class ReportEvidenceRemoveRequest(BaseModel):
    evidence_key: str = Field(..., min_length=1)


class ReportSectionRenderRequest(BaseModel):
    section_id: str = Field(..., min_length=1)


class ReportSectionValidationRequest(BaseModel):
    candidate_id: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Overview / bootstrap
# ---------------------------------------------------------------------------

@router.get("/{task_id}")
async def investigation_overview(
    task_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return await service.overview(task_id)
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/bootstrap")
async def investigation_bootstrap(
    task_id: str,
    request: BootstrapRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return await service.bootstrap(task_id)
    except Exception as exc:
        raise _map_errors(exc)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/{task_id}/events")
async def list_events(
    task_id: str,
    status: Optional[str] = Query(default=None),
    start_time: Optional[int] = Query(default=None),
    end_time: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        events = await service.list_events(
            task_id,
            status=status,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        return {"success": True, "events": events, "total": len(events)}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/events/{event_id}")
async def get_event(
    task_id: str,
    event_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        event = await service.get_event(task_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return {"success": True, "event": event}
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/review")
async def review_event(
    task_id: str,
    event_id: str,
    request: EventReviewRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        persistence = await service._persistence(task_id)
        persistence.set_event_review_status(task_id, event_id, request.status)
        return {"success": True, "event": persistence.get_event(task_id, event_id)}
    except Exception as exc:
        raise _map_errors(exc)


# ---------------------------------------------------------------------------
# Versioned semantic event refresh
# ---------------------------------------------------------------------------

@router.post("/{task_id}/events/{event_id}/refresh")
async def refresh_event(task_id: str, event_id: str, request: EventRefreshRequest, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        result = await service.start_event_refresh(
            task_id, event_id, request.analyst_note,
            request.include_related_evidence,
            request.include_review_pending_analyses,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/events/{event_id}/versions")
async def list_event_versions(task_id: str, event_id: str, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {"success": True, "versions": await service.list_event_versions(task_id, event_id)}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/versions/{version_id}/accept")
async def accept_event_version(task_id: str, event_id: str, version_id: str, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {"success": True, "version": await service.accept_event_version(task_id, event_id, version_id)}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/versions/{version_id}/reject")
async def reject_event_version(task_id: str, event_id: str, version_id: str, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {"success": True, "version": await service.reject_event_version(task_id, event_id, version_id)}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/claims/{claim_id}")
async def get_claim_provenance(
    task_id: str,
    claim_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {
            "success": True,
            "claim": await service.get_event_claim_provenance(task_id, claim_id),
        }
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/events/{event_id}/versions/{version_id}/claims")
async def list_event_claims(
    task_id: str,
    event_id: str,
    version_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {
            "success": True,
            "claims": await service.list_event_claims(task_id, event_id, version_id),
        }
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/versions/{version_id}/claims/{claim_id}/accept")
async def accept_event_claim(task_id: str, event_id: str, version_id: str, claim_id: str, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {"success": True, "claim": await service.review_event_claim(task_id, event_id, version_id, claim_id, True)}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/versions/{version_id}/claims/{claim_id}/reject")
async def reject_event_claim(task_id: str, event_id: str, version_id: str, claim_id: str, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {"success": True, "claim": await service.review_event_claim(task_id, event_id, version_id, claim_id, False)}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/events/{event_id}/claims/effective")
async def effective_event_claims(task_id: str, event_id: str, settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return {"success": True, "claims": await service.effective_event_claims(task_id, event_id)}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/events/{event_id}/evidence")
async def list_event_evidence(
    task_id: str,
    event_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        evidence = await service.list_event_evidence(task_id, event_id, limit, offset)
        return {"success": True, "evidence": evidence, "total": len(evidence)}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/evidence/link")
async def link_evidence(
    task_id: str,
    event_id: str,
    request: LinkEvidenceRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        result = await service.link_evidence(
            task_id, event_id, request.evidence_key, request.role, request.rationale
        )
        return {"success": True, **result}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/events/{event_id}/evidence/unlink")
async def unlink_evidence(
    task_id: str,
    event_id: str,
    request: UnlinkEvidenceRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        result = await service.unlink_evidence(task_id, event_id, request.evidence_key)
        return {"success": True, **result}
    except Exception as exc:
        raise _map_errors(exc)


# ---------------------------------------------------------------------------
# Evidence detail / notes
# ---------------------------------------------------------------------------

@router.get("/{task_id}/evidence/detail")
async def evidence_detail(
    task_id: str,
    evidence_key: str = Query(..., min_length=1),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        detail = await service.evidence_detail(task_id, evidence_key)
        if detail is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        return {"success": True, "evidence": detail}
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/notes")
async def save_note(
    task_id: str,
    request: NoteRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        note = await service.save_note(
            task_id, request.target_type, request.target_key,
            request.content, request.author,
        )
        return {"success": True, "note": note}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/notes")
async def get_note(
    task_id: str,
    target_type: str = Query(...),
    target_key: str = Query(...),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        note = await service.get_note(task_id, target_type, target_key)
        return {"success": True, "note": note}
    except Exception as exc:
        raise _map_errors(exc)


# ---------------------------------------------------------------------------
# Secondary analysis
# ---------------------------------------------------------------------------

@router.post("/{task_id}/evidence/analyze")
async def analyze_evidence(
    task_id: str,
    request: AnalyzeRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        result = await service.start_evidence_analysis(
            task_id=task_id,
            evidence_key=request.evidence_key,
            analyst_note=request.analyst_note,
            event_id=request.event_id,
            include_case_context=request.include_case_context,
            include_related_evidence=request.include_related_evidence,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/analysis-jobs/{job_id}")
async def get_analysis_job(
    task_id: str,
    job_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        job = await service.get_job_async(task_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"success": True, "job": job}
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/evidence/analysis")
async def list_analyses(
    task_id: str,
    evidence_key: str = Query(..., min_length=1),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        versions = await service.list_analyses(task_id, evidence_key)
        return {"success": True, "versions": versions}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/analysis/{analysis_id}/accept")
async def accept_analysis(
    task_id: str,
    analysis_id: str,
    request: AcceptRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        analysis = await service.accept_analysis(
            task_id, analysis_id, request.acknowledge_warnings
        )
        return {"success": True, "analysis": analysis}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/analysis/{analysis_id}/reject")
async def reject_analysis(
    task_id: str,
    analysis_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        analysis = await service.reject_analysis(task_id, analysis_id)
        return {"success": True, "analysis": analysis}
    except Exception as exc:
        raise _map_errors(exc)


# ---------------------------------------------------------------------------
# Report evidence
# ---------------------------------------------------------------------------

@router.put("/{task_id}/report-evidence")
async def set_report_evidence(
    task_id: str,
    request: ReportEvidenceRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        entry = await service.set_report_evidence(
            task_id, request.evidence_key, request.usage,
            role=request.role, report_note=request.report_note,
        )
        return {"success": True, "report_evidence": entry}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/report-evidence/remove")
async def remove_report_evidence(
    task_id: str,
    request: ReportEvidenceRemoveRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        result = await service.remove_report_evidence(task_id, request.evidence_key)
        return {"success": True, **result}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/report-evidence")
async def list_report_evidence(
    task_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        entries = await service.list_report_evidence(task_id)
        return {"success": True, "report_evidence": entries}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/report-dataset")
async def report_dataset(
    task_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return await service.build_report_dataset(task_id)
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/report-citations")
async def report_citations(
    task_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return await service.validate_report_citations(task_id)
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/report-section-plan")
async def report_section_plan(
    task_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        return await service.build_report_section_plan(task_id)
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/report-section-render")
async def report_section_render(
    task_id: str,
    request: ReportSectionRenderRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        candidate = await service.render_report_section(task_id, request.section_id)
        return {"success": True, "candidate": candidate}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/report-section-validations")
async def report_section_validation(
    task_id: str,
    request: ReportSectionValidationRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        validation = await service.validate_report_section(
            task_id, request.candidate_id
        )
        return {"success": True, "validation": validation}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/final-reports")
async def final_report_assembly(
    task_id: str,
    request: FinalReportAssemblyRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        result = await service.assemble_final_report(task_id, request)
        return {"success": True, **result}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/final-reports")
async def final_report_list(
    task_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        reports = await service.list_final_reports(task_id)
        return {"success": True, "reports": reports}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/final-reports/{report_id}")
async def final_report_detail(
    task_id: str,
    report_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        report = await service.get_final_report(task_id, report_id)
        return {"success": True, "report": report}
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/final-reports/{report_id}/markdown")
async def final_report_markdown(
    task_id: str,
    report_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        service = get_investigation_service()
        artifact = await service.get_final_report_presentation(
            task_id, report_id, "markdown"
        )
        return Response(
            content=artifact.body,
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{artifact.filename}"'
                ),
                "X-TraceLens-Presentation-Version": FINAL_REPORT_PRESENTATION_VERSION,
                "X-TraceLens-Presentation-SHA256": artifact.presentation_hash,
                "X-TraceLens-Final-Report-Hash": artifact.final_report_hash,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )
    except Exception as exc:
        raise _map_errors(exc)


@router.get("/{task_id}/final-reports/{report_id}/html")
async def final_report_html(
    task_id: str,
    report_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    return await _final_report_presentation_response(
        task_id, report_id, "html", inline=True
    )


@router.get("/{task_id}/final-reports/{report_id}/print")
async def final_report_print(
    task_id: str,
    report_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    return await _final_report_presentation_response(
        task_id, report_id, "print", inline=True
    )


async def _final_report_presentation_response(
    task_id: str,
    report_id: str,
    representation: str,
    *,
    inline: bool,
) -> Response:
    try:
        service = get_investigation_service()
        artifact = await service.get_final_report_presentation(
            task_id, report_id, representation
        )
        disposition = "inline" if inline else "attachment"
        return Response(
            content=artifact.body,
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": f"{disposition}; filename=\"{artifact.filename}\"",
                "X-TraceLens-Presentation-Version": FINAL_REPORT_PRESENTATION_VERSION,
                "X-TraceLens-Presentation-SHA256": artifact.presentation_hash,
                "X-TraceLens-Final-Report-Hash": artifact.final_report_hash,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )
    except Exception as exc:
        raise _map_errors(exc)

@router.get("/{task_id}/final-reports/{report_id}/publication")
async def final_report_publication(
    task_id: str,
    report_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        publication = await service.get_final_report_publication(task_id, report_id)
        return {"success": True, "publication": publication}
    except Exception as exc:
        raise _map_errors(exc)


@router.post("/{task_id}/final-reports/{report_id}/publish")
async def final_report_publish(
    task_id: str,
    report_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        publication = await service.publish_final_report(task_id, report_id)
        return {"success": True, "publication": publication}
    except Exception as exc:
        raise _map_errors(exc)


# ---------------------------------------------------------------------------

@router.get("/{task_id}/graph/local")
async def local_graph(
    task_id: str,
    evidence_key: Optional[str] = Query(default=None),
    event_id: Optional[str] = Query(default=None),
    max_nodes: int = Query(default=50, ge=1, le=200),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    try:
        service = get_investigation_service()
        graph = await service.local_graph(
            task_id, evidence_key=evidence_key, event_id=event_id, max_nodes=max_nodes
        )
        return {"success": True, **graph}
    except Exception as exc:
        raise _map_errors(exc)
