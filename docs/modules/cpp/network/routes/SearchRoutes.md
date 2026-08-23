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

注意 `index` 指向的是**已存在的 Xapian 索引目录**（通常由 3.2 的端点或 CLI 建好）——传错路径会得到打开失败的 500，而非 404。

### 3.2 POST /api/search/index（:136-214）

请求体 `{source_path, index_path, recursive=true}`。流程：

1. 双路径必填 400（:146-152）；
2. **路径围栏校验**（:154-164）：source_path 与 index_path 都必须在允许根内，否则 403 并附 `allowed_root` 与提示设置 `FTS_ALLOWED_ROOT` 的 hint；
3. 源不存在 400；
4. 目录则递归遍历，每个常规文件经 `TextExtractor` 抽文本（空内容跳过），`XapianIndexer.addDocument` 入索引，最后 commit（:177-196）；单文件则建一条；
5. 返回 `{success, source_path, index_path, indexed_count}`。

### 3.3 路径围栏：为什么搜索端点要做安全校验

`fts_path_within_allowed_root`（:17-35）把允许根默认定为 PathManager 的 data 目录，可用环境变量 `FTS_ALLOWED_ROOT` 放宽。没有这道围栏，`source_path=/etc` 之类的请求会让索引器读取并**通过搜索结果泄漏任意主机文件内容**——这正是它存在的原因。实现用 weakly_canonical + lexically_relative 判断，防 `..` 与软链逃逸。

## 4. 数据从哪来

不经过 SQLiteHelper、不查任务库：数据源是 `source_path` 目录下的文件内容（TextExtractor 支持的格式），持久形态是 `index_path` 处的 **Xapian 索引目录**（倒排索引 + 位置信息），查询时只读索引不碰原文件。若希望检索"镜像内文件"，先走 /api/forensics/extract 提取，再对提取目录建索引。

## 5. 常见错误与边界

- **400 q required / index required**：两个 GET 必填参数，最常见的前端失误；
- **403 must be under the allowed root**：索引目标在围栏外——按响应里的 allowed_root 调整路径或设置 FTS_ALLOWED_ROOT；
- **500 打不开索引**：index 路径不是有效 Xapian 索引（从未建过/建到别的路径）；
- **建索引是同步阻塞请求**：大目录会长时间占住一个 Crow worker，无进度回报（没有作业模型）；
- **indexed_count 偏小是正常的**：TextExtractor 抽不出文本的文件（纯二进制）被跳过；
- **索引不会自动更新**：源目录变化后需重新调用 index 端点。

## 6. 如何验证与扩展

- 冒烟：`POST /api/search/index {"source_path":"<data 下某目录>","index_path":"<data>/idx1"}` → `GET /api/search/fulltext?q=error&index=<data>/idx1` 应返回带 snippet 的命中；
- 安全验证：`source_path=/etc/passwd` 应 403 且响应含 allowed_root；
- 扩展方向：把建索引改造成异步作业（复用 extract 的作业模式）以支撑大目录；或把"任务完成→对提取目录自动建索引"接入 TaskManager 尾部——那需要在 TaskManagerAnalysis.cpp 收尾处调用 XapianIndexer，而非在本路由内做。

**最后更新**: 2026-08-23（解释式重写）
