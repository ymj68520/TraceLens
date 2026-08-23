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

### 3.2 过滤即"建副本库"：raw.db 永远完整

`applyFilter`（FileFilter.cpp:317-501）不是 DELETE，而是：打开源库读全表 → 新建目标库（WAL + synchronous=NORMAL + busy_timeout 5000，:340-342）→ `createFilteredSchema` 建与 raw 相同的 files 表 + 5 个索引（:275-311）→ 单事务逐行判定插入（:351、450-476）→ COMMIT → 打印统计 + 写 `FILE_FILTER` 审计日志（:494-498）。`COALESCE(partition_num, 0)`（:372）容忍旧库缺列。

### 3.3 画像发现：多候选目录探测

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

**glob 匹配** `matchGlob`（:122-165）：把 glob 转正则（`*`→`.*`、`?`→`.`、正则元字符转义），`icase` 全匹配；正则构造失败退化为子串包含（:161-164）。**路径匹配比 glob 更宽**：`matchPathPatterns`（:167-197）在 glob 未命中时，把 pattern 去掉 `*` 取"核心串"做子串匹配（:185-194）——`*/com.tencent.mm/*` 因此能命中任意深度的路径，但也意味着**子串误伤是可能的**（核心串出现在无关路径里也算命中）。

**失败语义**：源库打不开/建库失败时返回全零 stats 并打日志（不抛异常）；`applyFilterByName` 在目录找不到或画像不存在时抛 runtime_error（:536-545）——两个调用方（CLI 与 TMA）都 catch 后**降级用未过滤数据继续**（AnalysisOrchestrator.cpp:236-241、TaskManagerAnalysis.cpp:293-296）。过滤全排除（included_files==0）同样降级不换库。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| SceneDetector | 顺序耦合：检测必须在过滤前跑（TMA:227-231 注释——画像丢掉的"系统噪声"正是平台标记路径） |
| TaskManager / AnalysisOrchestrator | 调用方；成功后 effectiveRawDb 切到 filtered.db，失败/全排除回退 raw.db |
| FilterRoutes | HTTP 管理面（列画像/建画像/删画像/手动 apply），消费 listProfiles/loadProfile/applyFilterByName |
| AuditLog | 每次 apply 写 FILE_FILTER 系统审计（画像名 + 三项计数） |
| PathManager | 画像目录定位 |

## 6. 注意事项与已知问题

- **filtered.db 是"截断快照"不是视图**：任务完成后再改画像、再 apply，只会得到新副本；流水线中途的 `output_raw_db` 指向哪份，结果就是哪份。FilterRoutes 的手动 apply **不会**回写 task.output_raw_db（与 TMA:291-297 不同）。
- **子串匹配的误伤面**：§4 所述 core-substring 兜底没有词边界，画像评审时要留意短核心串（如 `*/tmp/*` 的核心串 `/tmp/`）。
- **include_wins 的非对称分支**：include 未命中且 exclude 也未命中时，只要 include 规则**非空**就保留（:428-434）——即 include_wins 模式下"include 规则存在"本身就改变默认行为，与直觉的"没匹配就不保留"相反，写画像时容易踩。
- **性能**：全表单线程逐行 + 每行最多 6 组 regex 构造（matchGlob 每次 `std::regex` 重编译，无缓存）；几十万文件 × 多 pattern 时 regex 编译是主要热点。
- **错误静默**：applyFilter 的失败只走 stderr，返回值与"过滤了 0 个文件"在调用方看起来一样（都是 included_files==0 分支）——审计日志里有记录，但任务进度条上只有一句 Warning。

## 7. 如何验证与扩展

- **验证**：`sqlite3 raw.db "SELECT COUNT(*) FROM files;"` 与 filtered.db 对比；`SELECT * FROM audit_logs WHERE action='FILE_FILTER' ORDER BY id DESC LIMIT 1`（Linux 场景库）看计数；故意 POST 一个不存在画像名给 `/api/filter/apply`，确认 404 后流水线仍可用 raw.db。
- **扩展新画像**：在 `config/filter_profiles/` 放一个 JSON（结构参考 general_forensics.json：`profile_name/description/version/combine_mode/include/exclude`），无需改代码——listProfiles 会自动发现。要加**新匹配维度**（如 mtime 区间）才需要动：FilterCondition 加字段 → loadProfile 解析 → matchesCondition 判定 → FilterRoutes::jsonToCondition/conditionToJson 同步（REST 面才可见）。

**最后更新**: 2026-08-23（新建，解释式）
