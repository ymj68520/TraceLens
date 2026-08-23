# 性能调优手册（PerformanceTuning）

> 适用场景：任务吞吐 / LLM 耗时 / SQLite 写入卡顿 / 图谱摄取吞吐 / 大镜像与 MIUI 备份解析失控等常见性能问题的旋钮调整。
> 前置：所有旋钮在 `.env`（改后重启 C++ / Python 服务生效）；本手册默认值以代码为准（`ConfigManager.cpp`、`httpserver/config.py`），与你环境 `.env` 的现值可能不同。

## 速查卡

```bash
# 看当前生效值（改 .env 前先记录）
grep -E "THREAD_POOL_SIZE|LLM_MAX|GRAPHITI_BATCH|DB_" .env

# 并发 / 线程
THREAD_POOL_SIZE=4            # 任务分析池 + LLM 批量并发共用（默认 4，>16 告警）
DB_BUSY_TIMEOUT_MS=5000       # SQLite 锁等待（默认 5000ms）

# LLM 限额三件套（C++ 侧读）
LLM_MAX_FILES=500             # smart/full 模式文件预算硬上限（默认 500）
LLM_MAX_CONTENT_LENGTH=10000  # 单文件送 LLM 的内容长度（默认 10000 字符）
LLM_MAX_EVENT_CLUSTERS=0      # 事件簇分析上限，0=不限（默认 0）

# 图谱批量与 8K 窗口
GRAPHITI_BATCH_SIZE=25        # .env.example 建议值（防 8096 token 溢出）
GRAPHITI_MAX_EPISODE_TOKENS=3000

# MIUI 解析限额（env，不经 .env 也可）
TRACELENS_MIUI_MAX_CANDIDATES / TRACELENS_MIUI_MAX_MANIFEST_PACKAGES ...

# 大镜像：先用过滤画像收窄
# 创建任务时 filter_profile 选 general_forensics/telecom_fraud/virus_intrusion/data_breach

# 观测基线（调优前后对比）
curl -s http://localhost:8666/api/tasks/statistics
curl -s http://localhost:8666/api/tasks/<task_id>/progress
```

## 1. THREAD_POOL_SIZE：并发任务与 LLM 并发共用一个旋钮

背景：这一个值同时决定两处并发，调大它是"全局提速"也是最易翻车的旋钮。

两处消费（读同一配置 `ConfigManager.cpp:138`）：
1. **任务分析池**：`TaskManager` 构造时 `analysis_pool_ = ThreadPool(pool_size)`（`TaskManager.cpp:21-31`）——决定同时跑几个分析任务；`pool_size <= 0` 会被钳到 2，`> 16` 打印警告 "seems high for forensics workloads"。
2. **LLM 批量并发**：`FileAnalyzer::analyzeBatch` 用同一个 poolSize 建临时线程池并发调用 LLM（`src/integration/LLMIntegration/FileAnalyzer.cpp:275-292`）——决定单任务内同时打几个 LLM 请求。

操作：
- 本地小模型（LM Studio 单卡）：保持 4。调大只会让 N 个请求挤同一 GPU，总吞吐不升、超时（`LLM_TIMEOUT_SECONDS=120`）反增。
- 多任务并行优先：适度调到 6-8（同时分析多个镜像）；此时务必压低 LLM 预算（§2），否则 N 任务 × M LLM 并发直接打爆端点。
- 验证：跑两个任务同时观察 `curl localhost:8666/api/tasks/statistics` 的 running 数；`nvidia-smi`/LM Studio 日志看请求排队。
- 失败排查：LLM 大量超时 → 回调 THREAD_POOL_SIZE；CPU 全满但磁盘空闲 → 编译并发（run.sh -j）与线程池叠加，错峰编译。

## 2. LLM 限额三件套与 SMART 模式成本曲线

背景：LLM 分析是整条管线最贵的一段；三个限额从"分析多少文件、每文件喂多少字、事件簇分析多少个"三个维度控制成本。C++ 侧读取（`ConfigManager.cpp:91-96`）。

