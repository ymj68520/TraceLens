"""Unified communication graph / timeline / edge-drilldown routes.

Mounted at ``/api/comm``. Every endpoint is a GET read surface:

  GET /api/comm/graph?task_id=...
  GET /api/comm/timeline?task_id=...
  GET /api/comm/edge?task_id=...&source=...&target=...&relation=...
  GET /api/comm/datasets?task_id=...

Imports are named explicitly (``wechat_imports`` / ``qq_imports``, each a
repeated query parameter) because an import is not yet linked to a task.
``dataset=wx_<id>`` is accepted as a shorthand so the existing UI vocabulary
keeps working.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from ..services import get_service_manager
from ..services.comm_graph import CommGraphService, GraphFilters
from ..services.comm_graph.datasets import DatasetResolutionError
from ..services.comm_graph.timeline import build_timeline, edge_detail

logger = logging.getLogger(__name__)
router = APIRouter()

_IMPORT_PREFIX = {"wx_": "wechat", "qq_": "qq"}


def _split_dataset_tokens(tokens: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Separate ``wx_``/``qq_`` shorthands from plain import ids and names."""
    wechat: list[str] = []
    qq: list[str] = []
    datasets: list[str] = []
    for token in tokens:
        value = token.strip()
        if not value:
            continue
        matched = False
        for prefix, kind in _IMPORT_PREFIX.items():
            if value.startswith(prefix):
                (wechat if kind == "wechat" else qq).append(value[len(prefix):])
                matched = True
                break
        if not matched:
            datasets.append(value)
    return wechat, qq, datasets


def _service() -> CommGraphService:
    manager = get_service_manager()
    return CommGraphService(manager.cpp_backend)


async def _resolve(task_id: str, wechat: list[str], qq: list[str]):
    service = _service()
    refs, unavailable = await service.resolve(task_id, wechat_imports=wechat, qq_imports=qq)
    if not refs and not unavailable:
        raise HTTPException(status_code=404,
                            detail="该任务没有可读的通讯数据源（无 android.db）")
    return service, refs, unavailable


@router.get("/graph")
async def comm_graph(
    task_id: str = Query(..., min_length=1, max_length=256),
    wechat_imports: Annotated[list[str], Query()] = [],
    qq_imports: Annotated[list[str], Query()] = [],
    dataset: Annotated[list[str], Query()] = [],
    start_time: int | None = Query(None, ge=0),
    end_time: int | None = Query(None, ge=0),
    min_edge_weight: int = Query(1, ge=1, le=1_000_000),
    include_union: bool = Query(True),
    max_nodes: int = Query(500, ge=1, le=2000),
    max_edges: int = Query(2000, ge=1, le=10000),
    communities: bool = Query(True),
):
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(status_code=422, detail="开始时间不能晚于结束时间")
    shorthand_wechat, shorthand_qq, explicit = _split_dataset_tokens(dataset)
    wechat = list(dict.fromkeys([*wechat_imports, *shorthand_wechat]))
    qq = list(dict.fromkeys([*qq_imports, *shorthand_qq]))
    try:
        service, refs, unavailable = await _resolve(task_id, wechat, qq)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except DatasetResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filters = GraphFilters(
        start_time=start_time, end_time=end_time, min_edge_weight=min_edge_weight,
        include_union=include_union, max_nodes=max_nodes, max_edges=max_edges,
        communities=communities, datasets=explicit,
    )
    try:
        graph = await asyncio.to_thread(service.build_graph, refs, filters,
                                        unavailable=unavailable)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "task_id": task_id, **graph.model_dump()}


@router.get("/timeline")
async def comm_timeline(
    task_id: str = Query(..., min_length=1, max_length=256),
    wechat_imports: Annotated[list[str], Query()] = [],
    qq_imports: Annotated[list[str], Query()] = [],
    dataset: Annotated[list[str], Query()] = [],
    start_time: int | None = Query(None, ge=0),
    end_time: int | None = Query(None, ge=0),
    kind: Annotated[list[str], Query()] = [],
    limit: int = Query(200, ge=1, le=500),
):
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(status_code=422, detail="开始时间不能晚于结束时间")
    valid_kinds = {"call", "sms", "im_private", "im_group", "im_artifact"}
    kinds = set(kind)
    unknown = kinds - valid_kinds
    if unknown:
        raise HTTPException(status_code=422,
                            detail=f"不支持的记录类型: {sorted(unknown)}")
    shorthand_wechat, shorthand_qq, explicit = _split_dataset_tokens(dataset)
    wechat = list(dict.fromkeys([*wechat_imports, *shorthand_wechat]))
    qq = list(dict.fromkeys([*qq_imports, *shorthand_qq]))
    try:
        _, refs, unavailable = await _resolve(task_id, wechat, qq)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except DatasetResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = await asyncio.to_thread(
            build_timeline, refs, start_time=start_time, end_time=end_time,
            kinds=kinds or None, datasets=set(explicit) or None, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["coverage"]["unavailable_datasets"] = unavailable
    return {"success": True, "task_id": task_id, **result}


@router.get("/edge")
async def comm_edge_detail(
    task_id: str = Query(..., min_length=1, max_length=256),
    source: str = Query(..., min_length=1, max_length=128),
    target: str = Query(..., min_length=1, max_length=128),
    relation: str = Query("", max_length=32),
    wechat_imports: Annotated[list[str], Query()] = [],
    qq_imports: Annotated[list[str], Query()] = [],
    dataset: Annotated[list[str], Query()] = [],
):
    valid_relations = {"", "call", "sms", "im_private", "im_group", "im_artifact",
                       "group_member"}
    if relation not in valid_relations:
        raise HTTPException(status_code=422, detail="不支持的关系类型")
    shorthand_wechat, shorthand_qq, _explicit = _split_dataset_tokens(dataset)
    wechat = list(dict.fromkeys([*wechat_imports, *shorthand_wechat]))
    qq = list(dict.fromkeys([*qq_imports, *shorthand_qq]))
    try:
        _, refs, _unavailable = await _resolve(task_id, wechat, qq)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except DatasetResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = await asyncio.to_thread(
        edge_detail, refs, source=source, target=target, relation=relation)
    return {"success": True, "task_id": task_id, **detail}


@router.get("/datasets")
async def comm_datasets(
    task_id: str = Query(..., min_length=1, max_length=256),
    wechat_imports: Annotated[list[str], Query()] = [],
    qq_imports: Annotated[list[str], Query()] = [],
):
    try:
        _, refs, unavailable = await _resolve(task_id, wechat_imports, qq_imports)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except DatasetResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "success": True,
        "task_id": task_id,
        "datasets": [
            {"dataset_id": ref.dataset_id, "kind": ref.kind, "id": ref.id,
             "label": ref.label}
            for ref in refs
        ],
        "unavailable": unavailable,
    }
