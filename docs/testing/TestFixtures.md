# 测试数据与镜像生成（TestFixtures）

本文盘点 `tests/` 下的全部测试数据（fixtures）、仓库根的共享镜像、`demo_datasets/` 演示数据集、以及各数据生成脚本：每项说明输入/产出/耗时特征、被哪些测试或验收消费。生成物与脚本的对应关系全部以源码为证；`tests/INTEGRATION_TEST_REPORT.md` 的定位（历史记录）在文末说明。配套阅读：[CppTestCatalog.md](CppTestCatalog.md)（谁在跑这些数据）、[AcceptanceHarness.md](AcceptanceHarness.md)（验收如何复制它们；第三方指标验收集的夹具口径）。

`tests/` 与仓库根数据相关的实际布局（2026-11-10 `ls` 实证）：

```
tests/
├── UnitTest/                # 71 个 C++ 单测源文件（见 CppTestCatalog.md）
├── test_data_13/            # 13 文件 LLM 路由集（生成物，入库）
├── samples/
│   ├── elf/                 # libc.so.6 / ld-linux.so.2 / libarmadillo.so.12（入库）
│   └── pe/test_minimal.exe  # 最小 PE（入库）
├── acceptance_metrics/      # 第三方指标验收集（本分支新增；fixtures/ 生成物不入库）
│   └── fixtures/            # manifest.json 入库固化夹具组成；实际夹具本地生成（实测 223MB）
├── raid_validation/         # RAID(MD v1) 解析验证 Python 包（本分支新增，含合成 fixtures.py）
├── EnMicroMsg_dataset.db        # WeChat raw 数据集（生成物，入库，778KB）
├── wechat_dataset_android.db    # WeChat 规范化数据集（生成物，入库，1.38MB）
├── ubuntu_real.img          # 900MiB 稀疏仿真 Ubuntu 镜像（生成物，入库）
├── smart_select_test.cpp    # Smart 选文件手工测试台源文件（根 CMakeLists.txt:687-689 注册、EXCLUDE_FROM_ALL，本分支新增）
├── wechat_graph_animation.gif   # 演示动画（非测试输入）
├── wechat_ui_animation.gif      # 演示动画（非测试输入）
└── create_pe_sample.py      # PE 样本生成脚本（输出路径已失效）
（仓库根）test_image.img     # 100MB 合成 ext4 镜像，验收硬前提（生成物，入库）
（仓库根）demo_datasets/     # 7 个脱敏演示数据集（本分支新增，git 入库，约 105MB）
（scripts/）create_*.sh、generate_wechat_dataset.py、create_test_data.py
```

## fixtures 全景（一张表看懂谁用什么）

| 数据 | 位置 | 形态/规模（实测） | 被谁使用 |
| --- | --- | --- | --- |
| `test_data_13/` | `tests/test_data_13/` | 13 个文件：`file1.txt`…`file11.conf` 共 11 个文本 + `file12.jpg`/`file13.png` 两图 | `tests/llm_files_test.cpp`（13 文件多模型 LLM 联调，非 ctest 目标）；`scripts/create_test_image.sh` 把整目录灌入 `test_image.img` |
| `test_image.img` | 仓库根（非 tests/） | 100MB 裸 ext4（实测 104857600 字节），根目录含 13 个文件 | 验收框架 `scripts/acceptance/live_services.py:248`（task/analyst/restart/matrix 复制为 `fixture.img`）；`web/scripts/e2e-analysis-budget.mjs` 的默认 `E2E_IMAGE_PATH`；`scripts/verify_llm_analysis.py` |
| `samples/elf/` | `tests/samples/elf/` | `libc.so.6`（2.1MB，x86-64 DYN）、`ld-linux.so.2`（209KB，x86 32 位动态加载器）、`libarmadillo.so.12`（72KB） | `DLLAnalyzerIntegrationTests`（ctest，经 `TEST_SAMPLES_DIR` 编译定义，`tests/CMakeLists.txt:1125-1126`） |
| `samples/pe/test_minimal.exe` | `tests/samples/pe/` | 1320 字节最小 PE32+（x86-64，2 节） | 同上 DLL 集成测试；验收 `matrix` 档案复制为 DLL 交接 fixture（`live_services.py:259-262`，缺失时该环节 NOT APPLICABLE） |
| `EnMicroMsg_dataset.db` | `tests/` | 778240 字节；真实 EnMicroMsg.db schema（message/rcontact/chatroom/userinfo 四表，群消息用 `wxid_xxx:\n<body>` 格式） | `python_service/tests/unit/test_wechat_dataset.py`（RAW_DB） |
| `wechat_dataset_android.db` | `tests/` | 1380352 字节；规范化 `_android.db` schema（wechat_* 四表，时间戳毫秒） | 同上（NORM_DB）；WeChat 图分析管线的确定性数据源 |
| `ubuntu_real.img` | `tests/` | 943718400 字节表观（900MiB 稀疏，实际约 200-300MiB）；GPT + FAT32 ESP + ext4 根 | 无自动化测试消费；按 `docs/modules/cpp/core/AnalysisOrchestrator.md` 指引用 CLI 手工跑 `--linux-analyze` 全链路 |
| `wechat_graph_animation.gif` | `tests/` | 1336528 字节动画 | 演示产物（`scripts/animate_wechat_graph.py` 渲染），非任何测试输入 |
| `wechat_ui_animation.gif` | `tests/` | 3579145 字节动画 | 同上（`scripts/animate_wechat_ui.py`） |
| `demo_datasets/`（01-07） | 仓库根 `demo_datasets/` | 3 个镜像/导出包 + 4 个备份目录（约 105MB，git 入库） | 第三方现场演示；`tests/acceptance_metrics/` 四个移动源用例（夹具同源）；`scripts/create_demo_case.py` 一键建案 |
| `acceptance_metrics/fixtures/` | `tests/acceptance_metrics/fixtures/` | 本地生成（实测 223MB）：raw_basic.img、dd_basic.dd、raw_llm.img、timeline_120.img、logs_server.img、windows_evidence.img、linux_evidence.img、阿里云导出包、iOS/小米/鸿蒙/vivo 备份目录、_md_in/_md_out、sample.png/mp4；**仅 manifest.json 入库** | `tests/acceptance_metrics/test_m1~m4`（25 用例）；组成由 `fixtures/manifest.json` 固化 |
| `raid_validation/fixtures.py` | `tests/raid_validation/` | 合成 MD v1 fixture 生成器（已知逻辑字节为 oracle，编码独立于生产解析器定义） | `tests/raid_validation/` 的 7 个 test_*.py（test_raw/test_infer/test_integration/test_readonly_md/test_sample_manifest/test_task_integration/test_task_raw_worker）+ `http_task_e2e.py` |
| 验收内置 fixture | live_services 临时工作区内（不入库） | `fixture/notes.txt`、`fixture/events.txt`、`fixture.img`、`acceptance.xlsx` | 仅 `live_services.py` 运行期使用（`:240-262`；xlsx 由 `create_xlsx_fixture` 用 zipfile 手写 OOXML，`:946-957`） |

