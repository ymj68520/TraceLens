# MobileEvidencePackage（src/analyzers/AndroidAnalyzer/MobileEvidence*）

> **一句话**：手机取证的统一取数格式——单文件 SQLite（`.mep.db`），是"取数层"与"分析层"的唯一契约：来源适配器（MIUI/鸿蒙/雷电/美亚）只负责把原始检材翻译成它，分析层只读它，不再感知任何厂商容器与 schema。

## 1. 为什么有这个模块

改造前，每个来源适配器都把解析结果**直接写进 android.db**。三个后果（`MobileEvidencePackage.h:4-14` 的头注释与 `docs/specs/mobile-evidence-package.md` §1 是同一件事的两种表述）：新增一种手机/取证软件格式必须同时改分析层和数据库 schema；写库时只保留分析层当前关心的列，原始行与时间原文在中间环节就丢了；"工件没解析出来"与"设备上本来没有"在下游看起来一样。

v1 用**固定骨架 + 可扩展载荷**的中间格式切断这条耦合：

```
原始检材 ──[取数适配器]──> .mep.db ──[统一分析]──> android.db / 报告 / 时间轴
   MIUI / 鸿蒙 / 雷电 / 美亚        （唯一格式，一次实现）
```

设计目标四条（`MobileEvidencePackage.h:4-17`）：取数与分析分离；骨架字段固定、厂商特有字段一律进 `payload_json` 不因新增来源改表；每条记录保留原始行（`raw_json`）与原始时间原文（`timestamp_raw`），规范化字段只是索引不是替代品；可追溯（来源容器/成员路径/源库哈希/解析器版本），另有 coverage 表记录"应有而没取到"。

物理形态选单文件 SQLite：可增量写、可用标准工具直接查证、天然带事务，且与仓库既有产物（android.db/files.db）同构（spec §2）。

## 2. 在系统中的位置

模块共 11 个源文件（`MobileEvidence*`：Package 与 Analysis 各含 .h/.cpp，三个适配器各含 .h/.cpp，Schema 为单头文件），分工如下：

| 文件 | 职责 |
|---|---|
| `MobileEvidencePackage.h/.cpp` | 内存模型（`Record`/`FileEntry`/`Coverage`/`Package`）+ `Writer`（落盘）+ `Reader`（只读回读）（`MobileEvidencePackage.h:86-296`） |
| `MobileEvidenceSchema.h` | 三主表 + 一覆盖表的 DDL 与元数据键名（`MobileEvidenceSchema.h:20-89`） |
| `MobileEvidenceMiuiAdapter` / `MobileEvidenceHarmonyAdapter` / `MobileEvidenceMeiyaAdapter` | 三个来源适配器（产出包） |
| `MobileEvidenceAnalysis.cpp/.h` | 分析层唯一入口 `analyzePackage`：包 → `AndroidAnalysisDatabase`（android.db）（`MobileEvidenceAnalysis.h:4-6`） |

**接线位置**：

- **CLI 取数**：`--mobile-extract` + `--android-source miui-backup|harmony-backup|thunder-backup`（`AnalysisOrchestrator.cpp:955-1014`），`AndroidAnalyzer::setExtractionOnly(true)` 后初始化只建提取器不建 android.db（`AndroidAnalyzerDeclarations.h:85-94`、`AndroidAnalyzerCore.cpp:216-235`），包写到 `--mobile-package-out` 或默认路径；`meiya` 的 CLI 分支内建了同一条"解码→包→（可选）分析"链（`AnalysisOrchestrator.cpp:743-831`）。
- **CLI 分析**：`--mobile-package <pkg>`（或 `--android-source mobile-evidence`）只读包重建 `<base>_files.db`，**不需要原始检材仍在原位**——包就是证据交接物（`AnalysisOrchestrator.cpp:277-296, 880-911`）。
- **HTTP 任务**：miui-backup/harmony-backup/thunder-backup 三来源在 AndroidAnalyzer 直写 android.db 之外**额外**产出包（失败仅 WARNING 不失败任务，`TaskManagerAnalysis.cpp:2073-2138`）；meiya 走独立的"解码→包→分析"全程分支（`:1836-1923`）。

## 3. 核心概念与设计

**三主表 + 一覆盖表**（`MobileEvidenceSchema.h:4-11` 的设计约束）：

