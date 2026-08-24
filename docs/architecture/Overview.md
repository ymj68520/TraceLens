# 理解 TraceLens：架构总览

> 这是一份"讲道理"的架构文档：先建立心智模型，再解释每个设计为什么是这个样子。清单式的端口/端点/变量表在 [Deployment.md](./Deployment.md)、[API 参考](../api_reference/CPP_REST_API.md) 和 [.env.example](../../.env.example) 里，这里不重复。

## 1. 五分钟心智模型

TraceLens 回答的问题是：**给一块磁盘镜像（或内存镜像、Android 备份），告诉我里面发生过什么。**

它的做法可以概括为一句话：**把"字节"逐层提炼成"证据"**。整个系统就是一条提炼流水线，每一步把数据变得更有语义、更接近"人能直接使用的信息"：

```
磁盘镜像（字节流）
   │  ImageAnalyzer：问文件系统"这里有哪些文件、什么时间戳"
   ▼
raw.db —— 忠实记录文件系统元数据，一个不多一个不少
   │  EventExtractor：把每条元数据的四个时间戳翻译成"发生过的事件"
   ▼
events.db —— 时间线：什么时间、什么文件、发生了什么
   │  FileClassifier：把几十万个文件按类型和取证价值分拣
   ▼
files.db —— 分拣后的文件清单（24 类），并标注哪些值得深挖
   │  平台分析器：用操作系统专属知识解读分拣出的文件
   ▼
android.db / windows.db / linux.db —— "这是一条微信消息"、"这是一次 SSH 登录"
   │  LLM + Graphiti：把结构化工件变成自然语言描述和知识图谱
   ▼
llm_* 列、file_descriptions、Neo4j 图谱 —— 调查员可以直接消费的结论层
```

理解了这条提炼链，几乎所有模块的位置就都清楚了：每个模块就是其中一层（或一层里的一个平台分支）。

**一个容易忽略的要点**：这条链是单向的，每一层只依赖上一层的产出（raw.db 是唯一事实来源，events/files 都从它派生）。这意味着任何一层出了问题，都可以只重跑那一层，而不必重新解析镜像——这是整个系统最重要的工程性质。

## 2. 为什么是三个服务加一个代理

TraceLens 跑起来是三个进程，很多设计只有知道"为什么分开"才能理解：

**C++ 服务（`forensic_analyzer`，默认 :8080）**负责一切"重"的活：解析镜像、遍历文件系统、雕刻、建索引。这些能力的生态（The Sleuth Kit、hivex、libevtx、Xapian）全是 C/C++ 库，性能也要求原生代码。它同时是任务的管理者——HTTP 任务队列、线程池、进度跟踪都在这里。可以说它是"发动机 + 变速箱"。

**Python 服务（`httpserver`，:8090）**负责一切"粘合 + AI 生态"的活：Graphiti 知识图谱、markitdown 文档转换、取证报告生成、调查工作台、微信关系图。这些能力在 Python 生态里有一等公民的支持，用 C++ 重写既不现实也无必要。它是"智能驾驶舱"。

**分布式 C/S 服务端（`server`，:8091）**是另一种部署形态的组件：当你有多台取证机、需要集中下发命令和回收结果时才用。它带着 PostgreSQL 和 JWT 认证——这两样正是"多机、多用户"场景才需要的东西，本地单机模式完全用不到。

**`tracelens_agent`** 跑在取证机上，轮询 C/S 服务端的命令队列，在本地调 `forensic_analyzer` 干活，再把结果传回去。它是 C/S 模式下"发动机的遥控启动器"。

三个服务**互相不 spawn**，都由 `run.sh` / `scripts/start_all_services.sh` 拉起，彼此只通过 HTTP 说话：

- C++ → Python：任务完成后，C++ 通过 `LLMPythonProxy` 异步触发 Graphiti 摄取；文档转换走 `MarkitdownProxy`。
- Python → C++：Python 通过 `CppBackendService` 回查任务、读时间线和文件数据。注意方向性——**Python 把 C++ 当硬依赖**（C++ 不在则 readiness=false），但 C++ 离了 Python 照样完成分析（只是没有图谱和报告）。

