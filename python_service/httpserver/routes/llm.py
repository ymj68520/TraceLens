"""
LLM analysis routes — aggregator.

Single entry point used by main.py:
    app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])

The 9 endpoints are split by domain under ``llm_endpoints/``:
  - _analysis.py    analyze, analyze/file, analyze-event-cluster, batch, batch status
  - _management.py  models, status, toggle-relevance, toggle-cluster-relevance

Pydantic models live in ``llm_models.py``. Public surface unchanged.
"""

import logging
from fastapi import APIRouter

from .llm_endpoints import _analysis, _management
from .llm_models import (  # noqa: F401
    AnalyzeRequest,
    AnalyzeResponse,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
    BatchStatusResponse,
    ModelInfo,
    ModelsResponse,
    LLMStatusResponse,
    ToggleRelevanceRequest,
    EventClusterAnalyzeRequest,
    ToggleClusterRelevanceRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(_analysis.router)
router.include_router(_management.router)
