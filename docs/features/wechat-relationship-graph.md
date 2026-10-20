# 微信关系图分析模块 (WeChat Relationship Graph Analysis)

## 概述

微信关系图分析模块是 Android 取证分析的重要扩展，能够解密微信 EnMicroMsg.db 数据库、解析聊天记录和联系人信息，并通过图算法构建社交关系网络，最终在前端以交互式力导向图展示人物关系。

### 核心能力

- **SQLCipher 解密**：支持用户手动输入密码和自动推导（IMEI + UIN）两种模式
- **增强解析**：联系人、群聊、私聊消息、设备主身份识别
- **图算法分析**：Louvain 社区发现、PageRank、中介中心性、时间维度分析
- **交互式可视化**：ForceGraph2D 关系图、时间线联动、聊天气泡面板

---

## 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    C++ AndroidAnalyzer                       │
│  ┌─────────────────┐  ┌────────────────┐  ┌──────────────┐  │
│  │ WeChatDecryptor  │→│ Enhanced Parser │→│ AndroidDB    │  │
│  │ (SQLCipher解密)  │  │ (联系人/群/消息)│  │ (_android.db)│  │
│  └─────────────────┘  └────────────────┘  └──────┬───────┘  │
└──────────────────────────────────────────────────┼──────────┘
                                                   │
┌──────────────────────────────────────────────────┼──────────┐
│                Python FastAPI Service             │          │
│  ┌────────────────────────────────────────────────┴───────┐  │
│  │              WeChatGraphService                         │  │
│  │  ┌─────────────┐ ┌──────────────┐ ┌─────────────────┐  │  │
│  │  │ Graph Build  │→│  Algorithms  │→│  Cache + API    │  │  │
│  │  │ (NetworkX)   │ │ (Louvain/PR) │ │ (30min TTL)     │  │  │
│  │  └─────────────┘ └──────────────┘ └─────────────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
│  REST API: /api/wechat/graph, /api/wechat/chat, ...          │
└──────────────────────────────────────────────────────────────┘
                                                   │
┌──────────────────────────────────────────────────┼──────────┐
│                  React Frontend                  │          │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────┴────────┐  │
│  │ GraphCanvas   │ │ TimelineSlider│ │ ChatPanel           │  │
│  │ (ForceGraph2D)│ │ (Recharts)   │ │ (聊天气泡)           │  │
│  └──────────────┘ └──────────────┘ └─────────────────────┘  │
│  路由: /wechat-graph                                        │
└──────────────────────────────────────────────────────────────┘
```

### 数据流

```
EnMicroMsg.db (SQLCipher加密)
    ↓ WeChatDecryptor.openDatabase(password)
    ↓ PRAGMA key + cipher 配置
解密后的 SQLite 数据库
    ↓ parseWeChatContacts()      → wechat_contacts 表
    ↓ parseWeChatChatrooms()     → wechat_chatrooms 表
    ↓ identifyWeChatOwner()      → wechat_owner_info 表
    ↓ parseWeChatEnhanced()      → wechat_messages 表 (增强版)
_android.db
    ↓ Python WeChatGraphService._build_graph()
NetworkX DiGraph
    ↓ _compute_metrics()
    ├─ Louvain 社区发现 → cluster_id
    ├─ PageRank → pagerank 分数
    └─ Betweenness → betweenness 分数
JSON 缓存 (30分钟 TTL)
    ↓ REST API
前端可视化
    ├─ ForceGraph2D: 节点=人物, 边=关系
    ├─ Recharts: 时间线面积图
    └─ ChatPanel: 聊天气泡侧边面板
```

---

## C++ 层实现

### 1. SQLCipher 解密器

**文件**：`src/analyzers/AndroidAnalyzer/WeChatDecryptor.h/.cpp`

#### 密码解析策略

优先级：用户手动输入 > 自动推导

```
命令行参数:
  --wechat-password <7位密码>    最高优先级
  --wechat-auto-decrypt          未提供密码时启用（默认开启）
```

#### 自动推导算法

```
1. 从 shared_prefs/auth_info_key_prefs.xml 提取 UIN
   - 搜索 "_auth_uin" 或 "default_uin" 属性
   - 解析 XML value="..." 格式

