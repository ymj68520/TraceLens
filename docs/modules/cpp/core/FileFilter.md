# FileFilter（src/core/FileFilter/FileFilter.{h,cpp}）

> **一句话**：场景化文件过滤器——按 `config/filter_profiles/` 下的 JSON 画像（include/exclude 的扩展名/路径 glob/文件名 glob/大小区间/删除与分配状态），把 `<镜像>_raw.db` 的 files 表复制裁剪成 `<镜像>_filtered.db` 副本，原图不动、下游全部改用副本。

## 1. 为什么有这个模块

一块完整磁盘镜像动辄几十万文件，其中绝大多是系统噪声（DLL、字体、缓存）。对"电信诈骗"场景，调查员关心的是聊天记录、图片、通讯录；对"病毒入侵"场景关心的是可执行文件与启动项。逐个分析器自己挑文件既重复又不可配置。FileFilter 把"哪些文件值得继续分析"抽成一个**可插拔的 JSON 画像层**，插在 raw.db（全量事实）与 FileClassifier/各平台分析器（分析视野）之间——一次过滤，全流水线受益，且 raw.db 永远保留全量证据（过滤是生成副本，不是删除）。

## 2. 在系统中的位置

```
IMAGE_ANALYSIS ──▶ raw.db（全量）
                     │
                     ├─(仅 HTTP 流水线) SceneDetector::detectScenes(rawDb)   ← 必须在过滤前：画像会丢系统路径特征
                     │   （TaskManagerAnalysis.cpp:227-259）
                     ▼
                FileFilter::applyFilterByName(raw.db, <base>_filtered.db, profile)
                     │  raw.db 只读，产出副本
                     ▼
              effectiveRawDb = filtered.db ──▶ FileClassifier / EventExtractor / 平台分析器 …
```

三个调用方（`grep FileFilter` 全部命中）：

- **CLI**：AnalysisOrchestrator.cpp:222-241（Step 2，未指定时默认 `general_forensics`）；
- **HTTP 任务流水线**：TaskManagerAnalysis.cpp:261-298（`task.filter_profile` 非空才跑；成功后把 `task.output_raw_db` 改指向 filtered.db，:291-297）；
- **HTTP 手动触发**：FilterRoutes 的 `POST /api/filter/apply`（见 routes/FilterRoutes.md）。

## 3. 核心概念与设计

### 3.1 画像模型：两个条件 + 一个合成模式

`FilterProfile`（FileFilter.h:37-44）= include 条件 + exclude 条件 + `FilterCombineMode`。`FilterCondition`（h:15-23）的维度：`extensions`（大小写不敏感）、`path_patterns`/`filename_patterns`（`*`/`?` glob）、`min_size`/`max_size`（0 = 不限）、`include_deleted`/`include_allocated`。

合成模式（h:28-32）是语义核心：

- **ExcludeWins**（默认，保守）：exclude 命中 → 出局；否则看 include；
- **IncludeWins**：include 命中 → 保留；
- **IncludeOnly**：只看 include。

`matchesCondition`（FileFilter.cpp:241-269）内部：删除/分配过滤是**硬门槛**（先判），大小是区间；三个内容维度之间是 **OR**；**一个内容维度都不填的条件匹配一切**——这就是"exclude 只配大小上限、include 留空"这类画像能工作的原因。

### 3.2 核心数据结构（FileFilter.h:15-53）

```cpp
struct FilterCondition {
    std::vector<std::string> extensions;       // e.g., {".pdf", ".doc"}
    std::vector<std::string> path_patterns;    // glob patterns, e.g., {"*/com.tencent.mm/*"}
    std::vector<std::string> filename_patterns; // glob patterns, e.g., {"*.log", "contacts*"}
    int64_t min_size = 0;                      // 0 = no limit
    int64_t max_size = 0;                      // 0 = no limit
    bool include_deleted = true;
    bool include_allocated = true;
};

enum class FilterCombineMode {
    ExcludeWins,  // If exclude matches, file is excluded (default, conservative)
    IncludeWins,  // If include matches, file is included (even if exclude matches)
    IncludeOnly   // Only include rules apply; no exclude
};

struct FilterProfile {
    std::string name;
    std::string description;
    std::string version;
    FilterCondition include;
    FilterCondition exclude;
    FilterCombineMode combine_mode = FilterCombineMode::ExcludeWins;
};

struct FilterStats {
    int64_t total_files = 0;
    int64_t included_files = 0;
    int64_t excluded_files = 0;
};
```