**需现场生成、仓库中不存在的镜像**（脚本产出，`ls` 实证缺失）：

- `tests/android_test_gen.img` 与 7 个 Android 样本库（`mmssms_test.db`、`contacts2_test.db`、`calllog_test.db`、`msgstore_test.db`、`cache4_test.db`、`EnMicroMsg_test.db`、`chrome_history_test.db`）——`scripts/create_android_image.sh` 产出；
- `tests/test_multi_partition.img`——`scripts/create_multipartition_image.sh` 产出；
- `tests/android_test.img`——`scripts/run_android_test.sh:6` 作为基线引用，同样不在库中。

## `demo_datasets/` 演示数据集（本分支新增，深表见 AcceptanceHarness.md 第三部分）

7 个数据集对应合同指标的全部来源类型，全部植入统一案情证据链（张伟/李娜/王五，￥386,000 设备采购与异常调拨款项）：

| 数据集 | 内容 | 生成/再生成方式 |
| --- | --- | --- |
| `01_windows/windows_evidence.img` | Windows 镜像：Prefetch/EVTX/LNK/注册表 Hive/财务文档 | `prepare_fixtures.py`（见下文脚本节） |
| `02_linux/linux_evidence.img` | Linux RAW：涉案文件 + 日志 + 重复对 + 低价值文件（轻量化过滤演示） | 同上 |
| `03_aliyun_oss/file_m-demo_aliyun_system.raw.tar.gz` | 阿里云 OSS/ECS 导出包：Alibaba Cloud Linux + nginx/oss 日志 | 同上 |
| `04_ios/ios_backup_evidence/` | iTunes/Finder 逻辑备份：Manifest.plist/db + 短信/通讯录/备忘录/日程哈希分片 | 同上 |
| `05_android_miui/miui_backup_evidence/` | 小米备份：descript.xml + Contacts/Mms `.bak` | 同上（`--only android` 需宿主 `sqlite3` CLI） |
| `06_android_harmony/harmony_backup_evidence/` | 鸿蒙备份：`.info.json` + `files/BASIC/<app>` 的 manage.jsonx/part.0.tarx/wal_blobx | 同上 |
| `07_android_vivo/vivo_backup_evidence/` | vivo/雷电快取备份：`.backup` 头 + index.json + 相册/文档 | 同上 |

要点：

- `prepare_fixtures.py` 的 `build_all_demo_datasets()`（`prepare_fixtures.py:725-726`）默认把演示数据集写回仓库根 `demo_datasets/`；`--only` 选择子含 `demo_datasets` 项（`:837`、`:899-900`），可单独重建。
- `tests/acceptance_metrics/fixtures/` 下的 iOS/小米/鸿蒙/vivo 夹具与 04-07 数据集**同源同内容**（`fixtures/manifest.json` 逐项注明），消费方分别是黑盒指标用例与第三方现场演示。
- 消费链：`tests/acceptance_metrics/test_m1_multisource.py` 的 `test_m1_1d_ios_source` / `_android_miui_source` / `_android_harmony_source` / `_android_vivo_source` 四个用例直接吃对应备份目录；`scripts/create_demo_case.py` 对 7 个数据集一键建案。

