# FullTextSearch（src/core/FullTextSearch/）

> **一句话**：基于 Xapian 的全文检索组件——`XapianIndexer` 把文件内容（路径/扩展名/正文）索引进倒排库，`XapianSearcher` 支持布尔/通配/字段前缀查询并生成高亮摘要，`TextExtractor` 负责"任意文件 → 文本"的抽取（100+ 扩展名白名单 + 二进制 strings 兜底）。

## 1. 为什么有这个模块

取证调查里有一类问题和时间线正交：**按内容找文件**。"镜像里哪些文件提到了某个账号、某个域名、某段代码？"SQL 的 LIKE 做不到分词、打分和排序，几十万文件的逐个 grep 又慢且无法做前缀/短语组合。Xapian 是成熟的倒排索引引擎，本模块把它包装成两个小类：索引器与查询器，加上查询语法的预设（布尔、通配、`path:`/`ext:` 字段前缀），让 CLI 与 HTTP 路由用同一套能力。

文本抽取是隐藏的另一半工作量。取证镜像里的文件什么类型都有：纯文本、源码、配置、还有大量二进制。直接把字节塞进索引会产生垃圾 token；只收白名单又漏掉"藏在二进制里的字符串证据"（无扩展名的木马样本里的 URL）。`TextExtractor` 的策略是双轨：约 130 个文本扩展名（`TextExtractor.cpp:14-71`）走原文读取，其余走 `strings` 式抽取（最小长度 4 的可打印序列，`:91`）。

安全边界是第三个设计点。HTTP 接口接受用户指定的索引目录，如果放任不管，攻击者可以让服务索引 `/etc` 并搜索出任意主机文件内容。因此路由层用 `FTS_ALLOWED_ROOT`（默认 PathManager 的 data 目录）把可索引路径圈死（`SearchRoutes.cpp:17-35`）。

## 2. 在系统中的位置

三个使用面：

- **CLI 子命令**：`AnalysisOrchestrator::runFullTextSearch`（`src/AnalysisOrchestrator.cpp:634-688`）——`--index <dir>` 遍历目录建索引（`:650-667`，每 100 个文件报一次进度），`--search <kw>` 查询（`:670-685`）；索引库默认 `search_index_xapian`，可用 `--db-dir` 改位置（`:635-639`）。
- **HTTP 路由**：`/api/search/index`（POST，建索引）与 `/api/search/fulltext`（GET，查询，q + index + limit/offset 参数）——`src/network/HTTPServer/routes/SearchRoutes.cpp:37-66` 注册，`handle_fulltext_search` 在 `:106-107` 直接构造 `XapianSearcher`。
- **http_agent（分布式部署的节点代理）**：在节点上完成索引构建后上传（`src/http_agent/index_uploader.cpp`、`image_indexer.cpp`）。

模块内部依赖 ConfigManager（缓存与截断参数）与 Xapian 库；TextExtractor 被索引侧和摘要生成侧共用。

```
目录/文件 ──TextExtractor.extract──> 文本 ──XapianIndexer.addDocument──> search_index_xapian/
                                                                    (倒排库, Q<path> 去重)
查询串(布尔/通配/path:/ext:) ──XapianSearcher.search──> MSet ──> {path,score,snippet,...}
```

## 3. 核心概念与设计

**索引侧的字段布局**（`FullTextSearch.cpp:111-154` 的 `addDocument`）：路径文本用前缀 `P` 索引（`:119`，供 `path:` 查询）；正文无前缀入主索引（`:120`）；扩展名既是布尔项 `E.pdf` 又是自由文本（`:123-128`，供 `ext:.pdf` 过滤）；文档 data 存一段手拼 JSON（path/size/extension/mtime，`:131-136`）；value 0/1 存 sortable_serialise 的 size/mtime 供将来排序（`:139-140`）。

**用 `Q<path>` 幂等去重**是索引器的关键决定：每个文档以路径生成唯一布尔项 `idterm`，写库用 `replace_document(idterm, doc)`（`:142-146`）——同一文件重复索引是**替换**而不是追加，这让"重建索引"可以增量跑而不会膨胀。

