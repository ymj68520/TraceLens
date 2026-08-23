# ServiceManager（python_service/httpserver/services/service_manager.py）

> **一句话**：单例生命周期协调者——用一把锁、一个状态机和 30 秒总预算编排所有服务的初始化/关闭，用惰性属性提供统一访问点，并把"C++ 可用性"作为一切上层服务的硬门槛。

## 1. 为什么有这个模块

Python 服务依赖一堆异质资源：C++ HTTP 后端、Neo4j、LLM 推理端点、Redis、若干 SQLite。它们的可用性互相影响（没有 C++ 就不该有报告服务），且启动耗时长短不一（Neo4j 探测可能挂很久）。如果没有一个集中协调者，每个路由各自"用到时再连"，会出现重复连接、竞态初始化和无限期卡死。ServiceManager 把这些问题收敛为三个职责：**有序初始化（带超时与回滚）、单例访问、健康汇总**。

## 2. 在系统中的位置

- **谁调用它**：main.py 的 lifespan 在启动时 `initialize()`（main.py:55）、关闭时 `shutdown()`（main.py:69）；`dependencies.init_dependencies()`（dependencies.py:15）把它交给全部路由（路由里 `from ..services import get_service_manager` 拿到的就是同一实例）；`/health/ready` 经它探测各服务。
- **它调用谁**：CppBackendService、GraphitiService、LLMService、IngestionJobManager、graphiti_integration.MigrationManager，以及 forensic_report / investigation / report_generation 三族服务与三个执行器（均为惰性构造）。

## 3. 核心概念与设计

**（a）单次共享的生命周期转换。** `initialize()`（service_manager.py:71-102）不是简单的顺序调用：它持有 `_lifecycle_lock` 与状态机（`new → initializing → running / shutting_down → stopped`），把真正的初始化包成一个 task；并发调用者 `asyncio.shield` 同一个 task——无论多少路由同时触发首次访问，初始化只跑一次。若调用时正在关闭，则先等关闭完成再干净地重开一轮（:89-100）。

**（b）30 秒总预算 + 回滚。** `_run_initialization()`（:104-118）用 `asyncio.timeout(startup_timeout)`（`PYTHON_STARTUP_TIMEOUT=30s`，:107-108）包住全部初始化；任何 BaseException（含超时）触发 `_rollback_initialization()`（:110-111）——按相反顺序对已初始化的服务调 close/shutdown、清空引用、回到 stopped（:251-283）。回滚收集但不抛出清理异常（:267-274），保证一个资源关闭失败不阻断其余回收。

**（c）依赖门槛：`_cpp_backend_ready`。** C++ 是唯一"普通失败被容忍但决定后续路径"的服务（:124-130）。ForensicReportService、三个执行器（SecondaryAnalysis / EventRefresh / ReportGeneration）都只在 `_cpp_backend_ready` 时才创建（:133、:166、:199）；LLM 允许为 None——执行器显式容忍，真实提交以 `llm_unavailable` 持久失败而非崩溃（:587-588 注释）。

**（d）每个可选服务 12 秒上限。** Graphiti、三个执行器、IngestionJobManager、MigrationManager 各自套 `optional_service_init_timeout`（默认 12s）的 `wait_for`（如 :148-151、:242-245），失败仅 warning，服务标记缺失、整体继续。

**（e）惰性属性 + 就绪校验。** 除启动期创建的服务外，investigation 系列、report_evidence、report_generation_service 等在**首次属性访问**时才构造（:447-571），构造工厂统一断言 C++ ready（如 :434-435）。`_require_service_access()`（:375-381）在 initializing/shutting_down/stopped 状态下抛 RuntimeError，防止关闭中拿到半死服务。个别服务刻意更惰性：investigation_graph_service 的 `base_graph_provider` 是每次 GET 才解析的 lambda，让 Graphiti 宕机降级为 `base_graph_available=false` 而不是端点失败（:493-499）。

## 4. 工作流程走读：启动序列

`_initialize_services()`（:120-249）的顺序即依赖图：

1. **CppBackendService**（:124-130）——httpx 客户端就绪即算成功（不 ping）；
2. **ForensicReportService**（仅当 C++ ready，:133-141）——报告库/快照/适配器；
3. **GraphitiService**（12s 上限，:144-153）——探测 Neo4j，不可用进入 initialized-but-disabled；
4. **LLMService**（:156-162）——只建两个 httpx 客户端，无网络调用，几乎不会失败；
5. **三个执行器**（仅当 C++ ready，各 12s，:166-211）——SecondaryAnalysis、EventRefresh、ReportGeneration（后者含 SQLite DDL，经 `asyncio.to_thread` 移出事件循环，:199-205）；
6. **IngestionJobManager**（:214-223）——尝试 Redis，失败回退内存；
7. **MigrationManager**（:226-249）——通过 sys.path 注入找到 graphiti_integration（:230-232），需 Neo4j。

全部通过后置 `_initialized=True / running`（:114-117）。关闭走 `_drain_shutdown()`（:309-331），按执行器 → 报告 → C++ → Graphiti → LLM → 作业/迁移的顺序清理（:339-350），首个异常延迟到最后抛出。

`health_check()`（:675-729）汇总三服务：C++ 失败把 overall 降为 degraded（:700-701），Graphiti/LLM 失败只记录 unavailable；异常只回类名（:697-699）。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| main.py lifespan | 唯一的 initialize/shutdown 驱动方 |
| dependencies.py | `init_dependencies` 后路由共享同一实例 |
| routes/* | 全部经 `get_service_manager()` 取服务，从不直接 import 服务类构造 |
| graphiti_integration | MigrationManager 是唯一跨包引用（:233） |
| `/health/ready` | 读 health_check 与各服务探测结果 |

## 6. 注意事项与已知问题

- **"初始化失败仍启动"是特性**：超时/异常回滚后 lifespan 只 warning（main.py:59-60），进程继续以降级模式跑；排障看启动日志 warning。
- 不要在路由里缓存服务引用——shutdown 后引用失效；每次经属性访问可拿到就绪校验。
- `_clear_services()`（:352-373）后所有 ready 标志复位；executor 属性在未就绪时抛 RuntimeError（:599-600）而非返回 None，路由应捕获并转 503/501。
- ReportGenerationExecutor 初始化做持久 DDL（建目录/schema/触发器），这就是它独享 `to_thread` 的原因——别在事件循环里加同类初始化。

## 7. 如何验证与扩展

- `python_service/tests/unit/test_startup_reliability.py`（超时/回滚/降级启动）。
- `test_service_manager_report_lifecycle.py`、`test_service_manager_investigation.py`（报告与调查服务的生命周期语义）。
- 新增服务：私有字段 + `_create_*` 工厂（断言 C++ ready 若依赖）+ 惰性属性；需要启动期初始化则在 `_initialize_services` 加一段 try/except + 12s `wait_for`，并同步补进 `_rollback_initialization` 与 `_service_cleanup_plan` 两个清理清单。

**最后更新**: 2026-08-23（解释式重写）