## `test_data_13/` 明细（13 个文件逐一）

| 文件 | 内容特征 | LLM 路由意义 |
| --- | --- | --- |
| `file1.txt` | `Simple text file for analysis.` | 纯文本基线 |
| `file2.md` | `# Markdown Header` + 正文 | Markdown 结构 |
| `file3.log` | `2026-01-11 10:00:00 [INFO] System started successfully.` | 日志格式 |
| `file4.cpp` | `const int x = 10; int main(){...}` | C++ 源码 |
| `file5.h` | include guard 头文件 | C 头文件 |
| `file6.html` | 最小 HTML 文档 | 标记语言 |
| `file7.json` | `{"key":"value","id":123}` | JSON |
| `file8.xml` | `<?xml...?><root><item>` | XML |
| `file9.csv` | `id,name,role` 表头 + 2 行 | CSV |
| `file10.sh` | `#!/bin/bash` 脚本 | Shell |
| `file11.conf` | `[General]` INI 段 | 配置文件 |
| `file12.jpg` | 复制自 `build/sample.jpg` | **视觉模型路由** |
| `file13.png` | 复制自 `libs/cpp-dotenv/cpp-dotenv.png` | **视觉模型路由** |

这 13 个文件是 `llm_files_test` 验证"文本走文本模型、图片走视觉模型"最小覆盖集；同时被整体灌入 `test_image.img`，成为验收 Journey A 里 Files/Timeline 路由能读到的确定内容。

## `samples/` 明细（DLL 集成测试的四个真实样本）

| 样本 | 大小/位数 | 集成测试覆盖点（据 `integration_dll_analyzer.cpp` 与报告） |
| --- | --- | --- |
| `libc.so.6` | 2.1MB，x86-64，DYN | ELF 解析、动态段、符号依赖 |
| `ld-linux.so.2` | 209KB，x86（32 位） | 32 位 ELF 路径、动态加载器识别 |
| `libarmadillo.so.12` | 72KB，x86-64，DYN | DYN 类型检测 |
| `test_minimal.exe` | 1320 字节，PE32+，2 节 | PE 头/节表/导入导出最小闭环；另被验收 matrix 的两个 DLL 端点复用 |

## WeChat 双数据集的 schema 对照

| 库 | 表 | 关键列/约定 |
| --- | --- | --- |
| `EnMicroMsg_dataset.db`（raw） | `message` | talker、content、createTime（**秒**）、type、isSend |
| | `rcontact` | username、nickname、conRemark、type、chatroomFlag |
| | `chatroom` | chatroomname、roomowner、memberlist、membercount、addtime |
| | `userinfo` | id/value（id=2 → username，id=4 → nickname） |
| `wechat_dataset_android.db`（norm） | `wechat_*` 四表 | 复刻 `parseWeChatEnhanced()` 输出；时间戳转换为**毫秒**；供 Python WeChatGraphService 读取 |

守护不变量（由 `test_wechat_dataset.py` 校验，fixture 缺失时自动再生成）：两库行数关系、社交圈可分离性（Louvain）、枢纽联系人的度数优势、群消息时间聚集等——即数据集"长得像真实取证数据"本身就是被测对象。

## 验收工作区内建 fixture（live_services 每次运行现场生成，不入库）

| 文件 | 内容 | 旅程角色 |
| --- | --- | --- |
| `fixture/notes.txt` | `TraceLens deterministic acceptance fixture.` | fake LLM 默认证据键 `file:fixture/notes.txt`；matrix 的 MarkItDown 转换输入 |
| `fixture/events.txt` | `2026-08-19T00:00:00Z fixture event` | 事件类证据样本 |
| `fixture.img` | 复制自仓库根 `test_image.img` | Journey A 的分析输入（复制而非引用，保证工作区自包含） |
| `fixture/acceptance.xlsx` | `create_xlsx_fixture` 用 zipfile 手写的最小 OOXML（Content_Types/rels/workbook/sheet1，A1=TraceLens acceptance） | matrix 的 Office 解析输入；不引入文档处理依赖 |
| `fixture/test_minimal.exe` | 复制自 `tests/samples/pe/` | matrix 的 DLL 两端点输入 |

## `acceptance_metrics/fixtures/manifest.json` 夹具清单（入库固化）

