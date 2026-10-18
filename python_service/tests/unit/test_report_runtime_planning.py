"""P7A-1 report planning contracts: admission / template / planning
context / outline plan / outline validation / chapter specs / persistence.

Covers P7A §63 (outline tests) and §64 (ChapterSpec tests) plus the
repository-investigation-driven persistence checks (§78 subset: fresh
schema, immutability by INSERT OR IGNORE replay, existing report DB not
disturbed).
"""

import json
import sqlite3

import pytest

from httpserver.services.report_runtime.report_admission import (
    ReportRuntimeAdmissionError,
    ReportRuntimeAdmissionService,
    ReportRuntimeAdmissionV1,
)
from httpserver.services.report_runtime.report_chapter import (
    ChapterSpecV1,
    chapter_specs_from_outline,
)
from httpserver.services.report_runtime.report_outline import (
    AcceptedFindingDigestV1,
    DeterministicReportOutlineBuilder,
    FindingReviewDigestV1,
    FinalizationAnchorV1,
    OutlineChapterV1,
    OutlineValidationError,
    ReportOutlinePlanV1,
    ReportPlanningContextBuilder,
    ReportPlanningContextError,
    ReportPlanningContextV1,
    validate_outline_plan,
)
from httpserver.services.report_runtime.report_repository import (
    ReportRuntimeRepository,
)
from httpserver.services.report_runtime.report_template import (
    DynamicChapterPolicyV1,
    ReportTemplateDefinitionV1,
    ReportTemplateSectionV1,
    build_starter_template,
    default_template_registry,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "a" * 8
FINALIZATION_ID = "fz_" + "b" * 8

TEMPLATE = build_starter_template()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _planning_context(**overrides) -> ReportPlanningContextV1:
    kwargs = dict(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        finalization=FinalizationAnchorV1(
            finalization_id=FINALIZATION_ID,
            record_hash="fh1",
            state_revision=3,
            state_hash="sh1",
            completion_mode="complete",
        ),
        charter_digest="ch",
        required_question_dispositions={"q1": "not_supported"},
        coverage_dispositions={"usb": "covered"},
        completion_mode="complete",
        accepted_findings=(
            AcceptedFindingDigestV1(
                ref="finding:f1",
                assertion_class="FACT",
                text_sha256="x",
                evidence_refs=("file:C/a.doc",),
            ),
        ),
        finding_review_statuses=(
            FindingReviewDigestV1(ref="finding:f1", status="accepted"),
        ),
        template_id=TEMPLATE.template_id,
        template_version=TEMPLATE.template_version,
        template_hash=TEMPLATE.template_hash,
    )
    kwargs.update(overrides)
    return ReportPlanningContextV1(**kwargs)


def _deterministic_plan(ctx=None) -> ReportOutlinePlanV1:
    ctx = ctx or _planning_context()
    return DeterministicReportOutlineBuilder().build(ctx, TEMPLATE)


# ---------------------------------------------------------------------------
# §63 outline tests
# ---------------------------------------------------------------------------


def test_template_registry_starter_versioned():
    registry = default_template_registry()
    template = registry.starter()
    assert template.template_id == "forensic_investigation_report"
    assert template.template_version.startswith("starter:")
    # starter must NOT claim its sections are the permanent architecture
    assert template.narrative_rules_status == "TBD"
    assert "TBD" in template.notes or "TBD" in template.notes.lower()


def test_template_hash_replay_stable():
    template = build_starter_template()
    assert template.template_hash == build_starter_template().template_hash


def test_deterministic_outline_same_input_same_hash():
    ctx = _planning_context()
    plan_a = _deterministic_plan(ctx)
    plan_b = _deterministic_plan(_planning_context(**ctx.model_dump()))
    assert plan_a.outline_id == plan_b.outline_id
    assert plan_a.input_hash == plan_b.input_hash


def test_deterministic_outline_replay_via_roundtrip():
    plan = _deterministic_plan()
    replay = ReportOutlinePlanV1(**plan.model_dump())
    assert replay.outline_id == plan.outline_id
    assert replay.input_hash == plan.input_hash


def test_outline_requires_completed_investigation_via_builder():
    """The planning-context builder fails closed on a missing store."""
    from httpserver.services.evidence.exceptions import EvidenceStoreError

    builder = ReportPlanningContextBuilder("/nonexistent/x.db", TASK_ID)
    with pytest.raises(EvidenceStoreError):
        builder.assemble(
            INVESTIGATION_ID, FINALIZATION_ID, template=TEMPLATE
        )


def test_outline_missing_required_section_rejected():
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    stripped = [
        chapter
        for chapter in plan.chapters
        if chapter.section_id != "evidence_inventory"
    ]
    bad = ReportOutlinePlanV1(
        **{
            **plan.model_dump(),
            "chapters": tuple(stripped),
            "planner_kind": "model_assisted",
        }
    )
    with pytest.raises(OutlineValidationError) as excinfo:
        validate_outline_plan(bad, ctx, TEMPLATE)
    assert excinfo.value.code == "missing_required_section"


def test_outline_review_pending_semantic_ref_rejected():
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    ctx_pending = _planning_context(
        finding_review_statuses=(
            FindingReviewDigestV1(ref="finding:f1", status="accepted"),
            FindingReviewDigestV1(ref="finding:f2", status="review_pending"),
        ),
    )
    # the plan must be built against the SAME context it is validated
    # against (context_id/hash are part of the outline identity)
    pending_plan = DeterministicReportOutlineBuilder().build(
        ctx_pending, TEMPLATE
    )
    bad = ReportOutlinePlanV1(
        **{
            **pending_plan.model_dump(),
            "planning_basis_refs": ("finding:f2",),
            "chapters": tuple(
                chapter.model_copy(
                    update={
                        "planning_basis_refs": ("finding:f2",)
                        if chapter.section_id
                        == "investigation_findings"
                        else chapter.planning_basis_refs
                    }
                )
                for chapter in pending_plan.chapters
            ),
            "planner_kind": "model_assisted",
        }
    )
    with pytest.raises(OutlineValidationError) as excinfo:
        validate_outline_plan(bad, ctx_pending, TEMPLATE)
    assert excinfo.value.code == "semantic_ref_not_accepted"


def test_outline_unknown_basis_ref_rejected():
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    bad = ReportOutlinePlanV1(
        **{
            **plan.model_dump(),
            "planning_basis_refs": ("finding:f9",),
            "planner_kind": "model_assisted",
        }
    )
    with pytest.raises(OutlineValidationError) as excinfo:
        validate_outline_plan(bad, ctx, TEMPLATE)
    assert excinfo.value.code == "unknown_basis_ref"


def test_outline_graph_ref_rejected():
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    bad = ReportOutlinePlanV1(
        **{
            **plan.model_dump(),
            "planning_basis_refs": ("graph:node-1",),
            "planner_kind": "model_assisted",
        }
    )
    with pytest.raises(OutlineValidationError) as excinfo:
        validate_outline_plan(bad, ctx, TEMPLATE)
    assert excinfo.value.code == "graph_ref_forbidden"


def test_outline_duplicate_chapter_id_rejected():
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    first = plan.chapters[0]
    dup = OutlineChapterV1(
        chapter_id=first.chapter_id,
        title="Dup",
        ordering=len(plan.chapters) + 1,
    )
    bad = ReportOutlinePlanV1(
        **{**plan.model_dump(), "chapters": (*plan.chapters, dup)}
    )
    with pytest.raises(OutlineValidationError) as excinfo:
        validate_outline_plan(bad, ctx, TEMPLATE)
    assert excinfo.value.code == "chapter_ids_invalid"


def test_outline_version_edit_creates_new_immutable_version():
    """§15: an analyst edit is a new revision row, never an UPDATE; the
    parent stays auditable."""
    ctx = _planning_context()
    plan_v1 = _deterministic_plan(ctx)
    edited_chapters = [
        chapter.model_copy(update={"title": chapter.title + "（修订）"})
        if chapter.section_id == "case_overview"
        else chapter
        for chapter in plan_v1.chapters
    ]
    plan_v2 = ReportOutlinePlanV1(
        **{
            **plan_v1.model_dump(),
            "chapters": tuple(edited_chapters),
            "planner_kind": "analyst_modified",
            "parent_outline_id": plan_v1.outline_id,
            "revision_reason": "analyst retitle",
        }
    )
    assert plan_v2.outline_id != plan_v1.outline_id
    assert plan_v2.parent_outline_id == plan_v1.outline_id
    validate_outline_plan(plan_v2, ctx, TEMPLATE)


def test_outline_dynamic_chapter_requires_accepted_finding():
    ctx_with_pending = _planning_context(
        finding_review_statuses=(
            FindingReviewDigestV1(ref="finding:f1", status="accepted"),
            FindingReviewDigestV1(ref="finding:f2", status="review_pending"),
        ),
    )
    plan = DeterministicReportOutlineBuilder().build(ctx_with_pending, TEMPLATE)
    dynamic_bad = OutlineChapterV1(
        chapter_id="dynamic_finding:f2",
        title="X",
        section_kind="dynamic",
        planning_basis_refs=("finding:f2",),
        ordering=len(plan.chapters) + 1,
    )
    bad = ReportOutlinePlanV1(
        **{
            **plan.model_dump(),
            "chapters": (*plan.chapters, dynamic_bad),
            "planner_kind": "model_assisted",
        }
    )
    with pytest.raises(OutlineValidationError) as excinfo:
        validate_outline_plan(bad, ctx_with_pending, TEMPLATE)
    # either code is a fail-closed rejection of the pending finding basis;
    # the general chapter-ref walk fires first
    assert excinfo.value.code in (
        "dynamic_basis_unaccepted",
        "semantic_ref_not_accepted",
    )


def test_outline_model_failure_falls_back_deterministic():
    """§13/§63: an invalid model output is rejected and the deterministic
    builder still produces a valid plan (fallback contract)."""
    ctx = _planning_context()
    fallback = _deterministic_plan(ctx)
    validate_outline_plan(fallback, ctx, TEMPLATE)


# ---------------------------------------------------------------------------
# §64 ChapterSpec tests
# ---------------------------------------------------------------------------


def test_chapter_specs_three_generation_modes_supported():
    spec = ChapterSpecV1(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="h",
        title="T",
        generation_mode="evidence_narrative",
        ordering=1,
    )
    assert spec.generation_mode in ("deterministic", "evidence_narrative")
    assert spec.context_stage == "ready"


def test_chapter_spec_synthesis_is_deferred():
    spec = ChapterSpecV1(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="h",
        title="T",
        generation_mode="synthesis",
        context_stage="deferred_until_chapter_digests",
        ordering=1,
    )
    assert spec.context_stage == "deferred_until_chapter_digests"
    with pytest.raises(ValueError):
        ChapterSpecV1(
            chapter_id="c2",
            outline_id="rout:x",
            outline_revision=1,
            outline_hash="h",
            title="T",
            generation_mode="synthesis",
            ordering=2,
        )


def test_chapter_specs_from_outline_modes_and_anchors():
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    specs = chapter_specs_from_outline(plan)
    by_id = {spec.chapter_id: spec for spec in specs}
    assert (
        by_id["core_evidence_inventory"].generation_mode == "deterministic"
    )
    assert (
        by_id["core_investigation_findings"].generation_mode
        == "evidence_narrative"
    )
    assert by_id["core_investigation_findings"].required_anchor_refs == (
        "finding:f1",
    )
    assert by_id["dynamic_finding:f1"].required_anchor_refs == ("finding:f1",)
    # §17: spec identity is pinned to the outline revision
    assert all(spec.outline_id == plan.outline_id for spec in specs)
    assert all(
        spec.outline_revision == plan.outline_revision for spec in specs
    )


def test_chapter_spec_same_semantic_input_same_hash():
    kwargs = dict(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="h",
        title="T",
        generation_mode="deterministic",
        ordering=1,
        entity_scope=("user:b", "user:a"),
    )
    spec_a = ChapterSpecV1(**kwargs)
    spec_b = ChapterSpecV1(**kwargs)
    assert spec_a.input_hash == spec_b.input_hash
    assert spec_a.entity_scope == ("user:a", "user:b")  # canonical order


def test_chapter_spec_semantic_change_new_hash():
    spec = ChapterSpecV1(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="h",
        title="T",
        generation_mode="deterministic",
        ordering=1,
    )
    changed = ChapterSpecV1(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="h",
        title="T2",
        generation_mode="deterministic",
        ordering=1,
    )
    assert spec.input_hash != changed.input_hash


def test_chapter_spec_cannot_mutate_outline_identity():
    """A spec is bound to one outline revision; changing the revision
    changes the spec hash (no in-place mutation of the outline)."""
    spec = ChapterSpecV1(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="h1",
        title="T",
        generation_mode="deterministic",
        ordering=1,
    )
    rebound = ChapterSpecV1(
        chapter_id="c",
        outline_id="rout:x",
        outline_revision=2,
        outline_hash="h2",
        title="T",
        generation_mode="deterministic",
        ordering=1,
    )
    assert spec.input_hash != rebound.input_hash


# ---------------------------------------------------------------------------
# admission tests (§5)
# ---------------------------------------------------------------------------


def test_admission_model_replay_stable_and_ids_differ():
    admission = ReportRuntimeAdmissionV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        finalization_id=FINALIZATION_ID,
        finalization_record_hash="fh",
        final_working_state_revision=3,
        final_working_state_hash="sh",
        completion_mode="complete",
        report_template_id=TEMPLATE.template_id,
        report_template_version=TEMPLATE.template_version,
        report_template_hash=TEMPLATE.template_hash,
        report_generation_request_id="rreq_1",
        requested_by="analyst",
    )
    replay = ReportRuntimeAdmissionV1(**admission.model_dump())
    assert replay.input_hash == admission.input_hash
    # admission_id is the request identity: a replayed payload keeps the
    # frozen id (identity is NOT re-derived on validation).
    assert replay.admission_id == admission.admission_id
    fresh = ReportRuntimeAdmissionV1(
        **{
            **admission.model_dump(),
            "admission_id": None,
            "created_at": None,
        }
    )
    assert fresh.admission_id != admission.admission_id


