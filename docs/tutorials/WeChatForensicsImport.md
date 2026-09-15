# 微信取证：解密并导入微信账号数据库（EnMicroMsg.db）

本页说明 TraceLens 「即时通讯取证」（`/im-forensics`，微信平台）功能：把安卓微信的
`EnMicroMsg.db`（支持 SQLCipher 加密原件或已解密明文库）导入系统，自动解密、
解析为人类可读的取证证据（会话 / 消息 / 联系人 / 群聊 / 媒体缩略图），并与
同页「关系分析」Tab 无缝对接。

## 快速开始

1. 打开侧边栏 **即时通讯取证**，确认顶部平台切换在 **微信**，点击 **导入数据库**。
2. 填写 `EnMicroMsg.db` 的绝对路径（加密或明文均可；同名 `-wal` 自动探测）。
3. 提供密钥材料（可自动推导口令，见下）或直接填口令，点击 **开始导入**。
4. 导入成功后即可在页面浏览：取证概览、会话列表、聊天记录（可按会话 /
   类型 / 关键词 / 时间过滤）、联系人、群聊。
5. 切换到 **关系分析** Tab，页面自动以 `wx_<导入ID>` 作为 task_id 生成关系图谱。

## 密钥推导（与手动破解流程一致）

主库口令 = `MD5(IMEI + UIN)[:7]`；FTS 索引库 = `MD5(UIN + IMEI + wxid)[:7]`。

| 材料 | 获取位置（备份内） |
|---|---|
| UIN | `shared_prefs/system_config_prefs.xml` 的 `default_uin`；`files/recovery_v3/last_uin` |
| IMEI | `files/KeyInfo.bin`（17 字节，RC4 密钥 `_wEcHAT_`）；取不到时为固定值 `1234567890ABCDEF` |
| wxid | `shared_prefs/com.tencent.mm_preferences.xml` 的 `login_weixin_username` |
| 交叉验证 | 账号目录名 = `MD5("mm" + UIN)` |

导入时只要提供 UIN（必要时补充 IMEI / wxid），服务端会依次尝试候选公式，
用**页面级检测**（解密第 1 页比对 SQLite 页头特征）确认口令与参数，
不依赖 SQLCipher 工具（可绕开 "file is not a database" 的 HMAC 误报陷阱）。

## 实测加密参数（微信 8.0.76）

| 方案 | 页大小 | KDF | 保留区 | 适用库 |
|---|---|---|---|---|
| A（主库） | 1024 | PBKDF2-HMAC-SHA1 ×4000 → 32B | 16B（IV 页尾，无 HMAC） | EnMicroMsg.db 等 |
| B（FTS） | 4096 | PBKDF2-HMAC-SHA1 ×64000 | 48B（IV 前 16B + 32B 校验） | FTS5IndexMicroMsg_encrypt.db |

WAL 一并解密：逐帧解密后按 SQLite 校验和算法（魔数 `0x377f0682`，小端）
重算帧校验链，再合并进主库，保证最新消息不丢。

完整过程记录见 [微信数据库解密过程](./WeChatDecryptionProcess.md)。

## 字段可读化

- 群消息按 `wxid:\n` 前缀拆分真实发送者，并解析为备注 / 昵称（含
  `chatroom.roomdata` protobuf 中最佳努力提取的群成员昵称）。
- 消息类型映射为中文标签（文本 / 图片 / 语音 / 动画表情 / 引用回复 /
  系统消息…），XML / protobuf / 表情码等原始内容不直接展示。
- 图片消息映射备份中的 `image2/xx/yy/th_<hash>` 缩略图并在页面内预览
  （导入时提供含 `image2/` 的账号目录作为媒体目录）。

## 相关实现

- 解密：`python_service/httpserver/services/wechat_decrypt.py`
- 导入 / 解析：`python_service/httpserver/services/wechat_import_service.py`
- API：`python_service/httpserver/routes/wechat_forensics.py`（`/api/wechat/forensics/*`）
- 前端：`web/src/pages/IMForensics/IMForensics.jsx`（微信面板 `WeChatPanels.jsx`）
- 与关系分析对接：`/api/wechat/*` 支持 `task_id=wx_<导入ID>`
  （`wechat_graph_models._resolve_android_db_path`）

测试：`python_service/tests/unit/test_wechat_forensics_import.py`
（加密 / 解密 / 口令推导 / 可读字段 / graph.db 归一化）。
