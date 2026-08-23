# EventClusterAnalyzer（src/network/HTTPServer/EventClusterAnalyzer.{h,cpp}）

> **一句话**：把时间线事件按"分钟窗 × 事件类型 × 父目录"聚成簇，再用 LLM 为每个簇生成摘要/描述/关键词/相关性判断，写回 _events.db——让调查员读"几十个故事"而不是"几万条事件"。

## 1. 为什么有这个模块

`_events.db` 的 events 表动辄数万行。逐条人工审查不现实；逐条喂 LLM 又贵又慢。折中方案是**先聚类再分析**：同一分钟、同一类型、同一目录下的事件（通常本来就是一次操作的副产物）合并为一个"簇"，LLM 只需要理解簇级别的叙事。这层抽象同时服务两个消费端：任务流水线（批量预分析）与时间线页的簇抽屉（按需重分析）。

## 2. 在系统中的位置

```
TaskManager::start_analysis (TaskManagerAnalysis.cpp:393-434)
    └─ llm_analyze=true 时调用 ──▶ EventClusterAnalyzer ──写──▶ _events.db 事件簇 LLM 列
EventClusterRoutes (/api/forensics/timeline/clusters/*)
    └─ 时间线页簇抽屉按需 analyze/reanalyze ──▶ 同一服务
                                          ──读──▶ llm::ModelRouter（文本模型）
```

- 上游：任务流水线（LLM_ANALYSIS 阶段尾部，进度占 90-95%）与 EventClusterRoutes 的四个端点（analyze/batch-analyze/reanalyze/analyzed，EventClusterRoutes.cpp:13-67）。
- 下游：只读 `_events.db` 的 events 表、只写簇级 LLM 列（经 `EventExtractorSQL::UPDATE_EVENT_CLUSTER_LLM_ANALYSIS`，EventClusterAnalyzer.cpp:305-323）；LLM 经 ModelRouter 使用 ConfigManager 的文本模型配置（:18-40）。

## 3. 核心概念与设计

### 3.1 簇的表示：三元组 std::tuple，没有结构体

本模块没有为"簇"定义专门类型，全部用裸 tuple 传递（EventClusterAnalyzer.h:27-60）：

```cpp
// src/network/HTTPServer/EventClusterAnalyzer.h:27-45（节选）
// 分析单个事件簇
bool analyzeEventCluster(const std::string& eventsDbPath, 
                       int64_t timeWindow, 
                       const std::string& eventType, 
                       const std::string& parentDirectory);

// 批量分析事件簇
int analyzeEventClusters(const std::string& eventsDbPath,
                        const std::vector<std::tuple<int64_t, std::string, std::string>>& clusters,
                        ProgressCallback progressCallback = nullptr);

// 智能分析（只分析重要的事件簇）
int analyzeSmartEventClusters(const std::string& eventsDbPath,
                             size_t maxClusters,
                             ProgressCallback progressCallback = nullptr);
```

- `std::tuple<int64_t, std::string, std::string>` 即 `(timeWindow, eventType, parentDirectory)`——簇的**完整身份**就是这三元组，它同时是查询键（WHERE 条件）与回写键（UPDATE 的 WHERE）；
- 簇内事件是五元组 `tuple<int64_t, string, string, int64_t, string>` = `(timestamp, event_type, file_path, file_size, description)`（getClusterEvents 的返回，:67-71），仅供拼 prompt，不落库；
- `ProgressCallback = function<bool(int,int,const string&)>`（h:24）：当前序号/总数/事件类型，返回 false 即取消。

### 3.2 簇的定义是 SQL，不是代码

`getAllEventClusters`（EventClusterAnalyzer.cpp:432-472）的一条 GROUP BY 就是簇的全部语义：

```sql
-- src/network/HTTPServer/EventClusterAnalyzer.cpp:443-451
SELECT 
    (timestamp / 60) as time_window, 
    event_type, 
    CASE WHEN file_path LIKE '%/%' THEN RTRIM(file_path, REPLACE(file_path, '/', '')) ELSE '' END as parent_directory
FROM events
GROUP BY time_window, event_type, parent_directory
ORDER BY COUNT(*) DESC
```

