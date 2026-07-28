#!/bin/bash
# ForensicsProject - One-click Dependency Setup
# Installs all C++ system libraries, Java 21, Neo4j, Redis, TSK, Crow and the
# Aliyun OSS SDK, sets up the Python venv, and builds the project.
#
# Usage:
#   chmod +x setup.sh && ./setup.sh

set -eo pipefail

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
info "Step 0/8: Checking NVM and Node.js..."

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
# Privilege helpers
# ========================================================================
# Prefer root/passwordless sudo for unattended runs.  Interactive sudo is
# requested lazily, only when a missing dependency actually needs it.
CAN_ELEVATE=false
SUDO_CMD=()

init_privileges() {
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        CAN_ELEVATE=true
        return
    fi

    if command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
        SUDO_CMD=(sudo -n)
        CAN_ELEVATE=true
    fi
}

acquire_elevation() {
    if [ "$CAN_ELEVATE" = true ]; then
        return 0
    fi
    if ! command -v sudo &>/dev/null || [ ! -t 0 ]; then
        return 1
    fi

    if [ -t 0 ]; then
        info "Administrator privileges are required for system dependencies."
        if sudo -v; then
            SUDO_CMD=(sudo)
            CAN_ELEVATE=true
            return 0
        else
            warn "sudo authentication failed"
        fi
    fi
    return 1
}

run_root() {
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        "$@"
    else
        "${SUDO_CMD[@]}" "$@"
    fi
}

run_as_user() {
    local target_user="$1"
    shift
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        runuser -u "$target_user" -- "$@"
    else
        "${SUDO_CMD[@]}" -u "$target_user" -- "$@"
    fi
}

require_elevation() {
    local purpose="$1"
    if [ "$CAN_ELEVATE" != true ] && ! acquire_elevation; then
        fail "$purpose requires root or sudo access. Run setup.sh from an interactive terminal or configure passwordless sudo."
    fi
}

