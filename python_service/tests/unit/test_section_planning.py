from __future__ import annotations

from copy import deepcopy

from httpserver.services.citation_validation import CitationGraphBuilder
from httpserver.services.report_dataset import (
    DatasetValidation,
    ReportDataset,
    ReportDatasetClaim,
    ReportDatasetClaimEvidenceLink,
    ReportDatasetEvent,
    ReportDatasetEvidence,
)
from httpserver.services.section_planning import (
    SECTION_CITATION_GRAPH_HASH_MISMATCH,
    _citation_number,
    SECTION_CITATION_NOT_ALLOWED,
    SECTION_CLAIM_NOT_IN_GRAPH,
    SECTION_DATASET_HASH_MISMATCH,
    SECTION_UPSTREAM_CITATION_BLOCKED,
    SectionPlanBuilder,
)


def _dataset(
    events: list[ReportDatasetEvent],
    evidence_keys: list[str] = ["file:/a", "file:/b"],
    *,
    validation: DatasetValidation | None = None,
) -> ReportDataset:
    dataset = ReportDataset(
        task_id="task-1",
        dataset_version="1",
        generated_at="2026-08-13T00:00:00+00:00",
        events=events,
        report_evidence=[
            ReportDatasetEvidence(
                evidence_key=key,
                evidence_type="file",
                report_status="main",
                snapshot={"evidence_key": key},
            )
            for key in evidence_keys
        ],
        validation=validation or DatasetValidation(status="valid"),
        report_dataset_hash="",
    )
    dataset.report_dataset_hash = dataset.compute_hash()
    return dataset


def _claim(
    claim_id: str,
    claim_type: str,
    key: str = "file:/a",
    *,
    readiness: str = "report_ready",
) -> ReportDatasetClaim:
    return ReportDatasetClaim(
        claim_id=claim_id,
        event_version_id="version-1",
        claim_type=claim_type,
        claim_text=claim_id,
        readiness=readiness,
        evidence_links=[ReportDatasetClaimEvidenceLink(
            evidence_key=key,
            relation="supports",
            rationale="grounded",
        )],
    )


def _event(
    event_id: str,
    start_time: int | None,
    claims: list[ReportDatasetClaim],
) -> ReportDatasetEvent:
    return ReportDatasetEvent(
        event_id=event_id,
        event_version_id="version-1",
        title=event_id,
        start_time=start_time,
        claims=claims,
    )


def _valid_inputs():
    dataset = _dataset([
        _event("event-late", 200, [
            _claim("claim-z", "fact", "file:/a"),
            _claim("claim-inference", "inference", "file:/b"),
        ]),
        _event("event-early", 100, [
            _claim("claim-a", "hypothesis", "file:/a"),
        ]),
    ])
    graph = CitationGraphBuilder().build(dataset)
    return dataset, graph


def test_fixed_taxonomy_and_chronology_first_claim_order():
    dataset, graph = _valid_inputs()

    plan = SectionPlanBuilder().build(dataset, graph)

    assert [
        (section.section_id, section.section_type, section.order)
        for section in plan.sections
    ] == [
        ("SEC-001", "analysis.overview", 1),
        ("SEC-002", "analysis.timeline", 2),
        ("SEC-003", "analysis.evidence", 3),
        ("SEC-004", "analysis.findings", 4),
        ("SEC-005", "analysis.conclusion", 5),
    ]
    overview = plan.sections[0]
    assert overview.event_ids == ["event-early", "event-late"]
    assert overview.claim_ids == ["claim-a", "claim-inference", "claim-z"]
    assert plan.validation.status == "valid"


def test_overview_and_evidence_are_intentionally_overlapping():
    dataset, graph = _valid_inputs()

    plan = SectionPlanBuilder().build(dataset, graph)

    assert plan.sections[0].claim_ids == plan.sections[2].claim_ids
    assert plan.sections[0].allowed_citation_ids == plan.sections[2].allowed_citation_ids


def test_findings_and_conclusion_use_claim_type_projection():
    dataset, graph = _valid_inputs()

    plan = SectionPlanBuilder().build(dataset, graph)

    assert plan.sections[3].claim_ids == ["claim-inference", "claim-z"]
    assert plan.sections[4].claim_ids == ["claim-a", "claim-inference"]


