# Forensics Project

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![C++](https://img.shields.io/badge/language-C%2B%2B-00599C.svg)](https://isocpp.org/)

A comprehensive digital forensics imaging analysis tool built on The Sleuth Kit.
## Features

- 多格式支持：E01 (EnCase) 和 DD (原始) 磁盘镜像
- 跨平台分析：Windows (NTFS, FAT)、Linux (EXT2/3/4) 和 USB 设备文件系统
- 三层数据库架构：原始数据库、事件数据库、文件数据库
- 测试镜像生成脚本，包含多种文件类型

# 数字取证镜像分析工具

基于 The Sleuth Kit (TSK) 4.14.0 构建的综合性数字取证工具，用于分析磁盘镜像并将取证数据提取到结构化的 SQLite 数据库中。

## 📚 文档

完整的技术文档请参阅 [docs/README.md](docs/README.md)：

- **[快速入门指南](docs/getting-started/QuickStart.md)** - 30 分钟完成安装和第一次分析
- **[架构总览](docs/architecture/Overview.md)** - 系统整体架构和技术栈
- **[C++ REST API](docs/api_reference/CPP_REST_API.md)** - C++ 服务 API 参考（端口 8080）
- **[Python REST API](docs/api_reference/Python_REST_API.md)** - Python 服务 API 参考（端口 8090）

## 功能特性

- **多格式支持**: 分析 E01 (EnCase) 和 DD (原始) 磁盘镜像
- **跨平台分析**: 支持 Windows (NTFS, FAT)、Linux (EXT2/3/4, XFS) 和 USB 设备文件系统
- **三层数据库架构**:
  1. **原始数据库**: 通过 TSK API 提取的完整文件系统元数据
  2. **事件数据库**: 文件系统事件时间线（创建、修改、访问、删除），支持聚类分析和可视化
  3. **文件数据库**: 按类型分类的文件（13 个类别），集成 LLM 分析结果
- **平台专项分析**:
  - **Android 取证**: 分析短信、联系人、通话记录、应用使用、设备信息、媒体文件
  - **Windows 取证**: 解析注册表、事件日志、Prefetch、浏览器历史、Jump Lists、SRUM、Amcache
  - **Linux 取证**: 分析系统日志、用户账户、Shell 历史、认证数据、Cron 任务
- **LLM 智能分析**:
  - 通过 OpenAI 兼容 API 实现 AI 驱动的文件描述生成
  - 支持图像自动检测和视觉模型分析（OCR、场景识别）
  - 案件智能分析：集成报告生成、证据相关性评估
  - 文件重新分析：支持用户提示的深度分析
- **知识图谱**: 通过 Graphiti 实现取证数据关联分析，支持实体搜索和关系发现
- **全文搜索**: 基于 Xapian 的高性能内容索引和搜索，支持 90+ 文件类型
- **文档解析**:
  - PDF 元数据和内容提取（Poppler）
  - Office 文档解析（DOCX, XLSX, PPTX）及 Markdown 导出
  - 支持从压缩文件和数据库中提取文档
- **数据库分析**:
  - SQLite、MySQL、PostgreSQL 数据库解析
  - 支持 InnoDB、PostgreSQL Heap、MySQL Binlog 格式
  - 数据库守护进程支持（PostgreSQL、MySQL）
- **文件雕刻**: 基于签名的已删除文件恢复，支持 30+ 文件类型
- **TOON 导出**: Token-Oriented Object Notation 格式，节省 30-60% LLM 提示 token
- **对象存储**: 集成阿里云 OSS，支持文件上传和管理

## 多服务架构

项目采用三层服务架构：

```
┌─────────────────────────────────────────────────────────────┐
│                    Web 前端 (React + Vite)                   │
│                     http://localhost:5173                    │
├─────────────────────────────────────────────────────────────┤
│         ↓                                      ↓            │
│  ┌─────────────────────┐      ┌─────────────────────────┐  │
│  │  C++ HTTP 服务       │      │   Python FastAPI 服务    │  │
│  │  端口: 8080          │      │   端口: 8090             │  │
│  │                     │      │                         │  │
│  │  • 取证分析核心      │      │  • LLM 分析服务          │  │
│  │  • 任务管理         │      │  • Graphiti 知识图谱      │  │
│  │  • 数据库操作       │      │  • 数据库导出 (TOON/JSON) │  │
│  │  • 文件提取         │      │  • Office 文档解析       │  │
│  │  • 文件雕刻         │      │  • 批量处理              │  │
│  │  • 全文搜索         │      │  • 配置管理              │  │
│  │  • TOON 导出        │      │  • Swagger 文档生成      │  │
│  │                     │      │  • C++ 后端代理          │  │
│  └─────────────────────┘      └─────────────────────────┘  │
│                                          ↓                  │
│                              ┌─────────────────────┐        │
│                              │   Neo4j (可选)       │        │
│                              │   端口: 7687         │        │
│                              └─────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### 启动所有服务

```bash
# 使用启动脚本
./scripts/start_services.sh

# 或手动启动
# 终端 1: C++ 服务
./build/forensic_analyzer --http-server 8080

# 终端 2: Python 服务
cd python_service && python -m httpserver.main

# 终端 3: Web 前端 (开发模式)
cd web && npm run dev
```

### Web 前端功能

| 页面 | 功能 |
|------|------|
| 仪表盘 | 系统概览和快速操作入口 |
| 任务列表 | 创建、管理取证分析任务，支持任务删除 |
| 时间线 | 文件系统事件可视化，支持聚类、分布图、分页、详细事件视图 |
| 文件管理 | 按类型浏览和提取文件，支持 LLM 分析和文件重新分析 |
| AI 描述 | 查看 LLM 生成的文件分析结果，支持图像视觉分析 |
| 案件智能 | 集成 LLM 分析、报告生成、证据相关性管理 |
| 知识图谱 | Graphiti 实体和关系搜索，支持任务隔离的知识图谱实例 |
| 安卓取证 | Android 设备数据分析，包含应用数据库详细信息 |
| Windows 取证 | Windows 系统 artifacts 分析 |
| Linux 取证 | Linux 系统日志和用户活动分析 |
| 搜索 | 全文内容搜索 |
| 统计 | 文件分布和活动模式分析 |
| 系统 | 系统监控和终端访问 |
| API 文档 | Swagger/OpenAPI 自动生成的 API 文档 |

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ForensicsProject.git
cd ForensicsProject

# Install required dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y build-essential cmake git pkg-config
sudo apt-get install -y libsqlite3-dev libewf-dev
sudo apt-get install -y libhivex-dev libevtx-dev libasio-dev
sudo apt-get install -y nlohmann-json3-dev libboost-system-dev libboost-thread-dev
sudo apt-get install -y libesedb-dev libolecf-dev libxapian-dev
sudo apt-get install -y libpoppler-cpp-dev antiword
sudo apt-get install -y libzip-dev libpugixml-dev libxlsxwriter-dev
sudo apt-get install -y libgtest-dev libgmock-dev
sudo apt-get install -y libcurl4-openssl-dev

# Python service dependencies (optional, for LLM and knowledge graph)
# Python 3.10+, pip, and requirements.txt packages

# Build the project
mkdir build && cd build
cmake ..
make -j$(nproc)
```

## Usage

```bash
./forensic_analyzer <image_file_path>
```

### Output
The tool generates three SQLite databases:
- **_raw.db**: Complete file system metadata
- **_events.db**: Timeline of file system events (created, modified, accessed)
- **_files.db**: Files categorized by type (images, documents, etc.)

## Documentation

For detailed documentation, please refer to:
- **API Reference**: [docs/API_REFERENCE.md](docs/API_REFERENCE.md) - Complete REST API documentation
- **API Usage Guide**: [docs/API_USAGE_GUIDE.md](docs/API_USAGE_GUIDE.md) - API usage examples and workflows
- **Project Analysis**: [docs/Project_Analysis.md](docs/Project_Analysis.md) - Detailed module analysis and design
- **Architecture**: [docs/architecture.md](docs/architecture.md) - Module relationships and deployment architecture
- **Classification Analysis**: [docs/Classification_Analysis.md](docs/Classification_Analysis.md) - File categorization logic
- **Module READMEs**: Located in individual source directories under `src/*/README.md`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 系统要求

### 依赖项

**核心依赖**:
- **C++ 编译器**: GCC 9+ 或 Clang 10+，支持 C++20 标准
- **CMake**: 3.20 或更高版本
- **The Sleuth Kit**: 4.14.0 版本
- **SQLite3**: 3.30 或更高版本

**格式支持**:
- **libewf**: 用于 E01 镜像支持
- **libzip**: 用于压缩文件分析
- **libpugixml**: 用于 XML 文件分析

**Windows 取证**:
- **libhivex**: 用于 Windows 注册表分析
- **libevtx**: 用于 Windows 事件日志分析
- **libolecf**: 用于 OLE 结构化存储（Legacy Office）
- **libesedb**: 用于 ESE 数据库（Windows 搜索、Active Directory）

**文档分析**:
- **libpoppler-cpp**: 用于 PDF 文件分析
- **antiword**: 用于 Word (DOC) 文件分析
- **libxlsxwriter**: 用于 Excel 文件生成

**网络和 HTTP**:
- **libasio**: 异步 I/O 和网络
- **Crow**: C++ HTTP 框架（需要单独编译安装）
- **nlohmann-json**: JSON 解析和生成
- **Boost**: System 和 Thread 库

**搜索和索引**:
- **libxapian**: 用于全文搜索

**测试**:
- **libgtest/libgmock**: Google 测试框架

**可选（Python 服务）**:
- **Python 3.10+**
- **FastAPI**: Python Web 框架
- **Graphiti**: 知识图谱库
- **Neo4j**: 图数据库（用于知识图谱后端）
- **OpenAI SDK**: 或其他兼容的 LLM API

### Ubuntu/Debian 安装

```bash
# 安装编译工具
sudo apt-get update
sudo apt-get install -y build-essential cmake git

# (可选) 安装 Google Test
sudo apt-get install -y libgtest-dev libgmock-dev

# 安装 SQLite3
sudo apt-get install -y libsqlite3-dev sqlite3

# 安装 libewf 以支持 E01 格式
sudo apt-get install -y libewf-dev

# 安装 Windows 系统文件分析支持
sudo apt-get install -y libhivex-dev libevtx-dev libevtx-utils
sudo apt-get install -y libolecf-dev libolecf-utils

# 安装 Xapian 以支持全文搜索
sudo apt-get install -y libxapian-dev

# 安装 Poppler 以支持 PDF 解析
sudo apt-get install -y libpoppler-cpp-dev

# 安装 antiword 以支持 doc 解析
sudo apt-get install -y antiword

# 安装 libxlsxwriter 以支持 Excel 文件分析
sudo apt-get install -y libxlsxwriter-dev

# 安装 DuckX 依赖, 可选，DuckX已经自带
sudo apt-get install -y libzip-dev libpugixml-dev
# 安装 DuckX 1.2.2
git clone https://github.com/amiremohamadi/DuckX.git
cd DuckX
mkdir build && cd build
cmake ..
cmake --build .
sudo make install

# 安装 HTTP 服务支持
sudo apt-get install libasio-dev nlohmann-json3-dev
sudo apt-get install libboost-system-dev libboost-thread-dev libesedb-dev
git clone https://github.com/CrowCpp/Crow.git
cd Crow && sudo mkdir build && cd build
cmake .. -DCROW_BUILD_EXAMPLES=OFF -DCROW_BUILD_TESTS=OFF
sudo make install

# 安装 The Sleuth Kit 4.14.0
wget https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.14.0/sleuthkit-4.14.0.tar.gz
tar -xzf sleuthkit-4.14.0.tar.gz
cd sleuthkit-4.14.0
./configure
make
sudo make install
sudo ldconfig

# 安装 google test 框架
sudo apt install libgtest-dev libgmock-dev
# 编译并安装 gtest/gmock 静态库
cd /usr/src/googletest        # 24.04 是这个目录，旧版本可能是 /usr/src/gtest
sudo cmake -B build -S .      # 生成 Makefile
sudo cmake --build build      # 编译
sudo cmake --install build    # 把 .a 装到 /usr/local/lib，把头文件放到 /usr/local/include
```

## 测试

### 单元测试

项目包含全面的 GTest 单元测试套件：

```bash
cd build

# 运行所有测试
ctest --output-on-failure

# 运行特定测试套件
./test_file_classifier      # 文件分类测试
./test_audit_log_gtest      # 审计日志测试
./test_file_carving         # 文件雕刻测试
./test_fulltext_search_gtest # 全文搜索测试
./test_llm_integration      # LLM 集成测试
./test_pdf_analyzer         # PDF 分析测试
./test_office_analyzer      # Office 文档测试
./test_toon_exporter        # TOON 导出测试
```

### Python 测试

```bash
cd python_service
pytest tests/ -v
```

### 集成测试

```bash
# Android 分析测试
bash tests/create_android_image.sh

# HTTP 服务器测试
bash tests/test_e01_http.sh
```

### 测试镜像生成

项目提供了 `tests/create_android_image.sh` 脚本，用于生成包含多种文件类型的测试镜像，便于验证分析工具的功能。

#### 生成的测试镜像内容

- **SQLite 数据库**: 包含短信 (SMS) 和 WhatsApp 消息的示例数据库
- **多种文件类型**:
  - 文本文件 (txt, json, csv)
  - 图片文件 (jpg, png)
  - PDF 文件
  - 可执行脚本
  - 日志文件
  - 配置文件 (ini)
  - 大文件 (4MB 二进制文件)
  - 隐藏文件

#### 使用方法

运行以下命令生成测试镜像：

```bash
bash tests/create_android_image.sh
```

生成的镜像文件位于 `tests/android_test_gen.img`，可直接用于分析工具测试。

如果系统未安装 `debugfs`，脚本会尝试使用 loop 设备挂载镜像并复制文件（需要 root 权限）。

## 配置

项目使用 `.env` 文件进行集中配置管理。创建 `.env` 文件（参考 `.env.example`）：

```env
# 数据库配置
DATABASE_DIR=./data
SQLITE_JOURNAL_MODE=WAL

# LLM 配置
LLM_BASE_URL=http://localhost:1234
LLM_MODEL=local-model
LLM_MAX_TOKENS=2000
LLM_TIMEOUT=30

# Neo4j 配置（知识图谱）
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
GRAPHITI_GROUP_ID=forensics_project

# 全文搜索配置
XAPIAN_INDEX_DIR=./xapian_index

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=forensic_analyzer.log

# HTTP 服务配置
CPP_SERVER_PORT=8080
PYTHON_SERVER_PORT=8090

# 对象存储（可选）
OSS_ENABLED=false
OSS_ACCESS_KEY_ID=your_access_key
OSS_ACCESS_KEY_SECRET=your_secret
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET_NAME=your_bucket
```

# 详细描述

## Windows 安装

1. 安装 Visual Studio 2019 或更高版本（包含 C++ 支持）
2. 安装 vcpkg 包管理器
3. 通过 vcpkg 安装依赖项：

```powershell
vcpkg install sqlite3:x64-windows
vcpkg install sleuthkit:x64-windows
```

## 编译项目

```powershell
# 克隆或创建项目目录
mkdir forensic_analyzer
cd forensic_analyzer

# 创建构建目录
mkdir build
cd build

# 使用 CMake 配置
cmake ..

# 编译
cmake --build . -j$(nproc)

# 安装（可选）
sudo cmake --install .
```
## 使用方法

### 基本用法

```bash
# 分析磁盘镜像
./forensic_analyzer <镜像路径>

# 指定输出目录
./forensic_analyzer <镜像路径> --db-dir /path/to/output

# 启动 HTTP 服务器
./forensic_analyzer --http-server 8080

# 文件提取
./forensic_analyzer --database <镜像路径>_raw.db --extract-file "*.log"
./forensic_analyzer --database <镜像路径>_raw.db --extract-all --output-dir extracted/

# 全文搜索
./forensic_analyzer --index /path/to/extracted_files
./forensic_analyzer --search "keyword" --db-dir /path/to/databases

# 文件雕刻（恢复已删除文件）
./forensic_analyzer <镜像路径> --carve --carve-out recovered_files/

# 平台专项分析
./forensic_analyzer <镜像路径> --android-analyze
./forensic_analyzer <镜像路径> --windows-analyze
./forensic_analyzer <镜像路径> --linux-analyze

# XFS 文件系统分析（选择解析模式）
sudo ./forensic_analyzer <镜像路径> --xfs-mode native    # 本地挂载（完整支持）
./forensic_analyzer <镜像路径> --xfs-mode pure          # 纯解析（跨平台）
```

### 输出结果

工具会生成多个 SQLite 数据库：

1. **<镜像名>_raw.db**: 原始取证数据（文件系统元数据）
2. **<镜像名>_events.db**: 文件系统时间线事件
3. **<镜像名>_files.db**: 按类型分类的文件（含 LLM 分析结果）
4. **<镜像名>_android.db**: Android 专项分析数据（可选）
5. **<镜像名>_windows.db**: Windows 专项分析数据（可选）
6. **<镜像名>_linux.db**: Linux 专项分析数据（可选）

## 数据库架构

### 原始数据库 (_raw.db)

#### files 表

存储文件系统的完整元数据

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inode INTEGER,              -- 索引节点号
    name TEXT,                  -- 文件名
    path TEXT,                  -- 完整路径
    size INTEGER,               -- 文件大小（字节）
    atime INTEGER,              -- 访问时间（Unix 时间戳）
    mtime INTEGER,              -- 修改时间
    ctime INTEGER,              -- 状态改变时间
    crtime INTEGER,             -- 创建时间（出生时间）
    type TEXT,                  -- 文件类型：REG（普通文件）、DIR（目录）、LNK（链接）
    md5 TEXT,                   -- MD5 哈希值
    is_deleted INTEGER,         -- 是否已删除（0=否，1=是）
    is_allocated INTEGER,       -- 是否已分配（0=否，1=是）
    permissions TEXT,           -- 权限（八进制）
    uid INTEGER,                -- 用户 ID
    gid INTEGER                 -- 组 ID
);
```

索引:

- idx_files_inode: 索引节点号索引
- idx_files_path: 路径索引
- idx_files_type: 文件类型索引
- idx_files_deleted: 删除状态索引

#### partitions 表

存储分区信息。

```sql
CREATE TABLE partitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    partition_num INTEGER,      -- 分区编号
    start_offset INTEGER,       -- 起始偏移量
    length INTEGER,             -- 分区长度
    description TEXT,           -- 描述
    fs_type TEXT               -- 文件系统类型
);
```

#### 事件数据库 (_events.db)

1. events表,主事件表，包含所有文件系统事件。

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,     -- 事件时间戳
    event_type TEXT NOT NULL,       -- 事件类型
    file_path TEXT NOT NULL,        -- 文件路径
    inode INTEGER,                  -- 索引节点号
    description TEXT,               -- 事件描述
    file_size INTEGER,              -- 文件大小
    file_type TEXT                  -- 文件类型
);
```
事件类型:
- CREATED: 文件创建
- MODIFIED: 文件内容修改
- ACCESSED: 文件访问/读取
- CHANGED: 元数据更改（权限、所有权等）
- DELETED: 文件删除