**进程内内容缓存**：`contentCache_` 是**静态**成员（`FullTextSearch.h:87`），按 path 存截断到 `SEARCH_MAX_CONTENT_LENGTH`（默认 50000）的内容（`:62-88`），容量对齐 `SEARCH_MAX_CACHE_SIZE`（默认 1000），淘汰用最旧 indexTime（`:66-79`）。它存在的唯一理由是**摘要生成**：Xapian 文档 data 里没存正文，命中后要展示上下文片段，从缓存拿比重新读文件快一个量级。`XapianSearcher` 通过 friend 声明访问它（`FullTextSearch.h:93`）。缓存 miss 时回退到 `TextExtractor::extract` 现读文件（`:232-244`），仍失败给出占位串。

**查询语法预设**（`search`，`:278-304`）：QueryParser 挂 `path→P`、`ext→E` 前缀（`:291-292`），打开 WILDCARD/PHRASE/BOOLEAN 旗标（`:294-298`），STEM_SOME 策略平衡召回与精确。命中后逐条从 data JSON 里**手工截取** path/size/extension（`:309-347`）——老格式（data 就是路径字符串）有回退分支（`:344-347`）。分数用 `get_percent()`。

**摘要生成**（`generateSnippet`，`:188-247`）：取查询 terms，在缓存内容里找首个命中位置，向两侧各扩 `snippetLength_/2`（默认 150，可由 `SEARCH_SNIPPET_LENGTH` 配置经路由传入），加 `...` 省略号，最后 `highlightTerms` 把命中词包成 `**词**`（`:249-276`，Markdown 风格，前端可直接渲染）。

**TextExtractor 的白名单**（`TextExtractor.cpp:14-71`）：覆盖纯文本、配置、Web、几十种编程语言、Shell、文档标记、SQL/GraphQL、构建/IaC、VCS 元数据等约 130 个扩展名；`isTextFile` 大小写归一比较（`:99-103`）。注意 `.pdf`、`.docx` 等**不在**名单——它们会被 strings 兜底抽出乱码碎片而非真正文本；富文档转换实际由 Python 服务的 markitdown 承担（见 AnalysisOrchestrator.md 的 --dump-text 一节），二者是互补关系。

### 3.1 核心数据结构（FullTextSearch.h:16-40）

```cpp
struct FileMetadata {
    std::string path;
    std::string extension;
    int64_t size = 0;
    int64_t mtime = 0;  // Modification time (Unix timestamp)
};

struct SearchResult {
    std::string path;
    double score;
    std::string snippet;
    int64_t fileSize = 0;
    std::string extension;
};

struct ContentCacheEntry {
    std::string content;
    int64_t indexTime;
};
```

逐个解释：`FileMetadata` 是索引输入的增强维度——两参版 `addDocument` 会现场 stat 补齐（size/mtime），四参版由调用方给全；extension 带 `.dot` 前缀且索引时会转小写。`SearchResult` 是查询输出——`score` 是 Xapian 的 `get_percent()`（0-100 的相对相关度，不是绝对分），`snippet` 是高亮后的上下文片段，fileSize/extension 从 data JSON 反解。`ContentCacheEntry` 的 `indexTime` 是**入缓存时刻**的 Unix 秒（不是文件 mtime），淘汰时扫全表找最小值——O(n) 淘汰换零额外内存，n≤1000 时合理。缓存放两个静态成员里（`contentCache_`/`cacheMutex_`，`:87-88`），被 Indexer 写、Searcher 读（friend 授权，`:93`）。

### 3.2 核心接口清单

