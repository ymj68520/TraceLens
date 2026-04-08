"""
Unit tests for FileEntityIngestor module.

Tests File entity creation, event attachment, and MD5 deduplication.
"""

import asyncio
import hashlib
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from graphiti_integration.file_entity_ingestor import (
    FileEntityIngestor,
    EventRecord,
    FileIngestionResult,
)
from graphiti_integration.database_reader.raw_reader import FileRecord


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
async def ingestor(mock_neo4j_driver):
    """Create FileEntityIngestor with mocked driver."""
    ingestor = FileEntityIngestor(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password"
    )
    ingestor._driver = mock_neo4j_driver
    ingestor._initialized = True
    return ingestor


@pytest.fixture
def sample_file():
    """Create a sample FileRecord."""
    return FileRecord(
        id=1,
        inode=12345,
        name="test.txt",
        path="/home/user/test.txt",
        size=1024,
        extension=".txt",
        category="documents",
        file_type="ASCII text",
        mtime=1609459200,
        ctime=1609459200,
        is_deleted=False,
        md5="d41d8cd98f00b204e9800998ecf8427e",
        llm_summary="A test file",
        llm_description="Detailed description",
        llm_keywords="test,sample",
        llm_analyzed_at=1609459200,
        llm_model_used="gpt-4"
    )


# Tests
@pytest.mark.asyncio
async def test_generate_path_hash(ingestor):
    """Test path hash generation."""
    path = "/home/user/test.txt"
    expected_hash = hashlib.sha256(path.encode('utf-8')).hexdigest()
    result = ingestor._generate_path_hash(path)
    assert result == expected_hash
    assert len(result) == 64  # SHA-256 hex length


@pytest.mark.asyncio
async def test_ensure_file_entity_creates_new(ingestor, sample_file, mock_neo4j_driver):
    """Test creating a new File entity."""
    # Mock query result for non-existent file
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value.data.return_value = []

    file_id = await ingestor.ensure_file_entity(sample_file, "task_1")

    expected_hash = hashlib.sha256(b"/home/user/test.txt").hexdigest()
    assert file_id == expected_hash

    # Verify MERGE query was called
    assert mock_neo4j_driver.session.return_value.__aenter__.return_value.run.called


@pytest.mark.asyncio
async def test_ensure_file_entity_updates_existing(ingestor, sample_file, mock_neo4j_driver):
    """Test updating an existing File entity."""
    # Mock query result for existing file
    existing_result = MagicMock()
    existing_result.data.return_value = [{"f": {"id": "some_id"}}]

    # Mock update result
    update_result = MagicMock()
    update_result.data.return_value = [{"id": "some_id", "is_update": True}]

    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value.data.side_effect = [
        existing_result.data(),  # First call (check existence)
        update_result.data()    # Second call (MERGE)
    ]

    file_id = await ingestor.ensure_file_entity(sample_file, "task_1")
    assert file_id is not None


@pytest.mark.asyncio
async def test_attach_event_to_file(ingestor, mock_neo4j_driver):
    """Test attaching an event to a File entity."""
    # Mock successful result
    result_mock = MagicMock()
    result_mock.data.return_value = [{"f": {"id": "file_id"}}]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    event = EventRecord(
        file_inode=12345,
        file_path="/home/user/test.txt",
        event_type="MODIFIED",
        timestamp=1609459200,
        task_id="task_1"
    )

    result = await ingestor.attach_event_to_file("/home/user/test.txt", event)
    assert result is True


@pytest.mark.asyncio
async def test_attach_event_to_file_not_found(ingestor, mock_neo4j_driver):
    """Test attaching event when file not found."""
    # Mock empty result
    result_mock = MagicMock()
    result_mock.data.return_value = []
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    event = EventRecord(
        file_inode=12345,
        file_path="/home/user/test.txt",
        event_type="MODIFIED",
        timestamp=1609459200,
        task_id="task_1"
    )

    result = await ingestor.attach_event_to_file("/home/user/test.txt", event)
    assert result is False


@pytest.mark.asyncio
async def test_link_episode_to_file(ingestor, mock_neo4j_driver):
    """Test linking an episode to a File entity."""
    # Mock successful result
    result_mock = MagicMock()
    result_mock.data.return_value = [{"e": {"uuid": "episode_uuid"}}]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    result = await ingestor.link_episode_to_file("episode_uuid", "/home/user/test.txt")
    assert result is True


