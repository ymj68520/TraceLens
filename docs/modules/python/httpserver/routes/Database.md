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

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