def test_admission_service_denies_active_investigation():
    class FakeRuntime:
        class _Status:
            value = "active"

        def get_investigation(self, investigation_id):
            investigation = type("I", (), {})()
            investigation.status = self._Status
            return investigation

        def get_finalization(self, investigation_id):
            return None

    async def provider(task_id):
        return FakeRuntime()

    service = ReportRuntimeAdmissionService(
        provider, _NullRepository(), default_template_registry()
    )
    import asyncio

    with pytest.raises(ReportRuntimeAdmissionError) as excinfo:
        asyncio.run(
            service.admit(TASK_ID, INVESTIGATION_ID, requested_by="analyst")
        )
    assert excinfo.value.code == "investigation_not_completed"


class _NullRepository:
    def record_report_runtime_admission(self, admission):
        raise AssertionError("denied admission must not persist")


def test_admission_service_denies_missing_finalization():
    class _Status:
        value = "completed"

    class _Investigation:
        status = _Status()

    class FakeRuntime:
        def get_investigation(self, investigation_id):
            return _Investigation()

        def get_finalization(self, investigation_id):
            return None

    async def provider(task_id):
        return FakeRuntime()

    service = ReportRuntimeAdmissionService(
        provider, _NullRepository(), default_template_registry()
    )
    import asyncio

    with pytest.raises(ReportRuntimeAdmissionError) as excinfo:
        asyncio.run(
            service.admit(TASK_ID, INVESTIGATION_ID, requested_by="analyst")
        )
    assert excinfo.value.code == "finalization_missing"


