# iOS 逻辑备份取证（iTunes / Finder）

本文件说明当前分支对 iOS 逻辑备份的识别、解析与证据链行为。iOS 与 Android 共用同一个 `android.db` 表结构与下游查询/报告链路，因此两者的覆盖度、结果集冻结、报告证据判定行为一致。

## 支持的输入

iTunes / Finder 逻辑备份目录。识别依据是目录中存在 `Manifest.plist` + `Manifest.db`：

- 可直接指向备份目录本身（`.../<UDID>/`）；
- 也可指向只包含该备份的包装目录（解压归档常见的 `extract/<案件名>/<UDID>/`，最多向下查找 2 层）。

`Manifest.db` 的 `Files` 表是权威索引：`fileID` 是分片文件名（SHA-1），`domain` + `relativePath` 是逻辑路径。解析器按 `<domain>/<relativePath>` 定位分片，例如 `HomeDomain/Library/SMS/sms.db`。

## 加密备份

`Manifest.plist` 的 `IsEncrypted` 为真时：

- 预检返回 `ios_backup_encrypted`、`ready=false`、`reason=encrypted_backup_requires_password`；
- 分析阶段 `IosBackupExtractor::initialize()` 返回 `IOS_BACKUP_ENCRYPTED`，任务失败并保留该错误码；
- **不会**解出空表后声称"已解析"。

当前不支持解密。带密码的加密备份需要先离线解密再作为普通备份目录接入。

## 解析的工件

| 工件 | 来源逻辑路径 | 落表 |
|---|---|---|
| 短信 / iMessage | `HomeDomain/Library/SMS/sms.db` | `sms_messages` |
| 通讯录 | `HomeDomain/Library/AddressBook/AddressBook.sqlitedb` | `contacts` |
| 备忘录 | `HomeDomain/Library/Notes/notes.sqlite` | `app_notes` |
| 日历 | `HomeDomain/Library/Calendar/Calendar.sqlitedb` | `app_notes` |
| 通话记录 | `HomeDomain/Library/CallHistoryDB/CallHistory.storedata` | `call_logs` |
| Safari 历史 | `HomeDomain/Library/Safari/History.db` | `chrome_history` |
| 应用清单 | 各 `AppDomain-*` / `AppDomainPlugin-*` 域 | `installed_packages` |
| 备份清单 | `Manifest.plist` + `Manifest.db` | `mobile_backup_manifest` |

通话记录与 Safari 历史只在**完整备份**中存在。iCloud 式的部分备份（`Status.plist` 的 `IsFullBackup=false`）两者都缺，覆盖度会如实写 `no_candidate_path`。

通话记录解析 `ZCALLRECORD`，按实际列名适配（`ZADDRESS` 或 `ZREMOTEPARTICIPANT`），`ZDURATION` 是浮点秒、写入前取整。Safari 解析 `history_items` 与 `history_visits`，按 `history_item` 聚合出访问次数与最后访问时间。

`mobile_backup_manifest` 写入 `platform=iOS`、`device=<机型> / iOS <版本>`、`backup_version`、`module_count`（应用数）与 `Manifest.db` 的 SHA-256，供页面徽章与覆盖度卡片直接读取。

## 时间戳

iOS 用 Apple 纪元（2001-01-01），多数 Core Data 存储是纳秒：

- `toUnixSeconds()` 按量级分类：`>1e14` 视为 Apple 纳秒，`<1.2e9` 视为 Apple 秒，其余按 Unix 秒；
- 写入 `sms_messages.date` 保留原始数值，`date_seconds` 写换算后的 Unix 秒；
- `classifyTimestamp()` 返回 `apple_epoch_ns` / `apple_epoch_s` / `unix_s` 供审计。

换算常量 `kAppleEpochOffset = 978307200`（2001-01-01 相对 1970-01-01 的秒数）。

## 覆盖度语义

每个候选工件都写一行 `android_source_coverage`：

- `PARSED`：解析出至少一行，detail 带条数；
- `staged_for_parser`：字节已取出但库返回零行（库为空，或该 schema 变体不在解析范围内）；
- `no_candidate_path`：`Manifest.db` 中没有该路径——**记录不存在不等于数据不存在**；
- `extract_failed`：索引有条目但分片拷贝失败。

`android_coverage_status` 由既有逻辑统一计算（`parsed > 0` 且 `unresolved == 0` 才算完整）。因此一个只有短信和通讯录的备份会如实报告 `incomplete`，而不是伪装成完整解析。

