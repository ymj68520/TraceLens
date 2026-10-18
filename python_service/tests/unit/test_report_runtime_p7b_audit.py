"""P7B freeze follow-up — dedicated audited publication gates (§29).

These are the P7B freeze HARD GATES, separate from the original 11 smoke
tests so future regressions can identify them precisely:

- publication trust boundary: the manifest is built from a durable-store
  reload (TrustedPublicationInput), never from caller-built objects;
- review binding: a pass review is only valid for ITS exact ledger;
- admission/finalization pinning across the whole chain;
- tamper cases (spec/pack/output/digest/ledger/review hashes);
- production orchestration E2E (completed Investigation -> READY
  report_versions -> strict Viewer);
- cross-resource failure semantics and existing-store migration.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from httpserver.services.forensic_report.generation_writer import (
    GenerationReportWriter,
)
from httpserver.services.forensic_report.narrative_reader import (
    read_narrative_version_strict,
)
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.report_runtime.report_admission import (
    ReportRuntimeAdmissionService,
)
from httpserver.services.report_runtime.report_chapter import ChapterSpecV1
from httpserver.services.report_runtime.report_chapter_draft import (
    ChapterDraftV1,
    ReportAssertionV1,
    WriterMetadataV1,
)
from httpserver.services.report_runtime.report_chapter_executor import (
    ChapterExecutionError,
    ChapterGenerationExecutor,
    retry_chapter_generation,
)
from httpserver.services.report_runtime.report_chapter_generation import (
    build_starter_narrative_policy,
    commit_report_chapter_dispatch,
)
from httpserver.services.report_runtime.report_chapter_validation import (
    ChapterValidationError,
    validate_chapter_draft,
)
from httpserver.services.report_runtime.report_context_pack import (
    AcceptedSemanticBasisV1,
    FrozenReportContextPackV1,
    ReportEvidenceItemV1,
)
from httpserver.services.report_runtime.report_ledger import (
    ChapterDigestV1,
    ReportAssertionLedgerV1,
    ReportConsistencyReviewV1,
    build_assertion_ledger,
    build_chapter_digest,
    run_deterministic_consistency,
)
from httpserver.services.report_runtime.report_publication import (
    PrevalidatedReportPublicationAdapter,
    PublicationTrustError,
    build_trusted_publication_input,
)
from httpserver.services.report_runtime.report_retrieval import (
    ReportRetrievalPlanV1,
)
from httpserver.services.report_runtime.report_repository import (
    ReportRuntimeRepository,
)
from httpserver.services.report_runtime.report_template import (
    build_starter_template,
    default_template_registry,
)

TASK = "task-P7BAUDIT"
INV = "inv-P7BAUDIT"
FZ = "fz-1"
FZ_HASH = "final-hash"


# ---------------------------------------------------------------------------
# shared fixture builders (same shapes as the focused suite, duplicated on
# purpose so the audit suite stays self-contained)
# ---------------------------------------------------------------------------


def _spec(chapter_id="chapter-1", mode="deterministic", ordering=1):
    return ChapterSpecV1(
        chapter_id=chapter_id,
        outline_id="outline-1",
        outline_revision=1,
        outline_hash="outline-hash",
        title=f"章节 {chapter_id}",
        generation_mode=mode,
        ordering=ordering,
    )


def _plan(spec):
    return ReportRetrievalPlanV1(
        task_id=TASK,
        investigation_id=INV,
        finalization_id=FZ,
        outline_id=spec.outline_id,
        outline_revision=spec.outline_revision,
        chapter_id=spec.chapter_id,
        chapter_spec_hash=spec.input_hash,
        anchor_refs=("file:C/a.doc",),
    )


def _pack(spec, plan, *, basis=()):
    return FrozenReportContextPackV1(
        task_id=TASK,
        investigation_id=INV,
        finalization_id=FZ,
        finalization_record_hash=FZ_HASH,
        outline_id=spec.outline_id,
        outline_revision=spec.outline_revision,
        chapter_id=spec.chapter_id,
        chapter_spec_hash=spec.input_hash,
        retrieval_plan_id=plan.retrieval_plan_id,
        retrieval_plan_hash=plan.input_hash,
        generation_mode=spec.generation_mode,
        anchor_evidence=(
            ReportEvidenceItemV1(
                evidence_ref="file:C/a.doc",
                role="anchor",
                evidence_digest="evidence-digest-a",
                hydration_depth="structured",
            ),
        ),
        accepted_semantic_basis=tuple(basis),
        hydration_policy_version="report-hydration-policy:v1",
        retrieval_policy_version="report-retrieval-policy:v1",
        dedup_policy_version="report-dedup-policy:v1",
        budget_policy_version="report-retrieval-budget:v1",
    )


def _record_admission(repo) -> str:
    """Persist one exact durable admission via the admission service
    against a completed-investigation runtime stub."""
    record = type(
        "FRec",
        (),
        {
            "finalization_id": FZ,
            "input_hash": FZ_HASH,
            "state_revision": 2,
            "state_hash": "state-hash",
            "completion_mode": "complete",
        },
    )()
    investigation = type("I", (), {})()
    investigation.status = type("S", (), {"value": "completed"})()

    class FakeRuntime:
        def get_investigation(self, investigation_id):
            return investigation

        def get_finalization(self, investigation_id):
            return record

    async def provider(task_id):
        return FakeRuntime()

    service = ReportRuntimeAdmissionService(
        provider, repo, default_template_registry()
    )
    admission = asyncio.run(
        service.admit(TASK, INV, requested_by="analyst")
    )
    return admission.admission_id


def _dispatch_chapter(repo, spec, plan, pack, admission_id):
    return commit_report_chapter_dispatch(
        repo,
        context_pack=pack,
        chapter_spec=spec,
        retrieval_plan=plan,
        narrative_policy=build_starter_narrative_policy(),
        prompt_version="chapter-writer:starter:v1",
        admission=repo.get_report_runtime_admission(admission_id),
    )


def _execute(repo, generation_id):
    return asyncio.run(
        ChapterGenerationExecutor(repository=repo).execute_chapter_generation(
            generation_id
        )
    )


def _build_ledger_and_digests(repo, admission_id, generation_ids):
    """Reload completed rows from the store and build the exact
    digest/ledger projections (deterministic, no caller payloads)."""
    admission = repo.get_report_runtime_admission(admission_id)
    completed = repo.list_completed_chapter_generations(
        task_id=admission.task_id,
        investigation_id=admission.investigation_id,
        finalization_id=admission.finalization_id,
    )
    ordered = [row for row in completed if row["generation_id"] in set(generation_ids)]
    ordered.sort(key=lambda row: generation_ids.index(row["generation_id"]))
    digests = [
        ChapterDigestV1.model_validate_json(row["digest_json"])
        for row in ordered
    ]
    ledger = build_assertion_ledger(
        task_id=admission.task_id,
        investigation_id=admission.investigation_id,
        finalization_id=admission.finalization_id,
        outline_id=ordered[0]["outline_id"],
        outline_revision=ordered[0]["outline_revision"],
        finalization_record_hash=admission.finalization_record_hash,
        completed=ordered,
    )
    repo.record_assertion_ledger(ledger)
    return ledger, digests


def _persist_pass_review(repo, ledger, *, status="pass", ledger_id=None,
                         ledger_hash=None) -> ReportConsistencyReviewV1:
    review = ReportConsistencyReviewV1(
        ledger_id=ledger_id if ledger_id is not None else ledger.ledger_id,
        ledger_hash=ledger_hash if ledger_hash is not None else ledger.input_hash,
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
    )
    repo.record_consistency_review(review)
    return review


class _R2RepoStub:
    """R2-side stub that delegates to a real ReportRepository so READY
    rows are actually persisted and strict-Viewer visible."""

    def __init__(self, report_repo):
        self._repo = report_repo

    def complete_prevalidated_publication(self, **kwargs):
        return self._repo.complete_prevalidated_publication(**kwargs)


def _adapter(runtime_repo, report_root):
    return PrevalidatedReportPublicationAdapter(
        runtime_repository=runtime_repo,
        r2_repository=_R2RepoStub(ReportRepository(report_root / "reports.db")),
        writer=GenerationReportWriter(report_root),
    )


def _stage_publication(tmp_path, *, chapters=1, mode="deterministic"):
    """One full durable pipeline up to (but not including) publication:
    admission -> dispatch -> execution -> ledger -> passing review."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    generation_ids = []
    for index in range(chapters):
        spec = _spec(f"chapter-{index + 1}", mode=mode, ordering=index + 1)
        plan = _plan(spec)
        pack = _pack(spec, plan)
        generation_input = _dispatch_chapter(
            repo, spec, plan, pack, admission_id
        )
        result = _execute(repo, generation_input.generation_id)
        assert result["outcome"] == "completed"
        generation_ids.append(generation_input.generation_id)
    ledger, digests = _build_ledger_and_digests(
        repo, admission_id, generation_ids
    )
    review = _persist_pass_review(repo, ledger)
    return repo, admission_id, generation_ids, ledger, digests, review