即：**同一分钟（timestamp/60 取整）、同类型、同父目录**的事件为一个簇，按事件量降序返回。`RTRIM(file_path, REPLACE(file_path,'/',''))` 是 SQLite 惯用的"掐掉最后一段"技巧——把非斜杠字符全删掉剩下斜杠串，再从尾部裁掉这串斜杠，等价于 dirname。时间窗固定为 60 秒——这与 SQLiteHelper 时间线路由的 `bucket_seconds`（默认 60）默认对齐，改动任何一侧都要想着另一侧。

取簇内事件的 SQL（:357-367）复用同一个 `/60` 口径：

```cpp
// src/network/HTTPServer/EventClusterAnalyzer.cpp:357-367
std::string sql = "SELECT timestamp, event_type, file_path, file_size, description FROM events WHERE (timestamp / 60) = ? AND event_type = ?";

if (!parentDirectory.empty()) {
    if (parentDirectory == "/") {
        sql += " AND (file_path NOT LIKE '%/%' OR file_path LIKE '/%')";
    } else {
        sql += " AND file_path LIKE ?";
    }
}

sql += " ORDER BY timestamp ASC";
```

目录过滤有两分支：普通目录用 `parentDirectory + "%"` 前缀 LIKE（:381-382）；根目录 `"/"` 特判为"根下文件"（路径不含斜杠或以单斜杠开头）。ORDER BY timestamp ASC 保证 buildClusterSummary 里的首尾时间戳（:408-410）有意义。

### 3.3 full / smart 两种分析策略

- **full**（analyzeEventClusters，:121-150）：拿全部簇逐个分析。簇多时耗时与费用线性增长。
- **smart**（analyzeSmartEventClusters，:152-170）：先让 LLM 从簇清单里挑重要的，再只分析选中的。预算 `maxClusters` 由任务流水线从 `LLM_MAX_EVENT_CLUSTERS` 读取（TaskManagerAnalysis.cpp:416-419），**0 表示不限额**（ConfigManager.cpp:92-93 默认 0）。

### 3.4 smart 的降级链：LLM 不可靠时不空手而归

`selectImportantEventClusters`（:172-276）的核心防御结构：

```cpp
// src/network/HTTPServer/EventClusterAnalyzer.cpp:186-199
// 少于预算时无需让 LLM 选择；0 means no upper limit.
if (maxClusters > 0 && allClusters.size() <= maxClusters) {
    return allClusters;
}

const size_t selectionLimit = maxClusters > 0 ? maxClusters : allClusters.size();

auto truncateToConfiguredLimit = [&]() {
    if (maxClusters > 0 && allClusters.size() > maxClusters) {
        allClusters.resize(maxClusters);
    }
    return allClusters;
};
```

`truncateToConfiguredLimit` 是捕获引用的 lambda，在后续**每一个失败出口**被复用，构成三层兜底：

1. 簇总数 ≤ 预算 → 直接全要，根本不调 LLM（:187-189）；
2. LLM 调用失败 / 返回解析失败 → 截断到预算取前 N（:194-199、:231-234、:250-253）；
3. LLM 返回的索引解析后一个都对不上 → 同样截断兜底（:264-269）。

对 LLM 返回只信"形如 [0,2,5] 的 JSON 数组"：

```cpp
// src/network/HTTPServer/EventClusterAnalyzer.cpp:239-249、257-261（节选）
size_t start = response.content.find('[');
size_t end = response.content.rfind(']');
if (start != std::string::npos && end != std::string::npos && end > start) {
    std::string jsonStr = response.content.substr(start, end - start + 1);
    auto jsonArray = nlohmann::json::parse(jsonStr);
    for (const auto& item : jsonArray) {
        if (item.is_number()) {
            selectedIndices.push_back(item.get<size_t>());
        }
    }
}
// ...
for (size_t index : selectedIndices) {
    if (index < allClusters.size()) {          // 越界索引静默过滤
        importantClusters.push_back(allClusters[index]);
    }
}
```

find/rfind 截取能容忍模型在 JSON 前后加解释文字；越界索引过滤防模型幻觉出不存在的簇号；若过滤后一个不剩则走第 3 层兜底（"falling back to first N clusters"，:265-268）。**截断的前 N 由 getAllEventClusters 的 ORDER BY COUNT(*) DESC 保证是事件量最大的簇**——兜底也是"最热闹优先"，不是随机。

### 3.5 取消经进度回调

