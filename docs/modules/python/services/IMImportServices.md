# IMImportServices（微信/QQ/WhatsApp 三平台导入服务：wechat_import_service.py + wechat_decrypt.py + qq_import_service.py + qq_decrypt.py + qq_legacy.py + whatsapp_import_service.py）

> **一句话**：三平台账号库的"复制→解密→归一化"导入实现层——微信走纯 Python 页级 SQLCipher 解密（密钥可从检材自动推导），QQ 走 SQLCipher 4 离线解密（nt_uid+rand 的 md5 推导链）并兼容老版 4.x XOR 混淆库，WhatsApp 读 iOS 备份的明文 Core Data 表；三者最终都归一化成同一套 `wechat_*` 表的 graph.db，供 `/api/wechat/graph` 与 comm_graph 跨源消费。源库只读、绝不回写。

## 1. 为什么有这三个（一套）服务

IM 取证面板（[../httpserver/routes/IMForensics.md](../httpserver/routes/IMForensics.md)）要求三平台同构，实现层因此也是一套平行结构：每平台一个 `*_import_service.py`（导入生命周期 + 查询），解密各归其位（wechat_decrypt/qq_decrypt 纯解密模块，qq_legacy 兼容层）。共同的不变量：**源库只读**（whatsapp_import_service.py:16-17："Nothing is ever written back to the evidence files: the source database is opened read-only and the normalised copy lives under whatsapp_imports"）；**归一化目标统一**——QQ 导入 docstring（qq_import_service.py:8-13）写明 graph.db "carrying the same `wechat_messages`/`wechat_contacts`/`wechat_chatrooms`/`wechat_owner_info` tables the existing relationship-analysis pipeline consumes"；**meta.json 是导入的账本**（状态/密钥来源/解密参数/统计）。

## 2. 在系统中的位置

- **谁调用它们**：三平台路由（imports CRUD + 五读取端点）；wechat_graph_models.py:161-188（`wx_/qq_<import_id>` 解析 → `ensure_graph_db` 自愈重建）；comm_graph/datasets.py:31-45（统一图谱的导入数据源，同样经 ensure_graph_db）。
- **它们调用谁**：wechat_decrypt/qq_decrypt（纯函数解密）；qq_legacy（老版 QQ 提取 + `_java_cfg_strings`（Java 序列化 Properties 解析，被微信密钥推导复用，wechat_import_service.py:112-113））；config.get_data_root（导入根目录）。
- **它们被谁依赖**：TimelineSummary 的 qq_legacy/wechat_import 来源（直接读导入目录里的 nt_msg.db/graph.db/EnMicroMsg.db）。

## 3. 核心数据结构：三平台导入目录布局

| 平台 | 根目录 | 目录内容 | import_id |
|---|---|---|---|
| 微信 | `{DATA_ROOT}/wechat_imports/<id>/` | meta.json、source/（原库+wal 副本）、EnMicroMsg.db（解密产物）、media/（可选缩略图）、graph.db（ensure 时） | 12-hex（:163-167） |
| QQ | `qq_imports/<id>/` | meta.json、source/（原始加密件）、nt_msg.db、profile_info.db、group_info.db（可选）、graph.db（qq_import_service.py:15-25 布局 docstring） | 12-hex |
| 老版 QQ（format=legacy_qq4） | 同 QQ 目录 | meta.json（带 `"format": "legacy_qq4"`）、source/（原库原样复制）、**graph.db（无 nt_msg.db，读取端点直接答 graph.db，:436-441 docstring）** | 12-hex |
| WhatsApp | `whatsapp_imports/<id>/` | meta.json、source/、graph.db（导入时即建，:244-246 `_build_graph_db`） | 12-hex |

meta.json 字段（微信 ：293-303 为例）：import_id/name/status（importing|ok|failed|…）/created_at/backup_source/key_material（uin/imei/wxid/account_dir）/decryption（scheme/params/pages/password_given/formula/integrity）/owner/stats/thumbs；QQ 增加 format/nt_uid，老版增加 format=legacy_qq4 + device_id。

