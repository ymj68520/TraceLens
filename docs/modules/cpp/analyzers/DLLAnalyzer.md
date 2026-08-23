# DLLAnalyzer（src/analyzers/DLLAnalyzer/）

> **一句话**：对可执行库文件（Windows PE 的 dll/exe/sys，Linux ELF 的 so）做静态画像——哈希、PE 头/节表/导入导出、异常启发式、威胁评分、依赖与取证关联——结果写入独立 dll.db（复用 windows.db 的 `dll_*` 表结构）。

## 1. 为什么有这个模块

恶意代码分析里，"DLL/共享库"是攻击者最爱栖身的地方：DLL 劫持（替换系统 DLL）、DLL 注入（CreateRemoteThread + LoadLibrary）、后门伪装成正常库名。对取证人员来说，一个库文件即使不运行也能从静态特征读出大量信息：节熵值高说明加壳，导入表里出现注入类 API 说明能力，数字签名缺失/异常说明来源可疑。这个模块的目标就是把这套"看静态特征猜行为"的启发式知识自动化：对每个库文件算 MD5/SHA1/SHA256/ImpHash 四个哈希、解析 PE 元数据、跑异常规则、汇总成 0-100 的威胁评分。

它的架构是清晰的三层协作：`DLLAnalyzer`（编排，`Core/DLLAnalyzer.h:31`）协调 `PEAnalyzer`（元数据提取）、`AnomalyDetector`（启发式异常）、`DependencyAnalyzer`（依赖树与跨库关联）三个组件，结果经 `DLLAnalysisDatabase` 落库。并行是内建的：文件多时用 ThreadPool（线程数 = min(CPU 核数, 8)）并发分析（`DLLAnalyzerCore.cpp:75-139`）。

必须坦诚说明的现状：**这个模块目前扫的是分析机本机的系统目录，而不是镜像里提取的文件**。`scanDLLFiles()` 里的 TODO 写得明白——"从 WindowsFilesAnalyzer 获取已提取的 DLL 列表…当前版本扫描常见 Windows 系统目录"（`DLLAnalyzerCore.cpp:299-302`），Linux 下扫 `/usr/lib` 等本机路径（第 325-356 行），Windows 下扫 `%WINDIR%\System32`。因此在完整取证流水线里，它的产出是"分析机自身库文件的画像"，对镜像内可疑 DLL 的覆盖要靠后续把扫描源接到提取目录才能实现。理解这一点对使用者至关重要，对二次开发者则是第一优先级的接线点。

## 2. 在流水线中的位置

三个入口，全部是 CLI/编排层主动调用，不参与 HTTP 任务流水线：

- **`--analyze-dlls`**：作为完整分析的第 4 步附加运行（`AnalysisOrchestrator.cpp:343-377`）。若同一命令还带了 `--windows-analyze`，会把刚生成的 files.db 以只读 `WindowsAnalysisDatabase` 挂进来做取证关联（第 351-367 行）。
- **`--analyze-dlls-only`**：独立子命令 `runDLLAnalysis`（`AnalysisOrchestrator.cpp:710-752`），只跑 DLL 分析。
- 输出库默认 `<镜像名>_dll.db`（可用 `--dll-db` 改），`--verify-signatures` 开签名验证（CLI 默认 true，分析器构造默认 false，`DLLAnalyzerCore.cpp:42`）。

输入是文件系统路径（见第 1 节的现状说明）；输出是 dll.db，建表直接复用 `windows_analysis_sql_tables::CREATE_ALL_TABLES`（即整个 Windows 表集 + 7 张 `dll_*` 表：dll_base_info、dll_sections、dll_imports、dll_exports、dll_anomalies、dll_dependencies、dll_forensic_links，见 `DLLAnalysisDatabase.cpp:48-63`）。

## 3. 证据来源与覆盖范围

扫描阶段按扩展名收文件：`.dll/.DLL/.so/.so.1-.so.3/.ocx/.cpl/.sys/.drv`（`DLLAnalyzerCore.cpp:246-249`），跳过白名单——14 个知名系统库名（kernel32.dll、libc.so.6 等）和 6 个系统目录前缀（第 21-30 行），这是性能优化，避免对成千上万个显然无害的系统库做完整分析。超过 100MB 的文件跳过（`maxFileSize_`，第 43 行）。

对每个文件，`PEAnalyzer::analyze()`（`PEAnalyzer.cpp:37-99`）产出的证据面包括：

- **身份**：MD5/SHA1/SHA256（任何文件都算，不只 PE）、文件时间戳（stat 系统调用，crtime 用 ctime 近似，第 57 行注释）。
- **PE 结构**：DOS/NT 头、节表（含每节熵值）、导入表、导出表、版本信息、编译时间戳（`extractTimestamps`）。
- **行为线索**：ImpHash（导入表哈希，同族恶意样本会撞值）、数字签名状态。

## 4. 解析机制走读

**链路一：单个 DLL 的完整分析流水（`analyzeDLL`，`DLLAnalyzerCore.cpp:380-492`）。** 六步串行：先查 `isAlreadyAnalyzed`（按路径/inode 增量跳过）；`peAnalyzer_->analyze()` 做全部静态解析；`anomalyDetector_->detect()` 出异常列表并 `calculateThreatScore()` 汇总评分；威胁分 ≥30 时才做依赖树（省时间的取舍，第 410-415 行）；最后依次落 dll_base_info → dll_sections/imports/exports → dll_anomalies → updateThreatScore。评分逻辑（第 494-513 行）：所有异常 riskScore 求和、与已有分取大者、文件名含 inject/hook/keygen 等可疑词再加 10，最终夹在 0-100。

