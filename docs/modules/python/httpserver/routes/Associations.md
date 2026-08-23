# Associations 路由（python_service/httpserver/routes/associations.py，前缀 /api/associations）

> **一句话**：事件簇与文件的**双向时间关联**端点——给一个事件簇找出 ±5 分钟内、同目录下的相关文件（含四时间戳异常检测），或给一个文件找出时间+目录双匹配的事件簇，供 /analysis-center 页的证据抽屉使用。

## 1. 这组路由承担什么职责（为什么存在）

时间线把文件系统事件聚成簇（`(timestamp/60, event_type)`），但簇本身不含完整文件元数据；反之文件详情页需要回答"这个文件牵涉哪些事件簇"。这组路由补上双向桥：`POST /cluster-files` 与 `POST /file-clusters`。关联语义被刻意做严：时间上严格 ±300 秒、目录上**段感知**（segment-aware）包含，匹配必须同时满足时间与目录（B2/B4），避免把整盘同秒文件都算进来。四时间戳（atime/mtime/ctime/crtime）优先取自 `_raw.db`，`_files.db` 只有 mtime/ctime（associations.py:9-11 的注释写明这一分工）。

## 2. 典型调用方（前端哪个页面/组件）

前端 `/analysis-center` 页的证据抽屉：web/src/pages/AnalysisCenter.jsx:16-22 引 `getClusterRelatedFiles`、`getFileRelatedClusters` 及异常展示 helper（formatAnomalyType/getAnomalySeverity/getAnomalyColorClass），服务封装在 web/src/services/associationService.js（`/cluster-files` :28、`/file-clusters` :58）。服务端无其他调用方。

## 3. 核心数据结构

两个请求模型（associations.py:31-45）：

```python
# associations.py:31-45
class ClusterFilesRequest(BaseModel):
    """Request model for getting files related to a cluster."""
    task_id: str = Field(..., description="Task ID")
    time_window: int = Field(..., description="Cluster time window (timestamp / 60)")
    timestamp: Optional[int] = Field(None, description="Cluster timestamp (original, deprecated - use time_window)")
    event_type: str = Field(..., description="Event type (CREATED, MODIFIED, DELETED, etc.)")
    parent_directory: str = Field("", description="Parent directory of the events")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results to return")

class FileClustersRequest(BaseModel):
    """Request model for getting clusters related to a file - simplified."""
    task_id: str = Field(..., description="Task ID")
    file_path: str = Field(..., description="Full file path")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results to return")
```

簇→文件方向：`time_window` 是分钟桶索引（簇时间戳 = time_window×60，:185-190），`timestamp` 是 deprecated 直给秒值；`parent_directory` 空串/"/" 表示无目录约束。文件→簇方向只要 `file_path`——簇参数全部由服务端从 events.db 重建。响应含 `cluster_info`/`file_info` 回显匹配上下文。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

全部只读。任务元数据经 `service_manager.cpp_backend.get_task` 拿 `output_files_db`/`output_raw_db`/`output_events_db`（:172-178、:335-343），任务不存在 404、无对应库 400。raw.db 缺失时从 files.db 换名派生（`_files.db→_raw.db`，:178）。簇→文件方向的核心查询把 raw.db ATTACH 进 files.db 做**逐路径回退**的联合候选（:210-241）：

```python
# associations.py:216-227（节选）——四个时间戳任一命中 ±300s 即候选
if attached_raw:
    files_table_sql = """
        SELECT f.path AS file_path, f.size AS file_size, f.mtime, f.ctime,
               f.extension, f.name, f.llm_summary, f.llm_description,
               r.atime AS atime, r.crtime AS crtime
        FROM files f
        LEFT JOIN raw.files r ON r.path = f.path
        WHERE (f.mtime IS NOT NULL AND f.mtime > ? AND f.mtime < ?)
           OR (f.ctime IS NOT NULL AND f.ctime > ? AND f.ctime < ?)
           OR (r.atime IS NOT NULL AND r.atime > ? AND r.atime < ?)
           OR (r.crtime IS NOT NULL AND r.crtime > ? AND r.crtime < ?)
        ORDER BY f.mtime DESC
    """
```

files.db 保持主位（元数据来源）；LEFT JOIN 让"在 files.db 有、raw 没有"的行仍由 f.mtime/f.ctime 子句选中——**逐文件**回退而非整体放弃。SQL 只是候选粗筛；**最终裁决在 Python**——严格不等式保住 `abs(diff) < 300` 的边界语义（注释 :192-194 明说不用 BETWEEN，那会悄悄变成 ≤300），裁决点在 :266-271（min_diff < 300 才收）。目录谓词 `is_path_under_directory`（:76-86）先经 `normalize_evidence_path` 规范化再做段感知包含（`/case/a` 不匹配 `/case/abc`），空或 `/` 视为无约束：

