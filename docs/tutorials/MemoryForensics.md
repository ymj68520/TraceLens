# 内存取证教程（LiME / raw dump → Volatility3）

> **目标读者**：拿到一台 Linux 服务器的 RAM 镜像（LiME `.lime` 或 raw dump），需要从中提取进程/网络/命令行证据，并与磁盘时间线对质的取证分析师。
> **前置条件**：完成 [快速入门](../getting-started/QuickStart.md)；`python_service/.venv/bin/vol` 可用（setup.sh 安装 volatility3）；知道或愿意让工具自动探测内存镜像的内核版本。
> **预计耗时**：30–60 分钟（4GB 级 dump 的五个插件串行跑需要耐心）。
> **端口约定**：curl 用 `http://localhost:8666`（run.sh 默认）。

---

## 0. 场景设定

接 [Linux 入侵排查教程](LinuxIntrusion.md) 的案子：磁盘时间线显示深夜有一段"无法解释的空档"（日志缺失），怀疑攻击者清除了痕迹后还在机上活动。运维在断电前用 LiME 抓了一块内存镜像 `mem.lime`（4GB，文件头魔数 `EMiL`）。内存里往往还留着磁盘上已被删除的东西：bash 历史、活跃 socket、陌生进程。你要回答：**空档时段机器上跑过什么命令、连过哪些地址、有没有磁盘上查不到的进程**。

---

## 1. 确认 Volatility3 就位

MemoryAnalyzer 通过 fork/exec 调用 vol 二进制，定位顺序是 `python_service/.venv/bin/vol`（从 CWD 向上最多 6 层找 `python_service`）→ 系统 PATH 上的 `vol`：

```bash
python_service/.venv/bin/vol --version || which vol
```

**预期看到**：版本号（要求 volatility3 2.x，`setup.sh` 按要求安装 `volatility3>=2.7.0`）。两个都找不到时内存分析只会产出一个空库加错误元数据（见排坑 5）。

**为什么要看**：这是整条链路唯一的硬外部依赖；C++ 侧不打包 vol。

---

## 2. 获取 ISF 符号（scripts/build-vol3-isf.sh）

vol3 解析 Linux 内存镜像必须有与**内核版本完全匹配**的 ISF（Intermediate Symbol File）符号表，否则所有插件报 `No Linux banners found`。一次性准备：

```bash
./scripts/build-vol3-isf.sh 6.8.0-110-generic
# 参数是镜像内核的 uname -r；默认安装到 ~/.cache/volatility3/symbols
# （注意：vol3 2.x 扫描的是 ~/.cache 而不是 ~/.config）
```

脚本的三级策略（快到慢）：

| 层级 | 方式 | 耗时 |
|------|------|------|
| L1 | 社区符号仓库（Abyss-W4tcher/volatility3-symbols）经 jsDelivr CDN 下载 `.json.xz` | 秒级 |
| L2 | 从 Ubuntu dbgsym ddeb 下载 vmlinux，用自带 dwarf2json 生成 | 分钟级（ddeb 约 1.7GB） |
| L3 | 友好失败，打印手工指引（社区仓库浏览 / ddebs apt 源 / 任意 vmlinux + dwarf2json） | — |

可选参数：`--from-ddeb` 跳过 L1 直接走 L2；第二个位置参数自定义安装目录。脚本幂等，同版本重跑会覆盖。

**预期看到**：L1 命中时打印 `Downloaded + validated ISF` 与文件大小，最后提示下一步命令；`~/.cache/volatility3/symbols/linux-6.8.0-110-generic.json` 存在。

**为什么要看**：不知道内核版本也没关系——第 3 步的自愈机制会替你跑这个脚本；但手工预取能在网络受限的取证机上先行排障。

---

## 3. 运行内存分析（CLI 专用旁路）

```bash
./build/forensic_analyzer /evidence/mem.lime \
  --memory-analyze --vol-symbols-dir ~/.cache/volatility3/symbols
```

