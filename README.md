# TraceLens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![C++](https://img.shields.io/badge/language-C%2B%2B-00599C.svg)](https://isocpp.org/)

数字取证镜像分析平台：基于 The Sleuth Kit (TSK) 4.14.0 的 C++20 分析内核 + Python FastAPI 智能分析服务 + React Web 前端，并支持分布式客户端/服务端（C/S）部署模式。

## 功能特性

- **镜像与文件系统**：E01 (EnCase) / DD 原始镜像；NTFS、FAT、EXT2/3/4、XFS（`--xfs-mode auto|native|pure`）；加密卷解密（LUKS / BitLocker 等，`--key-dir`/`--key-password`，BitLocker FVEK 需配套 Volatility3 插件）；多分区镜像分析
- **三层数据库产出**：`_raw.db`（文件系统元数据）→ `_events.db`（时间线事件）→ `_files.db`（24 类文件分类 + LLM 分析列 + 场景优先级）
- **平台专项取证**：
  - **Android**：短信/联系人/通话记录、Chrome 历史、已装应用、WiFi；MIUI 备份（`.bak`）解析、微信（SQLCipher 解密，支持 `--backup-password-stdin/-fd` 避免密码进 argv）、QQNT 工件；逻辑取证数据源 `--android-source tsk|dir|zip|miui-backup`
  - **Windows**：注册表、事件日志、Prefetch、Amcache、SRUM、LNK、Jump List、Shimcache、UserAssist、ShellBag、MFT、浏览器（Chromium/Firefox）、USB/RDP/WiFi 等
  - **Linux**：70+ 张 `linux_*` 工件表 —— 系统日志(syslog/journal/auditd)、用户/登录/SSH、Shell 历史、持久化检测、容器(Docker/Podman)、Web 服务器(Apache/Nginx)、防火墙/SELinux/AppArmor、攻击链与异常分析等
- **内存取证**：`--memory-analyze` 调用 Volatility3（进程/网络/Bash 历史/启动信息 → `<镜像>_memory.db`），`scripts/build-vol3-isf.sh` 生成内核 ISF 符号
- **LLM 智能分析**：OpenAI 兼容端点（LM Studio 等）；文件级描述生成（FULL/SMART 模式）、平台工件 LLM 分析（Linux/Windows/Android 各自服务）、事件簇 LLM 分析、视觉模型图像分析；`LLM_MAX_EVENT_CLUSTERS` 等限额可配
- **知识图谱**：Graphiti + Neo4j；任务完成后自动摄取，支持案件级多镜像图谱、实体/关系搜索、File 实体节点与跨任务实体合并
- **取证报告与调查工作台**：CLI Markdown 报告（`--report`）、Python 版分类取证报告（版本化快照、生成任务、叙事版本）、智能报告（intelligence report）、二次调查工作台（事件版本/证据链/结论采纳/终版报告发布与完整性校验）
- **文件雕刻**：基于签名的已删除文件恢复（29 种文件签名）
- **全文搜索**：Xapian 索引与搜索（布尔/通配符/`path:`/`ext:` 过滤），覆盖 100+ 常见文本/代码扩展名
- **文档解析**：PDF（Poppler）、Office → Markdown（Python markitdown 服务，支持批量转换）
- **数据库取证**：SQLite/MySQL/PostgreSQL 数据目录分析（含 InnoDB、PostgreSQL Heap、MySQL Binlog 解析）
- **DLL/可执行文件分析**：PE/ELF 解析、异常检测、威胁评分、依赖分析、签名验证（osslsigncode）
- **TOON 导出**：Token-Oriented Object Notation，面向 LLM 提示的紧凑表格格式
- **对象存储取证**：阿里云 OSS（对象/访问日志/桶分析）
- **分布式 C/S 模式**：PostgreSQL + JWT 的服务端（组织/客户端注册/命令队列/结果回收）与部署在取证机上的 `tracelens_agent` 客户端

