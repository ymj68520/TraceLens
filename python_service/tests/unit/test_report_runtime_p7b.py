"""P7B focused contracts and E2E tests.

These tests deliberately exercise the hard boundaries rather than model
quality: persist-before-generate, tools=0, pack-only citations, assertion
ceilings, immutable digest/ledger/review projections, synthesis gating,
restart/retry, and Adapter-B publication through the existing R2 reader.
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
    ChapterDispatchError,
    ChapterGenerationInputV1,
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
    LedgerAssertionV1,
    ReportAssertionLedgerV1,
    ReportConsistencyReviewV1,
    SemanticConsistencyReviewer,
    build_assertion_ledger,
    build_chapter_digest,
    run_deterministic_consistency,
)
from httpserver.services.report_runtime.report_publication import (
    PrevalidatedReportPublicationAdapter,
)
from httpserver.services.report_runtime.report_retrieval import (
    ReportRetrievalPlanV1,
)
from httpserver.services.report_runtime.report_synthesis import (
    SynthesisCeilingError,
    build_synthesis_context_pack,
    validate_synthesis_assertion,
)

TASK = "task-P7B"
INV = "inv-P7B"


def _spec(mode="deterministic"):
    return ChapterSpecV1(
        chapter_id="chapter-1",
        outline_id="outline-1",
        outline_revision=1,
        outline_hash="outline-hash",
        title="证据清单",
        generation_mode=mode,
        ordering=1,
    )


def _plan(spec, *, anchor="file:C/a.doc"):
    return ReportRetrievalPlanV1(
        task_id=TASK,
        investigation_id=INV,
        finalization_id="fz-1",
        outline_id=spec.outline_id,
        outline_revision=spec.outline_revision,
        chapter_id=spec.chapter_id,
        chapter_spec_hash=spec.input_hash,
        anchor_refs=(anchor,),
    )


def _pack(spec, plan, *, mode=None, basis=()):
    return FrozenReportContextPackV1(
        task_id=TASK,
        investigation_id=INV,
        finalization_id="fz-1",
        finalization_record_hash="final-hash",
        outline_id=spec.outline_id,
        outline_revision=spec.outline_revision,
        chapter_id=spec.chapter_id,
        chapter_spec_hash=spec.input_hash,
        retrieval_plan_id=plan.retrieval_plan_id,
        retrieval_plan_hash=plan.input_hash,
        generation_mode=mode or spec.generation_mode,
        anchor_evidence=(
            ReportEvidenceItemV1(
                evidence_ref="file:C/a.doc",
                role="anchor",
                evidence_digest="evidence-digest",
                hydration_depth="structured",
            ),
        ),
        accepted_semantic_basis=tuple(basis),
        hydration_policy_version="report-hydration-policy:v1",
        retrieval_policy_version="report-retrieval-policy:v1",
        dedup_policy_version="report-dedup-policy:v1",
        budget_policy_version="report-retrieval-budget:v1",
    )


def _dispatch(repo, *, mode="deterministic", basis=()):
    spec = _spec(mode)
    plan = _plan(spec)
    pack = _pack(spec, plan, mode=mode, basis=basis)
    generation_input = commit_report_chapter_dispatch(
        repo,
        context_pack=pack,
        chapter_spec=spec,
        retrieval_plan=plan,
        narrative_policy=build_starter_narrative_policy(),
        prompt_version="chapter-writer:starter:v1",
    )
    return spec, plan, pack, generation_input


def _draft(generation_input, *, cls="FACT", basis_type="direct_evidence",
           basis_refs=(), evidence_refs=("file:C/a.doc",),
           citation_refs=("file:C/a.doc",), text="Recorded file fact."):
    return ChapterDraftV1(
        chapter_id=generation_input.chapter_id,
        statements=(
            ReportAssertionV1(
                text=text,
                assertion_class=cls,
                basis_type=basis_type,
                basis_refs=basis_refs,
                evidence_refs=evidence_refs,
                citation_refs=citation_refs,
            ),
        ),
        writer_metadata=WriterMetadataV1(
            model="test-model",
            prompt_version=generation_input.prompt_version,
            narrative_policy_version=(
                generation_input.narrative_policy.policy_version
            ),
            generated_at="2026-01-01T00:00:00+00:00",
        ),
    )


def test_persist_before_generate_and_restart_reconstruction(tmp_path):
    from httpserver.services.report_runtime.report_repository import (
        ReportRuntimeRepository,
    )

    repo = ReportRuntimeRepository(tmp_path / "reports.db")
    spec, plan, pack, generation_input = _dispatch(repo)
    assert repo.get_retrieval_plan(plan.retrieval_plan_id) is not None
    assert repo.get_context_pack(pack.context_pack_id) is not None
    row = repo.get_chapter_generation(generation_input.generation_id)
    assert row["status"] == "admitted"
    assert row["context_pack_hash"] == pack.input_hash
    assert row["input_hash"] == generation_input.input_hash


def test_dispatch_failure_leaves_no_generation_row(tmp_path):
    from httpserver.services.report_runtime.report_repository import (
        ReportRuntimeRepository,
    )

    repo = ReportRuntimeRepository(tmp_path / "reports.db")
    spec = _spec()
    plan = _plan(spec)
    pack = _pack(spec, plan)
    bad_plan = plan.model_copy(update={"chapter_id": "other"})
    with pytest.raises(ChapterDispatchError):
        commit_report_chapter_dispatch(
            repo,
            context_pack=pack,
            chapter_spec=spec,
            retrieval_plan=bad_plan,
            narrative_policy=build_starter_narrative_policy(),
            prompt_version="chapter-writer:starter:v1",
        )
    with repo._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM report_chapter_generations"
        ).fetchone()[0] == 0


def test_deterministic_chapter_no_llm_and_completes(tmp_path):
    from httpserver.services.report_runtime.report_repository import (
        ReportRuntimeRepository,
    )

    repo = ReportRuntimeRepository(tmp_path / "reports.db")
    _spec0, _plan0, _pack0, generation_input = _dispatch(repo)
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("deterministic chapter called the LLM")

    result = asyncio.run(
        ChapterGenerationExecutor(repository=repo, llm_chat=forbidden)
        .execute_chapter_generation(generation_input.generation_id)
    )
    assert result["outcome"] == "completed"
    assert called is False
    assert repo.get_chapter_generation(generation_input.generation_id)["status"] == (
        "completed"
    )


def test_writer_tools_zero_and_only_frozen_input():
    from httpserver.services.report_runtime.report_chapter_writer import (
        ChapterWriter,
    )
    import inspect

    assert ChapterWriter.tools == 0
    params = inspect.signature(ChapterWriter.write).parameters
    assert set(params) == {"self", "generation_input", "context_pack"}
    source = inspect.getsource(ChapterWriter)
    assert "ToolRegistry" not in source
    assert "Graphiti" not in source
    assert "EvidenceResolver" not in source
    assert "sqlite" not in source.lower()


def test_writer_valid_output_passes_and_unknown_evidence_fails():
    spec = _spec("evidence_narrative")
    plan = _plan(spec)
    basis = AcceptedSemanticBasisV1(
        basis_ref="finding:f1",
        basis_type="finding",
        assertion_class="INFERENCE",
        text_digest="fd",
        evidence_refs=("file:C/a.doc",),
    )
    pack = _pack(spec, plan, mode="evidence_narrative", basis=(basis,))
    from httpserver.services.report_runtime.report_chapter_generation import (
        new_chapter_generation_input,
    )

    generation_input = new_chapter_generation_input(
        context_pack=pack,
        chapter_spec=spec,
        narrative_policy=build_starter_narrative_policy(),
        prompt_version="chapter-writer:starter:v1",
    )
    valid = _draft(
        generation_input,
        cls="INFERENCE",
        basis_type="accepted_finding",
        basis_refs=("finding:f1",),
        text="Activity is consistent with the accepted basis.",
    )
    bound = validate_chapter_draft(valid, generation_input, pack)
    assert bound.statements[0].assertion_id.startswith("ras:")
    guessed = _draft(
        generation_input,
        cls="INFERENCE",
        basis_type="accepted_finding",
        basis_refs=("finding:f1",),
        evidence_refs=("file:B/not-in-pack",),
        citation_refs=("file:B/not-in-pack",),
    )
    with pytest.raises(ChapterValidationError) as excinfo:
        validate_chapter_draft(guessed, generation_input, pack)
    assert excinfo.value.code == "evidence_not_pack_visible"


def test_assertion_ceiling_and_direct_evidence_overreach_fail():
    spec = _spec("evidence_narrative")
    plan = _plan(spec)
    basis = AcceptedSemanticBasisV1(
        basis_ref="finding:f1", basis_type="finding",
        assertion_class="INFERENCE", text_digest="fd",
        evidence_refs=("file:C/a.doc",),
    )
    pack = _pack(spec, plan, mode="evidence_narrative", basis=(basis,))
    from httpserver.services.report_runtime.report_chapter_generation import (
        new_chapter_generation_input,
    )

    inp = new_chapter_generation_input(
        context_pack=pack, chapter_spec=spec,
        narrative_policy=build_starter_narrative_policy(),
        prompt_version="chapter-writer:starter:v1",
    )
    overstrong = _draft(
        inp, cls="FACT", basis_type="accepted_finding",
        basis_refs=("finding:f1",), text="The user exfiltrated the file.",
    )
    with pytest.raises(ChapterValidationError) as excinfo:
        validate_chapter_draft(overstrong, inp, pack)
    assert excinfo.value.code == "assertion_ceiling_violated"
    direct_overreach = _draft(
        inp, cls="FACT", basis_type="direct_evidence", basis_refs=(),
        text="The attacker maliciously exfiltrated the file.",
    )
    with pytest.raises(ChapterValidationError) as excinfo:
        validate_chapter_draft(direct_overreach, inp, pack)
    assert excinfo.value.code == "direct_evidence_overreach"


def test_restart_running_failed_admitted_stays_dispatchable(tmp_path):
    from httpserver.services.report_runtime.report_repository import (
        ReportRuntimeRepository,
    )

    repo = ReportRuntimeRepository(tmp_path / "reports.db")
    _spec0, _plan0, _pack0, generation_input = _dispatch(repo)
    assert repo.claim_chapter_generation(generation_input.generation_id)
    recovery = ChapterGenerationExecutor(repository=repo).initialize()
    assert recovery["running_failed"] == 1
    failed = repo.get_chapter_generation(generation_input.generation_id)
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "runtime_restart"
    retry_id = retry_chapter_generation(
        repo, generation_input.generation_id,
        narrative_policy_version="report-narrative-policy:starter:v1",
        prompt_version="chapter-writer:starter:v1",
    )
    assert retry_id != generation_input.generation_id
    assert repo.get_chapter_generation(retry_id)["status"] == "admitted"


def test_digest_ledger_and_consistency_are_deterministic(tmp_path):
    from httpserver.services.report_runtime.report_ledger import (
        build_chapter_digest,
    )

    draft = ChapterDraftV1(
        chapter_id="c1",
        statements=(
            ReportAssertionV1(
                text="Recorded file fact.", assertion_class="FACT",
                basis_type="direct_evidence",
                evidence_refs=("file:C/a.doc",),
                citation_refs=("file:C/a.doc",),
            ),
        ),
        writer_metadata=WriterMetadataV1(
            model="deterministic_renderer", prompt_version="p",
            narrative_policy_version="n",
            generated_at="2026-01-01T00:00:00+00:00",
        ),
    ).with_identities("input-hash")
    digest = build_chapter_digest(
        draft, generation_id="rgen:1", context_pack_hash="pack-hash"
    )
    row = {
        "generation_id": "rgen:1", "chapter_id": "c1",
        "output_json": json.dumps({
            **draft.model_dump(mode="json"), "draft_hash": draft.draft_hash()
        }),
        "digest_json": digest.model_dump_json(),
    }
    ledger = build_assertion_ledger(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1",
        outline_id="outline-1", outline_revision=1,
        finalization_record_hash="final-hash", completed=[row],
    )
    assert ledger.ledger_id == build_assertion_ledger(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1",
        outline_id="outline-1", outline_revision=1,
        finalization_record_hash="final-hash", completed=[row],
    ).ledger_id
    assert run_deterministic_consistency(
        ledger, digests=[digest], evidence_digests={"file:C/a.doc": "d"},
        finalization_id="fz-1", outline_id="outline-1", outline_revision=1,
    ) == []


def test_reviewer_tools_zero_and_unknown_ref_rejected():
    from httpserver.services.report_runtime.report_ledger import (
        SemanticConsistencyReviewer,
    )
    import inspect

    assert SemanticConsistencyReviewer.tools == 0
    assert "EvidenceResolver" not in inspect.getsource(
        SemanticConsistencyReviewer
    )
    # model-level issue validation rejects unknown assertion ids
    with pytest.raises(ValueError):
        from httpserver.services.report_runtime.report_ledger import (
            ReportConsistencyReviewV1,
        )
        ReportConsistencyReviewV1(
            ledger_id="rled:1", ledger_hash="h", task_id=TASK,
            investigation_id=INV, status="issues_found",
            affected_assertion_ids=("ras:known",),
            issues=({
                "issue_type": "contradiction",
                "description": "bad",
                "affected_assertion_ids": ("ras:unknown",),
            },),
            created_at="2026-01-01T00:00:00+00:00",
        )


def test_synthesis_ceiling_uses_lowest_basis():
    from httpserver.services.report_runtime.report_synthesis import (
        build_synthesis_context_pack, validate_synthesis_assertion,
    )
    ledger = ReportAssertionLedgerV1(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1",
        outline_id="outline-1", outline_revision=1,
        assertions=(
            LedgerAssertionV1(
                chapter_id="c1", assertion_id="ras:fact",
                text_sha256="t1", assertion_class="FACT",
                basis_type="direct_evidence", evidence_refs=("file:C/a.doc",),
                citation_refs=("file:C/a.doc",),
            ),
            LedgerAssertionV1(
                chapter_id="c2", assertion_id="ras:inf",
                text_sha256="t2", assertion_class="INFERENCE",
                basis_type="accepted_finding", basis_refs=("finding:f1",),
                evidence_refs=("file:C/a.doc",),
                citation_refs=("file:C/a.doc",),
            ),
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    context = build_synthesis_context_pack(
        ledger, [], question_dispositions={"q1": "not_supported"}
    )
    classes = {"ras:fact": "FACT", "ras:inf": "INFERENCE"}
    allowed = ReportAssertionV1(
        text="Summary remains an inference.", assertion_class="INFERENCE",
        basis_type="report_assertion", basis_refs=("ras:fact", "ras:inf"),
        evidence_refs=("file:C/a.doc",), citation_refs=("file:C/a.doc",),
    )
    validate_synthesis_assertion(
        allowed, ledger=ledger, synthesis_context=context,
        ledger_classes=classes,
    )
    with pytest.raises(Exception) as excinfo:
        validate_synthesis_assertion(
            allowed.model_copy(update={"assertion_class": "FACT"}),
            ledger=ledger, synthesis_context=context, ledger_classes=classes,
        )
    assert getattr(excinfo.value, "code", "") == "synthesis_ceiling_violated"


def test_v3_publication_adapter_and_strict_viewer(tmp_path):
    """V3 publication through the durable trusted-input reload: the full
    P7B chain is staged in reports.db, publication takes IDs only, and
    the strict Viewer reads the reloaded validated text."""
    from httpserver.services.report_runtime.report_publication import (
        PrevalidatedReportPublicationAdapter,
    )
    from httpserver.services.report_runtime.report_repository import (
        ReportRuntimeRepository,
    )
    from httpserver.services.report_runtime.report_chapter import (
        ChapterSpecV1,
    )
    from httpserver.services.report_runtime.report_chapter_generation import (
        commit_report_chapter_dispatch,
    )
    from httpserver.services.report_runtime.report_chapter_executor import (
        ChapterGenerationExecutor,
    )
    from httpserver.services.report_runtime.report_retrieval import (
        ReportRetrievalPlanV1,
    )
    from httpserver.services.report_runtime.report_context_pack import (
        FrozenReportContextPackV1,
        ReportEvidenceItemV1,
    )
    from httpserver.services.report_runtime.report_admission import (
        ReportRuntimeAdmissionService,
    )
    from httpserver.services.report_runtime.report_template import (
        default_template_registry,
    )
    import asyncio as _asyncio
    import hashlib as _hashlib

    report_root = tmp_path / "reports"
    report_root.mkdir()
    report_repo = ReportRepository(report_root / "reports.db")
    writer = GenerationReportWriter(report_root)
    runtime_repo = ReportRuntimeRepository(tmp_path / "runtime-reports.db")

    record = type(
        "FRec", (), {
            "finalization_id": "fz-1", "input_hash": "final-hash",
            "state_revision": 2, "state_hash": "state-hash",
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

    admission = _asyncio.run(
        ReportRuntimeAdmissionService(
            provider, runtime_repo, default_template_registry()
        ).admit(TASK, INV, requested_by="analyst")
    )

    spec = ChapterSpecV1(
        chapter_id="c1", outline_id="outline-1", outline_revision=1,
        outline_hash="outline-hash", title="Chapter 1",
        generation_mode="deterministic", ordering=1,
    )
    plan = ReportRetrievalPlanV1(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1",
        outline_id="outline-1", outline_revision=1, chapter_id="c1",
        chapter_spec_hash=spec.input_hash,
        anchor_refs=("file:C/a.doc",),
    )
    pack = FrozenReportContextPackV1(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1",
        finalization_record_hash="final-hash", outline_id="outline-1",
        outline_revision=1, chapter_id="c1",
        chapter_spec_hash=spec.input_hash,
        retrieval_plan_id=plan.retrieval_plan_id,
        retrieval_plan_hash=plan.input_hash,
        generation_mode="deterministic",
        anchor_evidence=(
            ReportEvidenceItemV1(
                evidence_ref="file:C/a.doc", role="anchor",
                evidence_digest="evidence-digest",
                hydration_depth="structured",
            ),
        ),
        hydration_policy_version="report-hydration-policy:v1",
        retrieval_policy_version="report-retrieval-policy:v1",
        dedup_policy_version="report-dedup-policy:v1",
        budget_policy_version="report-retrieval-budget:v1",
    )
    generation_input = commit_report_chapter_dispatch(
        runtime_repo,
        context_pack=pack,
        chapter_spec=spec,
        retrieval_plan=plan,
        narrative_policy=build_starter_narrative_policy(),
        prompt_version="chapter-writer:starter:v1",
        admission=admission,
    )
    result = _asyncio.run(
        ChapterGenerationExecutor(
            repository=runtime_repo
        ).execute_chapter_generation(generation_input.generation_id)
    )
    assert result["outcome"] == "completed"
    completed = runtime_repo.list_completed_chapter_generations(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1"
    )
    # output_json embeds the derived draft_hash (executor contract);
    # ChapterDraftV1 itself is strict, so strip it before revalidation
    draft_payload = json.loads(completed[0]["output_json"])
    draft_payload.pop("draft_hash", None)
    draft = ChapterDraftV1.model_validate(draft_payload)
    digest = build_chapter_digest(
        draft,
        generation_id=generation_input.generation_id,
        context_pack_hash=pack.input_hash,
    )
    ledger = build_assertion_ledger(
        task_id=TASK, investigation_id=INV, finalization_id="fz-1",
        outline_id="outline-1", outline_revision=1,
        finalization_record_hash="final-hash", completed=completed,
    )
    runtime_repo.record_assertion_ledger(ledger)
    review = ReportConsistencyReviewV1(
        ledger_id=ledger.ledger_id, ledger_hash=ledger.input_hash,
        task_id=TASK, investigation_id=INV, status="pass",
        created_at="2026-01-01T00:00:00+00:00",
    )
    runtime_repo.record_consistency_review(review)
    report_id, manifest_path = PrevalidatedReportPublicationAdapter(
        runtime_repository=runtime_repo,
        r2_repository=report_repo,
        writer=writer,
    ).publish(
        task_id=TASK,
        title="P7B report",
        admission_id=admission.admission_id,
        expected_generation_ids=(generation_input.generation_id,),
        ledger_id=ledger.ledger_id,
        review_ids=(review.review_id,),
        chapter_titles={"c1": "Chapter 1"},
        evidence_digests={"file:C/a.doc": "evidence-digest"},
        model="deterministic_renderer",
        prompt_version="chapter-writer:starter:v1",
    )
    version = report_repo.get(report_id)
    assert version is not None
    assert version.status.value == "ready"
    assert version.report_kind == "agent_aware_generation"
    read = read_narrative_version_strict(
        report_root / "reports.db", report_root, TASK, report_id
    )
    assert read is not None
    _version, manifest = read
    assert manifest.schema_version == "3.0"
    assert manifest.report_kind == "agent_aware_generation"
    assert manifest.provenance.assertion_ledger_id == ledger.ledger_id
    assert manifest.provenance.chapter_spec_hashes == (spec.input_hash,)
    assert manifest.provenance.context_pack_ids == (pack.context_pack_id,)
    assert manifest.provenance.context_pack_hashes == (pack.input_hash,)
    assert manifest.citations[0].evidence_key == "file:C/a.doc"
    assert manifest.sections[0].content.startswith("- 【事实】")