- `--memory-analyze` 是**CLI 专用旁路子命令**：在 `AnalysisOrchestrator::runAnalysis` 顶部提前 return，绕过整条 TSK 磁盘流水线——RAM dump 不是磁盘镜像，没有 `_raw.db/_files.db`，只产出 `/evidence/mem.lime` 同目录的 `mem_memory.db`。
- `--vol-symbols-dir` 直通 vol3 的 `-s` 参数；省略则用 vol3 默认扫描路径。
- 镜像类型自动探测：读文件头 8 字节，`EMiL` → LiME/Linux 插件集，`PAGEDU64` → Windows 插件集，其余按 Linux 尝试。Linux 用 `linux.pslist / linux.bash / linux.sockstat / linux.boottime / linux.psaux`（vol3 2.x **没有** `linux.netstat` 和 `linux.cmdline`，socket 取 sockstat、命令行取 psaux）。

### 内核 banner 自愈机制（值得了解）

即使你没提前准备符号，分析也能自愈（[MemoryAnalyzer](../modules/cpp/analyzers/MemoryAnalyzer.md) 第 4 节链路二）：

1. 先跑一次 pslist；stderr 命中 banner/symbol 关键词即判定符号缺失；
2. `detectKernelVersion` 以 64MB 分块**流式扫描整个镜像**找 `Linux version ` 字符串（banner 可能埋在很深的位置——4GB 测试镜像里出现在 3.5GB 处；分块间保留重叠窗口防跨块漏检，版本号必须以数字开头防"GNU/Linux version of..."假命中）；
3. `autoFetchSymbols` 调 `scripts/build-vol3-isf.sh <版本>`，并确认 ISF 真的落盘；
4. 带 `-s` 重试一次 pslist；再失败则打印手工修复指引并干净退出（只留下带 `err:*` 元数据的空库）。

**预期看到**：stderr 逐插件打印进度；符号缺失时会看到 `[Memory] Kernel banner: Linux version ...` 一行与脚本级联输出。最终 `mem_memory.db` 含六张表：`processes / network_connections / bash_history / boot_info / cmdline / analysis_meta`。

**为什么要看**：每个插件独立超时与容错——一个插件失败不会拖垮其余，失败原因都进 `analysis_meta`。

---

## 4. 直接查 _memory.db（SQL）

列名刻意镜像 vol3 JSON 字段（`memory_analysis_sql_tables.h` 头注释），表结构见 [DatabaseSchema](../architecture/DatabaseSchema.md) 第 8 节：

```sql
-- 排查第一站：任何"空结果"先看这里有没有 err:* / parse_err:*
SELECT key, substr(value, 1, 200) FROM analysis_meta;

-- 陌生进程（按创建时间找"新出现的"）
SELECT pid, ppid, comm, uid, creation_time
FROM processes ORDER BY creation_time DESC LIMIT 50;

-- 外联连接（谁连了可疑地址/端口）
SELECT pid, comm, family, proto, local_addr, local_port,
       remote_addr, remote_port, state
FROM network_connections
WHERE remote_addr IS NOT NULL AND remote_addr != ''
ORDER BY remote_port;

-- 内存中的 bash 历史（磁盘上删掉的这里可能还在）
SELECT pid, comm, command, command_time, history_index
FROM bash_history
WHERE command LIKE '%rm %' OR command LIKE '%curl%' OR command LIKE '%wget%'
ORDER BY command_time;

-- 完整命令行（psaux）
SELECT pid, comm, args FROM cmdline WHERE comm IN ('bash','sshd','nc','curl');

-- 开机时间与运行时长（boottime 键值对）
SELECT * FROM boot_info;
```

**预期看到**：`bash_history.command_time` 是 ISO 8601 字符串（不是 Unix 秒，与磁盘库不同）；`local_port/remote_port` 在库里是字符串（vol3 输出如此）。`creation_time` 同为 ISO 8601。别在 SQL 里拿它们当整数比较。

**为什么要看**：`analysis_meta` 先行——summary 全 0 的"假成功"几乎都是 `err:linux.pslist`（符号问题）或 `err:linux.bash`（插件超时）。

