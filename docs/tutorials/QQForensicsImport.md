# QQ 取证：解密并导入 QQ 账号数据库（NTQQ nt_msg.db / 老版 QQ 4.x）

本页说明 TraceLens 「即时通讯取证」（`/im-forensics`，QQ 平台）功能：把安卓 QQ 9.x（NT 架构，
NTQQ）的 `nt_msg.db`（支持 SQLCipher 加密原件或已解密明文库）导入系统，自动
离线推导密钥并解密、解析为人类可读的取证证据（会话 / 消息 / 联系人 / 群聊），
并与同页「关系分析」Tab 无缝对接——关系图、社区检测、
时间线、聊天记录下钻等能力全部复用。

同一个导入入口还支持 **老版 QQ 4.x（pre-NTQQ，约 2013–2015）** 的明文账号库
（`databases/<QQ号>.db`），走设备 ID 异或解码支线，见
[下文专节](#老版-qq-4xpre-ntqq-账号库)。

## 快速开始

1. 打开侧边栏 **即时通讯取证**，顶部切换到 **QQ** 平台，点击 **导入数据库**。
2. 填写 `nt_msg.db` 的绝对路径（加密或明文均可；同目录的 `profile_info.db`、
   `group_info.db` 与 `-wal` 会自动一并处理）。
3. 提供 `nt_uid`（形如 `u_xxx`）用于自动推导密钥，或直接粘贴已知 32 位密钥。
4. 导入成功后即可在页面浏览：取证概览、会话列表、聊天记录（可按会话 /
   类型 / 关键词 / 时间过滤）、联系人、群聊。
5. 切换到 **关系分析** Tab，页面自动以 `qq_<导入ID>` 作为 task_id 生成关系图谱。

## 密钥推导（全部离线）

| 步骤 | 公式 / 位置 |
|---|---|
| 1. nt_uid | 备份内 `f/uid/<QQ号>###u_xxx` 文件名（或 `gpro_v1-6_u_xxx.db` 文件名） |
| 2. uid_hash | `md5(nt_uid)` |
| 3. 目录哈希 | `md5(uid_hash + "nt_kernel")` —— 即 `nt_qq_<目录哈希>` 目录名，可交叉验证 |
| 4. rand | 库头 1024B 自定义头（"QQ_NT DB" 标记）内 protobuf field2 |
| 5. key | `md5(uid_hash + rand)`，32 位 hex，以字符串形式作为 SQLCipher 密钥 |

实测账号：QQ `2874289874`，nt_uid `u_UJEcIMaQtYqv4WxT5Bl30Q`，
rand `7VklrMEZ`，推导密钥 `55a19994a4b6ed150c98ec6d7889c4af`。

## SQLCipher 参数（遍历实测确认）

| 参数 | 值 |
|---|---|
| 算法 | SQLCipher 4 |
| cipher_page_size | 4096 |
| kdf_iter | 4000 |
| cipher_hmac_algorithm | HMAC_SHA1 |
| cipher_kdf_algorithm | **PBKDF2_HMAC_SHA512**（注意不是 SHA1） |
| 前置处理 | 必须剥掉文件前 1024B 自定义头（salt 在其后） |
| WAL | 加密帧，交给 sqlcipher 连接自动回放（无需手工合并） |

完整过程记录见 [QQ 数据库解密过程](./QQDecryptionProcess.md)。

## 字段可读化

QQ NT 消息表列名为数字编码，导入时按逆向文档（QQBackup/nt_msg_db_util）
映射为可读字段：

| 列 | 含义 |
|---|---|
| 40001 | 消息唯一 ID（主键） |
| 40010 / 40011 | chatType（1=私聊 2=群聊）/ 外层消息类型 |
| 40013 | 方向（0=收到，1/2=本人发送，3=系统） |
| 40020 / 40021 | 发送者 NT UID / 会话对象 UID |
| 40030 / 40033 | 对方 QQ 号（或群号）/ 发送者 QQ 号 |
| 40050 | 消息时间（Unix 秒） |
| 40090 / 40093 | 群名片 / 发送者昵称 |
| 40800 | 消息体 Protobuf：`MsgBody.content(40800)` → `MsgContent{45002 内容类型, 45101 文本}` |

昵称来自 `profile_info.db`（列 1002=QQ号、20002=昵称），群名来自
`group_info.db`（60001=群号、60007=群名）；注意 `profile_info_v6` 是名片
缓存（可含上千条无关资料），只取消息中实际出现过的联系人。

## 老版 QQ 4.x（pre-NTQQ）账号库

同一导入入口（`POST /api/qq/forensics/imports`，请求体字段不变）自动识别老版
账号库——判定条件（`qq_legacy.looks_legacy_qq4`）：SQLite 明文魔数 + 文件名为
`<5–12 位数字>.db`（即 `databases/<QQ号>.db`）+ 同时存在 `Friends` 与
`TroopMemberInfo` 表。命中即走 `format=legacy_qq4` 支线，**没有解密环节**：
库本身是明文 SQLite，只有 TEXT 列被设备 ID 逐字节 XOR 混淆。

### 密钥材料：设备 ID（而非数据库密钥）

老版 QQ 用设备 ID（微信 `CompatibleInfo.cfg` 258 键存的同一标识，
`a00000420ce2b6` 风格）作为 XOR 密钥。解析顺序：

1. 请求体 `key_material.device_id` 显式提供（优先尝试）；
2. 自动收集：同镜像微信数据目录下的 `com.tencent.mm/MicroMsg/[/<账号目录>/]CompatibleInfo.cfg`
   （键 258，回退 256），Java 序列化 HashMap 解析；
3. 逐个候选验证：**≥80% 的 `Friends.uin` 异或解码后为 5 位以上纯数字** 才采纳
   （`validate_key`）。全部失败则导入 `status=failed`，错误信息提示提供
   `key_material.device_id`。

```bash
curl -X POST http://localhost:8090/api/qq/forensics/imports \
  -H "Content-Type: application/json" \
  -d '{
    "db_path": "/evidence/miui_backup/apps/com.tencent.mobileqq/databases/123456789.db",
    "key_material": {"device_id": "a00000420ce2b6"},
    "name": "老版QQ-123456789",
    "backup_source": "MIUI 备份（案件 xx）"
  }'
```

`device_id` 可省略——镜像里同时有微信数据时通常能自动收集成功；验证依据
（`decryption.source` 字段记录 `CompatibleInfo.cfg(258/256)` 还是
`key_material.device_id`）会写进 meta.json，可作鉴定留痕。

### 可恢复面与归一化

| 源表 | 内容 |
|---|---|
| `Friends` | uin / 昵称 / 备注（好友列表） |
| `TroopInfo` | 群号 / 群名 |
| `TroopMemberInfo` | 群成员关系 |
| `mr_troop_<md5(uin)>_New` / `mr_friend_<md5>_New` | 漫游消息，`msgData` XOR 后即 UTF-8 正文 |

提取结果归一化进与 NTQQ 相同的 `graph.db`（wechat_* 四表，时间戳为毫秒——
源库秒值 ×1000），**不产出 nt_msg.db**：概览 / 会话 / 消息 / 联系人 / 群聊
五个读接口对 legacy 导入直接从 graph.db 作答，`/api/wechat/graph?task_id=qq_<导入ID>`
关系图谱同样可用。边界：只有 `msgtype=-1000`（纯文本）的行才解码正文，其它
类型的二进制载荷（protobuf/XML）不会泄入内容列；昵称/群名超过密钥周期仍可能
保持乱码（解码失败时回退 QQ 号，不写乱码进图谱）。

## 时间规律（timeline-summary）

QQ 导入挂载 `GET /api/qq/forensics/imports/{id}/timeline-summary`
（及 `.../timeline-summary/records`，按原统计 token 回查记录）。后端按导入
`format` 选择只读来源（`timeline_sources.TimelineSource`）：

| 导入类型 | 来源库 | kind | 时间戳单位 | 方向语义 |
|---|---|---|---|---|
| NTQQ（默认） | `nt_msg.db`（解密副本） | `qq_import` | 秒 | 40013：0=收，1/2=发，3=系统 |
| 老版 QQ 4.x | `graph.db` 的 `wechat_messages` 投影 | `qq_legacy` | 毫秒 | `is_send`：1=发，0=收 |

两种 kind 的 `event_source` 均为 `QQ`；统计内容（按时区/日期聚合、活跃时段、
top 会话等）与微信导入的时间规律接口一致。微信侧对应路由是
`/api/wechat/forensics/imports/{id}/timeline-summary`（`wechat_import` kind，
读解密后的 `EnMicroMsg.db`）。

## 相关实现

- 解密：`python_service/httpserver/services/qq_decrypt.py`
- 导入 / 解析：`python_service/httpserver/services/qq_import_service.py`
  （NTQQ 与 legacy_qq4 两个分支）
- 老版 QQ 4.x 提取：`python_service/httpserver/services/qq_legacy.py`
  （识别 / 设备 ID 收集与验证 / XOR 解码 / mr_* 消息读取）
- 时间规律：`python_service/httpserver/routes/timeline_summary.py` +
  `python_service/httpserver/services/timeline_sources.py`
  （`qq_import` / `qq_legacy` / `wechat_import` 三种来源适配）
- API：`python_service/httpserver/routes/qq_forensics.py`（`/api/qq/forensics/*`）
- 前端：`web/src/pages/IMForensics/IMForensics.jsx`（QQ 面板 `QQPanels.jsx`）
- 与关系分析对接：`/api/wechat/*` 支持 `task_id=qq_<导入ID>`
  （`wechat_graph_models._resolve_android_db_path`），导入时构建与微信同构的
  `graph.db`（wechat_messages / wechat_contacts / wechat_chatrooms /
  wechat_owner_info）

测试：`python_service/tests/unit/test_qq_forensics_import.py`
（密钥链 / 头解析 / 消息体解码 / 加解密往返 / 可读字段 / graph.db 归一化）；
`python_service/tests/unit/test_qq_legacy_import.py`
（老版库识别 / 设备 ID 收集与验证 / XOR 往返 / graph.db 端到端）。

**最后更新**: 2026-11-10（补充老版 QQ 4.x 导入与 timeline-summary 说明）
