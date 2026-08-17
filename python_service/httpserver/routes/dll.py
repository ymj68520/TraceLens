"""DLL analysis route for LLM-powered security assessment."""

import logging
import time
from datetime import datetime
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..services import get_service_manager
from ..services.dll.dll_analyzer import DLLAnalyzerClient
from ..services.dll.dll_markdown_generator import DLLMarkdownGenerator

logger = logging.getLogger(__name__)

router = APIRouter()


def normalize_threat_level(raw: str, numeric_score: int) -> str:
    """Normalize threat level string to consistent English values."""
    mapping = {
        "低": "low", "低风险": "low", "low": "low", "safe": "low",
        "中": "medium", "中风险": "medium", "medium": "medium",
        "高": "high", "高风险": "high", "high": "high",
        "严重": "critical", "critical": "critical",
    }
    key = raw.strip().lower()
    return mapping.get(key, "low" if numeric_score < 30
                       else "medium" if numeric_score < 60
                       else "high" if numeric_score < 80
                       else "critical")


class DLLAnalysisRequest(BaseModel):
    """Request model for DLL analysis."""
    task_id: str | None = Field(None, description="Task ID owning the persistence target (required to persist)")
    file_path: str = Field(..., description="Absolute path to DLL file")
    # Deprecated: the persistence target is always resolved server-side from
    # task_id; a supplied value must exactly match that resolution.
    files_db_path: str | None = Field(None, description="(deprecated) Optional _files.db path; validated against the task-owned database")
    prompt: str | None = Field(None, description="Custom prompt for LLM analysis")


class DLLAnalysisResponse(BaseModel):
    """Response model for DLL analysis."""
    success: bool
    analysis: Dict[str, Any]
    model_used: str
    tokens_used: int
    processing_time_ms: float
    timestamp: str


# LLM prompt template for DLL security analysis
DLL_SECURITY_ANALYSIS_PROMPT = """你是一位专业的恶意软件分析专家。请基于以下DLL文件的技术分析报告,提供安全评估。

{markdown_report}

参考威胁评分: {threat_score}/100

请提供以下分析:
1. **功能评估**: 该DLL的主要功能和可能用途
2. **威胁级别**: 基于以下标准评估:
   - 低风险 (0-30): 正常系统DLL,无异常特征
   - 中风险 (31-60): 存在可疑特征但可能是合法软件
   - 高风险 (61-80): 多个恶意指标,高度可疑
   - 严重 (81-100): 确认为恶意软件或非常可疑
3. **可疑行为**: 基于导入/导出函数的恶意行为推测
4. **MITRE ATT&CK**: 可能的攻击技术映射
5. **缓解建议**: 具体的处置建议

请以JSON格式返回:
{{
  "threat_level": "低/中/高/严重",
  "confidence": "高/中/低",
  "function_assessment": "...",
  "suspicious_behaviors": ["行为1", "行为2"],
  "mitre_attack_techniques": ["T1055", "T1012"],
  "iocs": ["可疑指标1", "可疑指标2"],
  "recommendations": "处置建议"
}}
"""


@router.post("/analyze/dll", response_model=DLLAnalysisResponse)
async def analyze_dll(
    request: DLLAnalysisRequest,
    settings: Settings = Depends(get_settings),
):
    """
    Analyze DLL/PE/ELF file with C++ parser + LLM security assessment.

    This endpoint:
    1. Calls C++ backend to parse binary structure
    2. Generates Markdown report from parsed data
    3. Sends report to LLM for security analysis
    4. Returns LLM analysis results
    """
    start_time = time.time()

    try:
        # Get LLM service and C++ backend URL from settings
        service_manager = get_service_manager()
        cpp_backend_url = getattr(settings, 'cpp_backend_url', 'http://localhost:8080')

        # Step 1: Analyze DLL via C++ backend
        logger.info(f"Analyzing DLL file: {request.file_path}")
        async with DLLAnalyzerClient(cpp_backend_url) as dll_client:
            dll_data = await dll_client.analyze_dll(request.file_path)

        # Step 2: Generate Markdown report
        markdown_report = DLLMarkdownGenerator().generate(dll_data)
        logger.debug(f"Generated Markdown report ({len(markdown_report)} chars)")

        # Extract C++ threat score for LLM context
        threat_score_from_cpp = dll_data.get("threat_score", 0)

        # Step 3: Call LLM for security analysis
        prompt = request.prompt or DLL_SECURITY_ANALYSIS_PROMPT
        formatted_prompt = prompt.format(
            markdown_report=markdown_report,
            threat_score=threat_score_from_cpp,
        )

        llm_result = await service_manager.llm_service.analyze(
            content=markdown_report,
            model_type="text",
            prompt=formatted_prompt,
            max_tokens=2000,
            temperature=0.3,
        )

        processing_time = (time.time() - start_time) * 1000
        analysis = llm_result.get("analysis", {})

        # Normalize threat_level to consistent English values
        threat_level_raw = analysis.get("threat_level", "")
        analysis["threat_level"] = normalize_threat_level(threat_level_raw, threat_score_from_cpp)

        # Step 4: Persist to the task-owned database (D2b). The target is
        # resolved server-side from task_id; a supplied files_db_path is a
        # deprecated exact-validated hint, never the authority.
        if request.files_db_path or request.task_id:
            from ..services import task_store

            if not request.task_id:
                raise HTTPException(
                    status_code=400,
                    detail="task_id is required to persist analysis results",
                )
            try:
                trusted_files_db = await task_store.resolve_task_files_db(
                    request.task_id
                )
                task_store.validate_legacy_db_path(
                    request.files_db_path, trusted_files_db
                )
            except task_store.TaskStoreError as exc:
                if exc.code == task_store.TASK_NOT_FOUND:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            try:
                description = analysis.get("description", "")
                summary = analysis.get("summary") or description[:200]
                keywords = analysis.get("keywords", [])
                keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)

                service_manager.llm_service.persist_to_files_db(
                    db_path=str(trusted_files_db),
                    file_path=request.file_path,
                    description=description,
                    summary=summary,
                    keywords=keywords_str,
                    model_used=llm_result.get("model", "unknown"),
                )
                logger.info(f"Persisted LLM analysis to task files database for task {request.task_id}")
            except Exception as e:
                logger.warning(f"Failed to persist to database: {e}")

        return DLLAnalysisResponse(
            success=True,
            analysis=analysis,
            model_used=llm_result.get("model", "unknown"),
            tokens_used=llm_result.get("tokens_used", 0),
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DLL analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="dll analysis failed"
        )
