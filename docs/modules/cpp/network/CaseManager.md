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

## 3. 核心数据结构

### 3.1 ForensicCase：比"任务集合"多一点点的聚合根

结构体定义在 HTTPServerDataTypes.h（与 AnalysisTask 同文件），是本模块唯一的状态载体：

```cpp
// src/network/HTTPServer/HTTPServerDataTypes.h:420-438
struct ForensicCase {
    std::string id;                           ///< UUID
    std::string name;                         ///< Human-readable case title
    std::string description;                  ///< Case description (shared with LLM)
    std::vector<std::string> task_ids;        ///< Ordered list of contained task IDs
    CaseStatus status = CaseStatus::OPEN;
    std::string cross_analysis_job_id;        ///< Python background job ID

    std::chrono::system_clock::time_point created_at;
    std::chrono::system_clock::time_point updated_at;

    // Incremental analysis fields
    std::string case_db_path;                 ///< Path to case-level status database
    int total_files_analyzed = 0;             ///< Total files analyzed across all tasks
    std::map<std::string, TaskAnalysisState> task_analysis_states;  ///< Per-task analysis state

    // Copy / move — trivially default-constructible
    ForensicCase() = default;
};
```

逐字段看：

- `id`：boost UUID 字符串（`create_case` 内生成，CaseManager.cpp:19-20），也是 cases_ map 的键与 REST 路径参数；
- `task_ids`：**纯字符串引用**，没有任何外键约束——这是"悬空引用"问题（§7）的根源；
- `cross_analysis_job_id`：Python 侧跨镜像分析作业号，C++ 不解析其内容，只做透传保管；
- `case_db_path` / `total_files_analyzed` / `task_analysis_states`：三组案件级**增量分析**字段。注释自述场景是"新增任务后只分析新增部分"（HTTPServerDataTypes.h:415-418）；实践中主要由 Python 侧的 associate-tasks 端点消费（multi_analysis.py:180-209 会为每个任务写 'analyzed'/'pending' 状态行），**C++ 侧的 create/update 代码从不写这三个字段**——它们只在 load/save 的序列化里出现。

### 3.2 CaseStatus 与 TaskAnalysisState：两套四态

```cpp
// src/network/HTTPServer/HTTPServerDataTypes.h:392-407
enum class CaseStatus {
    OPEN,           ///< Tasks still running or not yet analysed
    ANALYSING,      ///< Cross-image LLM analysis in progress (Python job)
    COMPLETED,      ///< Cross-image report generated
    FAILED          ///< Cross-image analysis failed
};

enum class TaskAnalysisState {
    PENDING,        ///< Task not yet analyzed
    ANALYZED,       ///< Task has been analyzed (file_descriptions exist)
    NEEDS_UPDATE,   ///< Task data changed, needs re-analysis
    FAILED          ///< Task analysis failed
};
```

注意语义错位：CaseStatus 描述的是**跨镜像 LLM 分析**的进度（不是"案件里所有任务跑完了"）；TaskAnalysisState 描述的是**单个任务在案件级分析中的贡献状态**。两者落盘均为小写字符串（CaseManager.cpp:193-208、:115-118）。

### 3.3 朴素的持久化模型

与 TaskManager 同款思路：内存 `std::map` + 每次变更全量 dump 到 `data/cases.json`（路径来自 PathManager::getDataDir()/"cases.json"，CaseManager.cpp:91-93）。时间戳用毫秒 epoch（:105-108）。加载用 `j.value(key, default)` 全程容错（:154-184），旧文件缺字段也能读。

### 3.4 删除语义：只删记录，不动任务

`delete_case` 仅擦除案件记录（CaseManager.cpp:63-69），不级联删除其引用的任务——任务及其数据归 TaskManager 管。反向同样成立：删除任务不会更新引用它的案件，可能出现悬空 task_id（见 §7）。

## 4. 核心接口清单

