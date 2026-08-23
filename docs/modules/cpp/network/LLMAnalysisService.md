# LLMAnalysisService（src/network/HTTPServer/LLMAnalysisService.{h,cpp}）

> **一句话**：文件级 LLM 描述生成器——从 _files.db 挑文件、从磁盘镜像里把文件抽出来、喂给文本模型生成摘要/描述/关键词，再写回 files 表的 llm_* 列和 file_descriptions 表；full 全量、smart 先让 LLM（失败则启发式）选重要文件。

## 1. 为什么有这个模块

文件分类只能告诉你"这是个 JSON"，不能告诉你"这是攻击者的 C2 配置"。给海量文件生成语义描述必须解决三个现实问题，本模块各有一套机制：

1. **文件在镜像里，不在磁盘上** → `resolveFileForAnalysis` 经 TSK 按需抽取；
2. **文件太多，LLM 预算有限** → smart 模式的两级筛选（LLM 选择 + 启发式兜底）；
3. **结果要能被前端和 Python 侧共同消费** → 双写 files.llm_* 列与 file_descriptions 表。

### 关于"deprecated"标注的矛盾，先说清楚

`LLMPythonProxy.h:60-61` 的注释说 "The existing C++ LLMAnalysisService is preserved but **deprecated**. New LLM analysis flows should use this proxy instead." 但源码事实是：**任务流水线在 `llm_analyze=true` 时仍然活跃地调用本模块**（TaskManagerAnalysis.cpp:334-391），它不是死代码。

矛盾的由来：项目曾计划把所有 LLM 工作迁往 Python 服务（Graphiti 摄取、案件级分析确实迁过去了，经 LLMPythonProxy），文件描述这一环保留了 C++ 实现。于是形成"注释宣弃用、流水线照用"的现状。**结论：改文件级描述逻辑，改这里；接知识图谱/案件分析，走 Python。** 读到 deprecated 注释时以本节为准。

## 2. 在系统中的位置

```
TaskManager::start_analysis (LLM_ANALYSIS 阶段, TaskManagerAnalysis.cpp:334-391)
    └─ llm_analyze=true ──▶ LLMAnalysisService
                              ├─读─▶ _files.db files 表（候选清单）
                              ├─抽─▶ FileExtractor(TSK): 镜像+raw.db → llm_scratch 临时目录
                              ├─析─▶ llm::FileAnalyzer / ModelRouter（文本模型）
                              └─写─▶ _files.db: files.llm_* 列 + file_descriptions 表
前端 /files、调查中心：读 llm_* 列 / file_descriptions
```

- 每任务实例化一次（非单例），析构时清理本任务的抽取临时目录（LLMAnalysisService.cpp:21-25，LLMScratch）。
- 与平台工件级服务（Linux/Windows/AndroidLLMAnalysisService）分工：本模块面向 **files 表的普通文件**；那些面向平台分析库里的结构化工件（日志、注册表……）。

## 3. 核心数据结构与接口

### 3.1 AnalysisOptions：分析预算的唯一入口

```cpp
// src/network/HTTPServer/LLMAnalysisService.h:31-45
struct AnalysisOptions {
    size_t maxFiles = 1000;              // Maximum files to analyze
    size_t maxContentLength = 10000;     // Maximum content length per file
    std::vector<std::string> fileTypes;  // File types to analyze (empty = all)
    bool skipBinaryFiles = true;         // Skip binary files
};

using ProgressCallback = std::function<bool(int current, int total, const std::string& currentFile)>;
```

流水线不直接填这些值，而是从 ConfigManager 透传 env（TaskManagerAnalysis.cpp:345-349）：

| 字段 | env（ConfigManager.cpp:91-97） | 默认 | 说明 |
|---|---|---|---|
| maxFiles | `LLM_MAX_FILES` | 500 | smart/full 共同预算；旧硬编码下限 1000 曾让本地 LLM 任务跑数小时（TaskManagerAnalysis.cpp:369-372 注释） |
| maxContentLength | `LLM_MAX_CONTENT_LENGTH` | 10000 | 单文件喂模型的字符上限，超长截断 |
| fileTypes | （无 env） | 空 | 空=全部分类；非空时映射为 `category IN (...)` |
| skipBinaryFiles | `LLM_SKIP_BINARY` | true | 排除 Executables/Unknown 分类 |

