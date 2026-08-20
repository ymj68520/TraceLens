"""Task-scoped Workbench facade over canonical Investigation and R2 services.

The facade owns no persistence. It translates the remote Workbench response
shapes onto the local InvestigationRepository, R2 generation repository, and
strict narrative reader. The namespace is intentionally separate from the
flat canonical routes so it cannot shadow them.
"""

from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..config import get_project_root, get_settings
from ..services import get_service_manager
from ..services.evidence import EvidenceNotFoundError, EvidenceStoreError, parse_evidence_key
from ..services.evidence.resolver import EvidenceResolver
from ..services.forensic_report.models import ScopeType
from ..services.forensic_report.narrative_reader import read_narrative_version_strict
from ..services.investigation import AnalysisReviewDecision

router = APIRouter()


class BootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "cluster_seed"
    generate_llm_summaries: bool = False


class WorkbenchAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(min_length=1)
    analyst_note: str | None = None
    case_context: str | None = None
    related_evidence: list[str] = Field(default_factory=list, max_length=20)
    event_id: str | None = None
    include_case_context: bool = True
    include_related_evidence: bool = True


class WorkbenchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1)
    reviewer: str = "workbench"
    reason: str | None = None
    acknowledge_warnings: bool = False


class WorkbenchReportEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(min_length=1)
    usage: str = "excluded"
    role: str | None = None
    report_note: str | None = None
    analysis_id: str | None = None
    added_by: str = "workbench"


class WorkbenchNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(min_length=1)
    target_key: str = Field(min_length=1)
    content: str = Field(max_length=20_000)
    author: str | None = None


def _manager():
    try:
        return get_service_manager()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="investigation service unavailable") from exc


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _error(exc: Exception, not_found: str = "investigation resource not found") -> HTTPException:
    if isinstance(exc, EvidenceNotFoundError):
        return HTTPException(status_code=404, detail=not_found)
    if isinstance(exc, (ValueError, KeyError)):
        return HTTPException(status_code=400, detail="invalid investigation request")
    if isinstance(exc, EvidenceStoreError):
        return HTTPException(status_code=503, detail="investigation store unavailable")
    return HTTPException(status_code=500, detail="investigation operation failed")


async def _overview(task_id: str, manager) -> dict[str, Any]:
    evidence = await manager.investigation_read_service.list_evidence(task_id)
    events = await manager.investigation_event_service.list_events(task_id)
    report_evidence = await manager.report_evidence_service.list(task_id)
    graph = await manager.investigation_graph_service.get_graph(task_id)
    analyses: list[Any] = []
    for item in evidence:
        analyses.extend(
            await manager.secondary_analysis_executor.list_analyses(
                task_id, item.evidence_key
            )
        )
    return {
        "task": await manager.cpp_backend.get_task(task_id),
        "initialized": bool(evidence or events or report_evidence),
        "event_count": len(events),
        "analysis_count": len(analyses),
        "report_evidence_count": len(report_evidence),
        "evidence": [_dump(item) for item in evidence],
        "events": [{**_dump(item), "id": item.event_id} for item in events],
        "analyses": [{**_dump(item), "id": item.analysis_id} for item in analyses],
        "report_evidence": [_dump(item) for item in report_evidence],
        "graph": _dump(graph),
    }


def _analysis_view(analysis: Any) -> dict[str, Any]:
    value = _dump(analysis)
    value["id"] = analysis.analysis_id
    value["job_id"] = analysis.analysis_id
    value["progress"] = 100 if analysis.status.value in {"accepted", "rejected", "invalid", "failed"} else 0
    value["error"] = analysis.error_message
    return value