## 证据链

iOS 记录与 Android 记录走同一条冻结路径：

1. `GET .../android-artifacts/{kind}/{row_id}` 返回 `record_hash` 与 `source_revision`；
2. `POST .../android-artifacts/{kind}/{row_id}/capture` 用这两个 token 冻结，返回 `evidence_key = android_artifact:v1:<task_id>:<result_set_id>:<kind>:<row_id>`；
3. 该 key 可直接用于 Investigation 与报告证据判定。

来源粒度是**派生库版本**（`source_identity_granularity=derived_database_version`）：冻结的是 `android.db` 快照中的行，不宣称绑定原始手机库的物理行或 WAL frame。读取接口会带出对应的 `warning`。

## 即时通讯（IM）

WhatsApp 已作为与微信、QQ 并列的第三个平台接入即时通讯取证页（`/im-forensics?platform=whatsapp`）。它不走 Task 的 `android.db`，而是独立导入：后端把 iOS 的 Core Data 库归一化成与微信/QQ 相同的 `graph.db` 结构，因此取证概览、会话、消息、联系人、群聊五个页签与既有平台共用同一套面板。**「关系分析」与「时间规律」两个 Tab 当前不覆盖 WhatsApp 导入**：图谱服务只解析 `wx_`/`qq_` 前缀的 task_id，`/api/whatsapp` 也未挂载 timeline-summary 路由，选中 WhatsApp 导入后这两处会报"任务不存在/来源不可用"，属当前版本边界。

导入来源是 `ChatStorage.sqlite`（`AppDomainGroup-group.net.whatsapp.WhatsApp.shared` 域），同目录下的 `ContactsV2.sqlite` 与 `CallHistory.sqlite` 自动一并读取。

| iOS 表 | 归一化到 | 说明 |
|---|---|---|
| `ZWAMESSAGE` | `wechat_messages` | `ZISFROMME` 决定 `is_send`；`ZMESSAGETYPE` 存 `msg_type` 并映射中文标签 |
| `ZWACHATSESSION` | `wechat_contacts` / `wechat_chatrooms` | `ZPARTNERNAME` 是可读名称，群聊额外把 JID 存进 `owner` |
| `ZWAADDRESSBOOKCONTACT` | `wechat_contacts` | 号码补全显示名 |
| `ZWACDCALLEVENT` | `wechat_messages`（`msg_type=9`） | 通话事件进同一时间轴 |

关键约束：

- **`ZPUSHNAME` 是加密的推送名（base64 密文），不能当显示名**。解析器一律用会话的 `ZPARTNERNAME` 或号码，避免把密文写进身份字段。
- 群聊消息的 `talker` 是群 JID，会话名从 `wechat_chatrooms.owner` 反查，页面上显示的是「Healthy Motivation 💪」这类真实群名而不是 JID。
- 归一化库是派生文件，写库时关闭 `journal_mode`/`synchronous` 换取吞吐（5,000+ 条消息从 11 秒降到 0.03 秒）；源库始终以 `mode=ro` 打开。
- 导入状态用 `ready` / `parsing` / `failed`，与微信/QQ 一致。

iOS 的微信、Telegram、Signal、Facebook Messenger 等应用数据库尚未逐个适配，仅 WhatsApp 已支持。

## 未支持

- 加密备份解密；
- iCloud 同步数据、钥匙串、HealthKit 等需要额外密钥的存储；
- WhatsApp 以外的 iOS IM 应用（微信 / Telegram / Signal / Messenger 等）。

## 验证方式

```bash
# Python 预检单测
cd python_service && .venv/bin/python -m pytest tests/unit/test_ios_backup_preflight.py -q

# C++ 提取器与解析器单测
cd build && ./tests/test_ios_backup_gtest

# 真实样本端到端（需先启动 C++ 8666 与 Python 8090）
cd web && E2E_IOS_BACKUP=/path/to/extract node scripts/e2e-ios-task.mjs

# WhatsApp 三平台并列（需先启动 Python 8090 与 e2e-static-server）
cd web && E2E_WHATSAPP_DIR=/path/to/whatsapp_dir node scripts/e2e-whatsapp-im.mjs
```

E2E 脚本会在真实浏览器中点击创建任务、选择 iOS 来源、填路径与案件描述、提交，然后验证任务完成、设备徽章、覆盖度卡片与短信行内容，最后删除自己创建的任务。
