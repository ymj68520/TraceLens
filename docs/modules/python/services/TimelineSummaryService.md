# TimelineSummaryService（python_service/httpserver/services/timeline_summary.py + timeline_sources.py）

> **一句话**：版本化确定性时间规律统计——对既有来源库（events 派生表 / 微信消息表 / QQ 归一化或解密表）做单事务扫描，产出 24 小时分布、工作日热力图、按天变化与方向计数，context（来源版本 + 去重规则 + 覆盖度）整体进 context_id 摘要；钻取端点凭 `source_version + summary_id` 精确回查"某个柱子背后的原始记录"，来源中途被写即 409 绝不出半新半旧结果。

## 1. 为什么有这个模块

时间线页与 IM 面板需要"这个账号/检材的活跃规律"，但取证场景下统计数字必须**可辩护**：结论要能回答"统计了哪些记录、丢了哪些、依据哪个版本的库、能否钻回原始行"。timeline_summary.py:1 的模块定位（"Versioned deterministic statistics over an existing source, with exact drilldown"）就是这份契约：无 LLM、无随机性，同一库状态 + 同一 filters 必得同一结果；每次统计带 `source_version`（库文件修订束）与 `context_id`（统计语境的 SHA-256），钻取必须两证齐全（timeline_summary 路由 :80-88）。固定警示语数组（services :212-229）把"统计边界"写进每个响应——"收到消息不证明账号主人当时操作""文件时间戳不等于人为操作"——这是给法官看的免责与严谨声明，不是装饰。

## 2. 在系统中的位置

- **谁调用它**：routes/timeline_summary.py 的 `read_summary`（`summarize(source, filters, **options)`，:89）；三组挂载见 [../httpserver/routes/TimelineSummary.md](../httpserver/routes/TimelineSummary.md)。
- **它调用谁**：timeline_sources.py（TimelineSource/SourceChanged/digest）；sqlite3（只读连接）。
- **它被谁依赖**：无下游服务；前端 TimelineSummaryPanel 直接渲染其响应。

## 3. 核心数据结构

**SummaryFilters**（services :21-43）：timezone（IANA 校验）、start/end_time（float，禁 inf/nan）、start/end_date、event_type、event_source、talker、direction ∈ all|sent|received|unknown|system——model_validator 同时校验时区合法与区间正序。**RecordSelection**（:45-53）：hour/weekday/day/direction/quality ∈ valid|missing|invalid|inferred|processing/record_ref/offset/limit——钻取时把"柱子"翻译回行过滤条件。

**context**（:170 起，响应的元数据主体）：`scope`（来源身份：kind/scope_id/record_origin/timestamp_unit）、`filters`、`source_version`（+`source_version_kind: "database-and-wal-file-revision-not-forensic-hash"`——显式声明这是文件修订不是取证哈希）、`scanned_content_hash`、`statistics_version: "timeline-summary:v1"`、`deduplication`（规则 `"same-source-original-id-and-payload:v1"`：仅合并同源同原始 ID 同内容记录，冲突保留；身份定义：事件 id / 微信 msgSvrId / 派生行 id / QQ 消息 id）、`counts`（scanned/valid/missing/invalid/inferred/processing/duplicate/identity_conflict/outside_time/outside_direction）、`coverage`（scan_limit/truncated/scan_order/missing_tables/observed_days/displayed_days_limit/daily_truncated/quality_scope）。

**常量**（:15-18）：`STATISTICS_VERSION="timeline-summary:v1"`、`MAX_SCAN_ROWS=100_000`、`MAX_DAILY_POINTS=3660`、`DEDUP_RULE`——扫描截断与日点截断都在 coverage 里显式披露。

## 4. 核心机制走读

### 4.1 来源身份与修订（timeline_sources.py）

`TimelineSource`（:39-43，frozen dataclass；`identity` 属性 :45-52）的 `identity` 属性把 kind 翻译成 record_origin + timestamp_unit（qq_legacy → normalized_import_table + 毫秒；wechat_import → decrypted_import_table + 毫秒、qq_import → decrypted_import_table + 秒等；注：EnMicroMsg `createTime` 原始值疑似秒制，代码按毫秒换算，以代码现状为准）——钻取结果的呈现按来源语义分派。`revision()`（:57-68）读 db + `-wal` + `-journal` 三个文件各自的（st_dev, st_ino, size, mtime_ns）束（:66）：任一是 symlink 或缺失即 SourceUnavailable——**修订是文件级的**，响应里明确声明它"not-forensic-hash"（不冒充内容哈希）。`semantic_revision` 在统计事务首尾各取一次，不一致即 SourceChanged（services :163）。

### 4.2 单事务统计与钻取一体（services summarize :72-240）