| 签名（FullTextSearch.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `explicit XapianIndexer(dbPath)` | DB_CREATE_OR_OPEN 打开倒排库，挂 TermGenerator/english 词干器 | AnalysisOrchestrator.cpp:644、SearchRoutes 索路由 | Xapian 异常**重抛**（构造失败应立即可见） |
| `void addDocument(filePath, content)` | 简化版：现场 stat 补元数据后转调四参版 | CLI 遍历循环 | 内部 catch Xapian::Error 打 stderr 吞掉 |
| `void addDocument(filePath, content, metadata)` | 完整版：字段布局 + `Q<path>` replace_document + 入缓存 | 上一重载、http_agent | 同上 |
| `void commit()` | 提交挂起更改 | 每批/收尾 | db_ 为空时静默跳过 |
| `void setStemmerLanguage(language)` | 换词干语言 | 暂无生产调用方 | 非法语言打警告回退 english |
| `size_t getDocumentCount() const` | 库内文档数 | 进度统计 | db_ 为空返回 0 |
| `explicit XapianSearcher(dbPath)` | 只读打开 | SearchRoutes.cpp:106-107 | 异常被吞，isValid()==false |
| `vector<SearchResult> search(queryStr, limit=10, offset=0)` | 解析查询→MSet→逐条组装（含摘要） | CLI --search、HTTP 查询 | 库无效/查询异常返回空数组 |
| `void setSnippetLength(length)` | 调摘要窗长（默认 150） | SearchRoutes 读 `SEARCH_SNIPPET_LENGTH` 后注入 | 无 |
| `bool isValid() const` / `size_t getTotalDocuments() const` | 诊断 | 路由层报错判断 | 无 |
| `TextExtractor::extract(path, maxBytes=0)` | 文件→文本（白名单或 strings 兜底） | 索引与摘要两侧 | 读失败返回空串 |

## 4. 工作流程走读

CLI 建索引（`AnalysisOrchestrator.cpp:650-667`）：

1. 构造 `XapianIndexer(indexDbPath)`——`DB_CREATE_OR_OPEN` 打开/创建倒排库，TermGenerator 挂库、设 english 词干器、开拼写纠正旗标（`FullTextSearch.cpp:22-34`）。
2. `recursive_directory_iterator` 遍历源目录，`TextExtractor::extract` 取文本，非空则 `addDocument`（`AnalysisOrchestrator.cpp:653-661`）。
3. `addDocument` 内部完成第 3 节的字段布局、`replace_document` 幂等写入、内容入缓存（`FullTextSearch.cpp:114-153`）。
4. 循环外 `commit()`（`:156-160`；析构函数也会兜底 commit，`:36-44`）。

HTTP 查询（`SearchRoutes.cpp:68-130`）：

1. 参数校验：q 与 index 必填，limit 默认 50（`:72-104`）。
2. `XapianSearcher(index_path)` 打开只读 Database；`search(q, limit, offset)` 走 QueryParser → Enquire → `get_mset(offset, limit)` 分页（`FullTextSearch.cpp:283-305`）。
3. 每条命中解析 data、算 percent、生成高亮摘要（`:306-355`），组装 JSON 响应。

### 4.1 代码走读：addDocument 的字段布局与 Q<path> 幂等（FullTextSearch.cpp:111-154）

```cpp
void XapianIndexer::addDocument(const std::string& filePath, const std::string& content, const FileMetadata& metadata) {
    if (!db_) return;

    try {
        Xapian::Document doc;
        termGenerator_.set_document(doc);

        // Index specific fields with prefixes
        termGenerator_.index_text(filePath, 1, "P");  // Prefix 'P' for path
        termGenerator_.index_text(content);           // General content (no prefix)

        // Index extension as a boolean term for filtering
        if (!metadata.extension.empty()) {
            std::string ext = metadata.extension;
            std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
            doc.add_boolean_term("E" + ext);  // E prefix for extension
            termGenerator_.index_text(ext, 1, "E");
        }

        // Store document data as JSON for retrieval
        std::ostringstream dataStream;
        dataStream << "{\"path\":\"" << filePath << "\""
                   << ",\"size\":" << metadata.size
                   << ",\"extension\":\"" << metadata.extension << "\""
                   << ",\"mtime\":" << metadata.mtime << "}";
        doc.set_data(dataStream.str());

        // Store values for sorting and display
        doc.add_value(0, Xapian::sortable_serialise(static_cast<double>(metadata.size)));
        doc.add_value(1, Xapian::sortable_serialise(static_cast<double>(metadata.mtime)));

        // Add unique ID based on path to avoid duplicates
        std::string idterm = "Q" + filePath;
        doc.add_boolean_term(idterm);

        db_->replace_document(idterm, doc);

        // Cache content for snippet generation
        cacheContent(filePath, content);

    } catch (const Xapian::Error& e) {
        std::cerr << "Xapian Indexer AddDocument Error: " << e.get_msg() << std::endl;
    }
}
```

