# AnalysisOrchestrator（src/AnalysisOrchestrator.{h,cpp}）

> **一句话**：CLI 模式的总调度器——main.cpp 解析完命令行后把控制权交给它，由它按序驱动"镜像分析→过滤→分类→平台分析→时间线→（可选）DLL/报告/文本导出"的完整流水线，并把独立子命令（索引/搜索、雕复、提取、DLL 分析、内存分析）路由到各自的执行函数。

## 1. 为什么有这个模块

系统有两种运行形态：HTTP 服务形态（TaskManager 按阶段调度、支持并发任务与进度上报）和 CLI 形态（单镜像、单进程、一条命令跑完）。两种形态**共享同一批分析器**（ImageAnalyzer、FileClassifier、EventExtractor、平台 Analyzer……），但编排逻辑不同：HTTP 版要更新阶段进度、处理任务取消；CLI 版要处理命令行旗标组合、密码输入、退出码。

AnalysisOrchestrator 承担 CLI 侧的编排：它不实现任何分析能力，价值在于**固化正确的执行顺序与依赖关系**——分类必须发生在平台分析之前（平台分析器要往 files.db 写工件，而 files.db 由分类器创建，见 `AnalysisOrchestrator.cpp:272-273` 先 reset 释放锁的注释）；时间线必须消费过滤后的 raw.db（effectiveRawDb，`:231-245`）；DLL 关联分析要在 Windows 工件就位后进行（`:354-367`）。把这些顺序散在 main 里会迅速失控，集中在一个类里才可被测试与复述。

它同时是**特殊数据源的分流器**：Android 逻辑提取（目录/zip/MIUI 备份）和内存镜像（LiME/raw RAM）根本不是 TSK 磁盘镜像，走不了标准流水线，`runAnalysis` 开头就把它们分流到专属路径（`:170-181`）。

## 2. 在系统中的位置

上游是 `main.cpp`：初始化 PathManager/ConfigManager/AuditLog 后按旗标路由（`main.cpp:102-123`）——http_port→`runHTTPServer`；index/search→`runFullTextSearch`；carve→`runFileCarving`；extract-*→`runExtraction`；analyze-dlls-only→`runDLLAnalysis`；默认→`runAnalysis`。

下游是被它实例化并排序的整条分析链：

```
runAnalysis(TSK 镜像主路径):
 [1/4] ImageAnalyzer ──> <base>_raw.db
 [2/4] FileFilter(general_forensics) ──> <base>_filtered.db   (失败/空则退回 raw)
 [3/4] FileClassifier(场景感知) ──> <base>_files.db
 [4/4] 平台 Analyzer(Android/Windows/Linux, 工件并入 files.db)
       EventExtractor ──> <base>_events.db (+ import 平台工件)
       (可选) DLLAnalyzer / ReportGenerator / TextDumpExporter(--dump-text)
```

与 HTTP 形态的对照：TaskManagerAnalysis.cpp 执行同样的分析器序列，但产物落在 `data/tasks/<id>/` 下的固定文件名（PathManager.getTaskDbPaths），而 CLI 用 `<镜像名>_<阶段>.db` 前缀（`:196-202`，可加 `--db-dir` 前缀，`:137-147`）。两边的"平台工件进 files.db"约定一致，这也是理解 CLI/HTTP 差异的最短路径。

## 3. 核心概念与设计

**"编排即数据流"**：类的状态几乎为零（全部静态方法，`AnalysisOrchestrator.h:13-42`），函数间传递的是数据库路径字符串。核心变量是 `effectiveRawDb`（`:223-241`）——过滤成功且包含文件时指向 filtered.db，否则回退 raw.db，下游（分类、平台分析、时间线）统一用它。这个"降级链"是 CLI 健壮性的缩影：任何可选步骤失败都打警告继续，绝不让"过滤失败"杀死整个分析。

**场景旗标映射**：`--android-analyze/--windows-analyze/--linux-analyze` 转成 FileClassifier 的 SceneType（`:252-264`），并决定跑哪个平台 Analyzer（`:276-327`）。平台分析器通过 `setOutputDatabasePath(fileDbPath)` 把工件写进统一 files.db（如 `:287`），替代了旧的独立平台库输出——CLI 与 HTTP 在此对齐。

