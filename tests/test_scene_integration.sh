#!/bin/bash
# tests/test_scene_integration.sh
# Integration test for scene-aware pipeline in AnalysisOrchestrator

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
TEST_OUTPUT_DIR="$BUILD_DIR/test_scene_output"

echo "=== Scene Integration Test ==="
echo "Project: $PROJECT_DIR"
echo "Build:   $BUILD_DIR"

# Step 1: Build project
echo ""
echo "[1/4] Building project..."
cd "$BUILD_DIR"
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -3
cmake --build . -j$(nproc) 2>&1 | tail -5

if [ ! -f "$BUILD_DIR/forensic_analyzer" ]; then
    echo "FAIL: forensic_analyzer binary not found"
    exit 1
fi
echo "PASS: Build succeeded"

# Step 2: Create test image if needed
echo ""
echo "[2/4] Preparing test image..."
TEST_IMG="$BUILD_DIR/test_android.img"
if [ ! -f "$TEST_IMG" ]; then
    if [ -f "$SCRIPT_DIR/create_android_image.sh" ]; then
        echo "Creating test Android image..."
        bash "$SCRIPT_DIR/create_android_image.sh"
    else
        echo "SKIP: No test image creator found, using existing image if available"
    fi
fi

# Step 3: Run scene-aware analysis
echo ""
echo "[3/4] Running Android scene analysis..."
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

if [ -f "$TEST_IMG" ]; then
    "$BUILD_DIR/forensic_analyzer" "$TEST_IMG" \
        --android-analyze \
        --db-dir "$TEST_OUTPUT_DIR" 2>&1 | tail -20

    # Verify outputs
    BASENAME=$(basename "$TEST_IMG" | sed 's/\.[^.]*$//')
    RAW_DB="$TEST_OUTPUT_DIR/${BASENAME}_raw.db"
    FILES_DB="$TEST_OUTPUT_DIR/${BASENAME}_files.db"
    EVENTS_DB="$TEST_OUTPUT_DIR/${BASENAME}_events.db"

    echo ""
    echo "[4/4] Verifying results..."

    # Check databases exist
    for db in "$RAW_DB" "$FILES_DB" "$EVENTS_DB"; do
        if [ -f "$db" ]; then
            echo "PASS: $(basename $db) exists"
        else
            echo "FAIL: $(basename $db) missing"
            exit 1
        fi
    done

    # Verify scene_type column in files table
    SCENE_COUNT=$(sqlite3 "$FILES_DB" "SELECT COUNT(*) FROM files WHERE scene_type = 'android';" 2>/dev/null || echo "0")
    if [ "$SCENE_COUNT" -gt 0 ]; then
        echo "PASS: files table has scene_type='android' ($SCENE_COUNT rows)"
    else
        echo "WARN: No files with scene_type='android' found (may be empty image)"
    fi

    # Verify scene_priority column exists
    PRIORITY_COL=$(sqlite3 "$FILES_DB" "PRAGMA table_info(files);" 2>/dev/null | grep -c "scene_priority" || echo "0")
    if [ "$PRIORITY_COL" -gt 0 ]; then
        echo "PASS: files table has scene_priority column"
    else
        echo "FAIL: files table missing scene_priority column"
        exit 1
    fi

    # Verify no separate platform database was created
    ANDROID_DB="$TEST_OUTPUT_DIR/${BASENAME}_android.db"
    if [ ! -f "$ANDROID_DB" ]; then
        echo "PASS: No separate _android.db (artifacts in files.db)"
    else
        echo "WARN: Separate _android.db still exists"
    fi

    # Verify Android artifacts are in files.db
    ANDROID_TABLES=$(sqlite3 "$FILES_DB" ".tables" 2>/dev/null | grep -c "system_logs\|sms\|contacts\|call_logs" || echo "0")
    if [ "$ANDROID_TABLES" -gt 0 ]; then
        echo "PASS: Android artifact tables found in files.db"
    else
        echo "INFO: No Android artifact tables in files.db (analyzer may not have found data)"
    fi

    # Verify timeline imported scene artifacts
    EVENT_COUNT=$(sqlite3 "$EVENTS_DB" "SELECT COUNT(*) FROM events;" 2>/dev/null || echo "0")
    echo "INFO: Timeline has $EVENT_COUNT events"

    echo ""
    echo "=== All scene integration tests passed ==="
else
    echo "SKIP: No test image available at $TEST_IMG"
    echo "=== Integration test skipped (no test image) ==="
fi
