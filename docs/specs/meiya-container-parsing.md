# 美亚柏科（MobileMaster FL-901）中间结果解析

> 状态：已实现并通过单元测试与真实样本端到端验证。
> 代码：`src/analyzers/AndroidAnalyzer/Meiya*.{h,cpp}`、`MobileEvidenceMeiyaAdapter.{h,cpp}`

## 1. 现象与性质

美亚柏科手机取证塔（`strProductCode: FL-901V5`）导出的中间结果里，主容器（`.mf` / `.dmf` / `.amf` / `config.db` / `*_RECORD_MFC.DB` / `*.bm`）看起来是高熵密文，但**不是真正的加密**：

- 内容是标准 SQLite，只是按 **1024 字节周期** 与一段固定掩码逐字节 XOR；
- 掩码长度恰好等于 SQLite 页大小，所以每个数据库页被同一段掩码覆盖；
- 同一案件内的多个容器**共用同一套掩码**（`config.db`、`.dmf`、`.mf`、`.amf` 全部一致）；
- 不同用途的容器（笔录库、审计流水）使用另外几套掩码，但仍属同一构造。

这属于可逆混淆而非密码学保护：没有认证、没有盐、密钥与设备/案件无关。

## 2. 掩码如何得到：运行时自推导

**本模块不硬编码任何厂商密钥。** 掩码从检材自身推导，理由是这既是工程上更稳的方案（软件升级换密钥后仍可用），也避免把第三方软件的密钥固化进代码库。

推导流程（`MeiyaContainerCrypto.cpp`）：

1. 按 1024 字节切页，**同族文件合并取页**（小文件页数不足以做统计）；
2. 生成两个候选掩码：
   - `zero_page`：把最高频页当作"全零页"，其字节即为掩码；
   - `byte_mode`：逐字节取众数（多数页在多数偏移上为 0）；
3. 用页 0 的已知 SQLite 头部（`SQLite format 3\0`）**精确修正前 16 字节**——统计方法在页头几个字节上容易被内容污染；
4. 用 **SQLite 自身** 执行 `PRAGMA integrity_check` 验证。通过者才被采信。

第 4 步是整个设计的关键。统计假设在小文件或特殊内容上会失效，而 SQLite 的完整性校验是客观判据；没有它，"看起来解开了"会被误当成"确实解开了"。

**同族缺失时借用**：若某族自身推导失败（例如 4 KB 的笔录库），会用已解出的其他族的掩码逐容器试解，仍以 `integrity_check` 为准。实测 `1029手机提取.mf`（12 KB）就是这样解的，标注为 `zero_page+borrowed_from_device`。

## 3. 容器族

| family | 文件 | 内容 |
|---|---|---|
| `case` | `<案件>.mf`、`*.bm` | 案件与设备身份 |
| `device` | `<设备>/<设备>.dmf`、`<设备>/config.db` | 规范化业务库（`TBL_PR_*`） |
| `mark` | `MFCExcerpt.db`、`MFCMark.db` | 笔录/标记 |
| `record` | `<设备>_RECORD_MFC.DB` | 操作审计流水 |
| `appdb` | `<设备>/AppsAmf/*.amf` | 每应用解析库 |

族名由文件名后缀决定（`_record_mfc.db` 必须在 `.db` 之前判断，否则会被归错）。

## 4. 解析范围与取舍

**只做 `TBL_PR_*` 映射**，理由：这是美亚自己的跨设备统一 schema，三台设备列名一致，一次映射覆盖全部检材。逐个解析 122 个 `.amf` 私有表成本高得多、收益集中在少数应用。

已映射到统一格式的表：

| 美亚表 | 统一 `kind` |
|---|---|
| `TBL_PR_SMS_INFO` | `sms` |
| `TBL_PR_CONTACT_INFO` | `contact` |
| `TBL_PR_DIALOG_INFO` | `call_log` |
| `TBL_PR_NOTES_INFO` | `note` |
| `TBL_PR_CALENDAR_INFO` | `calendar_event` |
| `TBL_PR_WIFI_LINK_NET_INFO`、`TBL_PR_WIFI_PASSWD_INFO` | `wifi_network` |
| `TBL_PR_INSTALL_INFO` | `installed_app` |
| `TBL_PR_MEDIA_INFO` | `media_file` |
| `TBL_PR_FILE_DOCUMENT_INFO` | `document_file` |
| `TBL_PR_SYS_ACCOUNT_INFO` | `account` |
| `TBL_PR_SYS_BOOT_TIME_INFO` | `system_log` |
| `TBL_PR_BT_INFO` | `generic` |

