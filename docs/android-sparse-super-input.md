# Android sparse / super 容器规范化（第五阶段）

本阶段只补第四阶段 Android 文件系统链的**外层容器**。`sparse userdata → raw → EXT4/F2FS → AndroidAnalyzer → android.db` 可形成用户工件分析；`raw/sparse super → LP metadata → system/vendor/product/...` 仅形成逻辑分区规范化，**不能**因此声称已分析 userdata。

## 固定开源工具与安装

在 Ubuntu 22.04/WSL 的已验收环境安装：

```text
android-sdk-libsparse-utils 1:10.0.0+r36-9
android-libbase-dev, android-liblog-dev, android-libsparse-dev,
android-libcutils-dev, android-libcrypto-utils-dev 1:10.0.0+r36-9
android-libext4-utils-dev 10.0.0+r36+ds-2
```

用 `bash scripts/install_android_container_tools.sh` 从固定 AOSP Android 10 r36 源码构建 `liblp/lpmake/lpunpack` 与只读 JSON `lp_inventory`：core commit `204bd34e58de124ead5a1e65b852608620077b84`、extras commit `ef17b323e8be065ed9fbcd1ea863d72e63488fc0`。源码和工具在忽略的 `.deps/aosp-android10-r36/`，不引入不明二进制；运行时核对源码 commit、包版本及工具 SHA-256。Ubuntu 的 `simg2img` SHA-256 为 `ce77e6e736c3ac65b4f7457ac3d760154c1017762f73bc72f00c5a77dfce09f5`。AOSP 组件许可证和上游链接见 [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)。此工具链只在上述固定环境完成构建/验证；更新发行版或编译器时应重新审核二进制哈希，不静默接受新版本。

## 只读生产调用链

```text
原始 sparse / raw super / GPT RAW-E01 内 super
  → Evidence Preflight：全文件 SHA-256 + sparse chunk / liblp metadata 校验
  → HTTP Task 准入：job、原路径/大小/哈希、格式、plan SHA-256、metadata slot 绑定
  → Task/work/android_normalization/
      ├─ sparse：AOSP simg2img → raw，重新哈希与探测
      ├─ 完整磁盘：只派生 super 物理分区；E01 经只读逻辑块视图
      └─ super：AOSP liblp 验证 metadata，AOSP lpunpack 按需提取所选逻辑分区
  → sparse userdata：第四阶段 IFilesystemEvidenceSource → AndroidAnalyzer
  → super：逻辑分区库存与 provenance，userdata=NOT_PRESENT_IN_SOURCE
```

Python `AndroidImageNormalizationPipeline` 上限 `MAX_NORMALIZATION_DEPTH=3`，不递归解出 archive/sparse/super 的任意嵌套。固定参数 `subprocess`/POSIX spawn，不用 shell。转换/提取前核算展开后字节和工作文件系统剩余空间，保留安全余量；不足返回 `INSUFFICIENT_WORKSPACE`。Task 前后重新验证原来源 SHA-256，派生文件也计算 SHA-256；若预检后原文件被改动，Task API 返回 409 `EVIDENCE_CHANGED_AFTER_PREFLIGHT`。

## Sparse 判定

`android_sparse_image.py` 只**验证** magic、版本、头长、chunk 头长、块大小、声明块/chunk 数、RAW/FILL/DONT_CARE/CRC32 类型、每块 payload 长度、累计展开块数、文件尾、整数与展开上限。存在 CRC 时在受控上限内校验 CRC 值；超限 fail closed。它不实现解码，真正转换由 AOSP `simg2img` 完成，之后核对 raw 实际大小/哈希并重新探测 EXT4/F2FS 或 LP metadata。

- 只识别 magic：`DETECT_ONLY`。
- header 有效、后续 chunk 结构未通过：`CAN_ENUMERATE`，附失败原因，不能创建 Task。
- 全 chunk 结构有效：`CAN_NORMALIZE_READY`。
- 预检实际安全转换且后续文件系统/LP metadata 验证：`CAN_NORMALIZE` 预览。预检派生物随后删除；Task 仍须重新转换、验哈希。
- 只有 Task 真实运行到 AndroidAnalyzer 并生成工件时，具体 sparse userdata 才为 `CAN_ANALYZE`。

预检产生 `SparseImageInventory`：`source_size`、`expanded_size`、`block_size`、`chunk_count`、四类 chunk 数量、`validation_status` 和 warning。超展开大小、稀疏炸弹、结构冲突或不够磁盘空间都不能转成“已分析”。

## Super 判定与来源边界

只有 LP geometry magic 加 AOSP `liblp::ReadMetadata` 成功并经额外实际文件长度/extent 边界检查，才返回 `ANDROID_SUPER`；普通名为 `super.img` 的文件不自动升级。`SuperPartitionInventory` 包含 metadata 版本与 slot 数、block devices、groups、partition attributes、每个 extent 的 target source/sector、selected slot。预检优先展示全部库存；默认**明确选择 slot 0**，活动槽一律 `ACTIVE_SLOT_UNKNOWN`，切换 metadata slot 须重做该 slot 的预检，不合并 `_a`/`_b`。

