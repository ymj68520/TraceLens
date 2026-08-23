# SearchRoutes（src/network/HTTPServer/routes/SearchRoutes.cpp）

> **职责**：把 Xapian 全文搜索引擎暴露成两个端点——建索引（POST /api/search/index）与查索引（GET /api/search/fulltext），并对索引目录做路径围栏防任意文件读取。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

调查员经常需要"在证据文本里找关键词"：聊天记录、文档、配置里的某个手机号或域名。文件名/路径匹配（files 页）覆盖不了内容级检索，这组路由提供基于 Xapian 倒排索引的内容搜索：先对某目录建一次索引，之后查询毫秒级返回路径+相关度+上下文片段。

**重要定位**：它**不挂在任务流水线上**——索引对象是主机文件系统上的目录（比如已提取出来的证据文件），与 task_id/产出库无关，是独立的横向工具。

## 2. 典型调用方

- **/search 搜索页（Search.jsx）**：输入关键词 → GET /api/search/fulltext；索引进度/管理 → POST /api/search/index。
- 脚本化调查流程：先用文件提取路由把证据抽到某目录，再对其建索引，随后反复内容检索。

## 3. 端点分组与语义

### 3.1 GET /api/search/fulltext（SearchRoutes.cpp:68-134）

参数四个：`q`（查询词，必填）、`index`（索引路径，必填）、`limit`（默认 50）、`offset`（分页）。流程：两必填缺一即 400 → `XapianSearcher(index_path).search(query, limit, offset)` → 返回 `{query, results[{path, score, snippet}], count, limit, offset}`。异常统一 500 裸 `{"error":...}`。

```cpp
// SearchRoutes.cpp:106-126（查询主体）
XapianSearcher searcher(index_path);
auto results = searcher.search(query, limit, offset);

json response = {
    {"query", query},
    {"results", json::array()},
    {"count", results.size()},
    {"limit", limit},
    {"offset", offset}
};

for (const auto& result : results) {
    response["results"].push_back(json{
        {"path", result.path},
        {"score", result.score},
        {"snippet", result.snippet}
    });
}
```

响应结构里 `count` 等于本次返回条数（不是命中总数）——分页到底没有 has_more 信号，调用方只能靠"返回条数 < limit"判断可能翻完了。`snippet` 是 Xapian 生成的上下文片段（命中词高亮定位），这是全文搜索对调查员最有价值的输出：不用打开文件就能确认命中语境。查询词原文不做任何转义直接交给 Xapian 解析——Xapian 查询语法（如 `AND`/前缀过滤）对调用方可用，语法错误则由 Xapian 抛异常转 500。

注意 `index` 指向的是**已存在的 Xapian 索引目录**（通常由 3.2 的端点或 CLI 建好）——传错路径会得到打开失败的 500，而非 404。查询路径**不受 §3.3 围栏约束**（围栏只在建索引时校验 source/index 两参），这是围栏模型的一个边界：能读到的索引仍可能包含围栏外内容（若 FTS_ALLOWED_ROOT 曾被放宽后建过索引）。

### 3.2 POST /api/search/index（:136-214）

请求体 `{source_path, index_path, recursive=true}`。流程：

1. 双路径必填 400（:146-152）；
2. **路径围栏校验**（:154-164）：source_path 与 index_path 都必须在允许根内，否则 403 并附 `allowed_root` 与提示设置 `FTS_ALLOWED_ROOT` 的 hint；
3. 源不存在 400；
4. 目录则递归遍历，每个常规文件经 `TextExtractor` 抽文本（空内容跳过），`XapianIndexer.addDocument` 入索引，最后 commit（:177-196）；单文件则建一条；
5. 返回 `{success, source_path, index_path, indexed_count}`。

```cpp
// SearchRoutes.cpp:174-196（索引主体）
XapianIndexer indexer(index_path);
int indexed_count = 0;

if (std::filesystem::is_directory(source_path)) {
    // Index all files in directory
    for (const auto& entry : std::filesystem::recursive_directory_iterator(source_path)) {
        if (entry.is_regular_file()) {
            TextExtractor extractor;
            std::string content = extractor.extract(entry.path().string());
            if (!content.empty()) {
                indexer.addDocument(entry.path().string(), content);
                indexed_count++;
            }
        }
    }
    indexer.commit();
} else {
    TextExtractor extractor;
    std::string content = extractor.extract(source_path);
    indexer.addDocument(source_path, content);
    indexer.commit();
    indexed_count = 1;
}
```

三个实现细节：文档逐条 addDocument、**最后统一 commit**——中途异常（进程被杀/磁盘满）整批不入库，索引要么完整要么保持旧貌，不会出现半批脏数据；TextExtractor 抽不出文本的文件（纯二进制）被静默跳过，`indexed_count` 因此可能远小于目录文件数；`recursive` 参数虽然解析了（:144），**遍历却无条件用 recursive_directory_iterator**——传 `recursive=false` 一样递归全目录，参数当前是 no-op。

