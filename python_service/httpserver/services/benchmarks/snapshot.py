"""Immutable completed-run snapshot adapter (P8A §28, §61).

The evaluator consumes ONLY an immutable snapshot of the durable run
artifacts — never live Agent reasoning and never process memory (§12
answer to the investigation gate).  The snapshot is assembled from the
P1–P7 durable stores the same way restart recovery would: trajectory,
delegations, observations, working-state revisions, findings, grounding,
correlation, graph, finalization, and the P7 report runtime rows.

No chain-of-thought is collected (§61): the snapshot carries the Action
Trace (structured decisions, tool observations, state transitions) only.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

SNAPSHOT_VERSION = "benchmark-run-snapshot:v1"


class SnapshotUsageEntryV1(BaseModel):
    """One usage/telemetry record attached to a delegation or report step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str  # delegation_id / generation_id / reviewer id
    kind: str  # specialist | supervisor | verifier | reviewer | writer
    requests: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    wall_ms: Optional[int] = None
    model_name: str = ""


class SnapshotToolCallV1(BaseModel):
    """One tool call projected from durable ToolObservation + trajectory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    tool_id: str
    delegation_id: str = ""
    args_normalized: dict = Field(default_factory=dict)
    result_count: int = 0
    evidence_refs: tuple[str, ...] = ()
    status: str = "ok"  # ok | failed | zero_result
    created_at: str = ""
    state_revision_after: Optional[int] = None


class BenchmarkRunSnapshotV1(BaseModel):
    """Immutable evaluation input (§28/§50)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_version: str = SNAPSHOT_VERSION

    run_id: str
    task_id: str
    investigation_id: str

    terminal_status: str
    finalization_id: str = ""
    finalization_hash: str = ""

    # evidence discovery (durable visibility authority, P5A §33)
    discovered_evidence_refs: tuple[str, ...] = ()
    evidence_first_seen_seq: dict[str, int] = Field(default_factory=dict)

    tool_calls: tuple[SnapshotToolCallV1, ...] = ()
    delegations: tuple[dict, ...] = ()
    state_revisions: tuple[dict, ...] = ()

    questions: tuple[dict, ...] = ()  # terminal question rows
    coverage: tuple[dict, ...] = ()
    findings: tuple[dict, ...] = ()
    correlations: tuple[dict, ...] = ()
    graph_records: tuple[dict, ...] = ()
    report: dict = Field(default_factory=dict)

    usage_entries: tuple[SnapshotUsageEntryV1, ...] = ()
    wall_ms_total: Optional[int] = None

    limitations: tuple[str, ...] = ()

    snapshot_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data["discovered_evidence_refs"] = tuple(
            sorted(set(data.get("discovered_evidence_refs", ())))
        )
        data["limitations"] = tuple(
            dict.fromkeys(data.get("limitations", ()))
        )
        # defaulted-field normalization keeps snapshot_hash IDEMPOTENT.
        data.setdefault("snapshot_version", SNAPSHOT_VERSION)
        data.setdefault("finalization_id", "")
        data.setdefault("finalization_hash", "")
        data.setdefault("evidence_first_seen_seq", {})
        data["tool_calls"] = tuple(
            SnapshotToolCallV1.model_validate(item)
            for item in data.get("tool_calls", ())
        )
        data["usage_entries"] = tuple(
            SnapshotUsageEntryV1.model_validate(item)
            for item in data.get("usage_entries", ())
        )
        data.setdefault("delegations", ())
        data.setdefault("state_revisions", ())
        data.setdefault("questions", ())
        data.setdefault("coverage", ())
        data.setdefault("findings", ())
        data.setdefault("correlations", ())
        data.setdefault("graph_records", ())
        data.setdefault("report", {})
        data.setdefault("usage_entries", ())
        data.setdefault("wall_ms_total", None)
        if not data.get("created_at"):
            from datetime import datetime, timezone

            data["created_at"] = datetime.now(
                timezone.utc
            ).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("snapshot_hash", "created_at")
        }
        data["snapshot_hash"] = sha256_hex(payload)
        return data