2. 专用事件表:

- creation_events: 文件创建事件
- modification_events: 文件修改事件
- access_events: 文件访问事件
- change_events: 元数据更改事件
- deletion_events: 文件删除事件

每个表的结构：
```sql
CREATE TABLE <event_type>_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    inode INTEGER,
    file_size INTEGER,
    file_type TEXT
);
```



3. 视图:
	1, timeline 视图: 按时间顺序显示所有事件:
```sql
CREATE VIEW timeline AS
SELECT 
    datetime(timestamp, 'unixepoch') as event_time,
    event_type,
    file_path,
    inode,
    file_size,
    file_type,
    description
FROM events
ORDER BY timestamp DESC;
```

	2, event_statistics 视图: 事件统计摘要
```sql
CREATE VIEW event_statistics AS
SELECT 
    event_type,
    COUNT(*) as event_count,
    MIN(timestamp) as first_event,
    MAX(timestamp) as last_event,
    datetime(MIN(timestamp), 'unixepoch') as first_event_time,
    datetime(MAX(timestamp), 'unixepoch') as last_event_time
FROM events
GROUP BY event_type;
```

	3, hourly_activity 视图: 按小时统计的活动
```sql
CREATE VIEW hourly_activity AS
SELECT 
    strftime('%Y-%m-%d %H:00:00', datetime(timestamp, 'unixepoch')) as hour,
    event_type,
    COUNT(*) as event_count
FROM events
GROUP BY hour, event_type
ORDER BY hour DESC;
```

