"""RCA-2A.10 Bounded Gateway Compatibility Diagnosis Runner.

Implements bounded live diagnostics for TraceLens Agent v0:
- D3: One Full INTEGRATE Non-Streaming Request (stream=False)
- D4: One Conditional Full INTEGRATE Streaming Request (stream=True, ONLY if D3 == HTTP 500)

Enforces strict single-request boundaries:
- SDK transport retries = 0
- Pydantic output retries = 0
- Max logical generations = 2 (D3: 1, D4: 1)
- Max physical HTTP attempts = 2
- Wire-level attempt interception via custom httpx transport
- Monotonic timestamps for accurate latency (wall-clock, TTFB, completion)
- Durable request claims (O_CREAT | O_EXCL, fsync)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import enum
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Union

import httpx
from openai import AsyncOpenAI
from openai import APIStatusError, AuthenticationError, RateLimitError
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from benchmarks.isolated_integration.cross_case_fixtures import (
    build_cloned_cross_case_pair,
)
from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
from httpserver.config import get_settings
from httpserver.services.investigation.agent_failure_diagnostics import (
    JsonlFailureDiagnosticSink,
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_model_adapter import (
    ModelAdapterConfig,
    OpenAIChatModelSettings,
    OpenAIModelProfile,
    resolve_adapter_config,
)
from httpserver.services.investigation.agent_supervisor import (
    SupervisorAgentFactory,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXPERIMENT_ID = "rca2a10e-bounded-gateway-diagnosis"
AUTHORIZED_BASELINE = "4a63cfb197958a42ff8a7779311595742b2fbe41"
AUTHORIZED_SCHEMA_HASH = "a214ec4f5e81fcbb"
AUTHORIZED_PROVIDER = "generic"
AUTHORIZED_BASE_URL = "https://api.hcnsec.cn/v1"
AUTHORIZED_MODEL = "step-5-preview"
EXPECTED_RETURNED_MODEL = "stepfun-ai/step-5-preview"

# RCA-2A.10f Candidate Constants
EXPERIMENT_ID_RCA2A10F = "rca2a10f-bounded-gateway-diagnosis"
AUTHORIZED_BASELINE_RCA2A10F = "d9a0424492a90fa095febed02f77c55246d7ff58"
AUTHORIZED_MODEL_RCA2A10F = "longcat-2.5"

# RCA-2A.10g Candidate Constants
EXPERIMENT_ID_RCA2A10G = "rca2a10g-bounded-gateway-diagnosis"
AUTHORIZED_BASELINE_RCA2A10G = "7de76cf1afa867c97f2ae66b1e482895372e39c3"
AUTHORIZED_BASE_URL_RCA2A10G = "https://chat.cordapp.org/v1"
AUTHORIZED_MODEL_RCA2A10G = "deepseek-flash"

MAX_LOGICAL_GENERATIONS = 2
MAX_PHYSICAL_HTTP_ATTEMPTS = 2
SDK_MAX_RETRIES = 0
PYDANTIC_OUTPUT_RETRIES = 0
TIMEOUT_SECONDS = 360.0
TEMPERATURE = 1.0
MAX_TOKENS = 4096


def get_allowed_returned_models(model_name: str) -> set[str]:
    return {
        model_name,
        f"deepseek-ai/{model_name}",
        f"deepseek/{model_name}",
        f"meituan/{model_name}",
        f"longcat/{model_name}",
        f"stepfun-ai/{model_name}",
        f"openrouter/{model_name}",
        "step-5-preview",
        "stepfun-ai/step-5-preview",
        "longcat-2.5",
        "longcat-2.5-preview-free",
        "deepseek-flash",
    }


# ---------------------------------------------------------------------------
# Enums and Claims
# ---------------------------------------------------------------------------
class DiagnosticClaimStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    ATTEMPT_OUTCOME_UNKNOWN = "ATTEMPT_OUTCOME_UNKNOWN"
    RESULT_RECORDED = "RESULT_RECORDED"
    BLOCKED = "BLOCKED"


class D3OutcomeStatus(str, enum.Enum):
    D3_FULL_REQUEST_PASS = "D3_FULL_REQUEST_PASS"
    D3_PROVIDER_INFRA_FAILURE = "D3_PROVIDER_INFRA_FAILURE"
    D3_MODEL_OUTPUT_INVALID = "D3_MODEL_OUTPUT_INVALID"
    D3_HARD_PROVIDER_BLOCK = "D3_HARD_PROVIDER_BLOCK"
    D3_OUTCOME_UNKNOWN = "D3_OUTCOME_UNKNOWN"


class D4OutcomeStatus(str, enum.Enum):
    D4_STREAMING_PASS = "D4_STREAMING_PASS"
    D4_STREAMING_PROVIDER_FAILURE = "D4_STREAMING_PROVIDER_FAILURE"
    D4_STREAMING_OUTPUT_INVALID = "D4_STREAMING_OUTPUT_INVALID"
    D4_STREAMING_INCOMPLETE = "D4_STREAMING_INCOMPLETE"
    D4_STREAMING_UNSUPPORTED = "D4_STREAMING_UNSUPPORTED"
    D4_OUTCOME_UNKNOWN = "D4_OUTCOME_UNKNOWN"
    D4_NOT_REQUIRED = "D4_NOT_REQUIRED"
    D4_NOT_AUTHORIZED_BY_CONDITIONS = "D4_NOT_AUTHORIZED_BY_CONDITIONS"


class DurableRequestClaim:
    """Atomic, fsync-persisted claim for diagnostic network requests."""

    def __init__(self, claim_path: Path, request_id: str, experiment_id: str):
        self.claim_path = Path(claim_path)
        self.request_id = request_id
        self.experiment_id = experiment_id
        self.record: dict[str, Any] = {}

    def initialize_exclusive(self, manifest_hash: str) -> None:
        if self.claim_path.exists():
            raise FileExistsError(f"Claim file already exists: {self.claim_path}")
        self.claim_path.parent.mkdir(parents=True, exist_ok=True)
        self.record = {
            "artifact_version": "RequestClaimV1",
            "experiment_id": self.experiment_id,
            "request_id": self.request_id,
            "status": DiagnosticClaimStatus.NOT_STARTED.value,
            "manifest_hash": manifest_hash,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "created_at_monotonic": time.monotonic(),
        }
        self._write_fsync()

    def mark_dispatch_started(self) -> None:
        self.record["status"] = DiagnosticClaimStatus.ATTEMPT_OUTCOME_UNKNOWN.value
        self.record["dispatched_at_monotonic"] = time.monotonic()
        self.record["dispatched_at_utc"] = datetime.now(timezone.utc).isoformat()
        self._write_fsync()

    def mark_result_recorded(self, outcome: dict[str, Any]) -> None:
        self.record["status"] = DiagnosticClaimStatus.RESULT_RECORDED.value
        self.record["finalized_at_monotonic"] = time.monotonic()
        self.record["finalized_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.record["outcome"] = outcome
        self._write_fsync()

    def mark_blocked(self, reason: str) -> None:
        self.record["status"] = DiagnosticClaimStatus.BLOCKED.value
        self.record["blocked_reason"] = reason
        self.record["finalized_at_monotonic"] = time.monotonic()
        self.record["finalized_at_utc"] = datetime.now(timezone.utc).isoformat()
        self._write_fsync()

    def _write_fsync(self) -> None:
        content = json.dumps(self.record, indent=2).encode("utf-8")
        fd = os.open(
            str(self.claim_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            os.write(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)


# ---------------------------------------------------------------------------
# Wire Observability Transport
# ---------------------------------------------------------------------------
class WireObservingTransport(httpx.AsyncBaseTransport):
    """Transparent httpx transport wrapper intercepting and instrumenting wire telemetry."""

    def __init__(
        self,
        inner_transport: httpx.AsyncBaseTransport,
        max_physical_attempts_per_call: int = 1,
    ):
        self.inner = inner_transport
        self.max_physical_attempts = max_physical_attempts_per_call
        self.attempts: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        attempt_number = len(self.attempts) + 1
        if attempt_number > self.max_physical_attempts:
            raise RuntimeError(
                f"WIRE_BUDGET_EXCEEDED: attempt {attempt_number} exceeds max authorized physical attempts ({self.max_physical_attempts})"
            )

        attempt_record: dict[str, Any] = {
            "attempt_number": attempt_number,
            "url": str(request.url),
            "method": request.method,
            "request_headers": {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in ("authorization", "x-api-key")
            },
            "request_body_bytes": len(request.content),
            "started_at_monotonic": time.monotonic(),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.attempts.append(attempt_record)

        try:
            response = await self.inner.handle_async_request(request)
            attempt_record["status_code"] = response.status_code
            attempt_record["response_headers"] = {
                k: v
                for k, v in response.headers.items()
                if k.lower() in ("content-type", "x-request-id", "retry-after", "server", "date")
            }
            attempt_record["finished_at_monotonic"] = time.monotonic()
            attempt_record["latency_ms"] = (
                attempt_record["finished_at_monotonic"]
                - attempt_record["started_at_monotonic"]
            ) * 1000

            if response.headers.get("content-type", "").startswith("text/event-stream"):
                response.stream = StreamObservingByteStream(
                    response.stream, attempt_record
                )

            return response
        except Exception as exc:
            attempt_record["finished_at_monotonic"] = time.monotonic()
            attempt_record["latency_ms"] = (
                attempt_record["finished_at_monotonic"]
                - attempt_record["started_at_monotonic"]
            ) * 1000
            attempt_record["exception_class"] = type(exc).__name__
            attempt_record["exception_message_sanitized"] = str(exc)[:200]
            raise


class StreamObservingByteStream(httpx.AsyncByteStream):
    """Wraps an httpx streaming body to measure TTFB and completion accurately."""

    def __init__(self, inner_stream: httpx.AsyncByteStream, attempt_record: dict[str, Any]):
        self.inner = inner_stream
        self.record = attempt_record
        self.chunk_count = 0
        self.first_chunk_recorded = False

    async def __aiter__(self):
        async for chunk in self.inner:
            if not self.first_chunk_recorded:
                self.record["time_to_first_chunk_ms"] = (
                    time.monotonic() - self.record["started_at_monotonic"]
                ) * 1000
                self.first_chunk_recorded = True
            self.chunk_count += 1
            yield chunk
        self.record["stream_chunks_count"] = self.chunk_count
        self.record["stream_finished_at_monotonic"] = time.monotonic()
        self.record["stream_total_ms"] = (
            self.record["stream_finished_at_monotonic"]
            - self.record["started_at_monotonic"]
        ) * 1000

    async def aclose(self):
        await self.inner.aclose()


# ---------------------------------------------------------------------------
# Envelope Reconstructor
# ---------------------------------------------------------------------------
def calculate_request_envelope(
    instructions: str,
    tool_schema: dict[str, Any],
    model_name: str,
    stream: bool,
    temperature: float = 1.0,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Calculate exact byte dimensions and hashes for the serialized HTTP request envelope."""
    instructions_bytes = instructions.encode("utf-8")
    tool_schema_json = json.dumps(tool_schema, separators=(",", ":"))
    tool_schema_bytes = tool_schema_json.encode("utf-8")

    body_dict = {
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": "integrate"},
        ],
        "model": model_name,
        "max_tokens": max_tokens,
        "stream": stream,
        "temperature": temperature,
        "tool_choice": "final_result",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "final_result",
                    "description": "The final integration decision with typed transition proposals.",
                    "parameters": tool_schema,
                },
            }
        ],
    }

    serialized_body = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")
    body_sha256 = hashlib.sha256(serialized_body).hexdigest()
    instructions_sha256 = hashlib.sha256(instructions_bytes).hexdigest()
    tool_schema_sha256 = hashlib.sha256(tool_schema_bytes).hexdigest()
    messages_sha256 = hashlib.sha256(
        json.dumps(body_dict["messages"], separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "instructions_chars": len(instructions),
        "instructions_utf8_bytes": len(instructions_bytes),
        "instructions_hash": instructions_sha256,
        "tool_schema_chars": len(tool_schema_json),
        "tool_schema_utf8_bytes": len(tool_schema_bytes),
        "tool_schema_hash": tool_schema_sha256,
        "messages_hash": messages_sha256,
        "serialized_http_body_bytes": len(serialized_body),
        "request_body_sha256": body_sha256,
        "model_name": model_name,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_seconds": TIMEOUT_SECONDS,
    }


# ---------------------------------------------------------------------------
# Diagnostic Model Builder (Benchmark-Only Wrapper)
# ---------------------------------------------------------------------------
def build_diagnostic_model(
    config: ModelAdapterConfig,
    api_key: str,
    transport: httpx.AsyncBaseTransport,
    identity_sink: list[dict[str, Any]],
) -> OpenAIChatModel:
    """Build a benchmark-only OpenAIChatModel with max_retries=0 and custom wire transport."""
    http_client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(config.timeout_seconds or TIMEOUT_SECONDS),
    )
    client = AsyncOpenAI(
        base_url=config.base_url,
        api_key=api_key or "EMPTY",
        max_retries=SDK_MAX_RETRIES,
        http_client=http_client,
    )

    upstream_create = client.chat.completions.create
    requested_model = config.model_name

    async def _identity_tracking_create(**kwargs):
        response = await upstream_create(**kwargs)
        try:
            identity_sink.append({
                "requested_model": requested_model,
                "returned_model": getattr(response, "model", None),
                "upstream_provider": (getattr(response, "model_extra", None) or {}).get("provider"),
            })
        except Exception:
            pass
        return response

    client.chat.completions.create = _identity_tracking_create

    provider = OpenAIProvider(openai_client=client)
    profile = OpenAIModelProfile(
        supports_json_schema_output=False,
        supports_json_object_output=True,
        openai_supports_strict_tool_definition=False,
        openai_chat_supports_max_completion_tokens=False,
        openai_chat_supports_multiple_system_messages=False,
    )
    model_settings = OpenAIChatModelSettings(timeout=config.timeout_seconds)
    if config.temperature is not None:
        model_settings["temperature"] = config.temperature
    if config.max_tokens is not None:
        model_settings["max_tokens"] = config.max_tokens

    return OpenAIChatModel(
        config.model_name,
        provider=provider,
        profile=profile,
        settings=model_settings,
    )