@pytest.mark.asyncio
async def test_merge_duplicate_files(ingestor, mock_neo4j_driver):
    """Test MD5-based file deduplication."""
    # Mock duplicate groups result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "md5": "abc123",
            "files": [
                {"id": "file1", "path": "/path1/file.txt"},
                {"id": "file2", "path": "/path2/file.txt"}
            ]
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    groups_found = await ingestor.merge_duplicate_files("task_1")
    assert groups_found == 1


@pytest.mark.asyncio
async def test_batch_ensure_files(ingestor, sample_file, mock_neo4j_driver):
    """Test batch file entity creation."""
    # Mock results
    result_mock = MagicMock()
    result_mock.data.return_value = [{"id": "file_id", "is_update": False}]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    files = [sample_file, sample_file]  # Duplicate for testing

    result = await ingestor.batch_ensure_files(files, "task_1")

    assert result.files_created == 2
    assert result.files_updated == 0
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_get_file_by_id(ingestor, mock_neo4j_driver):
    """Test retrieving File entity by ID."""
    # Mock file result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {
            "f": {"id": "file_id", "path": "/test.txt"},
            "episode_uuids": ["ep1", "ep2"],
            "entities": [{"uuid": "ent1", "name": "Entity1", "frequency": 5}]
        }
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    result = await ingestor.get_file_by_id("file_id")
    assert result is not None
    assert result["f"]["id"] == "file_id"


@pytest.mark.asyncio
async def test_get_files_by_task(ingestor, mock_neo4j_driver):
    """Test retrieving all File entities for a task."""
    # Mock files result
    result_mock = MagicMock()
    result_mock.data.return_value = [
        {"f": {"id": "file1", "path": "/test1.txt"}},
        {"f": {"id": "file2", "path": "/test2.txt"}}
    ]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    files = await ingestor.get_files_by_task("task_1")
    assert len(files) == 2


@pytest.mark.asyncio
async def test_attach_events_batch(ingestor, mock_neo4j_driver):
    """Test batch event attachment."""
    # Mock successful result
    result_mock = MagicMock()
    result_mock.data.return_value = [{"f": {"id": "file_id"}}]
    mock_neo4j_driver.session.return_value.__aenter__.return_value.run.return_value = result_mock

    events = [
        (
            "/home/user/test.txt",
            EventRecord(file_inode=1, file_path="/home/user/test.txt",
                       event_type="MODIFIED", timestamp=1609459200, task_id="task_1")
        ),
        (
            "/home/user/test.txt",
            EventRecord(file_inode=1, file_path="/home/user/test.txt",
                       event_type="ACCESSED", timestamp=1609459300, task_id="task_1")
        )
    ]

    attached = await ingestor.attach_events_batch(events)
    assert attached == 2


@pytest.mark.asyncio
async def test_context_manager(ingestor):
    """Test async context manager."""
    async with ingestor:
        assert ingestor._initialized is True


@pytest.mark.asyncio
async def test_event_record_serialization():
    """Test EventRecord can be properly serialized."""
    event = EventRecord(
        file_inode=12345,
        file_path="/home/user/test.txt",
        event_type="MODIFIED",
        timestamp=1609459200,
        task_id="task_1"
    )

    # Test can be converted to dict
    event_dict = {
        "type": event.event_type,
        "timestamp": datetime.fromtimestamp(event.timestamp).isoformat(),
        "task_id": event.task_id
    }

    assert event_dict["type"] == "MODIFIED"
    assert event_dict["task_id"] == "task_1"


@pytest.mark.asyncio
async def test_file_ingestion_result():
    """Test FileIngestionResult statistics."""
    result = FileIngestionResult(
        files_created=10,
        files_updated=5,
        events_attached=20,
        duplicates_merged=2
    )

    assert result.files_created == 10
    assert result.files_updated == 5
    assert result.total_processed() == 15


# Property tests
@pytest.mark.asyncio
async def test_file_record_properties(sample_file):
    """Test FileRecord property methods."""
    assert sample_file.has_llm_analysis is True
    assert sample_file.mtime_datetime is not None
    assert sample_file.ctime_datetime is not None
    assert "test" in sample_file.keywords_list


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