2. IMEI 默认值: "1234567890ABCDEF"
   - 新设备可能无 IMEI，使用默认值

3. 密码 = MD5(IMEI + UIN).substring(0, 7)
```

#### SQLCipher 兼容性

```cpp
// 双模式尝试：先 SQLCipher 4.x（新版微信），再 2.x（旧版微信）
bool openDatabase(const std::string& dbPath, const std::string& password) {
    // 尝试 4.x: KDF 64000 次, SHA512 HMAC, 4096 页大小
    if (tryOpenWithCipher(dbPath, password, 64000, "sha512")) return true;
    // 回退 2.x: KDF 4000 次, SHA1 HMAC, 1024 页大小
    if (tryOpenWithCipher(dbPath, password, 4000, "sha1")) return true;
    return false;
}
```

#### 安全措施

- 使用 `PRAGMA key` 设置密码（单引号转义防注入）
- `OPENSSL_cleanse()` 清除内存中的敏感数据
- 禁止拷贝/移动构造（防 double-free）
- 解密验证：查询 `sqlite_master` 确认成功

### 2. 增强解析器

**文件**：`src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp`

#### 联系人解析

```sql
SELECT username, nickname, conRemark, type, chatroomFlag
FROM rcontact
WHERE username NOT LIKE '%@chatroom%'
  AND username != 'weixin'
  AND username != 'filehelper'
```

- 过滤系统账号（weixin, filehelper）
- 过滤群聊条目（@chatroom 后缀）
- 显示名优先级：conRemark（备注）> nickname（昵称）> username

#### 群聊解析

```sql
SELECT chatroomname, roomowner, memberlist, membercount, addtime
FROM chatroom
```

- `memberlist`：逗号分隔的成员 username 列表
- `roomowner`：群主 username

#### 消息解析

```sql
SELECT talker, content, createTime, type, isSend
FROM message
WHERE type IN (1, 3, 34, 43, 47, 49)
ORDER BY createTime
```

**消息类型过滤**：
| type | 含义 |
|------|------|
| 1 | 文本 |
| 3 | 图片 |
| 34 | 语音 |
| 43 | 视频 |
| 47 | 表情 |
| 49 | 链接/富媒体 |

**私聊 vs 群聊判断**：

```cpp
if (talker.find("@chatroom") != string::npos) {
    // 群聊：talker = 群ID，发送者从内容头部提取
    // 格式: "wxid_xxx:\n实际消息内容"
    size_t colonPos = content.find(":\n");
    sender = content.substr(0, colonPos);
    content = content.substr(colonPos + 2);
} else {
    // 私聊：isSend=1 表示设备主发送
    if (isSend == 1) { sender = owner; receiver = talker; }
    else { sender = talker; receiver = owner; }
}
```

#### 设备主识别

```sql
SELECT value FROM userinfo WHERE id = 2;  -- username
SELECT value FROM userinfo WHERE id = 4;  -- nickname
```

### 3. 数据库 Schema

**文件**：`src/core/DatabaseManager/SQL/android_analysis_sql.h`

#### 新增表

```sql
-- 联系人表
CREATE TABLE IF NOT EXISTS wechat_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,          -- 微信内部用户名
    nickname TEXT,                 -- 昵称
    remark TEXT,                   -- 备注名
    avatar_path TEXT,              -- 头像路径
    type INTEGER,                  -- 联系人类型
    chatroom_flag INTEGER DEFAULT 0
);

-- 群聊表
CREATE TABLE IF NOT EXISTS wechat_chatrooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chatroom_name TEXT UNIQUE,     -- 群ID (xxx@chatroom)
    owner TEXT,                    -- 群主
    member_list TEXT,              -- 成员列表（逗号分隔）
    member_count INTEGER,
    create_time INTEGER
);