```
浏览器 ──┬── /api/*（绝大多数）──────────► C++ :8080（也托管前端静态文件）
         ├── /api/llm|graphiti|reports|... ► Python :8090（智能层）
         └── /csapi ────────────────────► C/S :8091 ──轮询── tracelens_agent
```

为什么不用一个进程？因为两边的依赖树几乎不交叉（TSK vs graphiti-core），放一起会让构建、部署、重启互相拖累；Python 侧重启升级时 C++ 的长任务分析不受影响，这在实际使用中很重要。

## 3. 两种运行模式：同一套分析器，两个编排者

同样的分析器（ImageAnalyzer、EventExtractor、FileClassifier、各平台分析器……）有两个入口：

- **CLI 模式**（`./forensic_analyzer 镜像` → `AnalysisOrchestrator`）：同步跑完就退出，适合脚本化批处理。输出数据库放在镜像旁边（`<镜像>_raw.db` 等），平台工件**并入** `<镜像>_files.db`。
- **HTTP 任务模式**（`POST /api/tasks` → `TaskManager` → `TaskManagerAnalysis.cpp`）：异步任务，有线程池、进度、取消、看门狗，是 Web 前端使用的模式。每个任务的所有产出隔离在 `data/tasks/<task_id>/` 一個目录里（raw.db、events.db、files.db、各平台库、提取文件），平台工件写**独立**的 `android.db` / `windows.db` / `linux.db` / `oss.db`。

为什么 HTTP 模式要按任务隔离目录？因为并发任务互不干扰、删除任务就是删目录、上层服务（Python 的 task_store）可以用"精确匹配任务目录"的安全方式定位数据——这是后来一系列数据边界加固（见 docs/hardening/）的基础。

任务内部是一条八阶段流水线（`INITIALIZING → IMAGE_ANALYSIS → EVENT_EXTRACTION → FILE_CLASSIFICATION → LLM_ANALYSIS → PLATFORM_ANALYSIS → FILE_CARVING → FINALIZING`），各阶段有权重（5/25/10/15/20/20/3/2，见 `TaskManager.cpp:545`）用于折算总进度百分比。场景（ANDROID/WINDOWS/LINUX/SERVER_CLOUD）不必手工指定——`SceneDetector` 会先看一眼 raw.db 里的路径特征自动判断，这也是为什么创建任务时"场景"只是个可选的多选。

完整的一次任务生命周期走读见 [DataFlow.md](./DataFlow.md)——建议接下来读它。

## 4. 数据库为什么分这么多层

一个任务产出七八个 SQLite 文件，不是过度设计，每一层有明确的"读者"：

| 库 | 谁写 | 谁读 | 它存在的理由 |
|----|------|------|-------------|
| `raw.db` | ImageAnalyzer | 所有下游阶段、Graphiti 摄取 | **唯一事实来源**。忠实镜像文件系统元数据，保证任何结论可以回溯到原始证据 |
| `events.db` | EventExtractor | 时间线页/前端、事件簇分析 | 把元数据变成"叙事单位"（事件），支撑按时间调查 |
| `files.db` | FileClassifier、LLM 服务 | 文件页、报告、Python 服务 | "值得看的东西"的分拣结果 + LLM 结论的落点（`llm_*` 列、`file_descriptions`） |
| `android/windows/linux/oss.db` | 各平台分析器 | 平台页面、微信关系图、Graphiti | 平台语义层："路径 + 字节"在这里变成"一条聊天记录"这样的取证工件。注意 `oss.db` 是 SERVER_CLOUD 场景由 LinuxFilesAnalyzer 写入的服务器/云工件库，与阿里云 OSS 分析组件（未接线）同名不同物 |
| `forensics_audit.db` | AuditLog（全局） | 审计接口 | 独立于任何任务，记录"谁对系统做了什么操作" |

两个容易误解的点：
- 24 张分类表（images、documents、……）是**查询优化**，不是数据冗余的主张——主 `files` 表有 `category` 列，分类表是按类物化的副本；`llm_*`/`scene_*` 列**只在主表**上。
- CLI 模式把平台工件并入 files.db 是历史路径；HTTP 任务模式的独立平台库才是当前主线（前端和 Python 服务都按任务库发现规则找 `_android.db` 这类后缀）。

