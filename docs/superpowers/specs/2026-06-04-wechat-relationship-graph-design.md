# WeChat Relationship Graph Analysis — Design Spec

**Date**: 2026-06-04
**Status**: Approved
**Scope**: New module in AndroidAnalyzer for WeChat chat record analysis, relationship graph generation, and frontend visualization.

---

## 1. Overview

This design adds a WeChat (微信) relationship graph analysis capability to the forensic analysis pipeline. It covers:

1. **SQLCipher decryption** of EnMicroMsg.db with dual-mode password resolution
2. **Enhanced parsing** of contacts, group chats, and messages
3. **Graph analysis** using NetworkX (community detection, centrality, temporal, sentiment)
4. **REST API** served by the Python FastAPI service
5. **Frontend visualization** as an independent React page with interactive graph, timeline linkage, and chat panel

### Architecture Summary

```
C++ (AndroidAnalyzer)
  ├─ WeChatDecryptor: SQLCipher 解密（用户密码 > 自动推导）
  ├─ 增强 parseWeChat: 解析 contacts/chatroom/messages
  └─ 写入 _android.db (wechat_contacts, wechat_chatrooms, wechat_messages, wechat_owner_info)
       ↓
Python FastAPI (wechat_graph_service)
  ├─ 读取 _android.db → 构建 NetworkX 有向加权图
  ├─ 算法: Louvain社区 + PageRank + Betweenness + 时间切片 + 情感分析
  ├─ 缓存: 按 task_id, TTL=30min, mtime 失效
  └─ REST API: /api/wechat/graph, /api/wechat/chat, ...
       ↓
React 前端 (/wechat-graph)
  ├─ ForceGraph2D: 节点=人物, 边=关系(粗细=权重, 颜色=社区)
  ├─ 时间线联动: Recharts 面积图 + 拖拽选择
  └─ 侧边面板: 聊天气泡样式聊天记录 + 人物详情
```

---

## 2. C++ Parsing Layer

### 2.1 SQLCipher Decryption

**New file**: `src/analyzers/AndroidAnalyzer/WeChatDecryptor.h/.cpp`

**Password resolution** (priority order):
1. User-provided password via `--wechat-password <7-char-hex>` CLI argument
2. Auto-derivation from device files:
   - IMEI: from `data/data/com.tencent.mm/shared_prefs/` config files
   - UIN: from `shared_prefs/auth_info_key_prefs.xml` or `system_config_prefs.xml`
   - Formula: `MD5(IMEI + UIN).substring(0, 7)`

**SQLCipher compatibility**:
- Try SQLCipher 4.x defaults first (64000 KDF iterations, SHA512 HMAC)
- Fall back to SQLCipher 2.x defaults (4000 KDF iterations, SHA1 HMAC)
- Page size: 4096 bytes

**New CLI arguments**:
```
--wechat-password <7-char-hex>   Manually specify decryption password (highest priority)
--wechat-auto-decrypt            Enable auto-derivation (default: on, skipped if password provided)
```

**Dependency**: `libsqlcipher-dev` — to be added to CMakeLists.txt.

### 2.2 Enhanced Parser

**Modified file**: `src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp`

New/modified functions:
- `parseWeChatContacts(db)` — reads `rcontact` table, returns `username → {nickname, remark}` map
- `parseWeChatChatrooms(db)` — reads `chatroom` table, returns group membership data
- `parseWeChatMessages(db, contacts, chatrooms, ownerUsername)` — enhanced message parsing:
  - Private chats: `talker` = other party; `isSend=1` means device owner sent
  - Group chats: `talker` containing `@chatroom` suffix; sender extracted from message XML header
  - Message `type` field decoded: 1=text, 3=image, 34=voice, 43=video, 47=emoji, 49=link, 10000=system
- `identifyWeChatOwner(db)` — extracts device owner username from `userinfo` table or `shared_prefs`

### 2.3 New Data Structures

**Modified file**: `src/analyzers/AndroidAnalyzer/AndroidDataTypes.h`