逐块解释：一个 Xapian 文档在这里被拆成**四个存储区**，各司其职——terms 区（`index_text` 生成，可检索：`P` 前缀管路径分词、无前缀管正文）、boolean terms 区（精确过滤：`E.pdf` 与 `Q<path>`）、data 区（整段取回：手拼 JSON 给查询侧解析）、values 区（`sortable_serialise` 编码的数值，专供按 size/mtime 排序——把 double 编成字节序可比较的串是 Xapian 的惯用法）。`Q` 前缀 + `replace_document(idterm, doc)` 的组合实现了**以路径为主键的 upsert**：重跑索引时同路径文档整篇替换，词频与位置索引同步重建，库不膨胀——这是"增量重建"语义的根基；换主键（如内容哈希）需要同时改 idterm 生成与查询侧。data 的手拼 JSON 是已知坑（见第 6 节）：字段顺序恰为 path/size/extension/mtime，查询侧的截取逻辑与之耦合。Xapian 异常在这里被吞——单文档失败不中断批量索引，代价是静默缺文档。

### 4.2 代码走读：cacheContent 的全表淘汰（FullTextSearch.cpp:62-88）

```cpp
void XapianIndexer::cacheContent(const std::string& path, const std::string& content) {
    std::lock_guard<std::mutex> lock(cacheMutex_);

    // Enforce cache size limit
    if (contentCache_.size() >= static_cast<size_t>(forensics::ConfigManager::instance().getSearchMaxCacheSize())) {
        // Simple eviction: remove oldest entry
        auto oldest = contentCache_.begin();
        int64_t oldestTime = std::numeric_limits<int64_t>::max();
        for (auto it = contentCache_.begin(); it != contentCache_.end(); ++it) {
            if (it->second.indexTime < oldestTime) {
                oldestTime = it->second.indexTime;
                oldest = it;
            }
        }
        if (oldest != contentCache_.end()) {
            contentCache_.erase(oldest);
        }
    }

    // Cache truncated content
    ContentCacheEntry entry;
    entry.content = content.substr(0, static_cast<size_t>(forensics::ConfigManager::instance().getSearchMaxContentLength()));
    entry.indexTime = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    contentCache_[path] = std::move(entry);
}
```

逐块解释：淘汰是**先删后插**的容量守恒——容量满时先线性扫出 indexTime 最小的条目删掉，再插入新条目，保证 size 永不超过上限加一瞬。线性扫淘汰（O(n)）在 n≤1000（`SEARCH_MAX_CACHE_SIZE` 默认）时可接受；若调大配置应换成 LRU 链或时间堆。截断发生在**入缓存时**（`substr(0, SEARCH_MAX_CONTENT_LENGTH)`，默认 50000 字节）而非读取时——内存占用有了硬上界（1000 × 50KB ≈ 50MB），代价是超长文件的摘要只能出自前 50KB：命中词若只出现在文件尾部，摘要退化（generateSnippet 找不到命中会走占位分支）。`contentCache_[path] = ...` 对已存在的 path 是覆盖且刷新 indexTime——重复索引同文件不会重复占容量。两个容量参数都从 ConfigManager **每次现读**，运行期改 .env 不生效（ConfigManager 无 reload）但至少与配置源单点一致。

### 4.3 代码走读：search 的查询解析与 data 手工反解（FullTextSearch.cpp:283-347）

