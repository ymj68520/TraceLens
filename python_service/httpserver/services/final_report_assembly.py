"""Deterministic Final Report Assembly and publication-gate models."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .citation_validation import CitationValidationResult
from .report_dataset import ReportDataset
from .report_final_validation import SectionRenderValidation
from .report_render_repository import RENDER_PENDING_VALIDATION, ReportRenderCandidate
from .report_rendering import (
    SectionRenderInput,
    SectionRenderOutput,
    build_section_render_input,
    validate_section_render_output,
)
from .section_planning import SECTION_TAXONOMY, ReportSectionPlan

FINAL_REPORT_SCHEMA_VERSION = "final-report-v1"
FINAL_REPORT_ASSEMBLY_RULE_VERSION = "final-report-assembly-v1"
FINAL_REPORT_ASSEMBLED = "assembled"
FINAL_REPORT_VALID = "valid"
FINAL_REPORT_INVALID = "invalid"

REPORT_SECTION_BINDING_MISSING = "REPORT_SECTION_BINDING_MISSING"
REPORT_SECTION_CANDIDATE_NOT_FOUND = "REPORT_SECTION_CANDIDATE_NOT_FOUND"
REPORT_SECTION_VALIDATION_NOT_FOUND = "REPORT_SECTION_VALIDATION_NOT_FOUND"
REPORT_SECTION_VALIDATION_NOT_VALID = "REPORT_SECTION_VALIDATION_NOT_VALID"
REPORT_SECTION_CANDIDATE_MISMATCH = "REPORT_SECTION_CANDIDATE_MISMATCH"
REPORT_SECTION_HASH_MISMATCH = "REPORT_SECTION_HASH_MISMATCH"
REPORT_SECTION_ORDER_INVALID = "REPORT_SECTION_ORDER_INVALID"
REPORT_DUPLICATE_SECTION = "REPORT_DUPLICATE_SECTION"
REPORT_CITATION_NOT_FOUND = "REPORT_CITATION_NOT_FOUND"
REPORT_CITATION_ID_MISMATCH = "REPORT_CITATION_ID_MISMATCH"
REPORT_CITATION_CONFLICT = "REPORT_CITATION_CONFLICT"
REPORT_CLAIM_NOT_FOUND = "REPORT_CLAIM_NOT_FOUND"
REPORT_CLAIM_SECTION_MISMATCH = "REPORT_CLAIM_SECTION_MISMATCH"
REPORT_CLAIM_COVERAGE_MISMATCH = "REPORT_CLAIM_COVERAGE_MISMATCH"
REPORT_DUPLICATE_REPORT_SECTION = "REPORT_DUPLICATE_REPORT_SECTION"
REPORT_HASH_MISMATCH = "REPORT_HASH_MISMATCH"
REPORT_NOT_PUBLISHABLE = "REPORT_NOT_PUBLISHABLE"


class FinalReportSectionBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(..., min_length=1)
    candidate_id: Optional[str] = None
    validation_id: Optional[str] = None


class FinalReportAssemblyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: List[FinalReportSectionBindingRequest] = Field(default_factory=list)
    report_dataset_hash: Optional[str] = None
    citation_graph_hash: Optional[str] = None
    section_plan_hash: Optional[str] = None
    report_schema_version: str = FINAL_REPORT_SCHEMA_VERSION


class FinalReportPublicationBlocked(ValueError):
    """The persisted report cannot cross the explicit publication gate."""


class FinalReportAssemblyError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str = "error"
    entity_type: str
    entity_id: Optional[str] = None
    task_id: Optional[str] = None
    section_id: Optional[str] = None
    candidate_id: Optional[str] = None
    validation_id: Optional[str] = None
    claim_id: Optional[str] = None
    citation_id: Optional[str] = None
    expected_value: Any = None
    actual_value: Any = None
    message: str = ""


class FinalReportParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    claim_ids: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)


class FinalReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    section_type: str
    title: str
    order: int
    candidate_id: Optional[str] = None
    validation_id: Optional[str] = None
    render_input_hash: Optional[str] = None
    render_output_hash: Optional[str] = None
    validation_result_hash: Optional[str] = None
    paragraphs: List[FinalReportParagraph] = Field(default_factory=list)


class FinalReportCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    evidence_key: str
    evidence_type: str
    report_status: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    pinned_analysis: Optional[Dict[str, Any]] = None


class FinalReportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    section_ids: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)


class FinalReportVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = ""
    task_id: str
    report_version: int = 0
    report_schema_version: str = FINAL_REPORT_SCHEMA_VERSION
    assembly_rule_version: str = FINAL_REPORT_ASSEMBLY_RULE_VERSION
    report_dataset_hash: str
    citation_graph_hash: str
    section_plan_hash: str
    sections: List[FinalReportSection] = Field(default_factory=list)
    citation_manifest: List[FinalReportCitation] = Field(default_factory=list)
    claim_manifest: List[FinalReportClaim] = Field(default_factory=list)
    validation_status: str = FINAL_REPORT_VALID
    validation_errors: List[FinalReportAssemblyError] = Field(default_factory=list)
    validation_warnings: List[FinalReportAssemblyError] = Field(default_factory=list)
    final_report_hash: str = ""
    status: str = FINAL_REPORT_ASSEMBLED
    markdown_text: str = ""
    created_at: int = 0

    def canonical_content_dict(self) -> Dict[str, Any]:
        def machine_errors(errors: Iterable[FinalReportAssemblyError]) -> List[Dict[str, Any]]:
            values = []
            for error in errors:
                value = error.model_dump(mode="json", exclude_none=False)
                value.pop("message", None)
                values.append(value)
            return sorted(values, key=_canonical_json)

        return {
            "task_id": self.task_id,
            "report_schema_version": self.report_schema_version,
            "assembly_rule_version": self.assembly_rule_version,
            "report_dataset_hash": self.report_dataset_hash,
            "citation_graph_hash": self.citation_graph_hash,
            "section_plan_hash": self.section_plan_hash,
            "sections": [section.model_dump(mode="json") for section in self.sections],
            "citation_manifest": [
                citation.model_dump(mode="json") for citation in self.citation_manifest
            ],
            "claim_manifest": [
                claim.model_dump(mode="json") for claim in self.claim_manifest
            ],
            "validation_status": self.validation_status,
            "validation_errors": machine_errors(self.validation_errors),
            "validation_warnings": machine_errors(self.validation_warnings),
            "status": self.status,
            "markdown_text": self.markdown_text,
        }

    def canonical_content_json(self) -> str:
        return _canonical_json(self.canonical_content_dict())

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_content_json().encode("utf-8")).hexdigest()

    def with_hash(self) -> "FinalReportVersion":
        return self.model_copy(update={"final_report_hash": self.compute_hash()})

    def to_response_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class FinalReportPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_id: str
    task_id: str
    report_id: str
    report_version: int
    final_report_hash: str
    status: str
    published_at: int
    created_at: int

    def to_response_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class FinalReportAssemblyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    errors: List[FinalReportAssemblyError] = Field(default_factory=list)
    warnings: List[FinalReportAssemblyError] = Field(default_factory=list)
    report: Optional[FinalReportVersion] = None

    def to_response_dict(self) -> Dict[str, Any]:
        result = self.model_dump(mode="json")
        return result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _citation_number(citation_id: str) -> Tuple[int, str]:
    match = re.fullmatch(r"CIT-(\d+)", citation_id or "")
    if match:
        return int(match.group(1)), citation_id
    return (2**63 - 1, citation_id or "")


def _sort_citation_ids(values: Iterable[str]) -> List[str]:
    return sorted(set(values), key=_citation_number)


def _projection(citation: Any) -> Dict[str, Any]:
    return {
        "citation_id": citation.citation_id,
        "evidence_key": citation.evidence_key,
        "evidence_type": citation.evidence_type,
        "report_status": citation.report_status,
        "snapshot": citation.snapshot,
        "pinned_analysis": citation.pinned_analysis,
    }


def _error(
    code: str,
    message: str,
    *,
    task_id: Optional[str] = None,
    section_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
    validation_id: Optional[str] = None,
    entity_type: str = "final_report",
    entity_id: Optional[str] = None,
    claim_id: Optional[str] = None,
    citation_id: Optional[str] = None,
    expected_value: Any = None,
    actual_value: Any = None,
) -> FinalReportAssemblyError:
    return FinalReportAssemblyError(
        code=code,
        entity_type=entity_type,
        entity_id=entity_id,
        task_id=task_id,
        section_id=section_id,
        candidate_id=candidate_id,
        validation_id=validation_id,
        claim_id=claim_id,
        citation_id=citation_id,
        expected_value=expected_value,
        actual_value=actual_value,
        message=message,
    )


def format_final_report_markdown(sections: Sequence[FinalReportSection]) -> str:
    """Format structured sections without changing their canonical content."""
    lines = ["# Final Report", ""]
    for section in sections:
        lines.extend([f"## {section.title}", ""])
        for paragraph in section.paragraphs:
            lines.append(paragraph.text)
            metadata = []
            if paragraph.claim_ids:
                metadata.append(f"claims: {', '.join(paragraph.claim_ids)}")
            if paragraph.citation_ids:
                metadata.append(f"citations: {', '.join(paragraph.citation_ids)}")
            if metadata:
                lines.extend([f"<!-- {'; '.join(metadata)} -->", ""])
        if not section.paragraphs:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class FinalReportAssembler:
    """Pure deterministic assembly of explicitly pinned valid sections."""

    def assemble(
        self,
        request: FinalReportAssemblyRequest,
        dataset: ReportDataset,
        graph: CitationValidationResult,
        plan: ReportSectionPlan,
        candidates: Mapping[str, Optional[ReportRenderCandidate]],
        validations: Mapping[str, Optional[SectionRenderValidation]],
    ) -> FinalReportAssemblyResult:
        errors: List[FinalReportAssemblyError] = []
        warnings: List[FinalReportAssemblyError] = []
        task_id = dataset.task_id
        plan_sections = {section.section_id: section for section in plan.sections}
        canonical_ids = [f"SEC-{index:03d}" for index in range(1, len(SECTION_TAXONOMY) + 1)]
        request_bindings: Dict[str, FinalReportSectionBindingRequest] = {}

        for binding in request.sections:
            if binding.section_id not in plan_sections:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "Request references an unknown report section.",
                    task_id=task_id,
                    section_id=binding.section_id,
                ))
                continue
            if binding.section_id in request_bindings:
                errors.append(_error(
                    REPORT_DUPLICATE_SECTION,
                    "Request contains a duplicate section binding.",
                    task_id=task_id,
                    section_id=binding.section_id,
                ))
                continue
            request_bindings[binding.section_id] = binding

        current_hashes = {
            "dataset": dataset.report_dataset_hash,
            "citation_graph": graph.citation_graph_hash,
            "section_plan": plan.section_plan_hash,
        }
        explicit_hashes = {
            "dataset": request.report_dataset_hash,
            "citation_graph": request.citation_graph_hash,
            "section_plan": request.section_plan_hash,
        }
        for name, expected in explicit_hashes.items():
            if expected is not None and expected != current_hashes[name]:
                errors.append(_error(
                    REPORT_HASH_MISMATCH,
                    f"Explicit {name} hash does not match the current assembly input.",
                    task_id=task_id,
                    entity_type=name,
                    expected_value=expected,
                    actual_value=current_hashes[name],
                ))

        if dataset.validation.status != "valid":
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Report Dataset is not valid for assembly.",
                task_id=task_id,
                entity_type="dataset",
                actual_value=dataset.validation.status,
            ))
        if graph.validation.status != "valid":
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Citation Graph is not valid for assembly.",
                task_id=task_id,
                entity_type="citation_graph",
                actual_value=graph.validation.status,
            ))
        if plan.validation.status != "valid":
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Section Plan is not valid for assembly.",
                task_id=task_id,
                entity_type="section_plan",
                actual_value=plan.validation.status,
            ))
        if dataset.report_dataset_hash != dataset.compute_hash():
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Report Dataset self hash does not match.",
                task_id=task_id,
                entity_type="dataset",
                expected_value=dataset.report_dataset_hash,
                actual_value=dataset.compute_hash(),
            ))
        if graph.citation_graph_hash != graph.compute_hash():
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Citation Graph self hash does not match.",
                task_id=task_id,
                entity_type="citation_graph",
                expected_value=graph.citation_graph_hash,
                actual_value=graph.compute_hash(),
            ))
        if plan.section_plan_hash != plan.compute_hash():
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Section Plan self hash does not match.",
                task_id=task_id,
                entity_type="section_plan",
                expected_value=plan.section_plan_hash,
                actual_value=plan.compute_hash(),
            ))
        if graph.dataset_hash != dataset.report_dataset_hash:
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Citation Graph is not bound to this Dataset.",
                task_id=task_id,
                entity_type="citation_graph",
                expected_value=dataset.report_dataset_hash,
                actual_value=graph.dataset_hash,
            ))
        if (
            plan.dataset_hash != dataset.report_dataset_hash
            or plan.citation_graph_hash != graph.citation_graph_hash
        ):
            errors.append(_error(
                REPORT_HASH_MISMATCH,
                "Section Plan is not bound to this Dataset and Citation Graph.",
                task_id=task_id,
                entity_type="section_plan",
            ))

        sections: List[FinalReportSection] = []
        citation_nodes = {citation.citation_id: citation for citation in graph.citations}
        citation_projection_by_id: Dict[str, Dict[str, Any]] = {}
        claim_manifest_data: Dict[str, Dict[str, Any]] = {}
        built_inputs: Dict[str, SectionRenderInput] = {}

        for section_id in canonical_ids:
            section = plan_sections.get(section_id)
            if section is None:
                errors.append(_error(
                    REPORT_SECTION_ORDER_INVALID,
                    "Canonical Section Plan is missing a fixed section.",
                    task_id=task_id,
                    section_id=section_id,
                ))
                continue
            binding = request_bindings.get(section_id)
            is_empty = not section.claim_ids
            if binding is None:
                if not is_empty:
                    errors.append(_error(
                        REPORT_SECTION_BINDING_MISSING,
                        "A non-empty section requires explicit Candidate and Validation bindings.",
                        task_id=task_id,
                        section_id=section_id,
                    ))
                sections.append(FinalReportSection(
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title=section.title,
                    order=section.order,
                ))
                continue
            if is_empty and (binding.candidate_id or binding.validation_id):
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "An empty section cannot carry a Candidate or Validation binding.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=binding.candidate_id,
                    validation_id=binding.validation_id,
                ))
                sections.append(FinalReportSection(
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title=section.title,
                    order=section.order,
                ))
                continue
            if is_empty:
                sections.append(FinalReportSection(
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title=section.title,
                    order=section.order,
                ))
                continue
            if not binding.candidate_id or not binding.validation_id:
                errors.append(_error(
                    REPORT_SECTION_BINDING_MISSING,
                    "Both Candidate and Validation IDs are required for a non-empty section.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=binding.candidate_id,
                    validation_id=binding.validation_id,
                ))
                sections.append(FinalReportSection(
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title=section.title,
                    order=section.order,
                ))
                continue

            candidate = candidates.get(binding.candidate_id)
            validation = validations.get(binding.validation_id)
            if candidate is None:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_NOT_FOUND,
                    "Pinned Candidate was not found in the task scope.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=binding.candidate_id,
                ))
            if validation is None:
                errors.append(_error(
                    REPORT_SECTION_VALIDATION_NOT_FOUND,
                    "Pinned Validation was not found in the task scope.",
                    task_id=task_id,
                    section_id=section_id,
                    validation_id=binding.validation_id,
                ))
            if candidate is None or validation is None:
                sections.append(FinalReportSection(
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title=section.title,
                    order=section.order,
                    candidate_id=binding.candidate_id,
                    validation_id=binding.validation_id,
                ))
                continue

            if candidate.task_id != task_id or validation.task_id != task_id:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "Pinned Candidate or Validation is outside the task scope.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                    validation_id=validation.validation_id,
                ))
            if candidate.section_id != section_id or validation.section_id != section_id:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "Pinned Candidate or Validation section identity does not match.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                    validation_id=validation.validation_id,
                ))
            if candidate.status != RENDER_PENDING_VALIDATION:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "Pinned Candidate is not pending final validation.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                    expected_value=RENDER_PENDING_VALIDATION,
                    actual_value=candidate.status,
                ))
            if validation.status != FINAL_REPORT_VALID:
                errors.append(_error(
                    REPORT_SECTION_VALIDATION_NOT_VALID,
                    "Pinned Validation is not valid.",
                    task_id=task_id,
                    section_id=section_id,
                    validation_id=validation.validation_id,
                    actual_value=validation.status,
                ))
            if validation.candidate_id != candidate.candidate_id:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "Validation does not reference the pinned Candidate.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                    validation_id=validation.validation_id,
                    expected_value=candidate.candidate_id,
                    actual_value=validation.candidate_id,
                ))

            expected_pairs = (
                ("dataset_hash", candidate.dataset_hash, dataset.report_dataset_hash),
                ("citation_graph_hash", candidate.citation_graph_hash, graph.citation_graph_hash),
                ("section_plan_hash", candidate.section_plan_hash, plan.section_plan_hash),
            )
            for name, expected, actual in expected_pairs:
                if expected != actual:
                    errors.append(_error(
                        REPORT_SECTION_HASH_MISMATCH,
                        f"Candidate {name} does not match the current assembly chain.",
                        task_id=task_id,
                        section_id=section_id,
                        candidate_id=candidate.candidate_id,
                        validation_id=validation.validation_id,
                        entity_type=name,
                        expected_value=expected,
                        actual_value=actual,
                    ))
            validation_pairs = (
                ("dataset_hash", validation.dataset_hash, candidate.dataset_hash),
                ("citation_graph_hash", validation.citation_graph_hash, candidate.citation_graph_hash),
                ("section_plan_hash", validation.section_plan_hash, candidate.section_plan_hash),
                ("render_input_hash", validation.render_input_hash, candidate.render_input_hash),
                ("render_output_hash", validation.render_output_hash, candidate.render_output_hash),
                ("observed_dataset_hash", validation.observed_dataset_hash, dataset.report_dataset_hash),
                ("observed_citation_graph_hash", validation.observed_citation_graph_hash, graph.citation_graph_hash),
                ("observed_section_plan_hash", validation.observed_section_plan_hash, plan.section_plan_hash),
                ("observed_render_input_hash", validation.observed_render_input_hash, candidate.render_input_hash),
                ("observed_render_output_hash", validation.observed_render_output_hash, candidate.render_output_hash),
            )
            for name, expected, actual in validation_pairs:
                if expected != actual:
                    errors.append(_error(
                        REPORT_SECTION_HASH_MISMATCH,
                        f"Validation {name} does not match the pinned assembly chain.",
                        task_id=task_id,
                        section_id=section_id,
                        candidate_id=candidate.candidate_id,
                        validation_id=validation.validation_id,
                        entity_type=name,
                        expected_value=expected,
                        actual_value=actual,
                    ))

            output = candidate.structured_output
            if output is None:
                errors.append(_error(
                    REPORT_SECTION_CANDIDATE_MISMATCH,
                    "Pinned Candidate has no parseable structured output.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                ))
                sections.append(FinalReportSection(
                    section_id=section.section_id,
                    section_type=section.section_type,
                    title=section.title,
                    order=section.order,
                    candidate_id=candidate.candidate_id,
                    validation_id=validation.validation_id,
                ))
                continue
            observed_output_hash = output.compute_hash()
            if candidate.render_output_hash != observed_output_hash:
                errors.append(_error(
                    REPORT_SECTION_HASH_MISMATCH,
                    "Candidate structured output hash does not match.",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                    expected_value=candidate.render_output_hash,
                    actual_value=observed_output_hash,
                ))

            try:
                input_data = build_section_render_input(
                    dataset,
                    graph,
                    plan,
                    section_id,
                    prompt_version=candidate.prompt_version,
                )
                built_inputs[section_id] = input_data
                if candidate.render_input_hash != input_data.compute_hash():
                    errors.append(_error(
                        REPORT_SECTION_HASH_MISMATCH,
                        "Candidate render input hash does not match current input.",
                        task_id=task_id,
                        section_id=section_id,
                        candidate_id=candidate.candidate_id,
                        expected_value=candidate.render_input_hash,
                        actual_value=input_data.compute_hash(),
                    ))
                render_errors = validate_section_render_output(input_data, output)
                for render_error in render_errors:
                    errors.append(_error(
                        REPORT_SECTION_CANDIDATE_MISMATCH,
                        render_error.message,
                        task_id=task_id,
                        section_id=section_id,
                        candidate_id=candidate.candidate_id,
                        validation_id=validation.validation_id,
                        claim_id=render_error.claim_id,
                        citation_id=render_error.citation_id,
                    ))
            except Exception as exc:
                errors.append(_error(
                    REPORT_SECTION_HASH_MISMATCH,
                    f"Section render input cannot be reconstructed: {exc}",
                    task_id=task_id,
                    section_id=section_id,
                    candidate_id=candidate.candidate_id,
                    validation_id=validation.validation_id,
                ))

            section_output = FinalReportSection(
                section_id=section.section_id,
                section_type=section.section_type,
                title=section.title,
                order=section.order,
                candidate_id=candidate.candidate_id,
                validation_id=validation.validation_id,
                render_input_hash=candidate.render_input_hash,
                render_output_hash=candidate.render_output_hash,
                validation_result_hash=validation.validation_result_hash,
                paragraphs=[
                    FinalReportParagraph(**paragraph.model_dump(mode="json"))
                    for paragraph in output.paragraphs
                ],
            )
            sections.append(section_output)

            input_data = built_inputs.get(section_id)
            if input_data is None:
                continue
            claim_by_id = {claim.claim_id: claim for claim in input_data.claims}
            coverage_by_claim = {
                item.get("claim_id"): item
                for item in (validation.coverage.get("claims") or [])
                if isinstance(item, dict)
            }
            for claim_id in section.claim_ids:
                paragraph_indexes = [
                    index
                    for index, paragraph in enumerate(output.paragraphs)
                    if claim_id in paragraph.claim_ids
                ]
                allowed_for_claim = {
                    citation.citation_id
                    for citation in claim_by_id.get(claim_id, type("Missing", (), {"citations": []})()).citations
                }
                claim_citation_ids = _sort_citation_ids(
                    citation_id
                    for index in paragraph_indexes
                    for citation_id in output.paragraphs[index].citation_ids
                    if citation_id in allowed_for_claim
                )
                actual_coverage = {
                    "claim_id": claim_id,
                    "mentioned": bool(paragraph_indexes),
                    "citation_covered": bool(claim_citation_ids),
                    "paragraph_indexes": paragraph_indexes,
                    "citation_ids": claim_citation_ids,
                }
                expected_coverage = coverage_by_claim.get(claim_id)
                if expected_coverage != actual_coverage:
                    errors.append(_error(
                        REPORT_CLAIM_COVERAGE_MISMATCH,
                        "Assembly Claim coverage does not match the bound 4E coverage manifest.",
                        task_id=task_id,
                        section_id=section_id,
                        validation_id=validation.validation_id,
                        claim_id=claim_id,
                        expected_value=expected_coverage,
                        actual_value=actual_coverage,
                    ))
                if claim_id in claim_by_id and paragraph_indexes:
                    entry = claim_manifest_data.setdefault(
                        claim_id,
                        {"section_ids": [], "citation_ids": []},
                    )
                    if section_id not in entry["section_ids"]:
                        entry["section_ids"].append(section_id)
                    entry["citation_ids"].extend(claim_citation_ids)

            for paragraph in output.paragraphs:
                for citation_id in paragraph.citation_ids:
                    node = citation_nodes.get(citation_id)
                    if node is None:
                        errors.append(_error(
                            REPORT_CITATION_NOT_FOUND,
                            "Paragraph references a Citation absent from the current graph.",
                            task_id=task_id,
                            section_id=section_id,
                            citation_id=citation_id,
                        ))
                        continue
                    projection = _projection(node)
                    previous = citation_projection_by_id.get(citation_id)
                    if previous is not None and previous != projection:
                        errors.append(_error(
                            REPORT_CITATION_CONFLICT,
                            "The same Citation ID has conflicting canonical projections.",
                            task_id=task_id,
                            section_id=section_id,
                            citation_id=citation_id,
                            expected_value=previous,
                            actual_value=projection,
                        ))
                    citation_projection_by_id[citation_id] = projection

        for section_id in request_bindings:
            if section_id not in canonical_ids:
                continue

        citation_manifest = [
            FinalReportCitation(**citation_projection_by_id[citation_id])
            for citation_id in _sort_citation_ids(citation_projection_by_id)
        ]
        claim_manifest = [
            FinalReportClaim(
                claim_id=claim_id,
                section_ids=entry["section_ids"],
                citation_ids=_sort_citation_ids(entry["citation_ids"]),
            )
            for claim_id, entry in sorted(claim_manifest_data.items())
        ]
        sections.sort(key=lambda section: section.order)
        markdown_text = format_final_report_markdown(sections)

        if errors:
            return FinalReportAssemblyResult(
                status=FINAL_REPORT_INVALID,
                errors=errors,
                warnings=warnings,
            )

        report = FinalReportVersion(
            task_id=task_id,
            report_schema_version=request.report_schema_version,
            report_dataset_hash=dataset.report_dataset_hash,
            citation_graph_hash=graph.citation_graph_hash,
            section_plan_hash=plan.section_plan_hash,
            sections=sections,
            citation_manifest=citation_manifest,
            claim_manifest=claim_manifest,
            validation_status=FINAL_REPORT_VALID,
            validation_errors=[],
            validation_warnings=warnings,
            status=FINAL_REPORT_ASSEMBLED,
            markdown_text=markdown_text,
        ).with_hash()
        return FinalReportAssemblyResult(
            status=FINAL_REPORT_VALID,
            errors=[],
            warnings=warnings,
            report=report,
        )


__all__ = [
    "FINAL_REPORT_SCHEMA_VERSION",
    "FINAL_REPORT_ASSEMBLY_RULE_VERSION",
    "FINAL_REPORT_ASSEMBLED",
    "FINAL_REPORT_VALID",
    "FINAL_REPORT_INVALID",
    "FinalReportSectionBindingRequest",
    "FinalReportAssemblyRequest",
    "FinalReportAssemblyError",
    "FinalReportPublicationBlocked",
    "FinalReportParagraph",
    "FinalReportSection",
    "FinalReportCitation",
    "FinalReportClaim",
    "FinalReportVersion",
    "FinalReportPublication",
    "FinalReportAssemblyResult",
    "FinalReportAssembler",
    "format_final_report_markdown",
]