## 4. 核心机制走读

### 4.1 微信：密钥自动推导（wechat_import_service.py:73-125 `_harvest_key_material`）

EnMicroMsg.db 的密钥材料藏在库周边的检材文件里（:73-84 docstring）：uin 从 `shared_prefs/{system_config_prefs,auth_info_key_prefs,com.tencent.mm_preferences}.xml` 的 `default_uin`/`_auth_uin` 读（:97-106）；设备 id（IMEI 替身）从 `CompatibleInfo.cfg`（Java 序列化 map，键 258/256，`qq_legacy._java_cfg_strings` 解析）在 MicroMsg 根/账号目录/com.tencent.mm 三层候选位里找（:107-120）；wxid 从 preferences 的 `default_account` 读（:121-127）。整个推导**只在本提取树内**（account_dir → mm_root → com_mm 的相对层进），`OSError` 全吞返回空 dict——推导是尽力而为的增强，不是导入的前提。create 流程（:273-410）：复制原库+wal 到 source/ → 无 password 时先 harvest 再 `derive_candidates`（wechat_decrypt.py:47-59：MD5(IMEI+UIN)[:7] 与 MD5(UIN+IMEI+wxid)[:7] 等四个候选按历史命中率排序）→ `detect_scheme` 逐候选试 → `decrypt_file` → `merge_wal`（:373-376，WAL 合入主文件让单文件读完整）→ `verify_db`（integrity != "ok" 即 failed，:377-383）→ enrich meta（owner/联系人/群/统计）→ 可选复制媒体。

### 4.2 wechat_decrypt：纯 Python 页级解密的动机（wechat_decrypt.py:1-21）

不用 sqlcipher 的原因写在 docstring（:2-7）："sidesteps the 'file is not a database' trap of stock SQLCipher builds: when the key is correct but the HMAC/page parameters differ, SQLCipher reports the same error as a wrong key"——SQLCipher 把"密钥对但参数不对"和"密钥错"报成同一个错，无法枚举候选；纯 Python 方案直接 PBKDF2 派生密钥、AES-256-CBC 解第 1 页、检查 SQLite 页头签名（`_is_sqlite_page`，:71-80：页大小 BE + 版本字节 + 64/32/32 配比）——"one check covers every HMAC combination because the page payload layout never depends on HMAC config"。两套 scheme（:35）：A=主库（1024 字节页、PBKDF2-SHA1×4000、无 HMAC、IV=页尾 16 字节）；B=FTS 索引库（4096 字节页、×64000、48 字节 reserve）。`decrypt_file`（:123）逐页解密并处理 WAL（`_decrypt_wal` 自算 WAL 校验和，:112/:197）。

### 4.3 QQ：header 解析与密钥推导链（qq_decrypt.py:1-25）

Android NTQQ 的库是 SQLCipher-4 但带 1024 字节自定义头（`"SQLite header 3\0" ... "QQ_NT DB" <len32> <protobuf>`，:4-9）。推导四步（:11-20 docstring + :61-72 实现）：`uid_hash = md5(nt_uid)` → `path_hash = md5(uid_hash + "nt_kernel")`（即 nt_qq_<path_hash> 目录名——可反向定位库目录）→ `rand` = 头部 protobuf field2（每库 8 字符 ASCII）→ `key = md5(uid_hash + rand)`（32-hex 字符串密钥）。**1024 字节头必须剥离后才能交给 sqlcipher**（:17-18）；`parse_header`（:91）手工 varint 解析、`looks_encrypted`（:145）判形态、`decrypt_file`（:191）复制+剥头+sqlcipher3 打开（密码参数 sweep-verified：page 4096/kdf_iter 4000/HMAC_SHA1/PBKDF2_HMAC_SHA512，:16-17）。

### 4.4 老版 QQ 4.x（qq_legacy.py）：XOR 混淆与判定

