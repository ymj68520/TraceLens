"""Read-only, bounded preflight jobs for unfamiliar evidence packages."""

import asyncio
import hmac
import json
import os

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from ..services import evidence_preflight as intake
from ..services.android_coverage import read_coverage
from ..services.android_artifact_reader import ArtifactUnavailable, artifact_detail, list_artifacts
from ..services.android_artifact_reader import ArtifactChanged
from ..services.android_result_sets import freeze_selected_result, read_frozen_artifact
from ..services import get_service_manager
from ..services.investigation.paths import investigation_db_path_for_task
from ..services.investigation.repository import InvestigationMigrationRequiredError
from ..services.evidence.exceptions import EvidenceStoreError
from ..services.task_store import get_task_record, TaskStoreError

router = APIRouter()


@router.post("/tasks/{task_id}/android-artifacts/{kind}/{row_id}/capture")
async def capture_android_artifact(request: Request, task_id: str, kind: str, row_id: int,
                                   payload: dict = Body(...)):
    """Explicit selected-row freeze; no client path or arbitrary evidence key."""
    _field_gate(request)
    if set(payload) != {"record_hash", "source_revision"}:
        raise HTTPException(status_code=400, detail="selected row hash and revision required")
    try:
        task = await get_task_record(task_id)
        if str(task.get("id")) != task_id:
            raise HTTPException(status_code=404, detail="task not found")
        investigation_db_path_for_task(task)  # fail before publishing a result set
        capture_service = get_service_manager().investigation_service
        manifest = await asyncio.to_thread(
            freeze_selected_result, task, kind, row_id,
            expected_row_hash=payload["record_hash"],
            expected_source_revision=payload["source_revision"],
        )
        key = f"android_artifact:v1:{task_id}:{manifest['result_set_id']}:{kind}:{row_id}"
        snapshot = await capture_service.capture(task_id, key)
        return {"success": True, "evidence_key": key, "snapshot": snapshot.model_dump(mode="json")}
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ArtifactChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="selected artifact unavailable") from exc
    except (ValueError, ArtifactUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvestigationMigrationRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EvidenceStoreError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="investigation capture is unavailable") from exc


@router.get("/tasks/{task_id}/android-result-sets/{result_set_id}/{kind}/{row_id}")
async def frozen_android_artifact(request: Request, task_id: str, result_set_id: str,
                                  kind: str, row_id: int):
    _field_gate(request)
    try:
        task = await get_task_record(task_id)
        if str(task.get("id")) != task_id:
            raise HTTPException(status_code=404, detail="task not found")
        detail = await asyncio.to_thread(read_frozen_artifact, task, result_set_id, kind, row_id)
        return {"success": True, **detail}
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="frozen artifact not found") from exc
    except (ValueError, ArtifactUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _field_gate(request: Request) -> None:
    """Fail closed until a trusted entry proxy injects the field token.

    This guards *new* row-content APIs. It does not retroactively protect the
    legacy services; deployment remains blocked until the entire entry is
    authenticated and backend listeners are isolated.
    """
    policy = getattr(request.app.state, "field_policy", None)
    if policy is not None and policy.enabled:
        if getattr(request.state, "principal", None) is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return  # the global field policy already checked this same request
    expected = os.environ.get("TRACELENS_FIELD_API_TOKEN", "")
    supplied = request.headers.get("x-tracelens-field-token", "")
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="field access is not configured")
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="field access denied")


