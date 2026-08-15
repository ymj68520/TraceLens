"""Tests for Claims Persistence & Grounding Validator (Phase C5a).

Covers G1-G14: validator pure functions, derive_allowed_evidence_ids,
persist_claims (write-once, status==running, internal re-validation),
DB immutability triggers, and v4 migration.
"""

from __future__ import annotations

import sqlite3

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisGroundingStatus,
    AnalysisReviewDecision,
    ClaimCandidate,
    ClaimGroundingStatus,
    ClaimType,
    GroundingValidator,
    InvestigationRepository,
    SecondaryAnalysisStatus,
    compute_analysis_grounding,
    derive_allowed_evidence_ids,
    parse_analysis_input_envelope,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _c(ctype, text, refs=()):
    """Shorthand for ClaimCandidate with keyword args."""
    return ClaimCandidate(claim_type=ctype, claim_text=text, evidence_refs=refs)


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


def _setup_running(tmp_path, related_paths=None):
    fdb = str(tmp_path / "files.db")
    idb = str(tmp_path / "investigation.db")
    rows = [{"path": "/case/report.docx", "llm_description": "PRIMARY", "size": 7}]
    for p in (related_paths or []):
        rows.append({"path": p, "llm_description": f"DESC_{p}", "size": 3})
    _make_files_db(fdb, rows)
    repo = InvestigationRepository(idb, "A")
    snap = repo.capture_if_absent(ResolvedEvidence(
        task_id="A", evidence_key="file:/case/report.docx", evidence_type="file",
        normalized_path="/case/report.docx", source_db=fdb,
    ))
    related_keys = []
    for p in (related_paths or []):
        repo.capture_if_absent(ResolvedEvidence(
            task_id="A", evidence_key=f"file:{p}", evidence_type="file",
            normalized_path=p, source_db=fdb,
        ))
        related_keys.append(f"file:{p}")
    analysis = repo.create_analysis(
        snap, related_evidence=tuple(related_keys),
        prompt_version="investigation-evidence-analysis:v2",
    )
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    return idb, repo, analysis, related_keys


PRIMARY = "file:/case/report.docx"
ALLOWED = frozenset({PRIMARY, "file:/case/other.txt"})


# ---------------------------------------------------------------------------
# GroundingValidator (pure function tests)
# ---------------------------------------------------------------------------

def test_all_valid_refs_grounded():
    vc = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.INFERENCE, "test", (PRIMARY, "file:/case/other.txt"))
    ])
    assert vc[0].grounding_status == ClaimGroundingStatus.GROUNDED
    assert len(vc[0].evidence_refs) == 2


def test_mixed_valid_invalid_partially_grounded():
    vc = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.INFERENCE, "test", (PRIMARY, "file:/fabricated"))
    ])
    assert vc[0].grounding_status == ClaimGroundingStatus.PARTIALLY_GROUNDED
    assert vc[0].evidence_refs == (PRIMARY,)
    assert vc[0].warnings["invalid_evidence_refs"] == ["file:/fabricated"]


def test_all_invalid_ungrounded():
    vc = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.INFERENCE, "test", ("file:/fake1", "file:/fake2"))
    ])
    assert vc[0].grounding_status == ClaimGroundingStatus.UNGROUNDED
    assert vc[0].evidence_refs == ()


def test_empty_refs_ungrounded():
    vc = GroundingValidator(ALLOWED).validate([_c(ClaimType.HYPOTHESIS, "guess")])
    assert vc[0].grounding_status == ClaimGroundingStatus.UNGROUNDED


def test_G7_fact_no_refs_downgrade():
    vc = GroundingValidator(ALLOWED).validate([_c(ClaimType.FACT, "no evidence")])
    assert vc[0].claim_type == ClaimType.HYPOTHESIS
    assert vc[0].grounding_status == ClaimGroundingStatus.UNGROUNDED
    assert vc[0].warnings.get("fact_without_evidence_refs") is True


def test_G7_fact_all_invalid_downgrade():
    vc = GroundingValidator(ALLOWED).validate([_c(ClaimType.FACT, "fake refs", ("file:/fake",))])
    assert vc[0].claim_type == ClaimType.HYPOTHESIS
    assert vc[0].grounding_status == ClaimGroundingStatus.UNGROUNDED
    assert vc[0].warnings.get("fact_all_refs_invalid") is True


def test_G7_fact_with_valid_refs_stays_fact():
    vc = GroundingValidator(ALLOWED).validate([_c(ClaimType.FACT, "real", (PRIMARY,))])
    assert vc[0].claim_type == ClaimType.FACT
    assert vc[0].grounding_status == ClaimGroundingStatus.GROUNDED