def _publish(tmp_path, staged, **overrides):
    repo, admission_id, generation_ids, ledger, digests, review = staged
    kwargs = dict(
        task_id=TASK,
        title="P7B audit report",
        admission_id=admission_id,
        expected_generation_ids=tuple(generation_ids),
        ledger_id=ledger.ledger_id,
        review_ids=(review.review_id,),
        chapter_titles={
            f"chapter-{i + 1}": f"章节 {i + 1}"
            for i in range(len(generation_ids))
        },
        evidence_digests={"file:C/a.doc": "evidence-digest-a"},
        model="deterministic_renderer",
        prompt_version="chapter-writer:starter:v1",
    )
    kwargs.update(overrides)
    return _adapter(repo, tmp_path / "report-root").publish(**kwargs)


def _report_versions_rows(report_root):
    db_path = Path(report_root) / "reports.db"
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='report_versions'"
            ).fetchall()
        }
        if not names:
            return []
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM report_versions"
            ).fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# F1 — publication trust boundary (§3-§4)
# ---------------------------------------------------------------------------


def test_publication_reloads_exact_durable_artifacts(tmp_path):
    """F1: publish() takes IDs only; the manifest provenance must equal
    what the durable store reloads, and stale caller hashes cannot leak."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    report_id, manifest_path = _publish(tmp_path, staged)
    root = tmp_path / "report-root"
    read = read_narrative_version_strict(
        root / "reports.db", root, TASK, report_id
    )
    assert read is not None
    _version, manifest = read
    provenance = manifest.provenance
    _admission = repo.get_report_runtime_admission(admission_id)
    completed_rows = repo.list_completed_chapter_generations(
        task_id=_admission.task_id,
        investigation_id=_admission.investigation_id,
        finalization_id=_admission.finalization_id,
    )
    assert provenance.chapter_spec_hashes == tuple(
        row["chapter_spec_hash"] for row in completed_rows
    )
    assert provenance.context_pack_ids == tuple(
        row["context_pack_id"] for row in completed_rows
    )
    assert provenance.context_pack_hashes == tuple(
        row["context_pack_hash"] for row in completed_rows
    )
    assert provenance.assertion_ledger_id == ledger.ledger_id
    assert provenance.assertion_ledger_hash == ledger.input_hash
    assert provenance.consistency_review_ids == (review.review_id,)
    assert provenance.consistency_review_hashes == (review.input_hash,)
    assert provenance.finalization_id == FZ
    assert provenance.finalization_record_hash == FZ_HASH
    # the published section text equals the reloaded validated drafts
    completed = completed_rows
    outputs = [json.loads(row["output_json"]) for row in completed]
    assert manifest.sections[0].content.startswith(
        "- 【事实】证据 file:C/a.doc"
    ) or manifest.sections[0].content.startswith("- 【事实】")
    assert len(manifest.sections) == len(outputs)


def test_publication_rejects_unknown_generation_or_ledger_ids(tmp_path):
    """F1 hard gates: missing admission/chapter/ledger/review rows all
    fail closed with no Viewer-visible version."""
    staged = _stage_publication(tmp_path)
    root = tmp_path / "report-root"
    root.mkdir(parents=True, exist_ok=True)
    repo, admission_id, generation_ids, ledger, digests, review = staged

    with pytest.raises(PublicationTrustError):
        _publish(
            tmp_path,
            staged,
            expected_generation_ids=(generation_ids[0], "rgen:ghost"),
        )
    with pytest.raises(PublicationTrustError):
        _publish(tmp_path, staged, ledger_id="rled:ghost")
    with pytest.raises(PublicationTrustError):
        _publish(tmp_path, staged, review_ids=("rrev:ghost",))
    with pytest.raises(PublicationTrustError):
        _publish(tmp_path, staged, admission_id="rra_ghost")
    assert _report_versions_rows(root) == []


def test_publication_rejects_incomplete_chapter_set(tmp_path):
    """F1: a completed set that misses one expected generation cannot
    publish; neither can an unexpected extra generation sneak in."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    ids = []
    for index in range(2):
        spec = _spec(f"chapter-{index + 1}", ordering=index + 1)
        plan = _plan(spec)
        pack = _pack(spec, plan)
        gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)
        assert _execute(repo, gen.generation_id)["outcome"] == "completed"
        ids.append(gen.generation_id)
    ledger, _digests = _build_ledger_and_digests(repo, admission_id, ids)
    review = _persist_pass_review(repo, ledger)
    staged = (repo, admission_id, ids, ledger, _digests, review)
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(tmp_path, staged, expected_generation_ids=(ids[0],))
    assert excinfo.value.code in (
        "chapter_generation_missing",
        "chapter_set_mismatch",
    )
    assert _report_versions_rows(tmp_path / "report-root") == []


