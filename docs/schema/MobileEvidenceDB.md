# 统一取数包库（`<base>_mobile_evidence.mep.db`）字段参考（定义位置：`src/analyzers/AndroidAnalyzer/MobileEvidenceSchema.h`，namespace `mobile_evidence::schema`）

> 统一取数包（.mep.db）是手机备份取证的**中间交换格式**：美亚/MIUI/鸿蒙/雷电等异构备份先被适配器规约成同一个 Package（`MobileEvidencePackage.h`），落成这个 SQLite 包库，再由分析层原样搬进 android.db。它不建在 android.db 里，也不在 files.db 派生链上——它是"采集产物"，android.db 是"分析产物"。设计约束（`MobileEvidenceSchema.h:4-11` 文件头原文要点）：三张主表 + 一张覆盖表固定；**记录表不随厂商增减列**，厂商差异全部落 `raw_json`/`payload_json`；`UNIQUE(source_path, source_table, source_key)` 保证重复导入幂等，`source_key` 为空（整包导出）时靠 `row_uid` 兜底。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `mobile_evidence::Writer`：`open()` 执行单条 `kDDL`（`MobileEvidenceSchema.h:20-89`，调用 `MobileEvidencePackage.cpp:100-112`）；`writePackage()` 在 `BEGIN IMMEDIATE` 事务内写四表（`:119-369`：meta `:145`、record `:234`、file `:315`、coverage `:340-344`） |
| 谁读 | `mobile_evidence::Reader`（`MobileEvidencePackage.cpp:386` 起）以 `SQLITE_OPEN_READONLY` + `PRAGMA query_only=1` 双重只读打开（`:399,404`）；分析入口 `mobile_evidence::analyzePackage`（`MobileEvidenceAnalysis.cpp:231`）把包内容回写 android.db |
| 文件位置 | HTTP 任务：`data/tasks/<task_id>/<base>_mobile_evidence.mep.db`（`TaskManagerAnalysis.cpp:1421,1842,2107`）；CLI：镜像/备份同目录（`AnalysisOrchestrator.cpp:788,1000`）。CLI 支持直接对 `.mep.db` 做分析（`--mobile-package`，分析-only 模式，`AnalysisOrchestrator.cpp:837`） |
| 元数据键 | 键名集中在 `mobile_evidence::schema::meta_key`（`MobileEvidenceSchema.h:92-105`）：`format`/`schema_version`/`created_at`/`record_count`/`file_count`/`coverage_count`/`adapter_name`/`adapter_version`/`platform`/`device_json`/`acquisition_json`/`manifest_json`——采集层与分析层共用，避免字符串漂移 |

## 表清单总表（4 表 + 1 视图）

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `mobile_evidence_meta` | 元数据 | 设备/采集/适配器键值（键名见 meta_key） | 2 |
| `mobile_evidence_record` | 记录 | 规范化记录（消息/联系人/通话等，厂商差异进 JSON） | 26 |
| `mobile_evidence_file` | 文件 | 包内文件清单（媒体/附件等证据文件） | 10 |
| `mobile_evidence_coverage` | 覆盖 | 按工件种类的解析覆盖情况（成功/失败留痕） | 7 |
| `v_record_flat`（视图） | 记录 | 把 record 的常用列拉平供分析层直接 SELECT（`MobileEvidenceSchema.h:83-88`） | 15 |

## 逐表字段说明

### mobile_evidence_meta（`MobileEvidenceSchema.h:21-24`，写入 `MobileEvidencePackage.cpp:145`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| key | TEXT | PRIMARY KEY | 元数据键（meta_key 常量：format、schema_version、device_json 等） |
| value | TEXT | — | 值（device_json/acquisition_json/manifest_json 存 JSON 全文） |

写入用 `INSERT OR REPLACE`，键级 UPSERT。

### mobile_evidence_record（`:26-53`，写入 `MobileEvidencePackage.cpp:234`）

