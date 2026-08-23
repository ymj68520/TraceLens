# CppBackendClient / CppBackendService（python_service/httpserver/services/cpp_backend.py）

> **一句话**：通往 C++ 取证后端（:8080）的唯一异步 HTTP 通道——带重试、错误页检测和"客户端侧补齐"（过滤/分页/包装解包），把 C++ 端点的不一致挡在服务层之内。

## 1. 为什么有这个模块

C++ 后端是任务与取证数据的权威来源（任务列表、文件记录、时间线、TOON 导出、文件抽取）。Python 侧几乎所有功能都要向它要数据，但 C++ 的 REST 表面有几处"毛边"：错误时可能返回 HTML 错误页而非 JSON；文件列表端点不支持服务端过滤/分页；响应有时是裸 list 有时是包装 dict。如果每个调用方都自己处理这些，会到处重复且行为不一。CppBackendService 把这些一致性处理收敛到一个带连接池的 httpx 客户端后面。

## 2. 在系统中的位置

- **谁调用它**：ServiceManager 启动时初始化（service_manager.py:124-130）；routes/database.py、routes/llm_endpoints、graphiti_endpoints（任务存在性检查）、forensic_report/investigation 各服务（任务元数据、数据库路径解析）都经 `service_manager.cpp_backend` 使用；task_store（services/task_store.py:49-63）的 `get_task_record` 也经它取权威任务记录。
- **它调用谁**：仅 C++ HTTP 服务（`CPP_BACKEND_URL`，默认 http://localhost:8080，config.py:141）。

## 3. 核心概念与设计

**（a）统一请求内核 `_request()`（cpp_backend.py:79-134）。** 所有 JSON 端点共用它，签名与四条规则：

```python
# cpp_backend.py:79-96（签名与准备段）
async def _request(
    self,
    method: str,
    path: str,
    *,
    timeout: Optional[float] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    **kwargs,
) -> Dict[str, Any]:
    """Make a request, with optional short-lived startup/recovery bounds."""
    payload_preview = kwargs.get("json") or kwargs.get("params")
    logger.info(f"C++ Request: {method} {path} - Payload: {payload_preview}")

    request_kwargs = dict(kwargs)
    if timeout is not None:
        request_kwargs["timeout"] = httpx.Timeout(timeout)
    for attempt in range(max_retries):
```

1. **重试**：默认 3 次、间隔 1s（:96、:133）；启动/恢复路径可传更短的 timeout/retry_delay（见 `list_tasks` 的 0.25s，:171）。
2. **HTML 检测**：C++ 出错时可能吐 HTML 错误页，Content-Type 含 `text/html` 就直接返回 `{"success": False, "error": "Backend returned HTML"}`（:100-109），避免下游对着 HTML 做 `.get()` 崩掉：

```python
# cpp_backend.py:99-109
response = await self.client.request(method, path, **request_kwargs)
content_type = response.headers.get("Content-Type", "").lower()
if "text/html" in content_type:
    logger.error(
        "C++ API returned HTML instead of JSON! Status: %s",
        response.status_code,
    )
    return {
        "success": False,
        "error": "Backend returned HTML",
        "status": response.status_code,
    }
```

3. **HTTP >= 400**：记录响应文本到日志，返回失败 dict（:110-118）。
4. **传输异常**：重试耗尽后只返回异常**类名**（:124-131）——连接错误的消息里带内部 URL，不能外泄：

```python
# cpp_backend.py:124-131
except Exception as exc:
    if attempt == max_retries - 1:
        logger.error(
            "C++ backend request failed after %d attempts: %s",
            max_retries,
            type(exc).__name__,
        )
        return {"success": False, "error": type(exc).__name__}
```

错误字典的形状是**调用方契约**：`{"success": False, "error": <类名或响应文本>, ["status": int]}`。注意第 3 条（HTTP>=400）的 error 是 C++ 响应原文 `response.text`——它可能包含内部细节，但只到服务层日志与 Python 侧调用方，路由层有责任不再把它透传进 HTTP 响应。

**（b）连接池与超时。** `initialize()`（:49-60）建带池的客户端：

```python
# cpp_backend.py:54-58
self._client = httpx.AsyncClient(
    base_url=self.base_url,
    timeout=httpx.Timeout(30.0),
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)
```

