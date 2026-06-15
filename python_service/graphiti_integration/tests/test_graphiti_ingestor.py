"""
Unit tests for graphiti_ingestor module.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graphiti_integration.config import GraphitiConfig
from graphiti_integration.graphiti_ingestor import GraphitiIngestor, IngestionResult
from graphiti_integration.toon_transformer import EpisodeData
from graphiti_integration.exceptions import IngestionError


@pytest.fixture
def config():
    """Create a test configuration."""
    return GraphitiConfig(
        neo4j_uri="neo4j://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        llm_api_key="test-key",
        batch_size=10,
        max_retries=2,
    )


@pytest.fixture
def sample_episode():
    """Create a sample EpisodeData for testing."""
    return EpisodeData(
        name="Documents:test.pdf",
        episode_body='{"file_name": "test.pdf", "category": "Documents"}',
        source_description="forensics_file_analysis",
        reference_time=datetime.now(timezone.utc),
        file_path="/data/test.pdf",
        file_id=1,
        category="Documents",
    )


class TestIngestionResult:
    """Tests for IngestionResult dataclass."""
    
    def test_success_rate_calculation(self):
        """Test success rate is calculated correctly."""
        result = IngestionResult(total_episodes=10, successful=8, failed=2)
        assert result.success_rate == 80.0
    
    def test_success_rate_zero_episodes(self):
        """Test success rate with no episodes."""
        result = IngestionResult(total_episodes=0, successful=0, failed=0)
        assert result.success_rate == 0.0
    
    def test_errors_default_empty(self):
        """Test errors list defaults to empty."""
        result = IngestionResult(total_episodes=1)
        assert result.errors == []


class TestGraphitiIngestor:
    """Tests for GraphitiIngestor class."""
    
    @pytest.mark.asyncio
    async def test_initialize_creates_client(self, config):
        """Test initialization creates Graphiti client with local-LLM clients."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client

            ingestor = GraphitiIngestor(config)
            await ingestor.initialize()

            # config defaults to use_local_llm=True, so the client is constructed
            # with explicit llm_client/embedder/cross_encoder.
            mock_graphiti.assert_called_once()
            _, kwargs = mock_graphiti.call_args
            assert kwargs["uri"] == config.neo4j_uri
            assert kwargs["user"] == config.neo4j_user
            assert kwargs["password"] == config.neo4j_password
            assert "llm_client" in kwargs
            assert "embedder" in kwargs
            assert "cross_encoder" in kwargs
            mock_client.build_indices_and_constraints.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ingest_episode_success(self, config, sample_episode):
        """Test successful episode ingestion."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            ingestor = GraphitiIngestor(config)
            result = await ingestor.ingest_episode(sample_episode)
            
            assert result is True
            mock_client.add_episode.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ingest_episode_retry_on_failure(self, config, sample_episode):
        """Test retry logic on ingestion failure."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            # Fail first time, succeed second time
            mock_client.add_episode.side_effect = [Exception("Network error"), None]
            
            ingestor = GraphitiIngestor(config)
            result = await ingestor.ingest_episode(sample_episode)
            
            assert result is True
            assert mock_client.add_episode.call_count == 2
    
    @pytest.mark.asyncio
    async def test_ingest_episode_max_retries_exceeded(self, config, sample_episode):
        """Test IngestionError after max retries."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            # Always fail
            mock_client.add_episode.side_effect = Exception("Persistent error")
            
            ingestor = GraphitiIngestor(config)
            
            with pytest.raises(IngestionError, match="after 2 attempts"):
                await ingestor.ingest_episode(sample_episode)
    
    @pytest.mark.asyncio
    async def test_batch_ingest_success(self, config):
        """Test batch ingestion with multiple episodes."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            episodes = [
                EpisodeData(
                    name=f"test_{i}",
                    episode_body="{}",
                    source_description="test",
                    reference_time=datetime.now(timezone.utc),
                    file_path=f"/test_{i}",
                    file_id=i,
                )
                for i in range(5)
            ]
            
            ingestor = GraphitiIngestor(config)
            result = await ingestor.batch_ingest(episodes)
            
            assert result.total_episodes == 5
            assert result.successful == 5
            assert result.failed == 0
            assert result.success_rate == 100.0
    
    @pytest.mark.asyncio
    async def test_batch_ingest_with_failures(self, config):
        """Test batch ingestion handles individual failures."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client

            # Fail permanently on the second episode (exhausts all retries).
            async def side_effect(*args, **kwargs):
                name = kwargs.get("name", "")
                if name == "test_1":
                    raise Exception("Episode 2 failed permanently")

            mock_client.add_episode.side_effect = side_effect

            episodes = [
                EpisodeData(
                    name=f"test_{i}",
                    episode_body="{}",
                    source_description="test",
                    reference_time=datetime.now(timezone.utc),
                    file_path=f"/test_{i}",
                    file_id=i,
                )
                for i in range(3)
            ]

            ingestor = GraphitiIngestor(config)
            result = await ingestor.batch_ingest(episodes)

            # 3 episodes, 1 fails permanently after max_retries attempts.
            assert result.total_episodes == 3
            assert result.failed == 1
            assert result.successful == 2
            assert len(result.errors) == 1
    
    @pytest.mark.asyncio
    async def test_batch_ingest_progress_callback(self, config):
        """Test progress callback is called during batch ingestion."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            episodes = [
                EpisodeData(
                    name=f"test_{i}",
                    episode_body="{}",
                    source_description="test",
                    reference_time=datetime.now(timezone.utc),
                    file_path=f"/test_{i}",
                    file_id=i,
                )
                for i in range(3)
            ]
            
            progress_calls = []
            
            def progress_callback(current, total):
                progress_calls.append((current, total))
            
            ingestor = GraphitiIngestor(config)
            await ingestor.batch_ingest(episodes, progress_callback=progress_callback)
            
            assert len(progress_calls) == 3
            assert progress_calls == [(1, 3), (2, 3), (3, 3)]
    
    @pytest.mark.asyncio
    async def test_context_manager(self, config):
        """Test async context manager usage."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            async with GraphitiIngestor(config) as ingestor:
                assert ingestor._initialized
            
            mock_client.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_cleans_up(self, config):
        """Test close method cleans up resources."""
        with patch("graphiti_integration.graphiti_ingestor.Graphiti") as mock_graphiti:
            mock_client = AsyncMock()
            mock_graphiti.return_value = mock_client
            
            ingestor = GraphitiIngestor(config)
            await ingestor.initialize()
            await ingestor.close()
            
            mock_client.close.assert_called_once()
            assert ingestor._client is None
            assert ingestor._initialized is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