**安全输入三件套**（匿名命名空间，`:39-129`）：`readPasswordFromStdin` 关终端回显读密码（termios/Windows 双实现）、`readPasswordFromDescriptor` 从 fd 读（供 `--backup-password-fd`），并刻意让安全输入覆盖 argv 传入的明文密码并打警告（`:184-189, 496-508`）——密码不落 ps/命令历史是取证工具的合规底线。

**库名约定**：`getBaseName` 去扩展名（`:133-135`），产物为 `<base>_raw.db/_events.db/_files.db/_dll.db/_memory.db/_report.md`；`runExtraction` 还会做反向换算（传入 `_raw.db` 自动改用 `_files.db` 提取，`:575-579`）与按常见扩展名（.dd/.e01/.raw 等）猜镜像路径（`:586-597`）。

**runAndroidLogicalAnalysis / runMemoryAnalysis**（`:468-532, 534-565`）：非 TSK 数据源的专属入口，产物只有 `<base>_files.db`（Android 逻辑）或 `<base>_memory.db`（内存，Volatility3），不生成 raw/events——头文件注释（`AnalysisOrchestrator.h:21-42`）明确了这一边界。

### 3.1 核心接口清单（全部静态，AnalysisOrchestrator.h:15-43）

| 签名 | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `static int runAnalysis(const CommandLineArgs& args)` | TSK 镜像主流水线（过滤/分类/平台/时间线/可选段） | main.cpp 默认分支 | 核心步骤失败返回 1；可选步骤失败警告后继续 |
| `static int runExtraction(args)` | `--extract-*` 提取子命令 | main.cpp | 参数/库缺失返回 1 |
| `static int runFullTextSearch(args)` | `--index/--search` 全文检索 | main.cpp | 索引/查询异常返回 1 |
| `static int runFileCarving(args)` | `--carve` 雕复（FileCarver） | main.cpp | 镜像缺失返回 1 |
| `static int runHTTPServer(int port)` | 启动 Crow/asio HTTP 服务 | main.cpp（http_port 分支） | 服务异常返回非 0 |
| `static int runDLLAnalysis(args)` | `--analyze-dlls-only` 独立 DLL 库分析 | main.cpp | 库不可用返回 1 |
| `static int runMemoryAnalysis(args)` | 内存镜像（Volatility3），只产 `<base>_memory.db` | runAnalysis 分流 / main.cpp | 失败返回 1 |
| （私有）`static int runAndroidLogicalAnalysis(args)` | Android 逻辑提取（dir/zip/MIUI） | runAnalysis 分流 | 失败返回 1 |
| （私有）`static std::string getBaseName(path)` / `getDatabaseDir(args)` | 库名前缀与 `--db-dir` 目录 | 内部 | 无 |

调用契约：所有方法吃同一个 `CommandLineArgs` 结构（CommandLineParser 产物），返回进程退出码——编排层用 int 而非异常表达终态，异常只在 `runAnalysis` 内部的 try 块出现并在末尾 catch-all。

## 4. 工作流程走读

`forensic_analyzer image.dd --linux-analyze --analyze-dlls --generate-report` 的执行序：

1. 前置检查与分流（`:149-181`）：镜像存在性；android_source 为 dir/zip/miui-backup 或 memory_analyze 时改道。
2. 解密密码处理（`:183-190`）：`--key-password-stdin` 时安全读取。
3. `[1/4]` ImageAnalyzer：setXFSMode/解密选项后 `analyze()` + `extractToDatabase(rawDbPath)`（`:206-219`）。
4. `[2/4]` FileFilter：默认 profile `general_forensics`，产 filtered.db；included_files 为 0 或异常时回退（`:227-245`）。
5. `[3/4]` FileClassifier：设 SceneType::LINUX 后 `classifyAndExtract()`，成功后 **`classifier.reset()`**（`:273`）释放 files.db 写锁。
6. `[4/4]` 平台段：LinuxFilesAnalyzer 以 effectiveRawDb 初始化、工件写 files.db（`:312-327`）；随后 EventExtractor 生成 events.db 并 `importLinuxArtifacts(fileDbPath)`（`:331-339`）。
7. 可选段：DLLAnalyzer（关联只读 files.db，`:344-377`）、ReportGenerator（files+events 双库出 Markdown，`:380-391`）、TextDumpExporter（全量文件→Markdown，走 Python markitdown 服务，`:404-455`——含软限额、断点复用与服务不可用提示）。
8. 汇总输出与退出码（`:457-465`）；任何未捕获异常统一 `Fatal error` 返回 1。

