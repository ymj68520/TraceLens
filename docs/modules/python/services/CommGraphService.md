# CommGraphService（python_service/httpserver/services/comm_graph/ 子包：service/datasets/identity/sources/timeline/models）

> **一句话**：跨源统一通讯图谱——把一份检材的 android.db 与任意若干微信/QQ 导入的 graph.db 读侧联合投影成"谁和谁、通过什么方式、何时联系"的 UnifiedGraph；身份归一只认强键（归一手机号/wxid/QQ uin），同名只产候选不合并；每条边带来源 dataset 与 record_refs 可回指原始行，全程只读、绝不合并源库。

## 1. 为什么有这个模块

系统的三份通讯数据从不相遇：任务写 `android.db`，微信/QQ 导入各写自己的 `graph.db`（comm_graph/__init__.py:1-8）。关系图谱页（`/api/wechat/graph`）一次只吃一份，而"机主与 X 的全部联系渠道"是跨源问题。本包用一次读取回答它，并立下三条设计边界（__init__.py:10-14）：**只读**；**身份合并仅限强键**——"a same-name pair is never merged automatically"，姓名只产生候选链接；**每条边可回溯**——edge 保留来源 dataset 与 record 引用。包结构五件套：datasets.py（本请求该读哪些源）、sources.py（各源行读取器）、identity.py（身份归一与边累积）、service.py（聚合与查询入口）、timeline.py（统一时间线与单边钻取）。

## 2. 在系统中的位置

- **谁调用它**：routes/comm_graph.py（`/api/comm` 四端点，见 [../httpserver/routes/CommGraph.md](../httpserver/routes/CommGraph.md)）；每请求构造新实例（comm_graph.py:55-57 `CommGraphService(manager.cpp_backend)`）——服务无内部状态，状态全在请求参数里。
- **它调用谁**：CppBackendService（`resolve` 里 `get_task` 验身份，service.py:64-68）；各导入服务的 `ensure_graph_db`（datasets.py:31-45，库缺失/陈旧自愈）；sqlite3（全部 `mode=ro` + `query_only`，service.py:76-82）。
- **它被谁依赖**：无下游服务；前端 CommGraphPanel/CommTimelinePanel 是最终消费者。

## 3. 核心接口清单

| 方法（真实签名） | 语义 | 失败行为 |
|---|---|---|
| `async resolve(task_id, *, wechat_imports=(), qq_imports=())` | get_task 验身份 → resolve_datasets 返回 (refs, unavailable)（service.py:64-68） | 任务不存在 raise LookupError；坏导入 id raise DatasetResolutionError |
| `build_graph(refs, filters, *, unavailable=None) -> UnifiedGraph`（:71-73） | 读全部源 → 身份归一 → 边聚合 → 社区 → 裁剪 | 单库 DatabaseError 被吞进 unavailable（_guarded，:85-89） |
| `build_timeline(refs, *, start_time, end_time, kinds, datasets, limit)`（timeline.py） | 同源的统一时间线聚合（call/sms/im_private/im_group/im_artifact） | 同上 |
| `edge_detail(refs, *, source, target, relation)`（timeline.py） | 单边的支撑记录钻取 | 目标不存在返回空结果 |
| `resolve_datasets(task, *, wechat_imports, qq_imports)`（datasets.py） | 任务 android.db + 显式点名的导入；**不猜**（datasets.py:3-9 docstring："Guessing would risk pulling in an unrelated account"） | 坏 id → DatasetResolutionError；ensure 失败 → 该导入进 unavailable |

## 4. 核心机制走读

### 4.1 身份归一（identity.py）：强键与候选

models.py 提供 `normalize_phone / normalize_uin / normalize_wxid` 三个纯函数（service.py:19-24 导入），identity.py 的 `Matcher` 用它们做**同键合并**；姓名匹配只进 `name_candidates`（coverage 计数之一，service.py:50-55）——同名人出现的次数是显式暴露给分析师的"这里可能没合并"信号，而不是静默决策。`EdgeAccumulator` 累积每边的 weight/duration/media_count，并维护 `MAX_RECORD_REFS_PER_EDGE` 上限（service.py:47 `MAX_REF_LIST`）：超出只加 `truncated_refs` 计数，图不因热门边膨胀。

