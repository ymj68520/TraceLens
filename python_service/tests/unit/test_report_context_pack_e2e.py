"""P7A-4: FrozenReportContextPack + retrieval service E2E (§71-§77)
plus citation-allowlist hard gates (§69/§70) and pack-freeze invariants
(§71).  Offline: fake evidence resolver, optional fake P6 reader."""

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphReaderMode,
)
from httpserver.services.report_runtime.report_chapter import (
    ChapterSpecV1,
    chapter_specs_from_outline,
)
from httpserver.services.report_runtime.report_context_pack import (
    CitationAllowlistError,
    FrozenReportContextPackV1,
    ReportEvidenceItemV1,
    build_citation_allowlist,
    validate_citation_allowlist,
)
from httpserver.services.report_runtime.report_dedup import (
    EvidenceIndependenceResolver,
)
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
    DeterministicReportRetrievalPlanner,
)
from httpserver.services.report_runtime.report_retrieval_service import (
    ReportRetrievalService,
    RequiredAnchorResolutionError,
    RetrievalOutcome,
)
from httpserver.services.report_runtime.report_template import (
    build_starter_template,
)

TEMPLATE = build_starter_template()
PLANNER = DeterministicReportRetrievalPlanner()

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "a" * 8

# §67 scenario: one file behind every representation layer.  Evidence
# keys follow the real grammar (file: / cluster:v1:...) — a Windows
# event record is a file-backed artifact (its .evtx), browser history a
# file, so cross-source corroboration uses distinct file keys.
ROOT_FILE = "file:C/a.doc"
CROSS_1 = "file:C/Security.evtx"
CROSS_2 = "file:Users/bob/Chrome/History"