- `mobile_evidence_meta`：键值表。`format=tracelens.mobile.evidence`（格式标识，`MobileEvidencePackage.h:33`）、`schema_version=1`（`kSchemaVersion`，`:32`）、创建时间与各类计数，聚合 JSON 键 `device_json`/`acquisition_json`/`manifest_json` 承载设备与采集元数据（键名常量在 `meta_key`，`MobileEvidenceSchema.h:92-105`）。
- `mobile_evidence_record`：核心表。`kind`（语义类别）+ `native_kind`（厂商原类别名，原样写进 android.db 的 mobile_artifacts.kind，`:88-95`）+ `mobile_artifact`（是否同时产出一条 mobile_artifacts 行，`:92-98`）+ 四级来源定位（`source_path/source_table/source_key`）+ **双 JSON**（`raw_json` 完整原始行 / `payload_json` 规范化投影）+ 时间三元组（`timestamp_raw/unit/seconds`）+ 源哈希与解析器版本 + 数据库表级盘点列 + `status` + 幂等键 `row_uid`（`MobileEvidenceSchema.h:26-53`）。
- `mobile_evidence_file`：文件清单——**没有这张表，未逐行解析的媒体/文档就等于"不存在"**（`MobileEvidencePackage.h:139-150` 的结构注释与 spec §3.3）。
- `mobile_evidence_coverage`：覆盖度声明（`UNIQUE(artifact_kind, source_path)`），区分"证据不存在"与"本次未能提取"（`:156-166`、spec §3.4）。
- 另有视图 `v_record_flat` 方便直接 SQL 消费（`MobileEvidenceSchema.h:83-88`）。

**类别命名空间（kind::*）**：23 个常量（contact/call_log/sms/mms/im_message/im_conversation/im_contact/note/calendar_event/browser_history/browser_bookmark/wifi_network/account/device_identity/installed_app/media_file/document_file/system_log/location/recording/call_recording/database_table/generic），"取值一旦发布即稳定，不得复用或改名"（`MobileEvidencePackage.h:37-61`）。`status` 词表六值：parsed/partial/locked/unsupported/malformed/failed——"取数层必须如实标注，分析层不得把非 parsed 当成有数据"（`:73-81`）。`time_unit` 六值含 `apple_epoch_s` 与未解析的 `text`（`:63-71`）。

**幂等与防覆盖（makeRowUid，`MobileEvidencePackage.cpp:66-74`）**：`row_uid = kind|nativeKind|package|appIndex|sourcePath|sourceTable|sourceKey|<行内序号>`。保留 `UNIQUE(source_path, source_table, source_key)` 是为了重复导入幂等，但 `source_key` 可能与 `source_table` 一起为空（如整包导出），此时行内序号兜底避免同一秒内多条记录互相覆盖（`MobileEvidenceSchema.h:8-11`）。

**Writer 的两个保证**（`MobileEvidencePackage.cpp:100-141`）：整个包在一个 `BEGIN IMMEDIATE` 事务内写完，任何一步失败 ROLLBACK，不留半成品；重写同一个包时先清空四张表，保证幂等。`raw_json` 解析失败时包一层 `{"__unparsed_raw": …}` 而不是让整包写入失败（`:76-86`）。

**Reader 的两个保证**（`:392-436`）：`SQLITE_OPEN_READONLY` + `PRAGMA query_only=1`——取数产物不可被分析阶段篡改；打开时校验 `meta.format` 标识，非本格式的 SQLite 会被拒绝（`not a mobile evidence package`），`looksLikePackage` 供调用方先行探测（`MobileEvidencePackage.h:292-293`）。

**默认包路径（defaultPackagePath，`MobileEvidencePackage.cpp:692-701`）**：`<来源>_mobile_evidence.mep.db`，与来源同目录。

## 4. 工作流程走读

**取数半程（适配器 → Package）**：适配器填充 `Package`（设备/采集/清单/records/files/coverage 五个部分，`MobileEvidencePackage.h:224-231`）后交给 `Writer::writePackage`。三个已接入适配器的映射粒度举例：

- 美亚：`TBL_PR_*` 一表一映射，规范键给多个候选原始列按序取值（`MobileEvidenceMeiyaAdapter.cpp:82-98, 101-193`）；
- 鸿蒙：模块清单、schema 盘点与业务表行级记录，`adapterName="harmony-backup"`（`MobileEvidenceHarmonyAdapter.cpp:146`）；
- MIUI：`miui_bak/_tmp_bak` protobuf、清单、外部存储与数据库清单，`adapterName="miui-backup"`（`MobileEvidenceMiuiAdapter.cpp:390`）。

**分析半程（analyzePackage，`MobileEvidenceAnalysis.cpp:231-324`）**：按 `kind` 分派到 android.db 标准表——contact→contacts、call_log→call_logs、sms→sms_messages、note→app_notes、installed_app→installed_apps、wifi_network→wifi_networks、device_identity→device_identifiers、database_table→app_db_inventory（`:259-282`）；其余类别先计入 `otherRecords`（"取到了但没落表"要可观察，不静默丢弃，`:283-287`）。三个兼容行为：

