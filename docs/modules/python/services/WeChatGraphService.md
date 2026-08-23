# WeChatGraphService（python_service/httpserver/services/wechat_graph_service.py + wechat_graph_parts/）

> **一句话**：微信取证数据的社会网络分析——直连任务的 `<image>_android.db`（sqlite3 只读），把联系人/机主建成节点、私聊聚合成有向加权边、群聊在 1 小时窗口内成对出现者连共变边，用 networkx 算 PageRank/介数/（可选 python-louvain）社区，并提供聊天记录查询、月/周时间线与人物 ego 子图，结果按 `task_id:mtime` 缓存 30 分钟（可经 `POST /api/wechat/graph/invalidate` 失效）。

## 1. 为什么有这个模块

C++ Android 分析把微信数据规整进 `_android.db` 的五张表（wechat_messages/wechat_contacts/wechat_chatrooms/wechat_owner_info，见路由侧的表契约校验）。前端图谱页需要的是**分析产物**而不是原始行：谁最重要（中心性）、谁和谁是一伙的（社区）、什么时候活跃（时间线）、某个人的直接关系网（ego）。这些是纯内存图计算，与 Neo4j/Graphiti 的知识图谱链路完全独立——没有 LLM、没有外部依赖（networkx 缺失时优雅报错、python-louvain 缺失时回退连通分量），因此单独成服务，靠 mtime 键控缓存避免每次请求重算。

## 2. 在系统中的位置

- **谁调用它**：routes/wechat_graph_endpoints（`/api/wechat` 前缀）：`_graph.py` 的 `GET /graph`（全图+指标，:46-60）、`GET /graph/person/{username}`（ego 子图，:167-229）、`POST /graph/invalidate`（缓存失效，:231-252）与 `_data.py` 的聊天/群聊/机主/联系人/群列表端点；数据库路径由 wechat_graph_models 的 `_resolve_android_db_path` 解析（task 记录 → raw_db 推导 → legacy 命名 → glob 兜底）。
- **它调用谁**：sqlite3（直连 `_android.db`）；networkx（图构建与指标）；`community`（python-louvain，可选）。
- **它被谁依赖**：无下游服务依赖；前端 WeChat 分析页是唯一消费者。

## 3. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `async get_full_graph(task_id, db_path, include_metrics=True) -> Dict[str, Any]` | 缓存键→未命中则 to_thread 构建全图 | `GET /graph` | networkx 缺失/库缺失/缺表返回带 error 的结构 |
| `_build_and_analyze(task_id, db_path, include_metrics) -> Dict`（同步） | 开库→验表→建图→指标→metadata | get_full_graph 的线程体 | 同上 |
| `_build_graph(conn) -> nx.DiGraph` | 机主/联系人节点 + 私聊边 + 群共变边 | _build_and_analyze | wechat_messages 缺表在上游已拦截 |
| `_compute_metrics(G) -> Dict` / `_graph_to_basic(G)` | PageRank/介数/社区 或零指标快路径 | include_metrics 分支 | 指标异常兜底零向量 |
| `async get_person_graph(username, ...) / _get_ego_subgraph(...)` | ego 子图 | person 端点 | 人不存在返回空 |
| `invalidate_cache(task_id: str) -> None` | 删除 `{task_id}:` 前缀全部缓存键 | invalidate 端点 | 不抛 |
| `_queries.py`：`get_chat_history / get_owner_info / get_contacts / get_chatrooms`（to_thread + 同步实现） | 聊天/实体查询 | data 端点 | 表缺失返回空/告警 |

## 4. 核心概念与设计

**（a）Mixin 组合。** 类本体只声明继承（wechat_graph_service.py:29-35），实现按领域拆进 `wechat_graph_parts/` 四个 mixin：`_core.py`（缓存/全图入口/图构建）、`_analysis.py`（指标/社区/序列化）、`_timeline.py`（活跃时间线）、`_queries.py`（聊天历史/联系人/群查询）。实例状态只有 `self._cache` 与 `CACHE_TTL=1800`（_core.py:19、:25-28）。

**（b）mtime 键控缓存。** 键是 `f"{task_id}:{mtime}"`：

