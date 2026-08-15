"""Tests for Phase 4E final validation rules and provenance hashes."""

from __future__ import annotations

from copy import deepcopy

from httpserver.services.citation_validation import (
    CitationLink,
    CitationNode,
    CitationValidation,
    CitationValidationResult,
    ClaimCitations,
)
from httpserver.services.report_dataset import (
    DatasetValidation,
    ReportDataset,
    ReportDatasetClaim,
    ReportDatasetClaimEvidenceLink,
    ReportDatasetEvidence,
    ReportDatasetEvent,
)
from httpserver.services.report_final_validation import (
    FINAL_CLAIM_NOT_COVERED,
    FINAL_CLAIM_WITHOUT_CITATION,
    FINAL_PARAGRAPH_WITHOUT_CLAIM,
    FINAL_VALID,
    FINAL_BLOCKED,
    FinalSectionValidator,
    compute_validation_input_hash,
    compute_validation_result_hash,
)
from httpserver.services.report_render_repository import (
    RENDER_PENDING_VALIDATION,
    ReportRenderRepository,
)
from httpserver.services.report_rendering import (
    SectionRenderInput,
    SectionRenderOutput,
    SectionRenderParagraph,
    build_section_render_input,
)
from httpserver.services.section_planning import (
    ReportSection,
    ReportSectionPlan,
    SectionPlanValidation,
)


def _objects():
    dataset = ReportDataset(
        task_id="task-a",
        generated_at="2026-08-13T00:00:00+00:00",
        events=[ReportDatasetEvent(
            event_id="event-a",
            title="Event A",
            claims=[ReportDatasetClaim(
                claim_id="claim-a",
                event_version_id="version-a",
                claim_type="fact",
                claim_text="A fact",
                readiness="report_ready",
                evidence_links=[ReportDatasetClaimEvidenceLink(
                    evidence_key="file:/a",
                    relation="supports",
                )],
            )],
        )],
        report_evidence=[ReportDatasetEvidence(
            evidence_key="file:/a",
            evidence_type="file",
            report_status="main",
            snapshot={"hash": "a"},
            pinned_analysis={"status": "accepted"},
        )],
        validation=DatasetValidation(status="valid"),
        report_dataset_hash="",
    )
    dataset.report_dataset_hash = dataset.compute_hash()

    graph = CitationValidationResult(
        dataset_hash=dataset.report_dataset_hash,
        citations=[CitationNode(
            citation_id="CIT-001",
            evidence_key="file:/a",
            evidence_type="file",
            report_status="main",
            snapshot={"hash": "a"},
            pinned_analysis={"status": "accepted"},
            renderable=True,
        )],
        claim_citations=[ClaimCitations(
            event_id="event-a",
            event_version_id="version-a",
            claim_id="claim-a",
            claim_type="fact",
            readiness="report_ready",
            citations=[CitationLink(
                citation_id="CIT-001",
                relation="supports",
            )],
        )],
        renderable_citation_ids=["CIT-001"],
        allowed_citation_ids=["CIT-001"],
        validation=CitationValidation(status="valid"),
        citation_graph_hash="",
    )
    graph.citation_graph_hash = graph.compute_hash()

    plan = ReportSectionPlan(
        dataset_hash=dataset.report_dataset_hash,
        citation_graph_hash=graph.citation_graph_hash,
        sections=[ReportSection(
            section_id="SEC-001",
            section_type="analysis.overview",
            title="Overview",
            order=1,
            event_ids=["event-a"],
            claim_ids=["claim-a"],
            allowed_citation_ids=["CIT-001"],
        )],
        validation=SectionPlanValidation(status="valid"),
        section_plan_hash="",
    )
    plan.section_plan_hash = plan.compute_hash()
    return dataset, graph, plan


def _candidate(tmp_path, output=None):
    dataset, graph, plan = _objects()
    input_data = build_section_render_input(dataset, graph, plan, "SEC-001")
    repository = ReportRenderRepository(tmp_path / "investigation.db")
    candidate = repository.create_queued("task-a", "SEC-001", input_data)
    repository.mark_running(candidate.candidate_id)
    return repository.complete(
        candidate.candidate_id,
        status=RENDER_PENDING_VALIDATION,
        output=output or SectionRenderOutput(
            section_id="SEC-001",
            used_claim_ids=["claim-a"],
            paragraphs=[SectionRenderParagraph(
                text="A fact.",
                claim_ids=["claim-a"],
                citation_ids=["CIT-001"],
            )],
        ),
    ), dataset, graph, plan


def test_valid_candidate_has_per_claim_coverage(tmp_path):
    candidate, dataset, graph, plan = _candidate(tmp_path)
    result = FinalSectionValidator().validate(candidate, dataset, graph, plan)

    assert result.status == FINAL_VALID
    assert result.coverage["claims"] == [{
        "claim_id": "claim-a",
        "mentioned": True,
        "citation_covered": True,
        "paragraph_indexes": [0],
        "citation_ids": ["CIT-001"],
    }]
    assert result.observed_dataset_hash == dataset.report_dataset_hash
    assert result.observed_render_output_hash == candidate.render_output_hash


