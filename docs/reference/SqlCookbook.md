# SQL 食谱：跨库联查与诊断

> 比 [schema/ 各库"查询手册"](../schema/LinuxDB.md) 更进阶的**跨库/联查/诊断**食谱。约定：`<T>` 代表任务目录（`data/tasks/<task_id>`）；所有表列以 schema 文档为准；空表陷阱（见各库"已知边界"）在条目里标注。用 sqlite3 打开任一库后 `ATTACH` 其他库即可联查。

## 一、对质类（跨层回溯）

### 1. 时间线事件 ↔ 分类文件对质：某文件发生了什么、它是什么
```sql
ATTACH '<T>/files.db' AS f;
ATTACH '<T>/events.db' AS e;
SELECT e.timestamp, e.event_type, e.file_path, f.category, f.scene_relevant, f.llm_summary
FROM e.events e LEFT JOIN f.files f ON f.path = e.file_path
WHERE e.file_path LIKE '%/suspect%'
ORDER BY e.timestamp;
```
**读法**：LEFT JOIN 保证"有事件但未分类"（被过滤/非常规类型）不丢行；llm_summary 为空说明未到 LLM 或被 SMART 粗选淘汰。变体：`WHERE f.scene_relevant=1` 只看场景相关。

### 2. raw 与 filtered 对账：过滤画像丢了哪些值得看的文件
```sql
ATTACH '<T>/raw.db' AS r;
ATTACH '<T>/files.db' AS f;
SELECT r.path, r.size FROM r.files r
LEFT JOIN f.files f ON f.path = r.path
WHERE f.id IS NULL AND r.path LIKE '%.db'
ORDER BY r.size DESC LIMIT 50;
```
**读法**：找出"进了 raw 但没进分类"的 .db 文件（画像 include 未覆盖的证据库）。把 `LIKE '%.db'` 换成别的扩展名做同类对账。

### 3. LLM 结论与 file_descriptions 交叉：is_relevant 与主表摘要矛盾吗
```sql
SELECT f.path, f.llm_summary, d.is_relevant, d.model_used, d.analyzed_at
FROM files f LEFT JOIN file_descriptions d ON d.path = f.path
WHERE d.id IS NOT NULL ORDER BY d.is_relevant DESC, d.analyzed_at DESC LIMIT 100;
```
（files.db 内）**读法**：is_relevant=1 但 llm_summary 为空 → 重分析只写了 descriptions 表；两表都有但语义相反 → 模型前后判断翻转（看 analyzed_at 时间差）。

### 4. 事件簇 ↔ 文件双向（Python /api/associations 的 SQL 版）
```sql
ATTACH '<T>/raw.db' AS r;
WITH clusters AS (
  SELECT (timestamp/60)*60 AS minute, parent_dir, COUNT(*) cnt
  FROM (SELECT timestamp, rtrim(file_path, replace(file_path,'/','')) AS parent_dir FROM events)
  GROUP BY minute, parent_dir HAVING cnt >= 3)
SELECT c.minute, c.parent_dir, c.cnt, r.path, r.size
FROM clusters c JOIN r.files r ON r.path LIKE c.parent_dir || '%'
ORDER BY c.cnt DESC LIMIT 200;
```
**读法**：这是"簇↔文件关联"的手工等价（服务端是 ±300s 不等式 + 目录谓词双条件）；用于验证服务端结果或离线分析。

## 二、平台交叉类

### 5. Linux：登录失败 + 后续新文件（入侵黄金组合）
```sql
ATTACH '<T>/linux.db' AS l;
ATTACH '<T>/events.db' AS e;
SELECT l.user, l.source_ip, l.timestamp, x.file_path, x.event_type
FROM l.linux_login_records l
JOIN e.events x ON x.timestamp BETWEEN l.timestamp AND l.timestamp + 300
WHERE l.status LIKE '%fail%' AND x.event_type = 'CREATED'
ORDER BY l.timestamp LIMIT 200;
```
**读法**：失败登录后 5 分钟内的新建文件。变体：把 300 调大、加 `x.file_path LIKE '%/tmp/%' OR x.file_path LIKE '%/dev/shm/%'`。

### 6. Linux：持久化 + 攻击链联查
```sql
SELECT p.type, p.path, p.risk_level, c.chain_description
FROM linux_persistence_entries p
LEFT JOIN linux_attack_chains c ON c.chain_id = p.chain_id
ORDER BY CASE p.risk_level WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END;
```
**注意**：chain_id 关联存在时才有值；attack_chains 由分析引擎生成，可能为空。

### 7. Windows：自启动三源交叉
```sql
SELECT 'registry' src, key_path AS item, value_data AS detail FROM registry_values
 WHERE key_path LIKE '%Run%'
UNION ALL
SELECT 'service', name, image_path FROM windows_services WHERE start_type='AUTO'
UNION ALL
SELECT 'task', name, action FROM scheduled_tasks
ORDER BY item;
```
（windows.db 内）**读法**：三源同名/同路径项是持久化强信号；对照 [schema/WindowsDB](../schema/WindowsDB.md) 各表列名。

