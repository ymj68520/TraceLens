# TraceLens 模块文档索引

## 说明

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
| [TaskManager](cpp/network/TaskManager.md) | 异步任务生命周期管理（创建/调度/取消/持久化/看门狗） |
| [CaseManager](cpp/network/CaseManager.md) | 跨镜像案例管理 |
| [EventClusterAnalyzer](cpp/network/EventClusterAnalyzer.md) | 事件簇分析器（活跃，供任务流水线生成事件簇） |
| [LLMAnalysisService](cpp/network/LLMAnalysisService.md) | 文件级 LLM 分析服务：FULL/SMART 两种模式（deprecated 标注但仍活跃，见上方标注） |
| [LinuxLLMAnalysisService](cpp/network/LinuxLLMAnalysisService.md) | Linux 工件的 LLM 批量分析服务 |
| [WindowsLLMAnalysisService](cpp/network/WindowsLLMAnalysisService.md) | Windows 工件的 LLM 批量分析服务 |
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
| [RouteReference](cpp/network/routes/RouteReference.md) | C++ REST API 路由总览参考 |

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
| [LLM](python/httpserver/routes/LLM.md) | LLM 分析路由（`routes/llm.py` 等：文件/多模态分析） |
| [Database](python/httpserver/routes/Database.md) | 数据库访问路由（`routes/database.py`：文件/事件查询与导出） |

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

---

## 阅读建议

- **C++ 后端**：从 [HTTPServer](cpp/network/HTTPServer.md)、[TaskManager](cpp/network/TaskManager.md)、[AnalysisOrchestrator](cpp/core/AnalysisOrchestrator.md) 入手，理解任务从 API 到分析流水线的路径。
- **分析能力**：[ImageAnalyzer](cpp/analyzers/ImageAnalyzer.md) 及各平台/格式分析器。
- **Python 服务**：从 [Main](python/httpserver/Main.md) 入手，再到 Graphiti 摄取与 LLM 服务。

---

**最后更新**: 2026-08-23（以代码为准重写）
