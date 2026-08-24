# 内存分析库（`<image>_memory.db`）字段参考（定义位置：`src/core/DatabaseManager/SQL/memory_analysis_sql_tables.h` + `memory_analysis_sql_crud.h`）

> 内存库是唯一**不落任务目录**的分析库：CLI `--memory-analyze` 把 Volatility3 对内存镜像的 JSON 输出搬到 SQLite，紧贴镜像存放。它不参与 raw.db → events/files 的派生链（DatabaseSchema.md 决定一：每镜像一组文件），而是与磁盘侧平行的第二证据宇宙——磁盘上删掉的进程/连接，可能还活在内存里。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `MemoryAnalyzer` 的 `MemoryAnalysisDatabase`：单条 `CREATE_ALL_TABLES`（`memory_analysis_sql_tables.h:13-88`）建 6 表 + 6 索引；行写入用 `memory_analysis_sql_crud.h:10-32` 的 INSERT/UPSERT（调用如 `MemoryAnalysisDatabase.cpp:55` 进程、`:90` boot_info） |
| 谁读 | CLI 报告生成、后续分析流程；无 HTTP 任务路由（内存分析仅 CLI 入口） |
| 文件位置 | 镜像同目录 `<image>_memory.db`（DatabaseSchema.md 产出位置表） |
| 设计约定 | 头文件注释（`:10-12`）："Columns mirror the real Volatility3 (2.x) JSON output field names so the parsers can map fields 1:1 without renaming"——列名即 vol3 字段名 |

## 表清单总表

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `processes` | 进程 | vol3 linux.pslist/pstree 进程清单 | 12 |
| `network_connections` | 网络 | linux.sockstat 套接字连接 | 15 |
| `bash_history` | 命令 | linux.bash 内存中的 shell 历史 | 7 |
| `boot_info` | 元数据 | 内核/系统信息键值 | 4 |
| `cmdline` | 进程 | linux.psaux 进程命令行 | 5 |
| `analysis_meta` | 元数据 | 本次分析自身的信息 | 4 |

## 逐表字段说明

### processes（`memory_analysis_sql_tables.h:14-27`，写入 `memory_analysis_sql_crud.h:10-12`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| offset | INTEGER | — | 进程 task_struct 地址（SQL 注释：OFFSET (V)；vol3 原字段名） |
| pid | INTEGER | — | 进程 ID |
| tid | INTEGER | — | 线程 ID（共享 pid 的线程各自成行） |
| ppid | INTEGER | — | 父进程 ID（孤儿/伪装进程排查） |
| comm | TEXT | — | 进程名（COMM） |
| uid / gid / euid / egid | INTEGER | — | 四重身份（提权检测：uid≠euid） |
| creation_time | TEXT | — | 创建时间（ISO 8601 文本，非 unix 秒） |
| inserted_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

索引：`idx_processes_pid(pid)`（`:82`）。

### network_connections（`:29-46`，写入 `crud.h:14-17`）

来源：linux.sockstat（SQL 注释明言 vol3 2.x 没有 linux.netstat）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| offset | INTEGER | — | socket 结构地址（Sock Offset） |
| pid / tid | INTEGER | — | 归属进程/线程 |
| comm | TEXT | — | 进程名（Process Name） |
| family | TEXT | — | AF_INET/AF_UNIX/... |
| type | TEXT | — | STREAM/DGRAM/... |
| proto | TEXT | — | 协议 |
| local_addr | TEXT | — | 本端地址（Source Addr） |
| local_port | TEXT | — | 本端端口（**TEXT**——vol3 输出即字符串，SQL 注释："string in vol3 output"） |
| remote_addr | TEXT | — | 对端地址（Destination Addr） |
| remote_port | TEXT | — | 对端端口（TEXT） |
| state | TEXT | — | TCP 状态 |
| netns | INTEGER | — | 网络命名空间 |
| inserted_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

索引：`idx_net_pid(pid)`、`idx_net_rport(remote_port)`、`idx_net_lport(local_port)`（`:83-85`）。