keepalive 10 / 总连接 20 / 30s 默认超时；`client` property 兜底懒建（:69-77，无池参数——正常路径不应走到）。`shutdown()`（:62-67）aclose 后置 None，`_initialized=False`，与 ServiceManager 的重开语义对齐。

**（c）客户端侧补齐。** C++ 的 `/api/forensics/files/largest` 不支持过滤分页，于是 `get_task_files_paginated`（:238-283）做三件事——拉 `limit = page_size + offset` 全量（:254-258）、兼容裸 list / `{"largest_files": [...]}` / `{"files": [...]}` 三种包装（:259-265）、客户端过滤 file_type/extension/deleted_only 后切片（:267-278）：

```python
# cpp_backend.py:253-278（节选）
offset = (page - 1) * page_size
params = {"task_id": task_id, "limit": page_size + offset}
result = await self._request("GET", "/api/forensics/files/largest", params=params)
if isinstance(result, dict):
    all_files = result.get("largest_files") or result.get("files") or []
elif isinstance(result, list):
    all_files = result
else:
    all_files = []
# Apply client-side filtering and pagination
filtered_files = all_files
if file_type:
    filtered_files = [f for f in filtered_files if f.get("category") == file_type]
if extension:
    filtered_files = [f for f in filtered_files if f.get("extension") == extension]
if deleted_only:
    filtered_files = [f for f in filtered_files if f.get("is_deleted", False)]
total_count = len(filtered_files)
paginated_files = filtered_files[offset:offset + page_size]
```

注意一个已知事实：**`_request` 失败时返回的是错误 dict**，此时 `result.get("largest_files")` 得 `[]`——C++ 宕机时文件列表表现为"空"而非异常，上游 database 路由因此返回 200 + 空列表（只有非 dict/list 形态才走 else）。这是调用方必须检查 `success` 的根本原因。这是刻意的技术债——真服务端分页需要新 C++ 端点（:250-252 注释明说）。

**（d）TOON 流解析。** `get_files_toon_stream`（:387-427）拿 TOON 文本后按行拆分：`TOON.schema:` 行抽成 schema，其余进 data_lines——供分批送 LLM 而不撑爆上下文（:393-398 docstring）：

```python
# cpp_backend.py:409-427（节选）
lines = toon_data.split('\n')
schema_line = None
data_lines = []
for line in lines:
    line = line.strip()
    if not line:
        continue
    if line.startswith('TOON.schema:'):
        schema_line = line
    else:
        data_lines.append(line)
return {
    "schema": schema_line,
    "data_lines": data_lines,
    "total_files": len(data_lines),
    "batch_size": batch_size,
}
```

`batch_size` 只作为元数据随行返回（调用方按它切 data_lines），方法本身不切分。

## 4. 工作流程走读：一次文件列表请求

前端 `GET /api/db/tasks/{id}/files?page=2&page_size=50` → database 路由调 `get_task_files_paginated(task_id, page=2, page_size=50)`（:238）→ 计算 offset=50，请求 C++ `/api/forensics/files/largest?task_id=...&limit=100`（:254-258）→ 解包响应（list 或包装 dict，:259-265）→ 客户端过滤 file_type/extension/deleted_only（:267-275）→ 切片 `[50:100]` 并返回 `{files, total_count}`（:277-283）。

另一个值得走读的路径是 `get_task`（:174-201）：task_id 先 `quote` 防 path 注入（:182-184，且 `.`/`..` 直接拒收），再**校验响应身份**——C++ 返回的 `id` 必须与请求一致才算命中（:197），最后补齐历史字段别名 `image_name ← image_path`（:199-200）。这两处防御解释了为什么上层敢直接信任 task 元数据：

```python
# cpp_backend.py:182-200（节选）
if task_id in {".", ".."}:
    return None
task_segment = quote(task_id, safe="")
# ...
result = await self._request("GET", f"/api/tasks/{task_segment}", **request_kwargs)
if not isinstance(result, dict) or result.get("id") != task_id:
    return None
if "image_path" in result and "image_name" not in result:
    result["image_name"] = result["image_path"]
return result
```

`check_task_exists`（:203-206）就是 `get_task(...) is not None` 的薄封装——graphiti 摄取路由的 404 前置判定即源于此。返回 None 而非抛异常，是"任务不存在"在 Python 侧的统一表达。

## 5. 关键接口清单（一行语义 + 调用方 + 失败行为）

