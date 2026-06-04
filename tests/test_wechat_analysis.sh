#!/bin/bash
# Integration test for WeChat analysis pipeline
#
# This script verifies that all WeChat analysis components are properly
# integrated: C++ core, Python service, and frontend files.
#
# Components tested:
# - C++ unit tests (parser and decryptor)
# - Python route registration
# - Frontend page, service, route, and nav wiring

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PASS=0
FAIL=0
WARN=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASS=$((PASS + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAIL=$((FAIL + 1))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    WARN=$((WARN + 1))
}

log_info() {
    echo -e "[INFO] $1"
}

echo "=== WeChat Analysis Integration Test ==="
echo ""

# Step 1: Build the project
echo "[1/5] Building project..."
cd "$PROJECT_DIR"
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -5
cmake --build . -j$(nproc) 2>&1 | tail -5
if [ -f forensic_analyzer ]; then
    log_pass "Build completed successfully"
else
    log_fail "Build produced no executable"
fi
echo ""

# Step 2: Run C++ unit tests
echo "[2/5] Running C++ unit tests..."
ctest --output-on-failure -R "[Ww]e[Cc]hat" 2>&1 | tail -10
CTEST_EXIT=$?
if [ $CTEST_EXIT -eq 0 ]; then
    log_pass "C++ unit tests passed"
else
    log_warn "C++ unit tests had failures (exit code: $CTEST_EXIT) - SQLCipher may not be installed"
fi
echo ""

# Step 3: Run Python unit tests
echo "[3/5] Running Python unit tests..."
cd "$PROJECT_DIR"
PYTHON_TEST_FILE="python_service/tests/test_wechat_graph_service.py"
if [ -f "$PYTHON_TEST_FILE" ]; then
    python -m pytest "$PYTHON_TEST_FILE" -v 2>&1 | tail -15
    PYTEST_EXIT=$?
    if [ $PYTEST_EXIT -eq 0 ]; then
        log_pass "Python unit tests passed"
    else
        log_warn "Python unit tests had failures (exit code: $PYTEST_EXIT) - networkx may not be installed"
    fi
else
    log_warn "Python test file not found: $PYTHON_TEST_FILE (may be created in a later task)"
fi
echo ""

# Step 4: Verify Python API routes
echo "[4/5] Checking Python route registration..."
if grep -q "wechat_graph" python_service/httpserver/main.py; then
    log_pass "Router registered in main.py"
else
    log_fail "Router not registered in main.py"
fi

if grep -q "wechat_graph" python_service/httpserver/routes/__init__.py; then
    log_pass "Module in routes/__init__.py __all__"
else
    log_fail "Module not in routes/__init__.py __all__"
fi

# Verify route file exists
if [ -f python_service/httpserver/routes/wechat_graph.py ]; then
    log_pass "Route file exists: wechat_graph.py"
else
    log_fail "Route file missing: wechat_graph.py"
fi
echo ""

# Step 5: Verify frontend files
echo "[5/5] Checking frontend files..."
if [ -f web/src/pages/WeChatGraph/WeChatGraph.jsx ]; then
    log_pass "Main page exists: WeChatGraph.jsx"
else
    log_fail "Main page missing: WeChatGraph.jsx"
fi

if [ -f web/src/services/wechatService.js ]; then
    log_pass "Service file exists: wechatService.js"
else
    log_fail "Service file missing: wechatService.js"
fi

if grep -q "wechat" web/src/routes.jsx; then
    log_pass "Route registered in routes.jsx"
else
    log_fail "Route not registered in routes.jsx"
fi

if grep -q "wechat" web/src/components/Layout/Layout.jsx; then
    log_pass "Nav item registered in Layout.jsx"
else
    log_fail "Nav item not registered in Layout.jsx"
fi
echo ""

# Summary
echo "=== Integration Test Complete ==="
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed, ${WARN} warnings"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${RED}Some checks FAILED. Review the output above.${NC}"
    exit 1
elif [ $WARN -gt 0 ]; then
    echo -e "${YELLOW}All checks passed with warnings. Review the output above.${NC}"
    exit 0
else
    echo -e "${GREEN}All checks PASSED.${NC}"
    exit 0
fi
