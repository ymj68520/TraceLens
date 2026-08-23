# android.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/android_analysis_sql.h` + `SQL/android_analysis_sql_llm.h`）

> android.db 是 files.db 的**平台语义观点**（DatabaseSchema.md 派生链：files.db → android.db）：把"Android 镜像里有一批文件"翻译成"这是一台什么设备、谁在跟谁聊什么"。建表集中在 `android_analysis_sql.h`（SQL-as-headers，决定三）；14 张被 LLM 服务分析的表在初始化时动态补 5 个 llm_* 列（`AndroidAnalysisDatabase::addLlmColumns`，`src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp:706`）。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `AndroidAnalysisDatabase::createTables()`（`AndroidAnalysisDatabase.cpp:32-55`）：执行 `CREATE_ALL_TABLES`（21 表）+ `CREATE_MIUI_TABLES`（11 表）+ `CREATE_ANALYSIS_PROGRESS`（1 表），再给 14 张表补 llm_* 列；行数据由 AndroidAnalyzer 各解析器经 `insertXxx` 方法写入（内联 SQL，如 `AndroidAnalysisDatabase.cpp:68` 起） |
| 谁读 | HTTP 查询路由（`AndroidQueries.cpp`，其中 `:434` 注释说明 llm 列来源）、Web 前端 MIUI 备份页、`AndroidLLMAnalysisService`（pending 分析 SELECT 见 `android_analysis_sql_llm.h`） |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/android.db`；CLI 集成模式并入 files.db 的 `android_artifacts`（见 [FilesDB.md](./FilesDB.md)） |

## 表清单总表（33 张）

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `sms_messages` | 通信 | 短信（mmssms.db 抽取） | 11(+5 llm) |
| `contacts` | 通信 | 联系人（contacts2.db） | 8(+5) |
| `call_logs` | 通信 | 通话记录 | 8(+5) |
| `whatsapp_messages` | 通信 | WhatsApp 消息 | 8(+5) |
| `telegram_messages` | 通信 | Telegram 消息 | 8(+5) |
| `wechat_messages` | 微信 | 微信消息（SQLCipher 解密后） | 13(+5) |
| `wechat_contacts` | 微信 | 微信联系人 | 8 |
| `wechat_chatrooms` | 微信 | 微信群聊 | 7 |
| `wechat_owner_info` | 微信 | 机主身份（username/uin/imei） | 6 |
| `wechat_artifact_inventory` | 微信(MIUI) | 备份内微信工件文件清单 | 13 |
| `wechat_kv_records` | 微信(MIUI) | 微信 KV（shared_prefs 等）记录 | 10(+5) |
| `wechat_sqlite_records` | 微信(MIUI) | 微信 SQLite 明细记录 | 8(+5) |
| `wechat_log_events` | 微信(MIUI) | 微信日志事件 | 10 |
| `qqnt_artifact_inventory` | QQNT | 备份内 QQNT 工件文件清单 | 13 |
| `qqnt_kv_records` | QQNT | QQNT KV 记录 | 10 |
| `qqnt_sqlite_records` | QQNT | QQNT SQLite 明细记录 | 8(+5) |
| `qqnt_log_events` | QQNT | QQNT 日志事件 | 10 |
| `system_build_properties` | 设备与系统 | build.prop 键值 | 4 |
| `system_apps` | 设备与系统 | 系统应用清单 | 8 |
| `framework_files` | 设备与系统 | framework 目录文件清单 | 6 |
| `system_logs` | 设备与系统 | logcat 类系统日志 | 10(+5) |
| `device_identifiers` | 设备与系统 | SSAID/Android ID 等设备标识 | 6(+5) |
| `wifi_networks` | 设备与系统 | WiFi 配置（含 PSK） | 6(+5) |
| `chrome_history` | 设备与系统 | Chrome 浏览历史 | 7 |
| `installed_packages` | 应用 | 已装包（packages.xml） | 9 |
| `installed_apps` | 应用(MIUI) | MIUI 备份 manifest 应用清单 | 11(+5) |
| `usage_stats` | 应用 | 应用使用统计 | 6 |
| `app_database_files` | 应用 | 应用私有数据库文件清单 | 6 |
| `app_notes` | 应用 | 便签类应用笔记 | 9 |
| `app_db_inventory` | 应用(MIUI) | 备份内可开库的 DB 盘点 | 8 |
| `miui_backup_manifest` | 备份与加密 | MIUI 备份清单头 | 8(+5) |
| `encrypted_db_inventory` | 备份与加密 | SQLCipher 加密库及密钥线索盘点 | 8 |
| `android_analysis_progress` | 进度 | LLM 分析进度（task×table 粒度） | 8 |

(+5) 表示初始化时由 `addLlmColumns` 追加 `llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, llm_model_used TEXT` 五列（列表见 `AndroidAnalysisDatabase.cpp:41-47`，幂等 ALTER，重开库安全）。

## 逐表字段说明

### 分组一：通信（5 张）

手机取证的核心叙事：谁（contacts）、用什么号（sms/call_logs）、在哪个 App（whatsapp/telegram）说了什么。这组表列名刻意贴近各自源库（mmssms.db / WhatsApp msgstore），抽取时零改名。

#### sms_messages（`android_analysis_sql.h:37-49`，写入 `:296-297` 4 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| thread_id | INTEGER | — | 会话线程 ID（源库） |
| address | TEXT | — | 对端号码 |
| person | TEXT | — | 联系人名（可反查 contacts） |
| date | INTEGER | — | 收/发时刻（unix 毫秒，源库语义） |
| date_sent | INTEGER | — | 发送时刻 |
| read | INTEGER | — | 已读标志 |
| status | INTEGER | — | 投递状态码 |
| type | INTEGER | — | 方向：1 收 / 2 发（源库惯例） |
| body | TEXT | — | 正文 |
| service_center | TEXT | — | 短信中心号码 |

#### contacts（`:50-58`，写入 `:299-300` 2 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| raw_contact_id | INTEGER | — | 源库 raw contact id |
| display_name | TEXT | — | 显示名 |
| phone_number | TEXT | — | 号码（当前抽取仅写 display_name/phone_number） |
| email | TEXT | — | 邮箱 |
| account_type | TEXT | — | 账户类型（本地/Exchange...） |
| account_name | TEXT | — | 账户名 |

#### call_logs（`:59-67`，写入 `:302-303` 4 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| number | TEXT | — | 对端号码 |
| date | INTEGER | — | 通话开始时刻 |
| duration | INTEGER | — | 时长（秒） |
| type | INTEGER | — | 1 进 / 2 出 / 3 未接 |
| name | TEXT | — | 联系人名 |
| geocoded_location | TEXT | — | 归属地 |

#### whatsapp_messages / telegram_messages（`:68-85`，两表同构，写入 `:305-309` 4 列）

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

wechat_messages/contacts/chatrooms/owner_info 存**解密后内容**（SQLCipher 解密支持 `--wechat-password`、`--backup-password[-stdin|-fd]`，见 Security.md）；后 4 张 `wechat_*`（MIUI 备份系列）与 QQNT 系列同构，存**备份文件工件**本身。建表注释（`:251-253`）原文："WeChat (com.tencent.mm) evidence mirrors the QQNT inventory tables so the MIUI backup page can present file-evidence + recovered structured records alongside the existing decrypted-content tables."

#### wechat_messages（`:86-99`，写入 `INSERT_WECHAT_ENHANCED` `:314-315` 9 列）

| 列 | 类型 | 环境约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
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

#### wechat_contacts（`:100-108`，写入 `:317-318`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | UNIQUE | wxid |
| nickname | TEXT | — | 昵称 |
| remark | TEXT | — | 备注名 |
| avatar_path | TEXT | — | 头像文件路径 |
| type | INTEGER | — | 联系人类型码 |
| chatroom_flag | INTEGER | DEFAULT 0 | 1 = 群聊联系人 |

#### wechat_chatrooms（`:109-116`，写入 `:320-321`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| chatroom_name | TEXT | UNIQUE | 群 id |
| owner | TEXT | — | 群主 wxid |
| member_list | TEXT | — | 成员列表（序列化文本） |
| member_count | INTEGER | — | 成员数 |
| create_time | INTEGER | — | 建群时刻 |

#### wechat_owner_info（`:117-123`，写入 `:323-324`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | UNIQUE | 机主 wxid |
| nickname | TEXT | — | 机主昵称 |
| uin | INTEGER | — | 微信 UIN（跨设备追踪关键值） |
| imei | TEXT | — | 绑定 IMEI（旧版库加密盐） |

#### wechat_artifact_inventory / qqnt_artifact_inventory（`:225-232`、`:254-261`，两表同构）

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

#### wechat_kv_records / qqnt_kv_records（`:233-238`、`:262-267`，同构）

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

#### wechat_sqlite_records / qqnt_sqlite_records（`:239-244`、`:268-273`，同构）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| source_path | TEXT | NOT NULL | 来源 DB 路径 |
| table_name | TEXT | NOT NULL | 源表名 |
| record_key | TEXT | — | 记录键 |
| record_json | TEXT | — | 记录 JSON 全文 |
| artifact_kind | TEXT | — | 工件归类 |
| is_sensitive | INTEGER | DEFAULT 0 | 敏感标志 |

#### wechat_log_events / qqnt_log_events（`:245-250`、`:274-279`，同构）

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

#### system_build_properties（`:15-19`，写入 `:286-287`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| property_key | TEXT | NOT NULL UNIQUE | 属性名（ro.product.model 等） |
| property_value | TEXT | — | 属性值 |

#### system_apps（`:20-29`，写入 `:289-291`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL, UNIQUE 组合 | 包名 |
| apk_path | TEXT | NOT NULL, UNIQUE 组合 | APK 路径 |
| version_name | TEXT | — | 版本名 |
| version_code | TEXT | — | 版本号（注意 TEXT，非 INTEGER） |
| is_system_app | INTEGER | DEFAULT 1 | 系统预装 |
| is_privileged | INTEGER | DEFAULT 0 | 特权应用（/system/priv-app） |

#### framework_files（`:30-36`，写入 `:293-294`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_name | TEXT | NOT NULL | 文件名 |
| file_path | TEXT | NOT NULL UNIQUE | 路径 |
| file_type | TEXT | — | 类型 |
| file_size | INTEGER | — | 字节数 |

#### system_logs（`:164-174`，写入 `:341-342` 8 列）

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

#### device_identifiers（`:175-182`，SQL 注释："Android SSAID / per-app 'Android ID' values from settings_ssaid.xml"）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| identifier_type | TEXT | NOT NULL | 标识类型（SSAID/ANDROID_ID/...） |
| value | TEXT | NOT NULL | 值 |
| package_name | TEXT | — | 所属应用（SSAID 按应用隔离） |
| source_path | TEXT | — | 来源文件路径 |

#### wifi_networks（`:124-130`，写入 `:326-327`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| ssid | TEXT | NOT NULL | 网络名 |
| pre_shared_key | TEXT | — | 明文 PSK（高危证据） |
| key_mgmt | TEXT | — | 认证方式（WPA-PSK...） |
| last_connected | INTEGER | — | 最近连接时刻 |

#### chrome_history（`:131-138`，写入 `:329-330` 4 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| url | TEXT | NOT NULL | URL |
| title | TEXT | — | 页面标题 |
| visit_count | INTEGER | — | 访问次数 |
| last_visit_time | INTEGER | — | 最近访问（Chrome epoch，1601 起 微秒） |
| typed_count | INTEGER | — | 手输次数 |

### 分组四：应用（6 张）

#### installed_packages（`:139-148`，写入 `:332-333`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL UNIQUE | 包名 |
| code_path | TEXT | — | APK 所在目录 |
| native_library_path | TEXT | — | so 库目录 |
| first_install_time | INTEGER | — | 首装时刻 |
| last_update_time | INTEGER | — | 最近升级时刻 |
| version | TEXT | — | 版本 |
| installer | TEXT | — | 安装来源（com.android.vending...） |

#### usage_stats（`:149-155`，写入 `:335-336`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | — | 包名 |
| total_time_foreground | INTEGER | — | 前台累计时长（毫秒） |
| last_time_used | INTEGER | — | 最近使用 |
| interval_start | INTEGER | — | 统计区间起点 |

#### app_database_files（`:156-163`，写入 `:338-339`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL, UNIQUE 组合 | 包名 |
| file_name | TEXT | NOT NULL | DB 文件名 |
| file_path | TEXT | NOT NULL, UNIQUE 组合 | DB 路径 |
| file_size | INTEGER | DEFAULT 0 | 字节数 |

#### app_notes（`:183-193`，SQL 注释："Notes recovered from plaintext note-taking app databases (generic)"）

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

#### miui_backup_manifest / installed_apps / app_db_inventory（`:209-224`，MIUI 备份三件套）

miui_backup_manifest（写入经 `SELECT_MIUI_MANIFEST_PENDING_ANALYSIS` 可证列集）：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| device | TEXT | — | 设备型号 |
| miui_version | TEXT | — | MIUI 版本 |
| backup_date | INTEGER | — | 备份时刻 |
| total_size | INTEGER | — | 备份总字节 |
| package_count | INTEGER | — | 应用数 |
| source_folder | TEXT | — | 备份目录 |

installed_apps：

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

app_db_inventory：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | — | 包名 |
| db_path | TEXT | — | DB 路径 |
| table_name | TEXT | — | 表名 |
| row_count | INTEGER | — | 行数 |
| columns | TEXT | — | 列清单（序列化） |
| open_status | TEXT | — | 打开状态（明文可开/加密/损坏） |

### 分组五：备份与加密（2 张）

miui_backup_manifest 归上一组；encrypted_db_inventory（`:194-205`）——SQL 注释原文："Inventory of SQLCipher-encrypted app databases with their discovered key hints (password.json / shared_prefs). Whether the DB can be opened depends on the app's KDF; the hint itself is the contest answer."

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| package_name | TEXT | NOT NULL | 应用包名 |
| db_path | TEXT | NOT NULL | 加密 DB 路径 |
| key_hint_type | TEXT | — | 密钥线索类型（password.json/shared_prefs） |
| key_hint_value | TEXT | — | 线索值 |
| key_source_path | TEXT | — | 线索文件路径 |
| open_status | TEXT | — | 解密尝试结果 |

### 分组六：进度（1 张）

#### android_analysis_progress（`:347-351`，写入 `android_analysis_sql_llm.h:82-90`）

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

建表 SQL 内联的唯一约束自动建索引（如 `wechat_contacts.username`、`framework_files.file_path`）；除此之外**没有手工 CREATE INDEX**——时间列（date/timestamp/event_time）均无索引，时间线查询是全表扫描。

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

（14 张表与 `AndroidAnalysisDatabase.cpp:41-47` 的 kLlmTables 一一对应；进度语句 INSERT/UPDATE/COMPLETE 在 `:82-90`。）

## INSERT 列覆盖矩阵（建表列 vs 实际写入列）

| 表 | 建表列数 | INSERT 写入列 | 恒 NULL 的列 |
|----|---------|--------------|--------------|
| sms_messages | 11(+5) | 4（address/body/date/type，`:296-297`） | thread_id/person/date_sent/read/status/service_center |
| contacts | 8(+5) | 2（display_name/phone_number，`:299-300`） | raw_contact_id/email/account_type/account_name |
| call_logs | 8(+5) | 4（number/date/duration/type） | name/geocoded_location |
| whatsapp/telegram_messages | 8(+5) | 各 4（sender/receiver/content/timestamp） | media_url/media_type |
| wechat_messages | 13(+5) | 9（增强版 INSERT，`:314-315`） | media_url/media_type |
| wechat_contacts | 8 | 6（全列，`:317-318`） | — |
| wechat_chatrooms | 7 | 5（全数据列） | — |
| wechat_owner_info | 6 | 4（全数据列） | — |
| wifi_networks | 6(+5) | 3（ssid/pre_shared_key/key_mgmt） | last_connected |
| chrome_history | 7 | 4（url/title/visit_count/last_visit_time） | typed_count |
| installed_packages | 9 | 4（package_name/code_path/version/installer） | native_library_path/first_install_time/last_update_time |
| usage_stats | 6 | 4（全数据列） | — |
| app_database_files | 6 | 4（全数据列） | — |
| system_logs | 10(+5) | 8（全数据列，`:341-342`） | — |

（MIUI/QQNT 系列表由备份解析器按全数据列写入。）

## 跨表关联键

- 本库表间几乎不 JOIN：聊天内容按语义字段（chatroom_name ↔ wechat_chatrooms.chatroom_name；address/person ↔ contacts）对齐，无外键（决定二）。
- 回溯上游：`app_database_files.file_path`、`*_inventory.source_path` 对应 files.db 主表 `path`；LLM 层按 `is_sensitive DESC` 优先调度（`android_analysis_sql_llm.h:55,60`）。

真实 JOIN 示例（群消息补昵称——本库内最典型的一跳）：

```sql
SELECT m.chatroom_name, m.sender_nickname, m.timestamp, m.content
FROM wechat_messages m
JOIN wechat_chatrooms c ON c.chatroom_name = m.chatroom_name
ORDER BY m.timestamp DESC;
```

## 已知边界

- **llm_* 列只加在 14 张表上**（`AndroidAnalysisDatabase.cpp:41-47` 列表）：`wechat_contacts`/`wechat_chatrooms`/`wechat_owner_info`/`chrome_history`/`contacts` 之外的通信明细有，但 QQNT 系列 4 张中只有 `qqnt_sqlite_records` 有——`qqnt_kv_records`/`qqnt_log_events`/`qqnt_artifact_inventory` 及 `wechat_log_events`/`wechat_artifact_inventory` 无 llm 列，LLM 服务不覆盖它们。
- **`android_analysis_progress` 无主键**：task_id 不唯一，同任务多表各占一行（靠 task_id+table_name 语义区分），与 `windows_analysis_progress`（task_id PRIMARY KEY）设计不一致。
- **部分列恒 NULL**：`sms_messages` 建表 11 列但 INSERT 仅写 4 列（`:296-297`），thread_id/read/status/date_sent/service_center 保留给增强解析器，当前不填；`contacts` 同理只写 2 列；`chrome_history` 只写 4 列（typed_count 恒 NULL）。
- **时间戳单位不统一**：sms/call_logs 的 `date` 是源库毫秒，chrome `last_visit_time` 是 Chrome epoch（1601-01-01 起微秒），跨表排时间线须先归一。
- **`namespace` 作列名**：是 SQL 保留字（SQLite 接受，其他数据库迁移会踩坑）。

---

**最后更新**: 2026-08-24（新建，字段级参考）
