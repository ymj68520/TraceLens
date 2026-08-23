# TraceLens 术语表（Glossary）

> 按主题分组的术语速查表。每条给出：**术语 | 英文/代码名 | 一句话定义 | 详见**。
> 链接指向 docs/ 内对应文档；定义均以源码与既有文档为准。

## 如何使用本表

- 遇到文档里的黑话（TOON、episode、看门狗、fire-and-forget……）先查本表定位"详见"，
  再跳转阅读完整解释；本表只给一句话，不做展开。
- 同一个词在不同层有不同含义时（如 `case`、`status`、`task_id`），优先看文末的
  "跨文档同名对照"表，再回正文查分组。
- 找不到的词按此顺序兜底：[ServiceContracts.md](ServiceContracts.md)（跨服务命名最全）
  → 各 [schema 文档](../schema/)（字段级命名）→ [模块索引](../modules/README.md)。
- 维护约定：新增术语时同步补"详见"链接；实现语义变化时**以源码为准**更新定义，
  本表不做独立决策。

---

## 一、取证与分析术语

覆盖镜像格式、文件系统取证、各专项分析（内存/Android/加密）与取证合规概念。

| 术语 | 英文/代码名 | 一句话定义 | 详见 |
|------|-------------|-----------|------|
| 磁盘镜像 | image / image_path | 取证分析的数据源：E01、raw/dd、多分区镜像或 Android 数据源路径 | [QuickStart](../getting-started/QuickStart.md)、[ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) |
| E01 | Expert Witness Format | EnCase 证据镜像格式，经 libewf 打开，支持分割卷 | [ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) |
| TSK | The Sleuth Kit | 底层文件系统解析库（4.14.0 源码安装），提供 inode/目录树/删除条目遍历 | [ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md)、[Installation](../getting-started/Installation.md) |
| inode（元数据地址） | inode / TSK inum | 文件系统元数据编号；多分区镜像内仅分区局部唯一，须与 partition_num 联用 | [RawDB](../schema/RawDB.md) |
| 时间戳四元组 | atime/mtime/ctime/crtime | raw.db files 表的四个 Unix 秒时间戳：访问/修改/inode 变更/创建（NTFS、ext4 才有 crtime） | [RawDB](../schema/RawDB.md)、[EventsDB](../schema/EventsDB.md) |
| 文件雕刻 | file carving | 不依赖文件系统、按文件签名从未分配空间恢复文件（`--carve` / `file_carving`） | [FileCarving](../modules/cpp/analyzers/FileCarving.md)、[CommonTasks §5](../getting-started/CommonTasks.md) |
| 已删除文件 | is_deleted / 未分配 | TSK 未分配目录项，`is_deleted=1`、`is_allocated=0`；提取时可 `include_deleted` | [RawDB](../schema/RawDB.md) |
| 取证场景 | scenario(s) | 任务级分析开关：`android / windows / linux / server_cloud` 多选 | [场景选择](../features/forensic-scenario-selection.md)、[CPP_REST_API](../api_reference/CPP_REST_API.md) |
| 场景检测 | SceneDetector | 任务早期自动判定镜像类型/平台，产出场景库与 scene_* 字段 | [SceneDetector](../modules/cpp/network/SceneDetector.md) |
| 过滤画像 | filter profile | `config/filter_profiles/*.json` 的场景过滤规则集（include/exclude 规则、combine_mode） | [FileFilter](../modules/cpp/core/FileFilter.md)、[FilterRoutes](../modules/cpp/network/routes/FilterRoutes.md) |
| 内置画像 | general_forensics 等 | 仓库自带四个画像：general_forensics（默认）/ telecom_fraud / data_breach / virus_intrusion | [CommonTasks §12](../getting-started/CommonTasks.md) |
| 平台工件 | artifact | Windows/Linux/Android 分析器从系统痕迹（注册表、日志、App 数据库）提取的结构化记录 | [WindowsDB](../schema/WindowsDB.md)、[LinuxDB](../schema/LinuxDB.md) |
| 内存取证 | memory forensics | Volatility3 分析内存镜像（进程/网络/bash 历史/启动信息 → `_memory.db`） | [MemoryAnalyzer](../modules/cpp/analyzers/MemoryAnalyzer.md)、[MemoryForensics 教程](../tutorials/MemoryForensics.md) |
| ISF 符号 | Volatility3 ISF | Volatility3 按内核版本所需的符号表，`scripts/build-vol3-isf.sh` 生成 | [CommonTasks §8](../getting-started/CommonTasks.md) |
| Android 数据源 | android_source | 四种 Android 输入：`tsk`（镜像，默认）/ `dir`（已解包目录）/ `zip` / `miui-backup`；非 tsk 短路磁盘管线 | [AndroidAnalyzer](../modules/cpp/analyzers/AndroidAnalyzer.md) |
| SQLCipher 解密 | wechat password | Android 微信/QQNT 数据库的 SQLCipher 密钥解密（`--wechat-password`） | [AndroidWechat 教程](../tutorials/AndroidWechat.md) |
| 磁盘加密解密 | enable_decryption | BitLocker/LUKS/VeraCrypt 解密；密钥文件约定 `<imageBase>.part<N>.key` | [ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md)、[CommonTasks §8](../getting-started/CommonTasks.md) |
| XFS 模式 | xfs_mode | XFS 文件系统解析策略：`auto`（默认）/ `native`（内核）/ `pure`（纯库） | [ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) |
| 审计日志 | audit log | 取证操作的不可抵赖记录（谁、何时、对哪个任务做了什么），另有任务级 audit-log 端点 | [AuditLog](../modules/cpp/core/AuditLog.md)、[CPP_REST_API](../api_reference/CPP_REST_API.md) |
| 证据保管链 | chain of custody | 证据从采集到呈堂的完整可溯记录；本项目对应审计日志 + 调查域的快照/溯源机制 | [AuditLog](../modules/cpp/core/AuditLog.md)、[InvestigationService](../modules/python/services/InvestigationService.md) |
| 微信关系图谱 | WeChat graph | 从 Android 微信工件构建的人物-聊天关系网络（ForceGraph2D + Louvain 社区发现） | [WeChatGraphService](../modules/python/services/WeChatGraphService.md)、[WechatGraph 路由](../modules/python/httpserver/routes/WechatGraph.md) |
| OSS 对象存储分析 | OSS analysis | 阿里云 OSS 数据分析（oss.db）；C++ 侧查询路由未注册，Python 侧仅存 AI 过滤/分析 | [OSSAnalyzer](../modules/cpp/analyzers/OSSAnalyzer.md)、[OssAnalysis](../modules/python/httpserver/routes/OssAnalysis.md) |
| 全文检索 | fulltext search | Xapian（libxapian）索引与检索；索引路径受 `FTS_ALLOWED_ROOT` 约束 | [FullTextSearch](../modules/cpp/core/FullTextSearch.md)、[SearchRoutes](../modules/cpp/network/routes/SearchRoutes.md) |