## 多服务架构

```
┌────────────────────────────────────────────────────────────────────┐
│                Web 前端 (React 18 + Vite 5, web/)                  │
│   开发模式 http://localhost:3000；生产由 C++ 服务从 web/dist 托管     │
├──────────────┬─────────────────────────────┬───────────────────────┤
│   ↓ /api/*   │        ↓ 8090 专用前缀        │        ↓ /csapi       │
│ ┌────────────┴──────────┐ ┌────────────────┴───┐ ┌─────────────────┐ │
│ │ C++ HTTP 服务           │ │ Python FastAPI     │ │ C/S 服务端        │ │
│ │ forensic_analyzer      │ │ httpserver :8090   │ │ server :8091     │ │
│ │ :8080（HTTP_SERVER_    │ │ • LLM 分析          │ │ • JWT 认证       │ │
│ │  PORT；run.sh 未设置    │ │ • Graphiti 摄取/查询 │ │ • PostgreSQL     │ │
│ │  时回退 8666）          │ │ • 取证报告/调查工作台 │ │ • 命令队列/结果    │ │
│ │ • 取证分析流水线         │ │ • markitdown 转换   │ └────────┬────────┘ │
│ │ • 任务/案件管理          │ │ • 微信关系图         │          ↓ 轮询      │
│ │ • 时间线/统计/导出       │ │ • 多镜像案件分析      │ ┌─────────────────┐ │
│ │ • 文件提取/雕刻/搜索     │ │ • Office 解析       │ │ tracelens_agent  │ │
│ │ • Swagger (/api/docs)  │ │ • 启动分层超时+降级   │ │ (取证机客户端,     │ │
│ └──────────┬─────────────┘ └─────────┬─────────┘ │  本机执行分析)    │ │
│            │ C++ ↔ Python 互调        │           └─────────────────┘ │
│            └──────────┬──────────────┘                               │
│                       ↓                                              │
│   Neo4j :7687（Graphiti 图谱） · Redis（任务持久化，可选）              │
│   OpenAI 兼容 LLM 端点（LLM_BASE_URL）                                 │
└────────────────────────────────────────────────────────────────────┘
```

C++ 与 Python 的调用关系：C++ 通过 `LLMPythonProxy`/`MarkitdownProxy` 调 Python 的 Graphiti 摄取与 markitdown 接口；Python 通过 `CppBackendClient` 回调 C++ 的任务/取证查询接口。三个服务由 `run.sh`/`scripts/start_all_services.sh` 统一拉起，互不 spawn。

### 启动

```bash
# 一键依赖安装（apt 库、Node 22、Neo4j、TSK 4.14.0、Crow、OSS SDK、Python venv 等）
sudo bash setup.sh

# 配置
cp .env.example .env   # 按需修改 LLM_BASE_URL、NEO4J_PASSWORD、JWT_SECRET_KEY 等

# 构建并启动三服务（C++ + Python :8090 + C/S :8091），浏览器访问 C++ 端口即前端
./run.sh               # 支持 --no-build/--no-web/--no-python/--no-cpp/--jobs N/--clean

# 或用 Makefile
make build && make start
```

前端登录页为占位登录（任意账号即可进入，不校验后端）。本地三个服务本身无认证；跨机部署请使用 C/S 模式（JWT）。

### Web 前端页面