`ProgressCallback` 返回 false 即停止（:136-142），任务流水线借它在用户取消任务时中断簇分析循环（TaskManagerAnalysis.cpp:407-411）。

## 4. 核心接口清单

| 方法（真实签名，EventClusterAnalyzer.h） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `bool initialize()` | 惰性建 ModelRouter（文本模型） | 内部首调 + 外部 | 异常打印并返回 false |
| `bool analyzeEventCluster(db, timeWindow, eventType, parentDirectory)` | 单簇全流程：取事件→prompt→chat→解析→回写 | analyzeEventClusters / EventClusterRoutes | 任一步失败返回 false，不落库 |
| `int analyzeEventClusters(db, clusters, cb)` | 逐簇循环 + 进度回调 | 流水线 full 模式（先 getAllEventClusters） | 单簇失败仅不计入返回值 |
| `int analyzeSmartEventClusters(db, maxClusters, cb)` | 选择 + 分析的复合入口 | 流水线 smart 模式 | 选出 0 簇时打日志返回 0 |
| `vector<tuple<...>> selectImportantEventClusters(db, maxClusters)` | §3.4 降级链 | smart 入口 / 可独立调用 | 永不抛出，最差返回截断清单 |
| `bool storeClusterDescription(db, key..., summary, description, keywords, modelUsed, isRelevant)` | 簇级回写 | analyzeEventCluster | 更新行数 0 视为失败（:335-338） |
| `vector<tuple<...>> getAllEventClusters(db)` | 枚举全部簇（降序） | 流水线 full / selectImportant | 开库失败返回空 vector |

## 5. 工作流程走读

单个簇的分析（analyzeEventCluster，:42-119）：

1. `getClusterEvents` 取簇内事件（SQL 在 :357-383，按 time_window+event_type+目录 LIKE 过滤）；
2. `buildClusterSummary` 拼簇摘要——**最多列 20 条事件**，其余以 "... and N more" 概括（:401-430），控制 prompt 长度；
3. 固定 prompt 要求 LLM 只回 JSON：`{summary, description, keywords[], is_relevant}`（:63-81）；
4. 解析结果后 `storeClusterDescription`（:278-341）把 summary/description/keywords（逗号拼接）/时间戳/模型名/is_relevant 写回 events 库的对应簇行；**更新行数为 0 视为失败**（:335-338），防止"写了个寂寞"还报成功。

回写的绑定参数与检查（节选）：

```cpp
// src/network/HTTPServer/EventClusterAnalyzer.cpp:314-338
// Bind parameters
sqlite3_bind_text(stmt, 1, summary.c_str(), -1, SQLITE_TRANSIENT);
sqlite3_bind_text(stmt, 2, description.c_str(), -1, SQLITE_TRANSIENT);
sqlite3_bind_text(stmt, 3, keywordsStr.c_str(), -1, SQLITE_TRANSIENT);
sqlite3_bind_int64(stmt, 4, currentTime);
sqlite3_bind_text(stmt, 5, modelUsed.c_str(), -1, SQLITE_TRANSIENT);
sqlite3_bind_int(stmt, 6, isRelevant ? 1 : 0);
sqlite3_bind_int64(stmt, 7, timeWindow);
sqlite3_bind_text(stmt, 8, eventType.c_str(), -1, SQLITE_TRANSIENT);
sqlite3_bind_text(stmt, 9, parentDirectory.c_str(), -1, SQLITE_TRANSIENT);

rc = sqlite3_step(stmt);
int changes = sqlite3_changes(db);
// ...
if (changes == 0) {
    std::cerr << "Warning: No rows updated for event cluster" << std::endl;
    return false;
}
```

注意 UPDATE 的 WHERE 是**三键同时匹配**（timeWindow/eventType/parentDirectory，参数 7-9）——一个簇的所有事件行都会被同一组 llm_* 值覆盖。`sqlite3_changes` 取的是本次连接的变更行数，恰好等于簇内行数；为 0 说明簇键对不上（比如事件已被清理或键口径变化），按失败处理。另一个细节：keywords 在 :294-300 用逗号 join 成单串存进 llm_keywords 列——模型返回的关键词若自身含逗号则无法还原。

流水线批量路径见 TaskManager.md §4 第 6 步；时间线页点"分析此簇"时走 EventClusterRoutes 复用同一入口。

## 6. 与其他模块的协作

