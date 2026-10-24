#!/bin/bash
# TraceLens - One-click setup: dependencies + build + runtime configuration.
# When this script finishes, the system is ready to start:
#   ./scripts/start_all_services.sh      (or: make start, or: ./run.sh --no-build)
#
# What it does:
#   1. Bootstraps .env from .env.example (generated secrets) when missing
#   2. Installs system packages (apt): C++ libs, TSK deps, Redis, Neo4j, PostgreSQL
#   3. Installs Java 21 + Neo4j; ensures Redis/Neo4j/PostgreSQL are running and
#      provisions the DATABASE_URL role/database for the distributed C/S server
#   4. Builds The Sleuth Kit, Crow, and the vendored Aliyun OSS SDK
#   5. Creates the Python venv (both requirements files + large optional wheels)
#   6. Builds the C++ server and the web frontend (synced to build/web/dist,
#      from where the C++ server serves the SPA and proxies /python/*)
#   7. Downloads the local CPU models by default (checksum-pinned, tolerant of
#      network failure): Argos en_zh 1.9 EN→ZH translation (OPUS-MT via
#      CTranslate2) and SenseVoice int8 + silero VAD audio transcription
#
# Usage:
#   chmod +x setup.sh && ./setup.sh
#   ./setup.sh --start     # also start all services when setup completes
#
# Notes:
#   - Fresh clone on a host where the Git LFS fixture server is unreachable:
#     clone with GIT_LFS_SKIP_SMUDGE=1 (LFS objects are test data only, the
#     build and all services run without them).
#   - Without root, libarchive-dev may be substituted by a conda libarchive
#     (pkg-config + linker -L/-rpath) matching the CMake lookup.

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

# ── Command-line arguments ────────────────────────────────────────────────────
START_SERVICES=0
for arg in "$@"; do
    case "$arg" in
        --start) START_SERVICES=1 ;;
        -h|--help)
            sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "未知参数: $arg（用 --help 查看用法）"; exit 1 ;;
    esac
done

# CMake caches absolute source paths. Reusing a build directory after moving or
# copying the repository otherwise fails before CMake can regenerate it.
prepare_cmake_build_dir() {
    local build_dir="$1"
    local source_dir="$2"
    local cache_file="$build_dir/CMakeCache.txt"
    local cached_source=""

    mkdir -p "$build_dir"
    if [ -f "$cache_file" ]; then
        cached_source="$(sed -n 's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' "$cache_file" | head -1)"
        if [ -n "$cached_source" ] \
            && [ "$(realpath -m "$cached_source")" != "$(realpath -m "$source_dir")" ]; then
            warn "Removing stale CMake cache from $build_dir (old source: $cached_source)"
            rm -f "$cache_file"
            rm -rf "$build_dir/CMakeFiles"
        fi
    fi
}

# ------------------------------------------------------------------------
# Runtime configuration: .env
# The C++ ConfigManager, both Python services, and every start script read
# the root .env (gitignored). Bootstrap it from .env.example on a fresh
# clone so setup truly ends in a runnable system, with real secrets
# generated for the placeholders. An existing .env is never touched.
# ------------------------------------------------------------------------
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    echo "Using existing .env"
else
    if [ ! -f "$PROJECT_ROOT/.env.example" ]; then
        warn "Neither .env nor .env.example present — services will run on built-in defaults"
    else
        gen_hex() {
            openssl rand -hex "$1" 2>/dev/null \
                || od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'
        }
        cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
        GENERATED_SECRET="$(gen_hex 32)"
        GENERATED_NEO4J_PW="$(gen_hex 12)"
        GENERATED_PG_PW="$(gen_hex 12)"
        if [ -n "$GENERATED_SECRET" ]; then
            sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${GENERATED_SECRET}|" "$ENV_FILE"
        fi
        if [ -n "$GENERATED_NEO4J_PW" ]; then
            sed -i "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=${GENERATED_NEO4J_PW}|" "$ENV_FILE"
        fi
        if [ -n "$GENERATED_PG_PW" ]; then
            sed -i "s|^DATABASE_URL=postgresql://postgres:change-me@|DATABASE_URL=postgresql://postgres:${GENERATED_PG_PW}@|" "$ENV_FILE"
        fi
        ok ".env created from .env.example (JWT / Neo4j / PostgreSQL secrets generated)"
        warn "Review $ENV_FILE: the LLM endpoints default to a LAN LM Studio host (LLM_TEXT_BASE_URL / LLM_VISION_BASE_URL / GRAPHITI_LLM_BASE_URL) — point them at a reachable OpenAI-compatible server to enable AI features"
    fi
fi

