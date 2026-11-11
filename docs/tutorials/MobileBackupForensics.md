# 手机备份取证：多品牌备份接入与统一取数格式

> **目标读者**：需要把小米 / 华为鸿蒙 / vivo·OPPO·一加（雷电快取）/ iOS / 美亚柏科
> 等手机检材接入 TraceLens，并用统一取数格式（`.mep.db`）做"取数—分析分离"的
> 取证分析师。
> **前置条件**：完成 [快速入门](../getting-started/QuickStart.md)；`./build/forensic_analyzer`
> 已构建；服务运行中（`./run.sh`，curl 约定 C++ `http://localhost:8666`、Python
> `http://localhost:8090`）。
> **预计耗时**：40–60 分钟。
> **代码基准**：`src/CommandLineParser.cpp`、`src/analyzers/AndroidAnalyzer/MobileEvidence*`、
> [统一取数格式设计](../specs/mobile-evidence-package.md)。

---

## 0. 场景设定

一起资产挪用案中有四台手机：财务的小米（MIUI 备份）、主管的 iPhone（iTunes 逻辑
备份）、涉案华为 Mate（鸿蒙已解密备份）、外部收款人的 vivo iQOO（PC 助手备份）。
委托方还送检一份美亚柏科 MobileMaster FL-901 的案件导出。你的任务：全部接入、
盘点覆盖度，并把"取数产物"作为交接物移交分析。

---

## 1. `--android-source` 全部合法取值

CLI 解析器（`CommandLineParser.cpp::isValidAndroidSource`）接受 **15 个**取值；
`harmony-backup` / `mobile-evidence` / `meiya` / `ios-backup` / `vivo-backup`
五个取值会**隐含启用** `--android-analyze`，无需再显式携带：

| 取值 | 证据形态 | 说明 |
|---|---|---|
| `tsk` | 磁盘镜像（默认） | 走 TSK 管线产 `_raw.db`，Android 工件随之分析 |
| `dir` | 已解包 `data/` 目录树 | 逻辑提取，跳过磁盘管线 |
| `zip` | 打包的 Image.zip | 需构建时带 libzip |
| `tar` | tar/tar.gz/tgz/tar.xz 归档 | libarchive 按需读成员 |
| `seven-zip` | 7z 归档 | 密码走 stdin/fd（见第 6 节） |
| `android-backup` | Android `.ab` | AOSP adb backup 流 |
| `filesystem-image` | userdata EXT4/F2FS RAW/E01 | 单分区文件系统镜像 |
| `miui-backup` | 小米备份目录（`descript.xml` + `.bak`） | `MiuiBackupExtractor` |
| `harmony-backup` | 华为鸿蒙**已解密**备份目录 | `HarmonyBackupExtractor`；识别到即自动晋升该模式 |
| `thunder-backup` | 雷电手机快取（tar 或工程目录，任意 Android 品牌） | 旧别名 `oppo-backup` 仍接受并归一 |
| `ios-backup` | iTunes/Finder iOS 逻辑备份（`Manifest.plist` + `Manifest.db`） | `IosBackupExtractor`，详见 [iOS 逻辑备份取证](../ios-logical-backup.md) |
| `vivo-backup` | vivo/iQOO PC 助手备份（`.backup` + LevelDB `db/`） | `VivoBackupExtractor`，详见 [vivo 备份取证](../vivo-backup.md) |
| `mobile-evidence` | 统一取数包 `.mep.db` | **只读包分析**（阶段二） |
| `meiya` | 美亚柏科 MobileMaster FL-901 案件导出 | XOR 容器运行时自推导掩码；识别到即自动晋升 |

上传目录时的自动晋升（HTTP 任务同样生效）：备份目录当 `dir` 提交时，识别出
鸿蒙 / 雷电 / 美亚的结构会自动切到对应模式；显式给了错误模式则任务失败
（如 `INVALID_HARMONY_BACKUP`）。

---

