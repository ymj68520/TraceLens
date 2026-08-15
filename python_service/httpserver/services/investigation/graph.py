"""Read-only Investigation Graph composition service (Phase C8b).

Composes the derived overlay (immutable investigation.db rows via
``InvestigationGraphReader``) with the Base KG (``GraphitiService
.get_graph_data``) for one GET.  The error asymmetry is frozen: Base KG
failure degrades gracefully (``base_graph_available=false`` + fixed warning,
HTTP 200) while Investigation store failure fails closed
(``EvidenceStoreError`` -> HTTP 503).  G9: Base KG entities and Investigation
Evidence nodes are never merged, even when display names match.  G8: no
Event->Claim edge is synthesized.  B4: ``max_base_nodes`` bounds only the
Base KG read; the overlay is always complete.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from ..evidence.exceptions import EvidenceNotFoundError
from .graph_reader import InvestigationGraphReader, OverlayReadResult
from .models import (
    InvestigationGraphLink,
    InvestigationGraphNode,
    InvestigationGraphResponse,
)
from .paths import investigation_db_path_for_task

BASE_GRAPH_UNAVAILABLE_WARNING = "base_graph_unavailable"

# Renderer-facing labels.  The KnowledgeGraph page's existing "Event" color
# belongs to Base KG nodes, so overlay namespaces get distinct labels (C8c
# will color them; C8b only fixes the strings).
_EVENT_LABEL = "InvestigationEvent"
_EVIDENCE_LABEL = "Evidence"
_ANALYSIS_LABEL = "Analysis"
_CLAIM_LABEL = "Claim"

_EVENT_EVIDENCE_LABEL = "LINKS_EVIDENCE"
_ANALYSIS_EVIDENCE_LABEL = "ANALYZES_EVIDENCE"
_ANALYSIS_CLAIM_LABEL = "CONTAINS_CLAIM"
# Neutral semantics: a persisted valid ref does not mean the evidence
# semantically proves the claim (G6 docstring in models.py).
_CLAIM_EVIDENCE_LABEL = "REFERENCES_EVIDENCE"


def _base_nodes(rows: list[dict]) -> list[InvestigationGraphNode]:
    result = []
    for row in rows:
        node_id = row.get("id")
        if not node_id:
            continue
        result.append(InvestigationGraphNode(
            id=node_id,
            name=row.get("name") or node_id,
            label=row.get("label") or "Entity",
            summary=row.get("summary") or None,
            source="base_kg",
        ))
    return result


def _base_links(rows: list[dict]) -> list[InvestigationGraphLink]:
    result = []
    for row in rows:
        source, target = row.get("source"), row.get("target")
        if not source or not target:
            continue
        label = row.get("label") or "RELATES_TO"
        result.append(InvestigationGraphLink(
            # Base links carry no persisted edge id; derive one from the
            # (source, relation, target) triple the Base query returns.
            id=f"base:{source}:{label}:{target}",
            source=source,
            target=target,
            label=label,
            kind="base_relation",
        ))
    return result


def _project_overlay(
    overlay: OverlayReadResult,
) -> tuple[list[InvestigationGraphNode], list[InvestigationGraphLink]]:
    nodes: list[InvestigationGraphNode] = []
    links: list[InvestigationGraphLink] = []
    seen_nodes: set[str] = set()
    seen_links: set[str] = set()

    def add_node(node: InvestigationGraphNode) -> None:
        if node.id not in seen_nodes:
            seen_nodes.add(node.id)
            nodes.append(node)

    def add_link(link: InvestigationGraphLink) -> None:
        if link.id not in seen_links:
            seen_links.add(link.id)
            links.append(link)

    # Evidence is the anchor (canonical identity, G12).  The node set is the
    # union of event links, selected analysis primary keys, and selected
    # claims' persisted refs -- deduplicated by canonical evidence_key.
    evidence_keys: dict[str, None] = {}
    for link in overlay.event_links:
        evidence_keys.setdefault(link.evidence_key)
    for selection in overlay.selections:
        evidence_keys.setdefault(selection.evidence_key)
    for claim in overlay.claims:
        for ref in claim.evidence_refs:
            evidence_keys.setdefault(ref)

    for key in evidence_keys:
        provenance: dict = {"evidence_key": key}
        if key in overlay.evidence_types:
            provenance["evidence_type"] = overlay.evidence_types[key]
        add_node(InvestigationGraphNode(
            id=f"evidence:{key}",
            name=key,
            label=_EVIDENCE_LABEL,
            source="investigation",
            # Evidence is real system evidence; it never inherits an
            # Analysis review state.
            provenance=provenance,
        ))

    # Events always appear, including those with no Evidence link yet.
    for event in overlay.events:
        add_node(InvestigationGraphNode(
            id=f"event:{event.event_id}",
            name=event.title or event.event_id,
            label=_EVENT_LABEL,
            summary=event.summary,
            source="investigation",
            provenance={
                "event_id": event.event_id,
                "version": event.current_version,
            },
        ))

    selected_confirmed = {
        selection.analysis_id: selection.review_state == "accepted"
        for selection in overlay.selections
    }
    for selection in overlay.selections:
        add_node(InvestigationGraphNode(
            id=f"analysis:{selection.analysis_id}",
            name=f"Analysis v{selection.version} - {selection.evidence_key}",
            label=_ANALYSIS_LABEL,
            summary=selection.summary,
            source="investigation",
            confirmed=selection.review_state == "accepted",
            provenance={
                "analysis_id": selection.analysis_id,
                "evidence_key": selection.evidence_key,
                "version": selection.version,
                "review_state": selection.review_state,
            },
        ))
        # Without this edge a claims=[] accepted Analysis would be orphaned.
        add_link(InvestigationGraphLink(
            id=f"analysis_evidence:{selection.analysis_id}:{selection.evidence_key}",
            source=f"analysis:{selection.analysis_id}",
            target=f"evidence:{selection.evidence_key}",
            label=_ANALYSIS_EVIDENCE_LABEL,
            kind="analysis_evidence",
            provenance={
                "analysis_id": selection.analysis_id,
                "evidence_key": selection.evidence_key,
            },
        ))

    for claim in overlay.claims:
        confirmed = selected_confirmed.get(claim.analysis_id)
        add_node(InvestigationGraphNode(
            id=f"claim:{claim.claim_id}",
            name=claim.claim_text,
            label=_CLAIM_LABEL,
            source="investigation",
            # Claims inherit the confirmation context of their Analysis.
            confirmed=confirmed,
            provenance={
                "claim_id": claim.claim_id,
                "analysis_id": claim.analysis_id,
                "claim_type": claim.claim_type.value,
                "grounding_status": claim.grounding_status.value,
            },
        ))
        add_link(InvestigationGraphLink(
            id=f"analysis_claim:{claim.analysis_id}:{claim.claim_id}",
            source=f"analysis:{claim.analysis_id}",
            target=f"claim:{claim.claim_id}",
            label=_ANALYSIS_CLAIM_LABEL,
            kind="analysis_claim",
            provenance={
                "analysis_id": claim.analysis_id,
                "claim_id": claim.claim_id,
            },
        ))
        for ref in claim.evidence_refs:
            add_link(InvestigationGraphLink(
                id=f"claim_evidence:{claim.claim_id}:{ref}",
                source=f"claim:{claim.claim_id}",
                target=f"evidence:{ref}",
                label=_CLAIM_EVIDENCE_LABEL,
                kind="claim_evidence",
                provenance={
                    "claim_id": claim.claim_id,
                    "evidence_key": ref,
                },
            ))

    for link in overlay.event_links:
        add_link(InvestigationGraphLink(
            id=f"event_evidence:{link.event_id}:{link.evidence_key}",
            source=f"event:{link.event_id}",
            target=f"evidence:{link.evidence_key}",
            label=_EVENT_EVIDENCE_LABEL,
            kind="event_evidence",
            provenance={
                "event_id": link.event_id,
                "evidence_key": link.evidence_key,
            },
        ))

    return nodes, links


class InvestigationGraphService:
    """Compose the Base KG with the derived Investigation Overlay (C8b)."""

    def __init__(self, cpp_backend, base_graph_provider: Callable[[], object]):
        self._cpp_backend = cpp_backend
        self._base_graph_provider = base_graph_provider

    async def get_graph(
        self, task_id: str, *, max_base_nodes: int = 200
    ) -> InvestigationGraphResponse:
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        db_path = investigation_db_path_for_task(task)

        # B1/B2: a task without an investigation.db yet yields an empty
        # overlay; the GET never creates or migrates the store.
        if db_path.exists():
            overlay = await asyncio.to_thread(
                InvestigationGraphReader(db_path, task_id).read
            )
        else:
            overlay = OverlayReadResult()

        warnings: list[str] = []
        base_rows: list[dict] = []
        base_link_rows: list[dict] = []
        try:
            graphiti = self._base_graph_provider()
            base_rows, base_link_rows = await graphiti.get_graph_data(
                task_id, max_base_nodes
            )
            base_graph_available = True
        except Exception:
            # G11: a Base KG failure never fails the Investigation graph and
            # never leaks backend details -- only the fixed warning token.
            base_graph_available = False
            warnings.append(BASE_GRAPH_UNAVAILABLE_WARNING)

        overlay_nodes, overlay_links = _project_overlay(overlay)
        return InvestigationGraphResponse(
            task_id=task_id,
            base_graph_available=base_graph_available,
            base_max_nodes=max_base_nodes,
            nodes=tuple(overlay_nodes + _base_nodes(base_rows)),
            links=tuple(overlay_links + _base_links(base_link_rows)),
            warnings=tuple(warnings),
        )


__all__ = [
    "BASE_GRAPH_UNAVAILABLE_WARNING",
    "InvestigationGraphService",
]
