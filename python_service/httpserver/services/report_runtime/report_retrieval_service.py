"""ReportRetrievalService — deterministic retrieval orchestration (P7A
§52-§57).

Executes one frozen ChapterSpec + RetrievalPlan into a
FrozenReportContextPack:

    load exact spec/plan -> resolve anchors -> accepted semantic basis
    -> P6 report-mode graph navigation (seam, graceful degradation §54)
    -> hydrate graph results to real Evidence (P6 helper)
    -> deterministic association expansion -> dedup independence (§33)
    -> rank (§36) -> budget (§37) -> freeze pack (§39)

It is NOT an Agent: no tools, no LLM.  Evidence identity is always
``(task_id, evidence_key)`` validated through the injected evidence
resolver (§28); the planner/Graph can never name a DB path.  Required
anchor failure blocks the pack (§55); optional-context failure becomes a
limitation.  New investigation leads become ``ReportRetrievalGapV1``
proposals only (§56) — this service never mutates Investigation state
(§60) and consumes zero Working State revision (§86 invariant).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..investigation.agent_graph_admission import GraphReaderMode
from ..investigation.agent_graph_hydration import (
    hydrate_graph_result_to_evidence,
)
from ..investigation.agent_graph_reader import ProvenanceGraphReader
from .canonical import digest_text
from .report_context_pack import (
    AcceptedSemanticBasisV1,
    FrozenReportContextPackV1,
    GraphNavigationProvenanceV1,
    ReportEvidenceItemV1,
    build_citation_allowlist,
)
from .report_dedup import EvidenceIndependenceResolver
from .report_hydration import (
    BudgetAccounting,
    RetrievalBudgetV1,
    ROLE_DEFAULT_DEPTH,
    apply_budget,
    rank_candidates,
)
from .report_outline import ReportPlanningContextV1
from .report_retrieval import ReportRetrievalPlanV1

RETRIEVAL_SERVICE_VERSION = "report-retrieval-service:v1"


class ReportRetrievalGapV1:
    """§56: a proposal-only signal that retrieval surfaced a major new
    investigation direction.  Never a Finding; never reopens a case."""

    def __init__(
        self,
        *,
        gap_type: str,
        description: str,
        basis_evidence_refs: tuple[str, ...],
        suggested_investigation_question: str,
    ):
        self.gap_type = gap_type
        self.description = description
        self.basis_evidence_refs = basis_evidence_refs
        self.suggested_investigation_question = (
            suggested_investigation_question
        )

    def to_dict(self) -> dict:
        return {
            "gap_type": self.gap_type,
            "description": self.description,
            "basis_evidence_refs": list(self.basis_evidence_refs),
            "suggested_investigation_question": (
                self.suggested_investigation_question
            ),
        }


class RequiredAnchorResolutionError(RuntimeError):
    """§55: a required anchor failed resolution — pack is blocked."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class RetrievalOutcome:
    pack: FrozenReportContextPackV1
    accounting: BudgetAccounting
    gaps: list[ReportRetrievalGapV1] = field(default_factory=list)
    blocked: bool = False
    block_code: Optional[str] = None