- **TaskManager**：LLM_ANALYSIS 阶段的调用者与进度上报者（TaskManagerAnalysis.cpp:398-433）。
- **EventClusterRoutes**：按需重分析的 REST 入口；"analyzed" 端点读取这里写入的簇 LLM 列。
- **ModelRouter / ConfigManager**：文本模型配置（与 LLMAnalysisService、平台 LLM 服务共用 getTextModelConfig）。
- **SQLiteHelper::get_comprehensive_timeline**：消费同一套簇定义（bucket_seconds 聚类）展示簇列表——分析结果与展示分组天然对齐。

## 7. 注意事项与已知问题

- **时间窗硬编码 60 秒**：簇键的 `/60` 写死在两处 SQL（:357、:443-451）；若前端以非默认 bucket_seconds 聚簇展示，再触发重分析会按 60 秒窗错位。
- **is_relevant 完全信任 LLM**：没有规则校验，误判会直接落库并影响调查中心证据列表的展示权重。
- **full 模式无预算**：`LLM_MAX_EVENT_CLUSTERS=0`（默认）+ smart 模式时"全量"其实等价于"LLM 选全部"；真正的无界全量只在 full 模式发生，大事件库慎用。
- **keywords 存成逗号串**：关键词含逗号时会破坏可读性（:294-300）。
- **簇键就是文本匹配**：parentDirectory 用 LIKE 前缀匹配，目录名含 `%`/`_` 等 LIKE 元字符的病态路径会被误并簇/漏簇（罕见但存在）。

## 8. 如何验证与扩展

- **验证**：跑一个 llm_analyze=true 的任务后，对 `_events.db` 查询簇行（`SELECT time_window, event_type, llm_summary, llm_is_relevant FROM events ... LIMIT 20`）确认 llm_* 列已填充；或在时间线页展开簇抽屉触发 reanalyze 端点。
- **扩展**：新的簇级字段（如 risk_score）需同时改 prompt（:63-81）、解析（:100-110）、`UPDATE_EVENT_CLUSTER_LLM_ANALYSIS` SQL 与展示路由；若要支持可变时间窗，建议把 `/60` 参数化并让调用方传入 bucket_seconds（默认 60 保持兼容）。

## 9. 端点契约全表（EventClusterRoutes，二轮补全）

四个端点（EventClusterRoutes.cpp:13-77）的完整契约。**新发现**：`analyze` 端点是 **410 Gone 弃用桩**（:85-91），不再触达本模块——单簇分析已迁 Python（前端 forensicsService.analyzeEventCluster 直打 8090 的 `/api/llm/analyze-event-cluster`）；仍会触达本模块的只剩 batch-analyze / reanalyze / analyzed 三个。

| 端点 | 方法 | 请求字段 | 成功响应 | 失败响应 | handler |
|---|---|---|---|---|---|
| `clusters/analyze` | POST | （忽略一切 body） | **410** `{success:false, message:"DEPRECATED: Please use Python API /api/llm/analyze-event-cluster (Port 8090) instead."}` | — | :80-92 |
| `clusters/batch-analyze` | POST | `task_id`（必填）、`clusters[]`（必填数组；每项 `{time_window:int64, event_type:string, parent_directory:string=""}`，缺前两者的项**静默跳过**） | 200 `{success:true, message:"Batch analysis completed", analyzed_count:int, total_count:int}` | 400（task_id/clusters 缺失、数组全无效、JSON 坏）；500（其他异常） | :94-158 |
| `clusters/reanalyze` | POST | `task_id`、`time_window`（int64，必填）、`event_type`（必填非空）、`parent_directory`（默认 ""） | 200 `{success:true, message:"Event cluster reanalyzed successfully"}` | 400（字段缺失/JSON 坏）；500 `{"error":"Failed to reanalyze event cluster"}` | :160-216 |
| `clusters/analyzed` | GET | query：`task_id`（必填） | 200 `{clusters:[...], total_count:int}` | 400（缺 task_id）；500 | :218-315 |

