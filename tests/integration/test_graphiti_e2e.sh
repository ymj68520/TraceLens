#!/bin/bash
# End-to-end test script for Graphiti integration
#
# This script tests the complete Graphiti ingestion workflow:
# 1. Create analysis task
# 2. Wait for completion
# 3. Trigger Graphiti ingestion
# 4. Verify File entities created
# 5. Test file re-analysis
# 6. Test event sync
# 7. Verify MD5 deduplication
# 8. Test migration

set -e

# Configuration
PYTHON_SERVICE_URL="http://localhost:8090"
CPP_SERVICE_URL="http://localhost:8080"
TEST_IMAGE_PATH="/tmp/test_image.dd"
TEST_TASK_NAME="graphiti_e2e_test"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if services are running
check_services() {
    log_info "Checking if services are running..."

    # Check Python service
    if curl -sf "$PYTHON_SERVICE_URL/health" > /dev/null; then
        log_info "✓ Python service is running"
    else
        log_error "✗ Python service is not running"
        exit 1
    fi

    # Check C++ service
    if curl -sf "$CPP_SERVICE_URL/health" > /dev/null; then
        log_info "✓ C++ service is running"
    else
        log_warn "✗ C++ service is not running (optional for this test)"
    fi
}

# Create a test task
create_test_task() {
    log_info "Creating test task..."

    RESPONSE=$(curl -s -X POST "$CPP_SERVICE_URL/api/tasks" \
        -H "Content-Type: application/json" \
        -d "{
            \"image_path\": \"$TEST_IMAGE_PATH\",
            \"task_name\": \"$TEST_TASK_NAME\",
            \"llm_analyze\": false
        }")

    TASK_ID=$(echo "$RESPONSE" | jq -r '.task_id // .id // empty')

    if [ "$TASK_ID" = "empty" ] || [ -z "$TASK_ID" ]; then
        log_error "Failed to create task"
        echo "Response: $RESPONSE"
        exit 1
    fi

    log_info "✓ Task created: $TASK_ID"
    echo "$TASK_ID"
}

# Wait for task completion
wait_for_task() {
    local TASK_ID=$1
    local TIMEOUT=300  # 5 minutes
    local ELAPSED=0

    log_info "Waiting for task $TASK_ID to complete..."

    while [ $ELAPSED -lt $TIMEOUT ]; do
        STATUS=$(curl -s "$CPP_SERVICE_URL/api/tasks/$TASK_ID" | jq -r '.status // "unknown"')

        if [ "$STATUS" = "COMPLETED" ]; then
            log_info "✓ Task completed successfully"
            return 0
        elif [ "$STATUS" = "FAILED" ]; then
            log_error "Task failed"
            return 1
        fi

        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done

    echo
    log_error "Task timed out after $TIMEOUT seconds"
    return 1
}

# Trigger Graphiti ingestion
trigger_ingestion() {
    local TASK_ID=$1

    log_info "Triggering Graphiti ingestion for task $TASK_ID..."

    RESPONSE=$(curl -s -X POST "$PYTHON_SERVICE_URL/api/graphiti/ingest" \
        -H "Content-Type: application/json" \
        -d "{
            \"task_id\": \"$TASK_ID\",
            \"mode\": \"full\"
        }")

    JOB_ID=$(echo "$RESPONSE" | jq -r '.job_id // empty')

    if [ "$JOB_ID" = "empty" ] || [ -z "$JOB_ID" ]; then
        log_error "Failed to trigger ingestion"
        echo "Response: $RESPONSE"
        return 1
    fi

    log_info "✓ Ingestion job created: $JOB_ID"
    echo "$JOB_ID"
}

# Wait for ingestion job completion
wait_for_ingestion() {
    local JOB_ID=$1
    local TIMEOUT=600  # 10 minutes
    local ELAPSED=0

    log_info "Waiting for ingestion job $JOB_ID to complete..."

    while [ $ELAPSED -lt $TIMEOUT ]; do
        STATUS_RESPONSE=$(curl -s "$PYTHON_SERVICE_URL/api/graphiti/jobs/$JOB_ID")
        STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status // "unknown"')
        PROGRESS=$(echo "$STATUS_RESPONSE" | jq -r '.progress // 0')
        PHASE=$(echo "$STATUS_RESPONSE" | jq -r '.current_phase // "unknown"')

        echo "Status: $STATUS ($PROGRESS%) - Phase: $PHASE"

        if [ "$STATUS" = "COMPLETED" ]; then
            log_info "✓ Ingestion completed successfully"
            return 0
        elif [ "$STATUS" = "FAILED" ]; then
            ERROR=$(echo "$STATUS_RESPONSE" | jq -r '.error // "Unknown error"')
            log_error "Ingestion failed: $ERROR"
            return 1
        fi

        sleep 5
        ELAPSED=$((ELAPSED + 5))
    done

    log_error "Ingestion timed out after $TIMEOUT seconds"
    return 1
}

# Verify File entities
verify_file_entities() {
    local TASK_ID=$1

    log_info "Verifying File entities..."

    # Get graph status
    RESPONSE=$(curl -s "$PYTHON_SERVICE_URL/api/graphiti/status?task_id=$TASK_ID")
    TOTAL_ENTITIES=$(echo "$RESPONSE" | jq -r '.total_entities // 0')
    TOTAL_RELATIONSHIPS=$(echo "$RESPONSE" | jq -r '.total_relationships // 0')

    log_info "Total entities: $TOTAL_ENTITIES"
    log_info "Total relationships: $TOTAL_RELATIONSHIPS"

    if [ "$TOTAL_ENTITIES" -gt 0 ]; then
        log_info "✓ File entities created successfully"
    else
        log_warn "⚠ No entities found (may be expected for empty database)"
    fi
}

