# 数据流：一个任务的一生

> 这份文档不讲"有哪些端点/表"（那些在 [API 参考](../api_reference/CPP_REST_API.md) 和 [DatabaseSchema.md](./DatabaseSchema.md)），而是**跟着一个真实的 HTTP 任务从头走到尾**：每一步谁在做、为什么是这个顺序、产出给谁用。所有环节都标注了源码位置（`src/network/HTTPServer/TaskManagerAnalysis.cpp`，下称 `TMA`）。

## 第一幕：任务的诞生

一切从 `POST /api/tasks` 开始。请求体里的每个字段都在影响后面的路怎么走：

- `image_path` 是唯一的必经之路——分析师把证据镜像放在服务器可达的路径上（前端创建任务时浏览选择）；
- `case_description` 会进入 LLM 提示词，让模型带着案情上下文去读文件（"这是一起电信诈骗案"和"这是一次入侵排查"会让同一批文件得到不同深度的描述）；
- `scenarios` 可以不填——后面你会看到系统会自己猜；
- `filter_profile`（如 `telecom_fraud`）决定几十万个文件里哪些值得进入后续分析；
- `llm_mode`（full/smart）、`backup_password`、`android_source`、`xfs_mode` 等都是给特定阶段的"通行证"。

路由层（`TaskCRUDRoutes.cpp`）校验后交给 `TaskManager::create_task`：任务获得 ID、状态 `pending`（HTTP 层全部小写），被塞进队列，工作线程从 `ThreadPool`（默认 4 线程）里把它取出来的那一刻，状态变 `running`，好戏开场（`TMA:426 start_analysis`）。从这一刻起到任务终结，`TaskPersistence` 会把每次状态变化节流写入 `data/tasks.json`——所以即使进程崩溃重启，任务列表也不会丢（重启时未完成任务怎么判，见文末"断点续跑（阶段账本）"：有账本的判 `INTERRUPTED` 可续跑，无账本的仍标 failed——诚实的处理：没有任何可复用的完成事实，就不假装还能接着跑）。

前端看到的进度百分比来自一个简单的加权累计。`TaskManager.cpp:897` 的权重表是唯一权威：

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

第一阶段 `IMAGE_ANALYSIS`（占整体进度 25%，最重的一环）由 [ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) 负责：它打开镜像（E01 或 DD）、枚举分区、对每个可识别的文件系统（NTFS/FAT/EXT2/3/4/XFS）逐文件读出元数据——路径、大小、四个时间戳、是否已删除——全部写入 `raw.db` 的 `files` 和 `partitions` 表（`TMA:855-963`）。

这一步的哲学是**忠实**：不做任何判断、不过滤、不翻译，文件系统说什么就记什么。raw.db 因此成为整个任务唯一的"事实来源"——后面所有层都是从它派生的观点，任何结论存疑时回到这里对质。

紧接着是一个容易被忽略但顺序讲究的步骤：**场景自动检测**（`TMA:965-997`）。如果创建任务时没选 `scenarios`，`SceneDetector` 会扫一遍 raw.db 里的特征路径（比如 `/data/app` 意味着 Android，`Windows/System32/config` 意味着 Windows）。源码注释解释了为什么它必须跑在过滤**之前**：过滤配置的职责恰恰是丢弃"系统噪音"，而场景特征路径就是系统路径——先过滤再检测，证据就被自己人扔掉了。核心几行：

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

如果任务指定了 `filter_profile`，`FileFilter`（`TMA:999-1072`）按 `config/filter_profiles/` 下的画像（扩展名、路径模式、大小、是否已删除……）从 raw.db **复制**出一个 `<...>_filtered.db`——注意不是修改原库，raw.db 永远保持完整；过滤只是决定"下游用哪个视角"。之后的事件提取和分类都以这个过滤后的库为输入（任务对象上的 `output_raw_db` 字段被更新为过滤库路径，前端展示的也是它）。关键几行：

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