`analyzed` 的簇对象 14 字段（:279-300）：`time_window`、`event_type`、`parent_directory`、`timestamp`/`end_timestamp`（簇内首末事件时间，前端 `new Date(timestamp*1000)` 展示）、`cluster_count`（"N 个事件"徽标）、`file_path`（代表文件，GROUP BY 里的任意行）、`file_size`（SUM）、`llm_summary`/`llm_description`/`llm_keywords`/`llm_analyzed_at`/`llm_model_used`/`llm_is_relevant`（均 MAX 聚合——簇内所有行被 UPDATE 成同值，MAX 恒等）。SQL 的 WHERE `llm_analyzed_at IS NOT NULL`（:262）即"已分析"的判据，ORDER BY llm_analyzed_at DESC 最近分析的排前面。

**批量端点的同步阻塞**：batch-analyze 在 HTTP handler 内直接构造 `EventClusterAnalyzer` 并同步循环调 LLM（:137-138）——没有线程池、没有作业化。几十个簇 × 每簇一次 LLM 往返（LLM_TIMEOUT_SECONDS 默认 120s）意味着这个 HTTP 请求可能挂几分钟到几小时；Crow worker 被占用、前端 axios 默认超时会先断。对比之下 analyze 单簇路径已被 Python 端的异步作业替代——batch-analyze 是"该迁未迁"的遗留。

## 10. 簇级 LLM 列的数据契约（events 表）

本模块读写的 events 表簇级列（建表与 UPDATE SQL 归 EventExtractor/EventExtractorSQL，本模块是主要写方）：

| 列 | 写入方（EventClusterAnalyzer.cpp:305-338） | 语义 | 读出方 |
|---|---|---|---|
| `llm_summary` | bind 1 | LLM 一句话摘要 | analyzed 端点、综合时间线路由 |
| `llm_description` | bind 2 | LLM 详细描述 | 同上 |
| `llm_keywords` | bind 3（逗号 join 的串） | 关键词列表（含逗号不可还原，§7） | 同上 |
| `llm_analyzed_at` | bind 4（time_t 秒） | 分析时间戳；NULL=未分析（analyzed 端点的过滤键） | 同上 |
| `llm_model_used` | bind 5 | 模型标识（ModelRouter 配置名） | 同上 |
| `llm_is_relevant` | bind 6（0/1） | LLM 相关性判断 | 证据列表权重 |

UPDATE 语义（`UPDATE_EVENT_CLUSTER_LLM_ANALYSIS`，:305-323）：SET 六列，WHERE 三簇键（bind 7-9：timeWindow/eventType/parentDirectory）——**簇键即主键**，一次更新簇内全部事件行；`sqlite3_changes()==0` 判失败（:335-338）。重分析（reanalyze 端点）就是同一条 UPDATE 再跑一遍，旧值被无条件覆盖，无版本概念。

## 11. 配置影响表（EventClusterAnalyzer 视角）

| 配置 | 默认 | 消费点 | 影响 |
|---|---|---|---|
| `LLM_MAX_EVENT_CLUSTERS` | 0（不限） | TaskManagerAnalysis.cpp:416 → smart 的 maxClusters | >0 时 smart 选择预算；full 不受它限制 |
| `LLM_TEXT_BASE_URL/MODEL/MAX_TOKENS/TEMPERATURE` | 见 Environment.md | ModelRouter 文本模型配置（:18-40） | 每簇 LLM 调用的模型行为 |
| `LLM_TIMEOUT_SECONDS` | 120 | LLMClient 层 | 单簇最长等待；batch-analyze 总时长 ≈ 簇数 × 此值 |
| `LLM_MAX_RETRIES` | 3 | LLMClient 层 | 实为 4 次尝试（首试+3 重试），4xx 也重试 |
| `llm_mode`（任务字段） | "smart" | TaskManagerAnalysis.cpp:398 分支 | full→analyzeEventClusters；smart→analyzeSmartEventClusters |
| （无时间窗配置） | 60 秒硬编码 | :357、:443-451 两处 `/60` | 不可配；与前端 bucket_seconds 默认值对齐是隐式契约 |

## 12. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调 | TaskManagerAnalysis.cpp:398-434 | 流水线 LLM_ANALYSIS 尾部 | full/smart 两入口 + 进度回调（取消） |
| 被调 | EventClusterRoutes batch-analyze/reanalyze | 同步调用 | handler 内临时构造实例（非单例） |
| 不再被调 | EventClusterRoutes analyze | 410 桩 | 已迁 Python `/api/llm/analyze-event-cluster` |
| 依赖 | llm::ModelRouter（shared_ptr 成员） | initialize() 惰性建 | 与 LLMAnalysisService 共享配置读法 |
| 读写 | `_events.db` events 表 | 读事件/写 llm_* 列 | 只写六列，不碰事件本体 |
| 被 Python 替代 | python_service `/api/llm/analyze-event-cluster` | 前端直调 | 单簇路径的去向；批量路径仍在 C++ |
| 展示对齐 | SQLiteHelper::get_comprehensive_timeline | 同一 `/60` 聚类口径 | bucket_seconds≠60 时错位（§7 已记） |