## 二、架构与任务术语

任务/案件/调查域的生命周期概念，以及 M 系列阶段沉淀的架构决策。

| 术语 | 英文/代码名 | 一句话定义 | 详见 |
|------|-------------|-----------|------|
| 三后端拓扑 | topology | C++ 取证引擎（:8080/8666）+ Python httpserver（:8090）+ 分布式 C/S server（:8091），一个 React SPA 消费 | [Overview](../architecture/Overview.md)、[ServiceContracts §1](ServiceContracts.md) |
| 任务 | task | HTTP 模式的分析单元：一次镜像分析的全生命周期（状态、进度、产物库路径） | [TaskManager](../modules/cpp/network/TaskManager.md) |
| CLI 分析 | CLI mode | 直接运行 `forensic_analyzer <镜像>` 的无服务分析，产库名带镜像前缀 | [AnalysisOrchestrator](../modules/cpp/core/AnalysisOrchestrator.md)、[CLI](CLI.md) |
| 任务持久化 | tasks.json | C++ TaskManager 把全部任务元数据落 `data/tasks.json`（相对可执行文件） | [Troubleshooting §7](../getting-started/Troubleshooting.md) |
| 任务状态机 | task status | 全小写字符串：`pending / running / completed / failed / cancelled` | [CPP_REST_API 响应约定](../api_reference/CPP_REST_API.md) |
| 任务阶段 | phase | 进度的八个阶段：initializing → image_analysis → event_extraction → file_classification → llm_analysis → platform_analysis → file_carving → finalizing | [CPP_REST_API 响应约定](../api_reference/CPP_REST_API.md) |
| 任务优先级 | priority | `low / normal / high / critical`（priority 端点目前只回显不生效） | [CPP_REST_API §1](../api_reference/CPP_REST_API.md) |
| 任务看门狗 | TaskWatchdog | 每 60s 巡检：RUNNING 超 `TASK_WATCHDOG_STALE_MINUTES`（默认 30 分钟）无进度即标 FAILED | [Troubleshooting §7](../getting-started/Troubleshooting.md) |
| 批量任务 | batch-* | `/api/tasks/batch-create\|batch-status\|batch-cancel` 三端点一次操作多个镜像 | [CPP_REST_API §1](../api_reference/CPP_REST_API.md) |
| 案件 | case | 多镜像聚合单元；C++ CaseManager（cases.json）与 Python `/api/llm/cases` 双实现，前端经 Python 域 | [CaseManager](../modules/cpp/network/CaseManager.md)、[ServiceContracts §5](ServiceContracts.md) |
| 跨镜像分析 | multi-image analysis | 案件级关联分析 job（Python），完成后回写 C++ 案件状态 | [CaseAnalysis 路由](../modules/python/httpserver/routes/CaseAnalysis.md)、[ServiceContracts §5](ServiceContracts.md) |
| 关联任务复用 | associate-tasks | 把已完成分析的任务挂入案件并预填分析态，避免重跑 | [Python_REST_API §5](../api_reference/Python_REST_API.md) |
| 分析编排器 | AnalysisOrchestrator | CLI 模式的分析总调度（镜像→事件→分类→平台→报告的执行顺序与库落盘） | [AnalysisOrchestrator](../modules/cpp/core/AnalysisOrchestrator.md) |
| 任务工作区 | task workspace | HTTP 任务产物目录 `data/tasks/<task_id>/`，库用纯名（raw.db，无镜像前缀） | [PathManager](../modules/cpp/core/PathManager.md)、[ServiceContracts §8.1](ServiceContracts.md) |
| legacy 输出目录 | db_output_dir | 旧式自定义产物目录：库带镜像前缀，filter 后 `_raw.db` 换 `_filtered.db` | [ServiceContracts §8.1](ServiceContracts.md) |
| 逻辑 Android 任务短路 | logical android shortcut | android_source 非 tsk 时跳过磁盘管线，仅产 android.db/files.db（不产 raw.db） | [ServiceContracts §8.5](ServiceContracts.md)、[AndroidAnalyzer](../modules/cpp/analyzers/AndroidAnalyzer.md) |
| 调查工作台 | investigation workbench | 按任务聚合的二次调查域（`/api/investigation/workbench/{task_id}`）：证据→分析→事件→终版报告 | [Investigation 路由](../modules/python/httpserver/routes/Investigation.md)、[Python_REST_API §8](../api_reference/Python_REST_API.md) |
| 证据快照 | evidence snapshot | 对证据键的不可变快照（`POST /api/investigation/snapshots`，body 严格 `{task_id, evidence_key}`） | [InvestigationService](../modules/python/services/InvestigationService.md) |
| 二级分析 | secondary analysis | 对证据快照启动的异步分析（`POST /api/investigation/analyses` 返回 202），产出 claims | [Python_REST_API §7](../api_reference/Python_REST_API.md) |
| 调查事件 | InvestigationEvent | 调查域的事件实体：可挂证据、带版本历史与刷新机制 | [Python_REST_API §7](../api_reference/Python_REST_API.md) |
| 声明 | claim | 二级分析产出的可溯源断言，展开引用 evidence_keys 供回溯 | [Python_REST_API §7](../api_reference/Python_REST_API.md)、[Hooks](../modules/web/Hooks.md) |
| 待审阅态 | review_pending | 分析/声明的回落状态（尚未 accept）；前端图谱画虚线圈标注 Unconfirmed | [Python_REST_API §7](../api_reference/Python_REST_API.md)、[Components](../modules/web/Components.md) |
| 固定 409 端点 | fixed-409 | workbench 中已注册但按设计拒绝的端点（如版本/声明驳回）——显式契约边界，不是故障 | [Python_REST_API §8](../api_reference/Python_REST_API.md) |
| 终版报告 | final report | 调查工作台产出的可发布报告（markdown/html/print 多形态 + publish 发布） | [Python_REST_API §8](../api_reference/Python_REST_API.md) |
| 报告生成 | report generation | R2c 冻结契约：`POST /api/reports/generate` 返回 202（admission），body 仅 `{task_id, requested_by}` | [ForensicReports 路由](../modules/python/httpserver/routes/ForensicReports.md)、[Python_REST_API §6.3](../api_reference/Python_REST_API.md) |
| 报告证据 | report evidence | 报告可引用的证据集登记（`/api/reports/evidence`，重复登记 409） | [Python_REST_API §6.2](../api_reference/Python_REST_API.md) |
| 叙事版本 | narrative version | `report_kind='llm_generation'` 的已发布叙事版报告（只读） | [Python_REST_API §6.4](../api_reference/Python_REST_API.md) |
| 语义对账 | semantic reconciliation | M1 阶段新旧两套案件/分析域的语义对齐决策记录 | [M1 对账](../integration/m1-semantic-reconciliation.md) |