# Optional download proxy for flaky networks. Set PIP_PROXY in the environment
# or .env (e.g. PIP_PROXY=http://192.168.31.226:7897); it is exported as
# HTTP_PROXY/HTTPS_PROXY so pip/git/curl route through it.
if [ -z "${PIP_PROXY:-}" ] && [ -f "$PROJECT_ROOT/.env" ]; then
    PIP_PROXY="$(sed -nE 's/^[[:space:]]*PIP_PROXY=//p' "$PROJECT_ROOT/.env" | head -1)"
    PIP_PROXY="${PIP_PROXY%$'\r'}"
    PIP_PROXY="${PIP_PROXY%\"}"; PIP_PROXY="${PIP_PROXY#\"}"
    PIP_PROXY="${PIP_PROXY%\'}"; PIP_PROXY="${PIP_PROXY#\'}"
fi
if [ -n "${PIP_PROXY:-}" ]; then
    export HTTP_PROXY="$PIP_PROXY" HTTPS_PROXY="$PIP_PROXY"
    echo "Using download proxy: $PIP_PROXY"
fi

# ========================================================================
# Step 0: Setup NVM and Node.js (LTS, with npm 10+)
# ========================================================================
info "Step 0/10: Checking NVM and Node.js..."

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
echo "║              TraceLens - Setup Script                      ║"
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

# ------------------------------------------------------------------------
# libarchive discovery fallback.
# CMake requires libarchive through pkg-config (Android TAR/7z/AB container
# reader).  When libarchive-dev is not installed and cannot be (no root), a
# conda installation ships a compatible one: point pkg-config at its .pc file
# and hand CMake -L/-rpath so linking and runtime both resolve that library
# instead of the older system runtime (libarchive.so.13 exists on most
# distros but the linker needs the unversioned .so from the -dev package).
# Idempotent; a no-op whenever a system libarchive-dev is discoverable.
# ------------------------------------------------------------------------
LIBARCHIVE_CMAKE_FLAGS=()
configure_libarchive_fallback() {
    if [ "${#LIBARCHIVE_CMAKE_FLAGS[@]}" -gt 0 ]; then
        return 0
    fi
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libarchive 2>/dev/null; then
        local pc_libdir
        pc_libdir="$(pkg-config --variable=libdir libarchive 2>/dev/null || true)"
        case "$pc_libdir" in
            /usr/lib*|/lib*|/usr/local/lib*)
                ok "libarchive found via pkg-config (${pc_libdir:-system})"
                ;;
            *)
                # Non-default prefix (e.g. a user-exported PKG_CONFIG_PATH):
                # the bare -larchive needs -L/-rpath to resolve at link and
                # run time.
                LIBARCHIVE_CMAKE_FLAGS+=("-DCMAKE_EXE_LINKER_FLAGS=-L$pc_libdir -Wl,-rpath,$pc_libdir")
                warn "libarchive lives outside the default linker path ($pc_libdir); adding -L/-rpath"
                ;;
        esac
        return 0
    fi
    local conda_root
    for conda_root in "$HOME/anaconda3" "$HOME/miniconda3" "$HOME/miniforge3" "/opt/anaconda3" "/opt/miniconda3"; do
        if [ -f "$conda_root/lib/pkgconfig/libarchive.pc" ]; then
            export PKG_CONFIG_PATH="$conda_root/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
            LIBARCHIVE_CMAKE_FLAGS+=("-DCMAKE_EXE_LINKER_FLAGS=-L$conda_root/lib -Wl,-rpath,$conda_root/lib")
            warn "libarchive-dev not installed; using $conda_root's libarchive (pkg-config + linker -L/-rpath)"
            return 0
        fi
    done
    return 1
}

init_privileges

# ========================================================================
# Step 1/10: Install system packages (apt)
# ========================================================================
info "Step 1/10: Installing system packages via apt..."

APT_PACKAGES=(
    # Build tools
    build-essential cmake pkg-config git wget gnupg software-properties-common
    ca-certificates
    # Download proxy health checks and port cleanup in the start scripts
    curl lsof
    # Python runtime and venv support (python3 -m venv needs the distro package)
    python3 python3-venv
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
    # systemd journal parsing (systemd-python is built from source and needs
    # the libsystemd headers; without them the journal extractor silently
    # falls back to header-only output)
    libsystemd-dev
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
    # TAR/7z Android logical sources (libarchive, BSD-style license;
    # REQUIRED by this branch's CMake)
    libarchive-dev
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
    # PostgreSQL (distributed C/S server database, DATABASE_URL). Optional at
    # setup level: only the C/S server needs it, and the provisioning below
    # degrades to warnings — a sudo-less machine must still be able to build.
    postgresql postgresql-client
)

