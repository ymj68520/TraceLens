"""Pure Citation Graph validation for the deterministic report dataset."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from .report_dataset import (
    READINESS_BLOCKED,
    READINESS_EXCLUDED,
    READINESS_REPORT_READY,
    ReportDataset,
    ReportDatasetClaim,
    ReportDatasetClaimEvidenceLink,
    ReportDatasetEvidence,
)

CITATION_GRAPH_VERSION = "1"
CITATION_PREFIX = "CIT-"
CITATION_EVIDENCE_NOT_FOUND = "CITATION_EVIDENCE_NOT_FOUND"
CITATION_EVIDENCE_NOT_REPORT_READY = "CITATION_EVIDENCE_NOT_REPORT_READY"
CITATION_SNAPSHOT_MISSING = "CITATION_SNAPSHOT_MISSING"
CITATION_PINNED_ANALYSIS_INVALID = "CITATION_PINNED_ANALYSIS_INVALID"
CLAIM_WITHOUT_RENDERABLE_CITATION = "CLAIM_WITHOUT_RENDERABLE_CITATION"
CITATION_RELATION_INVALID = "CITATION_RELATION_INVALID"
CITATION_DUPLICATE = "CITATION_DUPLICATE"
CITATION_ID_COLLISION = "CITATION_ID_COLLISION"
DATASET_HASH_MISMATCH = "DATASET_HASH_MISMATCH"
UPSTREAM_DATASET_BLOCKED = "UPSTREAM_DATASET_BLOCKED"

VALIDATION_VALID = "valid"
VALIDATION_BLOCKED = "blocked"
VALID_RELATIONS = {"supports", "contradicts"}
VALID_REPORT_STATUSES = {"main", "appendix"}


class CitationValidationError(BaseModel):
    code: str
    severity: str = "error"
    entity_type: str
    entity_id: Optional[str] = None
    citation_id: Optional[str] = None
    claim_id: Optional[str] = None
    evidence_key: Optional[str] = None
    message: str


class CitationLink(BaseModel):
    citation_id: Optional[str] = None
    relation: str
    rationale: Optional[str] = None


class CitationNode(BaseModel):
    citation_id: str
    evidence_key: str
    evidence_type: str
    report_status: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    pinned_analysis: Optional[Dict[str, Any]] = None
    renderable: bool = False
    validation_errors: List[CitationValidationError] = Field(default_factory=list)


class ClaimCitations(BaseModel):
    event_id: str
    event_version_id: Optional[str] = None
    claim_id: str
    claim_type: str
    readiness: str
    citations: List[CitationLink] = Field(default_factory=list)


class CitationValidation(BaseModel):
    status: str
    errors: List[CitationValidationError] = Field(default_factory=list)
    warnings: List[CitationValidationError] = Field(default_factory=list)


class CitationValidationResult(BaseModel):
    dataset_hash: str
    citation_graph_version: str = CITATION_GRAPH_VERSION
    citations: List[CitationNode] = Field(default_factory=list)
    claim_citations: List[ClaimCitations] = Field(default_factory=list)
    renderable_citation_ids: List[str] = Field(default_factory=list)
    allowed_citation_ids: List[str] = Field(default_factory=list)
    validation: CitationValidation
    citation_graph_hash: str

    def canonical_content_dict(self) -> Dict[str, Any]:
        """Return canonical graph content with message-free error fields."""
        citations = []
        for citation in self.citations:
            item = citation.model_dump(mode="json", exclude_none=False)
            item["validation_errors"] = _canonical_errors(
                item.get("validation_errors", [])
            )
            citations.append(item)

        claim_citations = []
        for claim in self.claim_citations:
            item = claim.model_dump(mode="json", exclude_none=False)
            item["citations"] = sorted(
                item.get("citations", []),
                key=lambda link: (
                    link.get("citation_id") or "",
                    link.get("relation") or "",
                    link.get("rationale") or "",
                ),
            )
            claim_citations.append(item)

        validation = self.validation.model_dump(mode="json", exclude_none=False)
        validation["errors"] = _canonical_errors(validation.get("errors", []))
        validation["warnings"] = _canonical_errors(validation.get("warnings", []))
        return {
            "dataset_hash": self.dataset_hash,
            "citation_graph_version": self.citation_graph_version,
            "citations": sorted(
                citations,
                key=lambda citation: (
                    citation.get("evidence_key") or "",
                    citation.get("citation_id") or "",
                ),
            ),
            "claim_citations": sorted(
                claim_citations,
                key=lambda claim: (
                    claim.get("event_id") or "",
                    claim.get("claim_id") or "",
                ),
            ),
            "renderable_citation_ids": sorted(self.renderable_citation_ids),
            "allowed_citation_ids": sorted(self.allowed_citation_ids),
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
        "citation_id",
        "claim_id",
        "evidence_key",
    )
    projected = [{field: error.get(field) for field in fields} for error in errors]
    return sorted(
        projected,
        key=lambda error: tuple(error.get(field) or "" for field in fields),
    )


def _error_key(error: CitationValidationError) -> tuple[Any, ...]:
    return (
        error.code,
        error.severity,
        error.entity_type,
        error.entity_id,
        error.citation_id,
        error.claim_id,
        error.evidence_key,
    )


def _canonical_evidence(evidence: ReportDatasetEvidence) -> str:
    return json.dumps(
        evidence.model_dump(mode="json", exclude_none=False),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class CitationGraphBuilder:
    """Build a deterministic citation graph from an immutable ReportDataset."""

    @staticmethod
    def _citation_id(index: int) -> str:
        return f"{CITATION_PREFIX}{index:03d}"

    @staticmethod
    def _error(
        code: str,
        entity_type: str,
        message: str,
        *,
        entity_id: Optional[str] = None,
        citation_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        evidence_key: Optional[str] = None,
    ) -> CitationValidationError:
        return CitationValidationError(
            code=code,
            entity_type=entity_type,
            entity_id=entity_id,
            citation_id=citation_id,
            claim_id=claim_id,
            evidence_key=evidence_key,
            message=message,
        )

    def build(self, dataset: ReportDataset) -> CitationValidationResult:
        dataset_hash = dataset.report_dataset_hash
        errors: List[CitationValidationError] = []
        error_keys: set[tuple[Any, ...]] = set()

        def add_error(error: CitationValidationError) -> None:
            key = _error_key(error)
            if key not in error_keys:
                error_keys.add(key)
                errors.append(error)

        hash_matches = dataset.report_dataset_hash == dataset.compute_hash()
        if not hash_matches:
            add_error(self._error(
                DATASET_HASH_MISMATCH,
                "dataset",
                "ReportDataset hash does not match its canonical content.",
                entity_id=dataset.task_id,
            ))
        if dataset.validation.status == VALIDATION_BLOCKED:
            add_error(self._error(
                UPSTREAM_DATASET_BLOCKED,
                "dataset",
                "ReportDataset validation is blocked.",
                entity_id=dataset.task_id,
            ))
        for dataset_error in dataset.validation.errors:
            add_error(self._error(
                dataset_error.code,
                dataset_error.entity_type,
                dataset_error.message,
                entity_id=dataset_error.entity_id,
                claim_id=(
                    dataset_error.entity_id
                    if dataset_error.entity_type == "claim"
                    else None
                ),
                evidence_key=dataset_error.evidence_key,
            ))

        groups: Dict[str, List[ReportDatasetEvidence]] = {}
        for evidence in dataset.report_evidence:
            groups.setdefault(evidence.evidence_key, []).append(evidence)

        citation_by_key: Dict[str, CitationNode] = {}
        citation_by_id: Dict[str, CitationNode] = {}
        for index, key in enumerate(sorted(groups), start=1):
            citation_id = self._citation_id(index)
            representative = min(groups[key], key=_canonical_evidence)
            node_errors: List[CitationValidationError] = []

            if citation_id in citation_by_id:
                node_errors.append(self._error(
                    CITATION_ID_COLLISION,
                    "citation",
                    f"Citation ID {citation_id} was generated more than once.",
                    entity_id=key,
                    citation_id=citation_id,
                    evidence_key=key,
                ))
            if len(groups[key]) > 1:
                node_errors.append(self._error(
                    CITATION_DUPLICATE,
                    "citation",
                    f"ReportDataset contains duplicate evidence rows for {key}.",
                    entity_id=key,
                    citation_id=citation_id,
                    evidence_key=key,
                ))

            report_status = representative.report_status
            if not key or report_status not in VALID_REPORT_STATUSES:
                node_errors.append(self._error(
                    CITATION_EVIDENCE_NOT_REPORT_READY,
                    "citation",
                    "Evidence is not in a renderable Report Evidence state.",
                    entity_id=key,
                    citation_id=citation_id,
                    evidence_key=key,
                ))

            snapshot = representative.snapshot
            if not snapshot or snapshot.get("evidence_key") != key:
                node_errors.append(self._error(
                    CITATION_SNAPSHOT_MISSING,
                    "citation",
                    "Citation evidence does not have a matching immutable snapshot.",
                    entity_id=key,
                    citation_id=citation_id,
                    evidence_key=key,
                ))

            analysis_id = representative.analysis_id
            analysis = representative.pinned_analysis
            if analysis_id is not None and (
                not analysis
                or analysis.get("analysis_id") != analysis_id
                or analysis.get("status") != "accepted"
                or analysis.get("evidence_key") != key
                or analysis.get("evidence_type") != representative.evidence_type
            ):
                node_errors.append(self._error(
                    CITATION_PINNED_ANALYSIS_INVALID,
                    "citation",
                    "Citation pinned Analysis is missing or does not match its Evidence.",
                    entity_id=key,
                    citation_id=citation_id,
                    evidence_key=key,
                ))

            node_errors = _dedupe_errors(node_errors)
            node = CitationNode(
                citation_id=citation_id,
                evidence_key=key,
                evidence_type=representative.evidence_type,
                report_status=report_status,
                snapshot=snapshot,
                pinned_analysis=analysis,
                renderable=not node_errors,
                validation_errors=node_errors,
            )
            citation_by_key[key] = node
            if citation_id in citation_by_id:
                collision = self._error(
                    CITATION_ID_COLLISION,
                    "citation",
                    f"Citation ID {citation_id} was generated more than once.",
                    entity_id=key,
                    citation_id=citation_id,
                    evidence_key=key,
                )
                add_error(collision)
                node.renderable = False
            else:
                citation_by_id[citation_id] = node
            for node_error in node_errors:
                add_error(node_error)

        claim_citations: List[ClaimCitations] = []
        referenced_renderable_ids: set[str] = set()
        for event in dataset.events:
            for claim in event.claims:
                links: List[CitationLink] = []
                claim_renderable_ids: List[str] = []
                seen_ids: set[str] = set()
                claim_errors: List[CitationValidationError] = []
                if claim.readiness == READINESS_REPORT_READY:
                    for link in claim.evidence_links:
                        citation = citation_by_key.get(link.evidence_key)
                        citation_id = citation.citation_id if citation else None
                        links.append(CitationLink(
                            citation_id=citation_id,
                            relation=link.relation,
                            rationale=link.rationale,
                        ))
                        if link.relation not in VALID_RELATIONS:
                            claim_errors.append(self._error(
                                CITATION_RELATION_INVALID,
                                "claim",
                                f"Claim {claim.claim_id} has invalid citation relation.",
                                entity_id=claim.claim_id,
                                claim_id=claim.claim_id,
                                citation_id=citation_id,
                                evidence_key=link.evidence_key,
                            ))
                        if citation is None:
                            claim_errors.append(self._error(
                                CITATION_EVIDENCE_NOT_FOUND,
                                "claim",
                                f"Claim {claim.claim_id} cites unknown Evidence.",
                                entity_id=claim.claim_id,
                                claim_id=claim.claim_id,
                                evidence_key=link.evidence_key,
                            ))
                        else:
                            if citation_id in seen_ids:
                                claim_errors.append(self._error(
                                    CITATION_DUPLICATE,
                                    "claim",
                                    f"Claim {claim.claim_id} cites {citation_id} more than once.",
                                    entity_id=claim.claim_id,
                                    claim_id=claim.claim_id,
                                    citation_id=citation_id,
                                    evidence_key=link.evidence_key,
                                ))
                            if citation_id:
                                seen_ids.add(citation_id)
                            if not citation.renderable:
                                claim_errors.append(self._error(
                                    CITATION_EVIDENCE_NOT_REPORT_READY,
                                    "claim",
                                    f"Citation {citation_id} is not renderable.",
                                    entity_id=claim.claim_id,
                                    claim_id=claim.claim_id,
                                    citation_id=citation_id,
                                    evidence_key=link.evidence_key,
                                ))
                            elif link.relation in VALID_RELATIONS and citation_id:
                                claim_renderable_ids.append(citation_id)
                    if not claim_renderable_ids:
                        claim_errors.append(self._error(
                            CLAIM_WITHOUT_RENDERABLE_CITATION,
                            "claim",
                            f"Claim {claim.claim_id} has no renderable citation.",
                            entity_id=claim.claim_id,
                            claim_id=claim.claim_id,
                        ))
                    referenced_renderable_ids.update(claim_renderable_ids)
                    for claim_error in claim_errors:
                        add_error(claim_error)
                else:
                    links = [
                        CitationLink(
                            citation_id=(
                                citation_by_key[link.evidence_key].citation_id
                                if link.evidence_key in citation_by_key
                                else None
                            ),
                            relation=link.relation,
                            rationale=link.rationale,
                        )
                        for link in claim.evidence_links
                    ]
                claim_citations.append(ClaimCitations(
                    event_id=event.event_id,
                    event_version_id=event.event_version_id or claim.event_version_id,
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    readiness=claim.readiness,
                    citations=links,
                ))

        validation_status = (
            VALIDATION_BLOCKED if errors else VALIDATION_VALID
        )
        renderable_ids = sorted(
            citation.citation_id
            for citation in citation_by_key.values()
            if citation.renderable
        )
        allowed_ids = sorted(referenced_renderable_ids)
        if validation_status == VALIDATION_BLOCKED:
            allowed_ids = []
        result = CitationValidationResult(
            dataset_hash=dataset_hash,
            citation_graph_version=CITATION_GRAPH_VERSION,
            citations=sorted(
                citation_by_key.values(),
                key=lambda citation: (citation.evidence_key, citation.citation_id),
            ),
            claim_citations=claim_citations,
            renderable_citation_ids=renderable_ids,
            allowed_citation_ids=allowed_ids,
            validation=CitationValidation(
                status=validation_status,
                errors=errors,
                warnings=[],
            ),
            citation_graph_hash="",
        )
        result.citation_graph_hash = result.compute_hash()
        return result


def _dedupe_errors(errors: Iterable[CitationValidationError]) -> List[CitationValidationError]:
    result: List[CitationValidationError] = []
    seen: set[tuple[Any, ...]] = set()
    for error in errors:
        key = _error_key(error)
        if key not in seen:
            seen.add(key)
            result.append(error)
    return result
