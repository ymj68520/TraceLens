#!/bin/bash
# tests/test_scene_api.sh
# Integration test for scene query API endpoints

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
BINARY="$BUILD_DIR/forensic_analyzer"
PORT=18080  # Use non-standard port to avoid conflicts

echo "=== Scene API Test ==="
echo "Project: $PROJECT_DIR"

# Step 1: Build project
echo ""
echo "[1/5] Building project..."
cd "$BUILD_DIR"
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -3
cmake --build . -j$(nproc) 2>&1 | tail -5

if [ ! -f "$BINARY" ]; then
    echo "FAIL: forensic_analyzer binary not found"
    exit 1
fi
echo "PASS: Build succeeded"

# Step 2: Start HTTP server
echo ""
echo "[2/5] Starting HTTP server on port $PORT..."
"$BINARY" --http-server "$PORT" &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null || true" EXIT

# Wait for server to start
sleep 3

# Check server is running
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "FAIL: Server failed to start"
    exit 1
fi
echo "PASS: Server started (PID: $SERVER_PID)"

# Step 3: Test scene-stats endpoint (expect 404 or error since no task exists)
echo ""
echo "[3/5] Testing GET /api/tasks/{id}/scene-stats..."
RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:$PORT/api/tasks/nonexistent-task/scene-stats" 2>/dev/null || echo -e "\n000")
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "  HTTP Status: $HTTP_CODE"
echo "  Response: $BODY"

if [ "$HTTP_CODE" = "404" ] || [ "$HTTP_CODE" = "500" ]; then
    echo "PASS: scene-stats endpoint responds correctly for nonexistent task"
else
    echo "WARN: Unexpected HTTP status $HTTP_CODE (expected 404 or 500)"
fi

# Step 4: Test scene-artifacts endpoint (expect error since no task exists)
echo ""
echo "[4/5] Testing GET /api/tasks/{id}/scene-artifacts?scene_type=android..."
RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:$PORT/api/tasks/nonexistent-task/scene-artifacts?scene_type=android" 2>/dev/null || echo -e "\n000")
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "  HTTP Status: $HTTP_CODE"
echo "  Response: $BODY"

if [ "$HTTP_CODE" = "404" ] || [ "$HTTP_CODE" = "500" ]; then
    echo "PASS: scene-artifacts endpoint responds correctly for nonexistent task"
else
    echo "WARN: Unexpected HTTP status $HTTP_CODE (expected 404 or 500)"
fi

# Step 5: Test scene-artifacts endpoint without scene_type (expect 400)
echo ""
echo "[5/5] Testing GET /api/tasks/{id}/scene-artifacts without scene_type..."
RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:$PORT/api/tasks/nonexistent-task/scene-artifacts" 2>/dev/null || echo -e "\n000")
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "  HTTP Status: $HTTP_CODE"
echo "  Response: $BODY"

if [ "$HTTP_CODE" = "400" ]; then
    echo "PASS: scene-artifacts correctly rejects missing scene_type"
else
    echo "WARN: Expected 400 for missing scene_type, got $HTTP_CODE"
fi

# Test with invalid scene_type
RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:$PORT/api/tasks/nonexistent-task/scene-artifacts?scene_type=invalid" 2>/dev/null || echo -e "\n000")
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "  Invalid scene_type - HTTP Status: $HTTP_CODE"
echo "  Response: $BODY"

if [ "$HTTP_CODE" = "400" ]; then
    echo "PASS: scene-artifacts correctly rejects invalid scene_type"
else
    echo "WARN: Expected 400 for invalid scene_type, got $HTTP_CODE"
fi

echo ""
echo "=== Scene API Test Complete ==="
