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

### 3.1 核心数据结构（TOONExporter.h:15-46）

```cpp
struct TOONExportConfig {
    std::string delimiter = " | ";      // Delimiter between fields
    bool includeSchema = true;          // Include TOON.schema header line
    bool quoteStrings = true;           // Quote string values
    std::vector<std::string> fields;    // Fields to export (empty = all)
    std::string whereClause;            // Optional WHERE filter
};

struct FileRecordWithLLM {
    // Core file metadata
    int64_t inode = 0;
    std::string name;
    std::string path;
    int64_t size = 0;
    std::string extension;
    std::string category;
    std::string type;
    int64_t mtime = 0;
    int64_t ctime = 0;
    int isDeleted = 0;
    std::string md5;

    // LLM analysis fields
    std::string llm_summary;
    std::string llm_description;
    std::string llm_keywords;
    int64_t llm_analyzed_at = 0;
    std::string llm_model_used;
};
```

逐组解释：`TOONExportConfig` 五个字段里实际生效的是三个——fields（空则取 7 字段 LLM 精选集，**不是** `getAllFieldNames` 的 16 个全量，注释里的 "empty = all" 与实现不符，见第 6 节）、whereClause（原样拼 SQL，信任边界在调用方）、includeSchema（关掉后输出只剩 `# records[n]` + 数据行，省 token 的极限形态）；`delimiter` 与 `quoteStrings` 是预留自由度，前者改了会破坏消费方按 ` | ` 切分的假设、后者根本没被读（见第 6 节）。`FileRecordWithLLM` 是 files 主表 16 列的一比一镜像（列名 ↔ 成员名的映射在 `getFieldValue` 的 if-else 链里，如 `is_deleted` ↔ `isDeleted`），全部带默认值——**缺列/NULL 的库也能导出**，NULL 文本列在 queryFiles 里统一成空串；它比 DatabaseManager 的 FileRecord 多了 5 个 llm_* 字段、少了时间戳四件套中的 atime/crtime 与权限 uid/gid——导出视野与流水线视野的字段差集。

### 3.2 核心接口清单

| 签名（TOONExporter.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `std::string exportToTOON(sqlite3* db, config = {})` | 查库 + 渲染一步到位 | ExportRoutes.cpp 的 handle_export_toon | db null/prepare 失败返回仅含头两行的文本 |
| `std::string exportToTOON(const vector<FileRecordWithLLM>&, config = {})` | 纯记录渲染（无 SQL） | 上一重载；也可直接喂内存数据 | 恒成功 |
| `static vector<FileRecordWithLLM> queryFiles(db, whereClause="")` | 16 列查询，NULL 归空串，按 path 排序 | exportToTOON(db 版) | db null 或 prepare 失败返回空 vector |
| `static std::string escapeValue(value)` | TOON 转义（含引号判定） | formatRecord；也可被 CSV 导出复用 | 恒成功 |
| `static vector<string> getAllFieldNames()` | 16 个合法字段名 | 路由层校验 fields 参数 | 恒成功 |
| （私有）`std::string formatRecord(record, fields, delimiter) const` | 单行渲染：取值→转义→拼接 | exportToTOON 记录版 | 未知字段渲染为空串 |
| （私有）`std::string getFieldValue(record, fieldName) const` | 字段名→字符串值（数值 to_string） | formatRecord | 未知名返回 "" |

## 4. 工作流程走读

一次 `GET /api/forensics/export/toon?task_id=T&fields=name,path,llm_summary&filter=size>1024`：

1. 路由校验 task_id 与 filter 安全性（`ExportRoutes.cpp:64-79`），定位 files.db 并只读打开（`:82-92`）。
2. 组装 config：filter 进 whereClause，fields 按逗号切分去空白（`:94-107`）。
3. `exportToTOON(db, config)` → `queryFiles`（`TOONExporter.cpp:71-148`）：`SELECT 16 列 FROM files [WHERE ...] ORDER BY path`，逐行读出（NULL 归空串），组装记录数组。
4. 渲染（`:228-265`）：schema 行 `TOON.schema: name | path | llm_summary` → `# records[N]` → N 行转义后的数据。
5. 路由以附件形式返回（`ExportRoutes.cpp:114-117`）。