- **LLM_MAX_FILES（默认 500）**：smart 与 full 模式都遵守它——full 模式先取全部候选再 `resize(maxFiles)` 截断（`LLMAnalysisService.cpp:138-139`）；smart 模式把它作为选择预算（`TaskManagerAnalysis.cpp:347, 369` 的注释明确"File budget honours LLM_MAX_FILES exactly——此前硬编码 1000 下限导致真实镜像在本地 LLM 上跑数小时"）。当前环境 `.env` 设 80，并注释"本地 27B 模型每文件约 30-60s，80 个文件≈40-80 分钟"——这就是成本曲线的实例：**总耗时 ≈ 预算文件数 × 单文件耗时 ÷ 并发**。
- **LLM_MAX_CONTENT_LENGTH（默认 10000 字符）**：单文件送模型的内容上限，直接决定每请求 token 数。
- **LLM_MAX_EVENT_CLUSTERS（默认 0 = 不限）**：smart 模式下事件簇分析的最终数量上限（`TaskManagerAnalysis.cpp:413-421` → `EventClusterAnalyzer::analyzeSmartEventClusters`，`EventClusterAnalyzer.cpp:152-170`）。0 时"选择"环节退化为让 LLM 从全部簇里挑（`EventClusterAnalyzer.cpp:187-203`：簇数≤预算时跳过选择直接全分析；选择失败/解析失败回退"前 N 个"）。

SMART 成本曲线（smart 模式，`.env` `llm_mode` 非 full 时）：
1. 一次"选文件"调用：把候选文件摘要拼 prompt 让 LLM 挑重要的（`LLMAnalysisService.cpp:240-326`；候选先按启发式排序，LLM 返回不可用时回退启发式）；
2. 预算内逐文件分析（受 THREAD_POOL_SIZE 并发）；
3. 事件簇：再一次"选簇"调用 + 逐簇分析（每簇一次调用）。

操作建议：
- 首次摸底：`LLM_MAX_FILES=50`、`LLM_MAX_EVENT_CLUSTERS=10` 跑通看单文件耗时，再按工期反推预算；
- 只要文件画像不要叙述：把 `LLM_MAX_CONTENT_LENGTH` 降到 4000-6000，收益线性；
- 夜间批跑：恢复 500/0（全量），白天巡检用小预算。
- 验证：任务完成后进度消息/审计里有 "LLM analysis completed: N files analyzed"；`files.db` 中 `llm_analyzed_at` 非空行数即实际分析量。
- 失败排查：分析数量远小于预算 → 候选被 filter_profile 先收窄了（§5）；单文件耗时暴增 → 内容上限被调高或模型被换。

## 3. WAL + synchronous：jbd2 教训与 DB_BUSY_TIMEOUT_MS

背景：源码注释里最重要的性能教训——SQLite 默认 `journal_mode=DELETE + synchronous=FULL` 会在**每次事务提交**时 fsync，真实磁盘上表现为进程 D 状态卡在 `jbd2_log_wait_commit` 数分钟；tmpfs 上测不出（没有日志可等）。出处：`src/core/DatabaseManager/FileClassifier/FileClassifier.cpp:70-78` 注释与 `EventExtractorCore.cpp:61-64`。

现状（多套 Pragma，注意口径不一）：
- 全局配置：`DatabaseManager::initialize()`（`DatabaseManager.cpp:27-39`）按 `.env` 设置 `DB_BUSY_TIMEOUT_MS`（默认 5000）、`DB_JOURNAL_MODE`（默认 WAL）、`DB_SYNCHRONOUS_OFF`（默认 false；true 才会 `PRAGMA synchronous=OFF`——**掉电丢最近写入**，取证环境不建议开）。
- 分析器侧硬编码：`FileClassifier.cpp:76-78`、`WindowsAnalysisDatabase.cpp:33-35`、`EventExtractorCore.cpp:62-64` 等固定 `journal_mode=WAL + synchronous=NORMAL + busy_timeout=5000`——WAL+NORMAL 是兼顾安全与吞吐的推荐组合，不受 `.env` 开关影响。
- 审计库：WAL + synchronous=NORMAL（`AuditLog.cpp:101-112`），默认同步写（`batch_size=1`、`async_write=false`，`AuditLogDataTypes.h:51-54`）——审计要稳，不要为它开 async。