-- 设备主信息表
CREATE TABLE IF NOT EXISTS wechat_owner_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,          -- 设备主微信用户名
    nickname TEXT,
    uin INTEGER,
    imei TEXT
);
```

#### 增强的 wechat_messages 表

```sql
CREATE TABLE IF NOT EXISTS wechat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT,
    receiver TEXT,
    content TEXT,
    timestamp INTEGER,
    media_url TEXT,
    media_type TEXT,
    msg_type INTEGER DEFAULT 1,      -- 消息类型 (1=text, 3=image, ...)
    is_send INTEGER DEFAULT 0,       -- 是否设备主发送
    chatroom_name TEXT,              -- 群聊名称（私聊为NULL）
    sender_nickname TEXT,            -- 发送者昵称（冗余加速查询）
    talker TEXT                      -- 原始 talker 字段
);
```

### 4. CLI 参数

**文件**：`src/CommandLineParser.h/.cpp`

```
用法: forensic_analyzer <image> --android-analyze --wechat-password <7位密码>

参数:
  --android-analyze        启用 Android 分析（必需）
  --wechat-password <pwd>  手动指定微信解密密码（最高优先级）
```

密码传递链：`CommandLineParser` → `CommandLineArgs.wechat_password` → `AnalysisOrchestrator` → `AndroidAnalyzer.setWeChatPassword()` → `parseWeChatEnhanced()`

---

## Python 层实现

### 1. 图计算服务

**文件**：`python_service/httpserver/services/wechat_graph_service.py`

#### 图构建

```python
class WeChatGraphService:
    def _build_graph(self, db_path: str) -> nx.DiGraph:
        G = nx.DiGraph()
        # 1. 读取设备主信息 → 添加 owner 节点
        # 2. 读取联系人 → 构建 username→label 映射
        # 3. 读取私聊消息 → 构建边（weight, total_chars, sent/received, 时间范围）
        # 4. 读取群聊消息 → 共活跃度边（1小时窗口内同群活跃）
        return G
```

**节点属性**：
| 属性 | 说明 |
|------|------|
| `id` | WeChat username |
| `label` | 显示名（优先级: remark > nickname > username） |
| `is_owner` | 是否为设备主 |
| `message_count` | 参与的消息总数 |

**边属性（私聊）**：
| 属性 | 说明 |
|------|------|
| `weight` | 两人间消息总数 |
| `total_chars` | 总字数 |
| `first_time` / `last_time` | 最早/最晚消息时间戳 |
| `sent_count` / `received_count` | 双向消息计数 |

**边属性（群聊共活跃度）**：
| 属性 | 说明 |
|------|------|
| `weight` | 同群1小时窗口内共活跃次数 |
| `is_group_edge` | `true` |
| `chatroom_name` | 来源群名 |

共活跃度算法：对每个群的消息按时间排序，使用滑动窗口（1小时），窗口内的不同用户两两建立边。

#### 图算法

| 维度 | 算法 | 输出 |
|------|------|------|
| **社区发现** | Louvain (`community.louvain_communities`) | `cluster_id` per node |
| **关键人物** | PageRank (`nx.pagerank`) | `pagerank` 分数 |
| **桥梁人物** | Betweenness Centrality (`nx.betweenness_centrality`) | `betweenness` 分数 |
| **时间维度** | 按月/周切片聚合 | `intervals[]` 数组 |
| **情感分析** | LLM API（可选） | `sentiment_score` per edge |

Louvain 算法回退策略：如果 `python-louvain` 未安装，自动回退到 NetworkX 内置的连通分量分析。

#### 缓存策略

```python
_cache = {}  # task_id:mtime → { data, timestamp }

