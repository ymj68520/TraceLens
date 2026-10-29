# 手机取证统一取数格式（Mobile Evidence Package）

> 状态：v1 已实现并通过单元测试与 CLI 端到端验证。
> 代码：`src/analyzers/AndroidAnalyzer/MobileEvidence*.{h,cpp}`

## 1. 解决什么问题

改造前，每个来源适配器（MIUI、鸿蒙、雷电、目录、ZIP、EXT4/F2FS）都把解析结果**直接写进 `android.db`**。这带来三个后果：

1. **取数与分析耦合**：新增一种手机/一家取证软件的格式，必须同时改动分析层和数据库 schema。
2. **信息被过早裁剪**：写库时只保留分析层当前关心的列，原始行、时间原文、来源定位在中间环节就丢了。
3. **缺失无法区分**：某类工件没解析出来，与"设备上本来就没有"，在下游看起来一样。

v1 引入一个**固定骨架 + 可扩展载荷**的中间格式：适配器只负责产出它，分析层只负责消费它。

```
原始检材 ──[取数适配器]──> .mep.db ──[统一分析]──> android.db / 报告 / 时间轴
   MIUI / 鸿蒙 / 雷电 / iOS / UFED / 厂商导出      （唯一格式，一次实现）
```

## 2. 物理形态

单文件 SQLite，后缀 `.mep.db`。选 SQLite 而不是 JSON/protobuf 的理由：可增量写、可直接用标准工具查询取证、天然带事务、不需要额外解析器，且与仓库既有产物（`android.db`、`files.db`）同构，运维与归档流程不用变。

写入端整个包在一个事务内完成，失败回滚，不留半成品。分析端以 `PRAGMA query_only=1` 只读打开，保证取数产物不可被分析阶段篡改。

## 3. 数据结构

四张表，字段固定，不随厂商增减。

### 3.1 `mobile_evidence_meta` —— 设备与采集元数据

键值表。两个 JSON 聚合键承载结构化信息：

| 键 | 内容 |
|---|---|
| `format` | 固定 `tracelens.mobile.evidence`，用于识别 |
| `schema_version` | 当前 `1` |
| `device_json` | 设备：平台/厂商/型号/OS 版本/序列号/IMEI/MEID/ICCID/本机号/Android ID/UDID/时区 |
| `acquisition_json` | 采集：适配器名与版本、来源类型与路径、容器哈希、采集时间、提取人、取证软件版本 |

设备字段覆盖 Android、iOS、HarmonyOS 的并集；某平台没有的字段留空，不改变结构。

### 3.2 `mobile_evidence_record` —— 规范化记录（核心表）

一条记录 = 一个可独立引用的取证事实（一条短信、一次通话、一个联系人）。

| 列 | 作用 |
|---|---|
| `kind` | 语义类别，见 §3.5。分析层据此分派 |
| `package_name` / `app_index` | 所属应用；`app_index` 区分同包多账号/多实例 |
| `source_path` / `source_table` / `source_key` | 四级来源定位，可回溯到原始行 |
| `raw_json` | **完整原始行**，未改写 |
| `payload_json` | **规范化投影**，分析层直接取用；是 `raw_json` 的子集 |
| `timestamp_raw` / `timestamp_unit` / `timestamp_seconds` | 时间原文 + 单位 + 规范化秒值 |
| `source_sha256` / `source_wal_sha256` | 源库与旁路 WAL 哈希 |
| `parser_version` | 产生该行的解析器版本 |
| `related_path` / `related_status` | 关联外部文件（媒体、附件） |
| `status` | `parsed` / `partial` / `locked` / `unsupported` / `malformed` / `failed` |
| `row_uid` | 幂等键 |

**双 JSON 设计是关键**：`raw_json` 保证"不丢信息"——厂商新增字段、分析层暂时不认识的字段，都原样留着；`payload_json` 保证"分析层好用"——常用键已经是稳定名字，分析代码不依赖各来源的原始列名。两者分离后，新增来源只需正确填这两个字段，分析层零改动。

`row_uid` 在 `source_key` 存在时由 `kind|package|app_index|path|table|key` 组成；缺失时追加行内序号兜底，避免无主键来源的记录互相覆盖。

### 3.3 `mobile_evidence_file` —— 文件清单

不逐行解析的二进制（照片、视频、文档、未解密数据库）也必须有条目。`category` 分 `image/video/audio/document/database/archive/other`，`status` 复用 §3.4 语义。**没有这张表，未解析的媒体就等于"不存在"**。