子命令路径独立成函数：`runFullTextSearch`（索引+查询，见 FullTextSearch.md 第 4 节）、`runFileCarving`（FileCarver 雕复，`:690-701`）、`runExtraction`（见 FileExtractor.md 第 4 节）、`runDLLAnalysis`（独立 DLL 库分析，`:710-752`）、`runHTTPServer`（起 Crow/asio 服务，`:703-708`）。

### 4.1 代码走读：特殊数据源分流（AnalysisOrchestrator.cpp:167-190）

```cpp
    // Android logical extraction (directory or zip) does not need — and cannot
    // use — the TSK disk-image pipeline. Route it to a dedicated path that
    // runs only the Android analyzer against the data source directly.
    if (args.android_analyze &&
        (args.android_source == "dir" || args.android_source == "zip" ||
         args.android_source == "miui-backup")) {
        return runAndroidLogicalAnalysis(args);
    }

    // Memory (RAM) image analysis also bypasses the TSK disk-image pipeline:
    // a raw RAM dump is not a filesystem image. Route to a dedicated path that
    // runs Volatility3 and writes <baseName>_memory.db only.
    if (args.memory_analyze) {
        return runMemoryAnalysis(args);
    }

    std::string decryptPassword = args.decrypt_password;
    if (args.enable_decryption && args.decrypt_password_stdin) {
        if (!decryptPassword.empty()) {
            std::cerr << "Warning: Both --key-password-stdin and deprecated --key-password were "
                      << "provided; using the password read from stdin." << std::endl;
        }
        if (!readPasswordFromStdin(decryptPassword)) return 1;
    }
```

逐块解释：两个分流判断都放在**任何库文件创建之前**——晚一分流就会在磁盘上留下用不到的 `<base>_raw.db` 空壳。判断条件写得很保守：Android 分流要求 android_analyze **且** source 是三种逻辑形态之一（TSK 镜像里的 Android 分区仍走主流水线）；内存分流只看 memory_analyze 一个旗标。注释把"为什么分流"讲透（逻辑提取不是磁盘镜像、RAM dump 不是文件系统镜像），这是给未来维护者的护栏——不读懂注释就"统一"两条路径会直接坏功能。密码段的覆盖语义：argv 明文密码与 stdin 密码同时给时**安全输入赢**，只打一条 Warning 而不是报错——兼容旧脚本的同时把新习惯立起来；stdin 读取失败（EOF/终端异常）直接 return 1，宁可不起也不拿空密码去解密。

### 4.2 代码走读：effectiveRawDb 降级链（AnalysisOrchestrator.cpp:221-245）

```cpp
        // Step 2: Apply file filter (default: general_forensics)
        // The filtered database is used by all downstream processors
        std::string effectiveRawDb = rawDbPath;
        std::string effectiveProfile = args.filter_profile.empty()
            ? "general_forensics" : args.filter_profile;

        std::cout << "[2/4] Applying file filter: " << effectiveProfile << "..." << std::endl;
        std::string filteredDbPath = prefix + baseName + "_filtered.db";

        try {
            FileFilter filter;
            auto stats = filter.applyFilterByName(rawDbPath, filteredDbPath, effectiveProfile);

            if (stats.included_files > 0) {
                effectiveRawDb = filteredDbPath;
                std::cout << "✓ Filtered database: " << filteredDbPath
                          << " (" << stats.included_files << "/" << stats.total_files
                          << " files)\n" << std::endl;
            } else {
                std::cerr << "Warning: Filter excluded all files. Using unfiltered data." << std::endl;
            }
        } catch (const std::exception& e) {
            std::cerr << "Warning: Filter failed: " << e.what() << std::endl;
            std::cerr << "Continuing with unfiltered data." << std::endl;
        }
```