| 方法 | C++ 端点 | 失败行为 |
|---|---|---|
| `health_check() -> bool`（:136） | `GET /api/health` | 任何异常 False（readiness 用） |
| `list_tasks(status,page,page_size,timeout,max_retries)`（:152） | `GET /api/tasks/list` | 失败 dict；startup 路径传 0.25s retry_delay |
| `get_task(task_id) -> Optional[dict]`（:174） | `GET /api/tasks/{id}` | None（拒 `.`/`..`、身份不符、请求失败） |
| `check_task_exists(task_id) -> bool`（:203） | 同上 | False |
| `get_task_databases(task_id) -> List[dict]`（:208） | `GET /api/tasks/{id}/databases` | 失败 dict 时 `.get("databases",[])` → `[]` |
| `get_task_files(task_id,file_types,limit)`（:215） | `GET /api/forensics/files/largest` | 同上 → `[]`（category 客户端过滤 :233-235） |
| `get_task_files_paginated(...)`（:238） | 同上 | 见 (c)，`{files:[], total_count:0}` |
| `get_task_events(...)`（:287） | `GET /api/forensics/timeline/comprehensive` | dict 形态失败 → `events:[]`；list 形态直通 |
| `extract_files(task_id,file_paths,output_dir,overwrite)`（:326） | `POST /api/forensics/extract` | 失败 dict（file_paths 以逗号拼进 pattern，:345-353 注释） |
| `get_extraction_status(job_id)`（:358） | `GET /api/forensics/extract/status` | 失败 dict |
| `export_toon(task_id,include_llm) -> str`（:373） | `GET /api/forensics/export/toon` | **不走 `_request`**：`raise_for_status()` 直抛 |
| `get_files_toon_stream(task_id,batch_size,include_llm)`（:387） | 同上 | 同上 |
| `export_json(task_id,database_type,include_llm)`（:429） | `GET /api/forensics/export/events/json` | 失败 dict 原样返回 |

调用方分布：database.py 用 list/get/databases/files/events/export 全套；llm_endpoints 与 graphiti_endpoints 用 get_task/check_task_exists；investigation/forensic_report 服务用 get_task 的 `output_files_db`/`output_events_db` 派生 DB 路径（task_store 在其上建立 D2b 信任边界）；oss_filter_service 间接消费 task 元数据。

## 6. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| ServiceManager | 生命周期拥有者；`_cpp_backend_ready` 是上层服务的硬门槛 |
| routes/database.py | 任务/文件/事件/导出的数据通道 |
| routes/llm_endpoints、graphiti_endpoints | 任务存在性检查（404 语义来源） |
| forensic_report / investigation 服务 | 任务元数据与 `output_files_db`/`output_events_db` 路径来源 |
| services/task_store.py | `get_task_record` 的底层（D2b 权威记录） |
| llm/file_analyzer | 间接：经 task_info 拿 extraction_directory 解析证据路径 |

C++ 端点使用清单（全部经由本类）：`GET /api/health`、`/api/tasks/list`、`/api/tasks/{id}`、`/api/tasks/{id}/databases`、`/api/forensics/files/largest`、`/api/forensics/timeline/comprehensive`、`POST /api/forensics/extract`、`GET /api/forensics/extract/status`、`GET /api/forensics/export/toon`、`GET /api/forensics/export/events/json`。（DLL 分析走的 `POST /api/forensics/dlls/analyze` 在 services/dll/dll_analyzer.py 的独立客户端里，不经本类。）

## 7. 注意事项与已知问题

- 深分页放大传输（见 3c）；大任务的第 N 页会拉 N×page_size 条。
- `export_toon`/`export_json` 不走 `_request` 的重试/HTML 检测（直接 `self.client.get`，:373-385、:429-442），C++ 抖动时这两个方法最脆弱。
- 失败一律以 `{"success": False, "error": ...}` dict 返回而非抛异常——调用方**必须**检查 success，漏检会把错误 dict 当数据用（get_task_files 系列已把它静默成空列表）。
- `_request` 会 log payload 与响应前 200 字符（:91、:122），排查方便，但注意别把带敏感内容的请求开到 DEBUG 以上的日志采集里。
- env：`CPP_BACKEND_URL`（默认 http://localhost:8080）是唯一地址来源；`HTTP_SERVER_HOST/PORT`（:142-143）仅用于拼 `cpp_backend_base_url` property（config.py:294-297），后者当前无消费者。