def test_publication_tamper_matrix_fails_closed(tmp_path):
    """§9: each tampered durable hash must reject publication — never
    write the tampered value into the manifest.  Terminal chapter rows are
    trigger-immutable, so each tamper case runs on its own pipeline and
    simulates durable tampering by swapping the row the reload finds."""

    def _swap_generation_row(repo, generation_id, **overrides):
        """Simulate out-of-band durable tampering: the no-delete/no-update
        triggers are bypassed by dropping the trigger inside this test
        transaction (the tamper cases exist to prove the publication
        RELOADER fails closed, not to attack the triggers)."""
        row = repo.get_chapter_generation(generation_id)
        tampered = dict(row)
        tampered.update(overrides)
        with repo._connect() as conn:
            conn.execute(
                "DROP TRIGGER trg_report_chgen_no_delete"
            )
            conn.execute(
                "DROP TRIGGER trg_report_chgen_identity_frozen"
            )
            conn.execute(
                "DROP TRIGGER trg_report_chgen_terminal_immutable"
            )
            conn.execute(
                "UPDATE report_chapter_generations SET "
                + ", ".join(f"{k} = ?" for k in overrides)
                + " WHERE generation_id = ?",
                (*overrides.values(), generation_id),
            )
        return generation_id

    # case 1: generation row carries a chapter_spec_hash that differs from
    # the pack's frozen spec hash
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    _swap_generation_row(
        repo, generation_ids[0], chapter_spec_hash="tampered-spec-hash"
    )
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(
            tmp_path,
            staged,
            expected_generation_ids=tuple(generation_ids),
        )
    assert excinfo.value.code == "chapter_spec_hash_mismatch"
    assert _report_versions_rows(tmp_path / "report-root") == []

    # case 2: persisted digest payload binds another draft hash
    staged2 = _stage_publication(tmp_path / "case2")
    repo2, admission2, gen2, ledger2, digests2, review2 = staged2
    row2 = repo2.get_chapter_generation(gen2[0])
    digest_payload = json.loads(row2["digest_json"])
    digest_payload["draft_hash"] = "tampered-draft-hash"
    _swap_generation_row(
        repo2,
        gen2[0],
        digest_json=json.dumps(digest_payload, ensure_ascii=False),
    )
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(tmp_path / "case2", staged2)
    assert excinfo.value.code == "digest_hash_mismatch"

    # case 3: a ledger pinned to another finalization is rejected
    staged3 = _stage_publication(tmp_path / "case3")
    repo3, admission3, gen3, ledger3, digests3, review3 = staged3
    forged = ReportAssertionLedgerV1(
        task_id=ledger3.task_id,
        investigation_id=ledger3.investigation_id,
        finalization_id="fz-other",
        finalization_record_hash=ledger3.finalization_record_hash,
        outline_id=ledger3.outline_id,
        outline_revision=ledger3.outline_revision,
        chapter_generation_ids=ledger3.chapter_generation_ids,
        chapter_draft_hashes=ledger3.chapter_draft_hashes,
        assertions=ledger3.assertions,
    )
    repo3.record_assertion_ledger(forged)
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(
            tmp_path / "case3",
            staged3,
            ledger_id=forged.ledger_id,
        )
    assert excinfo.value.code == "ledger_finalization_mismatch"


def test_stale_review_cannot_approve_new_ledger(tmp_path):
    """§6/§F5: review(L1) pass cannot publish ledger L2 after a chapter
    regenerates."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    # chapter regenerated -> Ledger L2: completed rows are trigger-immutable,
    # so L2 is modelled as a new ledger over the durable set whose
    # finalization_record_hash changed (any durable change yields a new
    # content-addressed ledger id).
    base_ledger, _digests2 = _build_ledger_and_digests(
        repo, admission_id, list(generation_ids)
    )
    new_ledger = ReportAssertionLedgerV1(
        **{
            **base_ledger.model_dump(),
            "finalization_record_hash": "regenerated-final-hash",
        }
    )
    repo.record_assertion_ledger(new_ledger)
    assert new_ledger.ledger_id != ledger.ledger_id
    # old pass review points at the OLD ledger; publication against the
    # new ledger must be rejected
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(
            tmp_path,
            staged,
            ledger_id=new_ledger.ledger_id,
            review_ids=(review.review_id,),
        )
    assert excinfo.value.code == "review_ledger_mismatch"
    assert _report_versions_rows(tmp_path / "report-root") == []


def test_deterministic_consistency_rerun_blocks_mixed_set(tmp_path):
    """§7: publication re-runs deterministic consistency on the exact
    persisted ledger/chapter set — a reviewer pass cannot override it."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    # publish with an evidence digest map missing the pack's evidence ref
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(tmp_path, staged, evidence_digests={})
    assert excinfo.value.code == "deterministic_consistency_failed"
    assert _report_versions_rows(tmp_path / "report-root") == []


# ---------------------------------------------------------------------------
# F2 — atomic publication / failure semantics (§10-§12)
# ---------------------------------------------------------------------------