```cpp
        Xapian::Enquire enquire(*db_);
        Xapian::QueryParser parser;
        Xapian::Stem stemmer("english");
        parser.set_stemmer(stemmer);
        parser.set_database(*db_);
        parser.set_stemming_strategy(Xapian::QueryParser::STEM_SOME);

        // Enable prefix matching
        parser.add_prefix("path", "P");
        parser.add_prefix("ext", "E");

        Xapian::Query query = parser.parse_query(queryStr,
            Xapian::QueryParser::FLAG_DEFAULT |
            Xapian::QueryParser::FLAG_WILDCARD |
            Xapian::QueryParser::FLAG_PHRASE |
            Xapian::QueryParser::FLAG_BOOLEAN);

        std::cout << "Parsed Query: " << query.get_description() << std::endl;

        enquire.set_query(query);

        Xapian::MSet mset = enquire.get_mset(offset, limit);

        for (Xapian::MSetIterator i = mset.begin(); i != mset.end(); ++i) {
            SearchResult res;

            // Parse stored data (JSON format)
            std::string data = i.get_document().get_data();

            // Simple JSON parsing for path
            size_t pathStart = data.find("\"path\":\"");
            if (pathStart != std::string::npos) {
                pathStart += 8;
                size_t pathEnd = data.find("\"", pathStart);
                if (pathEnd != std::string::npos) {
                    res.path = data.substr(pathStart, pathEnd - pathStart);
                }
            }
            // ... size/extension 同款截取与老格式回退见 :323-347
```

