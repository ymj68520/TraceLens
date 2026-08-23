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

## 3.5 核心数据结构与查询

图族响应以 `GraphResponse`（wechat_graph_models.py）承载 `{success, task_id, nodes[], edges[], communities[], metadata, timestamp}`；节点字段（id/label/is_owner/message_count/pagerank/betweenness/cluster，_analysis.py 组装段）与边字段（source/target/weight/edge_type/total_chars/first_time/last_time/sent_count/received_count/chatroom）即前端 force-graph 的直接输入。数据族的私聊查询是典型的双向分页 SQL（services/wechat_graph_parts/_queries.py:73-106）：

```python
# _queries.py:73-106（节选）
# Count total messages
count_cursor = conn.execute(
    """
    SELECT COUNT(*) as total
    FROM wechat_messages
    WHERE (chatroom_name IS NULL OR chatroom_name = '')
      AND (
        (sender = ? AND receiver = ?)
        OR (sender = ? AND receiver = ?)
      )
    """,
    (owner_username, contact_username, contact_username, owner_username),
)
total = count_cursor.fetchone()["total"]

# Fetch page
offset = (page - 1) * page_size
cursor = conn.execute(
    """
    SELECT id, sender, receiver, content, timestamp,
           media_url, media_type, msg_type, is_send,
           chatroom_name, sender_nickname, talker
    FROM wechat_messages
    WHERE (chatroom_name IS NULL OR chatroom_name = '')
      AND ((sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?))
    ORDER BY timestamp ASC
    LIMIT ? OFFSET ?
    """,
    (owner_username, contact_username,
     contact_username, owner_username,
     page_size, offset),
)
```

双向 OR 谓词保证"我发给 TA"与"TA 发给我"都命中同一会话；owner_username 为空时先从 `wechat_owner_info` 自动探测（:68-70）。计数与取页是两条语句——大库上 COUNT 是全表扫描，靠 to_thread 不阻塞事件循环。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

**第一步永远是解析 android.db 路径**（wechat_graph_models.py:137-251 的 `_resolve_android_db_path`）。回退链的第二档有"WeChat 表契约"把关——候选 SQLite 里出现四张规范表之一才接受，防止把跨平台 files.db 误当微信库：

```python
# wechat_graph_models.py:169-189（节选）
# Some Android analysis outputs are stored directly in output_files_db,
# rather than in a separately named *_android.db artifact.  Only accept
# a SQLite database that contains at least one normalized WeChat table;
# files.db may otherwise be an unrelated cross-platform artifact DB.
files_db = task_info.get("output_files_db") or ""
if files_db:
    sibling_android = os.path.join(os.path.dirname(files_db), "android.db")
    for candidate in (sibling_android, files_db):
        if not candidate or not os.path.exists(candidate):
            continue
        try:
            import sqlite3
            with sqlite3.connect(candidate) as connection:
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            if tables.intersection({
                "wechat_messages", "wechat_contacts",
                "wechat_chatrooms", "wechat_owner_info",
            }):
                return candidate
        except sqlite3.Error:
            continue
```

完整顺序：任务 metadata 的 `android_db` → files.db 同目录 `android.db` 或 files.db 本身（须过表契约）→ 从 `output_raw_db` 派生 `*_android.db` → legacy `_files.db→_android.db` 换名（同样过表契约，:216-233）→ 兜底 glob 搜索（:236-245）→ 全部失败 404 "Ensure the task has completed Android analysis"。

图构建在 WeChatGraphService（mixin 组合，services/wechat_graph_service.py:29；实现分体在 services/wechat_graph_parts/）：机主 `wechat_owner_info`（_core.py:238）、联系人 `wechat_contacts`（:257-258）、边由 `wechat_messages` 聚合（:290-297）：

```python
# services/wechat_graph_parts/_core.py:290-304（私聊边聚合 SQL）
                SELECT
                    receiver,
                    COUNT(*) as msg_count,
                    SUM(LENGTH(COALESCE(content, ''))) as total_chars,
                    MIN(timestamp) as first_time,
                    MAX(timestamp) as last_time
                FROM wechat_messages
                WHERE (chatroom_name IS NULL OR chatroom_name = '')
                  AND sender IS NOT NULL
                  AND receiver IS NOT NULL
                  AND sender != ''
                  AND receiver != ''
                GROUP BY sender, receiver
```

