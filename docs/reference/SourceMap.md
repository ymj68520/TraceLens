# 源码导览：从哪个文件开始读

> 这是“文件级地图”，不是把目录树原样抄一遍。每组先说明运行时责任，再列推荐阅读顺序、入口文件、关键实现和下一跳。想从一个问题跳进代码时，按表查；想理解完整生命周期，先读 [Overview](../architecture/Overview.md) → [DataFlow](../architecture/DataFlow.md) → 本文。

## 1. 可执行入口

| 文件 | 入口/责任 | 下一跳 |
|---|---|---|
| `src/main.cpp` | PathManager/ConfigManager/AuditLog 初始化，CLI 分派 | CommandLineParser、AnalysisOrchestrator、HTTPServer |
| `src/CommandLineParser.cpp` | 参数解析、usage、输入校验 | AnalysisOrchestrator |
| `src/AnalysisOrchestrator.cpp` | CLI 各模式编排 | ImageAnalyzer/EventExtractor/FileClassifier/专项旁路 |
| `src/http_agent/http_agent_main.cpp` | 独立 agent 入口、`--once` | HttpAgentService、Poller |
| `python_service/httpserver/main.py` | 本地 FastAPI 应用 | ServiceManager、routes |
| `python_service/server/main.py` | C/S FastAPI 应用 | init_db、api routers、JWT |
| `web/src/index.jsx` | React Provider 链 | App、routes |
| `web/src/routes.jsx` | createBrowserRouter 路由表 | pages |

### CLI 调用链

```text
main.cpp
  ├─ --http-server → AnalysisOrchestrator::runHTTPServer → HTTPServer
  ├─ --index/--search → FullTextSearch
  ├─ --memory-analyze → MemoryAnalyzer（提前 return，CLI 旁路）
  ├─ --analyze-dlls → DLLAnalyzer
  ├─ --report → ReportGenerator
  ├─ --dump-text → TextDumpExporter
  └─ 默认 → AnalysisOrchestrator::runFullAnalysis
                 ├─ ImageAnalyzer
                 ├─ EventExtractor
                 ├─ FileClassifier
                 └─ 平台专项/LLM/报告
```

阅读 CLI 时重点关注 `parse()` 的参数状态如何传到 `AnalysisArguments`，再追 `AnalysisOrchestrator` 的分支；不要只看 printUsage，曾有 `--dll-threshold`/`--overwrite` 已解析但无消费者的情况。

## 2. HTTP 任务链

| 阅读顺序 | 文件 | 要回答的问题 |
|---:|---|---|
| 1 | `src/network/HTTPServer/HTTPserver.cpp` | 服务怎么启动、路由组怎么注册、SPA 怎么托管 |
| 2 | `routes/TaskCRUDRoutes.cpp` | 创建请求体哪些字段真的被读 |
| 3 | `TaskManager.cpp` | 状态、锁、进度、删除边界在哪里 |
| 4 | `TaskManagerAnalysis.cpp` | 八阶段的真实执行顺序 |
| 5 | `TaskPersistence.cpp` | 重启恢复和 tasks.json 形态 |
| 6 | `TaskWatchdog.cpp` | PENDING/RUNNING 如何判僵死 |
| 7 | `TaskSerialization.cpp` | 内存枚举如何变成 JSON |
| 8 | `SQLiteHelper.cpp` + `Queries/` | 前端查询实际落哪张表 |

### 任务对象的追踪方法

1. 搜 `struct AnalysisTask` 找字段声明；
2. 搜 `handle_create_task` 找请求字段解析；
3. 搜 `to_json/from_json` 找持久化键；
4. 搜 `tasks_[task_id]` 找运行时写入；
5. 搜前端 `taskService` 找客户端字段；
6. 若 5 个位置不一致，先写契约修复测试再改。

## 3. 核心库边界

### 3.1 ImageAnalyzer

| 文件 | 责任 |
|---|---|
| `ImageAnalyzer.h` | 外部接口与分析状态 |
| `ImageAnalyzer.cpp` | 主初始化/选择后端 |
| `TskFilesystemWalker.*` | TSK 文件系统遍历 |
| `NativeFilesystemWalker.*` | 本机挂载/XFS native 路径 |
| `XFSHelper.*` | XFS pure/native 辅助 |
| `DecryptionModule.*` | LUKS/BitLocker/VeraCrypt 外挂解密 |
| `KeyFileLoader.*` | key-dir/key-password 输入 |
| `ImageAnalyzerDataTypes.h` | PartitionEntry/FileRecord 等数据形态 |