# These packages enable optional features, but the project can still build and
# run without them.  Keeping the list explicit lets setup.sh remain useful in
# non-root CI/dev environments where sudo cannot prompt for a password.
OPTIONAL_APT_PACKAGES=(
    libsqlcipher-dev
    ffmpeg
    redis-server
    redis-tools
    postgresql
    postgresql-client
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

        # libarchive-dev has a no-root fallback (a conda libarchive via
        # pkg-config + -L/-rpath, see configure_libarchive_fallback); don't
        # hard-fail a sudo-less setup when that fallback is available.
        if [ ${#MISSING_REQUIRED[@]} -gt 0 ] \
            && printf '%s\n' "${MISSING_REQUIRED[@]}" | grep -qx 'libarchive-dev' \
            && configure_libarchive_fallback; then
            MISSING_REQUIRED=($(printf '%s\n' "${MISSING_REQUIRED[@]}" | grep -vx 'libarchive-dev' || true))
            warn "Continuing without libarchive-dev; the conda libarchive will be used at link time"
        fi

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
# Step 2/10: Java 21 + Neo4j, then PostgreSQL
# ========================================================================
info "Step 2/10: Checking Java 21 and Neo4j..."

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

# ------------------------------------------------------------------------
# PostgreSQL — the distributed C/S server (:8091) hard-depends on the
# DATABASE_URL from .env. Ensure the server is running and provision the
# role/database named there so the C/S server works right after setup.
# Best effort: any failure degrades to a warning because the legacy
# httpserver (:8090) and the C++ server do not need PostgreSQL.
# ------------------------------------------------------------------------
info "Ensuring PostgreSQL is ready (distributed C/S server database)..."
if command -v systemctl &>/dev/null && [ "$CAN_ELEVATE" = true ]; then
    run_root systemctl enable --now postgresql >/dev/null 2>&1 || true
fi
if command -v pg_isready >/dev/null 2>&1; then
    for _ in $(seq 1 15); do
        pg_isready -h 127.0.0.1 -q 2>/dev/null && break
        if [ "$CAN_ELEVATE" = true ]; then
            run_root service postgresql start >/dev/null 2>&1 || true
        fi
        sleep 1
    done
fi

PG_READY=false
if command -v pg_isready >/dev/null 2>&1 && pg_isready -h 127.0.0.1 -q 2>/dev/null; then
    PG_READY=true
    ok "PostgreSQL is running on 127.0.0.1:5432"
else
    warn "PostgreSQL is not responding on 127.0.0.1:5432 — the distributed C/S server will fail to start; the rest of the stack is unaffected"
fi

if [ "$PG_READY" = true ]; then
    DB_URL="$(read_dotenv_value DATABASE_URL)"
    if [ -z "$DB_URL" ]; then
        warn "DATABASE_URL is not set in .env; configure it before using the distributed C/S server"
    elif ! command -v python3 >/dev/null 2>&1; then
        warn "python3 unavailable; cannot parse DATABASE_URL — provision the database manually if needed"
    elif [ "$CAN_ELEVATE" != true ]; then
        warn "No root/sudo: skipping PostgreSQL provisioning — create the DATABASE_URL role/database manually if missing"
    else
        DB_PARSED="$(python3 - "$DB_URL" <<'PY'
import sys, urllib.parse as up
p = up.urlparse(sys.argv[1].strip())
print("|".join([
    p.username or "postgres",
    up.unquote(p.password or ""),
    p.hostname or "127.0.0.1",
    str(p.port or 5432),
    (p.path or "/").lstrip("/") or "tracelens",
]))
PY
)"
        IFS='|' read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME <<< "$DB_PARSED"
        case "$DB_HOST" in
            localhost|127.0.0.1|::1)
                DB_PASS_ESC="${DB_PASS//\'/\'\'}"

                role_exists="$(run_as_user postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" 2>/dev/null || true)"
                if [ "$role_exists" != "1" ]; then
                    info "Creating PostgreSQL role '${DB_USER}'..."
                    if run_as_user postgres psql -c "CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASS_ESC}'" >/dev/null 2>&1; then
                        ok "PostgreSQL role '${DB_USER}' created"
                    else
                        warn "Could not create PostgreSQL role '${DB_USER}'"
                    fi
                elif [ -n "$DB_PASS" ] && ! PGPASSWORD="$DB_PASS" psql -h 127.0.0.1 -p "$DB_PORT" -U "$DB_USER" -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
                    # Existing role, but the DATABASE_URL password doesn't work
                    # (fresh installs ship the role without a password). Align
                    # the role with .env; never touch a working configuration.
                    info "Resetting PostgreSQL role '${DB_USER}' password to match DATABASE_URL..."
                    if run_as_user postgres psql -c "ALTER ROLE \"${DB_USER}\" WITH LOGIN PASSWORD '${DB_PASS_ESC}'" >/dev/null 2>&1; then
                        ok "PostgreSQL role '${DB_USER}' password aligned with DATABASE_URL"
                    else
                        warn "Could not update the '${DB_USER}' password"
                    fi
                fi

                db_exists="$(run_as_user postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null || true)"
                if [ "$db_exists" != "1" ]; then
                    info "Creating PostgreSQL database '${DB_NAME}'..."
                    if run_as_user postgres createdb -O "$DB_USER" "$DB_NAME" >/dev/null 2>&1; then
                        ok "PostgreSQL database '${DB_NAME}' created (owner: ${DB_USER})"
                    else
                        warn "Could not create PostgreSQL database '${DB_NAME}'"
                    fi
                fi
                ;;
            *)
                warn "DATABASE_URL points at ${DB_HOST} — skipping local provisioning; ensure the role/database exist there"
                ;;
        esac
    fi
