# TOONExporter（src/core/TOONExporter/）

> **一句话**：把 files.db 的记录（含 LLM 分析列）导出为 TOON——一种"管道符分隔表格 + 首行 schema 声明"的紧凑文本格式，目标是把同一批文件证据塞进 LLM 提示词时比 JSON 省下 30-60% 的 token。

## 1. 为什么有这个模块

LLM 分析阶段要把文件清单喂给模型。JSON 的自我描述是把双刃剑：对程序友好，对 token 计数是灾难——每个对象重复一遍字段名、括号引号逗号全是开销。一次要带上百条文件记录（每条十几个字段）时，JSON 的结构开销可能比数据本身还大，直接挤占上下文窗口、推高成本。

TOON（Token-Oriented Object Notation）的解法是**把 schema 从每行提到首行只说一次**：

```
TOON.schema: name | path | size | category | llm_summary | ...
# records[123]
photo.jpg | /dcim/photo.jpg | 204800 | Images | A photo of ...
```

第一行声明字段顺序，之后每行一条记录、按序用 ` | ` 分隔，`# records[n]` 让模型预先知道数据规模。字段含义只出现一次，token 开销立刻从 O(行数×字段数) 降到 O(字段数+数据量)。解析侧（无论是 LLM 还是普通程序）按首行对齐列即可无损还原，这也是"lossless JSON conversion"的含义。

本模块是 TOON 的**生成端**：负责从 SQLite 查出文件记录、按配置选字段、做转义、拼出规范文本。它是一个无状态的纯函数式工具类（无单例、无状态成员，`TOONExporter.h:62-63` 默认构造）。

## 2. 在系统中的位置

唯一的 HTTP 消费点是导出路由：`GET /api/forensics/export/toon`（注册于 `src/network/HTTPServer/routes/ExportRoutes.cpp:14`，处理器 `handle_export_toon` 在 `:55-124`）。流程是 task_id → files.db 路径 → 只读打开（`SQLITE_OPEN_READONLY`，`:85`）→ 本模块导出 → 以 `text/toon` 附件返回（`:115-116`）。

数据源是 files.db 的**主 files 表**——这意味着它天然依赖 FileClassifier 建好的 category/llm_*/scene_* 列（见 FileClassifier.md 第 3 节）；查询固定包含全部 16 个字段（11 个元数据 + 5 个 llm_*，`TOONExporter.cpp:79-85`）。前端 React 拿到 .toon 文件后可直接展示或粘贴进 LLM 工作流。LLM 提示侧若直接内联 TOON，也应复用本模块保证转义一致。

```
files.db(files 表, 含 llm_*) ──queryFiles──> FileRecordWithLLM[] ──exportToTOON──> TOON 文本
GET /api/forensics/export/toon?task_id=&fields=&filter= ───────────────────────────┘
```

## 3. 核心概念与设计

**双入口共享一条渲染管线**。`exportToTOON(sqlite3*, config)` 先 `queryFiles` 把库行转成 `FileRecordWithLLM`（`:71-148`），再委托给纯记录版 `exportToTOON(records, config)`（`:219-222`）。记录版做三件事：确定字段集（`config.fields` 为空则用为 LLM 精选的 7 个默认字段：name/path/size/category/llm_summary/llm_description/llm_keywords，`:233-238`）；输出 schema 头与 `# records[n]`（`:242-257`）；逐行 `formatRecord`（`:259-262`）。`FileRecordWithLLM` 结构体（`TOONExporter.h:26-46`）是 files 表 16 列的镜像，`getFieldValue`（`:154-190`）负责字段名 → 值的字符串化，未知名返回空串而非报错——容错优先。

**转义规则**（`escapeValue`，`:21-65`）是格式正确性的核心：值里含 `|`、`"`、换行、`,` 或首尾空白时整段加引号，内部 `"` 双写、`\n`/`\r` 转成字面 `\n`。这段逻辑保证**任何文件名/描述都不会破坏列对齐**——取证数据里路径含空格、LLM 描述含换行是常态。