逐块解释：查询能力由三处配置合成——`add_prefix("path","P")/("ext","E")` 把用户语法 `path:src` 映射到索引侧前缀（两侧的字符串约定必须一致，改任何一边都断）；四个 FLAG 打开布尔（AND/OR/NOT）、通配（`tes*`）、短语（`"exact phrase"`）；`STEM_SOME` 只对未加前缀的自由词做词干化，路径/扩展名字段保持精确——否则 `path:src` 会被词干折成别的形式。`set_database` 让 `db*:` 之类的智能语法可用。分页由 `get_mset(offset, limit)` 在引擎内完成（不是取全量再切片），深翻页成本可控。**data 反解是全函数最脆的部分**：三段 find/substr 假设 JSON 无转义——路径含 `"` 或 `\` 时 pathEnd 找错位置，截出的 path 残缺且静默（`res.path` 默认空触发老格式回退 `res.path = data`，把整段 JSON 当路径用）；size 的 `std::stoll` 有 try/catch 兜底但字符串截取没有。`Parsed Query` 的 cout 是调试残留，生产上每次查询打一行 stdout。

### 4.4 代码走读：TextExtractor::extract 的分派与两轨实现（TextExtractor.cpp:73-103）

```cpp
std::string TextExtractor::extract(const std::string& path, size_t maxBytes) {
    if (!fs::exists(path)) {
        return "";
    }

    try {
        std::string ext = fs::path(path).extension().string();
        std::transform(ext.begin(), ext.end(), ext.begin(),
                       [](unsigned char c){ return std::tolower(c); });

        if (isTextFile(ext)) {
            return extractFromTextFile(path, maxBytes);
        } else {
            // Fallback to strings extraction for binary or unknown files
            return extractStrings(path, 4, maxBytes);
        }
    } catch (const std::exception& e) {
        std::cerr << "TextExtractor::extract error for " << path << ": " << e.what() << std::endl;
        return "";
    }
}
```

逐块解释：三个判定细节值得记录。(1) **无扩展名文件 ext 为空串**——isTextFile("") 查 set miss，走 strings 兜底，这正是"无扩展名木马样本里的 URL 也能被检索"的实现点（第 1 节承诺的双轨在此落地）。(2) tolower 的 lambda 参数显式转 `unsigned char`——避免 char 为负时 ::tolower 的 UB（对比 ConfigManager.cpp:79 直接传 char 的写法，这里更严谨）。(3) `fs::exists` 先行意味着**每次调用都有一次 stat**：CLI 索引循环里每个文件 stat 一次 + 打开读一次；summary 回退路径同样。extractFromTextFile 是"读整个文件（或 maxBytes 截断）原文返回"；extractStrings 逐字节扫可打印序列、长度 ≥4 才收——二进制文件的 token 密度远低于真文本，索引体积可控。两轨输出都不做编码转换：GBK/UTF-16 文本按字节入索引，中文检索因此基本不可用（Xapian 默认按 Unicode 字流处理单字节输入）——已知能力边界。

### 4.5 代码走读：highlightTerms 的 Markdown 包裹（FullTextSearch.cpp:249-276）

```cpp
std::string XapianSearcher::highlightTerms(const std::string& text,
                                           const std::string::size_type snippetLen,
                                           const std::vector<std::string>& terms) {
    std::string result = text;
    std::string::size_type pos = 0;
    for (const auto& term : terms) {
        pos = 0;
        while ((pos = result.find(term, pos)) != std::string::npos) {
            result.insert(pos, "**");
            result.insert(pos + term.size() + 2, "**");
            pos += term.size() + 4;
        }
    }
    return result;
}
```

逐块解释（骨架，完整实现见 `:249-276`）：对每个查询 term 在摘要文本里**子串替换式**加 `**` 包裹——大小写敏感的 `find` 意味着查询词 "Test" 不会高亮文本里的 "test"（词干化后的 term 与原文形态差异也不会高亮）；insert 两次移动后续偏移，`pos += term.size() + 4` 跳过刚包好的词避免 `**` 里再嵌 `**`。已知边界：term 恰是另一个 term 的子串时先处理者把后者切碎；term 含 `*` 字符时包裹与 Markdown 语义冲突。输出直接进 HTTP JSON 响应，前端按 Markdown 渲染即得高亮——这是"服务端做高亮"的取舍（客户端做则查询侧要传 terms 数组）。

## 5. 与其他模块的协作

- **ConfigManager**：四个搜索参数的消费点（`ConfigManager.cpp:151-154`）——`SEARCH_MAX_CACHE_SIZE`（缓存容量，默认 1000）、`SEARCH_MAX_CONTENT_LENGTH`（内容截断，默认 50000）、`SEARCH_SNIPPET_LENGTH`（摘要长度，默认 150）、`SEARCH_DEFAULT_LIMIT`（默认 limit，默认 10）。
- **PathManager/SearchRoutes**：`FTS_ALLOWED_ROOT` 安全校验以 PathManager 的 data 目录为默认根（`SearchRoutes.cpp:17-35`），越界请求被 4xx 拒绝并提示设置该变量（`:159`）。
- **TextExtractor ↔ 摘要回退**：索引时与查询时的文件内容抽取走同一实现，保证 token 一致性。
- **http_agent**：分布式部署里索引构建在节点本地完成（`image_indexer.cpp`），产物由 `index_uploader.cpp` 回传，服务端只做查询——带宽友好。
- 出错时行为：Xapian 异常全部捕获打 stderr 后吞掉（构造函数除外，它会重抛，`FullTextSearch.cpp:30-33`）； searcher 打不开库时 `isValid()` 为 false、search 返回空数组——路由层据此报错。
- 存储契约：索引库是 Xapian 目录（默认 `search_index_xapian/`），不是 SQLite；文档 data 为四字段 JSON、value 0/1 为 size/mtime、`P`/`E`/`Q` 三组前缀 terms。

## 6. 注意事项与已知问题

- **内容缓存是进程级静态**且跨 Indexer/Searcher 实例共享（`FullTextSearch.h:87-88`）：索引后立即查询能拿到摘要；但服务重启后缓存空，摘要退化为现读文件，被索引后又删除的文件摘要变为占位串。
- **data 的 JSON 是手拼的**（`FullTextSearch.cpp:131-136`）：路径含引号/反斜杠会产生非法 JSON，查询侧的字符串截取（`:309-347`）也会随之取错。Windows 风格路径（含 `\`）尤其危险。修复应换成 nlohmann 序列化。
- 查询侧 QueryParser 固定 english 词干器（`:285`），索引侧可 `setStemmerLanguage` 改语言——两侧不一致会导致中文等其他语言检索行为混乱；当前系统主要面向英文内容，暂无问题。
- `XapianIndexer` 每次构造都 `DB_CREATE_OR_OPEN`，两个进程同时索引同一库会锁冲突（Xapian 单写者）；http_agent 的"节点本地索引"模式正是为绕开它。
- 大文件没有截断上限传入索引（`TextExtractor::extract(path)` 的无限制重载，`AnalysisOrchestrator.cpp:655` 用的是它），超大日志会全量入索引拖慢构建——可用 `extract(path, maxBytes)` 重载改善。
- strings 兜底对 PDF/Office 只能抽碎片，评估"内容检索覆盖率"时不要把它算作完整支持。
- 摘要窗口只有文件前 `SEARCH_MAX_CONTENT_LENGTH` 字节（截断发生在入缓存时），尾部命中词出不了上下文。
- search 内 `std::cout << "Parsed Query: ..."`（`:303`）是调试残留，高频查询会刷日志。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_fulltext_search_gtest.cpp`（`tests/CMakeLists.txt:597`，测试名 `FullTextSearchGTests`）。
- 手工验证：`./forensic_analyzer --index <某目录> --search "test AND path:src"`，观察 CLI 打分的 `[NN%]` 行；再用 `curl 'localhost:8080/api/search/fulltext?q=test&index=<index_path>'` 对比 HTTP 行为。
- 扩展方向：(1) data 换正规 JSON 序列化并加版本字段（改 `FullTextSearch.cpp:111-154` 与 `:309-347` 两处）；(2) 富文档抽取——在 TextExtractor 增加对 markitdown 代理的可选调用，注意失败回退 strings；(3) 排序支持——value 0/1 已存 size/mtime，给 search 加 `set_sort_by_value` 参数即可暴露给前端。

