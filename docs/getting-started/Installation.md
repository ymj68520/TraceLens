# 安装指南

本文档提供 ForensicsProject 的详细安装步骤，涵盖系统要求、依赖安装、编译配置和常见问题。

---

## 1. 系统要求

### 1.1 最低配置

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| **操作系统** | Ubuntu 20.04 LTS / Debian 11 | Ubuntu 22.04 LTS / Debian 12 |
| **CPU** | 4 核 | 8 核以上 |
| **内存** | 8 GB RAM | 16 GB RAM 以上 |
| **磁盘空间** | 50 GB 可用空间 | 200 GB SSD 以上 |
| **编译器** | GCC 10+ / Clang 12+ | GCC 12+ / Clang 15+ |

### 1.2 支持的平台

- ✅ **Linux**: Ubuntu 20.04+, Debian 11+, CentOS 8+, Rocky Linux 8+
- ⚠️ **Windows**: 支持（需要 WSL2 或 MinGW，见 [Windows 安装](#12-windows-安装)）
- ⚠️ **macOS**: 支持（需要 Homebrew，见 [macOS 安装](#13-macos-安装)）

---

## 2. 依赖安装

### 2.1 核心依赖

| 库名称 | 版本 | 用途 | 许可证 |
|--------|------|------|--------|
| SQLite3 | 3.35+ | 数据库 | Public Domain |
| The Sleuth Kit | 4.14.0 | 磁盘镜像分析 | CPL / IBM |
| libewf | 20130412 | E01 格式支持 | LGPLv3 |
| libhivex | 1.3.20 | Windows 注册表解析 | LGPLv2 |
| libevtx | 20220109 | Windows 事件日志 | LGPLv3 |
| Boost | 1.74+ | C++ 网络和系统库 | BSL-1.0 |
| Crow | 1.0+ | HTTP 服务器框架 | BSD-3-Clause |
| nlohmann/json | 3.11+ | JSON 处理 | MIT |
| Xapian | 1.4.22 | 全文搜索引擎 | GPL-2 |
| Poppler-cpp | 22.0+ | PDF 解析 | GPL-2 |
| libolecf | 20210419 | Office 文档解析 | LGPLv3 |
| libzip | 1.9.2 | ZIP 压缩支持 | BSD-3-Clause |
| pugixml | 1.12+ | XML 解析 | MIT |

### 2.2 Ubuntu/Debian 安装

#### 自动安装脚本

```bash
#!/bin/bash
# install_deps_ubuntu.sh

set -e

echo "=== 安装 ForensicsProject 依赖 ==="

# 更新包管理器
sudo apt-get update

# 安装基础编译工具
sudo apt-get install -y build-essential cmake git pkg-config

# 安装核心库
sudo apt-get install -y \
    libsqlite3-dev \
    libewf-dev \
    libhivex-dev \
    libevtx-dev \
    libesedb-dev \
    libolecf-dev \
    libasio-dev \
    nlohmann-json3-dev

# 安装 Boost 库
sudo apt-get install -y \
    libboost-system-dev \
    libboost-thread-dev \
    libboost-filesystem-dev \
    libboost-program-options-dev

# 安装搜索和分析库
sudo apt-get install -y \
    libxapian-dev \
    libpoppler-cpp-dev \
    libzip-dev \
    libpugixml-dev

# 安装测试框架
sudo apt-get install -y \
    libgtest-dev \
    libgmock-dev

# 安装其他工具
sudo apt-get install -y \
    antiword \
    libcurl4-openssl-dev \
    python3 \
    python3-pip

echo "=== 依赖安装完成 ==="
```

保存并运行：

```bash
chmod +x install_deps_ubuntu.sh
./install_deps_ubuntu.sh
```

#### 手动分步安装

```bash
# 1. 更新系统
sudo apt-get update && sudo apt-get upgrade -y

# 2. 安装编译工具链
sudo apt-get install -y build-essential cmake git pkg-config ccache

# 3. 安装 SQLite3
sudo apt-get install -y libsqlite3-dev sqlite3

# 4. 安装 The Sleuth Kit (从源码编译，见下节)

# 5. 安装 EWF (E01 格式支持)
sudo apt-get install -y libewf-dev

# 6. 安装 Windows 解析库
sudo apt-get install -y libhivex-dev libevtx-dev

# 7. 安装 Boost 和网络库
sudo apt-get install -y \
    libboost-system-dev \
    libboost-thread-dev \
    libboost-filesystem-dev \
    libasio-dev \
    nlohmann-json3-dev

# 8. 安装全文搜索和文档解析
sudo apt-get install -y libxapian-dev libpoppler-cpp-dev antiword

# 9. 安装其他依赖
sudo apt-get install -y libesedb-dev libolecf-dev libzip-dev libpugixml-dev

# 10. 安装测试框架
sudo apt-get install -y libgtest-dev libgmock-dev
```

### 2.3 The Sleuth Kit 编译安装

The Sleuth Kit (TSK) 是核心依赖，必须从源码编译 4.14.0 版本：

```bash
#!/bin/bash
# install_tsk.sh

set -e

TSK_VERSION="4.14.0"
TSK_DIR="sleuthkit-${TSK_VERSION}"

echo "=== 下载并编译 The Sleuth Kit ${TSK_VERSION} ==="

# 下载源码
if [ ! -d "$TSK_DIR" ]; then
    wget https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-${TSK_VERSION}/sleuthkit-${TSK_VERSION}.tar.gz
    tar -xzf sleuthkit-${TSK_VERSION}.tar.gz
    rm sleuthkit-${TSK_VERSION}.tar.gz
fi

cd "$TSK_DIR"

# 配置编译选项
./configure \
    --prefix=/usr/local \
    --enable-afflib=yes \
    --enable-libewf=yes \
    --disable-java

# 编译（使用多核加速）
make -j$(nproc)

# 安装
sudo make install

# 更新动态链接库缓存
sudo ldconfig

echo "=== The Sleuth Kit 安装完成 ==="
tsk_version=$(tsk_loaddb -V 2>&1 | head -n 1)
echo "已安装版本: $tsk_version"
```

验证安装：

```bash
tsk_loaddb -V
# 输出应包含: The Sleuth Kit version 4.14.0
```

### 2.4 Crow 框架安装

Crow 是 C++ HTTP 服务器框架：

```bash
#!/bin/bash
# install_crow.sh

set -e

echo "=== 安装 Crow 框架 ==="

# 克隆源码
if [ ! -d "Crow" ]; then
    git clone https://github.com/CrowCpp/Crow.git
fi

cd Crow
mkdir -p build && cd build

# 配置 CMake（禁用示例和测试以加快编译）
cmake .. \
    -DCROW_BUILD_EXAMPLES=OFF \
    -DCROW_BUILD_TESTS=OFF

# 编译并安装
make -j$(nproc)
sudo make install

echo "=== Crow 安装完成 ==="
```

### 2.5 Python 依赖

Python 服务（FastAPI）的依赖：

```bash
# 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r python_service/httpserver/requirements.txt
```

`requirements.txt` 内容：

```txt
# FastAPI 核心
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pydantic-settings>=2.1.0

# HTTP 客户端
httpx>=0.25.0
aiohttp>=3.9.0

# Neo4j 和 Graphiti
neo4j>=5.14.0
graphiti>=0.3.0

# 工具库
python-dotenv>=1.0.0
python-multipart>=0.0.6

# 可选：开发工具
pytest>=7.4.0
pytest-asyncio>=0.21.0
black>=23.11.0
```

### 2.6 Neo4j 安装（可选）

Neo4j 用于知识图谱功能：

```bash
#!/bin/bash
# install_neo4j.sh

set -e

NEO4J_VERSION="5.14.0"
NEO4J_DIR="neo4j-community-${NEO4J_VERSION}"

echo "=== 安装 Neo4j Community Edition ==="

# 下载
if [ ! -d "$NEO4J_DIR" ]; then
    wget https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz
    tar -xzf neo4j-community-${NEO4J_VERSION}-unix.tar.gz
    rm neo4j-community-${NEO4J_VERSION}-unix.tar.gz
fi

cd "$NEO4J_DIR"

# 配置
sed -i 's/#dbms.default_listen_address=0.0.0.0/dbms.default_listen_address=0.0.0.0/' conf/neo4j.conf
sed -i 's/#dbms.connector.bolt.listen_address=:7687/dbms.connector.bolt.listen_address=0.0.0.0:7687/' conf/neo4j.conf

# 设置初始密码
export NEO4J_AUTH=neo4j/your_password

# 启动服务
./bin/neo4j start

echo "=== Neo4j 安装完成 ==="
echo "访问 http://localhost:7474 进行初始配置"
```

Docker 安装（更简单）：

```bash
docker run -d \
    --name neo4j \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/your_password \
    -v neo4j_data:/data \
    neo4j:5.14-community
```

---

## 3. 编译项目

### 3.1 克隆仓库

```bash
# 克隆主仓库
git clone https://github.com/ymj68520/ForensicsProject.git
cd ForensicsProject

# 或克隆个人 Fork
git clone https://github.com/your-username/ForensicsProject.git
cd ForensicsProject
```

### 3.2 CMake 配置

```bash
# 创建构建目录
mkdir -p build && cd build

# 基础配置（Release 模式）
cmake .. -DCMAKE_BUILD_TYPE=Release

# 开发配置（包含调试符号和测试）
cmake .. -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTS=ON

# 自定义安装路径
cmake .. -DCMAKE_INSTALL_PREFIX=/opt/forensics

# 启用特定功能
cmake .. \
    -DENABLE_XAPIAN=ON \
    -DENABLE_FILE_CARVING=ON \
    -DENABLE_LLM_INTEGRATION=ON \
    -DENABLE_MCP_SERVER=ON
```

**可用 CMake 选项**：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `CMAKE_BUILD_TYPE` | `Release` | 编译类型：Release/Debug/RelWithDebInfo |
| `BUILD_TESTS` | `OFF` | 是否编译测试 |
| `ENABLE_XAPIAN` | `ON` | 启用全文搜索 |
| `ENABLE_FILE_CARVING` | `ON` | 启用文件雕刻 |
| `ENABLE_LLM_INTEGRATION` | `ON` | 启用 LLM 集成 |
| `ENABLE_MCP_SERVER` | `ON` | 启用 MCP 服务器 |
| `CMAKE_CXX_STANDARD` | `20` | C++ 标准 |

### 3.3 编译

```bash
# 使用所有 CPU 核心编译
cmake --build . -j$(nproc)

# 或使用 make 直接编译
make -j$(nproc)

# 只编译特定目标
make forensic_analyzer
make test_file_classifier
```

**编译时间参考**：

| 配置 | CPU 核心数 | 预计时间 |
|------|-----------|---------|
| Release + 所有模块 | 4 核 | 10-15 分钟 |
| Release + 所有模块 | 8 核 | 5-8 分钟 |
| Debug + 测试 | 8 核 | 15-20 分钟 |

### 3.4 安装（可选）

```bash
# 安装到系统目录
sudo cmake --install .

# 或安装到自定义路径
cmake --install . --prefix /opt/forensics
```

---

## 4. 配置

### 4.1 环境变量

创建 `.env` 文件：

```bash
# 复制示例配置
cp .env.example .env

# 编辑配置
nano .env
```

`.env` 配置示例：

```env
# LLM 配置
LLM_BASE_URL=http://localhost:1234
LLM_MODEL=llama-3.2-3b-instruct
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=60

# Neo4j 配置
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
GRAPHITI_GROUP_ID=forensics_project

# 服务端口
CPP_HTTP_PORT=8080
PYTHON_HTTP_PORT=8090
MCP_SERVER_PORT=8890

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=/var/log/forensics/debug.log

# 数据库路径
DATABASE_DIR=./output
```

### 4.2 初始化数据库

```bash
# 创建输出目录
mkdir -p output

# 设置权限
chmod 755 output
```

### 4.3 验证安装

```bash
# 运行可执行文件查看帮助
./build/forensic_analyzer --help

# 运行单元测试
cd build
ctest --output-on-failure

# 启动 HTTP 服务器测试
./forensic_analyzer --http-server 8080
```

访问 http://localhost:8080/health 检查服务状态。

---

## 5. 常见安装问题

### 5.1 依赖问题

**问题**: `error: sqlite3.h: No such file or directory`

**解决**:
```bash
sudo apt-get install -y libsqlite3-dev
```

---

**问题**: `error: TSK library not found`

**解决**:
```bash
# 检查 TSK 是否安装
ldconfig -p | grep libtsk

# 如果没有，重新编译安装 TSK
cd sleuthkit-4.14.0
sudo make install
sudo ldconfig
```

---

**问题**: `error: Cannot find -lboost_system`

**解决**:
```bash
sudo apt-get install -y libboost-system-dev libboost-thread-dev

# 或指定 Boost 路径
cmake .. -DBOOST_ROOT=/usr/local
```

---

### 5.2 编译问题

**问题**: `error: static_assert failed due to requirement 'is_same_v<int, int>'`

**解决**:
```bash
# 确保使用 C++20
cmake .. -DCMAKE_CXX_STANDARD=20
cmake --build . --clean-first
```

---

**问题**: `fatal error: crow.h: No such file or directory`

**解决**:
```bash
# 重新安装 Crow
cd ../Crow/build
sudo make install
```

---

### 5.3 运行时问题

**问题**: `error while loading shared libraries: libtsk.so.13`

**解决**:
```bash
# 添加库路径到 LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# 或永久添加到 ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

# 更新动态链接库缓存
sudo ldconfig
```

---

**问题**: HTTP 服务器无法启动，端口已被占用

**解决**:
```bash
# 检查端口占用
sudo netstat -tulpn | grep 8080

# 终止占用进程
sudo kill <PID>

# 或更换端口
./forensic_analyzer --http-server 8081
```

---

## 6. Docker 安装（推荐）

### 6.1 使用 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  cpp-service:
    build:
      context: .
      dockerfile: docker/Dockerfile.cpp
    ports:
      - "8080:8080"
    volumes:
      - ./output:/output
      - ./evidence:/evidence:ro
    environment:
      - LOG_LEVEL=INFO
    depends_on:
      - neo4j

  python-service:
    build:
      context: .
      dockerfile: docker/Dockerfile.python
    ports:
      - "8090:8090"
    volumes:
      - ./output:/output
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=neo4j_password
    depends_on:
      - cpp-service
      - neo4j

  neo4j:
    image: neo4j:5.14-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/neo4j_password
    volumes:
      - neo4j_data:/data

volumes:
  neo4j_data:
```

启动服务：

```bash
docker-compose up -d
```

### 6.2 单独构建镜像

```bash
# 构建 C++ 服务镜像
docker build -f docker/Dockerfile.cpp -t forensics/cpp-service:latest .

# 构建 Python 服务镜像
docker build -f docker/Dockerfile.python -t forensics/python-service:latest .

# 运行容器
docker run -d -p 8080:8080 forensics/cpp-service:latest
```

---

## 7. Windows 安装

### 7.1 使用 WSL2（推荐）

```powershell
# 启用 WSL2
wsl --install

# 安装 Ubuntu
wsl --install -d Ubuntu-22.04

# 进入 WSL
wsl

# 在 WSL 内执行 Linux 安装步骤
```

### 7.2 原生 Windows 编译

使用 MinGW-w64 或 Visual Studio 2022：

```cmd
# 安装 vcpkg
git clone https://github.com/Microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat

# 安装依赖
.\vcpkg install sqlite3:x64-windows
.\vcpkg install boost-asio:x64-windows
.\vcpkg install nlohmann-json:x64-windows

# 使用 Visual Studio 打开项目
cmake -B build -S . -DCMAKE_TOOLCHAIN_FILE=vcpkg/scripts/buildsystems/vcpkg.cmake
cmake --build build --config Release
```

---

## 8. macOS 安装

```bash
# 安装 Homebrew（如果未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装依赖
brew install cmake git sqlite3 the-sleuth-kit boost
brew install nlohmann-json xapian poppler

# 安装 Crow（需要手动编译）
git clone https://github.com/CrowCpp/Crow.git
cd Crow
mkdir build && cd build
cmake ..
make && sudo make install

# 编译项目
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(sysctl -n hw.ncpu)
```

---

## 9. 验证安装

### 9.1 功能测试

```bash
# 1. 版本检查
./build/forensic_analyzer --version

# 2. 帮助信息
./build/forensic_analyzer --help

# 3. 单元测试
cd build
ctest --output-on-failure

# 4. 简单分析测试
./forensic_analyzer tests/fixtures/test_image.dd

# 5. HTTP 服务测试
./forensic_analyzer --http-server 8080 &
curl http://localhost:8080/health
```

### 9.2 集成测试

```bash
# 运行完整测试套件
./tests/run_integration_tests.sh

# 或单独测试
./tests/test_e01_http.sh
```

---

## 10. 卸载

### 10.1 卸载二进制文件

```bash
# 如果使用 make install
sudo xargs rm < build/install_manifest.txt

# 或手动删除
sudo rm -rf /opt/forensics
sudo rm /usr/local/bin/forensic_analyzer
```

### 10.2 卸载依赖

```bash
# Ubuntu/Debian
sudo apt-get remove -y \
    libsqlite3-dev libewf-dev libhivex-dev libevtx-dev \
    libboost-system-dev libboost-thread-dev \
    libxapian-dev libpoppler-cpp-dev

# 卸载 TSK
cd sleuthkit-4.14.0
sudo make uninstall

# 卸载 Neo4j
docker stop neo4j && docker rm neo4j
docker volume rm neo4j_data
```

---

## 11. 下一步

安装完成后，请参阅：

- **[快速入门指南](QuickStart.md)** - 第一次分析操作
- **[开发环境配置](Development.md)** - 开发工具设置
- **[常见任务](CommonTasks.md)** - 添加分析器、路由等

---

## 相关文档

- **[架构总览](../architecture/Overview.md)** - 系统架构
- **[依赖说明](../architecture/Dependencies.md)** - 详细依赖说明
- **[故障排查](Troubleshooting.md)** - 常见问题解决

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