### 文件数据库 (_files.db)

#### 文件分类表（13种类型）

1. images (图片文件)
   - 扩展名: jpg, jpeg, png, gif, bmp, tiff, svg, webp, raw, cr2, nef, psd, ai, heic 等
   - 用途: 照片、图形、设计文件

2. videos (视频文件)

   - 扩展名: mp4, avi, mkv, mov, wmv, flv, webm, mpg, mpeg, 3gp 等

   - 用途: 视频录像、电影、监控录像


3. audio_files (音频文件)

- 扩展名: mp3, wav, flac, aac, ogg, wma, m4a, opus 等
- 用途: 音乐、录音、播客

4. documents (文档文件)
    - 扩展名: pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, rtf, odt 等
    - 用途: 办公文档、报告、表格、演示文稿

5. archives (压缩文件)
    - 扩展名: zip, rar, 7z, tar, gz, bz2, iso, apk, jar 等
    - 用途: 压缩包、安装包、备份文件

6. executables (可执行文件)
    - 扩展名: exe, dll, so, dylib, app, bin, sh, bat, cmd, ps1 等
    - 用途: 程序、脚本、系统库

7. databases (数据库文件)
    - 扩展名: db, sqlite, sqlite3, mdb, accdb, sql, dbf 等
    - 用途: 数据库文件、备份

