"""Independent Phase 4E final validation for rendered report sections."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .citation_validation import CitationValidationResult
from .report_dataset import ReportDataset
from .report_rendering import (
    RENDER_CITATION_NOT_ALLOWED,
    RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM,
    RENDER_DUPLICATE_CITATION_ID,
    RENDER_DUPLICATE_CLAIM_ID,
    RENDER_EMPTY_PARAGRAPH,
    RENDER_OUTPUT_SCHEMA_INVALID,
    RENDER_SECTION_ID_MISMATCH,
    RENDER_USED_CLAIMS_MISMATCH,
    RENDER_CLAIM_NOT_ALLOWED,
    SectionRenderInput,
    SectionRenderOutput,
    build_section_render_input,
    validate_section_render_output,
)
from .report_render_repository import ReportRenderCandidate, RENDER_PENDING_VALIDATION
from .section_planning import ReportSectionPlan

FINAL_VALIDATION_RULE_VERSION = "report-final-validation-v1"

FINAL_QUEUED = "queued"
FINAL_RUNNING = "running"
FINAL_VALID = "valid"
FINAL_INVALID = "invalid"
FINAL_BLOCKED = "blocked"
FINAL_FAILED = "failed"

FINAL_UPSTREAM_DATASET_BLOCKED = "FINAL_UPSTREAM_DATASET_BLOCKED"
FINAL_UPSTREAM_CITATION_BLOCKED = "FINAL_UPSTREAM_CITATION_BLOCKED"
FINAL_UPSTREAM_SECTION_PLAN_BLOCKED = "FINAL_UPSTREAM_SECTION_PLAN_BLOCKED"
FINAL_DATASET_HASH_MISMATCH = "FINAL_DATASET_HASH_MISMATCH"
FINAL_CITATION_GRAPH_HASH_MISMATCH = "FINAL_CITATION_GRAPH_HASH_MISMATCH"
FINAL_SECTION_PLAN_HASH_MISMATCH = "FINAL_SECTION_PLAN_HASH_MISMATCH"
FINAL_RENDER_INPUT_HASH_MISMATCH = "FINAL_RENDER_INPUT_HASH_MISMATCH"
FINAL_RENDER_OUTPUT_HASH_MISMATCH = "FINAL_RENDER_OUTPUT_HASH_MISMATCH"
FINAL_CANDIDATE_NOT_PENDING_VALIDATION = "FINAL_CANDIDATE_NOT_PENDING_VALIDATION"
FINAL_CANDIDATE_TASK_MISMATCH = "FINAL_CANDIDATE_TASK_MISMATCH"
FINAL_CANDIDATE_SECTION_MISMATCH = "FINAL_CANDIDATE_SECTION_MISMATCH"
FINAL_SECTION_ID_MISMATCH = "FINAL_SECTION_ID_MISMATCH"
FINAL_CLAIM_NOT_ALLOWED = "FINAL_CLAIM_NOT_ALLOWED"
FINAL_CITATION_NOT_ALLOWED = "FINAL_CITATION_NOT_ALLOWED"
FINAL_CITATION_NOT_ALLOWED_FOR_CLAIM = "FINAL_CITATION_NOT_ALLOWED_FOR_CLAIM"
FINAL_CITATION_NOT_RENDERABLE = "FINAL_CITATION_NOT_RENDERABLE"
FINAL_USED_CLAIMS_MISMATCH = "FINAL_USED_CLAIMS_MISMATCH"
FINAL_DUPLICATE_CLAIM_ID = "FINAL_DUPLICATE_CLAIM_ID"
FINAL_DUPLICATE_CITATION_ID = "FINAL_DUPLICATE_CITATION_ID"
FINAL_EMPTY_PARAGRAPH = "FINAL_EMPTY_PARAGRAPH"
FINAL_CLAIM_NOT_COVERED = "FINAL_CLAIM_NOT_COVERED"
FINAL_CLAIM_WITHOUT_CITATION = "FINAL_CLAIM_WITHOUT_CITATION"
FINAL_PARAGRAPH_WITHOUT_CITATION = "FINAL_PARAGRAPH_WITHOUT_CITATION"
FINAL_PARAGRAPH_WITHOUT_CLAIM = "FINAL_PARAGRAPH_WITHOUT_CLAIM"
FINAL_ORPHAN_CITATION = "FINAL_ORPHAN_CITATION"
FINAL_STRUCTURED_OUTPUT_INVALID = "FINAL_STRUCTURED_OUTPUT_INVALID"
FINAL_VALIDATION_INTERRUPTED = "FINAL_VALIDATION_INTERRUPTED"

_RENDER_ERROR_MAP = {
    RENDER_SECTION_ID_MISMATCH: FINAL_SECTION_ID_MISMATCH,
    RENDER_CLAIM_NOT_ALLOWED: FINAL_CLAIM_NOT_ALLOWED,
    RENDER_CITATION_NOT_ALLOWED: FINAL_CITATION_NOT_ALLOWED,
    RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM: FINAL_CITATION_NOT_ALLOWED_FOR_CLAIM,
    RENDER_USED_CLAIMS_MISMATCH: FINAL_USED_CLAIMS_MISMATCH,
    RENDER_DUPLICATE_CLAIM_ID: FINAL_DUPLICATE_CLAIM_ID,
    RENDER_DUPLICATE_CITATION_ID: FINAL_DUPLICATE_CITATION_ID,
    RENDER_EMPTY_PARAGRAPH: FINAL_EMPTY_PARAGRAPH,
    RENDER_OUTPUT_SCHEMA_INVALID: FINAL_STRUCTURED_OUTPUT_INVALID,
}


class ReportRenderCandidateNotFound(KeyError):
    """Opaque task-scoped candidate lookup failure."""


class FinalValidationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str = "error"
    entity_type: str
    entity_id: Optional[str] = None
    candidate_id: Optional[str] = None
    section_id: Optional[str] = None
    paragraph_index: Optional[int] = None
    claim_id: Optional[str] = None
    citation_id: Optional[str] = None
    expected_value: Any = None
    actual_value: Any = None
    message: str = ""


class SectionRenderValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_id: str
    task_id: str
    candidate_id: str
    section_id: str
    validation_version: int
    validation_rule_version: str
    dataset_hash: str
    citation_graph_hash: str
    section_plan_hash: str
    render_input_hash: str
    render_output_hash: Optional[str] = None
    observed_dataset_hash: Optional[str] = None
    observed_citation_graph_hash: Optional[str] = None
    observed_section_plan_hash: Optional[str] = None
    observed_render_input_hash: Optional[str] = None
    observed_render_output_hash: Optional[str] = None
    validation_input_hash: Optional[str] = None
    validation_result_hash: Optional[str] = None
    status: str
    validation_errors: List[FinalValidationError] = Field(default_factory=list)
    validation_warnings: List[FinalValidationError] = Field(default_factory=list)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: int
    completed_at: Optional[int] = None

    def to_response_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class FinalValidationResult(BaseModel):
    """Pure validator output before it is persisted."""

    status: str
    errors: List[FinalValidationError] = Field(default_factory=list)
    warnings: List[FinalValidationError] = Field(default_factory=list)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    observed_dataset_hash: Optional[str] = None
    observed_citation_graph_hash: Optional[str] = None
    observed_section_plan_hash: Optional[str] = None
    observed_render_input_hash: Optional[str] = None
    observed_render_output_hash: Optional[str] = None
    validation_input_hash: Optional[str] = None
    validation_result_hash: Optional[str] = None
    error_message: Optional[str] = None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _machine_error(error: FinalValidationError) -> Dict[str, Any]:
    value = error.model_dump(mode="json", exclude_none=False)
    value.pop("message", None)
    return value


def _canonical_errors(errors: Iterable[FinalValidationError]) -> List[Dict[str, Any]]:
    values = [_machine_error(error) for error in errors]
    return sorted(values, key=_canonical_json)


def compute_validation_input_hash(
    candidate: ReportRenderCandidate,
    *,
    observed_dataset_hash: Optional[str],
    observed_citation_graph_hash: Optional[str],
    observed_section_plan_hash: Optional[str],
    observed_render_input_hash: Optional[str],
    observed_render_output_hash: Optional[str],
    validation_rule_version: str = FINAL_VALIDATION_RULE_VERSION,
) -> str:
    """Hash expected and observed provenance for this validation attempt."""
    payload = {
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "task_id": candidate.task_id,
            "section_id": candidate.section_id,
            "dataset_hash": candidate.dataset_hash,
            "citation_graph_hash": candidate.citation_graph_hash,
            "section_plan_hash": candidate.section_plan_hash,
            "render_input_hash": candidate.render_input_hash,
            "render_output_hash": candidate.render_output_hash,
        },
        "observed": {
            "dataset_hash": observed_dataset_hash,
            "citation_graph_hash": observed_citation_graph_hash,
            "section_plan_hash": observed_section_plan_hash,
            "render_input_hash": observed_render_input_hash,
            "render_output_hash": observed_render_output_hash,
        },
        "validation_rule_version": validation_rule_version,
    }
    return _sha256(payload)


def compute_validation_result_hash(
    *,
    validation_input_hash: Optional[str],
    status: str,
    errors: Iterable[FinalValidationError],
    warnings: Iterable[FinalValidationError],
    coverage: Mapping[str, Any],
) -> str:
    payload = {
        "validation_input_hash": validation_input_hash,
        "status": status,
        "errors": _canonical_errors(errors),
        "warnings": _canonical_errors(warnings),
        "coverage": coverage,
    }
    return _sha256(payload)


def _error(
    code: str,
    message: str,
    *,
    candidate_id: Optional[str] = None,
    section_id: Optional[str] = None,
    entity_type: str = "render_validation",
    entity_id: Optional[str] = None,
    paragraph_index: Optional[int] = None,
    claim_id: Optional[str] = None,
    citation_id: Optional[str] = None,
    expected_value: Any = None,
    actual_value: Any = None,
) -> FinalValidationError:
    return FinalValidationError(
        code=code,
        entity_type=entity_type,
        entity_id=entity_id,
        candidate_id=candidate_id,
        section_id=section_id,
        paragraph_index=paragraph_index,
        claim_id=claim_id,
        citation_id=citation_id,
        expected_value=expected_value,
        actual_value=actual_value,
        message=message,
    )


def _upstream_errors(
    status: str,
    errors: Sequence[Any],
    *,
    candidate_id: str,
    section_id: str,
    entity_type: str,
) -> List[FinalValidationError]:
    if status == "valid":
        return []
    code = {
        "dataset": FINAL_UPSTREAM_DATASET_BLOCKED,
        "citation_graph": FINAL_UPSTREAM_CITATION_BLOCKED,
        "section_plan": FINAL_UPSTREAM_SECTION_PLAN_BLOCKED,
    }[entity_type]
    if not errors:
        return [_error(
            code,
            f"Current {entity_type} validation is blocked without a recorded error.",
            candidate_id=candidate_id,
            section_id=section_id,
            entity_type=entity_type,
        )]
    result: List[FinalValidationError] = []
    for upstream_error in errors:
        data = upstream_error.model_dump(mode="json") if isinstance(upstream_error, BaseModel) else dict(upstream_error)
        result.append(_error(
            data.get("code", code),
            data.get("message", f"Current {entity_type} validation is blocked."),
            candidate_id=candidate_id,
            section_id=section_id,
            entity_type=data.get("entity_type", entity_type),
            entity_id=data.get("entity_id"),
            claim_id=data.get("claim_id"),
            citation_id=data.get("citation_id"),
        ))
    return result


def _map_render_errors(
    errors: Iterable[Any], *, candidate_id: str, section_id: str
) -> List[FinalValidationError]:
    mapped: List[FinalValidationError] = []
    for source in errors:
        data = source.model_dump(mode="json") if isinstance(source, BaseModel) else dict(source)
        source_code = data.get("code", FINAL_STRUCTURED_OUTPUT_INVALID)
        code = _RENDER_ERROR_MAP.get(source_code, FINAL_STRUCTURED_OUTPUT_INVALID)
        message = data.get("message", "4D render validation failed.")
        if source_code not in _RENDER_ERROR_MAP:
            message = f"Unknown 4D render validation code {source_code}: {message}"
        mapped.append(_error(
            code,
            message,
            candidate_id=candidate_id,
            section_id=data.get("section_id") or section_id,
            entity_type=data.get("entity_type", "render_output"),
            entity_id=data.get("entity_id"),
            claim_id=data.get("claim_id"),
            citation_id=data.get("citation_id"),
        ))
    return mapped


def _coverage(
    input_data: SectionRenderInput,
    output: SectionRenderOutput,
    *,
    candidate_id: str,
) -> Tuple[Dict[str, Any], List[FinalValidationError]]:
    claim_by_id = {claim.claim_id: claim for claim in input_data.claims}
    section_claim_ids = list(input_data.claim_ids)
    errors: List[FinalValidationError] = []
    claims_manifest: List[Dict[str, Any]] = []

    for claim_id in section_claim_ids:
        paragraph_indexes = [
            index
            for index, paragraph in enumerate(output.paragraphs)
            if claim_id in paragraph.claim_ids
        ]
        allowed_for_claim = {
            citation.citation_id
            for citation in claim_by_id.get(claim_id, type("Missing", (), {"citations": []})()).citations
        }
        citation_ids: List[str] = []
        for index in paragraph_indexes:
            for citation_id in output.paragraphs[index].citation_ids:
                if citation_id in allowed_for_claim and citation_id not in citation_ids:
                    citation_ids.append(citation_id)
        mentioned = bool(paragraph_indexes)
        citation_covered = bool(citation_ids)
        claims_manifest.append({
            "claim_id": claim_id,
            "mentioned": mentioned,
            "citation_covered": citation_covered,
            "paragraph_indexes": paragraph_indexes,
            "citation_ids": citation_ids,
        })
        if not mentioned:
            errors.append(_error(
                FINAL_CLAIM_NOT_COVERED,
                f"Claim {claim_id} is not covered by any paragraph.",
                candidate_id=candidate_id,
                section_id=input_data.section_id,
                claim_id=claim_id,
            ))
        elif not citation_covered:
            errors.append(_error(
                FINAL_CLAIM_WITHOUT_CITATION,
                f"Claim {claim_id} is mentioned without its own provenance citation.",
                candidate_id=candidate_id,
                section_id=input_data.section_id,
                claim_id=claim_id,
            ))

    for index, paragraph in enumerate(output.paragraphs):
        if paragraph.claim_ids and not paragraph.citation_ids:
            errors.append(_error(
                FINAL_PARAGRAPH_WITHOUT_CITATION,
                "A paragraph containing Claims must contain a Citation.",
                candidate_id=candidate_id,
                section_id=input_data.section_id,
                paragraph_index=index,
            ))
        if paragraph.text.strip() and not paragraph.claim_ids:
            errors.append(_error(
                FINAL_PARAGRAPH_WITHOUT_CLAIM,
                "A non-empty paragraph must contain at least one Claim.",
                candidate_id=candidate_id,
                section_id=input_data.section_id,
                paragraph_index=index,
            ))
        if not paragraph.claim_ids and paragraph.citation_ids:
            errors.append(_error(
                FINAL_ORPHAN_CITATION,
                "A Citation cannot appear in a paragraph without a Claim.",
                candidate_id=candidate_id,
                section_id=input_data.section_id,
                paragraph_index=index,
            ))

    return {"claims": claims_manifest}, errors


class FinalSectionValidator:
    """Pure, non-LLM final validation of one immutable render candidate."""

    def validate(
        self,
        candidate: ReportRenderCandidate,
        dataset: ReportDataset,
        graph: CitationValidationResult,
        plan: ReportSectionPlan,
    ) -> FinalValidationResult:
        errors: List[FinalValidationError] = []
        warnings: List[FinalValidationError] = []
        blocked_prerequisite = False
        observed_dataset_hash = dataset.compute_hash()
        observed_graph_hash = graph.compute_hash()
        observed_plan_hash = plan.compute_hash()
        observed_input_hash: Optional[str] = None
        observed_output_hash: Optional[str] = None
        input_data: Optional[SectionRenderInput] = None

        if dataset.validation.status != "valid":
            blocked_prerequisite = True
        errors.extend(_upstream_errors(
            dataset.validation.status,
            dataset.validation.errors,
            candidate_id=candidate.candidate_id,
            section_id=candidate.section_id,
            entity_type="dataset",
        ))
        if graph.validation.status != "valid":
            blocked_prerequisite = True
        errors.extend(_upstream_errors(
            graph.validation.status,
            graph.validation.errors,
            candidate_id=candidate.candidate_id,
            section_id=candidate.section_id,
            entity_type="citation_graph",
        ))
        if plan.validation.status != "valid":
            blocked_prerequisite = True
        errors.extend(_upstream_errors(
            plan.validation.status,
            plan.validation.errors,
            candidate_id=candidate.candidate_id,
            section_id=candidate.section_id,
            entity_type="section_plan",
        ))

        if candidate.status != RENDER_PENDING_VALIDATION:
            errors.append(_error(
                FINAL_CANDIDATE_NOT_PENDING_VALIDATION,
                "Candidate is not pending final validation.",
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
                entity_type="candidate",
                entity_id=candidate.candidate_id,
                expected_value=RENDER_PENDING_VALIDATION,
                actual_value=candidate.status,
            ))

        if candidate.task_id != dataset.task_id:
            errors.append(_error(
                FINAL_CANDIDATE_TASK_MISMATCH,
                "Candidate task does not match the current Dataset task.",
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
                entity_type="candidate",
                entity_id=candidate.candidate_id,
                expected_value=dataset.task_id,
                actual_value=candidate.task_id,
            ))

        if candidate.section_id not in {section.section_id for section in plan.sections}:
            errors.append(_error(
                FINAL_CANDIDATE_SECTION_MISMATCH,
                "Candidate section does not exist in the current Section Plan.",
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
                entity_type="candidate",
                entity_id=candidate.candidate_id,
                expected_value=[section.section_id for section in plan.sections],
                actual_value=candidate.section_id,
            ))

        try:
            input_data = build_section_render_input(
                dataset,
                graph,
                plan,
                candidate.section_id,
                prompt_version=candidate.prompt_version,
            )
            observed_input_hash = input_data.compute_hash()
        except Exception as exc:
            blocked_prerequisite = True
            errors.append(_error(
                FINAL_STRUCTURED_OUTPUT_INVALID,
                f"SectionRenderInput could not be reconstructed: {exc}",
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
                entity_type="render_input",
            ))

        expected_hashes = (
            (FINAL_DATASET_HASH_MISMATCH, "dataset", "dataset self hash", dataset.report_dataset_hash, observed_dataset_hash),
            (FINAL_DATASET_HASH_MISMATCH, "dataset", "candidate provenance", candidate.dataset_hash, observed_dataset_hash),
            (FINAL_CITATION_GRAPH_HASH_MISMATCH, "citation_graph", "citation graph self hash", graph.citation_graph_hash, observed_graph_hash),
            (FINAL_CITATION_GRAPH_HASH_MISMATCH, "citation_graph", "candidate provenance", candidate.citation_graph_hash, observed_graph_hash),
            (FINAL_SECTION_PLAN_HASH_MISMATCH, "section_plan", "section plan self hash", plan.section_plan_hash, observed_plan_hash),
            (FINAL_SECTION_PLAN_HASH_MISMATCH, "section_plan", "candidate provenance", candidate.section_plan_hash, observed_plan_hash),
            (FINAL_RENDER_INPUT_HASH_MISMATCH, "render_input", "candidate provenance", candidate.render_input_hash, observed_input_hash),
        )

        for code, entity_type, identity, expected, actual in expected_hashes:
            if expected != actual:
                errors.append(_error(
                    code,
                    f"Candidate {entity_type} ({identity}) hash does not match the current observed value.",
                    candidate_id=candidate.candidate_id,
                    section_id=candidate.section_id,
                    entity_type=entity_type,
                    entity_id=candidate.candidate_id,
                    expected_value=expected,
                    actual_value=actual,
                ))

        if candidate.structured_output is None:
            errors.append(_error(
                FINAL_STRUCTURED_OUTPUT_INVALID,
                "Candidate has no parseable structured output.",
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
                entity_type="render_output",
                entity_id=candidate.candidate_id,
            ))
        else:
            observed_output_hash = candidate.structured_output.compute_hash()
            if candidate.render_output_hash != observed_output_hash:
                errors.append(_error(
                    FINAL_RENDER_OUTPUT_HASH_MISMATCH,
                    "Candidate output hash does not match its structured output.",
                    candidate_id=candidate.candidate_id,
                    section_id=candidate.section_id,
                    entity_type="render_output",
                    entity_id=candidate.candidate_id,
                    expected_value=candidate.render_output_hash,
                    actual_value=observed_output_hash,
                ))

        if input_data is not None and candidate.structured_output is not None:
            errors.extend(_map_render_errors(
                validate_section_render_output(input_data, candidate.structured_output),
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
            ))
            citation_nodes = {citation.citation_id: citation for citation in input_data.citations}
            for index, paragraph in enumerate(candidate.structured_output.paragraphs):
                for citation_id in paragraph.citation_ids:
                    citation = citation_nodes.get(citation_id)
                    if citation is None:
                        continue
                    graph_node = next(
                        (node for node in graph.citations if node.citation_id == citation_id),
                        None,
                    )
                    if graph_node is None or not graph_node.renderable:
                        errors.append(_error(
                            FINAL_CITATION_NOT_RENDERABLE,
                            f"Citation {citation_id} is not currently renderable.",
                            candidate_id=candidate.candidate_id,
                            section_id=candidate.section_id,
                            paragraph_index=index,
                            citation_id=citation_id,
                        ))
            coverage, coverage_errors = _coverage(
                input_data, candidate.structured_output, candidate_id=candidate.candidate_id
            )
            errors.extend(coverage_errors)
        else:
            coverage = {"claims": []}

        status = FINAL_INVALID if errors else FINAL_VALID
        if blocked_prerequisite or any(error.code.startswith("FINAL_UPSTREAM_") or "HASH_MISMATCH" in error.code or error.code in {
            FINAL_CANDIDATE_NOT_PENDING_VALIDATION,
            FINAL_CANDIDATE_TASK_MISMATCH,
            FINAL_CANDIDATE_SECTION_MISMATCH,
            FINAL_STRUCTURED_OUTPUT_INVALID,
        } for error in errors):
            status = FINAL_BLOCKED

        validation_input_hash = compute_validation_input_hash(
            candidate,
            observed_dataset_hash=observed_dataset_hash,
            observed_citation_graph_hash=observed_graph_hash,
            observed_section_plan_hash=observed_plan_hash,
            observed_render_input_hash=observed_input_hash,
            observed_render_output_hash=observed_output_hash,
        )
        validation_result_hash = compute_validation_result_hash(
            validation_input_hash=validation_input_hash,
            status=status,
            errors=errors,
            warnings=warnings,
            coverage=coverage,
        )
        return FinalValidationResult(
            status=status,
            errors=errors,
            warnings=warnings,
            coverage=coverage,
            observed_dataset_hash=observed_dataset_hash,
            observed_citation_graph_hash=observed_graph_hash,
            observed_section_plan_hash=observed_plan_hash,
            observed_render_input_hash=observed_input_hash,
            observed_render_output_hash=observed_output_hash,
            validation_input_hash=validation_input_hash,
            validation_result_hash=validation_result_hash,
        )

    def failed(
        self,
        candidate: ReportRenderCandidate,
        exc: Exception,
    ) -> FinalValidationResult:
        validation_input_hash = compute_validation_input_hash(
            candidate,
            observed_dataset_hash=None,
            observed_citation_graph_hash=None,
            observed_section_plan_hash=None,
            observed_render_input_hash=None,
            observed_render_output_hash=None,
        )
        error = _error(
            FINAL_STRUCTURED_OUTPUT_INVALID,
            f"Final validation failed: {exc}",
            candidate_id=candidate.candidate_id,
            section_id=candidate.section_id,
        )
        result_hash = compute_validation_result_hash(
            validation_input_hash=validation_input_hash,
            status=FINAL_FAILED,
            errors=[error],
            warnings=[],
            coverage={"claims": []},
        )
        return FinalValidationResult(
            status=FINAL_FAILED,
            errors=[error],
            coverage={"claims": []},
            validation_input_hash=validation_input_hash,
            validation_result_hash=result_hash,
            error_message=str(exc),
        )


__all__ = [
    "FINAL_VALIDATION_RULE_VERSION",
    "FINAL_QUEUED",
    "FINAL_RUNNING",
    "FINAL_VALID",
    "FINAL_INVALID",
    "FINAL_BLOCKED",
    "FINAL_FAILED",
    "FinalValidationError",
    "FinalValidationResult",
    "SectionRenderValidation",
    "FinalSectionValidator",
    "ReportRenderCandidateNotFound",
    "compute_validation_input_hash",
    "compute_validation_result_hash",
]
