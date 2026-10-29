"""Pipeline-tail auto report generation: seed + submit once, idempotent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from httpserver.services.forensic_report.auto_report import (
    auto_generate_pipeline_report,
)


class _FakeEvidence:
    def __init__(self, evidence=("file:/case/a.txt",)):
        self.calls: list[tuple[str, str]] = []
        self._evidence = [SimpleNamespace(evidence_key=key) for key in evidence]

    async def seed_analyzed_files(self, task_id: str, *, added_by: str):
        self.calls.append((task_id, added_by))
        return {"task_id": task_id, "seeded": 3}

    async def list(self, task_id: str):
        return list(self._evidence)


class _FakeAdmission:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def admit(self, task_id: str, *, requested_by: str, analysis_mode: str):
        assert analysis_mode == "evidence_only"
        self.calls.append((task_id, requested_by))
        return SimpleNamespace(generation_id="gen-1")


class _FakeExecutor:
    def __init__(self, has_version: bool = False, inflight: bool = False):
        self._has_version = has_version
        self._inflight = inflight
        self.submitted: list[str] = []

    def has_report_version(self, task_id: str, *, analysis_mode: str) -> bool:
        assert analysis_mode == "evidence_only"
        return self._has_version

    def has_inflight_generation(self, task_id: str) -> bool:
        return self._inflight

    async def submit(self, generation_id: str) -> None:
        self.submitted.append(generation_id)


def test_auto_report_seeds_then_submits():
    evidence, admission, executor = _FakeEvidence(), _FakeAdmission(), _FakeExecutor()

    summary = asyncio.run(auto_generate_pipeline_report(
        "T", evidence_service=evidence, admission=admission, executor=executor,
    ))

    assert evidence.calls == [("T", "pipeline")]
    assert admission.calls == [("T", "pipeline")]
    assert executor.submitted == ["gen-1"]
    assert summary == {
        "task_id": "T", "seeded": 3, "mobile_seeded": None, "generation_id": "gen-1",
        "copies": None,
    }


def test_ensure_evidence_copies_extracts_before_generation(monkeypatch):
    from httpserver.services.forensic_report.auto_report import ensure_evidence_copies

    class _Item:
        def __init__(self, key):
            self.evidence_key = key

    class _ListEvidence:
        async def list(self, task_id):
            return [_Item("file:/case/a.txt"), _Item("file:/case/话术/b.docx"), _Item("cluster:v1:1:X")]

    class _Backend:
        def __init__(self):
            self.patterns, self.polls = [], 0

        async def extract_files(self, task_id, paths):
            self.patterns.append(list(paths))
            return {"job_id": "ext-1"}

        async def get_extraction_status(self, job_id):
            self.polls += 1
            return {"status": "completed", "extracted_files": 2}

    monkeypatch.setattr("httpserver.services.forensic_report.auto_report.asyncio.sleep",
                        _noop_sleep)
    evidence, backend = _ListEvidence(), _Backend()

    summary = asyncio.run(ensure_evidence_copies(
        "T", cpp_backend=backend, evidence_service=evidence))

    assert backend.patterns == [["/case/a.txt", "/case/话术/b.docx"]]
    assert summary == {"task_id": "T", "extracted": 2}


async def _noop_sleep(_seconds):
    return None


def test_auto_report_pulls_copies_when_backend_present(monkeypatch):
    evidence, admission, executor = _FakeEvidence(), _FakeAdmission(), _FakeExecutor()

    async def _fake_copies(task_id, *, cpp_backend, evidence_service):
        assert evidence_service.calls == [("T", "pipeline")]
        return {"task_id": task_id, "extracted": 3}

    monkeypatch.setattr(
        "httpserver.services.forensic_report.auto_report.ensure_evidence_copies",
        _fake_copies,
    )

    summary = asyncio.run(auto_generate_pipeline_report(
        "T", evidence_service=evidence, admission=admission, executor=executor,
        cpp_backend=object(),
    ))

    assert summary["copies"] == {"task_id": "T", "extracted": 3}
    assert executor.submitted == ["gen-1"]


def test_auto_report_skips_when_report_exists():
    evidence, admission, executor = (
        _FakeEvidence(), _FakeAdmission(), _FakeExecutor(has_version=True),
    )

    summary = asyncio.run(auto_generate_pipeline_report(
        "T", evidence_service=evidence, admission=admission, executor=executor,
    ))

    assert summary == {"task_id": "T", "skipped": "report_exists"}
    assert evidence.calls == []
    assert admission.calls == []
    assert executor.submitted == []


def test_auto_report_propagates_seed_failure():
    class _BrokenEvidence:
        async def seed_analyzed_files(self, task_id, *, added_by):
            raise RuntimeError("store unavailable")

        async def list(self, task_id):
            raise RuntimeError("store unavailable")

    with pytest.raises(RuntimeError):
        asyncio.run(auto_generate_pipeline_report(
            "T",
            evidence_service=_BrokenEvidence(),
            admission=_FakeAdmission(),
            executor=_FakeExecutor(),
        ))


def test_auto_report_seeds_when_files_table_is_absent():
    """Logical mobile tasks have no `files` table; seeding must not abort."""
    evidence, admission, executor = _FakeEvidence(), _FakeAdmission(), _FakeExecutor()

    class _NoFilesEvidence(_FakeEvidence):
        async def seed_analyzed_files(self, task_id, *, added_by):
            self.calls.append((task_id, added_by))
            raise RuntimeError("task has no files database")

    service = _NoFilesEvidence()

    summary = asyncio.run(auto_generate_pipeline_report(
        "T", evidence_service=service, admission=admission, executor=executor,
    ))

    # The pre-seeded mobile evidence is what lets the report proceed.
    assert service.calls == [("T", "pipeline")]
    assert admission.calls == [("T", "pipeline")]
    assert summary["generation_id"] == "gen-1"


def test_auto_report_skips_when_no_reportable_evidence():
    """Logical mobile sources have no `files` table: nothing can be seeded.

    Admission would raise no_report_evidence and the C++ completion gate would
    then mark a successful analysis FAILED, so the tail must skip explicitly.
    """
    evidence = _FakeEvidence(evidence=())
    admission, executor = _FakeAdmission(), _FakeExecutor()

    summary = asyncio.run(auto_generate_pipeline_report(
        "T", evidence_service=evidence, admission=admission, executor=executor,
    ))

    assert summary["skipped"] == "no_reportable_evidence"
    assert evidence.calls == [("T", "pipeline")]
    assert admission.calls == []
    assert executor.submitted == []


def test_extraction_batches_preserve_exact_unicode_paths():
    from httpserver.services.forensic_report.auto_report import ensure_evidence_copies
    from unittest.mock import AsyncMock
    paths = [f"/{i}/" + "中文目录/" * 80 + "same.docx" for i in range(100)]
    evidence = SimpleNamespace(list=AsyncMock(return_value=[
        SimpleNamespace(evidence_key="file:" + path) for path in paths]))
    backend = SimpleNamespace(
        extract_files=AsyncMock(return_value={"job_id": "extract"}),
        get_extraction_status=AsyncMock(return_value={"status": "completed", "extracted_files": 1}))
    asyncio.run(ensure_evidence_copies("T", cpp_backend=backend, evidence_service=evidence))
    batches = [call.args[1] for call in backend.extract_files.await_args_list]
    assert len(batches) > 1
    assert sorted(path for batch in batches for path in batch) == sorted(paths)
    assert all(len(",".join(batch).encode()) <= 60000 for batch in batches)
