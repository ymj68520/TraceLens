# Windows 取证流程教程

> **目标读者**：需要从 Windows 磁盘镜像中还原用户行为（登录、程序执行、上网、外设）并对可疑 DLL 做静态排查的取证分析师。
> **前置条件**：完成 [快速入门](../getting-started/QuickStart.md)；有一块 Windows 镜像（E01/raw 均可，NTFS）。
> **预计耗时**：60–90 分钟（大镜像的事件日志与 MFT 解析较耗时）。
> **端口约定**：curl 用 `http://localhost:8666`（run.sh 默认；`make cpp` 默认 8080）。

---

## 0. 场景设定

某员工离职后被怀疑在离职前两周批量下载了设计图纸并拷贝到 U 盘。公司提供了其工作电脑的 E01 镜像 `workstation.E01`。你要回答：**下载行为何时发生、用什么浏览器、拷到了哪个 U 盘（序列号）、期间运行过哪些程序**；顺带排查镜像里是否留有可疑的未签名库文件。

---

## 1. 镜像 → 任务

```bash
curl -X POST http://localhost:8666/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/workstation.E01",
    "scenarios": ["windows"],
    "filter_profile": "data_breach",
    "llm_analyze": true,
    "llm_mode": "smart",
    "case_description": "离职员工数据外带调查，重点关注浏览器下载、USB 设备与程序执行痕迹"
  }'
```

CLI 等价路径：`./build/forensic_analyzer workstation.E01 --windows-analyze`（平台工件并入 `workstation_files.db`；HTTP 任务则产出独立的 `data/tasks/<task_id>/windows.db`）。

跟踪进度与产物：

```bash
curl http://localhost:8666/api/tasks/<task_id>/progress
curl http://localhost:8666/api/tasks/<task_id>/databases     # 应列出 windows.db
```

**预期看到**：platform_analysis 阶段会依次跑注册表 → 事件日志 → Prefetch → LNK → JumpList → 回收站 → MFT → 用户配置 → 浏览器 → 计划任务/Amcache/SRUM → LLM（[WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md) 第 3 节主流程）。中间提取的工件文件会放在任务目录旁的 `<镜像名>_extracted_files/`（`registry/`、`eventlogs/`、`prefetch/`、`mft/` 等子目录），可供人工复核。

**为什么要看**：确认主流程走完再查表；E01 解析慢属正常，事件日志量大的机器上该阶段可能占任务大头。

---

## 2. windows.db 查证（SQL）

表结构定义在 `src/core/DatabaseManager/SQL/windows_analysis_sql_tables.h`（32 张表），速查见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 6 节。

### 2.1 注册表（registry_values）

```sql
-- 取证重要性分级后的 HIGH 值（Run 键、USBSTOR 等自动得 HIGH）
SELECT hive_type, key_path, value_name, value_type, substr(value_data, 1, 120) AS data_head,
       datetime(last_modified, 'unixepoch', 'localtime') AS key_modified
FROM registry_values
WHERE forensic_importance = 'HIGH'
ORDER BY last_modified DESC;

-- 自启动项（持久化排查）
SELECT key_path, value_name, value_data FROM registry_values
WHERE key_path LIKE '%\Run%' AND value_data IS NOT NULL AND value_data != '';
```

**预期看到**：注册表是全量遍历落库的，行数典型为几十万量级（视 hive 大小），所以查询务必带 `forensic_importance` 或路径过滤；`last_modified` 是**键级**时间戳（hivex 只提供键时间），报告里别写成"值修改时间"。

### 2.2 事件日志（event_logs）

```sql
-- 登录事件（4624 成功 / 4625 失败），按时间排
SELECT datetime(timestamp, 'unixepoch', 'localtime') AS at, event_id, log_source,
       computer_name, substr(message, 1, 160) AS msg_head
FROM event_logs
WHERE log_source = 'Security' AND event_id IN (4624, 4625, 4672)
ORDER BY timestamp DESC LIMIT 100;

-- 服务安装 / 进程创建
SELECT datetime(timestamp, 'unixepoch', 'localtime') AS at, event_id, substr(message, 1, 200) AS msg
FROM event_logs WHERE event_id IN (7045, 4688) ORDER BY timestamp DESC LIMIT 100;
```

**预期看到**：EVTX 解析是"双段读取"——正常记录之外还会提取损坏/清除后的**恢复记录**（libevtx recovered records），攻击者清日志后残存的事件从这里回来；审计日志里每条 `EVTX_PARSE_SUCCESS` 带 recovered 计数。

### 2.3 Prefetch（prefetch_files）

```sql
-- 程序执行证据：运行次数 + 最后运行时间 + 引用文件
SELECT executable_name, run_count,
       datetime(last_run_time, 'unixepoch', 'localtime') AS last_run
FROM prefetch_files
ORDER BY last_run_time DESC LIMIT 50;
```

**预期看到**：解析失败的 `.pf` 会从文件名反推至少留一条记录（`NOTEPAD.EXE-ABC12312.pf` 命名约定）；`referenced_files` 是该程序加载过的文件列表，是第 4 节 DLL 关联的原料。

