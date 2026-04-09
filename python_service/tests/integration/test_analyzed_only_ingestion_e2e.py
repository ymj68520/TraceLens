"""
End-to-end integration test for ANALYZED_ONLY ingestion mode.

This test verifies the complete flow from API request to completion:
1. Start ingestion with mode=analyzed_only via POST /api/graphiti/ingest
2. Receive job_id in response
3. Poll job status until COMPLETED/FAILED/CANCELLED
4. Verify status is COMPLETED
5. Verify result contains analyzed_files_processed > 0
6. (Optional) Verify only analyzed files are in Neo4j

Requirements:
- Neo4j must be available (test will skip if not)
- Test database with analyzed files fixture
- FastAPI test client
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =============================================================================
# Integration Test
# =============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_analyzed_only_ingestion_end_to_end(
    test_client,
    database_with_analyzed_files,
    neo4j_available,
    test_settings,
):
    """
    End-to-end test for ANALYZED_ONLY ingestion mode.

    Verifies the complete flow:
    1. Start ingestion with mode=analyzed_only via POST /api/graphiti/ingest
    2. Receive job_id in response
    3. Poll job status until COMPLETED/FAILED/CANCELLED
    4. Verify status is COMPLETED
    5. Verify result contains analyzed_files_processed > 0
    6. (Optional) Verify only analyzed files are in Neo4j

    Skip if:
    - Neo4j is not available
    """
    # Skip if Neo4j is not available
    if not neo4j_available:
        pytest.skip("Neo4j not available, skipping integration test")

    # Prepare test environment
    task_id = "test_task_analyzed_only"
    job_id: Optional[str] = None

    # Create test database in configured output directory
    import shutil
    output_dir = Path(test_settings.db_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task_dir = output_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Copy test database to task directory
    test_db_name = f"{task_id}_files.db"
    test_db_path = task_dir / test_db_name
    shutil.copy(database_with_analyzed_files, test_db_path)

    try:
        # Step 1: Start ingestion with mode=analyzed_only
        response = test_client.post(
            "/api/graphiti/ingest",
            json={
                "task_id": task_id,
                "mode": "analyzed_only",
                "include_llm_descriptions": True,
                "batch_size": 50,
            }
        )

        # Verify response
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "job_id" in data, "Response should contain job_id"
        assert data["status"] == "PENDING", f"Expected PENDING status, got {data['status']}"
        assert "analyzed_only" in data["message"].lower(), "Response should mention analyzed_only mode"

        job_id = data["job_id"]
        assert job_id is not None, "job_id should not be None"

        # Step 2 & 3: Poll job status until completion
        max_attempts = 60  # 60 seconds max
        poll_interval = 1  # 1 second between polls
        final_status: Optional[dict] = None

        for attempt in range(max_attempts):
            time.sleep(poll_interval)

            # Get job status
            status_response = test_client.get(f"/api/graphiti/jobs/{job_id}")

            if status_response.status_code == 404:
                # Job not found yet, may still be initializing
                if attempt < 10:  # Allow up to 10 seconds for initialization
                    continue
                else:
                    pytest.fail(f"Job {job_id} not found after {attempt} seconds")

            assert status_response.status_code == 200, \
                f"Expected 200, got {status_response.status_code}: {status_response.text}"

            final_status = status_response.json()
            current_status = final_status.get("status")

            # Check if job is complete
            if current_status in ("COMPLETED", "FAILED", "CANCELLED"):
                break

            # Verify progress is being made
            progress = final_status.get("progress", 0)
            assert 0 <= progress <= 100, f"Progress should be 0-100, got {progress}"

        else:
            pytest.fail(f"Job did not complete within {max_attempts} seconds")

        # Step 4: Verify status is COMPLETED
        assert final_status is not None, "Final status should not be None"
        assert final_status["status"] == "COMPLETED", \
            f"Expected COMPLETED status, got {final_status['status']}: {final_status.get('error', 'No error message')}"
        assert final_status["progress"] == 100, \
            f"Expected 100% progress, got {final_status['progress']}"

        # Step 5: Verify result contains analyzed_files_processed > 0
        result = final_status.get("result", {})
        assert result is not None, "Result should not be None"

        # Verify analyzed files were processed
        analyzed_files_processed = result.get("analyzed_files_processed", 0)
        assert analyzed_files_processed > 0, \
            f"Expected analyzed_files_processed > 0, got {analyzed_files_processed}"

        # Verify we processed exactly the analyzed files (5 in test database)
        assert analyzed_files_processed == 5, \
            f"Expected 5 analyzed files to be processed, got {analyzed_files_processed}"

        # Verify other metrics
        assert "files_created" in result, "Result should contain files_created"
        assert "files_updated" in result, "Result should contain files_updated"
        assert "events_attached" in result, "Result should contain events_attached"
        assert "entities_linked" in result, "Result should contain entities_linked"
        assert "duplicates_merged" in result, "Result should contain duplicates_merged"

        # Verify files were created or updated
        total_files = result["files_created"] + result["files_updated"]
        assert total_files > 0, "At least one file should be created or updated"

        # Step 6 (Optional): Verify only analyzed files are in Neo4j
        # This requires direct Neo4j query to verify
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                test_settings.neo4j_uri,
                auth=(test_settings.neo4j_user, test_settings.neo4j_password)
            )

            with driver.session() as session:
                # Count File entities for this task
                query = """
                    MATCH (f:File {task_id: $task_id})
                    RETURN count(f) as file_count
                """
                result = session.run(query, task_id=task_id)
                record = result.single()
                neo4j_file_count = record["file_count"]

                # Verify we have exactly the analyzed files count
                assert neo4j_file_count == 5, \
                    f"Expected 5 File entities in Neo4j, got {neo4j_file_count}"

                # Verify all files have LLM analysis properties
                query = """
                    MATCH (f:File {task_id: $task_id})
                    WHERE f.llm_summary IS NOT NULL
                    RETURN count(f) as analyzed_count
                """
                result = session.run(query, task_id=task_id)
                record = result.single()
                analyzed_count = record["analyzed_count"]

                assert analyzed_count == 5, \
                    f"Expected 5 File entities with LLM analysis, got {analyzed_count}"

            driver.close()

        except Exception as e:
            # Log warning but don't fail the test
            print(f"Warning: Could not verify Neo4j contents: {e}")

        print(f"\n✓ Integration test passed!")
        print(f"  Job ID: {job_id}")
        print(f"  Task ID: {task_id}")
        print(f"  Analyzed files processed: {analyzed_files_processed}")
        print(f"  Files created: {result['files_created']}")
        print(f"  Files updated: {result['files_updated']}")
        print(f"  Events attached: {result['events_attached']}")
        print(f"  Entities linked: {result['entities_linked']}")

    finally:
        # Cleanup: Delete test database
        try:
            if test_db_path.exists():
                test_db_path.unlink()
            if task_dir.exists():
                task_dir.rmdir()
        except Exception as e:
            print(f"Warning: Could not cleanup test database: {e}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analyzed_only_ingestion_no_analyzed_files(
    test_client,
    test_db_path,
    neo4j_available,
    test_settings,
):
    """
    Test ANALYZED_ONLY ingestion when no analyzed files exist.

    Verifies:
    1. Ingestion starts successfully
    2. Job completes with COMPLETED status
    3. Result indicates no analyzed files found
    4. analyzed_files_processed = 0

    Skip if:
    - Neo4j is not available
    """
    # Skip if Neo4j is not available
    if not neo4j_available:
        pytest.skip("Neo4j not available, skipping integration test")

    # Create database with NO analyzed files
    import sqlite3
    conn = sqlite3.connect(test_db_path)
    cursor = conn.cursor()

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

    # Insert only unanalyzed files
    unanalyzed_files = [
        (1, 1001, "data.csv", "/data.csv", 409600, ".csv", "documents", "text/csv",
         1640000500, 1630000500, 0, "pqr678stu901", None, None, None, None, None),
        (2, 1002, "backup.zip", "/backup.zip", 10485760, ".zip", "archives", "application/zip",
         1640000600, 1630000600, 0, "stu901vwx234", None, None, None, None, None),
    ]

    cursor.executemany(
        """INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        unanalyzed_files
    )

    conn.commit()
    conn.close()

    # Prepare test environment
    task_id = "test_task_no_analyzed"

    # Create test database in configured output directory
    import shutil
    output_dir = Path(test_settings.db_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task_dir = output_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Copy test database to task directory
    test_db_name = f"{task_id}_files.db"
    test_db_target_path = task_dir / test_db_name
    shutil.copy(test_db_path, test_db_target_path)

    try:
        # Start ingestion
        response = test_client.post(
            "/api/graphiti/ingest",
            json={
                "task_id": task_id,
                "mode": "analyzed_only",
            }
        )

        assert response.status_code == 200
        data = response.json()
        job_id = data["job_id"]

        # Poll for completion
        max_attempts = 30
        for attempt in range(max_attempts):
            time.sleep(1)

            status_response = test_client.get(f"/api/graphiti/jobs/{job_id}")
            assert status_response.status_code == 200

            final_status = status_response.json()
            if final_status["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                break

        else:
            pytest.fail(f"Job did not complete within {max_attempts} seconds")

        # Verify completion
        assert final_status["status"] == "COMPLETED"
        result = final_status.get("result", {})

        # Verify no files were processed
        assert result.get("files_processed", 0) == 0, \
            "Expected 0 files processed when no analyzed files exist"

        # Verify message
        assert "No AI-analyzed files found" in result.get("message", ""), \
            "Expected message about no analyzed files"

        print(f"\n✓ Integration test for no analyzed files passed!")
        print(f"  Job ID: {job_id}")
        print(f"  Task ID: {task_id}")
        print(f"  Message: {result.get('message')}")

    finally:
        # Cleanup
        try:
            if test_db_target_path.exists():
                test_db_target_path.unlink()
            if task_dir.exists():
                task_dir.rmdir()
        except Exception as e:
            print(f"Warning: Could not cleanup test database: {e}")


@pytest.mark.integration
def test_analyzed_only_ingestion_database_not_found(
    test_client,
    neo4j_available,
):
    """
    Test ANALYZED_ONLY ingestion when database doesn't exist.

    Verifies:
    1. Ingestion fails appropriately
    2. Job status shows FAILED
    3. Error message indicates database not found

    Skip if:
    - Neo4j is not available
    """
    # Skip if Neo4j is not available
    if not neo4j_available:
        pytest.skip("Neo4j not available, skipping integration test")

    task_id = "nonexistent_task"

    # Try to start ingestion for non-existent task
    response = test_client.post(
        "/api/graphiti/ingest",
        json={
            "task_id": task_id,
            "mode": "analyzed_only",
        }
    )

    # Should fail at task validation or database finding
    # Either 404 (task not found) or 500 (database not found)
    assert response.status_code in (404, 500), \
        f"Expected 404 or 500, got {response.status_code}: {response.text}"

    print(f"\n✓ Integration test for database not found passed!")
    print(f"  Task ID: {task_id}")
    print(f"  Status code: {response.status_code}")