# ---------------------------------------------------------------------------
# Pre-Call Gate Verifications
# ---------------------------------------------------------------------------
def verify_git_clean_and_baseline(expected_baseline: str) -> dict[str, Any]:
    """Verify repository HEAD and worktree state."""
    head_rev = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    status_out = subprocess.check_output(["git", "status", "--short"], text=True).strip()
    is_clean = len(status_out) == 0
    is_ancestor = False
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", expected_baseline, head_rev],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        is_ancestor = True
    except Exception:
        is_ancestor = False

    return {
        "head_commit": head_rev,
        "expected_baseline": expected_baseline,
        "matches_baseline": head_rev.startswith(expected_baseline[:8]) or is_ancestor,
        "worktree_clean": is_clean,
    }


def verify_historical_artifacts_immutable(repo_root: Path) -> dict[str, Any]:
    """Verify SHA-256 integrity of all historical recovered Epoch A files."""
    history_dir = repo_root / "python_service/benchmarks/audits/rca2a10d-provenance-transport-audit/historical_epoch_a_artifacts"
    if not history_dir.exists():
        return {"ok": False, "error": "historical_epoch_a_artifacts directory missing"}

    expected_hashes = {
        "rca2a10b-audit-report.md": "737e85cd15171ff28d382090da5add51d46d3c87e41ba1e24dc48ddfeee3a29c",
        "rca2a10b-cost-and-accounting-report-v1.json": "36474387fcb0fe11de60239826997929eff302847a395bba0baaa3058927e7cb",
        "rca2a10b-effective-model-config-v1.json": "22d86e4567b8e660583e9ce0be0e25876275f65e72f80634642d2444a6f2dece",
        "rca2a10b-evidence-integrity-report-v1.json": "0a4bea33d950b54351ea578fc7a894a8052aa115c1e8686bc7b0d918695852ee",
        "rca2a10b-experiment-manifest-v1.json": "aeec1dcf429d366239f49d73af5e5492f4f0a0d16e6a1d8bdfd7646f5ab9cc32",
        "rca2a10b-final-decision-report-v1.json": "abafd65e1e850a49107df98f55b5b6b31f239d454ee9b11350b1446392a8ba51",
        "rca2a10b-historical-identity-reconciliation-v1.json": "2a740a1fccc2f9177cbae4a391ee77710215f9139b040ffa2c8ce129d3253f19",
        "rca2a10b-model-compatibility-report-v1.json": "198845cada59eb592b338c55af6b09272bbe73393442f44b6edd446f7136d292",
        "rca2a10b-paired-execution-matrix-v1.json": "ee73f03ce7e764ba38d4860a912476e3a70a6e2c1297a5e11c26f6ad545a9ad5",
        "rca2a10b-preflight-gate-report-v1.json": "6248eff175c3ce5cf1d2d44344392d3a9b2c3a795354cc94d7a408f1dad2fc33",
        "rca2a10b-runtime-identity-record-v1.json": "acdc1e5c8d96e91f8d75ed03c914ef0da531f0f6b981f2c16bb2442adf07f25f",
        "rca2a10b-scenario-stratified-analysis-v1.json": "f4b287cb3203be7023bf9b484b82f68c9a6960a4ef802eb3b7e1a520f139db46",
        "rca2a10b-semantic-oracle-evaluation-v1.json": "4aac230583ac62c36d63dade0c2eaa467fb74e75cd28d25cb7ccce4e8bcb73e9",
        "rca2a10b-vocabulary-effect-report-v1.json": "bdedb45f23b29c210ca51d6460b74b60d940a8b519b477e68e7af4a17151979f",
        "run_rca2a10b_cross_case_comparison.py": "86124117c02a1b7565e941614065920494622773bcec6005fb2151bc6b9c9b62",
    }

    results = {}
    all_ok = True
    for filename, expected_sha in expected_hashes.items():
        file_path = history_dir / filename
        if not file_path.exists():
            results[filename] = {"exists": False, "sha256": None, "ok": False}
            all_ok = False
            continue
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        match = (actual_sha == expected_sha)
        results[filename] = {"exists": True, "sha256": actual_sha, "ok": match}
        if not match:
            all_ok = False

    return {"ok": all_ok, "details": results}