即边不是逐条消息而是 `(sender, receiver)` 聚合：msg_count/total_chars/first_time/last_time 作为边属性，消息计数累加到节点（:326-327）。指标与社区在 _analysis.py——PageRank `nx.pagerank(G, weight="weight")`（:42）、中介中心性（:49）都各自 try/except 失败置 0 向量；社区发现优先 python-louvain（:120-121），未安装或失败降级为连通分量（:129-141）：

```python
# services/wechat_graph_parts/_analysis.py:129-137（节选）
except (ImportError, Exception):
    logger.warning("python-louvain not installed. Falling back to "
                   "connected components.")
    components = nx.connected_components(G_undirected)
```

时间线在 _timeline.py：同步聚合放线程（:36-39），周期键为 ISO 周 `YYYY-Www` 或月 `YYYY-MM`（:94-99）：

```python
# services/wechat_graph_parts/_timeline.py:94-99
if granularity == "week":
    # ISO week: YYYY-Www
    period_key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
else:
    # Month: YYYY-MM
    period_key = f"{dt.year}-{dt.month:02d}"
```

构建/查询全程 `asyncio.to_thread`，不阻塞事件循环。缓存机制本体（_core.py:94-113）是标准 TTL 缓存：键 `{task_id}:{db mtime}`（:30-45，db 变更即换键）、`CACHE_TTL = 1800`（:19）、命中直接返回（:96-98）、未命中构建后写缓存（:103-111）——**机制本身是对的，问题在实例生命周期**（见第 5 节）。

## 5. 边界与已知状态（404/降级/缓存局限）

- **服务层缓存是实例级，而路由每请求新建实例**：`_get_service()` 每次 `WeChatGraphService()`（wechat_graph_models.py:254-257），`CACHE_TTL = 1800`（30 分钟，_core.py:19）的缓存只活在单次请求内，不跨请求生效；因此 `POST /graph/invalidate` 清的是新实例的空缓存，对其他请求无实际影响。当前行为上等于"每次请求都从 android.db 重建"——性能靠 db 体量小兜底，改缓存语义需要把服务实例提升为进程级单例。
- **社区发现降级**：python-louvain 缺失时返回连通分量（社区粒度变粗但可用）；全失败时所有节点归一个社区（_analysis.py:141）。
- **图端点的部分容错**：`/graph` 与 `/graph/community`、`/graph/person` 只在"有 error 且无 nodes"时才 404（_graph.py:50-51）——退化数据（空图）仍返回 200，前端按 nodes 空处理。
- 私聊/群聊历史若服务返回 error dict 则 404（_data.py:62-63 等），其余异常统一 500 且 detail 固定短句（如 "wechat chat history is unavailable"，:79）。
- 全组只读源库；没有任何端点写 android.db。
- env：无专属 env；db 解析依赖 C++ 任务元数据（android_db/output_raw_db/output_files_db 字段）。

## 6. 如何验证

- `python_service/tests/unit/test_wechat_graph_routes.py`（端点契约、db 解析回退链、降级路径）、`test_wechat_dataset.py`（图数据集语义）。
- 手工：先跑完一个 Android 任务的微信分析 → `curl ':8090/api/wechat/graph?task_id=...'` → `curl '.../graph/timeline?interval=week'` → 取 username 调 `/graph/person/{username}` 核对 ego 边。
- 验证缓存局限：连续两次 `/graph`，观察服务日志每次都打 "Building graph ... from"（而非 "Returning cached graph"）。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[Database.md](Database.md)（android.db 之外的取证库读端）。

## 7. 二轮深化 A：端点全表（9 个，含 query 参数）