```python
# associations.py:76-86
def is_path_under_directory(path: str, parent: str) -> bool:
    """Segment-aware containment: True if canonical `path` equals or is inside canonical `parent`.

    An empty or "/" parent means "no directory constraint" (matches everything).
    Segment-aware so '/case/a' does NOT match '/case/abc' or '/case/a-extra'.
    """
    path_n = normalize_evidence_path(path)
    parent_n = normalize_evidence_path(parent)
    if not parent_n or parent_n == "/":
        return True
    return path_n == parent_n or path_n.startswith(parent_n + "/")
```

文件→簇方向的关键是 B5b 的 CTE（:413-435）：**先完整建簇再按文件时间窗过滤**，不预截断事件行（否则 cluster_start/end/count 全会失真），簇的目录集合也从**全量**事件路径推导、响应只展示 5 个样本（:445-461 注释与实现）：

```python
# associations.py:413-435（节选）
sql = f"""
    WITH clusters AS (
        SELECT
            (timestamp / 60) AS time_window,
            event_type,
            MIN(timestamp) AS cluster_start,
            MAX(timestamp) AS cluster_end,
            COUNT(*) AS event_count,
            CASE
                WHEN MIN(timestamp) != MAX(timestamp) THEN MIN(timestamp)
                ELSE timestamp
            END AS representative_timestamp,
            llm_summary, llm_description, llm_keywords, llm_is_relevant
        FROM events
        GROUP BY time_window, event_type
    )
    SELECT * FROM clusters
    {cluster_filter}
    ORDER BY representative_timestamp DESC
"""
```

`cluster_filter` 由文件时间戳推出（min-300, max+300 的窗口，:403-411）；注释（:398-402）记录了两个被移除的反模式：预截断事件行、`ORDER BY ... LIMIT limit*10`（后者会漏掉"不够新"的有效簇）。异常检测 `detect_time_anomaly`（:89-132）四规则：

```python
# associations.py:113-130（节选）
# Check 1: mtime mismatch with cluster time
if mtime and abs(mtime - cluster_time) > 3600:
    anomalies.append('mtime_mismatch')
# Check 2: crtime after mtime
if crtime and mtime and crtime > mtime:
    anomalies.append('crtime_after_mtime')
# Check 3: atime before mtime
if atime and mtime and atime < mtime:
    anomalies.append('atime_before_mtime')
# Check 4: High time variance (> 1 day = 86400 seconds)
times = [t for t in [atime, mtime, ctime, crtime] if t is not None]
if times and len(times) >= 2:
    time_variance = max(times) - min(times)
    if time_variance > 86400:
        anomalies.append('high_time_variance')
```

四规则对应：时间操纵嫌疑（mtime 与簇差 >1h）、创建晚于修改（倒填）、访问早于修改、四时间戳跨度 >1 天。注意真值判断 `if mtime` 把 0 当缺失——而文件→簇方向的 has_timestamps 判定用 `is not None`（:389），两处语义刻意不同（0 在 raw 行里可能是有效值，见 :376 注释）。

## 5. 边界与已知状态（400/404/无时间戳分支）

- **匹配是双条件**：时间与目录必须同时命中（:503-509）；文件完全无时间戳时（raw 与 files 都查不到）退化为"仅目录匹配"并标注 `"无时间戳"`（:497-501）——这是唯一的降级分支。
- **错误语义**：任务不存在 404（:174、:337）；任务无 files/events 库 400（:181、:344-345）；SQL 失败统一 500 "database query failed"（:285-287、:511-513）；其余异常 500 "association query failed"。
- raw.db 缺失/ATTACH 失败是**逐路径回退**而非整体放弃：files.db 仍以 mtime/ctime 参与（:229-241），atime/crtime 置 NULL。
- 两端点都靠请求体 POST，limit 上限 1000；返回结构含 cluster_info/file_info 供前端回显匹配上下文。
- 时间戳 0 被视为有效值（:376 注释、:389 的 has_timestamps 判定用 `is not None`）——不要用真值判断时间戳存在性。
- env：无专属 env；库路径完全来自 C++ 任务元数据（output_files_db/output_raw_db/output_events_db）。

## 6. 如何验证

- `python_service/tests/unit/test_associations.py`（双向匹配、边界 300s、目录段感知、无时间戳分支）、`test_normalize_evidence_path.py`（路径规范化的底层契约）。
- 手工：`POST /api/associations/cluster-files` 用时间线某簇的 time_window/event_type → 对返回文件任取 path 再 `POST /file-clusters`，核对两个方向结果互含。
- 边界回归：构造 diff 恰为 300s 的样本，确认被严格不等式排除。

相关阅读：[Database.md](Database.md)（events/files 库的常规读端）、[LLM.md](LLM.md)（簇的 LLM 摘要写回）、[HTTPRoutes.md](../HTTPRoutes.md)。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