各库完整表清单见 [DatabaseSchema.md](./DatabaseSchema.md)。

## 5. 智能层：LLM 与知识图谱怎么参与

LLM 在系统里出现在**三个层级**，各有分工，理解这个分层就理解了"智能层"：

1. **文件级**（C++ `LLMAnalysisService`，任务流水线内）：对 files.db 里的文件生成摘要/描述/关键词，写回 `llm_*` 列。分 FULL（全量）和 SMART（先让 LLM 粗选值得深析的文件，再精析）两种模式——SMART 是为控制成本和速度设计的。它的类注释标着 deprecated（曾计划迁到 Python），但**当前任务流水线的活跃路径仍是它**，别被注释误导。
2. **工件级**（C++ `Linux/Windows/AndroidLLMAnalysisService`）：平台分析器解析出的工件（一条登录记录、一个注册表项）语义化程度已经很高，LLM 在这个层面做的是批量解读和风险标注，结论写进各平台库的 `llm_*` 列。
3. **事件簇级**（C++ `EventClusterAnalyzer` + Python `/api/llm/analyze-event-cluster`）：时间线事件先聚成簇（burst detection），LLM 对整个簇回答"这段时间发生了什么值得注意的事"——这是从"数据"到"叙事"的最后一步。

所有 C++ 侧 LLM 调用都经 `ModelRouter` → `LLMClient`（OpenAI 兼容，cpp-httplib）。ModelRouter 的存在让你可以配多个端点做故障转移或按能力分工（文本模型与视觉模型分离，`LLM_TEXT_*` / `LLM_VISION_*`）。端点默认指向局域网 LM Studio（`192.168.31.170:1234`），意味着**离线环境也能跑**——这是设计约束，不是巧合。

**知识图谱（Graphiti）**是 Python 侧的价值放大器：任务完成后，C++ 异步触发 Python 摄取（`LLMPythonProxy` → `/api/graphiti/ingest`），Python 发现任务目录下的库文件，把文件描述和平台工件转成"episode"喂给 Graphiti，Graphiti 用 LLM 抽取实体（人名、IP、路径、哈希）写入 Neo4j。图谱按任务隔离（group_id = task_id），跨任务的实体合并由 `EntityRelationBuilder`/`MigrationManager` 负责。一个实用细节：`llm_patch.py` 会清洗 qwen/deepseek 思考型模型的 `<think>` 输出——本地模型生态的兼容性问题在这个层解决，而不是让每个调用方自己处理。

## 6. 模块地图（按功能组，建议按序读）

以下分组每段话对应一批模块文档（[docs/modules/](../modules/README.md)），顺序也是建议的阅读顺序：

**编排与任务**：`main.cpp` 是唯一入口，按参数分派给 `AnalysisOrchestrator`（CLI）或 `HTTPServer`（服务）。HTTP 侧的心脏是 [TaskManager](../modules/cpp/network/TaskManager.md)——单例，线程池执行、`TaskPersistence` 落 `data/tasks.json`、`TaskWatchdog` 把僵死任务（默认 30 分钟无进度）标记失败。配套的 [TaskInfrastructure](../modules/cpp/network/TaskInfrastructure.md) 讲支撑组件群。

**解析层**：[ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) 是与 TSK 的边界，处理多分区/多文件系统/XFS 三种模式/加密卷解密，产出 raw.db。它决定了下游能看到什么，是全项目最"接地气"的模块。

**提炼层**：[EventExtractor](../modules/cpp/core/EventExtractor.md)（元数据→事件）、[FileClassifier](../modules/cpp/core/FileClassifier.md)（24 类分拣 + 场景优先级）、[FileFilter](../modules/cpp/network/HTTPServer.md)（`config/filter_profiles/` 按案情过滤，电信诈骗/数据泄露等画像）。数据"长什么样"由这层定型，[DatabaseManager](../modules/cpp/core/DatabaseManager.md) 的 SQL-as-headers 模式（所有建表语句集中在 `src/core/DatabaseManager/SQL/` 头文件里）也在这层体现。

