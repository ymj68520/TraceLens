# MemoryAnalyzer（src/analyzers/MemoryAnalyzer/）

> **一句话**：内存取证分析器——fork/exec 外部 Volatility3（`vol`）二进制跑 pslist/sockstat/bash 等插件，把 JSON 输出解析进 `<镜像>_memory.db`（进程/网络/bash 历史/启动信息/cmdline/元数据），Linux 内核符号缺失时还能从镜像里扫出内核版本并自动拉取 ISF 符号表。

## 1. 为什么有这个模块

磁盘镜像流水线（ImageAnalyzer → FileFilter → …）回答的是"文件系统里有什么"；而攻击者的痕迹往往在**内存**里：被删除的进程、活跃 socket、内存中的 bash 历史。这些只有 Volatility3 这类专用工具能挖。本模块把 Volatility3 包成"给一个 RAM 镜像 → 产出一个结构化 SQLite 库"的纯函数式黑盒，让内存证据与磁盘证据使用同一种消费方式（前端页面/HTTP 端点直接查表）。

与磁盘流水线的关系是**旁路而非一环**：RAM dump 不是文件系统镜像，走不了 TSK 管线（AnalysisOrchestrator.cpp:176-181 注释明确说明这一点）。

## 2. 在系统中的位置

```
CLI: forensic_analyzer <镜像> --memory-analyze [--vol-symbols-dir <dir>]
  └─ CommandLineParser.cpp:249-252 解析
       └─ AnalysisOrchestrator.cpp:179-181 提前 return runMemoryAnalysis(args)   ← 绕过整条磁盘流水线
            └─ AnalysisOrchestrator.cpp:534-564
                 MemoryAnalyzer(image) → initialize() → analyzeMemoryData()
                      ├─ Volatility3Runner（fork/exec python_service/.venv/bin/vol）
                      ├─ Parsers/*（vol3 JSON → 类型化 insert）
                      └─ Database/MemoryAnalysisDatabase → <base>_memory.db
                                 ↑ 只写这一个库，无 _raw.db / _files.db

HTTP 读侧（另一条独立链路）：
  GET /api/forensics/memory/{summary,processes,network,bash-history,boot-info}?task_id=
  （MemoryForensicsRoutes.cpp:11-20，按命名约定找 <base>_memory.db，见 §6）
  前端 /memory 页 ← web/src/services/memoryService.js
```

**查证结论**：`--memory-analyze` 是 **CLI 专用旁路子命令**，不进 HTTP 任务流水线——TaskManagerAnalysis.cpp 全文没有任何 MemoryAnalyzer 引用；HTTP 端点只负责"读已存在的 _memory.db"。

## 3. 核心概念与设计

### 3.1 目录分层：Core / Volatility / Parsers / Database