### 4.1 代码走读：escapeValue 的引号判定与转义（TOONExporter.cpp:21-65）

```cpp
std::string TOONExporter::escapeValue(const std::string& value) {
    if (value.empty()) {
        return "\"\"";
    }

    // Check if value needs quoting (contains delimiter, quotes, or newlines)
    bool needsQuoting = false;
    for (char c : value) {
        if (c == '|' || c == '"' || c == '\n' || c == '\r' || c == ',') {
            needsQuoting = true;
            break;
        }
    }

    if (!needsQuoting) {
        // Check for leading/trailing whitespace
        if (!value.empty() && (std::isspace(value.front()) || std::isspace(value.back()))) {
            needsQuoting = true;
        }
    }

    if (!needsQuoting) {
        return value;
    }

    // Escape internal quotes by doubling them
    std::string escaped;
    escaped.reserve(value.size() + 10);
    escaped += '"';

    for (char c : value) {
        if (c == '"') {
            escaped += "\"\"";
        } else if (c == '\n') {
            escaped += "\\n";
        } else if (c == '\r') {
            escaped += "\\r";
        } else {
            escaped += c;
        }
    }

    escaped += '"';
    return escaped;
}
```

逐块解释：三段结构是"判需不需要 → 不需要原样返回 → 需要则包壳转义"。**空值特判成 `"\"\""`（一对引号）而不是空串**——这保证空字段在行内占据一列（`a |  | b` 中间的空仍是可数列），消费方按分隔符切分不会错位。第一轮字符扫描检查五个危险字符：`|` 是列分隔符本身、`"` 是引语法的开始、`\n`/`\r` 会把一行撕成多行、`,` 为 CSV 复用预留（TOON 不需要但保守无害）；第二轮补查首尾空白——` | ` 分隔符自带空格，前导/尾随空白会与分隔符的空格混淆。转义规则是"**双写引号、字面化换行**"：`"`→`""` 与 CSV 惯例一致，`\n`→字面两字符 `\n` 让整行保持物理单行——多行 LLM 描述因此不会破坏 TOON 的"一行一记录"不变量。`reserve(size+10)` 是小优化，避免逐字符 push 的重复扩容。**反引号、tab、Unicode 等不在危险表里**——tab 会不会破坏某些按空白切分的消费方取决于解析器，当前约定下可接受。

### 4.2 代码走读：queryFiles 的 NULL 归一与排序（TOONExporter.cpp:71-98, 143-147）

```cpp
    std::string sql = R"(
        SELECT inode, name, path, size, extension, category, type,
               mtime, ctime, is_deleted, md5,
               llm_summary, llm_description, llm_keywords,
               llm_analyzed_at, llm_model_used
        FROM files
    )";

    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sql += " ORDER BY path";
    // ... prepare 失败静默返回空（:93-98），逐行 16 列读入，文本列 NULL→""（:100-144）
```

逐块解释：SELECT 列序与 `FileRecordWithLLM` 成员序、`getFieldValue` 的映射三方对齐——**列序即契约**，增删列必须三处同步（结构体、本查询、getFieldValue 链）。whereClause 是原样拼接（`:88`）：不参数化是因为 WHERE 语法结构（AND/OR/比较符）无法用绑定参数表达，模块把消毒责任上交路由层的 `is_safe_filter_clause`。`ORDER BY path` 无 COLLATE 声明，排序稳定性依赖 SQLite 默认 BINARY collation——同一库重复导出的行序一致，diff 友好。文本列全部 `text ? text : ""` 归一：SQLite 的 NULL 转成 `reinterpret_cast<const char*>` 是 nullptr，不归一会 UB。整个结果集**一次性物化进 vector**（无游标流式），配合无 limit——内存峰值问题见第 6 节。

### 4.3 代码走读：exportToTOON 记录版的头部协议（TOONExporter.cpp:228-265）