8. source_code (源代码文件)
    - 扩展名: c, cpp, java, py, js, php, go, rs, swift, html, css 等
    - 用途: 程序源代码、脚本

9. web_files (网页文件)
    - 扩展名: html, htm, css, xml, json, yaml, jsp, asp 等
    - 用途: 网页、配置文件

10. email_files (邮件文件)
    - 扩展名: eml, msg, pst, ost, mbox, emlx 等
    - 用途: 电子邮件、邮箱数据

11. system_files (系统文件)
    - 扩展名: ini, cfg, conf, reg, dat, tmp, log, cache 等
    - 用途: 系统配置、日志、临时文件

12. encrypted_files (加密文件)
     - 扩展名: gpg, pgp, aes, encrypted, p12, pfx, pem, key 等
     - 用途: 加密文件、证书、密钥

13. unknown_files (未知文件)
     - 无法识别扩展名或未分类的文件



表结构(每个分类表都有相同的结构):
```sql
CREATE TABLE <category> (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inode INTEGER,              -- 索引节点号
    name TEXT,                  -- 文件名
    path TEXT,                  -- 完整路径
    size INTEGER,               -- 文件大小
    extension TEXT,             -- 文件扩展名
    mtime INTEGER,              -- 修改时间
    ctime INTEGER,              -- 状态改变时间
    is_deleted INTEGER,         -- 是否已删除
    md5 TEXT                    -- MD5 哈希值
);
```