| 路由 | 功能 |
|------|------|
| `/dashboard` | 任务统计、五服务依赖健康卡（C++/Python/Neo4j/Redis/LLM） |
| `/tasks` | 创建/管理分析任务（镜像路径、数据源 tsk/dir/zip/miui-backup、场景多选、过滤配置、XFS 模式）、批量任务、组合案件 |
| `/cases` | 多镜像案件管理与跨镜像分析 |
| `/timeline` | 虚拟化时间线、分布图、事件簇调查抽屉、LLM 簇分析 |
| `/files` | 文件浏览/提取/Office 预览/LLM 分析与重分析/Graphiti 摄取/相关性标记 |
| `/android` | MIUI 概览/已装应用/DB 清单、QQNT/微信工件与记录、LLM 汇总 |
| `/memory` | 内存取证结果（进程/网络/Bash 历史/启动信息） |
| `/wechat-graph` | 微信关系力导向图（社区/时间线/人物详情/会话） |
| `/oss` | OSS 对象存储分析 |
| `/search` | Xapian 全文搜索与建索引 |
| `/statistics` | 任务数据库统计 |
| `/knowledge-graph` | Graphiti 图谱搜索/实体/关系/任务图管理 |
| `/case-intelligence` | 智能报告 + 取证报告（版本化）双视图 |
| `/analysis-center` | 分析工作台（证据文件卡、事件簇、簇↔文件关联） |
| `/investigation`、`/investigation/report` | 二次调查工作台、终版报告查看/发布 |
| `/settings` | 语言(en/zh)、暗色主题、LLM/Graphiti 状态 |

注：OSS 页面调用的 `/api/forensics/oss/*` C++ 路由当前未注册（编译但未挂载），页面在服务端未改造前不可用，详见 [docs/architecture/Overview.md](docs/architecture/Overview.md)。

## 命令行用法

```bash
# 全量分析（产出 <镜像>_raw.db / _events.db / _files.db，平台工件并入 _files.db）
./build/forensic_analyzer <镜像路径>

# HTTP 服务（默认端口 8080；.env 的 HTTP_SERVER_PORT 优先）
./build/forensic_analyzer --http-server [port]

# 平台专项
./build/forensic_analyzer <镜像> --android-analyze --android-source tsk|dir|zip|miui-backup
./build/forensic_analyzer <镜像> --windows-analyze
./build/forensic_analyzer <镜像> --linux-analyze
./build/forensic_analyzer <镜像> --wechat-password <密码>          # 微信 SQLCipher 解密
./build/forensic_analyzer <备份> --backup-password-stdin           # MIUI/ADB 备份密码（stdin/fd 更安全）

# 内存取证（Volatility3）
./build/forensic_analyzer mem.lime --memory-analyze --vol-symbols-dir ~/.cache/volatility3/symbols
./scripts/build-vol3-isf.sh <内核版本>                              # 其他内核生成 ISF 符号

# 提取 / 雕刻 / 搜索
./build/forensic_analyzer --database <镜像>_raw.db --extract-file "*.log" --output-dir out/
./build/forensic_analyzer <镜像> --carve --carve-out recovered/
./build/forensic_analyzer --index <目录> && ./build/forensic_analyzer --search "关键词"

# DLL 分析 / 报告 / 文本转储
./build/forensic_analyzer <镜像> --analyze-dlls [--dll-threshold 30]
./build/forensic_analyzer <镜像> --report --report-path report.md
./build/forensic_analyzer <镜像> --dump-text --dump-text-max-size 500M

# 场景过滤（config/filter_profiles/：general_forensics/telecom_fraud/data_breach/virus_intrusion）
./build/forensic_analyzer <镜像> --filter-profile telecom_fraud
```

完整参数见 `./build/forensic_analyzer --help` 或 [src/CommandLineParser.cpp](src/CommandLineParser.cpp)。

### 输出数据库

| 数据库 | 内容 |
|--------|------|
| `<镜像>_raw.db` | files（含 partition_num）、partitions —— TSK 提取的文件系统元数据 |
| `<镜像>_events.db` | events 主表 + 5 张事件类型表 + system_events + event_correlations + 聚合视图 |
| `<镜像>_files.db` | 主 files 表（category、`llm_*`、`scene_*` 列）+ 24 个分类表 + file_descriptions + 场景工件表与视图 |
| `<镜像>_memory.db` | processes、network_connections、bash_history、boot_info、cmdline |
| `<镜像>_dll.db` | PE/ELF 分析工件（亦可在 HTTP 任务模式下写入 windows.db 的 dll_* 表） |

