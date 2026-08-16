"""Phase R2c: report generation execution & citation validation (§25-§28).

The executor consumes ONLY the persisted frozen envelope, re-verifies its
hash, validates every emitted citation against the exact frozen identities,
and publishes body+manifest as one artifact before allocating the report
version in the completion transaction. Failures never leave a
Viewer-visible version; restart/shutdown fail stale rows durably.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.forensic_report.generation import (
    REPORT_GENERATION_PROMPT_VERSION,
    ReportGenerationInputBuilder,
)
from httpserver.services.forensic_report.generation_execution import (
    ReportCitationInvalidError,
    ReportGenerationExecutor,
    build_citation_manifest,
    validate_report_citations,
)
from httpserver.services.forensic_report.generation_prompts import (
    build_report_generation_user_prompt,
    get_report_generation_prompt,
)
from httpserver.services.forensic_report.generation_structured import (
    StructuredReportOutputError,
    parse_structured_report_response,
)
from httpserver.services.forensic_report.generation_writer import (
    GenerationReportWriter,
)
from httpserver.services.forensic_report.models import (
    EnvelopeBoundAnalysisReviewV1,
    EnvelopeBoundAnalysisV1,
    EnvelopeClaimV1,
    EnvelopeEvidenceItemV1,
    EnvelopeSnapshotV1,
    ReportGenerationEnvelopeV1,
    ScopeType,
    StructuredReportCitation,
    StructuredReportResponse,
    StructuredReportSection,
)
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    ClaimCandidate,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)
from httpserver.services.investigation.acquisition import canonical_json
from httpserver.services.investigation.models import (
    ClaimGroundingStatus,
    ClaimType,
    FileSnapshotPayload,
    ReportEvidenceStatus,
)

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"
OTHER_KEY = "file:/case/b.txt"


# ---------------------------------------------------------------------------
# Scaffolding (mirrors the R2b admission tests)
# ---------------------------------------------------------------------------


def _make_files_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for file_path in ("/case/a.txt", "/case/b.txt"):
        conn.execute(
            "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
            (file_path, "d", 1),
        )
    conn.commit()
    conn.close()


def _repo_with_binding(tmp_path: Path, task_id: str = "A"):
    """A task store with KEY captured, an accepted bound analysis with one
    claim (refs KEY+OTHER_KEY), and KEY bound as main report evidence."""
    root = tmp_path / task_id
    root.mkdir(parents=True, exist_ok=True)
    files_db = str(root / "files.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(root / "investigation.db", task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    other = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=OTHER_KEY, evidence_type="file",
        normalized_path="/case/b.txt", source_db=files_db,
    ))
    del other
    analysis = repo.create_analysis(
        snapshot, prompt_version=PROMPT_V3, related_evidence=(OTHER_KEY,)
    )
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="d", summary="s", model="analysis-model",
        candidates=[ClaimCandidate(
            claim_type="FACT", claim_text="c",
            evidence_refs=(KEY, OTHER_KEY),
        )],
    )
    repo.review_analysis(
        analysis.analysis_id,
        decision=AnalysisReviewDecision.accepted,
        reviewer="analyst-x",
    )
    accepted = repo.get_analysis(analysis.analysis_id)
    claim = repo.list_claims(analysis.analysis_id)[0]
    repo.add_report_evidence(
        KEY, report_status="main", analysis_id=accepted.analysis_id,
        added_by="analyst-x",
    )
    return root, repo, accepted, claim


def _admit(
    repository: ReportRepository, root: Path, task_id: str = "A",
    *, prompt_version: str = REPORT_GENERATION_PROMPT_VERSION,
    input_hash: str | None = None,
):
    import hashlib

    envelope = ReportGenerationInputBuilder(
        root / "investigation.db", task_id
    ).assemble(prompt_version)
    envelope_json = canonical_json(envelope)
    digest = input_hash or hashlib.sha256(
        envelope_json.encode("utf-8")
    ).hexdigest()
    return repository.create_generation_input(
        task_id, requested_by="analyst-x",
        input_schema_version=envelope.schema_version,
        prompt_version=prompt_version,
        input_envelope_json=envelope_json, input_hash=digest,
    )


class FakeLLM:
    def __init__(self, content: str, model: str = "test-model", error=None):
        self.content = content
        self.model = model
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def chat_completion(self, system: str, user: str):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return {"model": self.model, "content": self.content}


class BlockingLLM:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat_completion(self, system: str, user: str):
        self.started.set()
        await self.release.wait()
        return {"model": "blocked-model", "content": "{}"}


def _valid_report_json(citation) -> str:
    return json.dumps({
        "title": "最终报告",
        "sections": [{
            "heading": "H", "content": "C",
            "citation_ids": [citation["citation_id"]],
        }],
        "citations": [citation],
    }, ensure_ascii=False)


def _a_citation(analysis_id: str | None, claim_id: str | None = None) -> dict:
    return {
        "citation_id": "cit_1", "evidence_key": KEY,
        "analysis_id": analysis_id, "claim_id": claim_id,
    }


def _make_executor(tmp_path: Path, llm) -> tuple[ReportRepository, ReportGenerationExecutor]:
    repository = ReportRepository(tmp_path / "reports.db")
    executor = ReportGenerationExecutor(
        repository=repository,
        writer=GenerationReportWriter(tmp_path / "report_root"),
        llm_service=llm,
    )
    return repository, executor


async def _wait_terminal(repository: ReportRepository, generation_id: str, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = repository.get_generation_input(generation_id)
        if row.status in ("completed", "failed"):
            return row
        await asyncio.sleep(0.01)
    raise AssertionError("generation did not terminate in time")


def _count_versions(repository: ReportRepository) -> int:
    with sqlite3.connect(repository.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM report_versions").fetchone()[0]


# ---------------------------------------------------------------------------
# §25: execution
# ---------------------------------------------------------------------------


def test_happy_path_completes_and_publishes(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM(
            _valid_report_json(_a_citation(accepted.analysis_id, claim.claim_id))
        ))
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return repository, row, terminal

    repository, row, terminal = asyncio.run(scenario())

    assert terminal.status == "completed"
    assert terminal.produced_version == 1
    assert terminal.report_id is not None
    assert terminal.model == "test-model"
    version = repository.get(terminal.report_id)
    assert version.status == "ready"
    assert version.task_ids == ["A"]

    writer = GenerationReportWriter(tmp_path / "report_root")
    manifest = writer.read_manifest("A", terminal.report_id)
    assert manifest["generation_id"] == row.generation_id
    assert manifest["input_hash"] == row.input_hash
    assert manifest["title"] == "最终报告"
    entry = manifest["citations"][0]
    assert entry["evidence_key"] == KEY
    assert entry["analysis_id"] == accepted.analysis_id
    assert entry["claim_id"] == claim.claim_id
    assert entry["claim_type"] == "FACT"
    assert isinstance(entry["evidence_captured_at"], int)
    assert entry["analysis_version"] == accepted.version


def test_llm_timeout_fails_without_version(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM(
            "", error=httpx.ReadTimeout("t")
        ))
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return repository, terminal

    repository, terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "llm_timeout"
    assert terminal.report_id is None
    assert _count_versions(repository) == 0
    assert not (tmp_path / "report_root" / "snapshots").exists()


def test_dual_claim_runs_llm_exactly_once(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        llm = FakeLLM(_valid_report_json(_a_citation(accepted.analysis_id, claim.claim_id)))
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit(repository, root)
        await asyncio.gather(
            executor._execute(row.generation_id),
            executor._execute(row.generation_id),
        )
        return llm, repository.get_generation_input(row.generation_id)

    llm, final = asyncio.run(scenario())
    assert len(llm.calls) == 1  # loser never calls the LLM
    assert final.status == "completed"


def test_hash_mismatch_fails_integrity_without_version(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM("{}"))
        row = _admit(repository, root, input_hash="0" * 64)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return repository, terminal

    repository, terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "input_integrity_error"
    assert _count_versions(repository) == 0


def test_unknown_prompt_contract_fails(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM("{}"))
        row = _admit(repository, root, prompt_version="final-report:vX")
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal

    terminal = asyncio.run(scenario())
    assert terminal.error_code == "unsupported_input_contract"


def test_empty_llm_response_fails_with_model_audit(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM(""))
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal

    terminal = asyncio.run(scenario())
    assert terminal.error_code == "llm_empty_response"
    assert terminal.model == "test-model"  # execution audit metadata kept


def test_llm_unavailable_fails_durably(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, None)
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal

    terminal = asyncio.run(scenario())
    assert terminal.error_code == "llm_unavailable"


def test_user_prompt_is_exactly_the_persisted_envelope(tmp_path):
    """R2C1/R2C2 + §25-5/6: rebinding or adding evidence after admission
    cannot change what the LLM sees."""
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        llm = FakeLLM(_valid_report_json(_a_citation(accepted.analysis_id, claim.claim_id)))
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        await _wait_terminal(repository, row.generation_id)
        # Mutate R1 state after the fact: rebind + add new main evidence.
        a2 = repo.create_analysis(
            repo.get_snapshot(KEY), prompt_version=PROMPT_V3
        )
        repo.transition(a2.analysis_id, SecondaryAnalysisStatus.running)
        repo.complete_analysis_for_review(
            a2.analysis_id, description="d2", summary="s2", model="m2",
            candidates=[ClaimCandidate(claim_type="FACT", claim_text="c2")],
        )
        repo.review_analysis(
            a2.analysis_id, decision=AnalysisReviewDecision.accepted,
            reviewer="analyst-x",
        )
        repo.update_report_evidence(
            KEY, analysis_id=repo.get_analysis(a2.analysis_id).analysis_id,
            bind_analysis=True, updated_by="analyst-x",
        )
        repo.add_report_evidence(OTHER_KEY, report_status="main", added_by="x")
        await executor.shutdown()
        return llm, row

    llm, row = asyncio.run(scenario())
    system_prompt, user_template = get_report_generation_prompt(
        REPORT_GENERATION_PROMPT_VERSION
    )
    expected = build_report_generation_user_prompt(
        user_template,
        ReportGenerationEnvelopeV1.model_validate_json(row.input_envelope_json),
    )
    assert llm.calls == [(system_prompt, expected)]
    # The frozen allowed boundary and evidence lists exclude the newly
    # added B; OTHER_KEY can only appear as historical claim provenance.
    assert f'"allowed_report_evidence_ids":["{KEY}"]' in llm.calls[0][1]
    assert '"appendix_evidence":[]' in llm.calls[0][1]
    assert f'{{"evidence_key":"{OTHER_KEY}","report_status"' not in llm.calls[0][1]


def test_original_only_envelope_has_null_binding(tmp_path):
    root = tmp_path / "A"
    root.mkdir(parents=True)
    files_db = str(root / "files.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(root / "investigation.db", "A")
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id="A", evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s", model="m",
        candidates=[ClaimCandidate(claim_type="FACT", claim_text="c")],
    )
    repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted,
        reviewer="analyst-x",
    )
    repo.add_report_evidence(KEY, report_status="main", added_by="x")

    async def scenario():
        llm = FakeLLM(_valid_report_json(_a_citation(None)))
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return llm, terminal

    llm, terminal = asyncio.run(scenario())
    assert terminal.status == "completed"
    # The unbound accepted analysis never leaks into the LLM input.
    assert '"bound_analysis":null' in llm.calls[0][1]


# ---------------------------------------------------------------------------
# §25-10: strict parser
# ---------------------------------------------------------------------------


def _minimal_payload(**overrides) -> dict:
    payload = {
        "title": "T",
        "sections": [{"heading": "H", "content": "C", "citation_ids": ["cit_1"]}],
        "citations": [{
            "citation_id": "cit_1", "evidence_key": KEY,
            "analysis_id": None, "claim_id": None,
        }],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("content", [
    "```json\n" + json.dumps(_minimal_payload()) + "\n```",  # fence
    "prefix " + json.dumps(_minimal_payload()) + " suffix",  # embedded JSON
    json.dumps(_minimal_payload()).replace(
        '"title": "T"', '"title": "T", "title": "T2"', 1
    ).replace("{", "{ ", 1),  # duplicate key (re-serialized keeps both)
    '{"title": NaN, "sections": [], "citations": []}',  # NaN
    json.dumps({**_minimal_payload(), "extra": 1}),  # extra field
    json.dumps(_minimal_payload(sections=[], )),  # empty required sections
    json.dumps({
        "title": "T",
        "sections": [{"heading": "H", "content": "C", "citation_ids": ["ghost"]}],
        "citations": _minimal_payload()["citations"],
    }),  # unknown citation reference
    "[]",  # top-level non-object
    "",
])
def test_strict_parser_rejects_malformed_output(content):
    with pytest.raises(StructuredReportOutputError):
        parse_structured_report_response(content)


def test_strict_parser_accepts_valid_output():
    response = parse_structured_report_response(json.dumps(_minimal_payload()))
    assert response.title == "T"
    assert response.citations[0].evidence_key == KEY


def test_executor_marks_structured_output_invalid(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        fenced = "```json\n{}\n```"
        repository, executor = _make_executor(tmp_path, FakeLLM(fenced))
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal

    terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "structured_output_invalid"
    assert terminal.model == "test-model"


# ---------------------------------------------------------------------------
# §26: citation validation (envelope boundary only, no live lookups)
# ---------------------------------------------------------------------------


def _claim(cid: str, refs: tuple[str, ...] = ()) -> EnvelopeClaimV1:
    return EnvelopeClaimV1(
        claim_id=cid, claim_index=1, claim_type=ClaimType.FACT,
        claim_text="same text", grounding_status=ClaimGroundingStatus.GROUNDED,
        evidence_refs=refs, created_at="2026",
    )


def _item(key: str, bound: EnvelopeBoundAnalysisV1 | None) -> EnvelopeEvidenceItemV1:
    return EnvelopeEvidenceItemV1(
        evidence_key=key, report_status=ReportEvidenceStatus.main,
        snapshot=EnvelopeSnapshotV1(
            task_id="A", evidence_key=key, evidence_type="file", captured_at=7,
            payload=FileSnapshotPayload(normalized_path=key.removeprefix("file:")),
        ),
        bound_analysis=bound,
    )


def _bound(analysis_id: str, claims: tuple[EnvelopeClaimV1, ...]) -> EnvelopeBoundAnalysisV1:
    return EnvelopeBoundAnalysisV1(
        analysis_id=analysis_id, version=1, review=EnvelopeBoundAnalysisReviewV1(),
        claims=claims,
    )


def _envelope(items, allowed=None) -> ReportGenerationEnvelopeV1:
    keys = sorted({item.evidence_key for item in items})
    return ReportGenerationEnvelopeV1(
        prompt_version=REPORT_GENERATION_PROMPT_VERSION, task_id="A",
        main_evidence=tuple(items),
        allowed_report_evidence_ids=tuple(allowed if allowed is not None else keys),
    )


def _response(citations) -> StructuredReportResponse:
    return StructuredReportResponse(
        title="T",
        sections=(StructuredReportSection(
            heading="H", content="C",
            citation_ids=tuple(c.citation_id for c in citations),
        ),),
        citations=tuple(citations),
    )


def _citation(key, analysis_id=None, claim_id=None) -> StructuredReportCitation:
    return StructuredReportCitation(
        citation_id="cit_1", evidence_key=key,
        analysis_id=analysis_id, claim_id=claim_id,
    )


def test_citation_within_boundary_passes():
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1"),)))])
    validate_report_citations(
        _response([_citation(KEY, "A1", "C1")]), envelope
    )


def test_citation_of_unselected_evidence_is_invalid():
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1"),)))])
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(OTHER_KEY)]), envelope)


def test_citation_analysis_on_original_only_is_invalid():
    envelope = _envelope([_item(KEY, None)])
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(KEY, "A1")]), envelope)


def test_citation_of_newer_accepted_analysis_is_invalid():
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1"),)))])
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(KEY, "A2")]), envelope)


def test_citation_claim_without_analysis_is_invalid():
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1"),)))])
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(KEY, None, "C1")]), envelope)


def test_citation_claim_matched_by_exact_id_not_text():
    # C1 and C2 share claim_text; only C1 is in the frozen analysis.
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1"),)))])
    validate_report_citations(_response([_citation(KEY, "A1", "C1")]), envelope)
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(KEY, "A1", "C2")]), envelope)


def test_claim_external_ref_does_not_widen_citation_boundary():
    # Claim refs [A, B] but the report set is only A: citing B is invalid.
    envelope = _envelope(
        [_item(KEY, _bound("A1", (_claim("C1", (KEY, OTHER_KEY)),)))]
    )
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(OTHER_KEY)]), envelope)


def test_unknown_claim_is_invalid():
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1"),)))])
    with pytest.raises(ReportCitationInvalidError):
        validate_report_citations(_response([_citation(KEY, "A1", "ghost")]), envelope)


def test_manifest_entries_carry_exact_frozen_identity():
    envelope = _envelope([_item(KEY, _bound("A1", (_claim("C1", (KEY, OTHER_KEY)),)))])
    response = _response([_citation(KEY, "A1", "C1")])
    entries = build_citation_manifest(response, envelope)
    assert len(entries) == 1
    assert entries[0].claim_id == "C1"
    assert entries[0].analysis_version == 1
    assert entries[0].claim_type == ClaimType.FACT
    assert entries[0].evidence_captured_at == 7


# ---------------------------------------------------------------------------
# §27: publication & version
# ---------------------------------------------------------------------------


def test_old_versions_unchanged_and_versions_unique(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository = ReportRepository(tmp_path / "reports.db")
        legacy = repository.create_version(
            ScopeType.TASK, "A", "legacy", ["A"]
        )
        repository.mark_ready(legacy.report_id, "/legacy/manifest", [])
        llm = FakeLLM(_valid_report_json(_a_citation(accepted.analysis_id, claim.claim_id)))
        repository, executor = _make_executor(tmp_path, llm)
        row1 = _admit(repository, root)
        row2 = _admit(repository, root)
        await executor.submit(row1.generation_id)
        await executor.submit(row2.generation_id)
        t1 = await _wait_terminal(repository, row1.generation_id)
        t2 = await _wait_terminal(repository, row2.generation_id)
        await executor.shutdown()
        return repository, legacy, t1, t2

    repository, legacy, t1, t2 = asyncio.run(scenario())
    assert t1.produced_version != t2.produced_version
    assert {t1.produced_version, t2.produced_version} == {2, 3}
    old = repository.get(legacy.report_id)
    assert old.status == "ready"
    assert old.manifest_path == "/legacy/manifest"
    assert old.version == 1


def test_failure_after_publish_before_completion_is_invisible(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM(
            _valid_report_json(_a_citation(accepted.analysis_id, claim.claim_id))
        ))
        row = _admit(repository, root)
        real = repository.complete_generation_publication

        def explode(*args, **kwargs):
            raise RuntimeError("injected completion failure")

        repository.complete_generation_publication = explode
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        repository.complete_generation_publication = real
        await executor.shutdown()
        return repository, terminal

    repository, terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "publication_error"
    assert terminal.report_id is None
    assert _count_versions(repository) == 0  # no externally visible version


def test_writer_failure_is_publication_error(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM(
            _valid_report_json(_a_citation(accepted.analysis_id, claim.claim_id))
        ))
        row = _admit(repository, root)

        def explode(**kwargs):
            raise OSError("injected writer failure")

        executor._writer.publish = explode
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return repository, terminal

    repository, terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "publication_error"
    assert terminal.report_id is None
    assert _count_versions(repository) == 0


# ---------------------------------------------------------------------------
# §28: lifecycle
# ---------------------------------------------------------------------------


def test_restart_recovery_fails_stale_and_keeps_terminal(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM("{}"))
        admitted = _admit(repository, root)
        running = _admit(repository, root)
        repository.claim_generation(running.generation_id)
        terminal = _admit(repository, root)
        repository.fail_generation(
            terminal.generation_id, error_code="llm_timeout",
            error_message="LLM request timed out",
        )
        await executor.initialize()
        return (
            repository.get_generation_input(admitted.generation_id),
            repository.get_generation_input(running.generation_id),
            repository.get_generation_input(terminal.generation_id),
        )

    a, r, t = asyncio.run(scenario())
    assert (a.status, a.error_code) == ("failed", "service_restart")
    assert (r.status, r.error_code) == ("failed", "service_restart")
    assert (t.status, t.error_code) == ("failed", "llm_timeout")  # untouched


def test_shutdown_fails_running_generation(tmp_path):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        llm = BlockingLLM()
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit(repository, root)
        await executor.submit(row.generation_id)
        await asyncio.wait_for(llm.started.wait(), timeout=5)
        await executor.shutdown()
        llm.release.set()
        return repository.get_generation_input(row.generation_id)

    terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "service_shutdown"


def test_scheduling_failure_leaves_no_orphan_admitted(tmp_path, monkeypatch):
    root, repo, accepted, claim = _repo_with_binding(tmp_path)

    async def scenario():
        repository, executor = _make_executor(tmp_path, FakeLLM("{}"))
        row = _admit(repository, root)

        def explode(coro):
            raise RuntimeError("no task slots")

        monkeypatch.setattr(asyncio, "create_task", explode)
        await executor.submit(row.generation_id)
        return repository.get_generation_input(row.generation_id)

    terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "execution_schedule_failed"


# ---------------------------------------------------------------------------
# DB trigger guards for the execution state machine
# ---------------------------------------------------------------------------


def test_state_machine_triggers(tmp_path):
    repository = ReportRepository(tmp_path / "reports.db")
    row = repository.create_generation_input(
        "T", requested_by="x", input_schema_version=1,
        prompt_version=REPORT_GENERATION_PROMPT_VERSION,
        input_envelope_json="{}", input_hash="h",
    )
    conn = sqlite3.connect(repository.db_path)

    # Illegal transition admitted -> completed (rejected by the state
    # machine and/or the completed invariants -- either guard aborts it).
    with pytest.raises(
        sqlite3.IntegrityError,
        match="status transition|requires its published version",
    ):
        conn.execute(
            "UPDATE report_generation_inputs SET status = 'completed' "
            "WHERE generation_id = ?", (row.generation_id,)
        )
        conn.commit()
    conn.rollback()

    # Completed without report_id/version/model/completed_at.
    repository.claim_generation(row.generation_id)
    with pytest.raises(sqlite3.IntegrityError, match="published version"):
        conn.execute(
            "UPDATE report_generation_inputs SET status = 'completed', "
            "model = 'm', completed_at = '2026' "
            "WHERE generation_id = ?", (row.generation_id,)
        )
        conn.commit()
    conn.rollback()

    # Failed must not reference a published version.
    with pytest.raises(sqlite3.IntegrityError, match="must not reference"):
        conn.execute(
            "UPDATE report_generation_inputs SET status = 'failed', "
            "failed_at = '2026', report_id = 'rep', produced_version = 1 "
            "WHERE generation_id = ?", (row.generation_id,)
        )
        conn.commit()
    conn.rollback()

    repository.fail_generation(
        row.generation_id, error_code="llm_timeout",
        error_message="LLM request timed out",
    )
    # Terminal rows are immutable.
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE report_generation_inputs SET model = 'other' "
            "WHERE generation_id = ?", (row.generation_id,)
        )
        conn.commit()
    conn.rollback()
    conn.close()


def test_r2b_legacy_rows_migrate_additively(tmp_path):
    """An R2b-era reports.db gains the execution columns and triggers."""
    legacy = tmp_path / "reports.db"
    conn = sqlite3.connect(legacy)
    conn.executescript(
        """
        CREATE TABLE report_generation_inputs (
            generation_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'admitted',
            requested_by TEXT NOT NULL,
            input_schema_version INTEGER NOT NULL,
            prompt_version TEXT NOT NULL,
            input_envelope_json TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            report_id TEXT,
            created_at TEXT NOT NULL,
            CHECK (scope_type = 'task' AND scope_id = task_id)
        );
        INSERT INTO report_generation_inputs
            (generation_id, task_id, scope_type, scope_id, status, requested_by,
             input_schema_version, prompt_version, input_envelope_json,
             input_hash, created_at)
        VALUES ('rg_old', 'T', 'task', 'T', 'admitted', 'x', 1, 'p', '{}',
                'h', '2026');
        """
    )
    conn.commit()
    conn.close()

    repository = ReportRepository(legacy)
    row = repository.get_generation_input("rg_old")
    assert row.status == "admitted"  # historical row stays valid/queueable
    assert repository.claim_generation("rg_old").status == "running"
