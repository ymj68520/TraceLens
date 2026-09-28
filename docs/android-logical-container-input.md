# Android 逻辑归档/备份输入

第三阶段新增 `tar`、`seven-zip`、`android-backup` 来源模式。它们只负责安全枚举与按需提供成员字节，**不重新实现短信、联系人、应用或 Wi‑Fi 解析**；真正的工件由现有 `AndroidAnalyzer::analyzeAndroidData()` 写入 Task 的 `android.db`。`CAN_ANALYZE != forensic completeness`：还必须核对来源覆盖、实际表行数、加密状态和原始文件。

## 格式、构建与许可证

| 来源 | 容器读取 | 条件 |
| --- | --- | --- |
| `.tar`, `.tar.gz`, `.tgz`, `.tar.xz` | 系统 libarchive，支持 POSIX ustar、GNU/PAX 路径和 gzip/xz 过滤器 | 归档安全枚举、可信 Android 根、Task 预检哈希验证后进入 AndroidAnalyzer。 |
| `.7z` | 系统 libarchive 7z reader；成员按需读取，不调用 shell | 同上；加密 7z 受当前 libarchive 版本能力限制。 |
| `.ab` | 严格 `ANDROID BACKUP\n` 头部，AOSP 版本 1–5；AES-256-CBC/PBKDF2 与 zlib 流式解码后由 libarchive 读取内部 TAR | 无密码或已正确解锁且存在可信 Android 路径；旧版/非标准加密变体会拒绝。 |

`setup.sh` 安装 `libarchive-dev`；CMake 对它 `REQUIRED`，缺失时构建失败而非悄悄禁用。Python 密码预检使用 PyCA cryptography；组件及许可证见 [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)。没有 vendor 商业 SDK、来源不明的可执行文件或 7z 解压命令。

## 调用链与路径映射

```text
TAR/7z/AB 文件 → Evidence Preflight（只读识别、限额清单、SHA-256）
  → HTTP Task 准入复核（路径、大小、格式、Adapter、SHA-256）
  → ArchiveFileExtractor（libarchive / AB stream，按需取成员）
  → IFileExtractor::extractFileByPath()
  → AndroidAnalyzer → Task android.db
```

`AndroidPathMapper` 集中验证成员路径。可靠证据包括 `data/data/`、`data/user/0/`、`data/user_de/0/`、`data/system/`、`data/misc/wifi/`、`system/build.prop` 等具体 Android 工件路径；**单独出现一个 `data` 目录不够**。在确认根路径后，`data/` 和 `system/` 的其他文件也可按需提取。安全支持字面 `/data/data/...`、`./data/data/...`、`userdata/data/...`、`root/data/...`，以及所有常规成员共享的单层包装目录（如 `phone_export/data/...`）。`.ab` 的公开 `apps/<package>/db|f|sp/...` 成员分别映射为 `data/data/<package>/databases|files|shared_prefs/...`。冲突的规范化目标拒绝进入分析。

归档中的 SQLite 主库、`-wal`、`-shm`、`-journal` 分别按 AndroidAnalyzer 的实际请求提取，避免仅复制主库导致 WAL 行丢失。其他内嵌 ZIP/TAR/IMG/AB 只计入 `nested_container_detected`，不递归打开。

## 安全、加密与状态

- 所有成员在枚举时拒绝 `..`、非 Android 绝对路径、Windows 盘符、UNC 路径、模糊分隔符、过长路径及规范化冲突；符号/硬链接不作为 Android 文件内容读取。
- C++ Adapter 最多索引 100,000 成员，单成员 8 GiB、总声明展开量 2 TiB、路径 4096 字符、单段 255 字符；另检查高压缩比。超过界限报 `RISK_REJECTED`，不落盘解压整包。Python 预检另有 20,000 成员、15 秒的保守上限；超限不提供一键建 Task。
- `.ab` 由头部而非 `.ab` 扩展名识别。缺密码：`LOCKED_BACKUP`；密码不正确：`LOCKED_BACKUP`；不支持的加密/版本：`UNSUPPORTED_BACKUP_VARIANT`；截断流：`MALFORMED_BACKUP`。不会尝试密码猜测。
- 7z 可在内存中向 libarchive 提供密码，不写入 argv；缺密码或错误密码报 `LOCKED_ARCHIVE`，本机库不支持的加密方法报 `UNSUPPORTED_ARCHIVE_VARIANT`。不能把“有密码输入框”当成所有加密 7z 均可读。
- 预检密码只在当前作业的内存中使用，结束时擦除可变字节缓冲区；Python 不保证对临时不可变字符串做物理清零。job JSON/清单仅保留 `password_supplied=true/false`。Task 运行时密码不持久化并在 C++ 缓冲区使用后清零；CLI 的新归档模式禁止 `--backup-password <pass>` argv 传递，只接受 stdin 或已打开的 FD。全局参数校验日志也不会输出原请求体或带值的 `input`。
- 当前默认 Web/API 地址是 HTTP，密码请求**没有传输层加密保证**。现场通过局域网提交密码前应由部署方提供 HTTPS 反向代理或可信隧道；本阶段未改网络拓扑或实现 TLS。
- 新三种 HTTP source mode 必须带已完成、`integrity_status=verified` 的 `preflight_job_id`、`preflight_source_sha256`、`preflight_detected_kind`。Task 创建与分析前后重算哈希；变化报 `EVIDENCE_CHANGED_AFTER_PREFLIGHT`。`platform_analyze=false` 会拒绝新归档 Task。