### 3.2 核心接口清单

| 方法（真实签名，LLMAnalysisService.h:70-143） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `bool initialize()` | 惰性建 ModelRouter + FileAnalyzer | 所有公开方法首行 | 异常打印返回 false → 上层返回 0 |
| `int analyzeAllFiles(filesDbPath, options, cb)` | full：全量（截断到 maxFiles）逐文件分析 | 流水线 llm_mode=full | 抽取失败 continue；单文件异常打印继续 |
| `int analyzeSmartFiles(filesDbPath, options, cb)` | smart：先选择后分析 | 流水线 llm_mode=smart（默认） | 选出 0 文件时返回 0；LLM 失败打 Warning（:225-230） |
| `vector<string> selectImportantFiles(db, maxFiles)` | §4.2 筛选管线 | smart 入口 | 三重回退到 selectByHeuristic，永不空手（除非库空） |
| `setSceneType(scene)` / `setImagePaths(image, rawDb, taskId)` | 场景与镜像注入 | 流水线 :341-344 | 无失败路径 |
| `shouldSkipFile(file)` / `getSceneSpecificPrompt(file)` / `getScenePrioritizedFiles(db, limit)` | 场景感知 API | **主流水线不经过**（见 §7） | — |
| `storeDescription(...)`（private） | §4.4 双写 | 分析循环 | UPDATE 行数 0 返回 false |

## 4. 核心概念与设计

### 4.1 full / smart 两模式

- `analyzeAllFiles`（:122-178）：取库内文件（按 category 过滤、skipBinaryFiles 默认排除 Executables/Unknown，:442-499）截断到 maxFiles 逐个分析。
- `analyzeSmartFiles`（:180-237）：先 `selectImportantFiles` 选出重要文件再逐个分析。

### 4.2 smart 选文件的防线（这是本模块最精彩的部分）

`selectImportantFiles`（:239-340）的筛选管线，每一步都在防"LLM 不靠谱"：

1. **预算内直接返回**：文件数 ≤ maxFiles 就不用选（:256-258）；
2. **剔除 TSK 虚拟条目**：`$` 开头的 `$MFT` 类伪文件不是可分析证据（:261-269）；
3. **启发式排序限长**：`forensicPathPriority`（:501-567）按取证价值打分——凭证/历史类 100 分、/home 与用户目录 90、/var/log 80、浏览器/邮件 75、.db/.sqlite 70、/etc 60、/boot/cron 50、/usr/share 等大路货 5 分——排序后把送选 prompt 控制在 48000 字符内（:278-292），防止上下文爆炸导致选择调用必败；
4. **LLM 选择 + 三重回退**：调用失败、返回可用路径少于预算的 1/4、抛异常，任何一种都回退 `selectByHeuristic`（:316-339）；解析端还会拒掉 `""`/`"/"` 这类会"匹配一切"的垃圾项（:620-629）。

字符预算的实现（第 3 步核心）：

```cpp
// src/network/HTTPServer/LLMAnalysisService.cpp:278-292
// Bound the prompt sent to the LLM: on real images (thousands of files) an
// unbounded file list overflows context/timeouts and the selection call
// always fails. Order candidates by forensic priority first so truncation
// keeps the interesting files, then cap the summary at a char budget.
auto ranked = selectByHeuristic(candidates, candidates.size());
const size_t kMaxSummaryChars = 48000;
size_t summaryFiles = 0, summaryChars = 0;
for (const auto& f : ranked) {
    summaryChars += f.size() + 8;  // path + "- " + newline overhead
    if (summaryChars > kMaxSummaryChars) break;
    summaryFiles++;
}
if (summaryFiles < maxFiles) {
    summaryFiles = std::min(ranked.size(), maxFiles);
}
if (summaryFiles > ranked.size()) {
    summaryFiles = ranked.size();
}
std::vector<std::string> summaryList(ranked.begin(), ranked.begin() + summaryFiles);
```

要点：先按取证优先级**稳定排序**再截断，保证 48000 字符装不下的必然是低价值文件；`+8` 是每行 `- path\n` 的格式开销估算；后面两个 if 夹逼 summaryFiles 到 `[maxFiles, ranked.size()]` 区间——预算字符够但文件数超预算时仍然收紧到 maxFiles，反之字符预算算出的条数小于 maxFiles 时也不放松（截断更狠只会少分析，不会超支）。

