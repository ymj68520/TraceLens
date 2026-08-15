"""Deterministic presentation of immutable Final Report versions."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from typing import Iterable, Literal

from .final_report_assembly import FinalReportVersion
from .section_planning import SECTION_TAXONOMY

FINAL_REPORT_PRESENTATION_VERSION = "report-presentation-v1"
PresentationMode = Literal["screen", "print"]

_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    "font-src 'none'; connect-src 'none'; script-src 'none'; object-src 'none'; "
    "frame-src 'none'; base-uri 'none'; form-action 'none'"
)
_MARKDOWN_ESCAPABLE = frozenset(
    "\\`*_{}[]()#+-.!|>~=:/<>"
)
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class FinalReportPresentationIntegrityError(ValueError):
    """The persisted FinalReportVersion cannot be presented safely."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("final report presentation integrity check failed")


@dataclass(frozen=True)
class FinalReportPresentation:
    """One in-memory derived presentation artifact."""

    representation: str
    media_type: str
    body: bytes
    presentation_hash: str
    final_report_hash: str
    filename: str


def _duplicate_values(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def validate_final_report_for_presentation(report: FinalReportVersion) -> None:
    """Validate persisted report structure without normalizing it."""
    errors: list[str] = []
    if report.final_report_hash != report.compute_hash():
        errors.append("final_report_hash does not match canonical report content")

    expected_ids = [f"SEC-{index:03d}" for index in range(1, 6)]
    actual_ids = [section.section_id for section in report.sections]
    actual_orders = [section.order for section in report.sections]
    if actual_ids != expected_ids:
        errors.append("persisted section IDs do not match the canonical five-section structure")
    if actual_orders != list(range(1, 6)):
        errors.append("persisted section order does not match the canonical five-section structure")

    expected_types = [section_type for section_type, _title in SECTION_TAXONOMY]
    actual_types = [section.section_type for section in report.sections]
    if actual_types != expected_types:
        errors.append("persisted section types do not match the canonical five-section structure")

    claim_manifest_ids = [claim.claim_id for claim in report.claim_manifest]
    citation_manifest_ids = [citation.citation_id for citation in report.citation_manifest]
    if any(not isinstance(value, str) or not value for value in claim_manifest_ids):
        errors.append("claim manifest contains an invalid Claim ID")
    if any(not isinstance(value, str) or not value for value in citation_manifest_ids):
        errors.append("citation manifest contains an invalid Citation ID")
    if _duplicate_values(claim_manifest_ids):
        errors.append("claim manifest contains duplicate Claim IDs")
    if _duplicate_values(citation_manifest_ids):
        errors.append("citation manifest contains duplicate Citation IDs")

    paragraph_claim_ids: list[str] = []
    paragraph_citation_ids: list[str] = []
    section_ids = set(expected_ids)
    citation_ids = set(citation_manifest_ids)
    claim_ids = set(claim_manifest_ids)
    for section in report.sections:
        for paragraph in section.paragraphs:
            if _duplicate_values(paragraph.claim_ids):
                errors.append(f"section {section.section_id} contains duplicate paragraph Claim IDs")
            if _duplicate_values(paragraph.citation_ids):
                errors.append(f"section {section.section_id} contains duplicate paragraph Citation IDs")
            paragraph_claim_ids.extend(paragraph.claim_ids)
            paragraph_citation_ids.extend(paragraph.citation_ids)
            if any(claim_id not in claim_ids for claim_id in paragraph.claim_ids):
                errors.append(f"section {section.section_id} references an unknown Claim ID")
            if any(citation_id not in citation_ids for citation_id in paragraph.citation_ids):
                errors.append(f"section {section.section_id} references an unknown Citation ID")

    if set(paragraph_claim_ids) != claim_ids:
        errors.append("paragraph Claim ID union does not match the Claim manifest")
    if set(paragraph_citation_ids) != citation_ids:
        errors.append("paragraph Citation ID union does not match the Citation manifest")

    for claim in report.claim_manifest:
        if any(section_id not in section_ids for section_id in claim.section_ids):
            errors.append(f"Claim {claim.claim_id} references an unknown section ID")
        if any(citation_id not in citation_ids for citation_id in claim.citation_ids):
            errors.append(f"Claim {claim.claim_id} references an unknown Citation ID")

    if errors:
        raise FinalReportPresentationIntegrityError(errors)


def escape_markdown_text(value: str) -> str:
    """Escape Markdown syntax so narrative text remains plain text."""
    escaped: list[str] = []
    for character in str(value):
        if character in _MARKDOWN_ESCAPABLE:
            escaped.append("\\")
        escaped.append(character)
    return "".join(escaped)


def _markdown_metadata(label: str, values: Iterable[str]) -> str:
    escaped_values = ", ".join(escape_markdown_text(value) for value in values)
    return f"{escape_markdown_text(label)}: {escaped_values}"


def render_final_report_markdown(report: FinalReportVersion) -> str:
    """Render Markdown from the validated structured report only."""
    validate_final_report_for_presentation(report)
    lines = ["# Final Report", ""]
    for section in report.sections:
        lines.extend([f"## {escape_markdown_text(section.title)}", ""])
        for paragraph in section.paragraphs:
            lines.append(escape_markdown_text(paragraph.text))
            if paragraph.claim_ids:
                lines.append(_markdown_metadata("claims", paragraph.claim_ids))
            if paragraph.citation_ids:
                lines.append(_markdown_metadata("citations", paragraph.citation_ids))
            lines.append("")
        if not section.paragraphs:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _html_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _html_metadata(label: str, values: Iterable[str]) -> str:
    return (
        f'<div class="report-metadata" data-kind="{_html_text(label)}">'
        f'<span class="metadata-label">{_html_text(label)}:</span> '
        f'{_html_text(", ".join(values))}</div>'
    )


def _html_body(report: FinalReportVersion) -> str:
    sections: list[str] = []
    for section in report.sections:
        paragraphs: list[str] = []
        for paragraph in section.paragraphs:
            metadata: list[str] = []
            if paragraph.claim_ids:
                metadata.append(_html_metadata("Claims", paragraph.claim_ids))
            if paragraph.citation_ids:
                metadata.append(_html_metadata("Citations", paragraph.citation_ids))
            paragraphs.append(
                '<article class="report-paragraph">'
                f'<p>{_html_text(paragraph.text)}</p>'
                f'{"".join(metadata)}'
                "</article>"
            )
        sections.append(
            f'<section class="report-section" data-section-id="{_html_text(section.section_id)}" '
            f'data-section-order="{_html_text(section.order)}">'
            f'<h2>{_html_text(section.title)}</h2>'
            f'{"".join(paragraphs)}'
            "</section>"
        )
    return (
        '<main class="tracelens-report" '
        f'data-report-id="{_html_text(report.report_id)}" '
        f'data-report-version="{_html_text(report.report_version)}">'
        '<header class="report-header">'
        '<h1>Final Report</h1>'
        f'<p class="report-version">Version {_html_text(report.report_version)}</p>'
        f'<p class="report-hash">Final Report Hash: {_html_text(report.final_report_hash)}</p>'
        "</header>"
        f'{"".join(sections)}'
        "</main>"
    )


def render_final_report_html(report: FinalReportVersion, mode: PresentationMode = "screen") -> str:
    """Render self-contained screen or print HTML from structured content."""
    if mode not in ("screen", "print"):
        raise ValueError(f"unsupported presentation mode: {mode}")
    validate_final_report_for_presentation(report)
    print_css = """
@page { size: A4; margin: 18mm; }
@media print {
  body { background: #fff; color: #111; }
  .report-header { border-bottom: 1px solid #999; }
  .report-section { break-inside: avoid; }
  .report-paragraph { break-inside: avoid; }
  .report-metadata { color: #444; }
}
""" if mode == "print" else ""
    css = f"""
:root {{ color-scheme: light; font-family: sans-serif; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f8fafc; color: #172033; }}
.tracelens-report {{ max-width: 900px; margin: 0 auto; padding: 2rem; background: #fff; }}
.report-header {{ border-bottom: 2px solid #cbd5e1; margin-bottom: 1.5rem; }}
.report-header h1 {{ margin: 0; font-size: 2rem; }}
.report-version, .report-hash {{ color: #475569; font-size: .85rem; overflow-wrap: anywhere; }}
.report-section {{ margin: 0 0 1.5rem; }}
.report-section h2 {{ border-bottom: 1px solid #e2e8f0; padding-bottom: .35rem; font-size: 1.35rem; }}
.report-paragraph {{ margin: 0 0 1rem; }}
.report-paragraph p {{ margin: 0; white-space: pre-wrap; line-height: 1.65; overflow-wrap: anywhere; }}
.report-metadata {{ margin-top: .5rem; color: #64748b; font-size: .75rem; overflow-wrap: anywhere; }}
.metadata-label {{ font-weight: 700; }}
{print_css}
"""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_html_text(_CSP)}">\n'
        f'<meta name="tracelens-presentation-version" content="{_html_text(FINAL_REPORT_PRESENTATION_VERSION)}">\n'
        f'<title>{_html_text("Final Report v" + str(report.report_version))}</title>\n'
        f"<style>{css}</style>\n"
        "</head>\n<body>\n"
        f"{_html_body(report)}\n"
        "</body>\n</html>\n"
    )