逐块解释：`effectiveRawDb` 先初始化为 raw.db——**降级是默认态**，过滤是"尝试升级"：只有 included_files > 0 才切到 filtered.db，三条失败路径（画像不存在抛异常、过滤结果为空、库打不开返回全零 stats）全部落回全量数据。这个设计的价值判断是：过滤是优化（削下游成本），不是正确性依赖——宁可分析慢也不能因画像问题停摆。try 块圈住整个 FileFilter 调用，catch 的是 `std::exception`（applyFilterByName 的 runtime_error），警告两行把"失败了"和"继续用未过滤"都说清楚，脚本作者看 stderr 就能定位。`✓` 输出行带 `included/total` 分数，是事后核对过滤率的唯一 CLI 信号。

### 4.3 代码走读：reset 释放锁与平台段写入（AnalysisOrchestrator.cpp:272-298）

```cpp
        // Release classifier's database lock before platform analyzers write to files.db
        classifier.reset();

        // Step 4: Scene-specific analysis (writes artifacts into files.db)
        if (args.android_analyze) {
            std::cout << "[Android] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(effectiveRawDb);
            if (!dbMgr->initialize()) {
                std::cerr << "Error: Failed to initialize DatabaseManager for Android analysis" << std::endl;
            } else {
                auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(args.image_path, dbMgr.get());
                if (!args.wechat_password.empty()) {
                    androidAnalyzer->setWeChatPassword(args.wechat_password);
                }
                // Write Android artifacts into files.db for unified scene database
                androidAnalyzer->setOutputDatabasePath(fileDbPath);
                if (androidAnalyzer->initialize()) {
                    androidAnalyzer->analyzeAndroidData();
                    std::cout << "✓ Android analysis complete\n" << std::endl;
                }
            }
        }
```

逐块解释：`classifier.reset()` 一行是整个平台段的**前置条件**——unique_ptr 析构触发 FileClassifier 的 closeDatabases，files.db 的 SQLite 连接（含 WAL 写事务能力）随之释放；不 reset 的话平台分析器打开同一文件会遇到锁竞争（WAL 允许多读单写）。注释把这层因果写明，防止有人"优化"掉这个看似多余的 reset。Android 段的结构是"两重防御性初始化"：DatabaseManager 失败只报错继续（else 分支整个跳过，但流程不断）；AndroidAnalyzer 的 initialize 失败则**静默跳过 analyze**——注意 `if (androidAnalyzer->initialize())` 为假时没有任何错误输出，这是第 6 节"平台失败退出码仍 0"问题的具体源头。`setOutputDatabasePath(fileDbPath)` 是统一场景库约定的落点：平台工件不再进独立 android.db 而是并入 files.db，与 HTTP 形态对齐。`dbMgr.get()` 裸指针转交所有权语义——dbMgr 的 unique_ptr 存活到 if 块结束，覆盖 analyzer 的整个使用期，安全。

### 4.4 代码走读：时间线生成与工件回灌（AnalysisOrchestrator.cpp:329-341）

```cpp
        // Step 5: Generate timeline (uses effective raw db)
        std::cout << "[4/4] Generating timeline..." << std::endl;
        auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
        if (eventExtractor->extractEvents()) {
            // Import scene artifacts from files.db (where platform analyzers wrote)
            if (args.android_analyze && fs::exists(fileDbPath))
                eventExtractor->importAndroidArtifacts(fileDbPath);
            if (args.windows_analyze && fs::exists(fileDbPath))
                eventExtractor->importWindowsArtifacts(fileDbPath);
            if (args.linux_analyze && fs::exists(fileDbPath))
                eventExtractor->importLinuxArtifacts(fileDbPath);
            std::cout << "✓ Timeline: " << eventDbPath << "\n" << std::endl;
        }
```

逐块解释：EventExtractor 的输入是 **effectiveRawDb 而非 raw.db**——时间线也消费过滤后的数据，与分类/平台段保持同一视野；这让"过滤画像漏掉的文件"从全链路（清单、分类、时间线）一致消失，不会出现"时间线里有但 files.db 里没有"的错位。import 三连的次序约束在这里完成闭环：平台段必须先跑（工件已写入 files.db），时间线 import 才有东西可搬——这就是第 1 节说的"顺序固化"的具体体现。`fs::exists(fileDbPath)` 双保险防的是"分类失败提前 return 1 之外的低概率路径"（分类失败其实已返回，此处 exists 主要是防平台段全跳过时 fileDb 意外缺失的防御式写法）。注意 import 的实参是 files.db 路径——走的是 EventExtractor 里"检查平台风格表"的 import 分支（见 EventExtractor.md 第 4 节），失败静默。`extractEvents()` 为假时只跳过 import 与 ✓ 输出，**不返回 1**——时间线失败与平台失败一样属于"可降级"档位（与分类失败的"致命"档位形成对比，见第 6 节）。