### 2.4 浏览器（browser_history / browser_downloads）

```sql
-- 案发窗口内的下载记录（Chrome/Edge/Firefox 均覆盖）
SELECT browser_name, profile_name, url, target_path, file_name, file_size,
       datetime(start_time, 'unixepoch', 'localtime') AS started,
       datetime(end_time, 'unixepoch', 'localtime') AS finished, state
FROM browser_downloads
ORDER BY start_time DESC LIMIT 100;

-- 上网行为
SELECT browser_name, url, title, visit_count,
       datetime(visit_time, 'unixepoch', 'localtime') AS visited
FROM browser_history ORDER BY visit_time DESC LIMIT 100;
```

**预期看到**：`browser_downloads.target_path` 直接回答"下载到了哪里"；与 USB 时间窗（`usb_devices` 表的 `first_connected/last_connected`、序列号）交叉即可钉死"下载 → 拷贝"链。本案的关键查询：

```sql
SELECT vendor_id, product_id, serial_number, device_description,
       datetime(first_connected, 'unixepoch', 'localtime') AS first_at,
       datetime(last_connected, 'unixepoch', 'localtime') AS last_at, last_drive_letter
FROM usb_devices ORDER BY last_connected DESC;
```

### 2.5 SRUM（srum_entries）

```sql
-- 应用网络/资源用量（SRUM 周期聚合，可信度高、难清除）
SELECT app_name, user_name,
       datetime(timestamp, 'unixepoch', 'localtime') AS at,
       bytes_sent, bytes_received
FROM srum_entries
WHERE bytes_sent > 0
ORDER BY timestamp DESC LIMIT 100;
```

**预期看到**：SRUM 能佐证"某程序在某时段上传/下载了大量字节"——即使浏览器历史被清，这里通常还有残余。

### 2.6 恒空表（现状，必读）

以下表**建了但流水线没有调用对应解析器**，真实分析中永远是空的（[WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md) 第 7 节"未接线的工件"）：

- `shimcache_entries`（`parseShimcacheFromRegistry` 未被调用）
- `user_assist_entries`（同上）
- `rdp_connections`（同上）
- `wifi_profiles`（同上）
- `shell_bag_entries`（连解析器都没有）

报告里需要这些证据时要么人工从 `registry_values` 查原始键（Shimcache 在 SYSTEM hive 的 AppCompatCache，UserAssist/RDP 在 NTUSER.DAT），要么二次开发接线。

---

## 3. 时间线交叉

Windows 工件的时间戳与文件系统时间线对质：

```bash
# 可疑时段的综合时间线（事件簇）
curl "http://localhost:8666/api/forensics/timeline/comprehensive?task_id=<task_id>&cluster=true&bucket=300" \
  | python3 -m json.tool | less

# 用户活动与可疑模式
curl "http://localhost:8666/api/forensics/timeline/user-activity?task_id=<task_id>"
curl "http://localhost:8666/api/forensics/timeline/suspicious-patterns?task_id=<task_id>"
```

前端 `http://localhost:8666/timeline` 选择任务查看。跨库对质用 `ATTACH DATABASE`（库间无外键，靠 inode/path 逻辑对齐，见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 10 节）：

```bash
cd build/data/tasks/<task_id>
sqlite3 windows.db "ATTACH DATABASE 'events.db' AS e;
SELECT datetime(t.timestamp,'unixepoch','localtime') AS at, t.executable_name, t.run_count
FROM prefetch_files t
WHERE EXISTS (SELECT 1 FROM e.events ev
              WHERE ev.timestamp BETWEEN strftime('%s','2026-07-01') AND strftime('%s','2026-07-15')
                AND ev.inode IS NOT NULL)
ORDER BY t.last_run_time DESC LIMIT 50;"
```

**预期看到**：把下载时间（browser_downloads）、拷贝窗口（usb_devices）、程序执行（prefetch）叠进同一条时间线后，行为序列应当自洽；若 MFT 双时间戳（`mft_entries` 的 `creation_time` vs `fn_creation_time`）互相矛盾，本身就是反取证线索。

**为什么要看**：单一工件的 timestamps 可被伪造（timestomping），交叉验证是 Windows 取证的方法论核心。

---

## 4. DLL 分析（--analyze-dlls）及其现状与局限

CLI 专项入口（不参与 HTTP 任务流水线）：

```bash
# 作为完整分析的附加步骤（与 --windows-analyze 连用时挂只读 files.db 做取证关联）
./build/forensic_analyzer workstation.E01 --windows-analyze --analyze-dlls --dll-threshold 30

# 或独立子命令（只跑 DLL 分析，自定义输出库）
./build/forensic_analyzer workstation.E01 --analyze-dlls-only \
  --dll-db /evidence/workstation_dll.db --no-verify-signatures
```

产物 `<镜像名>_dll.db` 的 7 张 `dll_*` 表查询：

