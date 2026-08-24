# ServiceManager（python_service/httpserver/services/service_manager.py）

> **一句话**：单例生命周期协调者——用一把锁、一个状态机和 30 秒总预算编排所有服务的初始化/关闭，用惰性属性提供统一访问点，并把"C++ 可用性"作为一切上层服务的硬门槛。

## 1. 为什么有这个模块

Python 服务依赖一堆异质资源：C++ HTTP 后端、Neo4j、LLM 推理端点、Redis、若干 SQLite。它们的可用性互相影响（没有 C++ 就不该有报告服务），且启动耗时长短不一（Neo4j 探测可能挂很久）。如果没有一个集中协调者，每个路由各自"用到时再连"，会出现重复连接、竞态初始化和无限期卡死。ServiceManager 把这些问题收敛为三个职责：**有序初始化（带超时与回滚）、单例访问、健康汇总**。

## 2. 在系统中的位置

- **谁调用它**：main.py 的 lifespan 在启动时 `initialize()`（main.py:55）、关闭时 `shutdown()`（main.py:69）；`dependencies.init_dependencies()`（dependencies.py:15）把它交给全部路由（路由里 `from ..services import get_service_manager` 拿到的就是同一实例）；`/health/ready` 经它探测各服务。
- **它调用谁**：CppBackendService、GraphitiService、LLMService、IngestionJobManager、graphiti_integration.MigrationManager，以及 forensic_report / investigation / report_generation 三族服务与三个执行器（均为惰性构造）。

## 3. 核心概念与设计

**（0）状态即数据结构。** 类的全部生命周期状态就是 `__init__` 里这组字段——没有别的隐藏通道：

```python
# service_manager.py:60-69
self._initialized = False
self._cpp_backend_ready = False
self._forensic_report_ready = False
self._report_generation_ready = False
self._secondary_analysis_ready = False
self._event_refresh_ready = False
self._lifecycle_state = "new"
self._lifecycle_lock = asyncio.Lock()
self._initialization_task: Optional[asyncio.Task[None]] = None
self._shutdown_task: Optional[asyncio.Task[None]] = None
```

谁写谁读：五个 `*_ready` 布尔只在 `_initialize_services`/`_clear_services`/`_drain_shutdown` 写，被各惰性属性读（executor 族在未就绪时抛 RuntimeError，:599-600、:619-620、:638-642）；`_lifecycle_state` 取值 `new → initializing → running → shutting_down → stopped`，由 `_require_service_access()`（:375-381）在**每次属性访问**时校验；两个 task 句柄是并发去重的锚点——`_active_task()`（:333-337）把 done 的 task 视同 None。

```python
# service_manager.py:375-381
def _require_service_access(self) -> None:
    if self._lifecycle_state == "initializing":
        raise RuntimeError("ServiceManager is initializing")
    if self._lifecycle_state == "shutting_down":
        raise RuntimeError("ServiceManager is shutting down")
    if self._lifecycle_state == "stopped":
        raise RuntimeError("ServiceManager is not initialized")
```

注意 `running` 不在校验列表里：正常运行态是默认放行；而 `new`（从未初始化）也放行——惰性属性允许在 lifespan 初始化失败后按需重建服务（见 (e)）。

**（a）单次共享的生命周期转换。** `initialize()`（:71-102）不是简单的顺序调用：它持有 `_lifecycle_lock` 与状态机，把真正的初始化包成一个 task；并发调用者 `asyncio.shield` 同一个 task——无论多少路由同时触发首次访问，初始化只跑一次。若调用时正在关闭，则先等关闭完成再干净地重开一轮（:89-100）：

```python
# service_manager.py:74-102（节选）
async with self._lifecycle_lock:
    if self._initialized and self._lifecycle_state == "running":
        return
    shutdown_task = self._active_task(self._shutdown_task)
    if shutdown_task is None:
        initialization_task = self._active_task(self._initialization_task)
        if initialization_task is None:
            self._lifecycle_state = "initializing"
            initialization_task = asyncio.create_task(
                self._run_initialization()
            )
            self._initialization_task = initialization_task
    else:
        initialization_task = None

if shutdown_task is not None:
    try:
        await asyncio.shield(shutdown_task)
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except BaseException:
        # Cleanup errors belong to shutdown callers; once the drain has
        # restored stopped state, initialization may start a clean cycle.
        pass
    continue
await asyncio.shield(initialization_task)
return
```