## 三、数据库术语

SQLite 产物库家族：谁生产、谁消费、命名怎么解析、坏了怎么修。

| 术语 | 英文/代码名 | 一句话定义 | 详见 |
|------|-------------|-----------|------|
| raw 库 | raw.db / `<stem>_raw.db` | 派生链唯一事实来源：TSK 看到的一切原样落库，唯一不可重建的库 | [RawDB](../schema/RawDB.md) |
| 派生链 | derivation chain | raw.db →（filter → filtered.db）→ files.db / events.db / 各平台库 的单向数据流 | [DatabaseSchema](../architecture/DatabaseSchema.md)、[DataFlow](../architecture/DataFlow.md) |
| 过滤库 | filtered.db / `.filtered` | FileFilter 按 profile 产出的 raw 子集副本（raw.db 本体不动） | [FileFilter](../modules/cpp/core/FileFilter.md) |
| 事件库 | events.db | 时间线事件（从 raw 四时间戳提取的 CREATED/MODIFIED/... 事件流） | [EventsDB](../schema/EventsDB.md)、[EventExtractor](../modules/cpp/core/EventExtractor.md) |
| 文件主库 | files.db | 文件分类 + 平台工件统一库，LLM/报告/图谱的主数据源 | [FilesDB](../schema/FilesDB.md)、[FileClassifier](../modules/cpp/core/FileClassifier.md) |
| 平台库 | android/windows/linux.db | 各平台分析器的工件库（HTTP 任务用任务目录纯名，CLI 用镜像前缀名） | [AndroidDB](../schema/AndroidDB.md)、[WindowsDB](../schema/WindowsDB.md)、[LinuxDB](../schema/LinuxDB.md) |
| 内存库 | `_memory.db` | Volatility3 内存取证结果（只读打开，缺失时内存路由 404） | [MemoryDB](../schema/MemoryDB.md) |
| DLL 库 | `_dll.db` | PE/ELF 共享库分析结果（路由解析时 metadata 优先） | [DLLAnalyzer](../modules/cpp/analyzers/DLLAnalyzer.md) |
| 调查库 | investigation.db | 与任务可信库同目录的调查工作台库（Python 侧创建） | [ServiceContracts §8.1](ServiceContracts.md)、[InvestigationService](../modules/python/services/InvestigationService.md) |
| 后缀总表 | DB_SUFFIXES | 跨服务共识的库后缀集合 `{_raw,_filtered,_files,_events,_windows,_linux,_android}.db`，每个后缀还回退纯名 | [ServiceContracts §8.4](ServiceContracts.md) |
| 后缀回退 | RouteHelpers fallback | C++ 查 android/dll/memory 库时的多级路径解析（metadata → 任务目录纯名 → legacy 前缀名 → 兜底） | [ServiceContracts §8.2](ServiceContracts.md) |
| WAL | write-ahead logging | SQLite 日志模式（`.env` 的 `DB_JOURNAL_MODE=WAL`），残留 -wal/-shm 在持有进程退出后合并 | [Troubleshooting §11](../getting-started/Troubleshooting.md) |
| 完整性检查 | PRAGMA integrity_check | sqlite3 诊断库损坏的标准 pragma；损坏可用 `.dump` 管道恢复 | [Troubleshooting §11](../getting-started/Troubleshooting.md) |
| inode 碰撞 | inode collision | 多分区镜像中不同分区的 inode 撞号，靠 partition_num 列消除 | [RawDB](../schema/RawDB.md) |
| SQL-as-headers | SQL 头文件约定 | 建表 SQL 定义在 `SQL/` 头文件里供多模块复用（raw.db 是唯一例外，内联在 DatabaseManager） | [DatabaseManager](../modules/cpp/core/DatabaseManager.md) |
| 权威库解析 | TaskStore canonical | Python 侧以 `output_files_db/output_files_db_path` 为唯一持久化目标；客户端传路径仅做精确相等校验 | [TaskStore](../modules/python/services/TaskStore.md)、[ServiceContracts §8.3](ServiceContracts.md) |
| 检索索引 | search index | 前端按 `search_index_<taskId 前 8 位>` 命名建在任务提取目录的 Xapian 索引 | [Search](../modules/web/Pages.md)、[FullTextSearch](../modules/cpp/core/FullTextSearch.md) |