三重回退（第 4 步）：

```cpp
// src/network/HTTPServer/LLMAnalysisService.cpp:316-339
try {
    auto response = router_->chat(prompt);

    if (!response.success) {
        std::cerr << "LLM request failed: " << response.errorMessage
                  << " — falling back to heuristic file selection" << std::endl;
        return selectByHeuristic(candidates, maxFiles);
    }

    auto selected = parseImportantFiles(response.content, allFiles);
    if (selected.empty() || selected.size() < maxFiles / 4) {
        // The model responded but returned (nearly) nothing usable —
        // its selection is unreliable, prefer the deterministic ranking.
        std::cerr << "LLM selection returned only " << selected.size()
                  << " usable paths (budget " << maxFiles
                  << ") — falling back to heuristic file selection" << std::endl;
        return selectByHeuristic(candidates, maxFiles);
    }
    return selected;
} catch (const std::exception& e) {
    std::cerr << "Failed to select important files: " << e.what()
              << " — falling back to heuristic file selection" << std::endl;
    return selectByHeuristic(candidates, maxFiles);
}
```

三条路径殊途同归 `selectByHeuristic`：HTTP 层失败（response.success=false）、语义层失败（解析出的可用路径 < 预算 1/4，视为模型没认真选）、异常。`maxFiles / 4` 是个经验阈值：模型只要选出了四分之一以上就算"选择成功"，宁可接受不完美的选择也不再花钱重试。

打分函数 `forensicPathPriority`（:501-567）的匹配是对**全路径小写子串**做的（先 tolower 整条路径），不是精确文件名比较——`evil/shadow_backup.txt` 也会因含 "shadow" 得 100 分。函数是首匹配即返回的瀑布式打分（100→90→80→75→70→60→50→5→30→10），模式表集中在两个 static vector（credPatterns/highExt，:502-508），调优先级只改这里、无需动选择管线。

### 4.3 从镜像抽文件：宁可慢，不可错

`resolveFileForAnalysis`（:60-120）有一个明确的安全决策：**配置了镜像就永远从镜像抽取，绝不走宿主机 fs::exists 快路径**。工程细节（:74-95 节选）：

```cpp
// src/network/HTTPServer/LLMAnalysisService.cpp:66-68、74-81、84-95（节选）
// Image-backed analysis: ALWAYS extract from the image. A host-filesystem
// fast path (fs::exists) would silently analyse the ANALYST's own files
// (e.g. /etc/passwd exists on any Linux host) instead of the evidence.
// ...
// Reuse one extractor across files: opening the image + every partition
// + the SQLite DB per file dominates analysis time on large images.
if (!imageExtractor_) {
    auto extractor = std::make_unique<FileExtractor>(imagePath_, rawDbPath_);
    if (!extractor->initialize()) { /* ... */ return ""; }
    imageExtractor_ = std::move(extractor);
}
// ...
// Build a safe output path under the task's extracted_files directory.
std::string safeName = filePath;
std::replace(safeName.begin(), safeName.end(), '/', '_');
std::replace(safeName.begin(), safeName.end(), '\\', '_');

// Use a task-scoped scratch directory so concurrent tasks cannot
// overwrite one another's flattened evidence files.
fs::path extractDir = forensics::llm_scratch::dirForTask(scratchTaskId_);
fs::create_directories(extractDir);
fs::path outputPath = extractDir / safeName;
```

- 复用单个 FileExtractor 实例——逐文件重开镜像+分区+DB 会支配总耗时；
- 路径扁平化为安全文件名（斜杠换下划线），放进任务专属 llm_scratch 目录，避免并发任务互踩与目录穿越；
- 对首斜杠差异做正反两次重试（:101-112）：镜像内路径存成 `etc/passwd` 或 `/etc/passwd` 两种口径都试一遍。

### 4.4 双写：files.llm_* 与 file_descriptions

`storeDescription`（:342-440）先 UPDATE files 行（`FileClassifierSQL::UPDATE_FILE_LLM_ANALYSIS`，:369），再 UPSERT 进 `file_descriptions`：