## 2. 直连分析（取数+分析合一）

每种手机来源一条命令；产物是任务/目录旁的 `android.db`（逻辑源走
`runAndroidLogicalAnalysis`，没有 `_raw.db`）：

```bash
# 小米 MIUI 备份（加密备份的口令从 stdin 读，见第 6 节）
./build/forensic_analyzer /evidence/miui_backup/ \
  --android-analyze --android-source miui-backup

# 鸿蒙已解密备份（android-analyze 隐含）
./build/forensic_analyzer /evidence/harmony_backup/ --android-source harmony-backup

# vivo / iQOO PC 助手备份
./build/forensic_analyzer /evidence/vivo_backup/ --android-source vivo-backup

# iOS iTunes/Finder 逻辑备份
./build/forensic_analyzer /evidence/ios_backup/ --android-source ios-backup

# 美亚案件导出（可省略 --android-source，识别器命中即走本分支）
./build/forensic_analyzer /evidence/meiya_case/ --android-source meiya

# 雷电快取（tar 或工程目录）
./build/forensic_analyzer /evidence/thunder_project/ --android-analyze --android-source thunder-backup
```

**预期看到**：控制台输出适配器/容器盘点（美亚分支会逐容器打印
`[family] decrypted mask=… schema=…`），产物 `<baseName>_files.db`（CLI 逻辑源
把 android 工件并入 `_files.db`）。覆盖度看 `android_source_coverage` 表——
每类工件一行状态声明（各适配器词表不同：`PARSED` / `staged_for_parser` /
`no_candidate_path` / `extract_failed` / `locked_or_unsupported` / 雷电的
`LOCKED`、`PARTIAL` 等），空表与"没取到"从此可区分。

---

## 3. 统一取数格式：取数—分析分离

统一取数格式（Mobile Evidence Package）是单文件 SQLite，后缀 `.mep.db`，固定
三张主表 + 一张覆盖表（`MobileEvidenceSchema.h`）：

| 表 | 内容 |
|---|---|
| `mobile_evidence_meta` | 设备 / 采集元数据（`device_json`、`acquisition_json`、`adapter_name`…） |
| `mobile_evidence_record` | 规范化记录：`kind` + `raw_json`（完整原始行）+ `payload_json`（规范化投影）+ 时间三元组 + 四级来源定位 |
| `mobile_evidence_file` | 文件清单（未逐行解析的照片/视频/未解密库也必须登记） |
| `mobile_evidence_coverage` | 覆盖度声明（`no_candidate_path` / `locked` / `unsupported` 也是一行声明） |

### 3.1 阶段一：取数

```bash
./build/forensic_analyzer /evidence/miui_backup/ \
  --android-analyze --android-source miui-backup \
  --mobile-extract --mobile-package-out ./case.mep.db
```

**预期看到**：`[MobileEvidence] Extracting to package: ./case.mep.db` 与
`✓ Package: …  records=N files=N coverage=N`，**不产 android.db**（extraction-only，
分析层不被调用）。

`--mobile-extract` 的适用面（`AnalysisOrchestrator.cpp`）：

| 来源 | 取数产物 |
|---|---|
| `miui-backup` / `harmony-backup` / `thunder-backup`（含 `oppo-backup`） | `--mobile-extract` 即只写包 |
| `meiya` | 总是先写包；不带 `--mobile-extract` 时随即在同一命令里完成分析 |
| `ios-backup` / `vivo-backup` | **不在两阶段链路**，直连分析产 android.db |

`--mobile-package-out` 省略时默认输出 `<来源名>_mobile_evidence.mep.db`
（`defaultPackagePath`）。

### 3.2 阶段二：仅凭包分析（原始检材可离场）

```bash
# 两种等价写法
./build/forensic_analyzer --android-analyze \
  --mobile-package ./case.mep.db --db-dir ./out
./build/forensic_analyzer ./case.mep.db --android-source mobile-evidence --db-dir ./out
```

