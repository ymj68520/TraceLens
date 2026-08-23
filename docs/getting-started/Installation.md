# 安装指南

本文档提供 TraceLens 的安装步骤：一键脚本（推荐）、手动依赖、外部服务与 `.env` 配置。所有命令均与仓库当前脚本一致。

---

## 1. 系统要求

| 组件 | 最低要求 | 说明 |
|------|---------|------|
| 操作系统 | Ubuntu 20.04+ / Debian 11+ | setup.sh 基于 apt；其他发行版需手动移植依赖 |
| 编译器 | GCC 10+（支持 C++20） | 项目强制 `CMAKE_CXX_STANDARD 20` |
| CMake | ≥ 3.20 | `cmake_minimum_required(VERSION 3.20)` |
| Python | 3.10+ | venv 由脚本创建于 `python_service/.venv` |
| Node.js | 22 LTS（NVM 安装） | 仅构建 web 前端需要 |
| 磁盘 | 20GB+ | TSK/OSS SDK 源码编译 + Python 大包 |
| 权限 | sudo/root | 系统库、Neo4j、Redis 安装需要 |

---

## 2. 一键安装（推荐）

```bash
git clone https://github.com/ymj68520/TraceLens.git
cd TraceLens
sudo bash setup.sh
```

`setup.sh`（幂等，可重复运行）依次执行：

| 步骤 | 内容 |
|------|------|
| 0/8 | NVM 安装 + Node.js 22 LTS 激活 |
| 1/8 | apt 安装全部系统依赖（见下文明细）并确保 redis-server 运行 |
| 2/8 | Java 21（openjdk-21-jre-headless + jdk）+ Neo4j 官方 apt 仓库安装；用 `NEO4J_PASSWORD`（环境变量或 `.env`）设置初始密码，`systemctl enable --now neo4j` |
| 3/8 | The Sleuth Kit **4.14.0** 源码编译安装到 `/usr/local/lib/libtsk.so` |
| 4/8 | Crow 框架源码安装（`/usr/local/include/crow.h`） |
| 5/8 | Google Test（优先从 `/usr/src/googletest` 编译） |
| 6/8 | 阿里云 OSS C++ SDK：`libs/aliyun-oss-cpp-sdk` 下 cmake 构建 |
| 7/8 | Python venv：`python_service/.venv`，安装 `httpserver/requirements.txt` + `requirements.txt`，逐个核对安装大包（markitdown[all]、PyMuPDF==1.27.1、volatility3、graphiti-core、h5py、scipy、plyvel、pillow-heif、rawpy、pydicom），并把 `resources/volatility3-plugins/windows/bitlocker_fvek_scan.py` 安装进 venv 的 volatility3 插件目录 |
| 8/8 | OSS SDK 静态库 + CMake Release 构建 `build/forensic_analyzer`（ldd 检查缺失库）+ 可选 `npm run build` 前端 |

apt 安装的取证/分析相关包（摘自 setup.sh）：

```
libsqlite3-dev libsqlcipher-dev libssl-dev
libboost-dev libboost-system-dev libboost-thread-dev
nlohmann-json3-dev libasio-dev
libhivex-dev libevtx-dev libesedb-dev libolecf-dev libbfio-dev libewf-dev libfsntfs-dev
libxapian-dev libpoppler-cpp-dev libpugixml-dev
zlib1g-dev liblzma-dev libbz2-dev libzstd-dev
libcurl4-openssl-dev libzip-dev antiword ffmpeg
libgtest-dev libgmock-dev libmysqlclient-dev libpq-dev
redis-server redis-tools
```

网络不稳定时：`export PIP_PROXY=http://<代理>:<端口>`（或写入 `.env`），脚本会导出为 HTTP_PROXY/HTTPS_PROXY 供 pip/git/curl 使用。

安装完成标志：

```bash
ls build/forensic_analyzer && build/forensic_analyzer --version
# Forensic Image Analyzer v1.0 / Using The Sleuth Kit 4.14.0
```

---

## 3. 手动安装依赖

仅在无法使用一键脚本时参考。以下三项**不在 apt 中，必须源码安装**：TSK 4.14.0、Crow、阿里云 OSS C++ SDK（vendored 在仓库 `libs/aliyun-oss-cpp-sdk`）。

