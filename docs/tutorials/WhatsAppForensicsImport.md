# WhatsApp 取证：导入 iOS 备份中的 ChatStorage.sqlite

本页说明 TraceLens 「即时通讯取证」（`/im-forensics`，WhatsApp 平台）功能：把 iOS
（iPhone）WhatsApp 备份中的 `ChatStorage.sqlite` 导入系统，解析为人类可读的取证
证据（会话 / 消息 / 联系人 / 群聊 / 通话事件）。WhatsApp 库是**明文 SQLite**，
没有解密环节——与微信（EnMicroMsg.db）、QQ（nt_msg.db）不同，导入即解析。

后端把 iOS 的 Core Data 库归一化成与微信 / QQ 相同的 `graph.db` 结构
（wechat_messages / wechat_contacts / wechat_chatrooms / wechat_owner_info 四表），
因此 WhatsApp 作为第三个平台复用同一套面板，而不是一个孤立页面。

## 快速开始

1. 打开侧边栏 **即时通讯取证**，顶部平台切换到 **WhatsApp**，点击 **导入数据库**。
2. 填写 `ChatStorage.sqlite` 的绝对路径，**或**包含它的目录路径（例如从 iOS
   逻辑备份中提取出的 WhatsApp 数据目录）。
3. 同目录的 `ContactsV2.sqlite`（通讯录）与 `CallHistory.sqlite`（通话）如果
   存在会**自动一并导入**，无需单独指定。
4. 点击开始导入；导入成功后即可在页面浏览：取证概览、会话列表、聊天记录
   （可按会话 / 类型 / 关键词 / 时间过滤）、联系人、群聊。
5. WhatsApp 导入不参与「关系分析」与「时间规律」两个 Tab 的后端链路——图谱
   服务目前只解析 `wx_<导入ID>` / `qq_<导入ID>` 前缀（`/api/wechat/graph`），
   `/api/whatsapp` 也未挂载 timeline-summary 路由；选中 WhatsApp 导入后这两个
   Tab 会报"任务不存在 / 来源不可用"，属当前版本边界，不是操作错误。

## 命令行导入（curl）

```bash
# 指向 ChatStorage.sqlite 文件本身（或其所在目录，二选一）
curl -X POST http://localhost:8090/api/whatsapp/forensics/imports \
  -H "Content-Type: application/json" \
  -d '{
    "db_path": "/evidence/whatsapp_extract/ChatStorage.sqlite",
    "name": "嫌疑人iPhone-WhatsApp",
    "backup_source": "iTunes 逻辑备份 2026-10-xx（案件 2026-xx）"
  }'
```

**预期返回**：`{"success": true, "import": {...}}`，`import` 内含 12 位十六进制
`import_id`、`status`（`ready` / `parsing` / `failed`）、`message_count`、
`stats`（总消息 / 私聊 / 群聊 / 会话数 / 联系人数 / 群数 / 通话数 / 媒体消息数）。

```bash
# 导入列表 / 单条摘要 / 取证概览
curl http://localhost:8090/api/whatsapp/forensics/imports
curl http://localhost:8090/api/whatsapp/forensics/imports/<import_id>
curl http://localhost:8090/api/whatsapp/forensics/imports/<import_id>/overview

# 分页消息（talker 为对方 JID；start/end 为 Unix 秒；page_size 最大 200）
curl "http://localhost:8090/api/whatsapp/forensics/imports/<import_id>/messages?talker=8613800138000@s.whatsapp.net&page=1&page_size=50"

# 会话 / 联系人 / 群聊
curl http://localhost:8090/api/whatsapp/forensics/imports/<import_id>/sessions
curl http://localhost:8090/api/whatsapp/forensics/imports/<import_id>/contacts
curl http://localhost:8090/api/whatsapp/forensics/imports/<import_id>/chatrooms

# 删除导入（不改动原始证据文件）
curl -X DELETE http://localhost:8090/api/whatsapp/forensics/imports/<import_id>
```

`overview` 返回 `decryption: {scheme: "none"}`——这是诚实的"无解密环节"标记，
不是缺字段。

## 证据源定位（_resolve_sources）

`db_path` 两种合法形态：

| 形态 | 行为 |
|---|---|
| 指向 `ChatStorage.sqlite` 文件 | 以该文件为主库，在**同目录**找两个伴生库 |
| 指向包含它的目录 | 目录下找 `ChatStorage.sqlite` |

| 源 | 文件 | 缺失时 |
|---|---|---|
| chat（必需） | `ChatStorage.sqlite` | 报 `ChatStorage.sqlite not found`，导入失败 |
| contacts（可选） | `ContactsV2.sqlite` | 跳过，联系人仅来自会话对方号码 |
| calls（可选） | `CallHistory.sqlite` | 跳过，时间轴无通话事件 |

`ChatStorage.sqlite` 在 iTunes / Finder 逻辑备份中的逻辑路径是
`AppDomainGroup-group.net.whatsapp.WhatsApp.shared` 域；先从备份中把它（连同
需要的伴生库）提取到普通目录再导入。整包备份解析见
[iOS 逻辑备份取证](../ios-logical-backup.md)。

## 解析语义（导入时归一化）

| iOS 表 | 归一化到 | 说明 |
|---|---|---|
| `ZWAMESSAGE` | `wechat_messages` | `ZISFROMME` 决定 `is_send`；`ZMESSAGETYPE` 存 `msg_type` 并映射中文标签 |
| `ZWACHATSESSION` | `wechat_contacts` / `wechat_chatrooms` | `ZPARTNERNAME` 是可读名称；群聊（JID 以 `@g.us` 结尾）把群 JID 存进 `wechat_chatrooms.owner` |
| `ZWAADDRESSBOOKCONTACT` | `wechat_contacts` | 号码 ↔ 显示名补全（`ZPHONENUMBER` / `ZGIVENNAME` / `ZFAMILYNAME`） |
| `ZWACDCALLEVENT` | `wechat_messages`（`msg_type=9`） | 通话事件进同一时间轴，内容形如「WhatsApp 通话 · N 秒」 |