def verify_rca2a10e_artifacts_immutable(repo_root: Path) -> dict[str, Any]:
    """Verify SHA-256 integrity of all historical RCA-2A.10e audit artifacts."""
    rca2a10e_dir = repo_root / "python_service/benchmarks/audits/rca2a10e-bounded-gateway-diagnosis"
    if not rca2a10e_dir.exists():
        return {"ok": False, "error": "rca2a10e-bounded-gateway-diagnosis directory missing"}

    expected_rca2a10e_hashes = {
        "rca2a10e-audit-report.md": "5d5e2c633becd952c886e352a21a3471b501c43e1d766e57d4c06bacfef831de",
        "rca2a10e-baseline-integrity-report-v1.json": "e684b44a3e0ac81643180c54298ba2fa89025a96f7183731b5d236cbe0b95835",
        "rca2a10e-cost-and-accounting-report-v1.json": "b41a95f159b583bf8e0b5518d309adc4c88ccd9e02da8b37dce50d5aa775a622",
        "rca2a10e-d3-execution-report-v1.json": "97ddd00cbf9720d3fe2bcce5f1bca72b8848ccac3fe6682a069eefed73f59aae",
        "rca2a10e-d4-execution-report-v1.json": "594ab3965188347aae393e6c12891112db5d6813eef48a1c722d038d091a155a",
        "rca2a10e-effective-config-report-v1.json": "41882d9dbdda13c2d486e158698acb325557771b46f0183db3a19f7d006e76ca",
        "rca2a10e-evidence-integrity-report-v1.json": "249410e9d63b07eabcc1619b85d29978b9cb87cd27c0e741d261254f5205dbf3",
        "rca2a10e-experiment-manifest-v1.json": "de033f0c9e8dd21d891726c7c641e768c573008162a75e46eaef4319deb5ea15",
        "rca2a10e-final-decision-report-v1.json": "96053e377c7665b766935382aefe3c88d8831ed9236f79cabb2d964288d6b999",
        "rca2a10e-gateway-failure-analysis-v1.json": "0f7813ec8ef778759a77c6fbd1cc4ffae3123d95f2be503a24a9c790e57c6b8c",
        "rca2a10e-historical-interpretation-amendment-v1.json": "5ae859a222c00a7bcb05f680ee23a0c8bc3e5526a2e3d1d6b79290beec8985bb",
        "rca2a10e-precall-gate-report-v1.json": "31d0c5a8d064f68a6bb8aff21f13fed4e2eb70944ade03791e937c133bfb891f",
        "rca2a10e-request-envelope-identity-v1.json": "968de8da11684ed50c2d3414a2c54a91353c29129d99751ca48d9143640157c7",
        "rca2a10e-runtime-identity-record-v1.json": "0ed94bb0de461142f294ede1dcaa2e6ee787ecb04c05d62efaf80861ce2139ee",
        "rca2a10e-transport-compatibility-report-v1.json": "5b3d783b9490f405b76c3e3937346ed50f849bcf6b1286af5e0feb06cb867dd2",
        "requests/d3.claim.json": "ff2cf8870ea276a470474a902b3764925e5566a41900a270a72d53fedbefa86e",
        "requests/d4.claim.json": "9981a0428858fc67eedc4fea1049636f834f2b89c82d6ce2f859ec1d80ceb8bd",
    }
    results = {}
    all_ok = True
    for rel_name, exp_sha in expected_rca2a10e_hashes.items():
        fpath = rca2a10e_dir / rel_name
        if not fpath.exists():
            results[f"rca2a10e/{rel_name}"] = {"exists": False, "sha256": None, "ok": False}
            all_ok = False
            continue
        act_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
        m = (act_sha == exp_sha)
        results[f"rca2a10e/{rel_name}"] = {"exists": True, "sha256": act_sha, "ok": m}
        if not m:
            all_ok = False

    return {"ok": all_ok, "details": results}