pre-NTQQ 账号库是**明文 SQLite**，TEXT 列用设备 ID 做循环 XOR 混淆（:1-12 docstring；设备 ID 是微信 CompatibleInfo.cfg 键 258 同款 `a00000420ce2b6` 形态）。可恢复面（:5-10）：Friends（好友）、TroopInfo（群）、TroopMemberInfo（群成员）、`mr_troop_/mr_friend_<md5>_New` 漫游消息（msgData XOR 即得 UTF-8）。`looks_legacy_qq4`（:42 起）：SQLite magic + 文件名 `\d{5,12}.db` + 建表指纹——create_import 入口先分流（qq_import_service.py:303-305 注释：老版"have no nt_db/ layout at all"，走 `_create_legacy_import_sync` 产出同一 graph.db，读取端点直接答 graph.db）。诚实边界（docstring :15-17）：设备 ID 只恢复出部分时，超过密钥周期的长群名/昵称可能仍是乱码——QQ 号与消息正文（14 字节全密钥可解）是取证承重字段。

### 4.5 WhatsApp：Apple 纪元与类型标签（whatsapp_import_service.py）

iOS 库是 Core Data 明文表：`ZWAMESSAGE`/`ZWACHATSESSION`（:12-15）。`ZMESSAGEDATE` 是 Apple 纪元（2001-01-01，偏移 `APPLE_EPOCH_OFFSET=978307200`，:34-35），`apple_to_unix`（:125）按**数值量级分类**秒/毫秒——不同备份版本精度不同，靠量级判断而非配置。`_resolve_sources`（:170-227）：db_path 给目录时自动拾取同目录 ContactsV2/CallHistory。`_build_graph_db`（:244+）：先读 sessions（显示名+JID），逐条读消息（newest last 让时间线顺读，:287 注释），`_jid_to_number` 归一 JID、`_is_group_jid` 判群（:228-243）；通话记录经 `_append_calls`（:459）并入。`MESSAGE_TYPE_LABELS`（:39-52）把 ZMESSAGETYPE/ZFLAGS 映射成面板直显的中文标签。消息上限 `MAX_MESSAGES=2_000_000`（:55）。

### 4.6 ensure_graph_db：自愈与过期判定（qq_import_service.py:1344-1427，微信同构）

`/api/wechat/graph` 等下游解析导入 id 时调用：graph.db 缺失或 `_graph_db_stale`（:1414-1426："graph.db exists but carries no messages while nt_msg.db does"——解密成功但归一化失败的导入）即从解密库重建；老版导入走 `_ensure_legacy_graph_db`。这让"导入时归一化失败"的库在首次访问图谱时自愈，而不是让面板空转（wechat_graph_models.py:166-170 注释明说此动机）。

## 5. 数据流（读什么、写什么）

**读**：源库一次（导入时复制/解密）；后续查询全部打导入目录自己的产物（nt_msg.db/graph.db/EnMicroMsg.db），`_connect` 只读打开。**写**：仅导入目录。解密失败的导入**保留现场**：meta.status=failed + error + source/ 副本仍在（微信 ：357-361）——便于换密钥重试或人工分析，而不是删目录假装无事。

## 6. 边界与已知状态

- **密钥材料优先级**：显式 password > key_material 推导 > 检材自动 harvest（微信）；QQ 同构（password > nt_uid+rand）。三者都失败 → 微信抛 WeChatDecryptError（"no password given and none could be derived from key material"，wechat_import_service.py:352-354）、QQ 抛 QQDecryptError。
- **meta 是唯一状态**：无 DB、无跨进程锁——并发 create 各自生成独立 import_id 目录，互不干扰；status 字段只是账本，没有"进行中"的调度语义（导入是同步完成的）。
- **qq_legacy 长名可能乱码**（docstring :15-17）：设备 ID 部分恢复时超周期的字符串解不全——读取端点原样呈现乱码，不猜。
- **微信 B scheme（FTS 库）与主库分开解**：口令公式不同（MD5(UIN+IMEI+wxid)[:7]），wechat_decrypt 的 scheme 探测按库分派。
- **无删除保护**：DELETE 直接删导入目录（路由层 removed 布尔），无回收站。