CaseManager.h:22-73 定义的全部公开方法（均为 mutex 保护下的同步调用）：

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `std::string create_case(name, description, task_ids={})` | 生成 UUID、状态置 OPEN、立即落盘，返回新 id | CaseCRUDRoutes::handle_create_case（POST /api/cases） | 异常被 save 内部吞掉，仍返回 id |
| `bool add_task(case_id, task_id)` | 向案件追加 task_id（去重）并刷 updated_at | handle_add_tasks（PUT /api/cases/{id}/tasks） | 案件不存在返回 false（路由未检查该返回值） |
| `ForensicCase get_case(case_id)` | 拷贝返回案件；用 `fc.id.empty()` 判未命中 | get/delete/status 三个 handler | 未命中返回空对象，不报错 |
| `std::vector<ForensicCase> get_all_cases()` | 按 map 序（即 UUID 字典序，**非创建时间序**）全量拷贝 | handle_list_cases | 无失败路径 |
| `bool delete_case(case_id)` | 擦除记录并落盘 | handle_delete_case | 不存在返回 false → 路由 404 |
| `void update_status(case_id, CaseStatus)` | 改状态 + updated_at + 落盘 | handle_update_status | 案件不存在**静默 no-op**（:75） |
| `void set_cross_analysis_job(case_id, job_id)` | 记录 Python 作业号 + 落盘 | handle_update_status（双职责端点） | 同上静默 no-op（:83） |
| `save_cases()/load_cases()` | 手动保存 / 构造时装载 | load 仅构造函数；save 无外部调用方 | 解析失败只打日志（:186-188），全部案件丢失 |

一个值得注意的返回值缺口：`add_task`/`update_status`/`set_cross_analysis_job` 的失败（案件不存在）在路由层基本不可见——PUT 到不存在的案件 id 会得到一份 `case_to_json(空对象)` 的 200 响应而非 404（CaseCRUDRoutes.cpp:144-148 先调 set 再 get，get 返回空对象照常序列化）。

## 5. 工作流程走读（含代码）

### 5.1 建案：create_case

```cpp
// src/network/HTTPServer/CaseManager.cpp:14-34
std::string CaseManager::create_case(const std::string& name,
                                     const std::string& description,
                                     const std::vector<std::string>& task_ids) {
    std::lock_guard<std::mutex> lock(mtx_);

    boost::uuids::uuid uuid = boost::uuids::random_generator()();
    std::string id = boost::uuids::to_string(uuid);

    ForensicCase fc;
    fc.id          = id;
    fc.name        = name;
    fc.description = description;
    fc.task_ids    = task_ids;
    fc.status      = CaseStatus::OPEN;
    fc.created_at  = std::chrono::system_clock::now();
    fc.updated_at  = fc.created_at;

    cases_[id] = fc;
    save_cases_internal();
    return id;
}
```

要点：① 锁内完成"生成-插入-落盘"全流程，读侧不会观察到"已建未存"的中间态；② 新案件的增量分析三字段（case_db_path 等）走默认值（空串/0/空 map），证实 §3.1 的判断；③ 落盘在锁内执行——大案件列表时写盘耗时会计入锁持有时间，但 CaseManager 调用频率低，无实际瓶颈。

### 5.2 序列化：save_cases_internal 的增量字段处理

```cpp
// src/network/HTTPServer/CaseManager.cpp:110-136（节选）
// Convert task_analysis_states map to JSON object
json task_states_json;
for (const auto& [task_id, state] : fc.task_analysis_states) {
    std::string state_str;
    switch (state) {
        case TaskAnalysisState::PENDING:    state_str = "pending"; break;
        case TaskAnalysisState::ANALYZED:   state_str = "analyzed"; break;
        case TaskAnalysisState::NEEDS_UPDATE: state_str = "needs_update"; break;
        case TaskAnalysisState::FAILED:     state_str = "failed"; break;
    }
    task_states_json[task_id] = state_str;
}

json j;
j["id"]                    = fc.id;
j["name"]                  = fc.name;
// ...
j["status"]                = status_to_string(fc.status);
j["cross_analysis_job_id"] = fc.cross_analysis_job_id;
j["created_at"]            = epoch_ms(fc.created_at);
// Incremental analysis fields
j["case_db_path"]          = fc.case_db_path;
j["total_files_analyzed"]  = fc.total_files_analyzed;
j["task_analysis_states"]  = task_states_json;
arr.push_back(j);
```