| 夹具 | manifest 描述 |
| --- | --- |
| `raw_basic.img` | Linux 案情夹具：角色聊天/合同/台账/勒索标记/重复文件对 + 低价值文件集 |
| `dd_basic.dd` | raw_basic.img 的逐字节副本（DD 口径） |
| `raw_llm.img` | LLM 专用证据镜像（小文本 + 同分钟转账凭证图，供 M3-1/M4） |
| `timeline_120.img` | 120 个逐小时时间戳文件（M3-2 ≥100 事件） |
| `logs_server.img` | /var/log 与 /etc/passwd 的 Linux 服务器夹具 |
| `_md_in/_text_sample.html` + `_md_out/` | 文本提取输入（MarkItDown 转换样例）与期望产物 |
| `sample.png` | 视觉分析输入（含编号 `ACCT-2026-777` 的样例图，PIL 绘制） |
| `sample.mp4` | 视频内容分析输入（ffmpeg 2 秒测试片） |
| `ios_backup_evidence` / `miui_backup_evidence` / `harmony_backup_evidence` / `vivo_backup_evidence` | 四类移动设备备份夹具（与 demo_datasets 04-07 同源） |
| `file_m-demo_aliyun_system.raw.tar.gz` | 阿里云 OSS/ECS 导出演示包 |
| `windows_evidence.img` / `linux_evidence.img` | Windows / Linux 证据夹具 |

## 数据→消费者矩阵（自动化覆盖视角）

| 数据 | ctest | pytest | 验收 harness | 手工/联调 |
| --- | --- | --- | --- | --- |
| `test_data_13/` | —（仅被灌入镜像） | — | 间接（test_image.img 内容） | `llm_files_test` 直接读 |
| `test_image.img` | — | — | live_services task/analyst/restart/matrix | `verify_llm_analysis.py`、`e2e-analysis-budget` 默认镜像 |
| `samples/elf/`、`samples/pe/` | `DLLAnalyzerIntegrationTests` | — | matrix（仅 PE） | — |
| `EnMicroMsg_dataset.db`、`wechat_dataset_android.db` | — | `tests/unit/test_wechat_dataset.py` | — | 可选数据源 |
| `ubuntu_real.img` | — | — | — | CLI 手工全链路 |
| `test_multi_partition.img` | — | — | — | 多分区手工验证（`scripts/FINDINGS_MULTI_PARTITION.md`） |
| `android_test_gen.img` 族 | — | — | — | `scripts/run_android_test.sh`（其脚本路径已失效，见问题 1） |
| `demo_datasets/`（7 个） | `AndroidArchive*`/`Harmony*`/`ThunderForensic*` E2E 用各自合成 fixture（**不**直接吃 demo_datasets） | `acceptance_metrics`（黑盒，fixtures 同源） | 第三方现场演示 | `create_demo_case.py`、Web 人工导入 |
| `acceptance_metrics/fixtures/` | — | `tests/acceptance_metrics/test_m1~m4`（25 用例） | 第三方指标验收 | `prepare_fixtures.py` 再生 |
| `raid_validation/fixtures.py` | — | `tests/raid_validation/test_*`（手工） | — | `http_task_e2e.py` |

## 生成脚本逐一

### `scripts/create_test_data.py`（47 行）

| 维度 | 内容 |
| --- | --- |
| 输入 | 无外部输入；图片源取仓库内 `build/sample.jpg` 与 `libs/cpp-dotenv/cpp-dotenv.png`（保证视觉模型拿到有效图片数据） |
| 产出 | `tests/test_data_13/`：11 个文本文件（内容为脚本内字符串字面量：txt/md/log/cpp/h/html/json/xml/csv/sh/conf）+ 复制的 file12.jpg/file13.png |
| 耗时/依赖 | 秒级；纯 Python stdlib |
| 消费者 | `create_test_image.sh` 第一步；`llm_files_test` |
| 特征 | 幂等（`os.makedirs(exist_ok=True)` 覆盖写）；文件名 file1-file13 与扩展名稳定，是 LLM 路由（文本 vs 视觉）的最小覆盖集 |

### `scripts/create_test_image.sh`（38 行）

| 维度 | 内容 |
| --- | --- |
| 输入 | `tests/test_data_13/`（先调 `create_test_data.py` 重新生成） |
| 产出 | 仓库根 `test_image.img`：`dd` 100MB → `mkfs.ext4 -F` → 生成 `debugfs_cmds.txt`（`cd /` + 每个 `write <file> <name>` + `ls -l`）→ `/usr/sbin/debugfs -w -f` 写入 → 清理命令文件 |
| 耗时/依赖 | 秒到几十秒；需 `mkfs.ext4`/`debugfs`（e2fsprogs），**无需 root**（debugfs 直接写裸镜像） |
| 消费者 | 验收框架四个非 smoke 档案的硬前提——`live_services.py:252-255` 的报错文案直接指名本脚本；`verify_llm_analysis.py` |
| 特征 | 裸 ext4 无分区表；与 `ubuntu_real.img`（GPT+双分区+真实内容）形成"合成 vs 仿真"两档 |

### `scripts/create_android_image.sh`（396 行）

