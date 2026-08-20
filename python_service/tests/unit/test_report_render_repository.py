"""Tests for the task-local Phase 4D render candidate repository."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from httpserver.services.report_render_repository import (
    RENDER_FAILED,
    RENDER_PENDING_VALIDATION,
    RENDER_RUNNING,
    ReportRenderRepository,
)
from httpserver.services.report_rendering import SectionRenderInput, SectionRenderOutput


def _input(section_id="SEC-001"):
    return SectionRenderInput(
        dataset_hash="dataset-hash",
        citation_graph_hash="graph-hash",
        section_plan_hash="plan-hash",
        section_id=section_id,
        section_type="analysis.overview",
        title="概述",
    )


def _output(section_id="SEC-001"):
    return SectionRenderOutput(section_id=section_id, paragraphs=[])


def test_versions_are_scoped_to_task_and_section(tmp_path):
    repo = ReportRenderRepository(tmp_path / "investigation.db")
    one = repo.create_queued("task-a", "SEC-001", _input())
    two = repo.create_queued("task-a", "SEC-001", _input())
    other_section = repo.create_queued("task-a", "SEC-002", _input("SEC-002"))
    other_task = repo.create_queued("task-b", "SEC-001", _input())

    assert [one.render_version, two.render_version] == [1, 2]
    assert other_section.render_version == 1
    assert other_task.render_version == 1


def test_terminal_candidate_is_immutable(tmp_path):
    repo = ReportRenderRepository(tmp_path / "investigation.db")
    candidate = repo.create_queued("task-a", "SEC-001", _input())
    repo.mark_running(candidate.candidate_id)
    completed = repo.complete(
        candidate.candidate_id,
        status=RENDER_PENDING_VALIDATION,
        output=_output(),
        raw_llm_output='{"section_id":"SEC-001"}',
        model="test-model",
    )
    assert completed.status == RENDER_PENDING_VALIDATION
    assert completed.render_output_hash == _output().compute_hash()

    with pytest.raises(ValueError, match="immutable"):
        repo.mark_running(candidate.candidate_id)


def test_restart_recovery_marks_queued_and_running_failed(tmp_path):
    db_path = tmp_path / "investigation.db"
    repo = ReportRenderRepository(db_path)
    queued = repo.create_queued("task-a", "SEC-001", _input())
    running = repo.create_queued("task-a", "SEC-001", _input())
    repo.mark_running(running.candidate_id)

    recovered = ReportRenderRepository(db_path)
    assert recovered.get(queued.candidate_id).status == RENDER_FAILED
    assert recovered.get(running.candidate_id).status == RENDER_FAILED
    assert "service restart" in recovered.get(queued.candidate_id).error_message


def test_concurrent_version_allocation_has_no_duplicates(tmp_path):
    db_path = tmp_path / "investigation.db"
    errors = []
    versions = []
    lock = threading.Lock()

    def allocate():
        try:
            candidate = ReportRenderRepository(db_path).create_queued(
                "task-a", "SEC-001", _input()
            )
            with lock:
                versions.append(candidate.render_version)
        except Exception as exc:  # pragma: no cover - assertion below reports it
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=allocate) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(versions) == list(range(1, 9))


def test_failed_candidates_keep_provenance_and_list_unfinished_is_empty(tmp_path):
    repo = ReportRenderRepository(tmp_path / "investigation.db")
    candidate = repo.create_queued("task-a", "SEC-001", _input())
    repo.mark_running(candidate.candidate_id)
    failed = repo.fail(candidate.candidate_id, "transport failed")

    assert failed.status == RENDER_FAILED
    assert failed.render_input_hash == _input().compute_hash()
    assert failed.dataset_hash == "dataset-hash"
    assert repo.list_unfinished() == []


def test_cross_task_queries_are_isolated(tmp_path):
    repo = ReportRenderRepository(tmp_path / "investigation.db")
    one = repo.create_queued("task-a", "SEC-001", _input())
    two = repo.create_queued("task-b", "SEC-001", _input())

    assert repo.list_candidates("task-a") == [one]
    assert repo.list_candidates("task-b") == [two]
    assert repo.get_latest("task-a", "SEC-001").candidate_id == one.candidate_id


def test_user_version_is_not_changed(tmp_path):
    db_path = tmp_path / "investigation.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 37")
        conn.commit()

    ReportRenderRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
