"""P6B §5-§11 GraphMaterializationAdapter tests: deterministic frozen
episode -> backend payload translation with explicit provenance."""

import json

import pytest

from httpserver.services.investigation.agent_graph_admission import (
    GraphAdmissionDecision,
    GraphAdmissionPolicy,
)
from httpserver.services.investigation.agent_graph_backend import (
    FakeGraphBackend,
    GraphMaterializationAdapter,
    deterministic_episode_name,
    render_episode_text,
)
from httpserver.services.investigation.agent_graph_candidate import (
    GraphCandidateBuilder,
)
from httpserver.services.investigation.agent_graph_episode import (
    freeze_episode,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "9" * 8

_BUILDER = GraphCandidateBuilder()
_POLICY = GraphAdmissionPolicy()
_ADAPTER = GraphMaterializationAdapter()


def _candidate():
    return _BUILDER.candidate_from_evidence_context(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        summary="identical sha256 payload across hosts",
        evidence_refs=("file:C/1.iso", "file:D/2.iso"),
    )


def _episode(candidate):
    decision = _POLICY.evaluate(candidate)
    return freeze_episode(
        [candidate], {candidate.candidate_id: decision},
        task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        source_revision=3, source_state_hash="s-hash",
        policy_version=decision.policy_version,
        policy_hash=decision.policy_hash,
    )


def test_translation_is_deterministic():
    candidate = _candidate()
    episode = _episode(candidate)
    first = _ADAPTER.translate(
        episode, materialization_id="gm:1", group_id=TASK_ID
    )
    second = _ADAPTER.translate(
        episode, materialization_id="gm:1", group_id=TASK_ID
    )
    assert first.input_hash == second.input_hash
    assert first.episode_name == deterministic_episode_name("gm:1")


def test_backend_payload_carries_machine_readable_provenance():
    candidate = _candidate()
    episode = _episode(candidate)
    payload = _ADAPTER.translate(
        episode, materialization_id="gm:1", group_id=TASK_ID
    )
    assert payload.provenance_token["episode_hash"] == episode.input_hash
    assert payload.provenance_token["evidence_refs"] == [
        "file:C/1.iso", "file:D/2.iso",
    ]
    assert payload.provenance_token["policy_version"] == (
        "graph-admission-policy:v1"
    )
    # every unit body carries its assertion -> evidence map
    unit = json.loads(payload.units[0]["body"])
    assert unit["assertion"] == candidate.semantic_summary
    assert unit["evidence_refs"] == ["file:C/1.iso", "file:D/2.iso"]
    assert unit["review_status"] == "not_applicable"


def test_adapter_reads_only_the_frozen_episode():
    """§7: translate consumes the persisted episode mapping — the adapter
    module contains no repository/live-state access at all."""
    import inspect
    import httpserver.services.investigation.agent_graph_backend as mod

    source = inspect.getsource(mod)
    assert "AgentRuntimeRepository" not in source
    assert "commit_working_state" not in source
    assert "get_latest_working_state" not in source


async def test_fake_backend_roundtrip_and_lookup_failure():
    candidate = _candidate()
    episode = _episode(candidate)
    payload = _ADAPTER.translate(
        episode, materialization_id="gm:1", group_id=TASK_ID
    )
    backend = FakeGraphBackend()
    outcome = await backend.ingest(payload)
    assert outcome.success and outcome.backend_episode_ref

    ref = await backend.find_episode_ref(
        payload.episode_name, payload.group_id
    )
    assert ref == outcome.backend_episode_ref

    # a backend that cannot even confirm the deterministic episode name
    # reports unresolvable provenance (§11 Strategy D fail closed)
    blind = FakeGraphBackend(fail_lookup=True)
    outcome = await blind.ingest(payload)
    assert outcome.success
    assert await blind.find_episode_ref(
        payload.episode_name, payload.group_id
    ) is None


async def test_backend_ingest_failure_is_explicit():
    payload = _ADAPTER.translate(
        _episode(_candidate()), materialization_id="gm:2", group_id=TASK_ID
    )
    backend = FakeGraphBackend(fail_ingest=True)
    outcome = await backend.ingest(payload)
    assert not outcome.success
    assert outcome.failure_code == "GRAPH_BACKEND_INGEST_FAILED"


def test_text_renderer_includes_units_without_replacing_provenance():
    payload = _ADAPTER.translate(
        _episode(_candidate()), materialization_id="gm:3", group_id=TASK_ID
    )
    text = render_episode_text(payload)
    assert "TRACE_LENS_EPISODE" in text
    assert "SEMANTIC_UNIT" in text
    # the text is an aid only: machine-readable token stays authoritative
    assert payload.provenance_token["episode_id"] == payload.episode_id
