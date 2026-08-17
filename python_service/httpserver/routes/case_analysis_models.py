"""
Case-analysis routes — Pydantic request/response models.

Extracted from case_analysis.py so the per-domain endpoint modules under
case_analysis_endpoints/ can import the same types without circular imports.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field




# ------------------------------------------------------------------
# Request/Response Models
# ------------------------------------------------------------------

class CaseDescriptionRequest(BaseModel):
    """Request to save a case description."""
    task_id: str = Field(..., description="Task ID")
    case_description: str = Field(default="", description="案情描述")


class CaseDescriptionResponse(BaseModel):
    """Response for saving case description."""
    success: bool
    task_id: str
    message: str
    timestamp: str


class CaseAnalysisRequest(BaseModel):
    """Request to start full case analysis."""
    task_id: str = Field(..., description="Task ID owning the analysis target")
    # Deprecated: the target database is always resolved server-side from
    # task_id; a supplied value must exactly match that resolution.
    files_db_path: Optional[str] = Field(None, description="(deprecated) Path to _files.db; validated against the task-owned database")
    case_description: str = Field(default="", description="案情描述")
    max_filter_files: int = Field(default=200, ge=1, le=2000, description="Max files to filter")
    run_filtering: bool = Field(default=False, description="是否重新运行 LLM 文件筛选")
    report_only: bool = Field(default=False, description="仅基于已有证据重新生成报告，跳过文件提取/分析/图谱摄入")


class CaseAnalysisResponse(BaseModel):
    """Response for case analysis."""
    success: bool
    task_id: str
    job_id: str
    message: str
    timestamp: str


class CaseReportResponse(BaseModel):
    """Response containing the case report."""
    success: bool
    task_id: str
    case_description: Optional[str] = None
    report: Optional[str] = None
    filtered_files: Optional[List[str]] = None
    files_analyzed: Optional[int] = None
    generated_at: Optional[str] = None
    timestamp: str


class FilteredFilesResponse(BaseModel):
    """Response containing filtered files."""
    success: bool
    filtered_files: List[str]
    total_count: int
    timestamp: str


class AnalysisStatusResponse(BaseModel):
    """Response for analysis job status."""
    success: bool
    job_id: str
    status: str
    current_step: Optional[str] = None
    detail: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    timestamp: str


class ReanalyzeRequest(BaseModel):
    """Request to re-analyze files with user hints."""
    task_id: str = Field(..., description="Task ID")
    file_paths: List[str] = Field(..., min_length=1, description="要重新分析的文件路径列表")
    user_hint: str = Field(..., min_length=1, description="用户补充描述")
    # Deprecated: the persistence target is always resolved server-side from
    # task_id; a supplied value must exactly match that resolution.
    files_db_path: Optional[str] = Field(None, description="(deprecated) Path to _files.db; validated against the task-owned database")
    case_description: str = Field(default="", description="案情描述（可选，为空时自动获取）")


class ReanalyzeResponse(BaseModel):
    """Response for file re-analysis."""
    success: bool
    job_id: str
    file_count: int
    message: str
    timestamp: str


# ------------------------------------------------------------------
# Background job tracking
# ------------------------------------------------------------------
_analysis_jobs: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