---

## 5. HTTP 侧：/api/forensics/memory/* 与 /memory 页

内存分析没有任务生命周期（不建任务、不写 tasks.json），HTTP 端点只**读已存在的 `_memory.db`**，且靠命名约定定位：取某任务的 `output_raw_db` 路径，去掉 `_raw` 后缀拼 `_memory.db`。因此让页面有数据需要两步对齐：

```bash
# (a) 先用同一镜像建一个 HTTP 磁盘任务（得到任务记录里的镜像名/路径约定）
curl -X POST http://localhost:8666/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"image_path": "/evidence/server.img", "scenarios": ["linux"]}'

# (b) CLI 对同一镜像名跑内存分析时，把输出目录对齐任务目录：
./build/forensic_analyzer /evidence/mem.lime --memory-analyze \
  --vol-symbols-dir ~/.cache/volatility3/symbols \
  --db-dir <任务目录所在约定位置>
```

> 严格地说，命名匹配发生在"任务记录的 raw 库文件名 stem"与 CLI 产出的 `mem_memory.db` stem 之间——**两边 stem 不一致就是 404**（`{"error":"memory db not found"}`）。最稳的做法是让磁盘任务与内存分析针对同一个镜像文件名（`server.img` → `server_raw.db` / `server_memory.db`），CLI 用 `--db-dir` 指到任务目录同处。

端点清单（全部需 `task_id`，只读打开，[C++ REST API](../api_reference/CPP_REST_API.md) 2.7）：

```bash
curl "http://localhost:8666/api/forensics/memory/summary?task_id=<task_id>"
curl "http://localhost:8666/api/forensics/memory/processes?task_id=<task_id>&search=sshd"
curl "http://localhost:8666/api/forensics/memory/network?task_id=<task_id>"
curl "http://localhost:8666/api/forensics/memory/bash-history?task_id=<task_id>&keyword=rm"
curl "http://localhost:8666/api/forensics/memory/boot-info?task_id=<task_id>"
```

前端 `http://localhost:8666/memory` 页选择任务即可查看（进程表可搜索、bash 历史对 `rm -rf` 类关键词高亮）。

**预期看到**：`summary` 返回各表行数概览；`processes` 最多 1000 行按 pid 排序；`bash-history` 支持 keyword 过滤；缺 `_memory.db` 时统一 `404 {"error":"memory db not found"}`（先按第 5 节开头核对命名）。

**为什么要看**：页面是给办案人员看的；API 是给报告脚本用的。两者背后都是同一份 `_memory.db`。

补充：`/memory` 页属于"任务上下文页"（随全局任务选择器切换），如果你在任务下拉里看不到目标任务，先确认磁盘任务存在且状态 completed——内存端点只认任务记录，没有独立入口。

---

## 6. 与磁盘时间线交叉对质

内存证据的价值在"对质"：磁盘说没有的，内存说有的，就是反取证证据。对照 [LinuxIntrusion.md](LinuxIntrusion.md) 产出的 linux.db：

```bash
sqlite3 mem_memory.db "ATTACH DATABASE 'build/data/tasks/<磁盘任务>/linux.db' AS d;
-- 内存 bash 历史里有、磁盘 shell 历史没有的命令（已被清除的痕迹）
SELECT m.command, m.command_time FROM bash_history m
WHERE NOT EXISTS (
  SELECT 1 FROM d.linux_shell_history h
  WHERE h.command = m.command AND h.username IS NOT NULL)
ORDER BY m.command_time DESC LIMIT 100;"
```

三个标准对质方向：

| 内存表 | 磁盘表 | 回答的问题 |
|--------|--------|-----------|
| `bash_history` | `linux_shell_history` | `.bash_history` 被删/被清后内存里残留了什么 |
| `network_connections` | `linux_network_connections`（来自 `/proc/net` 快照类证据） | 哪些连接是取证抓取时仍活跃的（磁盘证据只有历史） |
| `processes`/`cmdline` | `linux_systemd_services`、事件日志 | 无服务定义、无日志的"隐形"进程 |