fi

# ========================================================================
# Step 3/10: Install The Sleuth Kit 4.14.0 (if not present)
# ========================================================================
info "Step 3/10: Checking The Sleuth Kit (TSK)..."

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
# Step 4/10: Install Crow framework (if not present)
# ========================================================================
info "Step 4/10: Checking Crow HTTP framework..."

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
# Step 5/10: Install Google Test (if not present)
# ========================================================================
info "Step 5/10: Checking Google Test..."

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
# Step 6/10: Build Aliyun OSS C++ SDK (if not present)
# ========================================================================
info "Step 6/10: Checking Aliyun OSS C++ SDK..."

OSS_SDK_DIR="$PROJECT_ROOT/libs/aliyun-oss-cpp-sdk"
OSS_SDK_LIB="$OSS_SDK_DIR/build/lib/libalibabacloud-oss-cpp-sdk.a"

if [ -f "$OSS_SDK_LIB" ]; then
    ok "Aliyun OSS C++ SDK already built at $OSS_SDK_LIB"
else
    info "Building Aliyun OSS C++ SDK from source..."
    cd "$OSS_SDK_DIR"
    prepare_cmake_build_dir "$OSS_SDK_DIR/build" "$OSS_SDK_DIR"
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
# Step 7/10: Setup Python virtual environment
# ========================================================================
info "Step 7/10: Setting up Python virtual environment..."

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

# graphiti-core (knowledge graph) needs Python 3.10+.
PYVER_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)' 2>/dev/null || echo 0)"
if [ "$PYVER_OK" != "1" ]; then
    fail "Python >= 3.10 is required (graphiti-core dependency). Found: $(python3 --version 2>&1). Install a newer python3 and re-run setup.sh."
fi

ensure_venv_pip() {
    if ! "$PYTHON_EXEC" -m pip --version &>/dev/null; then
        info "  pip is missing from the virtual environment; bootstrapping with ensurepip..."
        "$PYTHON_EXEC" -m ensurepip --upgrade \
            || fail "Failed to bootstrap pip in $VENV_DIR. Verify that python3-venv is installed, remove the incomplete venv, and re-run setup.sh."
    fi
}

create_python_venv() {
    local venv_log="$PROJECT_ROOT/build/python-venv-create.log"
    mkdir -p "$PROJECT_ROOT/build"
    if ! python3 -m venv "$VENV_DIR" >"$venv_log" 2>&1; then
        tail -100 "$venv_log"
        fail "Failed to create the Python virtual environment. Verify that python3-venv is installed. Full log: $venv_log"
    fi
}

# Install a large / network-heavy Python package only if its module is NOT
# already importable. Tolerant: a download failure warns and continues, so one
# flaky big wheel cannot abort the whole setup. Used by the dedicated large-
# packages block below (kept separate from the requirements install on purpose
# so each big package is verified and retried individually).
ensure_large_python_package() {
    local pip_name="$1"
    local module="$2"
    if "$PYTHON_EXEC" -c "import $module" 2>/dev/null; then
        ok "  $pip_name already installed"
        return 0
    fi
    info "  Installing $pip_name ..."
    if "$PYTHON_EXEC" -m pip install --retries 5 --timeout 120 -q "$pip_name" 2>/dev/null; then
        ok "  $pip_name installed"
    else
        warn "  $pip_name failed to install - continuing (the feature it provides will be unavailable until installed)"
    fi
}

# Detect a partial venv left by an interrupted or failed `python3 -m venv`.
if [ -d "$VENV_DIR" ] && { [ ! -x "$PYTHON_EXEC" ] || [ ! -f "$VENV_DIR/pyvenv.cfg" ]; }; then
    warn "Virtual environment at $VENV_DIR is incomplete, recreating..."
    rm -rf "$VENV_DIR"
fi

if [ -x "$PYTHON_EXEC" ] && [ -f "$VENV_DIR/pyvenv.cfg" ]; then
    ok "Virtual environment exists at $VENV_DIR"
    ensure_venv_pip
    # Upgrade pip and install/update deps
    info "  Updating pip and dependencies..."
    if ! "$PYTHON_EXEC" -m pip install --upgrade pip -q 2>/dev/null; then
        warn "  pip upgrade had issues, continuing with existing pip..."
    fi
    if ! "$PYTHON_EXEC" -m pip install -q --retries 3 -r "$REQUIREMENTS_HTTPSERVER" -r "$REQUIREMENTS_SERVER" 2>/dev/null; then
        warn "  Some dependencies failed via the requirements files (likely a large-package network error); retrying big packages individually below..."
    fi
    touch "$VENV_DIR/.deps_installed"
    ok "Python dependencies updated"