**每条记录保留完整原始行**：`raw_json` 是该行所有列的完整 JSON，`payload_json` 只是常用键的投影。因此未映射的列不会丢失，后续分析层要新字段时无需重新取数。

未映射的 `TBL_PR_*` 表会写一条 `unmapped_table` 覆盖度（含行数），明确"已盘点但未映射"，而不是让下游以为表不存在。

## 5. 时间语义

美亚时间是 `YYYY-MM-DD HH:MM:SS` 的**本地时间，无时区标记**。统一格式要求时间三元组，因此：

- `timestamp_raw` 保存原文；
- `timestamp_unit` 标为 `s`（当解析成功）或 `text`；
- `timestamp_seconds` 按 UTC 解析，**仅用于排序**。

**这个秒值不能当作绝对时刻引用**，除非另行确认设备时区。这是格式层面必须保留原文的原因之一。

## 6. 使用

```bash
# 一次完成取数 + 分析
forensic_analyzer /path/to/case_root --android-analyze --android-source meiya \
  --db-dir ./out

# 只取数，产出统一包
forensic_analyzer /path/to/case_root --android-analyze --android-source meiya \
  --mobile-extract --mobile-package-out ./case.mep.db

# 只分析已有的包
forensic_analyzer --android-analyze --mobile-package ./case.mep.db --db-dir ./out
```

`case_root` 可以是案件目录（含 `<name>.mf`）、设备目录（含 `<device>.dmf`），或 `.mf` 文件本身。

## 7. 真实样本实测

样本：`1029手机提取`，3 台设备（OnePlus GM1910 / OPPO PBEM00 / vivo V1824BA）。

容器解码结果：

| 容器 | 状态 |
|---|---|
| 3 × `config.db`、3 × `.dmf` | 解出，schema 83–89 表 |
| `.mf`、`SummaryMarkInfo.bm` | 解出（借用 device 掩码） |
| `MFCExcerpt.db`、`MFCMark.db` | 解出 |
| 3 × `*_RECORD_MFC.DB` | **失败**（见下） |

产出统一包：**30,096 条记录** —— 联系人 6,078、通话 6,000、短信 4,662、媒体 9,691、应用 1,675、文档 659、系统日志 64、WiFi 57、日历 56、账户 33、笔记 8。分析阶段零改动即写入 `android.db`，`contacts/sms/call_logs/app_notes/installed_apps` 计数与包一致。

## 8. 已知限制

**`*_RECORD_MFC.DB`（审计流水）未解出。** 这三个文件用另一套掩码，且实测中 `zero_page` 与 `byte_mode` 都无法产出通过 `integrity_check` 的镜像。可能原因是其页结构与常规 SQLite 不同（或掩码周期不是 1024）。它们只记录软件自身的操作审计，不是业务数据主体，因此按 `locked` 记入覆盖度并在报告中标注未解析，而不是假装解析成功。

**`.amf` 应用库（微信/QQ/Telegram 等）只登记未展开。** 这些库已成功解密，但在统一包里以 `file` 条目（`status=unsupported`）出现，行级解析需要按应用逐个写映射，属于后续增量工作。

**明文旁路未纳入。** `MY_MF_APPPrase/`、`*.db-wal`、`我的移动设备/` 等明文数据不在本适配器范围内；它们可作为交叉校验或降级路径单独处理。

## 9. 验证

- `tests/UnitTest/test_meiya_container_gtest.cpp`（6 项）：合成容器（真实 SQLite + 任意 XOR 掩码，**不含任何厂商密钥**）的掩码推导、精确往返、同族共享、明文库拒绝、非页对齐拒绝、随机数据必须校验失败。
- 合成夹具刻意构造"删除大表后留下的全零空闲页"，因为真实容器正是靠这类空页泄露掩码；不复现该条件，测试验证的就是不存在的假设。
- 回归：`ctest -R "Meiya|MobileEvidence|Miui|Harmony"` 全部 8 个套件通过。
