"""Pipeline-tail auto report generation (initial analysis flow, last step).

After a task's knowledge-graph ingestion job completes — the final stage of
the initial analysis pipeline — the flow ends by producing the final
report itself: pipeline-covered analyzed files are admitted as main
evidence (idempotent, never overrides analyst judgments) and one
final-report generation is submitted.

Skipped when the task already has any report version, so re-ingestion or
manual generations are never duplicated. Raises on failure — the caller
owns logging (the ingestion manager's fire-and-forget tail callback logs;
the synchronous pipeline-tail route surfaces the failure into the task
completion gate).
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

AUTO_REPORT_REQUESTER = "pipeline"
COPY_EXTRACTION_TIMEOUT_S = 1800


async def ensure_evidence_copies(task_id: str, *, cpp_backend, evidence_service,
                                 timeout_s: int = COPY_EXTRACTION_TIMEOUT_S) -> dict:
    """Extract report-evidence files so the frozen sources are readable.

    The first-stage report reads actual file content; pipeline analysis
    reads through TSK without keeping copies, so without this step the
    generation fails with ``neutral_sources_unavailable``. Best effort: a
    failure is returned, not raised — the admission step then fails honestly
    with the same terminal error as before this helper existed.
    """
    items = await evidence_service.list(task_id)
    paths = sorted({item.evidence_key[5:] for item in items
                    if item.evidence_key.startswith("file:") and len(item.evidence_key) > 5})
    if not paths:
        return {"task_id": task_id, "skipped": "no_file_evidence"}
    if len(",".join(paths)) > 60000:
        # Name-mode wildcards also match on plain file names; fall back to
        # basenames when the joined path list would exceed the request budget.
        paths = sorted({path.split("/")[-1] for path in paths})
    job = await cpp_backend.extract_files(task_id, paths)
    job_id = (job or {}).get("job_id")
    if not job_id:
        return {"task_id": task_id, "extracted": None, "error": "extraction_trigger_failed"}
    waited = 0.0
    status: dict = {}
    while waited < timeout_s:
        await asyncio.sleep(10)
        waited += 10
        try:
            status = await cpp_backend.get_extraction_status(job_id)
        except Exception:
            continue
        if str(status.get("status")) in ("completed", "failed"):
            break
    if str(status.get("status")) != "completed":
        return {"task_id": task_id, "extracted": None,
                "error": f"extraction_{status.get('status') or 'timeout'}"}
    return {"task_id": task_id, "extracted": status.get("extracted_files")}


async def auto_generate_pipeline_report(
    task_id: str,
    *,
    evidence_service,
    admission,
    executor,
    cpp_backend=None,
) -> dict:
    """Seed adopted evidence and submit the final report for a finished task.

    Args:
        evidence_service: ReportEvidenceService (seed_analyzed_files).
        admission: ReportGenerationAdmissionService (freezes the envelope).
        executor: ReportGenerationExecutor (submits the generation).
        cpp_backend: optional C++ backend used to pull extraction copies for
            the evidence files before the envelope freezes source text.

    Returns a small summary dict for logging; raises on failure.
    """
    if executor.has_report_version(task_id, analysis_mode="evidence_only"):
        logger.info(
            "Task %s already has a report version; auto generation skipped",
            task_id,
        )
        return {"task_id": task_id, "skipped": "report_exists"}

    copy_summary = None
    if cpp_backend is not None:
        try:
            copy_summary = await ensure_evidence_copies(
                task_id, cpp_backend=cpp_backend, evidence_service=evidence_service)
        except Exception as exc:
            logger.warning(
                "Evidence copy extraction failed for task %s: %s", task_id, exc)
            copy_summary = {"task_id": task_id, "error": str(exc)}
        if copy_summary.get("error"):
            logger.warning(
                "Evidence copies unavailable for task %s: %s",
                task_id, copy_summary["error"])

    seed = await evidence_service.seed_analyzed_files(
        task_id, added_by=AUTO_REPORT_REQUESTER
    )
    generation = await admission.admit(
        task_id, requested_by=AUTO_REPORT_REQUESTER, analysis_mode="evidence_only",
    )
    await executor.submit(generation.generation_id)
    logger.info(
        "Auto report generation submitted for task %s: generation=%s",
        task_id,
        generation.generation_id,
    )
    return {
        "task_id": task_id,
        "seeded": seed.get("seeded"),
        "copies": copy_summary,
        "generation_id": generation.generation_id,
    }


__all__ = ["AUTO_REPORT_REQUESTER", "auto_generate_pipeline_report", "ensure_evidence_copies"]