### bash_history（`:48-57`，写入 `crud.h:19-21`）

来源：linux.bash（进程内存中未刷盘的历史——磁盘 history 文件没有的部分）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| pid | INTEGER | — | 所属 bash 进程 |
| comm | TEXT | — | 进程名（Process） |
| command | TEXT | — | 命令（Command） |
| command_time | TEXT | — | 命令时刻（ISO 8601；SQL 注释："key for Q102/Q103"，即题目考察点） |
| history_index | INTEGER | — | 历史序号 |
| inserted_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

索引：`idx_bash_command(command)`、`idx_bash_cmdtime(command_time)`（`:86-87`）。

### boot_info（`:59-64`，写入 `crud.h:23-25` UPSERT ON CONFLICT(key)）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| key | TEXT | UNIQUE | 信息键（kernel 版本、主机名等） |
| value | TEXT | — | 值 |
| inserted_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

### cmdline（`:66-73`，写入 `crud.h:27-29`）

来源：linux.psaux（vol3 2.x 无 linux.cmdline，SQL 注释）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| pid | INTEGER | — | 进程 ID |
| comm | TEXT | — | 进程名 |
| args | TEXT | — | 完整命令行参数 |
| inserted_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

### analysis_meta（`:75-80`，写入 `crud.h:30-32` UPSERT）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| key | TEXT | UNIQUE | 元数据键（vol3 版本、分析时间等） |
| value | TEXT | — | 值 |
| inserted_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

## 表与 Volatility3 插件来源对照（建表 SQL 注释为证）

| 表 | vol3 插件 | 注释要点（`memory_analysis_sql_tables.h`） |
|----|-----------|------------------------------------------|
| processes | linux.pslist / pstree | 列名对齐 OFFSET/COMM 等原字段 |
| network_connections | linux.sockstat | "vol3 2.x has no linux.netstat" |
| bash_history | linux.bash | command_time 是 "key for Q102/Q103" |
| boot_info | 内核/系统信息聚合 | 键值 UPSERT |
| cmdline | linux.psaux | "vol3 2.x has no linux.cmdline" |
| analysis_meta | 分析器自身 | 记录 vol3 版本等 |

## 写入语句清单（`memory_analysis_sql_crud.h`）

| 语句 | 行 | 目标表 | 语义 |
|------|----|--------|------|
| INSERT_PROCESS | `:10-12` | processes | 10 列直插 |
| INSERT_NETWORK_CONNECTION | `:14-17` | network_connections | 13 列直插 |
| INSERT_BASH_HISTORY | `:19-21` | bash_history | 5 列直插 |
| UPSERT_BOOT_INFO | `:23-25` | boot_info | ON CONFLICT(key) 覆盖 value |
| INSERT_CMDLINE | `:27-28` | cmdline | 3 列直插 |
| UPSERT_ANALYSIS_META | `:30-32` | analysis_meta | 同 boot_info |

## 跨表关联键

- **pid** 是库内主键轴：`processes.pid` ↔ `network_connections.pid` ↔ `cmdline.pid` ↔ `bash_history.pid`（值对齐，无外键，决定二文化）。

真实 JOIN 示例（进程与其外联连接、完整命令行三表联查——内存分析的标准动作）：

```sql
SELECT p.pid, p.comm, c.args, n.remote_addr, n.remote_port, n.state
FROM processes p
LEFT JOIN cmdline c ON c.pid = p.pid
LEFT JOIN network_connections n ON n.pid = p.pid
WHERE n.remote_addr IS NOT NULL
ORDER BY p.pid;
```

## 已知边界

- **端口列是 TEXT**：`local_port/remote_port` 按数字比较/过滤时须 `CAST`（继承 vol3 JSON 输出类型，有意为之）。
- **时间格式两制并存**：`creation_time/command_time` 是 ISO 8601 文本，`inserted_at` 是 unix 秒——排序要分清。
- **无 LLM 列**：本库不参与 LLM 分析流水线（没有 llm_* 列，也无对应服务）。
- **无 UPSERT 冲突面**：boot_info/analysis_meta 用 ON CONFLICT(key)，其余表允许重复行（重复跑分析会追加而非去重，`CREATE TABLE IF NOT EXISTS` 不清旧数据）。

