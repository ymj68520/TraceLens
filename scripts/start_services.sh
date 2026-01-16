#!/bin/bash
# Start all ForensicsProject HTTP services
# This script starts both the C++ and Python HTTP servers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting ForensicsProject HTTP Services${NC}"
echo "=========================================="

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${GREEN}Loading environment from .env${NC}"
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

# Default ports
CPP_PORT=${HTTP_SERVER_PORT:-8080}
PYTHON_PORT=${PYTHON_HTTP_PORT:-8090}

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    if [ ! -z "$CPP_PID" ]; then
        kill $CPP_PID 2>/dev/null || true
    fi
    if [ ! -z "$PYTHON_PID" ]; then
        kill $PYTHON_PID 2>/dev/null || true
    fi
    echo -e "${GREEN}Services stopped${NC}"
}

trap cleanup EXIT

# Start C++ HTTP server
echo -e "\n${BLUE}Starting C++ HTTP server on port $CPP_PORT...${NC}"
if [ -f "$PROJECT_ROOT/build/forensic_analyzer" ]; then
    cd "$PROJECT_ROOT/build"
    ./forensic_analyzer --http-server $CPP_PORT &
    CPP_PID=$!
    echo -e "${GREEN}C++ server started (PID: $CPP_PID)${NC}"
else
    echo -e "${YELLOW}Warning: C++ binary not found at $PROJECT_ROOT/build/forensic_analyzer${NC}"
    echo -e "${YELLOW}Run 'cmake --build build' to build the C++ server${NC}"
fi

# Wait for C++ server to start
sleep 2

# Start Python HTTP server
echo -e "\n${BLUE}Starting Python HTTP server on port $PYTHON_PORT...${NC}"
cd "$PROJECT_ROOT/python_service"

# Check if virtual environment exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Install dependencies if needed
if [ -f "httpserver/requirements.txt" ]; then
    pip install -q -r httpserver/requirements.txt
fi

# Start Python server
python -m httpserver.main &
PYTHON_PID=$!
echo -e "${GREEN}Python server started (PID: $PYTHON_PID)${NC}"

echo -e "\n${GREEN}=========================================="
echo -e "All services started successfully!"
echo -e "==========================================${NC}"
echo -e "C++ HTTP Server:    ${BLUE}http://localhost:$CPP_PORT${NC}"
echo -e "  - API Docs:       ${BLUE}http://localhost:$CPP_PORT/api/docs${NC}"
echo -e "Python HTTP Server: ${BLUE}http://localhost:$PYTHON_PORT${NC}"
echo -e "  - API Docs:       ${BLUE}http://localhost:$PYTHON_PORT/docs${NC}"
echo -e "  - ReDoc:          ${BLUE}http://localhost:$PYTHON_PORT/redoc${NC}"
echo -e ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

# Wait for any process to exit
wait
