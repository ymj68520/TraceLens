"""Tests for independent Phase 4E validation persistence."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from httpserver.services.report_final_validation import (
    FINAL_FAILED,
    FINAL_VALID,
    FinalValidationResult,
)
from httpserver.services.report_render_repository import (
    RENDER_PENDING_VALIDATION,
    ReportRenderRepository,
)
from httpserver.services.report_rendering import SectionRenderInput, SectionRenderOutput
from httpserver.services.report_validation_repository import ReportValidationRepository


def _input(section_id="SEC-001"):
    return SectionRenderInput(
        dataset_hash="dataset-hash",
        citation_graph_hash="graph-hash",
        section_plan_hash="plan-hash",
        section_id=section_id,
        section_type="analysis.overview",
        title="概述",
    )


def _candidate(tmp_path):
    render_repo = ReportRenderRepository(tmp_path / "investigation.db")
    candidate = render_repo.create_queued("task-a", "SEC-001", _input())
    render_repo.mark_running(candidate.candidate_id)
    return render_repo.complete(
        candidate.candidate_id,
        status=RENDER_PENDING_VALIDATION,
        output=SectionRenderOutput(section_id="SEC-001"),
    )


def test_versions_and_history_are_scoped_per_candidate(tmp_path):
    candidate = _candidate(tmp_path)
    repo = ReportValidationRepository(tmp_path / "investigation.db")
    first = repo.create_queued("task-a", candidate)
    repo.mark_running(first.validation_id)
    first = repo.complete(
        first.validation_id,
        result=FinalValidationResult(status=FINAL_VALID),
    )
    second = repo.create_queued("task-a", candidate)

    assert first.validation_version == 1
    assert second.validation_version == 2
    assert repo.get_latest("task-a", candidate.candidate_id).validation_id == second.validation_id
    assert repo.get_latest_valid("task-a", candidate.candidate_id).validation_id == first.validation_id


def test_terminal_validation_is_immutable(tmp_path):
    candidate = _candidate(tmp_path)
    repo = ReportValidationRepository(tmp_path / "investigation.db")
    validation = repo.create_queued("task-a", candidate)
    repo.mark_running(validation.validation_id)
    repo.complete(validation.validation_id, result=FinalValidationResult(status=FINAL_VALID))

    with pytest.raises(ValueError, match="immutable"):
        repo.mark_running(validation.validation_id)


def test_restart_recovery_marks_queued_and_running_failed(tmp_path):
    candidate = _candidate(tmp_path)
    repo = ReportValidationRepository(tmp_path / "investigation.db")
    queued = repo.create_queued("task-a", candidate)
    running = repo.create_queued("task-a", candidate)
    repo.mark_running(running.validation_id)

    recovered = ReportValidationRepository(tmp_path / "investigation.db")
    assert recovered.get(queued.validation_id).status == FINAL_FAILED
    assert recovered.get(running.validation_id).status == FINAL_FAILED


def test_concurrent_validation_version_allocation(tmp_path):
    candidate = _candidate(tmp_path)
    db_path = tmp_path / "investigation.db"
    versions = []
    errors = []
    lock = threading.Lock()

    def allocate():
        try:
            validation = ReportValidationRepository(db_path).create_queued(
                "task-a", candidate
            )
            with lock:
                versions.append(validation.validation_version)
        except Exception as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=allocate) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(versions) == list(range(1, 9))


def test_user_version_and_candidates_are_unchanged(tmp_path):
    candidate = _candidate(tmp_path)
    db_path = tmp_path / "investigation.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 37")
        before = conn.execute(
            "SELECT candidate_id, status, structured_output_json, render_output_hash "
            "FROM section_render_candidates WHERE candidate_id = ?",
            (candidate.candidate_id,),
        ).fetchone()
        conn.commit()

    repo = ReportValidationRepository(db_path)
    validation = repo.create_queued("task-a", candidate)
    repo.mark_running(validation.validation_id)
    repo.complete(validation.validation_id, result=FinalValidationResult(status=FINAL_VALID))

    with sqlite3.connect(db_path) as conn:
        after = conn.execute(
            "SELECT candidate_id, status, structured_output_json, render_output_hash "
            "FROM section_render_candidates WHERE candidate_id = ?",
            (candidate.candidate_id,),
        ).fetchone()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
    assert after == before