```cpp
std::string TOONExporter::exportToTOON(const std::vector<FileRecordWithLLM>& records,
                                        const TOONExportConfig& config) {
    std::ostringstream oss;

    // Determine fields to export
    std::vector<std::string> fields = config.fields;
    if (fields.empty()) {
        // Default: export commonly useful fields for LLM
        fields = {"name", "path", "size", "category",
                  "llm_summary", "llm_description", "llm_keywords"};
    }

    const std::string& delimiter = config.delimiter;

    // Write schema header
    if (config.includeSchema) {
        oss << "TOON.schema: ";
        bool first = true;
        for (const auto& field : fields) {
            if (!first) {
                oss << delimiter;
            }
            first = false;
            oss << field;
        }
        oss << "\n";
    }

    // Write record count (helps LLM understand data size)
    oss << "# records[" << records.size() << "]\n";

    // Write data rows
    for (const auto& record : records) {
        oss << formatRecord(record, fields, delimiter) << "\n";
    }

    return oss.str();
}
```

逐块解释：输出协议三层——schema 行（`TOON.schema: ` 前缀 + 字段名按分隔符连接，消费方靠它对列，关掉它就要求双方带外约定列序）、计数行（`# records[n]` 让 LLM 在读数据前建立规模预期，也让人眼抽查行数）、数据行（每行 formatRecord + `\n`）。默认 7 字段的选择本身是个 prompt 工程决策：全是"LLM 用得上"的列（名称/路径/大小/类别 + 三个 LLM 产物），把 inode/时间戳/md5 这类机器字段裁掉省 token——注释 "Default: export commonly useful fields for LLM" 说得很直白；要全量得显式传 `getAllFieldNames()`。逐行 `oss << ... << "\n"` 而非 join 整串，流式追加对几十万行也可接受（ostringstream 会整体驻留内存，见第 6 节的内存注意）。`config.delimiter` 以 const 引用取用——schema 行与数据行共用同一分隔符字符串，保证两层的切分语法一致。

### 4.4 代码走读：formatRecord 与 getFieldValue 的字段映射链（TOONExporter.cpp:154-215）

```cpp
std::string TOONExporter::getFieldValue(const FileRecordWithLLM& record,
                                        const std::string& field) const {
    if (field == "inode") return std::to_string(record.inode);
    if (field == "name") return record.name;
    if (field == "path") return record.path;
    if (field == "size") return std::to_string(record.size);
    if (field == "extension") return record.extension;
    if (field == "category") return record.category;
    if (field == "type") return record.type;
    if (field == "mtime") return std::to_string(record.mtime);
    if (field == "ctime") return std::to_string(record.ctime);
    if (field == "is_deleted") return std::to_string(record.isDeleted);
    if (field == "md5") return record.md5;
    if (field == "llm_summary") return record.llm_summary;
    // ... llm_description/llm_keywords/llm_analyzed_at/llm_model_used 同构
    return "";
}

std::string TOONExporter::formatRecord(const FileRecordWithLLM& record,
                                       const std::vector<std::string>& fields,
                                       const std::string& delimiter) const {
    std::string line;
    for (size_t i = 0; i < fields.size(); ++i) {
        if (i > 0) line += delimiter;
        line += escapeValue(getFieldValue(record, fields[i]));
    }
    return line;
}
```

逐块解释（骨架，全链见 `:154-215`）：字段分发是**16 个 if 的平铺链**而非 switch/map——字段名是 string，switch 不适用，map 需要静态初始化；平铺的平均代价是 8 次字符串比较（前缀字段更快），每行每字段一次，几十万行 × 7 字段 × 8 比较 = 千万级 string::==，是渲染的 CPU 大头之一但远低于 SQL 读库。两个已知语义点：(1) **未知名静默空串**——fields 里拼错名（"lmm_summary"）不报错，输出里是一对引号的空列，消费方对列时才发现；路由层有 getAllFieldNames 校验挡住 HTTP 入口，但直接调用方没有这层防护；(2) `size`/`inode`/时间戳用 to_string——int64 直接十进制化，与 SQLite 里存的 INTEGER 文本形态一致，无损。formatRecord 的拼接顺序"取值→转义→加分隔符"保证**转义后的值（可能含引号与转义序列）不参与分隔符判定**——分隔符永远是干净的三字符 ` | `。