## 13. buildClusterSummary 与 prompt 的完整契约（二轮补全）

每簇一次 LLM 调用的输入构造（EventClusterAnalyzer.cpp:401-430）：

- **事件上限 20 条**：簇内事件多于 20 时只列前 20，尾部拼 "... and N more"——**按 ORDER BY timestamp ASC 的前 20**（最早事件优先），长尾事件对模型不可见；
- **每行格式**：时间戳 + 类型 + 路径 + 大小 + 描述的五元组文本行；
- **首尾时间戳**：`events.front()/back()` 的 timestamp（依赖 SQL 的 ASC 排序，§3.2 已记）；
- **prompt 输出模板**：`{summary, description, keywords[], is_relevant}` 四键 JSON——与文件级 LLMAnalysisService 的 SUMMARY:/DESCRIPTION:/KEYWORDS: 文本协议**不同**，簇级是 JSON 协议且多一个 is_relevant 布尔；
- **解析**：`json::parse(response.content)` 裸解析（:100-110 一带）——与平台工件服务同款严格策略，模型输出 JSON 外带任何字即整簇作废；**没有** EventClusterAnalyzer 自己的 find('[') 容错（那是 selectImportantEventClusters 选择调用的路径，走的是 find('[')/rfind(']') 截取——同文件两种解析策略并存，见 :239-249 与 :100-110）。

## 14. analyzed 端点 SQL 的完整文本（供核对）

EventClusterRoutes.cpp:245-265 的查询原文（去掉缩进）：

```sql
SELECT
    (timestamp / 60) as time_window,
    event_type,
    CASE WHEN file_path LIKE '%/%' THEN RTRIM(file_path, REPLACE(file_path, '/', '')) ELSE '' END as parent_directory,
    MIN(timestamp) as timestamp,
    MAX(timestamp) as end_timestamp,
    COUNT(*) as cluster_count,
    file_path,
    SUM(COALESCE(file_size, 0)) as file_size,
    MAX(llm_summary) as llm_summary,
    MAX(llm_description) as llm_description,
    MAX(llm_keywords) as llm_keywords,
    MAX(llm_analyzed_at) as llm_analyzed_at,
    MAX(llm_model_used) as llm_model_used,
    MAX(llm_is_relevant) as llm_is_relevant
FROM events
WHERE llm_analyzed_at IS NOT NULL
GROUP BY time_window, event_type, parent_directory
ORDER BY llm_analyzed_at DESC
```

与分析器侧的簇定义 SQL（EventClusterAnalyzer.cpp:443-451）**同口径**（/60 窗 + 同 dirname 表达式）但多了 WHERE llm_analyzed_at——"展示已分析簇"与"枚举全部簇"是同一 GROUP BY 的两个过滤版本。file_path 与 MAX(llm_*) 的组内取值：file_path 是任意行（SQLite 未指定时取最后扫描行），llm_* 因簇内同值 MAX 恒等。

## 15. 验证 runbook

```bash
# 1. 触发批量分析（同步阻塞——注意会挂住 curl）
curl -s -X POST :8080/api/forensics/timeline/clusters/batch-analyze \
  -d '{"task_id":"<id>","clusters":[{"time_window":271828,"event_type":"CREATED","parent_directory":"/etc"}]}' | jq
# 2. 查已分析簇
curl -s ":8080/api/forensics/timeline/clusters/analyzed?task_id=<id>" | jq '.total_count'
# 3. 核对落库（llm_* 六列）
sqlite3 data/tasks/<id>/*_events.db "SELECT COUNT(*) FROM events WHERE llm_analyzed_at IS NOT NULL"
# 4. 弃用端点
curl -s -o /dev/null -w '%{http_code}\n' -X POST :8080/api/forensics/timeline/clusters/analyze   # 410
# 5. 重分析覆盖验证：同一簇 reanalyze 两次，llm_analyzed_at 应更新
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