| 维度 | 内容 |
| --- | --- |
| 输入 | 无外部数据；`sqlite3` CLI 现场建 7 个样本库（SMS/联系人/通话记录/WhatsApp msgstore/Telegram cache4/WeChat EnMicroMsg_test/chrome_history）+ `WifiConfigStore.xml`/`packages.xml`/`usage_stats_1001` + `tests/test_assets/` 与 `tests/system_assets/` 下的 sample.jpg/pdf/apk/json/log/large.bin/runme.sh |
| 产出 | `tests/android_test_gen.img`（ext4）：优先 `debugfs -w` heredoc 写入；无 debugfs 且 root 时走 `losetup`+mount 回退；两者皆无则打印手动命令并跳过写入 |
| 耗时/依赖 | 秒-分钟；`sqlite3`、`mkfs.ext4` 为强检；root 回退需 sudo |
| 消费者 | `scripts/run_android_test.sh`（生成后跑 `--android-analyze` 并写 `tests/AndroidTestResults.md`）；`tests/test_scene_integration.sh` 试图引用但路径已失效（问题 1） |
| 特征 | 覆盖 Android 典型取证路径：`/data/data/<pkg>/db`、`/data/misc/wifi`、`/data/system/packages.xml`、usagestats、`/sdcard/DCIM|Download`、`/data/local/tmp/runme.sh`（可执行位） |

### `scripts/create_multipartition_image.sh`（106 行，中文注释）

| 维度 | 内容 |
| --- | --- |
| 输入 | 无；固定布局 |
| 产出 | `tests/test_multi_partition.img`（默认，位置参数可覆盖）：200MB 空镜像 → `sgdisk` 建 GPT + 2 分区（1: ext4 `LinuxRoot` ~90MB；2: NTFS `WindowsData` ~90MB）→ losetup 逐分区 mkfs 并写入带区分度的文件 → 卸载 |
| 耗时/依赖 | 分钟内；**必须 sudo**（losetup/mount），依赖 sgdisk、mkfs.ext4、mkntfs |
| 消费者 | 多分区解析手工验证（结论记录在 `scripts/FINDINGS_MULTI_PARTITION.md`）；无自动测试挂载 |
| 用途（脚本头注释） | 验证 ImageAnalyzer 遍历所有分区、FileExtractor 按分区路由抽取 |

### `scripts/create_ubuntu_real_image.sh`（180 行，中文注释）

| 维度 | 内容 |
| --- | --- |
| 输入 | 本机真实系统内容：`/etc` 全量、真实系统日志（auth/syslog/kern/dpkg/wtmp/btmp/journal）、真实 shell 历史、EFI 引导文件、真实 PDF/图片/SQLite、常用二进制 |
| 产出 | `tests/ubuntu_real.img`（默认）：GPT + 128MiB FAT32 ESP + ~770MiB ext4 根（模拟真实 UEFI Ubuntu 安装）；**稀疏文件**：表观 900MiB、实际 200-300MiB |
| 取证难点覆盖 | 中文/空格文件名、`.gz` 轮转日志、utmp/wtmp 二进制、已删除文件（雕刻）、符号链接（`/bin→usr/bin`、`/etc/mtab`）、稀疏镜像本身 |
| 安全边界 | **不包含**用户 SSH 私钥（`~/.ssh/id_*`）、token 库等高敏感凭据（头注释明确列出） |
| 耗时/依赖 | 分钟级；**必须 sudo**（EUID 检查），losetup/mount；cleanup trap 保证任何退出路径都卸载回环 |
| 消费者 | 手工 CLI 全链路（AnalysisOrchestrator 文档指引）；无自动测试 |

### `scripts/generate_wechat_dataset.py`（784 行）

| 维度 | 内容 |
| --- | --- |
| 输入 | 可选 `--seed N`（确定性随机）、`--scale F`（规模倍率）；默认规模 ~50 主体、~12k 会话 |
| 产出 | `tests/EnMicroMsg_dataset.db`（raw：message/rcontact/chatroom/userinfo，复刻 C++ `AndroidDataParsers.cpp` 所读四表）与 `tests/wechat_dataset_android.db`（规范化 wechat_* 四表，复刻 `parseWeChatEnhanced()` 变换，时间戳毫秒） |
| 社交结构设计 | 1 拥有者 + 49 真实联系人（+weixin/filehelper 系统行）；3 社交圈（family/colleague/friend）→ 可分离 Louvain 社区；每圈 1-2 个枢纽（高 PageRank/betweenness）；10 个群（圈聚簇 + 2 个跨圈桥群）；~7000 私聊（对 ~25 活跃联系人幂律分布）+ ~5000 群聊（时间聚集产生共活动边）；msg_type ∈ {1,3,34,43,47,49} 文本为主 |
| 耗时/依赖 | 秒级；仅 stdlib + sqlite3（与 `create_test_data.py` 同约定）；幂等（先 `rm -f` 再建） |
| 消费者 | `python_service/tests/unit/test_wechat_dataset.py`（fixture 缺失时**自动调用本脚本再生成**）；WeChat 图/报告测试间接依赖该形态 |

### `tests/acceptance_metrics/prepare_fixtures.py`（915 行，本分支新增）

