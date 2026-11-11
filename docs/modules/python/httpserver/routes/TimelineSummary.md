# TimelineSummary 路由（python_service/httpserver/routes/timeline_summary.py，三个子 router 分别挂到 /api/associations、/api/qq、/api/wechat）

> **一句话**：附加式时间规律统计面——对既有数据源（任务的 events 库 / 微信库、QQ/微信导入库）做"版本化确定性统计 + 精确钻取回查"，本文件只定义路由与来源解析，不做抽取、不建图、不改任何库；统计本体在 services/timeline_summary.py。

## 1. 这组路由承担什么职责（为什么存在）

文件第一行写明定位（timeline_summary.py:1）："Additive read surfaces mounted by the existing association/IM routers"——它不是一个独立前缀，而是**被既有 router include 的附件**：

- `task_router`（:19）由 associations.py:24-28 include，暴露 `GET /api/associations/timeline-summary[/records]`，服务任务的 events 库（C++ 产出的 `<task>_events.db`）与任务微信库（`resolve_android_db`）；
- `qq_router`（:21）由 qq_forensics.py:28-32 include，暴露 `GET /api/qq/forensics/imports/{import_id}/timeline-summary[/records]`；
- `wechat_router`（:20）由 wechat_forensics.py:28-32 include，同形于微信导入。

它存在的原因：时间线页与 IM 面板需要"这个账号/这份检材的活跃规律"（24 小时分布、按天变化、工作日×小时热力图），且结论必须**可复现、可回查**——所以统计是纯确定性的（无 LLM），每次返回带 `source_version` + `context_id`，钻取端点必须携带原统计的版本与标识才能回查明细（:80-88）。这是"统计结论→证据明细"的闭环契约，防止"看图说话"式的不可验证结论。

## 2. 典型调用方（前端哪个页面/组件）

- `/timeline` 页：`components/timeline/TimelineSummaryPanel`（Timeline.jsx:17 导入，:793 挂载，endpoint=`/api/associations/timeline-summary`，scopeParams 带 `task_id`+`source=events`+可选时间窗/event_type，:574-580）。
- `/im-forensics` 页：同一 Panel 组件按平台/导入挂载（IMForensics.jsx:321-323），ready 态的导入用 `qq/wechat` 导入端点、图谱覆写态用 associations 端点。
- service 层极薄：`web/src/services/timelineSummaryService.js:3-4`（`getTimelineSummary(endpoint, params)` 与 `/records` 变体）——endpoint 由调用方注入，Panel 组件对三来源零特判。

## 3. 核心数据结构

**TimelineSource**（services/timeline_sources.py:39-43，frozen dataclass；`identity` 属性 :45-52）：`path` + `kind` + `scope_id` 三元组。`kind` 决定身份与时间单位：

| kind | 来源 | record_origin | 时间戳单位 |
|---|---|---|---|
| `events` | 任务 `output_events_db` | derived_event_table | 秒 |
| `wechat_task` | 任务 android 库（resolve_android_db） | parsed_message_table | 毫秒 |
| `qq_import` | 导入目录 `nt_msg.db` | decrypted_import_table | 秒 |
| `qq_legacy` | 老版 QQ 导入归一化 `graph.db` | normalized_import_table | 毫秒 |
| `wechat_import` | 导入目录 `EnMicroMsg.db` | decrypted_import_table | 毫秒 |

（边界注记：`wechat_import` 的 EnMicroMsg `createTime` 原始值疑似秒制，但代码按毫秒换算——timeline_sources.py:51-52 声明毫秒、timeline_summary.py:65-66 按 /1000 处理，以代码现状为准。）

**SummaryFilters**（services/timeline_summary.py:21-42）：timezone（IANA 校验）、start/end_time、start/end_date、event_type、event_source、talker、direction（all/sent/received/unknown/system）。**RecordSelection**（:45-53）：hour/weekday/day/direction/quality/record_ref + offset/limit——钻取端点用它把"某个柱子"还原成原始记录列表。

响应（summarize 返回，services/timeline_summary.py:230-240）：`context`（含 `source_version`、`context_id`、`scanned_content_hash`、`statistics_version="timeline-summary:v1"`、去重规则与 coverage 全套）、`warnings`（固定警示语数组，如"收到消息不证明账号主人当时操作"）、`summary`（一句中文叙述）、`hours/weekdays/heatmap/daily/repeated_hours/communication/time_bases/event_types/event_sources`；records 变体返回 `{context, selection, records, total, page_truncated}`（:193-196）。

## 4. 端点语义分组（散文）

6 个端点（2 组 × 3 来源），全部 GET、全部只读：

- **任务域**（task_router）：`GET /api/associations/timeline-summary`（:104-106）与 `GET .../records`（:109-111）——query 必须含 `task_id`（≤256）与 `source`（`events`|`wechat`，默认 events，:26-27）；`wx_/qq_<import_id>` 形态的 task_id 在 source=wechat 时**先于 C++ 查询**被截胡转发到导入目录（:28-30）。
- **导入域**（wechat_router / qq_router）：`GET /api/{wechat,qq}/forensics/imports/{import_id}/timeline-summary[/records]`（:114-131）——import_id 由路径给出，query 只允许 filters。
- 两条路径共用 `read_summary`（:66-101）：先做**严格参数白名单**（未知或重复参数直接 422，:74-75；任务域额外放行 `task_id`/`source`，钻取域额外放行 `_SELECTORS|source_version|summary_id|record_direction`，:69-73），再解析来源、调 `summarize`。

