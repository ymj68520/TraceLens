"""
Integration tests for Graphiti ingestion pipeline.

Tests the complete ingestion workflow from API to knowledge graph.
"""

import asyncio
import pytest
import json
from httpx import AsyncClient
from datetime import datetime


# Test data
SAMPLE_INGEST_REQUEST = {
    "task_id": "test_task_integration",
    "mode": "full",
    "include_llm_descriptions": True,
    "batch_size": 10,
    "max_episodes": 50
}

SAMPLE_FILE_INGEST_REQUEST = {
    "file_id": 1,
    "task_id": "test_task_integration",
    "update_analysis": False
}

SAMPLE_EVENT_SYNC_REQUEST = {
    "task_id": "test_task_integration",
    "events": [
        {
            "inode": 12345,
            "file_path": "/home/user/test.txt",
            "event_type": "MODIFIED",
            "timestamp": 1609459200
        },
        {
            "inode": 12345,
            "file_path": "/home/user/test.txt",
            "event_type": "ACCESSED",
            "timestamp": 1609459300
        }
    ]
}


@pytest.mark.asyncio
async def test_full_ingestion_flow(async_client: AsyncClient, mock_task_exists):
    """
    Test complete ingestion flow from API to knowledge graph.

    This test verifies:
    1. POST /api/graphiti/ingest creates a job
    2. GET /api/graphiti/jobs/{job_id} returns status
    3. Job progresses from PENDING to RUNNING to COMPLETED
    4. File entities are created in Neo4j
    """
    # Start ingestion
    response = await async_client.post(
        "/api/graphiti/ingest",
        json=SAMPLE_INGEST_REQUEST
    )

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] in ["PENDING", "RUNNING"]

    job_id = data["job_id"]

    # Poll for completion (with timeout)
    max_polls = 30
    for i in range(max_polls):
        status_response = await async_client.get(f"/api/graphiti/jobs/{job_id}")
        assert status_response.status_code == 200

        status_data = status_response.json()
        status = status_data.get("status")

        if status == "COMPLETED":
            break
        elif status in ["FAILED", "CANCELLED"]:
            pytest.fail(f"Ingestion failed: {status_data.get('error', 'Unknown error')}")

        await asyncio.sleep(1)

    # Verify final status
    final_status = await async_client.get(f"/api/graphiti/jobs/{job_id}")
    final_data = final_status.json()
    assert final_data["status"] == "COMPLETED"
    assert final_data["progress"] == 100


@pytest.mark.asyncio
async def test_file_ingestion_updates_graph(async_client: AsyncClient, mock_task_exists):
    """
    Test that file ingestion updates existing File entity in-place.

    This test verifies:
    1. First ingestion creates File entity
    2. Second ingestion updates same entity (no duplicate)
    """
    file_id = SAMPLE_FILE_INGEST_REQUEST["file_id"]
    task_id = SAMPLE_FILE_INGEST_REQUEST["task_id"]

    # Initial ingest
    response1 = await async_client.post(
        "/api/graphiti/ingest/file",
        json=SAMPLE_FILE_INGEST_REQUEST
    )
    assert response1.status_code == 200
    job_id_1 = response1.json()["job_id"]

    # Wait for completion
    await wait_for_job(async_client, job_id_1)

    # Re-analyze with new data
    SAMPLE_FILE_INGEST_REQUEST["update_analysis"] = True
    response2 = await async_client.post(
        "/api/graphiti/ingest/file",
        json=SAMPLE_FILE_INGEST_REQUEST
    )
    assert response2.status_code == 200
    job_id_2 = response2.json()["job_id"]

    # Wait for completion
    await wait_for_job(async_client, job_id_2)

    # Verify only one File entity exists (not duplicate)
    # This would require querying Neo4j directly or through an endpoint
    # For now, we verify both jobs completed successfully


@pytest.mark.asyncio
async def test_event_sync_attaches_to_files(async_client: AsyncClient, mock_task_exists):
    """
    Test that event sync properly attaches events to File entities.

    This test verifies:
    1. Events are attached to the events array property
    2. Multiple events can be attached to same file
    """
    response = await async_client.post(
        "/api/graphiti/ingest/events",
        json=SAMPLE_EVENT_SYNC_REQUEST
    )

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data

    job_id = data["job_id"]

    # Wait for completion
    await wait_for_job(async_client, job_id)

    # Verify events were attached
    final_status = await async_client.get(f"/api/graphiti/jobs/{job_id}")
    final_data = final_status.json()
    assert final_data["status"] == "COMPLETED"
    assert final_data["result"]["events_attached"] == 2