### 4.5 代码走读：路由侧的字段校验与附件返回（ExportRoutes.cpp:64-117）

```cpp
    // Parse fields parameter (optional)
    std::vector<std::string> fields;
    if (req.url_params.get("fields")) {
        std::string fieldsStr = req.url_params.get("fields");
        // split by comma, trim
        ...
    }

    // Validate field names
    auto validFields = TOONExporter::getAllFieldNames();
    for (const auto& f : fields) {
        if (std::find(validFields.begin(), validFields.end(), f) == validFields.end()) {
            return RouteHelpers::errorResponse(400, "Invalid field name: " + f);
        }
    }

    TOONExporter exporter;
    std::string toon_content = exporter.exportToTOON(db, config);
    // ... 附件返回 text/toon（:114-117）
```

逐块解释（骨架）：HTTP 入口为本模块补上两道防线——**字段白名单**（getAllFieldNames 的 16 名单逐一 find，未知名 400 带名字返回，调用方因此永远送不进 getFieldValue 的静默空串分支）与 **filter 消毒**（is_safe_filter_clause，第 3 节）。fields 为空时走 7 字段默认集，与"all"语义的偏差对 HTTP 用户不可见（无参默认就是精选）。附件返回的 Content-Disposition 让浏览器下载而非渲染，.toon 扩展名即由此而来。注意 db 在此之前以 SQLITE_OPEN_READONLY 打开（:85）——导出与在跑任务并发安全（WAL 读不阻塞写）。

## 5. 与其他模块的协作

- **FileClassifier（间接上游）**：files 表的 category 与 scene 列由分类器写入；llm_* 列由 LLM 分析服务回写（`SQL/file_classifier_sql.h:85-94` 的 UPDATE 语句族）。导出质量直接取决于这些列的填充率。
- **ExportRoutes / RouteHelpers**：提供 task_id→库路径映射、CORS、错误 JSON；只读打开避免与正在跑的任务抢写锁。
- **SQLiteHelper.is_safe_filter_clause**：whereClause 的安全闸门（见第 3 节）。
- **前端/LLM 工作流**：Content-Type `text/toon` 是自定义 MIME，前端按文本处理；LLM 侧把导出内容贴进提示词即为本格式的设计场景。
- 出错时行为：db 为空或 prepare 失败返回空记录集（`:75-97`），导出结果只有头两行、无数据行——不会抛异常。
- 表契约：只读 files.db 主表 files 的 16 列（11 元数据 + 5 llm_*）；**不读** scene_* 三列、24 张分表与 events 表。

## 6. 注意事项与已知问题

- **无行数上限**：`queryFiles` 没有分页/limit，几十万文件的库会生成巨大字符串（内存峰值 = 全部记录）。大库导出应配合 filter 或在路由层加 limit。
- **quoteStrings 配置项是摆设**：`escapeValue` 自行判断是否需要引号（`:27-44`），并不读这个开关——配置里设 false 不会改变输出。
- **列分隔符与 escapeValue 的 `,` 判断**：转义把逗号也视为需引号的字符（`:29`），这是为 CSV 复用预留的保守行为，TOON 本身并不需要；副作用是含逗号的描述总带引号。
- 表名硬编码 `files`：只能导出 files.db 主表，不能导出分类分表或 events 表。需要事件 TOON 时应新建 `queryXxx` + 对应记录结构，复用 `formatRecord`/`escapeValue`。
- `llm_analyzed_at` 输出为 Unix 秒，消费方展示时需自行格式化。
- **"empty = all" 注释与实现不符**：`TOONExporter.h:19` 注释说 fields 空则导出全部，实现取 7 字段精选集（`:233-238`）——依赖注释写调用方会拿错字段集，以实现为准。
- scene_type/scene_priority/scene_relevant 三列不在 16 列内：场景标注数据当前无法通过 TOON 导出，需要时要加列 + getFieldValue 分支 + getAllFieldNames。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_toon_exporter.cpp`（`tests/CMakeLists.txt:802-812`，测试名 `TOONExporterTests`），覆盖转义、字段裁剪、schema 头。
- 手工验证：`curl 'localhost:8080/api/forensics/export/toon?task_id=<id>&fields=name,size,category'`，检查首行 schema 与 `# records[n]`、行数与 `sqlite3 <files.db> 'SELECT COUNT(*) FROM files'` 一致。
- 扩展方向：(1) 行数上限/分页参数——`queryFiles` 加 LIMIT 与 `getAllFieldNames` 旁的默认字段集文档；(2) 导出 events 表——复制 queryFiles 模式建 `EventRecordWithLLM` 与字段映射，渲染管线直接复用；(3) 让 quoteStrings 真正生效或从配置中删除，避免误导。