## 5. 数据流（读什么库、写什么）

**写**：无——全部端点以只读连接打开源库（timeline_sources.py 的 revision/semantic_revision 也是只读探针）。

**来源解析**（本文件的核心逻辑）：

```python
# timeline_summary.py:46-63（节选）
def import_source(platform: str, import_id: str):
    if not re.fullmatch(r"[0-9a-f]{12}", import_id):
        raise ValueError("导入标识无效")
    root = get_data_root() / f"{platform}_imports" / import_id
    if root.is_symlink():
        raise SourceUnavailable("导入目录不可用")
    if platform == "qq":
        # 老版QQ（pre-NTQQ）导入没有 nt_msg.db：时间规律直接读归一化
        # graph.db 的 wechat_messages 投影（与微信任务库同形状）。
        ...
        if legacy:
            return TimelineSource(root / "graph.db", "qq_legacy", import_id)
        return TimelineSource(root / "nt_msg.db", "qq_import", import_id)
    return TimelineSource(root / "EnMicroMsg.db", f"{platform}_import", import_id)
```

要点：symlink 一票否决（fail-closed，:50-51）；`meta.json` 里 `format == "legacy_qq4"` 判老版 QQ（:55-61）——这就是 **qq_legacy 时间源**：老版 4.x 导入没有解密产物 nt_msg.db，统计直接读归一化 graph.db 的 `wechat_messages` 投影，与微信任务库同一形状。任务域（:25-43）则先经 C++ `get_task` 验明正身，events 取 `output_events_db`、wechat 走 `resolve_android_db`，都拿不到路径 → `SourceUnavailable`。

**版本闭环**：summarize 在单事务内先取 `source_version`（db+wal+journal 的文件修订 bundle，timeline_sources.py:57-68），统计完再取一次，不一致即 `SourceChanged`（services/timeline_summary.py:163 的 `semantic_revision` 对比）——"统计期间来源被写"绝不出半新半旧的结果。

## 6. 边界与已知状态（错误码语义）

`read_summary` 的异常映射表（:91-101）：

| 异常 | 状态码 | detail |
|---|---|---|
| `SourceChanged` | **409** | 具体原因（"统计期间来源发生变化，请重试"或"回查条件或统计版本与原总结不一致"） |
| `SourceUnavailable` / `FileNotFoundError` | 404 | 固定"对应来源不可用或未完成解析" |
| `ValidationError` | 422 | 固定"筛选条件无效：请检查时区、日期范围及分页参数" |
| `ValueError`（参数白名单/坏 import_id/坏回查键） | 422 | 原文 |
| `sqlite3.Error` / `OSError` | **503** | 固定"来源暂不可读取，请稍后重试"（日志只记异常类名，不落内容，:99-101） |

钻取（records=true）的回查契约：`source_version` 与 `summary_id` 都必须是无 64 位十六进制，否则 422"来源回查必须携带原统计的来源版本和统计标识"（:80-83）；服务端用 `expected_version`/`expected_summary` 复验 context_id，不符抛 `SourceChanged`——**老统计 + 已变化的库 = 409 而不是错数**。

## 7. 如何验证

- 路由与服务层：`python_service/tests/unit/` 下 timeline 相关测试（filters 校验、qq_legacy 来源分派、SourceChanged 闭环）。
- 前端契约：`web/src/components/timeline/TimelineSummaryPanel.test.jsx`；页面挂载见 Timeline.jsx:793 与 IMForensics.jsx:321-323。
- 活体验证：`/timeline` 页右栏时间规律面板随 URL 时间窗联动；对一份老版 QQ（4.x）导入访问 `/api/qq/forensics/imports/<id>/timeline-summary`，context.scope.kind 应为 `qq_legacy`、record_origin 为 normalized_import_table。

相关阅读：[IMForensics.md](IMForensics.md)（导入域上游）、[Associations.md](Associations.md)（task_router 的挂载宿主）、services 侧 [TimelineSummaryService.md](../../services/TimelineSummaryService.md)（统计实现与去重规则）。

## 8. 二轮深化 A：严格参数白名单的工程含义

```python
# timeline_summary.py:74-75
if set(params) - allowed or len(params) != len(request.query_params.multi_items()):
    raise ValueError("存在未知或重复的筛选参数")
```

两个比较各有含义：第一半（未知键集合差）拒绝拼错字段——比如把 `end_time` 写成 `endTime` 不会静默当默认值；第二半（multi_items 计数）拒绝**同键重复**——`?hour=1&hour=2` 不取第一个而是整体 422。对"统计结论可复现"的目标来说这是必要条件：context_id 是对 filters.model_dump 的确定性摘要，任何未被声明字段的隐式输入（重复键取值顺序等）都会让"同一 URL 必得同一 context_id"失效。`allowed` 的三段拼装（:69-73）也按域收紧：任务域多两个定位键、钻取域多回查键，导入域只有 filters——同一实现服务三来源但不互开放字段。

**最后更新**: 2026-11-10（新建：时间规律统计路由文档，含 qq_legacy 时间源）