```cpp
// src/network/HTTPServer/LLMAnalysisService.cpp:394-419（节选）
// Also write to the file_descriptions table with is_relevant=1 so that
// AI-analyzed files from the main pipeline appear in the investigation
// center's evidence list automatically. The Python side (persist_to_files_db)
// does the same; the C++ side must stay in sync.
sqlite3_exec(db,
    "CREATE TABLE IF NOT EXISTS file_descriptions ("
    "  file_path TEXT PRIMARY KEY,"
    "  description TEXT,"
    "  summary TEXT,"
    "  keywords TEXT,"
    "  model_used TEXT,"
    "  is_relevant INTEGER DEFAULT 0,"
    "  created_at INTEGER DEFAULT 0"
    ")",
    nullptr, nullptr, nullptr);

sqlite3_stmt* descStmt = nullptr;
const char* descSql =
    "INSERT INTO file_descriptions (file_path, description, summary, keywords, model_used, is_relevant, created_at) "
    "VALUES (?, ?, ?, ?, ?, 1, ?) "
    "ON CONFLICT(file_path) DO UPDATE SET "
    "  description = excluded.description, "
    "  summary = excluded.summary, "
    "  keywords = excluded.keywords, "
    "  model_used = excluded.model_used, "
    "  created_at = excluded.created_at";
```

要点：① 表不存在则就地 CREATE——旧库无感升级；② `is_relevant=1` 硬编码，主流水线的产出默认视为"相关证据"，与 Python 侧 `persist_to_files_db` 保持同构（注释明说两边必须同步），保证"调查中心证据列表"能看到主流水线产出的 AI 分析；③ UPSERT 以 file_path 为主键，重复分析幂等覆盖；④ 第二次写不做行数检查——即使 file_descriptions 写失败，files 行的 UPDATE 已生效，函数返回值只取决于第一段。

## 5. 工作流程走读

smart 模式一次任务（TaskManagerAnalysis.cpp:367-384 驱动）：

1. `initialize` 建文本模型 ModelRouter（:27-50）；`setSceneType` + `setImagePaths(镜像, effectiveRawDb, task_id)`（TaskManagerAnalysis.cpp:341-344）；
2. `analyzeSmartFiles` → `selectImportantFiles`（§4.2 管线）得到 ≤500 个路径；
3. 循环：进度回调（返回 false 即任务取消，:203-208）→ `resolveFileForAnalysis` 抽文件 → `FileAnalyzer::analyzeFile` → 成功则双写库；失败现在会打 Warning（:225-230，旧版静默导致统计失真）；
4. 返回分析数，流水线汇报 "stored in _files.db"（TaskManagerAnalysis.cpp:386-387）。

full 模式仅第 2 步不同（无选择，直接截断）。

## 6. 与其他模块的协作

- **TaskManager**：唯一流水线调用方；进度/取消经回调。
- **FileExtractor（TSK）**：镜像内文件抽取。
- **ModelRouter/FileAnalyzer（LLMIntegration）**：实际模型调用，配置来自 ConfigManager 文本模型。
- **FileClassifierSQL / file_descriptions**：结果存储契约，Python 侧同步遵守。
- **LLMScratch**：任务级抽取临时目录的分配与清理（析构 + TaskManager 删除任务兜底 TaskManager.cpp:345）。
- **EventClusterAnalyzer**：姊妹模块，同一模式下对事件簇做类似的事。

## 7. 注意事项与已知问题

- **deprecated 注释与现状不符**：见 §1，以流水线实际调用为准。
- **结果写回依赖 path 精确匹配**：UPDATE 以 path 为键（:382），行数为 0 会记 Warning 并返回 false（:434-437）——镜像路径大小写/斜杠差异会导致"分析了却没写进"。
- **场景感知 API 未入主流水线**：`getScenePrioritizedFiles/shouldSkipFile/getSceneSpecificPrompt`（:675-767）只在直接调用时生效，analyzeAll/Smart 路径不经过它们。
- **maxContentLength 默认 10000 字符**：超大文件被截断描述（AnalysisOptions，LLMAnalysisService.h:31-36）。
- **抽取失败静默跳过**：resolve 返回空串时 continue（:159-161），统计里的 analyzed 数不含这些文件。
- **smart 选择成本**：即使走 LLM 选择，前置的启发式排序 + 48000 字符 prompt 本身也是一次全文模型调用；纯启发式环境下（LLM 必败）等于白付一次失败调用再回退。

## 8. 如何验证与扩展