def _evidence_detail(resolved: Any, snapshot: Any, analyses: list[Any], report_item: Any) -> dict[str, Any]:
    detail = _dump(resolved)
    detail["evidence_key"] = resolved.evidence_key
    detail["evidence_type"] = "event_cluster" if resolved.evidence_type == "cluster" else "file"
    detail["title"] = resolved.normalized_path or resolved.event_type or resolved.evidence_key
    detail["file_path"] = resolved.normalized_path
    detail["timestamp"] = resolved.representative_timestamp
    detail["metadata"] = {
        "event_type": resolved.event_type,
        "event_count": resolved.event_count,
        "time_window": [resolved.cluster_start, resolved.cluster_end]
        if resolved.cluster_start is not None else None,
    }
    detail["snapshot"] = _dump(snapshot) if snapshot is not None else None
    detail["analyses"] = [_analysis_view(item) for item in analyses]
    detail["report_evidence"] = _dump(report_item) if report_item is not None else None
    detail["analysis_status"] = analyses[0].status.value if analyses else None
    return detail


async def _strict_report(task_id: str, report_id: str):
    settings = get_settings()
    root = Path(settings.report_output_dir)
    if not root.is_absolute():
        root = get_project_root() / root
    result = read_narrative_version_strict(
        root / "reports.db", root, task_id, report_id
    )
    if result is None:
        raise EvidenceNotFoundError("report not found")
    version, manifest = result
    return version, manifest


def _report_view(version: Any, manifest: Any) -> dict[str, Any]:
    raw = manifest.model_dump(mode="json")
    report_id = version.report_id
    sections = []
    citation_map = {item["citation_id"]: item for item in raw.get("citations", [])}
    referenced_claims: dict[str, dict[str, Any]] = {}
    for index, section in enumerate(raw.get("sections", []), start=1):
        section_id = f"SEC-{index:03d}"
        paragraphs = [{
            "text": section.get("content", ""),
            "claim_ids": [section["citation_ids"][0]] if section.get("citation_ids") and citation_map.get(section["citation_ids"][0], {}).get("claim_id") else [],
            "citation_ids": section.get("citation_ids", []),
        }]
        for citation_id in section.get("citation_ids", []):
            claim_id = citation_map.get(citation_id, {}).get("claim_id")
            if claim_id:
                referenced_claims.setdefault(claim_id, {"claim_id": claim_id, "section_ids": [], "citation_ids": []})
                referenced_claims[claim_id]["section_ids"].append(section_id)
                referenced_claims[claim_id]["citation_ids"].append(citation_id)
        sections.append({
            "section_id": section_id,
            "section_type": "narrative",
            "title": section.get("heading", section_id),
            "order": index,
            "paragraphs": paragraphs,
        })
    manifest_bytes = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report = {
        "report_id": report_id,
        "task_id": version.scope_id,
        "report_version": version.version,
        "report_schema_version": "r2-manifest-v1",
        "report_kind": "llm_generation",
        "status": "assembled",
        "created_at": version.generated_at,
        "final_report_hash": hashlib.sha256(manifest_bytes).hexdigest(),
        "input_hash": raw.get("input_hash"),
        "manifest_hash": hashlib.sha256(manifest_bytes).hexdigest(),
        "sections": sections,
        "citation_manifest": raw.get("citations", []),
        "claim_manifest": list(referenced_claims.values()),
    }
    return report


@router.get("/{task_id}")
async def workbench_overview(task_id: str, manager=Depends(_manager)):
    try:
        return await _overview(task_id, manager)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{task_id}/bootstrap")
async def workbench_bootstrap(task_id: str, request: BootstrapRequest, manager=Depends(_manager)):
    del request
    try:
        return await _overview(task_id, manager)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{task_id}/events")