三处 shield 各有含义：等 shutdown 用 shield 是为了**不被取消者连带取消**（CancelledError 只在调用者自身也在取消时 re-raise）；吞掉 shutdown 的 BaseException 是因为清理错误归属关闭方，stopped 态之后初始化可以干净重启；最后 shield initialization task 让所有等待者共享同一次初始化的结果或异常。

**（b）30 秒总预算 + 回滚。** `_run_initialization()`（:104-118）用 `asyncio.timeout(startup_timeout)`（`PYTHON_STARTUP_TIMEOUT=30s`，:107-108）包住全部初始化；任何 BaseException（含超时）触发 `_rollback_initialization()`（:110-111）——按相反顺序对已初始化的服务调 close/shutdown、清空引用、回到 stopped（:251-283）。回滚收集但不抛出清理异常（:267-274），保证一个资源关闭失败不阻断其余回收：

```python
# service_manager.py:104-118
async def _run_initialization(self) -> None:
    logger.info("Initializing services...")
    try:
        startup_timeout = getattr(self.settings, "startup_timeout", 30.0)
        async with asyncio.timeout(startup_timeout):
            await self._initialize_services()
    except BaseException:
        await self._rollback_initialization()
        raise
    else:
        async with self._lifecycle_lock:
            self._initialized = True
            if self._lifecycle_state == "initializing":
                self._lifecycle_state = "running"
        logger.info("All services initialized successfully")
```

回滚计划是显式逆序元组（:253-263）：`(migration_manager,"close")` 最先、`(cpp_backend,"shutdown")` 最后——与初始化顺序严格相反；捕获 `BaseException` 而非 `Exception`，因为超时（TimeoutError 在 3.11+ 是 BaseException 族之外但 CancelledError 在内）也必须走完整回收。`asyncio.timeout` 超时时会向 `_initialize_services` 注入 CancelledError，逐层展开后被这里接住。

**（c）依赖门槛：`_cpp_backend_ready`。** C++ 是唯一"普通失败被容忍但决定后续路径"的服务（:124-130）。ForensicReportService、三个执行器（SecondaryAnalysis / EventRefresh / ReportGeneration）都只在 `_cpp_backend_ready` 时才创建（:133、:166、:199）；LLM 允许为 None——执行器显式容忍，真实提交以 `llm_unavailable` 持久失败而非崩溃（:587-588 注释）。

```python
# service_manager.py:124-141（节选）
try:
    from .cpp_backend import CppBackendService
    self._cpp_backend = CppBackendService(self.settings)
    await self._cpp_backend.initialize()
    self._cpp_backend_ready = True
except Exception as error:
    logger.warning(f"C++ backend service initialization failed: {error}")

# Report recovery must never bind to a backend that failed initialization.
if self._cpp_backend_ready:
    try:
        self._forensic_report_service = self._create_forensic_report_service()
        await self._forensic_report_service.initialize()
        self._forensic_report_ready = True
    except Exception as error:
        logger.warning(f"ForensicReportService initialization failed: {error}")
```

注意第一段捕获的是 `Exception` 而非 BaseException——docstring（:121-122）写明"cancellation and other BaseExceptions abort the whole transition"：Ctrl-C 或 30s 超时不能被吞成"降级"，必须整体回滚。

**（d）每个可选服务 12 秒上限。** Graphiti、三个执行器、IngestionJobManager、MigrationManager 各自套 `optional_service_init_timeout`（默认 12s，`OPTIONAL_SERVICE_INIT_TIMEOUT`）的 `wait_for`（如 :148-151、:242-245），失败仅 warning，服务标记缺失、整体继续。ReportGenerationExecutor 的工厂做持久 DDL（建目录/schema/触发器），所以先 `asyncio.to_thread(self._create_report_generation_executor)`（:199-201）移出事件循环再 `wait_for(executor.initialize(), 12s)`。

