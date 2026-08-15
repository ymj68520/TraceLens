"""Pure deterministic section planning for the report pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .citation_validation import CitationValidationResult
from .report_dataset import READINESS_REPORT_READY, ReportDataset, ReportDatasetEvent

SECTION_PLAN_VERSION = "1"
SECTION_PREFIX = "SEC-"
SECTION_UPSTREAM_DATASET_BLOCKED = "SECTION_UPSTREAM_DATASET_BLOCKED"
SECTION_UPSTREAM_CITATION_BLOCKED = "SECTION_UPSTREAM_CITATION_BLOCKED"
SECTION_DATASET_HASH_MISMATCH = "SECTION_DATASET_HASH_MISMATCH"
SECTION_CITATION_GRAPH_HASH_MISMATCH = "SECTION_CITATION_GRAPH_HASH_MISMATCH"
SECTION_CLAIM_NOT_IN_GRAPH = "SECTION_CLAIM_NOT_IN_GRAPH"
SECTION_CITATION_NOT_ALLOWED = "SECTION_CITATION_NOT_ALLOWED"
VALIDATION_VALID = "valid"
VALIDATION_BLOCKED = "blocked"

SECTION_TAXONOMY: Tuple[Tuple[str, str], ...] = (
    ("analysis.overview", "案件概述"),
    ("analysis.timeline", "时间线梳理"),
    ("analysis.evidence", "证据分析"),
    ("analysis.findings", "关键发现"),
    ("analysis.conclusion", "结论与建议"),
)


def _section_id(order: int) -> str:
    return f"{SECTION_PREFIX}{order:03d}"


def _citation_number(citation_id: Optional[str]) -> Tuple[int, str]:
    match = re.fullmatch(r"CIT-(\d+)", citation_id or "")
    if match:
        return int(match.group(1)), citation_id or ""
    return (2**63 - 1, citation_id or "")


def _event_sort_key(event: ReportDatasetEvent) -> Tuple[bool, int, str]:
    has_time = event.start_time is not None or event.end_time is not None
    event_time = event.start_time if event.start_time is not None else event.end_time
    return (not has_time, event_time if event_time is not None else 0, event.event_id)


class SectionValidationError(BaseModel):
    code: str
    severity: str = "error"
    entity_type: str
    entity_id: Optional[str] = None
    section_id: Optional[str] = None
    claim_id: Optional[str] = None
    citation_id: Optional[str] = None
    message: str


class ReportSection(BaseModel):
    section_id: str
    section_type: str
    title: str
    order: int
    event_ids: List[str] = Field(default_factory=list)
    claim_ids: List[str] = Field(default_factory=list)
    allowed_citation_ids: List[str] = Field(default_factory=list)
    validation_errors: List[SectionValidationError] = Field(default_factory=list)


class SectionPlanValidation(BaseModel):
    status: str
    errors: List[SectionValidationError] = Field(default_factory=list)
    warnings: List[SectionValidationError] = Field(default_factory=list)


class ReportSectionPlan(BaseModel):
    dataset_hash: str
    citation_graph_hash: str
    section_plan_version: str = SECTION_PLAN_VERSION
    sections: List[ReportSection] = Field(default_factory=list)
    validation: SectionPlanValidation
    section_plan_hash: str

    def canonical_content_dict(self) -> Dict[str, Any]:
        sections = []
        for section in self.sections:
            item = section.model_dump(mode="json", exclude_none=False)
            item["allowed_citation_ids"] = sorted(
                item.get("allowed_citation_ids", []), key=_citation_number
            )
            item["validation_errors"] = _canonical_errors(
                item.get("validation_errors", [])
            )
            sections.append(item)

        validation = self.validation.model_dump(mode="json", exclude_none=False)
        validation["errors"] = _canonical_errors(validation.get("errors", []))
        validation["warnings"] = _canonical_errors(validation.get("warnings", []))
        return {
            "dataset_hash": self.dataset_hash,
            "citation_graph_hash": self.citation_graph_hash,
            "section_plan_version": self.section_plan_version,
            "sections": sorted(
                sections,
                key=lambda section: (section.get("order", 0), section.get("section_id", "")),
            ),
            "validation": validation,
        }

    def canonical_content_json(self) -> str:
        return json.dumps(
            self.canonical_content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_content_json().encode("utf-8")).hexdigest()

    def to_response_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


def _canonical_errors(errors: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = (
        "code",
        "severity",
        "entity_type",
        "entity_id",
        "section_id",
        "claim_id",
        "citation_id",
    )
    projected = [{field: error.get(field) for field in fields} for error in errors]
    return sorted(
        projected,
        key=lambda error: tuple(error.get(field) or "" for field in fields),
    )


def _error_key(error: SectionValidationError) -> Tuple[Any, ...]:
    return (
        error.code,
        error.severity,
        error.entity_type,
        error.entity_id,
        error.section_id,
        error.claim_id,
        error.citation_id,
    )


def _dedupe_errors(errors: Iterable[SectionValidationError]) -> List[SectionValidationError]:
    result: List[SectionValidationError] = []
    seen: set[Tuple[Any, ...]] = set()
    for error in errors:
        key = _error_key(error)
        if key not in seen:
            seen.add(key)
            result.append(error)
    return result


def _event_claim_key(
    event: ReportDatasetEvent, claim_id: str
) -> Tuple[bool, int, str, str]:
    event_key = _event_sort_key(event)
    return (*event_key, claim_id)


class SectionPlanBuilder:
    """Build a deterministic Section Plan from validated report inputs."""

    @staticmethod
    def _error(
        code: str,
        entity_type: str,
        message: str,
        *,
        entity_id: Optional[str] = None,
        section_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        citation_id: Optional[str] = None,
    ) -> SectionValidationError:
        return SectionValidationError(
            code=code,
            entity_type=entity_type,
            entity_id=entity_id,
            section_id=section_id,
            claim_id=claim_id,
            citation_id=citation_id,
            message=message,
        )

    def build(
        self, dataset: ReportDataset, graph: CitationValidationResult
    ) -> ReportSectionPlan:
        errors: List[SectionValidationError] = []
        error_keys: set[Tuple[Any, ...]] = set()

        def add_error(error: SectionValidationError) -> None:
            key = _error_key(error)
            if key not in error_keys:
                error_keys.add(key)
                errors.append(error)

        if dataset.validation.status != VALIDATION_VALID:
            add_error(self._error(
                SECTION_UPSTREAM_DATASET_BLOCKED,
                "dataset",
                "ReportDataset validation is blocked.",
                entity_id=dataset.task_id,
            ))
        if graph.validation.status != VALIDATION_VALID:
            add_error(self._error(
                SECTION_UPSTREAM_CITATION_BLOCKED,
                "citation_graph",
                "Citation Graph validation is blocked.",
                entity_id=graph.citation_graph_hash,
            ))
        if dataset.report_dataset_hash != graph.dataset_hash:
            add_error(self._error(
                SECTION_DATASET_HASH_MISMATCH,
                "dataset",
                "Dataset hash does not match Citation Graph input.",
                entity_id=dataset.task_id,
            ))
        if dataset.report_dataset_hash != dataset.compute_hash():
            add_error(self._error(
                SECTION_DATASET_HASH_MISMATCH,
                "dataset",
                "Dataset hash does not match canonical Dataset content.",
                entity_id=dataset.task_id,
            ))
        if graph.citation_graph_hash != graph.compute_hash():
            add_error(self._error(
                SECTION_CITATION_GRAPH_HASH_MISMATCH,
                "citation_graph",
                "Citation Graph hash does not match canonical graph content.",
                entity_id=graph.citation_graph_hash,
            ))

        graph_claims = {claim.claim_id: claim for claim in graph.claim_citations}
        dataset_events = sorted(dataset.events, key=_event_sort_key)
        dataset_claims = {
            claim.claim_id: (event, claim)
            for event in dataset_events
            for claim in event.claims
        }
        allowed_global = set(graph.allowed_citation_ids)

        sections: List[ReportSection] = []
        for order, (section_type, title) in enumerate(SECTION_TAXONOMY, start=1):
            section_id = _section_id(order)
            section_claims: List[Tuple[ReportDatasetEvent, Any]] = []
            section_errors: List[SectionValidationError] = []
            if not errors:
                for event, claim in dataset_claims.values():
                    if claim.readiness != READINESS_REPORT_READY:
                        continue
                    include = (
                        section_type == "analysis.overview"
                        or (
                            section_type == "analysis.timeline"
                            and (event.start_time is not None or event.end_time is not None)
                        )
                        or (
                            section_type == "analysis.evidence"
                            and any(
                                link.relation in {"supports", "contradicts"}
                                for link in claim.evidence_links
                            )
                        )
                        or (
                            section_type == "analysis.findings"
                            and claim.claim_type in {"fact", "inference"}
                        )
                        or (
                            section_type == "analysis.conclusion"
                            and claim.claim_type in {"inference", "hypothesis"}
                        )
                    )
                    if include:
                        section_claims.append((event, claim))

                section_claims.sort(
                    key=lambda item: _event_claim_key(item[0], item[1].claim_id)
                )
                section_claim_ids = [claim.claim_id for _, claim in section_claims]
                section_event_ids = list(
                    dict.fromkeys(event.event_id for event, _ in section_claims)
                )
                section_citation_ids: set[str] = set()
                for event, claim in section_claims:
                    graph_claim = graph_claims.get(claim.claim_id)
                    if graph_claim is None:
                        section_error = self._error(
                            SECTION_CLAIM_NOT_IN_GRAPH,
                            "claim",
                            f"Claim {claim.claim_id} is absent from Citation Graph.",
                            entity_id=claim.claim_id,
                            section_id=section_id,
                            claim_id=claim.claim_id,
                        )
                        section_errors.append(section_error)
                        add_error(section_error)
                        continue
                    for link in graph_claim.citations:
                        if link.citation_id is None:
                            continue
                        if link.citation_id not in allowed_global:
                            section_error = self._error(
                                SECTION_CITATION_NOT_ALLOWED,
                                "citation",
                                f"Citation {link.citation_id} is not globally allowed.",
                                entity_id=claim.claim_id,
                                section_id=section_id,
                                claim_id=claim.claim_id,
                                citation_id=link.citation_id,
                            )
                            section_errors.append(section_error)
                            add_error(section_error)
                        else:
                            section_citation_ids.add(link.citation_id)
                allowed_ids = sorted(section_citation_ids, key=_citation_number)
            else:
                section_claim_ids = []
                section_event_ids = []
                allowed_ids = []

            sections.append(ReportSection(
                section_id=section_id,
                section_type=section_type,
                title=title,
                order=order,
                event_ids=section_event_ids,
                claim_ids=section_claim_ids,
                allowed_citation_ids=allowed_ids,
                validation_errors=_dedupe_errors(section_errors),
            ))

        validation_status = VALIDATION_BLOCKED if errors else VALIDATION_VALID
        plan = ReportSectionPlan(
            dataset_hash=dataset.report_dataset_hash,
            citation_graph_hash=graph.citation_graph_hash,
            section_plan_version=SECTION_PLAN_VERSION,
            sections=sections,
            validation=SectionPlanValidation(
                status=validation_status,
                errors=errors,
                warnings=[],
            ),
            section_plan_hash="",
        )
        plan.section_plan_hash = plan.compute_hash()
        return plan
