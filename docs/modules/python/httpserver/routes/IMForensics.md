# IMForensics 路由（python_service/httpserver/routes/whatsapp_forensics.py + qq_forensics.py + wechat_forensics.py，前缀 /api/whatsapp、/api/qq、/api/wechat）

> **一句话**：三个即时通讯平台的"导入→解密→归一化→查询"直通管道——每平台 9 个同构端点（imports CRUD + overview/sessions/messages/contacts/chatrooms 五类读取），把 iOS WhatsApp 备份、Android QQ（NTQQ 与老版 4.x）账号库、Android 微信账号库各自归一化成同一套 `graph.db`，从而以 `wx_/qq_<import_id>` 身份直接复用既有关系图谱管线；微信侧额外有 media 缩略图端点，QQ/微信侧各自挂载 timeline-summary 时间规律端点。

## 1. 这组路由承担什么职责（为什么存在）

三个平台的取证面板（前端 `/im-forensics` 页）需要同一套交互：导入一个账号数据库 → 看概览 → 翻会话/消息/联系人/群聊。如果每个平台各自发明 API，前端就得维护三套面板逻辑、关系图谱管线也得为每个平台单独适配。这组路由的解法是**形状镜像**（whatsapp_forensics.py:15-17 模块 docstring 明说"route surface mirrors /api/qq and /api/wechat"）：

- 每个 `routes/<platform>_forensics.py` 都挂载同一组 9 个端点（POST/GET/DELETE `/forensics/imports`、GET `/forensics/imports/{id}` 与五个读取子端点）；
- 每个平台的服务层把源数据归一化成**同一套 `graph.db` 表**（`wechat_messages` / `wechat_contacts` / `wechat_chatrooms` / `wechat_owner_info`），于是 `/api/wechat/graph?task_id=qq_<import_id>`（wechat_graph_models.py:177-188）或 `wx_<import_id>`（:161-176）都能经 `ensure_graph_db` 解析到对应导入库——WhatsApp/QQ 数据集作为"第三个平台"接入既有关系分析管线，而不是旁路（qq_forensics.py:16-18）。

三个文件间的差异点只有：微信多一个 `/media/{rel_path:path}`（缩略图文件服务，wechat_forensics.py:190-199）与导入时的密钥自动推导字段；QQ 的 create_import 接受显式 `password` 或 `key_material`（nt_uid+rand 推导，qq_forensics.py:48-54）；WhatsApp 无解密环节（iOS 备份库是明文 Core Data 表，whatsapp_forensics.py:46-54）。挂载位置：qq/wechat/whatsapp 分别由 main.py:357-358 与 wechat_graph.py:37（forensics_router 并入 `/api/wechat` 聚合器）注册。

## 2. 典型调用方（前端哪个页面/组件）

- `/im-forensics` 页（pages/IMForensics/IMForensics.jsx）：三平台各自的 `*ForensicsService`——`web/src/services/wechatForensicsService.js:10-46`（`/api/wechat/forensics/*`，media 用 `PYTHON_API_BASE_URL` 拼直链 ：46）、`qqForensicsService.js:10-42`、`whatsappForensicsService.js:11-39`。平台切换在 IMForensics.jsx:88-101（每平台的 imports/overview 与五个 Tab 组件的装配表）。
- 关系分析 Tab：`IMForensics/graph/hooks/useWeChatGraph.js` 以 `wx_/qq_<import_id>` 为 task_id 调 `/api/wechat/graph`——本组路由的导入是它的数据源。
- 时间规律：QQ/微信导入目录页经各平台 service 调 `/forensics/imports/{id}/timeline-summary`（由 timeline_summary.py 的子 router include 进各自 router，qq_forensics.py:28-32、wechat_forensics.py:28-32），详见 [TimelineSummary.md](TimelineSummary.md)。
- 服务间调用：无——C++ 不调这组路由；`/api/wechat/graph` 是唯一下游（读归一化产物）。

## 3. 核心数据结构

**导入身份**：12 位小写十六进制 `import_id`（服务层 `_import_dir` 用 `re.fullmatch(r"[0-9a-f]{12}")` 强校验，whatsapp_import_service.py:68-69、qq_import_service.py:94-95）；数据落在 `{DATA_ROOT}/<platform>_imports/<import_id>/`（whatsapp_imports / qq_imports / wechat_imports 三目录，qq_import_service.py:15-25 有完整布局 docstring）。每目录一份 `meta.json` 记录 source 路径、格式（QQ 老版额外记 `"format": "legacy_qq4"`，qq_import_service.py:455）、计数与密钥来源记录。

