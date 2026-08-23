# Associations 路由（python_service/httpserver/routes/associations.py，前缀 /api/associations）

> **一句话**：事件簇与文件的**双向时间关联**端点——给一个事件簇找出 ±5 分钟内、同目录下的相关文件（含四时间戳异常检测），或给一个文件找出时间+目录双匹配的事件簇，供 /analysis-center 页的证据抽屉使用。

## 1. 这组路由承担什么职责（为什么存在）

时间线把文件系统事件聚成簇（`(timestamp/60, event_type)`），但簇本身不含完整文件元数据；反之文件详情页需要回答"这个文件牵涉哪些事件簇"。这组路由补上双向桥：`POST /cluster-files` 与 `POST /file-clusters`。关联语义被刻意做严：时间上严格 ±300 秒、目录上**段感知**（segment-aware）包含，匹配必须同时满足时间与目录（B2/B4），避免把整盘同秒文件都算进来。四时间戳（atime/mtime/ctime/crtime）优先取自 `_raw.db`，`_files.db` 只有 mtime/ctime（associations.py:9-11 的注释写明这一分工）。

## 2. 典型调用方（前端哪个页面/组件）

前端 `/analysis-center` 页的证据抽屉：web/src/pages/AnalysisCenter.jsx:16-22 引 `getClusterRelatedFiles`、`getFileRelatedClusters` 及异常展示 helper（formatAnomalyType/getAnomalySeverity/getAnomalyColorClass），服务封装在 web/src/services/associationService.js（`/cluster-files` :28、`/file-clusters` :58）。服务端无其他调用方。

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 13 节。只有两个端点，方向相反：

- **簇 → 文件**：`POST /cluster-files`（:150）。入参给簇的 `time_window`（分钟窗，簇时间戳 = time_window×60，:185-190）+ event_type + parent_directory；返回按最小时间差升序的文件列表，每条带四时间戳差值、人类可读差值字符串（format_time_diff，:135-145）与异常标记。
- **文件 → 簇**：`POST /file-clusters`（:313）。入参 file_path；先从 raw.db/files.db 取该文件四时间戳（raw 优先、逐文件回退 files.db，:354-386），再从 events.db 用 CTE 完整建簇后过滤；每簇带 representative_timestamp、目录样本、matched_time/time_diff。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

全部只读。任务元数据经 `service_manager.cpp_backend.get_task` 拿 `output_files_db`/`output_raw_db`/`output_events_db`（:172-178、:335-343），任务不存在 404、无对应库 400。簇→文件方向的核心查询把 raw.db ATTACH 进 files.db 做**逐路径回退**的联合候选（:210-241）：

```python
# associations.py:222-228（节选）——四个时间戳任一命中 ±300s 即候选
WHERE (f.mtime IS NOT NULL AND f.mtime > ? AND f.mtime < ?)
   OR (f.ctime IS NOT NULL AND f.ctime > ? AND f.ctime < ?)
   OR (r.atime IS NOT NULL AND r.atime > ? AND r.atime < ?)
   OR (r.crtime IS NOT NULL AND r.crtime > ? AND r.crtime < ?)
```

SQL 只是候选粗筛；**最终裁决在 Python**——严格不等式保住 `abs(diff) < 300` 的边界语义（注释 :192-194 明说不用 BETWEEN，那会悄悄变成 ≤300），裁决点在 :271。目录谓词 `is_path_under_directory`（:76-86）先经 `normalize_evidence_path` 规范化再做段感知包含（`/case/a` 不匹配 `/case/abc`），空或 `/` 视为无约束。

文件→簇方向的关键是 B5b 的 CTE（:413-435）：**先完整建簇再按文件时间窗过滤**，不预截断事件行（否则 cluster_start/end/count 全会失真），簇的目录集合也从**全量**事件路径推导、响应只展示 5 个样本（:445-461 注释与实现）。异常检测 `detect_time_anomaly`（:89-132）四规则：mtime 与簇时差 >1h、crtime>mtime、atime<mtime、四时间戳跨度 >1 天。

## 5. 边界与已知状态（400/404/无时间戳分支）

- **匹配是双条件**：时间与目录必须同时命中（:503-509）；文件完全无时间戳时（raw 与 files 都查不到）退化为"仅目录匹配"并标注 `"无时间戳"`（:497-501）——这是唯一的降级分支。
- **错误语义**：任务不存在 404（:174、:337）；任务无 files/events 库 400（:181、:344-345）；SQL 失败统一 500 "database query failed"（:285-287、:511-513）；其余异常 500 "association query failed"。
- raw.db 缺失/ATTACH 失败是**逐路径回退**而非整体放弃：files.db 仍以 mtime/ctime 参与（:229-241），atime/crtime 置 NULL。
- 两端点都靠请求体 POST（模型见 :31-45），limit 上限 1000；返回结构含 cluster_info/file_info 供前端回显匹配上下文。
- 时间戳 0 被视为有效值（:376 注释、:389 的 has_timestamps 判定用 `is not None`）——不要用真值判断时间戳存在性。

## 6. 如何验证

- `python_service/tests/unit/test_associations.py`（双向匹配、边界 300s、目录段感知、无时间戳分支）、`test_normalize_evidence_path.py`（路径规范化的底层契约）。
- 手工：`POST /api/associations/cluster-files` 用时间线某簇的 time_window/event_type → 对返回文件任取 path 再 `POST /file-clusters`，核对两个方向结果互含。
- 边界回归：构造 diff 恰为 300s 的样本，确认被严格不等式排除。

相关阅读：[Database.md](Database.md)（events/files 库的常规读端）、[LLM.md](LLM.md)（簇的 LLM 摘要写回）、[HTTPRoutes.md](../HTTPRoutes.md)。

**最后更新**: 2026-08-23（新建，解释式）
