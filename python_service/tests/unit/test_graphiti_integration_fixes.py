"""
Unit tests for the Graphiti integration fixes.

Covers:
- GraphitiService._build_graphiti_config honours include_full_description /
  max_episode_tokens from Settings (previously dropped, leaving episodes
  without the llm_description the extractor needs).
- GraphitiService.ingest_task_episodes builds one episode per analyzed file,
  routes through the GraphitiIngestor (add_episode path), and returns a stats
  dict with per-episode error visibility (the old helpers only returned bool).
- ingest_task_episodes handles empty input and extractor failures gracefully.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def settings():
    """Build a Settings instance with deterministic graphiti-related values."""
    from httpserver.config import Settings

    return Settings(
        neo4j_uri="neo4j://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="pw",
        llm_text_base_url="http://localhost:1234",
        llm_text_model="test/model",
        llm_api_key="key",
        graphiti_use_local_llm=True,
        graphiti_batch_size=5,
        graphiti_max_retries=2,
        graphiti_include_full_desc=True,
        graphiti_max_episode_tokens=2500,
        graphiti_group_id="forensics_files",
    )


@pytest.fixture
def service(settings):
    """A GraphitiService marked initialized, so it does not try Neo4j."""
    from httpserver.services.graphiti_service import GraphitiService

    svc = GraphitiService(settings)
    svc._initialized = True
    return svc


# ---------------------------------------------------------------------------
# _build_graphiti_config
# ---------------------------------------------------------------------------

class TestBuildGraphitiConfig:
    def test_includes_full_description_flag(self, service, settings):
        """include_full_description must flow from Settings into GraphitiConfig."""
        config = service._build_graphiti_config(group_id="t1")
        # The bug was that this field was never passed; verify it now matches
        # what Settings holds (rather than hardcoding a value that .env may override).
        assert config.include_full_description == settings.graphiti_include_full_desc
        assert config.max_episode_tokens == settings.graphiti_max_episode_tokens
        # And it is a real int, not the GraphitiConfig default-only path.
        assert isinstance(config.max_episode_tokens, int)

    def test_respects_group_id(self, service):
        """Each entry point should get its own group_id for isolation."""
        assert service._build_graphiti_config(group_id="task-a").group_id == "task-a"
        assert service._build_graphiti_config(group_id="case-b").group_id == "case-b"

    def test_appends_v1_to_base_url(self, service):
        config = service._build_graphiti_config(group_id="t1")
        assert config.llm_base_url == "http://localhost:1234/v1"

    def test_does_not_double_append_v1(self, settings):
        from httpserver.services.graphiti_service import GraphitiService

        settings.llm_text_base_url = "http://localhost:1234/v1"
        svc = GraphitiService(settings)
        svc._initialized = True
        config = svc._build_graphiti_config(group_id="t1")
        assert config.llm_base_url == "http://localhost:1234/v1"


# ---------------------------------------------------------------------------
# ingest_task_episodes
# ---------------------------------------------------------------------------

class TestIngestTaskEpisodes:
    @pytest.mark.asyncio
    async def test_builds_one_episode_per_file(self, service):
        """Each analyzed file description should become its own episode."""
        mock_ingestor = MagicMock()
        mock_ingestor.batch_ingest = AsyncMock()
        # Return an object exposing .successful / .total_episodes / .failed / .errors
        mock_ingestor.batch_ingest.return_value = MagicMock(
            successful=2, total_episodes=2, failed=0, errors=[]
        )
        service._task_graphs["t1"] = {"config": MagicMock(), "ingestor": mock_ingestor}

        file_descs = [
            {"file_path": "/a.txt", "description": "file A analysis", "success": True},
            {"file_path": "/b.txt", "description": "file B analysis", "success": True},
            # Unsuccessful files must be skipped:
            {"file_path": "/c.txt", "description": "ignored", "success": False},
            # Files without a description must be skipped:
            {"file_path": "/d.txt", "description": "", "success": True},
        ]

        result = await service.ingest_task_episodes(task_id="t1", file_descriptions=file_descs)

        assert mock_ingestor.batch_ingest.await_count == 1
        episodes = mock_ingestor.batch_ingest.await_args.kwargs["episodes"]
        assert len(episodes) == 2  # only the two successful+described files
        assert result["success"] is True
        assert result["successful"] == 2
        assert result["total"] == 2
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_passes_group_id(self, service):
        mock_ingestor = MagicMock()
        mock_ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=1, total_episodes=1, failed=0, errors=[]
        ))
        service._task_graphs["t1"] = {"config": MagicMock(), "ingestor": mock_ingestor}

        await service.ingest_task_episodes(
            task_id="t1",
            file_descriptions=[{"file_path": "/a", "description": "x", "success": True}],
        )

        assert mock_ingestor.batch_ingest.await_args.kwargs["group_id"] == "t1"

    @pytest.mark.asyncio
    async def test_returns_error_visibility(self, service):
        """When the extractor fails, the failure detail must be surfaced."""
        mock_ingestor = MagicMock()
        mock_ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=0, total_episodes=1, failed=1,
            errors=[{"episode": "x", "error": "LLM extraction failed"}],
        ))
        service._task_graphs["t1"] = {"config": MagicMock(), "ingestor": mock_ingestor}

        result = await service.ingest_task_episodes(
            task_id="t1",
            file_descriptions=[{"file_path": "/a", "description": "x", "success": True}],
        )

        assert result["success"] is False
        assert result["failed"] == 1
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_empty_input(self, service):
        """No descriptions → no episodes, success True (vacuous)."""
        mock_ingestor = MagicMock()
        mock_ingestor.batch_ingest = AsyncMock()
        service._task_graphs["t1"] = {"config": MagicMock(), "ingestor": mock_ingestor}

        result = await service.ingest_task_episodes(task_id="t1", file_descriptions=[])

        assert mock_ingestor.batch_ingest.await_count == 0
        assert result["success"] is True
        assert result["successful"] == 0

    @pytest.mark.asyncio
    async def test_long_description_is_chunked(self, service):
        """A description longer than the chunk limit yields multiple episodes."""
        mock_ingestor = MagicMock()
        mock_ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=3, total_episodes=3, failed=0, errors=[]
        ))
        service._task_graphs["t1"] = {"config": MagicMock(), "ingestor": mock_ingestor}

        long_desc = "para.\n\n".join([f"paragraph {i} " + "x" * 2000 for i in range(3)])

        result = await service.ingest_task_episodes(
            task_id="t1",
            file_descriptions=[{"file_path": "/big", "description": long_desc, "success": True}],
        )

        episodes = mock_ingestor.batch_ingest.await_args.kwargs["episodes"]
        assert len(episodes) >= 2  # chunked into multiple parts

    @pytest.mark.asyncio
    async def test_missing_task_graph(self, service):
        """If the task graph cannot be created, return a structured error."""
        with patch.object(
            service, "_get_task_graph", new=AsyncMock(return_value=None)
        ):
            result = await service.ingest_task_episodes(
                task_id="ghost", file_descriptions=[{"file_path": "/a", "description": "x", "success": True}]
            )
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Episode rendering: source=text + forensic extraction instructions
#
# These guard the core fix for sparse knowledge graphs: the ingestor must
# ingest rendered text (not JSON) so Graphiti's extract_text prompt runs
# instead of extract_json (which actively discards forensic tokens), and it
# must pass custom_extraction_instructions to keep usernames/IPs/paths/hashes.
# ---------------------------------------------------------------------------

class TestEpisodeRendering:
    def test_json_body_is_rendered_as_text(self):
        """A JSON episode body must be rendered to readable text and typed text."""
        from graphiti_integration.graphiti_ingestor import GraphitiIngestor
        from graphiti_integration.toon_transformer import EpisodeData
        from graphiti_core.nodes import EpisodeType

        ep = EpisodeData(
            name="文件分析: /etc/passwd",
            episode_body='{"file_path": "/etc/passwd", "analysis": "root user"}',
            source_description="LLM分析结果",
            reference_time=datetime.now(),
            file_path="/etc/passwd",
            file_id=1,
            category="file_description",
        )
        rendered, source_type = GraphitiIngestor._render_episode_for_extraction(ep)

        assert source_type == EpisodeType.text
        assert "file_path: /etc/passwd" in rendered
        assert "analysis: root user" in rendered

    def test_forensic_tokens_survive_rendering(self):
        """High-value forensic tokens (IP, hash, hostname) must remain in the body."""
        from graphiti_integration.graphiti_ingestor import GraphitiIngestor
        from graphiti_integration.toon_transformer import EpisodeData

        body = (
            '{"file_path": "/x", "analysis": "connects to dc01.corp.local at '
            '10.0.0.5", "md5": "d41d8cd98f00b204e9800998ecf8427e"}'
        )
        ep = EpisodeData(
            name="文件分析: /x",
            episode_body=body,
            source_description="s",
            reference_time=datetime.now(),
            file_path="/x",
            file_id=1,
        )
        rendered, _ = GraphitiIngestor._render_episode_for_extraction(ep)
        assert "dc01.corp.local" in rendered
        assert "10.0.0.5" in rendered
        assert "d41d8cd98f00b204e9800998ecf8427e" in rendered

    def test_non_json_body_passes_through_as_text(self):
        """Plain-text bodies must be returned unchanged and typed text."""
        from graphiti_integration.graphiti_ingestor import GraphitiIngestor
        from graphiti_integration.toon_transformer import EpisodeData
        from graphiti_core.nodes import EpisodeType

        ep = EpisodeData(
            name="plain",
            episode_body="just some text, no json here",
            source_description="s",
            reference_time=datetime.now(),
            file_path="",
            file_id=0,
        )
        rendered, source_type = GraphitiIngestor._render_episode_for_extraction(ep)
        assert source_type == EpisodeType.text
        assert rendered == "just some text, no json here"

    @pytest.mark.asyncio
    async def test_add_episode_uses_text_source_and_instructions(self):
        """ingest_episode must call add_episode with source=text and forensic
        extraction instructions (the combination that actually populates the graph)."""
        from graphiti_integration.graphiti_ingestor import GraphitiIngestor, FORENSIC_EXTRACTION_INSTRUCTIONS
        from graphiti_integration.toon_transformer import EpisodeData
        from graphiti_core.nodes import EpisodeType

        ingestor = GraphitiIngestor.__new__(GraphitiIngestor)
        ingestor._initialized = True
        ingestor.config = MagicMock(max_episode_tokens=10000, max_retries=1, group_id="g")
        client = MagicMock()
        client.add_episode = AsyncMock()
        ingestor._client = client

        ep = EpisodeData(
            name="文件分析: /a",
            episode_body='{"file_path": "/a", "analysis": "user admin"}',
            source_description="s",
            reference_time=datetime.now(),
            file_path="/a",
            file_id=1,
        )
        await ingestor.ingest_episode(ep, group_id="g")

        client.add_episode.assert_awaited_once()
        kwargs = client.add_episode.await_args.kwargs
        assert kwargs["source"] == EpisodeType.text
        assert kwargs["custom_extraction_instructions"] == FORENSIC_EXTRACTION_INSTRUCTIONS
        # Rendered body must be text, not the raw JSON.
        assert "file_path: /a" in kwargs["episode_body"]

    @pytest.mark.asyncio
    async def test_ingest_task_episodes_enriches_body_with_metadata(self, service):
        """The episode body must carry summary/keywords/category/md5 so the
        extractor sees them as first-class content."""
        import json as _json
        mock_ingestor = MagicMock()
        mock_ingestor.batch_ingest = AsyncMock(return_value=MagicMock(
            successful=1, total_episodes=1, failed=0, errors=[]
        ))
        service._task_graphs["t1"] = {"config": MagicMock(), "ingestor": mock_ingestor}

        await service.ingest_task_episodes(
            task_id="t1",
            file_descriptions=[{
                "file_path": "/a.exe",
                "description": "malware dropper",
                "summary": "drops payload",
                "keywords": "malware, dropper",
                "category": "executable",
                "md5": "abc123",
                "name": "a.exe",
                "file_type": "PE32",
                "is_relevant": 1,
                "success": True,
            }],
        )
        episodes = mock_ingestor.batch_ingest.await_args.kwargs["episodes"]
        assert len(episodes) == 1
        body = _json.loads(episodes[0].episode_body)
        assert body["md5"] == "abc123"
        assert body["category"] == "executable"
        assert body["keywords"] == "malware, dropper"
        assert body["summary"] == "drops payload"
        assert body["filename"] == "a.exe"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])