## Provenance 与 Coverage

`android.db.android_source_provenance` 对每个**实际成功提取**的文件保存：`source_container`、`source_container_sha256`、`source_member_path`、`normalized_android_path`、`member_size`、`member_sha256`、`adapter_type`、`adapter_version`。例如由 `sms_messages` 的预设来源路径可反查到归档内的 `mmssms.db` 及独立的 `mmssms.db-wal`。

`android_container_coverage` 分别记录来源路径、规范化路径、Adapter、`FOUND` / `PARSED` / `NOT_FOUND` / `EXTRACT_FAILED` 等状态及原因；同一信息还进入既有 `android_source_coverage` 的 `container:<adapter>` 行。只有目标工件表确有解析行时才把对应的已提取来源标为 `PARSED`，其余文件仅为 `FOUND`。锁定/不支持/格式损坏会在 Task 初始化时失败，不产出“completed-success”的空分析。Task `completed` 只代表本轮流水线结束，不代表所有目标路径已找到或全部 Android 数据可解密。

## 使用示例

HTTP Task 必须先在“检材预检”中完成单文件 SHA-256。界面在安全枚举并证实根路径后预填；等价 API 请求结构（示意值，不是实际证据）：

```json
{
  "image_path": "/evidence/android_export.tar.gz",
  "android_source": "tar",
  "scenarios": ["android"],
  "platform_analyze": true,
  "preflight_job_id": "0123456789abcdef0123456789abcdef",
  "preflight_source_sha256": "<64 hex characters from the completed job>",
  "preflight_detected_kind": "tar_container"
}
```

CLI 可选 `--android-source tar|seven-zip|android-backup --android-analyze --no-ai`；例如 `forensic_analyzer /evidence/backup.ab --android-source android-backup --android-analyze --backup-password-stdin --no-ai`。CLI 遗留命名仍把独立 Android 分析数据库写为 `<baseName>_files.db`，HTTP Task 则写 `android.db`；两者均由同一 AndroidAnalyzer 解析。密码不出现在命令行参数值中。

## 已知限制

此适配不处理 F2FS raw/E01、Android sparse、`super.img`/动态分区、FBE、M01/MFC/MF、UFDR 或商业 SDK。真实大规模归档可能超过当前安全上限；未知厂商包装层、多根目录、未公开的 `.ab` 变体或 libarchive 不能解密的 7z 会拒绝/降级，不能依据扩展名宣称支持。预检清单与 Task 内容会分别检查，但它们也不能代替采集过程证明或手机原介质完整性鉴定。

## 确定性合成验收

不提交案件样本，测试运行时在临时目录生成相同的 Android 文件树。目录、ZIP、TAR、7z、AB 的 CLI 差分结果均为 `sms_messages=2`、`contacts=1`、`installed_packages=1`、`wifi_networks=1`；SMS 第二行保存在 SQLite `-wal` 中，验证了伴随文件按需提取。独立 HTTP Task 的 TAR、7z、AB 也分别产生 `android.db`，上述四表计数一致；每种来源实际使用成员的 provenance 为 6 行，`android_source_coverage` 中新容器行至少有 `PARSED=4`、`FOUND=3`、`NOT_FOUND=34`。这里的 `NOT_FOUND` 是分析器预设但本合成检材未包含的路径，不是现实证据不存在的结论。

加密 AB 的合成样本在正确密码下产生相同工件；无密码/错误密码会失败。来源在预检之后被改写，HTTP Task 创建返回 409 `EVIDENCE_CHANGED_AFTER_PREFLIGHT`。CTest 注册了 `AndroidArchiveGTests`、`AndroidArchiveCliEndToEndTests`、`AndroidArchiveHttpEndToEndTests`。这些结果只证明所列确定性样本已达 `CAN_ANALYZE`，不保证项目方尚未提供的其他加密变体或几个 TB 的归档能完成。
