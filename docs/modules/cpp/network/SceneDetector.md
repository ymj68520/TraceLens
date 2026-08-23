# SceneDetector（src/network/HTTPServer/SceneDetector.{h,cpp}）

> **一句话**：平台场景自动探测器——对**未过滤**的 raw.db 跑一组 `path LIKE` 计数查询（Android/Windows/Linux/Server-Cloud 各自的特征路径标记），返回 `SceneDetection{ok, detected, counts, dominant}`，供任务在用户没选场景时回填 `task.scenarios`。

## 1. 为什么有这个模块

提交任务要求用户勾选"取证场景"（android/windows/linux/server_cloud）——但用户经常不知道镜像是什么系统，选错了整条平台分析就跑偏。本模块把这一步自动化：镜像内容自己说话。头文件的设计陈述很完整：让 UI 可以去掉强制多选；检测只读、不改库、不依赖任何过滤画像（SceneDetector.h:8-25）。

## 2. 在系统中的位置

```
TaskManager::start_analysis（HTTP 流水线）
  IMAGE_ANALYSIS 完成后、FileFilter 之前
  └─ if (task.scenarios.empty())                       ← 只在用户未选择时探测
       SceneDetector::detectScenes(rawDbPath)          (TaskManagerAnalysis.cpp:227-259)
         ├─ 命中 ─▶ 回填 task.scenarios + 写 SCENE_DETECTED 审计日志（含各平台命中数）
         ├─ 未命中 ─▶ 审计日志 "No platform markers found; running generic analysis"
         └─ 失败(ok=false) ─▶ 静默跳过，下游按无场景处理
  之后 FileFilter 按 task.filter_profile 产 filtered.db（SceneDetector 必须在此之前）
```

**唯一调用方**是 TaskManagerAnalysis.cpp:236——CLI 流水线（AnalysisOrchestrator）不跑场景探测（CLI 用户用 `--android-analyze` 等显式声明）。这是一条 HTTP-only 的自动化。

## 3. 核心概念与设计

### 3.1 标记表：SQL LIKE 模式 ↔ 场景

18 条标记（SceneDetector.cpp:35-61），按场景分组：Android 4 条（`%/data/data/com.android.%`、`%/data/system/%` 等）、Windows 5 条（注册表配置目录、Prefetch、计划任务，**另配反斜杠变体**兼容 hive 里存的 `C:\...` 路径）、Linux 4 条（`/var/log/%`、`%/etc/passwd`、`%/etc/shadow`、`%/.bash_history`）、Server-Cloud 5 条（nginx/apache2/httpd/docker/kubernetes）。标记选择的注释标准是"**镜像各平台分析器真正会去处理的工件位置**"（:12-15）——命中即强信号"对应分析器有活干"。

### 3.2 结果结构：计数、排序与 tie-break

`SceneDetection`（SceneDetector.h:27-48）四个字段：

- `counts`：每场景命中文件数（所有枚举键恒存在，初始化为 0，SceneDetector.cpp:88-91）；
- `detected`：count>0 的场景列表，**按计数降序**；同数时按固定优先级 ANDROID > WINDOWS > LINUX > SERVER_CLOUD（PRIORITY_ORDER，:28-33；stable_sort + 索引比较，:114-130）保证结果确定；
- `dominant`：排头场景转成的 `SceneType`——供 FileClassifier / LLMAnalysisService 的"单场景"评分消费（h:43-45 注释）；
- `ok`：库打不开/查不动为 false，调用方按"无场景"处理（h:46-48）。

### 3.3 只读、只数、不判断内容

每个标记一条 `SELECT COUNT(*) FROM files WHERE path LIKE ? AND is_deleted=0`（:65-82），prepare 失败/step 异常一律计 0（"safe default"，:63-64）；READONLY 打开（:94-96）。**没有任何启发式内容解析**（不读文件内容、不看签名）——纯路径形态学，快（18 条索引可用的模糊查询）但也就只认"文件在不在"。

## 4. 工作流程走读

`detectScenes`（SceneDetector.cpp:86-148）三步：

1. counts 清零 + READONLY 开库（:88-98）；
2. 逐标记累加计数（:101-103）；
3. 构造 detected（计数排序 + 优先级 tie-break）、取 dominant、返回（:110-147）。

调用侧的回填逻辑（TaskManagerAnalysis.cpp:232-259）：命中则锁内写 `tasks_[task_id].scenarios = detection.detected`（**注意回填的是完整列表，不只有 dominant**——多平台镜像会同时跑多个场景分析器），审计日志逐平台记录 `android=123, linux=7` 这样的明细（:247-254），保证探测结论可追溯。

**顺序约束**（:227-231 注释 + SceneDetector.h:53-55 文档）：必须传**未过滤**的 raw.db 且必须跑在 FileFilter 之前——过滤画像丢掉的"系统噪声"恰恰是这些标记路径；对 filtered.db 探测会系统性漏检。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| TaskManagerAnalysis | 唯一调用方；探测结果回填 task.scenarios 决定后续平台分析器集合 |
| FileFilter | 顺序约束的对端：检测在前，过滤在后 |
| FileClassifier / LLMAnalysisService | 消费 dominant 场景做场景感知评分（经 task.scenarios 传导） |
| ForensicScenario / SceneType（HTTPServerDataTypes / FileClassifier.h） | 两套场景枚举在此转换（ForensicScenario 四值 ↔ SceneType，:134-144） |

## 6. 注意事项与已知问题

- **路径形态学的天花板**：只认路径不认内容。改名的安卓 data 目录、非标准前缀的 Linux 安装、Windows 盘符大小写/NTFS 交替数据流等都不在覆盖面内；`%/etc/passwd` 这类宽松模式也可能被嵌套目录里的同名文件误命中（计数>0 即算检出）。
- **CLI 路径无探测**：`forensic_analyzer` 单体 CLI 不调用本模块，场景只有显式 flag 一条路；两入口行为有差异。
- **multi-boot/混合镜像**：detected 可多值，下游会跑多组平台分析器（耗时叠加）；dominant 只取计数头名，tie 时按固定优先级而非语义权重。
- **SERVER_CLOUD 与 LINUX 的标记有重叠面**：`/var/lib/docker/%` 在 Linux 服务器镜像常与 `/var/log/%` 同时命中——两个场景都会被点亮，是否符合预期取决于调查定位。
- **性能**：18 条 `LIKE '%…%'` 前导通配查询无法走索引，files 表极大时是全表扫描 ×18；当前在 IMAGE_ANALYSIS 刚结束的关键路径上同步执行（进度条 FILE_CLASSIFICATION 2%）。

## 7. 如何验证与扩展

- **验证**：提交一个不含 scenarios 的任务，查审计日志 `SELECT * FROM audit_logs WHERE action='SCENE_DETECTED'`（任务库/系统审计）看命中明细；再对 filtered.db 手工调 detectScenes 对比计数缩水，直观理解"必须过滤前跑"。
- **扩展新场景/新标记**：在 MARKERS（SceneDetector.cpp:35-61）加 `{场景, LIKE 模式}` 一行即可，计数、排序、审计全部自动跟进；新增**场景枚举**则要动 ForensicScenario、PRIORITY_ORDER、dominant 的 switch（:134-144）以及下游分析器注册——成本主要在枚举联动，不在本模块。

**最后更新**: 2026-08-23（新建，解释式）
