# 雷电手机快取（ThunderForensic）提取

通用 Android 逻辑提取适配器。同一套代码处理 OPPO、vivo、一加等品牌的雷电手机快取工程，取代原 OPPO 专用适配器；旧来源名 `oppo-backup` 保留为别名并归一为 `thunder-backup`。

本适配器解析已提取出的容器，不实现解锁、提权、备份外层解密或手机仿真。容器可读不代表每个提取器都成功，也不代表应用数据库明文可读。

## 输入形态

`ThunderForensic.json` + `PhoneData/` 成员是识别标志；扫描是有界头遍历，命中才标 `thunderforensic_backup` / `thunder-backup`。

- 工程目录：`<root>/filesystem/1/tar/*.tar`，或 tar 直接放在工程根目录。
- 容器文件：直接传入 tar。
- 选择 `dir` 或其他来源时，只要实际是雷电提取即自动提升为 `thunder-backup`。

```bash
./build/forensic_analyzer /path/to/20261025OPPO \
  --android-analyze --android-source thunder-backup --no-ai --db-dir /path/to/results
```

CLI 结果沿用 `<baseName>_files.db`；HTTP Task 结果在 `android.db`，由 `metadata.android_db` 绑定，`android_source` 归一为 `thunder-backup`，`metadata.device_brand` / `device_model` 取清单品牌型号。

## 容器索引

不经过 libarchive：写入器会给成员头写非八进制 gid（`-6667000`），vivo 样本连**第一个**成员都是这样，libarchive 在 open 阶段即拒收整个容器。`ThunderForensicBackupExtractor` 直接 mmap 只读映射，逐 512 字节校验 ustar magic 与头校验和，按 offset 跳过数据块，并解析 GNU `L` 长名与 PAX `path`/`size`。53 GiB 的 vivo 容器索引约 30 秒（libarchive 路径需要数分钟且会先失败）。

- 重复成员（vivo 有 486 个）保留首次出现，其余计入 `duplicate_members` 覆盖明细。
- 成员数据按需从容器偏移读取，不整体解包；路径穿越与写回检材均被拒绝。
- 容器大小、mtime 在每次提取前复验，变化即 `EVIDENCE_CHANGED_AFTER_INDEX`。
- 完整 SHA-256 只对 ≤ 4 GiB 容器计算。超过阈值记录 `container_sha256_status=not_computed_large_container`，不静默省略；成员级哈希仍逐条记录在 `android_source_provenance`。

## 解析范围

| 成员 | 处理 |
| --- | --- |
| `ThunderForensic.json` | 品牌/型号/系统/厂商版本/任务时间 → `mobile_backup_manifest`，并抽取清单里的 IMEI/MEID/序列号/MAC |
| `PhoneData/*.json` | 逐条写入 `mobile_artifacts`（kind 按成员语义），并投影到 `installed_apps` / `wifi_networks` / `contacts` / `call_logs` / `sms_messages` / `device_identifiers` |
| `PhoneData/siminfo.json` | SIM 记录另抽 ICCID/IMSI/号码（vivo 有 2 条真实记录）；提取器错误串按 `parse_failed` + `extractor_error: …` 保留原因 |
| `wifi.xml` | vivo shared_prefs 兜底：解 4 字节大端分块封装 + HTML 实体 + JSON，`wifi_saved_network` 写入 WiFi 标准表，`allowedKeyManagement` 映射为 `NONE\|WPA_PSK` 等标签 |
| `note.zip` / `encryptNote.zip` | 解分块封装后读 ZIP 中央目录（不信任被前缀位移的本地头偏移），条目名与加密标志记入 `note_archive`；加密内容不尝试解密，覆盖记 `LOCKED` |
| `encryptContact.vcf` / `encryptSms.xml` | 空文件记 `empty`，非空记 `LOCKED`（无密钥） |
| `.backup` | 雷电标记文件，内容按 JSON 透传到 `device_marker` |
| `LogData/*.log` | 清单（名称/大小/mtime）记 `device_log`；不做逐行日志解析 |
| `sdcard/**` | 只做成员清单与字节统计，载荷留在容器内 |
| `<package>.tar/`、`<package>.ab/` 等 | 按包聚合为 `app_data_container`，数据库文件另记 `app_database` 并在 `app_db_inventory` 之外保留 `related_path`；不逐库解密 |
| `data/evidence_<n>_<kind>` | 雷电快取自身解析出的案件库（工程目录形态）：每库一张表，逐行读入 `mobile_artifacts`；SMS/通话/联系人/WiFi/应用/SIM 另投影标准表 |