### 3.1 apt 依赖

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential cmake pkg-config git wget gnupg software-properties-common ca-certificates \
    libsqlite3-dev libsqlcipher-dev libssl-dev \
    libboost-dev libboost-system-dev libboost-thread-dev \
    nlohmann-json3-dev libasio-dev \
    libhivex-dev libevtx-dev libesedb-dev libolecf-dev libbfio-dev libewf-dev libfsntfs-dev \
    libxapian-dev libpoppler-cpp-dev libpugixml-dev \
    zlib1g-dev liblzma-dev libbz2-dev libzstd-dev \
    libcurl4-openssl-dev libzip-dev antiword ffmpeg \
    libgtest-dev libgmock-dev libmysqlclient-dev libpq-dev \
    redis-server redis-tools
```

其中 ffmpeg/redis-server/libsqlcipher 是可选功能（媒体提取 / 摄取任务持久化 / 加密数据库），缺失时相关功能降级但不影响构建。

### 3.2 The Sleuth Kit 4.14.0（源码）

```bash
wget https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.14.0/sleuthkit-4.14.0.tar.gz
tar -xzf sleuthkit-4.14.0.tar.gz && cd sleuthkit-4.14.0
./configure
make -j$(nproc)
sudo make install && sudo ldconfig
```

### 3.3 Crow（源码）

```bash
git clone --depth 1 https://github.com/CrowCpp/Crow.git
cd Crow && mkdir build && cd build
cmake .. -DCROW_BUILD_EXAMPLES=OFF -DCROW_BUILD_TESTS=OFF
make -j$(nproc) && sudo make install
```

### 3.4 阿里云 OSS C++ SDK（仓库内置源码）

```bash
cd libs/aliyun-oss-cpp-sdk
mkdir -p build && cd build
cmake .. -DBUILD_SHARED_LIBS=OFF -DBUILD_SAMPLE=OFF -DBUILD_TESTS=OFF
make -j$(nproc)
# 产物: libs/aliyun-oss-cpp-sdk/build/lib/libalibabacloud-oss-cpp-sdk.a
```

### 3.5 Python venv（两个 requirements 都要装）

```bash
python3 -m venv python_service/.venv
python_service/.venv/bin/pip install --upgrade pip
python_service/.venv/bin/pip install \
    -r python_service/httpserver/requirements.txt \
    -r python_service/requirements.txt
# 大包（可选功能，失败会警告不中断）
python_service/.venv/bin/pip install "markitdown[all]" "PyMuPDF==1.27.1" volatility3 graphiti-core
```

也可直接 `make setup`（= setup-venv + setup-web）。

### 3.6 Node.js / web 前端

```bash
# NVM + Node 22
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.nvm/nvm.sh && nvm install 22
make setup-web        # cd web && npm install
```

### 3.7 构建

```bash
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)          # 或 make build
```

CMake 选项 `BUILD_WEB_FRONTEND`（默认 ON）控制是否在 ALL 目标里触发 npm 构建；`./run.sh` 显式传 `-DBUILD_WEB_FRONTEND=OFF` 并单独用 npm 构建，避免占满 CPU。

---

## 4. 外部服务

### 4.1 Neo4j（Graphiti 知识图谱，可选但推荐）

setup.sh 自动安装并设置密码。手动安装：

```bash
sudo apt-get install -y openjdk-21-jre-headless openjdk-21-jdk
# 添加官方仓库（见 setup.sh Step 2 的 keyring/sources 写法）后：
sudo apt-get install -y neo4j
sudo -u neo4j neo4j-admin dbms set-initial-password '<密码>'
sudo systemctl enable --now neo4j
```

连接失败时 GraphitiService 会标记 disabled（降级，不阻断服务）。浏览器管理界面 `http://localhost:7474`，Bolt 端口 7687。

### 4.2 Redis（摄取任务持久化，可选）

```bash
sudo apt-get install -y redis-server redis-tools
redis-cli ping    # PONG 即可
```

未运行时摄取任务队列自动退化为内存存储（日志出现 "Redis not available, using in-memory storage" 警告），重启后任务状态丢失。

### 4.3 PostgreSQL（分布式 C/S 服务，仅 server.main 需要）

`DATABASE_URL` 指向 PostgreSQL（默认 `postgresql://postgres:change-me@localhost:5432/tracelens`）。数据库不可用时 C/S 服务以降级模式启动（`/health` 返回 `"database": "degraded"`，`/health/ready` 返回 503）。不用分布式功能可忽略。

### 4.4 LLM 端点（AI 分析，可选）

