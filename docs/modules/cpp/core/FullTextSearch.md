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

## 5. 与其他模块的协作

- **ConfigManager**：四个搜索参数的消费点（`ConfigManager.cpp:151-154`）——缓存容量、内容截断、摘要长度、默认 limit。
- **PathManager/SearchRoutes**：`FTS_ALLOWED_ROOT` 安全校验以 PathManager 的 data 目录为默认根（`SearchRoutes.cpp:17-35`），越界请求被 4xx 拒绝并提示设置该变量（`:159`）。
- **TextExtractor ↔ 摘要回退**：索引时与查询时的文件内容抽取走同一实现，保证 token 一致性。
- **http_agent**：分布式部署里索引构建在节点本地完成（`image_indexer.cpp`），产物由 `index_uploader.cpp` 回传，服务端只做查询——带宽友好。
- 出错时行为：Xapian 异常全部捕获打 stderr 后吞掉（构造函数除外，它会重抛，`FullTextSearch.cpp:30-33`）； searcher 打不开库时 `isValid()` 为 false、search 返回空数组——路由层据此报错。

## 6. 注意事项与已知问题

- **内容缓存是进程级静态**且跨 Indexer/Searcher 实例共享（`FullTextSearch.h:87-88`）：索引后立即查询能拿到摘要；但服务重启后缓存空，摘要退化为现读文件，被索引后又删除的文件摘要变为占位串。
- **data 的 JSON 是手拼的**（`FullTextSearch.cpp:131-136`）：路径含引号/反斜杠会产生非法 JSON，查询侧的字符串截取（`:309-347`）也会随之取错。Windows 风格路径（含 `\`）尤其危险。修复应换成 nlohmann 序列化。
- 查询侧 QueryParser 固定 english 词干器（`:285`），索引侧可 `setStemmerLanguage` 改语言——两侧不一致会导致中文等其他语言检索行为混乱；当前系统主要面向英文内容，暂无问题。
- `XapianIndexer` 每次构造都 `DB_CREATE_OR_OPEN`，两个进程同时索引同一库会锁冲突（Xapian 单写者）；http_agent 的"节点本地索引"模式正是为绕开它。
- 大文件没有截断上限传入索引（`TextExtractor::extract(path)` 的无限制重载，`AnalysisOrchestrator.cpp:655` 用的是它），超大日志会全量入索引拖慢构建——可用 `extract(path, maxBytes)` 重载改善。
- strings 兜底对 PDF/Office 只能抽碎片，评估"内容检索覆盖率"时不要把它算作完整支持。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_fulltext_search_gtest.cpp`（`tests/CMakeLists.txt:597`，测试名 `FullTextSearchGTests`）。
- 手工验证：`./forensic_analyzer --index <某目录> --search "test AND path:src"`，观察 CLI 打分的 `[NN%]` 行；再用 `curl 'localhost:8080/api/search/fulltext?q=test&index=<index_path>'` 对比 HTTP 行为。
- 扩展方向：(1) data 换正规 JSON 序列化并加版本字段（改 `FullTextSearch.cpp:111-154` 与 `:309-347` 两处）；(2) 富文档抽取——在 TextExtractor 增加对 markitdown 代理的可选调用，注意失败回退 strings；(3) 排序支持——value 0/1 已存 size/mtime，给 search 加 `set_sort_by_value` 参数即可暴露给前端。

**最后更新**: 2026-08-23（解释式重写）