逐组解释：`FilterCondition` 的字段分两类——**硬门槛**（include_deleted/include_allocated，默认 true 即不过滤；置 false 才起筛除作用）与**内容维度**（extensions/path_patterns/filename_patterns 三者 OR）。"0 = no limit" 的 size 语义意味着**无法表达"只要 0 字节文件"**（min_size=0 被当作没设）；extension 比较在 `matchExtensions` 里两侧都转小写（`:220-235`），带不带点前缀需与画像一致（示例注释用 `.pdf` 带点形态）。`FilterCombineMode` 三态中 ExcludeWins 是默认值——结构体声明处即默认保守。`FilterProfile` 的 name/description/version 是展示元数据（FilterRoutes 列表用），不参与判定。`FilterStats` 的三个计数器恒满足 total = included + excluded，是调用方判断"过滤是否有效"的依据（included==0 触发降级回 raw.db）。

### 3.3 核心接口清单

| 签名（FileFilter.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `static FilterProfile loadProfile(profilePath)` | 解析画像 JSON | applyFilterByName、FilterRoutes | 坏 JSON 抛 runtime_error |
| `static vector<tuple<string,string,string>> listProfiles(profilesDir)` | 列目录内画像（文件名/名称/描述） | FilterRoutes 列表接口 | 单个坏画像跳过并打警告（:107-111） |
| `FilterStats applyFilter(sourceDbPath, filteredDbPath, profile)` | 全量判定 + 副本写入 | applyFilterByName、FilterRoutes 手动 apply | 打不开库/建表失败返回全零 stats，不抛 |
| `FilterStats applyFilterByName(sourceDbPath, filteredDbPath, profileName)` | 按画像名定位并应用 | AnalysisOrchestrator.cpp:222-241、TaskManagerAnalysis.cpp:261-298 | 目录/画像不存在抛 runtime_error |
| （私有）`bool matchesCondition(name, path, size, is_deleted, is_allocated, condition)` | 单记录对单条件的判定核 | 主循环三种模式共用 | 恒有返回值 |
| （私有）`bool matchGlob(pattern, text)` | `*`/`?` glob → regex 全匹配（icase） | 三个内容维度 | regex_error 退化为子串包含 |

### 3.4 过滤即"建副本库"：raw.db 永远完整

`applyFilter`（FileFilter.cpp:317-501）不是 DELETE，而是：打开源库读全表 → 新建目标库（WAL + synchronous=NORMAL + busy_timeout 5000，:340-342）→ `createFilteredSchema` 建与 raw 相同的 files 表 + 5 个索引（:275-311）→ 单事务逐行判定插入（:351、450-476）→ COMMIT → 打印统计 + 写 `FILE_FILTER` 审计日志（:494-498）。`COALESCE(partition_num, 0)`（:372）容忍旧库缺列。

### 3.5 画像发现：多候选目录探测

`findProfilesDirectory`（:507-530）依次试 PathManager 的 projectRoot/exeDir/../ 下的 `config/filter_profiles`，再退到 CWD 相对路径。仓库自带 4 个内置画像：`general_forensics / telecom_fraud / data_breach / virus_intrusion`（FilterRoutes 对这四个名字有写保护，见 routes 文档）。

## 4. 工作流程走读

**加载画像** `loadProfile`（:29-88）：逐字段 `value(key, default)` 容错解析，`combine_mode` 字符串映射三态（:48-55），坏 JSON 抛 runtime_error（调用方决定降级）。

**逐行判定**是主循环里唯一需要精读的分支（:413-448）：

```cpp
case FilterCombineMode::ExcludeWins:
default:
    if (matchesCondition(..., profile.exclude)) {
        included = false;
    } else {
        included = matchesCondition(..., profile.include);
    }
```

（FileFilter.cpp:437-447。注意 include 条件为空时 `matchesCondition` 返回 true——"只黑名单"画像由此实现。）

### 4.1 代码走读：matchGlob 的 glob→regex 翻译（FileFilter.cpp:122-165）

```cpp
bool FileFilter::matchGlob(const std::string& pattern, const std::string& text) {
    // Convert glob pattern to regex
    // Supports: * (any chars), ? (single char)
    std::string regexStr;
    regexStr.reserve(pattern.size() * 2);

    for (size_t i = 0; i < pattern.size(); ++i) {
        char c = pattern[i];
        switch (c) {
            case '*':
                regexStr += ".*";
                break;
            case '?':
                regexStr += '.';
                break;
            case '.':
            // ... 其余正则元字符 ()+^$|[]{}\ 统一加反斜杠（:138-151）
            default:
                regexStr += c;
                break;
        }
    }

    try {
        std::regex re(regexStr, std::regex::icase);
        return std::regex_match(text, re);
    } catch (const std::regex_error&) {
        // Fallback: simple contains check
        return text.find(pattern) != std::string::npos;
    }
}
```