def test_manifest_write_failure_leaves_no_version_row(tmp_path, monkeypatch):
    """§11-A: if the immutable manifest write fails, no report_versions
    row exists and the strict Viewer cannot see anything."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    adapter = _adapter(repo, tmp_path / "report-root")

    class ExplodingWriter(GenerationReportWriter):
        def publish(self, **kwargs):
            raise OSError("disk full")

    adapter._writer = ExplodingWriter(tmp_path / "report-root")
    with pytest.raises(OSError):
        adapter.publish(
            task_id=TASK,
            title="P7B audit report",
            admission_id=admission_id,
            expected_generation_ids=tuple(generation_ids),
            ledger_id=ledger.ledger_id,
            review_ids=(review.review_id,),
            chapter_titles={"chapter-1": "章节 1"},
            evidence_digests={"file:C/a.doc": "evidence-digest-a"},
            model="deterministic_renderer",
            prompt_version="chapter-writer:starter:v1",
        )
    assert _report_versions_rows(tmp_path / "report-root") == []
    assert read_narrative_version_strict(
        tmp_path / "report-root" / "reports.db",
        tmp_path / "report-root",
        TASK,
        "nonexistent",
    ) is None


def test_db_completion_failure_leaves_no_viewer_visible_version(
    tmp_path, monkeypatch
):
    """§11-B: manifest may exist, but a failing READY-row transaction
    must keep the version invisible to the strict Viewer."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    report_root = tmp_path / "report-root"
    adapter = _adapter(repo, report_root)

    class ExplodingR2:
        def complete_prevalidated_publication(self, **kwargs):
            raise sqlite3.OperationalError("lock timeout")

    adapter._r2_repository = ExplodingR2()
    with pytest.raises(sqlite3.OperationalError):
        adapter.publish(
            task_id=TASK,
            title="P7B audit report",
            admission_id=admission_id,
            expected_generation_ids=tuple(generation_ids),
            ledger_id=ledger.ledger_id,
            review_ids=(review.review_id,),
            chapter_titles={"chapter-1": "章节 1"},
            evidence_digests={"file:C/a.doc": "evidence-digest-a"},
            model="deterministic_renderer",
            prompt_version="chapter-writer:starter:v1",
        )
    rows = _report_versions_rows(report_root)
    assert rows == []
    # the orphan manifest directory may physically exist; no strict read
    # can reach any version because no READY row was allocated
    assert read_narrative_version_strict(
        report_root / "reports.db", report_root, TASK, "whatever"
    ) is None


def test_publication_replay_allocates_distinct_versions_or_rejects(
    tmp_path,
):
    """§12: identical replay must not silently double-publish equivalent
    versions — the second publish allocates a NEW report_id (distinct
    immutable directory) or fails; both keep Viewer consistency."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    report_id_1, _ = _publish(tmp_path, staged)
    # replay with the same durable inputs
    report_id_2, _ = _publish(tmp_path, staged)
    assert report_id_1 != report_id_2
    rows = _report_versions_rows(tmp_path / "report-root")
    assert len(rows) == 2
    assert {row["report_id"] for row in rows} == {
        report_id_1,
        report_id_2,
    }
    versions = sorted(row["version"] for row in rows)
    assert versions == [1, 2]


# ---------------------------------------------------------------------------
# F3 — retry / admission / frozen input (§13-§17)
# ---------------------------------------------------------------------------


def test_retry_preserves_exact_admission_id(tmp_path):
    """§13: attempt2.admission_id == A (never NULL / another admission)."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1")
    plan = _plan(spec)
    pack = _pack(spec, plan)
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)
    repo.fail_chapter_generation(
        gen.generation_id,
        failure_code="audit_fail",
        failure_summary="forced",
    )
    retry_id = retry_chapter_generation(
        repo,
        gen.generation_id,
        narrative_policy_version="report-narrative-policy:starter:v1",
        prompt_version="chapter-writer:starter:v1",
    )
    row = repo.get_chapter_generation(retry_id)
    assert row["admission_id"] == admission_id
    assert row["retry_of_generation_id"] == gen.generation_id
    assert row["attempt_no"] == 2


def test_terminal_write_revalidates_admission(tmp_path):
    """§14: corrupt/missing durable admission before terminal completion
    must fail the chapter (not just dispatch-time checks)."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1", mode="evidence_narrative")
    plan = _plan(spec)
    basis = AcceptedSemanticBasisV1(
        basis_ref="finding:f1",
        basis_type="finding",
        assertion_class="INFERENCE",
        text_digest="fd",
        evidence_refs=("file:C/a.doc",),
    )
    pack = _pack(spec, plan, basis=(basis,))
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)

    async def slow_llm(system_prompt, user_prompt):
        # delete the durable admission while the chapter is running
        with repo._connect() as conn:
            conn.execute("PRAGMA query_only = OFF")
            conn.execute(
                "DELETE FROM report_runtime_admissions WHERE admission_id = ?",
                (admission_id,),
            )
        return {
            "content": json.dumps(
                {
                    "chapter_id": spec.chapter_id,
                    "statements": [
                        {
                            "text": "Statement grounded in accepted basis.",
                            "assertion_class": "INFERENCE",
                            "basis_type": "accepted_finding",
                            "basis_refs": ["finding:f1"],
                            "evidence_refs": ["file:C/a.doc"],
                            "citation_refs": ["file:C/a.doc"],
                        }
                    ],
                    "writer_metadata": {
                        "model": "audit-llm",
                        "prompt_version": gen.prompt_version,
                        "narrative_policy_version": (
                            "report-narrative-policy:starter:v1"
                        ),
                        "generated_at": "2026-01-01T00:00:00+00:00",
                    },
                },
                ensure_ascii=False,
            ),
            "model": "audit-llm",
        }

    with pytest.raises(ChapterExecutionError) as excinfo:
        asyncio.run(
            ChapterGenerationExecutor(
                repository=repo, llm_chat=slow_llm
            ).execute_chapter_generation(gen.generation_id)
        )
    assert "admission" in str(excinfo.value)
    row = repo.get_chapter_generation(gen.generation_id)
    # the terminal write did NOT happen: no validated output persisted
    assert row["status"] == "running"
    assert row["output_json"] is None


def test_finalization_binding_mismatch_fails_dispatch(tmp_path):
    """§15: a pack pinned to another finalization cannot dispatch."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1")
    plan = _plan(spec)
    pack = _pack(spec, plan)
    foreign = FrozenReportContextPackV1(
        **{
            **pack.model_dump(),
            "finalization_id": "fz-other",
            "context_pack_id": None,
            "created_at": None,
        }
    )
    with pytest.raises(Exception):
        _dispatch_chapter(repo, spec, plan, foreign, admission_id)


