"""Tests for Analyst Context Snapshot (Phase C4c).

Covers CCTX1-8, related evidence canonicalization, envelope↔prompt compat,
v3 input immutability trigger, field limits, and RelatedEvidenceEntry validator.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import EvidenceNotFoundError, EvidenceResolver, ResolvedEvidence
from httpserver.services.investigation import (
    CURRENT_PROMPT_VERSION,
    ENVELOPE_PROMPT_COMPAT,
    InvestigationCaptureService,
    InvestigationRepository,
    RelatedEvidenceEntry,
    SecondaryAnalysisStatus,
    parse_analysis_input_envelope,
)
from httpserver.services.investigation.execution import SecondaryAnalysisExecutor
from httpserver.services.investigation.prompts import (
    PROMPT_REGISTRY,
    SECONDARY_ANALYSIS_SYSTEM_V2,
    SECONDARY_ANALYSIS_USER_TEMPLATE_V2,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_files_db(db_path, rows):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO files (path,name,extension,category,type,size,mtime,ctime,is_deleted,md5,"
            "llm_summary,llm_description,llm_keywords,llm_analyzed_at,llm_model_used,"
            "scene_type,scene_priority,scene_relevant) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.get("path"), r.get("name"), r.get("extension"), r.get("category"), r.get("type"),
             r.get("size"), r.get("mtime"), r.get("ctime"), r.get("is_deleted"), r.get("md5"),
             r.get("llm_summary"), r.get("llm_description"), r.get("llm_keywords"),
             r.get("llm_analyzed_at"), r.get("llm_model_used"),
             r.get("scene_type"), r.get("scene_priority"), r.get("scene_relevant")),
        )
    conn.commit()
    conn.close()


def _file_resolved(fdb, task_id="A", path="/case/report.docx"):
    return ResolvedEvidence(
        task_id=task_id, evidence_key=f"file:{path}", evidence_type="file",
        normalized_path=path, source_db=fdb,
    )


def _setup(tmp_path, paths=None):
    """Create files.db + investigation.db with primary + optional related captured."""
    fdb = str(tmp_path / "files.db")
    idb = str(tmp_path / "investigation.db")
    rows = [{"path": "/case/report.docx", "llm_description": "PRIMARY", "size": 7}]
    for p in (paths or []):
        rows.append({"path": p, "llm_description": f"DESC_{p}", "size": 3})
    _make_files_db(fdb, rows)
    repo = InvestigationRepository(idb, "A")
    snap = repo.capture_if_absent(_file_resolved(fdb))
    related_keys = []
    for p in (paths or []):
        repo.capture_if_absent(_file_resolved(fdb, path=p))
        related_keys.append(f"file:{p}")
    return fdb, idb, repo, snap, related_keys


def _mock_llm(content="分析结果"):
    m = Mock()
    m.chat_completion = AsyncMock(return_value={"content": content, "model": "m", "tokens_used": 1})
    return m


PRIMARY_KEY = "file:/case/report.docx"


# ---------------------------------------------------------------------------
# CCTX2: worker uses envelope analyst_note, not runtime re-read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_CCTX2_analyst_note_frozen(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(snap, analyst_note="ORIGINAL_NOTE", prompt_version=CURRENT_PROMPT_VERSION)
    mock_llm = _mock_llm()
    executor = SecondaryAnalysisExecutor(Mock(), mock_llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    call_kwargs = mock_llm.chat_completion.call_args
    user_prompt = call_kwargs.kwargs.get("user_prompt") or call_kwargs.args[1]
    assert "ORIGINAL_NOTE" in user_prompt


# ---------------------------------------------------------------------------
# CCTX5: envelope stores related key + frozen snapshot
# ---------------------------------------------------------------------------

def test_CCTX5_related_evidence_frozen_in_envelope(tmp_path):
    _, idb, repo, snap, rel = _setup(tmp_path, paths=["/case/other.txt"])
    analysis = repo.create_analysis(snap, related_evidence=tuple(rel), prompt_version=CURRENT_PROMPT_VERSION)
    envelope = parse_analysis_input_envelope(analysis.input_envelope_json)
    assert envelope.schema_version == 2
    assert len(envelope.related_evidence) == 1
    entry = envelope.related_evidence[0]
    assert entry.evidence_key == "file:/case/other.txt"
    assert entry.snapshot["evidence_key"] == "file:/case/other.txt"
    assert "payload" in entry.snapshot
    actual = hashlib.sha256(analysis.input_envelope_json.encode()).hexdigest()
    assert actual == analysis.input_hash


# ---------------------------------------------------------------------------
# CCTX7: different context → different hash → new version
# ---------------------------------------------------------------------------

def test_CCTX7_different_note_different_hash(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    v1 = repo.create_analysis(snap, analyst_note="NOTE_A", prompt_version=CURRENT_PROMPT_VERSION)
    v2 = repo.create_analysis(snap, analyst_note="NOTE_B", prompt_version=CURRENT_PROMPT_VERSION)
    assert v1.input_hash != v2.input_hash
    assert v2.version == v1.version + 1


def test_CCTX7_different_case_context_different_hash(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    v1 = repo.create_analysis(snap, case_context="CTX_A", prompt_version=CURRENT_PROMPT_VERSION)
    v2 = repo.create_analysis(snap, case_context="CTX_B", prompt_version=CURRENT_PROMPT_VERSION)
    assert v1.input_hash != v2.input_hash


def test_CCTX7_different_related_different_hash(tmp_path):
    _, idb, repo, snap, rel = _setup(tmp_path, paths=["/case/A.txt", "/case/B.txt"])
    v1 = repo.create_analysis(snap, related_evidence=("file:/case/A.txt",), prompt_version=CURRENT_PROMPT_VERSION)
    v2 = repo.create_analysis(snap, related_evidence=("file:/case/A.txt", "file:/case/B.txt"), prompt_version=CURRENT_PROMPT_VERSION)
    assert v1.input_hash != v2.input_hash


# ---------------------------------------------------------------------------
# CCTX8: old version retains old context
# ---------------------------------------------------------------------------

def test_CCTX8_old_version_retains_old_note(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    v1 = repo.create_analysis(snap, analyst_note="NOTE_A", prompt_version=CURRENT_PROMPT_VERSION)
    repo.create_analysis(snap, analyst_note="NOTE_B", prompt_version=CURRENT_PROMPT_VERSION)
    v1_after = repo.get_analysis(v1.analysis_id)
    envelope = parse_analysis_input_envelope(v1_after.input_envelope_json)
    assert envelope.analyst_note == "NOTE_A"


# ---------------------------------------------------------------------------
# Related evidence canonicalization (executor submit level)
# ---------------------------------------------------------------------------

class _FakeCapture:
    """Returns pre-captured snapshots; raises for unknown keys."""
    def __init__(self, snapshots):
        self._snapshots = snapshots
    async def capture(self, task_id, evidence_key):
        if evidence_key not in self._snapshots:
            raise EvidenceNotFoundError(f"not found: {evidence_key}")
        return self._snapshots[evidence_key]


class _FakeCpp:
    def __init__(self, task_dir):
        self._dir = str(task_dir)
    async def get_task(self, task_id):
        return {"id": task_id, "output_files_db": f"{self._dir}/files.db",
                "output_events_db": f"{self._dir}/events.db"}
    async def list_tasks(self, **kw):
        return {"tasks": []}


@pytest.mark.asyncio
async def test_canonicalization_order_independent(tmp_path):
    """Different input orders → same input_hash."""
    fdb, idb, repo, snap, rel = _setup(tmp_path, paths=["/case/A.txt", "/case/B.txt"])
    all_snaps = {PRIMARY_KEY: snap}
    for k in rel:
        all_snaps[k] = repo.get_snapshot(k)
    executor = SecondaryAnalysisExecutor(
        _FakeCpp(tmp_path), _mock_llm(), _FakeCapture(all_snaps),
    )
    a1 = await executor.submit("A", PRIMARY_KEY, related_evidence=("file:/case/A.txt", "file:/case/B.txt"))
    a2 = await executor.submit("A", PRIMARY_KEY, related_evidence=("file:/case/B.txt", "file:/case/A.txt"))
    assert a1.input_hash == a2.input_hash


@pytest.mark.asyncio
async def test_canonicalization_dedup(tmp_path):
    fdb, idb, repo, snap, rel = _setup(tmp_path, paths=["/case/A.txt"])
    all_snaps = {PRIMARY_KEY: snap, "file:/case/A.txt": repo.get_snapshot("file:/case/A.txt")}
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), _mock_llm(), _FakeCapture(all_snaps))
    a1 = await executor.submit("A", PRIMARY_KEY, related_evidence=("file:/case/A.txt",))
    a2 = await executor.submit("A", PRIMARY_KEY, related_evidence=("file:/case/A.txt", "file:/case/A.txt"))
    assert a1.input_hash == a2.input_hash


@pytest.mark.asyncio
async def test_canonicalization_self_removed(tmp_path):
    """Primary evidence in related list → removed (no self-reference)."""
    fdb, idb, repo, snap, rel = _setup(tmp_path, paths=["/case/A.txt"])
    all_snaps = {PRIMARY_KEY: snap, "file:/case/A.txt": repo.get_snapshot("file:/case/A.txt")}
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), _mock_llm(), _FakeCapture(all_snaps))
    a1 = await executor.submit("A", PRIMARY_KEY, related_evidence=("file:/case/A.txt",))
    a2 = await executor.submit("A", PRIMARY_KEY, related_evidence=(PRIMARY_KEY, "file:/case/A.txt"))
    assert a1.input_hash == a2.input_hash


# ---------------------------------------------------------------------------
# CCTX3: related evidence not found → submit raises
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_CCTX3_related_not_found_raises(tmp_path):
    fdb, idb, repo, snap, _ = _setup(tmp_path)
    all_snaps = {PRIMARY_KEY: snap}
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), _mock_llm(), _FakeCapture(all_snaps))
    with pytest.raises(EvidenceNotFoundError):
        await executor.submit("A", PRIMARY_KEY, related_evidence=["file:/nonexistent.txt"])


# ---------------------------------------------------------------------------
# CCTX4: related evidence resolves only in current task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_CCTX4_related_resolves_only_in_current_task(tmp_path):
    """Task A lacks file; Task B has it. Submit with task_id=A → 404."""
    dir_a = tmp_path / "taskA"
    dir_b = tmp_path / "taskB"
    dir_a.mkdir(); dir_b.mkdir()
    _make_files_db(str(dir_a / "files.db"), [{"path": "/case/report.docx", "llm_description": "A_DESC"}])
    _make_files_db(str(dir_b / "files.db"), [{"path": "/case/only-in-B.txt", "llm_description": "B_DESC"}])

    class MultiCpp:
        async def get_task(self, task_id):
            d = dir_a if task_id == "A" else dir_b
            return {"id": task_id, "output_files_db": str(d / "files.db"),
                    "output_events_db": str(d / "events.db")}
        async def list_tasks(self, **kw):
            return {"tasks": [{"id": "A"}, {"id": "B"}]}

    cpp = MultiCpp()
    capture_svc = InvestigationCaptureService(cpp, EvidenceResolver(cpp))
    executor = SecondaryAnalysisExecutor(cpp, _mock_llm(), capture_svc)

    with pytest.raises(EvidenceNotFoundError):
        await executor.submit("A", PRIMARY_KEY, related_evidence=["file:/case/only-in-B.txt"])


# ---------------------------------------------------------------------------
# Related snapshot frozen (modify source DB → LLM sees original)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_related_snapshot_frozen(tmp_path):
    fdb, idb, repo, snap, rel = _setup(tmp_path, paths=["/case/other.txt"])
    analysis = repo.create_analysis(snap, related_evidence=tuple(rel), prompt_version=CURRENT_PROMPT_VERSION)
    # Modify source DB
    conn = sqlite3.connect(fdb)
    conn.execute("UPDATE files SET llm_description='MODIFIED' WHERE path='/case/other.txt'")
    conn.commit(); conn.close()
    mock_llm = _mock_llm()
    executor = SecondaryAnalysisExecutor(Mock(), mock_llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    call_kwargs = mock_llm.chat_completion.call_args
    user_prompt = call_kwargs.kwargs.get("user_prompt") or call_kwargs.args[1]
    assert "DESC_/case/other.txt" in user_prompt
    assert "MODIFIED" not in user_prompt


# ---------------------------------------------------------------------------
# Prompt v2: context data in user_prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prompt_v2_includes_context(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(
        snap, analyst_note="SPECIAL_NOTE", case_context="CASE_DIRECTION",
        prompt_version=CURRENT_PROMPT_VERSION,
    )
    mock_llm = _mock_llm()
    executor = SecondaryAnalysisExecutor(Mock(), mock_llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    call = mock_llm.chat_completion.call_args
    user_prompt = call.kwargs.get("user_prompt") or call.args[1]
    assert "SPECIAL_NOTE" in user_prompt
    assert "CASE_DIRECTION" in user_prompt


# ---------------------------------------------------------------------------
# Envelope ↔ prompt version compatibility
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_envelope_prompt_compat_mismatch(tmp_path):
    """v2 envelope + v1 prompt in row → input_integrity_error."""
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    # Tamper: change row prompt_version to v1 (incompatible with v2 envelope)
    from httpserver.services.investigation.repository import _TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL
    conn = sqlite3.connect(idb)
    conn.execute("DROP TRIGGER trg_secondary_no_input_update")
    conn.execute("UPDATE secondary_analyses SET prompt_version='investigation-evidence-analysis:v1' WHERE analysis_id=?",
                 [analysis.analysis_id])
    conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)
    conn.commit(); conn.close()
    executor = SecondaryAnalysisExecutor(Mock(), _mock_llm(), Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "input_integrity_error"


# ---------------------------------------------------------------------------
# v3 trigger: input columns immutable for ALL states
# ---------------------------------------------------------------------------

def test_v3_input_immutable_for_queued(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="input is immutable"):
        conn.execute("UPDATE secondary_analyses SET input_envelope_json='{}' WHERE analysis_id=?",
                     [analysis.analysis_id])
    conn.close()


def test_v3_prompt_version_immutable(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="input is immutable"):
        conn.execute("UPDATE secondary_analyses SET prompt_version='x' WHERE analysis_id=?",
                     [analysis.analysis_id])
    conn.close()


def test_v3_output_columns_still_mutable(tmp_path):
    """Non-input columns (summary) are still updatable via state machine."""
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.review_pending, summary="updated")
    result = repo.get_analysis(analysis.analysis_id)
    assert result.summary == "updated"


# ---------------------------------------------------------------------------
# RelatedEvidenceEntry identity validator
# ---------------------------------------------------------------------------

def test_related_evidence_entry_identity_ok():
    entry = RelatedEvidenceEntry(
        evidence_key="file:/case/a.txt",
        snapshot={"evidence_key": "file:/case/a.txt", "payload": {}},
    )
    assert entry.evidence_key == "file:/case/a.txt"


def test_related_evidence_entry_identity_mismatch():
    with pytest.raises(ValueError, match="identity mismatch"):
        RelatedEvidenceEntry(
            evidence_key="file:/case/a.txt",
            snapshot={"evidence_key": "file:/different.txt", "payload": {}},
        )


# ---------------------------------------------------------------------------
# Field limits (route-level)
# ---------------------------------------------------------------------------

def test_field_limit_analyst_note_too_long():
    from httpserver.routes.investigation import CreateAnalysisRequest
    with pytest.raises(Exception):
        CreateAnalysisRequest(task_id="A", evidence_key="file:/x", analyst_note="x" * 20001)


def test_field_limit_related_too_many():
    from httpserver.routes.investigation import CreateAnalysisRequest
    with pytest.raises(Exception):
        CreateAnalysisRequest(task_id="A", evidence_key="file:/x",
                              related_evidence=["file:/x"] * 21)


# ---------------------------------------------------------------------------
# Empty context backward compat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_context_works(tmp_path):
    _, idb, repo, snap, _ = _setup(tmp_path)
    analysis = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    envelope = parse_analysis_input_envelope(analysis.input_envelope_json)
    assert envelope.analyst_note is None
    assert envelope.case_context is None
    assert len(envelope.related_evidence) == 0


# ---------------------------------------------------------------------------
# Prompt v2 SHA-256 immutability lock
# ---------------------------------------------------------------------------

def test_prompt_v2_immutable_hash():
    expected = "713acce3133129cf797441f41ebdd3381f01f57c82a9397314cfe8336f9054ff"
    data = (SECONDARY_ANALYSIS_SYSTEM_V2 + SECONDARY_ANALYSIS_USER_TEMPLATE_V2).encode("utf-8")
    actual = hashlib.sha256(data).hexdigest()
    assert actual == expected, (
        "v2 prompt text was modified! Create v3 instead. "
        "If intentional, update the expected hash."
    )


def test_envelope_prompt_compat_map():
    assert ENVELOPE_PROMPT_COMPAT[1] == "investigation-evidence-analysis:v1"
    assert ENVELOPE_PROMPT_COMPAT[2] == "investigation-evidence-analysis:v2"
    assert CURRENT_PROMPT_VERSION in PROMPT_REGISTRY
