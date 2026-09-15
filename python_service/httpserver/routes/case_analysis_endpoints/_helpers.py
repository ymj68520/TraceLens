"""Shared helpers and module-level state for the case-analysis endpoint modules.

Lives here (rather than inside ``_case.py`` / ``_windows.py``) so both
sub-modules can import the same symbols without creating a cross-module
dependency. These helpers were split out of the original monolithic
``case_analysis.py`` (see commit d8e3a09).
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# In-memory registry of background analysis jobs, keyed by job_id.
# Each entry tracks: status, current_step, detail, progress, result.
_analysis_jobs: Dict[str, Dict[str, Any]] = {}


def get_case_analysis_service(service_manager):
    """Get or create a CaseAnalysisService instance (lazily cached on the manager)."""
    if not hasattr(service_manager, "_case_analysis_service"):
        from ...services.case_analysis import CaseAnalysisService

        svc = CaseAnalysisService(service_manager.settings)
        svc.set_llm_service(service_manager.llm_service)
        svc.set_cpp_backend(service_manager.cpp_backend)  # Inject C++ backend service
        # Inject Graphiti service if available (optional dependency).
        # Always inject it if it exists - let modules handle availability at runtime.
        try:
            graphiti_svc = service_manager.graphiti_service
            if graphiti_svc:
                svc.set_graphiti_service(graphiti_svc)
                logger.info("Graphiti service injected into case analysis service")
        except Exception as e:
            logger.warning(f"Could not inject Graphiti service: {e}")
            # Graphiti is optional; proceed without it
        service_manager._case_analysis_service = svc
    return service_manager._case_analysis_service


async def run_reanalyze_background(
    job_id: str,
    case_service,
    task_id: str,
    file_paths: List[str],
    user_hint: str,
    files_db_path: str,
    case_description: str,
):
    """Run file re-analysis in the background."""
    try:
        results = await case_service.reanalyze_files(
            task_id=task_id,
            file_paths=file_paths,
            user_hint=user_hint,
            files_db_path=files_db_path,
            case_description=case_description,
        )

        successful = sum(1 for r in results if r.get("success"))
        _analysis_jobs[job_id]["status"] = "completed"
        _analysis_jobs[job_id]["current_step"] = "完成"
        _analysis_jobs[job_id]["detail"] = f"重新分析完成: {successful}/{len(results)} 个文件成功"
        _analysis_jobs[job_id]["result"] = {
            "total": len(results),
            "successful": successful,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Background re-analysis failed: {e}", exc_info=True)
        _analysis_jobs[job_id]["status"] = "failed"
        _analysis_jobs[job_id]["current_step"] = "错误"
        _analysis_jobs[job_id]["detail"] = "case analysis job failed"


async def run_windows_analysis_background(
    job_id: str,
    case_service,
    task_id: str,
    windows_db_path: str,
    case_description: str,
):
    """Run Windows artifacts analysis in the background."""
    try:
        async def progress_cb(step, detail=None, extra=None):
            if extra is not None:
                current, total, artifact_info = step, detail, extra
                percentage = int((current / total) * 100) if total > 0 else 0
                _analysis_jobs[job_id]["current_step"] = "分析Windows痕迹"
                _analysis_jobs[job_id]["detail"] = f"正在分析第 {current}/{total} 个: {artifact_info}"
                _analysis_jobs[job_id]["progress"] = percentage
            else:
                _analysis_jobs[job_id]["current_step"] = step
                _analysis_jobs[job_id]["detail"] = detail or ""

        result = await case_service.analyze_windows_artifacts(
            task_id=task_id,
            windows_db_path=windows_db_path,
            case_description=case_description,
            progress_callback=progress_cb,
        )

        _analysis_jobs[job_id]["status"] = "completed"
        _analysis_jobs[job_id]["current_step"] = "完成"
        _analysis_jobs[job_id]["detail"] = "Windows痕迹分析已完成"
        _analysis_jobs[job_id]["result"] = {
            "artifacts_filtered": result.get("filter", {}).get("selected_count", 0),
            "artifacts_analyzed": result.get("analysis", {}).get("analyzed_count", 0),
        }
    except Exception as e:
        logger.error(f"Background Windows analysis failed: {e}", exc_info=True)
        _analysis_jobs[job_id]["status"] = "failed"
        _analysis_jobs[job_id]["current_step"] = "错误"
        _analysis_jobs[job_id]["detail"] = "case analysis job failed"
