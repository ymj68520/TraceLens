"""P3 opt-in provider smoke test (work order §11).

Never part of the default pytest gate: set TRACELENS_AGENT_PROVIDER_SMOKE=1
to run against the real configured endpoint. Proves the adapter can reach the
provider and complete one structured output round-trip; it asserts nothing
about model quality.
"""

import os

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("TRACELENS_AGENT_PROVIDER_SMOKE") != "1",
        reason="opt-in provider smoke (TRACELENS_AGENT_PROVIDER_SMOKE=1)",
    ),
]


async def test_real_provider_structured_output_smoke():
    from pydantic import BaseModel, ConfigDict

    from httpserver.config import get_settings
    from httpserver.services.investigation.agent_model_adapter import (
        build_chat_model,
    )

    class SmokeProbe(BaseModel):
        model_config = ConfigDict(extra="forbid")

        ok: bool
        note: str

    settings = get_settings()
    model = build_chat_model(settings)
    from pydantic_ai import Agent

    agent = Agent(model, output_type=SmokeProbe)
    result = await agent.run(
        "Smoke probe. Reply with ok=true and a short note."
    )
    assert isinstance(result.output, SmokeProbe)