```python
# wechat_graph_parts/_core.py:30-45（节选）
def _get_cache_key(self, task_id: str, db_path: str) -> str:
    try:
        mtime = os.path.getmtime(db_path)
    except OSError:
        mtime = 0
    return f"{task_id}:{mtime}"

def _is_cache_valid(self, cache_key: str) -> bool:
    if cache_key not in self._cache:
        return False
    entry = self._cache[cache_key]
    return (time.time() - entry.get("timestamp", 0)) < self._cache_ttl
```

库文件被重新生成（C++ 重跑分析）时 mtime 变化自然失效，无需主动清理（旧键成了死条目，等实例销毁）；`invalidate_cache(task_id)` 删除所有以 `{task_id}:` 开头的键（:62-72），是 `POST /api/wechat/graph/invalidate` 的后端。构建在 `asyncio.to_thread` 里跑，避免 SQL+图计算阻塞事件循环（:102-105）。

**（c）图构建语义（_core.py:178-232）。** 节点=人（机主 is_owner=True 先入图，联系人以 remark 优先做 label）；边分两类：

```python
# 私聊：sender→receiver 聚合为有向加权边（_core.py:288-305）
SELECT sender, receiver, COUNT(*) as msg_count,
       SUM(LENGTH(COALESCE(content,''))) as total_chars,
       MIN(timestamp) as first_time, MAX(timestamp) as last_time
FROM wechat_messages
WHERE (chatroom_name IS NULL OR chatroom_name = '')
GROUP BY sender, receiver
```

单条 SQL 聚合出 weight/total_chars/first/last，sent/received 以机主视角拆分（:330-333）。**群聊共变边**（:362-466）：每个聊天室按时间排序消息，滑动窗口内成对出现的不同发送者连**双向** `edge_type="group"` 边，规范对 `(min,max)` 去重——表达"同群同期活跃"而非真实通讯：

```python
# wechat_graph_parts/_core.py:406-432（节选）
if len(messages) < 2:
    continue

# Sliding window: for each message, find other users active
# within the 1-hour window
seen_pairs = set()
for i, msg_i in enumerate(messages):
    sender_i = msg_i["sender"]
    ts_i = msg_i["timestamp"]

    for j in range(i + 1, len(messages)):
        msg_j = messages[j]
        ts_j = msg_j["timestamp"]

        # Since messages are sorted, break if beyond window
        if ts_j - ts_i > ONE_HOUR_MS:
            break

        sender_j = msg_j["sender"]
        if sender_i == sender_j:
            continue

        # Create a canonical pair key
        pair = (min(sender_i, sender_j), max(sender_i, sender_j))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
```

内层循环利用有序性在超窗即 break（O(n·w) 而非 O(n²)）；`seen_pairs` 保证每对每群只记一次，随后对 `(u,v)`/`(v,u)` 双向加 weight=1 的 group 边（:445-463）。所有 SQL 都容错 `wechat_*` 表缺失（OperationalError 只告警），但 `wechat_messages` 缺失时整个图判定为无效库（:159-164）。

**（d）指标与社区（_analysis.py）。** `_compute_metrics`（:24-100）：

```python
# wechat_graph_parts/_analysis.py:40-52（节选）
# PageRank
try:
    pagerank = nx.pagerank(G, weight="weight")
except Exception as e:
    logger.warning(f"PageRank computation failed: {e}")
    pagerank = {n: 0.0 for n in G.nodes()}

# Betweenness centrality
try:
    betweenness = nx.betweenness_centrality(G, weight="weight")
except Exception as e:
    logger.warning(f"Betweenness centrality computation failed: {e}")
    betweenness = {n: 0.0 for n in G.nodes()}
```

`nx.pagerank(G, weight="weight")` 与 `nx.betweenness_centrality` 各自 try/except 兜底为零向量（大图上 betweenness 可能很慢，`include_metrics=False` 走 `_graph_to_basic` 零指标路径，:144-186）。节点序列化带 `pagerank/betweenness/cluster`（round 到 6 位），边序列化带 weight/edge_type/total_chars/first/last/sent/received/chatroom（:63-91）。`_detect_communities`（:102-142）先转无向图，`community_louvain.best_partition(weight="weight")` 优先，ImportError/异常回退 `nx.connected_components`，最后兜底"全体一个社区"。