每个案件序列化为一个 JSON 对象，全部装进顶层数组（`json::array()`）。task_analysis_states 是 task_id → 小写状态串的对象嵌套。写盘用 `ofstream` 直接覆写 + `arr.dump(2)`（:138-141）——没有临时文件 + rename 的原子化，这就是 §7 "保存非原子"的实现根源。

### 5.3 加载：悬空 task_id 为什么不会炸

```cpp
// src/network/HTTPServer/CaseManager.cpp:154-160、168-177（节选）
ForensicCase fc;
fc.id                    = j.value("id", "");
fc.task_ids              = j.value("task_ids", std::vector<std::string>{});
fc.status                = status_from_string(j.value("status", "open"));
// Load task_analysis_states map
if (j.contains("task_analysis_states") && j["task_analysis_states"].is_object()) {
    for (auto& [task_id, state_str] : j["task_analysis_states"].items()) {
        TaskAnalysisState state = TaskAnalysisState::PENDING;
        std::string s = state_str.get<std::string>();
        if (s == "analyzed")       state = TaskAnalysisState::ANALYZED;
        else if (s == "needs_update") state = TaskAnalysisState::NEEDS_UPDATE;
        else if (s == "failed")     state = TaskAnalysisState::FAILED;
        fc.task_analysis_states[task_id] = state;
    }
}
// ...
if (!fc.id.empty()) cases_[fc.id] = fc;
```

加载全程 `value(key, default)` 容错：旧版本 cases.json 缺 cross_analysis_job_id、缺全部增量字段都能读回，缺什么补什么默认值。task_analysis_states 里的未知状态串一律归 PENDING。最后一行 `if (!fc.id.empty())` 是唯一的记录级过滤——**空 id 行被丢弃，但 task_ids 里指向已删除任务的字符串照样加载**，悬空引用从文件原样进入内存，CaseManager 不做任何与 TaskManager 的对账（对账逻辑不存在于 C++ 侧）。

### 5.4 发起跨镜像分析（链路总览）

前端调用 Python 服务的案件分析接口拿到 job_id，再经 Python 的状态回写端点 `PUT /api/cases/{id}/status`（body 含 cross_analysis_job_id，multi_analysis.py:271 构造该 body）→ `set_cross_analysis_job`（CaseManager.cpp:81-87）。C++ 在这条链路里只是"名片 holder"，分析本体在 Python。状态流转 ANALYSING→COMPLETED 的实际推动者是 Python 分析完成后的前端回调，同样走 `update_status`（:73-79）。

**重启恢复**：构造函数 `load_cases`（:8-10、147-189）把 JSON 读回内存；案件没有"运行态"，无需 TaskPersistence 那样的 RUNNING→FAILED 改写。

## 6. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| CaseCRUDRoutes | 唯一 REST 调用方（/api/cases 全套 CRUD，构造时注入 `CaseManager::instance()`，CaseCRUDRoutes.cpp:11） |
| Python multi_analysis 路由 | 经 C++ REST 间接读写；另直接读写增量字段语义（associate-tasks 预热 task_analysis_states） |
| TaskManager | 无直接调用；案件只是 task_id 的逻辑分组，查询任务详情时前端另行调任务接口 |
| PathManager | cases.json 路径（getDataDir()） |
| HTTPServerDataTypes.h | ForensicCase/CaseStatus/TaskAnalysisState 的定义处，结构变更要同步 save/load |

## 7. 注意事项与已知问题

- **悬空引用**：删除任务不会从案件中摘除 task_id；前端渲染案件详情时要容忍 task 查不到（404）。load_cases 也不清洗（§5.3）。
- **保存非原子**：与 tasks.json 同款问题——ofstream 直接覆写（CaseManager.cpp:138-141），写入中途崩溃会损坏 cases.json；解析失败时全部案件丢失（catch 只打日志，:186-188）。
- **状态字符串易混**：案件状态是小写（"analysing"），任务状态 REST 也是小写，但 tasks.json 里是大写——三处并存，脚本处理时逐个确认。
- **无并发分析保护**：同 id 的 cross_analysis_job 被重复提交时后写覆盖前写，CaseManager 不做去重。
- **update 类方法静默 no-op**：对不存在案件调 update_status/set_cross_analysis_job 不报错（§4），调用方以为写成功了。

