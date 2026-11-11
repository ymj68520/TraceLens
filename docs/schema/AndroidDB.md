# android.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/android_analysis_sql.h` + `SQL/android_analysis_sql_llm.h` + `src/analyzers/AndroidAnalyzer/MobileBackupSchema.h`）

> android.db 是 files.db 的**平台语义观点**（DatabaseSchema.md 派生链：files.db → android.db）：把"Android 镜像里有一批文件"翻译成"这是一台什么设备、谁在跟谁聊什么"。建表集中在 `android_analysis_sql.h`（SQL-as-headers，决定三）；14 张被 LLM 服务分析的表在初始化时动态补 5 个 llm_* 列（`AndroidAnalysisDatabase::addLlmColumns`，`src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp:906`）；另有 2 张**统一手机备份表**由各适配器运行时按 `MobileBackupSchema.h` 的 DDL 动态建。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `AndroidAnalysisDatabase::createTables()`（`AndroidAnalysisDatabase.cpp:34-79`）：执行 6 个 CREATE 块——`CREATE_ALL_TABLES`（21 表）+ `CREATE_MIUI_TABLES`（12 表）+ `CREATE_ANALYSIS_PROGRESS`（1 表）+ `CREATE_SOURCE_COVERAGE`（1 表）+ `CREATE_CONTAINER_PROVENANCE`（2 表）+ `CREATE_FILESYSTEM_PROVENANCE`（2 表），共 39 表；随后幂等迁移：`wechat_messages.source_path`（`:45-54`，PRAGMA table_info 检查后 ALTER）、`sms_messages`/`call_logs` 的 `date_seconds` 与 `wechat_contacts.mobile`（`:59-61` addColumnIfMissing），最后给 14 张表补 llm_* 列（`:65-77`）。行数据由 AndroidAnalyzer 各解析器经 `insertXxx` 方法写入；`mobile_backup_manifest`/`mobile_artifacts` 两表由适配器/统一取数包分析按需执行 `mobile_backup_schema::DDL` 现建（`HarmonyArtifactParsers.cpp:39`、`ThunderForensicArtifactParsers.cpp:1114`、`VivoArtifactParsers.cpp:85,116`、`IosArtifactParsers.cpp:480`、`MobileEvidenceAnalysis.cpp:248`） |
| 谁读 | HTTP 查询路由（`AndroidQueries.cpp`，其中 `:191` 读 mobile_backup_manifest、`:166-195` 读 mobile_artifacts）、Web 前端 MIUI 备份页、`AndroidLLMAnalysisService`（pending 分析 SELECT 见 `android_analysis_sql_llm.h`；mobile_artifacts 的 pending SELECT 内联在 `AndroidLLMAnalysisService_Database.cpp:141-158`） |
| 写入方全景 | Android 物理镜像/逻辑源（AndroidAnalyzerCore）、MIUI 备份（MiuiArtifactParsers）、鸿蒙备份（HarmonyArtifactParsers）、OPPO/vivo/一加等雷电快取（ThunderForensicArtifactParsers + VivoArtifactParsers）、**iOS 备份**（IosArtifactParsers——iOS 工件直接落本库同构表，`IosArtifactParsers.h:3` "Parses iOS backup artifacts into the shared android.db schema"）、统一取数包回写（MobileEvidenceAnalysis） |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/android.db`；CLI 集成模式并入 files.db 的 `android_artifacts`（见 [FilesDB.md](./FilesDB.md)）。统一取数包任务另有独立的 `<base>_mobile_evidence.mep.db`（见 [MobileEvidenceDB.md](./MobileEvidenceDB.md)） |

## 表清单总表（41 张）

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `sms_messages` | 通信 | 短信（mmssms.db 抽取；亦收 iOS/iMessage 解析） | 12(+5 llm) |
| `contacts` | 通信 | 联系人（contacts2.db；亦收 iOS AddressBook） | 7(+5) |
| `call_logs` | 通信 | 通话记录（亦收 iOS CallHistory） | 8(+5) |
| `whatsapp_messages` | 通信 | WhatsApp 消息 | 7(+5) |
| `telegram_messages` | 通信 | Telegram 消息 | 7(+5) |
| `wechat_messages` | 微信 | 微信消息（SQLCipher 解密后） | 13(+5) |
| `wechat_contacts` | 微信 | 微信联系人（含 mobile 强关联键） | 8 |
| `wechat_chatrooms` | 微信 | 微信群聊 | 6 |
| `wechat_owner_info` | 微信 | 机主身份（username/uin/imei） | 5 |
| `wechat_artifact_inventory` | 微信(MIUI) | 备份内微信工件文件清单 | 12 |
| `wechat_kv_records` | 微信(MIUI) | 微信 KV（shared_prefs 等）记录 | 9(+5) |
| `wechat_sqlite_records` | 微信(MIUI) | 微信 SQLite 明细记录 | 7(+5) |
| `wechat_log_events` | 微信(MIUI) | 微信日志事件 | 8 |
| `qqnt_artifact_inventory` | QQNT | 备份内 QQNT 工件文件清单 | 12 |
| `qqnt_kv_records` | QQNT | QQNT KV 记录 | 9 |
| `qqnt_sqlite_records` | QQNT | QQNT SQLite 明细记录 | 7(+5) |
| `qqnt_log_events` | QQNT | QQNT 日志事件 | 8 |
| `system_build_properties` | 设备与系统 | build.prop 键值 | 3 |
| `system_apps` | 设备与系统 | 系统应用清单 | 7 |
| `framework_files` | 设备与系统 | framework 目录文件清单 | 5 |
| `system_logs` | 设备与系统 | logcat 类系统日志 | 9(+5) |
| `device_identifiers` | 设备与系统 | SSAID/Android ID 等设备标识 | 5(+5) |
| `wifi_networks` | 设备与系统 | WiFi 配置（含 PSK） | 5(+5) |
| `chrome_history` | 设备与系统 | Chrome/Safari 浏览历史 | 6 |
| `installed_packages` | 应用 | 已装包（packages.xml；iOS 备份亦写，installer='ios-backup'） | 8 |
| `installed_apps` | 应用(MIUI) | MIUI 备份 manifest 应用清单 | 9(+5) |
| `usage_stats` | 应用 | 应用使用统计 | 5 |
| `app_database_files` | 应用 | 应用私有数据库文件清单 | 5 |
| `app_notes` | 应用 | 便签类应用笔记（亦收 iOS 备忘录/日历） | 8 |
| `app_db_inventory` | 应用(MIUI) | 备份内可开库的 DB 盘点 | 7 |
| `miui_external_files` | 应用(MIUI) | MIUI 备份外部存储（sdcard/）文件清单 | 7 |
| `miui_backup_manifest` | 备份与加密 | MIUI 备份清单头 | 7(+5) |
| `encrypted_db_inventory` | 备份与加密 | SQLCipher 加密库及密钥线索盘点 | 7 |
| `mobile_backup_manifest` | 统一备份 | 厂商中立单行备份清单头（鸿蒙/雷电/vivo/iOS） | 8 |
| `mobile_artifacts` | 统一备份 | 厂商中立规范化记录（自带 5 个 llm_* 列） | 21 |
| `android_source_coverage` | 溯源与覆盖 | 按工件种类的源文件解析覆盖 | 5 |
| `android_source_provenance` | 溯源与覆盖 | 归档成员级溯源（容器哈希→规范路径） | 8 |
| `android_container_coverage` | 溯源与覆盖 | 容器成员提取覆盖（七态状态机） | 5 |
| `android_filesystem_provenance` | 溯源与覆盖 | 镜像派生文件的分区/inode 级溯源 | 14 |
| `android_filesystem_metrics` | 溯源与覆盖 | 单镜像文件系统遍历性能指标 | 8 |
| `android_analysis_progress` | 进度 | LLM 分析进度（task×table 粒度） | 7 |

(+5) 表示初始化时由 `addLlmColumns` 追加 `llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, llm_model_used TEXT` 五列（列表见 `AndroidAnalysisDatabase.cpp:65-71` kLlmTables，幂等 ALTER，重开库安全）；`mobile_artifacts` 的 5 列是建表内联的（`MobileBackupSchema.h:23`），不在 kLlmTables 名单。

## 逐表字段说明

### 分组一：通信（5 张）

手机取证的核心叙事：谁（contacts）、用什么号（sms/call_logs）、在哪个 App（whatsapp/telegram）说了什么。这组表列名刻意贴近各自源库（mmssms.db / WhatsApp msgstore），抽取时零改名。

#### sms_messages（`android_analysis_sql.h:37-52`，写入 `AndroidAnalysisDatabase.cpp:158-160` 5 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| thread_id | INTEGER | — | 会话线程 ID（源库） |
| address | TEXT | — | 对端号码 |
| person | TEXT | — | 联系人名（可反查 contacts） |
| date | INTEGER | — | 收/发时刻（**保留来源原值**：MIUI 为毫秒、雷电/美亚为秒，`:49-50` 注释） |
| date_sent | INTEGER | — | 发送时刻 |
| read | INTEGER | — | 已读标志 |
| status | INTEGER | — | 投递状态码 |
| type | INTEGER | — | 方向：1 收 / 2 发（源库惯例） |
| body | TEXT | — | 正文 |
| service_center | TEXT | — | 短信中心号码 |
| date_seconds | INTEGER | — | **规范化的秒级时间**（跨源排序与合并只读它，避免下游猜单位；旧库由 `addColumnIfMissing` 补，`AndroidAnalysisDatabase.cpp:59`） |

#### contacts（`:53-61`，写入 `AndroidAnalysisDatabase.cpp:178` 2 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| raw_contact_id | INTEGER | — | 源库 raw contact id |
| display_name | TEXT | — | 显示名 |
| phone_number | TEXT | — | 号码（当前抽取仅写 display_name/phone_number） |
| email | TEXT | — | 邮箱 |
| account_type | TEXT | — | 账户类型（本地/Exchange...） |
| account_name | TEXT | — | 账户名 |

#### call_logs（`:62-71`，写入 `AndroidAnalysisDatabase.cpp:191-193` 5 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| number | TEXT | — | 对端号码 |
| date | INTEGER | — | 通话开始时刻（源库原值） |
| duration | INTEGER | — | 时长（秒） |
| type | INTEGER | — | 1 进 / 2 出 / 3 未接 |
| name | TEXT | — | 联系人名 |
| geocoded_location | TEXT | — | 归属地 |
| date_seconds | INTEGER | — | 规范化秒级时间（同 sms_messages） |

#### whatsapp_messages / telegram_messages（`:72-80`、`:81-89`，两表同构，写入 `:210`/`:225` 4 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| sender | TEXT | — | 发送者标识 |
| receiver | TEXT | — | 接收者标识 |
| content | TEXT | — | 消息正文 |
| timestamp | INTEGER | — | 时刻 |
| media_url | TEXT | — | 媒体文件引用 |
| media_type | TEXT | — | 媒体类型（图片/语音/视频） |

### 分组二：微信（8 张）

wechat_messages/contacts/chatrooms/owner_info 存**解密后内容**（SQLCipher 解密支持 `--wechat-password`、`--backup-password[-stdin|-fd]`，见 Security.md）；后 4 张 `wechat_*`（MIUI 备份系列）与 QQNT 系列同构，存**备份文件工件**本身。建表注释（`:270-272`）原文："WeChat (com.tencent.mm) evidence mirrors the QQNT inventory tables so the MIUI backup page can present file-evidence + recovered structured records alongside the existing decrypted-content tables."

#### wechat_messages（`:90-104`，写入：增强版 `AndroidAnalysisDatabase.cpp:254-258` 10 列 / 基础版 `:240` 4 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| source_path | TEXT | — | 消息来源库路径（旧任务库由 `ALTER TABLE ... ADD COLUMN` 补，`AndroidAnalysisDatabase.cpp:45-54`） |
| sender | TEXT | — | 发送者 wxid |
| receiver | TEXT | — | 接收者 wxid |
| content | TEXT | — | 正文 |
| timestamp | INTEGER | — | 时刻 |
| media_url | TEXT | — | 媒体引用 |
| media_type | TEXT | — | 媒体类型 |
| msg_type | INTEGER | DEFAULT 1 | 微信消息类型码（1 文本，其他为图片/系统等） |
| is_send | INTEGER | DEFAULT 0 | 1 = 机主发出 |
| chatroom_name | TEXT | — | 群聊标识（单聊为空） |
| sender_nickname | TEXT | — | 群内发送者昵称 |
| talker | TEXT | — | 会话对方/群 Talker 字段 |

#### wechat_contacts（`:105-116`，写入 `INSERT_WECHAT_CONTACT_WITH_MOBILE` `android_analysis_sql.h:342-346`，实现 `AndroidAnalysisDatabase.cpp:395-411` 7 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | UNIQUE | wxid |
| nickname | TEXT | — | 昵称 |
| remark | TEXT | — | 备注名 |
| avatar_path | TEXT | — | 头像文件路径 |
| type | INTEGER | — | 联系人类型码 |
| chatroom_flag | INTEGER | DEFAULT 0 | 1 = 群聊联系人 |
| mobile | TEXT | — | 绑定手机号（建表注释 `:113-114`："rcontact.mobile: the only strong key linking a WeChat identity to dialler / contacts / SMS identities"——微信身份与通话/短信身份互认的唯一强键；旧库由 `addColumnIfMissing` 补，`AndroidAnalysisDatabase.cpp:61`）。UPSERT 语义：username 冲突时仅当新值非空才覆盖（`sql.h:345-346`） |

#### wechat_chatrooms（`:117-124`，写入 `AndroidAnalysisDatabase.cpp:414`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| chatroom_name | TEXT | UNIQUE | 群 id |
| owner | TEXT | — | 群主 wxid |
| member_list | TEXT | — | 成员列表（序列化文本） |
| member_count | INTEGER | — | 成员数 |
| create_time | INTEGER | — | 建群时刻 |

#### wechat_owner_info（`:125-131`，写入 `AndroidAnalysisDatabase.cpp:430`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | UNIQUE | 机主 wxid |
| nickname | TEXT | — | 机主昵称 |
| uin | INTEGER | — | 微信 UIN（跨设备追踪关键值） |
| imei | TEXT | — | 绑定 IMEI（旧版库加密盐） |

#### wechat_artifact_inventory / qqnt_artifact_inventory（`:273-280`、`:244-251`，两表同构）

MIUI 备份内按文件盘点：备份里有什么证据文件、是否已解析。写入方为 MIUI 备份解析器（`UNIQUE(package_name, source_path)` 防重）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL, UNIQUE 组合 | 应用包名 |
| source_path | TEXT | NOT NULL, UNIQUE 组合 | 工件在备份内路径 |
| bak_file | TEXT | — | 所属 .bak 卷 |
| artifact_category | TEXT | — | 工件类别（db/xml/log...） |
| format | TEXT | — | 格式 |
| size | INTEGER | — | 字节数 |
| modified_time | INTEGER | — | 修改时刻 |
| type_flag | TEXT | — | 类型标记 |
| parse_status | TEXT | — | 解析状态（pending/ok/failed） |
| summary | TEXT | — | 摘要 |
| source_hash | TEXT | — | 源文件哈希（防篡改对质） |

#### wechat_kv_records / qqnt_kv_records（`:281-286`、`:252-257`，同构）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| source_path | TEXT | NOT NULL | 来源文件 |
| namespace | TEXT | — | KV 命名空间（shared_prefs 文件名等；`namespace` 是 SQL 关键字，SQLite 容忍作列名） |
| key | TEXT | NOT NULL | 键 |
| value_type | TEXT | — | 值类型 |
| value_text | TEXT | — | 值 |
| value_hash | TEXT | — | 值哈希 |
| is_sensitive | INTEGER | DEFAULT 0 | 1 = 含敏感标识（LLM 调度优先，`android_analysis_sql_llm.h:57-60` 注释：优先 uin/imei/mac/device） |
| parse_status | TEXT | — | 解析状态 |

#### wechat_sqlite_records / qqnt_sqlite_records（`:287-292`、`:258-263`，同构）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| source_path | TEXT | NOT NULL | 来源 DB 路径 |
| table_name | TEXT | NOT NULL | 源表名 |
| record_key | TEXT | — | 记录键 |
| record_json | TEXT | — | 记录 JSON 全文 |
| artifact_kind | TEXT | — | 工件归类 |
| is_sensitive | INTEGER | DEFAULT 0 | 敏感标志 |

#### wechat_log_events / qqnt_log_events（`:293-298`、`:264-269`，同构）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| source_path | TEXT | NOT NULL | 来源日志文件 |
| event_time | INTEGER | — | 事件时刻 |
| level | TEXT | — | 级别 |
| tag | TEXT | — | 日志 tag |
| message | TEXT | — | 日志正文 |
| parse_status | TEXT | — | 解析状态 |
| is_sensitive | INTEGER | DEFAULT 0 | 敏感标志 |

### 分组三：设备与系统（7 张）

回答"这是台什么设备、连过哪些网、看过哪些网页"。

#### system_build_properties（`:15-19`，写入 `AndroidAnalysisDatabase.cpp:93`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| property_key | TEXT | NOT NULL UNIQUE | 属性名（ro.product.model 等） |
| property_value | TEXT | — | 属性值 |

#### system_apps（`:20-29`，写入 `AndroidAnalysisDatabase.cpp:104`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL, UNIQUE 组合 | 包名 |
| apk_path | TEXT | NOT NULL, UNIQUE 组合 | APK 路径 |
| version_name | TEXT | — | 版本名 |
| version_code | TEXT | — | 版本号（注意 TEXT，非 INTEGER） |
| is_system_app | INTEGER | DEFAULT 1 | 系统预装 |
| is_privileged | INTEGER | DEFAULT 0 | 特权应用（/system/priv-app） |

#### framework_files（`:30-36`，写入 `AndroidAnalysisDatabase.cpp:119`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_name | TEXT | NOT NULL | 文件名 |
| file_path | TEXT | NOT NULL UNIQUE | 路径 |
| file_type | TEXT | — | 类型 |
| file_size | INTEGER | — | 字节数 |

#### system_logs（`:172-182`，写入 `AndroidAnalysisDatabase.cpp:508` 8 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 日志时刻 |
| log_level | TEXT | — | 级别（V/D/I/W/E） |
| tag | TEXT | — | logcat tag |
| process | TEXT | — | 进程名 |
| pid | INTEGER | — | 进程号 |
| message | TEXT | — | 正文 |
| log_file | TEXT | — | 来源日志文件（回溯证据） |
| log_source | TEXT | — | 来源类型 |

#### device_identifiers（`:184-190`，SQL 注释："Android SSAID / per-app 'Android ID' values from settings_ssaid.xml"，写入 `AndroidAnalysisDatabase.cpp:528`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| identifier_type | TEXT | NOT NULL | 标识类型（SSAID/ANDROID_ID/...） |
| value | TEXT | NOT NULL | 值 |
| package_name | TEXT | — | 所属应用（SSAID 按应用隔离） |
| source_path | TEXT | — | 来源文件路径 |

#### wifi_networks（`:132-138`，写入 `AndroidAnalysisDatabase.cpp:445`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| ssid | TEXT | NOT NULL | 网络名 |
| pre_shared_key | TEXT | — | 明文 PSK（高危证据） |
| key_mgmt | TEXT | — | 认证方式（WPA-PSK...） |
| last_connected | INTEGER | — | 最近连接时刻 |

#### chrome_history（`:139-146`，写入 `AndroidAnalysisDatabase.cpp:459` 4 列；iOS Safari 历史经 `IosArtifactParsers.cpp:404,429` 亦落此表）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| url | TEXT | NOT NULL | URL |
| title | TEXT | — | 页面标题 |
| visit_count | INTEGER | — | 访问次数 |
| last_visit_time | INTEGER | — | 最近访问（Chrome epoch，1601 起 微秒） |
| typed_count | INTEGER | — | 手输次数 |

### 分组四：应用（7 张）

#### installed_packages（`:147-156`，写入 `AndroidAnalysisDatabase.cpp:474`；iOS 备份亦写：`IosArtifactParsers.cpp:440-472`，installer='ios-backup'、code_path='AppDomain-<bundle>'）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL UNIQUE | 包名 |
| code_path | TEXT | — | APK 所在目录 |
| native_library_path | TEXT | — | so 库目录 |
| first_install_time | INTEGER | — | 首装时刻 |
| last_update_time | INTEGER | — | 最近升级时刻 |
| version | TEXT | — | 版本 |
| installer | TEXT | — | 安装来源（com.android.vending / ios-backup） |

#### usage_stats（`:157-163`，写入 `AndroidAnalysisDatabase.cpp:493`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | — | 包名 |
| total_time_foreground | INTEGER | — | 前台累计时长（毫秒） |
| last_time_used | INTEGER | — | 最近使用 |
| interval_start | INTEGER | — | 统计区间起点 |

#### app_database_files（`:164-171`，写入 `android_analysis_sql.h:367` 4 列 INSERT OR IGNORE）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL, UNIQUE 组合 | 包名 |
| file_name | TEXT | NOT NULL | DB 文件名 |
| file_path | TEXT | NOT NULL, UNIQUE 组合 | DB 路径 |
| file_size | INTEGER | DEFAULT 0 | 字节数 |

#### app_notes（`:192-201`，写入 `AndroidAnalysisDatabase.cpp:545`；iOS 备忘录（com.apple.mobilenotes）与日历事件（com.apple.mobilecal）经 `IosArtifactParsers.cpp:270,293,336` 亦落此表）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL | 应用包名 |
| note_id | TEXT | — | 笔记 ID |
| title | TEXT | — | 标题 |
| content | TEXT | — | 正文 |
| tags | TEXT | — | 标签 |
| is_private | INTEGER | DEFAULT 0 | 私密笔记标志 |
| source_db | TEXT | — | 来源 DB 路径 |

#### miui_backup_manifest / installed_apps / app_db_inventory（`:217-221`、`:222-227`、`:228-232`，MIUI 备份三件套）

miui_backup_manifest（写入 `AndroidAnalysisDatabase.cpp:586`；统一取数包的 MIUI 清单也回写此表，`MobileEvidenceAnalysis.cpp:203-207`）：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| device | TEXT | — | 设备型号 |
| miui_version | TEXT | — | MIUI 版本 |
| backup_date | INTEGER | — | 备份时刻 |
| total_size | INTEGER | — | 备份总字节 |
| package_count | INTEGER | — | 应用数 |
| source_folder | TEXT | — | 备份目录 |

installed_apps（写入 `AndroidAnalysisDatabase.cpp:609`）：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | — | 包名 |
| display_name | TEXT | — | 显示名 |
| version_code | TEXT | — | 版本号（TEXT） |
| version_name | TEXT | — | 版本名 |
| data_size | INTEGER | — | 数据区字节 |
| sd_size | INTEGER | — | SD 卡占用 |
| bak_type | INTEGER | — | 备份类型码 |
| manifest_summary | TEXT | — | manifest 摘要 |

app_db_inventory（写入 `AndroidAnalysisDatabase.cpp:655`）：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | — | 包名 |
| db_path | TEXT | — | DB 路径 |
| table_name | TEXT | — | 表名 |
| row_count | INTEGER | — | 行数 |
| columns | TEXT | — | 列清单（序列化） |
| open_status | TEXT | — | 打开状态（明文可开/加密/损坏） |

#### miui_external_files（`:237-243`，写入 `AndroidAnalysisDatabase.cpp:633`；调用方 `MiuiArtifactParsers.cpp:726`、统一取数包回写 `MobileEvidenceAnalysis.cpp:302`）

建表注释（`:233-236`）原文要点：完整 MIUI 导出里 sdcard/ 外部存储与 miui_backup/ 同舱——媒体与文档本身是证据，给它们建文件级清单，而不是随 .bak tar 成员被丢弃。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| relative_path | TEXT | NOT NULL UNIQUE | 备份内相对路径（`INSERT OR REPLACE` 幂等） |
| file_name | TEXT | — | 文件名 |
| extension | TEXT | — | 扩展名 |
| category | TEXT | — | 类别（媒体/文档等） |
| size | INTEGER | DEFAULT 0 | 字节数 |
| modified_time | INTEGER | DEFAULT 0 | 修改时刻 |

### 分组五：备份与加密（2 张）

miui_backup_manifest 归上一组；encrypted_db_inventory（`:205-213`）——SQL 注释原文："Inventory of SQLCipher-encrypted app databases with their discovered key hints (password.json / shared_prefs). Whether the DB can be opened depends on the app's KDF; the hint itself is the contest answer."（写入 `AndroidAnalysisDatabase.cpp:565`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL | 应用包名 |
| db_path | TEXT | NOT NULL | 加密 DB 路径 |
| key_hint_type | TEXT | — | 密钥线索类型（password.json/shared_prefs） |
| key_hint_value | TEXT | — | 线索值 |
| key_source_path | TEXT | — | 线索文件路径 |
| open_status | TEXT | — | 解密尝试结果 |

### 分组六：统一备份（2 张，`MobileBackupSchema.h`）

厂商中立表族：鸿蒙（HarmonyArtifactParsers）、雷电通用适配器（ThunderForensicArtifactParsers，OPPO/vivo/一加等）、vivo、iOS 四类来源共用同一 DDL（文件头注释 `MobileBackupSchema.h:2-9`："Keep every adapter on this one definition"）。表由适配器/分析层**按需现建**——纯 MIUI 或 Android 物理镜像任务不建这两张表。

#### mobile_backup_manifest（`MobileBackupSchema.h:16-17`，单行表 id 恒 1）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY CHECK(id=1) | 恒 1（单行清单头） |
| platform | TEXT | — | 平台标识（'iOS'/鸿蒙/雷电等） |
| device | TEXT | — | 设备描述（iOS 侧为 "型号 / iOS <版本>"，`IosArtifactParsers.cpp:488-491`） |
| backup_version | TEXT | — | 备份格式版本 |
| backup_time_ms | INTEGER | — | 备份时刻（毫秒） |
| module_count | INTEGER | — | 模块/应用数（Web 页当 package_count 展示，`AndroidQueries.cpp:193`） |
| manifest_sha256 | TEXT | — | manifest 哈希（防篡改） |
| adapter_version | TEXT | — | 适配器版本 |

写入方：`MobileEvidenceAnalysis.cpp:213`（统一取数包回写）、`IosArtifactParsers.cpp:495`、`VivoArtifactParsers.cpp:91`、ThunderForensic/Harmony 解析器（`ThunderForensicArtifactParsers.cpp:1114` 起、`HarmonyArtifactParsers.cpp:39` 起）。

#### mobile_artifacts（`MobileBackupSchema.h:18-24`，21 列含内联 llm_*）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY | 行号 |
| kind | TEXT | NOT NULL | 记录种类（calendar/recording/qq_contact/note_block/device_info/wifi/media/app_usage_session/application/app_traffic/device_log 等，LLM 调度按此分优先级） |
| package_name | TEXT | NOT NULL | 归属应用 |
| app_index | INTEGER | NOT NULL | 应用序号 |
| source_path | TEXT | NOT NULL, UNIQUE 组合 | 源库路径 |
| source_table | TEXT | NOT NULL, UNIQUE 组合 | 源表 |
| source_key | TEXT | NOT NULL, UNIQUE 组合 | 源行键（`UNIQUE(source_path,source_table,source_key)` 幂等） |
| record_json | TEXT | NOT NULL | 记录 JSON 全文 |
| timestamp_raw | TEXT | — | 原始时间串 |
| time_unit | TEXT | — | 时间单位 |
| timestamp_seconds | INTEGER | — | 归一化 unix 秒 |
| source_db_sha256 | TEXT | — | 源库哈希 |
| source_wal_sha256 | TEXT | — | 源 WAL 哈希 |
| parser_version | TEXT | NOT NULL | 解析器版本 |
| related_path | TEXT | — | 关联文件路径 |
| related_status | TEXT | — | 关联文件状态 |
| llm_summary | TEXT | — | LLM 摘要（**建表内联**，非 addLlmColumns） |
| llm_description | TEXT | — | LLM 描述 |
| llm_keywords | TEXT | — | LLM 关键词 |
| llm_analyzed_at | INTEGER | — | LLM 分析时刻 |
| llm_model_used | TEXT | — | LLM 模型 |

索引：`mobile_artifacts_kind(kind, id)`（`MobileBackupSchema.h:25`）。写入方：`MobileEvidenceAnalysis.cpp:30-34`（统一包回写）、`VivoArtifactParsers.cpp:54`、`ThunderForensicCaseDatabase.cpp:230`；LLM pending SELECT 与 UPDATE 在 `AndroidLLMAnalysisService_Database.cpp:35,141-158`（按 kind 分七档优先级：calendar/recording 最先，app_traffic/device_log 等批量计数最后）。

### 分组七：溯源与覆盖（5 张，`android_analysis_sql.h:381-421`）

证据链层：回答"这条规范化数据是从哪个容器/镜像的哪个成员来的、提取成功没有"。两组 CREATE 块的 SQL 注释明确定位：容器溯源"Container-only provenance; original Android artifact tables are unchanged"（`:388`）；镜像派生路径"Image-derived paths are separate from archive members... every staged file has partition/inode proof"（`:403-404`）。全部 `INSERT OR REPLACE` 幂等（复合主键）。当前无 HTTP 查询路由读这五张表（写入与重跑前的 DELETE 重置为主，`HarmonyArtifactParsers.cpp:45-46`、`ThunderForensicArtifactParsers.cpp:1124-1125`）。

#### android_source_coverage（`:382-386`，写入 `AndroidAnalysisDatabase.cpp:278-296` recordSourceCoverage）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| artifact_kind | TEXT | NOT NULL, PK 组合 | 工件种类（如 wechat） |
| source_path | TEXT | NOT NULL, PK 组合 | 源文件路径（占位值如 `<miui-backup>`/`<source-index>` 表示无具体文件） |
| status | TEXT | NOT NULL | 解析状态（ok/no_candidate_path/extract_failed 等，写入方自述） |
| detail | TEXT | — | 细节 |
| updated_at | INTEGER | NOT NULL DEFAULT (strftime('%s','now')) | 刷新时刻 |

写入方：AndroidAnalyzerCore.cpp:310,361-413（微信库提取覆盖）、ThunderForensicArtifactParsers.cpp:1153。

#### android_source_provenance（`:390-396`，写入 `AndroidAnalysisDatabase.cpp:300-316` insertSourceProvenance）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| source_container | TEXT | NOT NULL | 源容器（zip/快取包）路径 |
| source_container_sha256 | TEXT | NOT NULL | 容器哈希 |
| source_member_path | TEXT | NOT NULL, PK 组合 | 容器内成员路径 |
| normalized_android_path | TEXT | NOT NULL, PK 组合 | 归一化 Android 路径（`PK(normalized_android_path, source_member_path)`） |
| member_size | INTEGER | NOT NULL | 成员字节数 |
| member_sha256 | TEXT | NOT NULL | 成员哈希 |
| adapter_type | TEXT | NOT NULL | 适配器类型 |
| adapter_version | TEXT | NOT NULL | 适配器版本 |

写入方：AndroidAnalyzerCore.cpp:441,471、ThunderForensicArtifactParsers.cpp:1140-1142、ThunderForensicCaseDatabase.cpp:710、HarmonyArtifactParsers.cpp:59、IosArtifactParsers.cpp:592。

#### android_container_coverage（`:397-401`，写入 `AndroidAnalysisDatabase.cpp:366-384` recordContainerCoverage）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| source_path | TEXT | NOT NULL, PK 组合 | 容器/成员源路径 |
| normalized_path | TEXT | NOT NULL, PK 组合 | 归一化路径 |
| adapter | TEXT | NOT NULL, PK 组合 | 适配器名 |
| status | TEXT | NOT NULL CHECK | 七态状态机：'FOUND'/'PARSED'/'NOT_FOUND'/'EXTRACT_FAILED'/'LOCKED'/'UNSUPPORTED'/'MALFORMED'（`:399` CHECK 约束） |
| reason | TEXT | — | 原因 |

写入方：AndroidAnalyzerCore.cpp:463,492、ThunderForensicArtifactParsers.cpp:1148。

#### android_filesystem_provenance（`:406-415`，与 source_provenance 同一入口 `AndroidAnalysisDatabase.cpp:318-344`——容器溯源行携带文件系统信息时连带写此表）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| source_evidence_id | TEXT | NOT NULL, PK 组合 | 证据源 ID（当前实现写入容器哈希，`AndroidAnalysisDatabase.cpp:329-330`） |
| source_image_sha256 | TEXT | NOT NULL | 镜像哈希（同上，当前与 container_sha256 同值） |
| container_type | TEXT | NOT NULL | 容器类型 |
| partition_number | INTEGER | NOT NULL | 分区号 |
| partition_name | TEXT | NOT NULL | 分区名 |
| partition_start_offset | INTEGER | NOT NULL, PK 组合 | 分区起始偏移 |
| filesystem_type | TEXT | NOT NULL | 文件系统类型 |
| filesystem_object_id | TEXT | NOT NULL, PK 组合 | 文件系统对象 ID（inode/MFT 号） |
| filesystem_path | TEXT | NOT NULL | 文件系统内原始路径 |
| normalized_android_path | TEXT | NOT NULL, PK 组合 | 归一化路径 |
| file_size | INTEGER | NOT NULL | 字节数 |
| file_sha256 | TEXT | NOT NULL | 哈希 |
| reader | TEXT | NOT NULL | 读取器（ext4fs 等） |
| reader_version | TEXT | NOT NULL | 读取器版本 |

#### android_filesystem_metrics（`:416-421`，写入 `AndroidAnalysisDatabase.cpp:346-364` insertFilesystemMetrics；调用方 AndroidAnalyzerCore.cpp:452）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| source_image | TEXT | PRIMARY KEY | 镜像路径（一镜像一行） |
| filesystem_type | TEXT | NOT NULL | 文件系统类型 |
| reader | TEXT | NOT NULL | 读取器 |
| walk_milliseconds | INTEGER | NOT NULL | 遍历耗时 |
| indexed_file_count | INTEGER | NOT NULL | 索引文件数 |
| extracted_member_count | INTEGER | NOT NULL | 提取成员数 |
| bytes_read | INTEGER | NOT NULL | 读取字节 |
| analysis_milliseconds | INTEGER | NOT NULL | 分析耗时 |

### 分组八：进度（1 张）

#### android_analysis_progress（`android_analysis_sql.h:376-379`，写入 `android_analysis_sql_llm.h:82-90`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| task_id | TEXT | — | 任务 ID（**无 PRIMARY KEY**，与 windows/linux 同名表不同，见"已知边界"） |
| table_name | TEXT | — | 本进度行对应的表名 |
| total_artifacts | INTEGER | — | 总数 |
| completed_artifacts | INTEGER | — | 已完成 |
| started_at | INTEGER | — | 开始时刻 |
| last_updated | INTEGER | — | 最近刷新 |
| status | TEXT | — | 'running'/'completed' |

## 索引

建表 SQL 内联的唯一约束自动建索引（如 `wechat_contacts.username`、`framework_files.file_path`）+ 手工索引仅三处：`idx_mer_*` 系（统一取数包，见 MobileEvidenceDB.md）、`mobile_artifacts_kind`（`MobileBackupSchema.h:25`）；android.db 本体的工件表**没有手工 CREATE INDEX**——时间列（date/timestamp/event_time）均无索引，时间线查询是全表扫描。

## LLM 分析覆盖清单（`android_analysis_sql_llm.h` 全部 pending 语句）

| 语句 | 行 | 目标表 | 排序策略 |
|------|----|--------|---------|
| SELECT_SMS_PENDING_ANALYSIS | `:20-22` | sms_messages | date DESC |
| SELECT_WECHAT_MESSAGES_PENDING_ANALYSIS | `:24-27` | wechat_messages | timestamp DESC |
| SELECT_WHATSAPP_PENDING_ANALYSIS | `:29-31` | whatsapp_messages | timestamp DESC |
| SELECT_TELEGRAM_PENDING_ANALYSIS | `:33-35` | telegram_messages | timestamp DESC |
| SELECT_CONTACTS_PENDING_ANALYSIS | `:37-39` | contacts | display_name |
| SELECT_CALL_LOGS_PENDING_ANALYSIS | `:41-43` | call_logs | date DESC |
| SELECT_MIUI_MANIFEST_PENDING_ANALYSIS | `:45-47` | miui_backup_manifest | backup_date DESC |
| SELECT_INSTALLED_APPS_PENDING_ANALYSIS | `:49-51` | installed_apps | data_size DESC |
| SELECT_WECHAT_SQLITE_RECORDS_PENDING_ANALYSIS | `:53-55` | wechat_sqlite_records | is_sensitive DESC, id |
| SELECT_WECHAT_KV_RECORDS_PENDING_ANALYSIS | `:57-60` | wechat_kv_records | is_sensitive DESC, id（注释：优先 uin/imei/mac/device） |
| SELECT_QQNT_SQLITE_RECORDS_PENDING_ANALYSIS | `:62-64` | qqnt_sqlite_records | is_sensitive DESC, id |
| SELECT_SYSTEM_LOGS_PENDING_ANALYSIS | `:66-68` | system_logs | timestamp DESC |
| SELECT_DEVICE_IDENTIFIERS_PENDING_ANALYSIS | `:70-72` | device_identifiers | id |
| SELECT_WIFI_NETWORKS_PENDING_ANALYSIS | `:74-76` | wifi_networks | last_connected DESC |

（14 张表与 `AndroidAnalysisDatabase.cpp:65-71` 的 kLlmTables 一一对应；进度语句 INSERT/UPDATE/COMPLETE 在 `:82-90`。第 15 张带 llm 列的表 `mobile_artifacts` 不在本头文件——其 pending SELECT 按 kind 七档优先级排序，内联在 `AndroidLLMAnalysisService_Database.cpp:141-158`，UPDATE 语句 `:35`。）

## INSERT 列覆盖矩阵（建表列 vs 实际写入列）

| 表 | 建表列数 | INSERT 写入列 | 恒 NULL 的列 |
|----|---------|--------------|--------------|
| sms_messages | 12(+5) | 5（address/body/date/type/date_seconds，`AndroidAnalysisDatabase.cpp:158-160`） | thread_id/person/date_sent/read/status/service_center |
| contacts | 7(+5) | 2（display_name/phone_number，`:178`） | raw_contact_id/email/account_type/account_name |
| call_logs | 8(+5) | 5（number/date/duration/type/date_seconds，`:191-193`） | name/geocoded_location |
| whatsapp/telegram_messages | 7(+5) | 各 4（sender/receiver/content/timestamp，`:210`/`:225`） | media_url/media_type |
| wechat_messages | 13(+5) | 增强版 10（含 source_path，`:254-258`）/ 基础版 4（`:240`） | media_url/media_type |
| wechat_contacts | 8 | 7（全数据列含 mobile，`sql.h:342-346`） | — |
| wechat_chatrooms | 6 | 5（全数据列，`:414`） | — |
| wechat_owner_info | 5 | 4（全数据列，`:430`） | — |
| wifi_networks | 5(+5) | 3（ssid/pre_shared_key/key_mgmt，`:445`） | last_connected |
| chrome_history | 6 | 4（url/title/visit_count/last_visit_time，`:459`） | typed_count |
| installed_packages | 8 | 4（package_name/code_path/version/installer，`:474`） | native_library_path/first_install_time/last_update_time |
| usage_stats | 5 | 4（全数据列，`:493`） | — |
| app_database_files | 5 | 4（全数据列，`sql.h:367`） | — |
| system_logs | 9(+5) | 8（全数据列，`:508`） | — |
| miui_external_files | 7 | 6（全数据列，`:633`） | — |
| mobile_artifacts | 21 | 15（非 LLM 全列，`MobileEvidenceAnalysis.cpp:30-34`） | llm_* 5 列待 LLM 服务回填 |

（MIUI/QQNT 系列表由备份解析器按全数据列写入；溯源五表全列写入。）

## 跨表关联键

- 本库表间几乎不 JOIN：聊天内容按语义字段（chatroom_name ↔ wechat_chatrooms.chatroom_name；address/person ↔ contacts；**wechat_contacts.mobile ↔ call_logs.number / sms_messages.address**——跨源身份互认的新键）对齐，无外键（决定二）。
- 回溯上游：`app_database_files.file_path`、`*_inventory.source_path` 对应 files.db 主表 `path`；证据链上 `android_source_provenance.normalized_android_path` ↔ files.db `path`（哈希+分区/inode 溯源）；LLM 层按 `is_sensitive DESC` 优先调度（`android_analysis_sql_llm.h:55,60`）。

真实 JOIN 示例（群消息补昵称——本库内最典型的一跳）：

```sql
SELECT m.chatroom_name, m.sender_nickname, m.timestamp, m.content
FROM wechat_messages m
JOIN wechat_chatrooms c ON c.chatroom_name = m.chatroom_name
ORDER BY m.timestamp DESC;
```

## 已知边界

- **llm_* 列只加在 14 张表上**（`AndroidAnalysisDatabase.cpp:65-71` 列表）：`wechat_contacts`/`wechat_chatrooms`/`wechat_owner_info`/`chrome_history`/`contacts` 之外的通信明细有，但 QQNT 系列 4 张中只有 `qqnt_sqlite_records` 有——`qqnt_kv_records`/`qqnt_log_events`/`qqnt_artifact_inventory` 及 `wechat_log_events`/`wechat_artifact_inventory` 无 llm 列，LLM 服务不覆盖它们。第 15 张 `mobile_artifacts` 的 llm 列是建表内联的，走独立的 pending 语句。
- **`android_analysis_progress` 无主键**：task_id 不唯一，同任务多表各占一行（靠 task_id+table_name 语义区分），与 `windows_analysis_progress`（task_id PRIMARY KEY）设计不一致。
- **部分列恒 NULL**：`sms_messages` 建表 12 列但 INSERT 仅写 5 列（`:158-160`），thread_id/read/status/date_sent/service_center 保留给增强解析器，当前不填；`contacts` 同理只写 2 列；`chrome_history` 只写 4 列（typed_count 恒 NULL）。
- **时间戳单位三制并存**：`sms/call_logs.date` 保留源库原值（MIUI 毫秒、雷电/美亚秒），chrome `last_visit_time` 是 Chrome epoch（1601-01-01 起微秒），跨源排序一律用 `date_seconds`（注释 `android_analysis_sql.h:49-50` 明言此设计）；iOS 侧还有 Apple epoch（`IosArtifactParsers.cpp:512-519` 归一化）。
- **`namespace` 作列名**：是 SQL 保留字（SQLite 接受，其他数据库迁移会踩坑）。
- **溯源五表是写入侧私产**：无 HTTP 查询路由、无 Web 页面读取，仅重跑前 DELETE 重置（`HarmonyArtifactParsers.cpp:45-46`）；`android_filesystem_provenance` 的 `source_evidence_id`/`source_image_sha256` 当前实现都填容器哈希（`AndroidAnalysisDatabase.cpp:329-330`），尚无真正的镜像级区分。
- **统一备份两表按需存在**：`mobile_backup_manifest`/`mobile_artifacts` 只在鸿蒙/雷电/vivo/iOS/统一包任务中出现（适配器运行时建表），纯 MIUI 或物理镜像任务的 android.db 没有它们——查询前先 `table_exists`（`AndroidQueries.cpp:191` 即此写法）。
- **iOS 借用 Android 表**：iOS 备忘录/日历写 `app_notes`（包名 com.apple.mobilenotes / com.apple.mobilecal）、Safari 历史写 `chrome_history`、应用清单写 `installed_packages`（installer='ios-backup'）——按 package_name/installer 区分平台，无独立 iOS 表。

---

## 附录：写入时序与查询手册

### 写入时序

| 分组表 | 写入方 | 时机 | 备注 |
|--------|--------|------|------|
| 通信 5 表（sms/contacts/call_logs/whatsapp/telegram） | AndroidAnalyzer 逻辑/物理两条路径 | PLATFORM_ANALYSIS·ANDROID | 物理路径从镜像提取 db 后解析；iOS 备份写 sms/contacts/call_logs（IosArtifactParsers） |
| 微信增强组（messages/contacts/chatrooms/owner） | WeChatDecryptor 解密后 | 同上；SQLCipher 需密码（IMEI 缺失时占位推导可能失败） |
| MIUI 组（manifest/installed_apps/db_inventory/external_files） | MiuiBackupExtractor+TarIndex | `--android-source miui-backup` 路径 | 限额 env：TRACELENS_MIUI_MAX_CANDIDATES 等 |
| QQNT/微信 KV 工件组（inventory/kv/sqlite/log） | 各 ArtifactParsers | 同上 | |
| 统一备份两表 | Harmony/ThunderForensic/Vivo 解析器、统一取数包回写（MobileEvidenceAnalysis）、IosArtifactParsers（manifest） | 备份类源分析时按需建表+写入 | |
| 溯源五表 | AndroidAnalyzerCore / ThunderForensic / Harmony / Ios 解析器 | 容器与镜像派生文件处理时 | INSERT OR REPLACE 幂等 |
| LLM5 列组 | AndroidLLMAnalysisService（端点门控：无 LLM_BASE_URL 自动跳过） | 工件级 | mobile_artifacts 单独 pending 语句 |

### 查询手册（列名以本文档字段表为准）

**1. 时间窗内消息-通话行为序列**
```sql
SELECT datetime(timestamp,'unixepoch') t, sender, receiver, substr(content,1,50) preview, is_send
FROM wechat_messages WHERE timestamp BETWEEN :s AND :e
UNION ALL
SELECT datetime(date_seconds,'unixepoch'), number, name, 'call_'||type, NULL
FROM call_logs WHERE date_seconds BETWEEN :s AND :e
ORDER BY t;
```

**2. 机主发出的消息（is_send=1）聚焦**
```sql
SELECT datetime(timestamp,'unixepoch'), receiver, substr(content,1,60)
FROM wechat_messages WHERE is_send=1 ORDER BY timestamp DESC LIMIT 200;
```

**3. 高频联系人（消息量 Top）**
```sql
SELECT CASE WHEN is_send=1 THEN receiver ELSE sender END peer, COUNT(*) c
FROM wechat_messages GROUP BY peer ORDER BY c DESC LIMIT 30;
-- 与 contacts.display_name 关联补名（wxid 映射）
```

**4. 微信身份 ↔ 手机号 ↔ 通话记录互认（mobile 强键）**
```sql
SELECT c.display_name, w.nickname, w.mobile, cl.number, cl.name
FROM wechat_contacts w
LEFT JOIN contacts c ON c.phone_number = w.mobile
LEFT JOIN call_logs cl ON cl.number = w.mobile
WHERE COALESCE(w.mobile,'') <> '';
```

**5. 联系人-电话-邮件一页看**
```sql
SELECT display_name, phone_number, email, account_name FROM contacts
WHERE display_name IS NOT NULL ORDER BY display_name;
```

**6. 浏览记录时间线（Chrome+Safari 混合）**
```sql
SELECT datetime(last_visit_time,'unixepoch') t, url, title, visit_count
FROM chrome_history ORDER BY last_visit_time DESC LIMIT 200;
```

**7. MIUI 备份头信息（设备/版本/规模）**
```sql
SELECT device, miui_version, backup_date, total_size, package_count, source_folder
FROM miui_backup_manifest;
-- 备份里有哪些 App 看 installed_apps / app_db_inventory 两表；sdcard 文件看 miui_external_files
```

**8. 统一备份头与记录分布（鸿蒙/雷电/vivo/iOS 任务）**
```sql
SELECT platform, device, backup_version, module_count, adapter_version
FROM mobile_backup_manifest;
SELECT kind, COUNT(*) c FROM mobile_artifacts GROUP BY kind ORDER BY c DESC;
-- 表可能不存在（纯 MIUI/物理镜像任务），查询前 table_exists
```

**9. 加密库与密钥线索清单（还能解哪些）**
```sql
SELECT package_name, db_path, key_hint_type, key_hint_value, open_status
FROM encrypted_db_inventory
ORDER BY CASE open_status WHEN 'locked' THEN 0 ELSE 1 END;
-- open_status 取值以字段表为准；locked 的库需要人工供密码（--backup-password-stdin）
```

**10. 证据链溯源（这条数据从哪个容器来）**
```sql
SELECT p.normalized_android_path, p.source_container, p.source_member_path,
       p.member_sha256, p.adapter_type