**链路二：异常启发式（`AnomalyDetector.cpp:13-58` 的特征集）。** 这是模块的"专家知识"所在，全部是内置集合：注入类 API（CreateRemoteThread、WriteProcessMemory…）、提权类（AdjustTokenPrivileges…）、反调试类（IsDebuggerPresent…）、持久化类（RegCreateKeyEx、CreateService…）、壳签名（UPX!/VMProtect/.themida…）、标准节名白名单。`detect()` 逐项检查：高熵节（加壳）、非标准节名、导入表里的注入 API、无导出的 DLL、可疑时间戳等，每个异常带类型/描述/1-100 的 riskScore。这些规则很"经典"，适合初筛，不能当鉴定结论。

**链路三：与 Windows 取证库的关联（Step 6，`DLLAnalyzerCore.cpp:449-470`）。** 若 `setWindowsDatabase()` 挂了只读 WindowsAnalysisDatabase（files.db），`DependencyAnalyzer` 会拿 DLL 文件名去三个方向反查：Prefetch 的引用文件列表（哪些程序加载过它）、注册表值（哪里注册过它）、事件日志（哪里出现过它），命中各写一行 dll_forensic_links（关联类型 + 来源表）。这一步把"静态可疑"升级为"在系统里真的活动过"的证据链——`--analyze-dlls` 与 `--windows-analyze` 连用时自动生效。

签名验证的真实路径在 `PEAnalyzer::verifySignature()` → `SignatureVerifier::verify()`（`SignatureVerifier.cpp:20-60`）：先查 PE 的 security directory 判断有无签名，有则优先 popen 外部 `osslsigncode` 验证，失败再退回自研 PKCS#7 解析做基本校验。注意 `analyzeDLL` Step 4 里 `enableSignatureVerification_` 控制的那段是占位实现（直接写 "Unsigned"，第 417-420 行注释"占位实现"）——真正的验证发生在 PEAnalyzer 内部且不受该开关控制，两个机制并存容易误读。

## 5. 与 LLM 的协作（当前未接线）

`Core/DLLAnalyzerLLMService.h` 定义了完整的 LLM 服务：输入 DLLAnalysisResult，产出摘要/描述/关键词/威胁评估/行为分析/可疑指标/建议八件套（`DLLLLMResult` 结构，第 43-58 行），底层走 `ModelRouter` 与 `FileAnalyzer`。但**全项目没有任何调用方**——`DLLAnalyzer::analyze()` 不调用它，编排层也不调用。它与 `tests/UnitTest/test_dll_analyzer_llm.cpp` 一起构成"已实现、待接线"的状态。这与 Windows/Linux/Android 分析器"LLM 内建在 analyze() 尾部"的模式不同，二次开发时可以参照那三个平台把调用补上。

## 6. 与其他模块的协作 / 注意事项

- **ELF 解析器的地位**：`Parsers/ELFParser*.cpp`（含 Sections/Dynamic 分文件）实现了完整的 ELF 头/节/动态段解析，但 `PEAnalyzer::analyze()` 只走 PE 路径，ELFParser 目前只有测试（`tests/integration_dll_analyzer.cpp`）在用。`.so` 文件会被扫描进来，但 PE 头无效即跳过（`DLLAnalyzerCore.cpp:399-402`），实际不产出记录。
- **`--dll-threshold` 是哑参数**：CommandLineParser 解析了它（默认 30，`CommandLineParser.cpp:260-261`），但没有任何代码消费——阈值 30 硬编码在 `DLLAnalyzerCore.cpp:411,473` 和统计查询里（`DLLAnalysisDatabase_Queries.cpp:232`）。
- **表结构共享**：dll.db 复用 `windows_analysis_sql_tables.h` 的全部建表语句，所以一个 dll.db 里也有 registry_values、event_logs 等 Windows 表（空表）；反过来 windows.db 里也有 7 张 dll_* 空表。这不是 bug，是共享 SQL 的副作用，查表时别被空表迷惑。
- **依赖**：OpenSSL（哈希/PKCS#7）、可选外部工具 osslsigncode（运行时探测，缺失则退回内置解析）。
- **`analyzeSingleFile(dllPath, inode)` 是留给流水线接线的公开接口**——未来把扫描源换成"镜像提取目录"时，WindowsFilesAnalyzer/FileClassifier 只需把候选文件逐个喂进来即可。

## 7. 如何验证与扩展

- 测试：`tests/test_dll_analyzer_gtest.cpp`（单元级：PE 解析、异常检测、评分）、`tests/integration_dll_analyzer.cpp`（集成，也是目前唯一用到 ELFParser 的地方）、`tests/UnitTest/test_dll_analyzer_llm.cpp`（LLM 服务，验证其自身可用）。
- 手工验证：`./build/forensic_analyzer --analyze-dlls-only --dll-db /tmp/t.db` 后查 `SELECT file_name, threat_score FROM dll_base_info ORDER BY threat_score DESC`，再交叉核对 dll_anomalies 的异常描述。
- 接线建议（如果要用于真实镜像）：在 `scanDLLFiles()` 里改为读取 `setExtractDirectory()` 指定的提取目录（字段和 setter 都已存在），或由编排层把 files.db 里 EXECUTABLE 类文件提取后逐个 `analyzeSingleFile()`。
- 加新异常规则：在 `AnomalyDetector.cpp` 的静态集合加条目或在 `detect()` 加检测方法（返回带 riskScore 的 `Anomaly`），威胁评分自动聚合。

**最后更新**: 2026-08-23（解释式重写）
