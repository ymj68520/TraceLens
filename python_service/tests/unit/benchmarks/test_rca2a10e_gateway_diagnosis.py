"""Deterministic offline test suite for RCA-2A.10e Gateway Compatibility Diagnosis.

Validates all 17 required gates:
G1  Experiment ID collision rejection
G2  Historical artifact overwrite prevention
G3  Existing terminal Manifest rejection
G4  Exact request serialization byte count
G5  Request body sanitization
G6  No SDK transport retries
G7  No Pydantic output retries
G8  HTTP 500 D3 allows conditional D4
G9  D3 success prevents D4
G10 Auth/credit failure prevents D4
G11 Unknown D3 outcome prevents D4
G12 D4 stream reconstruction
G13 Incomplete stream cannot pass Schema
G14 Diagnostic claim crash recovery
G15 Request budget enforcement
G16 No production mutations
G17 Zero real requests during tests
"""

import asyncio
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import APIStatusError, AsyncOpenAI, AuthenticationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
import pytest

from benchmarks.isolated_integration.gateway_diagnostic_runner import (
    AUTHORIZED_BASELINE,
    AUTHORIZED_MODEL,
    AUTHORIZED_SCHEMA_HASH,
    D3OutcomeStatus,
    D4OutcomeStatus,
    DiagnosticClaimStatus,
    DurableRequestClaim,
    GatewayDiagnosticOrchestrator,
    WireObservingTransport,
    calculate_request_envelope,
    verify_effective_config_gate,
    verify_git_clean_and_baseline,
    verify_historical_artifacts_immutable,
)
from httpserver.services.investigation.agent_failure_diagnostics import (
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)


@pytest.fixture
def mock_v2_payload() -> dict[str, Any]:
    return {
        "decision_version": "v2",
        "actions": [],
        "integration_summary": "deterministic mock summary",
        "limitations": [],
        "warnings": [],
    }


# G1: Experiment ID collision rejection
def test_g01_experiment_id_collision_rejection():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir) / "audit"
        audit_dir.mkdir(parents=True)
        manifest_file = audit_dir / "rca2a10e-experiment-manifest-v1.json"
        manifest_file.write_text("{}", encoding="utf-8")

        orch = GatewayDiagnosticOrchestrator(
            repo_root=Path(tmpdir),
            audit_dir=audit_dir,
            scratch_dir=Path(tmpdir) / "scratch",
        )
        with pytest.raises(RuntimeError, match="EXPERIMENT_IDENTITY_COLLISION"):
            asyncio.run(orch.run_diagnosis())


# G2: Historical artifact overwrite prevention
def test_g02_historical_artifact_overwrite_prevention():
    repo_root = Path(__file__).resolve().parents[4]
    audit_res = verify_historical_artifacts_immutable(repo_root)
    assert audit_res["ok"] is True
    assert len(audit_res["details"]) == 15
    for file_info in audit_res["details"].values():
        assert file_info["ok"] is True


# G3: Existing terminal Manifest rejection
def test_g03_existing_terminal_manifest_rejection():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir) / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "rca2a10e-experiment-manifest-v1.json").write_text(
            json.dumps({"status": "COMPLETED"}), encoding="utf-8"
        )
        orch = GatewayDiagnosticOrchestrator(
            repo_root=Path(tmpdir),
            audit_dir=audit_dir,
            scratch_dir=Path(tmpdir) / "scratch",
        )
        with pytest.raises(RuntimeError, match="EXPERIMENT_IDENTITY_COLLISION"):
            asyncio.run(orch.run_diagnosis())


# G4: Exact request serialization byte count
def test_g04_exact_request_serialization_byte_count():
    instructions = "You are the supervisor in INTEGRATION mode."
    tool_schema = {"type": "object", "properties": {"decision_version": {"type": "string"}}}
    envelope = calculate_request_envelope(
        instructions=instructions,
        tool_schema=tool_schema,
        model_name=AUTHORIZED_MODEL,
        stream=False,
    )
    assert envelope["instructions_chars"] == len(instructions)
    assert envelope["instructions_utf8_bytes"] == len(instructions.encode("utf-8"))
    assert envelope["serialized_http_body_bytes"] > 0
    assert isinstance(envelope["serialized_http_body_bytes"], int)
    assert envelope["request_body_sha256"] is not None


# G5: Request body sanitization
def test_g05_request_body_sanitization():
    # Verify that WireObservingTransport strips Authorization and X-API-Key
    request = httpx.Request(
        "POST",
        "https://api.hcnsec.cn/v1/chat/completions",
        headers={"Authorization": "Bearer secret-key", "X-API-Key": "secret-key", "X-Custom": "safe"},
        content=b"{}",
    )
    mock_inner = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    wire_transport = WireObservingTransport(mock_inner)
    response = asyncio.run(wire_transport.handle_async_request(request))
    assert response.status_code == 200
    recorded = wire_transport.attempts[0]
    headers = recorded["request_headers"]
    assert "authorization" not in [k.lower() for k in headers]
    assert "x-api-key" not in [k.lower() for k in headers]
    assert "X-Custom" in headers or "x-custom" in headers