- **事件提取**（`EVENT_EXTRACTION`，10%）：[EventExtractor](../modules/cpp/core/EventExtractor.md) 读出每个文件的 atime/mtime/ctime/crtime 四个时间戳，翻译成 CREATED/MODIFIED/ACCESSED/CHANGED/DELETED 五类事件，写入 `events.db`（`TMA:1074-1114`）。从此"文件系统的一堆数字"变成了"某时刻发生了某事"的时间线。
- **文件分类**（`FILE_CLASSIFICATION`，15%）：[FileClassifier](../modules/cpp/core/FileClassifier.md) 把每个常规文件按扩展名/内容特征归入 24 个类别之一，写入 `files.db` 的主表和对应分类表；同时按场景标注 `scene_priority`——同一个 `hosts` 文件在入侵排查里优先级高、在电信诈骗里不重要，这就是"场景感知分类"（`TMA:1116-1166`，第一个场景被映射为分类器的 SceneType）。

## 第四幕：智能增强——LLM 什么时候进来

只要 `llm_analyze` 为真（前端固定传 true），`LLM_ANALYSIS` 阶段（20%）开始，注意它其实是**先后两件事**：

1. **文件级描述**（`TMA:1168-1280`）：[LLMAnalysisService](../modules/cpp/network/LLMAnalysisService.md) 把分类后的文件逐个（必要时先从镜像提取内容）送给 LLM，生成摘要/描述/关键词，写回 files.db 的 `llm_*` 列和 `file_descriptions` 表。full 模式全量分析；smart 模式先让模型粗选一批"值得深挖"的文件再精析——这是成本与覆盖的取舍旋钮。分析量还有一个总闸：任务级预算 `llm_max_files` 经 `analysis_budget::resolve` 统一裁决（`TMA:1191-1199`），同一个预算后面还约束图谱摄取范围（ANALYZED_ONLY）与报告证据种子。一个例外值得知道：Android 逻辑提取路径（`--android-source` 类任务）的工件级 LLM 在 `analyzeAndroidData()` 内部就完成了（`AndroidLLMAnalysisService`），文件级服务对 android.db 没有 `files` 表可写、实际空转，代码注释（`TMA:775-777`）明确说明了这层分工。
2. **事件簇分析**（`TMA:1282-1324`）：时间线事件先按时间邻近聚簇，`EventClusterAnalyzer` 让 LLM 对每个簇回答"这段时间发生了什么"。限额由 `LLM_MAX_EVENT_CLUSTERS` 控制（0 = 不限）。

## 第五幕：平台语义化——把字节变成"一条聊天记录"

`PLATFORM_ANALYSIS`（20%）是取证价值最密集的一步。按检测出的场景**依次**运行平台分析器（`TMA:1326-1569`，多场景任务按顺序执行，进度按场景数折算）：

- [AndroidAnalyzer](../modules/cpp/analyzers/AndroidAnalyzer.md)：找到短信/联系人/通话/Chrome 历史/已装应用数据库逐表解析；微信库是 SQLCipher 加密的，用 `--backup-password` 提供的密钥解密；MIUI 备份走 manifest+tar 索引；QQNT 走专用工件解析。产出 `android.db`（33 张表）。
- [WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md)：注册表（hivex）、事件日志（libevtx）、Prefetch/LNK/JumpList/Amcache/SRUM/MFT/浏览器……产出 `windows.db`（32 张表；Shimcache/UserAssist/RDP/WiFi 解析器已实现但未接线，对应表恒空）。
- [LinuxFilesAnalyzer](../modules/cpp/analyzers/LinuxFilesAnalyzer.md)：syslog/journal/auditd、账户与登录、Shell 历史、13 种持久化机制检测、容器、Web 服务器、攻击链与异常分析，产出 `linux.db`（73 张表）。SERVER_CLOUD 场景也由它处理（`analyzeServerCloudArtifacts`），工件写入 `oss.db`——文件名容易误会成阿里云 OSS 分析，实际是服务器/云场景的 Linux 工件库。

每个平台分析器内部还会调用自己的 LLM 服务（`Linux/Windows/AndroidLLMAnalysisService`）对工件做语义标注——注意这与第四幕的文件级 LLM 是两回事：那里读"文件"，这里读"已经解析成取证工件的记录"。

### 分支：手机备份源（`--android-source`）的取数-分析分离

