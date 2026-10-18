"""Run manifest / configuration / snapshot tests (P8A §21-§28, §97)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from httpserver.services.benchmarks.run_manifest import (
    BenchmarkConfigurationV1,
    BenchmarkRunManifestV1,
    CacheState,
    EnvironmentDigestV1,
    ModelIdentityV1,
    collect_environment_digest,
)
from httpserver.services.benchmarks.snapshot import (
    BenchmarkRunSnapshotV1,
    SnapshotToolCallV1,
    SnapshotUsageEntryV1,
)


def _model(**overrides) -> ModelIdentityV1:
    payload = dict(
        provider="deepseek",
        model_id="deepseek-flash",
        api_reported_version="2026-01",
        generation_params={"temperature": 0.2},
    )
    payload.update(overrides)
    return ModelIdentityV1(**payload)


def _config(**overrides) -> BenchmarkConfigurationV1:
    payload = dict(
        label="A1-supervisor-tools",
        model_provider="deepseek",
        model_id="deepseek-flash",
        agent_supervisor_enabled=True,
        graph_mode="selective",
        repeat_count=3,
        seed=42,
    )
    payload.update(overrides)
    return BenchmarkConfigurationV1(**payload)


def _manifest(**overrides) -> BenchmarkRunManifestV1:
    payload = dict(
        case_id="bcase:1",
        case_version="1",
        case_hash="c" * 64,
        dataset_hash="d" * 64,
        truth_manifest_id="tman:1",
        truth_manifest_hash="t" * 64,
        tracelens_git_commit="936d3fbd",
        tracelens_branch=(
            "mvp/agent-v0-phase8-benchmark-acceptance-calibration"
        ),
        model=_model(),
        configuration_id=_config().configuration_id,
        configuration_hash=_config().input_hash,
        prompt_versions={"supervisor": "supervisor-planning-context:v1"},
        assertion_policy_version="assertion-policy:v1",
        attention_policy_version="attention-policy:v1",
        finalization_policy_version="finalization-policy:v1",
        graph_admission_policy_version="graph-admission-policy:v1",
    )
    payload.update(overrides)
    return BenchmarkRunManifestV1(**payload)


# ---------------------------------------------------------------------------
# §23 configuration
# ---------------------------------------------------------------------------


def test_configuration_hash_stable_and_idempotent():
    config = _config()
    replay = BenchmarkConfigurationV1(**config.model_dump(mode="json"))
    assert replay.input_hash == config.input_hash
    assert replay.configuration_id == config.configuration_id


def test_configuration_captures_ablation_axes():
    config = _config(
        agent_supervisor_enabled=False,
        semantic_verifier_enabled=False,
        graph_mode="none",
    )
    assert config.agent_supervisor_enabled is False
    assert config.graph_mode == "none"
    assert config.repeat_count == 3


# ---------------------------------------------------------------------------
# §21/§57/§58 run manifest
# ---------------------------------------------------------------------------


def test_run_manifest_roundtrip_and_idempotent_hash():
    manifest = _manifest()
    replay = BenchmarkRunManifestV1(**manifest.model_dump(mode="json"))
    assert replay.input_hash == manifest.input_hash
    assert replay.benchmark_run_id == manifest.benchmark_run_id


def test_run_manifest_persists_reproducibility_metadata():
    manifest = _manifest()
    assert manifest.dataset_hash == "d" * 64
    assert manifest.truth_manifest_hash == "t" * 64
    assert manifest.tracelens_git_commit == "936d3fbd"
    assert manifest.model.provider == "deepseek"
    assert manifest.cache_state == CacheState.cold


def test_cloud_model_may_not_fake_weights_hash_but_local_may():
    cloud = _manifest(model=_model())
    assert cloud.model.weights_hash is None
    local = _manifest(
        model=_model(
            provider="local-ollama",
            model_id="qwen2.5:14b",
            weights_hash="a" * 64,
            quantization="q4_K_M",
        )
    )
    assert local.model.weights_hash == "a" * 64


def test_terminal_status_requires_completed_at():
    with pytest.raises(ValidationError):
        _manifest(terminal_status="completed")
    with pytest.raises(ValidationError):
        _manifest(terminal_status="exploded")
    ok = _manifest(
        terminal_status="failed",
        completed_at="2026-01-01T00:00:00+00:00",
    )
    assert ok.terminal_status == "failed"


def test_environment_digest_no_secrets():
    digest = collect_environment_digest()
    dumped = digest.model_dump_json()
    for forbidden in ("api_key", "API_KEY", "secret"):
        assert forbidden not in dumped
    assert digest.python_version
    assert digest.cpu_count >= 1


def test_env_digest_model_roundtrip():
    digest = EnvironmentDigestV1(
        os_name="Linux",
        arch="x86_64",
        python_version="3.14.0",
        cpu_count=8,
    )
    replay = EnvironmentDigestV1(**digest.model_dump(mode="json"))
    assert replay == digest


# ---------------------------------------------------------------------------
# §28 snapshot immutability
# ---------------------------------------------------------------------------


def _snapshot(**overrides) -> BenchmarkRunSnapshotV1:
    payload = dict(
        run_id="brun:1",
        task_id="task-1",
        investigation_id="inv-1",
        terminal_status="completed",
        finalization_id="fz_1",
        finalization_hash="f" * 64,
        discovered_evidence_refs=("file:C/a.doc", "file:C/b.doc"),
        evidence_first_seen_seq={"file:C/a.doc": 3, "file:C/b.doc": 7},
        tool_calls=(
            SnapshotToolCallV1(
                seq=1,
                tool_id="search_contacts",
                delegation_id="dlg:1",
                result_count=2,
                evidence_refs=("file:C/a.doc",),
            ),
        ),
        usage_entries=(
            SnapshotUsageEntryV1(
                ref="dlg:1",
                kind="specialist",
                requests=1,
                input_tokens=1200,
                output_tokens=300,
                model_name="deepseek-flash",
            ),
        ),
        wall_ms_total=45_000,
    )
    payload.update(overrides)
    return BenchmarkRunSnapshotV1(**payload)


def test_snapshot_hash_stable_and_evidence_sorted():
    snapshot = _snapshot()
    replay = BenchmarkRunSnapshotV1(**snapshot.model_dump(mode="json"))
    assert replay.snapshot_hash == snapshot.snapshot_hash
    reordered = _snapshot(
        discovered_evidence_refs=(
            "file:C/b.doc",
            "file:C/a.doc",
        )
    )
    assert reordered.discovered_evidence_refs == (
        "file:C/a.doc",
        "file:C/b.doc",
    )
    assert reordered.snapshot_hash == snapshot.snapshot_hash


def test_snapshot_captures_metrics_inputs():
    snapshot = _snapshot()
    assert snapshot.tool_calls[0].tool_id == "search_contacts"
    assert snapshot.usage_entries[0].input_tokens == 1200
    assert snapshot.evidence_first_seen_seq["file:C/b.doc"] == 7
