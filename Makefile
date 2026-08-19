# ForensicsProject - Top-level Makefile
# This provides convenient shortcuts for common build and run operations
#
# Usage:
#   make build          - Build the entire project
#   make start          - Start all services
#   make cpp            - Start only C++ server
#   make python         - Start only Python service
#   make web            - Build and start web dev server
#   make clean          - Clean build artifacts
#   make rebuild        - Clean and rebuild everything

.PHONY: all build start start-all cpp python web web-dev web-frontend clean rebuild \
	help test test-cpp test-python test-python-focused test-python-investigation \
	test-python-fast test-python-full test-all setup setup-venv setup-web docs

# Default target
all: build

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m

# Project directories
BUILD_DIR := build
PROJECT_ROOT := $(shell pwd)

# ==============================================================================
# Build Targets
# ==============================================================================

build:
	@echo "$(BLUE)➤ Building ForensicsProject...$(NC)"
	@mkdir -p $(BUILD_DIR)
	@cd $(BUILD_DIR) && cmake .. -DCMAKE_BUILD_TYPE=Release
	@cd $(BUILD_DIR) && cmake --build . -j$$(nproc)
	@echo "$(GREEN)✓ Build complete$(NC)"
	@echo "$(BLUE)C++ Binary:$(NC) $(BUILD_DIR)/forensic_analyzer"
	@echo "$(BLUE)Web Output:$(NC) $(BUILD_DIR)/web/dist/"

web-frontend:
	@echo "$(BLUE)➤ Building web frontend...$(NC)"
	@cd web && npm run build
	@echo "$(GREEN)✓ Web frontend built$(NC)"

# ==============================================================================
# Service Targets
# ==============================================================================

start: start-all
	@echo "$(GREEN)✓ All services started$(NC)"

start-all:
	@echo "$(BLUE)➤ Starting all services...$(NC)"
	@./scripts/start_all_services.sh

cpp:
	@echo "$(BLUE)➤ Starting C++ HTTP server...$(NC)"
	@if [ -f "$(BUILD_DIR)/forensic_analyzer" ]; then \
		cd $(BUILD_DIR) && ./forensic_analyzer --http-server $${HTTP_SERVER_PORT:-8080}; \
	else \
		echo "$(YELLOW)⚠ C++ binary not found. Run 'make build' first.$(NC)"; \
		exit 1; \
	fi

python:
	@echo "$(BLUE)➤ Starting Python FastAPI service...$(NC)"
	@if [ -f "python_service/.venv/bin/python" ]; then \
		cd python_service && .venv/bin/python -m httpserver.main; \
	else \
		echo "$(YELLOW)⚠ Virtual environment not found. Creating...$(NC)"; \
		python3 -m venv python_service/.venv; \
		python_service/.venv/bin/pip install -r python_service/httpserver/requirements.txt; \
		cd python_service && .venv/bin/python -m httpserver.main; \
	fi

web: web-dev

web-dev:
	@echo "$(BLUE)➤ Starting web development server...$(NC)"
	@cd web && npm run dev

# ==============================================================================
# Maintenance Targets
# ==============================================================================

clean:
	@echo "$(BLUE)➤ Cleaning build artifacts...$(NC)"
	@rm -rf $(BUILD_DIR)
	@rm -rf web/dist
	@rm -rf web/node_modules/.vite
	@echo "$(GREEN)✓ Clean complete$(NC)"

rebuild: clean build
	@echo "$(GREEN)✓ Rebuild complete$(NC)"

# ==============================================================================
# Development Targets
# ==============================================================================

setup-venv:
	@echo "$(BLUE)➤ Setting up Python virtual environment...$(NC)"
	@python3 -m venv python_service/.venv
	@python_service/.venv/bin/pip install --upgrade pip
	@python_service/.venv/bin/pip install -r python_service/httpserver/requirements.txt -r python_service/requirements.txt
	@echo "$(GREEN)✓ Virtual environment ready$(NC)"

setup-web:
	@echo "$(BLUE)➤ Setting up web dependencies...$(NC)"
	@cd web && npm install
	@echo "$(GREEN)✓ Web dependencies ready$(NC)"

