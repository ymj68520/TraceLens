# Database 路由（python_service/httpserver/routes/database.py，前缀 /api/db）

> **一句话**：把 C++ 产出的取证 SQLite 数据（任务、文件、时间线事件）以只读、分页、可导出的形式暴露给前端，是前端浏览取证结果的查询窗口。

## 这组路由承担什么职责

C++ 分析磁盘镜像后会生成任务元数据和 `<image>_files.db` / `<image>_events.db` 等数据库。这组路由**不直接打开这些库**（除导出外），而是把查询转发给 CppBackendService，再把 C++ 的原始响应整形为统一的 `{success, ..., total_count, page, page_size, timestamp}` 分页结构。职责边界：参数校验与响应建模在这里，数据获取与（客户端侧）过滤/分页补齐在 CppBackendService。

## 典型调用方

前端任务/文件/时间线相关页面（web/src 中调用 `/api/db/tasks*` 的 forensicsService 等，经 pythonApi）。这组是纯前端面向的只读接口，C++ 不会调用它。

## 核心数据结构

响应模型是这组的"收敛层"（database.py:26-68），FileRecord 逐字段带默认值：

```python
# database.py:26-39
class FileRecord(BaseModel):
    """File record from database."""
    id: int
    name: str
    path: str
    size: int
    file_type: str
    extension: Optional[str] = None
    md5: Optional[str] = None
    created_time: Optional[str] = None
    modified_time: Optional[str] = None
    accessed_time: Optional[str] = None
    is_deleted: bool = False
    llm_description: Optional[str] = None
```

字段来源：全部由 C++ `/api/forensics/files/largest` 的行经 `f.get(...)` 补齐（:231-247）——`id/name/path/size/file_type` 缺省值分别为 0/""/""/0/"unknown"，其余可空字段 None。`llm_description` 受 `include_llm` 开关控制（见下）。EventRecord（:52-58）只有 `id/event_type/file_path/timestamp/details` 五字段，details 是开放式 dict（承接 C++ 的 JSON 详情列）。四个 List 响应模型统一带 `success/total_count/page/page_size/timestamp` 分页包络。

## 端点签名

- `GET /tasks?status=&page=1&page_size=50(≤100)` → dict（:97-126）
- `GET /tasks/{task_id}` → `{success,task,timestamp}`（:138-163，404 由"C++ 找不到该任务"触发）
- `GET /tasks/{task_id}/databases` → `TaskDatabasesResponse`（:170-191）
- `GET /tasks/{task_id}/files?file_type=&extension=&deleted_only=&include_llm=&page=&page_size(≤500)` → `FileListResponse`（:202-259）
- `GET /tasks/{task_id}/events?event_type=&start_time=&end_time=&page=&page_size(≤500)` → `EventListResponse`（:270-318）
- `GET /tasks/{task_id}/export/toon?include_llm=` → StreamingResponse（:328-358）
- `GET /tasks/{task_id}/export/json?database_type=files&include_llm=` → StreamingResponse（:368-401）

## 数据流（读写什么）

纯**读路径**：路由 → `service_manager.cpp_backend` → C++ REST。`GET /tasks/{task_id}/files` 的 handler 主体就是"转发 + 整形"（:221-256）：

```python
# database.py:221-252（节选）
result = await service_manager.cpp_backend.get_task_files_paginated(
    task_id=task_id,
    file_type=file_type,
    extension=extension,
    deleted_only=deleted_only,
    include_llm=include_llm,
    page=page,
    page_size=page_size,
)

files = [
    FileRecord(
        id=f.get("id", 0),
        name=f.get("name", ""),
        path=f.get("path", ""),
        size=f.get("size", 0),
        file_type=f.get("file_type", "unknown"),
        extension=f.get("extension"),
        # ...
        llm_description=f.get("llm_description") if include_llm else None,
    )
    for f in result.get("files", [])
]
```

两个关键事实：

1. **分页是"补齐"出来的**。C++ 的 largest-files 端点不支持页码，CppBackendService 用 `limit = page_size + offset` 拉全量后客户端切片（cpp_backend.py:253-278）；file_type/extension/deleted_only 同样是客户端过滤（:267-275）。代价：深翻页会把前面所有页的数据都传一遍。database.py 只是如实地把这套补齐结果包装返回。`include_llm=False` 时 llm_description 置 None（:244），用于在未跑 LLM 分析时减小传输负载——注意它**不改变**对 C++ 的请求参数（过滤发生在 Python 侧序列化时）。
2. **响应模型是收敛层**。FileRecord/EventRecord 把 C++ 字段缺省补齐（`f.get(...)` 全带默认值），前端因此不必处理 C++ 端的字段演化。

