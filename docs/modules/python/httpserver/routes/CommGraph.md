# CommGraph 路由（python_service/httpserver/routes/comm_graph.py，前缀 /api/comm）

> **一句话**：统一通讯图谱的四端点只读面——把一份检材的 android.db（通话/短信/联系人）与任意若干微信/QQ 导入的 graph.db 在**读侧联合投影**成一张"谁和谁通过什么方式联系"的图，外加统一时间线、单边记录钻取与数据集清单；不合并、不回写任何源库。

## 1. 这组路由承担什么职责（为什么存在）

系统的三份通讯数据从来不会自己相遇：一个任务写 `android.db`，一个微信导入和一份 QQ 导入各写自己的 `graph.db`（comm_graph/__init__.py:1-8）。关系图谱页（`/api/wechat/graph`）一次只能吃其中一份，而办案问题恰恰是跨源的："机主和 X 的全部联系渠道有哪些？微信上聊得多还是短信发得多？"comm_graph.py 用一次请求回答它：所有可解析来源各自读出（calls/sms/messages/contacts/chatrooms），身份归一后（手机号/wxid/QQ uin 强键）聚合成一张 UnifiedGraph，每条边保留来源 dataset 与 record_refs 以便回溯原始行。四个端点全部是 GET（comm_graph.py:3），对应"建图、按时间切、看单边证据、列数据源"四个问题。

设计红线写在包 docstring（comm_graph/__init__.py:10-14）：只读；身份合并只认强键（同名绝不自动合并）；每条边可回指原始记录。挂载于 main.py:356（`/api/comm`）。

## 2. 典型调用方（前端哪个页面/组件）

- `/knowledge-graph` 页的通讯图谱视图：`web/src/components/knowledge-graph/CommGraphPanel.jsx`（及 CommunicationGraphEntry 入口），数据经 `web/src/services/commGraphService.js`——`getCommGraph`（:18-30）、`getCommTimeline`（:36-45）、`getCommEdgeDetail`（:49-55）、`getCommDatasets`（:59-63）。
- `/timeline` 页的通讯时间线 Tab：`components/timeline/CommTimelinePanel.jsx`（消费 getCommTimeline/getCommEdgeDetail）。
- 服务间：无下游——本组路由是这条管线的最上游入口。

## 3. 核心数据结构

**DatasetRef**（services/comm_graph/models.py）：一次请求解析出的数据源引用 `{dataset_id, kind, id, label}`——kind 取 `task_android` / `wechat_import` / `qq_import`。解析规则（datasets.py:1-9 docstring）：导入与任务还没有链接关系，所以**必须显式点名**——`wechat_imports`/`qq_imports` 重复 query 参数；`dataset=wx_<id>` / `qq_<id>` 是保持既有 UI 词表的简写（comm_graph.py:10-13），由 `_split_dataset_tokens`（:35-52）按前缀拆回两列。

**GraphFilters**（:95-99 的构造）：start_time/end_time（秒）、min_edge_weight（1..1e6）、include_union（默认 True）、max_nodes（1..2000）、max_edges（1..10000）、communities（默认 True，社区检测开关）、datasets（显式数据集 token）。

**UnifiedGraph**：节点（Person，含归一化身份与 name_candidates）+ 边（Edge：source/target/relation/weight/duration_seconds/media_count/direction/first_time/last_time/record_refs/dataset）+ coverage 计数（service.py:50-55 的 `_COVERAGE_KEYS`：datasets_total/readable/unavailable、messages_read/calls_read/sms_read/contacts_read/artifacts_read、truncated_sources、merged_identities、name_candidates、orphan_records、owner_unknown_datasets）——每次响应都自带"读了多少、合并了多少、丢了多少"，让图的可信度可审计。

relation 词表两处独立校验且一致：timeline 的 `kind ∈ {call, sms, im_private, im_group, im_artifact}`（:121），edge 的 `relation` 额外允许 `group_member`（:157-158）。

## 4. 端点语义分组（散文）

- `GET /api/comm/graph`（:69-105）：主端点。时间窗逆序 422（:83-84，中文 detail）；`_resolve` 得到 refs+unavailable 后 `build_graph`（to_thread）；`include_union=True` 时跨数据集的同端点对同关系边**折叠合并**（_merge_edges，service.py:108-139：weight/时长/媒体数累加、record_refs 上限截断计数、时间跨度取并集、方向冲突升级 `mixed`、dataset 标记 `union`）。响应 `{success, task_id, **graph.model_dump()}`（:105）。
- `GET /api/comm/timeline`（:108-144）：同一来源集的时间线聚合（build_timeline，services/comm_graph/timeline.py），kind 白名单校验（未知 kind 422，:122-126），limit 1..500 默认 200；响应附 `coverage.unavailable_datasets`（:143）——时间线不隐瞒"哪些数据集没读成"。
- `GET /api/comm/edge`（:147-172）：单边钻取——`source`/`target`/`relation` 定位后返回支撑这条边的原始记录（edge_detail），是"图上这条线有什么证据"的回答。
- `GET /api/comm/datasets`（:175-196）：列出本次会解析到哪些数据集（含不可用清单），前端用它先渲染数据源选择再发图请求。

## 5. 数据流（读什么库、写什么）

