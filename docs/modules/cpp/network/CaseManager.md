# CaseManager（src/network/HTTPServer/CaseManager.{h,cpp}）

> **一句话**：案件（ForensicCase）的单例管家——把多个分析任务组织进同一个取证案件，持久化到 data/cases.json，并替 Python 跨镜像分析保管 job id。

## 1. 为什么有这个模块

一个真实案件（如电信诈骗）往往涉及多台设备、多个镜像。逐个任务看结果既碎片又难关联。CaseManager 提供"案件"这一层聚合：建案件 → 把相关任务的 ID 挂进来 → 案件级别跟踪状态与跨镜像分析进度。头文件的自我描述很准确："Design intentionally mirrors TaskManager so integration is familiar"（CaseManager.h:6-7）——它就是一个小号、去掉线程池的 TaskManager。

## 2. 在系统中的位置

```
CaseCRUDRoutes (/api/cases*)  ──REST 门面──▶  CaseManager (单例)
                                               │  读写
                                               ▼
                                        data/cases.json
前端 /cases、/investigation（案件智能）页 ─┘
Python 服务：跨镜像分析（C++ 只存 job id）
TaskManager：案件引用的 task_id 由它实际执行
```

- CaseManager **不执行任何分析**：task_ids 只是字符串引用，任务的执行/状态完全属于 TaskManager。
- 跨镜像关联分析委托给 Python 服务，C++ 侧只通过 `cross_analysis_job_id` 记住异步作业号（CaseManager.cpp:81-87），前端拿着它去轮询 Python 侧状态。

## 3. 核心概念与设计

### 3.1 ForensicCase：比"任务集合"多一点点的聚合根

除 id/name/description/task_ids 外，还带三组案件级增量分析字段（CaseManager.cpp:123-136 持久化）：

- `status`：CaseStatus 四态 `OPEN / ANALYSING / COMPLETED / FAILED`，落盘为小写字符串（CaseManager.cpp:193-208）；
- `cross_analysis_job_id`：Python 跨镜像分析作业号；
- `case_db_path` + `total_files_analyzed` + `task_analysis_states`（每任务的 pending/analyzed/needs_update/failed 四态，CaseManager.cpp:112-121）——支撑"增量分析：新任务加入后只分析新增部分"的场景。

### 3.2 朴素的持久化模型

与 TaskManager 同款思路：内存 `std::map` + 每次变更全量 dump 到 `data/cases.json`（路径来自 PathManager::getDataDir()/"cases.json"，CaseManager.cpp:91-93）。时间戳用毫秒 epoch（:105-108）。加载用 `j.value(key, default)` 全程容错（:154-184），旧文件缺字段也能读。

### 3.3 删除语义：只删记录，不动任务

`delete_case` 仅擦除案件记录（CaseManager.cpp:63-69），不级联删除其引用的任务——任务及其数据归 TaskManager 管。反向同样成立：删除任务不会更新引用它的案件，可能出现悬空 task_id（见 §6）。

## 4. 工作流程走读

**建案并挂任务**：前端 POST /api/cases（name/description/task_ids）→ `create_case`（CaseManager.cpp:14-34）：生成 UUID、状态置 OPEN、立即落盘 → 返回案件 JSON。后续可 PUT /api/cases/{id}/tasks 追加 task_ids，`add_task` 去重后更新 updated_at（:36-47）。

**发起跨镜像分析**：前端调用 Python 服务的案件分析接口拿到 job_id，再 PUT /api/cases/{id}（body 含 cross_analysis_job_id）回写 → `set_cross_analysis_job`（:81-87）。C++ 在这条链路里只是"名片 holder"，分析本体在 Python。

**状态流转**：PUT /api/cases/{id}/status → `update_status`（:73-79）。ANALYSING→COMPLETED 的实际推动者是 Python 分析完成后的前端回调。

**重启恢复**：构造函数 `load_cases`（:8-10、147-189）把 JSON 读回内存；案件没有"运行态"，无需 TaskPersistence 那样的 RUNNING→FAILED 改写。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| CaseCRUDRoutes | 唯一 REST 调用方（/api/cases 全套 CRUD） |
| TaskManager | 无直接调用；案件只是 task_id 的逻辑分组，查询任务详情时前端另行调任务接口 |
| Python 服务 | 跨镜像/案件级 LLM 分析的实际执行者；C++ 保存其 job id |
| PathManager | cases.json 路径 |

## 6. 注意事项与已知问题

- **悬空引用**：删除任务不会从案件中摘除 task_id；前端渲染案件详情时要容忍 task 查不到（404）。
- **保存非原子**：与 tasks.json 同款问题——ofstream 直接覆写（CaseManager.cpp:138-141），写入中途崩溃会损坏 cases.json；解析失败时全部案件丢失（catch 只打日志，:186-188）。
- **状态字符串易混**：案件状态是小写（"analysing"），任务状态 REST 也是小写，但 tasks.json 里是大写——三处并存，脚本处理时逐个确认。
- **无并发分析保护**：同 id 的 cross_analysis_job 被重复提交时后写覆盖前写，CaseManager 不做去重。

## 7. 如何验证与扩展

- **验证**：`POST /api/cases` 建案 → `PUT /api/cases/{id}/tasks` 挂两个已完成任务 → `cat data/cases.json` 检查 task_analysis_states 序列化 → 重启服务确认案件仍在。
- **扩展**：给案件加字段时同步改 save_cases_internal（CaseManager.cpp:100-145）与 load_cases（:147-189），load 用 value() 容错；若要实现"案件完成度 = 已分析任务占比"之类派生指标，建议加只读方法由路由层计算，不要把派生值落盘。

**最后更新**: 2026-08-23（解释式重写）