事件端点的时序注意点：`get_task_events`（cpp_backend.py:287-322）把 page/page_size 换算成 C++ 认识的 `limit/offset` 传给 `/api/forensics/timeline/comprehensive`（**服务端真分页**，与 files 不同），并兼容 `{"timeline": [...], "metadata": {...}}` 包装形态：

```python
# cpp_backend.py:297-318（节选）
params = {
    "task_id": task_id,
    "limit": page_size,
    "offset": (page - 1) * page_size,
}
if event_type:
    params["event_type"] = event_type
if start_time:
    params["start_time"] = start_time
if end_time:
    params["end_time"] = end_time

result = await self._request("GET", "/api/forensics/timeline/comprehensive", params=params)

# Handle different response formats
if isinstance(result, dict):
    timeline = result.get("timeline", [])
    metadata = result.get("metadata", {})
    return {
        "events": timeline,
        "total_count": metadata.get("total_events", len(timeline)),
    }
```

`total_count` 优先取 C++ metadata 的 total_events（分页语义正确），缺失时回落到"本页条数"（此时前端翻页总数会失真——观察点）。

TOON 导出走 StreamingResponse 单块迭代（:349-355）：

```python
# database.py:349-355
return StreamingResponse(
    iter([toon_content.encode("utf-8")]),
    media_type="application/x-toon",
    headers={
        "Content-Disposition": f"attachment; filename={task_id}_export.toon"
    }
)
```

`export_toon` 直连 `self.client.get` + `raise_for_status()`（cpp_backend.py:380-385），异常（含 C++ 5xx）向上冒泡被路由的统一 except 捕获转 500 "database export failed"。

## 边界与已知状态

- 全组只读：没有任何 POST/PUT/DELETE；写路径（LLM 分析回写、相关性开关）在 `/api/llm`。
- 错误统一转 5xx + 简短 detail（如 "file records are unavailable"，database.py:259；"task list is unavailable" :126；"event records are unavailable" :318），内部异常文本不外泄；404 仅出现在任务级（:152）。
- `database_type` 查询参数（export/json，:370）目前只对 events 导出生效（CppBackendService.export_json 固定调 events 端点，cpp_backend.py:441）；其他库型的导出需要新的 C++ 端点。
- 深分页性能受客户端分页策略制约（见上）；大任务翻到很后面的页会明显变慢。
- C++ 宕机时文件/事件列表返回 200 + 空列表（`_request` 失败 dict 被 `.get("files", [])` 吞掉），只有任务详情会因 get_task 返回 None 而 404——排障时注意"空列表 ≠ 无数据"。
- env：间接消费 `CPP_BACKEND_URL`（默认 http://localhost:8080）；无本组专属 env。

## 如何验证与扩展

- 模型契约：`python_service/tests/unit/test_database_models.py`。
- 客户端过滤/分页补齐行为：CppBackendService 的相关单测（见 [httpserver/services/CppBackendClient.md](../services/CppBackendClient.md) 第 8 节）。
- 手工验证：`curl 'http://localhost:8090/api/db/tasks'` → 取 task_id → `curl '.../tasks/{id}/files?page=1&page_size=10'`。
- 扩展方向：若要真服务端分页，需要在 C++ 增加带 offset 的端点，然后把 `get_task_files_paginated` 换成直传——路由层几乎不用动，这正是"补齐逻辑藏在服务层"的好处。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[httpserver/services/CppBackendClient.md](../services/CppBackendClient.md)。

## 二轮深化 A：端点全表（含 query 参数与响应码）

| 端点 | 方法 | query 参数（默认/上限） | 响应 | 声明状态码 |
|---|---|---|---|---|
| `/api/db/tasks` | GET | status?、page=1、page_size=50（le=100） | Dict[str,Any]（C++ 原始形状直通） | 200/500 |
| `/api/db/tasks/{task_id}` | GET | — | `{success,task,timestamp}` | 200/404/500 |
| `/api/db/tasks/{task_id}/databases` | GET | — | TaskDatabasesResponse | 200/500 |
| `/api/db/tasks/{task_id}/files` | GET | file_type?、extension?、deleted_only=false、include_llm=true、page=1、page_size=50（le=500） | FileListResponse | 200/500 |
| `/api/db/tasks/{task_id}/events` | GET | event_type?、start_time?、end_time?、page=1、page_size=50（le=500） | EventListResponse | 200/500 |
| `/api/db/tasks/{task_id}/export/toon` | GET | include_llm=true | StreamingResponse（application/x-toon） | 200/500 |
| `/api/db/tasks/{task_id}/export/json` | GET | database_type="files"、include_llm=true | StreamingResponse（application/json） | 200/500 |

