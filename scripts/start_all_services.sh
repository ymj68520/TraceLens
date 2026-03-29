#!/bin/bash
# Start all ForensicsProject services
# This script starts C++ server, Python service (with venv), and serves the Web frontend
#
# Usage:
#   make start_all               # From build directory
#   ./scripts/start_all_services.sh  # From project root

set -e

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${PROJECT_ROOT}/build"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Banner
echo -e "${CYAN}${BOLD}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║        ForensicsProject - Starting All Services            ║"
echo "║     C++ Server + Python Service + Web Frontend             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Load environment variables from .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${GREEN}✓${NC} Loading environment from ${BOLD}.env${NC}"
    set -a  # Automatically export all variables
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo -e "${YELLOW}⚠${NC} No .env file found, using defaults"
fi

# Default ports
CPP_PORT=${HTTP_SERVER_PORT:-8080}
PYTHON_PORT=${PYTHON_HTTP_PORT:-8090}
WEB_PORT=${CPP_PORT}  # Web is served by C++ server

# PIDs for cleanup
CPP_PID=""
PYTHON_PID=""

# Create logs directory
LOG_DIR="$BUILD_DIR/logs"
mkdir -p "$LOG_DIR"

# Health check function
check_service() {
    local url=$1
    local name=$2
    local max_attempts=$3
    local attempt=1

    echo -ne "${CYAN}Waiting for $name...${NC}"

    while [ $attempt -le $max_attempts ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200\|404"; then
            echo -e " ${GREEN}✓ Ready${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
        ((attempt++))
    done

    echo -e " ${RED}✗ Failed${NC}"
    return 1
}

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}───────────────────────────────────────────────────────${NC}"
    echo -e "${YELLOW}Shutting down all services...${NC}"
    echo -e "${YELLOW}───────────────────────────────────────────────────────${NC}"

    if [ ! -z "$PYTHON_PID" ]; then
        echo -ne "${YELLOW}Stopping Python service (PID: $PYTHON_PID)...${NC} "
        kill $PYTHON_PID 2>/dev/null || true
        wait $PYTHON_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Stopped${NC}"
    fi

    if [ ! -z "$CPP_PID" ]; then
        echo -ne "${YELLOW}Stopping C++ server (PID: $CPP_PID)...${NC} "
        kill $CPP_PID 2>/dev/null || true
        wait $CPP_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Stopped${NC}"
    fi

    echo -e "${GREEN}✓ All services stopped${NC}"
    echo -e "${YELLOW}───────────────────────────────────────────────────────${NC}"
    
    # Crucial for Make: exit with 0 to prevent "Error 130" when user presses Ctrl+C
    trap - EXIT INT TERM
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup EXIT INT TERM

# ========================================================================
# Pre-startup: Kill any existing services
# ========================================================================
echo -e "\n${YELLOW}➤ Checking for existing services...${NC}"
echo -e "${YELLOW}────────────────────────────────────────────────────────────${NC}"

# Kill any existing forensic_analyzer processes on our ports
EXISTING_CPP=$(lsof -ti :$CPP_PORT 2>/dev/null || true)
EXISTING_PY=$(lsof -ti :$PYTHON_PORT 2>/dev/null || true)

if [ ! -z "$EXISTING_CPP" ]; then
    echo -e "${YELLOW}⚠ Found existing C++ service on port $CPP_PORT (PID: $EXISTING_CPP)${NC}"
    kill -9 $EXISTING_CPP 2>/dev/null || true
    sleep 1
    echo -e "${GREEN}✓ Killed existing C++ service${NC}"
fi

if [ ! -z "$EXISTING_PY" ]; then
    echo -e "${YELLOW}⚠ Found existing Python service on port $PYTHON_PORT (PID: $EXISTING_PY)${NC}"
    kill -9 $EXISTING_PY 2>/dev/null || true
    sleep 1
    echo -e "${GREEN}✓ Killed existing Python service${NC}"
fi

# ========================================================================
# Start C++ HTTP Server
# ========================================================================
echo -e "\n${BLUE}➤ Step 1/3: Starting C++ HTTP Server${NC}"
echo -e "${BLUE}────────────────────────────────────────────────────────────${NC}"

if [ ! -f "$BUILD_DIR/forensic_analyzer" ]; then
    echo -e "${RED}✗ Error: C++ binary not found at:${NC}"
    echo -e "  ${BOLD}$BUILD_DIR/forensic_analyzer${NC}"
    echo -e "\n${YELLOW}Please build the project first:${NC}"
    echo -e "  ${CYAN}cd $BUILD_DIR && cmake .. && cmake --build . -j\$(nproc)${NC}"
    exit 1
fi

cd "$BUILD_DIR"
./forensic_analyzer --http-server $CPP_PORT > "$LOG_DIR/cpp_server.log" 2>&1 &
CPP_PID=$!
echo -e "${GREEN}✓ C++ server started${NC}    PID: ${BOLD}$CPP_PID${NC} (Logging to $LOG_DIR/cpp_server.log)"

# Wait for C++ server to be ready
if ! check_service "http://localhost:$CPP_PORT/api/system/health" "C++ server" 10; then
    echo -e "${RED}✗ C++ server failed to start. Check logs at $LOG_DIR/cpp_server.log${NC}"
    exit 1
fi