读完后转 [RawDB](../schema/RawDB.md)，确认每个字段在哪里落库。

### 3.2 DatabaseManager

| 文件/目录 | 责任 |
|---|---|
| `DatabaseManager.*` | raw.db files/partitions 建表、插入、查询 |
| `DatabaseManagerDataTypes.h` | FileRecord/PartitionInfo |
| `SQL/*.h` | schema 常量（SQL-as-headers） |
| `FileExtractor/` | 按 inode/path/partition 提取安全文件 |
| `FileClassifier/` | 24 类判定、场景优先级 |
| `EventExtractor/` | 时间戳→事件 |

注意 `src/core/DatabaseManager/EventCorrelationEngine/` 是遗留撞名目录；真正引擎在 `src/core/EventCorrelationEngine/`。

### 3.3 EventExtractor

| 文件 | 重点 |
|---|---|
| `EventExtractorCore.cpp` | ATTACH/抽取/标准化主流程 |
| `FileSystemEventExtractor.cpp` | 创建/修改/访问/删除来源 |
| `SystemEventExtractor.cpp` | 系统事件 |
| `EventCorrelationExtractor.cpp` | extractor 版关联表（生产写入） |
| `event_extractor_sql.h` | events 表、类型表、视图、索引 |

这里要特别区分：生产 `events` 主线与未接线 EventCorrelationEngine 不是一条路径。

### 3.4 FileClassifier 与 FileFilter

| 组件 | 入口 | 核心逻辑 | 产出 |
|---|---|---|---|
| FileClassifier | `FileClassifier.cpp::determineCategory` | encryption→filename→metadata→path→extension 短路 | files.db 主表+24 分表 |
| SceneRules | `FileClassifier_SceneRules.cpp` | 场景 priority/relevant | scene_* 列 |
| FileFilter | `FileFilter.cpp::applyFilterByName` | include/exclude/combine_mode | `_filtered.db` 副本 |
| Profiles | `config/filter_profiles/*.json` | 案情规则数据 | 过滤选择 |

阅读分类时不要从旧的 `FileClassifierTypes.h` 13 值枚举开始——实际 24 值名称表在 `FileClassifier.cpp`。

## 4. 平台分析器阅读顺序

### 4.1 Android

```text
AndroidAnalyzer.h
  → AndroidAnalyzerCore.cpp
      → AndroidSourceMode 分流
          ├─ TSK / IFileExtractor
          ├─ LogicalDirExtractor
          ├─ ZipArchiveExtractor
          └─ MiuiBackupExtractor → MiuiBackupManifest/TarIndex
      → AndroidDataParsers/SystemParsers/LogicalParsers
      → WechatDecryptor/SqlCipherDatabase
      → AndroidAnalysisDatabase
      → AndroidLLMAnalysisService
```

| 想理解 | 从哪里读 |
|---|---|
| 四种数据源 | `IFileExtractor.h`、`LogicalDirExtractor.*`、`ZipArchiveExtractor.*` |
| MIUI | `MiuiBackupManifest.*`、`AndroidBackupHeader.*`、`TarIndex.*` |
| 微信解密 | `WeChatDecryptor.*`、`SqlCipherDatabase.*` |
| 应用工件 | `WechatArtifactParsers.*`、`QqntArtifactParsers.*`、`MiuiArtifactParsers.*` |
| 表与查询 | `AndroidAnalysisDatabase.*`、`SQL/android_analysis_sql*.h` |

### 4.2 Windows

```text
WindowsFilesAnalyzerCore.cpp
  → queryFilesByPattern（镜像内路径筛选）
  → extractFileToPath（任务临时文件）
  → Parsers（hivex/libevtx/自定义格式）
  → WindowsAnalysisDatabase/WindowsDBOperations_*.cpp
  → WindowsLLMAnalysisService
```

