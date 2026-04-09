"""
Pytest configuration and shared fixtures for forensics project tests.

This module provides common test fixtures used across unit and integration tests.
"""

import os
import sys
import tempfile
import sqlite3
from pathlib import Path
from typing import Generator, Optional
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest.fixture
def test_db_path() -> Generator[str, None, None]:
    """
    Create a temporary SQLite database file.

    Returns:
        Path to temporary database file.

    Yields:
        Path to temporary database file that will be cleaned up after test.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # Cleanup
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
def database_with_analyzed_files(test_db_path: str) -> str:
    """
    Create a test database with analyzed and unanalyzed files.

    Creates a SQLite database with exact production schema and:
    - 5 analyzed files (llm_analyzed_at IS NOT NULL)
    - 10 unanalyzed files (llm_analyzed_at IS NULL)
    - Total of 15 files

    Args:
        test_db_path: Path to create database at.

    Returns:
        Path to the created database.
    """
    conn = sqlite3.connect(test_db_path)
    cursor = conn.cursor()

    # Create files table with exact production schema
    cursor.execute("""
        CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            extension TEXT,
            category TEXT,
            type TEXT,
            mtime INTEGER,
            ctime INTEGER,
            is_deleted INTEGER,
            md5 TEXT,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT
        )
    """)

    # Current timestamp for LLM analysis
    analyzed_timestamp = int(datetime.now().timestamp())

    # Insert 5 analyzed files with LLM analysis
    analyzed_files = [
        (1, 1001, "report.pdf", "/documents/report.pdf", 102400, ".pdf", "documents", "application/pdf",
         1640000000, 1630000000, 0, "abc123def456",
         "Quarterly financial report", "Detailed Q3 financial analysis with charts and tables",
         "financial,report,q3,pdf", analyzed_timestamp, "gpt-4"),
        (2, 1002, "presentation.pptx", "/documents/presentation.pptx", 2048000, ".pptx", "documents", "application/vnd.ms-powerpoint",
         1640000100, 1630000100, 0, "def456ghi789",
         "Sales presentation deck", "Quarterly sales presentation for executive review",
         "sales,presentation,quarterly", analyzed_timestamp, "gpt-4"),
        (3, 1003, "photo.jpg", "/images/photo.jpg", 512000, ".jpg", "images", "image/jpeg",
         1640000200, 1630000200, 0, "ghi789jkl012",
         "Team photo at conference", "Group photograph from annual tech conference 2024",
         "photo,conference,team", analyzed_timestamp, "gpt-4"),
        (4, 1004, "source.py", "/dev/source.py", 15360, ".py", "source_code", "text/x-python",
         1640000300, 1630000300, 0, "jkl012mno345",
         "Python utility script", "Data processing utility with pandas integration",
         "python,script,data,pandas", analyzed_timestamp, "gpt-4"),
        (5, 1005, "notes.txt", "/notes.txt", 2048, ".txt", "documents", "text/plain",
         1640000400, 1630000400, 0, "mno345pqr678",
         "Meeting notes", "Notes from project planning meeting",
         "meeting,notes,planning", analyzed_timestamp, "gpt-4"),
    ]

    # Insert 10 unanalyzed files (no LLM analysis)
    unanalyzed_files = [
        (6, 1006, "data.csv", "/data.csv", 409600, ".csv", "documents", "text/csv",
         1640000500, 1630000500, 0, "pqr678stu901", None, None, None, None, None),
        (7, 1007, "backup.zip", "/backup.zip", 10485760, ".zip", "archives", "application/zip",
         1640000600, 1630000600, 0, "stu901vwx234", None, None, None, None, None),
        (8, 1008, "config.ini", "/config/config.ini", 1024, ".ini", "system", "text/plain",
         1640000700, 1630000700, 0, "vwx234yza567", None, None, None, None, None),
        (9, 1009, "driver.sys", "/system/driver.sys", 524288, ".sys", "system", "application/octet-stream",
         1640000800, 1630000800, 0, "yza567bcd890", None, None, None, None, None),
        (10, 1010, "log.txt", "/logs/log.txt", 8192, ".txt", "system", "text/plain",
         1640000900, 1630000900, 1, "bcd890efg123", None, None, None, None, None),
        (11, 1011, "image.png", "/images/image.png", 262144, ".png", "images", "image/png",
         1640001000, 1630001000, 0, "efg123hij456", None, None, None, None, None),
        (12, 1012, "music.mp3", "/music.mp3", 3145728, ".mp3", "audio", "audio/mpeg",
         1640001100, 1630001100, 0, "hij456klm789", None, None, None, None, None),
        (13, 1013, "video.mp4", "/videos/video.mp4", 104857600, ".mp4", "videos", "video/mp4",
         1640001200, 1630001200, 0, "klm789nop012", None, None, None, None, None),
        (14, 1014, "document.docx", "/docs/document.docx", 53248, ".docx", "documents", "application/vnd.ms-word",
         1640001300, 1630001300, 0, "nop012qrs345", None, None, None, None, None),
        (15, 1015, "spreadsheet.xlsx", "/docs/spreadsheet.xlsx", 73728, ".xlsx", "documents", "application/vnd.ms-excel",
         1640001400, 1630001400, 0, "qrs345tuv678", None, None, None, None, None),
    ]

    # Insert all files
    cursor.executemany(
        """INSERT INTO files VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        analyzed_files + unanalyzed_files
    )

    conn.commit()
    conn.close()

    return test_db_path


