"""
Case analysis routes — aggregator.

This module is the single entry point used by main.py:

    app.include_router(case_analysis.router, prefix="/api/llm", tags=["Case Analysis"])

The 9 endpoints have been split by domain under ``case_analysis_endpoints/``:
  - _case.py    case-description, case-analysis, reanalyze-files, status, report, filtered-files
  - _windows.py windows-analysis, windows-report, windows-export

Pydantic models live in ``case_analysis_models.py``. Public surface unchanged.
"""

import logging

from fastapi import APIRouter

from .case_analysis_endpoints import _case, _windows
from . import intelligence_report

# Re-export models for backward compatibility.
from .case_analysis_models import (  # noqa: F401
    AnalysisStatusResponse,
    CaseAnalysisRequest,
    CaseAnalysisResponse,
    CaseDescriptionRequest,
    CaseDescriptionResponse,
    CaseReportResponse,
    FilteredFilesResponse,
    ReanalyzeRequest,
    ReanalyzeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(_case.router)
router.include_router(_windows.router)
router.include_router(intelligence_report.router)