案件库是容器层的重要补充：vivo 样本**没有** `PhoneData/smss.json`，但 `data/evidence_1_sms` 有 2079 条短信；OPPO/OnePlus 的 `evidence_1_file`、`webhistory`、`searchhistory`、`downloadfile` 等也只存在于案件库。两层同时存在时按“行来源成员”去重——案件行的 `src_file_path` 指向已被容器层解析的成员（或该族案件行完全无来源，如 vivo 的 3615 条 provider 联系人）就不再重复入库，跳过条数记在聚合覆盖的 `skipped_duplicate_rows=`。已知后缀映射到语义 kind（`application`/`sms`/`call_log`/`contact`/`wifi`/`im_message`/`file_inventory`/`web_history`…），未识别后缀落为 `case_<suffix>`，仍保留整行 JSON。单个案件库读取上限 5 万行，超出记 `PARTIAL` + `truncated_at`。

其他约定：

- 时间按 ISO-8601 解析（含 `±HH:MM` 时区偏移）→ `timestamp_seconds`；标准表 `date` 使用同一 epoch 秒。
- 案件库的时间是**无时区本地时间字符串**（`2019-04-23 03:49:54`），不做时区推断：只保留 `timestamp_raw`，`timestamp_seconds` 为空，避免虚构 UTC 时刻。
- 通话类型 `outgoing/incoming/missed…` 与短信 `inbox/sent…` 映射为 Android provider 数值。
- WiFi SSID 去掉写入器的引号包裹，`LastConnected` 等非 ISO 值保留原文。
- `application.json` 的 `Delete` 字段语义未定，只随 `record_json` 透传；案件库的 `delete` 列以 `thunderforensic_delete` 保留，不做删除判定。
- OPPO 的 `contacts`/`calllogs`/`smss` 样本为空数组，按 `empty` 记录，不代表设备上不存在。

## 覆盖与来源

`android_source_coverage` 逐成员给 `parsed` / `empty` / `parse_failed` / `LOCKED` / `indexed` / `not_found`，并带 `rows=` 与 `standard_table_rows=`；合成聚合项：`<containers>`、`wifi_xml`、`note_archive`、`encrypted_artifact`、`vendor_archive`、`<LogData>`、`<sdcard>`、`case_database`/`<data>`、`container_root:thunder-backup`。`android_container_coverage` 记录容器名、哈希策略与重复成员数。每条解析过的成员在 `android_source_provenance` 留有 `thunder-backup` / `thunderforensic-v2` 来源行与 SHA-256；案件库作为解析派生物单独一行（`source_member_path=evidence_*`）。

## 限制

- 不解析 LogData 逐行内容，不展开 sdcard 载荷，不打开 `<package>` 内的加密数据库。
- note.zip 等加密归档只列出条目，需外部密钥。
- 案件库本地时间无时区，只保留原文，不做 UTC 换算。
- 案件库单库上限 5 万行（vivo `evidence_1_file` 301804 行、`evidence_1_cloudfile` 71680 行会记 `PARTIAL`），完整清单需另行导出。
- 53 GiB 容器不整体哈希；需要全量哈希时应在任务外单独计算并留存记录。
- 媒体 `related_path` 仅在会话内 sdcard 有精确同名成员时置为 `present_in_container`；否则不推断设备上是否存在。

## 验证

```bash
cmake --build build -j32
ctest --test-dir build --output-on-failure \
  -R 'ThunderForensic|HarmonyBackupTests|Miui|ChineseReport'
```

`mobile_artifacts.source_key` 必须是 JSON 对象（`{"row":N}`、`{"section":…,"row":N}`、`{"member":…}`、`{"archive":…}`、`{"container":…}`）：`android_artifact_reader.artifact_detail` 会 `json.loads` 它作为行主键，并把 `mobile_backup_manifest.platform` 作为来源平台标签。合成与真实样本测试都断言这一点，以及冻结（`freeze_selected_result`）能成功。

- `test_thunderforensic_backup_cli.py`：三种品牌合成容器（每头非法 gid、GNU 长名、重复成员、清单置尾、分块 wifi.xml、加密 note 归档、`<package>.ab` 数据树）加 8 个合成案件库，tar / 工程目录 / 根目录直放 tar 三形态；断言案件库补齐短信、同名案件行被去重、`source_key` 为 JSON 对象、旧别名与 `INVALID_THUNDERFORENSIC_BACKUP`。
- `test_thunderforensic_backup_http.py`：隔离 HTTP 服务 + 智能分析桩，OPPO tar、OnePlus 目录自动提升、vivo 旧别名三个任务均 COMPLETED、来源归一、manifest/overview 出数。
- `test_thunderforensic_real_samples.py`：三个真实工程目录的 CLI 断言（OPPO 989 工件/7 案件库、OnePlus 6004 工件/4 个 App 容器/10 案件库、vivo 204690 工件/165 容器/23 WiFi/7005 联系人/5010 通话/48 案件库），真实 OPPO 的 HTTP 任务、raw tar 直读，以及 `android_artifact_reader` + `freeze_selected_result` 逐 kind 契约检查；样本缺失时 SKIP。

```bash
python3 tests/integration/test_thunderforensic_real_samples.py \
  --analyzer build/forensic_analyzer --samples-root /path/to/samples
```

检材和解析出的个人数据不进入仓库。