**响应包**：全部端点包一层 `{"success": true, ...}`（如 whatsapp_forensics.py:59）；messages 返回 `{"success", "messages", "total", "page"...}`（服务层分页结果展开，whatsapp_forensics.py:134 的 `{"success": True, **result}`）。错误映射三层：`FileNotFoundError`→404、QQ/微信的 `ValueError`（坏 import_id / 坏参数）→400、其余→500 且 detail 固定前缀 `<what> failed:`（三个文件各自的 `_handle_error`，whatsapp_forensics.py:39-41）。

**消息筛选参数**（三平台同形，细节按平台语义）：

| 参数 | WhatsApp（:117-127） | QQ（:128-138） | 微信（:141-151） |
|---|---|---|---|
| 会话过滤 | `talker`（默认 ""） | `talker`（peer/group uin） | `talker`（session talker） |
| 类型 | `msg_type` int | `msg_type`（外层 40011） | `msg_type`（基础 1/3/47/49…） |
| 关键词 | `keyword` ≤200 | `keyword` | `keyword` |
| 时间窗 | `start`/`end`（秒，Apple 纪元换算后） | `start_ts`/`end_ts`（毫秒） | `start_ts`/`end_ts`（毫秒） |
| 分页 | `page` + `page_size`（≤200） | `limit`（≤2000）+ `offset` | `limit`（≤2000）+ `offset` |

## 4. 端点语义分组（散文）

每组路由 9+1 个端点（`@router` 定义行以微信文件为例）：

- **导入生命周期**：`POST /forensics/imports`（wechat_forensics.py:44；QQ :44；WhatsApp :44）——同步导入+解密+归一化（服务内部 to_thread），成功返回 import 摘要；`GET /forensics/imports`（:80）列全部导入（meta 摘要列表）；`GET /forensics/imports/{import_id}`（:93）单条 meta（QQ/微信对坏 id 返 400，:99-100）；`DELETE /forensics/imports/{import_id}`（:105）删目录并返回 `removed` 布尔。
- **读取五件套**：`/overview`（:116，消息计数/联系人/群组/时间跨度等概览）、`/sessions`（:129，会话列表）、`/messages`（:141，分页消息，筛选参数见上表）、`/contacts`（:166）、`/chatrooms`（:178，群详情+成员）。全部只读、全部 to_thread/Awaitable 包装服务层。
- **微信专属 media**：`GET /forensics/imports/{import_id}/media/{rel_path:path}`（:190-199）——服务层 `media_path` 做越界检查（ValueError→400、None→404），mimetype 猜测后 `FileResponse` 回缩略图。
- **时间规律（子路由挂载）**：QQ/微信 router 各 include timeline_summary 的 `qq_router`/`wechat_router`，实际暴露 `GET /api/{qq,wechat}/forensics/imports/{id}/timeline-summary[/records]`（timeline_summary.py:114-131）。

WhatsApp 的 create_import docstring（:46-54）写明自动拾取：`db_path` 给 `ChatStorage.sqlite` 的路径**或其所在目录**，同目录的 `ContactsV2.sqlite`/`CallHistory.sqlite` 存在即自动并入（服务层 `_resolve_sources`，whatsapp_import_service.py:170-227）。

## 5. 数据流（读什么库/服务、写什么）

**写**：只写自己的导入目录——源库以只读方式打开，解密/归一化产物（明文 `nt_msg.db`、`graph.db` 等）落在 `<platform>_imports/<id>/` 下，绝不回写证据文件（whatsapp_import_service.py:16-17 docstring）。**读**：源库（导入时一次性读）与导入目录（后续所有查询直连 `graph.db`/明文库）。路由层全部经 `asyncio.to_thread`/async 服务方法，事件循环不被 sqlite 阻塞（whatsapp_forensics.py:58）。

与图谱管线的交接在 `ensure_graph_db`：`/api/wechat/graph` 解析 `qq_/wx_` 前缀时若 `graph.db` 缺失或过期会**按需重建**（wechat_graph_models.py:166-170 注释："imports whose graph build failed heal on first graph-tab visit"），QQ 侧同理（:177-188）——导入失败的库不需要重新走导入 API，访问图谱页即自愈。时间规律端点则直接读源形态：QQ 导入读 `nt_msg.db`（`qq_import` 来源）或老版读归一化 `graph.db`（`qq_legacy` 来源，timeline_summary.py:52-62），微信读 `EnMicroMsg.db`（`wechat_import`，:63）。