逐块解释：翻译循环把 `*`/`?` 映射为 `.*`/`.`，**其余所有正则元字符逐一转义**——画像作者写 `file(1).log` 时括号按字面量匹配而非分组，这是把 glob 与 regex 两个语义空间隔开的正确做法。`regex_match` 是**全串匹配**（不是 search），所以 `*.log` 只匹配以 .log 结尾的名字、`contacts*` 匹配 contacts 开头的名字，语义与用户直觉一致；`icase` 让 Windows 大小写不敏感的文件名行为可控。catch 分支是防御：转义后仍可能构造出非法 regex（极端嵌套量词等），退化成"原始 pattern 子串包含"至少不会崩——但语义已不同（`*` 会按字面找），属于"保命不保对"。性能注记：每次调用现场构造 `std::regex`（构造是解析+编译，昂贵），几十万文件 × 每 pattern 一次是本模块最大热点（见第 6 节）。

### 4.2 代码走读：matchesCondition 的三段判定（FileFilter.cpp:241-269）

```cpp
bool FileFilter::matchesCondition(const std::string& name, const std::string& path,
                                  int64_t size, int is_deleted, int is_allocated,
                                  const FilterCondition& condition) {
    // Check allocation/deletion filters
    if (!condition.include_deleted && is_deleted) return false;
    if (!condition.include_allocated && !is_allocated) return false;

    // Check size range
    if (condition.min_size > 0 && size < condition.min_size) return false;
    if (condition.max_size > 0 && size > condition.max_size) return false;

    // If no content filters specified, matches by default
    bool hasContentFilter = !condition.extensions.empty() ||
                           !condition.path_patterns.empty() ||
                           !condition.filename_patterns.empty();

    if (!hasContentFilter) return true;

    // Check extensions
    if (matchExtensions(condition.extensions, name)) return true;

    // Check path patterns
    if (matchPathPatterns(condition.path_patterns, path)) return true;

    // Check filename patterns
    if (matchFilenamePatterns(condition.filename_patterns, name)) return true;

    return false;
}
```

逐块解释：判定序是"便宜的先做"——硬门槛两次比较、区间两次比较都先于任何字符串匹配；三个内容维度命中即返回（OR 语义 + 短路）。**最关键的是 hasContentFilter 分支**：一个条件若三个内容维度全空，则"只约束删除/分配/大小"——这赋予画像两种工作形态：include 全空 = "不设白名单，只靠 exclude 排除"（ExcludeWins 下的纯黑名单）；exclude 只配 max_size = "排除大文件"。代价是**空条件恒真**这一隐含语义，IncludeWins 模式的非对称分支正是它的连锁反应（见第 6 节）。注意本函数对三个内容维度全部 miss 时返回 false——"条件存在但没匹配"，与"条件不存在恒真"是两回事，读懂这对 distinction 是读懂整个过滤器的钥匙。

### 4.3 代码走读：applyFilter 主循环的双语句流水（FileFilter.cpp:388-482）

```cpp
    while (sqlite3_step(selectStmt) == SQLITE_ROW) {
        stats.total_files++;
        // ... 16 列读入局部变量，NULL 文本列归一为 ""（:393-411）
        bool included = false;

        switch (profile.combine_mode) {
            // ... IncludeOnly/IncludeWins 分支见 :417-435
            case FilterCombineMode::ExcludeWins:
            default:
                if (matchesCondition(name, path, size, is_deleted, is_allocated,
                                      profile.exclude)) {
                    included = false;
                } else {
                    included = matchesCondition(name, path, size, is_deleted, is_allocated,
                                                profile.include);
                }
                break;
        }

        if (included) {
            stats.included_files++;
            // ... 16 个参数绑定到常驻 insertStmt（:454-469）
            sqlite3_step(insertStmt);
            sqlite3_reset(insertStmt);
        } else {
            stats.excluded_files++;
        }
    }

    sqlite3_finalize(selectStmt);
    sqlite3_finalize(insertStmt);

    // Commit transaction
    sqlite3_exec(filteredDb, "COMMIT;", nullptr, nullptr, nullptr);
```

