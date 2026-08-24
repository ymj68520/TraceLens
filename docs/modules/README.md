# TraceLens 模块文档索引

## 说明

- 模块文档已经过技术深化：叙事结构之外，每篇补了真实代码走读、字段/方法清单、性能并发、调用矩阵与配置影响；数据库字段详见 [schema](../schema/)，跨层入口详见 [源码导览](../reference/SourceMap.md)。
- 模块文档按目录组织，与源码位置对应：`docs/modules/cpp/**` 对应 `src/**`，`docs/modules/python/**` 对应 `python_service/**`。
- 每篇模块文档按统一的**解释式结构**组织：`为什么有这个模块 → 在系统中的位置 → 核心概念与设计 → 工作流程走读（含 file:line 锚点）→ 与其他模块的协作 → 注意事项与已知问题 → 如何验证与扩展`。先读 [架构总览](../architecture/Overview.md) 和 [数据流](../architecture/DataFlow.md) 建立全局图景，再按需深入单个模块。
- 文档于 2026-08-23 按代码重写；后续代码演进时**请以代码为准**。
- 下表描述均依据当前代码核实编写；个别模块在代码中已处于过时/死代码状态，见下方"过时与死代码模块"标注。

## 过时与死代码模块

以下模块文档保留供参考，但其对应源码在当前代码库中的状态需特别注意：

| 文档 | 代码状态 |
|------|----------|
| [VisionAnalysis](cpp/analyzers/VisionAnalysis.md) | `src/analyzers/VisionAnalysis/VisionAnalyzer.cpp` 已编入 CMake，但项目中无任何调用方引用，属**死代码** |
| [AndroidAdbExtractor](cpp/integration/AndroidAdbExtractor.md) | `src/integration/AndroidAdbExtractor` 仅作为 include 目录出现在 CMakeLists.txt，其源文件**未编入构建**（且已无法通过语法检查） |
| [MCPIntegration](cpp/integration/MCPIntegration.md) | MCP 服务器已编译但**无生产调用方**（没有任何地方启动它）；`.env.example` 的 `MCP_SERVER_PORT`/`MCP_ALLOWED_PATHS` 无代码读取，仅 `MCP_HOST` 被读 |
| [OSSRoutes](cpp/network/routes/OSSRoutes.md) | OSS 路由源码（`OSSRoutes.cpp` 等）已编译，但 `HTTPserver` 从未注册该路由，**运行时不可用** |
| [LLMAnalysisService](cpp/network/LLMAnalysisService.md) | `LLMPythonProxy.h` 头注释将其标记为 deprecated，但任务流水线（`TaskManagerAnalysis.cpp`）仍调用它执行文件级 LLM 分析，**仍是活跃路径** |
| [EventClusterAnalyzer](cpp/network/EventClusterAnalyzer.md) | 存在且活跃（`TaskManager` / `TaskManagerAnalysis` 中使用） |

---

## C++ 模块文档（src/）

### 分析器（cpp/analyzers/）

