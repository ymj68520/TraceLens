# Android 文件系统镜像输入（第四阶段）

本链路只针对可验证的 Android `userdata` 文件系统镜像。它不改变第三方 HTML 报告 `records.db` 的派生数据边界，也不重写 Android 工件解析器。

## 只读调用链

```text
Evidence Preflight（完整来源哈希、分区/文件系统/Android 路径标记）
  → HTTP Task 准入（job、路径、大小、哈希、分区偏移绑定）
  → FilesystemEvidenceFileExtractor
      → TskFilesystemEvidenceSource（EXT4，offset 0 或 GPT/MBR 分区）
      → F2fsFilesystemEvidenceSource（F2FS，qnxprobe 只读块视图）
  → IFileExtractor::extractFileByPath
  → 现有 AndroidAnalyzer → android.db
  → android_coverage_manifest.json
```

`AndroidPathMapper::buildUserdata` 负责把 userdata 根下的 `data/`、`system/`、`misc/`、`user/` 等转换为 AndroidAnalyzer 使用的 `data/data/`、`data/system/`、`data/misc/`、`data/user/` 路径。无法证明 Android 路径标记的普通 EXT4/F2FS 不会被当作 userdata。无分区表时探测 offset 0；有 GPT/MBR 时探测各已分配分区。EXT4 由现有 TSK 按 inode 只读遍历和按需提取。F2FS 由固定上游 qnxprobe 版本只读遍历；C++ 通过固定 argv、无 shell、有超时的严格 JSON/NDJSON 桥接，非零退出码一律拒绝。E01 由 TSK 打开容器，F2FS 读取由 qnxprobe 附带的 ewfprobe 暴露 EWF 逻辑块视图，不默认导出整个 userdata。

## 安装与现场操作

在项目根目录执行 `bash scripts/install_android_image_reader.sh`。脚本下载 qnxprobe 1.34 固定提交 `fc74ca829c2773879243b326f2262c29f462df3a` 到忽略的 `.deps/qnxprobe/`，验证 qnxprobe 与 ewfprobe 的 SHA-256。运行时桥接再次验证文件哈希；未安装或版本不符会返回 `QNXPROBE_PIN_MISMATCH`，不会降级为“读取成功”。上游源码及许可见 [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)。需要 `f2fs-tools` 的仅是合成测试镜像生成，**读取证据不调用 mkfs、sload、fsck 或 mount**。

1. 将只读镜像文件放在 Evidence Inbox（默认项目上级目录，或由 `TRACELENS_EVIDENCE_INBOX` 指定）。预检支持无分区表的 `userdata.img/.dd/.raw`，以及含 userdata 的 RAW/E01。对不带后缀的单分区镜像也检查 EXT4/F2FS magic；仅 magic 不构成准入。
2. 在 Evidence Preflight 选择来源并运行**完整哈希**。查看分区清单、Android 路径标记、文件系统、加密状态与警告。未确认可读 userdata 时不创建普通分析 Task。
3. 预检通过后点击“按此来源新建 Android Task”。C++ 再核对预检 job、来源路径/大小/SHA-256、Adapter 和偏移；分析前后重新验证哈希。Task 结果存独立 `android.db`，非 Android 来源仍沿原流程。
4. 查阅 Android 页面与该 Task 的最终报告查看页中的来源覆盖卡片，下载它引用的 `android_coverage_manifest.json`（受 Task 约束的 `/api/evidence-intake/tasks/{task_id}/android-coverage-manifest`）；Task 完成不等于全部用户数据可读。工件来源可在 `android_filesystem_provenance` 追到镜像哈希、分区偏移、inode、文件系统原路径、规范化路径、提取文件哈希与读取器版本。`android_filesystem_metrics` 记录遍历时间、索引文件数、提取数、读取字节和分析时间。离线 HTML 报告导出本阶段尚未内嵌该 coverage 清单，导出时应连同 JSON 一起交付。

## 加密与锁定语义

`AndroidEncryptionInspector` 仅根据可证明的文件系统 feature flag、实际 inode 加密标记及可读取的 fstab 配置报告 `UNENCRYPTED`、`FBE_DETECTED`、`METADATA_ENCRYPTION_DETECTED`、`PARTIALLY_ACCESSIBLE`、`LOCKED` 或 `UNKNOWN`，并保留 evidence 与 confidence_basis；不猜密码、不解密。文件被 F2FS 标记为加密时桥接返回 `ENCRYPTED_FILE`，不会把密文或空内容交给 SQLite。名称不可恢复时记录 `name_state=encrypted_or_unavailable`，不制造路径。

能明确识别 userdata 但全部目标内容锁定的完整预检任务标为 `COMPLETED_WITH_LOCKED_USERDATA`（Task status 为 completed，覆盖为 LOCKED），消息明确说明 Android 工件覆盖不完整；不是 `FAILED`，也不是“已完成全部 Android 分析”。

## 已知边界

