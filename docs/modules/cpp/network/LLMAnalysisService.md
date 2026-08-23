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

## 3. 核心概念与设计

### 3.1 full / smart 两模式

- `analyzeAllFiles`（:122-178）：取库内文件（按 category 过滤、skipBinaryFiles 默认排除 Executables/Unknown，:442-499）截断到 maxFiles 逐个分析。
- `analyzeSmartFiles`（:180-237）：先 `selectImportantFiles` 选出重要文件再逐个分析。预算 `maxFiles` 来自 `LLM_MAX_FILES`（默认 500，ConfigManager.cpp:91）——流水线注释特别指出旧的硬编码下限 1000 曾让本地 LLM 任务跑数小时（TaskManagerAnalysis.cpp:369-372）。

### 3.2 smart 选文件的防线（这是本模块最精彩的部分）

`selectImportantFiles`（:239-340）的筛选管线，每一步都在防"LLM 不靠谱"：

1. **预算内直接返回**：文件数 ≤ maxFiles 就不用选（:256-258）；
2. **剔除 TSK 虚拟条目**：`$` 开头的 `$MFT` 类伪文件不是可分析证据（:261-269）；
3. **启发式排序限长**：`forensicPathPriority`（:501-567）按取证价值打分——凭证/历史类 100 分、/home 与用户目录 90、/var/log 80、浏览器/邮件 75、.db/.sqlite 70、/etc 60、/boot/cron 50、/usr/share 等大路货 5 分——排序后把送选 prompt 控制在 48000 字符内（:278-292），防止上下文爆炸导致选择调用必败；
4. **LLM 选择 + 三重回退**：调用失败、返回可用路径少于预算的 1/4、抛异常，任何一种都回退 `selectByHeuristic`（:316-339）；解析端还会拒掉 `""`/`"/"` 这类会"匹配一切"的垃圾项（:620-629）。

### 3.3 从镜像抽文件：宁可慢，不可错

`resolveFileForAnalysis`（:60-120）有一个明确的安全决策：**配置了镜像就永远从镜像抽取，绝不走宿主机 fs::exists 快路径**（:66-68 注释解释：否则会"分析分析师自己的 /etc/passwd"而不是证据）。工程细节：

- 复用单个 FileExtractor 实例——逐文件重开镜像+分区+DB 会支配总耗时（:74-81）；
- 路径扁平化为安全文件名，放进任务专属 llm_scratch 目录，避免并发任务互踩与目录穿越（:84-95）；
- 对首斜杠差异做正反两次重试（:101-112）。

### 3.4 双写：files.llm_* 与 file_descriptions

`storeDescription`（:342-440）先 UPDATE files 行（`FileClassifierSQL::UPDATE_FILE_LLM_ANALYSIS`，:369），再 UPSERT 进 `file_descriptions` 且 `is_relevant=1`（:398-430）——与 Python 侧 `persist_to_files_db` 保持同构，保证"调查中心证据列表"能看到主流水线产出的 AI 分析（:394-397 注释）。

## 4. 工作流程走读

smart 模式一次任务（TaskManagerAnalysis.cpp:367-384 驱动）：

1. `initialize` 建文本模型 ModelRouter（:27-50）；`setSceneType` + `setImagePaths(镜像, effectiveRawDb, task_id)`（TaskManagerAnalysis.cpp:341-344）；
2. `analyzeSmartFiles` → `selectImportantFiles`（§3.2 管线）得到 ≤500 个路径；
3. 循环：进度回调（返回 false 即任务取消，:203-208）→ `resolveFileForAnalysis` 抽文件 → `FileAnalyzer::analyzeFile` → 成功则双写库；失败现在会打 Warning（:225-230，旧版静默导致统计失真）；
4. 返回分析数，流水线汇报 "stored in _files.db"（TaskManagerAnalysis.cpp:386-387）。

full 模式仅第 2 步不同（无选择，直接截断）。

## 5. 与其他模块的协作

- **TaskManager**：唯一流水线调用方；进度/取消经回调。
- **FileExtractor（TSK）**：镜像内文件抽取。
- **ModelRouter/FileAnalyzer（LLMIntegration）**：实际模型调用，配置来自 ConfigManager 文本模型。
- **FileClassifierSQL / file_descriptions**：结果存储契约，Python 侧同步遵守。
- **LLMScratch**：任务级抽取临时目录的分配与清理（析构 + TaskManager 删除任务兜底 TaskManager.cpp:345）。
- **EventClusterAnalyzer**：姊妹模块，同一模式下对事件簇做类似的事。

## 6. 注意事项与已知问题

- **deprecated 注释与现状不符**：见 §1，以流水线实际调用为准。
- **结果写回依赖 path 精确匹配**：UPDATE 以 path 为键（:382），行数为 0 会记 Warning 并返回 false（:434-437）——镜像路径大小写/斜杠差异会导致"分析了却没写进"。
- **场景感知 API 未入主流水线**：`getScenePrioritizedFiles/shouldSkipFile/getSceneSpecificPrompt`（:675-767）只在直接调用时生效，analyzeAll/Smart 路径不经过它们。
- **maxContentLength 默认 10000 字符**：超大文件被截断描述（AnalysisOptions，LLMAnalysisService.h:31-36）。
- **抽取失败静默跳过**：resolve 返回空串时 continue（:159-161），统计里的 analyzed 数不含这些文件。

## 7. 如何验证与扩展

- **验证**：跑 llm_analyze=true + llm_mode=smart 的小镜像任务，检查 `_files.db`：`SELECT path, llm_summary, llm_model_used FROM files WHERE llm_analyzed_at > 0 LIMIT 10`，并确认 file_descriptions 有同批行；关掉 LLM 服务再跑，确认日志出现 "falling back to heuristic" 且任务仍完成（兜底生效）。
- **扩展**：调整优先级规则改 `forensicPathPriority`（:501-567）的模式表即可，无需动选择管线；新增输出字段要同步 prompt、解析、UPDATE_FILE_LLM_ANALYSIS、file_descriptions UPSERT 四处与 Python 侧。

**最后更新**: 2026-08-23（解释式重写）
