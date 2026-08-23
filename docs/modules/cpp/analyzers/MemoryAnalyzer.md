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

## 3. 核心数据结构

### 3.1 目录分层：Core / Volatility / Parsers / Database

- **Core/MemoryAnalyzerCore.cpp**：编排（初始化、镜像类型探测、符号自愈、插件调度）；
- **Volatility/Volatility3Runner.{h,cpp}**：唯一的子进程封装；**VolatilityPlugins.h** 是 vol3 2.x 插件名常量表；
- **Parsers/**：每个插件一个 JSON→行 解析器；**VolJson.h** 是共享取值工具；
- **Database/MemoryAnalysisDatabase.{h,cpp}**：sqlite3 薄封装（互斥锁 + prepared insert + `query()` 通用读）。

三个小而关键的结构：

```cpp
// Volatility3Runner.h:6-11  一次插件运行的结果
struct PluginResult {
    bool ok = false;
    std::string jsonText;    // raw stdout (JSON array)
    std::string stderrText;  // captured stderr
    int exitCode = -1;
};
```

`ok` 的定义在 run 尾部（`exitCode == 0 && !jsonText.empty()`）——退出码 0 但输出为空同样算失败，因为空 JSON 解析不出任何行，留给上层的是误导性的"成功"。

```cpp
// VolatilityPlugins.h:9-23  插件名常量（节选）
namespace MemoryVolatility {
// ---- Linux plugins ----
inline constexpr const char* LINUX_PSLIST   = "linux.pslist";
inline constexpr const char* LINUX_BASH     = "linux.bash";
inline constexpr const char* LINUX_SOCKSTAT = "linux.sockstat";
inline constexpr const char* LINUX_BOOTTIME = "linux.boottime";
inline constexpr const char* LINUX_PSAUX    = "linux.psaux";
// ---- Windows plugins ----
inline constexpr const char* WIN_PSLIST   = "windows.pslist";
inline constexpr const char* WIN_CMDLINE  = "windows.cmdline";
inline constexpr const char* WIN_NETSTAT  = "windows.netstat";
inline constexpr const char* WIN_HIVELIST = "windows.registry.hivelist";
}
```

头注释是一份防坑文档：vol3 2.x **没有** `linux.netstat` 和 `linux.cmdline`——socket 数据必须取自 `linux.sockstat`、命令行取自 `linux.psaux`。插件名写错不会报"插件不存在"，而是让符号探测逻辑误判，这类封装最常见的坑。

```cpp
// VolJson.h:20-28  候选键探测
inline const nlohmann::json* find(const nlohmann::json& row,
                                  std::initializer_list<const char*> keys) {
    if (!row.is_object()) return nullptr;
    for (const char* k : keys) {
        auto it = row.find(k);
        if (it != row.end() && !it->is_null()) return &*it;
    }
    return nullptr;
}
```

这个 9 行的函数是全部解析器的地基：vol3 的 JSON 行键名与插件 TreeGrid 表头完全一致（如 `"OFFSET (V)"`、`"Sock Offset"`），版本间会变，所以按"现名优先、旧名兜底"的列表取值（`VolJson.h:1-11` 的头注释详细记录了这个行为）。

### 3.2 镜像类型探测决定插件集

`detectImageType` 只读文件头 8 字节（MemoryAnalyzerCore.cpp:171-185）：`EMiL` → LiME（Linux），`PAGEDU64` → Windows 内核/完整转储，其余 UNKNOWN（按 Linux 插件集尝试）。Windows 与 Linux 的插件集不同（Core:279-316）：Windows 用 cmdline/netstat/registry.hivelist；Linux 用 sockstat/bash/boottime/psaux（原因见 3.1 的插件名注释）。

## 4. 解析机制走读

**链路一：fork/exec 与 poll 驱动的子进程管理（`Volatility3Runner::run`，`Volatility3Runner.cpp:50-180`）。**

```cpp
// Volatility3Runner.cpp:74-94（子进程侧）
if (pid == 0) {
    // child
    dup2(outPipe[1], STDOUT_FILENO);
    dup2(errPipe[1], STDERR_FILENO);
    // ...
    // NOTE: in vol3 2.x the plugin is a POSITIONAL arg placed LAST.
    // `-p` is --plugin-dirs, NOT the plugin name. Correct order: flags first, plugin last.
    std::vector<std::string> argvStr = {"vol", "-r", "json", "-f", memPath_};
    if (!symbolDir_.empty()) {
        argvStr.push_back("-s");
        argvStr.push_back(symbolDir_);
    }
    argvStr.push_back(pluginName);
    std::vector<const char*> argv;
    argv.reserve(argvStr.size() + 1);
    for (const auto& a : argvStr) argv.push_back(a.c_str());
    argv.push_back(nullptr);
    execv(volBinary_.c_str(), const_cast<char* const*>(argv.data()));
    _exit(127);  // exec failed
}
```

做什么：子进程把 stdout/stderr 重定向到两根管道后 `execv` vol 二进制（无 shell，纯 argv 数组）。参数顺序是 `vol -r json -f <镜像> [-s <符号目录>] <插件名>`——`-r json` 要 JSON 输出、`-f` 指内存镜像、`-s` 有符号目录才附加。注释特意提醒 `-p` 是 `--plugin-dirs` 不是插件名，顺序错了是这类封装最常见的坑。`execv` 失败 `_exit(127)` 而不是 return——子进程绝不能掉回父进程的代码路径。

```cpp
// Volatility3Runner.cpp:106-117、155-167（父进程侧）
// Set both pipe read-ends non-blocking so poll() + drain can run concurrently
// with the child. This avoids a deadlock when a plugin emits more JSON than
// the OS pipe buffer (~64KB): without draining, the child blocks on write
// and never exits, hanging the parent until timeout.
    setNonblock(outFd);
    setNonblock(errFd);
// ...
        if (std::chrono::steady_clock::now() > deadline) {
            kill(pid, SIGTERM);
            timedOut = true;
            waitpid(pid, &status, 0);
            drain(outFd, outBuf);
            drain(errFd, errBuf);
            break;
        }
        // Block briefly on the pipes so we don't spin; wakes when data arrives.
        poll(pfds, 2, 100);  // 100ms cap so the deadline check runs promptly
```

父进程把两根管道设为非阻塞，循环里"先抽干 → WNOHANG 查子进程 → 查超时 → poll 100ms"。为什么必须边等边抽：插件输出的 JSON 超过管道缓冲（约 64KB）时子进程会阻塞在 write 上、永远不退出，父进程跟着挂到超时（第 107-110 行注释原文）——pslist 在大镜像上的输出轻松超过这个量。超时路径：SIGTERM → 同步 waitpid 收尸 → 最后一次抽干（残留尾部字节）→ stderr 追加 `[timeout after Ns]` 标记。成功判定 = 退出码 0 **且** stdout 非空（第 178 行）。

**链路二：Linux 符号自愈——流式扫 banner（`detectKernelVersion`，`Core:73-127`）。**

```cpp
// MemoryAnalyzerCore.cpp:75-96（节选）
static std::string detectKernelVersion(const std::string& memPath,
                                       std::string* bannerOut = nullptr) {
    constexpr std::streamsize CHUNK = 64 * 1024 * 1024;      // 64MB read window
    // The kernel banner can be very deep in a large dump (it appeared at 3.5GB
    // in our 4GB test image), so scan the whole file, not just the head.
    const std::string needle = "Linux version ";
    std::ifstream f(memPath, std::ios::binary);
    if (!f) return "";
    std::string tail;  // overlap from the previous chunk (needle.size()-1 bytes)
    while (true) {
        std::string buf;
        buf.resize(CHUNK);
        f.read(&buf[0], buf.size());
        std::streamsize n = f.gcount();
        if (n <= 0) break;
        buf.resize(n);
        // Search in tail+buf so a banner straddling the boundary is caught.
        std::string window = tail + buf;
```

做什么：Linux 镜像必须有与内核版本**完全匹配**的 ISF 符号表，否则所有插件报 "No Linux banners found"。整个自愈流程（Core:210-277）是：先跑一次 pslist；stderr 命中 banner/symbol 关键词即判定符号缺失（:224-229）→ `detectKernelVersion` 流式扫描整个镜像找 `Linux version ` 串 → `autoFetchSymbols`（:147-169）调 `scripts/build-vol3-isf.sh <version>`（社区仓库 CDN，dwarf2json 兜底）→ ISF 落到 `~/.cache/volatility3/symbols/`（:139-142）→ `-s` 指过去**重试一次** pslist；再失败就打印手工修复指引并干净退出（:268-275，只产出一个带 `err:*` 元数据的空库）。这段代码的三个工程细节：64MB 分块 + 尾部重叠窗口防跨块漏检（banner 可能横跨两块边界）；版本号必须以数字开头才认（:115-121）——"GNU/Linux version of ..." 这类假命中被排除；脚本"报成功"后还要确认 ISF 文件真的落盘（`autoFetchSymbols` 的 exists 检查），防脚本静默失败。

**链路三：JSON 解析与候选键兜底（`NetworkParser.cpp` + `VolJson.h`）。**

```cpp
// Parsers/NetworkParser.cpp:13-35（节选）
size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertNetworkConnection(
            num(c, {"Sock Offset", "Offset"}),
            static_cast<int>(num(c, {"PID"})),
            static_cast<int>(num(c, {"TID", "PID"})),
            str(c, {"Process Name", "Process"}),
            // ...
            str(c, {"Source Addr", "LocalAddr"}),
            str(c, {"Destination Addr", "ForeignAddr", "RemoteAddr"}),
            str(c, {"State"}),
            num(c, {"NetNS"}));
        ++n;
    }
    return n;
}
```

做什么：`runAndStore`（Core:52-64）把 stdout `json::parse` 后交给对应 parser；parser 对每行用候选键列表取值——第一个键是当前 vol3 版本的列名，后面的（`LocalAddr/ForeignAddr/RemoteAddr`）是旧版兜底。`VolJson::num` 还要处理"端口以字符串渲染"的怪癖（sockstat 的 Source/Destination Port 是字符串，`VolJson.h:37-50` 的 `num` 同时接受数字与数字串）。错误路径分层：插件运行失败记 `err:<plugin>`、JSON 解析失败记 `parse_err:<plugin>`（`runAndStore` 的两个 setMeta），其他插件继续——一个插件崩不掉整场分析，事后可从 `analysis_meta` 表复盘。

## 5. 产出表结构说明（_memory.db 六张表）

表结构在 `DatabaseManager/SQL/memory_analysis_sql_tables.h:13-88`，头注释明确"列名镜像 vol3 2.x JSON 字段名以便 1:1 映射"：

| 表 | 关键列 | 取证含义 |
|----|--------|---------|
| `processes`（:14-27） | `offset/pid/tid/ppid/comm/uid/euid/creation_time` | 进程清单；`ppid` 树重建 + `creation_time`（ISO 8601）定位"何时出现的陌生进程" |
| `network_connections`（:29-46） | `pid/comm/family/type/proto/local_addr/remote_addr/remote_port/state/netns` | 从 linux.sockstat 派生（表内注释说明 vol3 无 linux.netstat）；`remote_port` 与 `local_port` 各有索引支撑"外联了哪个端口"查询 |
| `bash_history`（:48-57） | `pid/comm/command/command_time/history_index` | 内存中的 bash 历史——磁盘上删掉的历史这里可能还在；`command_time` 有索引 |
| `boot_info`（:59-64） | `key/value` | linux.boottime 的键值对（开机时间、运行时长） |
| `cmdline`（:66-73） | `pid/comm/args` | 从 linux.psaux 派生的完整命令行（含参数） |
| `analysis_meta`（:75-80） | `key/value` | 运行元数据：`image_type`、`err:<plugin>`、`parse_err:<plugin>`——排查第一站 |

## 6. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| AnalysisOrchestrator | 唯一调用方（runMemoryAnalysis，AnalysisOrchestrator.cpp:534-564）；`--vol-symbols-dir` 直通 `setSymbolDir` |
| MemoryAnalysisSQL（DatabaseManager/SQL/memory_analysis_sql*.h） | 表结构（:14-75 六张表）与 INSERT 语句（memory_analysis_sql_crud.h）定义处 |
| MemoryForensicsRoutes | HTTP 读侧；经 RouteHelpers::get_database_path(task_id,"memory") 按命名约定定位库（RouteHelpers.cpp:71-86），`SQLITE_OPEN_READONLY` 打开、缺库 404（MemoryForensicsRoutes.cpp:51-53） |
| scripts/build-vol3-isf.sh | 符号自愈调用的外部脚本；findProjectRoot 靠它定位项目根（Core:130-136） |
| python_service/.venv/bin/vol | 实际被 exec 的 vol3 二进制（resolveVolBinary 的首选：CWD → 向上 6 层 → PATH，Volatility3Runner.cpp:23-48） |

## 7. 注意事项与已知问题

- **CLI 与 HTTP 的"缝合处"靠命名约定**：`metadata["memory_db"]` 没有任何写入方（全库 grep 仅 RouteHelpers 读取），HTTP 端点实际走 fallback——把任务的 `output_raw_db` 去掉 `_raw` 后缀拼 `_memory.db`（RouteHelpers.cpp:77-85）。因此 `/memory` 页要能看到数据，前提是**存在一个以同一镜像为源的 HTTP 任务**且 CLI 用相同 `--db-dir` 跑过内存分析；两边目录不一致就 404。
- **内存分析不受任务生命周期管理**：不建任务、不写 tasks.json、无审计日志（对比 FileFilter 有 FILE_FILTER 审计）；长时间运行期间 HTTP 侧完全无感知。
- **依赖外部环境**：vol 未装 / ISF 拉不下来时优雅降级为"空库 + meta 里的错误串"，HTTP summary 会返回 0 计数而不是错误——排查时先查 `SELECT * FROM analysis_meta WHERE key LIKE 'err:%'`。
- **每插件一次冷启动**：每个插件都 fork 一个新 vol 进程（各自重新加载符号），大镜像上 pslist+4 插件约等于 5 次完整 vol 启动开销；600s 超时对超大镜像可能不够（`run` 的 timeoutSeconds 是参数但调用方都传默认值）。

## 8. 如何验证与扩展

- **验证**：`python_service/.venv/bin/vol` 就位后，`./build/forensic_analyzer <lime.dump> --memory-analyze --db-dir /tmp/m`，然后 `sqlite3 /tmp/m/<stem>_memory.db "SELECT COUNT(*) FROM processes; SELECT key FROM analysis_meta;"`；HTTP 侧再建一个同镜像的任务，`curl 'localhost:8080/api/forensics/memory/summary?task_id=<id>'` 验证命名约定命中。
- **扩展新插件**：① VolatilityPlugins.h 加常量；② Parsers/ 写一个 `size_t fn(const json&, MemoryAnalysisDatabase&)`（参考 NetworkParser.cpp）；③ 需要新表时在 memory_analysis_sql_tables.h 加 CREATE、crud.h 加 INSERT，并给 MemoryAnalysisDatabase 加 typed insert；④ 在 analyzeMemoryData 的 Windows/Linux 分支（Core:279-316）挂上 `runAndStore`。表格驱动程度不高（对比 AndroidLLMAnalysisService 的四件套），但模式统一。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