| 文档 | 描述 |
|------|------|
| [ImageAnalyzer](cpp/analyzers/ImageAnalyzer.md) | 磁盘镜像分析入口：TSK/原生文件系统遍历、加密镜像解密、XFS 支持 |
| [AndroidAnalyzer](cpp/analyzers/AndroidAnalyzer.md) | Android 取证分析：QQNT/微信/MIUI 备份工件解析、SQLCipher 解密、逻辑提取（dir/zip/miui-backup） |
| [WindowsFilesAnalyzer](cpp/analyzers/WindowsFilesAnalyzer.md) | Windows 系统工件分析（Shimcache/UserAssist/RDP/WiFi 解析器已实现未接线，对应表恒空） |
| [LinuxFilesAnalyzer](cpp/analyzers/LinuxFilesAnalyzer.md) | Linux 工件分析：日志/journal/auditd/容器/云工件解析与篡改、持久化检测 |
| [MemoryAnalyzer](cpp/analyzers/MemoryAnalyzer.md) | 内存取证：Volatility3 封装（进程/网络/Bash 历史/启动信息 → `_memory.db`；CLI 专用旁路，HTTP 侧靠命名约定找库） |
| [DatabaseAnalyzer](cpp/analyzers/DatabaseAnalyzer.md) | 数据库取证：SQLite/MySQL/PostgreSQL 分析，InnoDB/堆页与 binlog 解析（**未接线**：无 CLI/流水线入口，仅单测调用） |
| [DLLAnalyzer](cpp/analyzers/DLLAnalyzer.md) | PE/ELF 共享库分析：导入导出、依赖、异常检测、签名校验 |
| [FileCarving](cpp/analyzers/FileCarving.md) | 基于文件签名的雕刻恢复（含已删除文件） |
| [PDFAnalyzer](cpp/analyzers/PDFAnalyzer.md) | PDF 文档解析与元数据提取 |
| [OfficeAnalyzer](cpp/analyzers/OfficeAnalyzer.md) | Office 文档解析 |
| [OSSAnalyzer](cpp/analyzers/OSSAnalyzer.md) | 阿里云 OSS 数据分析集成（**未接线**：消费路由未注册，无生产调用方；任务目录的 oss.db 与之无关，见 Overview） |
| [VisionAnalysis](cpp/analyzers/VisionAnalysis.md) | 图像/视频视觉 LLM 分析（**死代码**，见上方标注） |

### 核心基础设施（cpp/core/）

| 文档 | 描述 |
|------|------|
| [AnalysisOrchestrator](cpp/core/AnalysisOrchestrator.md) | 分析编排器：调度镜像/内存/Android 逻辑提取等分析工作流（源码位于 `src/AnalysisOrchestrator.*`） |
| [DatabaseManager](cpp/core/DatabaseManager.md) | 案例与任务 SQLite 数据库的创建/访问封装（`src/core/DatabaseManager/`，含 EventExtractor/FileClassifier/FileExtractor 子模块） |
| [EventExtractor](cpp/core/EventExtractor.md) | 从镜像元数据提取时间线事件 |
| [EventCorrelationEngine](cpp/core/EventCorrelationEngine.md) | 时间线事件关联分析引擎（**未接入任务流水线**：`analyzeEventCorrelations()` 无生产调用方，见文档标注） |
| [FileClassifier](cpp/core/FileClassifier.md) | 文件分类：24 个分类（`getCategoryName` 分类表）+ 场景规则 |
| [FileFilter](cpp/core/FileFilter.md) | 场景过滤画像（`config/filter_profiles/`）：产出 `_filtered.db` 副本、raw.db 不动；必须在 SceneDetector 之后运行 |
| [FileExtractor](cpp/core/FileExtractor.md) | 按分类/过滤规则提取文件内容到输出目录 |
| [FullTextSearch](cpp/core/FullTextSearch.md) | Xapian 全文搜索引擎封装 |
| [TOONExporter](cpp/core/TOONExporter.md) | 取证结果导出为 TOON 格式 |
| [ConfigManager](cpp/core/ConfigManager.md) | 运行配置加载（.env/环境变量） |
| [PathManager](cpp/core/PathManager.md) | 输出目录与路径管理 |
| [AuditLog](cpp/core/AuditLog.md) | 取证操作审计日志 |
| [Logger](cpp/core/Logger.md) | 日志系统 |
| [ThreadPool](cpp/core/ThreadPool.md) | 并行分析用线程池 |
| [ErrorHandling](cpp/core/ErrorHandling.md) | 错误码与错误处理工具 |

### 集成模块（cpp/integration/）

| 文档 | 描述 |
|------|------|
| [LLMClient](cpp/integration/LLMClient.md) | OpenAI 兼容 API 的 HTTP 客户端 |
| [ModelRouter](cpp/integration/ModelRouter.md) | 多模型路由（文本/视觉等模型选择策略） |
| [FileAnalyzer](cpp/integration/FileAnalyzer.md) | LLM 驱动的单文件分析器 |
| [MCPIntegration](cpp/integration/MCPIntegration.md) | MCP（Model Context Protocol）协议集成 |
| [AndroidAdbExtractor](cpp/integration/AndroidAdbExtractor.md) | ADB 在线数据提取（**未编入 CMake**，见上方标注） |

