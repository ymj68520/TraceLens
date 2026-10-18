"""TraceLens provenance-aware Graph Reader (P6B §34, §36-§42, §44-§49,
§53-§57, §76-§77).

All Agent/P7-facing graph queries pass through this reader — never raw
Graphiti/Neo4j (§34).  It is the logical validity gate:

    backend results -> namespace filter -> resolve provenance binding
    -> manifest must be ACTIVE -> frozen episode/unit provenance
    -> retrieval-mode classification -> current canonical re-check
    -> typed GraphReadResultV1

Trust classes (§76): ``provenance_bound`` objects carry a complete
materialization lineage (bindings -> manifest -> episode -> unit ->
candidate/admission -> Evidence/Finding refs); everything else is
``locator_only`` — at most a retrieval hint whose content must be
hydrated to real Evidence before an Agent may rely on it.  A graph id is
a navigation identifier and can NEVER become an Evidence ref (§43).

Review-state races (§47): the reader re-checks CURRENT canonical Finding
status at query time — a backend object frozen as review_pending whose
Finding is now rejected is excluded even if the invalidation sweep has
not run yet.
"""

from __future__ import annotations

import enum
import hashlib
from typing import Callable, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from .agent_graph_admission import GraphReaderMode, retrieval_eligible
from .agent_runtime import AgentRuntimeRepository, canonical_state_json

GRAPH_READ_RESULT_VERSION = "graph-read-result:v1"
READER_VERSION = "provenance-graph-reader:v1"


class TrustClass(str, enum.Enum):
    PROVENANCE_BOUND = "provenance_bound"
    LOCATOR_ONLY = "locator_only"


class GraphObjectResult(BaseModel):
    """One typed graph object after logical/provenance filtering."""

    model_config = ConfigDict(frozen=True)

    backend_ref: str
    backend_object_kind: str
    trust_class: TrustClass

    materialization_id: Optional[str] = None
    episode_id: Optional[str] = None
    semantic_unit_id: Optional[str] = None

    review_status: Optional[str] = None
    confirmed: bool = False
    semantic_authority: str = "graph_derived_locator"

    evidence_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    semantic_summary: str = ""


class GraphReadResultV1(BaseModel):
    """§42 typed reader output."""

    model_config = ConfigDict(frozen=True)

    result_version: str = GRAPH_READ_RESULT_VERSION
    result_id: str
    mode: GraphReaderMode
    task_id: str
    investigation_id: str

    objects: tuple[GraphObjectResult, ...] = ()
    locator_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    query_hash: str


