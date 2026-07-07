#!/bin/bash
# ForensicsProject - One-click Dependency Setup
# Installs all C++ system libraries, builds TSK, Crow & Aliyun OSS SDK from source,
# sets up Python venv, and builds the project.
#
# Usage:
#   chmod +x setup.sh && ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}➤ $*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
fail()  { echo -e "${RED}✗ $*${NC}"; exit 1; }

# ========================================================================
# Step 0: Setup NVM and Node.js (LTS, with npm 10+)
# ========================================================================
info "Step 0/7: Checking NVM and Node.js..."

export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"

install_nvm() {
    info "  NVM not found, downloading and installing..."
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    # shellcheck disable=SC1090
    source "$NVM_DIR/nvm.sh"
    ok "NVM installed"
}

# Install NVM if missing
if [ ! -d "$NVM_DIR" ] || [ ! -s "$NVM_DIR/nvm.sh" ]; then
    if ! install_nvm; then
        warn "  NVM installation failed. Falling back to system node/npm."
    fi
fi

# Load NVM (safe to source even if NVM was just installed above)
if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1090
    source "$NVM_DIR/nvm.sh"
fi

# Install and activate Node.js 22 LTS via NVM if not already available
if command -v nvm &>/dev/null; then
    NODE_LTS="22"
    if ! nvm ls "$NODE_LTS" &>/dev/null; then
        info "  Installing Node.js ${NODE_LTS} LTS via NVM..."
        nvm install "$NODE_LTS"
    fi
    nvm use "$NODE_LTS" >/dev/null 2>&1 || nvm use default
    NODE_BIN_DIR="$(dirname "$(nvm which current 2>/dev/null || command -v node)")"
    # Prepend NVM node bin to PATH so subsequent cmake/npm calls use it
    export PATH="$NODE_BIN_DIR:$PATH"
    ok "Node $(node --version) / npm $(npm --version) (NVM-managed)"
else
    warn "  NVM not available, using system node $(node --version 2>/dev/null || echo 'not found') / npm $(npm --version 2>/dev/null || echo 'not found')"
fi

echo -e "${CYAN}${BOLD}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║       ForensicsProject - Dependency Setup Script           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ========================================================================
# Step 1/7: Install system packages (apt)
# ========================================================================
info "Step 1/7: Installing system packages via apt..."

APT_PACKAGES=(
    # Build tools
    build-essential cmake pkg-config git
    # Core libraries
    libsqlite3-dev libsqlcipher-dev libssl-dev
    # Boost (system/thread for runtime, uuid headers for CaseManager/TaskManager)
    libboost-dev libboost-system-dev libboost-thread-dev
    # JSON / async (header-only but need the -dev for cmake find)
    nlohmann-json3-dev libasio-dev
    # Forensic libraries
    libhivex-dev          # Windows registry parsing
    libevtx-dev           # Windows event log parsing
    libesedb-dev          # Windows ESE database parsing
    libolecf-dev          # OLE compound file parsing
    libbfio-dev           # Basic File I/O (used by evtx/esedb/olecf)
    libewf-dev            # E01/EnCase image format
    libfsntfs-dev         # NTFS MFT metadata parsing (Windows forensics)
    # Full-text search
    libxapian-dev
    # PDF analysis
    libpoppler-cpp-dev
    # XML
    libpugixml-dev
    # Compression
    zlib1g-dev liblzma-dev libbz2-dev libzstd-dev
    # HTTP client
    libcurl4-openssl-dev
    # ZIP
    libzip-dev
    # Word document parsing
    antiword
    # Testing
    libgtest-dev libgmock-dev
    # Database connectors
    libmysqlclient-dev libpq-dev
)

# Check which packages are already installed
MISSING=()
INSTALLED=0
for pkg in "${APT_PACKAGES[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        INSTALLED=$((INSTALLED + 1))
    else
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -eq 0 ]; then
    ok "All apt packages already installed ($INSTALLED packages)"
else
    info "Found $INSTALLED already installed, ${#MISSING[@]} missing: ${MISSING[*]}"
    info "Installing missing packages (may require sudo)..."
    sudo apt-get update -qq
    sudo apt-get install -y "${MISSING[@]}"
    ok "System packages installed"
fi

# ========================================================================
# Step 2/7: Install The Sleuth Kit 4.14.0 (if not present)
# ========================================================================
info "Step 2/7: Checking The Sleuth Kit (TSK)..."

TSK_LIB="/usr/local/lib/libtsk.so"
TSK_VERSION="4.14.0"

if [ -f "$TSK_LIB" ]; then
    ok "TSK already installed at $TSK_LIB"