分析端以只读方式打开包（`PRAGMA query_only=1`），**完全不需要原始检材仍在原位**
——包就是证据交接物。产物是 `<包名>_files.db`（`case.mep.db` → `case_files.db`）。

**为什么要分离**：新增一种手机/取证软件格式只需写一个"来源适配器 → 包"的
转换器（填 `raw_json` / `payload_json` / coverage），分析层零改动；缺什么、锁定
什么在覆盖表里可查询，而不是靠猜空表。

---

## 4. HTTP 任务路径与演示数据集

前端「新建任务」对应的 API（`POST http://localhost:8666/api/tasks`）：

```bash
curl -X POST http://localhost:8666/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/abs/path/demo_datasets/04_ios/ios_backup_evidence",
    "scenarios": ["android"],
    "android_source": "ios-backup",
    "case_description": "iOS 逻辑备份（短信/通讯录/备忘录）"
  }'
```

`android_source` 换成 `miui-backup` / `harmony-backup` / `vivo-backup` / `meiya` /
`thunder-backup` 即接入对应品牌；识别命中的来源即使提交 `dir` 也会自动晋升。
查询进度与产物：

```bash
curl http://localhost:8666/api/tasks/<task_id>/progress
curl http://localhost:8666/api/tasks/<task_id>/databases
```

**预期看到**：逻辑源任务直达平台分析（无 image_analysis 长尾）；MIUI/鸿蒙/雷电/
美亚四类任务还会在任务目录产出 `<baseName>_mobile_evidence.mep.db`，任务元数据
登记 `mobile_evidence_package` / `mobile_evidence_records` / `mobile_evidence_files` /
`mobile_evidence_adapter`；vivo 任务在分析前经 Python 桥把 LevelDB 索引转成任务
目录下的 `vivo_index.json`（`scripts/vivo_backup_index_cli.py`，失败报
`VIVO_INDEX_BRIDGE_FAILED`）。包写入失败只记 WARNING 不让任务失败——android.db
仍服务既有页面。

### demo_datasets 演示数据

仓库自带 7 份脱敏演示数据（`demo_datasets/README.md`），其中手机四份：

| 目录 | 来源类型（前端 / `android_source`） | 内容 |
|---|---|---|
| `04_ios/ios_backup_evidence/` | `ios-backup` | Manifest.plist/Manifest.db、短信 iMessage、通讯录、备忘录、日程 |
| `05_android_miui/miui_backup_evidence/` | `miui-backup` | descript.xml、联系人/短信 `.bak` |
| `06_android_harmony/harmony_backup_evidence/` | `harmony-backup` | `.info.json` 清单、`part.*.tarx` 分卷、WAL、日历/通讯工件 |
| `07_android_vivo/vivo_backup_evidence/` | `vivo-backup` | `.backup` 头、LevelDB 索引、相册/合同文档 |

### 一键演示案件

```bash
# 面向第三方验收的演示案件：创建案件 + 7 份数据全部跑完取证+分析并绑定案件
# （需 C++ 8666 / Python 8090 已启动）
python3 scripts/create_demo_case.py
```

脚本流程（`scripts/create_demo_case.py`）：`POST /api/cases` 建演示案件 → 按上表
为 7 份数据各建一个任务（iOS/MIUI/鸿蒙/vivo 用 `scenarios:["android"]` + 对应
`android_source`）→ 轮询 `/api/tasks/<id>` 等完成 → `PUT /api/cases/<id>/tasks`
绑定任务 → 对 Linux 任务播种研判工作台。

`scripts/create_real_case.py` 是同一流程的**真实检材**版本：镜像路径硬编码指向
`/mnt/evidence_sdb1`（移动硬盘）与 `/data2` 数据区，仅在有真实检材的环境可用，
不能直接照跑；替换路径前先确认各来源结构与演示集同构。

---

## 5. 备份口令与密码输入