| 工件 | 解析入口 | 数据库操作 |
|---|---|---|
| Registry | `WindowsRegistryParser.cpp`/Artifacts | `WindowsDBOperations_Registry.cpp` |
| EVTX | `WindowsEventLogParser.cpp` | `WindowsDBOperations_EventLog.cpp` |
| Prefetch | `WindowsPrefetchParser.*` | `WindowsDBOperations_Prefetch.cpp` |
| LNK/JumpList | 对应 Parser | `WindowsDBOperations_Lnk.cpp` |
| Browser | Chromium/Firefox parser | `WindowsDBOperations_Browser.cpp` |
| System | services/users/MFT | `WindowsDBOperations_System.cpp` |
| DLL | `DLLAnalyzer` 调用 | dll_* 表 |

Shimcache/UserAssist/RDP/WiFi 的 parser 文件存在不等于流水线调用——先搜 `WindowsFilesAnalyzerCore.cpp` 的调用点。

### 4.3 Linux

Linux 的阅读难度来自“解析很多、推理更多”。推荐顺序：

1. `LinuxFilesAnalyzerCore.cpp` 看 21 个 Phase；
2. `Parsers/` 看原始日志/账户/历史如何落库；
3. `Analysis/` 看 LogCorrelation、Timeline、Anomaly、Tampering、RuleEngine；
4. `Database/Detail/` 看每类 CRUD；
5. `SQL/linux_analysis_sql_tables.h` 对照 73 表；
6. `LinuxLLMAnalysisService*` 看哪些表进入 LLM。

重要：LLM SQL 头文件中有七类 SELECT 列名漂移，读取时必须以建表 SQL 为真。

## 5. LLM 与文档转换边界

| 问题 | 入口 | 下一跳 | 持久化 |
|---|---|---|---|
| 文件描述 | network `LLMAnalysisService` | integration `FileAnalyzer`→LLMClient | files.db llm_* + descriptions |
| 平台工件 | Linux/Windows/Android LLM service | ModelRouter→LLMClient | 平台库 LLM 列 |
| 簇叙事 | EventClusterAnalyzer | ModelRouter | events.db LLM 列 |
| Office | OfficeAnalyzer | Python `/api/office/parse`/markitdown | Markdown/preview |
| Text dump | TextDumpExporter | FileExtractor + Markitdown adapter | dump 目录 |
| 图谱 | LLMPythonProxy | Python `/api/graphiti/*` | Neo4j |

`integration/LLMClient` 是出站协议层；`network/LLMAnalysisService` 是业务编排层；Python `LLMService` 是另一条业务编排链，三者不要混称“LLM 模块”。

## 6. Python 服务阅读顺序

```text
httpserver/main.py
  → ServiceManager.initialize
      → CppBackendService
      → ForensicReportService
      → GraphitiService
      → LLMService
      → executors / ingestion / migration
  → routes/*.py
      → service mixins
          → sqlite/Neo4j/外部端点
```