## 8. 如何验证与扩展

- **验证**：`POST /api/cases` 建案 → `PUT /api/cases/{id}/tasks` 挂两个已完成任务 → `cat data/cases.json` 检查 task_analysis_states 序列化 → 重启服务确认案件仍在。
- **扩展**：给案件加字段时同步改 save_cases_internal（CaseManager.cpp:100-145）与 load_cases（:147-189），load 用 value() 容错；若要实现"案件完成度 = 已分析任务占比"之类派生指标，建议加只读方法由路由层计算，不要把派生值落盘。

## 9. 端点契约全表（二轮补全）

CaseCRUDRoutes 注册的 6 个端点（CaseCRUDRoutes.cpp:13-39）逐个列出请求/响应字段。**关键背景**：前端 web/src 里没有任何对 `/api/cases`（C++ 侧）的直接调用——前端案件 CRUD 全部走 Python 的 `/api/llm/cases*`（caseGroupService）；C++ 这组端点的**实际调用方是 Python 服务**（multi_analysis.py:109/127/137/150/172/270 经 `cpp_backend_url` 回环调用），Python 再把它包装成自己的案件 API。这条"前端→Python→C++"的双层结构是案件域最重要的调用链事实。

| 端点 | 方法 | 请求字段（缺省） | 成功响应 | 失败响应 | 源码 |
|---|---|---|---|---|---|
| `/api/cases` | GET | 无 | 200 `{cases:[case...], total:N}`（恒 200，空列表也是） | 无失败路径 | :44-54 |
| `/api/cases` | POST | `name`（默认 "Unnamed Case"）、`description`（""）、`task_ids[]`（[]，非数组忽略） | 201 case JSON | 400 `{"error":...}`（JSON 解析失败） | :56-77 |
| `/api/cases/{id}` | GET | 路径参数 | 200 case JSON | 404 `{"error":"Case not found","case_id":...}` | :79-92 |
| `/api/cases/{id}/tasks` | PUT | `task_ids[]`（必填数组） | 200 case JSON（追加后的完整案件） | 400（缺 task_ids 或 JSON 坏） | :94-114 |
| `/api/cases/{id}` | DELETE | 无 | 200 `{"success":true,"message":"Case deleted"}` | 404 | :116-129 |
| `/api/cases/{id}/status` | PUT | `status`（可选，"open"/"analysing"/"completed"/"failed"）、`cross_analysis_job_id`（可选） | 200 case JSON（**案件不存在时也是 200 空对象**，§4 已记） | 400（JSON 坏） | :131-154 |

`case_to_json`（CaseCRUDRoutes.cpp:158-173）输出的 8 个字段：`id`、`name`、`description`、`task_ids[]`、`status`（小写串）、`cross_analysis_job_id`、`created_at`、`updated_at`（毫秒 epoch）。

**契约缺口（新发现）**：`case_to_json` **不输出增量分析三字段**（case_db_path / total_files_analyzed / task_analysis_states）——它们只在 cases.json 落盘格式里存在（CaseManager.cpp:133-135），REST 层完全不可见。因此 Python 侧 multi_analysis.py:180-209 要预热 task_analysis_states 时，只能自己写（经 `_pipelines.py:546` 的 POST /api/cases 重建或直连路径），读不到 C++ 已存的状态——增量字段事实上是"只写不读的黑洞"。

## 10. 新走读分支：三个边界路径

### 10.1 PUT status 的"未知状态串重置为 open"缺陷

```cpp
// CaseCRUDRoutes.cpp:136-143
if (body.contains("status")) {
    std::string s = body["status"];
    CaseStatus cs = CaseStatus::OPEN;
    if (s == "analysing") cs = CaseStatus::ANALYSING;
    else if (s == "completed") cs = CaseStatus::COMPLETED;
    else if (s == "failed") cs = CaseStatus::FAILED;
    case_manager_.update_status(case_id, cs);
}
```