async def workbench_events(task_id: str, manager=Depends(_manager)):
    try:
        events = await manager.investigation_event_service.list_events(task_id)
        return {"success": True, "events": [{**_dump(item), "id": item.event_id} for item in events], "total": len(events)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{task_id}/events/{event_id}")
async def workbench_event(task_id: str, event_id: str, manager=Depends(_manager)):
    try:
        event = await manager.investigation_event_service.get_event(task_id, event_id)
        return {"success": True, "event": {**_dump(event), "id": event.event_id}}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{task_id}/events/{event_id}/review")
async def workbench_event_review(task_id: str, event_id: str):
    raise HTTPException(status_code=409, detail="event review is not part of the canonical local contract")


@router.get("/{task_id}/events/{event_id}/evidence")
async def workbench_event_evidence(task_id: str, event_id: str, manager=Depends(_manager)):
    try:
        evidence = await manager.investigation_event_service.list_event_evidence(task_id, event_id)
        return {"success": True, "evidence": [_dump(item) for item in evidence], "total": len(evidence)}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/{task_id}/events/{event_id}/evidence/link")
async def workbench_link_event_evidence(task_id: str, event_id: str, payload: dict[str, Any], manager=Depends(_manager)):
    try:
        item = await manager.investigation_event_service.link_event_evidence(
            task_id, event_id, payload["evidence_key"], linked_by=payload.get("linked_by") or "workbench"
        )
        return {"success": True, "link": _dump(item)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{task_id}/evidence/detail")
async def workbench_evidence_detail(task_id: str, evidence_key: str = Query(...), manager=Depends(_manager)):
    try:
        resolved = await EvidenceResolver(manager.cpp_backend).resolve_evidence(task_id, evidence_key)
        snapshot = await manager.investigation_read_service.get_snapshot(task_id, resolved.evidence_key)
        analyses = await manager.secondary_analysis_executor.list_analyses(task_id, resolved.evidence_key)
        report_items = await manager.report_evidence_service.list(task_id)
        report_item = next((item for item in report_items if item.evidence_key == resolved.evidence_key), None)
        return {"success": True, "evidence": _evidence_detail(resolved, snapshot, analyses, report_item)}
    except Exception as exc:
        raise _error(exc, "evidence not found") from exc


@router.post("/{task_id}/evidence/analyze")
async def workbench_start_analysis(task_id: str, request: WorkbenchAnalysisRequest, manager=Depends(_manager)):
    try:
        analysis = await manager.secondary_analysis_executor.submit(
            task_id, request.evidence_key,
            analyst_note=request.analyst_note,
            case_context=request.case_context if request.include_case_context else None,
            related_evidence=tuple(request.related_evidence) if request.include_related_evidence else (),
        )
        return {"success": True, "job_id": analysis.analysis_id, "analysis_id": analysis.analysis_id, "version": analysis.version}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{task_id}/analysis-jobs/{job_id}")
async def workbench_analysis_job(task_id: str, job_id: str, manager=Depends(_manager)):
    try:
        analysis = await manager.secondary_analysis_executor.get_analysis(task_id, job_id)
        if analysis is None:
            raise EvidenceNotFoundError("analysis not found")
        return {"success": True, "job": _analysis_view(analysis)}
    except Exception as exc:
        raise _error(exc, "analysis not found") from exc


@router.get("/{task_id}/evidence/analysis")
async def workbench_analysis_versions(task_id: str, evidence_key: str = Query(...), manager=Depends(_manager)):
    try:
        parsed = parse_evidence_key(evidence_key)
        analyses = await manager.secondary_analysis_executor.list_analyses(task_id, parsed.canonical_key)
        return {"success": True, "versions": [_analysis_view(item) for item in analyses]}
    except Exception as exc:
        raise _error(exc) from exc


async def _review_analysis(task_id: str, analysis_id: str, decision: str, manager):
    try:
        enum = AnalysisReviewDecision(decision)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid analysis review decision") from exc
    return await manager.investigation_review_service.review(
        task_id, analysis_id, decision=enum, reviewer="workbench", reason=None
    )


@router.post("/{task_id}/analysis/{analysis_id}/accept")
async def workbench_accept_analysis(task_id: str, analysis_id: str, request: WorkbenchReviewRequest, manager=Depends(_manager)):
    try:
        analysis = await _review_analysis(task_id, analysis_id, "accepted", manager)
        return {"success": True, "analysis": _analysis_view(analysis)}
    except Exception as exc:
        raise _error(exc, "analysis not found") from exc


@router.post("/{task_id}/analysis/{analysis_id}/reject")
async def workbench_reject_analysis(task_id: str, analysis_id: str, manager=Depends(_manager)):
    try:
        analysis = await _review_analysis(task_id, analysis_id, "rejected", manager)
        return {"success": True, "analysis": _analysis_view(analysis)}
    except Exception as exc:
        raise _error(exc, "analysis not found") from exc


@router.post("/{task_id}/events/{event_id}/refresh")
async def workbench_refresh_event(task_id: str, event_id: str, payload: dict[str, Any], manager=Depends(_manager)):
    try:
        refresh = await manager.event_refresh_executor.submit(task_id, event_id, requested_by=payload.get("requested_by") or "workbench")
        return {"success": True, "job_id": refresh.refresh_id, "refresh_id": refresh.refresh_id, "refresh": _dump(refresh)}
    except Exception as exc:
        raise _error(exc, "event not found") from exc


@router.get("/{task_id}/events/{event_id}/versions")
async def workbench_event_versions(task_id: str, event_id: str, manager=Depends(_manager)):
    try:
        versions = await manager.investigation_event_service.list_event_versions(task_id, event_id)
        return {"success": True, "versions": [_dump(item) for item in versions]}
    except Exception as exc:
        raise _error(exc, "event not found") from exc


@router.post("/{task_id}/events/{event_id}/versions/{version_id}/accept")
@router.post("/{task_id}/events/{event_id}/versions/{version_id}/reject")
async def workbench_event_version_review(task_id: str, event_id: str, version_id: str):
    raise HTTPException(status_code=409, detail="event semantic version review is not part of the canonical local contract")


@router.get("/{task_id}/events/{event_id}/versions/{version_id}/claims")
@router.get("/{task_id}/events/{event_id}/claims/effective")
async def workbench_event_claims(task_id: str, event_id: str, version_id: str | None = None):
    del task_id, event_id, version_id
    return {"success": True, "claims": []}


@router.post("/{task_id}/events/{event_id}/versions/{version_id}/claims/{claim_id}/accept")
@router.post("/{task_id}/events/{event_id}/versions/{version_id}/claims/{claim_id}/reject")
async def workbench_event_claim_review(task_id: str, event_id: str, version_id: str, claim_id: str):
    raise HTTPException(status_code=409, detail="event claim review is not part of the canonical local contract")


@router.get("/{task_id}/claims/{claim_id}")
async def workbench_claim_provenance(task_id: str, claim_id: str):
    raise HTTPException(status_code=404, detail="claim provenance not found")


@router.post("/{task_id}/notes")
async def workbench_save_note(task_id: str, request: WorkbenchNoteRequest):
    del task_id, request
    raise HTTPException(status_code=409, detail="analyst notes require an explicit canonical schema decision")


@router.get("/{task_id}/notes")
async def workbench_get_note(task_id: str, target_type: str = Query(...), target_key: str = Query(...)):
    del task_id, target_type, target_key
    return {"success": True, "note": None}


@router.put("/{task_id}/report-evidence")
async def workbench_set_report_evidence(task_id: str, request: WorkbenchReportEvidenceRequest, manager=Depends(_manager)):
    try:
        if request.usage == "excluded":
            item = await manager.report_evidence_service.update(
                task_id, request.evidence_key, report_status="excluded", updated_by=request.added_by
            )
        else:
            item = await manager.report_evidence_service.add(
                task_id, request.evidence_key, report_status=request.usage,
                analysis_id=request.analysis_id, added_by=request.added_by
            )
        return {"success": True, "report_evidence": _dump(item)}
    except Exception as exc:
        raise _error(exc, "report evidence not found") from exc


@router.post("/{task_id}/report-evidence/remove")
async def workbench_remove_report_evidence(task_id: str, payload: dict[str, Any], manager=Depends(_manager)):
    try:
        item = await manager.report_evidence_service.update(
            task_id, payload["evidence_key"], report_status="excluded", updated_by="workbench"
        )
        return {"success": True, "report_evidence": _dump(item)}
    except Exception as exc:
        raise _error(exc, "report evidence not found") from exc


@router.get("/{task_id}/report-evidence")
async def workbench_report_evidence(task_id: str, manager=Depends(_manager)):
    try:
        items = await manager.report_evidence_service.list(task_id)
        return {"success": True, "report_evidence": [_dump(item) for item in items]}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{task_id}/graph/local")
async def workbench_local_graph(task_id: str, max_nodes: int = Query(50, ge=1, le=200), manager=Depends(_manager)):
    try:
        graph = await manager.investigation_graph_service.get_graph(task_id, max_base_nodes=max_nodes)
        value = _dump(graph)
        value["base_available"] = value.pop("base_graph_available", False)
        value["links"] = value.pop("links", [])
        return {"success": True, **value}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/{task_id}/final-reports")
async def workbench_final_reports(task_id: str):
    try:
        settings = get_settings()
        root = Path(settings.report_output_dir)
        if not root.is_absolute():
            root = get_project_root() / root
        db_path = root / "reports.db"
        if not db_path.is_file():
            return {"success": True, "reports": []}
        uri = f"file:{db_path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(
                "SELECT * FROM report_versions WHERE scope_type = ? AND scope_id = ? AND report_kind = ? ORDER BY version DESC",
                (ScopeType.TASK.value, task_id, "llm_generation"),
            ).fetchall()
        from ..services.forensic_report.repository import ReportRepository
        versions = [ReportRepository._to_model(row) for row in rows]
        reports = []
        for version in versions:
            if version.report_kind != "llm_generation":
                continue
            try:
                _version, manifest = await _strict_report(task_id, version.report_id)
            except EvidenceNotFoundError:
                continue
            reports.append(_report_view(version, manifest))
        return {"success": True, "reports": reports}
    except Exception as exc:
        raise _error(exc, "report not found") from exc


@router.get("/{task_id}/final-reports/{report_id}")
async def workbench_final_report(task_id: str, report_id: str):
    try:
        version, manifest = await _strict_report(task_id, report_id)
        return {"success": True, "report": _report_view(version, manifest)}
    except Exception as exc:
        raise _error(exc, "report not found") from exc


@router.get("/{task_id}/final-reports/{report_id}/markdown")
@router.get("/{task_id}/final-reports/{report_id}/html")
@router.get("/{task_id}/final-reports/{report_id}/print")
async def workbench_final_report_presentation(task_id: str, report_id: str, request: Request):
    try:
        version, manifest = await _strict_report(task_id, report_id)
        raw = manifest.model_dump(mode="json")
        if request.url.path.endswith("/html") or request.url.path.endswith("/print"):
            sections = "".join(
                f"<section><h2>{html.escape(section.get('heading', ''))}</h2><p>{html.escape(section.get('content', ''))}</p></section>"
                for section in raw.get("sections", [])
            )
            body = f"<!doctype html><html><body><h1>{html.escape(raw.get('title', 'Final Report'))}</h1>{sections}</body></html>"
            return Response(content=body, media_type="text/html")
        body = [f"# {raw.get('title', 'Final Report')}", ""]
        for section in raw.get("sections", []):
            body.extend([f"## {section.get('heading', '')}", "", section.get("content", ""), ""])
        return Response(content="\n".join(body), media_type="text/markdown")
    except Exception as exc:
        raise _error(exc, "report not found") from exc


@router.get("/{task_id}/final-reports/{report_id}/publication")
async def workbench_final_report_publication(task_id: str, report_id: str):
    del task_id, report_id
    return {"success": True, "publication": None}


@router.post("/{task_id}/final-reports/{report_id}/publish")
async def workbench_publish_final_report(task_id: str, report_id: str):
    del task_id, report_id
    raise HTTPException(status_code=409, detail="publication is owned by the canonical R2 report workflow")