### 4.2 并集折叠（service.py:108-139 `_merge_edges`）

`include_union=True` 时，跨数据集的同端点对同关系边折叠成一条：weight/时长/媒体数累加、record_refs 逐条并入、时间跨度取并集；方向冲突有明确升级规则——一边 unknown 就采另一边，两边都非 unknown 且不同则升 `mixed`（:132-136）；来源不同的边 dataset 置 `union`（:137-138）。这条折叠只发生在**读投影**层，源库不动。

### 4.3 读侧容错（service.py:76-89）

每个数据集独立连接（`mode=ro`、`text_factory` 对坏字节 replace 解码），每个 reader 被 `_guarded` 包住——一份损坏的 graph.db 只贡献空读 + unavailable 记录，其余数据集照常出图。coverage 计数（`_COVERAGE_KEYS`，:50-55）随每个响应返回，图的"读了多少、丢了多少"完全可审计。

### 4.4 时间窗的 fail-closed（service.py:92-105 `_in_range`）

一旦请求带时间窗，**无日期记录一律出局**（"Undated records cannot be proven to fall inside a requested range"，:88-90）；半边日期用另一端补齐做区间重叠。取证取向：宁缺勿错。

## 5. 数据流（读什么、写什么）

**读**：android.db（read_call_logs/read_sms/read_contacts/read_mobile_artifacts/read_owner，sources.py）+ 导入 graph.db（read_wechat_*）——全部只读连接，`MAX_ROWS_PER_SOURCE` 限制单源行数（超限进 truncated_sources 计数）。**写**：无——本包不建缓存不落盘，每次请求全量重读（数据集规模经 max_nodes/max_edges/max_rows 三层上限控制）。

## 6. 边界与已知状态

- **导入不自动跟随任务**：datasets.py:3-9——导入与任务还没有链接关系，调用方必须点名；这是防"把别人的微信账号合进本案"的显式决策。
- **同名不合并**：identity 只认强键；`name_candidates`/`ambiguous_people` 类计数是给分析师的核对线索。
- **单库损坏是 200 不是 500**：unavailable 列表 + coverage 是降级的显式表达。
- **无身份持久化**：归一结果不落盘，跨请求不复用——一致性由归一函数的纯函数性保证，而非缓存。
- **record_refs 截断可观察**：`truncated_refs` 与 `MAX_RECORD_REFS_PER_EDGE`（identity.py）让"边证据太多"可见而非静默。

## 7. 如何验证

- 单测：`python_service/tests/unit/` 下 comm_graph 测试（resolve/identity 归一/merge 折叠/timeline/edge_detail）。
- 前端契约：`web/src/services/commGraphService.js`、`components/knowledge-graph/CommGraphPanel.test.jsx`、`components/timeline/CommTimelinePanel.test.jsx`。
- 活体验证：一个含 android.db 的任务 + 一份微信导入 → `/api/comm/graph` 核对 coverage.merged_identities（强键合并数）与 name_candidates（同名候选数）应同时非零；对 union 边钻取核对 record_refs 含多 dataset。

相关阅读：[../httpserver/routes/CommGraph.md](../httpserver/routes/CommGraph.md)（路由面）、[IMImportServices.md](IMImportServices.md)（graph.db 的产生方）、[WeChatGraphService.md](WeChatGraphService.md)（单源图谱指标计算）。

## 8. 二轮深化 A：DatasetRef 的三种 kind 与解析次序

datasets.py 的解析按"先任务后导入"进行：任务侧经 `resolve_android_db` 定位 android.db（kind=task_android）；导入侧 `_import_ref`（:27-45）先 12-hex 强校验，再调对应平台 `ensure_graph_db`（微信/QQ 各自的服务单例），失败不抛而是**进 unavailable**——只有一个例外：id 语法不对直接 DatasetResolutionError（422），因为那是调用方 bug 而不是数据问题。`_import_root`（:18-21）按 kind 选 `wechat_imports`/`qq_imports` 目录。这个"语法错误即拒、数据问题即降级"的分界与路由层的错误映射（DatasetResolutionError→422、unavailable→200 附列表）一一对应，是整条链路统一 fail-fast/fail-soft 分界的最小样本。

**最后更新**: 2026-11-10（新建：统一通讯图谱服务文档）