上面走的是"镜像 → raw.db → 分拣 → 平台分析"的主路。手机备份类任务（`android_source` 为 dir/zip/miui-backup/meiya/mobile-evidence/thunder-backup/tar/seven-zip/android-backup/filesystem-image/android-container/ios-backup/vivo-backup）在流水线早期就**短路**进一条专用路径：`runLogicalAndroidAnalysis`（分派在 `TMA:717-738`，实现在 `TMA:1714-2193`），不建 raw.db/events.db/files.db，直接从备份来源解析、写独立的 `android.db`（harmony-backup 是唯一例外，仍走下方的 ANDROID 场景分支）。这条路径里，"取数"与"分析"已经拆成两个以统一取数包为契约的阶段（规范见 [docs/specs/mobile-evidence-package.md](../specs/mobile-evidence-package.md)）：

```
原始检材 ──[取数适配器]──> <base>_mobile_evidence.mep.db ──[统一分析]──> android.db
   MIUI / 鸿蒙 / 雷电 / 美亚      （mobile_evidence_meta/_record/_file 三主表）
```

各来源的走法不同：

- **美亚 FL-901**（`TMA:1839-1923`）是唯一"适配器完全绕开 AndroidAnalyzer"的来源：`MeiyaBackupExtractor` 解码容器（1024 字节周期 XOR，掩码运行时自推导，规范见 [docs/specs/meiya-container-parsing.md](../specs/meiya-container-parsing.md)）→ `MobileEvidenceMeiyaAdapter` 转成统一包 → `Writer` 落到任务目录 → `mobile_evidence::analyzePackage` 写 android.db。进度里程碑 20%（解码）→ 55%（转包）→ 75%（分析库）→ 100%。
- **`mobile-evidence` 来源**（`TMA:1791-1834`）只做后半段：拿一个已有的 `.mep.db` 直接分析。包就是证据交接物——原始检材可以已经不在原位。
- **MIUI / 鸿蒙 / 雷电**仍经 AndroidAnalyzer 解析并写 android.db，统一包作为 **sidecar** 并行写出（`TMA:2079-2138`，miui/thunder 在逻辑短路径内；harmony 在 ANDROID 场景分支内写，`TMA:1406-1440`）。包写失败只记 WARNING、不失败任务——android.db 仍可服务既有页面，缺口通过审计日志与任务元数据（`mobile_evidence_package` / `mobile_evidence_records` / `mobile_evidence_files` / `mobile_evidence_adapter`）可见。
- **iOS / vivo 备份**目前不产统一包：`AndroidAnalyzerCore.cpp:149-155` 按来源分派 `IosBackupExtractor` / `VivoBackupExtractor`（vivo 的 LevelDB 索引先经固定脚本的 Python 桥物化为 JSON，`TMA:1988-2023`），工件解析（`AndroidAnalyzerCore.cpp:252-264`）直接写 android.db。

统一分析消费端只有一份：`MobileEvidenceAnalysis.cpp:231-324` 按 `kind` 把包里的记录写进 android.db 的标准表（contacts/call_logs/sms_messages/app_notes/installed_apps/wifi_networks/device_identifiers/app_db_inventory），带 `mobileArtifact` 标记的记录同时投影进 `mobile_artifacts`，覆盖度声明回写 `android_source_coverage`。新增一家手机/取证软件只需要写一个 `buildPackageFromXxx` 适配器，分析层零改动——这是这条分支存在的理由。

如果任务开了雕刻（`file_carving`），`FILE_CARVING`（3%）用 29 种文件签名扫未分配空间，恢复的文件放进任务目录的 `carved_files/`（`TMA:1571-1611`）。

## 第六幕：收尾——完成是一道门槛，不是一声令下

`FINALIZING`（2%）曾经是"触发图谱摄取然后立刻宣布完成"的 fire-and-forget；现在它是**两道完成门槛**（`TMA:1613-1704`）：任务只有等知识图谱摄取真正完成、且首轮研判报告生成完毕，才置 `completed`。任何一道门槛超时/失败，任务判 `FAILED`——但错误详情会写明"分析产物仍可浏览"，证据不因收尾失败而丢失。

第一道门槛是**图谱摄取**。触发时不再摄取整个 files 表，而是 `IngestionMode::ANALYZED_ONLY`——只摄取有描述的文件（范围正是第四幕那个 `AnalysisBudget` 裁决出的集合）。之后 `wait_for_graphiti_ingestion`（`TMA:313`）在预算内轮询作业状态：预算 `GRAPHITI_INGEST_WAIT_TIMEOUT_MIN`（默认 720 分钟，与 Python 侧作业超时对齐）、重试 `GRAPHITI_INGEST_RETRIES`（默认 2 次）。关键几行：