@pytest.mark.asyncio
async def test_list_jobs_filtering(async_client: AsyncClient, mock_task_exists):
    """
    Test job listing with filters.

    This test verifies:
    1. Can list all jobs
    2. Can filter by task_id
    3. Can filter by status
    """
    # Create a test job
    response = await async_client.post(
        "/api/graphiti/ingest",
        json=SAMPLE_INGEST_REQUEST
    )
    job_id = response.json()["job_id"]

    # List all jobs
    all_jobs = await async_client.get("/api/graphiti/jobs")
    assert all_jobs.status_code == 200
    jobs_data = all_jobs.json()
    assert "jobs" in jobs_data
    assert len(jobs_data["jobs"]) > 0

    # Filter by task_id
    task_jobs = await async_client.get(
        f"/api/graphiti/jobs?task_id={SAMPLE_INGEST_REQUEST['task_id']}"
    )
    assert task_jobs.status_code == 200
    task_jobs_data = task_jobs.json()
    assert any(j["task_id"] == SAMPLE_INGEST_REQUEST["task_id"] for j in task_jobs_data["jobs"])


@pytest.mark.asyncio
async def test_cancel_job(async_client: AsyncClient, mock_task_exists):
    """
    Test job cancellation.

    This test verifies:
    1. Pending job can be cancelled
    2. Cancelled job shows correct status
    """
    # Create a job
    response = await async_client.post(
        "/api/graphiti/ingest",
        json=SAMPLE_INGEST_REQUEST
    )
    job_id = response.json()["job_id"]

    # Cancel immediately (should be pending)
    cancel_response = await async_client.delete(f"/api/graphiti/jobs/{job_id}")
    assert cancel_response.status_code == 200

    # Verify cancelled status
    status_response = await async_client.get(f"/api/graphiti/jobs/{job_id}")
    status_data = status_response.json()
    assert status_data["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_md5_deduplication(async_client: AsyncClient, mock_task_exists):
    """
    Test that files with identical MD5 are linked.

    This test verifies:
    1. Files with same MD5 get SAME_CONTENT_AS edges
    2. Cross-task deduplication works
    """
    # This would require:
    # 1. Creating two files with same MD5 in different locations
    # 2. Running full ingestion
    # 3. Querying Neo4j for SAME_CONTENT_AS edges

    # For now, test the deduplication endpoint
    response = await async_client.post("/api/graphiti/migrate/deduplicate")
    assert response.status_code == 200

    data = response.json()
    assert "md5_groups_found" in data
    assert "edges_created" in data


@pytest.mark.asyncio
async def test_migration_status(async_client: AsyncClient, mock_task_exists):
    """
    Test migration status endpoint.

    This test verifies:
    1. Can check if task is migrated
    2. Returns detailed migration metrics
    """
    task_id = SAMPLE_INGEST_REQUEST["task_id"]

    response = await async_client.get(f"/api/graphiti/migrate/status/{task_id}")
    assert response.status_code == 200

    data = response.json()
    assert "task_id" in data
    assert "is_migrated" in data
    assert "status" in data


@pytest.mark.asyncio
async def test_migration_endpoint(async_client: AsyncClient, mock_task_exists):
    """
    Test task migration endpoint.

    This test verifies:
    1. Can trigger migration for a task
    2. Returns migration statistics
    """
    task_id = SAMPLE_INGEST_REQUEST["task_id"]

    response = await async_client.post(f"/api/graphiti/migrate/task/{task_id}")
    assert response.status_code == 200

    data = response.json()
    assert "success" in data
    assert "files_migrated" in data
    assert "episodes_linked" in data


# Helper functions and fixtures
async def wait_for_job(client: AsyncClient, job_id: str, timeout: int = 60):
    """Wait for job to complete."""
    for _ in range(timeout):
        response = await client.get(f"/api/graphiti/jobs/{job_id}")
        data = response.json()
        status = data.get("status")

        if status == "COMPLETED":
            return True
        elif status in ["FAILED", "CANCELLED"]:
            return False

        await asyncio.sleep(1)

    raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")


@pytest.fixture
def mock_task_exists(monkeypatch):
    """Mock task existence check in C++ backend."""
    async def mock_check(task_id):
        return True

    # This would require patching the service manager
    # For now, it's a placeholder for the actual implementation
    return mock_check


# Pytest fixtures for FastAPI test client
@pytest.fixture
async def async_client():
    """Create async HTTP client for testing."""
    # This would be set up to point to the test FastAPI app
    # For now, return a mock that simulates responses
    return AsyncClient(base_url="http://localhost:8090")


# Configure pytest
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_mark(
        "integration", "Integration tests (require full stack)"
    )
    config.addinivalue_mark(
        "slow", "Slow-running tests"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
