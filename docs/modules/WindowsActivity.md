# Windows 活动与事件分析

第四步继续使用既有任务、时间线、调查工作台、图谱和报告入口。原生任务顺序调整为：文件研判 → 平台解析 → Windows 活动导入 → FINALIZING 中的规范事件簇分析 → 图谱摄取 → 原报告完成门控。

## 来源与活动导入

`WindowsActivityImport.h` 使用实际 Windows 表结构导入事件日志、Prefetch、浏览历史、下载、账户条目、服务、计划任务、USB、回收站和 Amcache。ATTACH 使用参数绑定，写入在一个事务中完成；SQL 错误回滚本次导入。缺表、结构不兼容、空表、部分解析、仅元数据和解析失败分别记录。

- Prefetch 展开解析器提供的全部可用时间槽位，保留原始 FILETIME，不按运行次数生成时间。
- EVTX 保留提供程序、事件编号、原始 XML、时间和回收标记。标准可见与回收记录使用不同事件类型；已知级别映射到严重程度，未知级别不填 INFO。
- 账户条目最后使用时间不能证明登录成功；Amcache 文件元数据不能证明程序执行。
- 服务与计划任务的离线配置作为无时间观察保存，不用 next_run_time、处理时间、当前时间或零值生成活动。
- 旧 `windows_artifacts.extracted_at` 是处理时间，已停止将其导入为证据活动时间。
- BLOB 和包含 NUL 的文本参与完整字段投影；不能因字符串截断忽略尾部字节变化。非法 UTF-8/BLOB 使用带类型的十六进制表示。

`windows_activity_sets`、`windows_activity_records` 保存不可变派生版本及来源行，`windows_activity_current` 指向当前版本，`windows_activity_import_runs` 保存导入结果。来源记录身份由任务、结果集、来源表和记录定位共同确定；`record_hash` 是不可变结构化投影的 SHA-256，不是原镜像或原文件的整字节哈希。

`events` 是当前时间线投影。新结果替换旧投影前，将旧投影保存在 `windows_event_history`；源记录和规范分析记录不删除。重建 Windows 或事件数据库之前，通过 SQLite backup 保存到任务目录的 `windows_history`。读取历史 Windows 键可查该任务的归档库，不把历史 ID 指向新记录。

源文件路径能唯一匹配来源索引时绑定 source_id；缺失或歧义时保留明确状态，仍可追溯到派生结果集中的表/行，不声称已定位原镜像文件。未实现工件、MFT 的 100000 上限等保留在覆盖说明。

## 规范事件簇分析

C++ 自动任务调用既有 `/api/llm/event-cluster-analysis/run`，由 Python `ClusterAnalyzer` 写入 `event_cluster_analyses`。旧 `events.llm_*` 只作为兼容缓存；历史缓存通过既有 backfill 标记为 `migrated`，不冒充新的来源证据。

`cluster_revision.py` 将时间、描述、来源、上下文等成员内容纳入指纹。成员 ID 不变但内容改变，也会使旧分析失效。分析开始前和落库事务内再次检查内容；模型调用期间来源改变时拒绝持久化旧结果。`event_cluster_members` 冻结实际成员内容，`cluster_derivations` 保存派生及提示上下文版本。

`cluster_run_jobs` 持久保存运行状态；同任务活跃运行不会重复派发。服务重启、取消或异常不会丢失已完成规范记录。C++ 等待阶段检查暂停/取消并保留可续跑状态。数据库聚合移到线程执行，避免长扫描占住 HTTP 事件循环。

图谱摄取只选择内容仍匹配的当前规范版本，旧版本保留供审计。部分摄取不写完整成功水位。FINALIZING 的簇分析和摄取账本比较目标内容指纹，不再仅凭 `done` 复用。

## 预算和完成状态

`LLM_MAX_EVENT_CLUSTERS` 继续约束事件簇数量。新增：

| 配置 | 含义 |
| --- | --- |
| `EVENT_CLUSTER_MAX_CALLS` | 0 使用默认：任务运行最多为簇数量预算的 10 倍，单簇手动请求默认 10 次；可显式配置 |
| `EVENT_CLUSTER_MAX_TOTAL_TOKENS` | 0 使用调用上限 × 上下文上限；计保守预留值，不等于实际计费 |
| `EVENT_CLUSTER_WAIT_TIMEOUT_MIN` | C++ 等待规范事件分析，默认 120 分钟 |
| `EVENT_LLM_ANALYSIS_ENABLED` | 保留原开关，关闭时不调用事件模型 |

`cluster_model_budget` 和 `cluster_model_ledger` 以内容与配置版本绑定额度，SQLite 原子预留，每次派发计数；同计划重试/续跑不重置。文本在完整消息组装后检查上下文，超额明确失败，不静默截断后宣称全簇已分析。部分失败、超额暂缓及平台部分覆盖记录为 partial，并在任务中文消息中说明。

该额度覆盖事件模型请求，不替代文件阶段、图谱服务或报告阶段各自的预算。

## 证据快照与报告

新增键：`windows_artifact:v1:<task>:<result_set>:<kind>:<record_id>`。工作台、引用跳转和报告冻结读取同一不可变记录。默认报告投影移除账户加密密码字段，保留来源哈希及遮蔽说明。

调查库新增 v9，支持 Windows 快照 CHECK；v8 写入路径先备份到 `.before-v9.sqlite`，再事务迁移，校验行内容、外键和不可变触发器。v7 继续只读，显式升级规则保留。历史命令 `prepare_investigation_v8.py` 为兼容保留名称，当前输出副本为 v9，清单明确标注实际版本，不切换正式数据库。

包含 Windows 来源的新报告采用输入 envelope v7；旧 v1–v6 的输入与快照不改写。报告原有自动入报路径从当前有效 Windows 记录中每类最多取 30 条，最多 300 条；服务与任务配置进入附录。来源版本变化时，仅替换尚未经人工修改、也未绑定分析的自动入报项；人工判断与历史报告保留。该默认范围是有界来源补充，不代表全盘或所有活动都已独立研判。

文件页增加中文“Windows活动覆盖”，显示每类输入、有效活动、无时间观察、部分可读、仅元数据/跳过和失败。完整来源与诊断保留在任务库。此次不实施第五步的全局报告叙事重组。

## 验收边界

使用合成镜像测试原 HTTP 创建、Windows 解析/导入、规范分析、图谱摄取与重启续跑。模型和图谱使用测试替身；另以 PC.E01 的既有提取副本进行真实解析与导入复核，未调用真实模型。

验收输出在 `D:\取证\output\windows-activity-fix-20261025`。不能把这些结果称为真实模型全链路或最终案情报告质量验收。原检材只读，正式服务未切换。