**写**：无。**读**：`_connect`（service.py:76-82）以 `mode=ro&query_only=ON` 打开每个数据集，`text_factory` 对坏字节做 replace 解码（证据库不因编码问题整图失败）；每个 reader（sources.py 的 read_call_logs/read_sms/read_wechat_messages/...）都被 `_guarded`（:85-89）包住——单库 sqlite3.DatabaseError 只贡献空列表与 unavailable 记录，不炸整图。

解析链（comm_graph.py:60-66 → service.py:64-68 → datasets.py）：`resolve` 先经 C++ `get_task` 验 task 身份（不存在 → LookupError → 路由 404 "task not found"，:90-91）；`resolve_datasets` 对每个导入 id 做 12-hex 强校验（坏格式 → DatasetResolutionError → 422，:92-93）、调各自 `ensure_graph_db`（导入库缺失/陈旧时自愈重建）；task 侧经 `resolve_android_db` 定位 android.db。全部数据集都解析失败（refs 与 unavailable 双空）→ 404"该任务没有可读的通讯数据源（无 android.db）"（:63-65）——注意这条 404 只在"连一个可尝试的来源都没有"时触发，"有来源但读挂了"会以 unavailable 出现在正常 200 响应里。

## 6. 边界与已知状态（错误码/降级）

- **422 语义**：时间窗逆序（:83-84、:119-120）、未知 kind/relation（:122-126、:158-160）、DatasetResolutionError（坏导入 id，:92-93）——全部中文 detail，面向面板直接展示。
- **404 语义**：task 不存在（"task not found"）与"无可读数据源"（中文长句）两种，前者来自 LookupError、后者来自 `_resolve` 的双空判断。
- **无数据集的部分失败是 200**：unavailable 列表 + coverage 计数是本组路由对降级的显式表达；前端据 `unavailable` 渲染提示而不是报错。
- **record_refs 截断**：每边最多 MAX_RECORD_REFS_PER_EDGE 条引用（identity.py），超出只增 `truncated_refs` 计数——图不会因单边证据太多而膨胀。
- 无 env 开关、无持久化；communities 依赖社区检测（服务层内建），关掉即纯聚合。

## 7. 如何验证

- 前端契约：`web/src/services/commGraphService.js`（params 拼装）、`components/knowledge-graph/CommGraphPanel.test.jsx`、`components/timeline/CommTimelinePanel.test.jsx`。
- 服务层：`python_service/tests/unit/` 下 comm_graph 测试（resolve/identity/merge/timeline）。
- 活体验证：`/knowledge-graph` 页通讯图谱视图——选一个含 android.db 的任务 + 勾选微信/QQ 导入，确认 coverage.unavailable_datasets 与 merged_identities 数字合理；点一条 union 边钻取，record_refs 应含多数据集来源。

相关阅读：[IMForensics.md](IMForensics.md)（微信/QQ 导入的产生方）、[WechatGraph.md](WechatGraph.md)（单源关系图谱）、services 侧 [CommGraphService.md](../../services/CommGraphService.md)（身份归一与合并算法）。

## 8. 二轮深化 A：`_in_range` 的"无日期不可证在窗内"原则

```python
# services/comm_graph/service.py:92-105（节选）
def _in_range(edge: Edge, start: int | None, end: int | None) -> bool:
    if start is None and end is None:
        return True
    if edge.first_time is None and edge.last_time is None:
        # Undated records cannot be proven to fall inside a requested range.
        return False
    low = edge.first_time if edge.first_time is not None else edge.last_time
    high = edge.last_time if edge.last_time is not None else edge.first_time
    ...
```

逐块解释：不加时间窗时一切通过；**一旦加了窗，无日期的记录一律出局**——注释写明理由"无法证明落在窗内"。这是取证取向（fail-closed）：一条没有时间戳的联系记录在时间过滤视图中消失，比错误地出现在窗内更安全。半边日期（只有 first 或 last）用另一端补齐 low/high 后做区间重叠判断，即"已知边界与窗有交集即保留"。这条规则与 TimelineSummary 的 quality 语义（missing/invalid 单独计数、不混入 valid）是同一纪律的两个实现。

## 9. 二轮深化 B：数据集词表的三个入口

同一份 `DatasetRef` 列表有三个来源入口，语义不同：

| 入口 | 参数 | 语义 | 失败行为 |
|---|---|---|---|
| 任务 | `task_id`（必填） | 该任务的 android.db | 不存在 → 404 |
| 显式导入 | `wechat_imports`/`qq_imports`（重复参数） | 点名合并的导入账号 | 坏 id → 422；读不了 → unavailable |
| 简写 | `dataset=wx_<id>` / `qq_<id>` | UI 词表兼容，拆解后并入上两列 | 同上 |
| 显式数据集 token | `dataset=<dataset_id>` | 按 dataset_id 过滤（进 GraphFilters.datasets） | 未知 id 归入 unavailable |

`_split_dataset_tokens`（comm_graph.py:35-52）是简写与显式 token 的分拣器：按 `wx_`/`qq_` 前缀分流、去重（`dict.fromkeys`，:86-87）保持顺序。导入不自动跟随任务（datasets.py:3-9："Guessing would risk pulling in an unrelated account"）是刻意的——合并别人的微信账号是取证事故。

**最后更新**: 2026-11-10（新建：统一通讯图谱路由文档）