```cpp
// Finalization — gated on ingestion (budget: GRAPHITI_INGEST_WAIT_TIMEOUT_MIN,
// 0 restores the legacy fire-and-forget completion).
const bool ingestion_ok = noOptionalIntelligence || ingestionAlreadyDone ||
                          wait_for_graphiti_ingestion(task_id, graphiti_job_id);
if (is_task_cancelled(task_id)) { return; }

set_result_db(task_id, fileDbPath);
if (!ingestion_ok) {
    const int budget_minutes = forensics::ConfigManager::instance()
                                   .getInt("GRAPHITI_INGEST_WAIT_TIMEOUT_MIN", 720);
    update_status(task_id, TaskStatus::FAILED,
                  "Knowledge graph ingestion did not complete",
                  "Graphiti ingestion failed or timed out (budget: " +
                      std::to_string(budget_minutes) +
                      " minutes). Analysis artifacts remain available for browsing.");
    add_audit_log(task_id, "ERROR", "Analysis failed at the Graphiti ingestion gate");
    return;
}
```

逐块读：门槛有三个"旁路"——`noOptionalIntelligence`（野外模式：`TRACELENS_FIELD_AUTH=enabled` 且出站策略关闭，智能层整体缺席是特性不是故障）、`ingestionAlreadyDone`（账本里已有 `FINALIZING.ingestion` 完成事实，续跑时不再重等数小时的摄取）、以及预算设 0（显式退回旧的 fire-and-forget 语义）。摄取一旦过闸，立即把 `FINALIZING.ingestion` 写进阶段账本——此后哪怕报告门槛失败，resume 也直接从报告重试，不重等图谱。等待期间任务可以 pause：图谱作业在 Python 侧继续跑，完成事实由下一次 resume 的账本检查收下，什么都不丢。

第二道门槛是**首轮材料研判报告**（前置条件：任务开启 `llm_analyze` 且非野外模式，再叠加 `REPORT_AUTO_GENERATE_ENABLED`——默认开，`TMA:1687`）：`wait_for_pipeline_report`（`TMA:377`）触发 Python 侧报告生成并等待，预算 `REPORT_TAIL_WAIT_TIMEOUT_MIN`（默认 60 分钟）、重试 `REPORT_TAIL_RETRIES`（默认 1 次），同样带预算 0 的逃生口。两道门槛都过了，才执行那最后三行：`mark_stage_complete(kFinalizing)` → 进度 100% → `update_status(COMPLETED)`。

所以"分析"与"图谱"的故障域不再是彻底分离的——这是有意收紧的语义（图谱是任务承诺的一部分，缺席不该被伪装成成功）；代价是 Python/Neo4j 长时间不可用时任务会以 FAILED 收尾，此时前端展示的是"产物可浏览的失败任务"，而不是"假装成功的任务"。

## 任务之后：产出物给谁用

任务完成后，`data/tasks/<task_id>/` 是一个自包含的证据包。理解"谁读什么"就理解了整个上层建筑：

| 产出 | C++ 路由 | 前端页面 | Python 侧消费者 |
|------|---------|---------|----------------|
| `raw.db` | 文件/统计类查询（经 SQLiteHelper） | /files、/statistics | CppBackendService 回查、Graphiti DatabaseReader |
| `events.db` | 时间线 11 个端点、事件导出 | /timeline | 案件多镜像分析读事件 |
| `files.db` | 文件分析端点 | /files、/analysis-center | LLMService 持久化重分析结果（直接 UPDATE llm_* 列）、报告生成、Graphiti 摄取 |
| `android.db` 等 | 平台端点（如 android 14 个） | /android、/im-forensics | WeChatGraphService（直接 sqlite3 读 android.db）、Graphiti 平台 reader |
| `extracted_files/` | 提取状态端点 | /files 提取下载 | markitdown 转换输入（task_store 精确匹配路径） |

值得一提的是 Python 侧读任务库的方式：`task_store` 以任务 ID 解析出精确路径（fail-closed，拒绝任何不匹配的路径），这保证"服务间共享文件系统"不会变成越权读任意文件的漏洞——这是 2026 年加固的边界（docs/hardening/d2b）。

## 失败、取消与看门狗

