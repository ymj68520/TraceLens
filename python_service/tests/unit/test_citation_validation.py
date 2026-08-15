from __future__ import annotations

from copy import deepcopy

import pytest

from httpserver.services.citation_validation import (
    CLAIM_WITHOUT_RENDERABLE_CITATION,
    CITATION_DUPLICATE,
    CITATION_EVIDENCE_NOT_FOUND,
    CITATION_EVIDENCE_NOT_REPORT_READY,
    CITATION_PINNED_ANALYSIS_INVALID,
    CITATION_RELATION_INVALID,
    CITATION_SNAPSHOT_MISSING,
    DATASET_HASH_MISMATCH,
    UPSTREAM_DATASET_BLOCKED,
    CitationGraphBuilder,
)
from httpserver.services.report_dataset import (
    DatasetValidation,
    DatasetValidationError,
    ReportDataset,
    ReportDatasetClaim,
    ReportDatasetClaimEvidenceLink,
    ReportDatasetEvent,
    ReportDatasetEvidence,
)


def _evidence(
    key: str,
    *,
    status: str = "main",
    analysis_id: str | None = None,
    snapshot: dict | None = None,
    analysis: dict | None = None,
    snapshot_missing: bool = False,
) -> ReportDatasetEvidence:
    return ReportDatasetEvidence(
        evidence_key=key,
        evidence_type="file",
        report_status=status,
        analysis_id=analysis_id,
        snapshot=(
            None
            if snapshot_missing
            else (
                {"evidence_key": key, "source_hash": "hash"}
                if snapshot is None
                else snapshot
            )
        ),
        pinned_analysis=analysis,
    )


def _dataset(
    evidence: list[ReportDatasetEvidence],
    claims: list[ReportDatasetClaim],
    *,
    validation: DatasetValidation | None = None,
) -> ReportDataset:
    dataset = ReportDataset(
        task_id="task-1",
        dataset_version="1",
        generated_at="2026-08-13T00:00:00+00:00",
        events=[ReportDatasetEvent(
            event_id="event-1",
            event_version_id="version-1",
            title="Event",
            claims=claims,
        )],
        report_evidence=evidence,
        validation=validation or DatasetValidation(status="valid"),
        report_dataset_hash="",
    )
    dataset.report_dataset_hash = dataset.compute_hash()
    return dataset


def _claim(
    claim_id: str = "claim-1",
    *,
    claim_type: str = "fact",
    readiness: str = "report_ready",
    links: list[ReportDatasetClaimEvidenceLink] | None = None,
) -> ReportDatasetClaim:
    return ReportDatasetClaim(
        claim_id=claim_id,
        event_version_id="version-1",
        claim_type=claim_type,
        claim_text="Finding",
        readiness=readiness,
        evidence_links=links or [],
    )


def test_generates_dataset_scoped_ids_and_separates_renderable_from_allowed():
    dataset = _dataset(
        [_evidence("file:/b"), _evidence("file:/a"), _evidence("file:/unused")],
        [_claim(links=[ReportDatasetClaimEvidenceLink(
            evidence_key="file:/a", relation="supports", rationale="observed"
        )])],
    )

    result = CitationGraphBuilder().build(dataset)

    assert [item.citation_id for item in result.citations] == [
        "CIT-001", "CIT-002", "CIT-003"
    ]
    assert result.renderable_citation_ids == ["CIT-001", "CIT-002", "CIT-003"]
    assert result.allowed_citation_ids == ["CIT-001"]
    assert result.validation.status == "valid"


def test_supports_and_contradicts_links_are_preserved():
    dataset = _dataset(
        [_evidence("file:/a"), _evidence("file:/b")],
        [_claim(links=[
            ReportDatasetClaimEvidenceLink(
                evidence_key="file:/a", relation="supports", rationale="supports it"
            ),
            ReportDatasetClaimEvidenceLink(
                evidence_key="file:/b", relation="contradicts", rationale="contradicts it"
            ),
        ])],
    )

    result = CitationGraphBuilder().build(dataset)

    links = result.claim_citations[0].citations
    assert [(link.citation_id, link.relation, link.rationale) for link in links] == [
        ("CIT-001", "supports", "supports it"),
        ("CIT-002", "contradicts", "contradicts it"),
    ]