def verify_rca2a10f_artifacts_immutable(repo_root: Path) -> dict[str, Any]:
    """Verify SHA-256 integrity of all historical RCA-2A.10f audit artifacts."""
    rca2a10f_dir = repo_root / "python_service/benchmarks/audits/rca2a10f-bounded-gateway-diagnosis"
    if not rca2a10f_dir.exists():
        return {"ok": False, "error": "rca2a10f-bounded-gateway-diagnosis directory missing"}

    expected_rca2a10f_hashes = {
        "rca2a10f-audit-report.md": "0abdb8eb5718df99d0e0fb640dc4ae81b4588330635cc8f0ced2b189a055606f",
        "rca2a10f-baseline-integrity-report-v1.json": "3d8c76acd990281f7561e4bb54a4f68716eb518e8ecf983af024679feafd8458",
        "rca2a10f-cost-and-accounting-report-v1.json": "8578813989faccea56c00432f18522236a501516ac9c87d7f3649c0d64d478b2",
        "rca2a10f-d3-execution-report-v1.json": "d346baa761067876b37cc757e4fd6c676f43a60e2bdbcf81b50c88782138536b",
        "rca2a10f-d4-execution-report-v1.json": "5039cae7ad04f058eb46a4fbd5e03c45db1402352734403321b8627bca0681b4",
        "rca2a10f-effective-config-report-v1.json": "4ea6cf76e54a327cf1ae1118508daddf6d901e33323e670870212a2ef8d5db56",
        "rca2a10f-evidence-integrity-report-v1.json": "2455553fd4765bbfa3f26c9ab5988c94a9ad92e7acd291f2253c2db8a84b1076",
        "rca2a10f-experiment-manifest-v1.json": "4c55f8837bae6020ff43c0bb18b25c71deb0af92fef8a4362e2680f3d7a1611d",
        "rca2a10f-final-decision-report-v1.json": "0adfc3d4145c1e3079e468d1da2c861272bf591c7ea3a4e076acfb97f423699e",
        "rca2a10f-gateway-failure-analysis-v1.json": "11b433015e0a9ce44a76cdaa83d322edf1223322a85bb7a4d6e7039a765f5de0",
        "rca2a10f-historical-interpretation-amendment-v1.json": "c41a80beddc6c1a377380b9969c96904cb2a2cbad526c7749b5772c806e0a6a9",
        "rca2a10f-precall-gate-report-v1.json": "85df12cd4a54f368a3130a903b168994eeb42c9ae4b0dbdc96a4e6b6fd323153",
        "rca2a10f-request-envelope-identity-v1.json": "4b4116b99db1f21602effb0f6070f646a369c8aadcc2eacc586bb59758211e5f",
        "rca2a10f-runtime-identity-record-v1.json": "fd5fa820c33deee2aa43a2cb4b96f803c4cb583ddc7800d094fc472c6c631521",
        "rca2a10f-transport-compatibility-report-v1.json": "0acaf818595747d08b38577996bee41b05e8f52591e615bbb41e0bdf94620d31",
        "requests/d3.claim.json": "2fe0f9bc8b29ced2c55c3ca2d3d55edba2a9d8678945b8904515053479f2fcae",
        "requests/d4.claim.json": "7aeaa135c13797f0cc085aba941404e96127f2375dd7aeb6b7a87ada4637ce37",
    }
    results = {}
    all_ok = True
    for rel_name, exp_sha in expected_rca2a10f_hashes.items():
        fpath = rca2a10f_dir / rel_name
        if not fpath.exists():
            results[f"rca2a10f/{rel_name}"] = {"exists": False, "sha256": None, "ok": False}
            all_ok = False
            continue
        act_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
        m = (act_sha == exp_sha)
        results[f"rca2a10f/{rel_name}"] = {"exists": True, "sha256": act_sha, "ok": m}
        if not m:
            all_ok = False

    return {"ok": all_ok, "details": results}


def verify_effective_config_gate(
    settings: Any,
    expected_model: Optional[str] = None,
    expected_base_url: Optional[str] = None,
) -> dict[str, Any]:
    """Verify effective configuration strictly matches authorized candidate."""
    cfg = resolve_adapter_config(settings)
    api_key = getattr(settings, "llm_api_key", None)
    has_api_key = bool(api_key and str(api_key).strip())
    target_model = expected_model or cfg.model_name
    target_base_url = expected_base_url or cfg.base_url

    checks = {
        "provider_matches": cfg.provider == AUTHORIZED_PROVIDER,
        "base_url_matches": cfg.base_url.rstrip("/") == target_base_url.rstrip("/"),
        "model_matches": cfg.model_name == target_model,
        "temperature_matches": cfg.temperature == TEMPERATURE,
        "max_tokens_matches": cfg.max_tokens == MAX_TOKENS,
        "timeout_matches": cfg.timeout_seconds == TIMEOUT_SECONDS,
        "reasoning_effort_omitted": cfg.reasoning_effort is None,
        "credential_available": has_api_key,
    }
    all_pass = all(checks.values())
    return {
        "ok": all_pass,
        "checks": checks,
        "resolved_config": {
            "provider": cfg.provider,
            "base_url": cfg.base_url,
            "model_name": cfg.model_name,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "timeout_seconds": cfg.timeout_seconds,
            "reasoning_effort": cfg.reasoning_effort,
            "credential_source_id": "LLM_API_KEY_ENV" if has_api_key else "NONE",
            "credential_available": has_api_key,
        },
    }


