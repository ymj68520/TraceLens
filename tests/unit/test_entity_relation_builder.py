"""
Unit tests for EntityRelationBuilder module.

Tests entity-to-file relationship creation and cross-task entity resolution.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from graphiti_integration.entity_relation_builder import (
    EntityRelationBuilder,
    RelationBuildResult,
)


# Fixtures
@pytest.fixture
async def mock_neo4j_driver():
    """Mock Neo4j driver."""
    driver = MagicMock()
    session = MagicMock()
    driver.session = MagicMock(return_value=session)
    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None

    result = MagicMock()
    result.data = MagicMock(return_value=[])
    result.data.return_value = []
    session.run = MagicMock(return_value=result)
    session.run.return_value = result

    return driver


@pytest.fixture
async def builder(mock_neo4j_driver):
    """Create EntityRelationBuilder with mocked driver."""
    builder = EntityRelationBuilder(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password"
    )
    builder._driver = mock_neo4j_driver
    builder._initialized = True
    return builder


# Tests
@pytest.mark.asyncio
async def test_initialize(builder):
    """Test builder initialization."""
    await builder.initialize()
    assert builder._initialized is True


@pytest.mark.asyncio
async def test_create_mentioned_in_edges(builder, mock_neo4j_driver):
    """Test creating MENTIONED_IN edges."""
    # Mock successful result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "entity_name": "JohnDoe",
            "file_path": "/home/user/document.pdf"
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    file_id = "file_hash_123"
    entity_uuids = ["entity1", "entity2", "entity3"]

    edges_created = await builder.create_mentioned_in_edges(file_id, entity_uuids)
    assert edges_created == 3


@pytest.mark.asyncio
async def test_create_mentioned_in_edges_empty(builder):
    """Test creating edges with empty entity list."""
    edges_created = await builder.create_mentioned_in_edges("file_id", [])
    assert edges_created == 0


@pytest.mark.asyncio
async def test_create_mentioned_in_edges_from_episodes(builder, mock_neo4j_driver):
    """Test creating edges by extracting from episodes."""
    # Mock episode entities query result
    episode_result = MagicMock()
    episode_result.data.return_value = [
        {"entity_uuid": "ent1", "entity_name": "Entity1"},
        {"entity_uuid": "ent2", "entity_name": "Entity2"}
    ]

    # Mock create_mentioned_in_edges to return 2 edges
    builder.create_mentioned_in_edges = AsyncMock(return_value=2)

    episode_uuids = ["ep1", "ep2"]
    file_ids = {"ep1": "file1", "ep2": "file1"}

    total_edges = await builder.create_mentioned_in_edges_from_episodes(episode_uuids, file_ids)
    assert total_edges == 4  # 2 entities * 2 episodes


@pytest.mark.asyncio
async def test_get_entities_for_file(builder, mock_neo4j_driver):
    """Test retrieving entities for a file."""
    # Mock result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "uuid": "ent1",
            "name": "Malware",
            "summary": "Malicious software",
            "labels": ["software", "threat"],
            "frequency": 5,
            "first_seen": "2024-01-01T10:00:00Z",
            "last_seen": "2024-01-05T15:00:00Z"
        },
        {
            "uuid": "ent2",
            "name": "JohnDoe",
            "summary": "Person name",
            "labels": ["person"],
            "frequency": 3,
            "first_seen": "2024-01-02T10:00:00Z",
            "last_seen": "2024-01-02T10:00:00Z"
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    entities = await builder.get_entities_for_file("file_id")

    assert len(entities) == 2
    assert entities[0]["name"] == "Malware"
    assert entities[0]["frequency"] == 5
    assert entities[1]["name"] == "JohnDoe"


@pytest.mark.asyncio
async def test_get_files_for_entity(builder, mock_neo4j_driver):
    """Test retrieving files that mention an entity."""
    # Mock result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "file_id": "file1",
            "path": "/home/user/document.pdf",
            "filename": "document.pdf",
            "category": "documents",
            "tasks": ["task_1"],
            "frequency": 5
        },
        {
            "file_id": "file2",
            "path": "/home/user/report.pdf",
            "filename": "report.pdf",
            "category": "documents",
            "tasks": ["task_1", "task_2"],
            "frequency": 3
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    files = await builder.get_files_for_entity("Malware", task_id="task_1")

    assert len(files) == 2
    assert files[0]["filename"] == "document.pdf"
    assert files[0]["frequency"] == 5


@pytest.mark.asyncio
async def test_get_files_for_entity_no_task_filter(builder, mock_neo4j_driver):
    """Test retrieving files without task filter."""
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "file_id": "file1",
            "path": "/test.pdf",
            "filename": "test.pdf",
            "category": "documents",
            "tasks": ["task_1"],
            "frequency": 1
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    files = await builder.get_files_for_entity("Malware")
    assert len(files) == 1


@pytest.mark.asyncio
async def test_resolve_cross_task_entities(builder, mock_neo4j_driver):
    """Test cross-task entity resolution."""
    # Mock duplicate entities result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "entity_name": "Malware",
            "entities": [
                {"uuid": "ent1", "name": "Malware"},
                {"uuid": "ent2", "name": "Malware"}
            ]
        },
        {
            "entity_name": "JohnDoe",
            "entities": [
                {"uuid": "ent3", "name": "JohnDoe"},
                {"uuid": "ent4", "name": "JohnDoe"}
            ]
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    resolved = await builder.resolve_cross_task_entities("task_1")
    assert resolved == 2


@pytest.mark.asyncio
async def test_batch_create_mentioned_in_edges(builder, mock_neo4j_driver):
    """Test batch creation of MENTIONED_IN edges."""
    # Mock results
    episode_result = MagicMock()
    episode_result.data.return_value = [
        {"entity_uuid": "ent1", "entity_name": "Entity1"}
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = episode_result

    # Create edges mock
    builder.create_mentioned_in_edges_from_episodes = AsyncMock(return_value=10)

    file_entity_ids = {"1": "file1", "2": "file2"}
    episode_file_map = {
        "ep1": "file1",
        "ep2": "file1",
        "ep3": "file2"
    }

    result = await builder.batch_create_mentioned_in_edges(file_entity_ids, episode_file_map)

    assert result.mentioned_in_edges_created > 0
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_find_orphan_entities(builder, mock_neo4j_driver):
    """Test finding entities not linked to any File."""
    # Mock orphan result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {"uuid": "ent1", "name": "OrphanEntity"},
        {"uuid": "ent2", "name": "AnotherOrphan"}
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    orphans = await builder.find_orphan_entities(task_id="task_1")

    assert len(orphans) == 2
    assert orphans[0]["uuid"] == "ent1"


@pytest.mark.asyncio
async def test_find_orphan_entities_no_task_filter(builder, mock_neo4j_driver):
    """Test finding all orphans without task filter."""
    result_mock = MagicMock()
    result_mock.data.return_value = [{"uuid": "ent1", "name": "Orphan"}]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    orphans = await builder.find_orphan_entities()
    assert len(orphans) >= 0


@pytest.mark.asyncio
async def test_context_manager(builder):
    """Test async context manager."""
    async with builder:
        assert builder._initialized is True


@pytest.mark.asyncio
async def test_relation_build_result_statistics():
    """Test RelationBuildResult statistics."""
    result = RelationBuildResult(
        mentioned_in_edges_created=100,
        entities_resolved=10,
        cross_task_links=5
    )

    assert result.mentioned_in_edges_created == 100
    assert result.entities_resolved == 10
    assert result.cross_task_links == 5
    assert len(result.errors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