状态串没有白名单拒绝分支：传 `"COMPLETED"`（大写）、`"done"`、拼写错误等任何未识别值，`cs` 保持初始的 OPEN 并**照常落盘**——一个 COMPLETED 案件会被静默重置回 open。与 CaseManager::status_from_string（CaseManager.cpp:203-208）的"未知归 OPEN"行为一致（加载侧同款语义），两个方向都把坏输入当 open。调用方（multi_analysis.py:270/294/303 只发小写合法值）目前没踩坑，但任何新调用方传大写都会触发。

### 10.2 PUT tasks 的逐条加锁与部分失败语义

```cpp
// CaseCRUDRoutes.cpp:104-108
for (const auto& tid : body["task_ids"]) {
    case_manager_.add_task(case_id, tid.get<std::string>());
}
res.write(case_to_json(case_manager_.get_case(case_id)).dump());
```

N 个 task_id = N 次"拿锁-查重-可能落盘"。两个后果：① 每个新增 task_id 触发一次全量 cases.json 重写（add_task 内部 save，CaseManager.cpp:44）——挂 10 个任务写 10 次盘，O(N×全量)；② 数组中途某元素类型不对（如传了数字）抛 type_error，**前面已加入的保留、后面的丢弃**，catch 返回 400 但部分写入已生效——不是原子操作。

### 10.3 案件不存在时 PUT tasks 的"空成功"

`add_task` 对不存在案件返回 false 且不写（CaseManager.cpp:38），但 handle_add_tasks **不检查返回值**，循环走完后照样 `get_case(空) → case_to_json(空对象)` 返回 200。响应体是 `{"id":"","name":"",...,"task_ids":[]}` 的全默认对象——前端如果只看 200 不看 id 是否为空，会把它当合法案件渲染。与 §4 记录的 PUT status 空成功同源（get_case 的空对象哨兵没有被 handler 消费）。

## 11. 并发与持久化细节补充

- **锁粒度**：单一 `mtx_` 保护 `cases_`（CaseManager.h），所有公开方法独立加锁——不存在跨方法事务。update_status 与 set_cross_analysis_job 分两次调用时（PUT status 的双职责），两个写之间有窗口，另一线程的读会看到"新状态+旧 job id"的中间态。当前调用方（Python 串行回调）无并发，风险休眠。
- **锁内 I/O**：save_cases_internal 在 mtx_ 内 open/dump/write（CaseManager.cpp:138-141），与 TaskManager 同款权衡；案件数量通常个位数到十位数，dump(2) 的全量序列化在 KB 级，可接受。
- **无删除防护**：delete_case 与并发 add_task 之间无版本号/CAS——极端时序下 add 可能复活已删案件（erase 后 add 的 count 检查失败返回 false，不会复活；但"add 拿锁前 erase、add 后写盘"的顺序在单锁下实际安全，此风险不存在）。真正无防护的是**悬空引用**（§7 已记）。
- **cases.json 无备份**：写坏即全损（load 的 catch 只打日志，:186-188）；`create_directories`（:139）保证 data/ 存在，但不建临时文件。对比 tasks.json 有相同问题，两个文件都建议加 tmp+rename 原子化。

## 12. 配置影响表（CaseManager 视角）

| 配置 | 默认 | 作用 |
|---|---|---|
| `DATA_DIR` | `data` | cases.json 位于 `<DATA_DIR>/cases.json`（CaseManager.cpp:91-93，经 PathManager::getDataDir()） |
| `CPP_BACKEND_URL` | `http://localhost:8080` | **Python 侧**回环调用本模块端点的基址（multi_analysis.py 各处）——Python 配置漂移时案件读写整体失效 |
| `PYTHON_HTTP_PORT` / `PYTHON_SERVICE_URL` | 8090 | 反方向：前端→Python 的案件 API 与本模块无关，但排障时要区分两套 `/cases` |
| 无专有 env | — | CaseManager 不读任何环境变量；案件状态机阈值、清理策略均不存在（没有 cleanup_completed_tasks 的对应物） |