# 规则：
- 按 task_id + 数据库文件 mtime 组合为缓存键
- TTL = 30 分钟
- mtime 变化自动失效（数据库被重新写入时）
- POST /api/wechat/graph/invalidate 强制刷新
- 缓存存储序列化后的 JSON 数据，不缓存 NetworkX 对象
```

### 2. REST API

**文件**：`python_service/httpserver/routes/wechat_graph.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/wechat/graph?task_id=xxx` | 完整关系图（节点+边+社区+中心性） |
| `GET` | `/api/wechat/graph/timeline?task_id=xxx&interval=month` | 时间维度数据（按月/周聚合） |
| `GET` | `/api/wechat/graph/community?task_id=xxx` | 社区分组详情 |
| `GET` | `/api/wechat/graph/person/{username}?task_id=xxx` | 单人关系网络（ego network） |
| `GET` | `/api/wechat/chat?task_id=xxx&user1=A&user2=B&offset=0&limit=50` | 两人聊天记录（分页） |
| `GET` | `/api/wechat/chat/group?task_id=xxx&chatroom=xxx&offset=0&limit=50` | 群聊记录（分页） |
| `GET` | `/api/wechat/owner?task_id=xxx` | 设备主信息 |
| `GET` | `/api/wechat/contacts?task_id=xxx` | 联系人列表 |
| `POST` | `/api/wechat/graph/invalidate?task_id=xxx` | 强制刷新缓存 |

#### 响应格式

**关系图响应** (`GET /api/wechat/graph`)：
```json
{
  "success": true,
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
    {"cluster": 0, "members": ["wxid_abc", "wxid_def"], "label": "社区0"}
  ],
  "owner": {"username": "wxid_owner", "nickname": "我"},
  "timestamp": "2024-06-20T12:00:00"
}
```

**时间线响应** (`GET /api/wechat/graph/timeline`)：
```json
{
  "success": true,
  "intervals": [
    {
      "period": "2024-01",
      "total_messages": 523,
      "active_edges": 12,
      "top_contacts": [
        {"username": "wxid_abc", "label": "张三", "message_count": 150}
      ]
    }
  ],
  "timestamp": "2024-06-20T12:00:00"
}
```

#### 数据库路径解析

```
1. 查询 C++ 后端任务元数据 → android_db 字段
2. 回退: 从 output_raw_db 推导 (_raw.db → _android.db)
3. 最后: glob 搜索 *_android.db
```

---

## 前端实现

### 1. 页面结构

```
web/src/pages/WeChatGraph/
├── WeChatGraph.jsx              # 主页面容器
├── components/
│   ├── GraphCanvas.jsx          # 关系图画布 (react-force-graph-2d)
│   ├── TimelineSlider.jsx       # 时间线联动 (Recharts)
│   ├── ChatPanel.jsx            # 聊天气泡侧边面板
│   ├── CommunityLegend.jsx      # 社区图例
│   ├── PersonDetail.jsx         # 人物详情卡片
│   └── SearchBar.jsx            # 搜索/筛选栏
└── hooks/
    └── useWeChatGraph.js        # 数据获取与状态管理
```

### 2. 布局设计

```
┌─────────────────────────────────────────────────────────┐
│  🔍 搜索栏  |  筛选: [全部社区▾] [排序: PageRank▾]     │
├──────────────────────────────────┬──────────────────────┤
│                                  │                      │
│                                  │   侧边面板           │
│       关系图画布                  │   (聊天记录/详情)     │
│       (ForceGraph2D)             │                      │
│                                  │   默认: 社区图例      │
│                                  │   点击边: 聊天记录    │
│                                  │   点击节点: 人物详情  │
│                                  │                      │
├──────────────────────────────────┴──────────────────────┤
│  ▶ 时间线: ──●────────────────────●──  2024.01 ~ 2024.06 │
│     (Recharts 面积图 + 可拖拽时间范围选择器)              │
├─────────────────────────────────────────────────────────┤
│  社区图例: ●社区0  ●社区1  ●社区2  ●社区3               │
└─────────────────────────────────────────────────────────┘
```

### 3. 交互设计

#### 节点交互

| 操作 | 行为 |
|------|------|
| 悬停 | 显示 tooltip（昵称、消息总数、PageRank 排名） |
| 点击 | 侧边面板切换为「人物详情」— 关系列表、消息统计、所属社区 |
| 设备主节点 | 金色高亮，特殊标记 |

#### 边交互

| 操作 | 行为 |
|------|------|
| 悬停 | 显示 tooltip（消息数、时间范围） |
| 点击 | 侧边面板切换为「聊天记录」— 微信气泡样式，支持滚动加载 |
| 边粗细 | = 消息数量权重 |
| 颜色深浅 | = 活跃度 |

#### 时间线联动

- 底部 Recharts 面积图显示消息量随时间变化
- 支持 Brush 拖拽选择时间范围
- 选择范围后，关系图实时更新：仅显示该时段内有消息的边
- 未活跃节点变灰但保留位置

#### 社区图例

- 点击某个社区高亮该社区所有节点
- 再次点击取消选择

### 4. 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| 关系图渲染 | `react-force-graph-2d` | 项目已有依赖，支持自定义节点/边渲染 |
| 时间线图表 | `Recharts` | 项目已有依赖 |
| 聊天气泡 | 自定义 CSS | 模拟微信绿色/白色气泡 + 箭头伪元素 |
| 状态管理 | React hooks (useState/useCallback/useMemo) | 轻量场景足够 |
| API 调用 | Axios (pythonApi) | 与现有 graphitiService.js 模式一致 |
| 代码分割 | React.lazy + Suspense | 按需加载，减少主包体积 |

### 5. 路由与导航

```jsx
// routes.jsx
const WeChatGraph = React.lazy(() => import('./pages/WeChatGraph/WeChatGraph'));
{ path: 'wechat-graph', element: <React.Suspense ...><WeChatGraph /></React.Suspense> }