else
    info "Creating new virtual environment..."
    create_python_venv
    ensure_venv_pip
    "$PYTHON_EXEC" -m pip install --upgrade pip -q
    if ! "$PYTHON_EXEC" -m pip install -q --retries 3 -r "$REQUIREMENTS_HTTPSERVER" -r "$REQUIREMENTS_SERVER" 2>/dev/null; then
        warn "  Some dependencies failed via the requirements files (likely a large-package network error); retrying big packages individually below..."
    fi
    touch "$VENV_DIR/.deps_installed"
    ok "Python virtual environment created and dependencies installed"
fi

# ------------------------------------------------------------------------
# Large / network-heavy Python packages (separate block, check-then-install).
# These big wheels are what break on flaky networks. They are installed
# individually - each verified importable before install and tolerated on
# failure - so a single flaky download cannot abort setup and packages that
# are already present are skipped fast. The requirements install above already
# attempts these; this block guarantees them.
# ------------------------------------------------------------------------
info "Installing large/optional Python packages (check-first, one at a time)..."
ensure_large_python_package "markitdown[all]"    markitdown
ensure_large_python_package "PyMuPDF==1.27.1"    fitz
ensure_large_python_package "volatility3"        volatility3
ensure_large_python_package "graphiti-core"      graphiti_core
ensure_large_python_package "h5py"               h5py
ensure_large_python_package "scipy"              scipy
ensure_large_python_package "plyvel"             plyvel
ensure_large_python_package "pillow-heif"        pillow_heif
ensure_large_python_package "rawpy"              rawpy
ensure_large_python_package "pydicom"            pydicom
# CPU model inference engines (versions pinned to match requirements.txt):
# CTranslate2 runs the Argos en_zh 1.9 OPUS-MT translation model,
# sherpa-onnx 1.13.8 runs the SenseVoice STT + silero VAD models.
ensure_large_python_package "ctranslate2==4.8.2"   ctranslate2
ensure_large_python_package "sentencepiece==0.2.2" sentencepiece
ensure_large_python_package "sherpa-onnx==1.13.8"  sherpa_onnx

# ------------------------------------------------------------------------
# Forensic parser bindings (check-then-install).
#
# These are the Python bindings behind the artifact extractors. They are in
# requirements.txt, but a network hiccup there leaves the extractor silently
# degrading: the C++ backend still asks for the file, the extractor returns
# "content unavailable", and the report quietly loses that evidence class
# (this is how 373 event logs once came back with zero facts). Installing them
# individually and reporting the result makes a missing binding visible at
# setup time instead of at report time.
# ------------------------------------------------------------------------
info "Verifying forensic parser bindings..."
FORENSIC_BINDINGS_OK=1
for binding in \
    "python-evtx:Evtx:Windows Event Log (.evtx)" \
    "python-registry:Registry:Windows Registry hives" \
    "libscca-python:pyscca:Windows Prefetch (.pf, MAM/XPRESS)" \
    "libewf-python:pyewf:E01/EnCase images" \
    "pypdf:pypdf:PDF metadata" \
    "psd-tools:psd_tools:Photoshop .psd" \
    "olefile:olefile:OLE2 (.msg, jump lists)" \
    "defusedxml:defusedxml:Safe XML parsing"
do
    IFS=':' read -r pip_name module description <<< "$binding"
    if "$PYTHON_EXEC" -c "import $module" 2>/dev/null; then
        ok "  $description ($pip_name)"
        continue
    fi
    info "  Installing $pip_name ($description) ..."
    if "$PYTHON_EXEC" -m pip install --retries 5 --timeout 120 -q "$pip_name" 2>/dev/null \
        && "$PYTHON_EXEC" -c "import $module" 2>/dev/null; then
        ok "  $description ($pip_name) installed"
    else
        warn "  $description unavailable: $pip_name could not be installed."
        warn "    Artifacts of this type will report 'content unavailable' instead of being parsed."
        FORENSIC_BINDINGS_OK=0
    fi
done
if [ "$FORENSIC_BINDINGS_OK" != "1" ]; then
    warn "One or more forensic parser bindings are missing; affected evidence types will not be analyzed."
    warn "Install them manually: $PYTHON_EXEC -m pip install -r $REQUIREMENTS_HTTPSERVER"
fi