def test_section_whitelist_comes_only_from_section_claim_edges():
    dataset, graph = _valid_inputs()

    plan = SectionPlanBuilder().build(dataset, graph)

    findings = plan.sections[3]
    assert findings.claim_ids == ["claim-inference", "claim-z"]
    assert findings.allowed_citation_ids == ["CIT-001", "CIT-002"]
    assert "CIT-003" not in findings.allowed_citation_ids
    assert graph.allowed_citation_ids == ["CIT-001", "CIT-002"]


def test_blocked_and_excluded_claims_are_not_assigned():
    dataset = _dataset([_event(
        "event-1", 100, [
            _claim("blocked", "fact", readiness="blocked"),
            _claim("excluded", "hypothesis", readiness="excluded"),
        ]
    )])
    graph = CitationGraphBuilder().build(dataset)

    plan = SectionPlanBuilder().build(dataset, graph)

    assert all(not section.claim_ids for section in plan.sections)
    assert all(not section.allowed_citation_ids for section in plan.sections)


def test_blocked_graph_fails_closed_with_empty_sections():
    dataset = _dataset([_event("event-1", 100, [_claim("claim-1", "fact")])])
    dataset.validation = DatasetValidation(status="blocked")
    graph = CitationGraphBuilder().build(dataset)

    plan = SectionPlanBuilder().build(dataset, graph)

    assert plan.validation.status == "blocked"
    assert any(error.code == SECTION_UPSTREAM_CITATION_BLOCKED for error in plan.validation.errors)
    assert all(not section.claim_ids for section in plan.sections)
    assert all(not section.event_ids for section in plan.sections)
    assert all(not section.allowed_citation_ids for section in plan.sections)


def test_dataset_and_graph_hash_mismatches_fail_closed():
    dataset, graph = _valid_inputs()
    dataset.report_dataset_hash = "wrong-dataset-hash"
    plan = SectionPlanBuilder().build(dataset, graph)
    assert plan.validation.status == "blocked"
    assert any(error.code == SECTION_DATASET_HASH_MISMATCH for error in plan.validation.errors)
    assert all(not section.claim_ids for section in plan.sections)

    dataset, graph = _valid_inputs()
    graph.citation_graph_hash = "wrong-graph-hash"
    plan = SectionPlanBuilder().build(dataset, graph)
    assert plan.validation.status == "blocked"
    assert any(
        error.code == SECTION_CITATION_GRAPH_HASH_MISMATCH
        for error in plan.validation.errors
    )
    assert all(not section.claim_ids for section in plan.sections)


def test_claim_missing_from_graph_is_reported():
    dataset, graph = _valid_inputs()
    graph.claim_citations = [
        claim for claim in graph.claim_citations if claim.claim_id != "claim-z"
    ]
    graph.citation_graph_hash = graph.compute_hash()

    plan = SectionPlanBuilder().build(dataset, graph)

    assert plan.validation.status == "blocked"
    assert any(error.code == SECTION_CLAIM_NOT_IN_GRAPH for error in plan.validation.errors)


def test_claim_edge_outside_global_allowlist_is_reported():
    dataset, graph = _valid_inputs()
    graph.allowed_citation_ids = ["CIT-001"]
    graph.citation_graph_hash = graph.compute_hash()

    plan = SectionPlanBuilder().build(dataset, graph)

    assert plan.validation.status == "blocked"
    assert any(error.code == SECTION_CITATION_NOT_ALLOWED for error in plan.validation.errors)


def test_citation_ids_use_numeric_order():
    assert _citation_number("CIT-999") < _citation_number("CIT-1000")
    dataset = _dataset(
        [_event("event-1", 100, [_claim("claim-1", "fact", "file:/a")])],
        evidence_keys=["file:/a"],
    )
    graph = CitationGraphBuilder().build(dataset)
    assert graph.allowed_citation_ids == ["CIT-001"]

    plan = SectionPlanBuilder().build(dataset, graph)

    assert plan.sections[0].allowed_citation_ids == ["CIT-001"]


def test_plan_hash_is_stable_and_builder_does_not_mutate_inputs():
    dataset, graph = _valid_inputs()
    dataset_before = deepcopy(dataset.model_dump(mode="json"))
    graph_before = deepcopy(graph.model_dump(mode="json"))

    first = SectionPlanBuilder().build(dataset, graph)
    second = SectionPlanBuilder().build(dataset, graph)

    assert first.canonical_content_json() == second.canonical_content_json()
    assert first.section_plan_hash == second.section_plan_hash
    assert dataset.model_dump(mode="json") == dataset_before
    assert graph.model_dump(mode="json") == graph_before