流水线在每个阶段边界检查 `cancellation_requested` 原子标志（取消即置位，任务以 `cancelled` 终止，不再有后续写入——任务删除后写保护也依赖这个语义）。任何阶段返回失败，任务立即 `failed` 并记录原因；由于产出都在任务目录里，失败的垃圾不会污染其他任务。`TaskWatchdog` 后台线程持续轮询（注释写"每 60 秒"，实现实际每 1 秒醒一次，`TaskWatchdog.cpp:38-43`），把超过 `TASK_WATCHDOG_STALE_MINUTES`（RUNNING，默认 30 分钟）无进度更新或超过 `TASK_WATCHDOG_PENDING_MINUTES`（PENDING，默认 30 分钟）未被调度的任务标记失败——这是给"线程死了但没人知道"兜底。

## CLI 模式：同一台发动机的另一个方向盘

CLI（`./forensic_analyzer 镜像` → `AnalysisOrchestrator`）复用完全相同的分析器，差异只在编排层：同步执行、无进度/取消/看门狗、输出库放镜像旁边（`<镜像>_raw.db`...）、平台工件**并入** `<镜像>_files.db` 而不是独立库。为什么不同？HTTP 模式的任务目录隔离是给并发和多消费者准备的；CLI 面对的是"一个镜像一次跑完"的脚本场景，并入单库更顺手。这也意味着**给 CLI 写的消费工具不能假设平台工件在独立库里**——两个模式的库布局是 documented 行为，不是 bug。

另有独立子命令绕过主流水线直达单点能力：`--carve`（只雕刻）、`--index/--search`（只建索引/搜索）、`--extract-*`（只提取）、`--analyze-dlls`、`--memory-analyze`（Volatility3 子进程 → `<镜像>_memory.db`）、`--report`（Markdown 报告，`src/report/ReportGenerator`）、`--dump-text`（`src/export/` 的 `TextDumpExporter` + `TextDumpAdapters`）、以及手机来源的两阶段取数/分析：`--mobile-extract` / `--mobile-package`（统一取数包，见 [docs/specs/mobile-evidence-package.md](../specs/mobile-evidence-package.md)）。

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


## 第七幕（补）：失败路径走读——任务没能走到 COMPLETED 时发生了什么

叙事主线讲的是happy path；这一节专门走三条失败分支，代码位置都在 `TMA` 与 `TaskManager.cpp`。

### 分支一：阶段失败（FAILED）
任何阶段返回 false（如 `extractEvents()` 失败、`classifyAndExtract()` 失败）→ 立即 `update_status(task_id, FAILED, "<原因>")` 并 return。已产出的部分库**保留在任务目录**（不回滚——部分证据仍有价值，且失败原因写进任务的 error_details 供前端展示）。注意：Graphiti 不会触发（它在最后），所以失败任务的图谱永远缺席，属预期。

### 分支二：用户取消（CANCELLED）
DELETE /api/tasks/{id} 或 batch-cancel → 置 `cancellation_requested`。流水线在**每个阶段边界**检查（TMA 各段开头的 `is_task_cancelled`）：当前阶段跑完后置 CANCELLED。两个推论：①阶段内不可打断——大 SQL/大提取中途取消要等它做完这一段；②删除任务与取消共享该标志，但删除还会走终端写保护（删除后线程再想写库会被 existing-only 守卫拒绝——D4b）。

### 分支三：看门狗判死（FAILED+原因）
后台线程发现 RUNNING 超 `TASK_WATCHDOG_STALE_MINUTES` 无进度变化（或 PENDING 超时）→ 直接改状态为 FAILED，错误详情写明 inactivity 分钟数。任务线程**并不知道**自己被判死——它会继续跑完当前阶段，然后在下一次 update 时发现状态已变（TaskManager 的状态机以先到者为准）。排障时看到"任务还在写库但状态已 FAILED"不要惊讶，这是该设计的已知表象（TaskInfrastructure §6）。

### 重启恢复（第四条分支）
进程崩溃 → 重启时 `TaskPersistence::load_tasks` 检查任务的阶段账本：**有账本**的 RUNNING/PENDING 任务改判 `INTERRUPTED`（可续跑，`runningTaskIds` 收集其 ID 并写审计日志）；**无账本**的仍一律标 FAILED（"宁可信其坏"——没有任何已完成阶段可复用，就不假装还能接着跑）。孤儿任务目录清理**不校验 UUID 形态**（会删 tasks/ 下任何不在字典里的目录——运维别往里放私人物品；UUID 形态的注释在 `TaskPersistence.cpp:120`，而 `:121-123` 的删除实现并不校验形态——注释与实现的偏差已记录）。