### 3.3 路径围栏：为什么搜索端点要做安全校验

```cpp
// SearchRoutes.cpp:14-35（含注释）
// Confine a user-supplied filesystem path to an allowed root so the indexer
// cannot read/return arbitrary files (e.g. /etc/passwd). The root defaults to
// PathManager's data dir; operators can widen it via FTS_ALLOWED_ROOT.
static bool fts_path_within_allowed_root(const std::string& p, std::string& allowed_out) {
    namespace fs = std::filesystem;
    fs::path allowed;
    if (const char* env = std::getenv("FTS_ALLOWED_ROOT"); env && *env) {
        allowed = fs::path(env);
    } else {
        allowed = PathManager::instance().getDataDir();
    }
    std::error_code ec;
    fs::path allowed_canon = fs::weakly_canonical(allowed, ec);
    if (ec) allowed_canon = fs::absolute(allowed);
    allowed_out = allowed_canon.string();

    ec.clear();
    fs::path cand = fs::weakly_canonical(fs::path(p), ec);
    if (ec) cand = fs::absolute(fs::path(p));
    fs::path rel = cand.lexically_relative(allowed_canon);
    return !rel.empty() && (*rel.begin()) != "..";
}
```

实现三步：确定允许根（环境变量 `FTS_ALLOWED_ROOT` 优先，否则 PathManager 的 data 目录）；把候选路径与允许根都 `weakly_canonical` 化——消解 `..` 与符号链接后再比较，堵住 `data/../etc/passwd` 与"软链指向围栏外"两条逃逸路径（weakly 而非 fully canonical 是为了容忍还不存在的 index_path）；`lexically_relative` 求相对路径，首个分量是 `..` 即在围栏外。没有这道围栏，`source_path=/etc` 之类的请求会让索引器读取并**通过搜索结果泄漏任意主机文件内容**——这正是它存在的原因。

拒绝时的响应形态（调用侧，SearchRoutes.cpp:154-164）：

```cpp
// SearchRoutes.cpp:154-164
std::string allowed_root;
if (!fts_path_within_allowed_root(source_path, allowed_root) ||
    !fts_path_within_allowed_root(index_path, allowed_root)) {
    json error = {{"error", "source_path/index_path must be under the allowed root"},
                  {"allowed_root", allowed_root},
                  {"hint", "set FTS_ALLOWED_ROOT to widen the permitted directory"}};
    res.code = 403;
    res.set_header("Content-Type", "application/json");
    res.write(error.dump());
    return res;
}
```

403 响应把 `allowed_root` 的**实际解析值**带回去并附 hint——运维不用猜默认根在哪、下一步设哪个环境变量；source 与 index 两个路径共用一次校验调用的输出（第二次调用只是重复写同一个 allowed_out），错误信息里不区分具体是哪个越界。

## 4. 数据从哪来

不经过 SQLiteHelper、不查任务库：数据源是 `source_path` 目录下的文件内容（TextExtractor 支持的格式），持久形态是 `index_path` 处的 **Xapian 索引目录**（倒排索引 + 位置信息），查询时只读索引不碰原文件。若希望检索"镜像内文件"，先走 /api/forensics/extract 提取，再对提取目录建索引。与任务体系的唯一交点是共享 PathManager 的 data 目录默认值。

## 5. 常见错误与边界

- **400 q required / index required**：两个 GET 必填参数，最常见的前端失误；
- **403 must be under the allowed root**：索引目标在围栏外——按响应里的 allowed_root 调整路径或设置 FTS_ALLOWED_ROOT；
- **500 打不开索引**：index 路径不是有效 Xapian 索引（从未建过/建到别的路径）；
- **建索引是同步阻塞请求**：大目录会长时间占住一个 Crow worker，无进度回报（没有作业模型）；
- **indexed_count 偏小是正常的**：TextExtractor 抽不出文本的文件（纯二进制）被跳过；
- **索引不会自动更新**：源目录变化后需重新调用 index 端点；
- **recursive 参数无效**：解析了但遍历恒为递归（§3.2）；
- **count 不是总命中数**：只是本次页大小，深翻页只能迭代探测。

## 6. 如何验证与扩展

- 冒烟：`POST /api/search/index {"source_path":"<data 下某目录>","index_path":"<data>/idx1"}` → `GET /api/search/fulltext?q=error&index=<data>/idx1` 应返回带 snippet 的命中；
- 安全验证：`source_path=/etc/passwd` 应 403 且响应含 allowed_root；`source_path=<data>/../etc` 同样 403（canonical 化后逃逸被识破）；
- 扩展方向：把建索引改造成异步作业（复用 extract 的作业模式）以支撑大目录；或把"任务完成→对提取目录自动建索引"接入 TaskManager 尾部——那需要在 TaskManagerAnalysis.cpp 收尾处调用 XapianIndexer，而非在本路由内做。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
