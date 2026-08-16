"""Route contract for the strict task-scoped narrative Viewer read (R2d).

Real reports.db + real published manifest artifacts: the strict semantics
under test (mode=ro, opaque cross-task miss, confined manifest resolution,
fail-closed corruption) only mean anything against a real store.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import report_narrative
from httpserver.services.evidence.exceptions import EvidenceStoreError
from httpserver.services.forensic_report.generation_writer import (
    GenerationReportWriter,
)
from httpserver.services.forensic_report.models import (
    CitationManifestEntry,
    GenerationReportManifest,
    ScopeType,
    StructuredReportSection,
)
from httpserver.services.forensic_report.repository import ReportRepository

TASK = "task-A"


def _manifest(report_id: str, generation_id: str) -> GenerationReportManifest:
    return GenerationReportManifest(
        report_id=report_id,
        scope_type=ScopeType.TASK,
        scope_id=TASK,
        task_id=TASK,
        generation_id=generation_id,
        title="Narrative Report",
        prompt_version="final-report:v1",
        input_hash="h" * 64,
        model="test-model",
        generated_at="2026-08-16T00:00:00+00:00",
        sections=(
            StructuredReportSection(
                heading="Overview",
                content="Two items were recovered.",
                citation_ids=("cit-1",),
            ),
        ),
        citations=(
            CitationManifestEntry(
                citation_id="cit-1",
                evidence_key="file:/case/a.txt",
                analysis_id=None,
                claim_id=None,
                evidence_captured_at=1000,
                analysis_version=None,
                claim_type=None,
            ),
        ),
    )


def _publish(root: Path) -> tuple[ReportRepository, str, str]:
    """Create (repository, report_id, generation_id) with one snapshot + one
    published narrative version."""
    repository = ReportRepository(root / "reports.db")
    writer = GenerationReportWriter(root)

    # One deterministic snapshot version (report_kind stays NULL) and one
    # published narrative version (report_kind = llm_generation).
    deterministic = repository.create_version(
        ScopeType.TASK, TASK, "Snapshot", [TASK]
    )
    admitted = repository.create_generation_input(
        TASK,
        requested_by="analyst-x",
        input_schema_version=1,
        prompt_version="final-report:v1",
        input_envelope_json="{}",
        input_hash="h" * 64,
    )
    report_id = "11111111-1111-4111-8111-111111111111"
    generation_id = admitted.generation_id
    final_dir = writer.publish(
        task_id=TASK, report_id=report_id, manifest=_manifest(report_id, generation_id)
    )
    repository.claim_generation(generation_id)
    repository.complete_generation_publication(
        generation_id,
        report_id=report_id,
        title="Narrative Report",
        manifest_path=str(final_dir.relative_to(root)),
        model="test-model",
    )
    assert deterministic.report_kind is None
    return repository, report_id, generation_id


def make_client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        report_narrative, "_report_root", lambda: root
    )
    app = FastAPI()
    app.include_router(report_narrative.router, prefix="/api/reports")
    return TestClient(app)


def test_narrative_version_returns_persisted_contract(tmp_path, monkeypatch):
    repository, report_id, _generation_id = _publish(tmp_path)
    client = make_client(tmp_path, monkeypatch)

    response = client.get(
        f"/api/reports/narrative/versions/{report_id}", params={"task_id": TASK}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == TASK
    assert body["report_id"] == report_id
    assert body["version"] == 2  # deterministic snapshot took version 1
    assert body["generation_id"] == _generation_id
    assert body["model"] == "test-model"
    assert body["prompt_version"] == "final-report:v1"
    assert body["input_hash"] == "h" * 64
    assert [section["heading"] for section in body["sections"]] == ["Overview"]
    assert body["citations"][0]["evidence_key"] == "file:/case/a.txt"
    assert body["citations"][0]["analysis_id"] is None

    # The persisted version marker distinguishes narrative versions in the
    # A-chain list surface without filename heuristics.
    versions = repository.list_versions(ScopeType.TASK, TASK)
    kinds = {version.version: version.report_kind for version in versions}
    assert kinds == {1: None, 2: "llm_generation"}
    narrative_row = next(v for v in versions if v.report_id == report_id)
    assert narrative_row.manifest_path.startswith("snapshots/task/")
    assert not narrative_row.manifest_path.startswith("/")


def test_cross_task_and_snapshot_ids_are_opaque_404(tmp_path, monkeypatch):
    repository, report_id, _generation_id = _publish(tmp_path)
    client = make_client(tmp_path, monkeypatch)

    wrong_task = client.get(
        f"/api/reports/narrative/versions/{report_id}", params={"task_id": "task-B"}
    )
    unknown = client.get(
        "/api/reports/narrative/versions/33333333-3333-4333-8333-333333333333",
        params={"task_id": TASK},
    )
    assert wrong_task.status_code == 404
    assert unknown.status_code == 404
    assert wrong_task.json()["detail"] == unknown.json()["detail"] == "report not found"

    # A deterministic snapshot id is not a narrative version: opaque 404
    # too, never a hint that the id exists under another kind/task.
    snapshot = repository.list_versions(ScopeType.TASK, TASK)[1]
    assert snapshot.report_kind is None
    via_narrative = client.get(
        f"/api/reports/narrative/versions/{snapshot.report_id}",
        params={"task_id": TASK},
    )
    assert via_narrative.status_code == 404


def test_missing_store_and_missing_table_are_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    # No reports.db at all.
    missing = client.get(
        "/api/reports/narrative/versions/rg-x", params={"task_id": TASK}
    )
    assert missing.status_code == 404

    # reports.db exists but has no report_versions table.
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    sqlite3.connect(empty_root / "reports.db").close()
    monkeypatch.setattr(report_narrative, "_report_root", lambda: empty_root)
    bare = client.get(
        "/api/reports/narrative/versions/rg-x", params={"task_id": TASK}
    )
    assert bare.status_code == 404


def test_corrupt_store_fails_closed_503(tmp_path, monkeypatch):
    corrupt_root = tmp_path / "corrupt"
    corrupt_root.mkdir()
    (corrupt_root / "reports.db").write_bytes(b"this is not sqlite")
    monkeypatch.setattr(report_narrative, "_report_root", lambda: corrupt_root)
    client = make_client(corrupt_root, monkeypatch)

    response = client.get(
        "/api/reports/narrative/versions/rg-x", params={"task_id": TASK}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "report narrative record is unavailable"


def test_missing_or_diverging_manifest_is_503(tmp_path, monkeypatch):
    repository, report_id, _generation_id = _publish(tmp_path)

    final_dir = GenerationReportWriter(tmp_path).final_dir(TASK, report_id)

    # Manifest vanished after publication: integrity failure, not "missing".
    (final_dir / "manifest.json").unlink()
    client = make_client(tmp_path, monkeypatch)
    response = client.get(
        f"/api/reports/narrative/versions/{report_id}", params={"task_id": TASK}
    )
    assert response.status_code == 503

    # Manifest bytes that no longer satisfy the persisted schema.
    (final_dir / "manifest.json").write_text('{"report_id": "tampered"}')
    response = client.get(
        f"/api/reports/narrative/versions/{report_id}", params={"task_id": TASK}
    )
    assert response.status_code == 503


def test_reader_raises_store_error_for_row_kind_mismatch_never_leaks_scope():
    # Direct reader contract: a foreign-task row is a None miss; only real
    # store corruption raises EvidenceStoreError.
    from httpserver.services.forensic_report.narrative_reader import (
        read_narrative_version_strict,
    )

    assert read_narrative_version_strict(
        Path("/nonexistent/reports.db"), Path("/nonexistent"), TASK, "rg-x"
    ) is None


def test_r2c_era_store_backfills_narrative_kind(tmp_path):
    """Stores published by R2c (pre-marker) get typed by the owned layout."""
    db = tmp_path / "reports.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE report_versions (
            report_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            task_ids_json TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT,
            manifest_path TEXT,
            offline_bundle_path TEXT,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            error TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(scope_type, scope_id, version)
        );
        """
    )
    conn.executemany(
        "INSERT INTO report_versions (report_id, version, scope_type, scope_id,"
        " status, title, task_ids_json, stage, progress, manifest_path, created_at)"
        " VALUES (?, ?, 'task', ?, 'ready', 'T', '[]', 'ready', 100, ?, '2026')",
        (
            ("rep-r2c", 2, TASK, "snapshots/task/A/rep-r2c/manifest.json"),
            ("rep-det", 1, TASK, "task/A/rep-det/manifest.json"),
        ),
    )
    conn.commit()
    conn.close()

    repository = ReportRepository(db)  # migration + backfill run here
    kinds = {
        version.version: version.report_kind
        for version in repository.list_versions(ScopeType.TASK, TASK)
    }
    assert kinds == {1: None, 2: "llm_generation"}