| 维度 | 内容 |
| --- | --- |
| 输入 | 无外部数据；`--only <名…>` 选择子（raw/dd/timeline/logs/markdown/…/android/demo_datasets） |
| 产出 | `tests/acceptance_metrics/fixtures/`（或 `$TRACELENS_ACCEPT_FIXTURES`）全部夹具 + `manifest.json`（逐项中文描述，作为第三方复现的输入固化）；`demo_datasets` 项经 `build_all_demo_datasets()`（`:725-726`）写仓库根 `demo_datasets/` 七件套 |
| 夹具构成 | raw_basic.img/dd_basic.dd（Linux 案情 + 重复对 + 低价值集）、raw_llm.img（纯文本 LLM 镜像）、timeline_120.img（120 逐小时文件）、logs_server.img、windows/linux_evidence.img、阿里云导出包、iOS/小米/鸿蒙/vivo 四类备份目录、_md_in/_md_out、sample.png（PIL 绘制编号文字）、sample.mp4（ffmpeg 生成） |
| 耗时/依赖 | 秒-分钟；**仅 mkfs.ext4 + debugfs，无需 root**；Android 夹具分支需宿主 `sqlite3` CLI（README 已知缺口 5：缺失时用例跳过并现场补夹具） |
| 消费者 | `tests/acceptance_metrics/test_m1~m4`（25 用例）；`demo_datasets/`（现场演示）；`scripts/create_demo_case.py`（间接，读数据集文件） |
| 特征 | 夹具组成由 manifest.json 固化保证第三方复现一致；幂等覆盖写 |

### `tests/raid_validation/fixtures.py`（本分支新增，位于 tests/ 而非 scripts/）

| 维度 | 内容 |
| --- | --- |
| 输入 | 无 |
| 产出 | 合成 MD（raid）v1 fixture：已知逻辑字节为 oracle，编码**独立定义**自 Linux MD 格式/布局（不从生产解析器读回），避免循环验证 |
| 消费者 | `tests/raid_validation/` 的 7 个 test_*.py（test_raw/test_infer/test_integration/test_readonly_md/test_sample_manifest/test_task_integration/test_task_raw_worker）与 `http_task_e2e.py`（live 隔离 RAID→Task 回归） |
| 现状 | 该包无 pytest 配置收录，只能手工指路径运行（见 CppTestCatalog.md 问题 6） |

### `tests/create_pe_sample.py`（134 行，位于 tests/ 而非 scripts/）

| 维度 | 内容 |
| --- | --- |
| 输入 | 无；纯 Python 手工拼 PE 头/节表（DOS header、NT header、2 个 section） |
| 产出 | **硬编码绝对路径** `/home/ymj68520/projects/Forensics/ForensicsProject/tests/samples/pe/test_minimal.exe`（`create_pe_sample.py:134`，2026-11-10 复核仍在）——指向旧工程名 ForensicsProject，而非本仓库 TraceLens |
| 耗时/依赖 | 秒级；stdlib |
| 消费者 | 现存 `tests/samples/pe/test_minimal.exe` 即其历史产物（DLL 集成测试与 matrix 验收在用）；脚本当前运行不会更新仓库内样本（再生成链已断，见问题 2） |

## 快速重建清单

```bash
python3 scripts/create_test_data.py                    # 秒级；tests/test_data_13/
bash   scripts/create_test_image.sh                    # 秒级；仓库根 test_image.img（验收前提）
python3 scripts/generate_wechat_dataset.py             # 秒级；两枚 WeChat 数据集 DB
python3 scripts/generate_wechat_dataset.py --seed 42 --scale 2.0   # 更大规模确定性数据
python3 tests/acceptance_metrics/prepare_fixtures.py   # 秒-分钟；指标验收夹具 + demo_datasets 七件套
python3 tests/acceptance_metrics/prepare_fixtures.py --only android demo_datasets   # 只重建移动夹具与演示集
sudo bash scripts/create_multipartition_image.sh       # 分钟级；tests/test_multi_partition.img
sudo bash scripts/create_ubuntu_real_image.sh          # 分钟级；tests/ubuntu_real.img（稀疏）
bash   scripts/create_android_image.sh                 # 需 sqlite3；tests/android_test_gen.img 等
# tests/create_pe_sample.py 需先修 :134 的硬编码路径再运行
```

重建顺序约束：`test_image.img` 依赖 `test_data_13`（脚本内部已自动先跑 `create_test_data.py`）；`prepare_fixtures.py` 各夹具互相独立、可 `--only` 单独重建；其余互相独立。

## 何时该重建哪个（维护场景对照）

| 场景 | 动作 |
| --- | --- |
| live_services 验收报 `ENVIRONMENT BLOCKED: reusable test_image.img is missing` | `bash scripts/create_test_image.sh`（先确认 e2fsprogs 存在） |
| 第三方指标验收缺夹具 / `test_m1_multisource` 报夹具缺失 | `python3 tests/acceptance_metrics/prepare_fixtures.py`（Android 分支确认宿主有 `sqlite3`） |
| 现场演示数据集被改动/污染 | `python3 tests/acceptance_metrics/prepare_fixtures.py --only demo_datasets`（写回 `demo_datasets/`） |
| WeChat 单测首跑变慢/失败 | `python3 scripts/generate_wechat_dataset.py`（或让 fixture 自动重建），再跑 `test_wechat_dataset.py` |
| DLL 集成测试样本损坏 | `samples/` 属仓库存量：ELF 无再生成脚本（从系统复制同名库即可），PE 需先修复 `create_pe_sample.py:134` 再运行 |
| 需要贴近真实的 Linux 全链手工验证 | `sudo bash scripts/create_ubuntu_real_image.sh`，按 AnalysisOrchestrator 文档跑 CLI |
| 验证多分区路由 | `sudo bash scripts/create_multipartition_image.sh`，手工对照 `scripts/FINDINGS_MULTI_PARTITION.md` |
| Android 场景集成 | 先修 `test_scene_integration.sh` 的脚本/镜像路径（问题 1），再 `bash scripts/create_android_image.sh` |

