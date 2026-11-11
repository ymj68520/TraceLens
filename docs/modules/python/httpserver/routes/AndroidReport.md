# AndroidReport 路由（python_service/httpserver/routes/android_report.py，前缀 /api/android-report）

> **一句话**：第三方厂商 Android 取证 HTML 报告的**只读导入与查询**——把厂商导出报告（content*.html 页族+附件）解析成自己的索引库供分页检索与原文回看，绝不动报告本身、绝不执行其中的任何脚本；附带"导入↔任务"的链接管理，让一份外部报告挂进既有任务上下文。

## 1. 这组路由承担什么职责（为什么存在）

办案中常拿到的是兄弟单位/厂商工具导出的 HTML 报告，而不是原始镜像。这份东西是**派生报告**，不是手机镜像也不是应用库——android_report_import.py:1-4 的 docstring 划清边界："The export is a derived report... Only HTML text, read-only export metadata, and references to existing attachments are indexed. Vendor JavaScript and executables are never run or copied."这组路由的工作是：从候选根目录发现候选报告 → 解析（自带 HTMLParser、字段中英文别名映射、日期归一）→ 落自建 SQLite 索引 → 提供 candidates/imports CRUD、overview/manifest/coverage、records 分页检索、附件下载与"原文定位页"。解析器版本随 meta 记录（`PARSER_VERSION = "external-html-report-v3.3"`，android_report_import.py:45）。

挂载于 main.py:359。前端页面 `pages/AndroidReportImports.jsx` 嵌在 `/android` 页的 reportMode 里（Android.jsx:145）。

## 2. 典型调用方（前端哪个页面/组件）

- `web/src/services/androidReportService.js`：`listAndroidReportCandidates`（:6）、`createAndroidReportImportFromCandidate`（:8）、list/attach/detach（:11-19）、overview/manifest/coverage/records（:21-30）——唯一消费者是 `pages/AndroidReportImports.jsx`（270 行，含 `AndroidReportImports.test.jsx`）。
- 服务间：attach 端点经 C++ `get_task` 验任务存在（android_report.py:43-45，timeout 5.0、max_retries 1——控制挂载操作的延迟上界）；此外无服务间调用。

## 3. 核心数据结构

**import_id**：32 位小写十六进制（`IMPORT_ID = re.compile(r"[0-9a-f]{32}\Z")`，android_report_import.py:27）——与 IM 导入的 12-hex 不同域。

**候选与导入目录**（android_report_import.py:87-96）：候选在配置的 `candidate_root()` 下（外部报告的存放点），导入产物在 `import_root()/<import_id>/`（自建索引库 + meta.json）。meta 记录来源根、sha256 与页清单；读取时 `_source_still_matches`/`_verified_import_root`（:146/:243）会**重新校验来源未移动、未变 symlink**——来源漂移的报告拒绝服务（InvalidReport → 409），绝不用对不上账的索引。

**资源上限族**（:25-35，解析器的全部护栏）：`MAX_PAGES=2000`、`MAX_PAGE_BYTES=25MB`、`MAX_TOTAL_PAGE_BYTES=256MB`、`MAX_RECORD_CHARS=32000`、`MAX_ATTACHMENTS=30`、附件哈希字节上限（单 128MB/总 512MB）、`MAX_TABLES_PER_PAGE=5000`、`MAX_ROWS_PER_PAGE=200000`、`MAX_HTML_DEPTH=256`、扫描文件/目录数上限——厂商报告是敌意输入面，超限直接 `InvalidReport`（如 "HTML nesting exceeds supported limit"，:388；"table count exceeds supported limit"，:405）。

**字段别名表**（`_FIELD_ALIASES`，:39-51）：发送人/发件人→sender、消息内容→content、时间/日期→timestamp 等——厂商表格头是中文自由文本，归一后才可检索。

## 4. 端点语义分组（散文）

- **导入生命周期**：`GET /candidates`（android_report.py:15-17，列候选报告）；`POST /imports`（:20-30，**201**，body 只要 `candidate_id`；开始解析并建索引，失败 400）；`GET /imports?task_id=`（:33-35，列导入可按链接任务过滤）。
- **任务链接**：`POST /imports/{import_id}/tasks`（:38-52，body `task_id`；先 C++ 验任务再 `set_task_link`）；`DELETE /imports/{import_id}/tasks/{task_id}`（:55-63）——链接是元数据不是融合：外部报告永远不进任务的数据管线。
- **读取**：`GET /imports/{id}/overview`（:66-73）、`/manifest`（:76-83）、`/coverage`（:86-93）——meta/清单/类别覆盖的直读；`GET /imports/{id}/records`（:96-113，`query`≤200 + `category`≤80 + 分页 ≤100）；`GET /imports/{id}/records/{record_id}`（:116-123，单条详情）。
- **原文三端点**（对外部报告的"回看原始出处"）：`GET /attachment?path=`（:126-141，附件以 `application/octet-stream` **强制附件下载** + nosniff——绝不内联渲染厂商文件）；`GET /source-page?path=`（:144-158，原始 HTML 页转 **text/plain 附件**——HTML 永远不作为 HTML 送达浏览器，脚本无从执行）；`GET /source-location/{record_id}`（:161-174，记录在原页中的定位 HTML 片段，HTMLResponse 但带锁死 CSP `default-src 'none'; ... style-src 'unsafe-inline'; frame-ancestors 'none'`，:166-168）。

