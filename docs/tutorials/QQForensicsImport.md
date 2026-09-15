# QQ 取证：解密并导入 QQ 账号数据库（NTQQ nt_msg.db）

本页说明 TraceLens 「即时通讯取证」（`/im-forensics`，QQ 平台）功能：把安卓 QQ 9.x（NT 架构，
NTQQ）的 `nt_msg.db`（支持 SQLCipher 加密原件或已解密明文库）导入系统，自动
离线推导密钥并解密、解析为人类可读的取证证据（会话 / 消息 / 联系人 / 群聊），
并与同页「关系分析」Tab 无缝对接——关系图、社区检测、
时间线、聊天记录下钻等能力全部复用。

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

## 相关实现

- 解密：`python_service/httpserver/services/qq_decrypt.py`
- 导入 / 解析：`python_service/httpserver/services/qq_import_service.py`
- API：`python_service/httpserver/routes/qq_forensics.py`（`/api/qq/forensics/*`）
- 前端：`web/src/pages/IMForensics/IMForensics.jsx`（QQ 面板 `QQPanels.jsx`）
- 与关系分析对接：`/api/wechat/*` 支持 `task_id=qq_<导入ID>`
  （`wechat_graph_models._resolve_android_db_path`），导入时构建与微信同构的
  `graph.db`（wechat_messages / wechat_contacts / wechat_chatrooms /
  wechat_owner_info）

测试：`python_service/tests/unit/test_qq_forensics_import.py`
（密钥链 / 头解析 / 消息体解码 / 加解密往返 / 可读字段 / graph.db 归一化）。