| 目标 | 首读文件 | 再读 |
|---|---|---|
| 启动/降级 | `services/service_manager.py` | routes/health.py |
| C++ 通道 | `services/cpp_backend.py` | web/src/services/api.js |
| 图谱任务 | `services/graphiti_service.py` | graphiti_parts/_ingest.py、ingestor |
| 报告 | `services/forensic_report/*` | routes/forensic_reports.py |
| 调查 | investigation_service/parts | routes/investigation*.py |
| 数据边界 | task_store.py | markitdown/LLM 持久化调用方 |
| C/S | server/main.py | server/services/*.py、src/http_agent |

## 7. 前端阅读顺序

1. `web/src/index.jsx`：Provider 链；
2. `App.jsx`：ErrorBoundary/Layout；
3. `routes.jsx`：真正可达页面；
4. `services/api.js`：三 axios client；
5. `store/index.js`：七 slices；
6. `pages/Tasks.jsx`：最完整的任务状态流；
7. `pages/Investigation/Investigation.jsx`：调查工作台当前实现；
8. `pages/CaseIntelligence.jsx`：报告/智能报告双面；
9. `hooks/*Polling*`：异步状态与过期响应守卫。

页面文件存在但没有路由的组件不要当作产品入口：InvestigationGraph、Logs、LLMDescriptions、旧 Investigation shell 都在 [web/Pages](../modules/web/Pages.md) 标为死代码。

## 8. 如何追一条字段

```text
前端输入
  → web/src/services/<service>.js
  → vite proxy / baseURL
  → C++ route 或 Python route Pydantic model
  → service / TaskManager / SQLiteHelper
  → SQL schema + INSERT/UPDATE
  → response serializer
  → Redux slice / hook
  → 页面渲染
```

每条字段至少查六层。只查一个 handler 就宣布契约，正是旧文档出现“参数名字对但不生效”的原因。

## 9. 导览结论

- 想知道**发生什么**：DataFlow；
- 想知道**为什么这样**：DesignDecisions；
- 想知道**列是什么**：schema/；
- 想知道**端点是什么**：EndpointsFlat/API 参考；
- 想知道**怎么操作**：tutorials/；
- 想知道**怎么跑稳**：ops/；
- 想知道**改哪里**：本文 + 模块文档常见配方；
- 想知道**改坏怎么证**：FailureEvidenceMatrix/Testing。

---


## 10. 快速查找命令

| 想找 | 命令 |
|---|---|
| 哪些地方创建表 | `rg 'CREATE TABLE' src/core/DatabaseManager/SQL src/analyzers` |
| 谁写某张表 | `rg 'INSERT INTO .*table_name|INSERT_.*TABLE' src` |
| 谁读某列 | `rg 'SELECT .*column_name|column_name' src python_service` |
| 某端点注册在哪 | `rg 'CROW_ROUTE|@router\.(get|post|put|delete)' src python_service` |
| 前端谁调用端点 | `rg 'api\.(get|post)|pythonApi\.(get|post)' web/src` |
| 某配置是否接线 | `rg 'get\("NAME"|getenv\("NAME"|NAME' src python_service web` |
| 某类生产调用方 | `rg 'ClassName\(|make_unique<ClassName>|shared_ptr<ClassName>' src` |
| 某测试是否收录 | `rg 'add_test|add_executable|pytest' tests CMakeLists.txt python_service` |

### 10.1 查“只在文档出现”的假功能

```bash
# 名字出现在文档但源码没有引用的候选（人工复核）
rg -l 'FeatureName' docs | while read f; do
  rg -q 'FeatureName' src python_service web || printf 'doc-only: %s\n' "$f"
done
```

注意：文档中的旧名、死代码说明、测试 fixture 都会制造假阳性；命令只用于建立候选，不是自动判定。

### 10.2 查“只在源码出现”的新模块

```bash
find src python_service web/src -type f \
  \( -name '*.cpp' -o -name '*.h' -o -name '*.py' -o -name '*.jsx' \) \
  | sort > /tmp/source-files
find docs/modules docs/schema docs/reference -type f -name '*.md' \
  | sort > /tmp/doc-files
```

然后按目录对照：新增源码目录应有模块索引条目；新增路由应有 API 参考；新增 SQL 表应有 schema 字段参考；新增前端页面应有 Pages/Services 映射。

### 10.3 读代码的五个锚点

每个新功能至少留下五种锚点：

1. **入口锚点**：谁触发（CLI/route/lifespan/hook）；
2. **数据锚点**：输入结构或请求模型；
3. **执行锚点**：核心函数/状态机；
4. **存储锚点**：表、文件、Neo4j group 或 PG 行；
5. **验证锚点**：测试目标、验收 profile 或可复现 curl。

模块文档若只给出第 3 个锚点，读者能看到实现但不能知道如何使用；只给第 1/2 个锚点，读者只能看到接口而无法解释失败。

## 11. 新功能文档最小包

```text
docs/modules/<layer>/<Feature>.md       # 为什么/位置/代码走读/注意
 docs/reference/ 或 schema/              # 字段/契约/参数（如适用）
docs/testing/ 或对应测试文件             # 如何验证
docs/tutorials/                          # 分析师实际使用（如用户可见）
docs/ops/                                # 需要运维旋钮/外部服务（如适用）
```

不要求每个小修复创建五个文件，但要有一个明确的“事实落点”。大型功能只更新 README 是不够的：README 负责入口，模块文档负责理解，参考手册负责精确值，教程负责操作。

---

**最后更新**: 2026-08-24（新建：源码导览）
