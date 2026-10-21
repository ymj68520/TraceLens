"""People and priority overlays; no ingestion, report publication or GET writes."""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ...services import get_service_manager
from ...services.field_security import audit_actor
from ...services.evidence import EvidenceStoreError
from ...services.people_graph.models import GraphFilter, IdentityRequest, StartRequest
from ...services.people_graph.storage import RunConflict
from ...services.investigation.repository import InvestigationMigrationRequiredError

router = APIRouter()
logger = logging.getLogger(__name__)


def service():
    return get_service_manager().people_graph_service


def error(exc):
    if isinstance(exc, (RunConflict, InvestigationMigrationRequiredError)):
        return HTTPException(409, str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(422, "筛选或身份调整参数无效")
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    if isinstance(exc, (EvidenceStoreError, RuntimeError)):
        return HTTPException(503, "人员图谱存储或模型服务暂不可用")
    logger.exception("people graph operation failed")
    return HTTPException(503, "人员图谱操作暂不可用，已有版本保持不变")


@router.post("/people-analysis/runs", status_code=202)
async def start(payload: StartRequest, request: Request):
    try:
        return await service().start(payload, audit_actor(request, payload.requested_by))
    except Exception as exc:
        raise error(exc) from exc


@router.get("/people-analysis/runs")
async def runs(task_id: str):
    try:
        return {"runs": await service().list_runs(task_id)}
    except Exception as exc:
        raise error(exc) from exc


@router.get("/people-analysis/runs/{run_id}")
async def status(run_id: str, task_id: str):
    try:
        return await service().status(task_id, run_id)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/people-analysis/runs/{run_id}/graph")
async def graph(run_id: str, task_id: str, request: Request):
    try:
        params = dict(request.query_params)
        if len(params) != len(request.query_params.multi_items()):
            raise ValueError("筛选参数重复")
        params.pop("task_id", None)
        return await service().graph(task_id, run_id, GraphFilter.model_validate(params))
    except Exception as exc:
        raise error(exc) from exc


@router.get("/people-analysis/runs/{run_id}/targets/{target_id}")
async def detail(run_id: str, target_id: str, task_id: str):
    try:
        return await service().detail(task_id, run_id, target_id)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/people-analysis/runs/{run_id}/identity/review")
async def identity(run_id: str, task_id: str, payload: IdentityRequest, request: Request):
    try:
        return await service().revise_identity(task_id, run_id, payload, audit_actor(request, payload.reviewer))
    except Exception as exc:
        raise error(exc) from exc


@router.post("/people-analysis/runs/{run_id}/cancel")
async def cancel(run_id: str, task_id: str):
    try:
        return await service().cancel(task_id, run_id)
    except Exception as exc:
        raise error(exc) from exc