## 6. 边界与已知状态（错误码/降级）

- **400 vs 404 的分工**：QQ/微信把"import_id 语法不对/参数不对"（服务层 ValueError）映射 400，"导入不存在/文件丢失"（FileNotFoundError）映射 404（qq_forensics.py:62-67、wechat_forensics.py:72-77）；WhatsApp 只有 404/500 两档（whatsapp_forensics.py:60-65）。
- **500 不吞栈**：`_handle_error` 用 `logger.error(..., exc_info=True)` 记完整栈但把异常文本放进响应 detail（`<what> failed: {error}`）——与 investigation/report 域的"固定短句不泄内部异常"取向不同，这三条管道走的是调试友好路线。
- **导入是同步长操作**：POST 创建在请求内完成解密+归一化（无 job/202），大库会占住请求；没有进度端点，重试语义 = 直接再 POST 一次（生成新 import_id，旧目录残留）。
- **timeline-summary 子端点的错误面**归 TimelineSummary 管辖（409 来源变化 / 422 参数 / 503 源不可读），不经本组的 `_handle_error`。
- env/目录：`DATA_ROOT`（config.get_data_root）决定三平台导入根目录；无专属 env 开关。

## 7. 如何验证

- 前端契约与面板：`web/src/services/*ForensicsService*.js` 与 `pages/IMForensics/IMForensics.test.jsx`。
- 服务层单测在 `python_service/tests/unit/`（按平台各自的 import service/decrypt 测试文件）；时间规律子端点见 [TimelineSummary.md](TimelineSummary.md) 第 7 节。
- 活体链路：`/im-forensics` 页逐平台"导入数据库 → 概览 → 消息翻页 → 关系分析 Tab"（关系 Tab 走 `wx_/qq_<import_id>` 即验证 ensure_graph_db 自愈）。

相关阅读：[TimelineSummary.md](TimelineSummary.md)（时间规律端点）、[WechatGraph.md](WechatGraph.md)（下游图谱管线）、services 侧 [IMImportServices.md](../../services/IMImportServices.md)（解密与归一化的实现层）。

## 8. 二轮深化 A：三平台导入输入字段对照（create_import 请求体）

| 字段 | WhatsApp（:46-54） | QQ（:48-54） | 微信（:48-57） |
|---|---|---|---|
| `db_path` | ChatStorage.sqlite 路径**或目录** | nt_msg.db（加密 NTQQ 或明文） | EnMicroMsg.db（加密或明文） |
| `password` | — | 可选 32-hex 显式密钥 | 可选 SQLCipher 口令 |
| `key_material` | — | `{nt_uid, uin}`（缺 password 时推导） | `{uin, imei, wxid, account_dir}`（缺 password 时推导+留档） |
| `wal_path` | — | — | 可选 -wal（默认库旁自动探测） |
| `media_dir` | — | — | 可选账号目录（image2 等，复制缩略图） |
| `name` / `backup_source` | 人类标签 / 来源描述 | 同 | 同 |

三平台共同约束：`db_path` 为空 → 400（微信 ：59-61 显式检查；QQ :57-59；WhatsApp :56-57）。`backup_source` 是自由文本（如 MIUI 备份路径），只进 meta 留档，不参与解析。

## 9. 二轮深化 B：`wx_/qq_<import_id>` 伪任务身份的解析链

`/api/wechat/graph` 的 task_id 解析（wechat_graph_models.py:161-188）在进 C++ 查询**之前**先截胡两个前缀：

```
task_id = "qq_1a2b3c4d5e6f"
  → startswith("qq_") → qq_import_service.ensure_graph_db("1a2b3c4d5e6f")
      → meta.json 校验 + graph.db 缺失/陈旧则重建（_graph_db_stale 判 mtime）
      → 返回归一化 graph.db 绝对路径
  → 后续图谱计算把它当一份"android.db 同形状"的库读（wechat_* 四表）
```

这让关系图谱管线（WeChatGraphService）对"任务库 vs 导入库"零感知——三种数据源（真实任务 android.db、微信导入、QQ 导入）共用同一个 `/api/wechat/graph` 入口。副作用：这些伪 task_id 不能用于任何真正经 C++ `get_task` 的端点（会 404），前端 GraphTab 对此有专门的来源提示条处理（IMForensics 页）。

**最后更新**: 2026-11-10（新建：三平台 IM 取证路由文档）