**配置的三个自由度**（`TOONExportConfig`，`TOONExporter.h:15-21`）：字段裁剪（fields）、行过滤（whereClause 直接拼进 SQL，`:87-89`）、schema 头开关。默认 `delimiter=" | "`、includeSchema=true、quoteStrings=true。

**whereClause 的安全边界不在本模块**：`queryFiles` 把它原样拼到 `WHERE` 后（`:87-89`），防线在路由层——`SQLiteHelper::is_safe_filter_clause(filter)` 先拒绝能突破成子查询/DDL 的片段（`ExportRoutes.cpp:72-79`）。直接在代码里调用本模块时传内部可信串即可，但暴露给用户输入的任何新入口都必须复用该校验。

## 4. 工作流程走读

一次 `GET /api/forensics/export/toon?task_id=T&fields=name,path,llm_summary&filter=size>1024`：

1. 路由校验 task_id 与 filter 安全性（`ExportRoutes.cpp:64-79`），定位 files.db 并只读打开（`:82-92`）。
2. 组装 config：filter 进 whereClause，fields 按逗号切分去空白（`:94-107`）。
3. `exportToTOON(db, config)` → `queryFiles`（`TOONExporter.cpp:71-148`）：`SELECT 16 列 FROM files [WHERE ...] ORDER BY path`，逐行读出（NULL 归空串），组装记录数组。
4. 渲染（`:228-265`）：schema 行 `TOON.schema: name | path | llm_summary` → `# records[N]` → N 行转义后的数据。
5. 路由以附件形式返回（`ExportRoutes.cpp:114-117`）。

## 5. 与其他模块的协作

- **FileClassifier（间接上游）**：files 表的 category 与 scene 列由分类器写入；llm_* 列由 LLM 分析服务回写（`SQL/file_classifier_sql.h:85-94` 的 UPDATE 语句族）。导出质量直接取决于这些列的填充率。
- **ExportRoutes / RouteHelpers**：提供 task_id→库路径映射、CORS、错误 JSON；只读打开避免与正在跑的任务抢写锁。
- **SQLiteHelper.is_safe_filter_clause**：whereClause 的安全闸门（见第 3 节）。
- **前端/LLM 工作流**：Content-Type `text/toon` 是自定义 MIME，前端按文本处理；LLM 侧把导出内容贴进提示词即为本格式的设计场景。
- 出错时行为：db 为空或 prepare 失败返回空记录集（`:75-97`），导出结果只有头两行、无数据行——不会抛异常。

## 6. 注意事项与已知问题

- **无行数上限**：`queryFiles` 没有分页/limit，几十万文件的库会生成巨大字符串（内存峰值 = 全部记录）。大库导出应配合 filter 或在路由层加 limit。
- **quoteStrings 配置项是摆设**：`escapeValue` 自行判断是否需要引号（`:27-44`），并不读这个开关——配置里设 false 不会改变输出。
- **列分隔符与 escapeValue 的 `,` 判断**：转义把逗号也视为需引号的字符（`:29`），这是为 CSV 复用预留的保守行为，TOON 本身并不需要；副作用是含逗号的描述总带引号。
- 表名硬编码 `files`：只能导出 files.db 主表，不能导出分类分表或 events 表。需要事件 TOON 时应新建 `queryXxx` + 对应记录结构，复用 `formatRecord`/`escapeValue`。
- `llm_analyzed_at` 输出为 Unix 秒，消费方展示时需自行格式化。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_toon_exporter.cpp`（`tests/CMakeLists.txt:802-812`，测试名 `TOONExporterTests`），覆盖转义、字段裁剪、schema 头。
- 手工验证：`curl 'localhost:8080/api/forensics/export/toon?task_id=<id>&fields=name,size,category'`，检查首行 schema 与 `# records[n]`、行数与 `sqlite3 <files.db> 'SELECT COUNT(*) FROM files'` 一致。
- 扩展方向：(1) 行数上限/分页参数——`queryFiles` 加 LIMIT 与 `getAllFieldNames` 旁的默认字段集文档；(2) 导出 events 表——复制 queryFiles 模式建 `EventRecordWithLLM` 与字段映射，渲染管线直接复用；(3) 让 quoteStrings 真正生效或从配置中删除，避免误导。

**最后更新**: 2026-08-23（解释式重写）