## 8. 如何验证与扩展

- 相关单测：`python_service/tests/unit/test_database_models.py`（经由 database 路由的契约）、`test_d2b_task_store.py`（任务元数据信任链）；C++ 侧契约见 docs/api_reference/CPP_REST_API.md。
- 手工验证：停掉 C++ 后调 `/health/ready`（应 `ready:false`），或直接观察 `_request` 的 HTML 检测日志。
- 新增 C++ 端点封装：优先走 `_request()`（自动获得重试/HTML/错误处理）；需要流式或纯文本（如 TOON）时才直连 client，并自行处理状态码。

相关阅读：[httpserver/services/ServiceManager.md](./ServiceManager.md)、[httpserver/routes/Database.md](../routes/Database.md)。

## 9. 二轮深化 A：方法签名全清单（含默认值与精确调用点）

| 方法（完整签名要点） | 行 | 调用点（源码核对） |
|---|---|---|
| `health_check() -> bool` | :136 | ServiceManager.health_check（service_manager.py:689）；routes/health.py |
| `list_tasks(status=None, page=1, page_size=50, *, timeout=None, max_retries=3)` | :152 | routes/database.py:110；case_aggregation_manager.py:92；investigation/execution.py:518；investigation/event_refresh_execution.py:240（后两者为重启恢复，传短 timeout） |
| `get_task(task_id, *, timeout=None, max_retries=3) -> Optional[dict]` | :174 | task_store（get_task_record）；graphiti/_ingest、llm/case 各前置检查；ServiceManager 内部（报告工厂仅引用对象） |
| `check_task_exists(task_id) -> bool` | :203 | graphiti_endpoints/_ingest.py（404 前置判定） |
| `get_task_databases(task_id) -> List[dict]` | :208 | routes/database.py:181；forensic_report/source_resolver.py:60（DB 路径解析） |
| `get_task_files(task_id, file_types=None, limit=100) -> List[dict]` | :215 | llm_endpoints/_analysis.py:465（批量分析取文件清单） |
| `get_task_files_paginated(task_id, file_type=None, extension=None, deleted_only=False, include_llm=True, page=1, page_size=50) -> dict` | :238 | routes/database.py:221（唯一调用方） |
| `get_task_events(task_id, event_type=None, start_time=None, end_time=None, page=1, page_size=50) -> dict` | :287 | routes/database.py:288（唯一调用方） |
| `extract_files(task_id, file_paths, output_dir=None, overwrite=False) -> dict` | :326 | case_analysis_parts/_windows.py:199（Windows 工件先抽取再分析） |
| `get_extraction_status(job_id) -> dict` | :358 | case_analysis_parts/_windows.py:219（抽取进度轮询） |
| `export_toon(task_id, include_llm=True) -> str` | :373 | routes/database.py:344；file_filter.py 经 get_files_toon_stream 间接 |
| `get_files_toon_stream(task_id, batch_size=100, include_llm=False) -> dict` | :387 | case_analysis/file_filter.py:203（deterministic 筛选数据源） |
| `export_json(task_id, database_type, include_llm=True) -> dict` | :429 | routes/database.py:384（唯一调用方；`database_type` 参数当前未拼进请求——端点固定 events 导出） |

构造/生命周期：`__init__(settings)`（:36-47，读 `settings.cpp_backend_url` 存 base_url）、`initialize()`（:49-60，建池化客户端）、`shutdown()`（:62-67）、`client` property（:69-77，None 兜底懒建**无池参数**）。两个二轮新发现：`_request_timeout_override` 字段（:47）定义后**全仓无任何读写**——死字段；`__init__` 对 base_url 不做尾部斜杠归一（对比 dll_analyzer.py:20 有 `rstrip('/')`），若 CPP_BACKEND_URL 配成 `http://localhost:8080/`，httpx 拼接行为将依赖其自身的 base_url 合并规则。

## 10. 二轮深化 B：失败返回形状契约（逐方法）

`_request` 的失败 dict 是 `{"success": False, "error": <str>, ["status": int]}`，但每个公开方法把它二次加工成不同形状——这张表是上游路由实际拿到的契约：