## 生成脚本横评（选型速查）

| 脚本 | 需要 sudo | 需要外部工具 | 产出位置 | 典型耗时 | 自动化消费者 |
| --- | --- | --- | --- | --- | --- |
| `create_test_data.py` | 否 | 否（图片源在仓库内） | `tests/test_data_13/` | 秒 | 经 test_image.img 间接 |
| `create_test_image.sh` | 否 | e2fsprogs（mkfs.ext4/debugfs） | 仓库根 `test_image.img` | 秒-几十秒 | live_services 4 档案 |
| `create_android_image.sh` | 回退路径需要 | sqlite3（强检）、mkfs.ext4；debugfs 或 root 二选一 | `tests/android_test_gen.img` + 7 库 | 秒-分钟 | 仅 `run_android_test.sh`（路径已断） |
| `create_multipartition_image.sh` | **是** | sgdisk、mkfs.ext4、mkntfs | `tests/test_multi_partition.img` | 分钟内 | 无 |
| `create_ubuntu_real_image.sh` | **是** | losetup/mount（读真实 /etc 与日志） | `tests/ubuntu_real.img`（稀疏） | 分钟级 | 无 |
| `generate_wechat_dataset.py` | 否 | 否（stdlib+sqlite3） | `tests/` 两枚 DB | 秒 | pytest `test_wechat_dataset.py` |
| `tests/acceptance_metrics/prepare_fixtures.py`（新增） | 否 | mkfs.ext4 + debugfs；Android 分支需 sqlite3 | `tests/acceptance_metrics/fixtures/` + `demo_datasets/` | 秒-分钟 | `test_m1~m4` 25 用例、现场演示 |
| `tests/raid_validation/fixtures.py`（新增） | 否 | 否（纯合成） | 内存/临时目录 | 秒 | `tests/raid_validation/test_*`（手工） |
| `tests/create_pe_sample.py` | 否 | 否 | **旧工程绝对路径**（已断） | 秒 | 无（样本为存量） |

幂等性：`generate_wechat_dataset.py` 明确 `rm -f` 重建；`create_test_data.py` 覆盖写；镜像脚本直接覆盖目标文件；`prepare_fixtures.py` 各夹具独立覆盖写且以 manifest.json 记录组成。全部脚本均不校验已有产物的哈希，重复运行即全量重写。

## 动画 GIF 的说明

`tests/wechat_graph_animation.gif`（1.3MB）与 `tests/wechat_ui_animation.gif`（3.5MB）分别由 `scripts/animate_wechat_graph.py`（487 行）与 `scripts/animate_wechat_ui.py`（631 行）生成。它们是**演示/文档产物**：不被任何测试读取，却与真实 fixtures 一起存放在 `tests/` 下，容易被误认作测试输入（见问题 6）。

## `tests/INTEGRATION_TEST_REPORT.md` 的定位

这是一份**历史执行记录**（非活文档、非规范）：

- 日期 2026-05-14，对象 `test_dll_analyzer_integration`，结论 ALL TESTS PASSED（23/23）。
- 记录了当时样本清单与形态：ELF——`libc.so.6` 2.1MB x86-64 DYN、`ld-linux.so.2` 209KB x86 32 位、`libarmadillo.so.12` 72KB；PE——`test_minimal.exe` 1.3KB PE32+ 2 节。
- 23 项分七组：ELF 7/7、PE 5/5、Hash 3/3、Signature 2/2、Anomaly 2/2、Dependency 2/2、Cross-format 2/2：

| 组 | 项（报告原文标题） | 说明 |
| --- | --- | --- |
| ELF（7） | Parse libc.so.6 / Parse ld-linux.so.2 / Parse libarmadillo.so.12 / ELFParser validation / Header extraction / Program headers exist / Section headers exist | 三真实样本 + 校验/头/程序头/节头 |
| PE（5） | Parse minimal.exe / PEHeaderParser validation / Header extraction / Section parsing / Import/Export parsing | 最小 PE 闭环（.text/.data 两节，空导入导出不崩溃） |
| Hash（3） | Calculate MD5 / Calculate SHA256 / Consistency | 32/64 位十六进制、跨调用一致 |
| Signature（2） | Verify unsigned PE / Has signature check | 无签名 PE 正确识别 |
| Anomaly（2） | High entropy check / Threat score | 熵检测不崩溃、威胁分 0-100 |
| Dependency（2） | Parse imports / Calculate ImpHash | 最小 PE 上不崩溃（返回空） |
| Cross-format（2） | ELF not PE / PE not ELF | 跨格式正确互斥 |