## 8. 方法全清单

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `exportToTOON(db, config={})` | cpp:67-69（委托） | 查库+渲染一步 | ExportRoutes.cpp:110 |
| `exportToTOON(records, config)` | cpp:228-265 | 纯记录渲染 | 上一重载/测试 |
| `queryFiles(db, whereClause="")`（静态） | cpp:71-148 | 16 列查询 NULL 归一 | db 版导出 |
| `escapeValue(value)`（静态） | cpp:21-65 | TOON 转义 | formatRecord/测试 |
| `getAllFieldNames()`（静态） | cpp:192-207 | 16 字段白名单 | 路由校验 |
| `formatRecord(record, fields, delimiter)`（私有） | cpp:213-224 | 单行拼接 | 记录版导出 |
| `getFieldValue(record, field)`（私有） | cpp:154-210 | 字段分发（未知名 ""） | formatRecord |
| 构造/析构（默认） | h:62-63 | 无状态 | — |

## 9. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| ExportRoutes（唯一 HTTP 入口） | 上游 | /api/forensics/export/toon（:14, 55-124） | text/toon 附件 |
| files.db 主表 | 输入 | 16 列只读 SELECT（ORDER BY path） | FileRecordWithLLM vector |
| FileClassifier（数据上游） | 间接 | category/scene 列写入方 | — |
| LLMAnalysisService（数据上游） | 间接 | llm_* 五列 UPDATE（storeDescription） | — |
| SQLiteHelper.is_safe_filter_clause | 平行 | whereClause 闸门（ExportRoutes.cpp:72-79） | bool |
| RouteHelpers | 平行 | 错误 JSON/CORS | — |
| 同文件其他导出器（events/json、events/csv、visualization 三路由） | 平行 | 不复用本模块（events 走 SQLiteHelper 自家 JSON/CSV 拼装） | 值得注意的平行实现 |

## 10. 配置影响表

本模块无 .env/CLI 配置（纯函数式）；运行期自由度全部在 TOONExportConfig 五字段（其中 delimiter/quoteStrings 两个未生效或高危，见第 6 节）。路由参数：task_id（必填）、fields（逗号白名单）、filter（经消毒的 WHERE 片段）。

## 11. 性能与并发细节

- **内存峰值 = 全量记录 + 全量输出**：queryFiles 物化 vector（每记录约 300 字节 + 字符串堆）后 ostringstream 再拼等量文本——几十万行库的导出内存翻倍。分批/limit 是唯一缓解（未实现，第 6 节）。
- **CPU 三段**：SQL 读库（IO 密集，ORDER BY path 走 idx_files_path）、getFieldValue 链（平均 8 次串比较/字段）、escapeValue（单遍扫描+条件拷贝）。比例大约 6:3:1，读库主导。
- **无锁单线程**：整个导出在 HTTP handler 线程内完成；只读连接不与写方竞争（WAL）。并发导出同一库安全但各自吃内存。
- **token 收益实测口径**：7 字段默认集下，TOON 相对等价 JSON 的节省主要来自省去字段名重复与引号括号——记录数越多节省率越高（schema 头固定开销摊薄）；llm_description 为空时收益最明显。无内置基准，验证方法见第 7 节的手工命令对比字符数。


**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