## 5. 与其他模块的协作

- **main.cpp/CommandLineParser**：旗标解析在上游完成，Orchestrator 只消费结构体。
- **ImageAnalyzer→DatabaseManager**：raw.db 的生产链（详见 DatabaseManager.md）。
- **FileFilter**：可插拔的过滤 profile；其对 raw.db 复制出 filtered.db 的行为决定了 effectiveRawDb 语义。
- **FileClassifier / 平台 Analyzer / EventExtractor**：核心三段，顺序与锁约定见第 4 节；任何一方失败即返回 1（分类/时间线）或降级继续（过滤、平台、DLL、报告、文本导出）。
- **PathManager/ConfigManager/AuditLog**：由 main.cpp 提前就绪，Orchestrator 自身不触碰单例（除 TextDump 用 MarkitdownProxy 单例）。
- **export/TextDumpExporter 与 python_service**：`--dump-text` 依赖 Python 服务在线；服务缺失时输出明确的启动指引但不置失败（`:448-452`）。相关 .env：`PYTHON_SERVICE_URL`（默认 `http://localhost:8090`）。
- 出错时行为：致命异常 catch-all 返回 1；可选步骤失败只警告——退出码只反映核心取证库是否建成。

## 6. 注意事项与已知问题

- **步骤编号注释失真**：代码里 `[1/4]…[4/4]` 与实际步骤数（含平台段共 5-7 步）不一致（`:206, 330` 的 `[4/4] Generating timeline` 出现在第 5 步）；还有一处 `[4/4] DLL` 与 `[4/4] timeline` 撞号（`:330, 344`）。阅读时以调用顺序为准，勿信编号。
- **产物命名与 HTTP 形态不同**：CLI 的 `<base>_files.db` vs 任务的 `files.db`；工具链脚本混用两种路径时要区分。`--db-dir` 只影响 CLI 产物前缀。
- 密码从 argv 传入（`--key-password`/`--wechat-password`/`--backup-password`）仍会出现在 shell 历史——代码已把 stdin/fd 路径标为安全替代并打弃用警告（`:186-189`），脚本应迁移。
- `runExtraction` 的镜像猜名只认固定扩展名集合（`:592`），`.vmdk`/`.E01` 大写部分覆盖、其他格式需显式传 `--database` 与镜像同目录。
- 平台分析器的 `initialize()` 失败只报错继续（如 `:288-291`），最终退出码仍为 0——自动化脚本必须解析 stderr/检查产物，不能只看退出码。
- TextDump 的 `--dump-text-max-bytes` 是软限额（到量即停，`:429-434` 的输出区分 Completed 与截断）。
- **失败分档不一致**：分类失败 return 1（`:271-274`）、时间线失败仅静默跳过（`:332` 的 if 无 else）——同为"核心产物"，退出码语义却不同；写自动化脚本前先核对这份清单。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_command_line_parser.cpp` 覆盖旗标解析；编排本身的端到端验证靠 `tests/` 下的镜像样本（如 `tests/ubuntu_real.img`、仓库根 `test_image.img`）跑 `./forensic_analyzer <image> --linux-analyze` 后检查 `<base>_*.db` 三件套与报告。
- 冒烟清单：跑一次全旗标命令，用 `sqlite3` 打开三个库确认表存在（files 24 分表见 FileClassifier.md）；`--dump-text` 需先 `./scripts/start_python_service.sh`。
- 扩展新的分析阶段：(1) 在 `runAnalysis` 找到依赖锚点（需要 files.db 就排在分类后，需要 events.db 排在时间线后）；(2) 构造 Analyzer、setOutputDatabasePath 指向既有库或新 `<base>_x.db`；(3) 失败策略遵循"可选步骤警告继续"；若该阶段也应出现在 HTTP 形态，需同步改 TaskManagerAnalysis.cpp——两处编排目前是手工保持等价的，这是最大的维护风险点。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