read_dotenv_value() {
    local key="$1"
    local env_file="$PROJECT_ROOT/.env"
    local value=""
    if [ -f "$env_file" ]; then
        value="$(grep -m1 -E "^[[:space:]]*${key}=" "$env_file" 2>/dev/null | cut -d= -f2- || true)"
        value="${value%$'\r'}"
        if [[ "$value" == \"*\" && "$value" == *\" ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
            value="${value:1:${#value}-2}"
        fi
    fi
    printf '%s' "$value"
}

init_privileges

# ========================================================================
# Step 1/8: Install system packages (apt)
# ========================================================================
info "Step 1/8: Installing system packages via apt..."

APT_PACKAGES=(
    # Build tools
    build-essential cmake pkg-config git wget gnupg software-properties-common
    ca-certificates
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
    # Media analysis (VideoExtractor/AudioExtractor call ffmpeg/ffprobe via subprocess)
    ffmpeg
    # Testing
    libgtest-dev libgmock-dev
    # Database connectors
    libmysqlclient-dev libpq-dev
    # Redis (job storage for IngestionJobManager)
    redis-server redis-tools
)

# These packages enable optional features, but the project can still build and
# run without them.  Keeping the list explicit lets setup.sh remain useful in
# non-root CI/dev environments where sudo cannot prompt for a password.
OPTIONAL_APT_PACKAGES=(
    libsqlcipher-dev
    ffmpeg
    redis-server
    redis-tools
)

is_optional_apt_package() {
    local candidate="$1"
    local optional
    for optional in "${OPTIONAL_APT_PACKAGES[@]}"; do
        if [ "$candidate" = "$optional" ]; then
            return 0
        fi
    done
    return 1
}

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
    if [ "$CAN_ELEVATE" != true ]; then
        acquire_elevation || true
    fi
    if [ "$CAN_ELEVATE" = true ]; then
        info "Installing missing packages..."
        run_root apt-get update -qq
        run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING[@]}"
        ok "System packages installed"
    else
        MISSING_REQUIRED=()
        MISSING_OPTIONAL=()
        for pkg in "${MISSING[@]}"; do
            if is_optional_apt_package "$pkg"; then
                MISSING_OPTIONAL+=("$pkg")
            else
                MISSING_REQUIRED+=("$pkg")
            fi
        done

        if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
            fail "Required system packages are missing and sudo is unavailable: ${MISSING_REQUIRED[*]}. Install them with: sudo apt-get install ${MISSING_REQUIRED[*]}"
        fi

        warn "sudo is unavailable; skipping optional packages: ${MISSING_OPTIONAL[*]}"
        warn "Optional features affected: SQLCipher database support, media extraction, and Redis-backed job persistence"
    fi
fi

# Ensure Redis is enabled and running (job storage for IngestionJobManager)
info "Ensuring Redis service is running..."
if command -v systemctl &>/dev/null && [ "$CAN_ELEVATE" = true ]; then
    run_root systemctl enable redis-server >/dev/null 2>&1 || true
    run_root systemctl start redis-server 2>/dev/null || true
fi
# Fallback: start a local instance directly if systemd is unavailable
if command -v redis-cli &>/dev/null && ! redis-cli ping >/dev/null 2>&1; then
    warn "redis-cli ping failed; starting redis-server directly..."
    redis-server --daemonize yes
fi
if command -v redis-cli &>/dev/null && redis-cli ping >/dev/null 2>&1; then
    ok "Redis is running ($(redis-cli ping))"
else
    warn "Redis is not responding on localhost:6379 — IngestionJobManager will fall back to in-memory storage"
fi

# ========================================================================
# Step 2/8: Install Java 21 and Neo4j (if not present)
# ========================================================================
info "Step 2/8: Checking Java 21 and Neo4j..."

JAVA_PACKAGES=(openjdk-21-jre-headless openjdk-21-jdk)
MISSING_JAVA=()
for pkg in "${JAVA_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_JAVA+=("$pkg")
    fi
done

if [ ${#MISSING_JAVA[@]} -gt 0 ]; then
    if [ "$CAN_ELEVATE" != true ]; then
        acquire_elevation || true
    fi
    if [ "$CAN_ELEVATE" = true ]; then
        info "Installing Java 21: ${MISSING_JAVA[*]}"
        run_root apt-get update -qq
        run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_JAVA[@]}"
        ok "Java 21 installed"
    else
        warn "Java 21 is missing and sudo is unavailable; Neo4j cannot be installed"
    fi
fi

NEO4J_INSTALLED_NOW=false
NEO4J_KEYRING="/etc/apt/keyrings/neotechnology.gpg"
NEO4J_REPOSITORY_FILE="/etc/apt/sources.list.d/neo4j.list"
NEO4J_REPOSITORY="deb [signed-by=${NEO4J_KEYRING}] https://debian.neo4j.com stable latest"

if ! dpkg -s neo4j &>/dev/null; then
    if [ "$CAN_ELEVATE" != true ]; then
        acquire_elevation || true
    fi
    if [ "$CAN_ELEVATE" != true ]; then
        warn "Neo4j is not installed and sudo is unavailable — Graphiti knowledge graph support will be disabled"
    elif [ ${#MISSING_JAVA[@]} -gt 0 ] && ! command -v java &>/dev/null; then
        warn "Java installation failed or java is unavailable; skipping Neo4j installation"
    else
        info "Adding the official Neo4j apt repository..."
        run_root add-apt-repository -y universe >/dev/null
        run_root mkdir -p /etc/apt/keyrings

        if [ ! -s "$NEO4J_KEYRING" ]; then
            NEO4J_KEY_TMP_DIR="$(mktemp -d)"
            wget -qO "$NEO4J_KEY_TMP_DIR/neotechnology.gpg.key" \
                https://debian.neo4j.com/neotechnology.gpg.key \
                || fail "Failed to download the Neo4j repository signing key"
            gpg --batch --yes --dearmor \
                --output "$NEO4J_KEY_TMP_DIR/neotechnology.gpg" \
                "$NEO4J_KEY_TMP_DIR/neotechnology.gpg.key"
            run_root install -m 0644 \
                "$NEO4J_KEY_TMP_DIR/neotechnology.gpg" "$NEO4J_KEYRING"
            rm -rf "$NEO4J_KEY_TMP_DIR"
        else
            run_root chmod a+r "$NEO4J_KEYRING"
        fi

        if [ ! -f "$NEO4J_REPOSITORY_FILE" ] \
            || ! grep -Fqx "$NEO4J_REPOSITORY" "$NEO4J_REPOSITORY_FILE"; then
            NEO4J_REPO_TMP="$(mktemp)"
            printf '%s\n' "$NEO4J_REPOSITORY" > "$NEO4J_REPO_TMP"
            run_root install -m 0644 "$NEO4J_REPO_TMP" "$NEO4J_REPOSITORY_FILE"
            rm -f "$NEO4J_REPO_TMP"
        fi

        run_root apt-get update -qq
        run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y neo4j
        NEO4J_INSTALLED_NOW=true
        ok "Neo4j installed"
    fi
fi

if dpkg -s neo4j &>/dev/null; then
    if [ "$NEO4J_INSTALLED_NOW" = true ]; then
        NEO4J_INITIAL_PASSWORD="${NEO4J_PASSWORD:-$(read_dotenv_value NEO4J_PASSWORD)}"
        if command -v systemctl &>/dev/null; then
            run_root systemctl stop neo4j >/dev/null 2>&1 || true
        fi
        if [ -n "$NEO4J_INITIAL_PASSWORD" ]; then
            info "Setting the initial Neo4j password from NEO4J_PASSWORD..."
            run_as_user neo4j neo4j-admin dbms set-initial-password "$NEO4J_INITIAL_PASSWORD"
            ok "Neo4j initial password configured"
        else
            warn "NEO4J_PASSWORD is not set in the environment or .env; set the initial password manually before using Graphiti"
        fi
    fi

    if command -v systemctl &>/dev/null; then
        if [ "$CAN_ELEVATE" = true ]; then
            if ! run_root systemctl enable --now neo4j >/dev/null; then
                warn "Could not enable/start Neo4j through systemd"
            fi
        fi
        if systemctl is-active --quiet neo4j; then
            JAVA_VERSION="$(java -version 2>&1 | sed -n '1p' || echo 'Java version unavailable')"
            NEO4J_VERSION="$(neo4j --version 2>/dev/null | sed -n '1p' || echo 'version unavailable')"
            ok "Neo4j ${NEO4J_VERSION} is running with ${JAVA_VERSION}"
        else
            warn "Neo4j is installed but not running. Start it with: sudo systemctl enable --now neo4j"
        fi
    else
        warn "systemctl is unavailable; start Neo4j manually before using Graphiti"
    fi
fi

# ========================================================================
# Step 3/8: Install The Sleuth Kit 4.14.0 (if not present)
# ========================================================================
info "Step 3/8: Checking The Sleuth Kit (TSK)..."

TSK_LIB="/usr/local/lib/libtsk.so"
TSK_VERSION="4.14.0"

if [ -f "$TSK_LIB" ]; then
    ok "TSK already installed at $TSK_LIB"
else
    require_elevation "Installing TSK into /usr/local"
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
    run_root make install -s
    run_root ldconfig

    cd "$PROJECT_ROOT"
    rm -rf "$TSK_BUILD_DIR"
    ok "TSK $TSK_VERSION installed"
fi

# ========================================================================
# Step 4/8: Install Crow framework (if not present)
# ========================================================================
info "Step 4/8: Checking Crow HTTP framework..."

CROW_HEADER="/usr/local/include/crow.h"
if [ -f "$CROW_HEADER" ] || [ -d "/usr/local/include/crow" ]; then
    ok "Crow already installed"
else
    require_elevation "Installing Crow into /usr/local"
    info "Building Crow from source..."
    CROW_BUILD_DIR=$(mktemp -d)
    cd "$CROW_BUILD_DIR"

    git clone --depth 1 https://github.com/CrowCpp/Crow.git
    cd Crow
    mkdir build && cd build
    cmake .. -DCROW_BUILD_EXAMPLES=OFF -DCROW_BUILD_TESTS=OFF 2>&1 | tail -3
    make -j$(nproc) -s
    run_root make install -s

    cd "$PROJECT_ROOT"
    rm -rf "$CROW_BUILD_DIR"
    ok "Crow installed"
fi

# ========================================================================
# Step 5/8: Install Google Test (if not present)
# ========================================================================
info "Step 5/8: Checking Google Test..."

if pkg-config --exists gtest 2>/dev/null \
    || [ -f "/usr/local/lib/libgtest.a" ] \
    || [ -f "/usr/lib/libgtest.a" ] \
    || find /usr/lib -name libgtest.a -print -quit 2>/dev/null | grep -q .; then
    ok "Google Test already installed"
else
    # Try from system source first
    if [ -d "/usr/src/googletest" ]; then
        if [ "$CAN_ELEVATE" = true ]; then
            info "Building Google Test from system source..."
            cd /usr/src/googletest
            run_root cmake -B build -S . 2>&1 | tail -3
            run_root cmake --build build -j$(nproc) 2>&1 | tail -3
            run_root cmake --install build 2>&1 | tail -3
            cd "$PROJECT_ROOT"
            ok "Google Test installed"
        else
            warn "Google Test requires sudo to build from /usr/src/googletest"
        fi
    else
        warn "Google Test source not found at /usr/src/googletest"
        warn "Install manually: sudo apt-get install libgtest-dev"
    fi
fi

# Refresh ldconfig after all installs without triggering another password prompt.
if [ "$CAN_ELEVATE" = true ]; then
    run_root ldconfig 2>/dev/null || true
fi

# ========================================================================
# Step 6/8: Build Aliyun OSS C++ SDK (if not present)
# ========================================================================
info "Step 6/8: Checking Aliyun OSS C++ SDK..."

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
# Step 7/8: Setup Python virtual environment
# ========================================================================
info "Step 7/8: Setting up Python virtual environment..."

VENV_DIR="$PROJECT_ROOT/python_service/.venv"
PYTHON_EXEC="$VENV_DIR/bin/python"
# Both requirements files are installed so the single shared venv covers every
# service and the test suite:
#   - httpserver/requirements.txt : legacy httpserver (:8090) + forensic libs
#   - requirements.txt            : distributed C/S server (:8091) — adds
#                                   sqlalchemy/email-validator/passlib/etc.
# Installing only the httpserver file left the venv without the server deps,
# which broke python_service/server and the tests/unit/ DB/schema tests.
REQUIREMENTS_HTTPSERVER="$PROJECT_ROOT/python_service/httpserver/requirements.txt"
REQUIREMENTS_SERVER="$PROJECT_ROOT/python_service/requirements.txt"

ensure_venv_pip() {
    if ! "$PYTHON_EXEC" -m pip --version &>/dev/null; then
        info "  pip is missing from the virtual environment; bootstrapping with ensurepip..."
        "$PYTHON_EXEC" -m ensurepip --upgrade \
            || fail "Failed to bootstrap pip in $VENV_DIR"
    fi
}

# Detect broken venv: python binary exists but pyvenv.cfg is missing
if [ -f "$PYTHON_EXEC" ] && [ ! -f "$VENV_DIR/pyvenv.cfg" ]; then
    warn "Virtual environment at $VENV_DIR is broken (missing pyvenv.cfg), recreating..."
    rm -rf "$VENV_DIR"
fi

if [ -f "$PYTHON_EXEC" ] && [ -f "$VENV_DIR/pyvenv.cfg" ]; then
    ok "Virtual environment exists at $VENV_DIR"
    ensure_venv_pip
    # Upgrade pip and install/update deps
    info "  Updating pip and dependencies..."
    if ! "$PYTHON_EXEC" -m pip install --upgrade pip -q 2>/dev/null; then
        warn "  pip upgrade had issues, continuing with existing pip..."
    fi
    if ! "$PYTHON_EXEC" -m pip install -q --retries 3 -r "$REQUIREMENTS_HTTPSERVER" -r "$REQUIREMENTS_SERVER" 2>/dev/null; then
        rm -f "$VENV_DIR/.deps_installed"
        fail "Failed to install Python dependencies. Re-run without -q for details: $PYTHON_EXEC -m pip install -r $REQUIREMENTS_HTTPSERVER -r $REQUIREMENTS_SERVER"
    fi
    touch "$VENV_DIR/.deps_installed"
    ok "Python dependencies updated"
else
    info "Creating new virtual environment..."
    python3 -m venv "$VENV_DIR"
    ensure_venv_pip
    "$PYTHON_EXEC" -m pip install --upgrade pip -q
    "$PYTHON_EXEC" -m pip install -q --retries 3 -r "$REQUIREMENTS_HTTPSERVER" -r "$REQUIREMENTS_SERVER"
    touch "$VENV_DIR/.deps_installed"
    ok "Python virtual environment created and dependencies installed"
fi

# Soft check: Volatility3 for MemoryAnalyzer (non-fatal)
if [ ! -x "$VENV_DIR/bin/vol" ]; then
    warn "volatility3 not found in $VENV_DIR — memory forensics (--memory-analyze) will be unavailable."
else
    # Install the project-vendored BitLocker FVEK scanner into this venv only.
    # The source remains under resources/ so recreating the venv is reproducible.
    VOLATILITY_PLUGIN_SRC="$PROJECT_ROOT/resources/volatility3-plugins/windows/bitlocker_fvek_scan.py"
    VOLATILITY_PLUGIN_DIR="$($PYTHON_EXEC -c 'from pathlib import Path; import volatility3; print(Path(volatility3.__file__).resolve().parent / "plugins" / "windows")' 2>/dev/null || true)"
    if [ -f "$VOLATILITY_PLUGIN_SRC" ] && [ -n "$VOLATILITY_PLUGIN_DIR" ] && [ -d "$VOLATILITY_PLUGIN_DIR" ]; then
        if install -m 0644 "$VOLATILITY_PLUGIN_SRC" "$VOLATILITY_PLUGIN_DIR/bitlocker_fvek_scan.py"; then
            ok "Volatility3 BitLocker FVEK scanner installed in project venv"
        else
            warn "Could not install BitLocker FVEK scanner into $VOLATILITY_PLUGIN_DIR"
        fi
    else
        warn "BitLocker FVEK scanner source or Volatility3 plugin directory not found"
    fi

    # vol3 needs a kernel-matching ISF to parse a LiME dump. Symbols are NOT
    # shipped (kernel-specific, fetched on demand). Just point users at the
    # fetch script; the analyzer also prints this hint on symbol-mismatch.
    info "Volatility3 installed. To analyze a memory dump, fetch its kernel's ISF:"
    info "    ./scripts/build-vol3-isf.sh <kernel-version>   # e.g. 6.8.0-110-generic"
fi

# ========================================================================
# Step 8/8: Build C++ project
# ========================================================================
info "Step 8/8: Building C++ project..."

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
CMAKE_CONFIG_LOG="$BUILD_DIR/cmake-configure.log"
if ! cmake .. -DCMAKE_BUILD_TYPE=Release >"$CMAKE_CONFIG_LOG" 2>&1; then
    tail -100 "$CMAKE_CONFIG_LOG"
    fail "CMake configuration failed. Full log: $CMAKE_CONFIG_LOG"
fi
grep -E "(error|warning:|Found|Configuring|SQLCipher)" "$CMAKE_CONFIG_LOG" || true

info "  Building main target ($(nproc) threads)..."
# Build only the main target; web_frontend is handled separately below
CPP_BUILD_LOG="$BUILD_DIR/forensic_analyzer-build.log"
if ! cmake --build . --target forensic_analyzer -j$(nproc) >"$CPP_BUILD_LOG" 2>&1; then
    tail -100 "$CPP_BUILD_LOG"
    fail "C++ build failed. Full log: $CPP_BUILD_LOG"
fi
tail -20 "$CPP_BUILD_LOG"

if [ -x "$BUILD_DIR/forensic_analyzer" ]; then
    if ldd "$BUILD_DIR/forensic_analyzer" 2>/dev/null | grep -q "not found"; then
        ldd "$BUILD_DIR/forensic_analyzer" | grep "not found" || true
        fail "Build completed but forensic_analyzer has missing shared libraries"
    fi
    ok "Build successful: $BUILD_DIR/forensic_analyzer"
else
    fail "Build completed without producing an executable forensic_analyzer"
fi

# ========================================================================
# Build Web Frontend (optional)
# ========================================================================
if [ -d "$PROJECT_ROOT/web" ] && [ -f "$PROJECT_ROOT/web/package.json" ]; then
    info "Building web frontend..."
    cd "$PROJECT_ROOT/web"
    if [ ! -d "node_modules" ]; then
        info "  Installing web dependencies first..."
        npm install -s 2>&1 | tail -3
    fi
    WEB_BUILD_LOG="$BUILD_DIR/web-frontend-build.log"
    if ! npm run build >"$WEB_BUILD_LOG" 2>&1; then
        tail -100 "$WEB_BUILD_LOG"
        fail "Web frontend build failed. Full log: $WEB_BUILD_LOG"
    fi
    tail -3 "$WEB_BUILD_LOG"
    ok "Web frontend built"
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
echo -e "  ${CYAN}./scripts/start_all_services.sh${NC}  Start all services"
echo -e "  ${CYAN}make start${NC}           Same as above (via Makefile)"
echo -e "  ${CYAN}make cpp${NC}             Start C++ server only"
echo -e "  ${CYAN}make python${NC}          Start Python service only"
echo ""
echo -e "${BOLD}Service endpoints:${NC}"
echo -e "  C++ HTTP Server:    ${BLUE}http://localhost:8080${NC}"
echo -e "  Python FastAPI:     ${BLUE}http://localhost:8090${NC}"
echo -e "  Web Frontend:       ${BLUE}http://localhost:8080/${NC}"
echo -e "  Neo4j Browser:      ${BLUE}http://localhost:7474${NC}"
echo ""
