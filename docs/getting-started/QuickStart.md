# 快速入门指南

## 概述

本指南帮助你在 30 分钟内完成 TraceLens（仓库目录内历史名称为 ForensicsProject，GitHub: ymj68520/TraceLens）的安装、配置和第一次取证分析。

TraceLens 由三个服务组成，`run.sh` 会一并启动：

| 服务 | 说明 | 默认端口 |
|------|------|---------|
| C++ `forensic_analyzer --http-server` | 核心取证分析 + HTTP API + 托管 React 前端（SPA） | `.env` 中 `HTTP_SERVER_PORT`（run.sh 未设置时回退 **8666**） |
| Python `python_service/.venv -m httpserver.main` | FastAPI：LLM 代理、Graphiti 知识图谱、markitdown、报告 | 8090 |
| Python `-m server.main` | 分布式 C/S 服务端（客户端注册/命令下发/结果回收） | 8091（`PORT`） |

**前置要求**：
- Ubuntu 20.04+（推荐 22.04+），需要 `sudo` 权限
- Python 3.10+（venv 由脚本创建）
- 至少 8GB RAM、20GB 可用磁盘空间
- 如需 LLM/知识图谱功能：可访问的 OpenAI 兼容端点（如 LM Studio）和 Neo4j（setup.sh 会装）

---

## 目录