# ---------------------------------------------------------------------------
# persistence (§78 subset)
# ---------------------------------------------------------------------------


def _persist_plan(tmp_path):
    repo = ReportRuntimeRepository(tmp_path / "reports.db")
    ctx = _planning_context()
    plan = _deterministic_plan(ctx)
    repo.record_outline_version(plan)
    return repo, ctx, plan


def test_repository_fresh_schema_and_outline_roundtrip(tmp_path):
    repo, _ctx, plan = _persist_plan(tmp_path)
    got = repo.get_outline(plan.outline_id)
    assert got.outline_id == plan.outline_id
    assert got.input_hash == plan.input_hash
    # idempotent replay: no duplicate rows
    repo.record_outline_version(plan)
    assert len(repo.list_outlines(TASK_ID, INVESTIGATION_ID)) == 1


def test_repository_outline_versions_immutable_append_only(tmp_path):
    repo, ctx, plan = _persist_plan(tmp_path)
    edited = ReportOutlinePlanV1(
        **{
            **plan.model_dump(),
            "chapters": tuple(
                chapter.model_copy(update={"title": "新标题"})
                if chapter.section_id == "case_overview"
                else chapter
                for chapter in plan.chapters
            ),
            "planner_kind": "analyst_modified",
            "parent_outline_id": plan.outline_id,
        }
    )
    repo.record_outline_version(edited)
    rows = repo.list_outlines(TASK_ID, INVESTIGATION_ID)
    assert len(rows) == 2
    assert {row.outline_id for row in rows} == {
        plan.outline_id,
        edited.outline_id,
    }
    # parent version unchanged
    assert repo.get_outline(plan.outline_id).input_hash == plan.input_hash


