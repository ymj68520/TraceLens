# 数据流：一个任务的一生

> 这份文档不讲"有哪些端点/表"（那些在 [API 参考](../api_reference/CPP_REST_API.md) 和 [DatabaseSchema.md](./DatabaseSchema.md)），而是**跟着一个真实的 HTTP 任务从头走到尾**：每一步谁在做、为什么是这个顺序、产出给谁用。所有环节都标注了源码位置（`src/network/HTTPServer/TaskManagerAnalysis.cpp`，下称 `TMA`）。

## 第一幕：任务的诞生

一切从 `POST /api/tasks` 开始。请求体里的每个字段都在影响后面的路怎么走：

- `image_path` 是唯一的必经之路——分析师把证据镜像放在服务器可达的路径上（前端创建任务时浏览选择）；
- `case_description` 会进入 LLM 提示词，让模型带着案情上下文去读文件（"这是一起电信诈骗案"和"这是一次入侵排查"会让同一批文件得到不同深度的描述）；
- `scenarios` 可以不填——后面你会看到系统会自己猜；
- `filter_profile`（如 `telecom_fraud`）决定几十万个文件里哪些值得进入后续分析；
- `llm_mode`（full/smart）、`backup_password`、`android_source`、`xfs_mode` 等都是给特定阶段的"通行证"。

路由层（`TaskCRUDRoutes.cpp`）校验后交给 `TaskManager::create_task`：任务获得 ID、状态 `pending`（HTTP 层全部小写），被塞进队列，工作线程从 `ThreadPool`（默认 4 线程）里把它取出来的那一刻，状态变 `running`，好戏开场（`TMA:26 start_analysis`）。从这一刻起到任务终结，`TaskPersistence` 会把每次状态变化节流写入 `data/tasks.json`——所以即使进程崩溃重启，任务列表也不会丢（重启时未完成任务被标记为 failed，这是诚实的处理：进度无法恢复，就不假装还在跑）。

前端看到的进度百分比来自一个简单的加权累计。`TaskManager.cpp:545` 的权重表是唯一权威：

```cpp
int TaskManager::calculate_overall_percentage(TaskPhase phase, int phase_percentage) {
    std::map<TaskPhase, int> phase_weights = {
        {TaskPhase::INITIALIZING, 5},
        {TaskPhase::IMAGE_ANALYSIS, 25},
        {TaskPhase::EVENT_EXTRACTION, 10},
        {TaskPhase::FILE_CLASSIFICATION, 15},
        {TaskPhase::LLM_ANALYSIS, 20},
        {TaskPhase::PLATFORM_ANALYSIS, 20},
        {TaskPhase::FILE_CARVING, 3},
        {TaskPhase::FINALIZING, 2}
    };
    int total_percentage = 0;
    for (const auto& p : phase_weights) {
        if (p.first < phase) total_percentage += p.second;          // 已完成阶段：整份权重
        else if (p.first == phase) total_percentage += (p.second * phase_percentage) / 100;  // 当前阶段：按比例
    }
    return std::min(total_percentage, 100);
}
```

逐块读：`std::map` 按枚举值有序遍历，天然形成"扫过已完成阶段、在当前阶段按比例折算"的累计逻辑；权重之和恰好 100（5+25+10+15+20+20+3+2），所以 `min(..., 100)` 只是防御。两个隐含约定值得知道：其一，阶段推进调用 `update_progress(task_id, phase, pct, msg)` 时**先加锁更新 tasks_ 表再触发落盘**，进度条不会回跳；其二，FILE_CARVING 只有 3%——雕刻是可选的尾部步骤，设计上不让它左右总进度的体感。

## 第二幕：解析——建立唯一的事实来源

第一阶段 `IMAGE_ANALYSIS`（占整体进度 25%，最重的一环）由 [ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) 负责：它打开镜像（E01 或 DD）、枚举分区、对每个可识别的文件系统（NTFS/FAT/EXT2/3/4/XFS）逐文件读出元数据——路径、大小、四个时间戳、是否已删除——全部写入 `raw.db` 的 `files` 和 `partitions` 表（`TMA:203-225`）。