**（e）惰性属性 + 就绪校验。** 除启动期创建的服务外，investigation 系列、report_evidence、report_generation_service 等在**首次属性访问**时才构造（:447-571），构造工厂统一断言 C++ ready（如 :434-435）。个别服务刻意更惰性：investigation_graph_service 的 `base_graph_provider` 是每次 GET 才解析的 lambda，让 Graphiti 宕机降级为 `base_graph_available=false` 而不是端点失败（:493-499）：

```python
# service_manager.py:493-499
manager = self
return InvestigationGraphService(
    cpp_backend=self._cpp_backend,
    # Resolved lazily per GET so a Graphiti/Neo4j outage degrades to
    # base_graph_available=false instead of failing the endpoint.
    base_graph_provider=lambda: manager.graphiti_service,
)
```

## 4. 工作流程走读：启动序列

`_initialize_services()`（:120-249）的顺序即依赖图：

1. **CppBackendService**（:124-130）——httpx 客户端就绪即算成功（不 ping）；
2. **ForensicReportService**（仅当 C++ ready，:133-141）——报告库/快照/适配器；
3. **GraphitiService**（12s 上限，:144-153）——探测 Neo4j，不可用进入 initialized-but-disabled；
4. **LLMService**（:156-162）——只建两个 httpx 客户端，无网络调用，几乎不会失败；
5. **三个执行器**（仅当 C++ ready，各 12s，:166-211）——SecondaryAnalysis、EventRefresh、ReportGeneration；
6. **IngestionJobManager**（:214-223）——尝试 Redis（`redis.asyncio.from_url`，connect 5s/read 30s 超时），失败回退内存；
7. **MigrationManager**（:226-249）——通过 sys.path 注入找到 graphiti_integration（:230-232），需 Neo4j。

全部通过后置 `_initialized=True / running`（:114-117）。关闭走 `_drain_shutdown()`（:309-331），按执行器 → 报告 → C++ → Graphiti → LLM → 作业/迁移的顺序清理（`_service_cleanup_plan()`，:339-350），首个异常延迟到最后抛出（:318-331）——每个 finally 里还会即时把 forensic_report 引用清空（:321-324），防止后续段访问已关闭对象。

`health_check()`（:675-729）汇总三服务：C++ 失败把 overall 降为 degraded（:700-701），Graphiti/LLM 失败只记录 unavailable；异常只回类名（:697-699，注释写明"this dict reaches the /health/ready response and transport errors embed internal URLs"）。

## 5. 关键接口清单（谁调、失败行为）

| 成员 | 签名 | 语义 / 失败行为 |
|---|---|---|
| `initialize` | `async () -> None`（:71） | lifespan 启动调用；并发安全；超时/异常抛给调用者（main.py 只 warning） |
| `shutdown` | `async () -> None`（:285） | 幂等（stopped 直接 return）；先等在途初始化再 drain；首个清理异常最后抛 |
| `cpp_backend` | property（:383） | 未初始化时惰性重建 CppBackendService——它是唯一"允许事后自愈"的服务 |
| `graphiti_service` / `llm_service` | property（:645/:654） | 同上，惰性重建；服务内部自带 disabled 判定 |
| `ingestion_job_manager` / `migration_manager` | property → Optional（:663/:669） | **不重建**：启动失败即保持 None，路由层转 501（Graphiti 路由的降级语义） |
| `forensic_report_service` | property（:417） | 非 `new` 态且未就绪 → RuntimeError("...unavailable")，路由转 503 |
| `secondary_analysis_executor` / `event_refresh_executor` / `report_generation_executor` | property（:634/:616/:595） | `None or not ready` → RuntimeError，路由转 503 |
| `investigation_*` / `report_evidence_service` / `report_generation_service` | property（:447-571） | 工厂断言 `_cpp_backend_ready`，否则 RuntimeError("C++ backend is not initialized") |
| `health_check` | `async () -> dict`（:675） | 返回 `{overall, services{cpp_backend,graphiti,llm}}`，异常只回 `type(e).__name__` |

模块级单例：`get_service_manager()`（:736-746）进程内首次构造后固定；`services/__init__.py` re-export 它供路由使用。

