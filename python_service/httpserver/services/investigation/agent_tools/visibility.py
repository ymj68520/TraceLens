"""Evidence Visibility Ledger (P3 §19).

Grounding (P5) must distinguish "Evidence exists" from "Evidence was actually
exposed to the current Agent run". P3 fixes the reconstruction rule:

    allowed_evidence_ids =
        ContextPack initial evidence refs
      ∪ evidence_refs of every successful ToolObservation of the delegation

Nothing else enters the ledger — failed or invalid tool results contribute
nothing (they are never persisted as observations), and Case Context /
Analyst Notes stay context_only and never become visible Evidence.

The reconstruction is a pure function over durable records (ContextPack +
observation rows) so visibility stays auditable after restarts; no in-memory
set is authoritative.
"""

from typing import Iterable, Optional

from ..agent_runtime import ToolObservation


def reconstruct_allowed_evidence_ids(
    initial_evidence_refs: Iterable[str],
    observations: Iterable[ToolObservation],
    *,
    delegation_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> frozenset[str]:
    """Rebuild one delegation's Evidence visibility from durable records.

    `observations` is the durable observation list (e.g.
    ``AgentRuntimeRepository.list_tool_observations(investigation_id)``);
    when delegation_id/run_id is given, only observations of that delegation
    (or run) are folded in, mirroring the runtime linkage columns.
    """
    allowed = {ref for ref in initial_evidence_refs if ref}
    for observation in observations:
        if delegation_id is not None and observation.delegation_id != delegation_id:
            continue
        if run_id is not None and observation.run_id != run_id:
            continue
        for ref in observation.evidence_refs:
            if ref:
                allowed.add(ref)
    return frozenset(allowed)


__all__ = ["reconstruct_allowed_evidence_ids"]
