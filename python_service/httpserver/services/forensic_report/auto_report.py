"""Pipeline-tail auto report generation (initial analysis flow, last step).

After a task's knowledge-graph ingestion job completes — the final stage of
the initial analysis pipeline — the flow ends by producing the final
report itself: pipeline-covered analyzed files are admitted as main
evidence (idempotent, never overrides analyst judgments) and one
final-report generation is submitted. Entirely server-side; no HTTP route
and no manual trigger.

Skipped when the task already has any report version, so re-ingestion or
manual generations are never duplicated. Raises on failure — the caller
(the ingestion manager's fire-and-forget tail callback) owns logging.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

AUTO_REPORT_REQUESTER = "pipeline"


async def auto_generate_pipeline_report(
    task_id: str,
    *,
    evidence_service,
    admission,
    executor,
) -> dict:
    """Seed adopted evidence and submit the final report for a finished task.

    Args:
        evidence_service: ReportEvidenceService (seed_analyzed_files).
        admission: ReportGenerationAdmissionService (freezes the envelope).
        executor: ReportGenerationExecutor (submits the generation).

    Returns a small summary dict for logging; raises on failure.
    """
    if executor.has_report_version(task_id):
        logger.info(
            "Task %s already has a report version; auto generation skipped",
            task_id,
        )
        return {"task_id": task_id, "skipped": "report_exists"}

    seed = await evidence_service.seed_analyzed_files(
        task_id, added_by=AUTO_REPORT_REQUESTER
    )
    generation = await admission.admit(
        task_id, requested_by=AUTO_REPORT_REQUESTER
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
        "generation_id": generation.generation_id,
    }


__all__ = ["AUTO_REPORT_REQUESTER", "auto_generate_pipeline_report"]
