"""Tests for deterministic Final Report presentation."""

from __future__ import annotations

import hashlib

import pytest

from httpserver.services.final_report_assembly import (
    FINAL_REPORT_ASSEMBLED,
    FINAL_REPORT_VALID,
    FinalReportCitation,
    FinalReportClaim,
    FinalReportParagraph,
    FinalReportSection,
    FinalReportVersion,
)
from httpserver.services.final_report_presentation import (
    FINAL_REPORT_PRESENTATION_VERSION,
    FinalReportPresentationIntegrityError,
    build_final_report_presentation,
    render_final_report_html,
    render_final_report_markdown,
    validate_final_report_for_presentation,
)


def _report() -> FinalReportVersion:
    sections = []
    for order, (section_type, title) in enumerate(
        (
            ("analysis.overview", "Overview"),
            ("analysis.timeline", "Timeline"),
            ("analysis.evidence", "Evidence"),
            ("analysis.findings", "Findings"),
            ("analysis.conclusion", "Conclusion"),
        ),
        start=1,
    ):
        paragraphs = []
        if order == 1:
            paragraphs.append(FinalReportParagraph(
                text="# title <script>alert(1)</script> ![x](https://example.com/x.png) "
                "*emphasis* [link](https://example.com)\n第二行",
                claim_ids=["CLM-001"],
                citation_ids=["CIT-001"],
            ))
        sections.append(FinalReportSection(
            section_id=f"SEC-{order:03d}",
            section_type=section_type,
            title=title,
            order=order,
            paragraphs=paragraphs,
        ))
    return FinalReportVersion(
        report_id="report/one",
        task_id="task-a",
        report_version=3,
        report_dataset_hash="dataset",
        citation_graph_hash="graph",
        section_plan_hash="plan",
        sections=sections,
        claim_manifest=[FinalReportClaim(
            claim_id="CLM-001",
            section_ids=["SEC-001"],
            citation_ids=["CIT-001"],
        )],
        citation_manifest=[FinalReportCitation(
            citation_id="CIT-001",
            evidence_key="file:/docs/a.txt",
            evidence_type="file",
        )],
        status=FINAL_REPORT_ASSEMBLED,
        validation_status=FINAL_REPORT_VALID,
    ).with_hash()


def test_presentation_is_byte_stable_and_does_not_mutate_report():
    report = _report()
    before = report.model_dump(mode="json")
    markdown = build_final_report_presentation(report, "markdown")
    repeated = build_final_report_presentation(report, "markdown")
    html = build_final_report_presentation(report, "html")

    assert markdown.body == repeated.body
    assert markdown.presentation_hash == hashlib.sha256(markdown.body).hexdigest()
    assert markdown.final_report_hash == report.final_report_hash
    assert markdown.filename.endswith(".md")
    assert html.presentation_hash == hashlib.sha256(html.body).hexdigest()
    assert report.model_dump(mode="json") == before
    assert report.final_report_hash == report.compute_hash()


def test_presentation_walks_persisted_order_and_rejects_normalization():
    report = _report()
    assert [line for line in render_final_report_markdown(report).splitlines() if line.startswith("## ")] == [
        "## Overview", "## Timeline", "## Evidence", "## Findings", "## Conclusion"
    ]

    corrupted = report.model_copy(deep=True)
    corrupted.sections[0], corrupted.sections[1] = corrupted.sections[1], corrupted.sections[0]
    corrupted.final_report_hash = corrupted.compute_hash()
    with pytest.raises(FinalReportPresentationIntegrityError):
        validate_final_report_for_presentation(corrupted)


def test_markdown_escapes_narrative_syntax():
    markdown = render_final_report_markdown(_report())
    assert r"\# title \<script\>alert\(1\)\<\/script\>" in markdown
    assert r"\!\[x\]\(https\:\/\/example\.com\/x\.png\)" in markdown
    assert r"\*emphasis\* \[link\]\(https\:\/\/example\.com\)" in markdown
    assert "<script>" not in markdown
    assert "<!--" not in markdown


def test_html_is_static_escaped_and_csp_safe():
    screen = render_final_report_html(_report(), "screen")
    printed = render_final_report_html(_report(), "print")

    assert f'tracelens-presentation-version" content="{FINAL_REPORT_PRESENTATION_VERSION}' in screen
    assert "default-src &#x27;none&#x27;" in screen
    assert "<script" not in screen
    assert "https://example.com" in screen
    assert 'href="' not in screen
    assert 'src="' not in screen
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in screen
    assert "@page" not in screen
    assert "@page" in printed
    assert "@media print" in printed
    assert "<script" not in printed
    assert "external" not in printed.lower()


def test_manifest_union_integrity_fails_closed():
    report = _report().model_copy(deep=True)
    report.sections[0].paragraphs[0].citation_ids = []
    report.final_report_hash = report.compute_hash()
    with pytest.raises(FinalReportPresentationIntegrityError):
        build_final_report_presentation(report, "html")
