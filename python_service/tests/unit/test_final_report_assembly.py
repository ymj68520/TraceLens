"""Tests for deterministic Final Report Assembly."""

from __future__ import annotations

from httpserver.services.citation_validation import (
    CitationLink,
    CitationNode,
    CitationValidation,
    CitationValidationResult,
    ClaimCitations,
)
from httpserver.services.final_report_assembly import (
    FINAL_REPORT_INVALID,
    FINAL_REPORT_VALID,
    REPORT_CLAIM_COVERAGE_MISMATCH,
    REPORT_SECTION_BINDING_MISSING,
    FinalReportAssembler,
    FinalReportAssemblyRequest,
    FinalReportSectionBindingRequest,
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
    FinalValidationError,
    SectionRenderValidation,
)
from httpserver.services.report_render_repository import (
    RENDER_PENDING_VALIDATION,
    ReportRenderRepository,
)
from httpserver.services.report_rendering import (
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
                    evidence_key="file:/a", relation="supports"
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
            citations=[CitationLink(citation_id="CIT-001", relation="supports")],
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
        )] + [ReportSection(
            section_id=f"SEC-{index:03d}",
            section_type=f"analysis.section{index}",
            title=f"Section {index}",
            order=index,
        ) for index in range(2, 6)],
        validation=SectionPlanValidation(status="valid"),
        section_plan_hash="",
    )
    plan.section_plan_hash = plan.compute_hash()
    return dataset, graph, plan


def _candidate_and_validation(tmp_path):
    dataset, graph, plan = _objects()
    input_data = build_section_render_input(dataset, graph, plan, "SEC-001")
    render_repo = ReportRenderRepository(tmp_path / "investigation.db")
    candidate = render_repo.create_queued("task-a", "SEC-001", input_data)
    render_repo.mark_running(candidate.candidate_id)
    candidate = render_repo.complete(
        candidate.candidate_id,
        status=RENDER_PENDING_VALIDATION,
        output=SectionRenderOutput(
            section_id="SEC-001",
            used_claim_ids=["claim-a"],
            paragraphs=[SectionRenderParagraph(
                text="A fact.",
                claim_ids=["claim-a"],
                citation_ids=["CIT-001"],
            )],
        ),
    )
    output_hash = candidate.render_output_hash
    validation = SectionRenderValidation(
        validation_id="validation-1",
        task_id="task-a",
        candidate_id=candidate.candidate_id,
        section_id="SEC-001",
        validation_version=1,
        validation_rule_version="report-final-validation-v1",
        dataset_hash=candidate.dataset_hash,
        citation_graph_hash=candidate.citation_graph_hash,
        section_plan_hash=candidate.section_plan_hash,
        render_input_hash=candidate.render_input_hash,
        render_output_hash=output_hash,
        observed_dataset_hash=dataset.report_dataset_hash,
        observed_citation_graph_hash=graph.citation_graph_hash,
        observed_section_plan_hash=plan.section_plan_hash,
        observed_render_input_hash=candidate.render_input_hash,
        observed_render_output_hash=output_hash,
        validation_input_hash="validation-input",
        validation_result_hash="validation-result",
        status="valid",
        coverage={"claims": [{
            "claim_id": "claim-a",
            "mentioned": True,
            "citation_covered": True,
            "paragraph_indexes": [0],
            "citation_ids": ["CIT-001"],
        }]},
        created_at=1,
        completed_at=2,
    )
    return dataset, graph, plan, candidate, validation


def test_successful_assembly_normalizes_request_order_and_manifests(tmp_path):
    dataset, graph, plan, candidate, validation = _candidate_and_validation(tmp_path)
    request = FinalReportAssemblyRequest(sections=[
        FinalReportSectionBindingRequest(
            section_id="SEC-005", candidate_id=None, validation_id=None
        ),
        FinalReportSectionBindingRequest(
            section_id="SEC-001",
            candidate_id=candidate.candidate_id,
            validation_id=validation.validation_id,
        ),
    ])

    result = FinalReportAssembler().assemble(
        request,
        dataset,
        graph,
        plan,
        {candidate.candidate_id: candidate},
        {validation.validation_id: validation},
    )

    assert result.status == FINAL_REPORT_VALID
    assert result.report is not None
    assert [section.section_id for section in result.report.sections] == [
        "SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005"
    ]
    assert result.report.citation_manifest[0].citation_id == "CIT-001"
    assert result.report.claim_manifest[0].citation_ids == ["CIT-001"]
    assert result.report.final_report_hash == result.report.compute_hash()


def test_invalid_assembly_does_not_produce_report(tmp_path):
    dataset, graph, plan, candidate, validation = _candidate_and_validation(tmp_path)
    request = FinalReportAssemblyRequest(sections=[])

    result = FinalReportAssembler().assemble(
        request, dataset, graph, plan, {}, {}
    )

    assert result.status == FINAL_REPORT_INVALID
    assert any(error.code == REPORT_SECTION_BINDING_MISSING for error in result.errors)
    assert result.report is None


def test_claim_manifest_must_match_4e_per_claim_coverage(tmp_path):
    dataset, graph, plan, candidate, validation = _candidate_and_validation(tmp_path)
    validation.coverage["claims"][0]["citation_ids"] = []
    request = FinalReportAssemblyRequest(sections=[
        FinalReportSectionBindingRequest(
            section_id="SEC-001",
            candidate_id=candidate.candidate_id,
            validation_id=validation.validation_id,
        )
    ])

    result = FinalReportAssembler().assemble(
        request,
        dataset,
        graph,
        plan,
        {candidate.candidate_id: candidate},
        {validation.validation_id: validation},
    )

    assert result.status == FINAL_REPORT_INVALID
    assert any(error.code == REPORT_CLAIM_COVERAGE_MISMATCH for error in result.errors)
