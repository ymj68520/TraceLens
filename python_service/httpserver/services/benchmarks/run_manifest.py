"""Benchmark run manifests + configuration (P8A §21-§25, §56-§59).

Reproducibility identity of one benchmark run: dataset hash, TruthManifest
hash, model identity (§58 — cloud models never fake a weights hash),
policy/prompt versions, environment digest (§22, no secrets), and the
frozen configuration that must not change mid-run (§57).
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

RUN_MANIFEST_VERSION = "benchmark-run-manifest:v1"
BENCHMARK_CONFIGURATION_VERSION = "benchmark-configuration:v1"


class CacheState(str, Enum):
    """§67 explicit cache policy per run."""

    cold = "cold"
    warm = "warm"
    mixed = "mixed"


class BenchmarkConfigurationV1(BaseModel):
    """§23 explicit, hashable benchmark configuration.

    P8A NEVER tunes these to production defaults — the configuration
    RECORDS what a run used; P8B owns calibration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    config_version: str = BENCHMARK_CONFIGURATION_VERSION

    configuration_id: str
    label: str = ""

    # model identity (§58)
    model_provider: str = ""
    model_id: str = ""
    model_api_version: str = ""
    model_weights_hash: Optional[str] = None  # local models only
    model_quantization: Optional[str] = None
    generation_params: dict = Field(default_factory=dict)

    # agent features enabled (§24 ablation axes)
    agent_supervisor_enabled: bool = True
    playbook_enabled: bool = False
    specialist_enabled: bool = False
    correlation_enabled: bool = False
    semantic_verifier_enabled: bool = False
    graph_mode: str = "none"  # none | selective | full
    report_enabled: bool = False

    budgets: dict = Field(default_factory=dict)
    repeat_count: int = 1
    seed: Optional[int] = None
    timeout_seconds: Optional[int] = None
    cache_state: CacheState = CacheState.cold

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("config_version", BENCHMARK_CONFIGURATION_VERSION)
        # defaulted-field normalization keeps input_hash IDEMPOTENT (same
        # discipline as the P7B ledger/review root fix).
        data.setdefault("label", "")
        data.setdefault("model_api_version", "")
        data.setdefault("model_weights_hash", None)
        data.setdefault("model_quantization", None)
        data.setdefault("agent_supervisor_enabled", True)
        data.setdefault("playbook_enabled", False)
        data.setdefault("specialist_enabled", False)
        data.setdefault("correlation_enabled", False)
        data.setdefault("semantic_verifier_enabled", False)
        data.setdefault("graph_mode", "none")
        data.setdefault("report_enabled", False)
        data.setdefault("repeat_count", 1)
        data.setdefault("seed", None)
        data.setdefault("timeout_seconds", None)
        data.setdefault("cache_state", CacheState.cold)
        data["budgets"] = dict(sorted((data.get("budgets") or {}).items()))
        data["generation_params"] = dict(
            sorted((data.get("generation_params") or {}).items())
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("configuration_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("configuration_id"):
            data["configuration_id"] = "bconf:" + digest[:24]
        return data


class EnvironmentDigestV1(BaseModel):
    """§22 host environment identity.  NEVER records secrets, API keys,
    or the full environment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    os_name: str = ""
    os_version: str = ""
    arch: str = ""
    python_version: str = ""
    dependency_lock_hash: str = ""
    cpu_model: str = ""
    cpu_count: int = 0
    ram_gb: Optional[float] = None
    gpu_model: str = ""
    gpu_vram_gb: Optional[float] = None
    gpu_driver: str = ""
    notes: str = ""


class ModelIdentityV1(BaseModel):
    """§58 model identity actually recorded for the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model_id: str
    api_reported_version: str = ""
    weights_hash: Optional[str] = None
    quantization: Optional[str] = None
    generation_params: dict = Field(default_factory=dict)
    context_window_tokens: Optional[int] = None
    tokenizer_id: str = ""
    request_date: str = ""


class BenchmarkRunManifestV1(BaseModel):
    """§21 the reproducibility contract frozen BEFORE execution (§57)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = RUN_MANIFEST_VERSION

    benchmark_run_id: str

    case_id: str
    case_version: str
    case_hash: str

    dataset_hash: str

    truth_manifest_id: str
    truth_manifest_hash: str

    tracelens_git_commit: str
    tracelens_branch: str = ""

    model: ModelIdentityV1

    runtime_version: str = ""
    environment: EnvironmentDigestV1 = Field(default_factory=EnvironmentDigestV1)

    configuration_id: str
    configuration_hash: str

    prompt_versions: dict = Field(default_factory=dict)
    playbook_versions: dict = Field(default_factory=dict)
    skill_versions: dict = Field(default_factory=dict)
    tool_registry_hash: str = ""

    assertion_policy_version: str = ""
    attention_policy_version: str = ""
    finalization_policy_version: str = ""
    graph_admission_policy_version: str = ""
    graph_manifest_version: str = ""
    report_policy_versions: dict = Field(default_factory=dict)

    cache_state: CacheState = CacheState.cold

    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    terminal_status: str = "pending"  # pending|running|completed|failed

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("manifest_version", RUN_MANIFEST_VERSION)
        data.setdefault("tracelens_branch", "")
        data.setdefault("runtime_version", "")
        data.setdefault("tool_registry_hash", "")
        data.setdefault("assertion_policy_version", "")
        data.setdefault("attention_policy_version", "")
        data.setdefault("finalization_policy_version", "")
        data.setdefault("graph_admission_policy_version", "")
        data.setdefault("graph_manifest_version", "")
        data.setdefault("cache_state", CacheState.cold)
        data.setdefault("started_at", None)
        data.setdefault("completed_at", None)
        data.setdefault("terminal_status", "pending")
        data["environment"] = EnvironmentDigestV1.model_validate(
            data.get("environment") or {}
        )
        data["model"] = ModelIdentityV1.model_validate(data.get("model"))
        for key in (
            "prompt_versions",
            "playbook_versions",
            "skill_versions",
            "report_policy_versions",
        ):
            data[key] = dict(sorted((data.get(key) or {}).items()))
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("benchmark_run_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        if not data.get("benchmark_run_id"):
            data["benchmark_run_id"] = "brun:" + digest[:24]
        return data

    @model_validator(mode="after")
    def _validate_status(self):
        allowed = {"pending", "running", "completed", "failed"}
        if self.terminal_status not in allowed:
            raise ValueError(
                f"unknown run status: {self.terminal_status!r}"
            )
        if self.terminal_status in {"completed", "failed"} and not (
            self.completed_at
        ):
            raise ValueError("terminal runs must record completed_at")
        return self


def collect_environment_digest() -> EnvironmentDigestV1:
    """Best-effort host digest (§22).  CPU model may be unavailable; GPU
    fields stay empty when not detectable.  No secrets are read."""
    cpu_model = ""
    cpu_count = os.cpu_count() or 0
    try:
        if sys.platform == "linux":
            for line in Path_cpuinfo():
                if "model name" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        cpu_model = ""
    ram_gb = None
    try:
        import resource

        # not total RAM; left None rather than guessing (§64 semantics)
        del resource
    except Exception:
        pass
    return EnvironmentDigestV1(
        os_name=platform.system(),
        os_version=platform.release(),
        arch=platform.machine(),
        python_version=platform.python_version(),
        cpu_model=cpu_model,
        cpu_count=cpu_count,
        ram_gb=ram_gb,
    )


def Path_cpuinfo():
    with open("/proc/cpuinfo", encoding="utf-8") as handle:
        return handle.readlines()


__all__ = [
    "BENCHMARK_CONFIGURATION_VERSION",
    "BenchmarkConfigurationV1",
    "BenchmarkRunManifestV1",
    "CacheState",
    "EnvironmentDigestV1",
    "ModelIdentityV1",
    "RUN_MANIFEST_VERSION",
    "collect_environment_digest",
]
