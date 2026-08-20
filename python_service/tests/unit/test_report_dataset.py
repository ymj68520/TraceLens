from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from httpserver.services.investigation_persistence import InvestigationPersistence
from httpserver.services.report_dataset import (
    CLAIM_EVIDENCE_LINK_MISSING,
    CLAIM_EVIDENCE_NOT_IN_REPORT_SET,
    EVIDENCE_RESOLUTION_FAILED,
    EVIDENCE_SNAPSHOT_NOT_FOUND,
    PINNED_ANALYSIS_NOT_ACCEPTED,
    READINESS_BLOCKED,
    READINESS_EXCLUDED,
    READINESS_REPORT_READY,
    ReportDatasetBuilder,
)


TASK_ID = "dataset-task"
EVIDENCE_KEY = "file:/docs/a.txt"


class FakeResolver:
    def __init__(self, task_id: str = TASK_ID):
        self.task_id = task_id
        self.calls: list[tuple[str, str]] = []
        self.values: dict[str, object] = {}

    async def resolve(self, task_id: str, evidence_key: str):
        self.calls.append((task_id, evidence_key))
        return self.values.get(
            evidence_key,
            {
                "task_id": self.task_id,
                "evidence_key": evidence_key,
                "evidence_type": "file",
                "title": "a.txt",
            },
        )


@pytest.fixture
def dataset_fixture(tmp_path: Path):
    task_dir = tmp_path / TASK_ID
    task_dir.mkdir()
    files_db = task_dir / "files.db"
    with sqlite3.connect(files_db) as conn:
        conn.execute("CREATE TABLE files (path TEXT)")

    persistence = InvestigationPersistence(task_dir / "investigation.db")
    resolver = FakeResolver()

    async def load_task(task_id: str):
        assert task_id == TASK_ID
        return {"id": task_id, "output_files_db": str(files_db)}

    builder = ReportDatasetBuilder(load_task, resolver)
    return persistence, resolver, builder


def _accepted_analysis(persistence: InvestigationPersistence, key: str = EVIDENCE_KEY):
    analysis = persistence.create_analysis_version(
        TASK_ID, key, "file", None, None, "model", "prompt-v1", "hash", [key]
    )
    persistence.mark_analysis_running(analysis["id"])
    persistence.complete_analysis(
        analysis["id"], "description", "summary", "valid", [], status="review_pending"
    )
    persistence.accept_analysis(TASK_ID, analysis["id"])
    return analysis


def _accepted_event_with_claim(
    persistence: InvestigationPersistence,
    *,
    evidence_refs: list[str] | None = None,
    claim_status: str = "accepted",
):
    event_id, _ = persistence.upsert_seed_event(
        TASK_ID, "cluster:v1:10:MODIFIED", "seed", "seed summary", 600, 620
    )
    persistence.set_event_review_status(TASK_ID, event_id, "confirmed")
    refs = [EVIDENCE_KEY] if evidence_refs is None else evidence_refs
    version = persistence.create_event_version(
        TASK_ID, event_id, None, [], refs, "event-hash", 0, False, "event-v1"
    )
    persistence.mark_event_version_running(TASK_ID, event_id, version["id"])
    persistence.complete_event_version_bundle(
        TASK_ID,
        event_id,
        version["id"],
        "accepted title",
        "accepted summary",
        refs,
        "valid",
        [],
        "review_pending",
        "model",
        [{
            "text": "accepted finding",
            "type": "fact",
            "status": claim_status,
            "grounding_status": "grounded",
            "kept_refs": refs,
            "relation": "supports",
            "origin": "evidence_derived",
        }],
    )
    persistence.accept_event_version(TASK_ID, event_id, version["id"])
    claim = persistence.list_event_claims(TASK_ID, event_id, version["id"])[0]
    return event_id, version, claim


def _snapshot(persistence: InvestigationPersistence, key: str = EVIDENCE_KEY):
    persistence.capture_snapshot_if_absent(
        TASK_ID, key, "file", {"path": "/docs/a.txt"}, "initial description",
        "initial summary", "md5", 4, 10, 20,
    )


@pytest.mark.asyncio
async def test_builds_valid_normalized_dataset_with_pinned_analysis(dataset_fixture):
    persistence, resolver, builder = dataset_fixture
    _snapshot(persistence)
    analysis = _accepted_analysis(persistence)
    event_id, version, claim = _accepted_event_with_claim(persistence)
    persistence.set_report_evidence(
        TASK_ID, EVIDENCE_KEY, "file", "main", analysis_id=analysis["id"]
    )

    dataset = await builder.build(TASK_ID)

    assert dataset.validation.status == "valid"
    assert dataset.report_dataset_hash == dataset.compute_hash()
    assert dataset.events[0].event_id == event_id
    assert dataset.events[0].event_version_id == version["id"]
    assert dataset.events[0].claims[0].claim_id == claim["id"]
    assert dataset.events[0].claims[0].readiness == READINESS_REPORT_READY
    assert dataset.events[0].claims[0].evidence_links[0].relation == "supports"
    assert dataset.report_evidence[0].snapshot["initial_summary"] == "initial summary"
    assert dataset.report_evidence[0].pinned_analysis["analysis_id"] == analysis["id"]
    assert resolver.calls == [(TASK_ID, EVIDENCE_KEY)]


