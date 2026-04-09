# Integration Tests

This directory contains end-to-end integration tests for the forensics project Python service.

## Prerequisites

Integration tests require external services to be running:

- **Neo4j**: Knowledge graph backend (required for all integration tests)
- **Redis**: Optional, for job queue persistence
- **C++ Backend**: Optional, mocked in most tests

## Test Files

### `test_analyzed_only_ingestion_e2e.py`

End-to-end tests for the ANALYZED_ONLY ingestion mode:

- `test_analyzed_only_ingestion_end_to_end`: Complete flow test
  - Verifies ingestion starts successfully
  - Polls job status until completion
  - Validates results and metrics
  - Checks Neo4j for correct entities

- `test_analyzed_only_ingestion_no_analyzed_files`: Edge case test
  - Verifies behavior when no analyzed files exist
  - Validates graceful completion with zero files processed

- `test_analyzed_only_ingestion_database_not_found`: Error case test
  - Verifies proper error handling
  - Validates job failure status

## Running Tests

### Run All Integration Tests

```bash
cd python_service
source .venv/bin/activate
pytest tests/integration/ -v
```

### Run Specific Test

```bash
pytest tests/integration/test_analyzed_only_ingestion_e2e.py::test_analyzed_only_ingestion_end_to_end -v
```

### Run with Verbose Output

```bash
pytest tests/integration/ -v -s
```

### Run with Coverage

```bash
pytest tests/integration/ --cov=python_service --cov-report=html
```

## Test Behavior

### When Neo4j is Available

Tests will:
1. Create temporary test databases
2. Start ingestion via FastAPI endpoints
3. Poll job status until completion
4. Verify results in Neo4j
5. Clean up test data

### When Neo4j is NOT Available

Tests will:
1. Skip gracefully with clear message: "Neo4j not available, skipping integration test"
2. Not fail the test suite
3. Allow unit tests to run successfully

## Test Fixtures

### `database_with_analyzed_files`

Creates a test database with:
- 5 analyzed files (with LLM analysis)
- 10 unanalyzed files (without LLM analysis)
- Production schema matching real forensics databases

### `events_database`

Creates a test events database with:
- Events for analyzed files
- Events for unanalyzed files
- Timeline event data

### `neo4j_available`

Checks if Neo4j is available for testing.
Returns `True` if connected, `False` otherwise.

### `test_client`

Provides a FastAPI `TestClient` for making HTTP requests to the service.

## Environment Variables

Integration tests use these environment variables (from `.env` or defaults):

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
REDIS_URL=redis://localhost:6379
DB_OUTPUT_DIR=/tmp/test_db
```

## Cleanup

Integration tests automatically clean up:
- Temporary test databases
- Test task directories
- Neo4j test data (when possible)

If tests fail, cleanup may be incomplete. Manual cleanup:

```bash
# Remove test databases
rm -rf /tmp/test_db/tasks/test_task_*

# Clean Neo4j (requires cypher-shell)
cypher-shell -u neo4j -p password "MATCH (f:File {task_id: 'test_task_*'}) DETACH DELETE f"
```

## Troubleshooting

### Tests Skip with "Neo4j not available"

**Solution**: Start Neo4j service
```bash
sudo systemctl start neo4j
# or
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest
```

### Tests Fail with "Task not found"

**Solution**: Ensure test databases are being created in the correct location
```bash
ls -la /tmp/test_db/tasks/
```

### Tests Timeout

**Solution**: Increase timeout in test file or check if services are responsive
```bash
# Check Neo4j
curl http://localhost:7474

# Check Python service
curl http://localhost:8090/health
```

## Adding New Integration Tests

1. Create test file in `tests/integration/`
2. Use `@pytest.mark.integration` decorator
3. Add `neo4j_available` fixture and skip if unavailable
4. Clean up test data in `finally` blocks
5. Document test in this README

Example:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_my_new_integration(test_client, neo4j_available):
    if not neo4j_available:
        pytest.skip("Neo4j not available, skipping integration test")

    # Test implementation...
```

## Continuous Integration

In CI/CD pipelines:

1. Start Neo4j service before tests
2. Run integration tests with `pytest tests/integration/`
3. Cleanup services after tests
4. Report test results

Example CI configuration:

```yaml
services:
  - neo4j:latest

environment:
  NEO4J_URI: bolt://localhost:7687
  NEO4J_USER: neo4j
  NEO4J_PASSWORD: password

steps:
  - pip install -r requirements.txt
  - pytest tests/integration/ -v
```
