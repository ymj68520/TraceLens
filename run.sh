#!/bin/bash
#
# TraceLens 一键编译启动脚本
# ---------------------------------------------------------------------------
# 功能：CMake 编译 C++ → 构建 Web 前端 (npm) → 启动全部服务（前台运行）
#
# 用法:
#   ./run.sh                  # 编译 + 启动 C++(8666) + Python(8090) + C/S(8091)
#   ./run.sh --build-only     # 仅编译，不启动服务
#   ./run.sh --no-build       # 跳过编译，直接启动（需已构建）
#   ./run.sh --no-web         # 跳过 web 前端构建
#   ./run.sh --no-python      # 仅启动 C++ 服务，不启动 Python
#   ./run.sh --jobs 4         # 指定编译并行数（默认 4，避免占满 CPU）
#   ./run.sh --clean          # 编译前先清理 build 目录（保留数据库等数据）
#
# 端口从 .env 读取（默认: C++ 8666 / Python 8090 / C/S 8091）。
# 按 Ctrl+C 停止所有服务。
# ---------------------------------------------------------------------------

set -e

# ── 路径与默认值 ──────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
BUILD_DIR="$PROJECT_ROOT/build"
WEB_DIR="$PROJECT_ROOT/web"
LOG_DIR="$BUILD_DIR/logs"
mkdir -p "$LOG_DIR"

JOBS=4
DO_BUILD=1
BUILD_WEB=1
RUN_PYTHON=1
RUN_CPP=1
CLEAN_FIRST=0

# ── 解析参数 ──────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-only) DO_BUILD=1; RUN_CPP=0; RUN_PYTHON=0; shift ;;
        --no-build)   DO_BUILD=0; shift ;;
        --no-web)     BUILD_WEB=0; shift ;;
        --no-python)  RUN_PYTHON=0; shift ;;
        --no-cpp)     RUN_CPP=0; shift ;;
        --jobs)       JOBS="$2"; shift 2 ;;
        -j)           JOBS="$2"; shift 2 ;;
        --clean)      CLEAN_FIRST=1; shift ;;
        -h|--help)
            sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "未知参数: $1（用 --help 查看用法）"; exit 1 ;;
    esac
done

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── 加载 .env ─────────────────────────────────────────────────────────────────
# 注意：用独立变量 TRACELENS_ROOT 锁定项目根，避免被 .env 里的
# PROJECT_ROOT=（空值）或 DATA_DIR=（相对值）覆盖后路径错乱。
TRACELENS_ROOT="$PROJECT_ROOT"
if [ -f "$TRACELENS_ROOT/.env" ]; then
    set -a
    # 过滤两类行：
    #   1) PYTHON_CORS_ORIGINS=["*"] —— C++ dotenv 无法解析，会告警
    #   2) PROJECT_ROOT=（空值）—— 会覆盖脚本算出的真实项目根，导致
    #      后续 $PROJECT_ROOT/python_service 变成 /python_service 而报权限错误
    grep -vE '^\s*PYTHON_CORS_ORIGINS\s*=' "$TRACELENS_ROOT/.env" \
        | grep -vE '^\s*PROJECT_ROOT\s*=' \
        | grep -vE '^\s*#' | grep -vE '^\s*$' > /tmp/tracelens.env.$$
    source /tmp/tracelens.env.$$
    rm -f /tmp/tracelens.env.$$
    set +a
fi
# 始终用脚本算出的项目根，不受 .env 影响
PROJECT_ROOT="$TRACELENS_ROOT"

CPP_PORT="${HTTP_SERVER_PORT:-8666}"
PYTHON_PORT="${PYTHON_HTTP_PORT:-8090}"
CS_PORT="${CS_PORT:-8091}"

echo -e "${CYAN}${BOLD}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║              TraceLens  一键编译启动                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  编译并行数: ${BOLD}-j${JOBS}${NC}   (限制 CPU 防止卡死)"
echo -e "  C++    : ${BLUE}http://localhost:${CPP_PORT}${NC}"
[ "$RUN_PYTHON" = "1" ] && echo -e "  Python : ${BLUE}http://localhost:${PYTHON_PORT}${NC}"
[ "$RUN_PYTHON" = "1" ] && echo -e "  C/S    : ${BLUE}http://localhost:${CS_PORT}${NC}"
echo ""