# ========================================================================
# Start Python FastAPI Service
# ========================================================================
echo -e "\n${BLUE}➤ Step 2/3: Starting Python FastAPI Service${NC}"
echo -e "${BLUE}────────────────────────────────────────────────────────────${NC}"

cd "$PROJECT_ROOT/python_service"

# Check for virtual environment
VENV_DIR="$PROJECT_ROOT/python_service/.venv"
PYTHON_EXEC="$VENV_DIR/bin/python"

if [ ! -f "$PYTHON_EXEC" ]; then
    echo -e "${RED}✗ Error: Python virtual environment not found${NC}"
    echo -e "  Expected at: ${BOLD}$PYTHON_EXEC${NC}"
    echo -e "\n${YELLOW}Create virtual environment:${NC}"
    echo -e "  ${CYAN}cd python_service && python3 -m venv .venv${NC}"
    echo -e "  ${CYAN}.venv/bin/pip install -r httpserver/requirements.txt${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Virtual environment found${NC}    ${CYAN}$VENV_DIR${NC}"

# Install/update dependencies if needed
if [ "$FORCE_INSTALL" = "true" ] || [ ! -f "$VENV_DIR/.deps_installed" ]; then
    echo -ne "${YELLOW}Installing dependencies...${NC}"
    $PYTHON_EXEC -m pip install -q -r httpserver/requirements.txt && \
        touch "$VENV_DIR/.deps_installed"
    echo -e " ${GREEN}✓ Done${NC}"
fi

# Start Python service with virtual environment
# Run as module directly to avoid RuntimeWarning
cd "$PROJECT_ROOT/python_service"
PYTHONPATH="$PROJECT_ROOT/python_service:$PYTHONPATH" \
    $PYTHON_EXEC -m httpserver.main > "$LOG_DIR/python_service.log" 2>&1 &
PYTHON_PID=$!
echo -e "${GREEN}✓ Python service started${NC}  PID: ${BOLD}$PYTHON_PID${NC} (Logging to $LOG_DIR/python_service.log)"

# Wait for Python service to be ready
if ! check_service "http://localhost:$PYTHON_PORT/health" "Python service" 30; then
    echo -e "${YELLOW}⚠ Python service health check failed. Check logs at $LOG_DIR/python_service.log${NC}"
fi

# ========================================================================
# Web Frontend Status
# ========================================================================
echo -e "\n${BLUE}➤ Step 3/3: Web Frontend${NC}"
echo -e "${BLUE}────────────────────────────────────────────────────────────${NC}"

WEB_DIST="$BUILD_DIR/web/dist/index.html"
if [ -f "$WEB_DIST" ]; then
    echo -e "${GREEN}✓ Web frontend built${NC}      ${CYAN}Served by C++ server${NC}"
else
    echo -e "${YELLOW}⚠ Web frontend not found${NC}"
    echo -e "  Expected at: ${BOLD}$WEB_DIST${NC}"
    echo -e "  ${YELLOW}To build:${NC} ${CYAN}cd web && npm run build${NC}"
    echo -e "  ${YELLOW}Or:${NC} ${CYAN}cmake --build build --target web_frontend${NC}"
fi

# ========================================================================
# Service Summary
# ========================================================================
echo -e "\n${GREEN}${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║              ALL SERVICES STARTED SUCCESSFULLY              ║${NC}"
echo -e "${GREEN}${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"

echo -e "\n${BOLD}📍 Service Endpoints:${NC}\n"

echo -e "  ${CYAN}1. C++ HTTP Server${NC}   ${GREEN}●${NC}  ${BLUE}http://localhost:$CPP_PORT${NC}"
echo -e "     ${CYAN}→ Web Frontend${NC}    ${GREEN}●${NC}  ${BLUE}http://localhost:$CPP_PORT/${NC}"
echo -e "     ${CYAN}→ API Documentation${NC} ${GREEN}●${NC}  ${BLUE}http://localhost:$CPP_PORT/api/docs${NC}"
echo -e "     ${CYAN}→ System Health${NC}    ${GREEN}●${NC}  ${BLUE}http://localhost:$CPP_PORT/api/system/health${NC}"

echo -e "\n  ${CYAN}2. Python FastAPI${NC}     ${GREEN}●${NC}  ${BLUE}http://localhost:$PYTHON_PORT${NC}"
echo -e "     ${CYAN}→ API Docs (Swagger)${NC} ${GREEN}●${NC}  ${BLUE}http://localhost:$PYTHON_PORT/docs${NC}"
echo -e "     ${CYAN}→ API Docs (ReDoc)${NC}   ${GREEN}●${NC}  ${BLUE}http://localhost:$PYTHON_PORT/redoc${NC}"
echo -e "     ${CYAN}→ Health Check${NC}      ${GREEN}●${NC}  ${BLUE}http://localhost:$PYTHON_PORT/health${NC}"

echo -e "\n${BOLD}🔧 Running Processes:${NC}"
echo -e "     C++ Server:    ${GREEN}PID $CPP_PID${NC}"
echo -e "     Python Service: ${GREEN}PID $PYTHON_PID${NC}"

echo -e "\n${YELLOW}${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}${BOLD}  Press ${RED}Ctrl+C${YELLOW} to stop all services${NC}"
echo -e "${YELLOW}${BOLD}════════════════════════════════════════════════════════════${NC}\n"

# Keep script running
wait