Task 只选择 `system/system_ext/product/vendor/odm`（含 `_a/_b` 名字）的逻辑分区，用 AOSP `lpunpack` 指定分区提取到 Task 私有目录，逐个记录输入 super SHA-256、metadata slot、分区名/group/attributes、extent 映射、派生路径与 SHA-256、工具版本。每个输出再做实际文件系统探测：EXT4/F2FS 需只读 walker 可打开；EROFS 只识别并标 `UNSUPPORTED_FILESYSTEM`，`UNKNOWN` 不猜。多 block-device 或缺少 companion image 返回 `MULTI_DEVICE_SUPER_INPUT_REQUIRED`，不会把部分导出称为完整成功。LP metadata 不包含足够证据判断离线设备的 active slot 或 Virtual A/B COW 合并状态，因此不重建运行时 snapshot。

完整 RAW/E01 中的 super 由分区表和 LP geometry 共同定位，仅派生该物理分区；不复制整个磁盘。`super` 通常只包含系统动态分区，Task coverage 明确 `userdata.status=NOT_PRESENT_IN_SOURCE`，不会显示 `ANDROID_USERDATA_ANALYZED`。

## 可追溯产物

每个成功 Task 生成 `android_normalization_manifest.json`：`SOURCE → UNSPARSE? → SUPER_PARTITION_COPY? → LOGICAL_PARTITION_EXTRACT? → FILESYSTEM_PROBE? → ARTIFACT_ANALYSIS?`。每个 step 有 `step_id/parent_step`、输入/输出 ID 与 SHA-256、格式、操作、工具/版本、参数、状态、警告。sparse userdata 的 `android.db` 文件来源 SHA-256 指向**派生 raw**；从 raw 回溯原始 sparse 需沿该 manifest 的 `UNSPARSE` step，不能混淆两个哈希。`android_coverage_manifest.json` 引用 normalization manifest；最终报告查看页同时展示来源覆盖。

## 明确不支持

FBE/metadata encryption 解密、M01/MFC/MF、UFS LUN、OTA incremental payload、Virtual A/B snapshot/COW merge、删除文件恢复、任意多设备 super、EROFS 工件解析。固定 Android 10 r36 `liblp` 对更新 LP metadata 版本不作兼容承诺；真实项目方镜像与 TB 级性能仍需现场验证。多段 EWF 未绑定完整分段哈希，禁止一键准入。未知或损坏结构 fail closed，不能因为工具返回 0 或文件名命中就宣称可分析。

## 合成验收（2026-09-26）

隔离 HTTP Task 使用与第四阶段相同的 userdata 文件树：EXT4 RAW 与 sparse、F2FS RAW 与 sparse 均得到短信 2（第 2 条只在 WAL）、联系人 1、应用 1、Wi‑Fi 1；每组 raw/sparse 的工件、来源覆盖与 6 条文件 provenance 完全相同。sparse EXT4 展开 134,217,728 字节、转换约 0.20 秒；sparse F2FS 展开 268,435,456 字节、转换约 0.39 秒。这些只对应小型合成 fixture，不可外推到 TB 级。

同一合成 super 的 raw 与 sparse，以及包含该分区的完整 GPT RAW/E01，均读得 LP metadata `10.0`、2 个 metadata slot、3 个逻辑分区 `system_a/vendor_a/product_a`；按需提取总计 25,165,824 字节。四条链对应逻辑分区 SHA-256 完全一致。slot 1 也被独立预检与 Task 读取；均不声称其为活动槽。合成 `product_a` 是 EROFS，正确标为 `UNSUPPORTED_FILESYSTEM`；userdata coverage 是 `NOT_PRESENT_IN_SOURCE`。完整磁盘只派生偏移 1,048,576 的 super 分区，没有整盘转 raw。来源预检后追加字节，建 Task 被 HTTP 409 拒绝。合成 super metadata 解析约 0.016 秒、3 个逻辑分区提取约 0.08 秒；未计完整哈希时间。

`android_normalization_manifest.json` 的合成链示例：原 sparse SHA-256 `87605c952932d3320fbc411bb510dfb9a2ba0a1e7ff81fa945b618f95a154ed5` → `UNSPARSE` 派生 EXT4 RAW SHA-256 `be1c663c7eacec983c148c0b50910eacb2571c11dae2439f35c086af1014086f` → `FILESYSTEM_PROBE` → `ARTIFACT_ANALYSIS`/`android.db` SHA-256。super 的 `system_a` 来源记录保留 `metadata_slot=0`、`group_name=main_a`、`extent_count=1` 以及 `{target_source:0,target_data:2048,num_sectors:16384}`，可回到原始 super 的具体块范围。精确完整记录由 Task 下载清单提供。

损坏测试分别覆盖 sparse magic/头截断/chunk 类型与大小/声明数量/尾部数据/CRC 值/展开上限/磁盘空间不足，和 super geometry/metadata checksum/非法 extent source/extent 超过镜像末尾/多 block-device 来源缺失；均 fail closed。这里验证的是固定 AOSP Android 10 LP 构型，不包括 Virtual A/B 或真实设备上更新的 metadata 变体。
