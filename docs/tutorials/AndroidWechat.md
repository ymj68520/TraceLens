# Android / 微信取证端到端教程

> **目标读者**：需要从 Android 手机证据（MIUI 离线备份或逻辑提取）中恢复微信/QQNT 聊天与联系人关系，并做社会网络分析的取证分析师。
> **前置条件**：完成 [快速入门](../getting-started/QuickStart.md)；服务运行中（`./run.sh`）；如需微信解密，事先拿到 SQLCipher 密码或设备 UIN。
> **预计耗时**：45–75 分钟。
> **端口约定**：curl 用 `http://localhost:8666`（C++，run.sh 默认）与 `http://localhost:8090`（Python httpserver）。

---

## 0. 场景设定

一起电信诈骗案中，受害人转账前与"客服"在微信沟通两周。警方扣押了嫌疑人的小米手机并制作了 **MIUI 完整备份**（手机"设置 → 备份"生成的目录，含 `descript.xml` 清单和每个应用的 `.bak` 归档）。你的任务：确认机主身份、恢复与受害人的聊天记录、梳理其社交网络找到同伙。备份设置了密码，办案系统里登记为 `MiBackup#2026`。

---

## 1. 理解证据源：四种 android_source

AndroidAnalyzer 通过 `IFileExtractor` 抽象支持四种证据源（CLI `--android-source`，HTTP `android_source` 字段，取值 `tsk / dir / zip / miui-backup`）：

| 源 | 形态 | 说明 |
|----|------|------|
| `tsk` | 物理镜像 | 走 TSK 磁盘管线，产出 `_raw.db` 等，Android 工件随之分析 |
| `dir` | 已解包的 `data/` 目录树 | 逻辑提取，**跳过磁盘管线**，不产 `_raw.db` |
| `zip` | 打包的 Image.zip | 同上，需构建时带 libzip |
| `miui-backup` | 小米备份目录（`descript.xml` + `.bak`） | 本教程主路径；把备份目录当 `dir` 提交时检测到 MIUI 根标签会**自动晋升**为该模式 |

本案用 MIUI 备份。备份数据结构约定：`apps/<包名>/db/*.db` 存放各应用 SQLite，微信（`com.tencent.mm`）与 QQNT 的工件也在 tar 归档里。

**为什么先看这个**：证据源选错（比如把备份目录当镜像路径提交给 `tsk`）会得到空结果或初始化失败；这四种模式在解析器眼中透明，只有取文件方式不同。

---

## 2. 运行分析

### 2.1 CLI 路径（密码从 stdin 读，避免进入 argv）

```bash
printf '%s\n' 'MiBackup#2026' | ./build/forensic_analyzer /evidence/miui_backup/ \
  --android-analyze --android-source miui-backup --backup-password-stdin
```

产物在源目录旁：`miui_backup_files.db`（逻辑源模式下 android 工件表并入 `_files.db`）。

### 2.2 HTTP 任务路径（推荐，前端可视化依赖任务记录）

```bash
curl -X POST http://localhost:8666/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/miui_backup/",
    "scenarios": ["android"],
    "android_source": "miui-backup",
    "backup_password": "MiBackup#2026",
    "llm_analyze": true,
    "llm_mode": "smart",
    "case_description": "电信诈骗案，重点恢复微信聊天与联系人"
  }'
```

`backup_password` 仅运行期使用、不持久化（任务完成后即清除）。查询进度与产物：

```bash
curl http://localhost:8666/api/tasks/<task_id>/progress
curl http://localhost:8666/api/tasks/<task_id>/databases
```

**预期看到**：逻辑源任务阶段直达平台分析（没有 image_analysis 的长尾）；产物库为任务目录下的 `android.db`（HTTP 逻辑任务中它就是任务的结果库）。MIUI 清单解析成功时，审计日志与 `miui_backup_manifest` 表应有设备/MIUI 版本/备份日期记录。

**为什么要看**：确认备份密码正确、`.bak` 归档索引建立；如果备份未加密，去掉 `backup_password` 一样能跑。

---

## 3. android.db 查证（SQL）

表结构定义在 `src/core/DatabaseManager/SQL/android_analysis_sql.h`（通用工件表 + `CREATE_MIUI_TABLES` 的 MIUI/微信/QQNT 证据表），速查见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 5 节。HTTP 任务下对 `data/tasks/<task_id>/android.db` 执行：

### 3.1 MIUI 备份盘点

```sql
-- 备份元信息（设备型号 / MIUI 版本 / 备份时间）
SELECT device, miui_version, datetime(backup_date, 'unixepoch', 'localtime') AS backup_at,
       package_count, source_folder FROM miui_backup_manifest;

-- 各应用数据库盘点：能打开的记行数，打不开的如实登记 open_status
SELECT package_name, db_path, table_name, row_count, open_status
FROM app_db_inventory
WHERE package_name IN ('com.tencent.mm', 'com.tencent.qqnt', 'com.android.providers.contacts')
ORDER BY package_name;
```