- 仅 live 文件系统遍历和可读普通文件；不声称删除文件恢复、空闲区雕刻、历史 checkpoint/NAT/SIT 重建、FBE 解密、设备密钥提取。
- 不支持 Android sparse、super/dynamic partitions、M01/MFC/MF/BCP、UFS LUN 重组、闭源 SDK；未知或损坏文件系统 fail closed。
- qnxprobe 固定版本不会读取 F2FS compressed 文件；coverage 标 `UNSUPPORTED`。对带新 feature flag 的其他变体也不承诺完整兼容。
- 单次索引最多 1,000,000 项、目录深度受限为 64 层，IPC 输出最多 128 MiB，单文件提取最多 8 GiB，F2FS 子进程超时 600 秒；触限不得宣称分析完整。这些边界特别影响多 TB 检材，需实测并按任务分区处理。
- 预检的 E01 来源哈希当前针对选中的文件；多段 EWF 集合尚未建立整套分段哈希绑定，不能把单段哈希称为完整介质校验。
- 旧式手工 `tsk` Task 仍可建立，但 UI 标记 `UNVERIFIED_SOURCE`，不得与预检通过的 Android 镜像任务等同。

所有合成测试镜像由测试脚本生成在临时目录，真实镜像不会被写入、修复、挂载为可写或进行 journal replay。项目方真实 FBE 与厂商 F2FS 特性仍需现场样本对照；不能据此宣称支持所有 Android 手机。

## 合成验收记录（2026-09-26）

`tests/integration/test_android_filesystem_image_e2e.py` 与隔离的 `test_android_filesystem_http_e2e.py` 构造相同逻辑文件树，分别落入单分区 EXT4、单分区 F2FS、完整 RAW+EXT4、单段 E01+EXT4、完整 RAW+F2FS、单段 E01+F2FS。六条链均为 SMS 2（含 WAL 中第 2 条）、联系人 1、应用 1、Wi‑Fi 1；每条链在 `android_filesystem_provenance` 中产生 6 条来源记录。HTTP Task 均通过完整哈希预检、准入、分析、coverage manifest 与 `android.db` 核验。篡改预检后的镜像被 HTTP 409 拒绝。

锁定 fixture 是在**生成的** F2FS 镜像上设置 fscrypt feature 和 inode 加密标记，用于验证 fail-closed 状态机；并非真实手机加密样本。预检给出 `LOCKED`，Task 给出 `COMPLETED_WITH_LOCKED_USERDATA`，coverage 为 `LOCKED`，不运行 AndroidAnalyzer 解密/解析。真实设备 FBE、metadata encryption、不同厂商 checkpoint/压缩特性仍待真实样本确认。

隔离 HTTP 合成 Task 的读取器指标（毫秒，测试机）：

| 来源 | 文件系统遍历 | Android 分析 | 索引文件 / 按需提取 | 读取字节 |
| --- | ---: | ---: | ---: | ---: |
| userdata EXT4 | 5 | 61 | 6 / 6 | 53,541 |
| userdata F2FS | 139 | 895 | 6 / 6 | 53,541 |
| RAW+EXT4 | 3 | 60 | 6 / 6 | 53,541 |
| E01+EXT4 | 21 | 58 | 6 / 6 | 53,541 |
| RAW+F2FS | 148 | 934 | 6 / 6 | 53,541 |
| E01+F2FS | 170 | 1,070 | 6 / 6 | 53,541 |

这些数字只适用于小型合成镜像，不推算 TB 级或真实手机镜像吞吐；完整 SHA-256 预检与任务前后复核的时间不计入 `analysis_milliseconds`。

合成 EXT4 中的短信主库 provenance 实例（`android_filesystem_provenance`）：来源 SHA-256 `be1c663c7eacec983c148c0b50910eacb2571c11dae2439f35c086af1014086f`，`container_type=raw`，`partition_start_offset=0`，`filesystem_type=ext4`，`filesystem_object_id=18`，`filesystem_path=data/com.android.providers.telephony/databases/mmssms.db`，`normalized_android_path=data/data/com.android.providers.telephony/databases/mmssms.db`，主库文件 SHA-256 `d7a0f935887389859d2569220b0db74e0d3f8ab312cd2c9985489a05024ca883`，读取器 `The Sleuth Kit 4.14.0`。WAL 另有独立 provenance 行，不能把仅主库哈希当作 SQLite 合并视图哈希。

HTTP Task 的 coverage manifest 关键字段示例（仅节选）：

```json
{
  "schema_version": 1,
  "container": "raw",
  "partition": {"name": "lba0_userdata", "offset": "0"},
  "filesystem": "ext4",
  "encryption": "UNENCRYPTED",
  "reader": "The Sleuth Kit 4.14.0",
  "artifact_types": {
    "sms": {
      "status": "PARSED",
      "source_candidates": ["data/data/com.android.providers.telephony/databases/mmssms.db"],
      "parsed_count": 2,
      "failure_reason": ""
    }
  },
  "performance": {"indexed_file_count": 6, "extracted_member_count": 6, "bytes_read": 53541}
}
```

示例的 `partition.name` 取自实际预检分区标签，单分区合成 fixture 可为 `lba0_userdata`；不同容器/工具的标签不作为 Android 判定的唯一依据。