## 6. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| main.py lifespan | 唯一的 initialize/shutdown 驱动方 |
| dependencies.py | `init_dependencies` 后路由共享同一实例 |
| routes/* | 全部经 `get_service_manager()` 取服务，从不直接 import 服务类构造 |
| graphiti_integration | MigrationManager 是唯一跨包引用（:233） |
| `/health/ready` | 读 health_check 与各服务探测结果 |

## 7. 注意事项与已知问题

- **"初始化失败仍启动"是特性**：超时/异常回滚后 lifespan 只 warning（main.py:59-60），进程继续以降级模式跑；排障看启动日志 warning。
- 不要在路由里缓存服务引用——shutdown 后引用失效；每次经属性访问可拿到就绪校验。
- `_clear_services()`（:352-373）后所有 ready 标志复位；executor 属性在未就绪时抛 RuntimeError（:599-600）而非返回 None，路由应捕获并转 503/501。
- ReportGenerationExecutor 初始化做持久 DDL（建目录/schema/触发器），这就是它独享 `to_thread` 的原因——别在事件循环里加同类初始化。
- IngestionJobManager 的 sys.path 注入（ingestion_job_parts/_manager.py:95-107）带着一段历史注释：曾因父目录层数少算一层、解析到 httpserver/ 而使 `graphiti_integration` 静默导入失败（启动脚本未预设 PYTHONPATH 时尤甚）；现在固定 `Path(__file__).resolve().parents[3]` 并保留注释自检——改目录结构时留意这条隐式耦合。

## 8. 如何验证与扩展

- `python_service/tests/unit/test_startup_reliability.py`（超时/回滚/降级启动）。
- `test_service_manager_report_lifecycle.py`、`test_service_manager_investigation.py`（报告与调查服务的生命周期语义）。
- 新增服务：私有字段 + `_create_*` 工厂（断言 C++ ready 若依赖）+ 惰性属性；需要启动期初始化则在 `_initialize_services` 加一段 try/except + 12s `wait_for`，并同步补进 `_rollback_initialization` 与 `_service_cleanup_plan` 两个清理清单。

## 9. 二轮深化 A：生命周期状态机完整转移表

`_lifecycle_state` 共 5 个取值，全部转移如下（源码核对；`SM` = 本类实例）：

| # | 当前态 | 触发 | 转移到 | 守卫/副作用 | 源码 |
|---|---|---|---|---|---|
| 1 | （构造） | `ServiceManager(settings)` | new | 16 个服务字段全 None、5 个 ready 全 False | :36-69 |
| 2 | new | `initialize()` 且无在途 shutdown | initializing | 创建 `_initialization_task` | :81-85 |
| 3 | initializing | `_initialize_services` 全部完成 | running | `_initialized=True` | :113-118 |
| 4 | initializing | 任一 BaseException（含 30s 超时/Ctrl-C） | stopped | `_rollback_initialization()` 先执行（逆序回收全部已建服务、`_clear_services()`） | :110-112、:275-278 |
| 5 | initializing | C++/Graphiti/LLM 等**普通 Exception** | （不转移） | 仅 warning，服务标记缺失，最终仍走 #3 → running | :129-130 等 |
| 6 | running | `shutdown()` | shutting_down | 创建 `_shutdown_task`；stopped 态直接 return（幂等） | :287-296 |
| 7 | shutting_down | drain 完成 | stopped | `_clear_services()`；首个清理异常最后 re-raise | :325-331 |
| 8 | shutting_down | 并发 `initialize()` 到达 | （等待） | shield 等 shutdown_task 完成、吞其异常，`continue` 回到循环头 → 干净走 #2 重开 | :89-100 |
| 9 | running | 任意属性访问 | （不变） | `_require_service_access` 放行 | :375-381 |
| 10 | initializing / shutting_down / stopped | 任意属性访问 | — | RuntimeError → 路由转 503（或 501） | :375-381 |
| 11 | new | 任意属性访问 | （不变，放行） | 惰性属性允许 lifespan 失败后按需重建 | :45（既有叙述） |

关键不变量：**new 与 stopped 对属性访问的语义不同**——new 放行（允许自愈），stopped 拒绝（关闭后必须重启进程语义上才算干净）；`_active_task()`（:333-337）把 done 的 task 当 None，所以 #4/#7 完成后残留的 task 引用不会阻塞下一轮。

## 10. 二轮深化 B：属性访问矩阵（16 个属性 × 创建时机 × 门控 × 消费路由）

| 属性 | 行 | 创建时机 | 门控/未就绪行为 | 主要消费路由 |
|---|---|---|---|---|
| cpp_backend | :383 | 启动期 + 惰性重建（唯一允许自愈） | 仅状态校验；None 即重建 | health、associations、oss_analysis、wechat(模型)、intelligence_report、graphiti/_ingest |
| graphiti_service | :645 | 启动期(12s) + 惰性重建 | 服务内部 disabled 判定 | graphiti 全部 5 个子模块、case/_helpers、health |
| llm_service | :654 | 启动期 + 惰性重建 | 同上 | llm/_analysis、_management、case/_helpers、dll、oss_analysis、health |
| ingestion_job_manager | :663 | 仅启动期(12s) | **不重建**，None 时路由转 501 | graphiti/_ingest、_jobs、health |
| migration_manager | :669 | 仅启动期(12s) | 同上 | graphiti/_migrate |
| forensic_report_service | :417 | 启动期(仅 C++ ready) 或 state==new 时惰性 | 非 new 且未就绪 → RuntimeError | forensic_reports |
| investigation_service | :447 | 惰性（工厂断言 C++ ready） | RuntimeError("C++ backend is not initialized") | investigation |
| investigation_review_service | :462 | 惰性 | 同上 | investigation、investigation_workbench |
| investigation_event_service | :480 | 惰性（同时被 _create_event_refresh_executor 触发，:608-609） | 同上 | investigation、investigation_workbench |
| investigation_graph_service | :501 | 惰性（base_graph_provider 每次 GET 解析） | 同上；Graphiti 宕机降级 base_graph_available=false | investigation、investigation_workbench |
| investigation_read_service | :518 | 惰性 | 同上 | investigation_workbench、investigation |
| report_evidence_service | :535 | 惰性 | 同上 | investigation_workbench、report_evidence |
| report_generation_service | :563 | 惰性（R2b 准入服务） | 同上 | report_generation |
| report_generation_executor | :595 | 仅启动期(to_thread + 12s) | None 或未 ready → RuntimeError（**不可惰性重建**） | report_generation |
| event_refresh_executor | :616 | 仅启动期(12s) | 同上 | investigation、investigation_workbench |
| secondary_analysis_executor | :634 | 仅启动期(12s) | 同上 | investigation、investigation_workbench |

方法面（非属性）：`initialize()`(:71)、`shutdown()`(:285)、`health_check()`(:675) 三个公开协程 + 模块级 `get_service_manager()`(:736-746)。规律总结：**报告/调查读侧服务可惰性创建（失败=503 可自愈），三个执行器与两个管理器是"启动期一次性"（失败=503/501，重启才能恢复）**——因为执行器在 initialize() 里做过重启恢复（scan pending jobs），惰性重建会绕过恢复语义。

## 11. 二轮深化 C：初始化 / 回滚 / 关闭三序对照表

| 服务 | 初始化序（:120-249） | 回滚序（:253-263） | 关闭序（:339-350） |
|---|---|---|---|
| CppBackendService | 1 | 9（最后） | 5 |
| ForensicReportService | 2（仅 C++ ready） | 8 | 4 |
| GraphitiService | 3 | 7 | 6 |
| LLMService | 4 | 6 | 7 |
| SecondaryAnalysisExecutor | 5（仅 C++ ready） | 5 | 3 |
| EventRefreshExecutor | 6（仅 C++ ready） | 4 | 1 |
| ReportGenerationExecutor | 7（仅 C++ ready，to_thread） | 3 | 2 |
| IngestionJobManager | 8 | 2 | 8 |
| MigrationManager | 9 | 1（最先） | 9（最后） |

两个结构性差异值得指出：

1. **回滚序 = 初始化序的严格逆序**（9→1），这是"按依赖反向拆除"的标准形态；**关闭序不是逆序**——它把三执行器放最前、forensic_report 与 C++ 提前（4/5 位）、基础设施（Graphiti/LLM/Redis/Neo4j 迁移）垫后。关闭的排序原则是"先停业务写入方，再关承载层"，与回滚的"刚建到哪拆到哪"不同。
2. `_drain_shutdown` 的 finally 里**只**对 forensic_report 做即时引用清空（:321-324），其余 8 个服务要等循环结束后 `_clear_services()` 统一清——因为后续清理步骤（adapters 等）可能还要访问其他服务，唯独 forensic_report 的 shutdown 之后不允许任何人再碰。

## 12. 二轮深化 D：新走读——initialize/shutdown 并发交错分支

第 3 节(a)只解释了 shield 的语义，没有展开交错路径。补两个真实分支：

**分支一：关闭进行中来了初始化请求**（`initialize()` 的 while 循环体，:89-100）：

```python
# service_manager.py:89-100（节选）
if shutdown_task is not None:
    try:
        await asyncio.shield(shutdown_task)
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except BaseException:
        # Cleanup errors belong to shutdown callers; once the drain has
        # restored stopped state, initialization may start a clean cycle.
        pass
    continue
```

逐块：等待关闭期间若本协程被 cancel，`current.cancelling()` 为真才把取消向上传播（Python 3.11 的 Task.cancelling() 计数）——否则把这次取消视作"等待被打断"，继续走流程；关闭自身的异常（含 #7 的 re-raise）被吞掉，因为那些错误归属关闭调用方；`continue` 回到循环头，此时状态已是 stopped、两个 task 都 done → 走 #2 开始全新一轮初始化。**语义：进程里"关闭后立即重启"是被显式支持的路径**，不是未定义行为。

**分支二：初始化进行中来了关闭请求**（`_coordinate_shutdown`，:299-307）：

```python
# service_manager.py:299-307
async def _coordinate_shutdown(self) -> None:
    async with self._lifecycle_lock:
        initialization_task = self._active_task(self._initialization_task)
    if initialization_task is not None:
        try:
            await asyncio.shield(initialization_task)
        except BaseException:
            pass
    await self._drain_shutdown()
```

关闭不取消在途初始化，而是等它自然结束（成功或回滚），再 drain。初始化抛出的任何异常（包括回滚后 re-raise 的原始异常）在这里被吞——因为此时唯一重要的事是让状态机落回 stopped。注意 `shutdown()`(:287-297) 与 `initialize()` 不同，**没有循环**：它只处理一轮，调用方拿到的是 drain 完成后的结果。

## 13. 二轮深化 E：health_check 的三个隐式细节（新走读）

`health_check()`（:675-729）看似纯读，实际有三处副作用/语义边界：

1. **它可能触发惰性构造**：`self.cpp_backend` / `self.graphiti_service` / `self.llm_service` 是属性访问（:689、:705、:718）——若启动期失败留下了 None，健康检查会当场重建实例（cpp_backend 分支**不会** await 其 initialize()，直接调 health_check()；Graphiti/LLM 同样）。也就是说 `/health/ready` 在降级进程上有"顺手把服务对象建回来"的副作用。
2. **三档不同的失败降级**：C++ 异常把 `overall` 打成 degraded 且状态记 `"error"`（:697-701）；Graphiti/LLM 异常状态记 `"unavailable"` 且**不动 overall**（:711-714、:724-727）——与第 4 节"C++ 是硬门槛"的设计一致；返回 False（非异常）时两者都记 `"unhealthy"`。
3. **错误只回 `type(e).__name__`**：注释（:695-696）说明原因是 transport 异常的 str 里嵌着内部 URL——这条纪律与 main.py 的 500 处理器一致。

## 14. 二轮深化 F：本模块配置影响表

| env | 字段 | 默认 | 作用点 | 备注 |
|---|---|---|---|---|
| PYTHON_STARTUP_TIMEOUT | startup_timeout | 30.0 | `_run_initialization` 总预算（:107-108） | 超时 → CancelledError → 回滚 → stopped |
| OPTIONAL_SERVICE_INIT_TIMEOUT | optional_service_init_timeout | 12.0 | Graphiti/三执行器/Ingestion/Migration 的 `wait_for`（5 处） | 每个服务独立 12s，不共享池 |
| NEO4J_CONNECT_TIMEOUT / NEO4J_QUERY_TIMEOUT | neo4j_connect/query_timeout | 5.0 / 5.0 | MigrationManager 构造参数（:239-240） | GraphitiService 另有自己的驱动参数 |
| REDIS_URL | redis_url | redis://localhost:6379 | IngestionJobManager 初始化（:214-223） | 失败回退内存（见 IngestionJobManager.md） |
| FORENSIC_REPORT_DIR | report_output_dir | build/data/reports | 三个报告工厂的 root 解析（:403-407、:553-557、:582-586） | 相对路径锚定 get_project_root() |
| FORENSIC_REPORT_GENERATOR_VERSION | report_generator_version | 1.0.0 | SnapshotWriter 版本戳（:411-413） | |
| CPP_BACKEND_URL | cpp_backend_url | http://localhost:8080 | CppBackendService(self.settings) 内部 | 本模块不直接读 |

注意 `getattr(self.settings, "startup_timeout", 30.0)` 这类写法（:107、:150 等）让 ServiceManager 对测试用的简化 settings 对象也兼容——缺字段时回落硬编码默认，与 Settings 的 Field 默认值一致。

## 15. 二轮深化 G：RuntimeError 消息 → HTTP 状态码映射（服务边界契约）

属性抛出的 RuntimeError 字符串会原样进入路由层翻译后的 HTTPException detail（`raise ... detail=str(exc)`，如 report_generation.py:46-47、:55-56）。全表：

| RuntimeError 消息（service_manager.py） | 触发属性 | 路由翻译 | 状态码 |
|---|---|---|---|
| "ServiceManager is initializing" | 任意属性（:377） | Depends 工厂 / handler 内 except | 503 |
| "ServiceManager is shutting down" | 任意属性（:379） | 同上 | 503 |
| "ServiceManager is not initialized" | 任意属性（:381，stopped 态） | 同上 | 503 |
| "C++ backend is not initialized" | 9 个 `_create_*` 工厂（:402 等） | investigation/forensic_reports/report_generation/report_evidence 各 Depends | 503 |
| "Forensic report service is unavailable" | forensic_report_service（:423、:427） | forensic_reports.py:39、:70、:167 | 503 |
| "Report generation executor is unavailable" | report_generation_executor（:600） | report_generation.py:55 | 503 |
| "event refresh executor is unavailable" | event_refresh_executor（:620） | investigation.py、investigation_workbench.py 的 refresh 端点 | 503 |
| "secondary analysis executor is unavailable" | secondary_analysis_executor（:642） | analyses accept/reject 端点 | 503 |
| （属性返回 None，不抛） | ingestion_job_manager / migration_manager | graphiti_endpoints/_ingest.py:134、:179 与 _migrate.py:48、:90、:127、:175 的 `if ... is None` 分支 | **501** |

两种降级码的分工由此固定：**503 = 状态机拒绝或依赖服务未就绪（可等待重试）；501 = Graphiti 作业/迁移管理器启动期缺失（功能整体不可用）**。前端 Graphiti 页对 501 的处理是提示服务未启用，对 503 是提示稍后重试。


## 8. 常见任务配方

### 配方 A：新增一个受管服务（四件事）
1. `initialize()` 幂等且可回滚（失败抛出——外层 30s 预算会回滚已初始化项）。
2. 初始化顺序：插进 initialize 序列（可选服务记得 12s 上限 + 失败降级不抛）。
3. 健康上报：health_check() 汇总加你的状态。
4. shutdown() 幂等（重复调用安全）。
范例：读本文件 §4 的五个真实服务初始化段。

### 配方 B：调整启动预算
`PYTHON_STARTUP_TIMEOUT`（30s 总）/`OPTIONAL_SERVICE_INIT_TIMEOUT`（12s/服务）。预算超时会回滚并降级启动——新服务初始化耗时超过 12s 就该挪线程或拆分。

### 配方 C：定制降级行为
参照 GraphitiService 的 initialized-but-disabled 模式：服务对象存在、方法返回降级结果、/health/ready 报 optional 异常。
**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