- **验证**：跑 llm_analyze=true + llm_mode=smart 的小镜像任务，检查 `_files.db`：`SELECT path, llm_summary, llm_model_used FROM files WHERE llm_analyzed_at > 0 LIMIT 10`，并确认 file_descriptions 有同批行；关掉 LLM 服务再跑，确认日志出现 "falling back to heuristic" 且任务仍完成（兜底生效）。
- **扩展**：调整优先级规则改 `forensicPathPriority`（:501-567）的模式表即可，无需动选择管线；新增输出字段要同步 prompt、解析、UPDATE_FILE_LLM_ANALYSIS、file_descriptions UPSERT 四处与 Python 侧。

## 9. 写库契约细节（二轮补全）

### 9.1 files.llm_* 列与"唯一路径守卫"（新发现）

storeDescription 的 UPDATE 用的是 `FileClassifierSQL::UPDATE_FILE_LLM_ANALYSIS`（file_classifier_sql.h:85-93），完整 SQL：

```sql
UPDATE files SET
    llm_summary = ?, llm_description = ?, llm_keywords = ?,
    llm_analyzed_at = ?, llm_model_used = ?
WHERE path = ?
  AND (SELECT COUNT(*) FROM files AS candidate WHERE candidate.path = files.path) = 1;
```

末行的**唯一路径守卫**是此前未记录的关键语义：path 在 files 表中出现多于一次时（多分区镜像里两个分区各有 `/etc/passwd` 是常态），UPDATE 拒绝写入——子查询数出同名 path 的行数≠1 就一行都不改。后果链：`sqlite3_changes()==0` → storeDescription 返回 false（LLMAnalysisService.cpp:434-437）→ 该文件计入"分析失败"。也就是说**多分区镜像里路径重复的文件永远拿不到 LLM 描述**，且日志里表现为 "No rows updated" 而非抽取或模型错误。设计动机合理（无法决定写哪一行，索性不写），但调用方若把 analyzed 数当作覆盖指标会高估漏检。

五个 llm_* 列的来源：`ALTER_FILES_ADD_LLM_COLUMNS`（file_classifier_sql.h:75-81，5 条 ALTER）由 FileClassifier 建库时补列——llm_summary / llm_description / llm_keywords / llm_analyzed_at / llm_model_used。`llm_is_relevant` **不是** files 表的列（那是 events 表簇级列与 file_descriptions 的字段）——file_descriptions 的 is_relevant 由本模块硬编码 1（§4.4）。

### 9.2 每文件开关一次库连接

storeDescription 每次 `sqlite3_open(dbPath)` → UPDATE → UPSERT → `sqlite3_close`（:345-439）。分析 500 个文件 = 500 次开关连接 + 500 次 `CREATE TABLE IF NOT EXISTS`（:394-402 每次都 exec）。SQLite 开关是微秒级、DDL 幂等，实测不是瓶颈，但与"复用单个 FileExtractor"（§4.3）的优化思路形成对比——后者优化的是真正昂贵的镜像重开。多线程批量改造时这里需要先收敛为单连接+事务。

### 9.3 heuristic 打分全表

`forensicPathPriority`（:501-567）瀑布式首匹配，完整分值表（自上而下取首个命中）：

| 分值 | 匹配规则（全路径 tolower 后子串/后缀） | 代表场景 |
|---|---|---|
| 100 | credPatterns 子串：shadow、passwd、authorized_keys、known_hosts、id_rsa、id_ed25519、.bash_history、.zsh_history、sh_history、history.db、sudoers | 凭证与历史（:502-504） |
| 90 | /home/、/users/、/root/ 子串或前缀；desktop、documents、downloads 子串 | 用户数据区（:519-524） |
| 80 | /var/log/ 子串、journal 子串 | 系统日志（:526-528） |
| 75 | .mozilla、chrome、wechat、telegram、mail 子串 | 浏览器/聊天/邮件（:530-534） |
| 70 | 后缀 .db 或含 .sqlite | 数据库（:536-540） |
| 60 | /etc/ 子串或前缀 | 系统配置（:542-544） |
| 50 | /boot/ 子串、cron 子串 | 启动与调度（:546-548） |
| 5 | /usr/share/、/usr/lib、fonts、ssl/certs、locale、icons、node_modules 子串 | 大路货（:550-557） |
| 30 | highExt 后缀：.log/.db/.sqlite/.sqlite3/.md/.txt/.json/.xml/.csv/.conf/.cfg/.ini/.yaml/.yml/.sh/.py/.pdf/.docx/.xlsx/.pptx/.eml/.htm/.html | 可分析扩展名（:505-508、560-565） |
| 10 | 兜底 | 其余一切（:566） |