| 端点 | 方法 | query 参数 | 响应要点 | 失败形态 |
|---|---|---|---|---|
| /api/wechat/graph | GET | task_id 必填、include_metrics=**true** | nodes/edges/communities/metadata | 404（error 且无 nodes）/500 str(e) |
| /api/wechat/graph/timeline | GET | task_id、interval=month（month\|week，其他 400） | 周期聚合数组 | 400/404 |
| /api/wechat/graph/community | GET | task_id | 社区明细+消息量合计 | 同 /graph |
| /api/wechat/graph/person/{username} | GET | task_id | ego 节点+直连边 | 404/500 |
| /api/wechat/graph/invalidate | POST | task_id | 清缓存（见第 5 节局限） | 200 |
| /api/wechat/chat | GET | task_id、contact_username、page=1、page_size=50 | 双向会话分页 | 404（error dict）/500 |
| /api/wechat/chat/group | GET | task_id、chatroom_name、page、page_size | 群聊分页 | 同上 |
| /api/wechat/owner | GET | task_id | username/nickname/uin/imei | 404 |
| /api/wechat/contacts | GET | task_id、include_chatrooms=false | 联系人（可含群） | 404 |

## 8. 二轮深化 B：android.db 四表读写列清单（与 [AndroidDB.md](../../../schema/AndroidDB.md) 交叉核对）

本组**只读**以下列（写侧是 C++ Android 分析，AndroidDB.md:113 指出存的是 SQLCipher 解密后内容）：

| 表（列数） | 本组读取的列 | 用途 |
|---|---|---|
| wechat_messages（13+5） | sender、receiver、content、timestamp、media_url、media_type、msg_type、is_send、chatroom_name、sender_nickname、talker、id | 边聚合（GROUP BY sender,receiver）、私聊/群聊分页、时间线 |
| wechat_contacts（8） | 全部（username、nickname 等） | 节点构建、联系人列表 |
| wechat_chatrooms（7） | 群名/成员 | include_chatrooms 时并入联系人 |
| wechat_owner_info（6） | username、nickname、uin、imei | 机主节点 + 私聊会话的 owner_username 探测（_queries.py:68-70） |

注意 `_resolve_android_db_path` 的表契约恰好以这四张表的**前三张+owner_info** 为白名单（wechat_graph_models.py:186-89），MIUI 备份系列四表（wechat_artifact_inventory 等）不在白名单——只有"解密后内容"形态的库会被当作微信库。

## 9. 二轮深化 C：新走读——/graph 的部分容错分支（_graph.py:44-64）

```python
# _graph.py:44-64（骨架）
db_path = await _resolve_android_db_path(task_id)
service = _get_service()
result = await service.get_full_graph(task_id, db_path, include_metrics=include_metrics)
if "error" in result and not result.get("nodes"):
    raise HTTPException(status_code=404, detail=result["error"])
return GraphResponse(
    success=True,
    nodes=result.get("nodes", []),
    ...
)
```

逐块解释：判定条件是 `error 且无 nodes`——服务层遇到可恢复问题（如 Louvain 缺失、指标失败）会返回带 error 字段**但同时带部分数据**的结果，此时端点返回 200；只有"连图都没建出来"才 404。注意 `success=True` 是**硬编码**的——即使 result 带 error（降级数据），响应仍报 success:true，前端无法从该字段感知降级，只能看 metadata。三档实际信号：200+success:true（含降级数据）、404（无微信数据/任务未做 Android 分析）、500（异常，detail=str(e) 是脱敏偏离点）。

## 10. 二轮深化 D：缓存与构建参数表

| 参数 | 值 | 位置 | 实效 |
|---|---|---|---|
| CACHE_TTL | 1800s（30 分钟） | _core.py:19 | 因实例每请求新建而**实际无效**（第 5 节） |
| 缓存键 | `{task_id}:{db mtime}` | _core.py:30-45 | mtime 变更即换键（防旧数据） |
| PageRank | `nx.pagerank(G, weight="weight")` | _analysis.py:42 | 失败→全 0 向量 |
| betweenness | nx.betweenness_centrality | _analysis.py:49 | 同上（大图上是主要耗时点） |
| 社区 | python-louvain → 连通分量 → 单社区 | _analysis.py:120-141 | 三级降级 |
| 线程卸载 | 全部构建/查询 asyncio.to_thread | _core/_timeline/_queries | 不阻塞事件循环 |

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