@router.get("/tasks/{task_id}/android-artifacts/{kind}")
async def android_artifacts(request: Request, task_id: str, kind: str,
                            page: int = Query(1, ge=1),
                            page_size: int = Query(50, ge=1, le=100)):
    _field_gate(request)
    try:
        task = await get_task_record(task_id)
        if str(task.get("id")) != task_id:
            raise HTTPException(status_code=404, detail="task not found")
        return {"success": True, **await asyncio.to_thread(
            list_artifacts, task, kind, page=page, page_size=page_size)}
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, ArtifactUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/android-artifacts/{kind}/search")
async def search_android_artifacts(request: Request, task_id: str, kind: str,
                                   payload: dict = Body(...)):
    _field_gate(request)
    query = payload.get("query", "")
    page = payload.get("page", 1)
    if not isinstance(query, str) or len(query) > 200 or not isinstance(page, int) or isinstance(page, bool):
        raise HTTPException(status_code=400, detail="invalid Android artifact search")
    try:
        task = await get_task_record(task_id)
        if str(task.get("id")) != task_id:
            raise HTTPException(status_code=404, detail="task not found")
        return {"success": True, **await asyncio.to_thread(list_artifacts, task, kind, query=query, page=page)}
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, ArtifactUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/android-artifacts/{kind}/{row_id}")
async def android_artifact(request: Request, task_id: str, kind: str, row_id: int):
    _field_gate(request)
    try:
        task = await get_task_record(task_id)
        if str(task.get("id")) != task_id:
            raise HTTPException(status_code=404, detail="task not found")
        return {"success": True, **await asyncio.to_thread(artifact_detail, task, kind, row_id)}
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, ArtifactUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/android-coverage")
async def android_coverage(task_id: str):
    try:
        task = await get_task_record(task_id)
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "coverage": await asyncio.to_thread(read_coverage, task)}


@router.get("/tasks/{task_id}/android-coverage-manifest")
async def android_coverage_manifest(task_id: str):
    try:
        task = await get_task_record(task_id)
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    coverage = await asyncio.to_thread(read_coverage, task)
    manifest = coverage.get("manifest")
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=404, detail="Android coverage manifest unavailable")
    return Response(json.dumps(manifest, ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="android-coverage-manifest.json"',
                             "X-Content-Type-Options": "nosniff"})


@router.get("/tasks/{task_id}/android-normalization-manifest")
async def android_normalization_manifest(task_id: str):
    try:
        task = await get_task_record(task_id)
    except TaskStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    coverage = await asyncio.to_thread(read_coverage, task)
    manifest = coverage.get("normalization_manifest")
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=404, detail="Android normalization manifest unavailable")
    return Response(json.dumps(manifest, ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="android-normalization-manifest.json"',
                             "X-Content-Type-Options": "nosniff"})


@router.get("/candidates")
async def candidates():
    return {"success": True, "candidates": await asyncio.to_thread(intake.list_candidates)}


@router.post("/jobs", status_code=202)
async def start(payload: dict = Body(...)):
    candidate_id = payload.get("candidate_id")
    full_hash = payload.get("full_hash", False)
    password = payload.get("password", "")
    selected_slot = payload.get("selected_slot", 0)
    if not isinstance(full_hash, bool):
        raise HTTPException(status_code=400, detail="full_hash must be boolean")
    if not isinstance(password, str) or len(password) > 1024:
        raise HTTPException(status_code=400, detail="password must be a string of at most 1024 characters")
    if not isinstance(selected_slot, int) or isinstance(selected_slot, bool) or not 0 <= selected_slot <= 31:
        raise HTTPException(status_code=400, detail="selected_slot must be 0..31")
    try:
        return {"success": True, "job": await asyncio.to_thread(
            intake.start_job, candidate_id, full_hash=full_hash, password=password,
            selected_slot=selected_slot,
        )}
    except intake.PreflightError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
async def status(job_id: str):
    try:
        return {"success": True, "job": await asyncio.to_thread(intake.get_job, job_id)}
    except intake.PreflightError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    try:
        return {"success": True, "job": await asyncio.to_thread(intake.cancel_job, job_id)}
    except intake.PreflightError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/manifest")
async def manifest(job_id: str):
    try:
        job = intake.get_job(job_id)
        if job["status"] not in {"completed", "partial"}:
            raise HTTPException(status_code=409, detail="manifest is not finalized")
        path = intake._job_dir(job_id) / "manifest.jsonl"
        if not path.is_file():
            raise FileNotFoundError("manifest not available for this job")
        return FileResponse(path, filename=f"{job_id}-manifest.jsonl",
                            media_type="application/x-ndjson",
                            content_disposition_type="attachment",
                            headers={"X-Content-Type-Options": "nosniff"})
    except HTTPException:
        raise
    except intake.PreflightError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