# ── 健康检查 ──────────────────────────────────────────────────────────────────
check_service() {
    local url=$1 name=$2 max_attempts=${3:-30} attempt=1
    echo -ne "${CYAN}等待 ${name} 启动...${NC}"
    while [ $attempt -le $max_attempts ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -qE "200|404"; then
            echo -e " ${GREEN}✓ 就绪${NC}"
            return 0
        fi
        echo -n "."; sleep 1; attempt=$((attempt + 1))
    done
    echo -e " ${RED}✗ 超时${NC}"
    return 1
}

# ── 编译阶段 ──────────────────────────────────────────────────────────────────
if [ "$DO_BUILD" = "1" ]; then
    echo -e "${BLUE}➤ 阶段 1: CMake 编译 C++（-j${JOBS}）${NC}"

    if [ "$CLEAN_FIRST" = "1" ]; then
        echo -e "${YELLOW}  清理 build 目录（保留 logs/ data/ 和 *_*.db 数据）${NC}"
        find "$BUILD_DIR" -maxdepth 1 \( \
            -name 'CMakeFiles' -o -name 'CMakeCache.txt' -o -name 'cmake_install.cmake' \
            -o -name 'Makefile' -o -name 'CTestTestfile.cmake' -o -name 'Testing' \
            -o -name '*.o' \) -exec rm -rf {} + 2>/dev/null || true
    fi

    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"
    if [ ! -f CMakeCache.txt ]; then
        echo -e "${YELLOW}  首次配置，运行 cmake ..${NC}"
        cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_WEB_FRONTEND=OFF
    fi
    # BUILD_WEB_FRONTEND=OFF：前端由本脚本用 npm 单独构建，
    # 避免 CMake 在 ALL 目标里触发全量 npm install/build 占满 CPU。
    cmake --build . -j"$JOBS"
    if [ ! -f "$BUILD_DIR/forensic_analyzer" ]; then
        echo -e "${RED}✗ 编译失败：未生成 forensic_analyzer${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ C++ 编译完成${NC}\n"

    # ── Web 前端构建 ────────────────────────────────────────────────────────
    if [ "$BUILD_WEB" = "1" ]; then
        echo -e "${BLUE}➤ 阶段 2: 构建 Web 前端 (npm run build)${NC}"
        cd "$WEB_DIR"
        if [ ! -d node_modules ]; then
            echo -e "${YELLOW}  node_modules 不存在，运行 npm install...${NC}"
            nice -n 19 npm install
        fi
        nice -n 19 npm run build
        if [ ! -f "$WEB_DIR/dist/index.html" ]; then
            echo -e "${RED}✗ Web 构建失败：dist/index.html 未生成${NC}"
            exit 1
        fi
        # 同步到 C++ 二进制所在目录（C++ 从相对路径 web/dist 读取前端）
        echo -e "${YELLOW}  同步 dist → build/web/dist${NC}"
        rm -rf "$BUILD_DIR/web/dist"
        mkdir -p "$BUILD_DIR/web/dist"
        cp -r "$WEB_DIR/dist/." "$BUILD_DIR/web/dist/"
        echo -e "${GREEN}✓ Web 前端构建完成${NC}\n"
    fi
fi

# build-only 则到此结束
if [ "$RUN_CPP" = "0" ] && [ "$RUN_PYTHON" = "0" ]; then
    echo -e "${GREEN}${BOLD}✓ 编译完成（未启动服务）${NC}"
    exit 0
fi

# ── 启动前检查二进制 ──────────────────────────────────────────────────────────
if [ "$RUN_CPP" = "1" ] && [ ! -f "$BUILD_DIR/forensic_analyzer" ]; then
    echo -e "${RED}✗ C++ 二进制不存在: $BUILD_DIR/forensic_analyzer${NC}"
    echo -e "${YELLOW}  请去掉 --no-build 重新运行以先编译${NC}"
    exit 1
fi

# ── 清理可能残留的旧进程 ─────────────────────────────────────────────────────
echo -e "${YELLOW}➤ 清理端口上的残留进程...${NC}"
for port in "$CPP_PORT" "$PYTHON_PORT" "$CS_PORT"; do
    OLD_PID="$(lsof -ti :"$port" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ]; then
        echo -e "  ${YELLOW}端口 ${port} 被 PID ${OLD_PID} 占用，正在停止${NC}"
        kill -9 $OLD_PID 2>/dev/null || true
        sleep 1
    fi
done

# ── 子进程 PID 跟踪与清理 ─────────────────────────────────────────────────────
CPP_PID=""; PYTHON_PID=""; CS_PID=""
cleanup() {
    echo -e "\n${YELLOW}───────────────────────────────────────────${NC}"
    echo -e "${YELLOW}正在停止所有服务...${NC}"
    for pid in "$CS_PID" "$PYTHON_PID" "$CPP_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    echo -e "${GREEN}✓ 全部服务已停止${NC}"
    trap - EXIT INT TERM
    exit 0
}
trap cleanup EXIT INT TERM

# ── 启动 C++ 服务 ─────────────────────────────────────────────────────────────
if [ "$RUN_CPP" = "1" ]; then
    echo -e "${BLUE}➤ 启动 C++ HTTP 服务（端口 ${CPP_PORT}）${NC}"
    cd "$BUILD_DIR"
    ./forensic_analyzer --http-server "$CPP_PORT" > "$LOG_DIR/cpp_server.log" 2>&1 &
    CPP_PID=$!
    echo -e "  ${GREEN}✓ PID ${CPP_PID}${NC}  日志: $LOG_DIR/cpp_server.log"
    if ! check_service "http://localhost:${CPP_PORT}/api/system/health" "C++ 服务" 15; then
        echo -e "${RED}✗ C++ 服务启动失败，日志尾部：${NC}"
        tail -n 30 "$LOG_DIR/cpp_server.log" 2>/dev/null || true
        exit 1
    fi
    echo
fi

# ── 启动 Python 服务 ─────────────────────────────────────────────────────────
if [ "$RUN_PYTHON" = "1" ]; then
    PY_DIR="$PROJECT_ROOT/python_service"
    PY_EXEC="$PY_DIR/.venv/bin/python"

    if [ ! -f "$PY_EXEC" ]; then
        echo -e "${YELLOW}  Python venv 不存在，正在创建...${NC}"
        python3 -m venv "$PY_DIR/.venv"
        "$PY_EXEC" -m pip install -q --upgrade pip
        "$PY_EXEC" -m pip install -q -r "$PY_DIR/httpserver/requirements.txt" \
                                    -r "$PY_DIR/requirements.txt"
    elif [ ! -f "$PY_DIR/.venv/.deps_installed" ]; then
        echo -e "${YELLOW}  安装 Python 依赖...${NC}"
        "$PY_EXEC" -m pip install -q -r "$PY_DIR/httpserver/requirements.txt" \
                                    -r "$PY_DIR/requirements.txt" && \
        touch "$PY_DIR/.venv/.deps_installed"
    fi

    # httpserver (8090)
    echo -e "${BLUE}➤ 启动 Python FastAPI 服务（端口 ${PYTHON_PORT}）${NC}"
    cd "$PY_DIR"
    PYTHONPATH="$PY_DIR:$PYTHONPATH" \
        "$PY_EXEC" -m httpserver.main > "$LOG_DIR/python_service.log" 2>&1 &
    PYTHON_PID=$!
    echo -e "  ${GREEN}✓ PID ${PYTHON_PID}${NC}  日志: $LOG_DIR/python_service.log"
    check_service "http://localhost:${PYTHON_PORT}/health" "Python 服务" 30 || \
        echo -e "${YELLOW}⚠ Python 健康检查失败，查看日志: $LOG_DIR/python_service.log${NC}"

    # 分布式 C/S server (8091) —— 与 httpserver 并行，失败不阻断
    echo -e "${BLUE}➤ 启动分布式 C/S 服务（端口 ${CS_PORT}）${NC}"
    ( cd "$PY_DIR" && PORT="$CS_PORT" \
        PYTHONPATH="$PY_DIR:$PYTHONPATH" \
        exec "$PY_EXEC" -m server.main ) > "$LOG_DIR/cs_server.log" 2>&1 &
    CS_PID=$!
    echo -e "  ${GREEN}✓ PID ${CS_PID}${NC}  日志: $LOG_DIR/cs_server.log"
    check_service "http://localhost:${CS_PORT}/health" "C/S 服务" 30 || \
        echo -e "${YELLOW}⚠ C/S 健康检查失败（不影响 C++/httpserver）${NC}"
    echo
fi

# ── 总结 ──────────────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║              全部服务启动成功                               ║${NC}"
echo -e "${GREEN}${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "  ${BOLD}📍 访问地址:${NC}"
echo -e "    Web 界面    ${BLUE}http://localhost:${CPP_PORT}/${NC}"
echo -e "    C++ API 文档 ${BLUE}http://localhost:${CPP_PORT}/api/docs${NC}"
echo -e "    健康检查     ${BLUE}http://localhost:${CPP_PORT}/api/system/health${NC}"
[ "$RUN_PYTHON" = "1" ] && {
    echo -e "    Python API   ${BLUE}http://localhost:${PYTHON_PORT}/docs${NC}"
    echo -e "    C/S API      ${BLUE}http://localhost:${CS_PORT}/docs${NC}"
}
echo
echo -e "  ${BOLD}🔧 进程:${NC}"
[ -n "$CPP_PID" ]    && echo -e "    C++ 服务     ${GREEN}PID ${CPP_PID}${NC}"
[ -n "$PYTHON_PID" ] && echo -e "    Python 服务  ${GREEN}PID ${PYTHON_PID}${NC}"
[ -n "$CS_PID" ]     && echo -e "    C/S 服务     ${GREEN}PID ${CS_PID}${NC}"
echo
echo -e "${YELLOW}${BOLD}按 Ctrl+C 停止所有服务${NC}"
echo

# 前台等待，直到收到信号
wait
