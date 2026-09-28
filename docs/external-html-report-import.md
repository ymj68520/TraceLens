# 第三方 Android HTML 报告导入（派生证据）

本功能只读索引第三方工具**已导出的 HTML 报告**。记录的 `source_type=external_html_report`；它们是第三方派生记录，**不是** TraceLens 从原始 Android 镜像重建的工件。索引只写运行数据目录中的 `android_report_imports/<import_id>/records.db`、`report_manifest.json`、`report_import_coverage.json`，绝不写入 `android.db`，也不触发 `AndroidAnalyzer`。Task 关联仅是人工管理关系，不证明来源相同。

## 已验证的样本目录结构

```text
报告包/
  index.html                         # 外层入口；静态 frame 指向首页
  report/
    page.js                          # var page = {"page":[{"currentPage":1,"contenthtml":"content0.html"},...]};
    content0.html                    # 外层首页
    检材目录/
      index.html                     # 静态 frame 可指向检材首页（不执行其中脚本）
      export.db                      # archiveInfo：工具名/版本，非原始手机数据库
      report/
        content/
          data.js                    # var data = {"list":[...]}; 静态导航 JSON
          content0.html             # 检材首页，可能不在外层 page.js 中
          content1.html ...          # 报告表格页
        resource/                    # 报告附件
```

只接受 `page.js` 中明确可解析的 JSON 字面量 `var page = {...}`，验证 `currentPage` 为唯一正整数、`contenthtml` 为报告目录内的相对 `contentN.html`。不执行 JS、不执行浏览器 eval。`data.js` 同样只读固定 `var data = {...}` JSON 形状，用于导航分类；`page.js` 用于页码/文件映射及缺页检查。静态 `<frame src>` 可标记外层/检材首页，避免把样例的检材 `content0.html` 错判成未知页。其他 JS 结构返回 `UNSUPPORTED_PAGE_JS` 等 warning，安全内容页仍继续解析。**无表格但有明确标题和可见正文**的页面按 `section_text` 保守索引为章节文本，不冒充表格行、消息或联系人；无法确认结构且没有可信文本时标 `UNSUPPORTED_PAGE_STRUCTURE`。

单个已验证样例不代表该工具其他版本，也不代表美亚竞赛未知原始镜像或私有容器。`REAL_SAMPLE_VALIDATION_REQUIRED` 适用于新的厂商/版本/目录形状；须以现场样本对照原工具导出清单。

## 导入结果与状态

每次有效报告包导入写出：

- `report_manifest.json`：`import_id`、`source_root`、`source_sha256`、`parser_version`、入口/metadata/JS 是否存在、页码映射、声明/发现/解析/跳过/失败页、表/行数、附件引用、结构化 warnings、状态。
- `report_import_coverage.json`：总页、成功/失败页、表数、记录数、各 category/application/来源页计数、未映射字段单元格数、截断行、未支持/跳过页、缺失附件、warning 数。
- `records.db`：只读来源的派生索引。`source_sha256` 是**已纳入索引的来源路径及可哈希附件引用与各文件 SHA-256 的排序清单摘要**，不是原始手机、整个报告目录或介质镜像的哈希；超限/缺失页和未哈希附件未纳入该摘要。每条记录另有来源页面 `source_hash`。重新选择同一报告时会复核已索引文件/附件哈希；发现变化即新建导入批次，不复用旧的完整性结论。

状态语义：

| 状态 | 判定 |
| --- | --- |
| `COMPLETE` | 有可信记录，声明页（含静态首页）与发现页对应，目标页全部解析，且无缺页、跳过、解析失败、行截断、缺失附件或不支持结构等 warning。 |
| `PARTIAL` | 有可信记录，但存在上述任一 warning；API 返回 201/200 不改变此状态。 |
| `FAILED` | 报告入口可建立索引任务，但没有得到可信记录，或 metadata 无法建立。完全不符合报告入口结构的路径会在创建前返回 HTTP 400。 |

典型 warning code：`PAGE_JS_MISSING`、`UNSUPPORTED_PAGE_JS`、`UNSUPPORTED_PAGE_MAPPING`、`PAGE_NUMBER_GAP`、`MISSING_PAGE`、`UNDECLARED_PAGE`、`DATA_JS_MISSING`、`DATA_JS_UNSUPPORTED`、`PAGE_LIMIT`、`PAGE_SCAN_LIMIT`、`PAGE_PARSE_FAILED`、`UNSUPPORTED_PAGE_STRUCTURE`、`SYMLINK_DIRECTORY_SKIPPED`、`MALFORMED_ENCODING`、`TRUNCATED_ROW`、`ATTACHMENT_REF_LIMIT`、`MISSING_ATTACHMENT`。不要把 `PARTIAL` 当作完整取证结论。

## `records.db` schema 与保守字段规范化

