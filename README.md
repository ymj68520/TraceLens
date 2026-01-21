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

## 功能特性

- **多格式支持**: 分析 E01 (EnCase) 和 DD (原始) 磁盘镜像
- **跨平台分析**: 支持 Windows (NTFS, FAT)、Linux (EXT2/3/4) 和 USB 设备文件系统
- **三层数据库架构**:
  1. **原始数据库**: 通过 TSK API 提取的完整文件系统元数据
  2. **事件数据库**: 文件系统事件时间线（创建、修改、访问、删除）
  3. **文件数据库**: 按类型分类的文件（13 个类别）
- **测试镜像生成**: 提供脚本生成包含多种文件类型的测试镜像，支持 SQLite 数据库、图片、PDF、日志、脚本等。
- **LLM 文件分析**: 通过 OpenAI 兼容 API 实现 AI 驱动的文件描述生成
- **知识图谱**: 通过 Graphiti 实现取证数据关联分析
- **全文搜索**: 基于 Xapian 的高性能内容索引和搜索

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
│  │  • 文件提取         │      │  • 批量处理              │  │
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
| 任务列表 | 创建、管理取证分析任务 |
| 时间线 | 文件系统事件可视化 |
| 文件管理 | 按类型浏览和提取文件 |
| AI 描述 | 查看 LLM 生成的文件分析结果 |
| 知识图谱 | Graphiti 实体和关系搜索 |
| 安卓取证 | Android 设备数据分析 |
| 搜索 | 全文内容搜索 |
| 统计 | 文件分布和活动模式分析 |

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ForensicsProject.git
cd ForensicsProject

# Install required dependencies (Ubuntu/Debian)
# libzip-dev libpugixml-dev is optional
sudo apt-get update
sudo apt-get install -y build-essential cmake git libsqlite3-dev libewf-dev libhivex-dev libevtx-dev libolecf-dev libasio-dev nlohmann-json3-dev libboost-system-dev libboost-thread-dev libesedb-dev libxapian-dev libpoppler-cpp-dev antiword libzip-dev libpugixml-dev

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

For detailed analysis and architecture documentation, please refer to [Project Analysis](docs/Project_Analysis.md).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 系统要求

### 依赖项

- **C++ 编译器**: GCC 9+ 或 Clang 10+，支持 C++20 标准
- **CMake**: 3.20 或更高版本
- **The Sleuth Kit**: 4.14.0 版本
- **SQLite3**: 3.30 或更高版本
- **libewf**: 用于 E01 镜像支持
- **libhivex**: 用于 Windows 系统文件分析
- **libevtx**: 用于 Windows 事件日志分析
- **libolecf**: 用于 Office 文件分析
- **libxapian**: 用于全文搜索
- **libpoppler-cpp**: 用于 PDF 文件分析
- **antiword**: 用于 Word 文件分析
- **libzip**: 用于压缩文件分析
- **libpugixml**: 用于 XML 文件分析

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

## 测试镜像生成

项目提供了 `tests/create_android_image.sh` 脚本，用于生成包含多种文件类型的测试镜像，便于验证分析工具的功能。

### 生成的测试镜像内容

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

### 使用方法

运行以下命令生成测试镜像：

```bash
bash tests/create_android_image.sh
```

生成的镜像文件位于 `tests/android_test_gen.img`，可直接用于分析工具测试。

如果系统未安装 `debugfs`，脚本会尝试使用 loop 设备挂载镜像并复制文件（需要 root 权限）。

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
./forensic_analyzer <镜像路径>
```
### 输出结果

工具会生成三个 SQLite 数据库：

1. <镜像名>_raw.db: 原始取证数据
2. <镜像名>_events.db: 文件系统时间线事件
3. <镜像名>_files.db: 按类型分类的文件

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

# 结束
