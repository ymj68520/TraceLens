"""Tests for constrained Phase 4D section rendering."""

from __future__ import annotations

import asyncio
import copy
import json
from unittest.mock import AsyncMock

import pytest

from httpserver.services.citation_validation import CitationGraphBuilder
from httpserver.services.report_dataset import (
    DatasetValidation,
    ReportDataset,
    ReportDatasetClaim,
    ReportDatasetClaimEvidenceLink,
    ReportDatasetEvent,
    ReportDatasetEvidence,
)
from httpserver.services.report_rendering import (
    REPORT_RENDER_PROMPT_VERSION,
    RENDER_CITATION_NOT_ALLOWED,
    RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM,
    RENDER_DUPLICATE_CLAIM_ID,
    RENDER_EMPTY_PARAGRAPH,
    RENDER_OUTPUT_SCHEMA_INVALID,
    RENDER_USED_CLAIMS_MISMATCH,
    ConstrainedSectionRenderer,
    SectionRenderClaim,
    SectionRenderClaimCitation,
    SectionRenderInput,
    SectionRenderOutput,
    SectionRenderParagraph,
    build_section_render_input,
    validate_section_render_output,
)
from httpserver.services.section_planning import SectionPlanBuilder


def _valid_inputs():
    dataset = ReportDataset(
        task_id="task-render",
        generated_at="2026-08-13T00:00:00+00:00",
        events=[ReportDatasetEvent(
            event_id="event-1",
            event_version_id="event-version-1",
            title="事件",
            summary="摘要",
            start_time=100,
            claims=[ReportDatasetClaim(
                claim_id="claim-1",
                event_version_id="event-version-1",
                claim_type="fact",
                claim_text="文件包含服务器地址",
                readiness="report_ready",
                evidence_links=[ReportDatasetClaimEvidenceLink(
                    evidence_key="file:/evidence.txt",
                    relation="supports",
                    rationale="原始文件内容",
                )],
            )],
        )],
        report_evidence=[ReportDatasetEvidence(
            evidence_key="file:/evidence.txt",
            evidence_type="file",
            report_status="main",
            analysis_id="analysis-1",
            snapshot={"evidence_key": "file:/evidence.txt", "hash": "abc"},
            pinned_analysis={
                "analysis_id": "analysis-1",
                "evidence_key": "file:/evidence.txt",
                "evidence_type": "file",
                "status": "accepted",
            },
        )],
        validation=DatasetValidation(status="valid"),
        report_dataset_hash="",
    )
    dataset.report_dataset_hash = dataset.compute_hash()
    graph = CitationGraphBuilder().build(dataset)
    plan = SectionPlanBuilder().build(dataset, graph)
    return dataset, graph, plan


def test_build_input_is_section_scoped_and_hash_includes_prompt_version():
    dataset, graph, plan = _valid_inputs()
    input_data = build_section_render_input(dataset, graph, plan, "SEC-001")

    assert input_data.claim_ids == ["claim-1"]
    assert [claim.claim_id for claim in input_data.claims] == ["claim-1"]
    assert input_data.allowed_citation_ids == ["CIT-001"]
    assert [citation.citation_id for citation in input_data.citations] == ["CIT-001"]
    assert input_data.prompt_version == REPORT_RENDER_PROMPT_VERSION

    changed = input_data.model_copy(update={"prompt_version": "report-render-v2"})
    assert changed.compute_hash() != input_data.compute_hash()