def test_inference_no_refs_not_downgraded():
    vc = GroundingValidator(ALLOWED).validate([_c(ClaimType.INFERENCE, "inferred")])
    assert vc[0].claim_type == ClaimType.INFERENCE


def test_duplicate_refs_dedup():
    vc = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.INFERENCE, "test", (PRIMARY, PRIMARY, PRIMARY))
    ])
    assert vc[0].evidence_refs == (PRIMARY,)
    assert vc[0].grounding_status == ClaimGroundingStatus.GROUNDED


def test_exact_match_no_canonicalize():
    vc = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.INFERENCE, "test", (r"file:\case\report.docx",))
    ])
    assert vc[0].evidence_refs == ()
    assert vc[0].grounding_status == ClaimGroundingStatus.UNGROUNDED


# ---------------------------------------------------------------------------
# compute_analysis_grounding
# ---------------------------------------------------------------------------

def test_aggregation_zero_claims_valid():
    assert compute_analysis_grounding([]) == AnalysisGroundingStatus.VALID


def test_aggregation_all_grounded_valid():
    claims = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.FACT, "c1", (PRIMARY,)),
        _c(ClaimType.FACT, "c2", ("file:/case/other.txt",)),
    ])
    assert compute_analysis_grounding(claims) == AnalysisGroundingStatus.VALID


def test_aggregation_all_ungrounded_invalid():
    claims = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.HYPOTHESIS, "c1"),
        _c(ClaimType.FACT, "c2"),  # downgraded
    ])
    assert compute_analysis_grounding(claims) == AnalysisGroundingStatus.INVALID


def test_aggregation_mixed_partially_grounded():
    claims = GroundingValidator(ALLOWED).validate([
        _c(ClaimType.FACT, "c1", (PRIMARY,)),  # grounded
        _c(ClaimType.HYPOTHESIS, "c2"),        # ungrounded
    ])
    assert compute_analysis_grounding(claims) == AnalysisGroundingStatus.PARTIALLY_GROUNDED


# ---------------------------------------------------------------------------
# derive_allowed_evidence_ids
# ---------------------------------------------------------------------------

def test_derive_allowed_v2(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path, related_paths=["/case/other.txt"])
    envelope = parse_analysis_input_envelope(
        repo.get_analysis(analysis.analysis_id).input_envelope_json
    )
    allowed = derive_allowed_evidence_ids(envelope)
    assert PRIMARY in allowed
    assert "file:/case/other.txt" in allowed
    assert len(allowed) == 2


def test_derive_allowed_v1():
    from httpserver.services.investigation import AnalysisInputEnvelopeV1
    envelope = AnalysisInputEnvelopeV1(
        evidence_snapshot={"evidence_key": PRIMARY},
        related_evidence=("file:/A", "file:/B"),
    )
    allowed = derive_allowed_evidence_ids(envelope)
    assert allowed == frozenset({PRIMARY, "file:/A", "file:/B"})


# ---------------------------------------------------------------------------
# persist_claims (G11-G13)
# ---------------------------------------------------------------------------

def test_persist_claims_normal(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path, related_paths=["/case/other.txt"])
    claims = repo.persist_claims(analysis.analysis_id, [
        _c(ClaimType.FACT, "found evidence", (PRIMARY,)),
        _c(ClaimType.INFERENCE, "likely related", ("file:/case/other.txt", "file:/fake")),
    ])
    assert len(claims) == 2
    assert claims[0].grounding_status == ClaimGroundingStatus.GROUNDED
    assert claims[1].grounding_status == ClaimGroundingStatus.PARTIALLY_GROUNDED
    assert claims[1].evidence_refs == ("file:/case/other.txt",)
    assert claims[1].warnings["invalid_evidence_refs"] == ["file:/fake"]
    assert repo.get_grounding_summary(analysis.analysis_id) == AnalysisGroundingStatus.PARTIALLY_GROUNDED


def test_persist_G12_write_once_rejects_second(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "first", (PRIMARY,))])
    with pytest.raises(ValueError, match="write-once"):
        repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "second", (PRIMARY,))])
    claims = repo.list_claims(analysis.analysis_id)
    assert len(claims) == 1
    assert claims[0].claim_text == "first"


def test_persist_G13_queued_rejected(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    snap = repo.get_snapshot(PRIMARY)
    queued = repo.create_analysis(snap, prompt_version="investigation-evidence-analysis:v2")
    with pytest.raises(ValueError, match="running status"):
        repo.persist_claims(queued.analysis_id, [_c(ClaimType.FACT, "x")])


def test_persist_G13_review_pending_rejected(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.review_pending)
    with pytest.raises(ValueError, match="running status"):
        repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "x")])