逐块解释：与 DatabaseManager 的逐条自动提交不同，这里 INSERT 语句**只 prepare 一次、循环里 reset 复用**（`:472`），配合外层单事务（`:351` BEGIN）——几十万行的复制成本被压到"每行一次绑定+step"，是模块内 SQL 工程的正面范例。SELECT 与 INSERT 分属两个连接（sourceDb/filteredDb），读游标与写目标互不阻塞，天然流式。combine_mode 的 switch 落在循环体内意味着每个文件都要走一遍完整分支——代价可忽略，换来的是画像热切换的可能（虽然当前画像在循环前固定）。step 后立即 reset 清空绑定，下一行直接重用；COMMIT 之后的统计打印与审计写入（`:488-498`）是调用方判断"过滤是否值得换库"的唯一信号源。

**失败语义**：源库打不开/建库失败时返回全零 stats 并打日志（不抛异常）；`applyFilterByName` 在目录找不到或画像不存在时抛 runtime_error（:536-545）——两个调用方（CLI 与 TMA）都 catch 后**降级用未过滤数据继续**（AnalysisOrchestrator.cpp:236-241、TaskManagerAnalysis.cpp:293-296）。过滤全排除（included_files==0）同样降级不换库。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| SceneDetector | 顺序耦合：检测必须在过滤前跑（TMA:227-231 注释——画像丢掉的"系统噪声"正是平台标记路径） |
| TaskManager / AnalysisOrchestrator | 调用方；成功后 effectiveRawDb 切到 filtered.db，失败/全排除回退 raw.db |
| FilterRoutes | HTTP 管理面（列画像/建画像/删画像/手动 apply），消费 listProfiles/loadProfile/applyFilterByName |
| AuditLog | 每次 apply 写 FILE_FILTER 系统审计（画像名 + 三项计数） |
| PathManager | 画像目录定位（findProfilesDirectory 消费 projectRoot/exeDir） |
| raw.db/files 表 | 只读输入（16 列全量 SELECT）；filtered.db 同 schema 复制（含 5 索引，**不含** llm_* 列——那是 FileClassifier 的 files.db 才有） |

## 6. 注意事项与已知问题

- **filtered.db 是"截断快照"不是视图**：任务完成后再改画像、再 apply，只会得到新副本；流水线中途的 `output_raw_db` 指向哪份，结果就是哪份。FilterRoutes 的手动 apply **不会**回写 task.output_raw_db（与 TMA:291-297 不同）。
- **子串匹配的误伤面**：§4.1 所述 matchPathPatterns 的 core-substring 兜底（`:185-194`）没有词边界，画像评审时要留意短核心串（如 `*/tmp/*` 的核心串 `/tmp/`）。
- **include_wins 的非对称分支**：include 未命中且 exclude 也未命中时，只要 include 规则**非空**就保留（:428-434）——即 include_wins 模式下"include 规则存在"本身就改变默认行为，与直觉的"没匹配就不保留"相反，写画像时容易踩。
- **性能**：全表单线程逐行 + 每行最多 6 组 regex 构造（matchGlob 每次 `std::regex` 重编译，无缓存）；几十万文件 × 多 pattern 时 regex 编译是主要热点。
- **错误静默**：applyFilter 的失败只走 stderr，返回值与"过滤了 0 个文件"在调用方看起来一样（都是 included_files==0 分支）——审计日志里有记录，但任务进度条上只有一句 Warning。
- size 硬门槛与内容维度不同：它们在 include/exclude 两个条件里都是**筛除性**的（min/max 只能把文件判出条件外），不能反过来"因为大而保留"。
- INSERT 的 step 返回值未检查（`:471`），单行写失败静默漏行——filtered.db 行数可能略少于 included_files 计数，对账以 SELECT COUNT 为准。

## 7. 如何验证与扩展

- **验证**：`sqlite3 raw.db "SELECT COUNT(*) FROM files;"` 与 filtered.db 对比；`SELECT * FROM audit_logs WHERE action='FILE_FILTER' ORDER BY id DESC LIMIT 1`（Linux 场景库）看计数；故意 POST 一个不存在画像名给 `/api/filter/apply`，确认 404 后流水线仍可用 raw.db。
- **相关测试**：FileFilter **没有专属单元测试**（tests/UnitTest/ 无 test_file_filter，tests/CMakeLists.txt 亦未注册）；当前覆盖靠 CLI/HTTP 流水线的端到端验证与 FilterRoutes 的手动接口。
- **扩展新画像**：在 `config/filter_profiles/` 放一个 JSON（结构参考 general_forensics.json：`profile_name/description/version/combine_mode/include/exclude`），无需改代码——listProfiles 会自动发现。要加**新匹配维度**（如 mtime 区间）才需要动：FilterCondition 加字段 → loadProfile 解析 → matchesCondition 判定 → FilterRoutes::jsonToCondition/conditionToJson 同步（REST 面才可见）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