**预期看到**：对质差集就是报告里"反取证"章节的素材；若两边完全一致，也可据此排除"内存驻留型"手段（写明检查范围与时间点）。

**为什么要看**：单一信源都有盲区；内存/磁盘互相印证是这道题的标准答案。

### 6.1 对质时的三个注意点

1. **时间口径**：内存 `command_time` 是 ISO 8601（通常 UTC），磁盘 `linux_shell_history.timestamp` 是 Unix 秒——先统一时区再比对，否则"差 8 小时"会误判成两条记录。
2. **进程树证据要留全**：`processes` 的 `ppid` 列可重建进程树；对质发现的陌生进程，把它的 pid 同步拿到 `cmdline` 表查完整 argv，两表都查不到的进程才是真正的"隐形"结论。
3. **boot_info 是时间锚**：内存证据的时间解释都应以 boottime 为锚点（开机前的"creation_time"即可疑）；uptime 与抓取时刻的差值还能验证镜像完整性（相差过大说明 dump 不完整或时钟被篡改）。

---

## 排坑清单

1. **CLI 与 HTTP 的"缝合处"靠命名约定**：任务元数据 `memory_db` 字段没有写入方，HTTP 端点实际按"`output_raw_db` 去 `_raw` 拼 `_memory.db`"定位（`RouteHelpers::get_database_path(task_id,"memory")`）。目录/stem 不一致 → 404（[MemoryAnalyzer](../modules/cpp/analyzers/MemoryAnalyzer.md) 第 7 节）。
2. **不受任务生命周期管理**：内存分析不建任务、无审计日志、无进度上报——长时间运行期间 HTTP 侧完全无感知，别在任务页等它。
3. **summary 全 0 ≠ 成功**：vol 缺失/符号拉不下来时优雅降级为"空库 + `analysis_meta` 里的错误串"。排查第一步永远是 `SELECT * FROM analysis_meta WHERE key LIKE 'err:%'`。
4. **每插件一次冷启动**：五个插件各 fork 一个新 vol 进程（各自重新加载符号），大镜像上总耗时约等于 5 次完整 vol 启动；默认 600s/插件超时对超大镜像可能不够。
5. **时间列类型不统一**：`processes.creation_time`、`bash_history.command_time` 是 ISO 8601 字符串，与磁盘库的 Unix 秒整数不同，SQL 直接比较会得出错误结果。
6. **Windows 内存未验证**：探测支持 `PAGEDU64` 与 `windows.*` 插件集，但项目内没有 Windows RAM 镜像实测过（设计文档 out-of-scope，见 [内存取证设计](../superpowers/specs/2026-06-22-memory-forensics-design.md)）；生产使用前自行验证。
7. **`-p` 不是插件名**：vol3 的 `-p` 是 `--plugin-dirs`；本项目封装里插件名是最后一个位置参数。自己手敲 vol 命令时最容易踩（源码注释专门提醒）。
8. **大 dump 的磁盘与内存预算**：banner 自愈会流式扫全文件（64MB 分块），符号 L2 路线要下载约 1.7GB 的 ddeb——取证机先确认磁盘余量；`--vol-symbols-dir` 指向自定义目录时，确保该目录在多机部署间一致，否则换机器又要重新自愈一轮。

---

## 7. 结果可信度自检（设计验证问题）

模块设计时用五个问题验收（[内存取证设计](../superpowers/specs/2026-06-22-memory-forensics-design.md) 第 7 节）。拿真实镜像练手时可以用同样的问题自检链路是否健康：

| 问题 | 数据来源 | 查询要点 |
|------|---------|---------|
| 开机时间/运行时长 | `boot_info`（linux.boottime 键值对） | uptime 与取证抓取时间相减应吻合 |
| SSH 会话数 | `network_connections` | 过滤端口 `22` 的 ESTABLISHED 行 |
| 危险删除命令的时间 | `bash_history` | `command LIKE 'rm %'` 取 `command_time` |
| 快照/备份操作名 | `bash_history` | `command LIKE '%snapshot%'` 类关键词 |
| 解锁/挂载口令 | `bash_history` | `load-key` / `mount` 类命令是否把口令留在 argv 里 |