# systemd journal (Linux .journal files). systemd-python has no wheel: it builds
# against libsystemd headers, so it only succeeds once libsystemd-dev is present
# (installed in step 1). Optional — the extractor degrades to header-only output
# without it — so a build failure here warns instead of aborting setup.
if "$PYTHON_EXEC" -c "import systemd.journal" 2>/dev/null; then
    ok "  systemd journal parsing (systemd-python)"
else
    info "  Installing systemd-python (systemd journal parsing) ..."
    if "$PYTHON_EXEC" -m pip install --retries 3 --timeout 120 -q systemd-python 2>/dev/null \
        && "$PYTHON_EXEC" -c "import systemd.journal" 2>/dev/null; then
        ok "  systemd journal parsing (systemd-python) installed"
    else
        warn "  systemd journal parsing unavailable (systemd-python needs libsystemd-dev)."
        warn "    Linux .journal artifacts will report header-only metadata."
    fi
fi

# ------------------------------------------------------------------------
# Local CPU models (checksum-pinned installers, tolerant of network failure).
# Both are optional at runtime — a missing model disables one overlay feature,
# never the forensic pipeline — but they are what makes the EN→ZH reading aid
# and audio/video transcription work out of the box, so install by default.
# ------------------------------------------------------------------------
# The Initial Analysis Chinese overlay translates the frozen English LLM
# output on CPU: Argos en_zh 1.9 (OPUS-MT weights in CTranslate2 format,
# ~67 MB) into build/models/translate-en_zh-1_9.
INSTALL_TRANSLATION_MODEL="${INSTALL_INITIAL_ANALYSIS_TRANSLATION_MODEL:-$(read_dotenv_value INSTALL_INITIAL_ANALYSIS_TRANSLATION_MODEL)}"
if [ "${INSTALL_TRANSLATION_MODEL:-1}" != "0" ]; then
    info "Installing offline EN-ZH translation model (Argos en_zh 1.9, ~67 MB)..."
    if "$PYTHON_EXEC" "$PROJECT_ROOT/scripts/install_initial_analysis_translation_model.py"; then
        ok "Offline EN-ZH translation model ready (build/models/translate-en_zh-1_9)"
    else
        warn "Offline EN-ZH model unavailable; Initial Analysis will show its original snapshot until the installer succeeds"
    fi
fi

# Audio STT: SenseVoice-small int8 (~239 MB) + silero VAD. The sherpa-onnx
# wheel is covered by the large-packages block above; this fetches the model
# files into python_service/models/audio.
INSTALL_STT_MODEL="${INSTALL_AUDIO_STT_MODEL:-$(read_dotenv_value INSTALL_AUDIO_STT_MODEL)}"
if [ "${INSTALL_STT_MODEL:-1}" != "0" ]; then
    info "Installing audio STT models (SenseVoice int8 ~239 MB + silero VAD)..."
    if "$PYTHON_EXEC" "$PROJECT_ROOT/scripts/install_audio_stt_model.py"; then
        ok "Audio STT models ready (python_service/models/audio)"
    else
        warn "Audio STT models unavailable; audio/video-soundtrack transcription will be skipped until the installer succeeds"
    fi
fi

# Core sanity check: if even the lightweight core failed, the venv is unusable
# - fail loudly rather than proceed to the C++ build.
if ! "$PYTHON_EXEC" -c "import fastapi, pydantic" 2>/dev/null; then
    rm -f "$VENV_DIR/.deps_installed"
    fail "Core Python dependencies (fastapi/pydantic) are missing. Re-run setup (set PIP_PROXY on a flaky network) or install manually: $PYTHON_EXEC -m pip install -r $REQUIREMENTS_HTTPSERVER -r $REQUIREMENTS_SERVER"
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
# Step 8/10: Build C++ project
# ========================================================================
info "Step 8/10: Building C++ project..."

# Build vendored Alibaba OSS SDK first (required by forensic_analyzer)
OSS_BUILD_DIR="$PROJECT_ROOT/libs/aliyun-oss-cpp-sdk/build"
if [ ! -f "$OSS_BUILD_DIR/lib/libalibabacloud-oss-cpp-sdk.a" ]; then
    info "  Building Alibaba OSS SDK..."
    prepare_cmake_build_dir "$OSS_BUILD_DIR" "$PROJECT_ROOT/libs/aliyun-oss-cpp-sdk"
    cd "$OSS_BUILD_DIR"
    cmake .. -DBUILD_SHARED_LIBS=OFF -DBUILD_SAMPLE=OFF -DBUILD_TESTS=OFF 2>&1 | tail -3
    make -j$(nproc) -s
    ok "OSS SDK built"
else
    ok "OSS SDK already built"
fi

BUILD_DIR="$PROJECT_ROOT/build"
prepare_cmake_build_dir "$BUILD_DIR" "$PROJECT_ROOT"
cd "$BUILD_DIR"