1. [一键安装依赖](#1-一键安装依赖)
2. [配置环境变量](#2-配置环境变量)
3. [启动全部服务](#3-启动全部服务)
4. [在浏览器创建第一个任务](#4-在浏览器创建第一个任务)
5. [CLI 最小示例](#5-cli-最小示例)
6. [常用 Makefile 命令](#6-常用-makefile-命令)
7. [下一步](#7-下一步)
8. [第一次分析之后：看懂任务产出](#8-第一次分析之后看懂任务产出)
9. [五个最常用查询](#9-五个最常用查询)
10. [下一步学习路径图](#10-下一步学习路径图)

---

## 1. 一键安装依赖

```bash
sudo bash setup.sh
```

`setup.sh` 是幂等的（已安装的依赖会跳过），按步骤完成：

1. **NVM + Node.js 22 LTS**（构建 web 前端用）；
2. **apt 系统包**：编译工具链（build-essential/cmake/pkg-config 等）+ 取证库（libhivex/libevtx/libesedb/libolecf/libbfio/libewf/libfsntfs）+ libxapian（全文搜索）+ libpoppler-cpp（PDF）+ 压缩库（zlib/lzma/bz2/zstd）+ libzip + libcurl + ffmpeg + redis-server + libpq/libmysqlclient + libsqlcipher + GTest 等；
3. **Java 21 + Neo4j**：官方 apt 仓库安装，用 `NEO4J_PASSWORD` 环境变量（或 `.env` 中的同名值）设置初始密码并 `systemctl enable --now neo4j`；
4. **The Sleuth Kit 4.14.0**：下载源码编译安装到 `/usr/local`；
5. **Crow**（C++ HTTP 框架，源码安装）；
6. **Google Test**（从 `/usr/src/googletest` 编译）；
7. **阿里云 OSS C++ SDK**：源码编译 `libs/aliyun-oss-cpp-sdk`；
8. **Python venv**：创建 `python_service/.venv`，安装 `httpserver/requirements.txt` + `requirements.txt`，并逐个核对安装大包（markitdown[all]、PyMuPDF==1.27.1、volatility3、graphiti-core、h5py、scipy 等）和 BitLocker FVEK volatility3 插件（源码在 `resources/volatility3-plugins/windows/bitlocker_fvek_scan.py`）；
9. **CMake Release 构建** `build/forensic_analyzer`（并按需 `npm run build` 前端）。

网络不稳定时可设 `PIP_PROXY=http://<代理>:<端口>`（环境变量或 `.env`），脚本会导出为 HTTP_PROXY/HTTPS_PROXY。

完成后按提示验证：

```bash
ls build/forensic_analyzer   # 应存在
build/forensic_analyzer --version
```

---

## 2. 配置环境变量

```bash
cp .env.example .env
```

最小可用配置只需关心（完整变量表见 [Installation.md](Installation.md)）：

```env
# LLM 端点（LM Studio / OpenAI 兼容 API）
LLM_BASE_URL=http://192.168.31.170:1234
LLM_TEXT_MODEL=qwen/qwen3.6-35b-a3b

# Neo4j（知识图谱，setup.sh 安装时应设置过 NEO4J_PASSWORD）
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_PASSWORD=<你设置的密码>

# C++ 服务端口（run.sh 读它；不设置则 run.sh 用 8666）
HTTP_SERVER_PORT=8666
```

> 不配置 LLM/Neo4j 也能跑：分析任务加 `--no-ai` 跳过 AI，Graphiti 服务连接失败会自动降级（disabled），不阻断主流程。

---

## 3. 启动全部服务

```bash
./run.sh
```

`run.sh` 流程：CMake 构建（`-DBUILD_WEB_FRONTEND=OFF`，前端由脚本单独 `npm run build` 并同步到 `build/web/dist`）→ 清理端口残留进程（lsof/kill）→ 前台启动三个服务 → 健康检查（**C++ 服务失败则退出**，Python/C/S 失败仅警告）→ Ctrl+C 一并停止（trap 清理）。

常用参数：

| 参数 | 说明 |
|------|------|
| `--build-only` | 只编译不启动 |
| `--no-build` | 跳过编译直接启动（需已构建） |
| `--no-web` / `--no-python` / `--no-cpp` | 跳过前端构建 / 不启动 Python 与 C/S / 不启动 C++ |
| `--jobs N`（或 `-j N`） | 编译并行数，默认 4 |
| `--clean` | 编译前清理 CMake 产物（保留 logs/data/db） |

服务日志写入 `build/logs/`：

```
build/logs/cpp_server.log        # C++
build/logs/python_service.log    # httpserver :8090
build/logs/cs_server.log         # C/S :8091
```

启动成功后访问地址（以默认 8666 为例）：

```
Web 界面      http://localhost:8666/
C++ API 文档  http://localhost:8666/api/docs
健康检查      http://localhost:8666/api/system/health
Python API   http://localhost:8090/docs
C/S API      http://localhost:8091/docs
```

---

## 4. 在浏览器创建第一个任务

1. 打开 `http://localhost:8666/`（**必须访问 C++ 端口**，React SPA 由 C++ 服务托管）。
2. `/login` 为 mock 登录：任意用户名 + 密码即可。
3. 进入任务创建页，填写：
   - **镜像路径**：磁盘镜像（E01/raw/多分区）或 Android 数据源；
   - **数据源类型**（Android 场景）：`tsk`（镜像，默认）/ `dir`（已解包 data/ 目录）/ `zip`（Image.zip）/ `miui-backup`（小米备份 .bak 目录）；
   - **分析场景**（多选）：`android` / `windows` / `linux` / `server_cloud`；
   - **过滤配置**：`config/filter_profiles/` 下的 profile（general_forensics / telecom_fraud / data_breach / virus_intrusion），默认 general_forensics。
4. 提交后在任务列表/详情页查看进度与结果。

没有真实镜像时可先生成测试镜像（见 [CommonTasks.md](CommonTasks.md)）：

```bash
bash scripts/create_test_image.sh
bash scripts/create_ubuntu_real_image.sh   # 更真实的 Ubuntu 多分区镜像
```

---

## 5. CLI 最小示例

全量分析一个镜像（在仓库根目录）：

```bash
./build/forensic_analyzer test_image.img
```

产出三个 SQLite 数据库（与镜像同目录、以镜像名为前缀）：

```
test_image_raw.db      # 文件系统元数据
test_image_events.db   # 时间线事件
test_image_files.db    # 文件分类 + 平台工件（android/windows/linux 并入此库）
```

用 sqlite3 快速查看：

```bash
sqlite3 test_image_files.db "SELECT COUNT(*) FROM files;"
sqlite3 test_image_raw.db ".tables"
```

其他最常用的 CLI 入口（完整参数见 `--help` 或 [CommonTasks.md](CommonTasks.md)）：

```bash
# 平台工件分析
./build/forensic_analyzer <镜像> --android-analyze --android-source tsk
./build/forensic_analyzer <镜像> --windows-analyze
./build/forensic_analyzer <镜像> --linux-analyze

# 从已生成的库中按名称提取文件
./build/forensic_analyzer --database test_image_raw.db --extract-file "*.log" --output-dir extracted

# 生成 Markdown 报告（无需 AI）
./build/forensic_analyzer <镜像> --report --report-path report.md
```

> 注意：CLI 分析直接在当前工作目录产出 `_raw.db/_events.db/_files.db`；通过 HTTP 任务创建的分析，数据库与结果在 `data/tasks/<task_id>/` 下（`data` 目录相对于可执行文件位置，通常即 `build/data`），可用 `GET /api/tasks/<id>/databases` 查询。

---

## 6. 常用 Makefile 命令

```bash
make build          # 全量构建（cmake Release + --build -j$(nproc)）
make web-frontend   # 只构建 web 前端（npm run build）
make start          # scripts/start_all_services.sh：C++(默认8080) + Python(8090) + C/S(8091)
make cpp            # 仅启动 C++：build/forensic_analyzer --http-server ${HTTP_SERVER_PORT:-8080}
make python         # 仅启动 Python httpserver（8090）
make web-dev        # vite 开发服务器（端口 3000，含 API 代理）
make test           # C++ 测试（= test-cpp：cd build && ctest）
make test-python    # Python 测试（pytest tests/）
make test-all       # C++ + Python
make setup          # setup-venv + setup-web
make clean          # 清理 build/、web/dist 等
make rebuild        # clean + build
make docs           # 打印 API 文档 URL
```

> `./run.sh` 与 `make start` 都能起服务，区别：run.sh 会先构建、默认 C++ 端口 8666、日志集中到 `build/logs/`；make start 走 `scripts/start_all_services.sh`，C++ 端口默认 8080。

---

## 7. 下一步

- [安装指南](Installation.md) — 手动依赖、外部服务、`.env` 全量变量表
- [开发指南](Development.md) — 目录结构、构建、测试、vite 代理
- [常见任务](CommonTasks.md) — 提取、雕刻、全文搜索、Graphiti、C/S 分布式等工作流
- [故障排查](Troubleshooting.md) — 健康检查、日志、端口、依赖降级

---

## 8. 第一次分析之后：看懂任务产出

CLI 分析的产出在与镜像同目录；HTTP 任务的产出在 `data/tasks/<task_id>/`（相对可执行
文件，通常是 `build/data/tasks/<task_id>/`，可用
`curl http://localhost:8666/api/tasks/<task_id>/databases` 查路径）。逐文件导览：

| 文件/目录 | 是什么 | 深入阅读 |
|-----------|--------|----------|
| `raw.db` | 唯一事实来源：TSK 看到的全量文件系统元数据（路径、四时间戳、md5、删除标志）；不可重建 | [RawDB](../schema/RawDB.md) |
| `_filtered.db`（可选） | 过滤画像产出的 raw 子集（仅配置 filter_profile 时出现） | [FileFilter](../modules/cpp/core/FileFilter.md) |
| `events.db` | 时间线事件流：从 raw 四时间戳提取 + 系统叙事事件 | [EventsDB](../schema/EventsDB.md) |
| `files.db` | 文件分类 + LLM 描述列 + 平台工件统一库——最重要的库 | [FilesDB](../schema/FilesDB.md) |
| `android.db` / `windows.db` / `linux.db` | 按所选场景产出的平台工件库（没选则没有） | [AndroidDB](../schema/AndroidDB.md) 等 |
| `<task_id>/extracted_files/` | 提取输出目录（跑过 `/api/forensics/extract` 才有） | [CommonTasks §4](CommonTasks.md) |
| `../tasks.json` | 全部任务的注册表（注意：文件内状态是大写） | [Troubleshooting §13.1](Troubleshooting.md) |

派生关系一句话：**raw.db →（filter→filtered.db）→ events.db + files.db + 平台库**，
单向流动、raw 永不被下游修改（详见 [DatabaseSchema](../architecture/DatabaseSchema.md)）。

HTTP 任务目录的典型长相（`build/data/tasks/<task_id>/`）：

```text
build/data/tasks/task_xxx/
├── raw.db            # TSK 全量（有磁盘管线时才有；逻辑 Android 任务无此库）
├── events.db         # 时间线
├── files.db          # 分类 + LLM + 工件（永远有）
├── android.db        # 选了 android 场景才有（windows.db / linux.db 同理）
└── extracted_files/  # 跑过提取才有；全文索引的默认源路径
```

三条快速判读（产物"健康自检"）：

```bash
# ① 规模感：raw 行数应是 files 行数的超集，events 行数通常远大于文件数
sqlite3 raw.db "SELECT COUNT(*) FROM files;"
sqlite3 files.db "SELECT COUNT(*) FROM files;"
sqlite3 events.db "SELECT COUNT(*) FROM events;"

# ② LLM 是否真跑了：有行 = 跑了（llm_analyze 开且 LLM 可达）
sqlite3 files.db "SELECT COUNT(*) FROM files WHERE llm_analyzed_at IS NOT NULL;"

# ③ 时间范围：任务的"起止时刻"，用于对照案情
sqlite3 events.db "SELECT datetime(MIN(timestamp),'unixepoch'), datetime(MAX(timestamp),'unixepoch') FROM events;"
```

## 9. 五个最常用查询

前两个 curl 对 HTTP 任务，后三个 sqlite3 对任意产物库：

```bash
TID=task_xxx

# ① 任务进度与当前阶段（轮询用）
curl http://localhost:8666/api/tasks/$TID/progress

# ② 任务结果摘要（完成 200 / 未完成 202；含 llm_results 时说明 LLM 证据已落库）
curl http://localhost:8666/api/tasks/$TID/results

# ③ 文件分类总览——最先看的一张分布
sqlite3 files.db "SELECT category, COUNT(*), SUM(size) FROM files GROUP BY category ORDER BY 2 DESC;"

# ④ 时间线按天分布——找"案发日"
sqlite3 events.db "SELECT date(timestamp,'unixepoch'), COUNT(*) FROM events GROUP BY 1 ORDER BY 1;"

# ⑤ 已 LLM 分析的文件清单（files.db，llm_analyzed_at 非空即已分析）
sqlite3 files.db "SELECT path, substr(llm_summary,1,80) FROM files WHERE llm_analyzed_at IS NOT NULL LIMIT 20;"
```

> 各库列名以 [docs/schema/](../schema/) 为准；查不对时先 `.schema <表>` 看真实定义。

## 10. 下一步学习路径图

按角色选一条线读完，比跳读快得多：

```text
所有角色
  └─ 本篇 QuickStart → [Installation](Installation.md)（.env 全量） → [Glossary](../reference/Glossary.md)（术语速查）
        │
        ├─ 取证分析师线
        │    [CommonTasks](CommonTasks.md) §1-8（工作流）→ §13 高级工作流（案件/调查/索引/TOON/审计）
        │    → 教程：[LinuxIntrusion](../tutorials/LinuxIntrusion.md) / [WindowsCase](../tutorials/WindowsCase.md)
        │            / [AndroidWechat](../tutorials/AndroidWechat.md) / [MemoryForensics](../tutorials/MemoryForensics.md)
        │            / [KnowledgeGraphReports](../tutorials/KnowledgeGraphReports.md) / [DistributedCS](../tutorials/DistributedCS.md)
        │
        ├─ 后端开发线
        │    [架构总览](../architecture/Overview.md) → [数据流](../architecture/DataFlow.md) → [数据库模式](../architecture/DatabaseSchema.md)
        │    → API 参考：[C++](../api_reference/CPP_REST_API.md) / [Python](../api_reference/Python_REST_API.md)
        │    → 模块索引 [modules/README](../modules/README.md)（按 src/ 与 python_service/ 对应深入）
        │
        ├─ 前端开发线
        │    [modules/web/Overview](../modules/web/Overview.md)（地图）→ Pages → Services → Store → Hooks
        │    → Components / I18nTheming / Testing（模块七篇按序）
        │
        └─ 运维/部署线
             [ServiceRunbook](../ops/ServiceRunbook.md) → [ExternalServices](../ops/ExternalServices.md)
             → [Troubleshooting](Troubleshooting.md) §1-12（症状速查）→ §13 深挖工具箱
             → 参考：[ServiceContracts](../reference/ServiceContracts.md)（端口/契约）· [Environment](../reference/Environment.md) · [ErrorCodes](../reference/ErrorCodes.md)
```

三条建议：

1. **别跳过 Glossary**——本仓库文档用词高度一致（TOON/episode/派生链/三口径），
   术语表 120 条可在十分钟内扫完，之后所有文档的阅读摩擦都会显著下降；
2. **改代码前先查 [modules/README](../modules/README.md) 的"过时与死代码模块"表**——
   有 5+ 个模块（VisionAnalysis、OSSRoutes 等）看起来活着实际未接线；
3. **排障先查 [Troubleshooting §13.5 已知问题索引表](Troubleshooting.md)**——
   二十余个已记录缺陷覆盖了最常撞见的"诡异现象"，避免重复定位。

---

**最后更新**: 2026-08-24（扩充：高级工作流/深挖工具箱/产出导览）
