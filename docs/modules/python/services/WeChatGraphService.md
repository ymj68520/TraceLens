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

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