def test_claim_edge_scoped_citation_whitelist_is_enforced():
    input_data = SectionRenderInput(
        dataset_hash="dataset",
        citation_graph_hash="graph",
        section_plan_hash="plan",
        section_id="SEC-001",
        section_type="analysis.overview",
        title="概述",
        claim_ids=["claim-a", "claim-b"],
        allowed_citation_ids=["CIT-001", "CIT-002"],
        claims=[
            SectionRenderClaim(
                claim_id="claim-a",
                claim_type="fact",
                claim_text="A",
                citations=[SectionRenderClaimCitation(
                    citation_id="CIT-001", relation="supports"
                )],
            ),
            SectionRenderClaim(
                claim_id="claim-b",
                claim_type="fact",
                claim_text="B",
                citations=[SectionRenderClaimCitation(
                    citation_id="CIT-002", relation="supports"
                )],
            ),
        ],
        citations=[],
    )
    output = SectionRenderOutput(
        section_id="SEC-001",
        used_claim_ids=["claim-a"],
        paragraphs=[SectionRenderParagraph(
            text="A",
            claim_ids=["claim-a"],
            citation_ids=["CIT-002"],
        )],
    )

    errors = validate_section_render_output(input_data, output)
    assert any(error.code == RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM for error in errors)
    assert not any(error.code == RENDER_CITATION_NOT_ALLOWED for error in errors)


def test_output_union_duplicate_and_empty_paragraph_errors():
    input_data = SectionRenderInput(
        dataset_hash="dataset",
        citation_graph_hash="graph",
        section_plan_hash="plan",
        section_id="SEC-001",
        section_type="analysis.overview",
        title="概述",
        claim_ids=["claim-a"],
        allowed_citation_ids=[],
        claims=[SectionRenderClaim(
            claim_id="claim-a", claim_type="fact", claim_text="A"
        )],
    )
    output = SectionRenderOutput(
        section_id="SEC-001",
        used_claim_ids=["claim-a", "claim-a"],
        paragraphs=[
            SectionRenderParagraph(text="", claim_ids=["claim-a"]),
            SectionRenderParagraph(text="A", claim_ids=[]),
        ],
    )

    codes = {error.code for error in validate_section_render_output(input_data, output)}
    assert RENDER_DUPLICATE_CLAIM_ID in codes
    assert RENDER_EMPTY_PARAGRAPH in codes
    assert RENDER_USED_CLAIMS_MISMATCH in codes


@pytest.mark.asyncio
async def test_renderer_parses_structured_json_and_keeps_raw_output_out_of_hash():
    raw = json.dumps({
        "section_id": "SEC-001",
        "used_claim_ids": ["claim-1"],
        "paragraphs": [{
            "text": "文件包含服务器地址。",
            "claim_ids": ["claim-1"],
            "citation_ids": ["CIT-001"],
        }],
    }, ensure_ascii=False)
    llm = type("LLMStub", (), {})()
    llm.analyze = AsyncMock(return_value={
        "analysis": {"description": raw},
        "model": "test-model",
    })
    dataset, graph, plan = _valid_inputs()
    input_data = build_section_render_input(dataset, graph, plan, "SEC-001")

    result = await ConstrainedSectionRenderer(llm).render(input_data)

    assert result["status"] == "render_pending_validation"
    assert result["output"].compute_hash()
    assert result["raw_llm_output"] == raw
    assert result["output"].compute_hash() == SectionRenderOutput.model_validate_json(raw).compute_hash()
    llm.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_renderer_marks_malformed_json_invalid_and_transport_failures_failed():
    dataset, graph, plan = _valid_inputs()
    input_data = build_section_render_input(dataset, graph, plan, "SEC-001")

    malformed = type("LLMStub", (), {})()
    malformed.analyze = AsyncMock(return_value={"analysis": {"description": "not json"}})
    result = await ConstrainedSectionRenderer(malformed).render(input_data)
    assert result["status"] == "invalid"
    assert result["validation_errors"][0].code == RENDER_OUTPUT_SCHEMA_INVALID

    failing = type("LLMStub", (), {})()
    failing.analyze = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    result = await ConstrainedSectionRenderer(failing).render(input_data)
    assert result["status"] == "failed"
    assert result["error_message"] == "LLM unavailable"


def test_renderer_does_not_mutate_upstream_inputs():
    dataset, graph, plan = _valid_inputs()
    before = (copy.deepcopy(dataset), copy.deepcopy(graph), copy.deepcopy(plan))
    build_section_render_input(dataset, graph, plan, "SEC-001")
    assert dataset == before[0]
    assert graph == before[1]
    assert plan == before[2]