这一步的哲学是**忠实**：不做任何判断、不过滤、不翻译，文件系统说什么就记什么。raw.db 因此成为整个任务唯一的"事实来源"——后面所有层都是从它派生的观点，任何结论存疑时回到这里对质。

紧接着是一个容易被忽略但顺序讲究的步骤：**场景自动检测**（`TMA:227-259`）。如果创建任务时没选 `scenarios`，`SceneDetector` 会扫一遍 raw.db 里的特征路径（比如 `/data/app` 意味着 Android，`Windows/System32/config` 意味着 Windows）。源码注释解释了为什么它必须跑在过滤**之前**：过滤配置的职责恰恰是丢弃"系统噪音"，而场景特征路径就是系统路径——先过滤再检测，证据就被自己人扔掉了。核心几行：

```cpp
// 1.4b. Auto-detect platform scenarios when the user did not pick any.
// Probes the *un-filtered* raw DB for tell-tale artifact paths and
// back-fills task.scenarios so downstream classification / platform
// analyzers run against the right OS. Must run before the filter,
// since filter profiles drop system-noise — exactly these markers.
if (task.scenarios.empty()) {
    SceneDetection detection = detectScenes(rawDbPath);
    if (detection.ok && !detection.detected.empty()) {
        {
            std::lock_guard<std::mutex> lock(mtx_);
            if (tasks_.count(task_id)) {
                tasks_[task_id].scenarios = detection.detected;   // 回填到任务对象
                task.scenarios = detection.detected;
            }
        }
        // Record the detection for traceability (which platforms,
        // and how many marker files each matched).
        ...
        add_audit_log(task_id, "SCENE_DETECTED", "Auto-detected scenarios: " + detail);
    }
}
```

逐块读：检测跑在**原始** raw.db 上（注释第一句特意强调 un-filtered）；检测结果在互斥锁内同时回填到共享的 `tasks_` 表和本次执行的局部 `task` 副本——前者让前端立即看到，后者驱动本流水线后续的平台分支；最后强制写一条 `SCENE_DETECTED` 审计日志，附带每个场景命中的特征文件数。也就是说"系统替你做了判断"这件事本身是可追溯、可复核的——这是取证工具的纪律。

## 第三幕：过滤与提炼——从"全部文件"到"值得看的文件"

如果任务指定了 `filter_profile`，`FileFilter`（`TMA:261-298`）按 `config/filter_profiles/` 下的画像（扩展名、路径模式、大小、是否已删除……）从 raw.db **复制**出一个 `<...>_filtered.db`——注意不是修改原库，raw.db 永远保持完整；过滤只是决定"下游用哪个视角"。之后的事件提取和分类都以这个过滤后的库为输入（任务对象上的 `output_raw_db` 字段被更新为过滤库路径，前端展示的也是它）。关键几行：

```cpp
FileFilter filter;
std::string filteredDbPath = rawDbPath;
size_t pos = filteredDbPath.rfind("_raw.db");
if (pos != std::string::npos) {
    filteredDbPath.replace(pos, 7, "_filtered.db");     // raw.db → filtered.db 命名约定
}
auto filterStats = filter.applyFilterByName(rawDbPath, filteredDbPath, task.filter_profile);
if (filterStats.included_files > 0) {
    effectiveRawDb = filteredDbPath;                     // 下游全部改读过滤库
    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10,
        "Filter applied: " + std::to_string(filterStats.included_files) + "/" +
        std::to_string(filterStats.total_files) + " files selected");
} else {
    std::cerr << "Warning: Filter excluded all files for task " << task_id << std::endl;
}
...
if (effectiveRawDb != rawDbPath) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(task_id)) tasks_[task_id].output_raw_db = effectiveRawDb;
}
```