class ReportRetrievalService:
    """Deterministic per-chapter pack builder (§52 pipeline).

    ``graph_reader_factory`` returns the P6 ProvenanceGraphReader for one
    task (or None: §54 degradation).  ``evidence_resolver`` is the task's
    real resolver — ``async (task_id, evidence_key) -> resolved|None``.
    """

    version = RETRIEVAL_SERVICE_VERSION

    def __init__(
        self,
        *,
        evidence_resolver: Callable[[str, str], Awaitable[Any]],
        graph_reader_factory: Optional[
            Callable[[str], Optional[ProvenanceGraphReader]]
        ] = None,
        budget: Optional[RetrievalBudgetV1] = None,
        gap_detector: Optional[
            Callable[[str, tuple[str, ...]], Optional[ReportRetrievalGapV1]]
        ] = None,
    ):
        self._evidence_resolver = evidence_resolver
        self._graph_reader_factory = graph_reader_factory
        self._budget = budget or RetrievalBudgetV1()
        self._gap_detector = gap_detector
        self._dedup = EvidenceIndependenceResolver()

    async def execute(
        self,
        *,
        task_id: str,
        context: ReportPlanningContextV1,
        chapter_spec,
        plan: ReportRetrievalPlanV1,
    ) -> RetrievalOutcome:
        limitations: list[str] = []
        graph_provenance: list[GraphNavigationProvenanceV1] = []
        gaps: list[ReportRetrievalGapV1] = []

        # -- 1. resolve anchors (§55) ------------------------------------
        # semantic anchors resolve through their provenance evidence refs;
        # evidence-key anchors resolve directly (§28).  Semantic refs are
        # NOT evidence candidates — they never enter the expansion pool.
        semantic_anchor_refs: list[str] = []
        required_anchors = set(chapter_spec.required_anchor_refs)
        resolved_refs: list[str] = []
        for ref in plan.anchor_refs:
            if ref.startswith(("finding:", "event:", "sa_")):
                semantic_anchor_refs.append(ref)
                continue
            resolved = await self._resolve_evidence(task_id, ref)
            if resolved is None:
                if ref in required_anchors:
                    raise RequiredAnchorResolutionError(
                        "required_anchor_unresolved",
                        f"required anchor failed resolution: {ref}",
                    )
                limitations.append(f"ANCHOR_RESOLUTION_FAILED:{ref}")
                continue
            resolved_refs.append(ref)

        # -- 2. P6 report-mode graph navigation (§25/§54) -----------------
        graph_evidence_refs: tuple[str, ...] = ()
        graph_distance: dict[str, int] = {}
        reader = (
            self._graph_reader_factory(task_id)
            if self._graph_reader_factory
            else None
        )
        if reader is None:
            limitations.append("GRAPH_RETRIEVAL_UNAVAILABLE")
        else:
            for query in plan.graph_queries:
                try:
                    result = reader.read(
                        context.investigation_id,
                        GraphReaderMode.REPORT,
                        query=query.query_text,
                        task_id=task_id,
                    )
                except Exception:
                    limitations.append("GRAPH_RETRIEVAL_UNAVAILABLE")
                    continue
                hydration = await hydrate_graph_result_to_evidence(
                    result,
                    task_id=task_id,
                    evidence_resolver=self._evidence_resolver,
                )
                graph_evidence_refs = tuple(
                    sorted(
                        set(graph_evidence_refs)
                        | set(hydration["resolved_evidence_refs"])
                    )
                )
                for distance, ref in enumerate(
                    hydration["resolved_evidence_refs"], start=1
                ):
                    graph_distance.setdefault(ref, distance)
                for obj in result.objects:
                    graph_provenance.append(
                        GraphNavigationProvenanceV1(
                            graph_ref=obj.backend_ref,
                            materialization_id=obj.materialization_id,
                            hydrated_evidence_refs=tuple(
                                ref
                                for ref in obj.evidence_refs
                                if ref in set(hydration["resolved_evidence_refs"])
                            ),
                            trust_class=obj.trust_class.value,
                        )
                    )

        # -- 3. deterministic expansion (§27) -----------------------------
        expanded_refs: list[str] = list(resolved_refs)
        expanded_refs.extend(graph_evidence_refs)
        report_keys = context.report_evidence_keys()
        for expansion in plan.deterministic_expansions:
            if expansion.expansion_kind == "report_evidence_set":
                expanded_refs.extend(report_keys[: expansion.max_items])
            elif expansion.expansion_kind == "finding_evidence_provenance":
                finding = context.accepted_finding(expansion.basis_ref)
                if finding:
                    expanded_refs.extend(
                        finding.evidence_refs[: expansion.max_items]
                    )
            elif expansion.expansion_kind == "analysis_evidence_refs":
                analysis = context.accepted_analysis(expansion.basis_ref)
                if analysis:
                    expanded_refs.append(analysis.evidence_key)
            elif expansion.expansion_kind == "event_evidence_links":
                # event→evidence links are resolved by the executor's
                # association source; P7A reuses the planning context's
                # pinned event refs only (bounded)
                event = context.accepted_event(expansion.basis_ref)
                if event is None:
                    limitations.append(
                        f"EVENT_LINK_SOURCE_UNAVAILABLE:{expansion.basis_ref}"
                    )

        # -- 4. dedup independence (§33/§34) -------------------------------
        # every semantic path that grounds a file accumulates as one layer
        # of that file's representation provenance (first occurrence wins
        # per path; the dedup resolver folds them onto the single item)
        layer_provenance: dict[str, list[str]] = {}

        def _add_layer(ref: str, layer: str) -> None:
            layers = layer_provenance.setdefault(ref, [])
            if layer not in layers:
                layers.append(layer)

        for ref in resolved_refs:
            _add_layer(ref, "anchor")
        for ref in graph_evidence_refs:
            _add_layer(ref, "graph_navigation")
        for finding in context.accepted_findings:
            for ref in finding.evidence_refs:
                _add_layer(ref, f"finding:{finding.ref}")
        for analysis in context.accepted_analyses:
            _add_layer(analysis.evidence_key, f"analysis:{analysis.ref}")
        for ref in report_keys:
            _add_layer(ref, "report_evidence")

        unique_candidates = list(dict.fromkeys(expanded_refs))
        verdicts = self._dedup.resolve(
            unique_candidates, layer_provenance=layer_provenance
        )

        # -- 5. re-validate every candidate through the resolver (§28) ----
        # semantic anchors themselves are not evidence keys; the required
        # anchor check maps them onto their provenance evidence refs
        semantic_required = {
            ref
            for ref in chapter_spec.required_anchor_refs
            if ref.startswith(("finding:", "event:", "sa_"))
        }
        semantic_required_evidence: set[str] = set()
        for ref in semantic_required:
            finding = context.accepted_finding(ref)
            if finding is not None:
                semantic_required_evidence.update(finding.evidence_refs)
                continue
            analysis = context.accepted_analysis(ref)
            if analysis is not None:
                semantic_required_evidence.add(analysis.evidence_key)
        verified: list[tuple[Any, str]] = []
        for verdict in verdicts:
            root = verdict.root_evidence_key
            if root.startswith(("finding:", "event:", "sa_")):
                # a semantic ref with no resolvable provenance evidence:
                # keep it out of the evidence lists (its basis row still
                # carries the assertion)
                limitations.append(f"SEMANTIC_BASIS_NO_EVIDENCE:{root}")
                continue
            resolved = await self._resolve_evidence(task_id, root)
            if resolved is None:
                if root in required_anchors or (
                    root in semantic_required_evidence
                ):
                    raise RequiredAnchorResolutionError(
                        "required_anchor_unresolved",
                        f"required anchor evidence failed resolution: {root}",
                    )
                limitations.append(f"CONTEXT_RESOLUTION_FAILED:{root}")
                continue
            verified.append((verdict, root))

        # -- 6. roles + rank + budget (§29/§36/§37) ------------------------
        # semantic anchors are satisfied by their provenance evidence: any
        # evidence ref derived from a required semantic anchor is an
        # anchor-role item (§38: required anchors must reach the pack)
        anchor_evidence_refs = {
            ref
            for ref in chapter_spec.required_anchor_refs
            if not ref.startswith(("finding:", "event:", "sa_"))
        } | semantic_required_evidence
        optional_anchor_evidence_refs = {
            ref
            for ref in chapter_spec.optional_anchor_refs
            if not ref.startswith(("finding:", "event:", "sa_"))
        }
        role_by_ref: dict[str, str] = {}
        for verdict, _root in verified:
            ref = verdict.evidence_ref
            if ref in anchor_evidence_refs or (
                ref in optional_anchor_evidence_refs
            ):
                role_by_ref.setdefault(ref, "anchor")
            elif ref in graph_evidence_refs or ref not in report_keys:
                role_by_ref.setdefault(ref, "retrieved_context")
            else:
                role_by_ref.setdefault(ref, "supporting")
        ranked = rank_candidates(
            [
                (verdict, role_by_ref.get(verdict.evidence_ref, "supporting"))
                for verdict, _ in verified
            ],
            report_evidence_status={
                item.evidence_key: item.report_status
                for item in context.report_evidence
            },
            accepted_semantic_refs=tuple(
                ref
                for finding in context.accepted_findings
                for ref in finding.evidence_refs
            ),
            entity_scope=plan.entity_scope,
            graph_distance=graph_distance,
        )
        kept, accounting = apply_budget(
            ranked,
            # the resolvable evidence identities of every required anchor
            required_anchor_refs=anchor_evidence_refs,
            budget=self._budget,
        )
        limitations.extend(accounting.limitations)

        # -- 7. build evidence items (§30-§32) -----------------------------
        status_by_key = {
            item.evidence_key: item.report_status
            for item in context.report_evidence
        }

        def _item(verdict, role) -> ReportEvidenceItemV1:
            depth = ROLE_DEFAULT_DEPTH[role]
            resolved = None
            return ReportEvidenceItemV1(
                evidence_ref=verdict.evidence_ref,
                role=role,
                source_kind=(
                    "cluster" if verdict.root_evidence_key.startswith("cluster:") else "file"
                ),
                evidence_digest=digest_text(verdict.root_evidence_key),
                hydration_depth=depth,
                source_scope=status_by_key.get(
                    verdict.root_evidence_key, ""
                ),
                independence_key=verdict.independence_key,
                retrieval_provenance=verdict.representation_layers,
                limitations=(),
            )

        anchor_items = [
            _item(candidate.independence, "anchor")
            for candidate in kept
            if role_by_ref.get(candidate.independence.evidence_ref) == "anchor"
        ]
        supporting_items = [
            _item(candidate.independence, "supporting")
            for candidate in kept
            if role_by_ref.get(candidate.independence.evidence_ref)
            == "supporting"
        ]
        retrieved_items = [
            _item(candidate.independence, "retrieved_context")
            for candidate in kept
            if role_by_ref.get(candidate.independence.evidence_ref)
            == "retrieved_context"
        ]

        # -- 8. accepted semantic basis (§42) -------------------------------
        semantic_basis: list[AcceptedSemanticBasisV1] = []
        for ref in plan.semantic_basis_refs:
            finding = context.accepted_finding(ref)
            if finding is not None:
                semantic_basis.append(
                    AcceptedSemanticBasisV1(
                        basis_ref=ref,
                        basis_type="finding",
                        assertion_class=finding.assertion_class,
                        text_digest=finding.text_sha256,
                        evidence_refs=finding.evidence_refs,
                        accepted_version="accepted",
                        provenance_hash=context.finalization.record_hash,
                    )
                )
                continue
            analysis = context.accepted_analysis(ref)
            if analysis is not None:
                semantic_basis.append(
                    AcceptedSemanticBasisV1(
                        basis_ref=ref,
                        basis_type="analysis",
                        assertion_class="INFERENCE",
                        text_digest=analysis.summary_sha256,
                        evidence_refs=(analysis.evidence_key,),
                        accepted_version=str(analysis.version),
                        provenance_hash=context.finalization.record_hash,
                    )
                )
                continue
            event = context.accepted_event(ref)
            if event is not None:
                semantic_basis.append(
                    AcceptedSemanticBasisV1(
                        basis_ref=ref,
                        basis_type="event",
                        assertion_class="FACT",
                        text_digest=event.title_sha256,
                        evidence_refs=(),
                        accepted_version=f"v{event.version}",
                        provenance_hash=context.finalization.record_hash,
                    )
                )

        # -- 9. §56 gaps ----------------------------------------------------
        if self._gap_detector is not None:
            gap = self._gap_detector(
                chapter_spec.chapter_id, tuple(unique_candidates)
            )
            if gap is not None:
                gaps.append(gap)

        # -- 10. freeze pack (§39-§41) ---------------------------------------
        pack = FrozenReportContextPackV1(
            task_id=task_id,
            investigation_id=context.investigation_id,
            finalization_id=context.finalization.finalization_id,
            finalization_record_hash=context.finalization.record_hash,
            outline_id=chapter_spec.outline_id,
            outline_revision=chapter_spec.outline_revision,
            chapter_id=chapter_spec.chapter_id,
            chapter_spec_hash=chapter_spec.input_hash,
            retrieval_plan_id=plan.retrieval_plan_id,
            retrieval_plan_hash=plan.input_hash,
            generation_mode=chapter_spec.generation_mode,
            context_stage=chapter_spec.context_stage,
            anchor_evidence=tuple(anchor_items),
            supporting_evidence=tuple(supporting_items),
            retrieved_context_evidence=tuple(retrieved_items),
            accepted_semantic_basis=tuple(semantic_basis),
            graph_navigation_provenance=tuple(graph_provenance),
            required_question_dispositions=dict(
                context.required_question_dispositions
            ),
            coverage_refs=tuple(
                f"coverage:{key}" for key in context.coverage_dispositions
            ),
            limitations=tuple(limitations),
            allowed_citation_refs=build_citation_allowlist(
                _RawPackView(
                    anchor_items,
                    supporting_items,
                    retrieved_items,
                )
            ),
            hydration_policy_version="report-hydration-policy:v1",
            retrieval_policy_version=plan.retrieval_policy_version,
            dedup_policy_version=plan.dedup_policy_version,
            budget_policy_version="report-retrieval-budget:v1",
        )
        return RetrievalOutcome(
            pack=pack, accounting=accounting, gaps=gaps
        )

    async def _resolve_evidence(
        self, task_id: str, evidence_key: str
    ) -> Any:
        try:
            return await self._evidence_resolver(task_id, evidence_key)
        except Exception:
            return None


class _RawPackView:
    """Minimal view for the citation allowlist derivation before the pack
    model exists (avoids constructing the model twice)."""

    def __init__(self, anchor, supporting, retrieved):
        self.anchor_evidence = anchor
        self.supporting_evidence = supporting
        self.retrieved_context_evidence = retrieved


__all__ = [
    "FrozenReportContextPackV1",
    "ReportRetrievalGapV1",
    "ReportRetrievalService",
    "RequiredAnchorResolutionError",
    "RetrievalOutcome",
    "RETRIEVAL_SERVICE_VERSION",
]