### 8. Windows Prefetch + 时间线：程序何时执行过
```sql
ATTACH '<T>/events.db' AS e;
SELECT p.name, p.last_run_times, x.file_path, x.timestamp
FROM prefetch_files p JOIN e.events x ON x.file_path LIKE '%' || p.name || '%'
ORDER BY p.last_run_times DESC LIMIT 100;
```
**注意**：prefetch 的运行时间是文本多值列，精确对时以 events 为准。

### 9. Android：微信消息 ↔ 通话记录时间窗
```sql
SELECT m.talker, m.timestamp, 'msg' kind, substr(m.content,1,60) preview
FROM wechat_messages m WHERE m.timestamp BETWEEN :s AND :e
UNION ALL
SELECT c.number, c.timestamp, 'call_' || c.type, c.duration
FROM call_logs c WHERE c.timestamp BETWEEN :s AND :e
ORDER BY timestamp;
```
（android.db 内）**读法**：案发窗口内"消息-通话"行为序列。`:s/:e` 为占位。

### 10. 内存 ↔ 磁盘：进程网络连接对质
```sql
-- memory.db
SELECT p.pid, p.name, n.local_port, n.remote_addr, n.remote_port
FROM processes p JOIN network_connections n ON n.pid = p.pid
WHERE n.state = 'ESTABLISHED' ORDER BY p.pid;
```
**读法**：与 linux.db 的 linux_network_connections 或 windows 的事件日志 5156 交叉（PID/端口/时间三键）。

## 三、诊断类（运维与排障）

### 11. 任务库完整性三连
```sql
PRAGMA integrity_check;        -- 期望 ok
PRAGMA foreign_key_check;      -- 当前 schema 无外键，应空
PRAGMA journal_mode;           -- 期望 wal（除 raw 只读场景）
```
对所有 .db 逐个跑；验收框架的 Journey A 也这么验（[AcceptanceHarness](../testing/AcceptanceHarness.md)）。

### 12. 时间线分布速览（找"异常安静"或"爆发"时段）
```sql
SELECT strftime('%Y-%m-%d %H:00', timestamp, 'unixepoch') h, event_type, COUNT(*)
FROM events GROUP BY h, event_type ORDER BY h;
```
**读法**：长时间零事件可能是时钟回拨/镜像静默；某小时爆发配合簇分析（/api/forensics/timeline/clusters/analyze）。

### 13. 索引缺口自查（对照 schema 文档的缺口清单）
```sql
SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name;
-- 期望：android.db 几乎没有（已知缺口）、windows.db 仅 dll_* 组、linux.db 见 LinuxDB 文档
```

### 14. 审计库：任务操作轨迹
```sql
-- forensics_audit.db（注意在 CWD/build 下）
SELECT timestamp, action, resource_id, substr(details,1,80)
FROM audit_logs WHERE resource_id LIKE '%<task_id>%'
ORDER BY timestamp;
```
**读法**：SCENE_DETECTED（自动场景判定）、GRAPHITI_INGESTION（图谱触发）都在这里——"系统替你做的判断"可复核。

### 15. C/S PostgreSQL：命令积压与代理在线
```sql
SELECT status, COUNT(*) FROM command_queue GROUP BY status ORDER BY 2 DESC;
SELECT id, hostname, last_seen_at FROM clients
 WHERE last_seen_at > now() - interval '90 seconds';  -- 60s 在线窗口
SELECT task_id, COUNT(*) FROM analysis_results GROUP BY task_id ORDER BY 2 DESC LIMIT 20;
```

## 四、健康与统计类

### 16. 任务产出"体检"一页
```sql
-- files.db
SELECT category, COUNT(*), ROUND(AVG(size)) FROM files GROUP BY category ORDER BY 2 DESC;
SELECT COUNT(*) total, SUM(llm_analyzed_at IS NOT NULL) llm_done,
       SUM(scene_relevant) relevant FROM files;
-- events.db
SELECT event_type, COUNT(*) FROM events GROUP BY event_type;
```
**读法**：llm_done/relevant 比例异常低时查 SMART 粗选日志与 LLM_MAX_FILES。

### 17. 大文件与删除文件 Top
```sql
ATTACH '<T>/raw.db' AS r;
SELECT path, size, is_deleted, partition_num FROM r.files
WHERE type='REG' ORDER BY size DESC LIMIT 50;
SELECT path, size FROM r.files WHERE is_deleted=1 AND size > 1048576 ORDER BY size DESC LIMIT 50;
```

### 18. 分区分布（多分区镜像）
```sql
SELECT partition_num, fs_type, COUNT(files.id) files, ROUND(SUM(files.size)/1048576.0) mb
FROM partitions p LEFT JOIN files ON files.partition_num = p.partition_num
GROUP BY partition_num;  -- raw.db
```

## 使用提醒

- **空表先看边界**：查 [schema/ 对应库的"已知边界"](../schema/WindowsDB.md)——恒空表（如 shimcache）查不出数据是正常的。
- **大小写**：tasks.json 里状态是大写、表内枚举大小写以 schema 文档为准。
- **写操作**：这些食谱都是只读。任何对任务库的写都应走服务（重分析/摄取），直接 UPDATE 会绕过 D2b/D4b 边界。

---

**最后更新**: 2026-08-24（新建：18 组跨库食谱）