`report_meta` 保存导入元数据；`pages` 保存已解析源页路径、大小、SHA-256、页码和表/行数；`records` 保存行级记录。主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `record_id` / `id`, `import_id`, `source_type`, `source_vendor`, `record_kind` | 稳定记录 ID、导入批次、固定派生来源类型、`export.db.archiveInfo.softName` 及 `table_row` / `section_text` 粒度。 |
| `category`, `application`, `section_title`, `table_title` | 来自导航/章节/标题的分类和明确应用标签；不从记录内容猜应用。 |
| `timestamp`, `sender`, `receiver`, `account`, `content`, `file_path` | 仅在明确表头别名映射时填写，否则为 `NULL`；`occurred_at` 仅从明确时间字段解析，保留报告原时区语义。 |
| `raw_fields_json`, `raw_text`, `content_truncated` | 保留原表头与单元格、可见行文本及截断标记；无表头以 `column_N` 保存，不把文本冒充标准字段。 |
| `source_file`, `source_page`, `source_table_index`, `source_row_index`, `source_anchor`, `source_locator`, `source_hash` | 原报告页相对路径、页/表/行位置、页内原锚点、稳定定位串及导入时页面 SHA-256。未编号检材首页的 `source_page` 可为 `NULL`；`section_text` 使用表号 0 与章节序号。 |
| `source_start_offset`, `source_end_offset`, `attachments_json` | 解码后源 HTML 行片段的字符范围与仅在报告根目录内解析的附件引用。 |

当前明确表头别名：发送人/发件人/Sender→`sender`，接收人/收件人/Receiver→`receiver`，消息内容/内容/Message→`content`，时间/日期/Timestamp→`timestamp`，账号/账户/Account→`account`，文件路径/路径/File Path→`file_path`。其他表头仅进入 `raw_fields_json`，不猜语义。全文检索使用 `raw_text`，因此未映射行仍可检索；检索命中不等于标准字段已识别。

## 来源回跳与安全边界

记录的 `source_locator` 形如 `report/检材目录/report/content/content1.html#table-3-row-17` 或 `.../content11.html#section-2`，按相对页路径和表/行或章节序号唯一定位，不修改原 HTML。详情页显示源页、页码/表/行或章节、原页面哈希，并提供“查看原始报告位置”：后端仅通过 `import_id + record_id` 从已索引 DB 找到页路径，重新验证来源页 SHA-256，再在受限 HTML 视图中**转义**显示原始页面对应片段和高亮标记。完整原页面另可作为 `text/plain` 附件下载；任何报告脚本都不会执行。源页变更/缺失时拒绝回跳。

路径必须留在导入时报告根目录内；拒绝绝对路径、`..`、symlink 越界、外部 URL、`file://` 与 `data:` 附件 URI。源定位视图设置 `Content-Security-Policy: default-src 'none'`。单页 25 MiB、全部内容页 256 MiB、最多 2,000 页、每页最多 5,000 表/200,000 行、HTML 嵌套深度 256、最多扫描 100,000 文件/10,000 目录、`page.js`/`data.js` 各 2 MiB；超限明确告警并保留其他安全页的结果。附件不可用标 `MISSING_ATTACHMENT`；未哈希附件不能获得完整性保证。未识别编码字节可安全替换显示，但标 `MALFORMED_ENCODING`，状态不判完整。

## 现场导入与核验

1. 保留第三方导出原包及来源/交接/哈希记录，不把报告文件复制进 Git。服务器证据目录默认项目上级目录；可用 `ANDROID_REPORT_SEARCH_ROOT` 指向专门的只读目录。
2. Task 页“检材预检”先核对报告目录结构与逐文件清单/哈希；预检不是导入完成证明。
3. 前端进入 `/android?mode=report`，在已发现报告列表中选择报告并导入；可选关联现有 Task，但不因此成为该 Task 的原生 Android 工件。
4. 查看导入状态、完整度、记录数、warning 数；通过 `/api/android-report/imports/{id}/manifest` 和 `/coverage` 取机器可读的完整清单。对 `MISSING_PAGE`、缺失附件和跳过页逐项核对原工具导出。
5. 检索/筛选记录，打开详情并按 `source_locator` 回跳至安全文本视图；抽查源页 SHA-256、原始表格行及附件。只有核对后才可在案件分析中引用其派生性质。

## 本地真实样例验收（未提交数据）

对项目方当前提供的本地报告包进行过只读预检、导入、API 与无头浏览器集成验证。完整逐文件哈希预检识别为 `derived_html_report`，**6,544 文件**，状态 `completed / manifest_hashed`、哈希错误 0、清单未截断；该目录清单哈希不是手机原介质哈希。报告导入的 `page.js` 映射 21 页，加 1 个检材静态首页，发现/成功解析 **22/22 页**，入库 **7,404 条派生索引记录**（7,366 条表格行、38 条文本章节），页面解析失败 **0**、跳过/不支持页 **0**、截断行 **0**。分类计数：网盘 3,724、设备 2,370、媒体 585、联系人 511、其他 130、微信 75、通话 7、QQ 2。唯一导入 warning 为 `MISSING_ATTACHMENT` 1 条，因此**报告导入状态是 `PARTIAL`**，不能因预检哈希完成而写作 `COMPLETE`。分类计数是混合粒度的**索引记录数**，不是手机数据总条数。详情和两种记录的来源回跳链路已在本地样例上验证。真实报告包留在仓库外；自动化集成测试通过 `TRACELENS_HTML_REPORT_SAMPLE` 指向现场文件，未设置时标记 `REAL_SAMPLE_VALIDATION_REQUIRED` 并跳过。
