"""
Unit tests for the Path-A episode completion gate (honest job terminal state).

A FULL ingestion job that produced zero successful episodes must not report
COMPLETED — the C++ FINALIZING gate treats a COMPLETED job as a successful
ingestion, so 0/N all-failed runs used to silently pass the gate and leave
the knowledge graph empty (observed 2026-10-15: LM Studio response_format
rejection gave 0/12 while the job stayed COMPLETED).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from httpserver.services.ingestion_job_parts._worker import IngestionJobWorkerMixin


def test_all_episodes_failed_is_a_gate_error():
    stats = {"episodes_successful": 0, "episodes_total": 12,
             "episodes_failed": 12, "error": None}
    msg = IngestionJobWorkerMixin._episode_gate_error(stats)
    assert msg is not None
    assert "0/12" in msg


def test_hard_error_with_nothing_attempted_is_a_gate_error():
    stats = {"episodes_successful": 0, "episodes_total": 0,
             "episodes_failed": 0, "error": "graphiti_service unavailable"}
    msg = IngestionJobWorkerMixin._episode_gate_error(stats)
    assert msg is not None
    assert "graphiti_service unavailable" in msg


def test_partial_success_stays_completed():
    stats = {"episodes_successful": 9, "episodes_total": 12,
             "episodes_failed": 3, "error": None}
    assert IngestionJobWorkerMixin._episode_gate_error(stats) is None


def test_legitimate_empty_state_stays_completed():
    stats = {"episodes_successful": 0, "episodes_total": 0,
             "episodes_failed": 0, "error": "no analyzed descriptions to ingest"}
    assert IngestionJobWorkerMixin._episode_gate_error(stats) is None
    assert IngestionJobWorkerMixin._episode_gate_error({"episodes_successful": 0,
                                                   "episodes_total": 0,
                                                   "episodes_failed": 0,
                                                   "error": None}) is None