逐块读：过滤结果是一个**新文件**而不是原库上的 DELETE——这是"raw.db 不可变"纪律的落实，换过滤画像重跑只需重新复制；`effectiveRawDb` 局部变量让本流水线后续阶段立即切换数据源，而 `output_raw_db` 回填让**前端和 Python 服务**也能发现过滤库（D2b 的任务库发现按后缀约定找 `_raw.db`/`_filtered.db`）；一个诚实的边界：如果画像把所有文件都筛掉了，代码只打警告并**继续用未过滤库**跑——宁可全量分析也不产出空结果，这个取舍值得知道。

然后是两步"翻译"：

- **事件提取**（`EVENT_EXTRACTION`，10%）：[EventExtractor](../modules/cpp/core/EventExtractor.md) 读出每个文件的 atime/mtime/ctime/crtime 四个时间戳，翻译成 CREATED/MODIFIED/ACCESSED/CHANGED/DELETED 五类事件，写入 `events.db`（`TMA:300-309`）。从此"文件系统的一堆数字"变成了"某时刻发生了某事"的时间线。
- **文件分类**（`FILE_CLASSIFICATION`，15%）：[FileClassifier](../modules/cpp/core/FileClassifier.md) 把每个常规文件按扩展名/内容特征归入 24 个类别之一，写入 `files.db` 的主表和对应分类表；同时按场景标注 `scene_priority`——同一个 `hosts` 文件在入侵排查里优先级高、在电信诈骗里不重要，这就是"场景感知分类"（`TMA:311-332`，第一个场景被映射为分类器的 SceneType）。

## 第四幕：智能增强——LLM 什么时候进来

只要 `llm_analyze` 为真（前端固定传 true），`LLM_ANALYSIS` 阶段（20%）开始，注意它其实是**先后两件事**：

1. **文件级描述**（`TMA:334-386`）：[LLMAnalysisService](../modules/cpp/network/LLMAnalysisService.md) 把分类后的文件逐个（必要时先从镜像提取内容）送给 LLM，生成摘要/描述/关键词，写回 files.db 的 `llm_*` 列和 `file_descriptions` 表。full 模式全量分析；smart 模式先让模型粗选一批"值得深挖"的文件再精析——这是成本与覆盖的取舍旋钮。一个例外值得知道：Android 逻辑提取路径（`--android-source` 类任务）的工件级 LLM 在 `analyzeAndroidData()` 内部就完成了（`AndroidLLMAnalysisService`），文件级服务对 android.db 没有 `files` 表可写、实际空转，代码注释（`TMA:164-171`）明确说明了这层分工。
2. **事件簇分析**（`TMA:396-429`）：时间线事件先按时间邻近聚簇，`EventClusterAnalyzer` 让 LLM 对每个簇回答"这段时间发生了什么"。限额由 `LLM_MAX_EVENT_CLUSTERS` 控制（0 = 不限）。

## 第五幕：平台语义化——把字节变成"一条聊天记录"

`PLATFORM_ANALYSIS`（20%）是取证价值最密集的一步。按检测出的场景**依次**运行平台分析器（`TMA:440-526`，多场景任务按顺序执行，进度按场景数折算）：

- [AndroidAnalyzer](../modules/cpp/analyzers/AndroidAnalyzer.md)：找到短信/联系人/通话/Chrome 历史/已装应用数据库逐表解析；微信库是 SQLCipher 加密的，用 `--backup-password` 提供的密钥解密；MIUI 备份走 manifest+tar 索引；QQNT 走专用工件解析。产出 `android.db`（33 张表）。
- [WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md)：注册表（hivex）、事件日志（libevtx）、Prefetch/LNK/JumpList/Amcache/SRUM/MFT/浏览器……产出 `windows.db`（32 张表；Shimcache/UserAssist/RDP/WiFi 解析器已实现但未接线，对应表恒空）。
- [LinuxFilesAnalyzer](../modules/cpp/analyzers/LinuxFilesAnalyzer.md)：syslog/journal/auditd、账户与登录、Shell 历史、13 种持久化机制检测、容器、Web 服务器、攻击链与异常分析，产出 `linux.db`（73 张表）。SERVER_CLOUD 场景也由它处理（`analyzeServerCloudArtifacts`），工件写入 `oss.db`——文件名容易误会成阿里云 OSS 分析，实际是服务器/云场景的 Linux 工件库。