HTTP 任务模式下每个任务的数据库独立存放于 `data/tasks/<task_id>/`：`raw.db`、`events.db`、`files.db`、`android.db`、`windows.db`、`linux.db`、`oss.db` 及 `extracted_files/`、`carved_files/`。

## 测试

```bash
# C++（约 61 个 GTest 目标）
cd build && ctest --output-on-failure        # 或 make test

# Python（python_service/tests/，含 server 与 httpserver 双应用）
make test-python
python_service/scripts/test.py fast          # 档案：focused|investigation|fast|full

# 前端（Vitest + Testing Library）
cd web && npm test

# 隔离环境验收（冒烟/任务/分析员/重启/矩阵）
make acceptance-smoke
```

## 配置

配置集中于仓库根 `.env`（参考 [.env.example](.env.example)，C++ 由 ConfigManager 经 cpp-dotenv 读取，Python 由 pydantic-settings 读取）。关键变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HTTP_SERVER_PORT` | 8080 | C++ 服务端口（run.sh 未设置时回退 8666） |
| `PYTHON_HTTP_PORT` | 8090 | Python 分析服务端口 |
| `PORT` | 8091 | 分布式 C/S 服务端口 |
| `LLM_BASE_URL` / `LLM_TEXT_MODEL` | `http://192.168.31.170:1234` / `qwen/qwen3.6-35b-a3b` | OpenAI 兼容端点与模型 |
| `NEO4J_URI` / `NEO4J_PASSWORD` | `neo4j://127.0.0.1:7687` / change-me | Graphiti 图谱后端 |
| `DATABASE_URL` | `postgresql://...` | C/S 服务端 PostgreSQL |
| `THREAD_POOL_SIZE` | 4 | C++ 分析线程池 |
| `LLM_MAX_EVENT_CLUSTERS` | 0（不限） | 事件簇 LLM 分析上限 |

Graphiti 全功能需 LLM 服务同时加载 `openai/gpt-oss-20b` 与 `text-embedding-nomic-embed-text-v1.5`。

## 系统要求

- Ubuntu/Debian（setup.sh 面向 Ubuntu 24.04）；GCC 11+/Clang 13+（C++20）、CMake ≥ 3.20
- The Sleuth Kit 4.14.0（setup.sh 源码编译安装）、Crow（源码安装）、阿里云 OSS C++ SDK（vendored，`libs/aliyun-oss-cpp-sdk`）
- 取证库：libhivex、libevtx、libesedb、libolecf、libbfio、libewf、libfsntfs；Xapian、Poppler-cpp；SQLite3（可选 SQLCipher）
- Python 3.10+（venv：FastAPI、graphiti-core、neo4j、markitdown[all]、volatility3 等）
- Node.js 22（NVM 安装）、Neo4j 5/2026、PostgreSQL 16（C/S）、Redis（可选，任务队列持久化）
- Windows 构建理论支持（CMake 含 vendored sleuthkit 分支），以 Linux 为主要平台

## 文档

- **[文档索引](docs/README.md)** —— 全部文档入口
- **[快速入门](docs/getting-started/QuickStart.md)** —— 安装与第一次分析
- **[架构总览](docs/architecture/Overview.md)** / **[数据流](docs/architecture/DataFlow.md)** / **[数据库模式](docs/architecture/DatabaseSchema.md)** / **[部署](docs/architecture/Deployment.md)**
- **[C++ REST API](docs/api_reference/CPP_REST_API.md)**（:8080）· **[Python REST API](docs/api_reference/Python_REST_API.md)**（:8090 / :8091）· 运行时 Swagger：`/api/docs`
- **[模块文档索引](docs/modules/README.md)**

## Contributing / License

欢迎提交 PR。本项目基于 MIT License，见 [LICENSE](LICENSE)。
