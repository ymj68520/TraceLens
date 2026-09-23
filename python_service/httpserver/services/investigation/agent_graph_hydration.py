"""Evidence hydration for graph results (P6B §50-§52, §70).

The final proof chain is always:

    graph object -> materialization provenance -> frozen semantic unit
    -> canonical Finding/Correlation/Evidence refs
    -> resolve_evidence(task_id, ref) -> real Evidence

A graph id is a navigation identifier and NEVER becomes an Evidence ref
(§43).  Hydration fails closed: a provenance ref that no longer resolves
excludes its semantic object from the hydrated result and surfaces an
invalidation signal for the manifest (§51).  This is contract only —
the P7 Report Writer is out of scope (§52).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from .agent_graph_reader import GraphReadResultV1, TrustClass

HYDRATION_VERSION = "graph-evidence-hydration:v1"


async def hydrate_graph_result_to_evidence(
    result: GraphReadResultV1,
    *,
    task_id: str,
    evidence_resolver: Callable[[str, str], Any],
) -> Mapping[str, Any]:
    """§50: resolve every provenance_bound object's Evidence refs through
    the real evidence resolver.

    Returns a mapping with:

      resolved_evidence_refs  -- refs that resolved inside the task
      resolved_objects        -- per-object hydration (unit -> refs)
      excluded_objects        -- objects whose refs failed resolution
      invalidation_signals    -- (materialization_id, evidence_ref) pairs
                                 hinting the manifest sweep (§51)

    Graph ids never appear as hydrated refs: only resolver-valid
    Evidence refs survive (§43/§51 fail closed)."""
    resolved_refs: list[str] = []
    resolved_objects: list[dict] = []
    excluded_objects: list[dict] = []
    invalidation_signals: list[dict] = []

    for obj in result.objects:
        if obj.trust_class is not TrustClass.PROVENANCE_BOUND:
            excluded_objects.append({
                "backend_ref": obj.backend_ref,
                "reason": "NOT_PROVENANCE_BOUND",
            })
            continue
        object_refs: list[str] = []
        failed: list[str] = []
        for ref in obj.evidence_refs:
            try:
                resolved = await evidence_resolver(task_id, ref)
            except Exception:
                resolved = None
            if resolved is not None:
                object_refs.append(ref)
            else:
                failed.append(ref)
        if object_refs:
            resolved_objects.append({
                "materialization_id": obj.materialization_id,
                "episode_id": obj.episode_id,
                "semantic_unit_id": obj.semantic_unit_id,
                "review_status": obj.review_status,
                "confirmed": obj.confirmed,
                "evidence_refs": object_refs,
            })
            resolved_refs.extend(object_refs)
        if failed:
            excluded_objects.append({
                "backend_ref": obj.backend_ref,
                "reason": "EVIDENCE_RESOLUTION_FAILED",
                "failed_refs": failed,
            })
            if obj.materialization_id:
                invalidation_signals.append({
                    "materialization_id": obj.materialization_id,
                    "evidence_refs": failed,
                })

    unique_refs = sorted(set(resolved_refs))
    return {
        "hydration_version": HYDRATION_VERSION,
        "resolved_evidence_refs": unique_refs,
        "resolved_objects": resolved_objects,
        "excluded_objects": excluded_objects,
        "invalidation_signals": invalidation_signals,
    }


__all__ = [
    "HYDRATION_VERSION",
    "hydrate_graph_result_to_evidence",
]