`{task_id}` 是纯路径段（无 Pydantic 校验）；`page/page_size` 的上限只在这组路由声明（Query le=），CppBackendService 侧不复查。

## 二轮深化 B：模型契约补全与死模型

六个模型中一个此前未提及的细节：**ExportResponse（database.py:71-76）定义后从未被任何端点引用**——两个 export 端点实际返回 StreamingResponse（无 response_model），这是死模型。其余包络字段（success/total_count/page/page_size/timestamp）的写者/读者：

| 模型 | 字段 | 来源 | 说明 |
|---|---|---|---|
| FileRecord | is_deleted | `f.get("is_deleted", False)` | 客户端过滤 deleted_only 的同源字段 |
| | llm_description | include_llm=False 时强制 None（:244） | **响应层过滤**，不改变 C++ 请求 |
| EventRecord | details | Optional[Dict] | C++ 的 JSON 详情列直通；无 schema |
| TaskDatabasesResponse | databases | List[Dict[str,Any]] | 行内含 name/path/type 等键（C++ 定义） |
| 四个 List 包络 | total_count | files=客户端切片总数；events=C++ metadata.total_events（缺失回落本页条数） | 两族语义不同（见 CppBackendClient.md 11 节） |

## 二轮深化 C：分页机制对照表（files vs events）

| 维度 | /files | /events |
|---|---|---|
| C++ 端点 | /api/forensics/files/largest | /api/forensics/timeline/comprehensive |
| 分页位置 | **Python 客户端切片**（limit=page_size+offset 拉全量） | **C++ 服务端**（limit/offset 直传） |
| 过滤位置 | Python 客户端（file_type/extension/deleted_only） | C++ 服务端（event_type/start/end_time） |
| total_count 语义 | 过滤后全量数（准确） | 依赖 metadata；裸 list 形态恒 0（失真） |
| 深翻页成本 | O(累计行数) 传输 | 恒定 |
| C++ 宕机表现 | 200 + 空列表 | 200 + 空列表 |
| page_size 上限 | 500 | 500 |

## 二轮深化 D：新走读——export/json 的"失败也成文件"分支

```python
# database.py:383-398（节选）
data = await service_manager.cpp_backend.export_json(
    task_id=task_id,
    database_type=database_type,
    include_llm=include_llm,
)
json_content = json.dumps(data, indent=2, ensure_ascii=False)
return StreamingResponse(
    iter([json_content.encode("utf-8")]),
    media_type="application/json",
    headers={"Content-Disposition": f"attachment; filename={task_id}_{database_type}.json"}
)
```

逐块解释：`export_json` 失败时返回的是 `{"success": False, "error": <类名>}` dict（CppBackendClient.md 10 节），而这里**不检查 success**——失败 dict 会被 `json.dumps` 序列化成一份合法 JSON 下载文件（HTTP 200）。也就是说：C++ 宕机时用户拿到的是名为 `<task>_files.json`、内容为 `{"success": false, "error": "ConnectError"}` 的"导出成果"。触发条件（异常直抛成 500 "database export failed"）只覆盖传输层 httpx 异常，覆盖不了 `_request` 的失败 dict 形态。TOON 导出没有这个问题——`export_toon` 直连 client、失败直接抛异常进 except 分支。排障/验收时应先 `jq .success` 检查导出文件。另外 `json.dumps(indent=2, ensure_ascii=False)`：大任务全量 events 的导出在 Python 侧一次性驻留内存（无流式切分），内存敏感场景注意。

## 二轮深化 E：调用方矩阵（二轮新发现）

对 `web/src/` 全量 grep（services、pages、hooks）的结果：**没有任何前端代码引用 `/api/db/*`**——forensicsService 的文件/时间线方法全部走 C++ 基座（`api` → `/api/forensics/*`），与本组无关。结合上文"典型调用方"一节的描述，二轮核实的结论是：**`/api/db` 七个端点当前没有前端消费者**，实际用户是手工 curl、测试（`test_database_models.py`）与潜在的集成方；本文前面"前端任务/文件/时间线相关页面调用 /api/db/tasks*"的说法与源码不符，以本节 grep 结果为准。这组路由因此更像"预留的 Python 侧只读代理层"：功能可用、无人在用、下线不影响前端。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
