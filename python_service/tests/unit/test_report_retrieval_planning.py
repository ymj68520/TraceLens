"""P7A-2 bounded report retrieval planning tests (§65).

Covers: Report Evidence prioritized as anchor; accepted Finding / Event /
Analysis anchors; chapter scope bounded; review_pending and rejected
semantic basis excluded; graph query uses report mode; no whole-case
scan; planner creates no Finding / Working State (pure function of
inputs).
"""

import pytest

from httpserver.services.report_runtime.report_chapter import ChapterSpecV1
from httpserver.services.report_runtime.report_outline import (
    AcceptedAnalysisDigestV1,
    AcceptedFindingDigestV1,
    FindingReviewDigestV1,
    FinalizationAnchorV1,
    InvestigationEventDigestV1,
    ReportEvidenceDigestV1,
    ReportPlanningContextV1,
)
from httpserver.services.report_runtime.report_retrieval import (
    ANCHOR_PRIORITY,
    DeterministicReportRetrievalPlanner,
    ReportRetrievalPlanV1,
    RetrievalPlanError,
)
from httpserver.services.report_runtime.report_template import (
    build_starter_template,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "a" * 8
TEMPLATE = build_starter_template()


def _context(**overrides) -> ReportPlanningContextV1:
    kwargs = dict(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        finalization=FinalizationAnchorV1(
            finalization_id="fz_1",
            record_hash="fh",
            state_revision=3,
            state_hash="sh",
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
            FindingReviewDigestV1(ref="finding:f2", status="review_pending"),
            FindingReviewDigestV1(ref="finding:f3", status="rejected"),
        ),
        events=(
            InvestigationEventDigestV1(
                ref="event:e1@v2",
                event_id="e1",
                version=2,
                title_sha256="t",
            ),
        ),
        accepted_analyses=(
            AcceptedAnalysisDigestV1(
                ref="sa_abc", evidence_key="file:D/b.txt", version=1,
                summary_sha256="s",
            ),
        ),
        report_evidence=(
            ReportEvidenceDigestV1(
                evidence_key="file:C/a.doc", report_status="main"
            ),
        ),
        template_id=TEMPLATE.template_id,
        template_version=TEMPLATE.template_version,
        template_hash=TEMPLATE.template_hash,
    )
    kwargs.update(overrides)
    return ReportPlanningContextV1(**kwargs)


def _spec(**overrides) -> ChapterSpecV1:
    kwargs = dict(
        chapter_id="core_investigation_findings",
        outline_id="rout:x",
        outline_revision=1,
        outline_hash="oh",
        title="调查发现",
        generation_mode="evidence_narrative",
        required_anchor_refs=("finding:f1",),
        ordering=4,
    )
    kwargs.update(overrides)
    return ChapterSpecV1(**kwargs)


PLANNER = DeterministicReportRetrievalPlanner()


def test_report_evidence_prioritized_as_anchor():
    ctx = _context()
    spec = _spec(
        required_anchor_refs=("finding:f1",),
        optional_anchor_refs=("file:C/a.doc",),
    )
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    # §22 priority: report evidence first even though declared optional
    assert plan.anchor_refs[0] == "file:C/a.doc"
    assert plan.anchor_kinds[0] == "report_evidence"
    assert ANCHOR_PRIORITY[0] == "report_evidence"


def test_accepted_finding_event_analysis_anchors():
    ctx = _context()
    spec = _spec(
        required_anchor_refs=(
            "sa_abc",
            "event:e1@v2",
            "finding:f1",
            "file:D/b.txt",
        ),
    )
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    # accepted semantics + the accepted analysis's evidence anchor,
    # priority-ordered (report_evidence kind first, then finding/event/
    # analysis). file:C/a.doc is only a finding-provenance ref here, not
    # a report-evidence row, so it is not independently an anchor.
    assert plan.anchor_refs == (
        "file:D/b.txt",
        "finding:f1",
        "event:e1@v2",
        "sa_abc",
    )
    assert set(plan.semantic_basis_refs) == {"finding:f1", "event:e1@v2",
                                            "sa_abc"}


def test_semantic_basis_excludes_review_pending_and_rejected():
    ctx = _context()
    with pytest.raises(RetrievalPlanError) as excinfo:
        PLANNER.build_plan(
            context=ctx,
            chapter_spec=_spec(required_anchor_refs=("finding:f2",)),
        )
    assert excinfo.value.code == "semantic_ref_not_accepted"
    with pytest.raises(RetrievalPlanError) as excinfo:
        PLANNER.build_plan(
            context=ctx,
            chapter_spec=_spec(required_anchor_refs=("finding:f3",)),
        )
    assert excinfo.value.code == "semantic_ref_not_accepted"


def test_unknown_anchor_rejected():
    ctx = _context()
    with pytest.raises(RetrievalPlanError) as excinfo:
        PLANNER.build_plan(
            context=ctx,
            chapter_spec=_spec(required_anchor_refs=("finding:f9",)),
        )
    assert excinfo.value.code == "unknown_anchor"


def test_graph_ref_never_an_anchor():
    ctx = _context()
    with pytest.raises(RetrievalPlanError) as excinfo:
        PLANNER.build_plan(
            context=ctx,
            chapter_spec=_spec(required_anchor_refs=("graph:node-1",)),
        )
    assert excinfo.value.code == "graph_ref_forbidden"


def test_graph_query_uses_report_mode_and_is_intent_only():
    ctx = _context()
    spec = _spec(topic_scope="shared logon cluster")
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    assert len(plan.graph_queries) == 1
    query = plan.graph_queries[0]
    assert query.mode == "report"
    assert query.query_text == "shared logon cluster"
    # the plan carries no graph results at all
    assert not any(
        key.startswith("graph_result") for key in plan.model_dump()
    )


def test_no_whole_case_scan_expansions_are_bounded():
    ctx = _context()
    plan = PLANNER.build_plan(context=ctx, chapter_spec=_spec())
    for expansion in plan.deterministic_expansions:
        assert expansion.max_items >= 1
        assert expansion.basis_ref != "*"
        assert expansion.expansion_kind in (
            "event_evidence_links",
            "finding_evidence_provenance",
            "analysis_evidence_refs",
            "report_evidence_set",
        )
    # no unrestricted-scan expansion kind exists
    kinds = {e.expansion_kind for e in plan.deterministic_expansions}
    assert "whole_case_search" not in kinds
    assert "full_text_scan" not in kinds


def test_plan_replay_same_id_and_hash():
    ctx = _context()
    spec = _spec(topic_scope="t")
    plan_a = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    plan_b = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    assert plan_a.retrieval_plan_id == plan_b.retrieval_plan_id
    assert plan_a.input_hash == plan_b.input_hash
    replay = ReportRetrievalPlanV1(**plan_a.model_dump())
    assert replay.retrieval_plan_id == plan_a.retrieval_plan_id


def test_planner_pure_no_finding_or_state_creation():
    """§20/§65: the planner is a pure function — no runtime, no store, no
    writes. It accepts only the frozen context and the spec."""
    import inspect

    signature = inspect.signature(PLANNER.build_plan)
    assert set(signature.parameters) == {"context", "chapter_spec"}


def test_chapter_scope_bounded_into_plan():
    ctx = _context()
    spec = _spec(
        entity_scope=("user:bob", "user:alice"),
        time_scope={"start": 1000, "end": 2000},
    )
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    assert plan.entity_scope == ("user:alice", "user:bob")  # canonical
    assert plan.time_scope == {"start": 1000, "end": 2000}
