# WechatGraph 路由（python_service/httpserver/routes/wechat_graph.py + wechat_graph_endpoints/，前缀 /api/wechat）

> **一句话**：微信取证分析读端——从任务产物 `<image>_android.db` 构建联系人关系图（networkx 指标 + 可选 Louvain 社区发现）、时间线滑块数据、人物 ego 网络与聊天记录/机主/联系人查询，供前端 /wechat-graph 页使用。

## 1. 这组路由承担什么职责（为什么存在）

C++ 的 Android 分析把微信数据规范化进 `<image>_android.db`（wechat_contacts/wechat_messages/wechat_chatrooms/wechat_owner_info 四表）。这组路由在其上做**图分析读端**：wechat_graph.py 是聚合器（include `_graph.py` 与 `_data.py`，wechat_graph.py:32-34），模型与共享 helper 在 wechat_graph_models.py。全部端点只读；唯一的"写"语义是缓存失效请求（POST /graph/invalidate），不碰源库。

## 2. 典型调用方（前端哪个页面/组件）

前端 `/wechat-graph` 页（web/src/routes.jsx:69-72 → `pages/WeChatGraph/WeChatGraph.jsx`），全部经 **web/src/services/wechatService.js**：`/graph` :12、`/graph/timeline` :21、`/graph/community` :29、`/graph/person/{username}` :38、`/chat` :50、`/chat/group` :63、`/owner` :73、`/contacts` :81、`/graph/invalidate` :89。服务端无其他调用方。

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 12 节。分组：

- **图族（_graph.py）**：`GET /graph`（:29）——节点（联系人 + 分析属性）、边（消息流）、社区簇三合一，`include_metrics` 控制 PageRank/中介中心性；`GET /graph/timeline`（:67）——按月或周聚合的消息活动（时间线滑块数据源），interval 只接受 month/week 否则 400（:84-85）；`GET /graph/community`（:106）——在 /graph 结果上再展开每个社区的成员明细与消息量合计；`GET /graph/person/{username}`（:167）——单人 ego 网络（节点属性 + 全部直连边）；`POST /graph/invalidate`（:231）——请求清缓存。
- **数据族（_data.py）**：`GET /chat`（:27，私聊双方分页，offset/limit 内部换算 page/page_size）、`GET /chat/group`（:80，群聊分页）、`GET /owner`（:131，机主 username/nickname/UIN/IMEI）、`GET /contacts`（:164，可选含群聊条目）。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

**第一步永远是解析 android.db 路径**（wechat_graph_models.py:137-251 的 `_resolve_android_db_path`）：任务 metadata 的 `android_db` → files.db 同目录 `android.db` 或 files.db 本身（必须通过"WeChat 表契约"验证——候选 SQLite 里出现四张规范表之一才接受，防止把跨平台 files.db 误当微信库，:169-189）→ 从 `output_raw_db` 派生 `*_android.db` → legacy `_files.db→_android.db` 换名（同样过表契约，:216-233）→ 兜底 glob 搜索（:236-245）→ 全部失败 404 "Ensure the task has completed Android analysis"。

图构建在 WeChatGraphService（mixin 组合，services/wechat_graph_service.py:29；实现分体在 services/wechat_graph_parts/）：机主 `wechat_owner_info`（_core.py:238）、联系人 `wechat_contacts`（:257-258）、边由 `wechat_messages` 聚合（:290-297）；指标与社区在 _analysis.py——PageRank `nx.pagerank(G, weight="weight")`（:42）、中介中心性（:49）、社区发现优先 python-louvain（:120-121），未安装或失败降级为连通分量（:129-141）：

```python
# services/wechat_graph_parts/_analysis.py:129-137（节选）
except (ImportError, Exception):
    logger.warning("python-louvain not installed. Falling back to "
                   "connected components.")
    components = nx.connected_components(G_undirected)
```

时间线在 _timeline.py：同步聚合放线程（:36-38），周期键为 ISO 周 `YYYY-Www` 或月 `YYYY-MM`（:94-99）。构建/查询全程 `asyncio.to_thread`，不阻塞事件循环。

## 5. 边界与已知状态（404/降级/缓存局限）

- **服务层缓存是实例级，而路由每请求新建实例**：`_get_service()` 每次 `WeChatGraphService()`（wechat_graph_models.py:254-257），`CACHE_TTL = 1800`（30 分钟，_core.py:19）的缓存只活在单次请求内，不跨请求生效；因此 `POST /graph/invalidate` 清的是新实例的空缓存，对其他请求无实际影响。当前行为上等于"每次请求都从 android.db 重建"——性能靠 db 体量小兜底，改缓存语义需要把服务实例提升为进程级单例。
- **社区发现降级**：python-louvain 缺失时返回连通分量（社区粒度变粗但可用）；全失败时所有节点归一个社区（_analysis.py:141）。
- **图端点的部分容错**：`/graph` 与 `/graph/community`、`/graph/person` 只在"有 error 且无 nodes"时才 404（_graph.py:50-51）——退化数据（空图）仍返回 200，前端按 nodes 空处理。
- 私聊/群聊历史若服务返回 error dict 则 404（_data.py:62-63 等），其余异常统一 500 且 detail 固定短句（如 "wechat chat history is unavailable"，:79）。
- 全组只读源库；没有任何端点写 android.db。

## 6. 如何验证

- `python_service/tests/unit/test_wechat_graph_routes.py`（端点契约、db 解析回退链、降级路径）、`test_wechat_dataset.py`（图数据集语义）。
- 手工：先跑完一个 Android 任务的微信分析 → `curl ':8090/api/wechat/graph?task_id=...'` → `curl '.../graph/timeline?interval=week'` → 取 username 调 `/graph/person/{username}` 核对 ego 边。
- 验证缓存局限：连续两次 `/graph`，观察服务日志每次都打 "Building graph ... from"（而非 "Returning cached graph"）。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[Database.md](Database.md)（android.db 之外的取证库读端）。

**最后更新**: 2026-08-23（新建，解释式）