索引:

- idx_<category>_path: 路径索引
- idx_<category>_extension: 扩展名索引
- idx_<category>_size: 大小索引



视图

1. file_summary视图: 文件分类统计摘要

```sql
CREATE VIEW file_summary AS
SELECT 
    'Images' as category,
    COUNT(*) as file_count,
    SUM(size) as total_size,
    ROUND(AVG(size), 2) as avg_size,
    MAX(size) as max_size
FROM images
UNION ALL
SELECT 'Videos', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM videos
-- ... 其他类别
```

2. extension_statistics 视图: 扩展名统计

```sql
CREATE VIEW extension_statistics AS
SELECT 
    extension, 
    COUNT(*) as count, 
    SUM(size) as total_size
FROM (
    SELECT extension, size FROM images
    UNION ALL
    SELECT extension, size FROM videos
    -- ... 其他类别
)
GROUP BY extension
ORDER BY count DESC;
```

3. deleted_files 视图: 所有已删除的文件

```sql
CREATE VIEW deleted_files AS
SELECT 
    'Images' as category, 
    name, 
    path, 
    size, 
    extension 
FROM images 
WHERE is_deleted = 1
UNION ALL
SELECT 'Videos', name, path, size, extension FROM videos WHERE is_deleted = 1
-- ... 其他类别
```

