"""Read-only event projections and explicitly requested, versioned suggestions."""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ...services import get_service_manager
from ...services.event_graph.models import StartRequest, ViewFilter
from ...services.field_security import audit_actor
from ...services.people_graph.storage import RunConflict
from ...services.investigation.repository import InvestigationMigrationRequiredError

router = APIRouter()
logger = logging.getLogger(__name__)


def service():
    return get_service_manager().event_graph_service


def failure(exc):
    if isinstance(exc, (RunConflict, InvestigationMigrationRequiredError)):
        return HTTPException(409, str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(422, "图谱筛选参数无效")
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    logger.exception("event graph operation failed")
    return HTTPException(503, "事件图谱暂不可读，已有版本保持不变")


def filters(request):
    params = dict(request.query_params)
    if len(params) != len(request.query_params.multi_items()):
        raise ValueError("筛选参数重复")
    params.pop("task_id", None)
    return ViewFilter.model_validate(params)


@router.get("/event-views")
async def live(task_id: str, request: Request):
    try:
        return await service().live(task_id, filters(request))
    except Exception as exc:
        raise failure(exc) from exc


@router.get("/event-views/detail")
async def live_detail(task_id: str, target_id: str, source_version: str):
    try:
        return await service().detail(task_id, target_id, source_version=source_version)
    except Exception as exc:
        raise failure(exc) from exc


@router.post("/event-analysis/runs", status_code=202)
async def start(payload: StartRequest, request: Request):
    try:
        return await service().start(payload, audit_actor(request, payload.requested_by))
    except Exception as exc:
        raise failure(exc) from exc


@router.get("/event-analysis/runs")
async def runs(task_id: str):
    try:
        return {"runs": await service().list_runs(task_id)}
    except Exception as exc:
        raise failure(exc) from exc


@router.get("/event-analysis/runs/{run_id}")
async def status(task_id: str, run_id: str):
    try:
        return await service().status(task_id, run_id)
    except Exception as exc:
        raise failure(exc) from exc


@router.get("/event-analysis/runs/{run_id}/graph")
async def graph(task_id: str, run_id: str, request: Request):
    try:
        return await service().graph(task_id, run_id, filters(request))
    except Exception as exc:
        raise failure(exc) from exc


@router.get("/event-analysis/runs/{run_id}/detail")
async def detail(task_id: str, run_id: str, target_id: str):
    try:
        return await service().detail(task_id, target_id, run_id=run_id)
    except Exception as exc:
        raise failure(exc) from exc


@router.post("/event-analysis/runs/{run_id}/cancel")
async def cancel(task_id: str, run_id: str):
    try:
        return await service().cancel(task_id, run_id)
    except Exception as exc:
        raise failure(exc) from exc