操作：
- 分类器/事件提取阶段分钟级卡顿（`ps` 见 D 状态、`iostat` 见 jbd2 忙）→ 确认输出库在 WAL（`sqlite3 <db> "PRAGMA journal_mode;"` 应返回 wal）；若在机械盘上仍慢，考虑把 `build/data` 挪到 SSD/NVMe。
- `database is locked` 报错 → 适度上调 `DB_BUSY_TIMEOUT_MS`（如 10000），并检查是否有手工 sqlite3 会话长事务挂着。
- 验证：`sqlite3 build/data/tasks/<id>/files.db "PRAGMA journal_mode; PRAGMA synchronous;"` → `wal` / `1`(NORMAL) 或 `2`(FULL)。
- 失败排查：改了 `DB_JOURNAL_MODE` 不生效——部分分析库是硬编码 WAL，`.env` 只影响 DatabaseManager 直管的库。

## 4. GRAPHITI_BATCH_SIZE 与 8K 窗口

背景：Graphiti 摄取把文件分析结果组批喂给 LLM 抽取实体；批量过大触发 **8096 token 上下文溢出**，这是 `.env.example:96` 注释记录的真实教训（"Reduced from 50 to prevent 8096 token overflow"）。

旋钮：
- `GRAPHITI_BATCH_SIZE`：`.env.example` 建议 **25**；注意代码默认值有两处且不同——httpserver Settings 默认 50（`httpserver/config.py:201`），graphiti_integration `from_env` 默认 10（`graphiti_integration/config.py:112`，注释 "Reduced from 50"）。以 `.env` 显式设置为准。
- `GRAPHITI_MAX_EPISODE_TOKENS`（默认 3000，约 7500 字符）：单 episode 安全上限；
- `GRAPHITI_INCLUDE_FULL_DESC=true`：episode 带 3000+ 字符的完整 LLM 描述，抽取质量更好但更吃 token——**溢出时第一个关它**。

操作：出现 token 溢出/截断报错时：`GRAPHITI_INCLUDE_FULL_DESC=false` → `GRAPHITI_BATCH_SIZE` 降到 10-15 → 确认 `LLM_TEXT_MODEL` 的实际上下文窗口（`LLM_CONTEXT_LENGTH` 只影响本地预算计算，不改变服务端能力）。
验证：摄取任务（`/api/graphiti/...` job）完成无 8096/overflow 报错；Neo4j 实体数合理增长。
失败排查：见 ExternalServices.md §4 的模型名一致性——名字不对会报 model not found 而非溢出，别混淆。

## 5. MIUI 限额 env 与大镜像的"过滤画像先行"策略

### 5.1 MIUI 备份解析限额

背景：恶意/畸形 MIUI 备份（超大 manifest、海量包记录）可拖死分析器，代码用常量上限 + env 收紧实现双向限制。这些是**进程环境变量**（`std::getenv` 直读，可放 `.env` 由 run.sh 导出）。

| env | 代码上限（默认） | 作用 | 位置 |
|-----|----------------|------|------|
| `TRACELENS_MIUI_MAX_CANDIDATES` | 100000 | 候选微信库数量上限 | `MiuiArtifactParsers.cpp:38,49,146-155` |
| `TRACELENS_MIUI_MAX_MANIFEST_PACKAGES` | 100000 | manifest 包记录数 | `MiuiBackupManifest.cpp:22-28,30-43` |
| `TRACELENS_MIUI_MAX_MANIFEST_FIELD_BYTES` | 4096 | 单字段字节数 | 同上 |
| `TRACELENS_MIUI_MAX_MANIFEST_METADATA_BYTES` | 16MB | 元数据总字节 | 同上 |

解析 env 的规则：值非法/为 0/超过上限时**回退到代码上限**（不会因配错而放大）。操作：怀疑 MIUI 备份解析耗时异常时，先设 `TRACELENS_MIUI_MAX_CANDIDATES=1000` 复现定位，再逐步放宽。

### 5.2 大镜像：过滤画像先行（最重要的提速手段）

背景：全盘文件清单先落 `raw.db`，随后 **filter_profile** 把它过滤成 `raw.db.filtered`，后续分类/LLM 全部只看过滤库（`TaskManagerAnalysis.cpp:269-288`：`applyFilterByName(rawDbPath, filteredDbPath, task.filter_profile)`，成功则 `effectiveRawDb = filteredDbPath`，失败回退未过滤库继续）。仓库自带四个画像：`config/filter_profiles/{general_forensics,telecom_fraud,virus_intrusion,data_breach}.json`。