关键约束（解析器内建，取证报告可直接引用）：

- **时间戳**：`ZMESSAGEDATE` 是 Apple 纪元（2001-01-01 起），`apple_to_unix` 按
  量级分**四档**换算为 Unix 秒——`>1e14` 视为 Apple 纳秒（÷1e9 再加纪元偏移）、
  `1e11 < 值 ≤ 1e14` 视为毫秒（÷1000 取整为秒）、`1.2e9 ≤ 值 ≤ 1e11` 按 Unix 秒
  原样保留、`<1.2e9` 视为 Apple 秒（加纪元偏移）；避免"错 31 年"的系统性偏移。
- **`ZPUSHNAME` 不是显示名**：它是加密的推送名（base64 密文），解析器一律不把
  它写进身份列；发送者取会话 `ZPARTNERNAME` 或消息级 JID 的号码部分。
- **群聊**：消息的 `talker` 是群 JID（`xxx@g.us`），发送者是成员 JID；会话列表
  通过 `wechat_chatrooms.owner`（JID → 群名）反查，页面显示真实群名。
- **空正文补类型标签**：类型 6（群成员变动）等无正文消息不会显示为空白行，
  而是落到对应中文标签。
- **消息量级上限**：单次导入最多读 200 万条消息（`MAX_MESSAGES`），按时间升序。
- 源库始终以 `mode=ro` 只读打开（`PRAGMA query_only=ON`），归一化结果写入
  `<data_root>/whatsapp_imports/<import_id>/graph.db`，**不回写证据文件**。

## 消息类型标签

`MESSAGE_TYPE_LABELS` 登记了以下 `msg_type` 及其中文标签：

| `msg_type` | 标签 | | `msg_type` | 标签 |
|---|---|---|---|---|
| 0 | 文本 | | 5 | 名片 |
| 1 | 图片 | | 6 | 群成员变动 |
| 2 | 语音 | | 7 | 链接/媒体 |
| 3 | 视频 | | 8 | 文档 |
| 4 | 位置 | | 10 | 系统消息 |
|  |  | | 14 | 贴纸 |

不在表中的类型**没有专属标签**：API 的 `msg_type_label` 对未登记类型回退为
`类型N`（例如 `msg_type=9` 显示为 `类型9`）。CallHistory 通话事件的通话语义不在
`msg_type` 标签里，而写在 `media_type` 列（值为 `通话`），正文形如
「WhatsApp 通话 · N 秒」。

## 与另外两个平台的关系

| | 微信 | QQ | WhatsApp |
|---|---|---|---|
| 平台参数 | `platform=wechat` | `platform=qq` | `platform=whatsapp` |
| 图谱 task 前缀 | `wx_<导入ID>` | `qq_<导入ID>` | `wa_`（后端暂未解析） |
| 解密环节 | SQLCipher 页级检测 + 逐页解密 | SQLCipher（剥 1024B 头） | 无 |
| 时间规律接口 | `/api/wechat/.../timeline-summary` | `/api/qq/.../timeline-summary` | 未挂载 |

三平台的概览 / 会话 / 消息 / 联系人 / 群聊读接口契约一致（同构 graph.db），
前端共用同一组面板组件（`WhatsAppPanels.jsx` 等）。

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| 400 `db_path is required` | 请求体没带 `db_path` 或为空白字符串 |
| 404 `ChatStorage.sqlite not found at ...` | 路径写错，或指向的目录里没有该文件；确认提取出的目录结构 |
| 导入 `status=failed`：`ChatStorage.sqlite has no ZWAMESSAGE table` | 拿到的不是 WhatsApp 消息库（常见错拿成 `Chat.db` 或其他应用的库）；重新核对域路径 |
| 会话/消息有数据但联系人是裸号码 | `ContactsV2.sqlite` 不在 `ChatStorage.sqlite` 同目录；把它移到同一目录后重新导入 |
| 时间规律 Tab 报 404 | `/api/whatsapp` 未挂载 timeline-summary 路由，当前版本边界；时间轴数据仍可从 `messages?start=&end=` 按时间窗取 |
| 关系分析 Tab 报任务不存在 | 图谱服务只解析 `wx_` / `qq_` 前缀，`wa_<导入ID>` 尚未接入 |

## 相关实现

- API：`python_service/httpserver/routes/whatsapp_forensics.py`（`/api/whatsapp/forensics/*`）
- 导入 / 解析：`python_service/httpserver/services/whatsapp_import_service.py`
  （类 `WhatsAppImportService`；`_resolve_sources` 源定位、`_build_graph_db` 归一化）
- 前端：`web/src/pages/IMForensics/IMForensics.jsx`（WhatsApp 面板
  `WhatsAppPanels.jsx`）
- 与 iOS 任务链路的关系：`/api/tasks` 的 iOS 备份任务走 C++ `IosAnalyzer` 写
  `android.db`（短信 / 通讯录 / 备忘录等）；本页 WhatsApp 导入是独立的 Python
  服务链路，两者互不依赖

测试：`python_service/tests/unit/test_whatsapp_import_service.py`
（Apple 纪元换算 / JID 归一 / 群聊 talker / 通话事件 / 加密推送名不落身份列 /
graph.db 归一化）；浏览器端到端：`web/scripts/e2e-whatsapp-im.mjs`。

**最后更新**: 2026-11-10（新建，教程）