**预期看到**：`app_db_inventory` 覆盖备份里 `apps/<包名>/db/` 下每个库；加密/损坏库的 `open_status` 会写明原因（如 `encrypted_locked`）而不是缺行——这是工具"诚实登记"的设计（[AndroidAnalyzer 文档](../modules/cpp/analyzers/AndroidAnalyzer.md) 第 4 节）。

### 3.2 微信内容表（解密成功后）

```sql
-- 机主身份（username 即 wxid，uin 是密钥推导原料）
SELECT username, nickname, uin, imei FROM wechat_owner_info;

-- 与某联系人的聊天（talker 为对方 wxid；is_send=1 是机主发的）
SELECT datetime(timestamp, 'unixepoch', 'localtime') AS at, is_send, sender_nickname,
       msg_type, content
FROM wechat_messages
WHERE talker = 'wxid_xxxxx' OR chatroom_name = 'xxxxx@chatroom'
ORDER BY timestamp;

-- 联系人与群
SELECT username, nickname, remark, chatroom_flag FROM wechat_contacts ORDER BY nickname;
SELECT chatroom_name, owner, member_count, datetime(create_time, 'unixepoch') AS created
FROM wechat_chatrooms;
```

**预期看到**：`wechat_messages` 有 `sender/receiver/content/timestamp/msg_type/is_send/chatroom_name/sender_nickname/talker` 列（增强写入，见 `INSERT_WECHAT_ENHANCED`）；未解密或部分解密时内容表可能为空，但结构证据仍在 3.3 的 inventory 表里。

### 3.3 微信/QQNT 结构证据表（MIUI 模式）

```sql
-- 微信工件的文件级清单（含解析状态与哈希）
SELECT artifact_category, format, size, parse_status, summary, source_path
FROM wechat_artifact_inventory ORDER BY modified_time DESC;

-- 恢复出的 KV / SQLite 结构化记录
SELECT namespace, key, substr(value_text, 1, 120) AS value_head, is_sensitive
FROM wechat_kv_records WHERE is_sensitive = 1 LIMIT 50;

-- QQNT 同构四表
SELECT artifact_category, parse_status, COUNT(*) FROM qqnt_artifact_inventory GROUP BY 1, 2;
SELECT source_path, table_name, artifact_kind FROM qqnt_sqlite_records LIMIT 20;
```

**预期看到**：inventory 表按 `UNIQUE(package_name, source_path)` 登记每个证据文件（`parse_status` 可为 success/parse_error/encrypted_locked 等）；`*_sqlite_records` 的 `record_json` 是逐行 JSON。QQNT 的 MMKV 私有格式未解码时会如实标注，不编造内容。

**为什么要看**：即使聊天库打不开，这些表也是"证据存在、处于何种状态"的合法鉴定材料。

---

## 4. 前端 /android 页与 MIUI 专用端点

打开 `http://localhost:8666/android`，选择任务。对应后端（C++ 侧，前缀 `/api/forensics/android/`，全部需 `task_id`，见 [C++ REST API](../api_reference/CPP_REST_API.md) 2.6）：

```bash
curl "http://localhost:8666/api/forensics/android/miui-overview?task_id=<task_id>"
curl "http://localhost:8666/api/forensics/android/miui-installed-apps?task_id=<task_id>&query=weixin"
curl "http://localhost:8666/api/forensics/android/miui-wechat-overview?task_id=<task_id>"
curl "http://localhost:8666/api/forensics/android/miui-wechat-records?task_id=<task_id>&limit=50"
curl "http://localhost:8666/api/forensics/android/miui-qqnt-overview?task_id=<task_id>"
```

通用摘要也可用：`communication-summary`（短信/通话）、`device-info`、`app-usage`。

**预期看到**：overview 返回微信/QQNT 工件的分类统计与代表性记录；`miui-db-inventory` 默认隐藏敏感值，`reveal_sensitive=1` 才显示 `value_text`（`kind=kv` 时）。

**为什么要看**：页面把 3.x 的 SQL 结果组织成可截图归档的视图，出报告时比裸表快。

---

## 5. /wechat-graph 关系图分析

前端 `http://localhost:8666/wechat-graph`（Python 侧服务，前缀 `/api/wechat`，所有 GET 需 `task_id`，见 [Python REST API](../api_reference/Python_REST_API.md) 第 12 节）：