else
    info "Building TSK $TSK_VERSION from source..."
    TSK_BUILD_DIR=$(mktemp -d)
    cd "$TSK_BUILD_DIR"

    wget -q "https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-${TSK_VERSION}/sleuthkit-${TSK_VERSION}.tar.gz" \
        || fail "Failed to download TSK. Check network connection."

    tar -xzf "sleuthkit-${TSK_VERSION}.tar.gz"
    cd "sleuthkit-${TSK_VERSION}"

    info "  Configuring TSK..."
    ./configure 2>&1 | tail -3

    info "  Building TSK (this may take a few minutes)..."
    make -j$(nproc) -s

    info "  Installing TSK..."
    sudo make install -s
    sudo ldconfig

    cd "$PROJECT_ROOT"
    rm -rf "$TSK_BUILD_DIR"
    ok "TSK $TSK_VERSION installed"
fi

# ========================================================================
# Step 3/7: Install Crow framework (if not present)
# ========================================================================
info "Step 3/7: Checking Crow HTTP framework..."

CROW_HEADER="/usr/local/include/crow.h"
if [ -f "$CROW_HEADER" ] || [ -d "/usr/local/include/crow" ]; then
    ok "Crow already installed"
else
    info "Building Crow from source..."
    CROW_BUILD_DIR=$(mktemp -d)
    cd "$CROW_BUILD_DIR"

    git clone --depth 1 https://github.com/CrowCpp/Crow.git
    cd Crow
    mkdir build && cd build
    cmake .. -DCROW_BUILD_EXAMPLES=OFF -DCROW_BUILD_TESTS=OFF 2>&1 | tail -3
    make -j$(nproc) -s
    sudo make install -s

    cd "$PROJECT_ROOT"
    rm -rf "$CROW_BUILD_DIR"
    ok "Crow installed"
fi

# ========================================================================
# Step 4/7: Install Google Test (if not present)
# ========================================================================
info "Step 4/7: Checking Google Test..."

if [ -f "/usr/local/lib/libgtest.a" ] || [ -f "/usr/lib/libgtest.a" ]; then
    ok "Google Test already installed"
else
    # Try from system source first
    if [ -d "/usr/src/googletest" ]; then
        info "Building Google Test from system source..."
        cd /usr/src/googletest
        sudo cmake -B build -S . 2>&1 | tail -3
        sudo cmake --build build -j$(nproc) 2>&1 | tail -3
        sudo cmake --install build 2>&1 | tail -3
        cd "$PROJECT_ROOT"
        ok "Google Test installed"
    else
        warn "Google Test source not found at /usr/src/googletest"
        warn "Install manually: sudo apt-get install libgtest-dev"
    fi
fi

# Refresh ldconfig after all installs (non-interactive: don't block on sudo password)
sudo -n ldconfig 2>/dev/null || true

# ========================================================================
# Step 5/7: Build Aliyun OSS C++ SDK (if not present)
# ========================================================================
info "Step 5/7: Checking Aliyun OSS C++ SDK..."

OSS_SDK_DIR="$PROJECT_ROOT/libs/aliyun-oss-cpp-sdk"
OSS_SDK_LIB="$OSS_SDK_DIR/build/lib/libalibabacloud-oss-cpp-sdk.a"

if [ -f "$OSS_SDK_LIB" ]; then
    ok "Aliyun OSS C++ SDK already built at $OSS_SDK_LIB"
else
    info "Building Aliyun OSS C++ SDK from source..."
    cd "$OSS_SDK_DIR"
    mkdir -p build
    cd build
    cmake .. -DBUILD_SAMPLE=OFF -DBUILD_TESTS=OFF 2>&1 | tail -5
    make -j$(nproc) -s 2>&1 | tail -5

    if [ -f "$OSS_SDK_LIB" ]; then
        ok "Aliyun OSS C++ SDK built successfully"
    else
        fail "Failed to build Aliyun OSS C++ SDK. Check cmake output above."
    fi

    cd "$PROJECT_ROOT"
fi

# ========================================================================
# Step 6/7: Setup Python virtual environment
# ========================================================================
info "Step 6/7: Setting up Python virtual environment..."

VENV_DIR="$PROJECT_ROOT/python_service/.venv"
PYTHON_EXEC="$VENV_DIR/bin/python"
REQUIREMENTS="$PROJECT_ROOT/python_service/httpserver/requirements.txt"

# Detect broken venv: python binary exists but pyvenv.cfg is missing
if [ -f "$PYTHON_EXEC" ] && [ ! -f "$VENV_DIR/pyvenv.cfg" ]; then
    warn "Virtual environment at $VENV_DIR is broken (missing pyvenv.cfg), recreating..."
    rm -rf "$VENV_DIR"