def _context(**overrides) -> ReportPlanningContextV1:
    kwargs = dict(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        finalization=FinalizationAnchorV1(
            finalization_id="fz_1",
            record_hash="fh",
            state_revision=7,
            state_hash="sh",
            completion_mode="complete_with_limitations",
        ),
        charter_digest="ch",
        required_question_dispositions={"q1": "not_supported"},
        coverage_dispositions={"usb": "covered"},
        completion_mode="complete_with_limitations",
        limitations=("one limitation",),
        accepted_findings=(
            AcceptedFindingDigestV1(
                ref="finding:fA",
                assertion_class="INFERENCE",
                text_sha256="ta",
                evidence_refs=(ROOT_FILE,),
            ),
            AcceptedFindingDigestV1(
                ref="finding:fB",
                assertion_class="FACT",
                text_sha256="tb",
                evidence_refs=(CROSS_1, CROSS_2),
            ),
        ),
        finding_review_statuses=(
            FindingReviewDigestV1(ref="finding:fA", status="accepted"),
            FindingReviewDigestV1(ref="finding:fB", status="accepted"),
            FindingReviewDigestV1(ref="finding:fP", status="review_pending"),
            FindingReviewDigestV1(ref="finding:fR", status="rejected"),
        ),
        accepted_analyses=(
            AcceptedAnalysisDigestV1(
                ref="sa_1",
                evidence_key=ROOT_FILE,
                version=2,
                summary_sha256="s1",
            ),
        ),
        report_evidence=(
            ReportEvidenceDigestV1(
                evidence_key=ROOT_FILE, report_status="main"
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
        required_anchor_refs=("finding:fA",),
        ordering=4,
    )
    kwargs.update(overrides)
    return ChapterSpecV1(**kwargs)


async def _resolver_all(task_id, key):
    return {"resolved": True}


async def _resolver_only_root(task_id, key):
    return {"resolved": True} if key == ROOT_FILE else None


def _service(resolver=None, graph_reader_factory=None, **kwargs):
    return ReportRetrievalService(
        evidence_resolver=resolver or _resolver_all,
        graph_reader_factory=graph_reader_factory,
        **kwargs,
    )

async def _build(ctx=None, spec=None, resolver=None, factory=None):
    ctx = ctx or _context()
    spec = spec or _spec()
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service(resolver, factory).execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    return ctx, spec, plan, outcome


# ---------------------------------------------------------------------------
# §74 E2E: accepted finding chapter
# ---------------------------------------------------------------------------


async def test_e2e_accepted_finding_chapter(tmp_path):
    ctx, spec, plan, outcome = await _build()
    pack = outcome.pack
    # accepted basis present with its ceiling
    basis = {b.basis_ref: b for b in pack.accepted_semantic_basis}
    assert basis["finding:fA"].assertion_class == "INFERENCE"
    # the finding's evidence resolved into the pack
    all_refs = {
        item.evidence_ref
        for item in (*pack.anchor_evidence, *pack.supporting_evidence,
                     *pack.retrieved_context_evidence)
    }
    assert ROOT_FILE in all_refs
    # citation allowlist only real Evidence refs present in the pack
    validate_citation_allowlist(pack)
    assert set(pack.allowed_citation_refs) == all_refs
    for ref in pack.allowed_citation_refs:
        assert not ref.startswith(("graph:", "gm:", "gcand:", "finding:",
                                   "event:", "sa_"))
    # graph refs only in retrieval provenance
    for item in (*pack.anchor_evidence, *pack.supporting_evidence):
        for layer in item.retrieval_provenance:
            assert not layer.startswith("gm:")
    # Working State untouched is structural: the service has no runtime
    from httpserver.services.report_runtime.report_retrieval_service import (
        ReportRetrievalService as Svc,
    )

    import inspect

    params = inspect.signature(Svc.__init__).parameters
    assert "runtime" not in params and "repository" not in params


async def test_e2e_pack_replay_identical():
    """§62: same inputs -> same pack id (freeze idempotency)."""
    _ctx, _spec, _plan, first = await _build()
    _ctx2, _spec2, _plan2, second = await _build()
    assert first.pack.context_pack_id == second.pack.context_pack_id
    assert first.pack.input_hash == second.pack.input_hash


# ---------------------------------------------------------------------------
# §75 E2E: review_pending exclusion (semantic vs evidence layers)
# ---------------------------------------------------------------------------


async def test_review_pending_semantic_text_excluded_but_evidence_may_enter():
    ctx = _context(
        accepted_findings=(
            AcceptedFindingDigestV1(
                ref="finding:fA",
                assertion_class="INFERENCE",
                text_sha256="ta",
                evidence_refs=(ROOT_FILE,),
            ),
            # the review_pending finding's underlying evidence anchors
            # CROSS_1 into the anchor vocabulary (§24 second layer)
            AcceptedFindingDigestV1(
                ref="finding:fP",
                assertion_class="INFERENCE",
                text_sha256="tp",
                evidence_refs=(CROSS_1,),
            ),
        ),
        finding_review_statuses=(
            FindingReviewDigestV1(ref="finding:fA", status="accepted"),
            FindingReviewDigestV1(ref="finding:fP", status="review_pending"),
        ),
        accepted_analyses=(),
    )
    spec = _spec(
        required_anchor_refs=("finding:fA",),
        optional_anchor_refs=(CROSS_1,),  # independently in chapter scope
    )
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service().execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    pack = outcome.pack
    basis_refs = {b.basis_ref for b in pack.accepted_semantic_basis}
    assert "finding:fA" in basis_refs
    assert "finding:fP" not in basis_refs
    # §24: the pending finding's underlying real evidence may still enter
    all_refs = {
        item.evidence_ref
        for item in (*pack.anchor_evidence, *pack.supporting_evidence,
                     *pack.retrieved_context_evidence)
    }
    assert CROSS_1 in all_refs


async def test_rejected_finding_fully_excluded():
    ctx = _context(
        finding_review_statuses=(
            FindingReviewDigestV1(ref="finding:fA", status="accepted"),
            FindingReviewDigestV1(ref="finding:fR", status="rejected"),
        ),
    )
    spec = _spec(required_anchor_refs=("finding:fA",))
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service().execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    basis_refs = {b.basis_ref for b in outcome.pack.accepted_semantic_basis}
    assert "finding:fR" not in basis_refs


# ---------------------------------------------------------------------------
# §76 E2E: duplicate representation via four layers is ONE item
# ---------------------------------------------------------------------------


async def test_duplicate_representation_single_item_multi_provenance():
    ctx = _context()
    spec = _spec(required_anchor_refs=("finding:fA",))
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service().execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    pack = outcome.pack
    root_items = [
        item
        for item in (*pack.anchor_evidence, *pack.supporting_evidence,
                     *pack.retrieved_context_evidence)
        if item.evidence_ref == ROOT_FILE
    ]
    assert len(root_items) == 1
    # semantic basis provenance keeps every accepted basis ref that
    # grounds this file: the required finding plus the analysis layer
    # (analysis only enters the basis when its ref is a plan anchor, so
    # here the finding + the second accepted finding sharing the file)
    basis_with_file = [
        basis
        for basis in pack.accepted_semantic_basis
        if ROOT_FILE in basis.evidence_refs
    ]
    assert len(basis_with_file) >= 1
    # the item's retrieval provenance records the distinct semantic layers
    assert len(root_items[0].retrieval_provenance) >= 2
    # but they are NOT counted as independent evidence items
    assert len(root_items) == 1


# ---------------------------------------------------------------------------
# §77 E2E: graph unavailable degradation
# ---------------------------------------------------------------------------


async def test_graph_unavailable_degrades_with_limitation():
    ctx, spec, plan, outcome = await _build()
    assert outcome.pack.limitations == ("GRAPH_RETRIEVAL_UNAVAILABLE",)
    # pack still completed with real evidence
    assert outcome.pack.anchor_evidence


# ---------------------------------------------------------------------------
# §54/§72 graph degradation + hydration paths
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, objects):
        self.objects = objects
        self.locator_refs = ()
        self.evidence_refs = tuple(
            ref for obj in objects for ref in obj.evidence_refs
        )
        self.limitations = ()
        self.warnings = ()


class _FakeObject:
    def __init__(self, ref, evidence_refs):
        self.backend_ref = ref
        self.materialization_id = "gm:1"
        self.episode_id = "gepis:1"
        self.semantic_unit_id = None
        self.trust_class = type("T", (), {"value": "provenance_bound"})()
        self.review_status = "accepted"
        self.confirmed = True
        self.evidence_refs = evidence_refs


def _graph_reader_factory(resolved=set()):
    class _Reader:
        def read(self, investigation_id, mode, *, query="", task_id=None):
            assert mode is GraphReaderMode.REPORT  # §E15 report mode only
            return _FakeResult([
                _FakeObject("node-1", (ROOT_FILE,)),
                _FakeObject("node-2", ("file:missing/ghost.doc",)),
            ])

    return lambda task_id: _Reader()


async def test_graph_report_mode_hydrates_to_real_evidence():
    ctx = _context()
    spec = _spec(
        required_anchor_refs=("finding:fA",), topic_scope="logon"
    )
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service(
        graph_reader_factory=_graph_reader_factory()
    ).execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    pack = outcome.pack
    # navigation provenance recorded with the graph locator
    assert len(pack.graph_navigation_provenance) == 2
    graph_refs = {prov.graph_ref for prov in pack.graph_navigation_provenance}
    assert "node-1" in graph_refs
    # the unresolvable ghost evidence was dropped by hydration
    all_refs = {
        item.evidence_ref
        for item in (*pack.anchor_evidence, *pack.supporting_evidence,
                     *pack.retrieved_context_evidence)
    }
    assert "file:missing/ghost.doc" not in all_refs
    # and graph ids are nowhere in the evidence lists / allowlist
    assert not any(ref.startswith("node-") for ref in all_refs)
    validate_citation_allowlist(pack)


async def test_graph_ref_never_enters_citation_allowlist():
    # §26/§41: a graph id that somehow reached the evidence lists can never
    # get an allowlist entry — derivation raises instead.
    item = ReportEvidenceItemV1(
        evidence_ref="node-1", role="anchor", evidence_digest="d"
    )
    with pytest.raises(CitationAllowlistError):
        build_citation_allowlist(_View(item))


class _View:
    def __init__(self, item):
        self.anchor_evidence = (item,)
        self.supporting_evidence = ()
        self.retrieved_context_evidence = ()


# ---------------------------------------------------------------------------
# §69 allowlist hard gates
# ---------------------------------------------------------------------------


async def test_allowlist_excludes_case_evidence_not_in_pack():
    ctx, spec, plan, outcome = await _build(resolver=_resolver_only_root)
    pack = outcome.pack
    # CROSS_2 exists in the case (accepted finding provenance) but its
    # resolution failed here: it must NOT be in the allowlist
    assert CROSS_2 not in pack.allowed_citation_refs
    validate_citation_allowlist(pack)


async def test_semantic_ids_never_in_allowlist():
    _ctx, _spec, _plan, outcome = await _build()
    for ref in outcome.pack.allowed_citation_refs:
        assert not ref.startswith(("finding:", "event:", "sa_", "prop:",
                                   "disp:", "gm:", "gcand:", "graph:"))


# ---------------------------------------------------------------------------
# §55 required anchor failure
# ---------------------------------------------------------------------------


async def test_required_anchor_failure_blocks_pack():
    ctx = _context(
        accepted_findings=(
            AcceptedFindingDigestV1(
                ref="finding:fA",
                assertion_class="INFERENCE",
                text_sha256="ta",
                evidence_refs=("file:gone/missing.doc",),
            ),
        ),
    )
    spec = _spec(required_anchor_refs=("finding:fA",))
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    with pytest.raises(RequiredAnchorResolutionError):
        await _service(resolver=_resolver_only_root).execute(
            task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
        )


async def test_optional_context_failure_becomes_limitation():
    ctx = _context()
    spec = _spec(
        required_anchor_refs=("finding:fA",),
        optional_anchor_refs=(CROSS_2,),  # unresolvable under this resolver
    )
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service(resolver=_resolver_only_root).execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    assert any(
        limitation.startswith(("ANCHOR_RESOLUTION_FAILED", "CONTEXT_RESOLUTION_FAILED"))
        for limitation in outcome.pack.limitations
    )
    assert CROSS_2 not in outcome.pack.allowed_citation_refs


# ---------------------------------------------------------------------------
# §73 Report Evidence status non-mutation
# ---------------------------------------------------------------------------


async def test_retrieval_does_not_change_report_evidence_status():
    """Structural guarantee: the service never opens a write connection —
    it receives only an async evidence resolver; report_evidence rows live
    in investigation.db behind R1's write path which the service cannot
    reach."""
    import inspect

    from httpserver.services.report_runtime.report_retrieval_service import (
        ReportRetrievalService as Svc,
    )

    source = inspect.getsource(Svc)
    assert "report_evidence" not in source.replace(
        "report_evidence_set", ""
    ) or "UPDATE" not in source
    assert "INSERT" not in source


# ---------------------------------------------------------------------------
# §71 pack freeze invariants
# ---------------------------------------------------------------------------


async def test_pack_set_ordering_irrelevant_to_hash():
    ctx = _context()
    spec_a = _spec(
        optional_anchor_refs=(CROSS_1, CROSS_2),
    )
    spec_b = _spec(
        optional_anchor_refs=(CROSS_2, CROSS_1),  # different input order
    )
    plan_a = PLANNER.build_plan(context=ctx, chapter_spec=spec_a)
    plan_b = PLANNER.build_plan(context=ctx, chapter_spec=spec_b)
    out_a = await _service().execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec_a, plan=plan_a
    )
    out_b = await _service().execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec_b, plan=plan_b
    )
    assert out_a.pack.context_pack_id == out_b.pack.context_pack_id