```bash
# 全图 + 中心性指标（PageRank / 介数）
curl "http://localhost:8090/api/wechat/graph?task_id=<task_id>&include_metrics=true"

# 社区发现（Louvain；未装 python-louvain 时回退连通分量）
curl "http://localhost:8090/api/wechat/graph/community?task_id=<task_id>"

# 通信活跃时间线（默认月粒度，granularity=week 用 ISO 周）
curl "http://localhost:8090/api/wechat/graph/timeline?task_id=<task_id>"

# 某人的 ego 网络（重点联系人下钻）
curl "http://localhost:8090/api/wechat/graph/person/wxid_xxxxx?task_id=<task_id>"
```

图构建语义（[WeChatGraphService](../modules/python/services/WeChatGraphService.md)）：节点 = 机主 + 联系人；边 = 私聊聚合的有向加权边 + 群聊 1 小时窗口内成对出现的共变边。

**预期看到**：`graph` 返回 `nodes/edges/communities/metadata`（节点数/边数/UTC 时间）；节点带 `pagerank/betweenness/cluster`，边带 `weight/first/last/chatroom` 等字段。时间线每期含消息量、活跃边对与 top 联系人。这些是**定性结构**：具体数值取决于聊天量，办案时以导出的聊天原文为准。

**为什么要看**：回答"同伙是谁"——高 PageRank 的非机主节点、与机主同社区的密集小群体、时间线上与案发窗口重合的活跃边，都是下钻方向。

---

## 6. 没有真机备份时：生成微信测试数据集

教学/联调环境可用仓库自带的数据集生成器（纯 stdlib + sqlite3，幂等）：

```bash
python3 scripts/generate_wechat_dataset.py
# 产出两个库：
#   tests/EnMicroMsg_dataset.db        -- 原始 EnMicroMsg.db schema（message/rcontact/chatroom/userinfo 四表）
#   tests/wechat_dataset_android.db    -- 已规整的 _android.db schema（四张 wechat_* 表，时间戳为毫秒）
```

设计特征（脚本头注释）：1 名机主 + 49 名联系人，构成 family / colleague / friend 三个社交圈（可被 Louvain 分离），每圈 1–2 个枢纽联系人（高 PageRank/介数），10 个群聊含 2 个跨圈桥接群，默认量级约 1.2 万条会话、7000 条私聊 + 5000 条群聊。

把它接到第 5 节的图谱链路验证社区发现是否分出三个圈、枢纽人物是否浮到 PageRank 前列——这是验证整条微信分析管线（C++ 解析 → android.db → Python 图谱）最省事的方法。

**为什么要看**：真机证据不可得时，用它确认部署/版本没有回归，再上真证据。

---

## 7. 自动推导失败时的密码人工路径

微信 EnMicroMsg.db 的密码公式是 `MD5(IMEI + UIN)` 取前 7 位（[微信关系图谱设计](../superpowers/specs/2026-06-04-wechat-relationship-graph-design.md) 第 2 节）。工具链里 UIN 可恢复、IMEI 恢复不了（见第 8 节坑 1），所以人工路径是：

```bash
# ① 先跑一遍分析，让 owner_info / kv_records 落库
printf '%s\n' 'MiBackup#2026' | ./build/forensic_analyzer /evidence/miui_backup/ \
  --android-analyze --android-source miui-backup --backup-password-stdin

# ② 从库里找 UIN（两个来源交叉验证）
sqlite3 miui_backup_files.db \
  "SELECT uin FROM wechat_owner_info;
   SELECT value_text FROM wechat_kv_records WHERE key LIKE '%_auth_uin%' LIMIT 5;"

# ③ 有真实 IMEI（来自设备外壳、包装盒或运营商记录）时本地推导：
echo -n "<IMEI><UIN>" | md5sum | cut -c1-7     # 前 7 位即 SQLCipher 密码

# ④ 带密码重跑（CLI）
./build/forensic_analyzer /evidence/miui_backup/ --android-analyze \
  --android-source miui-backup \
  --wechat-password '<推导出的7位密码>'
```

打开成功的判定不是"不报错"，而是 `wechat_messages` / `wechat_contacts` 开始有数据（解密器按"SQLCipher v4 默认 → v2 传统参数 → 全版本矩阵"顺序尝试，全失败只在 lastError 记录）。设备上曾开启"微信锁"或使用新版本微信时，公式可能不适用——此时以送检单位提供的密码为准并在报告注明来源。

**为什么要看**：这是 Android 微信取证最常见的卡点；把推导过程留痕（UIN 从哪张表来、IMEI 从哪来）本身就是鉴定文书的一部分。

---

## 8. 已知坑（务必读）

