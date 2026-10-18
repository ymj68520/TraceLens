"""Evidence independence / dedup layer (P7A §33-§35) — CRITICAL.

The same original Evidence reaches report context through many layers:

    file:A -> Initial Analysis -> accepted Finding -> Graph node
           -> Timeline representation

All of those are ONE root Evidence source ``(task_id, evidence_key)``.
Without dedup the Writer would treat representation chains as independent
corroboration.  This module collapses every retrieved ref to its root
evidence identity and preserves *real* cross-source corroboration:
genuinely different evidence keys (a Windows Event, a browser-history
file, a file-metadata record) stay separate items (§35).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .canonical import sha256_hex

DEDUP_POLICY_VERSION = "report-dedup-policy:v1"


@dataclass(frozen=True)
class EvidenceIndependence:
    """Dedup verdict for one candidate evidence ref."""

    evidence_ref: str
    root_evidence_key: str
    independence_key: str  # canonical dedup key (root identity)
    representation_layers: tuple[str, ...]  # how this ref reached us


class EvidenceIndependenceResolver:
    """Collapse evidence refs to root ``(task_id, evidence_key)`` identity.

    ``layer_resolver`` maps a candidate ref to its root evidence key plus
    the representation layers that produced it.  For plain evidence keys
    (``file:...`` / ``cluster:...``) the ref IS the root identity.  For
    semantic-object-derived candidates the caller supplies the provenance
    mapping (Finding/Analysis/Graph → evidence refs) built from the frozen
    planning context — this resolver never queries a store.
    """

    policy_version = DEDUP_POLICY_VERSION

    def resolve(
        self,
        candidate_refs: Iterable[str],
        *,
        layer_provenance: Optional[Mapping[str, tuple[str, ...]]] = None,
    ) -> list[EvidenceIndependence]:
        """Return one independence verdict per candidate ref, deduped by
        root identity (first occurrence wins; the layers of later
        occurrences are folded into the kept verdict's layer list)."""
        layer_provenance = layer_provenance or {}
        by_root: dict[str, EvidenceIndependence] = {}
        ordered: list[EvidenceIndependence] = []
        for ref in candidate_refs:
            layers = layer_provenance.get(ref, ("direct",))
            root = self.root_evidence_key(ref)
            key = self.independence_key(root)
            existing = by_root.get(key)
            if existing is None:
                verdict = EvidenceIndependence(
                    evidence_ref=ref,
                    root_evidence_key=root,
                    independence_key=key,
                    representation_layers=tuple(layers),
                )
                by_root[key] = verdict
                ordered.append(verdict)
            else:
                merged = tuple(
                    dict.fromkeys(existing.representation_layers + tuple(layers))
                )
                if merged != existing.representation_layers:
                    merged_verdict = EvidenceIndependence(
                        evidence_ref=existing.evidence_ref,
                        root_evidence_key=existing.root_evidence_key,
                        independence_key=existing.independence_key,
                        representation_layers=merged,
                    )
                    by_root[key] = merged_verdict
                    ordered[ordered.index(existing)] = merged_verdict
        return ordered

    @staticmethod
    def root_evidence_key(ref: str) -> str:
        """The root evidence identity of one candidate ref (§34).

        Plain evidence keys are their own root.  Graph ids are NOT legal
        candidates here (they never become Evidence, §26); the caller
        must hydrate them first.
        """
        if ref.startswith(("graph:", "gm:", "gcand:", "node-")):
            raise ValueError(
                f"graph ids are never evidence candidates: {ref}"
            )
        return ref

    @staticmethod
    def independence_key(root_evidence_key: str) -> str:
        return sha256_hex(root_evidence_key)


__all__ = [
    "DEDUP_POLICY_VERSION",
    "EvidenceIndependence",
    "EvidenceIndependenceResolver",
]