## 8. 方法全清单（含 TextExtractor）

**XapianIndexer**（FullTextSearch.h:47-91）：

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `XapianIndexer(dbPath)` | cpp:22-34 | DB_CREATE_OR_OPEN + TermGenerator + english 词干 + 拼写纠正 | CLI/SearchRoutes/http_agent |
| `addDocument(path, content)` | cpp:96-108 | stat 补元数据转四参版 | CLI 循环 |
| `addDocument(path, content, metadata)` | cpp:111-154 | 字段布局+upsert+入缓存 | 上一重载 |
| `commit()` | cpp:156-160 | 提交（析构兜底再 commit，:36-44） | 批尾 |
| `setStemmerLanguage(lang)` | cpp:46-55 | 换词干语言（未接线） | 无生产调用方 |
| `getDocumentCount()` | .h | 库内文档数 | 进度 |
| 私有 `cacheContent(path, content)` | cpp:62-88 | 全表淘汰缓存 | addDocument |
| 静态成员 `contentCache_/cacheMutex_` | .h:87-88 | 进程级共享 | 两类实例 |

**XapianSearcher**（h:95-143）：

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `XapianSearcher(dbPath)` | cpp:262-275 | 只读打开，异常吞 | SearchRoutes:106 |
| `search(query, limit=10, offset=0)` | cpp:278-355 | 解析+MSet+组装 | CLI/HTTP |
| `setSnippetLength(n)` | .h | 摘要窗长（默认 150） | SearchRoutes 注入 |
| `isValid()/getTotalDocuments()` | .h | 诊断 | 路由 |
| 私有 `generateSnippet(...)` | cpp:188-247 | 缓存/回退/占位三段 | search |
| 私有 `highlightTerms(...)` | cpp:249-276 | `**` 包裹 | generateSnippet |

**TextExtractor**（TextExtractor.h:26-70，全静态）：

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `extract(path)` / `extract(path, maxBytes)` | cpp:73-90 | 白名单/strings 分派 | 索引+摘要 |
| `isTextFile(ext)` | cpp:99-103 | 大小写归一 set 查询 | extract |
| `getSupportedExtensions()` | .h | 130+ 扩展名集合只读 | 路由展示 |
| `extractMetadata(path)` | cpp:105 起 | isText+扩展名判定（ExtractedMetadata） | http_agent |
| `extractFromTextFile(path, maxBytes=0)` | .h:67 | 原文读取 | extract |
| `extractStrings(path, minLength=4, maxBytes=0)` | .h:68 | strings 兜底 | extract |