## 7. 如何验证

- 单测：`python_service/tests/unit/` 下 wechat_decrypt/qq_decrypt/qq_legacy/*_import_service 测试（密钥推导向量、scheme 探测、header 解析、XOR 还原、归一化计数）。
- 路由契约：[../httpserver/routes/IMForensics.md](../httpserver/routes/IMForensics.md) 第 7 节。
- 活体验证：拿一份只给 db_path 的微信库导入（不给 password），meta.decryption.formula 应记录命中的推导公式；对老版 QQ 库导入，meta.format=legacy_qq4 且目录无 nt_msg.db；两份导入在 `/api/wechat/graph?task_id=wx_/qq_<id>` 下出图。

相关阅读：[../httpserver/routes/IMForensics.md](../httpserver/routes/IMForensics.md)（路由面）、[CommGraphService.md](CommGraphService.md)（跨源消费）、[WeChatGraphService.md](WeChatGraphService.md)（graph.db 的指标计算）、[TimelineSummaryService.md](TimelineSummaryService.md)（qq_legacy 时间源）。

## 8. 二轮深化 A：为什么微信解密要"逐候选试页签名"而不是验一次 HMAC

wechat_decrypt 的候选枚举（derive_candidates 返回 2-4 个公式）配合 `detect_scheme(db, password_bytes)` 逐个试，看似低效，实则是对 SQLCipher 语义缺陷的精确绕行：官方 `PRAGMA key` 验证依赖 HMAC 比对，而微信主库 scheme A **根本无 HMAC**（reserve 16 字节全是 IV），FTS scheme B 的 HMAC 参数又与主库不同——同一个密码在 A 上"正确"的表现方式是页头签名匹配，不是 HMAC 通过。`_is_sqlite_page`（:71-80）检查的四项（BE 页大小、read/write 版本 ∈{1,2}、64/32/32 配比）是 SQLite 页头中**与加密参数无关**的不变量，所以一次页解密即可判定密钥正确与否，与 HMAC 配置解耦。这也是 docstring"one check covers every HMAC combination"的落地。副作用是解密器必须自己处理两套 reserve 布局（A: IV 在页尾；B: IV 在头 + 32 字节 digest 在尾）与 WAL 的独立校验和（`_wal_checksum`，:112-121）——这些复杂度被封装在 decrypt_file 之内，导入服务只见 scheme/params/pages 三个结果字段。

## 9. 二轮深化 B：老版 QQ 为什么"复制原库 + 只产 graph.db"

`_create_legacy_import_sync`（qq_import_service.py:434-455）对老版库的处理是三平台里最"薄"的：原库原样复制进 source/（它已经是明文，无解密产物），归一化直出 graph.db，**不产 nt_msg.db**（docstring :436-441："the read endpoints answer from graph.db for these imports, so no native nt_msg.db is produced"）。这个决定由两个事实推出：① 老版库的表结构（Friends/TroopInfo/mr_* 漫游表）与 NTQQ（c2c_msg_table/group_msg_table）完全不同，硬造一个"nt_msg.db 形状"的假象只会误导；② 读取端点的所有查询本来就有 legacy 分支（`_is_legacy` :1058-1059 按 meta.format 分派到 `_legacy_*` 方法族 :1067-1330），graph.db 的 wechat_* 形状让下游（图谱/时间线）完全无感。meta.json 的 `format` 字段因此成为整个导入族的**格式判别器**：timeline_sources 读它选 qq_legacy 时间源（timeline_summary.py:52-62），读取端点读它选方法族——一个字段驱动三处分派。

**最后更新**: 2026-11-10（新建：三平台 IM 导入服务文档）
