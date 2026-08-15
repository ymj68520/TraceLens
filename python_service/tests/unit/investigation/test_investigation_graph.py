"""Investigation Graph overlay reader + composition tests (Phase C8b).

Locks the frozen overlay contract: accepted-first task-level analysis
selection (G3/G5), explicit unconfirmed fallback (G4), exact persisted
Claim/Event provenance (G6/G7), no Event->Claim edge (G8), no Base KG merge
(G9), Base KG graceful degradation vs Investigation fail-closed (B3/G11),
zero-write reads (B2/G13), task isolation, and deterministic IDs (G12).
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    ResolvedEvidence,
)
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    ClaimCandidate,
    ClaimType,
    InvestigationGraphReader,
    InvestigationGraphService,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

KEY_A = "file:/case/a.txt"
KEY_B = "file:/case/b.txt"
OVERLAY_PREFIXES = ("event:", "analysis:", "claim:", "evidence:")


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _make_files_db(path, paths):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for p in paths:
        conn.execute(
            "INSERT INTO files (path,llm_description,size) VALUES (?,?,?)",
            (p, "D", 1),
        )
    conn.commit()
    conn.close()


def _store(tmp_path, task_id="A"):
    files_db = str(tmp_path / "files.db")
    _make_files_db(files_db, ["/case/a.txt", "/case/b.txt"])
    repo = InvestigationRepository(tmp_path / "investigation.db", task_id)
    return files_db, repo


def _capture(repo, files_db, key=KEY_A, task_id="A"):
    return repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id,
        evidence_key=key,
        evidence_type="file",
        normalized_path=key.removeprefix("file:"),
        source_db=files_db,
    ))


def _candidate(text="claim", refs=(KEY_A,)):
    return ClaimCandidate(
        claim_type=ClaimType.FACT, claim_text=text, evidence_refs=refs
    )


def _analysis(repo, snapshot, *, related=(), candidates=(_candidate(),),
              decision=None, summary="s"):
    """Drive the real state machine to a terminal or review_pending state."""
    analysis = repo.create_analysis(
        snapshot,
        prompt_version="investigation-evidence-analysis:v3",
        related_evidence=related,
    )
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="d", summary=summary, model="m",
        candidates=list(candidates),
    )
    if decision is not None:
        repo.review_analysis(
            analysis.analysis_id, decision=decision, reviewer="r", reason="ok"
        )
    return repo.get_analysis(analysis.analysis_id)


class _Backend:
    """Minimal trusted cpp_backend for graph composition tests."""

    def __init__(self, task_dir, task_id="A", exists=True):
        self._task_dir = Path(task_dir)
        self._task_id = task_id
        self._exists = exists

    async def get_task(self, task_id):
        if not self._exists or task_id != self._task_id:
            return None
        return {
            "id": task_id,
            "output_files_db": str(self._task_dir / "files.db"),
            "output_events_db": str(self._task_dir / "events.db"),
        }


class _Graphiti:
    """Fake Base KG source with optional failure injection."""

    def __init__(self, nodes=None, links=None, error=None):
        self.nodes = nodes or []
        self.links = links or []
        self.error = error
        self.calls = []

    async def get_graph_data(self, task_id, max_nodes):
        self.calls.append((task_id, max_nodes))
        if self.error is not None:
            raise self.error
        return self.nodes, self.links


def _service(task_dir, graphiti=None, provider=None):
    if provider is None:
        fake = graphiti if graphiti is not None else _Graphiti()
        provider = lambda: fake
    return InvestigationGraphService(
        cpp_backend=_Backend(task_dir), base_graph_provider=provider
    )


def _ids(nodes):
    return [n.id for n in nodes]


# ---------------------------------------------------------------------------
# reader: selection semantics (G3/G5)
# ---------------------------------------------------------------------------

def test_selection_accepted_wins_over_newer_pending_and_rejected(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    v1 = _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    _analysis(repo, snap, decision=AnalysisReviewDecision.rejected)
    _analysis(repo, snap)  # newest, but only review_pending

    result = InvestigationGraphReader(tmp_path / "investigation.db", "A").read()
    assert len(result.selections) == 1
    selection = result.selections[0]
    assert selection.analysis_id == v1.analysis_id
    assert selection.version == v1.version == 1
    assert selection.review_state == "accepted"
    assert selection.evidence_key == KEY_A


def test_selection_pending_fallback_only_without_accepted(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    _analysis(repo, snap, decision=AnalysisReviewDecision.rejected)
    pending = _analysis(repo, snap)

    result = InvestigationGraphReader(tmp_path / "investigation.db", "A").read()
    selection = result.selections[0]
    assert selection.analysis_id == pending.analysis_id
    assert selection.version == 2
    assert selection.review_state == "review_pending"


def test_selection_empty_without_accepted_or_pending(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    _analysis(repo, snap, decision=AnalysisReviewDecision.rejected)
    repo.create_analysis(snap)  # stays queued

    result = InvestigationGraphReader(tmp_path / "investigation.db", "A").read()
    assert result.selections == ()
    assert repo.list_analyses(KEY_A)  # rows exist; emptiness is a selection fact


def test_selection_is_task_level_not_event_anchored(tmp_path):
    # B1: an accepted analysis with no Event link must still be selected.
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    accepted = _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    repo.create_event(title="unrelated event")

    result = InvestigationGraphReader(tmp_path / "investigation.db", "A").read()
    assert result.selections[0].analysis_id == accepted.analysis_id


def test_claims_read_only_from_selected_analysis(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    accepted = _analysis(
        repo, snap, candidates=[_candidate("accepted claim")],
        decision=AnalysisReviewDecision.accepted,
    )
    _analysis(repo, snap, candidates=[_candidate("pending claim")])

    result = InvestigationGraphReader(tmp_path / "investigation.db", "A").read()
    assert len(result.claims) == 1
    assert result.claims[0].analysis_id == accepted.analysis_id
    assert result.claims[0].claim_text == "accepted claim"


def test_events_included_without_evidence_links(tmp_path):
    files_db, repo = _store(tmp_path)
    event = repo.create_event(title="孤立事件", summary="no links yet")

    result = InvestigationGraphReader(tmp_path / "investigation.db", "A").read()
    assert [e.event_id for e in result.events] == [event.event_id]
    assert result.event_links == ()


def test_reader_task_isolation_on_shared_store(tmp_path):
    files_db, repo_a = _store(tmp_path, task_id="A")
    snap_a = _capture(repo_a, files_db, KEY_A, task_id="A")
    _analysis(repo_a, snap_a, decision=AnalysisReviewDecision.accepted)

    repo_b = InvestigationRepository(tmp_path / "investigation.db", "B")
    snap_b = _capture(repo_b, files_db, KEY_A, task_id="B")
    accepted_b = _analysis(repo_b, snap_b, decision=AnalysisReviewDecision.accepted)

    result = InvestigationGraphReader(tmp_path / "investigation.db", "B").read()
    assert [s.analysis_id for s in result.selections] == [accepted_b.analysis_id]
    assert result.events == ()
    for claim in result.claims:
        assert claim.analysis_id == accepted_b.analysis_id


# ---------------------------------------------------------------------------
# reader: fail-closed store semantics (B3) + zero-write (B2/G13)
# ---------------------------------------------------------------------------

def test_reader_never_modifies_store_bytes(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    repo.create_event(title="事件")
    db_path = tmp_path / "investigation.db"
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    InvestigationGraphReader(db_path, "A").read()

    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_reader_corrupt_store_fails_closed(tmp_path):
    (tmp_path / "investigation.db").write_bytes(b"definitely not a sqlite db")
    with pytest.raises(EvidenceStoreError):
        InvestigationGraphReader(tmp_path / "investigation.db", "A").read()


def test_reader_unsupported_schema_version_fails_closed(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    db_path = tmp_path / "investigation.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    with pytest.raises(EvidenceStoreError):
        InvestigationGraphReader(db_path, "A").read()


def test_reader_missing_store_fails_closed_without_creating(tmp_path):
    db_path = tmp_path / "investigation.db"
    with pytest.raises(EvidenceStoreError):
        InvestigationGraphReader(db_path, "A").read()
    assert not db_path.exists()


# ---------------------------------------------------------------------------
# composition: node/edge shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compose_overlay_and_base(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    _capture(repo, files_db, KEY_B)
    accepted = _analysis(
        repo, snap_a,
        related=(KEY_B,),
        candidates=[_candidate("覆盖 A 与 B", refs=(KEY_A, KEY_B))],
        decision=AnalysisReviewDecision.accepted,
    )
    event = repo.create_event(title="事件", summary="叙述")
    repo.link_event_evidence(event.event_id, KEY_A)
    graphiti = _Graphiti(
        nodes=[
            {"id": "uuid-1", "name": "malware.exe", "label": "Entity", "summary": "s"},
            # Same display name as the Evidence node -- still separate (G9).
            {"id": "uuid-2", "name": KEY_A, "label": "Entity", "summary": ""},
        ],
        links=[{"source": "uuid-1", "target": "uuid-2", "label": "USES"}],
    )

    response = await _service(tmp_path, graphiti).get_graph(
        "A", max_base_nodes=500
    )

    assert response.task_id == "A"
    assert response.base_graph_available is True
    assert response.base_max_nodes == 500
    assert response.warnings == ()
    assert graphiti.calls == [("A", 500)]

    assert set(_ids(response.nodes)) >= {
        f"analysis:{accepted.analysis_id}",
        f"evidence:{KEY_A}",
        f"evidence:{KEY_B}",
        f"event:{event.event_id}",
        "uuid-1",
        "uuid-2",
    }
    claim_nodes = [n for n in response.nodes if n.id.startswith("claim:")]
    assert len(claim_nodes) == 1
    assert claim_nodes[0].confirmed is True
    assert claim_nodes[0].provenance["claim_type"] == "FACT"
    assert claim_nodes[0].provenance["grounding_status"] == "grounded"

    analysis_node = next(
        n for n in response.nodes if n.id == f"analysis:{accepted.analysis_id}"
    )
    assert analysis_node.confirmed is True
    assert analysis_node.provenance["review_state"] == "accepted"
    assert analysis_node.provenance["version"] == 1

    evidence_node = next(n for n in response.nodes if n.id == f"evidence:{KEY_A}")
    assert evidence_node.confirmed is None  # never inherits review state
    assert evidence_node.provenance == {
        "evidence_key": KEY_A, "evidence_type": "file",
    }

    kinds = {link.kind for link in response.links}
    assert kinds == {
        "base_relation", "event_evidence", "analysis_evidence",
        "analysis_claim", "claim_evidence",
    }
    base_link = next(l for l in response.links if l.kind == "base_relation")
    assert base_link.id == "base:uuid-1:USES:uuid-2"
    claim_evidence_targets = {
        l.target for l in response.links if l.kind == "claim_evidence"
    }
    assert claim_evidence_targets == {f"evidence:{KEY_A}", f"evidence:{KEY_B}"}

    # No cross-namespace edge: overlay subgraph and Base KG stay disjoint.
    for link in response.links:
        source_overlay = link.source.startswith(OVERLAY_PREFIXES)
        target_overlay = link.target.startswith(OVERLAY_PREFIXES)
        assert source_overlay == target_overlay
    # No Event->Claim edge may ever be synthesized (G8).
    for link in response.links:
        assert not link.source.startswith("event:") or not link.target.startswith("claim:")
        assert not link.source.startswith("claim:") or not link.target.startswith("event:")


@pytest.mark.asyncio
async def test_pending_fallback_is_explicitly_unconfirmed(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    pending = _analysis(repo, snap, candidates=[_candidate("待审")] + [])

    response = await _service(tmp_path).get_graph("A")

    analysis_node = next(
        n for n in response.nodes if n.id == f"analysis:{pending.analysis_id}"
    )
    assert analysis_node.confirmed is False
    assert analysis_node.provenance["review_state"] == "review_pending"
    claim_node = next(n for n in response.nodes if n.id.startswith("claim:"))
    assert claim_node.confirmed is False


@pytest.mark.asyncio
async def test_empty_claims_analysis_still_anchored_by_analysis_evidence(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    accepted = _analysis(
        repo, snap, candidates=[],
        decision=AnalysisReviewDecision.accepted,
    )

    response = await _service(tmp_path).get_graph("A")

    assert [n.id for n in response.nodes if n.id.startswith("claim:")] == []
    links = [
        l for l in response.links
        if l.source == f"analysis:{accepted.analysis_id}"
    ]
    assert [l.kind for l in links] == ["analysis_evidence"]
    assert links[0].target == f"evidence:{KEY_A}"


@pytest.mark.asyncio
async def test_shared_evidence_one_node_all_relations_kept(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    accepted = _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    e1 = repo.create_event(title="同名事件")
    e2 = repo.create_event(title="同名事件")  # same title, distinct identity
    repo.link_event_evidence(e1.event_id, KEY_A)
    repo.link_event_evidence(e2.event_id, KEY_A)

    response = await _service(tmp_path).get_graph("A")

    evidence_nodes = [n for n in response.nodes if n.id == f"evidence:{KEY_A}"]
    assert len(evidence_nodes) == 1
    event_nodes = [n for n in response.nodes if n.id.startswith("event:")]
    assert len(event_nodes) == 2  # same title never merges events
    event_evidence = [l for l in response.links if l.kind == "event_evidence"]
    assert len(event_evidence) == 2
    assert {l.source for l in event_evidence} == {
        f"event:{e1.event_id}", f"event:{e2.event_id}",
    }
    claim_ids = [n.id.split(":", 1)[1] for n in response.nodes
                 if n.id.startswith("claim:")]
    assert len(claim_ids) == 1
    assert {l.id for l in response.links} == {
        f"event_evidence:{e1.event_id}:{KEY_A}",
        f"event_evidence:{e2.event_id}:{KEY_A}",
        f"analysis_evidence:{accepted.analysis_id}:{KEY_A}",
        f"analysis_claim:{accepted.analysis_id}:{claim_ids[0]}",
        f"claim_evidence:{claim_ids[0]}:{KEY_A}",
    }


@pytest.mark.asyncio
async def test_same_claim_text_distinct_claim_nodes(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    snap_b = _capture(repo, files_db, KEY_B)
    _analysis(
        repo, snap_a, candidates=[_candidate("相同断言")],
        decision=AnalysisReviewDecision.accepted,
    )
    _analysis(
        repo, snap_b, candidates=[_candidate("相同断言", refs=(KEY_B,))],
        decision=AnalysisReviewDecision.accepted,
    )

    response = await _service(tmp_path).get_graph("A")

    claim_nodes = [n for n in response.nodes if n.id.startswith("claim:")]
    assert len(claim_nodes) == 2
    assert {n.name for n in claim_nodes} == {"相同断言"}
    assert len({n.id for n in claim_nodes}) == 2


# ---------------------------------------------------------------------------
# composition: degradation vs fail-closed (B3/G11)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_base_failure_degrades_gracefully(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    accepted = _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    graphiti = _Graphiti(error=RuntimeError("neo4j://secret@10.0.0.9:7687 unreachable"))

    response = await _service(tmp_path, graphiti).get_graph("A")

    assert response.base_graph_available is False
    assert response.warnings == ("base_graph_unavailable",)
    payload = response.model_dump_json()
    assert "neo4j" not in payload
    assert "secret" not in payload
    # Overlay survives the Base KG outage.
    assert f"analysis:{accepted.analysis_id}" in _ids(response.nodes)


@pytest.mark.asyncio
async def test_base_provider_failure_degrades(tmp_path):
    def _provider():
        raise RuntimeError("ServiceManager is not initialized")

    response = await _service(tmp_path, provider=_provider).get_graph("A")
    assert response.base_graph_available is False
    assert response.warnings == ("base_graph_unavailable",)


@pytest.mark.asyncio
async def test_missing_store_empty_overlay_and_no_creation(tmp_path):
    files_db = str(tmp_path / "files.db")
    _make_files_db(files_db, ["/case/a.txt"])
    graphiti = _Graphiti(
        nodes=[{"id": "uuid-1", "name": "n", "label": "Entity", "summary": None}],
    )

    response = await _service(tmp_path, graphiti).get_graph("A")

    assert response.base_graph_available is True
    assert _ids(response.nodes) == ["uuid-1"]
    assert response.links == ()
    assert not (tmp_path / "investigation.db").exists()


@pytest.mark.asyncio
async def test_corrupt_store_fails_closed_not_base_only(tmp_path):
    files_db = str(tmp_path / "files.db")
    _make_files_db(files_db, ["/case/a.txt"])
    (tmp_path / "investigation.db").write_bytes(b"corrupted store")
    graphiti = _Graphiti(
        nodes=[{"id": "uuid-1", "name": "n", "label": "Entity", "summary": None}],
    )

    with pytest.raises(EvidenceStoreError):
        await _service(tmp_path, graphiti).get_graph("A")


@pytest.mark.asyncio
async def test_task_not_found(tmp_path):
    with pytest.raises(EvidenceNotFoundError):
        await _service(tmp_path).get_graph("missing-task")


@pytest.mark.asyncio
async def test_backend_missing_task_fails_not_found(tmp_path):
    service = InvestigationGraphService(
        cpp_backend=_Backend(tmp_path, exists=False),
        base_graph_provider=lambda: _Graphiti(),
    )
    with pytest.raises(EvidenceNotFoundError):
        await service.get_graph("A")


# ---------------------------------------------------------------------------
# composition: determinism + base bounds (B4/G12)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deterministic_ids_across_consecutive_reads(tmp_path):
    files_db, repo = _store(tmp_path)
    snap_a = _capture(repo, files_db, KEY_A)
    _capture(repo, files_db, KEY_B)
    _analysis(
        repo, snap_a, related=(KEY_B,),
        candidates=[_candidate("c", refs=(KEY_A, KEY_B))],
        decision=AnalysisReviewDecision.accepted,
    )
    event = repo.create_event(title="事件")
    repo.link_event_evidence(event.event_id, KEY_A)
    graphiti = _Graphiti(
        nodes=[
            {"id": "uuid-1", "name": "x", "label": "Entity", "summary": None},
            {"id": "uuid-2", "name": "y", "label": "Entity", "summary": None},
        ],
        links=[{"source": "uuid-1", "target": "uuid-2", "label": "RELATES_TO"}],
    )
    service = _service(tmp_path, graphiti)

    first = await service.get_graph("A")
    second = await service.get_graph("A")

    assert _ids(first.nodes) == _ids(second.nodes)
    assert [l.id for l in first.links] == [l.id for l in second.links]
    assert first == second


@pytest.mark.asyncio
async def test_max_base_nodes_bounds_base_read_only(tmp_path):
    files_db, repo = _store(tmp_path)
    snap = _capture(repo, files_db)
    _analysis(repo, snap, decision=AnalysisReviewDecision.accepted)
    graphiti = _Graphiti(
        nodes=[{"id": "uuid-1", "name": "n", "label": "Entity", "summary": None}],
    )

    response = await _service(tmp_path, graphiti).get_graph(
        "A", max_base_nodes=7
    )

    assert graphiti.calls == [("A", 7)]
    assert response.base_max_nodes == 7
    # The overlay is never truncated by the base cap (B4).
    assert any(n.id == f"evidence:{KEY_A}" for n in response.nodes)
    assert any(n.id.startswith("analysis:") for n in response.nodes)
