"""Read-only, task-scoped source tracing for extracted graph relationships."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from ...services import get_service_manager
from ...services.evidence import EvidenceNotFoundError, EvidenceStoreError
from ...services.graphiti_relation_trace import (
    enrich_relationship_trace,
    read_task_source_file,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/source-file")
async def get_task_source_file(
    task_id: str = Query(min_length=1),
    evidence_key: str = Query(min_length=1),
):
    try:
        source = await read_task_source_file(
            task_id, evidence_key, get_service_manager()
        )
        return {"success": True, "source": source}
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid file evidence key") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="source evidence store unavailable") from exc
    except Exception as exc:
        logger.exception("task source file lookup failed for task %s", task_id)
        raise HTTPException(status_code=500, detail="task source file unavailable") from exc


@router.get("/relationships/{relationship_id}/trace")
async def get_relationship_trace(
    relationship_id: str,
    task_id: str = Query(min_length=1),
):
    try:
        UUID(relationship_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid relationship ID") from exc
    try:
        manager = get_service_manager()
        trace = await manager.graphiti_service.get_relationship_trace(
            task_id, relationship_id
        )
        if trace is None:
            raise HTTPException(status_code=404, detail="task relationship not found")
        enriched = await enrich_relationship_trace(trace, task_id, manager)
        return {"success": True, "task_id": task_id, "relationship": enriched}
    except HTTPException:
        raise
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task or source evidence not found") from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=503, detail="source evidence store unavailable") from exc
    except Exception as exc:
        logger.exception("relationship trace failed for task %s", task_id)
        raise HTTPException(status_code=500, detail="relationship trace unavailable") from exc
