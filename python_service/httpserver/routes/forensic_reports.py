"""Versioned forensic report snapshot HTTP routes."""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import get_service_manager
from ..services.forensic_report.service import ReportServiceUnavailable
from ..services.forensic_report.models import ReportVersion, ScopeType

router = APIRouter()

_RESOURCE_INTEGRITY_DETAIL = "report resource integrity error"
_SEARCH_INTEGRITY_DETAIL = "report search index is unavailable"


class CreateReportRequest(BaseModel):
    scope_type: ScopeType
    scope_id: str = Field(min_length=1)


class SearchResponse(BaseModel):
    total: int
    offset: int
    limit: int
    hits: list[dict[str, Any]]


def get_report_service():
    """Resolve the ready report service through the service manager."""
    try:
        return get_service_manager().forensic_report_service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503, detail="report service is unavailable"
        ) from exc


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="report not found")


def _not_ready() -> HTTPException:
    return HTTPException(status_code=409, detail="report is not ready")


def _resource_integrity_error() -> HTTPException:
    return HTTPException(status_code=500, detail=_RESOURCE_INTEGRITY_DETAIL)


def _search_integrity_error() -> HTTPException:
    return HTTPException(status_code=500, detail=_SEARCH_INTEGRITY_DETAIL)


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _file_response(loader: Any, *args: Any) -> Response:
    try:
        path = Path(loader(*args))
    except KeyError as exc:
        raise _not_found() from exc
    except RuntimeError as exc:
        raise _not_ready() from exc
    except (TypeError, ValueError, OSError) as exc:
        raise _resource_integrity_error() from exc

    try:
        payload = path.read_bytes()
        json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (
        RecursionError,
        ValueError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise _resource_integrity_error() from exc
    return Response(content=payload, media_type="application/json")


def _serialize_hit(hit: Any) -> dict[str, Any]:
    if isinstance(hit, Mapping):
        return dict(hit)
    model_dump = getattr(hit, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if hasattr(hit, "__dict__"):
        return dict(vars(hit))
    raise TypeError("unsupported report search hit")


@router.post("", response_model=ReportVersion, status_code=202)
async def create_report(
    request: CreateReportRequest,
    service: Any = Depends(get_report_service),
) -> ReportVersion:
    try:
        return await service.start(request.scope_type, request.scope_id)
    except ReportServiceUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="report service is unavailable"
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="report scope not found") from exc
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501, detail="report scope type is not supported"
        ) from exc


@router.get("", response_model=list[ReportVersion])
def list_reports(
    scope_type: Annotated[ScopeType, Query(...)],
    scope_id: Annotated[str, Query(min_length=1)],
    service: Any = Depends(get_report_service),
) -> list[ReportVersion]:
    return service.list_versions(scope_type, scope_id)


@router.get("/{report_id}/status", response_model=ReportVersion)
def report_status(report_id: str, service: Any = Depends(get_report_service)) -> ReportVersion:
    version = service.get_status(report_id)
    if version is None:
        raise _not_found()
    return version


@router.get("/{report_id}/manifest")
def manifest(report_id: str, service: Any = Depends(get_report_service)) -> Response:
    return _file_response(service.get_manifest_path, report_id)


@router.get("/{report_id}/categories/{category_id}/pages/{page}")
def category_page(
    report_id: str,
    category_id: str,
    page: Annotated[int, FastAPIPath(ge=1)],
    service: Any = Depends(get_report_service),
) -> Response:
    return _file_response(service.get_page_path, report_id, category_id, page)


@router.get("/{report_id}/search", response_model=SearchResponse)
def search(
    report_id: str,
    q: Annotated[str, Query(min_length=1)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    service: Any = Depends(get_report_service),
) -> SearchResponse:
    try:
        total, hits = service.search(report_id, q, offset, limit)
        serialized_hits = [_serialize_hit(hit) for hit in hits]
    except KeyError as exc:
        raise _not_found() from exc
    except RuntimeError as exc:
        raise _not_ready() from exc
    except (FileNotFoundError, ValueError, OSError, sqlite3.Error, TypeError) as exc:
        raise _search_integrity_error() from exc
    return SearchResponse(
        total=total,
        offset=offset,
        limit=limit,
        hits=serialized_hits,
    )