## 5. 数据流（读什么库、写什么）

**写**：只有导入时写自建索引（import_root 下的 SQLite + meta）；之后全部端点只读。**读**：候选/来源报告目录（只读，`_safe_source`，:236-241，越界即 InvalidReport "report file escapes the selected directory"）与自建索引库（`_connect`，:211）。

错误映射（路由层统一三段，:29-30 为代表）：`InvalidReport`/`ValueError`/`FileNotFoundError` → 400（导入创建）；读取端点的 `ValueError` → 400、`FileNotFoundError` → 404；**`InvalidReport` 在原文三端点是 409**（:136-137、:153-154、:169-170）——语义是"来源与索引对不上账"（移动/替换/symlink），属状态冲突而非参数错误：索引还在但不再可信，需要重新导入。

## 6. 边界与已知状态（安全边界/降级）

- **厂商内容三不原则**（docstring :3-4 + 实现佐证）：不执行（JS 从不被运行）、不复制（MAX_PAGE_JS_BYTES 只用于**检测**内联脚本体积上限，:31）、不内联送达（attachment/source-page 都强制下载，source-location 用 CSP 锁死）。这是把外部报告当敌意输入的安全 posture。
- **409 来源漂移**：`_verified_import_root`（:243-247）在每次访问来源文件前验证"来源根未移动、不是 symlink"，破约即 InvalidReport——导入不是快照截断，来源必须一直在原位。
- **链接不是融合**：attach 只写元数据（set_task_link），外部报告的记录不会出现在任务自己的证据域，反之亦然。
- **400/404/409 分工**：参数/解析失败 400；导入不存在 404；来源漂移 409。
- 分页上限 100（page_size le=100，:102）、检索词上限 200（:99）——索引库无 FTS，是 LIKE 级别的查询面。

## 7. 如何验证

- 前端契约：`web/src/services/androidReportService.js`、`pages/AndroidReportImports.test.jsx`。
- 服务层：`python_service/tests/unit/` 下 android_report_import 测试（解析器护栏、别名映射、来源漂移 409、字段归一）。
- 活体验证：把一份厂商导出报告放进候选目录 → `/android` 页 reportMode 导入 → 记录分页检索 → 点开一条记录的 source-location，确认浏览器收到的是锁 CSP 的片段而原页是纯文本附件。

相关阅读：[EvidenceIntake.md](EvidenceIntake.md)（同属"进场域"的预检路线）、services 实现层 `services/android_report_import.py`；C++ 侧相关任务准入见 [TaskManager.md](../../../cpp/network/TaskManager.md)。

## 8. 二轮深化 A：`_ReportPageParser` 的护栏式解析

android_report_import.py:338 起的 `_ReportPageParser(HTMLParser)` 把"解析敌意 HTML"写成了一组**先到先拒**的断言：

```python
# android_report_import.py:379-414（节选）
def handle_starttag(self, tag, attrs):
    ...
    if <嵌套超深>:
        raise InvalidReport("HTML nesting exceeds supported limit")      # :388
    if <表格超量>:
        raise InvalidReport("table count exceeds supported limit")       # :405
    if <行数超量>:
        raise InvalidReport("row count exceeds supported limit")         # :414
```

逐层含义：深度上限（MAX_HTML_DEPTH=256）挡的是解析器栈耗尽；表/行上限挡的是"一份报告里塞十万行"的资源放大；字节上限在打开文件前就检查。所有违规抛同一个 `InvalidReport`，路由层转 400——整个导入是**全有或全无**事务：要么得到一份完整索引，要么什么都不留，不存在"解析了一半的导入"。`set_source_text`/`_offset`（:365-377）则在解析时同步记录每条记录在原页的行/列偏移，这正是 source-location 端点能"跳回原文位置"的数据基础——索引与原文的可回溯性在解析期一次性建成。

**最后更新**: 2026-11-10（新建：第三方 Android 报告导入路由文档）