规范化记录主表。25 个数据列刻意**不随厂商增减**——新厂商的新字段进 `raw_json`/`payload_json`，不 ALTER 表。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| row_uid | TEXT | NOT NULL UNIQUE | 行唯一标识（source_key 为空的整包导出靠它兜底，防同秒多行互覆） |
| kind | TEXT | NOT NULL | 规范种类（contact/message/call_log 等分析层语义） |
| native_kind | TEXT | — | 厂商原生种类（如 Harmony/ThunderForensic 的 kind 原值） |
| mobile_artifact | INTEGER | NOT NULL DEFAULT 0 | 1 = 归 `mobile_artifacts` 族（分析层按原 schema 回写 android.db，见 AndroidDB.md 统一备份组） |
| package_name | TEXT | NOT NULL DEFAULT '' | 归属应用包名 |
| app_index | INTEGER | NOT NULL DEFAULT 0 | 应用序号（多应用备份分桶） |
| source_path | TEXT | NOT NULL DEFAULT '' | 源文件在备份内路径（幂等键之一） |
| source_table | TEXT | NOT NULL DEFAULT '' | 源表名（幂等键之二，可为空） |
| source_key | TEXT | NOT NULL DEFAULT '' | 源行键（幂等键之三，可为空；UNIQUE(source_path,source_table,source_key)） |
| raw_json | TEXT | NOT NULL DEFAULT '{}' | 源记录原文 JSON（厂商差异在此，不改表） |
| payload_json | TEXT | NOT NULL DEFAULT '{}' | 规范化后载荷 JSON（分析层消费的键值） |
| timestamp_raw | TEXT | — | 原始时间串（单位不限） |
| timestamp_unit | TEXT | — | 时间单位标注（unix_s/apple_epoch_ns 等） |
| timestamp_seconds | INTEGER | — | 归一化 unix 秒（跨源排序轴） |
| source_sha256 | TEXT | — | 源库文件哈希（防篡改对质） |
| source_wal_sha256 | TEXT | — | 源 WAL 文件哈希（有 WAL 时） |
| parser_version | TEXT | NOT NULL DEFAULT '' | 解析器版本 |
| related_path | TEXT | — | 关联文件（消息附件等）在包内路径 |
| related_status | TEXT | — | 关联文件状态（提取成功/缺失等） |
| database_path | TEXT | — | 来源数据库路径（数据库类工件） |
| database_table | TEXT | — | 来源数据库表名 |
| database_columns_json | TEXT | — | 来源表列清单 JSON（盘点用） |
| database_open_status | TEXT | — | 来源库打开状态（明文可开/加密/损坏） |
| database_row_count | INTEGER | — | 来源表行数 |
| status | TEXT | NOT NULL DEFAULT 'parsed' | 行状态（parsed 等） |

索引 3 个（`:54-56`）：`idx_mer_kind(kind, id)`、`idx_mer_package(package_name, id)`、`idx_mer_time(timestamp_seconds)`。

### mobile_evidence_file（`:58-69`，写入 `MobileEvidencePackage.cpp:315`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| relative_path | TEXT | NOT NULL UNIQUE | 包内相对路径（幂等键） |
| file_name | TEXT | — | 文件名 |
| extension | TEXT | — | 扩展名 |
| category | TEXT | — | 类别（媒体/文档/数据库等） |
| package_name | TEXT | — | 归属应用包名 |
| size | INTEGER | NOT NULL DEFAULT 0 | 字节数 |
| modified_time_ms | INTEGER | NOT NULL DEFAULT 0 | 修改时刻（毫秒） |
| sha256 | TEXT | — | 内容哈希 |
| status | TEXT | NOT NULL DEFAULT 'parsed' | 文件状态 |

索引 1 个（`:70`）：`idx_mef_category(category)`。

### mobile_evidence_coverage（`:72-81`，写入 `MobileEvidencePackage.cpp:340-344`）

按工件种类记录"解析到了什么程度"，失败/跳过也留痕——结论的覆盖边界由此表对质。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| artifact_kind | TEXT | NOT NULL, UNIQUE 组合 | 工件种类 |
| source_path | TEXT | NOT NULL DEFAULT '', UNIQUE 组合 | 来源路径（`UNIQUE(artifact_kind, source_path)`） |
| status | TEXT | NOT NULL | 解析状态（ok/failed/skipped 等适配器自述） |
| native_status | TEXT | — | 厂商原生状态 |
| detail | TEXT | — | 细节（失败原因等） |
| record_count | INTEGER | NOT NULL DEFAULT 0 | 该工件产出的记录数 |

### v_record_flat（视图，`:84-88`）

把 record 的常用键提成平铺列（id/kind/native_kind/mobile_artifact/package_name/app_index/source_path/source_table/source_key/timestamp_raw/timestamp_unit/timestamp_seconds/status/raw_json/payload_json），保留完整原文；分析层与临时排查直接 SELECT 视图即可。