// Layout.jsx
{ name: t('nav.wechat_graph'), href: '/wechat-graph', icon: MessageCircle }
// taskContextPages 中添加 '/wechat-graph' 以传递 task_id
```

---

## 依赖关系

### 新增依赖

| 层 | 依赖 | 用途 |
|----|------|------|
| C++ | `libsqlcipher-dev` | SQLCipher 加密数据库支持（可选，编译时检测） |
| C++ | `libcrypto` (OpenSSL) | MD5 密码推导 + 内存清理 |
| Python | `networkx>=3.0` | 图数据结构和算法 |
| Python | `python-louvain>=0.16` | Louvain 社区发现算法 |
| 前端 | 无新增 | 复用 `react-force-graph-2d` + `recharts` |

### CMake 集成

```cmake
# SQLCipher 作为可选依赖
pkg_check_modules(SQLCIPHER QUIET sqlcipher)
if(SQLCIPHER_FOUND)
  add_definitions(-DHAVE_SQLCIPHER)
  set(SQLITE_LINK_LIBRARIES ${SQLCIPHER_LIBRARIES})
else()
  set(SQLITE_LINK_LIBRARIES ${SQLite3_LIBRARIES})
endif()

# WeChatDecryptor 仅在 SQLCipher 可用时编译
$<$<BOOL:${SQLCIPHER_FOUND}>:src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp>
```

---

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| SQLCipher 密码错误 | 返回明确错误信息，提示检查密码或使用 `--wechat-password` |
| EnMicroMsg.db 不存在 | 跳过微信分析，日志 WARNING，不影响其他模块 |
| 自动推导密码失败 | 返回空字符串，提示用户手动输入 |
| 数据库表结构不匹配 | 宽容解析，跳过缺失字段，日志记录 |
| 无消息数据 | 返回空图，前端显示"未发现微信聊天记录" |
| python-louvain 未安装 | 回退到连通分量分析 |
| 网络请求失败 | 前端显示错误信息，支持重试 |

---

## 测试

### C++ 单元测试

| 测试文件 | 测试数 | 覆盖范围 |
|----------|--------|---------|
| `test_wechat_decryptor_gtest.cpp` | 13 | 空密码、不存在文件、MD5推导、拷贝禁止、状态管理 |
| `test_wechat_parser_gtest.cpp` | 19 | 数据库创建、联系人/消息/群聊数据、群消息格式解析、设备主识别 |

### 集成测试

`tests/test_wechat_analysis.sh` 验证：
1. 项目编译成功
2. C++ 单元测试通过
3. Python 路由注册正确
4. 前端文件和路由存在

### 测试运行

```bash
# C++ 测试
cd build && ctest --output-on-failure -R wechat