```cpp
struct WeChatContact {
    std::string username;
    std::string nickname;
    std::string remark;
    std::string avatarPath;
    int type;
    bool isChatroom;
};

struct WeChatChatroom {
    std::string chatroomName;
    std::string owner;
    std::vector<std::string> members;
    int memberCount;
    int64_t createTime;
};

struct WeChatOwnerInfo {
    std::string username;
    std::string nickname;
    int uin;
    std::string imei;
};
```

### 2.4 Integration Point

**Modified file**: `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp`

In `analyzeAndroidData()`, after the existing WeChat parsing block:
1. Attempt decryption via `WeChatDecryptor`
2. If successful, call enhanced parsers
3. Insert results into `_android.db`

---

## 3. Database Schema

**Modified file**: `src/core/DatabaseManager/SQL/android_analysis_sql.h`

### 3.1 New Tables

**wechat_contacts**:
```sql
CREATE TABLE IF NOT EXISTS wechat_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    nickname TEXT,
    remark TEXT,
    avatar_path TEXT,
    type INTEGER,
    chatroom_flag INTEGER DEFAULT 0
);
```

**wechat_chatrooms**:
```sql
CREATE TABLE IF NOT EXISTS wechat_chatrooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chatroom_name TEXT UNIQUE,
    owner TEXT,
    member_list TEXT,
    member_count INTEGER,
    create_time INTEGER
);
```

**wechat_owner_info**:
```sql
CREATE TABLE IF NOT EXISTS wechat_owner_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    nickname TEXT,
    uin INTEGER,
    imei TEXT
);
```

### 3.2 Enhanced wechat_messages

New columns added to existing table:
```sql
ALTER TABLE wechat_messages ADD COLUMN msg_type INTEGER DEFAULT 1;
ALTER TABLE wechat_messages ADD COLUMN is_send INTEGER DEFAULT 0;
ALTER TABLE wechat_messages ADD COLUMN chatroom_name TEXT;
ALTER TABLE wechat_messages ADD COLUMN sender_nickname TEXT;
ALTER TABLE wechat_messages ADD COLUMN talker TEXT;
```

### 3.3 New Database Methods

**Modified file**: `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h/.cpp`

- `bool insertWeChatContact(const WeChatContact& contact)`
- `bool insertWeChatChatroom(const WeChatChatroom& chatroom)`
- `bool insertWeChatOwnerInfo(const WeChatOwnerInfo& owner)`

---

## 4. Python Graph Analysis Layer

### 4.1 Module Structure

```
python_service/httpserver/
├── routes/
│   └── wechat_graph.py          # API route handlers
├── services/
│   └── wechat_graph_service.py  # Core graph computation service
```

### 4.2 Graph Construction

Read from `_android.db`, build a NetworkX `DiGraph`:

**Node attributes**:
- `id`: WeChat username
- `label`: display name (priority: remark > nickname > username)
- `is_owner`: boolean, whether this is the device owner
- `message_count`: total messages participated in

**Edge attributes** (private chat):
- `weight`: total message count between two users
- `total_chars`: total character count
- `first_time` / `last_time`: earliest/latest message timestamp
- `sent_count` / `received_count`: directional message counts

**Edge attributes** (group chat):
- Group members get pairwise edges. Edge weight = number of messages where both users are active in the same group within a 1-hour window (co-activity metric)
- `group_name`: source chatroom name
- `is_group_edge`: true
- `chatroom_name`: the chatroom identifier

### 4.3 Graph Algorithms