- OpenAI 兼容 API（LM Studio / vLLM 等），`.env` 中配置 `LLM_BASE_URL` + `LLM_ENDPOINT=/v1/chat/completions`。
- Graphiti 全功能要求同一端点**同时加载**两个模型（`.env.example` 注释）：`openai/gpt-oss-20b`（推理）与 `text-embedding-nomic-embed-text-v1.5`（嵌入）。
- 模型名必须与 `LLM_TEXT_MODEL` / `LLM_VISION_MODEL` 完全一致。
- 无 LLM 环境用 `--no-ai` 跳过 AI 分析。

---

## 5. .env 配置

```bash
cp .env.example .env
```

以下为 `.env.example` 中的全部真实变量（默认值取自该文件）：

### 5.1 路径

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROJECT_ROOT` | 空（自动检测） | 项目根绝对路径；留空则按可执行文件位置推导 |
| `DATA_DIR` | `data` | 运行时数据目录（相对可执行文件） |

### 5.2 LLM

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `http://192.168.31.170:1234` | OpenAI 兼容端点（共享） |
| `LLM_ENDPOINT` | `/v1/chat/completions` | chat completions 路径 |
| `LLM_API_KEY` | 空 | API key（本地端点可为空） |
| `LLM_TEXT_BASE_URL` | `http://192.168.31.170:1234` | 文本模型端点 |
| `LLM_TEXT_MODEL` | `qwen/qwen3.6-35b-a3b` | 文本模型名 |
| `LLM_TEXT_MAX_TOKENS` | `4096` | 文本模型 max tokens |
| `LLM_TEXT_TEMPERATURE` | `0.7` | 文本模型温度 |
| `LLM_VISION_BASE_URL` | `http://192.168.31.170:1234` | 视觉模型端点 |
| `LLM_VISION_MODEL` | `qwen/qwen3.6-35b-a3b` | 视觉模型名 |
| `LLM_VISION_MAX_TOKENS` | `4096` | 视觉模型 max tokens |
| `LLM_VISION_TEMPERATURE` | `0.5` | 视觉模型温度 |
| `LLM_TIMEOUT_SECONDS` | `120` | 请求超时 |
| `LLM_MAX_RETRIES` | `3` | 重试次数 |
| `LLM_MAX_EVENT_CLUSTERS` | `0` | 事件簇智能分析上限；0 = 不限 |
| `LLM_CONTEXT_LENGTH` | `163840` | 上下文窗口 tokens |
| `LLM_RESERVED_TOKENS` | `512` | 预留 tokens |
| `LLM_CHARS_PER_TOKEN` | `4.0` | 字符/token 估算系数 |

### 5.3 MCP / 文件分析 / 数据库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_SERVER_PORT` | `8890` | MCP 服务端口 |
| `MCP_SERVER_HOST` | `localhost` | MCP 绑定地址 |
| `MCP_ALLOWED_PATHS` | 空 | MCP 文件访问白名单（逗号分隔，空 = 不限） |
| `FILE_ANALYSIS_MAX_CONTENT` | `10000` | 送 LLM 的内容长度上限（字符） |
| `FILE_ANALYSIS_MAX_KEYWORDS` | `10` | 关键词提取上限 |
| `FILE_ANALYSIS_MAX_CONTENT_LIMIT` | `50000` | 绝对上限（字符） |
| `DB_OUTPUT_DIR` | `./output` | 数据库输出目录 |
| `DB_NAME` | `forensics.db` | 数据库文件名 |

### 5.4 Neo4j / Graphiti

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEO4J_URI` | `neo4j://127.0.0.1:7687` | 连接串 |
| `NEO4J_USER` | `neo4j` | 用户 |
| `NEO4J_PASSWORD` | `change-me` | 密码（setup.sh 用它设置初始密码） |
| `GRAPHITI_USE_LOCAL_LLM` | `true` | true = 用上面 LLM_TEXT_* 配置 |
| `GRAPHITI_BATCH_SIZE` | `25` | 批大小（防 8096 token 溢出） |
| `GRAPHITI_MAX_RETRIES` | `3` | 重试 |
| `GRAPHITI_GROUP_ID` | `forensics_files` | Graphiti group |
| `GRAPHITI_INCLUDE_FULL_DESC` | `true` | 是否带完整 LLM 描述 |
| `GRAPHITI_MAX_EPISODE_TOKENS` | `3000` | 每集 token 上限 |