## 四、LLM 与知识图谱术语

AI 分析的开关/模式、事件簇、Graphiti 图谱栈与 token 优化格式。

| 术语 | 英文/代码名 | 一句话定义 | 详见 |
|------|-------------|-----------|------|
| LLM 分析开关 | llm_analyze | 任务级 AI 分析总开关（false 时可用 `--no-ai` 跳过） | [CPP_REST_API §1](../api_reference/CPP_REST_API.md) |
| FULL 模式 | llm_mode=full | 全量文件 LLM 分析（逐文件请求，成本高） | [Environment](Environment.md)、[CPP_REST_API §1](../api_reference/CPP_REST_API.md) |
| SMART 模式 | llm_mode=smart | 默认模式：先过滤/抽样再分析，控制 token 成本 | [Environment](Environment.md)、[CPP_REST_API §1](../api_reference/CPP_REST_API.md) |
| 文本/视觉模型 | LLM_TEXT_MODEL / LLM_VISION_MODEL | OpenAI 兼容端点的两个模型名，必须与端点加载的模型完全一致 | [Environment](Environment.md)、[Troubleshooting §6](../getting-started/Troubleshooting.md) |
| 模型路由 | ModelRouter | C++ 侧多模型选择/降级路由 | [ModelRouter](../modules/cpp/integration/ModelRouter.md) |
| LLM 代理 | LLMPythonProxy | C++ 调 Python Graphiti 作业面的同步 httplib 单例 | [LLMPythonProxy](../modules/cpp/network/LLMPythonProxy.md)、[ServiceContracts §2](ServiceContracts.md) |
| 事件簇 | event cluster | 时间线按时间窗+类型+目录聚合的簇（`cluster=true&bucket=秒`） | [EventClusterAnalyzer](../modules/cpp/network/EventClusterAnalyzer.md) |
| 簇描述符 | group_descriptor | 簇的唯一身份 `{bucket_index, bucket_seconds, event_type, parent_directory}`，明细/研判调用原样上送 | [Timeline 路由](../api_reference/CPP_REST_API.md)、[web/Pages](../modules/web/Pages.md) |
| 聚簇窗口 | bucket | 聚簇秒窗，钳制 [1,86400]，默认 60；前端 auto 档按跨度映射 60s~6h | [CPP_REST_API §2.1](../api_reference/CPP_REST_API.md)、[web/Pages](../modules/web/Pages.md) |
| LLM 描述列 | llm_summary 等五列 | files 表的 `llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used`（raw.db 同名列恒 NULL 仅预留） | [FilesDB](../schema/FilesDB.md)、[RawDB](../schema/RawDB.md) |
| 批量分析 | batch job | `POST /api/llm/batch` 的后台批量文件分析（前端轮询 job 进度） | [LLM 路由](../modules/python/httpserver/routes/LLM.md)、[web/Services](../modules/web/Services.md) |
| 二次分析（文件） | reanalyze-files | `POST /api/llm/reanalyze-files`：带提示词重跑选定文件的分析 | [Python_REST_API §4](../api_reference/Python_REST_API.md) |
| Graphiti | graphiti-core | Neo4j 上的知识图谱框架：episode → LLM 抽取实体/关系 → 图存储 | [GraphitiIntegration](../modules/python/graphiti/GraphitiIntegration.md) |
| episode | episode | Graphiti 的摄取单元：取证记录变换成的自然语言叙事块（单块上限 `max_episode_tokens=3000`） | [GraphitiIntegration](../modules/python/graphiti/GraphitiIntegration.md) |
| 图命名空间 | group（task_id） | Graphiti 的隔离单元：`task_id` 兼作 group，删图按 task 维度 | [ServiceContracts §2.1](ServiceContracts.md)、[Graphiti](../modules/python/httpserver/routes/Graphiti.md) |
| 嵌入模型 | text-embedding-nomic-embed-text-v1.5 | Graphiti 默认嵌入模型，维度 768；换模型必须同步 `EMBEDDING_DIM` | [GraphitiIntegration](../modules/python/graphiti/GraphitiIntegration.md)、[Troubleshooting §5](../getting-started/Troubleshooting.md) |
| 摄取模式 | ingest mode | `full / files_only / events_only / analyzed_only`（analyzed_only 只重摄取已分析行，不重跑 LLM） | [Python_REST_API §2.1](../api_reference/Python_REST_API.md) |
| 摄取队列 | IngestionJobManager | Graphiti 摄取作业管理器：优先 Redis 持久化，退化进程内存（重启丢状态） | [IngestionJobManager](../modules/python/services/IngestionJobManager.md)、[Troubleshooting §4](../getting-started/Troubleshooting.md) |
| TOON | Token-Oriented Object Notation | "首行 schema + 管道符分隔行"的紧凑文本格式，比 JSON 省 30-60% token | [TOONExporter](../modules/cpp/core/TOONExporter.md) |
| TOON 流切分 | TOON.schema: 行 | Python 侧把 TOON 文本按首行 schema 与数据行切分再分批消费的适配 | [ServiceContracts §6-12](ServiceContracts.md)、[TOONTransformer](../modules/python/graphiti_integration/TOONTransformer.md) |
| markitdown | markitdown | Python 文档转 Markdown 服务（convert/convert-one/batch-convert），读取受三重边界约束 | [Markitdown 路由](../modules/python/httpserver/routes/Markitdown.md) |
| 情报报告 | intelligence report | `/api/llm/intelligence-report/{task_id}` 历史 LLM 研判报告（三栏阅读器消费） | [Python_REST_API §4](../api_reference/Python_REST_API.md)、[web/Components](../modules/web/Components.md) |
| 事件关联 | associations | 簇↔文件双向关联端点（`/api/associations/cluster-files`、`file-clusters`） | [Associations 路由](../modules/python/httpserver/routes/Associations.md) |
| 案情描述 | case_description | 贯穿任务创建/案件/LLM 提示的案情上下文字段（Python 会回写 C++ 任务） | [ServiceContracts §6](ServiceContracts.md)、[CPP_REST_API §1](../api_reference/CPP_REST_API.md) |