`summarize` 在一个只读事务里完成：先取 source_version → 逐行扫描（至 MAX_SCAN_ROWS）分类计数（时间质量六态：valid/missing/invalid/inferred/processing + duplicate/identity_conflict 冲突单列）→ 聚合 hourly/weekday/heatmap/daily/directions → **若带 selection 则同扫描内收集钻取明细**（:150-162，offset/limit 窗口 + 六条件匹配）→ 事务尾再取 semantic_revision 对比 → context 组装 + digest。要点：**统计与钻取是同一次扫描**——钻取的 records 与统计的柱子来自同一行集，不存在"柱子说 5 条、钻出 6 条"的分裂；连接本身是只读打开（timeline_sources.py:71 以 `file:...?mode=ro` URI 连接，:80 再设 `PRAGMA query_only=ON`），扫描完成后用 rollback 结束（:163）归还连接，全程零写入。

### 4.3 回查的两证校验（路由 :80-88 + services :188-192）

records 请求必须带 `source_version` 与 `summary_id`（都要 64-hex，缺失/格式错即 422"来源回查必须携带原统计的来源版本和统计标识"）；服务端把 filters+selection+scope 重算 context_id 与传入 `expected_summary` 对比、文件修订与 `expected_version` 对比，任一不符抛 SourceChanged（"回查条件或统计版本与原总结不一致，请重新生成统计"）——**老统计 + 已变化的库 = 409**，绝不静默按新库重算（那会让"钻查明细"变成"重新统计"，结论漂移不可察觉）。

### 4.4 人工可读层（services :210-243）

summary 是一句模板化的中文叙述（"已统计 N 条有效时间记录，分布在 D 个有记录日期；HH:00—HH+1:00 的记录最多…"）；warnings 按来源分派：events 源加"文件时间戳与后台事件不等于人为操作；推定删除和处理时间已排除出分布"，消息源加"收到消息不证明账号主人当时操作；系统消息和未知方向单独计数"；截断/缺表/不足 3 天各有专属警示。每个聚合项都带 `selector`（hour/day/weekday 组合），这就是钻取端点的请求参数来源——前端把 selector 原样拼进 records 请求即可回查。

## 5. 数据流（读什么、写什么）

**读**：仅来源库（events 派生表 / wechat_messages 形态表，按 TimelineSource.kind 分派的 SQL 与呈现）；qq_legacy 来源读导入归一化 graph.db 的 `wechat_messages` 投影（与微信任务库同形状——[../httpserver/routes/TimelineSummary.md](../httpserver/routes/TimelineSummary.md) 第 5 节）。**写**：无——连接 rollback 结束，无任何落盘缓存；"同库同参必同结果"由纯函数性保证而非缓存。

## 6. 边界与已知状态

- **扫描截断是显式的**：`coverage.truncated` + 专属警示"来源扫描已截断，当前结果仅描述已扫描记录"；scan_order 固定（表序 + rowid 升序，先于时间/方向过滤）——截断点可复现。
- **quality 分态不混算**：missing/invalid/inferred/processing 各自计数、各有 selector；valid 才进分布分母（share 按 valid_records）。
- **去重保守**：仅同源同 ID 同内容合并；跨源不自动合并（identity_conflict 计数暴露冲突）。
- **timezone 是统计语义的一部分**：小时/工作日/日界都按 filters.timezone 本地化，context 里记录——换时区重查是不同 context_id。
- **MAX_DAILY_POINTS=3660**（约 10 年）：超出 daily_truncated 显式披露，热力图不受影响。

## 7. 如何验证

- 单测：`python_service/tests/unit/` 下 timeline 相关测试（filters 校验/质量分态/去重/截断披露/qq_legacy 来源）。
- 前端契约：`web/src/components/timeline/TimelineSummaryPanel.test.jsx`（面板渲染与 selector 回查链）。
- 活体验证：`/timeline` 页改时间窗/时区看 context_id 变化；点一个小时柱回查 records，核对返回 records 数与柱子 count 一致；统计期间向来源库追加一行后立即回查应 409。

相关阅读：[../httpserver/routes/TimelineSummary.md](../httpserver/routes/TimelineSummary.md)（路由与来源解析）、[IMImportServices.md](IMImportServices.md)（qq_legacy/wechat_import 来源库的产生方）。

## 8. 二轮深化 A：context_id 为什么是对整个 context 而不只是 filters 的摘要

`context_id = digest(context)`（:188-189），而 context 里装的不止 filters：还有 scope、source_version、scanned_content_hash、统计版本、去重规则与 coverage。把回查凭证做成"全语境摘要"的用意：钻取端点要验证的命题不是"参数没变"，而是"**产生那次统计的全部前提都没变**"——库换了一个字节（scanned_content_hash 变）、服务升级改了统计口径（statistics_version 变）、甚至只换了时区（filters.scope 变），重算的 context_id 都会不同，老凭证立即失效。这比"对比 source_version"强一层：即便库文件修订没变（某些写入不改 mtime/size 的边角），扫描内容哈希的变化也会暴露。设计代价是 context 里不能放任何不可序列化或顺序不定的对象——digest 用 `ensure_ascii=False, sort_keys=True` 的规范化 JSON（timeline_sources.py:22-24），全模块的哈希输入都过这一道。

**最后更新**: 2026-11-10（新建：时间规律统计服务文档）
