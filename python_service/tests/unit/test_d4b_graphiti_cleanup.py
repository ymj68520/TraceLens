"""D4b owned Graphiti resource cleanup tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_ingestor_close_closes_owned_clients_even_when_driver_fails():
    from graphiti_integration.graphiti_ingestor import GraphitiIngestor

    ingestor = GraphitiIngestor.__new__(GraphitiIngestor)
    ingestor._initialized = True
    ingestor._owned_llm_client = MagicMock()
    ingestor._owned_llm_client.aclose = AsyncMock()
    ingestor._owned_embedder = MagicMock()
    ingestor._owned_embedder.aclose = AsyncMock()
    ingestor._client = MagicMock()
    ingestor._client.close = AsyncMock(side_effect=RuntimeError("driver close"))

    owned_llm = ingestor._owned_llm_client
    owned_embedder = ingestor._owned_embedder
    driver = ingestor._client

    with pytest.raises(RuntimeError, match="driver close"):
        await ingestor.close()

    owned_llm.aclose.assert_awaited_once()
    owned_embedder.aclose.assert_awaited_once()
    driver.close.assert_awaited_once()
    assert ingestor._client is None
    assert ingestor._owned_llm_client is None
    assert ingestor._owned_embedder is None


@pytest.mark.asyncio
async def test_ingestor_close_is_safe_for_injected_client():
    from graphiti_integration.graphiti_ingestor import GraphitiIngestor

    injected = MagicMock()
    injected.close = AsyncMock()
    ingestor = GraphitiIngestor.__new__(GraphitiIngestor)
    ingestor._initialized = True
    ingestor._owned_llm_client = None
    ingestor._owned_embedder = None
    ingestor._client = injected

    await ingestor.close()
    injected.close.assert_awaited_once()