def build_snapshot_from_runtime(
    runtime_repository: Any,
    *,
    task_id: str,
    investigation_id: str,
    run_id: str,
    report_runtime_repository: Optional[Any] = None,
) -> BenchmarkRunSnapshotV1:
    """Assemble the immutable snapshot from durable stores only (§12:
    completed Investigation → full run metrics without process memory).

    Reads via the SAME repository readers restart recovery uses; never
    calls the Agent or any LLM.
    """
    run = runtime_repository.get_run(run_id)
    if run is None:
        raise ValueError(f"unknown run: {run_id}")
    trajectory = [
        event
        for event in runtime_repository.list_trajectory(investigation_id)
        if event.run_id == run_id
    ]
    observations = runtime_repository.list_tool_observations(
        investigation_id, run_id=run_id
    )
    delegations = runtime_repository.list_delegations(run_id)

    evidence_refs: list[str] = []
    first_seen: dict[str, int] = {}
    tool_calls: list[SnapshotToolCallV1] = []
    for seq, event in enumerate(trajectory):
        payload = event.payload or {}
        for ref in payload.get("evidence_refs", ()) or ():
            if ref not in first_seen:
                first_seen[ref] = seq
                evidence_refs.append(ref)
    for observation in observations:
        tool_calls.append(
            SnapshotToolCallV1(
                seq=observation.result.get("seq", 0)
                if isinstance(observation.result, dict)
                else 0,
                tool_id=observation.tool_id,
                delegation_id=observation.delegation_id or "",
                result_count=observation.result_count,
                evidence_refs=tuple(observation.evidence_refs),
                status=(
                    "zero_result"
                    if observation.result_count == 0
                    and not observation.truncated
                    else "ok"
                ),
                created_at=observation.created_at,
            )
        )
        for ref in observation.evidence_refs:
            if ref not in first_seen:
                first_seen[ref] = len(trajectory)
                evidence_refs.append(ref)

    latest_state = runtime_repository.get_latest_working_state(
        investigation_id
    )
    questions: tuple[dict, ...] = ()
    coverage: tuple[dict, ...] = ()
    limitations: tuple[str, ...] = ()
    if latest_state is not None:
        state = latest_state.state or {}
        questions = tuple(
            {
                "question_id": q.get("question_id"),
                "status": q.get("status"),
                "disposition": q.get("disposition"),
            }
            for q in state.get("questions", ())
        )
        coverage = tuple(
            {
                "dimension_id": c.get("dimension_id"),
                "status": c.get("status"),
                "capability_basis": c.get("capability_basis"),
            }
            for c in state.get("coverage", ())
        )
        limitations = tuple(state.get("limitations", ()) or ())

    finalization = runtime_repository.get_finalization(investigation_id)

    usage_entries: list[SnapshotUsageEntryV1] = []
    for delegation in delegations:
        result = runtime_repository.get_delegation_result(
            delegation.delegation_id
        )
        if result is None or result.usage is None:
            continue
        usage = result.usage or {}
        usage_entries.append(
            SnapshotUsageEntryV1(
                ref=delegation.delegation_id,
                kind="specialist",
                requests=usage.get("requests"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                model_name=result.model_name or "",
            )
        )

    findings = tuple(
        runtime_repository.list_investigation_findings(investigation_id)
    )
    correlations = tuple(
        candidate
        for candidate in runtime_repository.list_correlation_candidates(
            investigation_id
        )
    )
    graph_records = tuple(
        record
        for record in runtime_repository.list_graph_materializations(
            investigation_id
        )
    )

    report_payload: dict = {}
    if report_runtime_repository is not None:
        report_payload = {"report_runtime_persisted": True}

    return BenchmarkRunSnapshotV1(
        run_id=run_id,
        task_id=task_id,
        investigation_id=investigation_id,
        terminal_status=run.status.value,
        finalization_id=(
            finalization.finalization_id if finalization else ""
        ),
        finalization_hash=finalization.input_hash if finalization else "",
        discovered_evidence_refs=tuple(evidence_refs),
        evidence_first_seen_seq=dict(first_seen),
        tool_calls=tuple(tool_calls),
        delegations=tuple(
            delegation.model_dump(mode="json") for delegation in delegations
        ),
        questions=questions,
        coverage=coverage,
        findings=findings,
        correlations=correlations,
        graph_records=graph_records,
        report=report_payload,
        usage_entries=tuple(usage_entries),
        limitations=limitations,
    )


__all__ = [
    "BenchmarkRunSnapshotV1",
    "SNAPSHOT_VERSION",
    "SnapshotToolCallV1",
    "SnapshotUsageEntryV1",
    "build_snapshot_from_runtime",
]