## 13. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调（REST） | multi_analysis.py | 8 处回环调用（:109/127/137/150/172/270/294/303/380） | 建案/列表/详情/删除/挂任务/状态与 job 回写 |
| 被调（REST） | case_aggregation_manager.py | 3 处（:162/226/287） | 聚合管理器挂任务/删案件 |
| 被调（REST） | _pipelines.py:546 | POST /api/cases | 分析管线建案 |
| 不被前端直调 | web/src/services | 无 `/api/cases` 引用 | 前端案件 UI 全在 Python `/api/llm/cases*` 上 |
| 持久化 | data/cases.json | save/load（:100-189） | 顶层数组，毫秒 epoch |
| 引用（无校验） | TaskManager 的 task_id | 仅字符串 | 悬空引用风险（§7） |
| 同构 | TaskManager | 镜像设计（单例+map+全量 JSON） | 对照参考 |

## 14. cases.json 磁盘契约全表（逐键）

save_cases_internal（CaseManager.cpp:100-145）写出的顶层数组元素键集：

| 键 | 类型 | from_json 行为 | 说明 |
|---|---|---|---|
| id | string | value 默认 "" | 空则整条丢弃（:184） |
| name | string | value 默认 "" | |
| description | string | value 默认 "" | |
| task_ids | array of string | value 默认 [] | 悬空引用不清洗（§5.3） |
| status | 小写串 | 未知值归 OPEN（:203-208） | open/analysing/completed/failed |
| cross_analysis_job_id | string | value 默认 "" | Python 作业号 |
| created_at / updated_at | **毫秒** epoch int64 | value 默认 0 | 注意与 tasks.json 的**秒**级不同 |
| case_db_path | string | value 默认 "" | 增量字段：C++ 不写（§9 缺口） |
| total_files_analyzed | int | value 默认 0 | 同上 |
| task_analysis_states | object: task_id→小写串 | 未知串归 pending（:170-174） | 同上 |

dump(2) 缩进、ofstream 直接覆写（无原子化）——与 tasks.json（dump(4)、秒级时间戳）在缩进与时间单位上都不一致，脚本同时处理两份文件时逐项确认。

## 15. Python 侧 9 个调用点的请求体形态（multi_analysis.py 实测口径）

从 multi_analysis.py 各调用点提取的 C++ 端点收到的真实 body（Python 是唯一线上客户端，这些就是事实契约）：

| Python 位置 | C++ 端点 | body | 时机 |
|---|---|---|---|
| :109 | POST /api/cases | CreateCaseRequest.model_dump()：`{name, description, task_ids}` | 用户建案 |
| :127 | GET /api/cases | — | 列案 |
| :137 | GET /api/cases/{id} | — | 详情 |
| :150 | DELETE /api/cases/{id} | — | 删案 |
| :172 | PUT /api/cases/{id}/tasks | `{task_ids: [...]}` | 挂任务/associate 预热 |
| :270 | PUT /api/cases/{id}/status | `{status:"analysing", cross_analysis_job_id}` | 跨镜像分析启动 |
| :294 | PUT /api/cases/{id}/status | `{status:"completed", ...}` | 分析成功回写 |
| :303 | PUT /api/cases/{id}/status | `{status:"failed", ...}` | 失败回写 |
| :380 | PUT /api/cases/{id}/tasks | 同 :172 | 二次挂任务 |

每次调用独立 `httpx.AsyncClient(timeout=10)`——C++ 锁内落盘超 10s 时 Python 报超时但 C++ 已写成功（§11 的语义分叉点）。

## 16. 验证 runbook

```bash
# 1. 直接建案（绕过 Python 验证 C++ 层）
curl -s -X POST :8080/api/cases -d '{"name":"案-001","task_ids":["<已完成任务id>"]}' | jq .
# 2. 查落盘
cat data/cases.json | jq '.[0]'
# 3. 状态回写（注意小写）
curl -s -X PUT :8080/api/cases/<id>/status -d '{"status":"analysing","cross_analysis_job_id":"job-42"}' | jq .
# 4. 拼错状态名观察"重置为 open"缺陷（§10.1）
curl -s -X PUT :8080/api/cases/<id>/status -d '{"status":"COMPLETED"}' | jq .status   # "open"
# 5. 重启验证持久化
# 6. 悬空引用：删除任务后 GET 案件，task_ids 仍含该 id
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
