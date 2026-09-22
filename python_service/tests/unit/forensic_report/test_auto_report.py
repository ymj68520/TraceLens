"""Pipeline-tail auto report generation: seed + submit once, idempotent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from httpserver.services.forensic_report.auto_report import (
    auto_generate_pipeline_report,
)


class _FakeEvidence:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def seed_analyzed_files(self, task_id: str, *, added_by: str):
        self.calls.append((task_id, added_by))
        return {"task_id": task_id, "seeded": 3}


class _FakeAdmission:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def admit(self, task_id: str, *, requested_by: str):
        self.calls.append((task_id, requested_by))
        return SimpleNamespace(generation_id="gen-1")


class _FakeExecutor:
    def __init__(self, has_version: bool = False):
        self._has_version = has_version
        self.submitted: list[str] = []

    def has_report_version(self, task_id: str) -> bool:
        return self._has_version

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
        "task_id": "T", "seeded": 3, "generation_id": "gen-1",
    }


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

    with pytest.raises(RuntimeError):
        asyncio.run(auto_generate_pipeline_report(
            "T",
            evidence_service=_BrokenEvidence(),
            admission=_FakeAdmission(),
            executor=_FakeExecutor(),
        ))
