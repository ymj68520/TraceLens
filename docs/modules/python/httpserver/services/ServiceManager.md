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

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