每个平台分析器内部还会调用自己的 LLM 服务（`Linux/Windows/AndroidLLMAnalysisService`）对工件做语义标注——注意这与第四幕的文件级 LLM 是两回事：那里读"文件"，这里读"已经解析成取证工件的记录"。

如果任务开了雕刻（`file_carving`），`FILE_CARVING`（3%）用 29 种文件签名扫未分配空间，恢复的文件放进任务目录的 `carved_files/`（`TMA:533-550`）。

## 第六幕：收尾——完成不等于结束

`FINALIZING`（2%）做两件事（`TMA:170-196`）：把进度推到 100%、状态置 `completed`；以及**触发知识图谱摄取**——通过 `LLMPythonProxy::async_ingest(task_id, FULL)` 调 Python 的 `/api/graphiti/ingest`，拿到 job id 存在任务对象上（前端知识图谱页可以拿它查进度）。真实代码：

```cpp
// Graphiti ingestion (best-effort, fire-and-forget) — same as the
// TSK pipeline tail so logical tasks join the knowledge graph too.
update_progress(task_id, TaskPhase::FINALIZING, 10, "Triggering knowledge graph ingestion...");
try {
    auto& proxy = forensics::LLMPythonProxy::instance();
    std::string graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);
    if (!graphiti_job_id.empty()) {
        add_audit_log(task_id, "GRAPHITI_INGESTION",
            "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");
        {
            std::lock_guard<std::mutex> lock(mtx_);
            if (tasks_.count(task_id)) tasks_[task_id].graphiti_job_id = graphiti_job_id;
        }
        save_tasks_internal();      // 立即落盘，job id 不因重启丢失
    }
} catch (const std::exception& e) {
    std::cerr << "Warning: Exception triggering Graphiti ingestion: " << e.what() << std::endl;
}
```

逐块读：注释明说这是 best-effort、fire-and-forget——`async_ingest` 只提交作业就返回，不等摄取完成；整段被 try/catch 包住且 catch 只打警告，**Python/Neo4j 不可用时任务照样 `completed`**，图谱只是缺席；job id 会立即写审计日志并同步进 `tasks_` + 落盘（`save_tasks_internal()`），所以重启后前端仍能查到这次摄取作业。这个设计把"分析"和"图谱"的故障域彻底分离——代价是图谱缺席时界面上要靠用户主动发现，好在知识图谱页会显示 job 状态。

## 任务之后：产出物给谁用

任务完成后，`data/tasks/<task_id>/` 是一个自包含的证据包。理解"谁读什么"就理解了整个上层建筑：

| 产出 | C++ 路由 | 前端页面 | Python 侧消费者 |
|------|---------|---------|----------------|
| `raw.db` | 文件/统计类查询（经 SQLiteHelper） | /files、/statistics | CppBackendService 回查、Graphiti DatabaseReader |
| `events.db` | 时间线 11 个端点、事件导出 | /timeline | 案件多镜像分析读事件 |
| `files.db` | 文件分析端点 | /files、/analysis-center | LLMService 持久化重分析结果（直接 UPDATE llm_* 列）、报告生成、Graphiti 摄取 |
| `android.db` 等 | 平台端点（如 android 14 个） | /android、/wechat-graph | WeChatGraphService（直接 sqlite3 读 android.db）、Graphiti 平台 reader |
| `extracted_files/` | 提取状态端点 | /files 提取下载 | markitdown 转换输入（task_store 精确匹配路径） |