注意分值顺序不是单调的：5 分的大路货检查在 30 分的扩展名检查**之前**——`/usr/share/doc/readme.txt` 得 5 而不是 30（先命中 bulk 规则）。改优先级只需动这张表，排序/截断/回退管线全部不动。

## 10. 新走读分支：两个分析循环的错误路径差异（二轮走读）

full 与 smart 的循环体（:145-175、:199-234）**不完全同构**，差异值得记录。full 循环：

```cpp
// LLMAnalysisService.cpp:145-175（节选）
for (size_t i = 0; i < files.size(); ++i) {
    if (progressCallback) {
        if (!progressCallback(i + 1, total, filePath)) {
            std::cout << "LLM full-mode analysis stopped by callback after "
                      << i << "/" << total << " files" << std::endl;
            break;  // task cancelled
        }
    }
    try {
        std::string localPath = resolveFileForAnalysis(filePath);
        if (localPath.empty()) { continue; }  // extraction failed

        auto result = fileAnalyzer_->analyzeFile(localPath, options.maxContentLength);
        if (result.success) {
            storeDescription(filesDbPath, filePath, result.description,
                             result.summary, result.keywords, result.modelUsed);
            analyzed++;   // ← 不检查 storeDescription 返回值
        }
    } catch (const std::exception& e) {
        std::cerr << "Failed to analyze file " << filePath << ": " << e.what() << std::endl;
    }
}
```

三个此前未记录的细节：

1. **full 模式对模型失败完全静默**——`result.success==false` 时没有任何日志（smart 模式 :225-230 才补了 Warning，注释自述"previously silent — the task summary under-reported"）。full 模式的失败文件无声消失。
2. **analyzed 不看写库结果**——两个循环都在 `result.success` 后直接 `analyzed++`，storeDescription 返回 false（含 §9.1 唯一守卫拒绝）不影响计数。返回值是"模型成功的文件数"而非"成功落库的文件数"。
3. **analyzeFile 收到 maxContentLength**——截断发生在 FileAnalyzer 内部（本模块不预截），`options.maxContentLength` 逐文件传入；而 smart 选择 prompt 的 48000 字符预算是另一个独立常量。

## 11. 配置影响表（全集）

| 配置 | 默认 | 消费链 | 说明 |
|---|---|---|---|
| `LLM_MAX_FILES` | 500 | ConfigManager.cpp:91 → TaskManagerAnalysis.cpp:345 → AnalysisOptions.maxFiles | smart/full 共同预算 |
| `LLM_MAX_CONTENT_LENGTH` | 10000 | ConfigManager.cpp:96 → :346 → maxContentLength | 单文件截断；与 `FILE_ANALYSIS_MAX_CONTENT`（10000，FileAnalyzer 内部）是两个变量，都生效时取更紧 |
| `LLM_SKIP_BINARY` | true | ConfigManager.cpp:97 → :347 → skipBinaryFiles | 排除 Executables/Unknown 分类 |
| `LLM_TEXT_*` 五项 | 见 Environment.md | ModelRouter 文本模型 | 每文件 LLM 调用 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 120 / 3 | LLMClient | 串行化下总时长 ≈ min(文件数,500) × 单次调用时长 |
| `FILE_ANALYSIS_MAX_KEYWORDS` | 10 | FileAnalyzer | 解析出的关键词数上限（keywords join 进 llm_keywords） |
| `llm_mode`（任务字段） | "smart" | TaskManagerAnalysis.cpp:398 | 选 full 或 smart 入口 |
| （无 48000 字符预算的 env） | 48000 硬编码 | :280 kMaxSummaryChars | 选择 prompt 上限不可配 |