- 包来自鸿蒙/雷电（manifest.targetTable=mobile_backup_manifest 或有 mobileArtifact 记录）时，按 `mobile_backup_schema::DDL` 建原生结果表，保证时间轴/LLM/artifact reader 行为不变（`:236-252`）；
- `mirrorFiles` 时非数据库类文件条目回写 `miui_external_files`（`:296-309`）；
- `mirrorCoverage` 时 coverage 回写 `android_source_coverage`，**`nativeStatus` 非空时优先用它**——既有下游按厂商原生词表（雷电大写 `LOCKED`/`indexed`）判断，迁移不得改变已发布的可见值（`:311-321`、`MobileEvidencePackage.h:158-164`）。

三个重载：`analyzePackage(Reader…)` / 内存 `Package` 直入（"取数+分析合一"路径免落盘）/ 路径直开（`MobileEvidenceAnalysis.h:43-52`）。

## 5. 与其他模块的协作

| 对端 | 方向 | 交互点 |
|---|---|---|
| 三个来源适配器 + `buildPackageFromThunderForensic`（`ThunderForensicArtifactParsers.h:35-36`） | 上游 | 产出 `Package` |
| `AndroidAnalyzer::setExtractionOnly` | 上游 | 取数-only 模式不建 android.db（`AndroidAnalyzerCore.cpp:216-235`） |
| `AndroidAnalysisDatabase` | 下游 | analyzePackage 的全部写入 |
| `mobile_backup_schema::DDL` | 下游 | 鸿蒙/雷电原生结果表兼容 |
| CLI `--mobile-extract` / `--mobile-package` / `--mobile-package-out` | 入口 | 取数/分析两阶段（`CommandLineParser.cpp:133-137`） |
| 任务元数据 `mobile_evidence_package/records/files/adapter` | 下游 | HTTP 任务留痕（`TaskManagerAnalysis.cpp:2112-2119`） |

各来源的专有非记录产物（雷电 `android_container_coverage`、`android_source_provenance` 等）**不进包**，由调用方在分析阶段补写；雷电案件库 provenance 经 `caseProvenanceOut` 交回调用方（spec §5.2、`TaskManagerAnalysis.cpp:2097-2102`）。

## 6. 注意事项与已知问题

- **权威语义文档在 spec**：`docs/specs/mobile-evidence-package.md` 是格式规范（字段表、类别命名空间、验证矩阵）；本文档聚焦代码走读，两者冲突时以代码为准。
- **已接入来源以代码为准**：当前有适配器的是 MIUI/鸿蒙/雷电/美亚四个；iOS/vivo **未接入**包路径（`TaskManagerAnalysis.cpp:2079-2081` 白名单与 `AnalysisOrchestrator.cpp:955-957` 的 extractionOnly 条件都不含它们），spec §5 表格之外的来源属于规划而非实现。
- **v1 已知边界**（spec §7，与代码一致）：MIUI 适配器不逐条展开数据库内部行（登记在 file 表 `status=unsupported`）；加密 `.bak` 记 `locked`。补实现不需要改格式。
- **分析层硬约束**：不要在新适配器里写 android.db，也不要在 `analyzePackage` 加来源判断——这是该设计唯一的红线（spec §6；`MobileEvidenceAnalysis.cpp:257-294` 的分派只看 `kind`）。
- **record 的 `mobileArtifact` 语义**：仅落标准表的记录（设备标识、应用清单）应置 false，避免凭空新增下游可见的工件行（`MobileEvidencePackage.h:92-98`）。

## 7. 如何验证与扩展

- 单元测试：`test_mobile_evidence_package_gtest.cpp`（读写往返/幂等/拒绝非本格式/夹具适配器/仅凭包重建/缺失类别 coverage）、`test_mobile_evidence_adapters_gtest.cpp`（鸿蒙产出与检材移走后重建、nativeStatus/nativeKind 往返保真）——命名见 spec §8；`ctest -R "MobileEvidence|Miui|Harmony"`。
- 端到端（取数→移走检材→分析）是本格式最核心的验收：`--mobile-extract` 出包后把原始检材挪走，`--mobile-package` 仍应重建出完整 android.db。
- 接入新来源五步（spec §6）：实现 `buildPackageFromXxx(source, options, Package&)` → 填 `device`/`acquisition`（`acquisition.adapterName` 是来源稳定标识）→ 每条记录填齐 kind/双 JSON/来源定位/时间三元组 → 每个"应有而未有"写 coverage → `Writer` 落盘。
- 新增 kind 三步：`kind::` 加常量（`MobileEvidencePackage.h:37-61`）→ 适配器产出 → `analyzePackage` 加 `else if` 落表分支。表结构不动。

**最后更新**: 2026-11-10（按代码重写）