## 最新功能更新

### 2024-2025 年度主要更新

**智能分析增强**:
- 案件智能分析系统：集成 LLM 报告生成、证据相关性评估
- 文件重新分析功能：支持用户提示的深度 LLM 分析
- 图像自动检测和视觉模型分析（OCR、场景识别）
- 可配置的嵌入模型用于知识图谱

**时间线改进**:
- 事件聚类分析和可视化
- 活动分布图表
- 分页浏览和详细事件视图
- UI 本地化支持

**文档处理**:
- 模块化文档提取架构
- Office 文档（DOCX, XLSX, PPTX）解析和 Markdown 导出
- 从压缩文件和数据库中提取文档
- PostgreSQL 和 MySQL 守护进程支持

**知识图谱**:
- 任务隔离的知识图谱实例
- 延迟加载和过滤选项
- 实体和关系搜索 API

**系统架构**:
- 集中式配置管理（ConfigManager + .env）
- 路径管理器（PathManager）
- Python FastAPI 服务集成
- Swagger/OpenAPI 自动文档生成

**前端 UI**:
- 黑暗模式支持
- WebSocket 实时更新
- Toast 通知系统
- 响应式侧边栏
- 登录页面

**后端增强**:
- Aliyun OSS C++ SDK 集成
- TOON 导出功能（节省 30-60% LLM token）
- 数据库分析器（SQLite, MySQL, PostgreSQL）
- 连接池和标准化 API 响应

# 结束