@pytest.mark.asyncio
async def test_excluded_historical_and_unaccepted_claims_do_not_block(dataset_fixture):
    persistence, _, builder = dataset_fixture
    _snapshot(persistence)
    event_id, version, claim = _accepted_event_with_claim(persistence, claim_status="rejected")
    persistence.set_report_evidence(TASK_ID, EVIDENCE_KEY, "file", "main")

    dataset = await builder.build(TASK_ID)

    assert dataset.validation.status == "valid"
    assert dataset.events[0].claims[0].readiness == READINESS_EXCLUDED
    assert dataset.events[0].claims[0].exclusion_reasons
    assert dataset.events[0].claims[0].claim_id == claim["id"]

    # A second accepted semantic version leaves the first claim historical.
    persistence.invalidate_event_semantics(TASK_ID, event_id)
    second = persistence.create_event_version(
        TASK_ID, event_id, None, [], [EVIDENCE_KEY], "event-hash-2", 1, False, "event-v1"
    )
    persistence.mark_event_version_running(TASK_ID, event_id, second["id"])
    persistence.complete_event_version_bundle(
        TASK_ID, event_id, second["id"], "new", "new", [EVIDENCE_KEY],
        "valid", [], "review_pending", "model", [],
    )
    persistence.accept_event_version(TASK_ID, event_id, second["id"])
    dataset = await builder.build(TASK_ID)
    assert dataset.validation.status == "valid"
    assert dataset.events[0].claims[0].readiness == READINESS_EXCLUDED
    assert dataset.events[0].event_version_id == second["id"]


@pytest.mark.asyncio
async def test_missing_claim_provenance_is_blocked(dataset_fixture):
    persistence, _, builder = dataset_fixture
    _snapshot(persistence)
    _accepted_event_with_claim(persistence, evidence_refs=[])
    persistence.set_report_evidence(TASK_ID, EVIDENCE_KEY, "file", "main")

    dataset = await builder.build(TASK_ID)

    assert dataset.validation.status == "blocked"
    claim = dataset.events[0].claims[0]
    assert claim.readiness == READINESS_BLOCKED
    assert claim.validation_errors[0].code == CLAIM_EVIDENCE_LINK_MISSING


@pytest.mark.asyncio
async def test_claim_outside_report_set_is_blocked(dataset_fixture):
    persistence, _, builder = dataset_fixture
    _snapshot(persistence)
    _accepted_event_with_claim(persistence, evidence_refs=["file:/docs/other.txt"])
    persistence.set_report_evidence(TASK_ID, EVIDENCE_KEY, "file", "main")

    dataset = await builder.build(TASK_ID)

    assert dataset.validation.status == "blocked"
    claim = dataset.events[0].claims[0]
    assert claim.readiness == READINESS_BLOCKED
    codes = {error.code for error in claim.validation_errors}
    assert CLAIM_EVIDENCE_NOT_IN_REPORT_SET in codes


@pytest.mark.asyncio
async def test_snapshot_and_resolver_failures_are_reported_without_writes(dataset_fixture):
    persistence, resolver, builder = dataset_fixture
    _accepted_event_with_claim(persistence)
    persistence.set_report_evidence(TASK_ID, EVIDENCE_KEY, "file", "main")
    resolver.values[EVIDENCE_KEY] = None

    before = persistence.get_snapshot(TASK_ID, EVIDENCE_KEY)
    dataset = await builder.build(TASK_ID)
    after = persistence.get_snapshot(TASK_ID, EVIDENCE_KEY)

    assert dataset.validation.status == "blocked"
    assert {error.code for error in dataset.validation.errors} >= {
        EVIDENCE_RESOLUTION_FAILED,
        EVIDENCE_SNAPSHOT_NOT_FOUND,
    }
    assert before == after is None


@pytest.mark.asyncio
async def test_pinned_analysis_must_remain_accepted_and_exact(dataset_fixture):
    persistence, _, builder = dataset_fixture
    _snapshot(persistence)
    analysis = _accepted_analysis(persistence)
    _accepted_event_with_claim(persistence)
    persistence.set_report_evidence(
        TASK_ID, EVIDENCE_KEY, "file", "main", analysis_id=analysis["id"]
    )
    persistence.reject_analysis(TASK_ID, analysis["id"])

    dataset = await builder.build(TASK_ID)

    assert dataset.validation.status == "blocked"
    assert any(
        error.code == PINNED_ANALYSIS_NOT_ACCEPTED
        for error in dataset.validation.errors
    )


@pytest.mark.asyncio
async def test_canonical_content_and_hash_are_stable_across_builds(dataset_fixture):
    persistence, _, builder = dataset_fixture
    _snapshot(persistence)
    analysis = _accepted_analysis(persistence)
    _accepted_event_with_claim(persistence)
    persistence.set_report_evidence(
        TASK_ID, EVIDENCE_KEY, "file", "main", analysis_id=analysis["id"]
    )

    first = await builder.build(TASK_ID)
    await asyncio.sleep(0)
    second = await builder.build(TASK_ID)

    assert first.canonical_content_json() == second.canonical_content_json()
    assert first.report_dataset_hash == second.report_dataset_hash
    assert first.generated_at != ""
    assert "generated_at" not in first.canonical_content_dict()