## 五、运维、部署与前端术语

健康/降级语义、端口与代理、前端状态管理模式、分布式 C/S 概念。

| 术语 | 英文/代码名 | 一句话定义 | 详见 |
|------|-------------|-----------|------|
| 健康探针三口径 | health endpoints | C++ 探 Python 用 `/health`、Python 探 C++ 用 `/api/health`、run.sh 探 C++ 用 `/api/system/health` 三个口径并存 | [ServiceContracts §9-8](ServiceContracts.md) |
| 存活/就绪探针 | live / ready | `live` 只探进程活着；`ready` 探依赖（C++ 的 ready 检 task_manager/database，Python 的 ready 中 cpp_backend 为硬依赖） | [CPP_REST_API §6](../api_reference/CPP_REST_API.md)、[Python_REST_API §1](../api_reference/Python_REST_API.md) |
| 可选依赖降级 | graceful degradation | Python 的 Neo4j/LLM/Redis 不可用只降级不阻断（Graphiti disabled、队列转内存、`/health` 仍 ready） | [Troubleshooting §4-5,§9](../getting-started/Troubleshooting.md)、[Deployment](../architecture/Deployment.md) |
| 尽力而为 | fire-and-forget | C++ 任务尾部触发 Graphiti ingest 的语义：失败不影响任务成败，不等待不重试 | [ServiceContracts §8.5](ServiceContracts.md)、[LLMPythonProxy](../modules/cpp/network/LLMPythonProxy.md) |
| run.sh | — | 一键构建并前台启动三服务的脚本：C++ 端口兜底 8666，日志集中 `build/logs/` | [QuickStart §3](../getting-started/QuickStart.md) |
| 环境变量文件 | .env | ConfigManager 与 Python config 共读的配置文件（`cp .env.example .env`） | [Environment](Environment.md)、[ConfigManager](../modules/cpp/core/ConfigManager.md) |
| 基址约定 | base URLs | C++→Python 用 `PYTHON_SERVICE_URL`（否则 PYTHON_HTTP_PORT），Python→C++ 用 `CPP_BACKEND_URL` | [ServiceContracts §1](ServiceContracts.md) |
| 改端口检查清单 | port checklist | 改端口需同步 .env 三处 + `PYTHON_SERVICE_URL` + run.sh 回退 + 前端重启/重建 | [ServiceContracts 附录 B](ServiceContracts.md) |
| 三 axios 客户端 | api / pythonApi / csApi | 前端分别指向 C++（同源）、Python 8090、C/S 8091 的三个客户端，统一拦截器解包 | [web/Overview](../modules/web/Overview.md)、[ServiceContracts §7.2](ServiceContracts.md) |
| Vite 代理表 | proxy prefixes | dev 模式按前缀分发：`/csapi`→8091（剥前缀）、`/api/{reports,graphiti,llm,office,db,wechat,investigation}`→8090、兜底 `/api` 与 `/tasks`→C++ | [web/Overview](../modules/web/Overview.md)、[ServiceContracts §7.1](ServiceContracts.md) |
| 动态 host 推导 | currentHost() | pythonApi/csApi 按浏览器当前 hostname 拼端口，解决跨机访问时 localhost 指向客户端自身的问题 | [web/Overview](../modules/web/Overview.md) |
| 双 token | auth_token / cs_auth_token | 本地 mock 登录与分布式 JWT 各自独立存储，401 行为不同（前者跳登录页，后者仅清除） | [web/Overview](../modules/web/Overview.md)、[ServiceContracts §7.2](ServiceContracts.md) |
| mock 登录 | mock login | `/login` 任意账密即发假 JWT（`mock_jwt_token_<ts>`），无路由守卫 | [web/Pages](../modules/web/Pages.md) |
| 任务上下文传播 | task_id query | 当前任务靠 URL query 在 13+ 个任务页间透传（TaskSelector ↔ Layout.getLinkUrl） | [web/Overview](../modules/web/Overview.md)、[web/Pages](../modules/web/Pages.md) |
| identity 轮询 | identity polling | 轮询 hooks 把对象多元组拼成 identity 字符串，identity 变化即丢弃全部旧状态、null 不发请求 | [web/Hooks](../modules/web/Hooks.md) |
| requestId 防陈旧 | stale-guard | 单调递增计数器 + key ref，旧请求的晚到响应（成功或失败）一律不落 state | [web/Hooks](../modules/web/Hooks.md) |
| 静默拉取 | fetchTasksSilent | 不置 `status='loading'` 的后台列表刷新 thunk，避免整页每 5 秒闪 loading | [web/Store](../modules/web/Store.md) |
| 脏标记 | refreshFlags | intelligenceSlice 的跨页面"数据已变脏"信号（files/clusters 两个位） | [web/Store](../modules/web/Store.md) |
| ApiResponse 封装 | ApiResponse | `{success, message, data, timestamp, pagination, error_code}`——仅 `/api/filter/*` 使用，其余 C++ 路由直接返回领域 JSON | [CPP_REST_API 响应约定](../api_reference/CPP_REST_API.md)、[web/Store](../modules/web/Store.md) |
| SSE 日志流 | logs-stream | `GET /api/system/logs-stream/{service}` 的 Server-Sent Events 实时日志（Python 代读） | [Python_REST_API §15](../api_reference/Python_REST_API.md)、[web/I18nTheming](../modules/web/I18nTheming.md) |
| 错误码区间 | error codes | `ErrorHandling.h` 的分段：100 文件 / 200 LLM / 300 模型 / 400 配置 / 500 数据库 / 600 分析 / 900 通用 | [Troubleshooting §12](../getting-started/Troubleshooting.md)、[ErrorCodes](ErrorCodes.md) |
| 410 退役契约 | retired endpoints | 已退役端点固定返回 410（如 legacy case analysis），调用方应迁移到报告生成 | [ErrorCodes](ErrorCodes.md)、[web/Services](../modules/web/Services.md) |
| C/S 命令队列 | command queue | 分布式模式：服务端下发命令 → http_agent 轮询取命令 → 本地拉起 CLI → 回报状态 | [HttpAgent](../modules/cpp/http_agent/HttpAgent.md)、[DistributedCS 教程](../tutorials/DistributedCS.md) |
| 注册令牌 | registration token | 组织管理员签发的一次性客户端注册凭证（client credential 体系） | [Python_REST_API §16](../api_reference/Python_REST_API.md) |
| 产物引用上报 | artifact reference | C/S 结果只上报 `file_path + storage_location + result_metadata`，镜像字节永不离开客户端 | [Python_REST_API §16](../api_reference/Python_REST_API.md) |
| 现场机代理 | http_agent | 部署在现场机的代理进程：向 C/S 领命令并在本地执行 CLI（`command_executor.cpp`） | [HttpAgent](../modules/cpp/http_agent/HttpAgent.md) |
| PostgreSQL C/S | PostgreSQLCS | 分布式 C/S 的元数据库（DATABASE_URL），不可用时服务降级启动 | [PostgreSQLCS](../schema/PostgreSQLCS.md)、[Python_REST_API §16](../api_reference/Python_REST_API.md) |
| 死代码 | dead code | 有实现、有测试但无路由/无调用方的模块（前端 4 页面、C++ OSSRoutes 等），绿灯不等于可达 | [modules/README](../modules/README.md)、[web/Pages](../modules/web/Pages.md) |