## 与 android.db 的关系（回写路径）

`mobile_evidence::analyzePackage`（`MobileEvidenceAnalysis.cpp:231`）用 Reader 读包，按 kind 分派写 android.db：

- **清单/文件**：非数据库条目回写 `miui_external_files`；数据库成员的盘点由 `android_source_coverage` 承载（`MobileEvidenceAnalysis.cpp:298-299` 注释原文）。
- **清单头**：`manifest.targetTable` 分派——MIUI 落 `miui_backup_manifest`，鸿蒙/雷电（`mobile_backup_manifest`）按 `mobile_backup_schema::DDL` 现建表后单行回写（`MobileEvidenceAnalysis.cpp:202-227,247-252`）。
- **记录**：`mobile_artifact=1` 的记录按原 schema 写 `mobile_artifacts`（`insertMobileArtifact`，`MobileEvidenceAnalysis.cpp:25-58`）；其余按 kind 写 contacts/call_logs 等既有表。

## 写入时序

| 表 | 写入方 | 时机 |
|----|--------|------|
| 四表全量 | `mobile_evidence::Writer::writePackage`（单事务） | 适配器构建完 Package 后：美亚（`TaskManagerAnalysis.cpp:1868`）、鸿蒙（`:1422`）、MIUI/雷电（`:2108`）；CLI 侧 `AnalysisOrchestrator.cpp:788,1000` |
| 四表读取 | `mobile_evidence::Reader`（只读双保险） | 分析阶段 `analyzePackage`；CLI `--mobile-package` 分析-only 模式 |

适配器清单：`MobileEvidenceMeiyaAdapter` / `MobileEvidenceMiuiAdapter` / `MobileEvidenceHarmonyAdapter`（鸿蒙）+ ThunderForensic 通用适配器（OPPO/vivo/一加等，见 AndroidDB.md）。

## 跨表关联键

- `mobile_evidence_record.related_path` ↔ `mobile_evidence_file.relative_path`（消息附件对质）。
- `mobile_evidence_record.source_path` ↔ `mobile_evidence_coverage.source_path`（某文件解析出多少记录、状态如何）。
- `mobile_evidence_record.kind` / `mobile_artifact` 决定回写 android.db 的目标表（决定三：分派逻辑在 `MobileEvidenceAnalysis.cpp`，不在 schema）。

真实 JOIN 示例（某工件失败明细与产出记录数对质）：

```sql
SELECT c.artifact_kind, c.status, c.detail, COUNT(r.id) AS records
FROM mobile_evidence_coverage c
LEFT JOIN mobile_evidence_record r
       ON r.source_path = c.source_path
GROUP BY c.artifact_kind, c.source_path
ORDER BY c.status DESC;
```

## 已知边界

- **包库是"规约层"不是"事实层"**：事实仍在原始备份里；包库的 raw_json 保留原文，但 file 清单只含适配器选择的文件（不是全备份遍历）。
- **只读是双保险不是加密**：Reader 用 READONLY 打开 + `PRAGMA query_only=1`（`MobileEvidencePackage.cpp:399,404`），文件本身是普通 SQLite，可被任意工具写。
- **record 表的 database_* 五列**仅数据库类工件填写；消息类记录这五列恒 NULL。
- **幂等两把钥匙**：`(source_path, source_table, source_key)` 唯一 + `row_uid` 全局唯一；两者语义不同——前者防"同源重复导入"，后者防"同秒多行互覆"（`MobileEvidenceSchema.h:9-11` 注释）。
- **视图不建索引**：`v_record_flat` 只是 SELECT 语法糖，时间过滤仍走 `idx_mer_time`。

---

## 自检清单

- [ ] mobile_evidence_meta 的 `record_count`/`file_count`/`coverage_count` 与各表实际行数一致（写入方在 `writePackage` 收尾统计）
- [ ] mobile_evidence_coverage 无未解释的 failed/skipped 行（影响分析结论覆盖边界）
- [ ] `schema_version` 与当前代码期望一致（跨版本包复用旧分析路径前先核对）
- [ ] 分析阶段回写 android.db 后，android_source_coverage 的状态与包内 coverage 对质

**最后更新**: 2026-11-10（新建：统一取数包库字段参考）