**平台语义层**：[AndroidAnalyzer](../modules/cpp/analyzers/AndroidAnalyzer.md)（含微信 SQLCipher 解密、QQNT、MIUI 备份）、[WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md)（注册表/事件日志/Prefetch/SRUM……）、[LinuxFilesAnalyzer](../modules/cpp/analyzers/LinuxFilesAnalyzer.md)（73 张表，日志/账户/持久化/容器/Web 服务器/攻击链）。三个分析器结构同构：Parsers（格式解析）→ Analysis（取证推理）→ Database（落库）→ LLM 服务（语义标注）。

**专项分析器**：[DLLAnalyzer](../modules/cpp/analyzers/DLLAnalyzer.md)（PE/ELF 威胁分析，注意当前扫描的是分析机本机系统目录而非镜像内容）、[FileCarving](../modules/cpp/analyzers/FileCarving.md)（29 种签名雕刻）、内存取证（Volatility3 子进程）。另有两个**已实现但未接线**的组件：[DatabaseAnalyzer](../modules/cpp/analyzers/DatabaseAnalyzer.md)（SQLite/MySQL/PG 数据目录取证，无 CLI/流水线入口，仅单测调用）与 [OSSAnalyzer](../modules/cpp/analyzers/OSSAnalyzer.md)（阿里云 OSS 编目，消费路由未注册，仅单测调用）。

**智能层**：[LLMClient](../modules/cpp/integration/LLMClient.md)/[ModelRouter](../modules/cpp/integration/ModelRouter.md)（C++ 出站 LLM）、Python [LLMService](../modules/python/services/LLMService.md)（重分析/批量 job）、[GraphitiService](../modules/python/services/GraphitiService.md) + [GraphitiIngestor](../modules/python/graphiti_integration/GraphitiIngestor.md)（图谱摄取与查询）。

**HTTP 与查询**：[HTTPServer](../modules/cpp/network/HTTPServer.md)（Crow、路由聚合、静态托管）、[SQLiteHelper](../modules/cpp/network/SQLiteHelper.md)（路由层的查询面，按 Timeline/Statistics/Files 等查询域拆分实现）、Python [httpserver/Main](../modules/python/httpserver/Main.md) 与 [ServiceManager](../modules/python/httpserver/services/ServiceManager.md)（分层超时、降级启动的故事在后者）。

**支撑设施**：[PathManager](../modules/cpp/core/PathManager.md)（所有运行时路径的唯一裁决者）、[AuditLog](../modules/cpp/core/AuditLog.md)、[FullTextSearch](../modules/cpp/core/FullTextSearch.md)（Xapian）、[TOONExporter](../modules/cpp/core/TOONExporter.md)（为 LLM 省 token 的表格编码——为什么存在：把"给模型看的数据"和"给人看的数据"分成两种格式）、[ThreadPool](../modules/cpp/core/ThreadPool.md)、[ConfigManager](../modules/cpp/core/ConfigManager.md)、[ErrorHandling](../modules/cpp/core/ErrorHandling.md)。

## 7. 关键设计决策一览（为什么）

- **为什么任务产出全在 `data/tasks/<id>/`**：并发隔离 + 删除即目录删除 + Python 侧 task_store 可以 fail-closed 地做精确路径匹配（防路径注入/越权读别的任务）。
- **为什么建表 SQL 放头文件**（SQL-as-headers）：让"schema 是代码"——分析器和 DatabaseManager 引用同一份常量，改表结构必须过编译，避免 schema 与代码漂移。
- **为什么 LLM 分三层**：不同层的信息密度不同，文件级要便宜（SMART 模式）、工件级要准确（上下文已经很干净）、簇级要叙事（整段行为）。统一一层做不了这种取舍。
- **为什么 TOON 存在**：给 LLM 的提示里，表格型数据用管道分隔比 JSON 省约 30-60% token，且模型解析稳定。凡是"把库内容喂给模型"的路径（导出、Python 端 TOON 流解析）都复用它。
- **为什么 Python 启动要分层超时**（30s 总预算/12s 可选服务）：真实环境 Neo4j/Redis 可能不健康，服务应该"带着降级能力起来"而不是卡死或崩溃——这是 2026-08 加固的成果（详见 docs/hardening/、docs/investigation/）。
- **为什么本地服务没有认证**：定位是取证工作站上的单机/内网工具，认证体系（JWT/组织/角色）只在 C/S 形态引入。前端登录页是占位交互，不接后端。