---


## 附录：写入时序与查询手册

### 写入时序

| 表 | 写入方 | 时机 | 备注 |
|----|--------|------|------|
| processes | Volatility3Runner（linux.pslist/pstree）→ ProcessParser | `--memory-analyze`（**CLI 专用旁路**，HTTP 侧靠命名约定找库） | 列名对齐 vol 原字段 |
| network_connections | linux.sockstat → NetworkParser | 同上 | |
| bash_history / boot_info / cmdline / analysis_meta | 各解析器 | 同上 | 失败信息入 analysis_meta |

### 查询手册（列名以本文档字段表为准）

**1. 活动连接清单（ ESTABLISHED 优先）**
```sql
SELECT pid, comm, proto, local_addr, local_port, remote_addr, remote_port
FROM network_connections
ORDER BY CASE state WHEN 'ESTABLISHED' THEN 0 ELSE 1 END, pid;
```

**2. 可疑进程画像（无路径/父进程异常/用户异常）**
```sql
SELECT pid, ppid, comm, uid, euid, creation_time
FROM processes
WHERE uid=0 OR ppid=1 OR ppid=2
ORDER BY creation_time;
```

**3. 进程↔连接对质（谁在连哪）**
```sql
SELECT p.pid, p.comm, n.remote_addr, n.remote_port, n.state
FROM processes p JOIN network_connections n ON n.pid=p.pid
WHERE n.remote_addr IS NOT NULL AND n.remote_addr NOT IN ('0.0.0.0','::');
```

**4. 与磁盘时间线交叉（bash 命令时刻对 events）**
```sql
-- memory.db：先取命令时刻
SELECT command, timestamp FROM bash_history WHERE command LIKE '%curl%' OR command LIKE '%nc %';
-- 再到 events.db：SELECT ... FROM events WHERE timestamp BETWEEN :t-5 AND :t+5;
```

**5. 会话环境（boot_info 单行读）**
```sql
SELECT * FROM boot_info;
```

**6. 分析自检（Volatility 是否有报错/降级）**
```sql
SELECT * FROM analysis_meta;
-- 插件失败/符号缺失会留痕；符号自愈流程见 MemoryAnalyzer 模块文档
```

## 分析案例

### 案例一：运行时外联确认

**取证问题**：磁盘侧发现可疑脚本但无运行证据。有同期内存镜像，要求确认"当时是否在跑、连到哪"。

**第 1 步：外联清单**
```sql
SELECT pid, comm, proto, local_port, remote_addr, remote_port, state
FROM network_connections
WHERE state='ESTABLISHED' ORDER BY pid;
```
读法：关注非常用端口/裸 IP 远端；`comm` 直接给出进程名。

**第 2 步：进程归属与异常特征**
```sql
SELECT pid, ppid, comm, uid, euid, creation_time FROM processes
WHERE pid IN (<第1步 pid 列表>) OR ppid IN (<第1步 pid 列表>);
```
读法：ppid=1/2（孤儿化）、euid≠uid（提权痕迹）、creation_time 晚于磁盘侧脚本落地时间——三点对上即"脚本落地→进程拉起"闭环。

**第 3 步：命令历史交叉**
`bash_history` 找启动命令原句；与 events.db（ATTACH）时间对齐（SqlCookbook 第 4 条）。
边界：内存表六张全来自 vol3 插件，插件失败只留 analysis_meta——先查 meta 再下"没有"的结论。

## 自检清单

- [ ] analysis_meta 无插件级失败/符号缺失
- [ ] processes 行数量级正常（几十~两百）
- [ ] network_connections 的 state 分布（全空=sockstat 未跑）
- [ ] 时间交叉前确认内存捕获时刻与磁盘镜像时刻的关系
**最后更新**: 2026-08-24（补：写入时序与查询手册）