def presentation_hash(body: bytes) -> str:
    """Hash the exact UTF-8 response bytes of one derived representation."""
    return hashlib.sha256(body).hexdigest()


def build_final_report_presentation(
    report: FinalReportVersion,
    representation: Literal["markdown", "html", "print"],
) -> FinalReportPresentation:
    """Build one deterministic, non-persisted presentation artifact."""
    if representation == "markdown":
        content = render_final_report_markdown(report)
        media_type = "text/markdown"
    elif representation == "html":
        content = render_final_report_html(report, "screen")
        media_type = "text/html"
    elif representation == "print":
        content = render_final_report_html(report, "print")
        media_type = "text/html"
    else:
        raise ValueError(f"unsupported presentation representation: {representation}")
    body = content.encode("utf-8")
    return FinalReportPresentation(
        representation=representation,
        media_type=media_type,
        body=body,
        presentation_hash=presentation_hash(body),
        final_report_hash=report.final_report_hash,
        filename=presentation_filename(report) if representation == "markdown" else (
            f"tracelens-report-v{report.report_version}-{_FILENAME_SAFE.sub('-', report.report_id).strip('.-') or 'report'}.html"
        ),
    )


def presentation_filename(report: FinalReportVersion) -> str:
    """Return a deterministic safe filename for Markdown download."""
    report_id = _FILENAME_SAFE.sub("-", report.report_id).strip(".-") or "report"
    return f"tracelens-report-v{report.report_version}-{report_id}.md"


__all__ = [
    "FINAL_REPORT_PRESENTATION_VERSION",
    "FinalReportPresentation",
    "FinalReportPresentationIntegrityError",
    "build_final_report_presentation",
    "escape_markdown_text",
    "presentation_filename",
    "presentation_hash",
    "render_final_report_html",
    "render_final_report_markdown",
    "validate_final_report_for_presentation",
]