**（e）时间线与查询。** `_compute_timeline_sync`（_timeline.py:45-138）：毫秒时间戳转 UTC，`granularity=week` 用 ISO 周键 `YYYY-Www`、默认月键 `YYYY-MM`，每期统计 total_messages、去重 active_edges（无向对）、top 10 联系人。`_queries.py` 提供私聊/群聊历史（分页 + 时间过滤）、机主信息、联系人/群列表，同样 `to_thread` + 同步实现成对出现。

## 5. 工作流程走读：一次全图请求

`GET /api/wechat/graph?task_id=...&include_metrics=true`（_graph.py:46）→ `_resolve_android_db_path(task_id)`（信任 C++ 任务记录；files.db 若含微信表可直接用，否则 raw_db 换后缀推导，再 legacy `_files.db→_android.db` 替换并验表，最后 glob）→ `_get_service()` 取服务实例 → `get_full_graph`（_core.py:74-113）：算缓存键 → 未命中则 `to_thread(_build_and_analyze)`：开库 → 验 `wechat_messages` 表 → `_build_graph`（机主/联系人节点 + 私聊边 + 群共变边）→ `_compute_metrics` → 附 metadata（节点/边数、UTC 时间）→ 写缓存 → 返回 nodes/edges/communities/metadata。

## 6. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| CppBackendService | 任务记录（android 库定位的信任源） |
| networkx / python-louvain | 图算法；均为可选依赖，缺失降级 |
| routes/wechat_graph_endpoints + wechat_graph_models | 全部 HTTP 面、路径解析、响应模型 |
| GraphitiService | 无直接耦合：本服务是进程内图计算，不入 Neo4j |

## 7. 注意事项与已知问题

- **缓存实际不生效**：路由侧 `_get_service()` 每次请求 `WeChatGraphService()` 新实例（wechat_graph_models.py:255-258），实例级 `_cache` 生命周期=单请求，30 分钟 TTL 与 `POST /graph/invalidate`（对新实例调用 `invalidate_cache`）都是 no-op。要恢复缓存语义，应把服务提升为模块级单例（参考 office_service 的 `get_office_service` 模式）——目前的行为是"每次全量重算"，正确但慢。
- `betweenness_centrality` 是 O(VE) 级：万人级图请让前端默认 `include_metrics=false`。
- 群共变边基于"1 小时窗口内都发过言"，不是消息级交互证据；报告中引用时注意措辞。
- `_resolve_android_db_path` 的 glob 兜底（`**/{task_id}*_android.db`）在大目录树上可能慢，且理论上可命中工作区外文件——新增任务布局时应优先扩展信任记录路径而不是 glob。
- 时间线把 `receiver` 也计入 top_contacts（发送+接收合并计数），机主通常会霸榜，解读时注意。
- 读并发：sqlite3 直连默认同进程串行，`to_thread` 并发请求各开各的连接（只读），无锁问题；同一任务的并发构建可能重复计算（缓存不生效的放大效应）。

## 8. 如何验证（python_service/tests/unit/）

- `test_wechat_dataset.py`（测试库上的图构建/聚合正确性）、`test_wechat_graph_routes.py`（路由契约：404/缓存失效端点/ego 子图形状）。
- 手工链路：`GET /api/wechat/graph?task_id=`（看 nodes/edges/communities）→ `GET /api/wechat/graph/person/{username}` → `GET /api/wechat/data/chat?...` → `GET /api/wechat/timeline?granularity=week` → `POST /api/wechat/graph/invalidate`。

## 9. 二轮深化 A：方法全清单（四 mixin，11 个公开方法）

| 方法 | mixin:行 | 签名要点 |
|---|---|---|
| get_full_graph | _core:74 | `(task_id, db_path, include_metrics=True) -> Dict`（缓存+to_thread） |
| invalidate_cache | _core:62 | `(task_id)` 删 `{task_id}:` 前缀键 |
| compute_timeline | _timeline:24 | `(task_id, db_path, granularity="month") -> Dict` |
| get_chat_history | _queries:24 | `(db_path, owner_username, contact_username, page, page_size, start/end?)` |
| get_group_chat_history | _queries:139 | `(db_path, chatroom_name, page, page_size, ...)` |
| get_owner_info | _queries:236 | `(db_path) -> Dict` |
| get_contacts_list | _queries:263 | `(db_path, include_chatrooms=False)` |
| get_chatrooms_list | _queries:332 | `(db_path) -> Dict` |
| （内部）_build_and_analyze/_build_graph/_compute_metrics/_graph_to_basic/_detect_communities/_get_ego_subgraph | _core/_analysis | 同步实现，全部经 to_thread |

