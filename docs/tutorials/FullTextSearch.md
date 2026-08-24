# 教程：全文搜索实战（Xapian）

> 目标读者：需要在大量提取文件里做内容检索的分析师。前置：一个已完成分析的任务（或至少跑过提取）。约 25 分钟。命令端口以 run.sh 的 8666 为例。

## 场景设定

你有一个完成的任务，`extracted_files/` 里躺着数千个文件。时间线告诉你"18:42 左右有批量写入"，但你想按**内容**找证据：谁提到过某个手机号、哪个脚本里有反弹 shell、哪些文档含"合同"二字。目录翻找不现实——这正是 Xapian 索引的用武之地。

## 1. 理解索引模型（一分钟）

TraceLens 的 [FullTextSearch](../modules/cpp/core/FullTextSearch.md) 对每个文件：抽取文本（[TextExtractor](../modules/cpp/core/FullTextSearch.md)，100+ 文本/代码扩展名白名单）→ 建倒排索引（英文词干化 `STEM_SOME`、原文存 path/ext 元数据）→ 文档以 `Q<绝对路径>` 为唯一键（**重复索引同一文件是替换而非重复**——幂等）。索引落在独立目录（默认 `search_index_xapian`），不碰任务库。

**关键决策**：索引针对"提取出来的文件"（有真实内容可读），而不是镜像内路径——所以索引前先想清楚索 引哪个集合（见第 2 步的策略）。

## 2. 选择索引集合：先 filter 后 index

大任务直接全量索引又慢又贵。推荐两段式：

1. **定位候选**：先用文件页/SQL 把目标文件集缩小（按 category、scene_relevant、时间窗、目录）。例如只要文档类：
```bash
sqlite3 data/tasks/<id>/files.db "SELECT path FROM files WHERE category IN ('DOCUMENTS','DATABASES') AND scene_relevant=1" > /tmp/candidates.txt
```
2. **提取并索引候选**：用提取端点（`POST /api/forensics/extract`，mode=extension/name）把候选拉到 `extracted_files/`，再建索引。

如果目标就是"全部提取过的内容"，跳过筛选直接第 3 步。

## 3. 建索引

HTTP（推荐，走任务提取目录的固定语义）：
```bash
curl -X POST http://localhost:8666/api/search/index \
  -H 'Content-Type: application/json' \
  -d '{"index": "search_index_xapian", "path": "/abs/path/data/tasks/<id>/extracted_files"}'
```
注意：`path` 必须在 `FTS_ALLOWED_ROOT` 围栏内（默认数据目录）——越界返回 403，这是防任意目录扫描的安全设计。索引是同步完成的（无作业模型），大集合会阻塞该请求一会儿。`recursive` 参数存在但实现恒为递归遍历（no-op，见 SearchRoutes 文档标注）。

CLI 等价：`./build/forensic_analyzer --index <目录>`。

## 4. 查询语法完全指南

解析器（FullTextSearch.cpp:284-297）启用：**布尔**（AND/OR/NOT，大小写敏感的关键字）、**通配符**、**短语**（引号包裹）、词干化 STEM_SOME、两个命名前缀：

| 想查 | 写法 |
|------|------|
| 任一词命中 | `ransomware OR 勒索` |
| 同时包含 | `invoice AND payment` |
| 排除 | `contract NOT draft` |
| 短语精确 | `"reverse shell"` |
| 通配 | `passwd*`、`*.pem`（token 内） |
| 按路径过滤 | `password path:etc`（命中"password"且路径含 etc） |
| 按扩展名过滤 | `secret ext:log` |
| 组合 | `"反弹 shell" path:tmp NOT test` |

查询：
```bash
curl "http://localhost:8666/api/search/fulltext?q=password%20path:etc&index=search_index_xapian&limit=50&offset=0"
```
注意 `index` 参数在 Swagger 里标 optional，但 handler 缺失即 400——带上它。CLI 等价：`--search "..."`。

**读懂结果**：每条含 path、摘要片段（SEARCH_SNIPPET_LENGTH）、相关度。命中数为该查询的 mset 总数（分页用 offset/limit）。

## 5. 与 LLM 分析配合（搜索定位 → 重分析）

搜索是"便宜的大海捞针"，LLM 是"贵的精读"。组合拳：
1. 搜索 `path:wechat OR 微信` 等关键词定位候选文件；
2. 在 /files 页对命中文件触发重分析（`POST /api/llm/analyze/file`，带案情提示词）——只对有用的文件花 token；
3. 重分析结果落回 files.db 的 llm_* 列，再用 SQL 食谱 [第 3 条](../reference/SqlCookbook.md)交叉复核。

## 排坑清单

- **403 on index/search**：路径不在 FTS_ALLOWED_ROOT 内（查 .env 或用数据目录内路径）。
- **索引后查不到**：确认查的不是"扩展名白名单外"的二进制（TextExtractor 只认文本类）；确认 index 名一致。
- **dev 前端跨服务**：`/api/search/*` 走 C++（vite 兜底前缀），别与 8090 的端点混淆。
- **索引目录会增长**：删除任务不会自动删索引（键是绝对路径，任务删了键还在）——低峰期重建索引目录可回收。
- **性能**：首次索引是 IO/CPU 大头；增量（同 key 替换）便宜。SEARCH_MAX_CACHE_SIZE/DEFAULT_LIMIT 影响查询侧。

## 延伸阅读

- [FullTextSearch 模块文档](../modules/cpp/core/FullTextSearch.md)——索引器/查询器实现与 TextExtractor 白名单
- [SearchRoutes](../modules/cpp/network/routes/SearchRoutes.md)——端点语义与围栏实现
- [FilterProfiles 教程](FilterProfiles.md)——第 2 步筛选用到的画像系统

---

**最后更新**: 2026-08-24（新建：全文搜索教程）