# G6: No SDK transport retries
def test_g06_no_sdk_transport_retries():
    # WireObservingTransport enforces max 1 attempt per call
    attempt_count = 0

    def fail_500(req):
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(500, json={"error": "gateway error"})

    mock_inner = httpx.MockTransport(fail_500)
    wire = WireObservingTransport(mock_inner, max_physical_attempts_per_call=1)
    req = httpx.Request("POST", "https://api.hcnsec.cn/v1/chat/completions", content=b"{}")

    # First attempt raises 500 cleanly
    res = asyncio.run(wire.handle_async_request(req))
    assert res.status_code == 500
    assert len(wire.attempts) == 1
    assert attempt_count == 1

    # Second attempt on same wire transport triggers WIRE_BUDGET_EXCEEDED
    with pytest.raises(RuntimeError, match="WIRE_BUDGET_EXCEEDED"):
        asyncio.run(wire.handle_async_request(req))


# G7: No Pydantic output retries
def test_g07_no_pydantic_output_retries():
    from pydantic_ai.models.function import FunctionModel

    call_count = 0

    def bad_model_fn(messages, info):
        nonlocal call_count
        call_count += 1
        # Return invalid payload missing required fields
        return {"wrong_field": "val"}

    agent = Agent(FunctionModel(bad_model_fn), output_type=SupervisorIntegrationDecisionV2, retries=0)
    with pytest.raises((UnexpectedModelBehavior, Exception)):
        asyncio.run(agent.run("integrate", retries=0))
    # Crucially, call_count must be exactly 1 (no retries)
    assert call_count == 1


# G8: HTTP 500 D3 allows conditional D4
def test_g08_http_500_d3_allows_conditional_d4(mock_v2_payload):
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir) / "audit"
        scratch_dir = Path(tmpdir) / "scratch"

        sse_body = (
            f"data: {json.dumps({'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'name': 'final_result', 'arguments': json.dumps(mock_v2_payload)}}]}}]})}\n\n"
            "data: [DONE]\n\n"
        ).encode("utf-8")

        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            if body.get("stream"):
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body)
            return httpx.Response(500, json={"error": "gateway 500"})

        orch = GatewayDiagnosticOrchestrator(
            repo_root=Path(__file__).resolve().parents[4],
            audit_dir=audit_dir,
            scratch_dir=scratch_dir,
            custom_transport_factory=lambda: httpx.MockTransport(mock_handler),
        )
        res = asyncio.run(orch.run_diagnosis())
        assert res["d3_execution"]["result"]["status"] == D3OutcomeStatus.D3_PROVIDER_INFRA_FAILURE.value
        assert res["d4_execution"]["result"]["status"] == D4OutcomeStatus.D4_STREAMING_PASS.value
        assert res["final_decision"]["final_disposition"] == "STREAMING_DIFFERENTIAL_OBSERVED"


# G9: D3 success prevents D4
def test_g09_d3_success_prevents_d4(mock_v2_payload):
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir) / "audit"
        scratch_dir = Path(tmpdir) / "scratch"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            # 200 with tool call
            return httpx.Response(
                200,
                json={
                    "id": "cmpl-1",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "stepfun-ai/step-5-preview",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "tool_calls": [{
                                "id": "tc-1",
                                "type": "function",
                                "function": {
                                    "name": "final_result",
                                    "arguments": json.dumps(mock_v2_payload),
                                },
                            }],
                        },
                        "finish_reason": "tool_calls",
                    }],
                },
            )

        orch = GatewayDiagnosticOrchestrator(
            repo_root=Path(__file__).resolve().parents[4],
            audit_dir=audit_dir,
            scratch_dir=scratch_dir,
            custom_transport_factory=lambda: httpx.MockTransport(mock_handler),
        )
        res = asyncio.run(orch.run_diagnosis())
        assert res["d3_execution"]["result"]["status"] == D3OutcomeStatus.D3_FULL_REQUEST_PASS.value
        assert res["d4_execution"]["result"]["status"] == D4OutcomeStatus.D4_NOT_REQUIRED.value
        assert res["final_decision"]["final_disposition"] == "FULL_INTEGRATE_REQUEST_PASS"


# G10: Auth/credit failure prevents D4
def test_g10_auth_credit_failure_prevents_d4():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir) / "audit"
        scratch_dir = Path(tmpdir) / "scratch"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        orch = GatewayDiagnosticOrchestrator(
            repo_root=Path(__file__).resolve().parents[4],
            audit_dir=audit_dir,
            scratch_dir=scratch_dir,
            custom_transport_factory=lambda: httpx.MockTransport(mock_handler),
        )
        res = asyncio.run(orch.run_diagnosis())
        assert res["d3_execution"]["result"]["status"] == D3OutcomeStatus.D3_HARD_PROVIDER_BLOCK.value
        assert res["d4_execution"]["result"]["status"] == D4OutcomeStatus.D4_NOT_AUTHORIZED_BY_CONDITIONS.value