FROM android_source_provenance p
WHERE p.normalized_android_path LIKE '%msgstore%'
ORDER BY p.source_container;
```

## 分析案例

### 案例一：涉诈账号行为画像

**取证问题**：MIUI 备份，涉案微信账号涉嫌电信诈骗。要求还原案发窗口内的行为轨迹与关系网。

**第 1 步：时间窗行为序列**
```sql
SELECT datetime(date_seconds,'unixepoch') t, CASE is_send WHEN 1 THEN '发' ELSE '收' END dir,
       CASE WHEN is_send=1 THEN receiver ELSE sender END peer, substr(content,1,40) preview
FROM wechat_messages
WHERE timestamp BETWEEN strftime('%s','2026-08-18 09:00') AND strftime('%s','2026-08-18 12:00')
ORDER BY t;
```
读法：`is_send` 区分方向；群聊行看 `chatroom_name`/`sender_nickname`（字段表）还原群内发言。连续"发→秒收"脚本化模式是引流/诈骗群特征。

**第 2 步：高频对手方与电话交叉**
```sql
SELECT CASE WHEN is_send=1 THEN receiver ELSE sender END peer, COUNT(*) c
FROM wechat_messages GROUP BY peer ORDER BY c DESC LIMIT 15;
SELECT number, name, type, duration, datetime(date_seconds,'unixepoch')
FROM call_logs WHERE date_seconds BETWEEN :s AND :e ORDER BY date_seconds;
```
读法：消息 Top 对手方与通话记录里的号码对齐（联系人表补 display_name；`wechat_contacts.mobile` 直连手机号身份）；短时高频通话+特定号段强化"引流→话务"判断。

**第 3 步：证据完备性自检**
```sql
SELECT package_name, db_path, open_status FROM encrypted_db_inventory WHERE open_status<>'ok';
SELECT artifact_kind, source_path, status FROM android_source_coverage WHERE status<>'ok';
```
读法：解密失败的库（key_hint 不足）意味着部分会话缺失——结论要注明覆盖边界；必要时人工供密码重跑（`--backup-password-stdin`）。coverage 表给出同类结论的另一份留痕。

### 案例二：应用安装与浏览侧写

`installed_apps`/`installed_packages` 与 `chrome_history`（url/title/last_visit_time）交叉：涉案时段新装的应用 + 搜索/访问记录还原准备动作（如搜"接码平台"、装多开工具）。iOS 任务改看 `installed_packages WHERE installer='ios-backup'`。

## 自检清单

- [ ] wechat_messages 时间分布与案发窗吻合（无大面积缺失）
- [ ] encrypted_db_inventory 无未处理的 locked 库（影响覆盖完整性）
- [ ] call_logs/sms 与 wechat 的账号体系一致（同一机主；mobile 键互认可作校验）
- [ ] MIUI 任务核对 manifest 的 package_count 与 installed_apps 行数
- [ ] LLM5 列覆盖率（Android 有端点门控，无端点时全空属预期）
- [ ] 统一备份任务核对 mobile_artifacts 的 kind 分布与 mobile_backup_manifest.module_count
**最后更新**: 2026-11-10（统一备份两表/溯源五表/miui_external_files 入册；date_seconds/source_path/mobile 新列；iOS/vivo 写入方；行号与列数校准）