setup: setup-venv setup-web
	@echo "$(GREEN)✓ All dependencies installed$(NC)"

# ==============================================================================
# Testing Targets
# ==============================================================================

test:
	@echo "$(BLUE)➤ Running tests...$(NC)"
	@cd $(BUILD_DIR) && ctest --output-on-failure

test-cpp:
	@echo "$(BLUE)➤ Running C++ tests...$(NC)"
	@cd $(BUILD_DIR) && ctest --output-on-failure

test-python:
	@echo "$(BLUE)➤ Running all Python tests...$(NC)"
	@cd python_service && .venv/bin/python -m pytest tests/ -v

# Stable Python regression profiles. Each runner fixes its own cwd.
test-python-focused:
	@echo "$(BLUE)➤ Running focused Python tests...$(NC)"
	@python_service/.venv/bin/python python_service/scripts/test.py focused $(ARGS)

test-python-investigation:
	@echo "$(BLUE)➤ Running Investigation fast regression...$(NC)"
	@python_service/.venv/bin/python python_service/scripts/test.py investigation

test-python-fast:
	@echo "$(BLUE)➤ Running fast Python unit regression...$(NC)"
	@python_service/.venv/bin/python python_service/scripts/test.py fast

test-python-full:
	@echo "$(BLUE)➤ Running full Python unit regression...$(NC)"
	@python_service/.venv/bin/python python_service/scripts/test.py full

test-all: test-cpp test-python
	@echo "$(GREEN)✓ All tests complete$(NC)"

# ==============================================================================
# Utilities
# ==============================================================================

help:
	@echo "$(BLUE)ForensicsProject - Available Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Build Commands:$(NC)"
	@echo "  make build          - Build entire project (C++ + Web)"
	@echo "  make web-frontend   - Build only web frontend"
	@echo "  make clean          - Clean build artifacts"
	@echo "  make rebuild        - Clean and rebuild"
	@echo ""
	@echo "$(GREEN)Service Commands:$(NC)"
	@echo "  make start          - Start all services (C++ + Python + Web)"
	@echo "  make cpp            - Start only C++ HTTP server (port 8080)"
	@echo "  make python         - Start only Python service (port 8090)"
	@echo "  make web-dev        - Start web dev server (port 3000)"
	@echo ""
	@echo "$(GREEN)Setup Commands:$(NC)"
	@echo "  make setup          - Install all dependencies"
	@echo "  make setup-venv     - Setup Python virtual environment"
	@echo "  make setup-web      - Setup web dependencies"
	@echo ""
	@echo "$(GREEN)Test Commands:$(NC)"
	@echo "  make test           - Run C++ CTest suite"
	@echo "  make test-cpp       - Run C++ CTest suite"
	@echo "  make test-python    - Run all Python tests"
	@echo "  make test-python-focused ARGS=... - Run selected Python tests"
	@echo "  make test-python-investigation - Run Investigation fast regression"
	@echo "  make test-python-fast - Run fast Python unit regression"
	@echo "  make test-python-full - Run full Python unit regression"
	@echo ""
	@echo "$(GREEN)Quick Start:$(NC)"
	@echo "  1. make setup       - Install dependencies"
	@echo "  2. make build       - Build the project"
	@echo "  3. make start       - Start all services"
	@echo ""
	@echo "$(GREEN)Access Points:$(NC)"
	@echo "  Web Interface:      http://localhost:8080/"
	@echo "  C++ API:            http://localhost:8080/api/docs"
	@echo "  Python API:         http://localhost:8090/docs"

# ==============================================================================
# Documentation
# ==============================================================================

docs:
	@echo "$(BLUE)➤ Opening API documentation...$(NC)"
	@echo "$(GREEN)C++ API:$(NC) http://localhost:8080/api/docs"
	@echo "$(GREEN)Python API:$(NC) http://localhost:8090/docs"
	@if command -v xdg-open > /dev/null; then \
		xdg-open http://localhost:8080/api/docs 2>/dev/null || true; \
	fi
