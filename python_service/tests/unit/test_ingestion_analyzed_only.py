"""
Unit tests for IngestionJobManager._process_analyzed_only method.

Tests the ANALYZED_ONLY ingestion mode that processes only AI-analyzed files
and their associated events.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =============================================================================
# Mock Dependencies
# =============================================================================

# Mock neo4j and graphiti_integration modules before importing
sys.modules['neo4j'] = MagicMock()
sys.modules['graphiti_integration'] = MagicMock()
sys.modules['graphiti_integration.file_entity_ingestor'] = MagicMock()
sys.modules['graphiti_integration.entity_relation_builder'] = MagicMock()
sys.modules['graphiti_integration.database_reader'] = MagicMock()
sys.modules['graphiti_integration.database_reader.raw_reader'] = MagicMock()
sys.modules['graphiti_integration.database_reader.events_reader'] = MagicMock()

# Create the enums and classes we need
class IngestionMode(str, Enum):
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class FileRecord:
    """File record from ForensicsDatabase."""
    id: int
    inode: int
    name: str
    path: str
    size: int
    extension: str
    category: str
    file_type: str
    mtime: int
    ctime: int
    is_deleted: bool
    md5: str
    llm_summary: Optional[str] = None
    llm_description: Optional[str] = None
    llm_keywords: Optional[str] = None
    llm_analyzed_at: Optional[int] = None
    llm_model_used: Optional[str] = None

@dataclass
class FileIngestionResult:
    files_created: int = 0
    files_updated: int = 0
    events_attached: int = 0
    episodes_linked: int = 0
    duplicates_merged: int = 0
    errors: list = field(default_factory=list)

@dataclass
class RelationBuildResult:
    mentioned_in_edges_created: int = 0
    relationships_built: int = 0

@dataclass
class EventRecord:
    file_inode: int
    file_path: str
    event_type: str
    timestamp: int
    task_id: str

# Mock the classes in the modules
sys.modules['graphiti_integration.file_entity_ingestor'].FileEntityIngestor = MagicMock
sys.modules['graphiti_integration.file_entity_ingestor'].EventRecord = EventRecord
sys.modules['graphiti_integration.file_entity_ingestor'].FileIngestionResult = FileIngestionResult
sys.modules['graphiti_integration.entity_relation_builder'].EntityRelationBuilder = MagicMock
sys.modules['graphiti_integration.entity_relation_builder'].RelationBuildResult = RelationBuildResult
sys.modules['graphiti_integration.database_reader.raw_reader'].ForensicsDatabase = MagicMock
sys.modules['graphiti_integration.database_reader.raw_reader'].FileRecord = FileRecord
sys.modules['graphiti_integration.database_reader.events_reader'].EventsDatabase = MagicMock

# Now import the actual module
from httpserver.services.ingestion_job_manager import IngestionJobManager


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_settings():
    """Mock Settings object."""
    settings = MagicMock()
    settings.redis_url = "redis://localhost:6379"
    settings.neo4j_uri = "bolt://localhost:7687"
    settings.neo4j_user = "neo4j"
    settings.neo4j_password = "password"
    settings.db_output_dir = "/tmp/test_db"
    return settings


@pytest.fixture
def job_manager(mock_settings):
    """Create IngestionJobManager instance with mocked dependencies."""
    manager = IngestionJobManager(mock_settings)

    # Mock component services
    manager._file_ingestor = AsyncMock()
    manager._entity_builder = AsyncMock()

    # Mock database classes
    manager._ForensicsDatabase = MagicMock()
    manager._EventsDatabase = MagicMock()

    return manager


@pytest.fixture
def sample_file_records():
    """Create sample file records with LLM analysis."""
    return [
        FileRecord(
            id=1,
            inode=12345,
            name="document.txt",
            path="/path/to/document.txt",
            size=1024,
            extension=".txt",
            category="documents",
            file_type="text/plain",
            mtime=1640000000,
            ctime=1630000000,
            is_deleted=False,
            md5="abc123",
            llm_summary="A text document",
            llm_description="Contains important information",
            llm_keywords="important,info",
            llm_analyzed_at=1640000000,
            llm_model_used="gpt-4",
        ),
        FileRecord(
            id=2,
            inode=12346,
            name="image.jpg",
            path="/path/to/image.jpg",
            size=2048,
            extension=".jpg",
            category="images",
            file_type="image/jpeg",
            mtime=1640000100,
            ctime=1630000100,
            is_deleted=False,
            md5="def456",
            llm_summary="An image file",
            llm_description="Contains a photograph",
            llm_keywords="photo,image",
            llm_analyzed_at=1640000100,
            llm_model_used="gpt-4",
        ),
    ]


@pytest.fixture
def sample_events():
    """Create sample timeline events."""
    return [
        MagicMock(
            file_path="/path/to/document.txt",
            inode=12345,
            event_type="MODIFIED",
            timestamp=1640000000,
        ),
        MagicMock(
            file_path="/path/to/image.jpg",
            inode=12346,
            event_type="CREATED",
            timestamp=1630000100,
        ),
    ]


# =============================================================================
# Test 1: test_process_analyzed_only_with_analyzed_files
# =============================================================================

@pytest.mark.asyncio
async def test_process_analyzed_only_with_analyzed_files(
    job_manager,
    sample_file_records,
    sample_events,
):
    """
    Test _process_analyzed_only with AI-analyzed files present.

    Verifies:
    - get_analysis_stats() is called and returns analyzed file count
    - iter_files_batched(analyzed_only=True) is called with correct parameter
    - batch_ensure_files() is called with the analyzed files
    - attach_events_batch() is called for events of analyzed files only
    - _create_mentioned_in_edges() is called
    - merge_duplicate_files() is called
    - Progress updates are sent at expected milestones
    """
    job_id = "test_job_123"
    task_id = "test_task_456"

    # Setup database mocks
    mock_db_instance = MagicMock()
    mock_db_instance.get_analysis_stats.return_value = {
        "analyzed_files": 2,
        "total_files": 10,
        "analysis_percentage": 20.0,
    }
    mock_db_instance.iter_files_batched.return_value = [sample_file_records]

    mock_events_db_instance = MagicMock()
    mock_events_db_instance.get_events.return_value = sample_events

    job_manager._ForensicsDatabase.return_value = mock_db_instance
    job_manager._EventsDatabase.return_value = mock_events_db_instance

    # Mock _find_database to return paths
    with patch.object(
        job_manager,
        '_find_database',
        side_effect=lambda task_id, db_type: f"/tmp/{task_id}_{db_type}.db"
    ):
        # Mock file ingestor methods
        file_result = FileIngestionResult(
            files_created=2,
            files_updated=0,
            events_attached=2,
            episodes_linked=0,
            duplicates_merged=0,
        )
        job_manager._file_ingestor.batch_ensure_files.return_value = file_result
        job_manager._file_ingestor.attach_events_batch.return_value = 2
        job_manager._file_ingestor.merge_duplicate_files.return_value = 1

        # Mock _create_mentioned_in_edges
        relation_result = RelationBuildResult(
            mentioned_in_edges_created=2,
            relationships_built=0,
        )
        job_manager._create_mentioned_in_edges = AsyncMock(return_value=relation_result)

        # Mock _update_job_status to track calls
        job_manager._update_job_status = AsyncMock()

        # Execute
        await job_manager._process_analyzed_only(job_id, task_id)

    # Verify database initialization
    job_manager._ForensicsDatabase.assert_called_once()
    job_manager._EventsDatabase.assert_called_once()

    # Verify get_analysis_stats was called
    mock_db_instance.get_analysis_stats.assert_called_once()

    # Verify iter_files_batched was called with analyzed_only=True
    mock_db_instance.iter_files_batched.assert_called_once_with(
        batch_size=100,
        analyzed_only=True
    )

    # Verify batch_ensure_files was called with analyzed files
    job_manager._file_ingestor.batch_ensure_files.assert_called_once()
    call_args = job_manager._file_ingestor.batch_ensure_files.call_args
    assert call_args[0][0] == sample_file_records
    assert call_args[0][1] == task_id
    assert call_args[1]['progress_callback'] is not None

    # Verify attach_events_batch was called
    job_manager._file_ingestor.attach_events_batch.assert_called_once()
    event_list = job_manager._file_ingestor.attach_events_batch.call_args[0][0]
    assert len(event_list) == 2
    # Verify events are only for analyzed files
    paths_in_events = {event[0] for event in event_list}
    assert paths_in_events == {"/path/to/document.txt", "/path/to/image.jpg"}

    # Verify merge_duplicate_files was called
    job_manager._file_ingestor.merge_duplicate_files.assert_called_once_with(task_id)

    # Verify _create_mentioned_in_edges was called
    job_manager._create_mentioned_in_edges.assert_called_once_with(task_id, sample_file_records)

    # Verify progress updates at expected milestones
    status_calls = job_manager._update_job_status.call_args_list
    progress_values = [call[1].get('progress') for call in status_calls if call[1].get('progress') is not None]

    # Check key progress milestones
    assert 5 in progress_values  # Initial "reading_databases"
    assert 10 in progress_values  # "checking_analyzed_files"
    assert 15 in progress_values  # "processing_files" start
    assert 70 in progress_values  # "attaching_events"
    assert 85 in progress_values  # "linking_entities"
    assert 90 in progress_values  # "deduplicating_files"
    assert 95 in progress_values  # "finalizing"


# =============================================================================
# Test 2: test_process_analyzed_only_no_analyzed_files
# =============================================================================

@pytest.mark.asyncio
async def test_process_analyzed_only_no_analyzed_files(job_manager):
    """
    Test _process_analyzed_only when no AI-analyzed files exist.

    Verifies:
    - get_analysis_stats() returns 0 analyzed files
    - Processing completes early with progress=100
    - Result message indicates "No AI-analyzed files found"
    - batch_ensure_files() is NOT called
    """
    job_id = "test_job_123"
    task_id = "test_task_456"

    # Setup database mocks with no analyzed files
    mock_db_instance = MagicMock()
    mock_db_instance.get_analysis_stats.return_value = {
        "analyzed_files": 0,
        "total_files": 10,
        "analysis_percentage": 0.0,
    }

    job_manager._ForensicsDatabase.return_value = mock_db_instance

    # Mock _find_database to return paths
    with patch.object(
        job_manager,
        '_find_database',
        side_effect=lambda task_id, db_type: f"/tmp/{task_id}_{db_type}.db"
    ):
        # Mock _update_job_status to track calls
        job_manager._update_job_status = AsyncMock()

        # Execute
        await job_manager._process_analyzed_only(job_id, task_id)

    # Verify get_analysis_stats was called
    mock_db_instance.get_analysis_stats.assert_called_once()

    # Verify iter_files_batched was NOT called (early return)
    mock_db_instance.iter_files_batched.assert_not_called()

    # Verify batch_ensure_files was NOT called
    job_manager._file_ingestor.batch_ensure_files.assert_not_called()

    # Verify attach_events_batch was NOT called
    job_manager._file_ingestor.attach_events_batch.assert_not_called()

    # Verify job was marked COMPLETED with proper message
    job_manager._update_job_status.assert_called()
    final_call = job_manager._update_job_status.call_args_list[-1]
    assert final_call[0][1] == JobStatus.COMPLETED
    assert final_call[1]['progress'] == 100
    assert final_call[1]['result']['message'] == "No AI-analyzed files found"
    assert final_call[1]['result']['files_processed'] == 0


# =============================================================================
# Test 3: test_process_analyzed_only_database_not_found
# =============================================================================

@pytest.mark.asyncio
async def test_process_analyzed_only_database_not_found(job_manager):
    """
    Test _process_analyzed_only when files database is missing.

    Verifies:
    - _find_database() returns None
    - FileNotFoundError is raised with correct message
    - Initial status update was called before the error
    """
    job_id = "test_job_123"
    task_id = "test_task_456"

    # Mock _find_database to return None (database not found)
    with patch.object(
        job_manager,
        '_find_database',
        return_value=None
    ):
        # Mock _update_job_status to track calls
        job_manager._update_job_status = AsyncMock()

        # Execute and expect FileNotFoundError
        with pytest.raises(FileNotFoundError) as exc_info:
            await job_manager._process_analyzed_only(job_id, task_id)

        # Verify error message
        assert "Files database not found for task" in str(exc_info.value)
        assert task_id in str(exc_info.value)

    # Verify database initialization was NOT attempted
    job_manager._ForensicsDatabase.assert_not_called()

    # Verify initial status update was called before the error
    job_manager._update_job_status.assert_called_once()
    # Verify the status was RUNNING (not FAILED - FAILED is set by caller)
    status_call = job_manager._update_job_status.call_args_list[0]
    assert status_call[0][1] == JobStatus.RUNNING


# =============================================================================
# Additional Edge Case Tests
# =============================================================================

@pytest.mark.asyncio
async def test_process_analyzed_only_events_db_missing(job_manager, sample_file_records):
    """
    Test _process_analyzed_only when events database is missing but files exist.

    Verifies:
    - Processing continues without events
    - attach_events_batch() is NOT called
    - Other steps complete successfully
    """
    job_id = "test_job_123"
    task_id = "test_task_456"

    # Setup database mocks
    mock_db_instance = MagicMock()
    mock_db_instance.get_analysis_stats.return_value = {
        "analyzed_files": 2,
        "total_files": 10,
    }
    mock_db_instance.iter_files_batched.return_value = [sample_file_records]

    job_manager._ForensicsDatabase.return_value = mock_db_instance

    # Mock _find_database: files DB exists, events DB doesn't
    def mock_find_db(task_id, db_type):
        if db_type == "files":
            return f"/tmp/{task_id}_files.db"
        return None  # events DB not found

    with patch.object(job_manager, '_find_database', side_effect=mock_find_db):
        # Mock file ingestor methods
        file_result = FileIngestionResult(
            files_created=2,
            files_updated=0,
        )
        job_manager._file_ingestor.batch_ensure_files.return_value = file_result
        job_manager._file_ingestor.merge_duplicate_files.return_value = 0

        # Mock entity builder
        relation_result = RelationBuildResult(mentioned_in_edges_created=0)
        job_manager._entity_builder.batch_create_mentioned_in_edges.return_value = relation_result

        # Mock _update_job_status
        job_manager._update_job_status = AsyncMock()

        # Execute
        await job_manager._process_analyzed_only(job_id, task_id)

    # Verify EventsDatabase was NOT initialized
    job_manager._EventsDatabase.assert_not_called()

    # Verify attach_events_batch was NOT called
    job_manager._file_ingestor.attach_events_batch.assert_not_called()

    # Verify other steps completed
    job_manager._file_ingestor.batch_ensure_files.assert_called_once()
    job_manager._file_ingestor.merge_duplicate_files.assert_called_once()


@pytest.mark.asyncio
async def test_process_analyzed_only_multiple_batches(job_manager, sample_file_records):
    """
    Test _process_analyzed_only with multiple batches of files.

    Verifies:
    - iter_files_batched returns multiple batches
    - All batches are combined and processed
    - Progress callback handles total correctly
    """
    job_id = "test_job_123"
    task_id = "test_task_456"

    # Create more file records for multiple batches
    batch1 = sample_file_records
    batch2 = [
        FileRecord(
            id=3,
            inode=12347,
            name="report.pdf",
            path="/path/to/report.pdf",
            size=4096,
            extension=".pdf",
            category="documents",
            file_type="application/pdf",
            mtime=1640000200,
            ctime=1630000200,
            is_deleted=False,
            md5="ghi789",
            llm_summary="A PDF report",
            llm_description="Contains financial data",
            llm_keywords="financial,report",
            llm_analyzed_at=1640000200,
            llm_model_used="gpt-4",
        ),
    ]

    # Setup database mocks
    mock_db_instance = MagicMock()
    mock_db_instance.get_analysis_stats.return_value = {
        "analyzed_files": 3,
        "total_files": 15,
    }
    mock_db_instance.iter_files_batched.return_value = iter([batch1, batch2])

    job_manager._ForensicsDatabase.return_value = mock_db_instance

    # Mock _find_database
    with patch.object(
        job_manager,
        '_find_database',
        side_effect=lambda task_id, db_type: f"/tmp/{task_id}_{db_type}.db"
    ):
        # Mock file ingestor
        file_result = FileIngestionResult(files_created=3, files_updated=0)
        job_manager._file_ingestor.batch_ensure_files.return_value = file_result
        job_manager._file_ingestor.merge_duplicate_files.return_value = 0

        # Mock events DB with no events
        mock_events_db_instance = MagicMock()
        mock_events_db_instance.get_events.return_value = []
        job_manager._EventsDatabase.return_value = mock_events_db_instance

        # Mock entity builder
        relation_result = RelationBuildResult(mentioned_in_edges_created=0)
        job_manager._entity_builder.batch_create_mentioned_in_edges.return_value = relation_result

        # Mock _update_job_status
        job_manager._update_job_status = AsyncMock()

        # Execute
        await job_manager._process_analyzed_only(job_id, task_id)

    # Verify batch_ensure_files was called with all files from all batches
    job_manager._file_ingestor.batch_ensure_files.assert_called_once()
    call_args = job_manager._file_ingestor.batch_ensure_files.call_args
    all_files = call_args[0][0]
    assert len(all_files) == 3  # 2 from batch1 + 1 from batch2
    assert all_files[0].name == "document.txt"
    assert all_files[1].name == "image.jpg"
    assert all_files[2].name == "report.pdf"


@pytest.mark.asyncio
async def test_process_analyzed_only_no_events_for_analyzed_files(
    job_manager,
    sample_file_records,
):
    """
    Test _process_analyzed_only when events exist but none match analyzed files.

    Verifies:
    - Events database is queried
    - attach_events_batch is called with empty list
    - Processing continues successfully
    """
    job_id = "test_job_123"
    task_id = "test_task_456"

    # Setup database mocks
    mock_db_instance = MagicMock()
    mock_db_instance.get_analysis_stats.return_value = {
        "analyzed_files": 2,
        "total_files": 10,
    }
    mock_db_instance.iter_files_batched.return_value = [sample_file_records]

    # Events for different files (not analyzed)
    other_events = [
        MagicMock(
            file_path="/other/path/file.txt",
            inode=99999,
            event_type="MODIFIED",
            timestamp=1640000000,
        ),
    ]

    mock_events_db_instance = MagicMock()
    mock_events_db_instance.get_events.return_value = other_events

    job_manager._ForensicsDatabase.return_value = mock_db_instance
    job_manager._EventsDatabase.return_value = mock_events_db_instance

    # Mock _find_database
    with patch.object(
        job_manager,
        '_find_database',
        side_effect=lambda task_id, db_type: f"/tmp/{task_id}_{db_type}.db"
    ):
        # Mock file ingestor
        file_result = FileIngestionResult(files_created=2, files_updated=0)
        job_manager._file_ingestor.batch_ensure_files.return_value = file_result
        job_manager._file_ingestor.attach_events_batch.return_value = 0
        job_manager._file_ingestor.merge_duplicate_files.return_value = 0

        # Mock entity builder
        relation_result = RelationBuildResult(mentioned_in_edges_created=0)
        job_manager._entity_builder.batch_create_mentioned_in_edges.return_value = relation_result

        # Mock _update_job_status
        job_manager._update_job_status = AsyncMock()

        # Execute
        await job_manager._process_analyzed_only(job_id, task_id)

    # Verify attach_events_batch was called with empty list (no matching events)
    job_manager._file_ingestor.attach_events_batch.assert_called_once()
    event_list = job_manager._file_ingestor.attach_events_batch.call_args[0][0]
    assert len(event_list) == 0