## 10. 二轮深化 B：SQL 读取面汇总（表 × 列 × 方法）

| 表 | 读取列 | 读取方法 |
|---|---|---|
| wechat_messages | sender、receiver、content（LENGTH 聚合）、timestamp（MIN/MAX）、chatroom_name（NULL/空=私聊过滤） | _build_graph 私聊边聚合、get_chat_history、get_group_chat_history、compute_timeline |
| wechat_messages | id、media_url、media_type、msg_type、is_send、sender_nickname、talker | get_chat_history/get_group_chat_history 的行直读 |
| wechat_contacts | username、nickname、remark（label 优先级：remark>nickname） | _build_graph 节点、get_contacts_list |
| wechat_chatrooms | chatroomname/成员 | get_chatrooms_list、include_chatrooms 并入联系人 |
| wechat_owner_info | username、nickname、uin、imei | get_owner_info、_build_graph 机主节点、owner 自动探测 |

全部查询带 `is_send/chatroom_name` 等业务过滤但**没有 LIMIT 上限保护**（除分页端点）——群共变边的全量加载（:362-466 按聊天室逐个 ORDER BY timestamp）在百万消息库上是主要内存风险点。

## 11. 二轮深化 C：节点/边序列化字段契约（_analysis.py:63-91）

**node**：id（username）、label（remark 优先）、is_owner、message_count（收发合计）、pagerank、betweenness、cluster（社区 id，round 6 位浮点仅中心性）。
**edge（私聊，edge_type="chat"）**：source、target、weight（msg_count）、total_chars、first_time、last_time、sent_count/received_count（机主视角拆分）、chatroom（私聊边为 None）。
**edge（群共变，edge_type="group"）**：双向两条、weight=1、chatroom=群名——不携带 total_chars/时间窗信息（窗口只是建边条件，不进边属性）。
前端 force-graph 直接消费这组字段；community 端点在 node.cluster 之上再展开成员明细。

## 12. 二轮深化 D：新走读——群共变边的窗口参数与复杂度（_core.py:362-466）

```python
# _core.py:406-432 的关键常量与循环结构
ONE_HOUR_MS = 3_600_000          # 窗口硬编码
for i, msg_i in enumerate(messages):        # messages 已按 timestamp 排序
    for j in range(i + 1, len(messages)):
        if ts_j - ts_i > ONE_HOUR_MS:
            break                            # 有序性保证可提前断
        if sender_i == sender_j:
            continue
        pair = (min(sender_i, sender_j), max(sender_i, sender_j))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
```

逐块解释：① 窗口 1 小时是**硬编码常量**（不可配置）——改窗口要改代码；② 内层 break 依赖"messages 已排序"的前置（每个聊天室的查询带 ORDER BY），复杂度 O(n·w)（w=窗口内平均消息数）；③ `seen_pairs` 是**每群一套**（外层循环每个 chatroom 重置），同一对用户在不同群共变会得到多条 group 边（chatroom 字段区分）；④ 双向加边发生在循环外（:445-463 对 `(u,v)`/`(v,u)` 各加一条 weight=1）。语义边界重申：这是"同期活跃"共现证据，两用户可能从未互发消息。

## 13. 二轮深化 E：资源与复杂度参数表

| 参数 | 值 | 位置 | 说明 |
|---|---|---|---|
| CACHE_TTL | 1800s | _core:19 | 实例级（第 7 节已证不生效） |
| 群共变窗口 | 1h（硬编码） | _core:362 附近 | 不可配 |
| betweenness | O(VE) | networkx | include_metrics=false 可跳过 |
| timeline top_contacts | 前 10 | _timeline | receiver 也计数（机主霸榜风险） |
| 时间线周期键 | `YYYY-Www`（ISO 周）/ `YYYY-MM` | _timeline:94-99 | 跨年周正确（isocalendar） |

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