## 六、跨文档同名对照

同一个词在不同层含义不同，读代码/文档时按下表消歧：

| 同名词 | 层 A | 层 B | 差异要点 | 详见 |
|--------|------|------|----------|------|
| case | C++ CaseManager（`/api/cases*`） | Python `/api/llm/cases*` | 前端与跨镜像分析走 Python 域，C++ 侧承接状态回写；cases.json 与 Python 各存一份 | [ServiceContracts §5](ServiceContracts.md) |
| status（任务） | C++ 任务全小写 | Graphiti 作业全大写 | `completed` vs `COMPLETED`——两套字面量并存且各自有比较方 | [ServiceContracts §2 漂移点](ServiceContracts.md)、[web/Hooks](../modules/web/Hooks.md) |
| task_id | C++ 任务 id | Graphiti group 命名空间 | 同一字符串在图域兼作隔离单元，删图按它 | [ServiceContracts §2.1](ServiceContracts.md) |
| review | `/api/investigation/analyses/{id}/review`（200） | workbench events review（固定 409） | 冻结契约域可审阅；本地工作台域明确不提供 | [Python_REST_API §7-8](../api_reference/Python_REST_API.md) |
| results | 任务结果 `/api/tasks/{id}/results` | C/S 结果上报 `/api/tasks/{id}/results` | 前者是文件摘要+LLM 证据；后者是产物引用列表（不同服务、不同鉴权） | [CPP_REST_API §1](../api_reference/CPP_REST_API.md)、[Python_REST_API §16](../api_reference/Python_REST_API.md) |
| databases | `GET /api/tasks/{id}/databases`（C++） | `GET /api/db/tasks/{id}/databases`（Python） | 语义相同（库清单），两个服务各实现一份 | [ServiceContracts §6/§9](ServiceContracts.md) |
| largest files | C++ `files/largest` 直出 | Python CppBackendService 再包装 | Python 侧兼容裸数组或 `{largest_files\|files}` 两种形态并做客户端过滤 | [ServiceContracts §6-6/7](ServiceContracts.md) |
| extraction | C++ 异步提取 job | Python extract_files 代理 | Python 把文件列表逗号拼进 name 模式模拟列表模式（C++ 无真列表模式） | [ServiceContracts §6-9/§9-5](ServiceContracts.md) |
| 分析 | 文件级 LLM（llm_analyze） | 调查域二级分析（secondary analysis） | 前者改 files.db 描述列；后者产 claims 不改原始证据 | [FilesDB](../schema/FilesDB.md)、[Python_REST_API §7](../api_reference/Python_REST_API.md) |