| Dimension | Algorithm | Output |
|-----------|-----------|--------|
| **Community Detection** | Louvain (`community.louvain_communities`) | `cluster_id` per node |
| **Key Person Identification** | PageRank + Betweenness Centrality | Ranking scores per node |
| **Temporal Analysis** | Time-sliced subgraphs (monthly/weekly) | Edge weight changes over time |
| **Sentiment Analysis** | LLM via existing OpenAI-compatible API (project's LLMIntegration module) | `sentiment_score` per edge (-1.0 to 1.0), computed per batch of messages |

### 4.4 Caching Strategy

```python
_cache = {}  # task_id → { graph_data, metrics, timestamp, db_mtime }

# Rules:
- Results cached by task_id, TTL = 30 minutes
- First request computes and caches; subsequent requests return cached
- Auto-invalidate when _android.db file mtime changes
- POST /api/wechat/graph/invalidate for forced refresh
- Cache stores serialized graph data (nodes/edges JSON), not NetworkX objects
```

### 4.5 REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/wechat/graph?task_id=xxx` | Full relationship graph (nodes + edges + communities + centrality) |
| `GET` | `/api/wechat/graph/timeline?task_id=xxx&interval=month` | Temporal data (aggregated by month/week) |
| `GET` | `/api/wechat/graph/community?task_id=xxx` | Community group details |
| `GET` | `/api/wechat/graph/person/{username}?task_id=xxx` | Single person ego network |
| `GET` | `/api/wechat/chat?task_id=xxx&user1=A&user2=B&offset=0&limit=50` | Chat history between two users (paginated) |
| `GET` | `/api/wechat/chat/group?task_id=xxx&chatroom=xxx&offset=0&limit=50` | Group chat history (paginated) |
| `GET` | `/api/wechat/owner?task_id=xxx` | Device owner info |
| `GET` | `/api/wechat/contacts?task_id=xxx` | Contact list |
| `POST` | `/api/wechat/graph/invalidate?task_id=xxx` | Force cache refresh |

### 4.6 Response Format

**GET /api/wechat/graph**:
```json
{
  "nodes": [
    {
      "id": "wxid_abc",
      "label": "张三",
      "is_owner": false,
      "message_count": 1523,
      "pagerank": 0.085,
      "betweenness": 0.12,
      "cluster": 0
    }
  ],
  "edges": [
    {
      "source": "wxid_abc",
      "target": "wxid_def",
      "weight": 342,
      "sent_count": 200,
      "received_count": 142,
      "total_chars": 15230,
      "first_time": "2024-01-15T08:30:00",
      "last_time": "2024-06-20T22:15:00",
      "is_group_edge": false
    }
  ],
  "communities": [
    {"cluster": 0, "members": ["wxid_abc", "wxid_def"], "label": "社区1"}
  ],
  "owner": {"username": "wxid_owner", "nickname": "我"}
}
```

**GET /api/wechat/graph/timeline?task_id=xxx&interval=month**:
```json
{
  "intervals": [
    {
      "period": "2024-01",
      "total_messages": 523,
      "active_edges": 12,
      "top_contacts": [
        {"username": "wxid_abc", "label": "张三", "message_count": 150}
      ]
    },
    {
      "period": "2024-02",
      "total_messages": 680,
      "active_edges": 15,
      "top_contacts": []
    }
  ]
}
```

---

## 5. Frontend Visualization

### 5.1 Page Structure

```
web/src/pages/WeChatGraph/
├── WeChatGraph.jsx              # Main page container
├── components/
│   ├── GraphCanvas.jsx          # Relationship graph (react-force-graph-2d)
│   ├── TimelineSlider.jsx       # Timeline linkage component
│   ├── ChatPanel.jsx            # Side panel for chat records
│   ├── CommunityLegend.jsx      # Community color legend
│   ├── PersonDetail.jsx         # Person detail card
│   └── SearchBar.jsx            # Search/filter bar
└── hooks/
    └── useWeChatGraph.js        # Data fetching and state management
```

### 5.2 Layout

```
┌─────────────────────────────────────────────────────────┐
│  🔍 Search Bar  |  Filter: [All Communities▾] [Sort: PR▾]│
├──────────────────────────────────┬──────────────────────┤
│                                  │                      │
│                                  │   Side Panel         │
│       Graph Canvas               │   (Chat/Detail)      │
│       (ForceGraph2D)             │                      │
│                                  │   Default: Owner info│
│                                  │   Edge click: Chat   │
│                                  │   Node click: Detail │
│                                  │                      │
├──────────────────────────────────┴──────────────────────┤
│  ▶ Timeline: ──●────────────────────●── 2024.01~2024.06 │
│     (Recharts area chart + draggable range selector)    │
├─────────────────────────────────────────────────────────┤
│  Legend: ●Community0  ●Community1  ●Community2          │
└─────────────────────────────────────────────────────────┘
```

### 5.3 Interactions

**Nodes**:
- Hover: tooltip (nickname, message count, PageRank rank)
- Click: side panel switches to "Person Detail" — all relationships, message stats, community membership
- Device owner node: special color/icon

**Edges**:
- Hover: tooltip (message count, time range)
- Click: side panel switches to "Chat Records" — WeChat-style bubble UI, scroll-to-load (paginated)
- Edge thickness = message weight, color intensity = activity level

**Timeline**:
- Bottom area chart shows message volume over time
- Draggable range selector for time window
- Graph updates in real-time: only edges with messages in selected range remain active
- Inactive nodes grey out but retain positions

**Community Legend**:
- Click a community to highlight its nodes
- Double-click to show only that community's subgraph

### 5.4 Tech Stack

| Component | Technology | Reason |
|-----------|-----------|--------|
| Graph rendering | `react-force-graph-2d` | Already in project, supports custom node/edge rendering |
| Timeline chart | `Recharts` | Already in project |
| Chat bubble style | Custom CSS | WeChat-style green/white bubbles |
| State management | React hooks + Redux (optional) | Lightweight for hooks, cross-page sharing via Redux |
| API calls | Axios to Python service | Consistent with existing `graphitiService.js` pattern |

### 5.5 Route Registration

```jsx
// web/src/routes.jsx — new entry
{
  path: "/wechat-graph",
  element: <WeChatGraph />,
}
```

Sidebar navigation gets a new "微信关系分析" entry with `Network` or `MessageCircle` icon.

---

## 6. Error Handling

| Scenario | Handling |
|----------|----------|
| SQLCipher password incorrect | Clear error message, suggest checking password or using `--wechat-password` |
| EnMicroMsg.db not found | Skip WeChat analysis, log WARNING,不影响 other modules |
| Auto-derivation fails (missing IMEI/UIN) | Fall back to prompting user for manual password |
| DB schema mismatch (WeChat version differences) | Lenient parsing, skip missing fields, log details |
| Empty message data | Return empty graph, frontend shows "No WeChat chat records found" |
| Graph algorithm timeout | 30-second timeout, return basic graph (nodes + edges only, no advanced metrics) |

---

## 7. Testing

### 7.1 C++ Unit Tests (`tests/UnitTest/`)

- `test_wechat_decryptor_gtest.cpp`: password derivation logic, decrypt success/failure
- `test_wechat_parser_gtest.cpp`: private/group message parsing, contact parsing, owner identification
- Uses unencrypted test databases (does not depend on real encrypted data)

### 7.2 Python Unit Tests (`python_service/tests/`)

- `test_wechat_graph_service.py`: graph construction, community detection, centrality computation, cache hit/miss/invalidation
- Uses in-memory SQLite test database

### 7.3 Frontend Tests

- Component render tests (GraphChatPanel, TimelineSlider interactions)
- API integration tests (mock data)

### 7.4 Integration Test

- `tests/test_wechat_analysis.sh`: end-to-end flow — parse → database → API → response format validation

---

## 8. New Dependencies

| Layer | Dependency | Purpose |
|-------|-----------|---------|
| C++ | `libsqlcipher-dev` | SQLCipher encrypted database support |
| Python | `networkx` | Graph algorithms (may already be installed) |
| Python | `python-louvain` | Louvain community detection |
| Python | (existing LLMIntegration) | Sentiment analysis via OpenAI-compatible API |
| Frontend | None (reuse existing) | `react-force-graph-2d` + `recharts` |

---

## 9. Integration Points

| File | Change |
|------|--------|
| `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp` | Call enhanced WeChat parsing in `analyzeAndroidData()` |
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h/.cpp` | Add `insertWeChatContact()`, `insertWeChatChatroom()`, `insertWeChatOwnerInfo()` |
| `src/core/DatabaseManager/SQL/android_analysis_sql.h` | Add new table DDL and enhanced columns |
| `src/main.cpp` | Add `--wechat-password` CLI argument |
| `src/analyzers/AndroidAnalyzer/AndroidDataTypes.h` | Add `WeChatContact`, `WeChatChatroom`, `WeChatOwnerInfo` structs |
| `python_service/httpserver/main.py` | Register `wechat_graph` router |
| `web/vite.config.js` | Add `/api/wechat` proxy to Python service |
| `web/src/routes.jsx` | Add `/wechat-graph` route |
| `CMakeLists.txt` | Add `libsqlcipher` link dependency |