## 8. 哪些代码不要参考（死代码清单）

这些代码在仓库里但**不在运行路径上**，读代码或写文档时不要把它们当活功能（它们尚未被清理是历史原因，清理前先确认无外部脚本依赖）：

- `src/network/HTTPServer/routes/OSS*.cpp`：OSS 路由已编译但从未注册，`/api/forensics/oss/*` 运行时 404（前端 `/oss` 页面因此不可用）；其消费的 OSSAnalyzer 同样无生产调用方（仅单测）。注意任务目录里的 `oss.db` 是 SERVER_CLOUD 场景由 LinuxFilesAnalyzer 写入的，与阿里云 OSS 分析无关。
- `src/analyzers/VisionAnalysis/`：编译进二进制但无任何调用方。
- `src/integration/LLMIntegration/MCPIntegration.cpp`：MCP 服务器已编译但无生产调用方（没有任何地方启动它；`.env.example` 里的 `MCP_SERVER_PORT`/`MCP_ALLOWED_PATHS` 无代码读取，仅 `MCP_HOST` 被读）。
- `src/integration/AndroidAdbExtractor/`：不在 CMake `LIB_SOURCES`，未编译（且头文件与实现已失配到无法编译）；Android 逻辑取证实际走 AndroidAnalyzer 的 `--android-source dir|zip|miui-backup`。
- `src/network/HTTPServer/TaskAnalysisRunner.h`：无人引用的遗留头文件（任务执行实际在 `TaskManagerAnalysis.cpp`）。
- `python_service/httpserver/routes/system_logs.py`：router 未注册（日志路由的注册版在 `system.py`）。
- `python_service/httpserver` 的 `/api/llm/case-analysis`：固定返回 410，旧案件分析链路已退役，现行的是 multi_analysis + report 服务。

## 9. 相关文档

- **[DataFlow.md](./DataFlow.md)** —— 一个 HTTP 任务从创建到图谱摄取的完整走读（叙事版）
- **[Concurrency.md](./Concurrency.md)** —— 线程/协程/锁的全景：四种并发主体、大锁纪律、协作式取消、已知并发坑速查表
- **[DatabaseSchema.md](./DatabaseSchema.md)** —— 各库表清单与分层理由（逐列字段参考见 [docs/schema/](../schema/)）
- **[Deployment.md](./Deployment.md)** —— 部署形态与外部依赖
- **[Security.md](./Security.md)** —— 安全机制与边界
- **[模块文档索引](../modules/README.md)** —— 按模块深入

---


## 10. 新成员第一周路线图

**Day 1**：跑通 QuickStart（setup→run→建任务）→ 读本文 §1-§3 → 用 SqlCookbook 第 16 条看懂自己的任务产出。
**Day 2**：读 DataFlow 全文（一个任务的一生）→ 对着自己任务的 tasks.json 与审计日志把六幕走一遍。
**Day 3**：按方向分叉——C++ 方向读 ImageAnalyzer+TaskManager+EventExtractor；Python 方向读 httpserver/Main+ServiceManager+GraphitiService；前端读 web/Overview+Pages。
**Day 4**：跑一次验收（make acceptance-smoke）+ 读 AcceptanceHarness 理解隔离契约；跑ctest/pytest 各一轮。
**Day 5**：挑一个小任务实操（模块文档"常见任务配方"任选其一）→ 提交前过 Development 的 PR 自查清单。
随时翻：Glossary（术语）、FAQ（疑问）、DesignDecisions（为什么）、ThreatModel（边界）。
**最后更新**: 2026-08-23（解释式重写：以心智模型和设计动机为主线）
