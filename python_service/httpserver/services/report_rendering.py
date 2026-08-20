"""Constrained LLM rendering for deterministic report sections."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .citation_validation import CitationValidationResult
from .report_dataset import ReportDataset
from .section_planning import ReportSectionPlan

REPORT_RENDER_PROMPT_VERSION = "report-render-v1"

RENDER_SECTION_ID_MISMATCH = "RENDER_SECTION_ID_MISMATCH"
RENDER_CLAIM_NOT_ALLOWED = "RENDER_CLAIM_NOT_ALLOWED"
RENDER_CITATION_NOT_ALLOWED = "RENDER_CITATION_NOT_ALLOWED"
RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM = "RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM"
RENDER_USED_CLAIMS_MISMATCH = "RENDER_USED_CLAIMS_MISMATCH"
RENDER_DUPLICATE_CLAIM_ID = "RENDER_DUPLICATE_CLAIM_ID"
RENDER_DUPLICATE_CITATION_ID = "RENDER_DUPLICATE_CITATION_ID"
RENDER_EMPTY_PARAGRAPH = "RENDER_EMPTY_PARAGRAPH"
RENDER_OUTPUT_SCHEMA_INVALID = "RENDER_OUTPUT_SCHEMA_INVALID"

VALIDATION_VALID = "valid"


class SectionRenderBlocked(RuntimeError):
    """Raised when a section cannot cross the 4D trust boundary."""

    def __init__(self, errors: Sequence[Dict[str, Any]]):
        self.errors = [dict(error) for error in errors]
        super().__init__("Section render is blocked by upstream validation.")


class RenderValidationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str = "error"
    entity_type: str
    entity_id: Optional[str] = None
    section_id: Optional[str] = None
    claim_id: Optional[str] = None
    citation_id: Optional[str] = None
    message: str


class SectionRenderClaimCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    relation: str
    rationale: Optional[str] = None


class SectionRenderClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_type: str
    claim_text: str
    citations: List[SectionRenderClaimCitation] = Field(default_factory=list)


class SectionRenderCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    evidence_type: str
    report_status: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    pinned_analysis: Optional[Dict[str, Any]] = None


class SectionRenderInput(BaseModel):
    """Minimal, section-scoped data allowed in the render prompt."""

    model_config = ConfigDict(extra="forbid")

    dataset_hash: str
    citation_graph_hash: str
    section_plan_hash: str
    prompt_version: str = REPORT_RENDER_PROMPT_VERSION
    section_id: str
    section_type: str
    title: str
    claim_ids: List[str] = Field(default_factory=list)
    allowed_citation_ids: List[str] = Field(default_factory=list)
    claims: List[SectionRenderClaim] = Field(default_factory=list)
    citations: List[SectionRenderCitation] = Field(default_factory=list)

    def canonical_content_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)

    def canonical_content_json(self) -> str:
        return json.dumps(
            self.canonical_content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_hash(self) -> str:
        payload = {
            "section_render_input": self.canonical_content_dict(),
            "prompt_version": self.prompt_version,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class SectionRenderParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    claim_ids: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)


class SectionRenderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    used_claim_ids: List[str] = Field(default_factory=list)
    paragraphs: List[SectionRenderParagraph] = Field(default_factory=list)

    def canonical_content_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)

    def canonical_content_json(self) -> str:
        return json.dumps(
            self.canonical_content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_content_json().encode("utf-8")).hexdigest()


def _error(
    code: str,
    message: str,
    *,
    entity_type: str = "render_output",
    entity_id: Optional[str] = None,
    section_id: Optional[str] = None,
    claim_id: Optional[str] = None,
    citation_id: Optional[str] = None,
) -> RenderValidationError:
    return RenderValidationError(
        code=code,
        entity_type=entity_type,
        entity_id=entity_id,
        section_id=section_id,
        claim_id=claim_id,
        citation_id=citation_id,
        message=message,
    )


def _duplicates(values: Iterable[str]) -> Set[str]:
    seen: Set[str] = set()
    duplicates: Set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_section_render_output(
    input_data: SectionRenderInput,
    output: SectionRenderOutput,
) -> List[RenderValidationError]:
    """Validate output against section and Claim-edge-scoped whitelists."""
    errors: List[RenderValidationError] = []
    allowed_claims = set(input_data.claim_ids)
    allowed_citations = set(input_data.allowed_citation_ids)
    claim_by_id = {claim.claim_id: claim for claim in input_data.claims}

    if output.section_id != input_data.section_id:
        errors.append(_error(
            RENDER_SECTION_ID_MISMATCH,
            "Rendered section does not match the requested section.",
            section_id=output.section_id,
            entity_id=output.section_id,
        ))

    for claim_id in _duplicates(input_data.claim_ids):
        errors.append(_error(
            RENDER_DUPLICATE_CLAIM_ID,
            f"Claim {claim_id} appears more than once in the input whitelist.",
            entity_type="render_input",
            claim_id=claim_id,
            section_id=input_data.section_id,
        ))
    for citation_id in _duplicates(input_data.allowed_citation_ids):
        errors.append(_error(
            RENDER_DUPLICATE_CITATION_ID,
            f"Citation {citation_id} appears more than once in the input whitelist.",
            entity_type="render_input",
            citation_id=citation_id,
            section_id=input_data.section_id,
        ))

    for claim_id in _duplicates(output.used_claim_ids):
        errors.append(_error(
            RENDER_DUPLICATE_CLAIM_ID,
            f"Claim {claim_id} appears more than once in used_claim_ids.",
            claim_id=claim_id,
            section_id=input_data.section_id,
        ))
    used_union: Set[str] = set()
    used_order: List[str] = []
    for index, paragraph in enumerate(output.paragraphs):
        paragraph_id = f"paragraph-{index + 1}"
        if not paragraph.text or not paragraph.text.strip():
            errors.append(_error(
                RENDER_EMPTY_PARAGRAPH,
                "Rendered paragraph text must be non-empty.",
                entity_id=paragraph_id,
                section_id=input_data.section_id,
            ))
        for claim_id in _duplicates(paragraph.claim_ids):
            errors.append(_error(
                RENDER_DUPLICATE_CLAIM_ID,
                f"Claim {claim_id} appears more than once in a paragraph.",
                entity_id=paragraph_id,
                claim_id=claim_id,
                section_id=input_data.section_id,
            ))
        for citation_id in _duplicates(paragraph.citation_ids):
            errors.append(_error(
                RENDER_DUPLICATE_CITATION_ID,
                f"Citation {citation_id} appears more than once in a paragraph.",
                entity_id=paragraph_id,
                citation_id=citation_id,
                section_id=input_data.section_id,
            ))
        for claim_id in paragraph.claim_ids:
            if claim_id not in used_union:
                used_order.append(claim_id)
            used_union.add(claim_id)
            if claim_id not in allowed_claims:
                errors.append(_error(
                    RENDER_CLAIM_NOT_ALLOWED,
                    f"Claim {claim_id} is not allowed in this section.",
                    entity_id=paragraph_id,
                    claim_id=claim_id,
                    section_id=input_data.section_id,
                ))
        paragraph_allowed_citations: Set[str] = set()
        for claim_id in paragraph.claim_ids:
            claim = claim_by_id.get(claim_id)
            if claim:
                paragraph_allowed_citations.update(
                    citation.citation_id for citation in claim.citations
                )
        for citation_id in paragraph.citation_ids:
            if citation_id not in allowed_citations:
                errors.append(_error(
                    RENDER_CITATION_NOT_ALLOWED,
                    f"Citation {citation_id} is not allowed in this section.",
                    entity_id=paragraph_id,
                    citation_id=citation_id,
                    section_id=input_data.section_id,
                ))
            elif citation_id not in paragraph_allowed_citations:
                errors.append(_error(
                    RENDER_CITATION_NOT_ALLOWED_FOR_CLAIM,
                    f"Citation {citation_id} is not linked to a Claim in this paragraph.",
                    entity_id=paragraph_id,
                    citation_id=citation_id,
                    section_id=input_data.section_id,
                ))

    for claim_id in output.used_claim_ids:
        if claim_id not in allowed_claims:
            errors.append(_error(
                RENDER_CLAIM_NOT_ALLOWED,
                f"Claim {claim_id} is not allowed in this section.",
                claim_id=claim_id,
                section_id=input_data.section_id,
            ))
    if output.used_claim_ids != used_order or set(output.used_claim_ids) != used_union:
        errors.append(_error(
            RENDER_USED_CLAIMS_MISMATCH,
            "used_claim_ids must equal the union of paragraph claim_ids.",
            section_id=input_data.section_id,
        ))

    return errors


def build_section_render_input(
    dataset: ReportDataset,
    graph: CitationValidationResult,
    plan: ReportSectionPlan,
    section_id: str,
    *,
    prompt_version: str = REPORT_RENDER_PROMPT_VERSION,
) -> SectionRenderInput:
    """Project one valid Section Plan section into the minimal render input."""
    errors: List[Dict[str, Any]] = []
    if dataset.validation.status != VALIDATION_VALID:
        errors.extend(error.model_dump(mode="json") for error in dataset.validation.errors)
        if not dataset.validation.errors:
            errors.append({
                "code": "SECTION_UPSTREAM_DATASET_BLOCKED",
                "entity_type": "dataset",
            })
    if graph.validation.status != VALIDATION_VALID:
        errors.extend(error.model_dump(mode="json") for error in graph.validation.errors)
        if not graph.validation.errors:
            errors.append({
                "code": "SECTION_UPSTREAM_CITATION_BLOCKED",
                "entity_type": "citation_graph",
            })
    if plan.validation.status != VALIDATION_VALID:
        errors.extend(error.model_dump(mode="json") for error in plan.validation.errors)
        if not plan.validation.errors:
            errors.append({
                "code": "SECTION_UPSTREAM_SECTION_PLAN_BLOCKED",
                "entity_type": "section_plan",
            })
    if dataset.report_dataset_hash != dataset.compute_hash():
        errors.append({"code": "SECTION_DATASET_HASH_MISMATCH", "entity_type": "dataset"})
    if graph.citation_graph_hash != graph.compute_hash():
        errors.append({"code": "SECTION_CITATION_GRAPH_HASH_MISMATCH", "entity_type": "citation_graph"})
    if graph.dataset_hash != dataset.report_dataset_hash:
        errors.append({"code": "SECTION_DATASET_HASH_MISMATCH", "entity_type": "dataset"})
    if plan.section_plan_hash != plan.compute_hash():
        errors.append({"code": "SECTION_PLAN_HASH_MISMATCH", "entity_type": "section_plan"})
    if plan.dataset_hash != dataset.report_dataset_hash:
        errors.append({"code": "SECTION_DATASET_HASH_MISMATCH", "entity_type": "dataset"})
    if plan.citation_graph_hash != graph.citation_graph_hash:
        errors.append({"code": "SECTION_CITATION_GRAPH_HASH_MISMATCH", "entity_type": "citation_graph"})
    if errors:
        raise SectionRenderBlocked(errors)

    section = next((item for item in plan.sections if item.section_id == section_id), None)
    if section is None:
        raise KeyError(section_id)
    if section.validation_errors:
        raise SectionRenderBlocked([
            error.model_dump(mode="json") for error in section.validation_errors
        ])

    dataset_claims = {
        claim.claim_id: claim
        for event in dataset.events
        for claim in event.claims
    }
    graph_claims = {claim.claim_id: claim for claim in graph.claim_citations}
    citation_nodes = {citation.citation_id: citation for citation in graph.citations}
    render_claims: List[SectionRenderClaim] = []
    for claim_id in section.claim_ids:
        dataset_claim = dataset_claims.get(claim_id)
        graph_claim = graph_claims.get(claim_id)
        if dataset_claim is None or graph_claim is None:
            raise SectionRenderBlocked([{
                "code": "SECTION_CLAIM_NOT_IN_GRAPH",
                "entity_type": "claim",
                "claim_id": claim_id,
            }])
        section_citation_ids = set(section.allowed_citation_ids)
        linked_ids = {
            link.citation_id
            for link in graph_claim.citations
            if link.citation_id is not None
        }
        if not linked_ids.issubset(set(graph.allowed_citation_ids)):
            raise SectionRenderBlocked([{
                "code": "SECTION_CITATION_NOT_ALLOWED",
                "entity_type": "citation",
                "claim_id": claim_id,
                "section_id": section_id,
            }])
        if not linked_ids.intersection(section_citation_ids) == linked_ids:
            raise SectionRenderBlocked([{
                "code": "SECTION_CITATION_NOT_ALLOWED",
                "entity_type": "citation",
                "claim_id": claim_id,
                "section_id": section_id,
            }])
        render_claims.append(SectionRenderClaim(
            claim_id=dataset_claim.claim_id,
            claim_type=dataset_claim.claim_type,
            claim_text=dataset_claim.claim_text,
            citations=[SectionRenderClaimCitation(
                citation_id=link.citation_id,
                relation=link.relation,
                rationale=link.rationale,
            ) for link in graph_claim.citations if link.citation_id is not None],
        ))

    render_citations: List[SectionRenderCitation] = []
    for citation_id in section.allowed_citation_ids:
        citation = citation_nodes.get(citation_id)
        if citation is None:
            raise SectionRenderBlocked([{
                "code": "SECTION_CITATION_NOT_ALLOWED",
                "entity_type": "citation",
                "citation_id": citation_id,
                "section_id": section_id,
            }])
        if not citation.renderable or citation_id not in graph.allowed_citation_ids:
            raise SectionRenderBlocked([{
                "code": "SECTION_CITATION_NOT_ALLOWED",
                "entity_type": "citation",
                "citation_id": citation_id,
                "section_id": section_id,
            }])
        render_citations.append(SectionRenderCitation(
            citation_id=citation.citation_id,
            evidence_type=citation.evidence_type,
            report_status=citation.report_status,
            snapshot=citation.snapshot,
            pinned_analysis=citation.pinned_analysis,
        ))

    return SectionRenderInput(
        dataset_hash=dataset.report_dataset_hash,
        citation_graph_hash=graph.citation_graph_hash,
        section_plan_hash=plan.section_plan_hash,
        prompt_version=prompt_version,
        section_id=section.section_id,
        section_type=section.section_type,
        title=section.title,
        claim_ids=list(section.claim_ids),
        allowed_citation_ids=list(section.allowed_citation_ids),
        claims=render_claims,
        citations=render_citations,
    )


REPORT_RENDER_SYSTEM_PROMPT = """You are a constrained forensic report section renderer.
Use only the claims and citation IDs in the supplied SectionRenderInput.
Do not select evidence, invent claims, invent citation IDs, change the section,
or assess credibility. Return one JSON object only with section_id,
used_claim_ids, and paragraphs. Each paragraph must contain text, claim_ids,
and citation_ids. Do not return Markdown or explanatory text."""


def _render_user_prompt(input_data: SectionRenderInput) -> str:
    payload = json.dumps(
        input_data.canonical_content_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "Render the requested section from this exact input. Preserve factual "
        "boundaries and cite only claim-linked citation IDs.\n"
        f"SectionRenderInput JSON:\n{payload}"
    )


class ConstrainedSectionRenderer:
    """Call the existing LLM service and return a structured 4D result."""

    def __init__(self, llm_service: Any):
        self._llm_service = llm_service

    async def render(
        self, input_data: SectionRenderInput
    ) -> Dict[str, Any]:
        try:
            result = await self._llm_service.analyze(
                content=input_data.canonical_content_json(),
                model_type="text",
                prompt=_render_user_prompt(input_data),
                system_prompt=REPORT_RENDER_SYSTEM_PROMPT,
            )
            analysis = result.get("analysis") if isinstance(result, dict) else None
            raw_output = (
                analysis.get("description", "")
                if isinstance(analysis, dict)
                else str(analysis or result or "")
            )
            model = result.get("model") if isinstance(result, dict) else None
        except Exception as exc:
            return {
                "status": "failed",
                "raw_llm_output": None,
                "model": None,
                "validation_errors": [],
                "error_message": str(exc),
            }

        try:
            from .investigation_service import extract_json_payload

            payload = extract_json_payload(raw_output)
            output = SectionRenderOutput.model_validate_json(payload)
        except Exception as exc:
            error = _error(
                RENDER_OUTPUT_SCHEMA_INVALID,
                f"LLM output is not valid SectionRenderOutput: {exc}",
                section_id=input_data.section_id,
            )
            return {
                "status": "invalid",
                "raw_llm_output": raw_output,
                "model": model,
                "output": None,
                "validation_errors": [error],
                "error_message": None,
            }

        validation_errors = validate_section_render_output(input_data, output)
        if validation_errors:
            return {
                "status": "invalid",
                "raw_llm_output": raw_output,
                "model": model,
                "output": output,
                "validation_errors": validation_errors,
                "error_message": None,
            }
        return {
            "status": "render_pending_validation",
            "raw_llm_output": raw_output,
            "model": model,
            "output": output,
            "validation_errors": [],
            "error_message": None,
        }