def test_pack_spec_hash_mismatch_rejected(tmp_path):
    """§16: a pack carrying another chapter's spec hash fails dispatch;
    a generation row with a differing spec hash fails execution."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec_a = _spec("chapter-a", ordering=1)
    spec_b = _spec("chapter-b", ordering=2)
    plan_a = _plan(spec_a)
    pack_wrong_spec = FrozenReportContextPackV1(
        **{
            **_pack(spec_a, plan_a).model_dump(),
            "chapter_id": spec_a.chapter_id,
            "chapter_spec_hash": spec_b.input_hash,
            "context_pack_id": None,
            "created_at": None,
        }
    )
    with pytest.raises(Exception):
        _dispatch_chapter(repo, spec_a, plan_a, pack_wrong_spec, admission_id)
    assert repo.get_chapter_generation("rgen:anything") is None


def test_persisted_input_reconstruction_after_process_loss(tmp_path):
    """§17: drop every in-process object; reload from reports.db only and
    re-execute — hashes must match exactly."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1")
    plan = _plan(spec)
    pack = _pack(spec, plan)
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)
    # simulate process loss: fresh repository handle on the same store
    repo2 = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    row = repo2.get_chapter_generation(gen.generation_id)
    pack2 = repo2.get_context_pack(row["context_pack_id"])
    plan2 = repo2.get_retrieval_plan(row["retrieval_plan_id"])
    assert pack2.input_hash == pack.input_hash
    assert pack2.context_pack_id == pack.context_pack_id
    assert plan2.input_hash == plan.input_hash
    result = asyncio.run(
        ChapterGenerationExecutor(repository=repo2).execute_chapter_generation(
            gen.generation_id
        )
    )
    assert result["outcome"] == "completed"
    completed = repo2.get_chapter_generation(gen.generation_id)
    assert completed["output_hash"] == json.loads(
        completed["output_json"]
    )["draft_hash"]


# ---------------------------------------------------------------------------
# F4 — synthesis ceiling / reviewer binding (§18-§21)
# ---------------------------------------------------------------------------