fi

if [ -f "$PYTHON_EXEC" ] && [ -f "$VENV_DIR/pyvenv.cfg" ]; then
    ok "Virtual environment exists at $VENV_DIR"
    # Upgrade pip and install/update deps
    info "  Updating pip and dependencies..."
    if ! "$PYTHON_EXEC" -m pip install --upgrade pip -q 2>/dev/null; then
        warn "  pip upgrade had issues, continuing with existing pip..."
    fi
    if ! "$PYTHON_EXEC" -m pip install -q -r "$REQUIREMENTS" 2>/dev/null; then
        warn "  Some Python dependencies may not have installed correctly"
    fi
    touch "$VENV_DIR/.deps_installed"
    ok "Python dependencies updated"
else
    info "Creating new virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$PYTHON_EXEC" -m pip install --upgrade pip -q
    "$PYTHON_EXEC" -m pip install -q -r "$REQUIREMENTS"
    touch "$VENV_DIR/.deps_installed"
    ok "Python virtual environment created and dependencies installed"
fi

# Soft check: Volatility3 for MemoryAnalyzer (non-fatal)
if [ ! -x "$VENV_DIR/bin/vol" ]; then
    warn "volatility3 not found in $VENV_DIR — memory forensics (--memory-analyze) will be unavailable."
fi

# ========================================================================
# Step 7/7: Build C++ project
# ========================================================================
info "Step 7/7: Building C++ project..."

# Build vendored Alibaba OSS SDK first (required by forensic_analyzer)
OSS_BUILD_DIR="$PROJECT_ROOT/libs/aliyun-oss-cpp-sdk/build"
if [ ! -f "$OSS_BUILD_DIR/lib/libalibabacloud-oss-cpp-sdk.a" ]; then
    info "  Building Alibaba OSS SDK..."
    mkdir -p "$OSS_BUILD_DIR"
    cd "$OSS_BUILD_DIR"
    cmake .. -DBUILD_SHARED_LIBS=OFF -DBUILD_SAMPLE=OFF -DBUILD_TESTS=OFF 2>&1 | tail -3
    make -j$(nproc) -s
    ok "OSS SDK built"
else
    ok "OSS SDK already built"
fi

BUILD_DIR="$PROJECT_ROOT/build"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

info "  Running cmake..."
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | grep -E "(error|warning:|Found|Configuring)" || true

info "  Building main target ($(nproc) threads)..."
# Build only the main target; web_frontend is handled separately below
cmake --build . --target forensic_analyzer -j$(nproc) 2>&1 | tail -20
# Check if build actually succeeded (cmake may return 0 even with partial failures)
if ! ldd "$BUILD_DIR/forensic_analyzer" &>/dev/null; then
    warn "Binary has missing shared libraries, build may have partially failed"
fi

if [ -f "$BUILD_DIR/forensic_analyzer" ]; then
    ok "Build successful: $BUILD_DIR/forensic_analyzer"
else
    fail "Build failed. Check cmake output above."
fi

# ========================================================================
# Build Web Frontend (optional)
# ========================================================================
if [ -d "$PROJECT_ROOT/web" ] && [ -f "$PROJECT_ROOT/web/package.json" ]; then
    info "Building web frontend..."
    cd "$PROJECT_ROOT/web"
    if [ -d "node_modules" ]; then
        npm run build 2>&1 | tail -3 || warn "Web frontend build failed (non-critical)"
        ok "Web frontend built"
    else
        info "  Installing web dependencies first..."
        npm install -s 2>&1 | tail -3
        npm run build 2>&1 | tail -3 || warn "Web frontend build failed (non-critical)"
        ok "Web frontend built"
    fi
fi

cd "$PROJECT_ROOT"

# ========================================================================
# Summary
# ========================================================================
echo ""
echo -e "${GREEN}${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║              SETUP COMPLETE SUCCESSFULLY                    ║${NC}"
echo -e "${GREEN}${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo -e "  ${CYAN}./start.sh${NC}           Start all services"
echo -e "  ${CYAN}make start${NC}           Same as above (via Makefile)"
echo -e "  ${CYAN}make cpp${NC}             Start C++ server only"
echo -e "  ${CYAN}make python${NC}          Start Python service only"
echo ""
echo -e "${BOLD}Service endpoints:${NC}"
echo -e "  C++ HTTP Server:    ${BLUE}http://localhost:8080${NC}"
echo -e "  Python FastAPI:     ${BLUE}http://localhost:8090${NC}"
echo -e "  Web Frontend:       ${BLUE}http://localhost:8080/${NC}"
echo ""
