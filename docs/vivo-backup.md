# vivo / iQOO 手机备份取证

本文说明当前分支对 vivo（含 iQOO）PC 助手备份的识别、索引解析与负载解码。

## 备份结构

vivo 手机助手 / 互传导出的备份是一个目录，包含三部分：

| 部分 | 内容 |
|---|---|
| `.backup` | 单行 JSON 头：`model`、`createTime`、`encrypted`、`backupPackageVer`、`success` |
| `db/` | LevelDB 索引。键是类别汇总（`sms`、`contact`、`call`…）或条目记录 `<类别>_<7位序号>_<sha1>` |
| 每项一个文件 | 文件名即内容 SHA-1 |

`db/` 是唯一权威索引。条目值形如：

```json
{"filename":"storage/emulated/0/DCIM/Camera/IMG_20180620_143828.jpg",
 "hash":"1b90a570521e806982f6bac0e6785126341909b7",
 "size":3403363,"mtime":1573115211000}
```

## 两类数据要区分

索引里有两种类别，语义完全不同：

- **文件型**（`data_type` 3 或无）：相册 4259、文档 395、音乐 192、视频 171、录音 7、压缩包 16、应用 294、设置 41。这些在备份里有实际文件，按 hash 可定位。
- **结构化记录**（`data_type` 1/2）：联系人 3039、通话 3000、短信 2331、日程 27、便签 4、系统设置 42。它们只有手机侧 `count`，**备份包内没有数据文件**。

因此本实现不会因为 `count=2331` 就往 `sms_messages` 写 2331 行。预检和任务都会把结构化类别单独列出，并注明"手机侧计数，不是备份内记录数"。

## 负载混淆（xor_obfuscated）

`.backup` 或索引声明 `xor_obfuscated: true` 时，每个负载文件都按位置做 XOR：

```
plain[i] = cipher[i] ^ key[i % 8]
key = 7F A3 C8 E1 5B 9D 2E F4
```

密钥来自已知明文分析。若干台设备的相机 JPEG 都以 `FF D8 FF E1`（SOI + APP1）开头，这固定了密钥前 4 字节；APP1 长度字段与 `Exif\0\0` 标记固定了后 4 字节。全量 5040 个文件验证：解码后文件头分别命中 JPEG（2221）、PNG（1979）、ZIP（258）、MP4（177）、MP3（118）、RIFF（53）、OLE（14）、PDF（9）、FLAC（6）、RAR（4）、PE（3）等标准魔数，无一例外。

**这不是加密**：没有 nonce、没有 KDF、没有完整性标签，密钥全设备通用。真加密（`encrypted: true`）仍会被拒绝并报 `VIVO_BACKUP_ENCRYPTED`。

解码在 `src/analyzers/VivoAnalyzer/VivoDeobfuscator.cpp`。任务启动时会先做探针：解码 8 个样本文件的头部，命中已知魔数的比例 ≥50% 才认为密钥适用。若厂商更换密钥，探针失败，覆盖度会退回 `locked_or_unsupported`，不会假装解析成功。

## 落库映射

| 索引类别 | `mobile_artifacts.kind` |
|---|---|
| album | `media_photo` |
| video | `media_video` |
| music | `media_audio` |
| record | `recording` |
| document | `document` |
| zip_file | `archive` |
| settings_file | `app_settings` |
| app | `app_package` |

每个索引条目写一行 `mobile_artifacts`，`record_json` 包含原始路径、hash、大小、mtime 和 `payload_state`（`readable` / `deobfuscated` / `obfuscated`）。`source_key` 是合法 JSON，`source_path` 用原始文件路径，保证 `android_artifact` 证据链可以直接引用。

`mobile_backup_manifest` 记录 `platform=Android`、`device=<model>`、`backup_version`、`module_count`（应用数）与 `adapter_version=vivo-backup-v1`。

## 性能

5,334 条记录必须在一个事务里写入。逐条自动提交时每条都要 fsync，任务会看起来卡死；单事务后完整任务约 10 秒（含 LevelDB 解析与探针）。

## 覆盖度语义

每类写一行 `android_source_coverage`：

- `PARSED`：负载未混淆，或混淆已被内置密钥成功解开；
- `locked_or_unsupported`：`encrypted: true`，或混淆探针失败（密钥不适用）；
- `no_candidate_path`：索引中没有该类条目。

`android_coverage_status` 由既有逻辑统一计算，因此只有文件型类别、没有结构化记录的备份会如实报 `incomplete`。

## 未支持

- `encrypted: true` 的备份解密（需要用户密码，算法未公开）；
- 应用内数据库（微信 `weixin_data` 等）虽可解出，但未逐应用适配 schema；
- 结构化记录（短信/联系人/通话）无法提供，因为备份包里根本没有这些数据——这需要在手机上重新做一次包含"系统数据"的备份。

## 验证

```bash
# Python 预检
cd python_service && .venv/bin/python -m pytest tests/unit/test_vivo_backup_preflight.py -q

# C++ 提取器 / 解析器 / 反混淆
cd build && ./tests/test_vivo_backup_gtest

# 真实样本端到端（需先启动 C++ 8666 与 Python 8090）
cd web && E2E_VIVO_BACKUP=/path/to/vivo_extract node scripts/e2e-vivo-task.mjs
```

索引桥接 CLI（C++ 任务在分析前调用一次，把 LevelDB 转成 JSON）：

```bash
python_service/.venv/bin/python scripts/vivo_backup_index_cli.py <backup_root> <output.json>
```