## 七、缩写速查

| 缩写 | 全称 | 所属 |
|------|------|------|
| TSK | The Sleuth Kit（文件系统取证库） | 取证 |
| E01 | EnCase Expert Witness Format | 取证 |
| ISF | Intermediate Symbol Format（Volatility3 符号表） | 取证 |
| WAL | Write-Ahead Logging（SQLite 日志模式） | 数据库 |
| FTS | Full-Text Search（Xapian 全文检索） | 数据库 |
| TOON | Token-Oriented Object Notation | LLM |
| LLM | Large Language Model | LLM |
| JWT | JSON Web Token（仅 C/S 域使用） | 运维 |
| SSE | Server-Sent Events（日志实时流） | 运维 |
| SPA | Single-Page Application（React 前端） | 前端 |
| C/S | Client/Server（分布式服务 :8091） | 架构 |
| CLI | Command-Line Interface（`forensic_analyzer`） | 架构 |
| API | Application Programming Interface | 通用 |
| OSS | Object Storage Service（阿里云对象存储） | 取证 |

## 八、代码名 → 中文术语反查

读源码/API 时看到英文名，从这里反查中文释义与所属分组：

| 代码名 | 中文术语（分组） |
|--------|------------------|
| `android_source` | Android 数据源（一） |
| `bucket` / `bucket_seconds` | 聚簇窗口（四） |
| `chain of custody` | 证据保管链（一） |
| `cross_analysis_job_id` | 跨镜像分析 job（二） |
| `DB_JOURNAL_MODE` | WAL（三） |
| `enable_decryption` | 磁盘加密解密（一） |
| `evidence_key` | 证据快照的寻址键（二） |
| `filtered.db` | 过滤库（三） |
| `fire-and-forget` | 尽力而为触发（五） |
| `group_descriptor` | 簇描述符（四） |
| `IngestRequest.mode` | 摄取模式（四） |
| `is_deleted` / `is_allocated` | 已删除/未分配标志（一） |
| `llm_analyze` / `llm_mode` | LLM 分析开关 / FULL·SMART（四） |
| `max_episode_tokens` | episode 长度上限（四） |
| `output_files_db` | 权威库解析的锚点字段（三） |
| `partition_num` | inode 碰撞消解列（三） |
| `registration_token` | 注册令牌（五） |
| `requested_by` | 报告生成的发起者字段（二） |
| `review_pending` | 待审阅态（二） |
| `TASK_WATCHDOG_STALE_MINUTES` | 看门狗阈值（二） |
| `tasks.json` | 任务持久化文件（二） |
| `workspace_root` | markitdown 的工作区锚定参数（四） |
| `xfs_mode` | XFS 模式（一） |