值得一提的是 Python 侧读任务库的方式：`task_store` 以任务 ID 解析出精确路径（fail-closed，拒绝任何不匹配的路径），这保证"服务间共享文件系统"不会变成越权读任意文件的漏洞——这是 2026 年加固的边界（docs/hardening/d2b）。

## 失败、取消与看门狗

流水线在每个阶段边界检查 `cancellation_requested` 原子标志（取消即置位，任务以 `cancelled` 终止，不再有后续写入——任务删除后写保护也依赖这个语义）。任何阶段返回失败，任务立即 `failed` 并记录原因；由于产出都在任务目录里，失败的垃圾不会污染其他任务。`TaskWatchdog` 后台线程持续轮询（注释写"每 60 秒"，实现实际每 1 秒醒一次，`TaskWatchdog.cpp:38-43`），把超过 `TASK_WATCHDOG_STALE_MINUTES`（RUNNING，默认 30 分钟）无进度更新或超过 `TASK_WATCHDOG_PENDING_MINUTES`（PENDING，默认 30 分钟）未被调度的任务标记失败——这是给"线程死了但没人知道"兜底。

## CLI 模式：同一台发动机的另一个方向盘

CLI（`./forensic_analyzer 镜像` → `AnalysisOrchestrator`）复用完全相同的分析器，差异只在编排层：同步执行、无进度/取消/看门狗、输出库放镜像旁边（`<镜像>_raw.db`...）、平台工件**并入** `<镜像>_files.db` 而不是独立库。为什么不同？HTTP 模式的任务目录隔离是给并发和多消费者准备的；CLI 面对的是"一个镜像一次跑完"的脚本场景，并入单库更顺手。这也意味着**给 CLI 写的消费工具不能假设平台工件在独立库里**——两个模式的库布局是 documented 行为，不是 bug。

另有独立子命令绕过主流水线直达单点能力：`--carve`（只雕刻）、`--index/--search`（只建索引/搜索）、`--extract-*`（只提取）、`--analyze-dlls`、`--memory-analyze`（Volatility3 子进程 → `<镜像>_memory.db`）、`--report`（Markdown 报告）、`--dump-text`。

## C/S 分布式：镜像不动，命令流动

本地模式假设"镜像就在这台机器上"；当取证机分布在多地时，TraceLens 用**反过来**的思路：镜像不动，让计算去镜像那里。

叙事是这样的：管理员在 `server`（:8091，PostgreSQL）上建组织、发注册令牌；取证机上的 `tracelens_agent`（`src/http_agent/`）凭令牌注册成客户端，拿到自己的 JWT，然后进入轮询循环——从 `/api/commands/poll` 领命令（如 `analyze_disk`），**在本地**调 `forensic_analyzer` 执行（复用上面讲的整条流水线），把产出的数据库和索引用 `result_uploader`/`index_uploader` 传回服务端（写入 `analysis_results`，镜像目录索引写入 `disk_images`），期间 `status_reporter` 持续汇报状态。服务端的表（organizations/clients/command_queue/analysis_tasks/analysis_results 等 10 张，`migrations/postgresql/`）就是这条故事线的角色表。

```
运营方 ──建组织/发令牌──► server(:8091, PG)
                            ▲   │ 命令(队列)          ┌────────── 取证机 ──────────┐
                            │   ▼                    │ tracelens_agent（JWT 轮询） │
                            └── 结果/索引/状态 ◄──────┤   └─本地─ forensic_analyzer │
                                                   └────────────────────────────┘
```

## 相关文档

- **[Overview.md](./Overview.md)** —— 心智模型与设计动机（建议先读）
- **[DatabaseSchema.md](./DatabaseSchema.md)** —— 各库表清单
- **[模块文档](../modules/README.md)** —— 流水线每个环节的深入讲解

---

**最后更新**: 2026-08-23（技术深化：叙事主线保留，补 4 段核心源码逐块走读）