1. **IMEI 缺失时密钥推导用占位值**：微信 EnMicroMsg.db 的密码推导是 `MD5(IMEI + UIN)` 前 7 位，但新版设备 IMEI 不可读，代码用硬编码占位 `1234567890ABCDEF`（`WeChatDecryptor.cpp:100`）——**自动推导大概率失败，需要人工提供密码**（`--wechat-password '<密码>'`，HTTP 任务暂无等价字段）。UIN 可从 `wechat_owner_info` 或 shared_prefs 的 `_auth_uin` 找到（[AndroidAnalyzer 文档](../modules/cpp/analyzers/AndroidAnalyzer.md) 第 5 节链路二）。
2. **加密 ADB v5 备份不支持**：`--backup-password`（argv 形式，已弃用）的实现说明写明"encrypted ADB v5 remains locked"。MIUI 备份的 AES-256 解密走 AOSP `adb backup` v5 方案的**受支持实现**（`--backup-password-stdin/-fd`）；但设计文档注明没有加密样本实测（[MIUI 备份设计](../superpowers/specs/2026-07-29-xiaomi-miui-backup-forensics-design.md) 决策 5），遇不识别的 scheme 会显式报错而不是输出错数据。
3. **构建缺 SQLCipher 时加密库只能登记**：`open_status` 会出现 `encrypted_no_sqlcipher_build`；解密前先确认 `setup.sh` 装了 libsqlcipher。
4. **逻辑源没有 `_raw.db`**：`dir/zip/miui-backup` 跳过 TSK 管线，时间线/文件分类页对该任务无数据是**正常现象**，不是故障。
5. **Chrome 历史只取单 profile**（`app_chrome/Default/History`），多 profile 不覆盖；zip 模式没编 libzip 时初始化直接失败。
6. **关系图缓存实际不生效**：路由每次请求新建服务实例，30 分钟缓存与 `POST /api/wechat/graph/invalidate` 是 no-op——行为正确但每次全量重算，大聊天量时页面偏慢（[WeChatGraphService](../modules/python/services/WeChatGraphService.md) 注意事项）。
7. **消息量不要引用页面数字当证据**：`wechat_messages` 行数是解析出的记录数，删除过的消息天然缺失；引用计数前先在报告里注明口径。
8. **`whatsapp_messages` / `telegram_messages` 表存在但源数据稀缺**：schema 里建了表，实际填充取决于证据源里是否有对应库；空表不是 bug，先查 `app_db_inventory` 里有没有对应包名的库。
9. **备份密码走 stdin 而不是 argv**：`--backup-password <pass>` 已弃用（会进入进程列表）；脚本/CI 一律用 `printf '%s\n' '<密码>' | ... --backup-password-stdin` 或 `--backup-password-fd <N>`。
10. **HTTP 任务没有 `--wechat-password` 的等价字段**：`POST /api/tasks` 只接受 `backup_password`（MIUI 备份 AES 口令）；微信 SQLCipher 密码目前只能经 CLI 注入（第 7 节路径）。前端 MIUI 页查询的是任务库，重跑 CLI 后注意库文件是 CLI 目录下的那份。

---

## 延伸阅读

- [AndroidAnalyzer 模块文档](../modules/cpp/analyzers/AndroidAnalyzer.md) — 四种证据源、MIUI 索引、SQLCipher 版本矩阵
- [WeChatGraphService](../modules/python/services/WeChatGraphService.md) / [WechatGraph 路由](../modules/python/httpserver/routes/WechatGraph.md) — 图构建与端点契约
- [微信关系图谱设计](../superpowers/specs/2026-06-04-wechat-relationship-graph-design.md) — 数据表与推导公式的历史设计
- [MIUI 备份取证设计](../superpowers/specs/2026-07-29-xiaomi-miui-backup-forensics-design.md) — `.bak` 头格式与解密分层
- [数据库模式](../architecture/DatabaseSchema.md) 第 5 节 — android.db 33 张表
- [知识图谱与报告教程](KnowledgeGraphReports.md) — 把本任务汇入案件图谱并出报告

---


## 练习与扩展实验

- [ ] 练习 1：把本教程的时间窗参数换到镜像的另一时段，重跑第 3 步查询，对比事件量分布。
- [ ] 练习 2：只改 WHERE 的一个条件（如按用户名/按目录），观察结果形态变化。
- [ ] 练习 3：用 SqlCookbook 的 ATTACH 模式把本教程两张表的查询合成一条联查。
- [ ] 扩展实验 A：给同镜像换一个 filter_profile 重跑任务，用"raw 与 filtered 对账"（SqlCookbook 第 2 条）量化画像效果。
- [ ] 扩展实验 B：触发对应平台的 LLM 重分析（/api/llm/analyze/file 或 windows-analysis），对比 llm_analyzed_at 前后的覆盖差异。
- [ ] 扩展实验 C：开启 file_carving 重跑，比较 carved_files/ 与时间线删除事件的数量关系。
- [ ] 思考题：如果时间线在案发时段完全静默，列出三种可能解释及各自的验证查询（提示：时钟/清除/过滤）。
- [ ] 思考题：本教程哪一步的结论会因为"已知恒空表"而不可靠？对照 schema 文档的已知边界复核。
**最后更新**: 2026-08-24（新建，教程）