def test_persist_G13_terminal_rejected(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.failed,
                    error_code="E", error_message="m")
    with pytest.raises(ValueError, match="running status"):
        repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "x")])


def test_persist_G11_cannot_bypass_with_fabricated_ref(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    claims = repo.persist_claims(analysis.analysis_id, [
        _c(ClaimType.FACT, "fabricated", ("file:/totally-fake",)),
    ])
    assert claims[0].evidence_refs == ()
    assert claims[0].claim_type == ClaimType.HYPOTHESIS
    assert claims[0].grounding_status == ClaimGroundingStatus.UNGROUNDED


def test_persist_fact_downgrade_stored_as_hypothesis(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "no evidence fact")])
    db_claim = repo.list_claims(analysis.analysis_id)[0]
    assert db_claim.claim_type == ClaimType.HYPOTHESIS


# ---------------------------------------------------------------------------
# G14: DB immutability triggers
# ---------------------------------------------------------------------------

def test_G14_claim_no_update(tmp_path):
    idb, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "x", (PRIMARY,))])
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("UPDATE analysis_claims SET claim_text='hacked'")
    conn.close()


def test_G14_claim_no_delete(tmp_path):
    idb, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "x", (PRIMARY,))])
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("DELETE FROM analysis_claims")
    conn.close()


def test_G14_ref_no_update(tmp_path):
    idb, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "x", (PRIMARY,))])
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("UPDATE claim_evidence_refs SET evidence_key='hacked'")
    conn.close()


def test_G14_ref_no_delete(tmp_path):
    idb, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "x", (PRIMARY,))])
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("DELETE FROM claim_evidence_refs")
    conn.close()


# ---------------------------------------------------------------------------
# G10: grounding independent from review status
# ---------------------------------------------------------------------------

def test_G10_grounding_survives_review_lifecycle(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [_c(ClaimType.FACT, "grounded", (PRIMARY,))])
    assert repo.get_grounding_summary(analysis.analysis_id) == AnalysisGroundingStatus.VALID
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.review_pending)
    repo.review_analysis(
        analysis.analysis_id,
        decision=AnalysisReviewDecision.accepted,
        reviewer="analyst",
    )
    assert repo.get_grounding_summary(analysis.analysis_id) == AnalysisGroundingStatus.VALID


# ---------------------------------------------------------------------------
# get_grounding_summary semantics
# ---------------------------------------------------------------------------

def test_grounding_summary_nonexistent_raises(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    repo = InvestigationRepository(idb, "A")
    with pytest.raises(KeyError):
        repo.get_grounding_summary("nonexistent")


def test_grounding_summary_null_before_claims(tmp_path):
    _, repo, analysis, _ = _setup_running(tmp_path)
    assert repo.get_grounding_summary(analysis.analysis_id) is None


# ---------------------------------------------------------------------------
# v4 migration (v3 → v4)
# ---------------------------------------------------------------------------

def test_v4_migration_from_v3(tmp_path):
    """v3 DB (stripped claims) → reopen → latest (v5) with claims tables."""
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")  # creates latest
    # Strip to v3: drop claims objects + event objects, keep everything else
    conn = sqlite3.connect(idb)
    for t in ("trg_claim_refs_no_delete", "trg_claim_refs_no_update",
              "trg_claims_no_delete", "trg_claims_no_update",
              "trg_inv_events_no_identity_update",
              "trg_inv_event_versions_no_update", "trg_inv_event_versions_no_delete",
              "trg_inv_event_evidence_no_update", "trg_inv_event_evidence_no_delete"):
        conn.execute(f"DROP TRIGGER IF EXISTS {t}")
    conn.execute("DROP TABLE IF EXISTS claim_evidence_refs")
    conn.execute("DROP TABLE IF EXISTS analysis_claims")
    conn.execute("DROP TABLE IF EXISTS investigation_event_evidence")
    conn.execute("DROP TABLE IF EXISTS investigation_event_versions")
    conn.execute("DROP TABLE IF EXISTS investigation_events")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    # Reopen → triggers v3→v4→v5→v6 migration chain
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_claims'"
    ).fetchone() is not None
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='investigation_events'"
    ).fetchone() is not None
    for trigger in ("trg_claims_no_update", "trg_claims_no_delete",
                     "trg_claim_refs_no_update", "trg_claim_refs_no_delete"):
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", [trigger]
        ).fetchone() is not None
    conn.close()