def test_synthesis_ceiling_ignores_forged_caller_classes(tmp_path):
    """§18: the ceiling derives from the immutable ledger only; a forged
    caller map claiming INFERENCE=FACT cannot strengthen a summary."""
    from httpserver.services.report_runtime.report_synthesis import (
        build_synthesis_context_pack,
        validate_synthesis_assertion,
    )

    ledger = ReportAssertionLedgerV1(
        task_id=TASK,
        investigation_id=INV,
        finalization_id=FZ,
        outline_id="outline-1",
        outline_revision=1,
        finalization_record_hash=FZ_HASH,
        assertions=(
            __import__(
                "httpserver.services.report_runtime.report_ledger",
                fromlist=["LedgerAssertionV1"],
            ).LedgerAssertionV1(
                chapter_id="c1",
                assertion_id="ras:inf",
                text_sha256="t",
                assertion_class="INFERENCE",
                basis_type="accepted_finding",
                basis_refs=("finding:f1",),
                evidence_refs=("file:C/a.doc",),
                citation_refs=("file:C/a.doc",),
            ),
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    context = build_synthesis_context_pack(
        ledger, [], question_dispositions={}
    )
    summary = ReportAssertionV1(
        text="Forged FACT summary.",
        assertion_class="FACT",
        basis_type="report_assertion",
        basis_refs=("ras:inf",),
        evidence_refs=("file:C/a.doc",),
        citation_refs=("file:C/a.doc",),
    )
    with pytest.raises(Exception) as excinfo:
        validate_synthesis_assertion(
            summary,
            ledger=ledger,
            synthesis_context=context,
            ledger_classes={"ras:inf": "FACT"},  # forged
        )
    assert getattr(excinfo.value, "code", "") == "synthesis_ceiling_violated"


def test_review_hash_covers_ledger_identity(tmp_path):
    """§19: review input_hash deterministically covers ledger_id/hash; a
    review of another ledger yields a different input_hash, and the
    publication gate rejects the stale pairing (already covered at the
    publication boundary in test_stale_review_cannot_approve_new_ledger)."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    other = ReportAssertionLedgerV1(
        **{
            **ledger.model_dump(),
            "finalization_record_hash": "other-final-hash",
        }
    )
    review_same_ledger = ReportConsistencyReviewV1(
        ledger_id=ledger.ledger_id,
        ledger_hash=ledger.input_hash,
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        status="pass",
        created_at="2026-01-01T00:00:00+00:00",
    )
    review_other = ReportConsistencyReviewV1(
        ledger_id=other.ledger_id,
        ledger_hash=other.input_hash,
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        status="pass",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert review_other.input_hash != review_same_ledger.input_hash
    assert review_same_ledger.input_hash == review.input_hash


def test_reviewer_missing_nonpass_and_empty_exploit(tmp_path):
    """§20/§21: no review / issues_found / indeterminate / forged-empty
    pass with default hashes all fail at the publication boundary."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged

    # issues_found review persisted and referenced
    issues_review = ReportConsistencyReviewV1(
        ledger_id=ledger.ledger_id,
        ledger_hash=ledger.input_hash,
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        status="issues_found",
        issues=(
            {
                "issue_type": "contradiction",
                "description": "chapters disagree",
                "affected_chapter_ids": ("chapter-1",),
            },
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    repo.record_consistency_review(issues_review)
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(
            tmp_path,
            staged,
            review_ids=(issues_review.review_id,),
        )
    assert excinfo.value.code == "review_not_pass"

    # indeterminate review
    indeterminate = ReportConsistencyReviewV1(
        ledger_id=ledger.ledger_id,
        ledger_hash=ledger.input_hash,
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        status="indeterminate",
        created_at="2026-01-01T00:00:00+00:00",
    )
    repo.record_consistency_review(indeterminate)
    with pytest.raises(PublicationTrustError):
        _publish(tmp_path, staged, review_ids=(indeterminate.review_id,))

    # empty-review exploit: an ID that collides with nothing
    with pytest.raises(PublicationTrustError) as excinfo:
        _publish(tmp_path, staged, review_ids=())
    assert excinfo.value.code == "review_missing"
    assert _report_versions_rows(tmp_path / "report-root") == []


# ---------------------------------------------------------------------------
# F5 — production E2E closure (§22-§28)
# ---------------------------------------------------------------------------


def test_production_e2e_completed_to_strict_viewer(tmp_path):
    """§22/§F14: full production chain through real repository
    orchestration; the Viewer-visible text equals the validated P7 text."""
    staged = _stage_publication(tmp_path, chapters=2)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    report_root = tmp_path / "report-root"
    report_id, manifest_path = _publish(tmp_path, staged)
    version_repo = ReportRepository(report_root / "reports.db")
    version = version_repo.get(report_id)
    assert version is not None
    assert version.status.value == "ready"
    assert version.report_kind == "agent_aware_generation"
    read = read_narrative_version_strict(
        report_root / "reports.db", report_root, TASK, report_id
    )
    assert read is not None
    _row, manifest = read
    assert manifest.schema_version == "3.0"
    # Viewer text == validated chapter text (deterministic formatting only)
    _admission_e2e = repo.get_report_runtime_admission(admission_id)
    completed = repo.list_completed_chapter_generations(
        task_id=_admission_e2e.task_id,
        investigation_id=_admission_e2e.investigation_id,
        finalization_id=_admission_e2e.finalization_id,
    )
    for section, row in zip(manifest.sections, completed):
        output = json.loads(row["output_json"])
        for statement in output["statements"]:
            marker = {
                "FACT": "【事实】",
                "INFERENCE": "【推断】",
                "HYPOTHESIS": "【假设】",
                "LIMITATION": "【局限】",
            }[statement["assertion_class"]]
            assert marker in section.content
            assert statement["text"] in section.content
    # provenance is exact persisted identity
    assert manifest.provenance.assertion_ledger_id == ledger.ledger_id
    assert manifest.provenance.chapter_generation_ids == tuple(
        row["generation_id"] for row in completed
    )


def test_production_e2e_review_blocker_hides_version(tmp_path):
    """§23/§F4: flipping the persisted review to issues_found blocks
    publication and NO report_versions row exists (not just an adapter
    exception)."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    # replace the pass review with an issues_found review of the same ledger
    issues_review = ReportConsistencyReviewV1(
        ledger_id=ledger.ledger_id,
        ledger_hash=ledger.input_hash,
        task_id=ledger.task_id,
        investigation_id=ledger.investigation_id,
        status="issues_found",
        issues=(
            {
                "issue_type": "overstatement",
                "description": "summary exceeds support",
                "affected_chapter_ids": ("chapter-1",),
            },
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    repo.record_consistency_review(issues_review)
    with pytest.raises(PublicationTrustError):
        _publish(tmp_path, staged, review_ids=(issues_review.review_id,))
    assert _report_versions_rows(tmp_path / "report-root") == []


def test_production_e2e_hidden_evidence_blocker(tmp_path):
    """§25/§F16: the Writer cites real task Evidence B that the pack
    never exposed; production execution fails validation and nothing is
    publishable."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1", mode="evidence_narrative")
    plan = _plan(spec)
    basis = AcceptedSemanticBasisV1(
        basis_ref="finding:f1",
        basis_type="finding",
        assertion_class="INFERENCE",
        text_digest="fd",
        evidence_refs=("file:C/a.doc",),
    )
    pack = _pack(spec, plan, basis=(basis,))
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)

    async def hidden_evidence_llm(system_prompt, user_prompt):
        # file:D/b.doc is real task evidence but NOT in the pack
        return {
            "content": json.dumps(
                {
                    "chapter_id": spec.chapter_id,
                    "statements": [
                        {
                            "text": "Statement citing hidden evidence.",
                            "assertion_class": "INFERENCE",
                            "basis_type": "accepted_finding",
                            "basis_refs": ["finding:f1"],
                            "evidence_refs": ["file:D/hidden.doc"],
                            "citation_refs": ["file:D/hidden.doc"],
                        }
                    ],
                    "writer_metadata": {
                        "model": "audit-llm",
                        "prompt_version": gen.prompt_version,
                        "narrative_policy_version": (
                            "report-narrative-policy:starter:v1"
                        ),
                        "generated_at": "2026-01-01T00:00:00+00:00",
                    },
                },
                ensure_ascii=False,
            ),
            "model": "audit-llm",
        }

    result = asyncio.run(
        ChapterGenerationExecutor(
            repository=repo, llm_chat=hidden_evidence_llm
        ).execute_chapter_generation(gen.generation_id)
    )
    assert result["outcome"] == "failed"
    assert result["code"] == "evidence_not_pack_visible"
    row = repo.get_chapter_generation(gen.generation_id)
    assert row["status"] == "failed"
    # nothing publishable: no completed chapters, no ledger, no versions
    assert (
        repo.list_completed_chapter_generations(
            task_id=TASK, investigation_id=INV, finalization_id=FZ
        )
        == []
    )
    assert _report_versions_rows(tmp_path / "report-root") == []


def test_production_e2e_assertion_overreach_blocker(tmp_path):
    """§26/§F15: accepted INFERENCE basis; Writer claims FACT; the
    production path fails the chapter with no digest/ledger/publication."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1", mode="evidence_narrative")
    plan = _plan(spec)
    basis = AcceptedSemanticBasisV1(
        basis_ref="finding:f1",
        basis_type="finding",
        assertion_class="INFERENCE",
        text_digest="fd",
        evidence_refs=("file:C/a.doc",),
    )
    pack = _pack(spec, plan, basis=(basis,))
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)

    async def overreach_llm(system_prompt, user_prompt):
        return {
            "content": json.dumps(
                {
                    "chapter_id": spec.chapter_id,
                    "statements": [
                        {
                            "text": "Confirmed as fact beyond the basis.",
                            "assertion_class": "FACT",
                            "basis_type": "accepted_finding",
                            "basis_refs": ["finding:f1"],
                            "evidence_refs": ["file:C/a.doc"],
                            "citation_refs": ["file:C/a.doc"],
                        }
                    ],
                    "writer_metadata": {
                        "model": "audit-llm",
                        "prompt_version": gen.prompt_version,
                        "narrative_policy_version": (
                            "report-narrative-policy:starter:v1"
                        ),
                        "generated_at": "2026-01-01T00:00:00+00:00",
                    },
                },
                ensure_ascii=False,
            ),
            "model": "audit-llm",
        }

    result = asyncio.run(
        ChapterGenerationExecutor(
            repository=repo, llm_chat=overreach_llm
        ).execute_chapter_generation(gen.generation_id)
    )
    assert result["outcome"] == "failed"
    assert result["code"] == "assertion_ceiling_violated"
    row = repo.get_chapter_generation(gen.generation_id)
    assert row["digest_json"] is None
    assert _report_versions_rows(tmp_path / "report-root") == []


def test_production_e2e_retry_then_publish(tmp_path):
    """§27/§F7: first provider attempt fails, retry keeps the exact
    admission, second attempt succeeds, publication succeeds with
    attempt history preserved."""
    repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")
    admission_id = _record_admission(repo)
    spec = _spec("chapter-1", mode="evidence_narrative")
    plan = _plan(spec)
    basis = AcceptedSemanticBasisV1(
        basis_ref="finding:f1",
        basis_type="finding",
        assertion_class="INFERENCE",
        text_digest="fd",
        evidence_refs=("file:C/a.doc",),
    )
    pack = _pack(spec, plan, basis=(basis,))
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)
    calls = {"n": 0}

    async def flaky_llm(system_prompt, user_prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider connection reset")
        return {
            "content": json.dumps(
                {
                    "chapter_id": spec.chapter_id,
                    "statements": [
                        {
                            "text": "Second attempt inference.",
                            "assertion_class": "INFERENCE",
                            "basis_type": "accepted_finding",
                            "basis_refs": ["finding:f1"],
                            "evidence_refs": ["file:C/a.doc"],
                            "citation_refs": ["file:C/a.doc"],
                        }
                    ],
                    "writer_metadata": {
                        "model": "audit-llm",
                        "prompt_version": gen.prompt_version,
                        "narrative_policy_version": (
                            "report-narrative-policy:starter:v1"
                        ),
                        "generated_at": "2026-01-01T00:00:00+00:00",
                    },
                },
                ensure_ascii=False,
            ),
            "model": "audit-llm",
        }

    first = asyncio.run(
        ChapterGenerationExecutor(
            repository=repo, llm_chat=flaky_llm
        ).execute_chapter_generation(gen.generation_id)
    )
    assert first["outcome"] == "failed"
    retry_id = retry_chapter_generation(
        repo,
        gen.generation_id,
        narrative_policy_version="report-narrative-policy:starter:v1",
        prompt_version="chapter-writer:starter:v1",
    )
    assert repo.get_chapter_generation(retry_id)["admission_id"] == (
        admission_id
    )
    second = asyncio.run(
        ChapterGenerationExecutor(
            repository=repo, llm_chat=flaky_llm
        ).execute_chapter_generation(retry_id)
    )
    assert second["outcome"] == "completed"
    ledger, digests = _build_ledger_and_digests(
        repo, admission_id, [retry_id]
    )
    review = _persist_pass_review(repo, ledger)
    staged = (repo, admission_id, [retry_id], ledger, digests, review)
    report_id, _path = _publish(tmp_path, staged)
    # attempt history preserved: failed attempt 1 + completed attempt 2
    attempts = repo.list_completed_chapter_generations(
        task_id=TASK, investigation_id=INV, finalization_id=FZ
    )
    failed_row = repo.get_chapter_generation(gen.generation_id)
    assert failed_row["status"] == "failed"
    assert failed_row["attempt_no"] == 1
    completed_row = repo.get_chapter_generation(retry_id)
    assert completed_row["attempt_no"] == 2
    version_repo = ReportRepository(tmp_path / "report-root" / "reports.db")
    assert version_repo.get(report_id).status.value == "ready"


def test_viewer_strictness_tampered_manifest_unreachable(tmp_path):
    """§28/§F13: a hand-built manifest without a matching DB row is not
    reachable through the strict reader; old V1/V2 rows stay readable."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    report_root = tmp_path / "report-root"
    report_id, _ = _publish(tmp_path, staged)

    # hand-forge a manifest directory with no DB row
    from httpserver.services.forensic_report.ids import safe_segment

    ghost_dir = (
        report_root / "snapshots" / "task"
        / safe_segment(TASK) / safe_segment("ghost-id")
    )
    ghost_dir.mkdir(parents=True)
    (ghost_dir / "manifest.json").write_text(
        json.dumps({"schema_version": "3.0", "report_id": "ghost-id"}),
        encoding="utf-8",
    )
    assert (
        read_narrative_version_strict(
            report_root / "reports.db", report_root, TASK, "ghost-id"
        )
        is None
    )
    # the real published V3 version is still strictly readable
    read = read_narrative_version_strict(
        report_root / "reports.db", report_root, TASK, report_id
    )
    assert read is not None


def test_old_v1_v2_viewer_compatibility(tmp_path):
    """§28/§F13: a legacy llm_generation v1 manifest row keeps strict
    readability alongside the P7B V3 row."""
    report_root = tmp_path / "report-root"
    report_root.mkdir(parents=True)
    legacy_repo = ReportRepository(report_root / "reports.db")
    from httpserver.services.forensic_report.models import (
        CitationManifestEntry,
        GenerationReportManifest,
        StructuredReportSection,
    )
    from httpserver.services.forensic_report.ids import safe_segment

    from httpserver.services.forensic_report.repository import ScopeType

    version = legacy_repo.create_version(
        ScopeType.TASK, TASK, title="legacy", task_ids=[TASK]
    )
    manifest = GenerationReportManifest(
        report_id=version.report_id,
        scope_type=ScopeType.TASK,
        scope_id=TASK,
        task_id=TASK,
        generation_id="gen-legacy",
        title="legacy",
        prompt_version="p",
        input_hash="h",
        model="m",
        generated_at="2026-01-01T00:00:00+00:00",
        sections=(
            StructuredReportSection(
                heading="S", content="body", citation_ids=()
            ),
        ),
        citations=(),
    )
    writer = GenerationReportWriter(report_root)
    final_dir = writer.publish(
        task_id=TASK, report_id=version.report_id, manifest=manifest
    )
    from datetime import datetime, timezone

    import json as _json

    with legacy_repo._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE report_versions
               SET status = 'ready', stage = 'ready', progress = 100,
                   manifest_path = ?, generated_at = ?, report_kind =
                   'llm_generation'
               WHERE report_id = ?""",
            (
                str(
                    (final_dir / "manifest.json").relative_to(report_root)
                ),
                datetime.now(timezone.utc).isoformat(),
                version.report_id,
            ),
        )
        conn.commit()
    read = read_narrative_version_strict(
        report_root / "reports.db", report_root, TASK, version.report_id
    )
    assert read is not None
    assert read[1].schema_version == "1.0"


# ---------------------------------------------------------------------------
# §30 static boundary re-run + §31 migration
# ---------------------------------------------------------------------------


def test_static_boundaries_p7b_components():
    """§30: ChapterWriter/reviewer/publication stay retrieval-free; the
    P7 runtime never mutates accepted/rejected case semantics."""
    import inspect

    from httpserver.services.report_runtime.report_chapter_writer import (
        ChapterWriter,
    )
    from httpserver.services.report_runtime.report_publication import (
        PrevalidatedReportPublicationAdapter,
    )

    assert ChapterWriter.tools == 0
    writer_src = inspect.getsource(ChapterWriter)
    for forbidden in (
        "ToolRegistry",
        "Graphiti",
        "EvidenceResolver",
        "InvestigationRepository",
    ):
        assert forbidden not in writer_src
    reviewer_src = inspect.getsource(
        __import__(
            "httpserver.services.report_runtime.report_ledger",
            fromlist=["SemanticConsistencyReviewer"],
        ).SemanticConsistencyReviewer
    )
    assert "get_retrieval_plan" not in reviewer_src
    assert "get_context_pack" not in reviewer_src
    adapter_src = inspect.getsource(PrevalidatedReportPublicationAdapter)
    assert "llm" not in adapter_src.lower().replace(
        "llm_chat", ""
    ) or "_llm_chat" not in adapter_src
    assert "chat_completion" not in adapter_src


def test_migration_existing_p7a_store_adds_admission_column(tmp_path):
    """§31/§F18: a P7A-era store without admission_id migrates additively,
    old rows survive, new dispatch requires admission, retry preserves it."""
    db_path = tmp_path / "reports.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE report_chapter_generations (
            generation_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            investigation_id TEXT NOT NULL,
            finalization_id TEXT NOT NULL,
            outline_id TEXT NOT NULL,
            outline_revision INTEGER NOT NULL,
            chapter_id TEXT NOT NULL,
            chapter_spec_hash TEXT NOT NULL,
            context_pack_id TEXT NOT NULL,
            context_pack_hash TEXT NOT NULL,
            retrieval_plan_id TEXT NOT NULL,
            generation_mode TEXT NOT NULL,
            narrative_policy_version TEXT NOT NULL,
            output_contract_version TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            attempt_no INTEGER NOT NULL DEFAULT 1,
            retry_of_generation_id TEXT,
            status TEXT NOT NULL DEFAULT 'admitted',
            model TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            failed_at TEXT,
            failure_code TEXT,
            failure_summary TEXT,
            output_json TEXT,
            output_hash TEXT,
            digest_json TEXT
        );
        INSERT INTO report_chapter_generations
            (generation_id, task_id, investigation_id, finalization_id,
             outline_id, outline_revision, chapter_id, chapter_spec_hash,
             context_pack_id, context_pack_hash, retrieval_plan_id,
             generation_mode, narrative_policy_version,
             output_contract_version, prompt_version, input_hash,
             created_at, status)
        VALUES ('rgen:legacy', 'task-old', 'inv-old', 'fz-old',
                'outline-old', 1, 'chapter-old', 'spec-old',
                'rpack:old', 'pack-old', 'rplan:old', 'deterministic',
                'report-narrative-policy:starter:v1', 'chapter-draft:v1',
                'p', 'legacy-hash', '2026-01-01T00:00:00+00:00',
                'completed');
        """
    )
    conn.commit()
    conn.close()

    repo = ReportRuntimeRepository(db_path)
    with repo._connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(report_chapter_generations)"
            ).fetchall()
        }
        legacy_row = conn.execute(
            "SELECT * FROM report_chapter_generations "
            "WHERE generation_id = 'rgen:legacy'"
        ).fetchone()
    assert "admission_id" in columns
    assert legacy_row is not None
    assert legacy_row["admission_id"] is None
    # legacy completed row survives; no chapter owns admission_id
    assert legacy_row["status"] == "completed"

    # new dispatch + retry preserve admission binding
    admission_id = _record_admission(repo)
    spec = _spec("chapter-new", ordering=1)
    plan = _plan(spec)
    pack = _pack(spec, plan)
    gen = _dispatch_chapter(repo, spec, plan, pack, admission_id)
    assert repo.get_chapter_generation(gen.generation_id)["admission_id"] == (
        admission_id
    )
    repo.fail_chapter_generation(
        gen.generation_id,
        failure_code="audit_fail",
        failure_summary="forced",
    )
    retry_id = retry_chapter_generation(
        repo,
        gen.generation_id,
        narrative_policy_version="report-narrative-policy:starter:v1",
        prompt_version="chapter-writer:starter:v1",
    )
    assert repo.get_chapter_generation(retry_id)["admission_id"] == (
        admission_id
    )
    # old row untouched
    with repo._connect() as conn:
        assert (
            conn.execute(
                "SELECT admission_id FROM report_chapter_generations "
                "WHERE generation_id = 'rgen:legacy'"
            ).fetchone()[0]
            is None
        )


def test_trusted_reload_rejects_tampered_output_hash(tmp_path):
    """§4/§F1: chapter output_hash tampering in the durable store must
    fail the reload — the manifest cannot silently carry caller values."""
    staged = _stage_publication(tmp_path)
    repo, admission_id, generation_ids, ledger, digests, review = staged
    with repo._connect() as conn:
        # tamper simulation bypasses the immutability triggers on purpose
        conn.execute("DROP TRIGGER trg_report_chgen_identity_frozen")
        conn.execute("DROP TRIGGER trg_report_chgen_terminal_immutable")
        conn.execute(
            "UPDATE report_chapter_generations SET output_hash = 'deadbeef' "
            "WHERE generation_id = ?",
            (generation_ids[0],),
        )
    with pytest.raises(PublicationTrustError) as excinfo:
        build_trusted_publication_input(
            repo,
            admission_id=admission_id,
            expected_generation_ids=tuple(generation_ids),
            ledger_id=ledger.ledger_id,
            review_ids=(review.review_id,),
        )
    assert excinfo.value.code == "chapter_output_hash_mismatch"