| 方法 | 成功形状 | C++ 宕机/失败时的实际返回 | 静默空值风险 |
|---|---|---|---|
| list_tasks | C++ 原始 dict | 失败 dict（保留 success=False） | 低（database 路由检查 success） |
| get_task | task dict 或 **None** | None | 中：None 语义="任务不存在"，与"后端宕机"不可区分 |
| get_task_databases | `[{...}]` | `[]`（`.get("databases", [])` 吞掉失败 dict，:211） | **高**：宕机时表现为"任务无数据库" |
| get_task_files | `[{...}]` | `[]`（:226-231 兼容解包吞掉失败） | **高**：同上 |
| get_task_files_paginated | `{files, total_count}` | `{files: [], total_count: 0}` | **高**（见 3c 既有叙述） |
| get_task_events | `{events, total_count}` | `{events: [], total_count: 0}` | **高** |
| extract_files | C++ 原始 dict | 失败 dict | 低（_windows.py 检查） |
| get_extraction_status | C++ 原始 dict | 失败 dict | 低 |
| export_toon | TOON 文本 str | **抛 httpx.HTTPStatusError**（raise_for_status，:384） | 无静默（见 12 节走读） |
| get_files_toon_stream | `{schema, data_lines, total_files, batch_size}` | 继承 export_toon 的抛异常 | 无 |
| export_json | dict（或 `{"data": <list>}` 包装，:442） | 失败 dict 原样 | 中 |

规律：**只有直连 client 的两个 TOON 方法会抛异常，其余全部走"失败 dict / 空集合"降值**。排障口诀：文件/事件/数据库列表"变空"先怀疑 C++ 可用性，再看 `_request` 日志里的 HTML/超时行。

## 11. 二轮深化 C：新走读——get_task_events 的双形态解包与 total_count 陷阱

```python
# cpp_backend.py:309-322
result = await self._request("GET", "/api/forensics/timeline/comprehensive", params=params)

# Handle different response formats
if isinstance(result, dict):
    timeline = result.get("timeline", [])
    metadata = result.get("metadata", {})
    return {
        "events": timeline,
        "total_count": metadata.get("total_events", len(timeline)),
    }
return {
    "events": result if isinstance(result, list) else [],
    "total_count": 0,
}
```

逐块解释：dict 分支取 `timeline` 数组与 `metadata.total_events`（缺失时退回当页条数——本身也只是"本页大小"而非总数）；非 dict 分支兼容 C++ 直接返回裸 list 的形态。三个边界：

1. **失败 dict 也命中 dict 分支**：`{"success": False, "error": "ConnectError"}` 没有 `timeline` 键 → `events: [], total_count: 0`，错误信息被完全吞掉。
2. **裸 list 形态下 total_count 恒为 0**：即使 events 非空，`total_count: 0`——前端若用它做分页总数会得到"共 0 条却有数据"的自相矛盾展示。这是真实存在的形态依赖：只有 C++ 按时返回包装 dict 时分页才是对的。
3. `limit/offset` 直接透传（:299-300），不像 files 系列做客户端切片——事件分页是**服务端分页**，两种机制的差异在 database 路由文档里再展开。

## 12. 二轮深化 D：新走读——export_toon 直连路径（唯一会抛异常的出口）

```python
# cpp_backend.py:373-385
async def export_toon(
    self,
    task_id: str,
    include_llm: bool = True,
) -> str:
    """Export task data in TOON format."""
    params = {"include_llm": include_llm}
    response = await self.client.get(
        f"/api/forensics/export/toon",
        params={"task_id": task_id, **params},
    )
    response.raise_for_status()
    return response.text
```

与 `_request` 的四条规则对照，这条路**全都没有**：无重试（C++ 抖动一次即失败）、无 HTML 检测（错误页会当正文返回——好在 raise_for_status 通常先拦住 4xx/5xx，但 200+HTML 的极端形态会漏过）、无错误 dict（`raise_for_status()` 抛 httpx.HTTPStatusError，`str(e)` 内含 URL）、无 payload 日志。两个消费者：database.py:344 把异常交给路由的兜底 500；file_filter.py:203 的 `get_files_toon_stream` 让异常继续上抛到确定性筛选入口——也就是说 **deterministic 文件筛选在 C++ 宕机时是显式失败（500/作业失败），不是静默空集**，与 get_task_files 系列行为相反。`include_llm=True` 默认值在 `get_files_toon_stream`(:391) 被显式改回 `False`——筛选场景不要 LLM 列，减小传输。