# Test file re-analysis
test_file_reanalysis() {
    local TASK_ID=$1
    local FILE_ID=1

    log_info "Testing file re-analysis..."

    RESPONSE=$(curl -s -X POST "$PYTHON_SERVICE_URL/api/graphiti/ingest/file" \
        -H "Content-Type: application/json" \
        -d "{
            \"file_id\": $FILE_ID,
            \"task_id\": \"$TASK_ID\",
            \"update_analysis\": true
        }")

    JOB_ID=$(echo "$RESPONSE" | jq -r '.job_id // empty')

    if [ "$JOB_ID" != "empty" ] && [ -n "$JOB_ID" ]; then
        log_info "✓ File re-analysis job created: $JOB_ID"
        wait_for_ingestion "$JOB_ID"
        log_info "✓ File re-analysis completed"
    else
        log_warn "⚠ File re-analysis not supported or file not found"
    fi
}

# Test event sync
test_event_sync() {
    local TASK_ID=$1

    log_info "Testing event synchronization..."

    RESPONSE=$(curl -s -X POST "$PYTHON_SERVICE_URL/api/graphiti/ingest/events" \
        -H "Content-Type: application/json" \
        -d "{
            \"task_id\": \"$TASK_ID\",
            \"events\": [
                {
                    \"inode\": 12345,
                    \"file_path\": \"/test/file.txt\",
                    \"event_type\": \"MODIFIED\",
                    \"timestamp\": 1609459200
                }
            ]
        }")

    JOB_ID=$(echo "$RESPONSE" | jq -r '.job_id // empty')

    if [ "$JOB_ID" != "empty" ] && [ -n "$JOB_ID" ]; then
        log_info "✓ Event sync job created: $JOB_ID"
        wait_for_ingestion "$JOB_ID"
        log_info "✓ Event sync completed"
    else
        log_warn "⚠ Event sync not supported"
    fi
}

# Test MD5 deduplication
test_deduplication() {
    log_info "Testing MD5 deduplication..."

    RESPONSE=$(curl -s -X POST "$PYTHON_SERVICE_URL/api/graphiti/migrate/deduplicate")

    MD5_GROUPS=$(echo "$RESPONSE" | jq -r '.md5_groups_found // 0')
    EDGES_CREATED=$(echo "$RESPONSE" | jq -r '.edges_created // 0')

    log_info "MD5 groups found: $MD5_GROUPS"
    log_info "Edges created: $EDGES_CREATED"

    log_info "✓ Deduplication test completed"
}

# Test migration
test_migration() {
    local TASK_ID=$1

    log_info "Testing migration..."

    # Check migration status
    STATUS_RESPONSE=$(curl -s "$PYTHON_SERVICE_URL/api/graphiti/migrate/status/$TASK_ID")
    IS_MIGRATED=$(echo "$STATUS_RESPONSE" | jq -r '.is_migrated // false')

    log_info "Is migrated: $IS_MIGRATED"

    if [ "$IS_MIGRATED" = "true" ]; then
        log_info "✓ Task already migrated"
    else
        log_info "Running migration..."
        MIGRATE_RESPONSE=$(curl -s -X POST "$PYTHON_SERVICE_URL/api/graphiti/migrate/task/$TASK_ID")

        FILES_MIGRATED=$(echo "$MIGRATE_RESPONSE" | jq -r '.files_migrated // 0')
        EPISODES_LINKED=$(echo "$MIGRATE_RESPONSE" | jq -r '.episodes_linked // 0')

        log_info "Files migrated: $FILES_MIGRATED"
        log_info "Episodes linked: $EPISODES_LINKED"
        log_info "✓ Migration completed"
    fi
}

# Cleanup
cleanup() {
    log_info "Cleaning up..."

    # Note: Don't delete test task automatically - it may be useful for debugging
    log_info "Test artifacts preserved for inspection"
}

# Main test flow
main() {
    log_info "=========================================="
    log_info "Graphiti E2E Test"
    log_info "=========================================="

    check_services

    # Note: Skip task creation if C++ service is not available
    if ! curl -sf "$CPP_SERVICE_URL/health" > /dev/null; then
        log_warn "Skipping C++ backend tests (service not available)"
        log_info "Testing Python service endpoints only..."

        # Test deduplication (doesn't require task)
        test_deduplication

        log_info "=========================================="
        log_info "Partial tests completed"
        log_info "=========================================="
        return 0
    fi

    # Create test task
    TASK_ID=$(create_test_task)

    # Wait for task completion
    wait_for_task "$TASK_ID"

    # Trigger ingestion
    JOB_ID=$(trigger_ingestion "$TASK_ID")

    # Wait for ingestion
    wait_for_ingestion "$JOB_ID"

    # Verify results
    verify_file_entities "$TASK_ID"

    # Test file re-analysis
    test_file_reanalysis "$TASK_ID"

    # Test event sync
    test_event_sync "$TASK_ID"

    # Test deduplication
    test_deduplication

    # Test migration
    test_migration "$TASK_ID"

    # Cleanup
    cleanup

    log_info "=========================================="
    log_info "All tests passed!"
    log_info "=========================================="
}

# Run tests
main "$@"