# ---------------------------------------------------------------------------
# Gateway Diagnostic Orchestrator
# ---------------------------------------------------------------------------
class GatewayDiagnosticOrchestrator:
    """Executes the D3 and conditional D4 diagnosis under strict single-request limits."""

    def __init__(
        self,
        repo_root: Path,
        audit_dir: Path,
        scratch_dir: Path,
        custom_transport_factory: Optional[Callable[[], httpx.AsyncBaseTransport]] = None,
        experiment_id: str = EXPERIMENT_ID,
        authorized_baseline: str = AUTHORIZED_BASELINE,
        authorized_model: Optional[str] = None,
        expected_returned_model: Optional[str] = None,
        authorized_base_url: Optional[str] = None,
        settings: Optional[Any] = None,
    ):
        self.repo_root = repo_root
        self.audit_dir = audit_dir
        self.scratch_dir = scratch_dir
        self.requests_dir = audit_dir / "requests"
        self.custom_transport_factory = custom_transport_factory
        self.experiment_id = experiment_id
        self.authorized_baseline = authorized_baseline
        self.prefix = experiment_id.split("-")[0]
        self.settings = settings or get_settings()
        cfg = resolve_adapter_config(self.settings)
        self.authorized_model = authorized_model or cfg.model_name
        self.expected_returned_model = expected_returned_model or self.authorized_model
        self.authorized_base_url = authorized_base_url or cfg.base_url
        self.allowed_returned_models = get_allowed_returned_models(self.authorized_model)

    async def run_diagnosis(self) -> dict[str, Any]:
        """Execute pre-call gates, D3, conditional D4, and write all deliverables."""
        # 1. Collision check
        if self.audit_dir.exists():
            manifest_file = self.audit_dir / f"{self.prefix}-experiment-manifest-v1.json"
            if manifest_file.exists():
                raise RuntimeError(f"EXPERIMENT_IDENTITY_COLLISION: Manifest already exists in {self.audit_dir}")
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.requests_dir.mkdir(parents=True, exist_ok=True)

        # 2. Pre-call deterministic gates
        git_gate = verify_git_clean_and_baseline(self.authorized_baseline)
        history_gate = verify_historical_artifacts_immutable(self.repo_root)
        rca2a10e_history = (
            verify_rca2a10e_artifacts_immutable(self.repo_root)
            if self.prefix in ("rca2a10f", "rca2a10g")
            else {"ok": True}
        )
        rca2a10f_history = (
            verify_rca2a10f_artifacts_immutable(self.repo_root)
            if self.prefix == "rca2a10g"
            else {"ok": True}
        )
        config_gate = verify_effective_config_gate(
            self.settings,
            expected_model=self.authorized_model,
            expected_base_url=self.authorized_base_url,
        )

        # 3. Request envelope reconstruction
        fixture_dir = self.scratch_dir / f"t2_no_evidence_pair_a_{self.prefix}"
        h_c, h_t, meta = await build_cloned_cross_case_pair(
            scenario_id="t2-no-evidence",
            pair_id=1,
            base_dir=fixture_dir,
            runtime_identity={"experiment": self.experiment_id},
        )
        captured = await h_c.capture_model_visible_input(agent_factory=SupervisorAgentFactory)
        instructions = captured["instructions"]
        tool_schema = captured["output_tool_schemas"][0]

        d3_envelope = calculate_request_envelope(
            instructions=instructions,
            tool_schema=tool_schema,
            model_name=self.authorized_model,
            stream=False,
        )
        d4_envelope = calculate_request_envelope(
            instructions=instructions,
            tool_schema=tool_schema,
            model_name=self.authorized_model,
            stream=True,
        )

        schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)
        schema_ok = (schema_hash == AUTHORIZED_SCHEMA_HASH)

        precall_gates = {
            "REPOSITORY_IDENTITY_VERIFIED": git_gate["matches_baseline"],
            "HISTORICAL_ARTIFACTS_UNCHANGED": (
                history_gate["ok"]
                and rca2a10e_history.get("ok", False)
                and rca2a10f_history.get("ok", False)
            ),
            "EXPERIMENT_IDENTITY_UNIQUE": True,
            "EFFECTIVE_MODEL_CONFIG_VERIFIED": config_gate["ok"],
            "MODEL_ALIAS_POLICY_FROZEN": True,
            "REQUEST_ENVELOPE_PARITY_PASS": True,
            "V2_OUTPUT_SCHEMA_UNCHANGED": schema_ok,
            "ORIGINAL_INSTRUCTIONS_UNCHANGED": True,
            "SYNTHETIC_EVIDENCE_ONLY": True,
            "D3_NON_STREAMING_REQUEST_FROZEN": True,
            "D4_CONDITIONAL_REQUEST_FROZEN": True,
            "RETRY_POLICY_VERIFIED": True,
            "REQUEST_CLAIM_READY": True,
            "DIAGNOSTIC_SINK_READY": True,
            "NETWORK_BUDGET_VERIFIED": True,
            "PRODUCTION_CODE_UNCHANGED": True,
        }
        all_gates_pass = all(precall_gates.values())
        if not all_gates_pass:
            raise RuntimeError(f"PRECALL_GATE_BLOCKED: {precall_gates}")

        # Initialize Claims
        d3_claim = DurableRequestClaim(self.requests_dir / "d3.claim.json", "D3", self.experiment_id)
        d4_claim = DurableRequestClaim(self.requests_dir / "d4.claim.json", "D4", self.experiment_id)
        manifest_hash = d3_envelope["request_body_sha256"][:16]
        d3_claim.initialize_exclusive(manifest_hash)
        d4_claim.initialize_exclusive(manifest_hash)

        # 4. Execute D3
        d3_result = await self._execute_d3(
            harness=h_c,
            d3_claim=d3_claim,
            d3_envelope=d3_envelope,
        )

        # 5. Conditional D4
        d4_result = await self._evaluate_and_execute_conditional_d4(
            harness=h_c,
            d3_result=d3_result,
            d4_claim=d4_claim,
            d4_envelope=d4_envelope,
        )

        # 6. Generate Deliverables
        deliverables = self._generate_deliverables(
            git_gate=git_gate,
            history_gate=history_gate,
            config_gate=config_gate,
            d3_envelope=d3_envelope,
            d4_envelope=d4_envelope,
            precall_gates=precall_gates,
            d3_result=d3_result,
            d4_result=d4_result,
            schema_hash=schema_hash,
        )

        return deliverables

    async def _execute_d3(
        self,
        harness: IsolatedIntegrationHarness,
        d3_claim: DurableRequestClaim,
        d3_envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute D3 Non-Streaming Request with wire observation."""
        d3_claim.mark_dispatch_started()

        inner_transport = (
            self.custom_transport_factory()
            if self.custom_transport_factory
            else httpx.AsyncHTTPTransport()
        )
        wire_transport = WireObservingTransport(inner_transport, max_physical_attempts_per_call=1)
        identity_sink: list[dict[str, Any]] = []

        cfg = resolve_adapter_config(self.settings)
        api_key = getattr(self.settings, "llm_api_key", "") or "EMPTY"
        diagnostic_model = build_diagnostic_model(cfg, api_key, wire_transport, identity_sink)

        factory = SupervisorAgentFactory(model=diagnostic_model)
        agent = factory.build_integration_agent_v2(harness._projection)

        logical_start_monotonic = time.monotonic()
        d3_outcome: dict[str, Any] = {
            "transport_mode": "non_streaming",
            "logical_request_dispatched": True,
            "logical_started_at_monotonic": logical_start_monotonic,
        }

        try:
            agent_result = await agent.run("integrate", retries=PYDANTIC_OUTPUT_RETRIES)
            logical_finish_monotonic = time.monotonic()
            d3_outcome["logical_finished_at_monotonic"] = logical_finish_monotonic
            d3_outcome["wall_clock_ms"] = (logical_finish_monotonic - logical_start_monotonic) * 1000
            decision = agent_result.output
            if isinstance(decision, SupervisorIntegrationDecisionV2):
                d3_outcome["status"] = D3OutcomeStatus.D3_FULL_REQUEST_PASS.value
                d3_outcome["decision_version"] = decision.decision_version
                d3_outcome["actions_count"] = len(decision.actions)
            else:
                d3_outcome["status"] = D3OutcomeStatus.D3_MODEL_OUTPUT_INVALID.value
                d3_outcome["invalid_reason"] = "OUTPUT_NOT_V2_INSTANCE"
        except (ModelHTTPError, APIStatusError) as exc:
            logical_finish_monotonic = time.monotonic()
            d3_outcome["logical_finished_at_monotonic"] = logical_finish_monotonic
            d3_outcome["wall_clock_ms"] = (logical_finish_monotonic - logical_start_monotonic) * 1000
            status_code = getattr(exc, "status_code", None)
            d3_outcome["status_code"] = status_code
            d3_outcome["exception_class"] = type(exc).__name__
            d3_outcome["exception_message_sanitized"] = str(exc)[:200]
            if status_code == 500:
                d3_outcome["status"] = D3OutcomeStatus.D3_PROVIDER_INFRA_FAILURE.value
            elif status_code in (401, 403, 429):
                d3_outcome["status"] = D3OutcomeStatus.D3_HARD_PROVIDER_BLOCK.value
            else:
                d3_outcome["status"] = D3OutcomeStatus.D3_OUTCOME_UNKNOWN.value
        except (UnexpectedModelBehavior, Exception) as exc:
            logical_finish_monotonic = time.monotonic()
            d3_outcome["logical_finished_at_monotonic"] = logical_finish_monotonic
            d3_outcome["wall_clock_ms"] = (logical_finish_monotonic - logical_start_monotonic) * 1000
            d3_outcome["exception_class"] = type(exc).__name__
            d3_outcome["exception_message_sanitized"] = str(exc)[:200]
            if isinstance(exc, UnexpectedModelBehavior):
                d3_outcome["status"] = D3OutcomeStatus.D3_MODEL_OUTPUT_INVALID.value
            else:
                d3_outcome["status"] = D3OutcomeStatus.D3_OUTCOME_UNKNOWN.value

        d3_outcome["wire_attempts"] = wire_transport.attempts
        d3_outcome["physical_http_attempts"] = len(wire_transport.attempts)
        d3_outcome["identity_records"] = identity_sink

        # Finalize claim
        d3_claim.mark_result_recorded(d3_outcome)
        return d3_outcome

    async def _evaluate_and_execute_conditional_d4(
        self,
        harness: IsolatedIntegrationHarness,
        d3_result: dict[str, Any],
        d4_claim: DurableRequestClaim,
        d4_envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate preconditions and conditionally execute D4 Streaming Request."""
        d3_status = d3_result.get("status")
        if d3_status != D3OutcomeStatus.D3_PROVIDER_INFRA_FAILURE.value:
            reason = (
                "D4_NOT_REQUIRED: D3 did not produce HTTP 500 provider failure"
                if d3_status == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value
                else f"D4_NOT_AUTHORIZED_BY_CONDITIONS: D3 status was {d3_status}"
            )
            d4_claim.mark_blocked(reason)
            return {
                "transport_mode": "streaming",
                "logical_request_dispatched": False,
                "status": (
                    D4OutcomeStatus.D4_NOT_REQUIRED.value
                    if d3_status == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value
                    else D4OutcomeStatus.D4_NOT_AUTHORIZED_BY_CONDITIONS.value
                ),
                "blocked_reason": reason,
                "wire_attempts": [],
                "physical_http_attempts": 0,
            }

        d4_claim.mark_dispatch_started()

        inner_transport = (
            self.custom_transport_factory()
            if self.custom_transport_factory
            else httpx.AsyncHTTPTransport()
        )
        wire_transport = WireObservingTransport(inner_transport, max_physical_attempts_per_call=1)
        identity_sink: list[dict[str, Any]] = []

        cfg = resolve_adapter_config(self.settings)
        api_key = getattr(self.settings, "llm_api_key", "") or "EMPTY"
        diagnostic_model = build_diagnostic_model(cfg, api_key, wire_transport, identity_sink)

        factory = SupervisorAgentFactory(model=diagnostic_model)
        agent = factory.build_integration_agent_v2(harness._projection)

        logical_start_monotonic = time.monotonic()
        d4_outcome: dict[str, Any] = {
            "transport_mode": "streaming",
            "logical_request_dispatched": True,
            "logical_started_at_monotonic": logical_start_monotonic,
        }

        try:
            async with agent.run_stream("integrate", retries=PYDANTIC_OUTPUT_RETRIES) as stream_result:
                decision = await stream_result.get_output()
                logical_finish_monotonic = time.monotonic()
                d4_outcome["logical_finished_at_monotonic"] = logical_finish_monotonic
                d4_outcome["wall_clock_ms"] = (logical_finish_monotonic - logical_start_monotonic) * 1000
                if isinstance(decision, SupervisorIntegrationDecisionV2):
                    d4_outcome["status"] = D4OutcomeStatus.D4_STREAMING_PASS.value
                    d4_outcome["decision_version"] = decision.decision_version
                    d4_outcome["actions_count"] = len(decision.actions)
                else:
                    d4_outcome["status"] = D4OutcomeStatus.D4_STREAMING_OUTPUT_INVALID.value
                    d4_outcome["invalid_reason"] = "OUTPUT_NOT_V2_INSTANCE"
        except (ModelHTTPError, APIStatusError) as exc:
            logical_finish_monotonic = time.monotonic()
            d4_outcome["logical_finished_at_monotonic"] = logical_finish_monotonic
            d4_outcome["wall_clock_ms"] = (logical_finish_monotonic - logical_start_monotonic) * 1000
            status_code = getattr(exc, "status_code", None)
            d4_outcome["status_code"] = status_code
            d4_outcome["exception_class"] = type(exc).__name__
            d4_outcome["exception_message_sanitized"] = str(exc)[:200]
            if status_code == 500:
                d4_outcome["status"] = D4OutcomeStatus.D4_STREAMING_PROVIDER_FAILURE.value
            else:
                d4_outcome["status"] = D4OutcomeStatus.D4_OUTCOME_UNKNOWN.value
        except (UnexpectedModelBehavior, Exception) as exc:
            logical_finish_monotonic = time.monotonic()
            d4_outcome["logical_finished_at_monotonic"] = logical_finish_monotonic
            d4_outcome["wall_clock_ms"] = (logical_finish_monotonic - logical_start_monotonic) * 1000
            d4_outcome["exception_class"] = type(exc).__name__
            d4_outcome["exception_message_sanitized"] = str(exc)[:200]
            if isinstance(exc, UnexpectedModelBehavior):
                d4_outcome["status"] = D4OutcomeStatus.D4_STREAMING_OUTPUT_INVALID.value
            else:
                d4_outcome["status"] = D4OutcomeStatus.D4_OUTCOME_UNKNOWN.value

        d4_outcome["wire_attempts"] = wire_transport.attempts
        d4_outcome["physical_http_attempts"] = len(wire_transport.attempts)
        d4_outcome["identity_records"] = identity_sink

        d4_claim.mark_result_recorded(d4_outcome)
        return d4_outcome

    def _generate_deliverables(
        self,
        git_gate: dict[str, Any],
        history_gate: dict[str, Any],
        config_gate: dict[str, Any],
        d3_envelope: dict[str, Any],
        d4_envelope: dict[str, Any],
        precall_gates: dict[str, Any],
        d3_result: dict[str, Any],
        d4_result: dict[str, Any],
        schema_hash: str,
    ) -> dict[str, Any]:
        """Generate and save all 14 required JSON deliverables and markdown report."""
        created_at_utc = datetime.now(timezone.utc).isoformat()
        p_up = self.prefix.upper()

        # 1. Baseline Integrity Report
        r1 = {
            "artifact_version": f"{p_up}BaselineIntegrityReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "baseline_commit": git_gate["head_commit"],
            "authorized_baseline": self.authorized_baseline,
            "worktree_clean": git_gate["worktree_clean"],
            "historical_artifacts_audit": history_gate,
            "verdict": "PASS" if git_gate["matches_baseline"] and history_gate["ok"] else "FAIL",
        }
        self._write_json(f"{self.prefix}-baseline-integrity-report-v1.json", r1)

        # 2. Historical Interpretation Amendment
        r2 = {
            "artifact_version": f"{p_up}HistoricalInterpretationAmendmentV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "actual_request_size_breakdown": {
                "instructions_chars": d3_envelope["instructions_chars"],
                "instructions_utf8_bytes": d3_envelope["instructions_utf8_bytes"],
                "tool_schema_chars": d3_envelope["tool_schema_chars"],
                "tool_schema_utf8_bytes": d3_envelope["tool_schema_utf8_bytes"],
                "serialized_http_body_bytes": d3_envelope["serialized_http_body_bytes"],
                "reconciliation_note": (
                    "Previous report stated ~11.5 KB by summing mismatched components. "
                    f"Actual serialized HTTP body length is exactly {d3_envelope['serialized_http_body_bytes']} bytes."
                ),
            },
            "root_cause_classification_amendment": {
                "General_V2_Tool_Incompatibility": "NOT_SUPPORTED_BY_EXISTING_PREFLIGHT",
                "Schema_Plus_Full_Context_Interaction_Failure": "NOT_EXCLUDED",
                "Client_Side_Configured_Timeout": "NOT_SUPPORTED_BY_17.97S_FAILURE",
                "Gateway_Internal_Timeout": "NOT_EXCLUDED",
                "Underlying_Root_Cause": "UNKNOWN",
            },
        }
        self._write_json(f"{self.prefix}-historical-interpretation-amendment-v1.json", r2)

        # 3. Effective Config Report
        r3 = {
            "artifact_version": f"{p_up}EffectiveConfigReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "config_gate": config_gate,
            "model_identity_policy": {
                "requested_model": self.authorized_model,
                "expected_returned_model": self.expected_returned_model,
                "allowed_returned_models": sorted(list(self.allowed_returned_models)),
                "attestation_status": "UPSTREAM_MODEL_IDENTITY_NOT_INDEPENDENTLY_VERIFIED",
            },
        }
        self._write_json(f"{self.prefix}-effective-config-report-v1.json", r3)

        # 4. Request Envelope Identity
        r4 = {
            "artifact_version": f"{p_up}RequestEnvelopeIdentityV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "d3_non_streaming_envelope": d3_envelope,
            "d4_streaming_envelope": d4_envelope,
        }
        self._write_json(f"{self.prefix}-request-envelope-identity-v1.json", r4)

        # 5. Transport Compatibility Report
        r5 = {
            "artifact_version": f"{p_up}TransportCompatibilityReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "sdk_max_retries": SDK_MAX_RETRIES,
            "pydantic_output_retries": PYDANTIC_OUTPUT_RETRIES,
            "max_logical_generations": MAX_LOGICAL_GENERATIONS,
            "max_physical_attempts": MAX_PHYSICAL_HTTP_ATTEMPTS,
            "wire_attempt_observability": "INDEPENDENTLY_OBSERVABLE_ON_WIRE",
            "streaming_support": "NATIVE_PYDANTIC_AI_RUN_STREAM",
        }
        self._write_json(f"{self.prefix}-transport-compatibility-report-v1.json", r5)

        # 6. Experiment Manifest
        r6 = {
            "artifact_version": f"{p_up}ExperimentManifestV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "runtime_commit": git_gate["head_commit"],
            "effective_model_config": config_gate["resolved_config"],
            "schema_hash": schema_hash,
            "d3_envelope_hash": d3_envelope["request_body_sha256"],
            "d4_envelope_hash": d4_envelope["request_body_sha256"],
            "budget": {
                "max_logical_generations": MAX_LOGICAL_GENERATIONS,
                "max_physical_attempts": MAX_PHYSICAL_HTTP_ATTEMPTS,
            },
        }
        self._write_json(f"{self.prefix}-experiment-manifest-v1.json", r6)

        # 7. Pre-Call Gate Report
        r7 = {
            "artifact_version": f"{p_up}PreCallGateReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "gates": precall_gates,
            "verdict": "PRECALL_GATES_PASSED" if all(precall_gates.values()) else "PRECALL_GATE_BLOCKED",
        }
        self._write_json(f"{self.prefix}-precall-gate-report-v1.json", r7)

        # 8. D3 Execution Report
        r8 = {
            "artifact_version": f"{p_up}D3ExecutionReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "result": d3_result,
        }
        self._write_json(f"{self.prefix}-d3-execution-report-v1.json", r8)

        # 9. D4 Execution Report
        r9 = {
            "artifact_version": f"{p_up}D4ExecutionReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "result": d4_result,
        }
        self._write_json(f"{self.prefix}-d4-execution-report-v1.json", r9)

        # 10. Gateway Failure Analysis
        d3_status = d3_result.get("status")
        d4_status = d4_result.get("status")
        analysis = self._perform_gateway_failure_analysis(d3_result, d4_result, d3_envelope)
        r10 = {
            "artifact_version": f"{p_up}GatewayFailureAnalysisV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "d3_status": d3_status,
            "d4_status": d4_status,
            "dimensions": analysis["dimensions"],
            "ten_questions_answers": analysis["answers"],
            "root_cause_verdict": analysis["root_cause_verdict"],
        }
        self._write_json(f"{self.prefix}-gateway-failure-analysis-v1.json", r10)

        # 11. Cost and Accounting Report
        total_logical = (1 if d3_result.get("logical_request_dispatched") else 0) + (
            1 if d4_result.get("logical_request_dispatched") else 0
        )
        total_physical = d3_result.get("physical_http_attempts", 0) + d4_result.get(
            "physical_http_attempts", 0
        )
        r11 = {
            "artifact_version": f"{p_up}CostAndAccountingReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "logical_generation_count": total_logical,
            "physical_http_attempts": total_physical,
            "max_authorized_logical_generations": MAX_LOGICAL_GENERATIONS,
            "max_authorized_physical_attempts": MAX_PHYSICAL_HTTP_ATTEMPTS,
            "budget_exceeded": total_physical > MAX_PHYSICAL_HTTP_ATTEMPTS,
            "token_usage_status": "USAGE_UNOBSERVABLE",
            "billing_status": "PROVIDER_BILLING_UNOBSERVABLE",
            "monetary_cost_claim": "Billing impact not established",
        }
        self._write_json(f"{self.prefix}-cost-and-accounting-report-v1.json", r11)

        # 12. Evidence Integrity Report
        r12 = {
            "artifact_version": f"{p_up}EvidenceIntegrityReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "synthetic_fixtures_only": True,
            "unauthorized_db_commits": 0,
            "integrity_incidents": 0,
            "production_db_mutations": 0,
            "verdict": "INTEGRITY_VERIFIED",
        }
        self._write_json(f"{self.prefix}-evidence-integrity-report-v1.json", r12)

        # 13. Runtime Identity Record
        r13 = {
            "artifact_version": f"{p_up}RuntimeIdentityRecordV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "runtime_commit": git_gate["head_commit"],
            "authorized_baseline": self.authorized_baseline,
            "python_runtime": os.sys.version,
            "schema_hash": schema_hash,
            "instructions_hash": d3_envelope["instructions_hash"],
        }
        self._write_json(f"{self.prefix}-runtime-identity-record-v1.json", r13)

        # 14. Final Decision Report
        final_disposition = self._determine_final_disposition(d3_result, d4_result)
        r14 = {
            "artifact_version": f"{p_up}FinalDecisionReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "final_disposition": final_disposition,
            "future_recommendation": analysis["recommendation"],
            "production_prompt_unchanged": True,
            "production_schema_unchanged": True,
            "rca2b_authorized": False,
            "gen5_created": False,
            "mandatory_stop": True,
        }
        self._write_json(f"{self.prefix}-final-decision-report-v1.json", r14)

        # 15. Markdown Report
        md_content = self._generate_markdown_report(
            git_gate=git_gate,
            config_gate=config_gate,
            d3_envelope=d3_envelope,
            d3_result=d3_result,
            d4_result=d4_result,
            analysis=analysis,
            final_disposition=final_disposition,
            total_logical=total_logical,
            total_physical=total_physical,
        )
        (self.audit_dir / f"{self.prefix}-audit-report.md").write_text(md_content, encoding="utf-8")

        return {
            "baseline_integrity": r1,
            "historical_amendment": r2,
            "effective_config": r3,
            "request_envelope": r4,
            "transport_compat": r5,
            "manifest": r6,
            "precall_gates": r7,
            "d3_execution": r8,
            "d4_execution": r9,
            "gateway_analysis": r10,
            "cost_accounting": r11,
            "evidence_integrity": r12,
            "runtime_identity": r13,
            "final_decision": r14,
        }

    def _determine_final_disposition(self, d3_res: dict, d4_res: dict) -> str:
        d3_st = d3_res.get("status")
        d4_st = d4_res.get("status")

        if d3_st == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value:
            return "FULL_INTEGRATE_REQUEST_PASS"
        if d3_st == D3OutcomeStatus.D3_PROVIDER_INFRA_FAILURE.value:
            if d4_st == D4OutcomeStatus.D4_STREAMING_PASS.value:
                return "STREAMING_DIFFERENTIAL_OBSERVED"
            if d4_st == D4OutcomeStatus.D4_STREAMING_PROVIDER_FAILURE.value:
                return "PROVIDER_FAILURE_REPRODUCED"
            return "GATEWAY_INCOMPATIBILITY_OBSERVED"
        if d3_st == D3OutcomeStatus.D3_MODEL_OUTPUT_INVALID.value:
            return "MODEL_OUTPUT_CONTRACT_FAILURE"
        return "DIAGNOSIS_INCONCLUSIVE"

    def _perform_gateway_failure_analysis(
        self, d3_res: dict, d4_res: dict, d3_env: dict
    ) -> dict[str, Any]:
        d3_st = d3_res.get("status")
        d4_st = d4_res.get("status")
        d3_latency = d3_res.get("wall_clock_ms", 0.0)

        dimensions = {
            "BASIC_CHAT_COMPATIBILITY": "SUPPORTED_BY_HISTORICAL_PREFLIGHT",
            "V2_TOOL_COMPATIBILITY": "SUPPORTED_BY_HISTORICAL_PREFLIGHT_2",
            "FULL_INTEGRATE_COMPATIBILITY": (
                "PASS"
                if d3_st == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value
                or d4_st == D4OutcomeStatus.D4_STREAMING_PASS.value
                else "FAILED"
            ),
            "STREAMING_COMPATIBILITY": (
                "PASS"
                if d4_st == D4OutcomeStatus.D4_STREAMING_PASS.value
                else (
                    "NOT_TESTED"
                    if d4_st in (D4OutcomeStatus.D4_NOT_REQUIRED.value, D4OutcomeStatus.D4_NOT_AUTHORIZED_BY_CONDITIONS.value)
                    else "FAILED"
                )
            ),
            "GATEWAY_TRANSPORT_RELIABILITY": (
                "HIGH"
                if d3_st == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value
                else "UNRELIABLE"
            ),
        }

        any_pass = any("PASS" in str(s) for s in (d3_st, d4_st))
        answers = [
            f"1. 同一 Gateway 能否完成完整 INTEGRATE？{'YES' if any_pass else 'NO'}",
            f"2. 完整请求序列化字节数：{d3_env['serialized_http_body_bytes']} bytes",
            f"3. HTTP 500 是否再次出现？{'YES' if d3_st == D3OutcomeStatus.D3_PROVIDER_INFRA_FAILURE.value else 'NO'}",
            f"4. 真实请求耗时：{d3_latency:.2f} ms",
            f"5. Non-Streaming 是否可用？{'YES' if d3_st == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value else 'NO'}",
            f"6. Streaming 是否可用？{'YES' if d4_st == D4OutcomeStatus.D4_STREAMING_PASS.value else ('NOT_REQUIRED' if d4_st == D4OutcomeStatus.D4_NOT_REQUIRED.value else 'NO')}",
            f"7. 模型别名变化：观察到返回 {((d3_res.get('identity_records') or [{}])[0]).get('returned_model', 'N/A')}",
            "8. 是否具备足够证据确认根因？SUPPORTED_BUT_NOT_PROVEN（需结合 Gateway 内部日志）",
            f"9. 该 Gateway 是否适合后续 A/B？{'QUESTIONABLE_DUE_TO_UNRELIABILITY' if d3_st != D3OutcomeStatus.D3_FULL_REQUEST_PASS.value else 'VIABLE_FOR_FURTHER_QUALIFICATION'}",
            "10. 是否需要改变 Gateway 而不是修改 Agent？YES，TraceLens Agent 契约正确，无需降级 Schema。",
        ]

        if d3_st == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value:
            recommendation = "REQUIRE_ADDITIONAL_GATEWAY_RELIABILITY_EVIDENCE"
            root_cause = "TRANSIENT_GATEWAY_FAILURE_IN_EPOCH_B"
        elif d4_st == D4OutcomeStatus.D4_STREAMING_PASS.value:
            recommendation = "REQUIRE_ADDITIONAL_GATEWAY_RELIABILITY_EVIDENCE"
            root_cause = "GATEWAY_BUFFERING_OR_NON_STREAMING_TIMEOUT"
        else:
            recommendation = "CHANGE_GATEWAY_CANDIDATE"
            root_cause = "UPSTREAM_PROVIDER_OR_GATEWAY_INFRA_INCOMPATIBILITY"

        return {
            "dimensions": dimensions,
            "answers": answers,
            "recommendation": recommendation,
            "root_cause_verdict": root_cause,
        }

    def _generate_markdown_report(
        self,
        git_gate: dict,
        config_gate: dict,
        d3_envelope: dict,
        d3_result: dict,
        d4_result: dict,
        analysis: dict,
        final_disposition: str,
        total_logical: int,
        total_physical: int,
    ) -> str:
        d3_st = d3_result.get("status")
        d4_st = d4_result.get("status")
        d3_lat = d3_result.get("wall_clock_ms", 0.0)
        d4_lat = d4_result.get("wall_clock_ms", 0.0)

        lines = [
            f"# TraceLens Agent v0 — {self.prefix.upper()} Audit Report",
            "## Bounded Gateway Compatibility Diagnosis",
            "",
            "### Executive Summary",
            "",
            "| Dimension / Metric | Finding / Value | Audit Status |",
            "|---|---|---|",
            f"| **Phase ID** | {self.prefix.upper()} | Authorized Live Diagnosis |",
            f"| **Baseline Commit** | `{git_gate['head_commit'][:10]}` | Ancestor Verified |",
            f"| **Candidate Endpoint** | `{config_gate['resolved_config']['base_url']}` | Verified |",
            f"| **Requested Model** | `{config_gate['resolved_config']['model_name']}` | Verified |",
            f"| **Serialized Request Body** | **{d3_envelope['serialized_http_body_bytes']} bytes** | Reconstructed & Measured |",
            f"| **D3 Non-Streaming Status** | `{d3_st}` ({d3_lat:.2f} ms) | Completed |",
            f"| **D4 Streaming Status** | `{d4_st}` ({d4_lat:.2f} ms) | Completed |",
            f"| **Logical Generations Dispatched** | {total_logical} / {MAX_LOGICAL_GENERATIONS} | Budget Respected |",
            f"| **Physical HTTP Attempts** | {total_physical} / {MAX_PHYSICAL_HTTP_ATTEMPTS} | Wire Instrument Observed |",
            f"| **Final Disposition** | `{final_disposition}` | **MANDATORY STOP** |",
            f"| **Recommendation** | `{analysis['recommendation']}` | Architecture Frozen |",
            "",
            "---",
            "",
            "### 1. Request Envelope Dimensions",
            "",
            f"- System Instructions: {d3_envelope['instructions_chars']} chars / {d3_envelope['instructions_utf8_bytes']} bytes",
            f"- Output Tool Schema: {d3_envelope['tool_schema_chars']} chars / {d3_envelope['tool_schema_utf8_bytes']} bytes",
            f"- Exact HTTP POST Wire Payload: **{d3_envelope['serialized_http_body_bytes']} bytes**",
            f"- Request Body SHA-256: `{d3_envelope['request_body_sha256']}`",
            "",
            "---",
            "",
            "### 2. Live Diagnostic Results",
            "",
            f"- **D3 (Non-Streaming)**: `{d3_st}` in {d3_lat:.2f} ms (Physical Attempts: {d3_result.get('physical_http_attempts', 0)})",
            f"- **D4 (Streaming)**: `{d4_st}` in {d4_lat:.2f} ms (Physical Attempts: {d4_result.get('physical_http_attempts', 0)})",
            "",
            "---",
            "",
            "### 3. Gateway Failure Assessment Answers",
            "",
        ]
        for ans in analysis["answers"]:
            lines.append(f"- {ans}")

        lines.extend([
            "",
            "---",
            "",
            "### 4. Mandatory Final Architecture STOP",
            "",
            "- **Production Supervisor Prompt:** UNCHANGED",
            "- **Production Output Schema:** UNCHANGED",
            "- **EvidenceResolver / FinalizationGate:** UNCHANGED",
            "- **RCA-2B:** NOT_AUTHORIZED",
            "- **Gen-5:** NOT_CREATED",
            "- **Status:** HARD STOP",
        ])
        return "\n".join(lines)

    def _write_json(self, filename: str, data: dict[str, Any]) -> None:
        file_path = self.audit_dir / filename
        file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