# Resolve libarchive before configuring: no-op when the system -dev package is
# discoverable, otherwise exports the conda pkg-config path and linker flags.
if ! configure_libarchive_fallback; then
    warn "libarchive was not found — CMake configure will fail until libarchive-dev is installed or a conda libarchive is available"
fi

info "  Running cmake..."
CMAKE_CONFIG_LOG="$BUILD_DIR/cmake-configure.log"
CMAKE_ARGS=(-DCMAKE_BUILD_TYPE=Release)
# setup.sh builds the frontend itself in Step 9; keep npm out of the ALL
# target so a later plain `make build` cannot trigger a full npm install/build.
CMAKE_ARGS+=(-DBUILD_WEB_FRONTEND=OFF)
if [ ${#LIBARCHIVE_CMAKE_FLAGS[@]} -gt 0 ]; then
    CMAKE_ARGS+=("${LIBARCHIVE_CMAKE_FLAGS[@]}")
fi
if ! cmake .. "${CMAKE_ARGS[@]}" >"$CMAKE_CONFIG_LOG" 2>&1; then
    tail -100 "$CMAKE_CONFIG_LOG"
    fail "CMake configuration failed. Full log: $CMAKE_CONFIG_LOG"
fi
grep -E "(error|warning:|Found|Configuring|SQLCipher)" "$CMAKE_CONFIG_LOG" || true

info "  Building main target ($(nproc) threads)..."
# Build only the main target: web_frontend is handled in Step 9, and the
# release branch's test targets are known to fail to link (tests/CMakeLists.txt
# misses MediaAnalysisProxy.cpp for four LLM test targets) — the main binary
# and all services are unaffected.
CMAKE_BUILD_LOG="$BUILD_DIR/forensic_analyzer-build.log"
if ! cmake --build . --target forensic_analyzer -j$(nproc) >"$CMAKE_BUILD_LOG" 2>&1; then
    tail -100 "$CMAKE_BUILD_LOG"
    fail "C++ build failed. Full log: $CMAKE_BUILD_LOG"
fi
tail -20 "$CMAKE_BUILD_LOG"

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
# Step 9/10: Build Web Frontend (required — the C++ server serves the SPA)
# ========================================================================
BUILD_DIR="$PROJECT_ROOT/build"

if [ -d "$PROJECT_ROOT/web" ] && [ -f "$PROJECT_ROOT/web/package.json" ]; then
    info "Step 9/10: Building web frontend..."
    cd "$PROJECT_ROOT/web"
    if ! command -v node &>/dev/null || ! command -v npm &>/dev/null; then
        fail "Node.js and npm are required to build the web frontend. Install Node.js 22 or fix the NVM installation, then re-run setup.sh."
    fi
    # (Re)install when node_modules is missing/broken OR when package-lock.json
    # is newer than the last install — a branch switch can add dependencies
    # (e.g. docx-preview) that CMake's npm stamp would not pick up.
    NEEDS_WEB_INSTALL=0
    if [ ! -d "node_modules" ] || [ ! -x "node_modules/.bin/vite" ]; then
        NEEDS_WEB_INSTALL=1
    elif [ -f "package-lock.json" ] && [ "package-lock.json" -nt "node_modules/.package-lock.json" ]; then
        NEEDS_WEB_INSTALL=1
    fi
    if [ "$NEEDS_WEB_INSTALL" = "1" ]; then
        info "  Installing web dependencies..."
        WEB_INSTALL_LOG="$BUILD_DIR/web-frontend-install.log"
        if [ -f "package-lock.json" ]; then
            NPM_INSTALL_COMMAND=(npm ci --silent)
        else
            NPM_INSTALL_COMMAND=(npm install --silent)
        fi
        if ! "${NPM_INSTALL_COMMAND[@]}" >"$WEB_INSTALL_LOG" 2>&1; then
            warn "  npm ci failed (lockfile out of sync?); falling back to npm install..."
            NPM_INSTALL_COMMAND=(npm install --silent)
            if ! "${NPM_INSTALL_COMMAND[@]}" >"$WEB_INSTALL_LOG" 2>&1; then
                tail -100 "$WEB_INSTALL_LOG"
                fail "Web dependency installation failed. Full log: $WEB_INSTALL_LOG"
            fi
        fi
        tail -3 "$WEB_INSTALL_LOG"
    fi
    WEB_BUILD_LOG="$BUILD_DIR/web-frontend-build.log"
    if ! npm run build >"$WEB_BUILD_LOG" 2>&1; then
        tail -100 "$WEB_BUILD_LOG"
        fail "Web frontend build failed. Full log: $WEB_BUILD_LOG"
    fi
    tail -3 "$WEB_BUILD_LOG"
    # The C++ server serves the SPA from <cwd>/web/dist, and the start scripts
    # run it with cwd=build/. Mirror the CMake web_frontend target: wipe the
    # destination first so stale hashed chunks cannot accumulate
    # (copy_directory merges into what is already there otherwise).
    rm -rf "$BUILD_DIR/web/dist"
    mkdir -p "$BUILD_DIR/web/dist"
    cp -r "$PROJECT_ROOT/web/dist/." "$BUILD_DIR/web/dist/"
    ok "Web frontend built and synced to $BUILD_DIR/web/dist"
else
    warn "web/ frontend sources not found — the C++ server will have no SPA to serve"
fi

cd "$PROJECT_ROOT"

# ========================================================================
# Step 10/10: Verify the installation is ready to use
# ========================================================================
info "Step 10/10: Verifying the installation..."

CPP_PORT="$(read_dotenv_value HTTP_SERVER_PORT)"; CPP_PORT="${CPP_PORT:-8080}"
PY_PORT="$(read_dotenv_value PYTHON_HTTP_PORT)"; PY_PORT="${PY_PORT:-8090}"
CS_PORT="$(read_dotenv_value CS_PORT)"; CS_PORT="${CS_PORT:-8091}"

if [ ! -x "$BUILD_DIR/forensic_analyzer" ]; then
    fail "C++ binary missing: $BUILD_DIR/forensic_analyzer"
fi
ok "C++ binary: $BUILD_DIR/forensic_analyzer"

if [ ! -f "$BUILD_DIR/web/dist/index.html" ]; then
    fail "Web frontend missing: $BUILD_DIR/web/dist/index.html (the C++ server would have no SPA to serve)"
fi
ok "Web frontend: $BUILD_DIR/web/dist"

if ! "$PYTHON_EXEC" -c "import fastapi, pydantic" 2>/dev/null; then
    fail "Python venv unusable (fastapi/pydantic missing): $VENV_DIR"
fi
ok "Python venv: $VENV_DIR"

if [ -f "$PROJECT_ROOT/build/models/translate-en_zh-1_9/model/model.bin" ]; then
    ok "EN-ZH translation model: build/models/translate-en_zh-1_9"
else
    warn "EN-ZH translation model missing — Initial Analysis will show the original English snapshot (re-run setup, or set INSTALL_INITIAL_ANALYSIS_TRANSLATION_MODEL=0 to silence)"
fi

if [ -f "$PROJECT_ROOT/python_service/models/audio/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx" ] \
    && [ -f "$PROJECT_ROOT/python_service/models/audio/silero_vad.onnx" ]; then
    ok "Audio STT models: python_service/models/audio"
else
    warn "Audio STT models missing — audio/video-soundtrack transcription will be skipped (re-run setup, or set INSTALL_AUDIO_STT_MODEL=0 to silence)"
fi

if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    ok "Redis: running (127.0.0.1:6379)"
else
    warn "Redis: not responding — start it (sudo systemctl start redis-server); ingestion jobs will use in-memory storage"
fi

if curl -fsS --max-time 3 -o /dev/null http://localhost:7474 2>/dev/null; then
    ok "Neo4j: running (http://localhost:7474)"
else
    warn "Neo4j: not responding on 7474 — start it (sudo systemctl start neo4j); knowledge-graph features need it"
fi

if command -v pg_isready >/dev/null 2>&1 && pg_isready -h 127.0.0.1 -q 2>/dev/null; then
    ok "PostgreSQL: running (127.0.0.1:5432)"
else
    warn "PostgreSQL: not responding — the distributed C/S server (:${CS_PORT}) needs it"
fi

# ========================================================================
# Summary
# ========================================================================
echo ""
echo -e "${GREEN}${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║              SETUP COMPLETE — READY TO START                ║${NC}"
echo -e "${GREEN}${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo -e "  ${CYAN}./scripts/start_all_services.sh${NC}  Start all services (foreground; Ctrl+C stops them)"
echo -e "  ${CYAN}./run.sh --no-build${NC}              Same stack with rotated logs (daily entry point)"
echo -e "  ${CYAN}make start${NC}                       Alias of start_all_services.sh"
echo -e "  ${CYAN}./setup.sh --start${NC}               (next time) setup and start in one step"
echo ""
echo -e "${BOLD}Service endpoints (from .env):${NC}"
echo -e "  Web UI (SPA + /python gateway): ${BLUE}http://localhost:${CPP_PORT}/${NC}"
echo -e "  C++ API docs:                   ${BLUE}http://localhost:${CPP_PORT}/api/docs${NC}"
echo -e "  Python service:                 ${BLUE}http://localhost:${PY_PORT}/docs${NC}"
echo -e "  Distributed C/S (PostgreSQL):   ${BLUE}http://localhost:${CS_PORT}/docs${NC}"
echo -e "  Neo4j Browser:                  ${BLUE}http://localhost:7474${NC}"
echo ""

if [ "$START_SERVICES" = "1" ]; then
    info "Starting all services (--start)..."
    exec "$PROJECT_ROOT/scripts/start_all_services.sh"
fi