## 13. 二轮深化 E：配置与传输参数影响表

| 参数 | 值 | 位置 | 说明 |
|---|---|---|---|
| CPP_BACKEND_URL | http://localhost:8080 | config.py:141 → :44 | 唯一地址来源；不做尾部斜杠归一（见上） |
| 默认请求超时 | 30.0s | :55（httpx.Timeout(30.0)） | `_request` 的 timeout 参数可覆盖（startup 路径传 5s 档） |
| 吞吐恢复期超时/重试 | 调用方传 | :158-159、:171 | `list_tasks(timeout=...)` 触发 `retry_delay=0.25`，否则 1.0s |
| 连接池 | keepalive 10 / max 20 | :56 | 并发>20 的调用会排队等连接 |
| 重试次数 | 3（默认） | :96 | HTML/4xx/5xx **不**重试——只有传输异常重试（:110-118 直接返回） |
| 日志 | payload + 响应前 200 字符 | :91、:122 | INFO 级 |

注意重试语义的精确边界：HTTP >= 400 与 HTML 响应在**第一次**尝试就直接返回失败 dict，`for attempt in range(max_retries)` 循环只对 `Exception`（网络层）生效——重试不是通用的。

## 14. 二轮深化 F：C++ 端点请求参数明细（Python 侧实际发送的形状）

| C++ 端点 | 方法 | 发送的参数（源码核对） | 期望响应形态 |
|---|---|---|---|
| `/api/health` | GET | 无 | 仅看状态码 200（health_check，:144-145） |
| `/api/tasks/list` | GET | `page`(默认1)、`page_size`(默认50)、可选 `status`（:162-164） | 包装 dict（含任务数组与分页字段） |
| `/api/tasks/{id}` | GET | 路径段经 `quote(task_id, safe="")`；`.`/`..` 直接拒收（:182-184） | dict，且 `id` 必须回显一致（:197） |
| `/api/tasks/{id}/databases` | GET | 仅路径 | `{"databases": [...]}` |
| `/api/forensics/files/largest` | GET | `task_id`、`limit`（paginated 版传 `page_size+offset`，:254-258；plain 版传 limit，:222） | 裸 list 或 `{"largest_files":[...]}` 或 `{"files":[...]}` 三态（:226-231、:259-265） |
| `/api/forensics/timeline/comprehensive` | GET | `task_id`、`limit`、`offset`、可选 `event_type/start_time/end_time`（:297-307） | `{"timeline":[...], "metadata":{"total_events":N}}` 或裸 list |
| `/api/forensics/extract` | POST | json：`task_id`、`mode:"name"`、`pattern:`逗号拼接的 file_paths、`output_dir`（默认 "extracted_files"）、`overwrite`（:347-353） | 含 `job_id` 的 dict |
| `/api/forensics/extract/status` | GET | `job_id`（:368） | 进度 dict |
| `/api/forensics/export/toon` | GET | `task_id`、`include_llm`（:379-383） | TOON 纯文本（非 JSON） |
| `/api/forensics/export/events/json` | GET | `task_id`（:440；`database_type`/`include_llm` **未发送**） | dict 或 list（:442 统一包装成 dict） |

三处值得标注的契约缝隙：`extract_files` 的逗号拼接 pattern（:345-346 注释自认"may need C++ backend extension for true list mode"——文件名本身含逗号会被误拆）；`export_json` 的 `database_type` 形参从未进请求（端点名固定 events）；`get_task` 的身份回显校验（:197）是唯一防"错配响应"的防线。

## 15. 二轮深化 G：与 DLL 独立客户端的对照

`services/dll/dll_analyzer.py` 的 DLLAnalyzerClient 是仓库里第二个直连 C++ 的客户端（`POST {cpp_backend_url}/api/forensics/dlls/analyze`，dll_analyzer.py:54），与本类的差异构成一组有意无意的对照：它有 `rstrip('/')` 归一（dll_analyzer.py:20）、超时来自 `DLL_ANALYSIS_TIMEOUT`（30s，dll_analyzer.py:26）、无重试无 HTML 检测、异常直接上抛（DLL 路由自己转 502/503）。也就是说"C++ 毛边处理"只存在于 CppBackendService 一处——新代码若要直连 C++，应优先复用本类而不是再起一个客户端。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