# 集成测试
bash tests/test_wechat_analysis.sh
```

---

## 安全考虑

1. **密码处理**：使用 `OPENSSL_cleanse()` 清除内存中的敏感数据
2. **SQL 注入防护**：密码单引号转义，所有查询使用参数化绑定
3. **拷贝禁止**：WeChatDecryptor 禁止拷贝/移动构造，防止 sqlite3 句柄 double-free
4. **编译时可选**：SQLCipher 依赖通过 `HAVE_SQLCIPHER` 宏控制，无 SQLCipher 时优雅降级
5. **审计日志**：所有解析操作通过 Logger 记录

---

## 已知限制

1. **IMEI 自动提取**：当前使用默认值 `"1234567890ABCDEF"`，需要从 build.prop 或 telephony 数据库中提取真实 IMEI
2. **群聊发送者提取**：依赖消息内容中的 `wxid_xxx:\n` 格式，非标准格式的消息可能解析失败
3. **情感分析**：设计中包含但当前未实现，需要集成 LLM API
4. **HTTP API 密码传递**：仅支持 CLI 参数，HTTP 任务创建路径暂不支持 `--wechat-password`
5. **Python 单元测试**：集成测试脚本检查但测试文件尚未创建

---

## 文件清单

### 新增文件

| 文件 | 层 | 说明 |
|------|-----|------|
| `src/analyzers/AndroidAnalyzer/WeChatDecryptor.h` | C++ | SQLCipher 解密器头文件 |
| `src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp` | C++ | 解密器实现 |
| `tests/UnitTest/test_wechat_decryptor_gtest.cpp` | C++ | 解密器单元测试 |
| `tests/UnitTest/test_wechat_parser_gtest.cpp` | C++ | 解析器单元测试 |
| `python_service/httpserver/services/wechat_graph_service.py` | Python | 图计算服务 |
| `python_service/httpserver/routes/wechat_graph.py` | Python | REST API 路由 |
| `web/src/services/wechatService.js` | 前端 | API 客户端 |
| `web/src/pages/WeChatGraph/WeChatGraph.jsx` | 前端 | 主页面 |
| `web/src/pages/WeChatGraph/hooks/useWeChatGraph.js` | 前端 | 数据 Hook |
| `web/src/pages/WeChatGraph/components/GraphCanvas.jsx` | 前端 | 关系图画布 |
| `web/src/pages/WeChatGraph/components/ChatPanel.jsx` | 前端 | 聊天面板 |
| `web/src/pages/WeChatGraph/components/TimelineSlider.jsx` | 前端 | 时间线 |
| `web/src/pages/WeChatGraph/components/CommunityLegend.jsx` | 前端 | 社区图例 |
| `web/src/pages/WeChatGraph/components/PersonDetail.jsx` | 前端 | 人物详情 |
| `web/src/pages/WeChatGraph/components/SearchBar.jsx` | 前端 | 搜索栏 |
| `web/src/styles/wechat-graph.css` | 前端 | 聊天气泡样式 |
| `tests/test_wechat_analysis.sh` | 测试 | 集成测试脚本 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/analyzers/AndroidAnalyzer/AndroidDataTypes.h` | 新增 WeChatContact, WeChatChatroom, WeChatOwnerInfo 结构体 |
| `src/core/DatabaseManager/SQL/android_analysis_sql.h` | 新增 3 张表 + 增强 wechat_messages + INSERT 常量 |
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h/.cpp` | 新增 4 个 insert 方法 |
| `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h` | 新增解析方法声明 + wechatPassword_ 成员 |
| `src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp` | 增强微信解析器实现 |
| `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp` | 集成 parseWeChatEnhanced |
| `src/CommandLineParser.h/.cpp` | 新增 --wechat-password 参数 |
| `src/AnalysisOrchestrator.cpp` | 传递密码到 AndroidAnalyzer |
| `CMakeLists.txt` | SQLCipher 可选依赖 |
| `tests/CMakeLists.txt` | 新增测试目标 |
| `python_service/httpserver/main.py` | 注册 wechat_graph 路由 |
| `python_service/httpserver/routes/__init__.py` | 添加 wechat_graph |
| `python_service/httpserver/requirements.txt` | 添加 networkx, python-louvain |
| `web/src/routes.jsx` | 添加 /wechat-graph 路由 |
| `web/src/components/Layout/Layout.jsx` | 添加侧边栏导航 |
| `web/src/locales/zh.js` | 添加翻译键 |
| `web/src/locales/en.js` | 添加翻译键 |
| `web/vite.config.js` | 添加 /api/wechat 代理 |