## 9. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| AnalysisOrchestrator.runFullTextSearch | 上游 | 索引循环+查询（:650-685） | 目录路径 |
| SearchRoutes（HTTP） | 上游 | index/fulltext 两路由；FTS_ALLOWED_ROOT 圈禁 | JSON 请求/响应 |
| http_agent（image_indexer/index_uploader） | 上游 | 节点本地索引+回传 | Xapian 目录 |
| ConfigManager | 上游 | 四个 SEARCH_* 键（cpp:158,175 每次现读） | int |
| Xapian 库 | 下游 |WritableDatabase/Database/QueryParser/MSet | C++ API |
| TextExtractor | 内部 | extract 双轨 | string |
| Python markitdown | 互补 | 富文档转文本不归本模块（--dump-text 管线） | — |

## 10. 配置影响表

| 参数 | 默认 | 影响 | 未接线标注 |
|---|---|---|---|
| `SEARCH_MAX_CACHE_SIZE` | 1000 | 摘要缓存条目上限（FullTextSearch.cpp:158） | 不在 .env.example |
| `SEARCH_MAX_CONTENT_LENGTH` | 50000 | 入缓存截断=摘要可见窗口（:175） | 不在 .env.example |
| `SEARCH_SNIPPET_LENGTH` | 150 | 摘要窗长（SearchRoutes 读后 setSnippetLength 注入） | getter getSearchSnippetLength 无 C++ 调用方——**经路由间接接线** |
| `SEARCH_DEFAULT_LIMIT` | 10 | **未接线**：getter 无调用方（路由默认硬编码 50，SearchRoutes.cpp:72-104） | 缺省与代码实际默认不一致 |
| `FTS_ALLOWED_ROOT` | PathManager data 目录 | HTTP 可索引根白名单（SearchRoutes.cpp:17-35） | 不在 .env.example |
| `--db-dir`（CLI） | 空 | 索引目录前缀（Orchestrator:635-639） | |

## 11. 性能与并发细节

- **索引构建是 CPU+IO 双重热点**：每文件一次 stat + 全量读 + TextGenerator 分词 + Xapian B 树写。百万级小文件时 CLI 单线程顺序处理（Orchestrator:653-661 无并行）；commit 只在批尾一次（崩溃丢整批，见 AnalysisOrchestrator.md 4.6 节）。
- **strings 兜底的读放大**：二进制文件全量读入但只留 ≥4 字节可打印序列——一个 2 GB 的虚拟机磁盘文件会把 2 GB 读进内存再丢掉 99% 字节；maxBytes 重载（CLI 未用，第 6 节）是现成的刹车。
- **静态缓存的两面**：进程级共享让 Indexer→Searcher 零拷贝传递摘要素材（好），也意味着多任务并发索引共享同一 1000 条容量、互相逐出（坏）——HTTP 并发任务的摘要质量不可预期。锁只有 cacheMutex_ 一把，读写都走它（generateSnippet 取缓存时同样 lock_guard cacheMutex_，FullTextSearch.cpp:191-193）——并发面正确；friend 声明（h:93）只是访问授权不是绕锁通道。
- **Xapian 单写者**：同库并发写直接报错（DB_LOCKED），http_agent 分而治之；查询侧只读打开无限并发。
- **内存峰值**：单文件内容（extract 无限制重载时）+ 50MB 级缓存上界（1000×50KB）；深翻页的 MSet 在引擎内截取，不占应用内存。
- **可调参数影响**：SEARCH_MAX_CONTENT_LENGTH 调大提升尾部命中摘要质量但线性放大缓存内存；SEARCH_MAX_CACHE_SIZE 调大降低回退现读频率但淘汰 O(n) 变贵。


**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