def test_report_ready_claim_without_renderable_citation_blocks():
    dataset = _dataset([_evidence("file:/a", snapshot_missing=True)], [_claim(
        links=[ReportDatasetClaimEvidenceLink(evidence_key="file:/a", relation="supports")]
    )])

    result = CitationGraphBuilder().build(dataset)

    assert result.validation.status == "blocked"
    assert result.allowed_citation_ids == []
    assert any(error.code == CITATION_SNAPSHOT_MISSING for error in result.validation.errors)
    assert any(
        error.code == CLAIM_WITHOUT_RENDERABLE_CITATION
        for error in result.validation.errors
    )


def test_unknown_evidence_and_invalid_relation_are_machine_readable():
    dataset = _dataset(
        [],
        [_claim(links=[
            ReportDatasetClaimEvidenceLink(evidence_key="file:/missing", relation="supports"),
            ReportDatasetClaimEvidenceLink(evidence_key="file:/missing", relation="bad-relation"),
        ])],
    )

    result = CitationGraphBuilder().build(dataset)

    codes = {error.code for error in result.validation.errors}
    assert CITATION_EVIDENCE_NOT_FOUND in codes
    assert CITATION_RELATION_INVALID in codes
    assert CLAIM_WITHOUT_RENDERABLE_CITATION in codes


def test_invalid_pinned_analysis_blocks_citation_node():
    dataset = _dataset([_evidence(
        "file:/a", analysis_id="analysis-1", analysis={
            "analysis_id": "analysis-other",
            "status": "review_pending",
            "evidence_key": "file:/a",
            "evidence_type": "file",
        }
    )], [_claim(links=[ReportDatasetClaimEvidenceLink(
        evidence_key="file:/a", relation="supports"
    )])])

    result = CitationGraphBuilder().build(dataset)

    assert result.validation.status == "blocked"
    assert any(
        error.code == CITATION_PINNED_ANALYSIS_INVALID
        for error in result.validation.errors
    )
    assert any(
        error.code == CITATION_EVIDENCE_NOT_REPORT_READY
        for error in result.validation.errors
    )


def test_duplicate_evidence_uses_one_id_and_is_not_renderable():
    dataset = _dataset([_evidence("file:/a"), _evidence("file:/a", status="appendix")], [])

    result = CitationGraphBuilder().build(dataset)

    assert len(result.citations) == 1
    assert result.citations[0].citation_id == "CIT-001"
    assert result.citations[0].renderable is False
    assert CITATION_DUPLICATE in {error.code for error in result.validation.errors}


def test_blocked_and_excluded_claims_do_not_enter_allowed_ids():
    dataset = _dataset(
        [_evidence("file:/a")],
        [
            _claim("blocked", readiness="blocked", links=[
                ReportDatasetClaimEvidenceLink(evidence_key="file:/a", relation="supports")
            ]),
            _claim("excluded", readiness="excluded", links=[
                ReportDatasetClaimEvidenceLink(evidence_key="file:/a", relation="supports")
            ]),
        ],
        validation=DatasetValidation(status="blocked", errors=[
            DatasetValidationError(
                code="EVIDENCE_SNAPSHOT_NOT_FOUND",
                entity_type="evidence",
                entity_id="file:/a",
                evidence_key="file:/a",
                message="missing",
            )
        ]),
    )

    result = CitationGraphBuilder().build(dataset)

    assert result.validation.status == "blocked"
    assert result.allowed_citation_ids == []
    assert any(error.code == UPSTREAM_DATASET_BLOCKED for error in result.validation.errors)


def test_dataset_hash_mismatch_fails_closed():
    dataset = _dataset([_evidence("file:/a")], [_claim(
        links=[ReportDatasetClaimEvidenceLink(evidence_key="file:/a", relation="supports")]
    )])
    dataset.report_dataset_hash = "tampered"

    result = CitationGraphBuilder().build(dataset)

    assert result.validation.status == "blocked"
    assert result.allowed_citation_ids == []
    assert DATASET_HASH_MISMATCH in {error.code for error in result.validation.errors}


def test_graph_hash_is_stable_and_builder_does_not_mutate_dataset():
    dataset = _dataset([_evidence("file:/a")], [_claim(
        links=[ReportDatasetClaimEvidenceLink(evidence_key="file:/a", relation="supports")]
    )])
    before = deepcopy(dataset.model_dump(mode="json"))

    first = CitationGraphBuilder().build(dataset)
    second = CitationGraphBuilder().build(dataset)

    assert first.canonical_content_json() == second.canonical_content_json()
    assert first.citation_graph_hash == second.citation_graph_hash
    assert dataset.model_dump(mode="json") == before