### 3.4 `mobile_evidence_coverage` —— 覆盖度声明

`artifact_kind` + `source_path` + `status` + `detail` + `record_count`。

这是与"空表"划清界限的关键：适配器即使在某个类别上一行都没产出，也要写一条明确声明（`no_candidate_path` / `locked` / `unsupported`）。下游看到空结果时，能区分"本次没取到"与"检材里没有"。

### 3.5 类别（`kind`）命名空间

已定义并有落地路径：

| 类别 | 分析目标表 |
|---|---|
| `contact` | `contacts` |
| `call_log` | `call_logs` |
| `sms` | `sms_messages` |
| `note` | `app_notes` |
| `installed_app` | `installed_apps` |
| `wifi_network` | `wifi_networks` |
| `device_identity` | `device_identifiers` |
| `database_table` | `app_db_inventory` |
| `generic` + `nativeKind` | `mobile_artifacts`（`mobileArtifact=true` 时）|

已由美亚适配器产出并落入覆盖度/文件表、但尚无专用分析落表的类别：`calendar_event`、`wifi_network`、`account`、`media_file`、`document_file`、`system_log`、`generic`。

已预留、当前只计入覆盖度的类别：`mms`、`im_message`、`im_conversation`、`im_contact`、`browser_history`、`browser_bookmark`、`device_identity`、`location`。

**新增类别的完整流程**：在 `kind::` 加常量 → 适配器产出该类别 → 在 `MobileEvidenceAnalysis.cpp` 的 `analyzePackage` 加一个 `else if` 分支与写入函数。表结构不用动。

## 4. 使用方式

### 4.1 取数（阶段一）

```bash
./build/forensic_analyzer /path/to/miui_backup \
  --android-analyze --android-source miui-backup \
  --mobile-extract --mobile-package-out ./case.mep.db
```

产出只有 `.mep.db`，**不建 `android.db`**（`AndroidAnalyzer::setExtractionOnly`）。默认输出路径为 `<source>_mobile_evidence.mep.db`。

### 4.2 分析（阶段二）

```bash
./build/forensic_analyzer --android-analyze \
  --mobile-package ./case.mep.db --db-dir ./out
```

也可用 `--android-source mobile-evidence <pkg>`。分析阶段**完全不需要原始检材仍在原位**——包就是证据交接物。

### 4.3 兼容性

既有命令不受影响：`--android-source miui-backup` 不带 `--mobile-extract` 时仍走原来的"取数+分析合一"路径，行为与之前一致（已回归验证）。

## 5. 已接入来源

| 来源 | 适配器 | 入口 | 说明 |
|---|---|---|---|
| Xiaomi MIUI 离线备份 | `MobileEvidenceMiuiAdapter` | `--android-source miui-backup` | `miui_bak/_tmp_bak` protobuf（联系人/通话/短信/笔记） |
| 美亚柏科 MobileMaster FL-901 | `MobileEvidenceMeiyaAdapter` | `--android-source meiya` | 1024 字节 XOR 容器运行时自推导掩码；`TBL_PR_*` 映射。详见 [meiya-container-parsing.md](./meiya-container-parsing.md) |
| 华为鸿蒙已解密备份 | `MobileEvidenceHarmonyAdapter` | `--android-source harmony-backup` | 模块清单、数据库 schema 盘点与业务表行级记录（calendar/note/media/recording 等） |
| 雷电手机快取（OPPO/vivo/一加等） | `ThunderForensicArtifactParsers::buildPackageFromThunderForensic` | `--android-source thunder-backup` | PhoneData JSON、wifi.xml、LogData/sdcard 清单、per-app 数据树、note.zip 等厂商信封、`data/evidence_*` 案件库 |

三个来源都支持 `--mobile-extract` 与 `--mobile-package` 两阶段；不拆分时仍走"取数+分析合一"路径。

### 5.1 原生类别与状态词的保留

迁移不得改变下游已发布的可见值，因此格式提供两个透传字段：

- `Record.nativeKind` → 原样写入 `mobile_artifacts.kind`。鸿蒙用 `calendar`/`note`/`media` 等，雷电用 `contact`/`sms`/`app_data_container` 等，共 56 种；统一包内部仍可用通用 `kind` 分派。
- `Coverage.nativeStatus` → 原样写入 `android_source_coverage.status`。雷电的 `LOCKED`、`PARTIAL`、`indexed` 等大写词表保持不变。