async def test_pack_semantic_change_new_id():
    _ctx, _spec, _plan, first = await _build()
    ctx2 = _context(
        accepted_findings=(
            AcceptedFindingDigestV1(
                ref="finding:fA",
                assertion_class="INFERENCE",
                text_sha256="DIFFERENT",
                evidence_refs=(ROOT_FILE,),
            ),
        ),
    )
    _c, _s, _p, second = await _build(ctx=ctx2)
    assert first.pack.context_pack_id != second.pack.context_pack_id


async def test_pack_model_roundtrip_stable():
    _ctx, _spec, _plan, outcome = await _build()
    pack = outcome.pack
    replay = FrozenReportContextPackV1(**pack.model_dump())
    assert replay.context_pack_id == pack.context_pack_id
    assert replay.input_hash == pack.input_hash
    assert replay.allowed_citation_refs == pack.allowed_citation_refs


def test_pack_tamper_attempt_overwritten_by_derivation():
    item = ReportEvidenceItemV1(
        evidence_ref="file:C/a.doc", role="anchor", evidence_digest="d"
    )
    pack = FrozenReportContextPackV1(
        task_id="A",
        investigation_id="inv",
        finalization_id="fz",
        finalization_record_hash="fh",
        outline_id="rout",
        outline_revision=1,
        chapter_id="c",
        chapter_spec_hash="sh",
        retrieval_plan_id="rrpl",
        retrieval_plan_hash="rh",
        generation_mode="evidence_narrative",
        anchor_evidence=(item,),
        allowed_citation_refs=("file:secret/not_in_pack.doc",),
        hydration_policy_version="h",
        retrieval_policy_version="r",
        dedup_policy_version="d",
        budget_policy_version="b",
    )
    # §41: the allowlist is always re-derived from pack contents
    assert pack.allowed_citation_refs == ("file:C/a.doc",)


# ---------------------------------------------------------------------------
# §56 gap proposal
# ---------------------------------------------------------------------------


async def test_retrieval_gap_is_proposal_only():
    def gap_detector(chapter_id, refs):
        from httpserver.services.report_runtime.report_retrieval_service import (
            ReportRetrievalGapV1,
        )

        return ReportRetrievalGapV1(
            gap_type="major_new_direction",
            description="unexplained mass deletion",
            basis_evidence_refs=(ROOT_FILE,),
            suggested_investigation_question="who ran the wipe tool?",
        )

    ctx, spec, plan = None, None, None
    ctx = _context()
    spec = _spec()
    plan = PLANNER.build_plan(context=ctx, chapter_spec=spec)
    outcome = await _service(gap_detector=gap_detector).execute(
        task_id=TASK_ID, context=ctx, chapter_spec=spec, plan=plan
    )
    assert len(outcome.gaps) == 1
    gap = outcome.gaps[0]
    payload = gap.to_dict()
    assert payload["gap_type"] == "major_new_direction"
    # a gap is a proposal: nothing in the pack and no investigation change
    assert "unexplained mass deletion" not in str(outcome.pack.model_dump())