操作：创建任务时按案情选画像（默认 `general_forensics`；电信诈骗案选 `telecom_fraud` 只保留相关类型文件）——LLM 预算（§2）作用于**过滤后**的候选集，画像越准，同样预算覆盖的证据越相关。
验证：任务目录出现 `raw.db.filtered` 且明显小于 `raw.db`；任务 JSON 里 `filter_profile` 值正确。
失败排查：画像名写错 → 过滤失败，管线回退全量（日志有告警），表现为 LLM 分析文件数远超预期；此时核对 `FileFilter::listProfiles` 可用的四个名字。

## 6. LLM_TIMEOUT_SECONDS / LLM_MAX_RETRIES / LLM_CONTEXT_LENGTH

背景：这三个值决定"单请求等多久、失败重试几次、本地预算怎么算"。C++ 侧 LLMClient 把 `LLM_TIMEOUT_SECONDS`（默认 120）同时用作连接/读/写三个超时（`src/integration/LLMIntegration/LLMClient.cpp:126-128`），`LLM_MAX_RETRIES`（默认 3）是请求级重试上限（`LLMClient.cpp:172-199`）。

操作：
- 慢模型（27B 级）+ 长内容：单请求可能逼近 120s，出现大量 timeout 报错时优先调大 `LLM_TIMEOUT_SECONDS`（如 300），而不是加并发；
- LLM 端点不稳定：`LLM_MAX_RETRIES=3` 保持，重试是串行的，调大只会拖长失败任务的墙钟时间；
- `LLM_CONTEXT_LENGTH`（`.env.example` 给 163840，Python Settings 默认 4096，`httpserver/config.py:184`）只参与本地"内容截断预算"计算（配合 `LLM_RESERVED_TOKENS`、`LLM_CHARS_PER_TOKEN`），**不会扩大服务端模型的真实窗口**——填超过模型能力没有意义。
- Python 侧同名超时用于 httpx 客户端（`httpserver/config.py:182-183`），两端保持一致避免"C++ 等得住、Python 先放弃"的错位。

验证：`build/logs/cpp_server.log` 中无成串 timeout/retry 报错；任务能跑完 LLM 阶段。
失败排查：偶发超时看 LM Studio 推理队列；稳定超时说明单请求内容超预算，回 §2 调 `LLM_MAX_CONTENT_LENGTH`。

## 7. 全文检索缓存与杂项旋钮

背景：FTS 内容缓存有上限，超限即逐出（`src/core/FullTextSearch/FullTextSearch.cpp:66` 用 `SEARCH_MAX_CACHE_SIZE`，默认 1000 条，`ConfigManager.cpp:151-154`）。同组还有 `SEARCH_MAX_CONTENT_LENGTH=50000`（单文件入索引内容上限）、`SEARCH_SNIPPET_LENGTH=150`、`SEARCH_DEFAULT_LIMIT=10`。

操作：检索反复变慢（重建索引/重读文件）时上调 `SEARCH_MAX_CACHE_SIZE`；大文件搜索命中不全时查 `SEARCH_MAX_CONTENT_LENGTH` 是否截断了目标段。
**如实说明——配置存在但当前无消费方**：`MAX_BATCH_SIZE`（`ConfigManager.cpp:139` 定义、`.env.example:161` 有示例）在源码中没有调用方，调它不会改变任何行为；`LOG_MAX_DISPLAY_FILES=20` 只影响日志展示条数，非性能旋钮。

## 8. 场景化推荐配置（以当前环境实测为参照）

| 场景 | THREAD_POOL_SIZE | LLM_MAX_FILES | LLM_MAX_EVENT_CLUSTERS | filter_profile | 预期 |
|------|-----------------|---------------|------------------------|----------------|------|
| 快速摸底（任意镜像） | 4 | 30-50 | 10 | 按案情选 | 小时级出首批线索 |
| 日常分析（百 GB 级） | 4 | 80（当前 .env 值，27B 模型 30-60s/文件 → 40-80 分钟） | 0 | 按案情选 | 半个工作日 |
| 夜间全量（LLM 充裕） | 4-6 | 500（默认） | 0 | general_forensics | 过夜跑完 |
| 无 LLM 环境 | 4 | —（不勾 llm_analyze） | — | 按案情选 | 纯规则分析，分钟-小时级 |
| MIUI 备份异常排查 | 2 | 50 | 10 | android 相关 | 先用 TRACELENS_MIUI_* 限额定位 |