@pytest.fixture
def events_database(test_db_path: str) -> str:
    """
    Create a test events database with timeline events.

    Creates events for both analyzed and unanalyzed files.

    Args:
        test_db_path: Path to create events database at.

    Returns:
        Path to the created events database.
    """
    # Generate events db path
    events_db_path = test_db_path.replace(".db", "_events.db")

    conn = sqlite3.connect(events_db_path)
    cursor = conn.cursor()

    # Create events table
    cursor.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            file_path TEXT,
            inode INTEGER,
            event_type TEXT,
            timestamp INTEGER,
            task_id TEXT
        )
    """)

    # Insert events for analyzed files
    analyzed_events = [
        (1, "/documents/report.pdf", 1001, "MODIFIED", 1640000000, "test_task"),
        (2, "/documents/presentation.pptx", 1002, "CREATED", 1630000100, "test_task"),
        (3, "/images/photo.jpg", 1003, "MODIFIED", 1640000200, "test_task"),
        (4, "/dev/source.py", 1004, "CREATED", 1630000300, "test_task"),
        (5, "/notes.txt", 1005, "ACCESSED", 1640000400, "test_task"),
    ]

    # Insert events for unanalyzed files
    unanalyzed_events = [
        (6, "/data.csv", 1006, "MODIFIED", 1640000500, "test_task"),
        (7, "/backup.zip", 1007, "CREATED", 1630000600, "test_task"),
        (8, "/logs/log.txt", 1009, "DELETED", 1640000900, "test_task"),
    ]

    cursor.executemany(
        """INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)""",
        analyzed_events + unanalyzed_events
    )

    conn.commit()
    conn.close()

    return events_db_path


# =============================================================================
# Neo4j Fixture
# =============================================================================

@pytest.fixture
def neo4j_available() -> bool:
    """
    Check if Neo4j is available for testing.

    Returns:
        True if Neo4j is available, False otherwise.
    """
    try:
        from neo4j import GraphDatabase
        import os

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


# =============================================================================
# FastAPI App Fixture
# =============================================================================

@pytest.fixture
def test_settings():
    """Create test settings for FastAPI app."""
    from httpserver.config import Settings

    return Settings(
        python_http_port=8090,
        cpp_backend_url="http://localhost:8080",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        redis_url="redis://localhost:6379",
        db_output_dir="/tmp/test_db",
    )


@pytest.fixture
def test_app(test_settings):
    """
    Create a test FastAPI application.

    Args:
        test_settings: Test settings.

    Returns:
        FastAPI application instance.
    """
    from httpserver.main import create_app

    # Override settings
    from httpserver.config import get_settings

    def _get_test_settings():
        return test_settings

    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = _get_test_settings

    yield app

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def test_client(test_app):
    """
    Create a test client for FastAPI app.

    Args:
        test_app: FastAPI application.

    Returns:
        TestClient instance.
    """
    from fastapi.testclient import TestClient

    return TestClient(test_app)


# =============================================================================
# Mock C++ Backend Fixture
# =============================================================================

@pytest.fixture
def mock_cpp_backend():
    """
    Mock C++ backend service.

    Returns:
        Mock C++ backend service.
    """
    from unittest.mock import AsyncMock, MagicMock

    backend = MagicMock()
    backend.check_task_exists = AsyncMock(return_value=True)
    backend.get_task_status = AsyncMock(return_value={"status": "completed"})

    return backend