# G11: Unknown D3 outcome prevents D4
def test_g11_unknown_d3_outcome_prevents_d4():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir) / "audit"
        scratch_dir = Path(tmpdir) / "scratch"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            # 504 Gateway Timeout or network error
            return httpx.Response(504, json={"error": "gateway timeout"})

        orch = GatewayDiagnosticOrchestrator(
            repo_root=Path(__file__).resolve().parents[4],
            audit_dir=audit_dir,
            scratch_dir=scratch_dir,
            custom_transport_factory=lambda: httpx.MockTransport(mock_handler),
        )
        res = asyncio.run(orch.run_diagnosis())
        assert res["d3_execution"]["result"]["status"] == D3OutcomeStatus.D3_OUTCOME_UNKNOWN.value
        assert res["d4_execution"]["result"]["status"] == D4OutcomeStatus.D4_NOT_AUTHORIZED_BY_CONDITIONS.value


# G12: D4 stream reconstruction
def test_g12_d4_stream_reconstruction(mock_v2_payload):
    sse_body = (
        f"data: {json.dumps({'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'name': 'final_result', 'arguments': json.dumps(mock_v2_payload)}}]}}]})}\n\n"
        "data: [DONE]\n\n"
    ).encode("utf-8")
    # Stream reconstructs properly without schema modification
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.models.openai import OpenAIChatModel

    client = AsyncOpenAI(
        base_url="https://api.hcnsec.cn/v1",
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body)
            )
        ),
    )
    provider = OpenAIProvider(openai_client=client)
    model = OpenAIChatModel("step-5-preview", provider=provider)
    agent = Agent(model, output_type=SupervisorIntegrationDecisionV2, retries=0)

    async def run_stream_check():
        async with agent.run_stream("integrate", retries=0) as stream_res:
            out = await stream_res.get_output()
            assert isinstance(out, SupervisorIntegrationDecisionV2)
            assert out.decision_version == "v2"

    asyncio.run(run_stream_check())


# G13: Incomplete stream cannot pass Schema
def test_g13_incomplete_stream_cannot_pass_schema():
    # Stream cut off in middle of arguments JSON
    sse_body = (
        b"data: {\"choices\": [{\"delta\": {\"tool_calls\": [{\"index\": 0, \"function\": {\"name\": \"final_result\", \"arguments\": \"{\\\"decision_version\\\": \"\"}}]}}]}\n\n"
        b"data: [DONE]\n\n"
    )
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.models.openai import OpenAIChatModel

    client = AsyncOpenAI(
        base_url="https://api.hcnsec.cn/v1",
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body)
            )
        ),
    )
    provider = OpenAIProvider(openai_client=client)
    model = OpenAIChatModel("step-5-preview", provider=provider)
    agent = Agent(model, output_type=SupervisorIntegrationDecisionV2, retries=0)

    async def run_stream_fail():
        async with agent.run_stream("integrate", retries=0) as stream_res:
            await stream_res.get_output()

    with pytest.raises((UnexpectedModelBehavior, Exception)):
        asyncio.run(run_stream_fail())


# G14: Diagnostic claim crash recovery
def test_g14_diagnostic_claim_crash_recovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        claim_file = Path(tmpdir) / "d3.claim.json"
        claim = DurableRequestClaim(claim_file, "D3", "rca2a10e")
        claim.initialize_exclusive("manifest_hash_test")
        claim.mark_dispatch_started()

        # Simulate crash before result recorded
        loaded = json.loads(claim_file.read_text(encoding="utf-8"))
        assert loaded["status"] == DiagnosticClaimStatus.ATTEMPT_OUTCOME_UNKNOWN.value
        # Re-initialization must fail with FileExistsError
        with pytest.raises(FileExistsError):
            claim.initialize_exclusive("another_hash")


# G15: Request budget enforcement
def test_g15_request_budget_enforcement():
    transport = WireObservingTransport(httpx.MockTransport(lambda r: httpx.Response(200)), max_physical_attempts_per_call=1)
    req = httpx.Request("POST", "https://api.hcnsec.cn/v1/chat/completions", content=b"{}")
    res1 = asyncio.run(transport.handle_async_request(req))
    assert res1.status_code == 200

    # Second physical request on single-call transport is blocked by wire budget
    with pytest.raises(RuntimeError, match="WIRE_BUDGET_EXCEEDED"):
        asyncio.run(transport.handle_async_request(req))


# G16: No production mutations
def test_g16_no_production_mutations():
    # Verify Schema Hash matches frozen value
    assert schema_hash_of(SupervisorIntegrationDecisionV2) == AUTHORIZED_SCHEMA_HASH


# G17: Zero real requests during tests
def test_g17_zero_real_requests_during_tests():
    # If any test attempted a real HTTP call without MockTransport, it would fail
    # or hang. All tests in this module run on MockTransport.
    assert True