### 网络与任务服务（cpp/network/）

| 文档 | 描述 |
|------|------|
| [HTTPServer](cpp/network/HTTPServer.md) | Crow HTTP 服务器：路由注册、静态前端托管（`src/network/HTTPServer/`） |
| [Swagger](cpp/network/Swagger.md) | OpenAPI 文档生成（`src/network/Swagger/`，`/api/docs` Swagger UI） |
| [TaskManager](cpp/network/TaskManager.md) | 异步任务生命周期管理（创建/调度/取消/持久化/看门狗） |
| [SceneDetector](cpp/network/SceneDetector.md) | 从 raw.db 特征路径自动检测场景（ANDROID/WINDOWS/LINUX/SERVER_CLOUD；HTTP 流水线专用） |
| [CaseManager](cpp/network/CaseManager.md) | 跨镜像案例管理 |
| [EventClusterAnalyzer](cpp/network/EventClusterAnalyzer.md) | 事件簇分析器（活跃，供任务流水线生成事件簇） |
| [LLMAnalysisService](cpp/network/LLMAnalysisService.md) | 文件级 LLM 分析服务：FULL/SMART 两种模式（deprecated 标注但仍活跃，见上方标注） |
| [LinuxLLMAnalysisService](cpp/network/LinuxLLMAnalysisService.md) | Linux 工件的 LLM 批量分析服务 |
| [WindowsLLMAnalysisService](cpp/network/WindowsLLMAnalysisService.md) | Windows 工件的 LLM 批量分析服务 |
| [AndroidLLMAnalysisService](cpp/network/AndroidLLMAnalysisService.md) | Android 工件的 LLM 批量分析服务（活跃；与 Linux/Windows 版的差异：有端点可用性门控） |
| [LLMPythonProxy](cpp/network/LLMPythonProxy.md) | 将 C++ 侧 LLM 请求代理给 Python 服务的过渡层 |
| [SQLiteHelper](cpp/network/SQLiteHelper.md) | HTTP 层使用的 SQLite 查询助手 |
| [TaskInfrastructure](cpp/network/TaskInfrastructure.md) | TaskManager 内部支撑组件：任务执行（`TaskManagerAnalysis.cpp`）、持久化、序列化、看门狗 |

### HTTP 路由（cpp/network/routes/）

| 文档 | 描述 |
|------|------|
| [TaskRoutes](cpp/network/routes/TaskRoutes.md) | 任务管理路由：任务 CRUD/批量/监控（由 Task/TaskCRUD/TaskBatch/TaskMonitoring 等路由文件组成） |
| [ForensicsRoutes](cpp/network/routes/ForensicsRoutes.md) | 取证数据路由：时间线、文件列表、平台工件等查询 |
| [SearchRoutes](cpp/network/routes/SearchRoutes.md) | 全文搜索路由（Xapian） |
| [SystemRoutes](cpp/network/routes/SystemRoutes.md) | 系统路由：健康检查、系统信息/事件/文档等 |
| [OSSRoutes](cpp/network/routes/OSSRoutes.md) | 阿里云 OSS 分析路由（**编译但从未注册，运行时不可用**，见上方标注） |
| [CaseRoutes](cpp/network/routes/CaseRoutes.md) | 案例管理路由（`CaseCRUDRoutes.cpp`；前端经 Python `/api/llm/cases` 代理到达，浏览器不直连） |
| [FilterRoutes](cpp/network/routes/FilterRoutes.md) | 过滤配置路由（全服务唯一使用 ApiResponse 封装的路由组） |
| [RouteReference](cpp/network/routes/RouteReference.md) | C++ REST API 路由总览参考 |

### 导出与报告（cpp/export/ 与 cpp/report/）

| 文档 | 描述 |
|------|------|
| [TextDumpExporter](cpp/export/TextDumpExporter.md) | `--dump-text`：提取文件转文本/Markdown 的有界导出（双适配器 + 软上限记账 + 断点续跑） |
| [ReportGenerator](cpp/report/ReportGenerator.md) | `--report`：无 AI 依赖的确定性 Markdown 取证报告（细节章当前仅 Linux 实现） |