没有这两个字段，迁移会把厂商词表统一成内部小写枚举，导致时间轴筛选、报告断言与既有集成测试失效（本次迁移中正是这两处被发现并修正）。

### 5.2 各来源专有的非记录产物

少数产物不属于"一条记录"，仍由适配器直接写库，不进包：

- 雷电的 `android_container_coverage`（容器哈希策略、重复成员数）
- `android_source_provenance`（成员级哈希与适配器版本）
- 雷电案件库的 provenance 行

它们由 `analyzeThunderForensicBackup` / `buildPackageFromCaseDatabases` 的调用方在分析阶段补写，`buildPackageFromThunderForensic` 通过 `caseProvenanceOut` 把案件库 provenance 交回调用方。

## 6. 如何接入新来源

以接入一家新厂商导出为例：

1. 实现一个 `buildPackageFromXxx(source, options, Package&)`，把容器成员翻译成 `Record` / `FileEntry` / `Coverage`。
2. 填 `device` 与 `acquisition`：`acquisition.adapterName` 是该来源的稳定标识。
3. 每条记录填齐 `kind`、`raw_json`、`payload_json`、来源定位、时间三元组。
4. 每个"应有而未有"的工件写一条 `Coverage`。
5. 用 `mobile_evidence::Writer` 落盘。

**不要**在新适配器里写 `android.db`，也不要在分析层加来源判断。这是该设计唯一的硬约束。

## 7. 设计取舍

**为什么保留 `raw_json` 又做 `payload_json`？** 只有 raw 则分析层要认识每个来源的列名，退回耦合；只有 payload 则信息在取数阶段就被裁剪，无法回溯。两者并存，用存储换解耦。

**为什么 coverage 是表而不是日志？** 它要参与下游判断（报告要不要写"未提取到"、UI 要不要标"锁定"），必须可查询。

**为什么不像 `mobile_artifacts` 那样只用单表 `record_json`？** `mobile_artifacts` 是鸿蒙/雷电的分析产物表，其 JSON 结构随适配器变化，下游需按 kind 特判。本格式把"取数是否完整"（coverage）与"文件是否登记"（file）独立成表，并强制时间三元组，使分析层无需解析各来源的时间语义。

**已知边界**：v1 的 MIUI 适配器只覆盖 `miui_bak/_tmp_bak` 私有 protobuf（联系人/通话/短信/笔记）、清单、外部存储与数据库清单；加密 `.bak` 仍记 `locked`；数据库内部行尚未逐条展开（登记在 `file` 表，`status=unsupported`）。这些都不需要改格式，只需在适配器侧补实现。

## 8. 验证

**单元测试**

- `test_mobile_evidence_package_gtest.cpp`（6 项）：读写往返、重复写幂等、拒绝非本格式库、MIUI 真实 protobuf 夹具的适配器产出、仅凭包重建分析结果、缺失类别的 coverage 声明。
- `test_mobile_evidence_adapters_gtest.cpp`（4 项）：鸿蒙适配器产出清单/盘点/事件记录；移走原始检材后仅凭包重建 `mobile_artifacts` + `mobile_backup_manifest`；`nativeStatus` 与 `nativeKind` 往返保真。

**端到端（取数 → 移走检材 → 分析）**

| 来源 | 取数产物 | 分析结果（检材已移走） |
|---|---|---|
| MIUI | `records=13 files=0 coverage=8` | contacts=2 / call_logs=6 / sms=2 / installed_apps=3 |
| 鸿蒙 | `records=3 files=0 coverage=7` | `mobile_artifacts{calendar:1}`、manifest=HarmonyOS、installed_apps=1、app_db_inventory=1 |
| 雷电 | `records=13 files=0 coverage=12` | artifacts `{application,call_log,contact,device_log,sms,wifi}` 各 1；`call_logs.date` 保持秒语义 |

**回归**

- `ctest -R "MobileEvidence|Miui|Harmony"`：8 个套件全通过（含鸿蒙 CLI 与 HTTP 端到端）。
- 雷电 `test_thunderforensic_backup_cli.py` / `_http.py` / `_real_samples.py`：全通过。真实样本行数与迁移前一致——OPPO 989、OnePlus 6004、vivo 204690，vivo 案件库 48 个、`PARTIAL` 截断报告仍在。
- 不带 `--mobile-extract` 的旧路径输出不变。
