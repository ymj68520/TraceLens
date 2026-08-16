"""Phase R2b: frozen report generation admission (§26 matrix).

Admission assembles the LLM-generation input ONLY from R1 Report Evidence:
exact immutable snapshots plus (when bound) the exact accepted analysis with
its persisted claims. Original-only rows keep ``analysis_id = NULL`` -- there
is never a latest-accepted fallback; excluded rows never enter the envelope;
the whole input is read in one read transaction and frozen by SHA-256 hash on
an insert-only row in reports.db.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.evidence.exceptions import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from httpserver.services.forensic_report.generation import (
    REPORT_GENERATION_PROMPT_VERSION,
    ReportGenerationAdmissionService,
    ReportGenerationInputBuilder,
    ReportGenerationInputError,
)
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.models import ScopeType
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    ClaimCandidate,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)
from httpserver.services.investigation.repository import SUPPORTED_SCHEMA_VERSION

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"
OTHER_KEY = "file:/case/b.txt"
THIRD_KEY = "file:/case/c.txt"

_OLD_REPORT_VERSIONS_DDL = """
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
)
"""


def _make_files_db(path: str, rows: tuple[tuple[str, int], ...]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for file_path, size in rows:
        conn.execute(
            "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
            (file_path, "d", size),
        )
    conn.commit()
    conn.close()


def _repo_with_evidence(
    tmp_path: Path,
    task_id: str = "A",
    rows: tuple[tuple[str, int], ...] = (("/case/a.txt", 1), ("/case/b.txt", 2)),
):
    root = tmp_path / task_id
    root.mkdir(parents=True, exist_ok=True)
    files_db = str(root / "files.db")
    _make_files_db(files_db, rows)
    repo = InvestigationRepository(root / "investigation.db", task_id)
    snapshots = {}
    for file_path, _size in rows:
        key = f"file:{file_path}"
        snapshots[key] = repo.capture_if_absent(ResolvedEvidence(
            task_id=task_id, evidence_key=key, evidence_type="file",
            normalized_path=file_path, source_db=files_db,
        ))
    return root, repo, snapshots


def _analysis_at(
    repo: InvestigationRepository,
    snapshot,
    *,
    decision: str | None,  # None = leave review_pending
    claim_refs: tuple[str, ...] = (),
    related: tuple[str, ...] = (),
    claim_text: str = "c",
):
    """Create one analysis version and drive it to the requested state."""
    analysis = repo.create_analysis(
        snapshot, prompt_version=PROMPT_V3, related_evidence=related
    )
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="d", summary="s", model="m",
        candidates=[ClaimCandidate(
            claim_type="FACT", claim_text=claim_text,
            evidence_refs=(snapshot.evidence_key, *claim_refs),
        )],
    )
    if decision is not None:
        repo.review_analysis(
            analysis.analysis_id,
            decision=AnalysisReviewDecision(decision),
            reviewer="analyst-x",
        )
    return repo.get_analysis(analysis.analysis_id)


def _task_dict(root: Path, task_id: str) -> dict:
    return {
        "id": task_id,
        "output_files_db": str(root / "files.db"),
        "output_events_db": None,
    }


def _service(tmp_path: Path, tasks: dict[str, dict]):
    repository = ReportRepository(tmp_path / "reports.db")
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(side_effect=lambda tid: tasks.get(tid))
    service = ReportGenerationAdmissionService(
        cpp_backend=cpp, repository=repository
    )
    return service, repository


def _admit(service, task_id="A", requested_by="analyst-x", **kwargs):
    return asyncio.run(service.admit(task_id, requested_by=requested_by, **kwargs))


def _generation_count(repository: ReportRepository) -> int:
    with sqlite3.connect(repository.db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM report_generation_inputs"
        ).fetchone()[0]


def _strip_report_extension(db_path: Path) -> None:
    """Simulate a C10-era v7 store that never got the R1 extension table."""
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE report_evidence")
    conn.commit()
    conn.close()


def _envelope(row) -> dict:
    return json.loads(row.input_envelope_json)


# ---------------------------------------------------------------------------
# §26-1: Original Evidence only (analysis_id = NULL), no latest fallback
# ---------------------------------------------------------------------------

def test_original_only_main_null_binding(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    _analysis_at(repo, snapshots[KEY], decision="accepted")  # exists, unbound
    repo.add_report_evidence(KEY, report_status="main", added_by="analyst-x")
    service, repository = _service(tmp_path, {"A": _task_dict(root, "A")})

    row = _admit(service)

    envelope = _envelope(row)
    assert [item["evidence_key"] for item in envelope["main_evidence"]] == [KEY]
    assert envelope["main_evidence"][0]["bound_analysis"] is None
    # The unbound accepted analysis never leaks into the frozen input.
    assert "analysis_id" not in json.dumps(envelope["main_evidence"][0]["snapshot"])
    assert PROMPT_V3 not in row.input_envelope_json
    assert row.input_hash == __import__("hashlib").sha256(
        row.input_envelope_json.encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# §26-2: bound A1 -> exact A1 + exact claims/refs frozen
# ---------------------------------------------------------------------------

def test_bound_a1_freezes_exact_analysis_and_claims(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snapshots[KEY], decision="accepted")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="analyst-x"
    )
    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})

    row = _admit(service)

    bound = _envelope(row)["main_evidence"][0]["bound_analysis"]
    assert bound["analysis_id"] == a1.analysis_id
    assert bound["version"] == a1.version
    assert bound["description"] == "d"
    assert bound["model"] == "m"
    assert bound["review"]["decided_by"] == "analyst-x"
    assert [c["claim_text"] for c in bound["claims"]] == ["c"]
    assert bound["claims"][0]["evidence_refs"] == [KEY]


# ---------------------------------------------------------------------------
# §26-3: newer accepted A2 never changes the frozen input
# ---------------------------------------------------------------------------

def test_newer_accepted_a2_does_not_change_envelope(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snapshots[KEY], decision="accepted")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="analyst-x"
    )
    service, repository = _service(tmp_path, {"A": _task_dict(root, "A")})
    row1 = _admit(service)
    assert _envelope(row1)["main_evidence"][0]["bound_analysis"]["analysis_id"] == a1.analysis_id

    a2 = _analysis_at(repo, snapshots[KEY], decision="accepted", claim_text="c2")

    row2 = _admit(service)
    assert _envelope(row2)["main_evidence"][0]["bound_analysis"]["analysis_id"] == a1.analysis_id
    assert row2.input_hash == row1.input_hash  # unbound change is invisible
    # The UI hint is never part of the generation input.
    assert "newer_accepted_available" not in row2.input_envelope_json


# ---------------------------------------------------------------------------
# §26-4: main / appendix / excluded matrix
# ---------------------------------------------------------------------------

def test_main_appendix_excluded_matrix(tmp_path):
    root, repo, snapshots = _repo_with_evidence(
        tmp_path, rows=(("/case/a.txt", 1), ("/case/b.txt", 2), ("/case/c.txt", 3))
    )
    repo.add_report_evidence(KEY, report_status="main", added_by="x")
    repo.add_report_evidence(OTHER_KEY, report_status="appendix", added_by="x")
    repo.add_report_evidence(THIRD_KEY, report_status="main", added_by="x")
    repo.update_report_evidence(
        THIRD_KEY, report_status="excluded", updated_by="x"
    )
    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})

    row = _admit(service)
    envelope = _envelope(row)

    assert [i["evidence_key"] for i in envelope["main_evidence"]] == [KEY]
    assert [i["evidence_key"] for i in envelope["appendix_evidence"]] == [OTHER_KEY]
    assert envelope["allowed_report_evidence_ids"] == sorted([KEY, OTHER_KEY])
    # Excluded is fully absent from the frozen input.
    assert THIRD_KEY not in row.input_envelope_json


# ---------------------------------------------------------------------------
# §26-5: claim external ref retained as provenance, not allowed citation
# ---------------------------------------------------------------------------

def test_claim_external_ref_retained_but_not_allowed(tmp_path):
    root, repo, snapshots = _repo_with_evidence(
        tmp_path, rows=(("/case/a.txt", 1), ("/case/b.txt", 2))
    )
    a1 = _analysis_at(
        repo, snapshots[KEY], decision="accepted",
        claim_refs=(OTHER_KEY,), related=(OTHER_KEY,),
    )
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="x"
    )  # B is NOT added to the report evidence set
    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})

    row = _admit(service)
    envelope = _envelope(row)

    claim = envelope["main_evidence"][0]["bound_analysis"]["claims"][0]
    assert claim["evidence_refs"] == sorted([KEY, OTHER_KEY])  # provenance kept
    assert envelope["allowed_report_evidence_ids"] == [KEY]  # citation boundary


# ---------------------------------------------------------------------------
# §26-6: invalid persisted binding fails closed, no generation row
# ---------------------------------------------------------------------------

def test_invalid_persisted_binding_fails_closed(tmp_path):
    root, repo, snapshots = _repo_with_evidence(
        tmp_path, rows=(("/case/a.txt", 1), ("/case/b.txt", 2))
    )
    b_key = _analysis_at(repo, snapshots[OTHER_KEY], decision=None)  # review_pending
    repo.add_report_evidence(KEY, report_status="main", added_by="x")
    service, repository = _service(tmp_path, {"A": _task_dict(root, "A")})

    # Tamper case 1: binding points at another evidence's analysis.
    conn = sqlite3.connect(root / "investigation.db")
    conn.execute(
        "UPDATE report_evidence SET analysis_id = ?", (b_key.analysis_id,)
    )
    conn.commit()
    with pytest.raises(ReportGenerationInputError) as excinfo:
        _admit(service)
    assert excinfo.value.code == "invalid_report_evidence_binding"

    # Tamper case 2: binding points at a non-accepted analysis of this evidence.
    pending = _analysis_at(repo, snapshots[KEY], decision=None)
    conn.execute(
        "UPDATE report_evidence SET analysis_id = ?", (pending.analysis_id,)
    )
    conn.commit()
    conn.close()
    with pytest.raises(ReportGenerationInputError) as excinfo:
        _admit(service)
    assert excinfo.value.code == "invalid_report_evidence_binding"
    assert _generation_count(repository) == 0


# ---------------------------------------------------------------------------
# §26-7: cross-task isolation
# ---------------------------------------------------------------------------

def test_cross_task_envelopes_are_isolated(tmp_path):
    root_a, repo_a, snapshots_a = _repo_with_evidence(tmp_path / "A", task_id="A")
    root_b, repo_b, snapshots_b = _repo_with_evidence(tmp_path / "B", task_id="B")
    analysis_a = _analysis_at(repo_a, snapshots_a[KEY], decision="accepted", claim_text="from-a")
    analysis_b = _analysis_at(repo_b, snapshots_b[KEY], decision="accepted", claim_text="from-b")
    repo_a.add_report_evidence(
        KEY, report_status="main", analysis_id=analysis_a.analysis_id, added_by="x"
    )
    repo_b.add_report_evidence(
        KEY, report_status="main", analysis_id=analysis_b.analysis_id, added_by="x"
    )
    service, _ = _service(tmp_path, {
        "A": _task_dict(root_a, "A"), "B": _task_dict(root_b, "B"),
    })

    row_a = _admit(service, task_id="A")
    row_b = _admit(service, task_id="B")

    bound_a = _envelope(row_a)["main_evidence"][0]["bound_analysis"]
    bound_b = _envelope(row_b)["main_evidence"][0]["bound_analysis"]
    assert bound_a["analysis_id"] == analysis_a.analysis_id
    assert bound_b["analysis_id"] == analysis_b.analysis_id
    assert row_a.task_id == "A" and row_b.task_id == "B"
    assert analysis_b.analysis_id not in row_a.input_envelope_json
    assert analysis_a.analysis_id not in row_b.input_envelope_json


def test_foreign_analysis_id_cannot_enter_task_envelope(tmp_path):
    root_a, repo_a, snapshots_a = _repo_with_evidence(tmp_path / "A", task_id="A")
    root_b, repo_b, snapshots_b = _repo_with_evidence(tmp_path / "B", task_id="B")
    analysis_a = _analysis_at(repo_a, snapshots_a[KEY], decision="accepted")
    repo_b.add_report_evidence(KEY, report_status="main", added_by="x")
    # Corrupt B's store so its binding points at A's analysis.
    conn = sqlite3.connect(root_b / "investigation.db")
    conn.execute(
        "UPDATE report_evidence SET analysis_id = ?", (analysis_a.analysis_id,)
    )
    conn.commit()
    conn.close()
    service, repository = _service(tmp_path, {
        "A": _task_dict(root_a, "A"), "B": _task_dict(root_b, "B"),
    })

    with pytest.raises(ReportGenerationInputError):
        _admit(service, task_id="B")
    assert _generation_count(repository) == 0


# ---------------------------------------------------------------------------
# §26-8: determinism -- same source state -> identical envelope/hash
# ---------------------------------------------------------------------------

def test_determinism_same_state_identical_hash(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snapshots[KEY], decision="accepted")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="x"
    )
    builder = ReportGenerationInputBuilder(root / "investigation.db", "A")
    from httpserver.services.investigation.acquisition import canonical_json
    import hashlib

    first = canonical_json(builder.assemble())
    second = canonical_json(builder.assemble())
    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == \
        hashlib.sha256(second.encode("utf-8")).hexdigest()

    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})
    row1 = _admit(service)
    row2 = _admit(service)
    assert row1.input_envelope_json == row2.input_envelope_json == first
    assert row1.input_hash == row2.input_hash
    assert row1.generation_id != row2.generation_id


# ---------------------------------------------------------------------------
# §26-9: any frozen input change -> different hash
# ---------------------------------------------------------------------------

def test_hash_changes_when_frozen_inputs_change(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snapshots[KEY], decision="accepted", claim_text="c1")
    a2 = _analysis_at(repo, snapshots[KEY], decision="accepted", claim_text="c2")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="x"
    )
    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})
    baseline = _admit(service).input_hash

    # Binding change (different analysis with different claims).
    repo.update_report_evidence(
        KEY, analysis_id=a2.analysis_id, bind_analysis=True, updated_by="x"
    )
    assert _admit(service).input_hash != baseline

    # Report status change.
    repo.update_report_evidence(KEY, report_status="appendix", updated_by="x")
    assert _admit(service).input_hash != baseline

    # Prompt version change.
    row = _admit(service, prompt_version="final-report:v2")
    assert row.prompt_version == "final-report:v2"
    assert row.input_hash != baseline

    # Snapshot payload change: same key captured from different source state.
    root_b, repo_b, snapshots_b = _repo_with_evidence(
        tmp_path / "B2", task_id="B2", rows=(("/case/a.txt", 42),)
    )
    repo_b.add_report_evidence(KEY, report_status="main", added_by="x")
    service_b, _ = _service(tmp_path, {"B2": _task_dict(root_b, "B2")})
    assert _admit(service_b, task_id="B2").input_hash != baseline


# ---------------------------------------------------------------------------
# §26-10: frozen input DB triggers
# ---------------------------------------------------------------------------

def test_frozen_input_triggers_reject_mutation(tmp_path):
    repository = ReportRepository(tmp_path / "reports.db")
    row = repository.create_generation_input(
        "T", requested_by="analyst-x", input_schema_version=1,
        prompt_version=REPORT_GENERATION_PROMPT_VERSION,
        input_envelope_json="{}", input_hash="deadbeef",
    )
    assert row.status == "admitted"
    assert row.report_id is None

    conn = sqlite3.connect(repository.db_path)
    # Lifecycle columns stay writable for R2c.
    conn.execute(
        "UPDATE report_generation_inputs SET status = 'running' "
        "WHERE generation_id = ?", (row.generation_id,)
    )
    conn.commit()
    # Frozen columns reject any change.
    for statement in (
        "UPDATE report_generation_inputs SET input_hash = 'x' WHERE generation_id = ?",
        "UPDATE report_generation_inputs SET input_envelope_json = 'x' WHERE generation_id = ?",
        "UPDATE report_generation_inputs SET prompt_version = 'x' WHERE generation_id = ?",
        "UPDATE report_generation_inputs SET task_id = 'other' WHERE generation_id = ?",
        "UPDATE report_generation_inputs SET requested_by = 'y' WHERE generation_id = ?",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement, (row.generation_id,))
            conn.commit()
        conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        conn.execute(
            "DELETE FROM report_generation_inputs WHERE generation_id = ?",
            (row.generation_id,),
        )
        conn.commit()
    conn.close()
    fetched = repository.get_generation_input(row.generation_id)
    assert fetched.input_hash == "deadbeef"
    assert fetched.status == "running"


# ---------------------------------------------------------------------------
# §26-11: empty / missing report evidence -> typed error, no row
# ---------------------------------------------------------------------------

def test_all_excluded_is_no_report_evidence(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    repo.add_report_evidence(KEY, report_status="main", added_by="x")
    repo.update_report_evidence(KEY, report_status="excluded", updated_by="x")
    service, repository = _service(tmp_path, {"A": _task_dict(root, "A")})

    with pytest.raises(ReportGenerationInputError) as excinfo:
        _admit(service)
    assert excinfo.value.code == "no_report_evidence"
    assert _generation_count(repository) == 0


def test_store_without_extension_table_is_no_report_evidence(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    _strip_report_extension(root / "investigation.db")
    service, repository = _service(tmp_path, {"A": _task_dict(root, "A")})

    with pytest.raises(ReportGenerationInputError) as excinfo:
        _admit(service)
    assert excinfo.value.code == "no_report_evidence"
    assert _generation_count(repository) == 0


def test_missing_store_and_untrusted_task_are_no_report_evidence(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    (root / "investigation.db").unlink()
    service, repository = _service(tmp_path, {"A": _task_dict(root, "A")})
    with pytest.raises(ReportGenerationInputError) as excinfo:
        _admit(service)
    assert excinfo.value.code == "no_report_evidence"

    # Task without any trusted database path cannot own report evidence.
    service, repository = _service(tmp_path, {"A": {"id": "A"}})
    with pytest.raises(ReportGenerationInputError) as excinfo:
        _admit(service)
    assert excinfo.value.code == "no_report_evidence"

    # Unknown task stays an opaque not-found, never probeable.
    with pytest.raises(EvidenceNotFoundError):
        _admit(service, task_id="ghost")
    assert _generation_count(repository) == 0


def test_unsupported_investigation_version_fails_closed(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    repo.add_report_evidence(KEY, report_status="main", added_by="x")
    assert (root / "investigation.db").exists()
    conn = sqlite3.connect(root / "investigation.db")
    conn.execute(f"PRAGMA user_version = {SUPPORTED_SCHEMA_VERSION - 1}")
    conn.commit()
    conn.close()
    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})

    with pytest.raises(EvidenceStoreError):
        _admit(service)


# ---------------------------------------------------------------------------
# §26-12: read consistency -- one connection, one read epoch
# ---------------------------------------------------------------------------

def test_assembly_uses_exactly_one_connection(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snapshots[KEY], decision="accepted")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="x"
    )
    builder = ReportGenerationInputBuilder(root / "investigation.db", "A")

    with patch(
        "httpserver.services.forensic_report.generation.sqlite3.connect",
        wraps=sqlite3.connect,
    ) as connect:
        builder.assemble()
    assert connect.call_count == 1


def test_admission_epochs_never_mix(tmp_path):
    root, repo, snapshots = _repo_with_evidence(tmp_path)
    a1 = _analysis_at(repo, snapshots[KEY], decision="accepted", claim_text="c1")
    a2 = _analysis_at(repo, snapshots[KEY], decision="accepted", claim_text="c2")
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=a1.analysis_id, added_by="x"
    )
    service, _ = _service(tmp_path, {"A": _task_dict(root, "A")})

    row1 = _admit(service)
    repo.update_report_evidence(
        KEY, analysis_id=a2.analysis_id, bind_analysis=True, updated_by="x"
    )
    row2 = _admit(service)

    assert _envelope(row1)["main_evidence"][0]["bound_analysis"]["analysis_id"] == a1.analysis_id
    assert _envelope(row2)["main_evidence"][0]["bound_analysis"]["analysis_id"] == a2.analysis_id
    assert row1.input_hash != row2.input_hash


# ---------------------------------------------------------------------------
# Envelope contract guards (determinism is validated, not just performed)
# ---------------------------------------------------------------------------

def test_envelope_model_rejects_nondeterministic_shapes():
    from httpserver.services.forensic_report import (
        EnvelopeEvidenceItemV1,
        EnvelopeSnapshotV1,
        ReportGenerationEnvelopeV1,
    )

    def snapshot_for(key: str) -> EnvelopeSnapshotV1:
        from httpserver.services.investigation.models import FileSnapshotPayload
        return EnvelopeSnapshotV1(
            task_id="A", evidence_key=key, evidence_type="file", captured_at=1,
            payload=FileSnapshotPayload(normalized_path=key.removeprefix("file:")),
        )

    def item(key: str) -> EnvelopeEvidenceItemV1:
        from httpserver.services.investigation.models import ReportEvidenceStatus
        return EnvelopeEvidenceItemV1(
            evidence_key=key, report_status=ReportEvidenceStatus.main,
            snapshot=snapshot_for(key),
        )

    base = dict(
        prompt_version="p", task_id="A",
        main_evidence=(item("file:/b"), item("file:/a")),  # unsorted
    )
    with pytest.raises(ValueError, match="sorted"):
        ReportGenerationEnvelopeV1(**base)
    with pytest.raises(ValueError, match="allowed_report_evidence_ids"):
        ReportGenerationEnvelopeV1(
            prompt_version="p", task_id="A",
            main_evidence=(item("file:/a"),),
            allowed_report_evidence_ids=("file:/a", "file:/zz"),
        )
    with pytest.raises(ValueError, match="task mismatch"):
        ReportGenerationEnvelopeV1(
            prompt_version="p", task_id="B",
            main_evidence=(item("file:/a"),),
            allowed_report_evidence_ids=("file:/a",),
        )


# ---------------------------------------------------------------------------
# Schema compatibility: additive companion on a legacy reports.db
# ---------------------------------------------------------------------------

def test_legacy_reports_db_gets_additive_companion_and_old_reads_work(tmp_path):
    legacy = tmp_path / "reports.db"
    conn = sqlite3.connect(legacy)
    conn.executescript(_OLD_REPORT_VERSIONS_DDL)
    conn.execute(
        """INSERT INTO report_versions
           (report_id, version, scope_type, scope_id, status, title,
            task_ids_json, stage, progress, created_at)
           VALUES ('r1', 1, 'task', 'T', 'ready', 't', '["T"]', 'ready', 100, '2026')"""
    )
    conn.commit()
    conn.close()

    repository = ReportRepository(legacy)  # constructor migrates additively

    assert repository.get("r1") is not None  # old chain still readable
    assert [v.version for v in repository.list_versions(ScopeType.TASK, "T")] == [1]
    row = repository.create_generation_input(
        "T", requested_by="x", input_schema_version=1,
        prompt_version=REPORT_GENERATION_PROMPT_VERSION,
        input_envelope_json="{}", input_hash="h",
    )
    assert repository.get_generation_input(row.generation_id) is not None