| 参数 | 用法 | 说明 |
|---|---|---|
| `--backup-password-stdin` | `printf '%s\n' '<口令>' \| … --backup-password-stdin` | MIUI 备份 AES 口令等；交互时无回显 |
| `--backup-password-fd <fd>` | `… --backup-password-fd 3 3< <(printf '%s' '<口令>')` | 从已打开的文件描述符读 |
| `--backup-password <口令>` | （已弃用） | argv 会进进程列表；**7z 与 Android Backup 源带 argv 密码直接报错**（完整文案 `Error: archive passwords must be supplied via stdin or an open file descriptor, not argv`，`AnalysisOrchestrator.cpp:739`）；其余来源仅警告。加密 ADB v5 备份不支持解密 |

任务 API 里对应字段是 `backup_password`（仅运行期使用，任务完成即清除）。
微信 SQLCipher 密码的 CLI 通道是 `--wechat-password`（详见
[Android/微信取证端到端教程](AndroidWechat.md) 第 7 节）。

---

## 6. 已知坑（务必读）

1. **`ios-backup` / `vivo-backup` 不产统一包**：两阶段 `--mobile-extract` 链路目前
   只覆盖 MIUI / 鸿蒙 / 雷电 / 美亚；iOS 与 vivo 走各自适配器直产 `android.db`。
2. **鸿蒙备份必须已解密**：`harmony-backup` 只吃"已解密备份目录"；加密原件需要
   先在手机端/华为工具内完成解密再导入。
3. **vivo 结构化记录不在备份里**：短信/联系人/通话在手机侧只有 `count`，备份包内
   没有数据文件；不要期待 `sms_messages` 出现对应行（详见
   [vivo 备份取证](../vivo-backup.md) "两类数据要区分"）。
4. **iOS 加密备份不解密**：`IsEncrypted=true` 时预检 `ios_backup_encrypted`、任务
   `IOS_BACKUP_ENCRYPTED` 失败；先离线解密再作为普通目录接入。
5. **逻辑源没有 `_raw.db`**：时间线/文件分类页对该任务无数据是正常现象。
6. **`--mobile-extract` 输出路径**：省略 `--mobile-package-out` 时包落在**来源目录旁**
   （`<来源名>_mobile_evidence.mep.db`），只读介质场景必须显式给出可写路径。
7. **美亚容器掩码运行时推导**：掩码不编译进代码，解码以 SQLite `integrity_check`
   验证；打不开的容器如实登记，不会用错掩码硬解。
8. **argv 形式 `--backup-password`**：已弃用且有 7z/AB 的硬拒绝（见第 5 节），
   脚本/CI 一律 stdin / fd。

---

## 7. 验证与延伸阅读

```bash
# 统一取数格式单元测试（读写往返 / 幂等 / 拒绝非本格式库 / 适配器产出）
cd build && ctest -R "MobileEvidence|Miui|Harmony" -V

# iOS / vivo 提取器单测
cd build && ./tests/test_ios_backup_gtest && ./tests/test_vivo_backup_gtest

# Python 预检单测
cd python_service && .venv/bin/python -m pytest tests/unit/test_ios_backup_preflight.py tests/unit/test_vivo_backup_preflight.py -q
```

- [统一取数格式设计（specs/mobile-evidence-package.md）](../specs/mobile-evidence-package.md) — 表结构、双 JSON 设计、接入新来源流程
- [iOS 逻辑备份取证](../ios-logical-backup.md) / [vivo 备份取证](../vivo-backup.md) — 两个专有通道的逐项行为
- [美亚容器解析](../specs/meiya-container-parsing.md) — XOR 容器与 TBL_PR_* 映射
- [Android / 微信取证端到端教程](AndroidWechat.md) — MIUI 通道的 SQL 查证与微信解密
- [Android 输入能力矩阵](../android-input-support-matrix.md) — 各通道能力等级与边界

**最后更新**: 2026-11-10（新建，教程）