调整顺序建议：先画像（§5.2，零成本收益最大）→ 再限额（§2）→ 最后并发（§1）。并发是唯一可能"越调越慢"的旋钮（本地模型排队）。

## 9. 观测：用现有端点量化调优效果

背景：调旋钮前先有基线，否则"感觉变快"不可信。仓库自带的观测面足够做前后对比。

```bash
# 任务总量/状态分布（对比吞吐）
watch -n 30 'curl -s http://localhost:8666/api/tasks/statistics'

# 单任务阶段进度（LLM 阶段占比最直观）
curl -s http://localhost:8666/api/tasks/<id>/progress
#   → {current_phase, phase_percentage, overall_percentage, phase_description}

# Python 侧依赖健康（LLM/Neo4j/Redis 降级会拖慢"看起来是性能"的问题）
curl -s http://localhost:8090/health/ready | python3 -m json.tool

# 落盘验证：各库体积（WAL 膨胀会伪装成"写慢"）
ls -lh build/data/tasks/<id>/*.db* build/forensics_audit.db*
```

判读要点：
- 进度长时间停在 LLM_ANALYSIS → §2 限额或 §1 并发问题；
- 进度停在分类/事件提取且进程 D 状态 → §3 的 WAL/jbd2 问题；
- `progress` 消息里有 "Analyzing file N/M" —— M 就是该任务实际进入 LLM 的文件数，直接验证预算是否按预期生效（smart 模式的选择结果）。

## 与代码的对应

| 机制 | 位置 |
|------|------|
| THREAD_POOL_SIZE 读取 | `src/core/ConfigManager/ConfigManager.cpp:138` |
| 任务分析池 + >16 告警 | `src/network/HTTPServer/TaskManager.cpp:21-31` |
| LLM 批量并发共用同值 | `src/integration/LLMIntegration/FileAnalyzer.cpp:275-292` |
| LLM 三限额定义 | `src/core/ConfigManager/ConfigManager.cpp:91-96` |
| full 模式 resize 截断 | `src/network/HTTPServer/LLMAnalysisService.cpp:138-139` |
| smart 选文件 + 预算语义 | `LLMAnalysisService.cpp:180-190, 240-326`；`TaskManagerAnalysis.cpp:347, 369` |
| smart 选簇 + 回退策略 | `src/network/HTTPServer/EventClusterAnalyzer.cpp:152-170, 187-203`；`TaskManagerAnalysis.cpp:413-421` |
| jbd2 教训注释 | `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp:70-78` |
| 全局 DB Pragma | `src/core/DatabaseManager/DatabaseManager.cpp:27-39`；`ConfigManager.cpp:146-148` |
| 分析器硬编码 WAL+NORMAL | `FileClassifier.cpp:76-78`；`EventExtractorCore.cpp:61-64`；`WindowsAnalysisDatabase.cpp:33-35` |
| 审计库 WAL+NORMAL+同步写 | `src/core/AuditLog/AuditLog.cpp:101-112`；`AuditLogDataTypes.h:51-54` |
| GRAPHITI_BATCH_SIZE 双默认（50/10）与建议 25 | `python_service/httpserver/config.py:201`；`graphiti_integration/config.py:112`；`.env.example:96-103` |
| MIUI 限额 env | `src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp:38,49,146-155`；`MiuiBackupManifest.cpp:22-43` |
| 过滤画像先行（raw.db.filtered） | `src/network/HTTPServer/TaskManagerAnalysis.cpp:269-288`；`src/core/FileFilter/FileFilter.h:73-108` |
| LLM 三超时共用一个值 / 重试 | `src/integration/LLMIntegration/LLMClient.cpp:126-128, 172-199` |
| FTS 内容缓存上限 | `src/core/FullTextSearch/FullTextSearch.cpp:66`；`src/core/ConfigManager/ConfigManager.cpp:151-154` |
| MAX_BATCH_SIZE 无消费方 | `src/core/ConfigManager/ConfigManager.cpp:139`（仅定义） |
| 任务进度/统计端点（观测） | `src/network/HTTPServer/routes/TaskMonitoringRoutes.cpp:13-21` |

**最后更新**: 2026-08-24（新建，运维手册）