### 分布式代理（cpp/http_agent/）

| 文档 | 描述 |
|------|------|
| [HttpAgent](cpp/http_agent/HttpAgent.md) | `tracelens_agent`（独立 CMake 目标）：JWT 轮询 C/S 命令队列、本地执行分析、上传结果/索引；当前仅执行 analyze_disk 命令 |

---

## Python 模块文档（python_service/）

### 顶层（python/）

| 文档 | 描述 |
|------|------|
| [Main](python/Main.md) | `python_service/httpserver/main.py`：FastAPI 应用入口（中间件、路由注册、启动流程） |
| [ServiceManager](python/ServiceManager.md) | 服务生命周期管理（懒加载初始化各服务） |
| [CppBackendClient](python/CppBackendClient.md) | Python 侧调用 C++ 后端 REST API 的客户端封装 |

### Graphiti 集成（python/graphiti/ 与 python/graphiti_integration/）

| 文档 | 描述 |
|------|------|
| [GraphitiIntegration](python/graphiti/GraphitiIntegration.md) | Graphiti 知识图谱集成综合文档（摄取流水线、Neo4j/Graphiti 配置） |
| [GraphitiIngestor](python/graphiti_integration/GraphitiIngestor.md) | 将取证数据作为 Episode 摄入 Graphiti 图谱（`graphiti_ingestor.py` / `file_entity_ingestor.py`） |
| [TOONTransformer](python/graphiti_integration/TOONTransformer.md) | 取证数据到 TOON/Episode 的转换（`toon_transformer.py` / `forensic_episode_transformer.py`） |
| [DatabaseReader](python/graphiti_integration/DatabaseReader.md) | 从取证 SQLite 结果库读取文件/事件数据（`database_reader.py`） |

### HTTP 服务（python/httpserver/）

| 文档 | 描述 |
|------|------|
| [Main](python/httpserver/Main.md) | FastAPI 主程序（`httpserver/main.py`） |
| [HTTPRoutes](python/httpserver/HTTPRoutes.md) | `httpserver/routes/` 路由模块总览 |

#### 路由（python/httpserver/routes/）

| 文档 | 描述 |
|------|------|
| [Health](python/httpserver/routes/Health.md) | 健康检查路由（`routes/health.py`） |
| [Graphiti](python/httpserver/routes/Graphiti.md) | 知识图谱路由（`routes/graphiti.py` 等：图搜索、实体关系） |
| [LLM](python/httpserver/routes/LLM.md) | LLM 分析路由（`routes/llm.py` 等：文件/多模态/DLL 分析） |
| [Database](python/httpserver/routes/Database.md) | 数据库访问路由（`routes/database.py`：文件/事件查询与导出） |
| [Investigation](python/httpserver/routes/Investigation.md) | 二次调查路由（`investigation.py` + `investigation_workbench.py`：快照/分析/评审/事件/证据/图谱 + 工作台） |
| [ForensicReports](python/httpserver/routes/ForensicReports.md) | 取证报告路由（版本化快照、证据绑定、202 生成轮询、叙事版本） |
| [CaseAnalysis](python/httpserver/routes/CaseAnalysis.md) | 案件分析路由（案情描述、410 退役链路、多镜像案件、智能报告） |
| [Markitdown](python/httpserver/routes/Markitdown.md) | 文档转换路由（`markitdown.py` + `office.py`；主调用方是 C++ MarkitdownProxy） |
| [WechatGraph](python/httpserver/routes/WechatGraph.md) | 微信关系图路由（读 android.db，networkx 图分析） |
| [System](python/httpserver/routes/System.md) | 服务日志路由（logs/logs-stream SSE；`system_logs.py` 为未注册死代码） |
| [Associations](python/httpserver/routes/Associations.md) | 事件簇↔文件关联路由（analysis-center 抽屉的数据源） |
| [OssAnalysis](python/httpserver/routes/OssAnalysis.md) | Python 侧 OSS AI 过滤（已注册但无活跃调用方，见文档标注） |

#### 服务（python/httpserver/services/）