```sql
-- 高威胁评分的库
SELECT name, path, md5, imp_hash, compile_timestamp, signature_status, threat_score
FROM dll_base_info
ORDER BY threat_score DESC LIMIT 30;

-- 高熵可执行节（加壳/加密代码指征：entropy 6-7 疑似加壳，7-8 高可疑）
SELECT b.name, s.section_name, s.entropy, s.is_executable, s.is_writeable
FROM dll_sections s JOIN dll_base_info b ON b.id = s.dll_id
WHERE s.entropy > 6.5 AND s.is_executable = 1;

-- 异常明细（注入 API / 反调试 / 壳签名等启发式命中）
SELECT b.name, a.anomaly_type, a.risk_level, a.description
FROM dll_anomalies a JOIN dll_base_info b ON b.id = a.dll_id
WHERE a.risk_level IN ('HIGH', 'CRITICAL');

-- 与 Windows 工件的关联（--analyze-dlls + --windows-analyze 连用时产出）
SELECT b.name, l.link_type, l.source_data
FROM dll_forensic_links l JOIN dll_base_info b ON b.id = l.dll_id LIMIT 50;
```

HTTP 侧只读查询也有对应端点（`GET /api/forensics/dlls?task_id=`、`/dlls/suspicious?min_score=`、`/dlls/<id>/anomalies`），数据源同样是 dll.db。

**必须知道的现状与局限**（[DLLAnalyzer](../modules/cpp/analyzers/DLLAnalyzer.md) 第 1 节，源码 TODO 原文在 `DLLAnalyzerCore.cpp:299-302`）：

1. **它扫的是分析机本机的系统目录，不是镜像里提取的文件**——Linux 下扫 `/usr/lib` 等路径，Windows 下扫 `%WINDIR%\System32`。因此在取证流水线里，dll.db 当前是"分析机自身库文件的画像"，**不能当作镜像内可疑 DLL 的覆盖性结论**。要分析镜像内文件，需二次开发把扫描源接到提取目录（`setExtractDirectory`/`analyzeSingleFile` 接口已预留）。
2. **`--dll-threshold` 是哑参数**：被解析但没有任何代码消费，威胁分阈值 30 硬编码在实现里。
3. **`.so` 文件会被扫进但不产出记录**（PE 头无效即跳过；ELF 解析器只有测试在用）。
4. **dll.db 里也有空的 Windows 工件表**：它复用 windows 全部建表 SQL，别被 registry_values 等空表迷惑；反向 windows.db 里也有 7 张空的 dll_* 表。
5. 白名单：14 个知名系统库名（kernel32.dll、libc.so.6 等）与系统目录前缀下的文件会被跳过——这是性能取舍，意味着"系统目录里的伪装同名库"不会进 dll.db。

**为什么要看**：尽管有上述局限，dll_anomalies 的启发式（高熵节、注入 API、壳签名）与 ImpHash 仍是恶意样本初筛的成熟套路；只要在报告中如实标注"扫描范围为分析机目录"，作为方法论演示与工具链验证是安全的。

---

## 排坑清单

1. **恒空表当结论是事故**：`shimcache_entries / user_assist_entries / rdp_connections / wifi_profiles / shell_bag_entries` 在当前流水线必空（见 2.6）。查空后下结论前先对照 [WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md) 第 7 节。
2. **工件查询只取未删除文件**：`queryFilesByPattern` 带 `is_deleted=0`，被删的 hive/evtx 不会进入分析；补救靠 EVTX 恢复记录与 MFT 层（第 2.2/3 节）。
3. **中文路径可能丢字**：`readUTF16LEString` 只保 ASCII（非 ASCII 替换为 `?`），中文用户名/文件名在 windows.db 里可能是问号，定位时用 SID/RID 交叉（[WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md) 注意事项）。
4. **MFT 默认截断**：mft_entries 默认只处理前 10 万条，超大盘上"没查到"不等于"不存在"。
5. **MFT 默认不做 LLM 分析**：`options.includeMFT = false`（量太大），LLM 摘要覆盖其余 15 类工件但不含 MFT。
6. **E01 大镜像的 LLM 阶段耗时**：默认每类工件上限 10000 条；`--no-ai` 或不配 `LLM_BASE_URL` 会跳过（门禁看 URL 而非 key）。
7. **SRUM 需要 libesedb**：setup.sh 已装；自行精简依赖的构建里 SRUM 表会空。

---

## 延伸阅读

- [WindowsFilesAnalyzer 模块文档](../modules/cpp/analyzers/WindowsFilesAnalyzer.md) — 工件来源模式表与"查询-提取-解析"三段式
- [DLLAnalyzer 模块文档](../modules/cpp/analyzers/DLLAnalyzer.md) — PE 解析、异常启发式、威胁评分
- [数据库模式](../architecture/DatabaseSchema.md) 第 6 节 — windows.db 32 张表
- [C++ REST API](../api_reference/CPP_REST_API.md) — 时间线/DLL 端点
- [Linux 入侵排查教程](LinuxIntrusion.md) — 同套时间线方法在 Linux 侧的运用

---

**最后更新**: 2026-08-24（新建，教程）