### 5.5 Python httpserver（:8090）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PYTHON_HTTP_PORT` | `8090` | 端口 |
| `PYTHON_HTTP_HOST` | `0.0.0.0` | 绑定地址 |
| `CPP_BACKEND_URL` | `http://localhost:8080` | 回连 C++ 的地址 |
| `CPP_STARTUP_REQUEST_TIMEOUT` | `5` | 启动时探测 C++ 超时 |
| `CPP_RECOVERY_TIMEOUT` | `8` | C++ 恢复探测超时 |
| `NEO4J_CONNECT_TIMEOUT` | `5` | Neo4j 连接超时 |
| `NEO4J_QUERY_TIMEOUT` | `5` | Neo4j 查询超时 |
| `OPTIONAL_SERVICE_INIT_TIMEOUT` | `12` | 可选服务（Neo4j/LLM/Redis）初始化超时 |
| `PYTHON_STARTUP_TIMEOUT` | `30` | 启动总预算（超时回滚已初始化项，服务仍以降级模式启动） |
| `PYTHON_CORS_ORIGINS` | `["*"]` | CORS 白名单（JSON 数组） |

### 5.6 C++ HTTP 服务

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HTTP_SERVER_PORT` | `8080` | 端口（`./run.sh` 未设置时用 8666 兜底） |
| `HTTP_SERVER_HOST` | `0.0.0.0` | 绑定地址 |

### 5.7 日志 / 性能 / DLL / OSS

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEBUG_OUTPUT_MODE` | `stdout` | 调试输出：stdout / file / none |
| `DEBUG_LOG_FILE` | `debug.log` | 调试日志文件名 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_FILE` | `forensics.log` | 日志文件名 |
| `THREAD_POOL_SIZE` | `4` | 线程池大小 |
| `MAX_BATCH_SIZE` | `100` | 批处理文件数上限 |
| `LOG_MAX_DISPLAY_FILES` | `20` | 日志展示文件数 |
| `DB_JOURNAL_MODE` | `WAL` | SQLite journal 模式 |
| `DLL_ANALYSIS_ENABLED` | `true` | DLL 分析开关 |
| `DLL_CPP_BACKEND_URL` | `http://localhost:8080` | DLL 分析请求的 C++ 后端 |
| `DLL_ANALYSIS_TIMEOUT` | `30` | DLL 分析超时（秒） |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 空 | OSS 凭证 |
| `OSS_ENDPOINT` | 空 | 如 `oss-cn-hangzhou.aliyuncs.com` |
| `OSS_REGION` | `cn-hangzhou` | OSS 区域 |

### 5.8 分布式 C/S server（:8091）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8091` | C/S 服务端口 |
| `JWT_SECRET_KEY` | `change-me-generate-a-unique-secret` | JWT 签名密钥 |
| `JWT_ALGORITHM` | `HS256` | JWT 算法 |
| `DATABASE_URL` | `postgresql://postgres:change-me@localhost:5432/tracelens` | PostgreSQL 连接串 |
| `DB_CONNECT_TIMEOUT` | `5` | 连接超时 |
| `DB_POOL_TIMEOUT` | `5` | 连接池获取超时 |
| `DB_STARTUP_TIMEOUT` | `30` | 启动等待数据库超时 |

---

## 6. 验证安装

```bash
# 1. 二进制与帮助
./build/forensic_analyzer --version
./build/forensic_analyzer --help

# 2. C++ 单元测试（约 60 个 GTest 目标）
cd build && ctest --output-on-failure

# 3. 一键启动并做健康检查（C++ 失败会硬报错退出）
cd .. && ./run.sh
curl http://localhost:8666/api/system/health   # 端口以 .env HTTP_SERVER_PORT 为准

# 4. 生成测试镜像跑一次 CLI 分析
bash scripts/create_test_image.sh
./build/forensic_analyzer test_image.img
```

---

## 7. 常见安装问题

详细排查见 [Troubleshooting.md](Troubleshooting.md)。最常见的三类：

- **构建缺库**：TSK / Crow / OSS SDK 是源码安装，不在 apt —— 对照 [第 3 节](#3-手动安装依赖) 补装后重跑 cmake。
- **CMake 找不到包**：`build/cmake-configure.log`（setup.sh 生成）里有完整配置日志。
- **Python 大包下载失败**：设 `PIP_PROXY` 后重跑 setup.sh（脚本对大包逐个重试且失败不中断）。

---

**最后更新**: 2026-08-23（以代码为准重写）