### 断点续跑（阶段账本）

任务不再只有"重跑=新任务"一条路。每个阶段在**出口**把自己的完成事实写入 `AnalysisTask::metadata["stage.<NAME>"]`，值形如 `done:<输入指纹>`；阶段在**入口**读取该记录，只有同时满足"标记 done + 记录的指纹等于当前输入指纹 + 产物存在且非空"才跳过。

账本载体是 `metadata`（随 `tasks.json` 一起持久化，零 schema 变更），值语法与指纹工具在 [TaskStageLedger.h](../../src/network/HTTPServer/TaskStageLedger.h)。

关键设计约束（都是踩过的坑）：

- **指纹必须覆盖 SQLite 的 `-wal` 侧车**。分析器统一开 `PRAGMA journal_mode=WAL`，未 checkpoint 的写入只改 `-wal`，主库的 size/mtime 完全不变；只哈希主库会对"刚被重写"的库报"没变"——这正是让续跑复用陈旧产物的假阴性。`-shm` 反而必须排除：它在**只读打开**时就会被创建，纳入会让"有人读过这个库"也变成指纹变化，把每次续跑都变成误判失效。
- **上游变化必须连带作废下游**。`clear_downstream_stages()` 按 `pipeline_stage_order()` 清掉后续阶段的账本并删除它们拥有的产物（events.db / files.db）。CLI 的阶段顺序与 HTTP 不同（CLI 先分类+平台分析、后建时间线，因为平台工件要并入 events.db），所以两边各有一份顺序表，必须与实际执行顺序一致。
- **重跑前必须清产物**。`ImageAnalyzer` / `FileClassifier` / `EventExtractor` / 平台分析器全是 `CREATE TABLE IF NOT EXISTS` + `INSERT`（追加语义），不清库重跑会产生重复行。清理由 `remove_sqlite_artifacts()`（含 `-wal/-shm/-journal` 侧车）在阶段入口完成。
- **天然幂等的阶段不记指纹**。文件级 LLM 分析的候选查询自带 `llm_analyzed_at IS NULL`，平台工件 LLM 的 SQL 同样带该条件，图谱摄取靠 `ingested_at` 水印——这些阶段中断后重跑本身只会补缺口，账本只记一个裸 `done` 用于表达"这一阶段整体完成过"。

对外接口：

| 方法 | 端点 | 语义 |
|---|---|---|
| POST | `/api/tasks/{id}/resume` | 从账本继续（同 ID、同目录、同配置）。仅 FAILED / CANCELLED / INTERRUPTED / PAUSED 且账本非空；否则 409 并返回具体原因 |
| POST | `/api/tasks/{id}/pause` | 协作式暂停：当前阶段跑完后停到 PAUSED（与取消同样的粒度），之后可 resume |

`TaskHelpers::is_resumable()` 是唯一判据（任务状态 + 镜像仍可读 + 账本非空 + 未被标记 `resume.exhausted`），`GET /api/tasks` 把它作为 `resumable` 字段透出给前端按钮。

**可复核性**：每次续跑写一条 `TASK_RESUMED` 审计日志，记录续跑次数与下一个待跑阶段；任务上的 `resume_count` / `last_resumed_time` 持久化。被跳过的阶段各写一条 `STAGE_SKIPPED`，被作废的写 `STAGE_INVALIDATED`——终版报告可以自证"这个任务被续跑过，哪些阶段是复用而非重算"。

CLI 走同一套账本语义，但载体是产物旁的 sidecar `<base>_stages.json`（CLI 没有任务状态库）。`--overwrite` 现在有真实含义：删除该账本、强制全量重跑（此前它被解析但无消费者）。C/S agent 的 `--overwrite` 因此与续跑联动：`resume_interrupted_commands` 开启时，崩溃后重执行的命令不再传该参数，从而保留账本继续跑。

**最后更新**: 2026-11-10（新增"手机备份源的取数-分析分离"分支：统一取数包 `.mep.db` 数据流；重写第六幕——收尾从 fire-and-forget 收紧为"图谱摄取 + 首轮报告"两道完成门槛；行号锚点对齐当前代码）