| 文档 | 描述 |
|------|------|
| [ServiceManager](python/httpserver/services/ServiceManager.md) | 服务管理器（`services/service_manager.py`） |
| [CppBackendClient](python/httpserver/services/CppBackendClient.md) | C++ 后端客户端（`services/cpp_backend.py`） |

### 服务层（python/services/）

| 文档 | 描述 |
|------|------|
| [GraphitiService](python/services/GraphitiService.md) | Graphiti 服务封装（`services/graphiti_service.py`） |
| [LLMService](python/services/LLMService.md) | LLM 服务（`services/llm_service.py`：文本/视觉模型调用） |
| [ForensicReportService](python/services/ForensicReportService.md) | 取证报告域：A 链确定性快照、R2 链 LLM 叙事、终版报告装配/发布 |
| [InvestigationService](python/services/InvestigationService.md) | 调查域：schema v7 仓储状态机、E1-E11 执行器不变量、证据键与 grounding 规则 |
| [CaseAnalysisService](python/services/CaseAnalysisService.md) | 案件分析：四条流水线（full/multi/smart/incremental）与双模式文件过滤 |
| [IngestionJobManager](python/services/IngestionJobManager.md) | Graphiti 摄取后台任务队列（Redis 持久化 + 内存回退，五模式） |
| [TaskStore](python/services/TaskStore.md) | 任务归属路径解析（D2b fail-closed 数据边界的安全基石） |
| [WeChatGraphService](python/services/WeChatGraphService.md) | 微信关系图服务（networkx 指标/社区/时间线；注意路由层每请求新建实例致缓存失效，见文档标注） |
| [DocumentExtractors](python/services/DocumentExtractors.md) | 文档提取器定位器与回退链（`config/extractor_mapping.json` + markitdown 主路径） |

### 分布式 C/S 服务端（python/server/）

| 文档 | 描述 |
|------|------|
| [Main](python/server/Main.md) | C/S 服务端应用装配（:8091，PostgreSQL + JWT；启动降级语义与双栈共存） |
| [Services](python/server/Services.md) | 四件套：auth（JWT）/command_queue（命令队列）/task_orchestrator/result_aggregator |

### Web 前端（web/）

| 文档 | 描述 |
|------|------|
| [Overview](web/Overview.md) | 前端架构：入口链、三 axios 客户端、vite 代理与分包 |
| [Pages](web/Pages.md) | 23 条路由逐页走读 + 死代码页面与已知问题 |
| [Services](web/Services.md) | 24 个 service 文件的方法↔端点↔消费者三向映射 |
| [Store](web/Store.md) | 7 个 Redux slice 逐个：state/thunk/localStorage |
| [Hooks](web/Hooks.md) | 16 个 hooks：轮询身份绑定模式、死 hooks 标注 |
| [Components](web/Components.md) | 组件库导览：common/reports 渲染器/workbench/抽屉 |
| [I18nTheming](web/I18nTheming.md) | i18n 键表、主题链、设置持久化、日志三通道 |
| [Testing](web/Testing.md) | Vitest 配置与 48 个测试文件解读 |

---

## 阅读建议

- **C++ 后端**：从 [HTTPServer](cpp/network/HTTPServer.md)、[TaskManager](cpp/network/TaskManager.md)、[AnalysisOrchestrator](cpp/core/AnalysisOrchestrator.md) 入手，理解任务从 API 到分析流水线的路径。
- **分析能力**：[ImageAnalyzer](cpp/analyzers/ImageAnalyzer.md) 及各平台/格式分析器。
- **Python 服务**：从 [Main](python/httpserver/Main.md) 入手，再到 Graphiti 摄取与 LLM 服务。
- **报告与调查**：[ForensicReportService](python/services/ForensicReportService.md) → [InvestigationService](python/services/InvestigationService.md)（配合对应路由文档）。
- **分布式 C/S**：[HttpAgent](cpp/http_agent/HttpAgent.md)（取证机侧）+ [server/Main](python/server/Main.md)（服务端侧）。

---

**最后更新**: 2026-08-23（以代码为准重写；同日补齐 27 个此前无文档的子系统）