## 12. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调 | TaskManagerAnalysis.cpp:334-391 | 流水线 LLM_ANALYSIS 阶段 | 唯一流水线调用方 |
| 依赖 | llm::ModelRouter / llm::FileAnalyzer | initialize() | 文本模型 + 单文件分析 |
| 依赖 | ::FileExtractor（TSK） | resolveFileForAnalysis 惰性建 | 镜像内抽取，复用单实例 |
| 写 | `_files.db` files.llm_* 五列 | UPDATE 带唯一路径守卫（§9.1） | 多分区重名路径写不进 |
| 写 | `_files.db` file_descriptions 表 | UPSERT，is_relevant=1 | 与 Python persist_to_files_db 同构 |
| 临时目录 | llm_scratch（LLMScratch） | dirForTask(taskId) | 任务级隔离；析构+删除任务双清理 |
| 平级 | EventClusterAnalyzer | 同阶段姊妹模块 | 事件簇侧；同一套回退哲学 |
| 不相往来 | LLMPythonProxy | 无直接调用 | 文件描述未走 Python（§1 矛盾的另一面） |
| 读出方 | 前端 Files 页/调查中心 | llm_* 列 + file_descriptions | Python 案件分析也读同表 |

## 13. getFilesFromDatabase 的候选查询契约（新走读分支）

full 模式的候选清单 SQL（:442-499）动态拼装，三个条件分支：

```cpp
// LLMAnalysisService.cpp:458-487（节选）
std::string sql = "SELECT path FROM files";
if (!options.fileTypes.empty()) {
    // category IN ('type1','type2') —— 字符串拼接！
}
if (options.skipBinaryFiles) {
    conditions.push_back("category NOT IN ('Executables', 'Unknown Files')");
}
sql += " LIMIT " + std::to_string(options.maxFiles);
```

四个此前未记录的事实：

1. **fileTypes 是拼接进 SQL 的**（:463-470 单引号包裹直接拼）——当前流水线恒传空（无 env 映射到此字段），注入面休眠；**任何未来把用户输入接进 AnalysisOptions.fileTypes 的改动都会打开 SQL 注入**——接之前必须改参数化；
2. **skipBinaryFiles 的排除集是精确两值**：'Executables' 与 'Unknown Files'（:475）——注意 'Unknown Files' 带空格，是 FileClassifier 的分类串原样；其他二进制类（如 Archive）**不被排除**；
3. **无 ORDER BY**：候选按 rowid 自然序返回，LIMIT 截断等于"入库顺序的前 N 个"——与 smart 模式的取证优先级排序形成对照（full 的截断不偏向高价值文件）；
4. 查询只取 path 一列——分类、大小等上下文在 analyzeFile 阶段经 detectFileType 重取，不依赖此查询。

## 14. 双写一致性矩阵（files 行 × file_descriptions 行）

storeDescription 两段写的四种结局（§9-10 的补充视角）：

| files UPDATE | file_descriptions UPSERT | 返回值 | 后果 |
|---|---|---|---|
| 成功 | 成功 | true | 一致——正常路径 |
| 成功 | prepare 失败（静默） | true | **半写**：files 有 llm_*，证据列表（读 file_descriptions 的消费方）看不到该文件 |
| 守卫拒绝（重名 path） | 已执行 | **false** | 不一致的反向：file_descriptions 有行而 files 无注解（重跑后可能出现） |
| prepare 失败 | — | false | 都没写 |

第二种"半写"无任何日志（descStmt 的 prepare 失败分支什么都不打，:421-422 的 if 只在成功时执行）——排查"files 有描述但调查中心没有"时此处是首查点。前端调查中心读 file_descriptions（Python 侧同表），Files 页读 files.llm_*——两页数据不一致的根源多半在这。

## 15. 验证 runbook

```bash
# 1. smart 兜底链验证：停掉 LLM 端点后跑 llm 任务
#    日志应出现 "falling back to heuristic file selection"
# 2. 唯一守卫验证：对多分区镜像（两个分区都有 /etc/passwd）跑完查
sqlite3 data/tasks/<id>/*_files.db \
  "SELECT path, COUNT(*) c FROM files GROUP BY path HAVING c > 1 LIMIT 5"
#    这些 path 的 llm_analyzed_at 应为 NULL（§9.1 守卫拒绝）
# 3. 双写核对
sqlite3 data/tasks/<id>/*_files.db \
  "SELECT (SELECT COUNT(*) FROM files WHERE llm_analyzed_at>0),
          (SELECT COUNT(*) FROM file_descriptions)"
#    两数不等 => §14 半写发生
# 4. 临时目录清理
ls /tmp/forensics_llm_extract/<task_id>/ 2>/dev/null   # 任务删除后应不存在
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