- **Core/MemoryAnalyzerCore.cpp**：编排（初始化、镜像类型探测、符号自愈、插件调度）；
- **Volatility/Volatility3Runner.{h,cpp}**：唯一的子进程封装；**VolatilityPlugins.h** 是 vol3 2.x 插件名常量表；
- **Parsers/**：每个插件一个 JSON→行 解析器；**VolJson.h** 是共享取值工具；
- **Database/MemoryAnalysisDatabase.{h,cpp}**：sqlite3 薄封装（互斥锁 + prepared insert + `query()` 通用读）。

### 3.2 镜像类型探测决定插件集

`detectImageType` 只读文件头 8 字节（MemoryAnalyzerCore.cpp:171-185）：`EMiL` → LiME（Linux），`PAGEDU64` → Windows 内核/完整转储，其余 UNKNOWN（按 Linux 插件集尝试）。Windows 与 Linux 的插件集不同（Core:279-316）：Windows 用 cmdline/netstat/registry.hivelist；Linux 用 sockstat/bash/boottime/psaux——因为 vol3 2.x **没有** `linux.netstat` 和 `linux.cmdline`，socket 数据取自 `linux.sockstat`、命令行取自 `linux.psaux`（VolatilityPlugins.h:5-9 注释，Core:290-315）。

### 3.3 符号自愈：从镜像里找内核版本再拉 ISF

Linux 镜像必须有与内核版本完全匹配的 ISF 符号表，否则所有插件报 "No Linux banners found"。设计上的应对（Core:210-277）：

1. 先跑一次 pslist；stderr 命中 banner/symbol 关键词即判定符号缺失（:224-229）；
2. `detectKernelVersion`（:73-127）**流式扫描整个镜像**找 `Linux version ` 串——banner 可能埋在几 GB 深处（注释：4GB 测试镜像里出现在 3.5GB 处），64MB 分块 + 尾部重叠窗口防止跨块漏检，且要求版本号以数字开头以排除 "GNU/Linux version of ..." 之类的假命中（:115-121）；
3. `autoFetchSymbols`（:147-169）调 `scripts/build-vol3-isf.sh <version>`（社区仓库 CDN，dwarf2json 兜底），ISF 落到 `~/.cache/volatility3/symbols/`（:139-142），然后 `-s` 指过去**重试一次** pslist；再失败就打印手工修复指引并干净退出（:268-275，只产出一个带 `err:*` 元数据的空库）。

### 3.4 错误进 analysis_meta，不中断

每个插件失败都记 `setMeta("err:<plugin>", stderr)` 或 `parse_err:<plugin>`（Core:52-64），其他插件继续——一个插件崩不掉整场分析，事后可从 `analysis_meta` 表复盘。

## 4. 工作流程走读

**initialize**（Core:23-50）：输出库默认取镜像同目录 `<stem>_memory.db`（:24-29）；`resolveVolBinary` 找 vol 二进制（项目 venv → 向上 6 层 → PATH，Volatility3Runner.cpp:23-48），找不到只告警不报错（分析会产出空库，Core:39-41）；写 `image_type` 元数据。

**analyzeMemoryData**（Core:187-319）主循环。Volatility3Runner::run（Volatility3Runner.cpp:50-180）是最值得读的一段：

```cpp
std::vector<std::string> argvStr = {"vol", "-r", "json", "-f", memPath_};
if (!symbolDir_.empty()) { argvStr.push_back("-s"); argvStr.push_back(symbolDir_); }
argvStr.push_back(pluginName);            // vol3 2.x: 插件是最后一个位置参数
...
execv(volBinary_.c_str(), const_cast<char* const*>(argv.data()));
```

（Volatility3Runner.cpp:83-93。注释特意提醒 `-p` 是 `--plugin-dirs` 不是插件名——顺序错了是这类封装最常见的坑。）

父进程把两根管道设为非阻塞，用 `poll()` 边等边抽干（:106-124）——否则插件输出的 JSON 超过管道缓冲（约 64KB）时子进程写阻塞、永远不退出，父进程挂到超时（:107-110 注释）。默认 600s 超时后 SIGTERM（:128、155-161）。成功判定 = 退出码 0 **且** stdout 非空（:178）。

之后 `runAndStore`（Core:52-64）把 stdout `json::parse` 后交给对应 parser 落库。Parsers 侧统一用 VolJson 的候选键探测（VolJson.h:24-32）——vol3 的 JSON 列名与插件 TreeGrid 表头完全一致（如 `"OFFSET (V)"`、`"Sock Offset"`），版本间会变，所以按"现名优先、旧名兜底"的列表取值。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| AnalysisOrchestrator | 唯一调用方（runMemoryAnalysis，AnalysisOrchestrator.cpp:534-564）；`--vol-symbols-dir` 直通 `setSymbolDir` |
| MemoryAnalysisSQL（DatabaseManager/SQL/memory_analysis_sql*.h） | 表结构（processes/network_connections/bash_history/boot_info/cmdline/analysis_meta，memory_analysis_sql_tables.h:14-75）与 INSERT 语句定义处 |
| MemoryForensicsRoutes | HTTP 读侧；经 RouteHelpers::get_database_path(task_id,"memory") 按命名约定定位库（RouteHelpers.cpp:71-86） |
| scripts/build-vol3-isf.sh | 符号自愈调用的外部脚本；findProjectRoot 靠它定位项目根（Core:130-136） |
| python_service/.venv/bin/vol | 实际被 exec 的 vol3 二进制（首选安装位置） |

## 6. 注意事项与已知问题

- **CLI 与 HTTP 的"缝合处"靠命名约定**：`metadata["memory_db"]` 没有任何写入方（全库 grep 仅 RouteHelpers 读取），HTTP 端点实际走 fallback——把任务的 `output_raw_db` 去掉 `_raw` 后缀拼 `_memory.db`（RouteHelpers.cpp:77-85）。因此 `/memory` 页要能看到数据，前提是**存在一个以同一镜像为源的 HTTP 任务**且 CLI 用相同 `--db-dir` 跑过内存分析；两边目录不一致就 404。
- **内存分析不受任务生命周期管理**：不建任务、不写 tasks.json、无审计日志（对比 FileFilter 有 FILE_FILTER 审计）；长时间运行期间 HTTP 侧完全无感知。
- **依赖外部环境**：vol 未装 / ISF 拉不下来时优雅降级为"空库 + meta 里的错误串"，HTTP summary 会返回 0 计数而不是错误——排查时先查 `SELECT * FROM analysis_meta WHERE key LIKE 'err:%'`。
- **每插件一次冷启动**：每个插件都 fork 一个新 vol 进程（各自重新加载符号），大镜像上 pslist+4 插件约等于 5 次完整 vol 启动开销；600s 超时对超大镜像可能不够（`run` 的 timeoutSeconds 是参数但调用方都传默认值）。
- **route 侧只读打开**：MemoryForensicsRoutes 用 `SQLITE_OPEN_READONLY`（MemoryForensicsRoutes.cpp:53），缺库 404 而不是在证据目录里凭空造空文件——这是有意的（:51-52 注释）。

## 7. 如何验证与扩展

- **验证**：`python_service/.venv/bin/vol` 就位后，`./build/forensic_analyzer <lime.dump> --memory-analyze --db-dir /tmp/m`，然后 `sqlite3 /tmp/m/<stem>_memory.db "SELECT COUNT(*) FROM processes; SELECT key FROM analysis_meta;"`；HTTP 侧再建一个同镜像的任务，`curl 'localhost:8080/api/forensics/memory/summary?task_id=<id>'` 验证命名约定命中。
- **扩展新插件**：① VolatilityPlugins.h 加常量；② Parsers/ 写一个 `size_t fn(const json&, MemoryAnalysisDatabase&)`（参考 NetworkParser.cpp）；③ 需要新表时在 memory_analysis_sql_tables.h 加 CREATE、crud.h 加 INSERT，并给 MemoryAnalysisDatabase 加 typed insert；④ 在 analyzeMemoryData 的 Windows/Linux 分支（Core:279-316）挂上 `runAndStore`。表格驱动程度不高（对比 AndroidLLMAnalysisService 的四件套），但模式统一。

**最后更新**: 2026-08-23（新建，解释式）