def test_claim_coverage_is_per_claim_not_per_paragraph(tmp_path):
    dataset, graph, plan = _objects()
    dataset.events[0].claims.append(ReportDatasetClaim(
        claim_id="claim-b",
        event_version_id="version-a",
        claim_type="fact",
        claim_text="B fact",
        readiness="report_ready",
        evidence_links=[ReportDatasetClaimEvidenceLink(
            evidence_key="file:/a", relation="supports"
        )],
    ))
    dataset.events[0].claims[-1].evidence_links = [ReportDatasetClaimEvidenceLink(
        evidence_key="file:/b", relation="supports"
    )]
    dataset.report_evidence.append(ReportDatasetEvidence(
        evidence_key="file:/b",
        evidence_type="file",
        report_status="main",
        snapshot={"hash": "b"},
        pinned_analysis={"status": "accepted"},
    ))
    dataset.report_dataset_hash = dataset.compute_hash()
    graph.citations.append(CitationNode(
        citation_id="CIT-002",
        evidence_key="file:/b",
        evidence_type="file",
        report_status="main",
        snapshot={"hash": "b"},
        pinned_analysis={"status": "accepted"},
        renderable=True,
    ))
    graph.renderable_citation_ids = ["CIT-001", "CIT-002"]
    graph.allowed_citation_ids = ["CIT-001", "CIT-002"]
    graph.claim_citations.append(ClaimCitations(
        event_id="event-a",
        event_version_id="version-a",
        claim_id="claim-b",
        claim_type="fact",
        readiness="report_ready",
        citations=[CitationLink(citation_id="CIT-002", relation="supports")],
    ))
    graph.dataset_hash = dataset.report_dataset_hash
    graph.citation_graph_hash = graph.compute_hash()
    plan.dataset_hash = dataset.report_dataset_hash
    plan.citation_graph_hash = graph.citation_graph_hash
    plan.sections[0].claim_ids = ["claim-a", "claim-b"]
    plan.sections[0].allowed_citation_ids = ["CIT-001", "CIT-002"]
    plan.section_plan_hash = plan.compute_hash()
    input_data = build_section_render_input(dataset, graph, plan, "SEC-001")
    repository = ReportRenderRepository(tmp_path / "investigation.db")
    candidate = repository.create_queued("task-a", "SEC-001", input_data)
    repository.mark_running(candidate.candidate_id)
    candidate = repository.complete(
        candidate.candidate_id,
        status=RENDER_PENDING_VALIDATION,
        output=SectionRenderOutput(
            section_id="SEC-001",
            used_claim_ids=["claim-a", "claim-b"],
            paragraphs=[SectionRenderParagraph(
                text="Both facts.",
                claim_ids=["claim-a", "claim-b"],
                citation_ids=["CIT-001"],
            )],
        ),
    )
    result = FinalSectionValidator().validate(candidate, dataset, graph, plan)

    assert result.status == "invalid"
    assert any(
        error.code == FINAL_CLAIM_WITHOUT_CITATION and error.claim_id == "claim-b"
        for error in result.errors
    )
    assert result.coverage["claims"][1]["citation_covered"] is False


def test_uncovered_and_claimless_prose_are_invalid(tmp_path):
    candidate, dataset, graph, plan = _candidate(
        tmp_path,
        SectionRenderOutput(
            section_id="SEC-001",
            used_claim_ids=[],
            paragraphs=[SectionRenderParagraph(
                text="Unsupported prose.",
                claim_ids=[],
                citation_ids=[],
            )],
        ),
    )
    result = FinalSectionValidator().validate(candidate, dataset, graph, plan)
    codes = {error.code for error in result.errors}

    assert result.status == "invalid"
    assert FINAL_CLAIM_NOT_COVERED in codes
    assert FINAL_PARAGRAPH_WITHOUT_CLAIM in codes


def test_observed_provenance_changes_validation_input_hash(tmp_path):
    candidate, dataset, graph, plan = _candidate(tmp_path)
    first = compute_validation_input_hash(
        candidate,
        observed_dataset_hash=dataset.report_dataset_hash,
        observed_citation_graph_hash=graph.citation_graph_hash,
        observed_section_plan_hash=plan.section_plan_hash,
        observed_render_input_hash=candidate.render_input_hash,
        observed_render_output_hash=candidate.render_output_hash,
    )
    second = compute_validation_input_hash(
        candidate,
        observed_dataset_hash="dataset-b",
        observed_citation_graph_hash=graph.citation_graph_hash,
        observed_section_plan_hash=plan.section_plan_hash,
        observed_render_input_hash=candidate.render_input_hash,
        observed_render_output_hash=candidate.render_output_hash,
    )

    assert first != second


def test_validation_result_hash_ignores_human_message():
    from httpserver.services.report_final_validation import FinalValidationError

    one = FinalValidationError(code="X", entity_type="candidate", message="one")
    two = one.model_copy(update={"message": "two"})
    assert compute_validation_result_hash(
        validation_input_hash="input",
        status="invalid",
        errors=[one], warnings=[], coverage={"claims": []}
    ) == compute_validation_result_hash(
        validation_input_hash="input",
        status="invalid",
        errors=[two], warnings=[], coverage={"claims": []}
    )