class ProvenanceGraphReader:
    """Facade composition over the task-scoped store (§35: option B —
    the existing InvestigationGraphReader stays untouched)."""

    VERSION = READER_VERSION

    def __init__(
        self,
        runtime: AgentRuntimeRepository,
        *,
        finding_resolver: Optional[Callable[[str], Optional[Mapping]]] = None,
        evidence_resolver: Optional[Callable[[str, str], bool]] = None,
        backend_query: Optional[
            Callable[[str, str], Sequence[Mapping]]
        ] = None,
    ):
        self._runtime = runtime
        self._finding_resolver = finding_resolver
        self._evidence_resolver = evidence_resolver
        # injected backend query: (group_id, query) -> backend rows with
        # at least {backend_episode_name, backend_ref, backend_object_kind}
        self._backend_query = backend_query

    def read(
        self,
        investigation_id: str,
        mode: GraphReaderMode,
        *,
        query: str = "",
        task_id: Optional[str] = None,
    ) -> GraphReadResultV1:
        task_id = task_id or self._runtime.task_id
        limitations: list[str] = []
        warnings: list[str] = []
        objects: list[GraphObjectResult] = []
        locator_refs: list[str] = []
        evidence_refs: set[str] = set()

        if self._backend_query is None:
            limitations.append("GRAPH_BACKEND_UNAVAILABLE")
        else:
            try:
                backend_rows = list(
                    self._backend_query(task_id, query)
                )
            except Exception as exc:
                backend_rows = []
                limitations.append(
                    f"GRAPH_BACKEND_UNAVAILABLE:{type(exc).__name__}"
                )
            for row in backend_rows:
                trusted, is_locator = self._resolve_object(
                    row, investigation_id=investigation_id,
                    mode=mode, limitations=limitations,
                    warnings=warnings,
                )
                if trusted is not None:
                    objects.append(trusted)
                    evidence_refs.update(trusted.evidence_refs)
                elif is_locator:
                    # no materialization lineage at all: at most a hint
                    locator_refs.append(str(row.get("backend_ref")))
                # else: named binding but not ACTIVE -> silently filtered
                # (§37: immediate logical filtering, no locator either)

        query_payload = {
            "task_id": task_id,
            "investigation_id": investigation_id,
            "mode": mode.value,
            "query": query,
        }
        query_hash = hashlib.sha256(
            canonical_state_json(query_payload).encode("utf-8")
        ).hexdigest()
        result_id = "gread:" + query_hash[:24]
        return GraphReadResultV1(
            result_id=result_id,
            mode=mode,
            task_id=task_id,
            investigation_id=investigation_id,
            objects=tuple(objects),
            locator_refs=tuple(sorted(set(locator_refs))),
            evidence_refs=tuple(sorted(evidence_refs)),
            limitations=tuple(limitations),
            warnings=tuple(warnings),
            query_hash=query_hash,
        )

    # -- internals --------------------------------------------------------

    def _resolve_object(
        self,
        row: Mapping,
        *,
        investigation_id: str,
        mode: GraphReaderMode,
        limitations: list,
        warnings: list,
    ) -> tuple[Optional[GraphObjectResult], bool]:
        """Returns (object, is_locator). is_locator is True only when the
        object carries NO materialization lineage at all."""
        backend_name = str(row.get("backend_episode_name") or "")
        materialization_id = _materialization_from_name(backend_name)
        if materialization_id is None:
            return None, True  # locator_only fallback
        manifest = self._runtime.get_graph_materialization(
            investigation_id, materialization_id
        )
        if manifest is None:
            # §39/§40: a name that maps to no durable manifest has no
            # lineage at all - at most a locator hint
            return None, True
        if manifest["task_id"] != self._runtime.task_id:
            # §54: cross-task leakage is dropped outright, never trusted
            warnings.append("CROSS_TASK_PROVENANCE_DROPPED")
            return None, False
        # §37: only ACTIVE manifests are trusted retrieval; named bindings
        # in other states are silently filtered (known, not trusted)
        if manifest["status"] != "active":
            return None, False
        episode = self._runtime.get_graph_episode(
            investigation_id, manifest["episode_id"]
        )
        if episode is None:
            return None, False
        unit_id = str(row.get("semantic_unit_id") or "")
        unit = next(
            (
                u for u in episode["semantic_units"]
                if u["unit_id"] == unit_id
            ),
            None,
        )
        if unit is None:
            # episode-level object without a specific unit: keep episode
            # provenance, no unit-level status
            unit = None
        review_status = (
            unit["review_status"] if unit
            else episode["review_statuses"].get(unit_id)
        )
        finding_refs = tuple(
            unit["finding_refs"] if unit else episode["finding_refs"]
        )
        verification_refs = tuple(
            unit.get("verification_refs") or () if unit else ()
        )
        # §47 current canonical re-check (race protection)
        if self._finding_resolver is not None:
            for finding_ref in finding_refs:
                finding = self._finding_resolver(finding_ref)
                if finding is None:
                    warnings.append(
                        f"finding missing at query time: {finding_ref}"
                    )
                    return None, False
                if finding["status"] == "rejected":
                    return None, False
                if (
                    finding["status"] == "accepted"
                    and review_status == "review_pending"
                ):
                    # §48: keep frozen provenance, evaluate by CURRENT
                    # canonical eligibility (accepted -> eligible)
                    review_status = "accepted"
        verified = bool(verification_refs)
        if not retrieval_eligible(review_status, mode, verified=verified):
            return None, False
        confirmed = review_status in (None, "accepted", "not_applicable")
        authority = (
            "canonical_finding" if finding_refs
            else "evidence_derived" if unit is None or unit["candidate_kind"]
            == "evidence_derived_context"
            else "graph_derived_locator"
        )
        return GraphObjectResult(
            backend_ref=str(row.get("backend_ref")),
            backend_object_kind=str(
                row.get("backend_object_kind") or "episode"
            ),
            trust_class=TrustClass.PROVENANCE_BOUND,
            materialization_id=materialization_id,
            episode_id=manifest["episode_id"],
            semantic_unit_id=unit_id or None,
            review_status=review_status,
            confirmed=confirmed,
            semantic_authority=authority,
            evidence_refs=tuple(
                unit["evidence_refs"] if unit else episode["evidence_refs"]
            ),
            finding_refs=finding_refs,
            semantic_summary=(
                unit["semantic_summary"] if unit
                else str(episode.get("semantic_units", [{}])[0].get(
                    "semantic_summary", ""
                )) if episode["semantic_units"] else ""
            ),
        ), False


def _materialization_from_name(backend_episode_name: str) -> Optional[str]:
    prefix = "tracelens:materialization:"
    if not backend_episode_name.startswith(prefix):
        return None
    rest = backend_episode_name[len(prefix):]
    return rest.split(":unit:", 1)[0] or None


__all__ = [
    "GRAPH_READ_RESULT_VERSION",
    "GraphObjectResult",
    "GraphReadResultV1",
    "GraphReaderMode",
    "ProvenanceGraphReader",
    "TrustClass",
]