## 九、按角色阅读路径

- **取证分析师**：第一、四组 → [QuickStart](../getting-started/QuickStart.md) →
  [CommonTasks](../getting-started/CommonTasks.md) → 各 [tutorials](../tutorials/)。
- **后端开发者**：第二、三组 → [architecture/Overview](../architecture/Overview.md) →
  [DatabaseSchema](../architecture/DatabaseSchema.md) → [modules 索引](../modules/README.md)。
- **前端开发者**：第五组 → [web/Overview](../modules/web/Overview.md) → 其余七篇模块文档。
- **运维/部署**：第五组 → [ServiceRunbook](../ops/ServiceRunbook.md) →
  [Troubleshooting](../getting-started/Troubleshooting.md) → [Environment](Environment.md)。
- **分布式使用者**：第二组（C/S 相关）→ [DistributedCS 教程](../tutorials/DistributedCS.md)。

---

## 统计与维护说明

- 本表共 **120 条**术语：取证 23 / 架构 28 / 数据库 17 / LLM 24 / 运维前端 28；另有
  同名对照 9 条、缩写 14 条、代码名反查 23 条作为辅助索引（不计入术语数）。
- 维护约定见文首"如何使用本表"；统计行随内容同步更新。

---

**最后更新**: 2026-08-24（新建，术语表）