（原设计对应 Q100–Q104：uptime、SSH 会话数、删除命令时间、ZFS 快照名、ZFS 解锁口令。）

**预期看到**：五个问题都能从 `_memory.db` 得到答案（或明确回答"未捕获"）；任何一项答不出，先回 `analysis_meta` 查对应插件是否 `err:`/超时，再考虑"该数据本就不在内存里"。

**为什么要看**：内存取证最容易犯的错误是把"插件没跑成"当成"证据不存在"——这张表强制你区分两者。

---

## 8. 相关能力：BitLocker FVEK 内存恢复（Windows 侧）

Windows 内存镜像的常规插件集（pslist/cmdline/netstat/registry.hivelist）未经实测（见排坑 6），但仓库内有一套**经过实测的 Windows 内存衍生能力**——从内存 dump 里扫出 BitLocker FVEK 密钥再解密分区：

- Volatility3 插件 `resources/volatility3-plugins/windows/bitlocker_fvek_scan.py`（setup.sh 会安装进 venv）在 Windows 内存镜像上扫描 FVEK；
- 独立解密器 `scripts/bitlocker_fvek_decrypt.py` 用恢复出的 FVEK（32 字节文件）直接做 AES-XTS 解密，产出 TSK 可读的 NTFS 裸镜像：

```bash
python3 scripts/bitlocker_fvek_decrypt.py <encrypted_partition.raw> <fvek_file> <output.raw> \
  [--ewf <E01文件> --partition-offset <扇区数>]   # 支持 E01 直接输入
```

**为什么要看**：这是"内存证据解锁磁盘证据"的完整范例——拿到加密磁盘 + 内存两份证据的案件，先内存后磁盘的顺序能省掉要密码的等待。详见 `scripts/DECRYPTION_FINDINGS.md` 的实测记录。

---

## 延伸阅读

- [MemoryAnalyzer 模块文档](../modules/cpp/analyzers/MemoryAnalyzer.md) — 子进程 poll 驱动、banner 自愈、六张表逐列说明
- [内存取证设计文档](../superpowers/plans/2026-06-22-memory-forensics.md) — 插件选择与验证问题（Q100–Q104）背景
- [scripts/build-vol3-isf.sh](../../scripts/build-vol3-isf.sh) — 三级符号获取策略脚本本体
- [数据库模式](../architecture/DatabaseSchema.md) 第 8 节 — `_memory.db` 表结构定义位置
- [Linux 入侵排查教程](LinuxIntrusion.md) — 磁盘侧时间线与 linux.db 查证（本教程的对质对象）

---


## 练习与扩展实验

- [ ] 练习 1：按本教程流程走一遍后，把关键中间结果（job_id/表行数/端点响应）记录成你自己的实验日志模板。
- [ ] 练习 2：故意制造一次失败（如停掉 Neo4j/输错令牌），观察降级表现并对照 Concurrency/Security 文档的解释。
- [ ] 练习 3：把教程中的 curl 换成你趁手的客户端（httpie/Postman），沉淀成集合。
- [ ] 扩展实验 A：对比"成功路径"与"练习 2 的失败路径"在审计日志/服务日志里的痕迹差异。
- [ ] 扩展实验 B：用最小 fixture（TestFixtures 里的生成脚本）替代真实证据复现全流程，估算耗时量级。
- [ ] 扩展实验 C：将本教程产出接入报告链（/api/reports），完成"证据→报告"闭环一次。
- [ ] 思考题：这条链路的哪一环是 fire-and-forget？失败了主流程会怎样？（对照 DataFlow 第六幕。）
- [ ] 思考题：如果把本流程放进 C/S 模式（agent 执行），哪些步骤要换端点？（对照 ServiceContracts。）
**最后更新**: 2026-08-24（新建，教程）