def test_repository_chapter_specs_roundtrip(tmp_path):
    repo, _ctx, plan = _persist_plan(tmp_path)
    specs = chapter_specs_from_outline(plan)
    repo.record_chapter_specs(specs)
    loaded = repo.list_chapter_specs(plan.outline_id, 1)
    assert [spec.input_hash for spec in loaded] == [
        spec.input_hash for spec in specs
    ]
    # replay: still one row per spec
    repo.record_chapter_specs(specs)
    assert len(repo.list_chapter_specs(plan.outline_id, 1)) == len(specs)


def test_repository_coexists_with_report_tables(tmp_path):
    """§78: the planning tables live alongside the existing reports.db
    schema without disturbing it."""
    db_path = tmp_path / "reports.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE report_versions (
            report_id TEXT PRIMARY KEY, version INTEGER, scope_type TEXT,
            scope_id TEXT, status TEXT, title TEXT, task_ids_json TEXT,
            stage TEXT, progress INTEGER, created_at TEXT
        );
        INSERT INTO report_versions VALUES ('r1', 1, 'task', 'task-A',
            'ready', 'T', '[]', 'ready', 100, '2026-01-01');
        """
    )
    conn.commit()
    conn.close()
    repo = ReportRuntimeRepository(db_path)
    _ctx, plan = _persist_plan(tmp_path)[1:]
    repo.record_outline_version(plan)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT report_id, status FROM report_versions WHERE report_id='r1'"
    ).fetchone()
    conn.close()
    assert row == ("r1", "ready")