- 报告还记录了当时的构建参数（Release、GCC C++20、CMake 3.16+）与旧工程路径下的执行命令（`/home/ymj68520/projects/Forensics/ForensicsProject/build`——又一处旧工程名残留）。
- 使用方式：对照样本形态与当年断言明细的参考；**当前回归以 `ctest -R DLLAnalyzerIntegrationTests` 的实际输出为准**，与报告不一致时以测试源码（`tests/integration_dll_analyzer.cpp`）为准。

## 已发现的测试层面问题

1. **两处脚本路径漂移（互相矛盾，2026-11-10 复核仍在）**：`scripts/run_android_test.sh:27` 以 `tests/create_android_image.sh` 调用、`tests/test_scene_integration.sh:34` 检查 `$SCRIPT_DIR/create_android_image.sh`，但脚本实际位于 `scripts/create_android_image.sh`——两处引用都落空；且 `test_scene_integration.sh:32` 期望镜像在 `build/test_android.img`，而生成脚本产出 `tests/android_test_gen.img`，路径也对不上，最终走"SKIP: No test image creator found / SKIP: No test image available"双静默跳过。
2. **`create_pe_sample.py:134` 硬编码旧工程绝对路径**（`Forensics/ForensicsProject`），在本仓库运行会把样本写到仓库外；PE 样本的"再生成链"已断，只能靠仓库存量文件。
3. **`llm_files_test` 的 fixture 无人守护**：`test_data_13` 只被该非 ctest 目标使用，目录被清理不会有任何测试失败。
4. **`ubuntu_real.img` 与 `test_multi_partition.img` 无自动消费者**：两个最"真实"的镜像只支撑手工验证；live_services 验收框架仍只用合成 `test_image.img`。
5. **`test_wechat_dataset.py` 隐式写仓库文件**：单测 fixture 在 DB 缺失时自动执行 `generate_wechat_dataset.py` 再生成——对首跑友好，但意味着"单测"可能改动工作区外的仓库文件（也被 `slow` 标记排除出 fast 档案，见 PythonTestCatalog.md）。
6. **大文件与演示产物入库**：`ubuntu_real.img`（900MiB 表观稀疏）、`test_image.img`（100MB）、`demo_datasets/`（约 105MB）、两个 GIF（合计 ~4.8MB）直接提交在仓库；GIF 纯为演示，占库存却无测试价值，且与 fixtures 混放易误导。
7. **基线镜像缺失**：`run_android_test.sh` 的对照基线 `tests/android_test.img` 不在库中，该脚本的"新旧镜像对比"语义当前不可复现。
8. **案情夹具双份存放且无互检**（新增）：`demo_datasets/`（git 入库）与 `tests/acceptance_metrics/fixtures/`（gitignore，本地生成）同源，合计磁盘 300MB+；manifest.json 只描述组成不做哈希锁定，两份漂移不可感知。
9. **`smart_select_test.cpp` 不进默认构建**（新增）：根 `CMakeLists.txt:687-689` 已以 `if(EXISTS)` 注册为 `smart_select_test`（EXCLUDE_FROM_ALL），不进默认构建、ctest 不收录；build 树中若已构建（当前 `build/smart_select_test` 已存在）可直接运行其手工用法（`smart_select_test <files_db> [budget]`）。
10. **`prepare_fixtures.py` 的 Android 分支隐式依赖宿主 `sqlite3` CLI**（新增）：`--only android` 在无该 CLI 的机器上不报错而是留下不完整夹具，README 以"现场补夹具"一句话带过（其已知缺口 5）。

## 与其它测试文档的关系

- [CppTestCatalog.md](CppTestCatalog.md)：消费这些 fixtures 的 C++ 目标逐一说明（含 `DLLAnalyzerIntegrationTests` 对 `samples/` 的依赖方式）。
- [PythonTestCatalog.md](PythonTestCatalog.md)：`test_wechat_dataset.py` 的标记（`slow`）与四档案的取舍关系。
- [AcceptanceHarness.md](AcceptanceHarness.md)：`test_image.img`/`test_minimal.exe` 被复制进隔离工作区的精确路径与降级行为；`tests/acceptance_metrics/` 指标验收集的完整口径；`demo_datasets/` 与建案脚本的深表。
- [browser-e2e.md](browser-e2e.md)：`e2e-analysis-budget.mjs` 以 `test_image.img` 为默认任务镜像。
- [test-profiles.md](test-profiles.md)：Python 四档案的历史基线数据（以代码为准的原则同本文）。
- [live-integration.md](live-integration.md)：验收框架的 Phase F 历史记录。

**最后更新**: 2026-11-10（feature/model-routing 分支改版：并入 demo_datasets 七件套、prepare_fixtures.py 与 raid_validation fixtures；全部存量条目复核未变）
