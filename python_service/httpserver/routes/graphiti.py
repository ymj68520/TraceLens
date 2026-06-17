"""
Graphiti knowledge graph integration routes — aggregator.

This module is the single entry point used by main.py:

    app.include_router(graphiti.router, prefix="/api/graphiti", tags=["Graphiti"])

The 17 endpoints have been split by domain under ``graphiti_endpoints/``:
  - _ingest.py   POST /ingest, /ingest/file, /ingest/events
  - _jobs.py     GET /jobs, GET/DELETE /jobs/{id}
  - _migrate.py  POST /migrate/task/{id}, /migrate/deduplicate, /migrate/cleanup/{id}, GET /migrate/status/{id}
  - _query.py    POST /search, GET /entities, GET /relationships
  - _admin.py    GET /status, /tasks, DELETE /tasks/{id}, GET /graph

Pydantic request/response models live in ``graphiti_models.py`` so the
endpoint modules can import them without circular imports.

Public surface unchanged: the same ``router`` symbol is exported with all
endpoints attached at the same paths.
"""

import logging

from fastapi import APIRouter

from .graphiti_endpoints import _ingest, _jobs, _migrate, _query, _admin

# Re-export models for backward compatibility (some external code may import
# request/response classes from this module).
from .graphiti_models import (  # noqa: F401
    IngestionMode,
    IngestRequest,
    FileIngestRequest,
    EventSyncRequest,
    IngestionResponse,
    JobStatusResponse,
    IngestResponse,
    SearchRequest,
    SearchResult,
    SearchResponse,
    EntityListResponse,
    RelationshipListResponse,
    GraphitiStatusResponse,
    TaskGraphsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(_ingest.router)
router.include_router(_jobs.router)
router.include_router(_migrate.router)
router.include_router(_query.router)
router.include_router(_admin.router)
