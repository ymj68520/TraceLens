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

- 上游：任务流水线（LLM_ANALYSIS 阶段尾部，进度占 90-95%）与 EventClusterRoutes 的四个端点（analyze/batch-analyze/reanalyze/analyzed）。
- 下游：只读 `_events.db` 的 events 表、只写簇级 LLM 列（经 `EventExtractorSQL::UPDATE_EVENT_CLUSTER_LLM_ANALYSIS`，EventClusterAnalyzer.cpp:305-323）；LLM 经 ModelRouter 使用 ConfigManager 的文本模型配置（:18-40）。

## 3. 核心概念与设计

### 3.1 簇的定义是 SQL，不是代码

`getAllEventClusters`（EventClusterAnalyzer.cpp:432-472）的一条 GROUP BY 就是簇的全部语义：

```sql
SELECT (timestamp / 60) AS time_window, event_type,
       ...parent_directory...
FROM events
GROUP BY time_window, event_type, parent_directory
ORDER BY COUNT(*) DESC
```

即：**同一分钟（timestamp/60 取整）、同类型、同父目录**的事件为一个簇，按事件量降序返回。时间窗固定为 60 秒——这与 SQLiteHelper 时间线路由的 `bucket_seconds`（默认 60）默认对齐，改动任何一侧都要想着另一侧。

### 3.2 full / smart 两种分析策略

- **full**（analyzeEventClusters，:121-150）：拿全部簇逐个分析。簇多时耗时与费用线性增长。
- **smart**（analyzeSmartEventClusters，:152-170）：先让 LLM 从簇清单里挑重要的，再只分析选中的。预算 `maxClusters` 由任务流水线从 `LLM_MAX_EVENT_CLUSTERS` 读取（TaskManagerAnalysis.cpp:416-419），**0 表示不限额**（ConfigManager.cpp:92-93 默认 0）。

### 3.3 smart 的降级链：LLM 不可靠时不空手而归

`selectImportantEventClusters`（:172-276）有三层兜底，保证选择阶段永远返回可用清单：

1. 簇总数 ≤ 预算 → 直接全要，根本不调 LLM（:187-189）；
2. LLM 调用失败 / 返回解析失败 → 截断到预算取前 N（`truncateToConfiguredLimit`，:194-199、:231-234、:250-253）；
3. LLM 返回的索引解析后一个都对不上 → 同样截断兜底（:264-269）。

对 LLM 返回只信"形如 [0,2,5] 的 JSON 数组"，用 find('[')/rfind(']') 截取后解析（:239-249），并对越界索引过滤（:257-261）。

### 3.4 取消经进度回调

`ProgressCallback` 返回 false 即停止（:136-142），任务流水线借它在用户取消任务时中断簇分析循环（TaskManagerAnalysis.cpp:407-411）。

## 4. 工作流程走读

单个簇的分析（analyzeEventCluster，:42-119）：

1. `getClusterEvents` 取簇内事件（SQL 在 :357-383，按 time_window+event_type+目录 LIKE 过滤）；
2. `buildClusterSummary` 拼簇摘要——**最多列 20 条事件**，其余以 "... and N more" 概括（:401-430），控制 prompt 长度；
3. 固定 prompt 要求 LLM 只回 JSON：`{summary, description, keywords[], is_relevant}`（:63-81）；
4. 解析结果后 `storeClusterDescription`（:278-341）把 summary/description/keywords（逗号拼接）/时间戳/模型名/is_relevant 写回 events 库的对应簇行；**更新行数为 0 视为失败**（:335-338），防止"写了个寂寞"还报成功。

流水线批量路径见 TaskManager.md §4 第 6 步；时间线页点"分析此簇"时走 EventClusterRoutes 复用同一入口。

## 5. 与其他模块的协作

- **TaskManager**：LLM_ANALYSIS 阶段的调用者与进度上报者。
- **EventClusterRoutes**：按需重分析的 REST 入口；"analyzed" 端点读取这里写入的簇 LLM 列。
- **ModelRouter / ConfigManager**：文本模型配置（与 LLMAnalysisService、平台 LLM 服务共用 getTextModelConfig）。
- **SQLiteHelper::get_comprehensive_timeline**：消费同一套簇定义（bucket_seconds 聚类）展示簇列表——分析结果与展示分组天然对齐。

## 6. 注意事项与已知问题

- **时间窗硬编码 60 秒**：簇键的 `/60` 写死在两处 SQL（:357、:443-451）；若前端以非默认 bucket_seconds 聚簇展示，再触发重分析会按 60 秒窗错位。
- **is_relevant 完全信任 LLM**：没有规则校验，误判会直接落库并影响调查中心证据列表的展示权重。
- **full 模式无预算**：`LLM_MAX_EVENT_CLUSTERS=0`（默认）+ smart 模式时"全量"其实等价于"LLM 选全部"；真正的无界全量只在 full 模式发生，大事件库慎用。
- **keywords 存成逗号串**：关键词含逗号时会破坏可读性（:294-300）。

## 7. 如何验证与扩展

- **验证**：跑一个 llm_analyze=true 的任务后，对 `_events.db` 查询簇行（`SELECT time_window, event_type, llm_summary, llm_is_relevant FROM events ... LIMIT 20`）确认 llm_* 列已填充；或在时间线页展开簇抽屉触发 reanalyze 端点。
- **扩展**：新的簇级字段（如 risk_score）需同时改 prompt（:63-81）、解析（:100-110）、`UPDATE_EVENT_CLUSTER_LLM_ANALYSIS` SQL 与展示路由；若要支持可变时间窗，建议把 `/60` 参数化并让调用方传入 bucket_seconds（默认 60 保持兼容）。

**最后更新**: 2026-08-23（解释式重写）
