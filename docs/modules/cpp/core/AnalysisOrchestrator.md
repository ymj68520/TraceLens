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

## 5. 与其他模块的协作

- **main.cpp/CommandLineParser**：旗标解析在上游完成，Orchestrator 只消费结构体。
- **ImageAnalyzer→DatabaseManager**：raw.db 的生产链（详见 DatabaseManager.md）。
- **FileFilter**：可插拔的过滤 profile；其对 raw.db 复制出 filtered.db 的行为决定了 effectiveRawDb 语义。
- **FileClassifier / 平台 Analyzer / EventExtractor**：核心三段，顺序与锁约定见第 4 节；任何一方失败即返回 1（分类/时间线）或降级继续（过滤、平台、DLL、报告、文本导出）。
- **PathManager/ConfigManager/AuditLog**：由 main.cpp 提前就绪，Orchestrator 自身不触碰单例（除 TextDump 用 MarkitdownProxy 单例）。
- **export/TextDumpExporter 与 python_service**：`--dump-text` 依赖 Python 服务在线；服务缺失时输出明确的启动指引但不置失败（`:448-452`）。
- 出错时行为：致命异常 catch-all 返回 1；可选步骤失败只警告——退出码只反映核心取证库是否建成。

## 6. 注意事项与已知问题

- **步骤编号注释失真**：代码里 `[1/4]…[4/4]` 与实际步骤数（含平台段共 5-7 步）不一致（`:206, 330` 的 `[4/4] Generating timeline` 出现在第 5 步）；还有一处 `[4/4] DLL` 与 `[4/4] timeline` 撞号（`:330, 344`）。阅读时以调用顺序为准，勿信编号。
- **产物命名与 HTTP 形态不同**：CLI 的 `<base>_files.db` vs 任务的 `files.db`；工具链脚本混用两种路径时要区分。`--db-dir` 只影响 CLI 产物前缀。
- 密码从 argv 传入（`--key-password`/`--wechat-password`/`--backup-password`）仍会出现在 shell 历史——代码已把 stdin/fd 路径标为安全替代并打弃用警告（`:186-189`），脚本应迁移。
- `runExtraction` 的镜像猜名只认固定扩展名集合（`:592`），`.vmdk`/`.E01` 大写部分覆盖、其他格式需显式传 `--database` 与镜像同目录。
- 平台分析器的 `initialize()` 失败只报错继续（如 `:288-291`），最终退出码仍为 0——自动化脚本必须解析 stderr/检查产物，不能只看退出码。
- TextDump 的 `--dump-text-max-bytes` 是软限额（到量即停，`:429-434` 的输出区分 Completed 与截断）。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_command_line_parser.cpp` 覆盖旗标解析；编排本身的端到端验证靠 `tests/` 下的镜像样本（如 `tests/ubuntu_real.img`、仓库根 `test_image.img`）跑 `./forensic_analyzer <image> --linux-analyze` 后检查 `<base>_*.db` 三件套与报告。
- 冒烟清单：跑一次全旗标命令，用 `sqlite3` 打开三个库确认表存在（files 24 分表见 FileClassifier.md）；`--dump-text` 需先 `./scripts/start_python_service.sh`。
- 扩展新的分析阶段：(1) 在 `runAnalysis` 找到依赖锚点（需要 files.db 就排在分类后，需要 events.db 排在时间线后）；(2) 构造 Analyzer、setOutputDatabasePath 指向既有库或新 `<base>_x.db`；(3) 失败策略遵循"可选步骤警告继续"；若该阶段也应出现在 HTTP 形态，需同步改 TaskManagerAnalysis.cpp——两处编排目前是手工保持等价的，这是最大的维护风险点。

**最后更新**: 2026-08-23（解释式重写）
