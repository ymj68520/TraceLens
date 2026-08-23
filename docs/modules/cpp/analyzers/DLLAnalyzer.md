# DLLAnalyzer（src/analyzers/DLLAnalyzer/）

> **一句话**：对可执行库文件（Windows PE 的 dll/exe/sys，Linux ELF 的 so）做静态画像——哈希、PE 头/节表/导入导出、异常启发式、威胁评分、依赖与取证关联——结果写入独立 dll.db（复用 windows.db 的 `dll_*` 表结构）。

## 1. 为什么有这个模块

恶意代码分析里，"DLL/共享库"是攻击者最爱栖身的地方：DLL 劫持（替换系统 DLL）、DLL 注入（CreateRemoteThread + LoadLibrary）、后门伪装成正常库名。对取证人员来说，一个库文件即使不运行也能从静态特征读出大量信息：节熵值高说明加壳，导入表里出现注入类 API 说明能力，数字签名缺失/异常说明来源可疑。这个模块的目标就是把这套"看静态特征猜行为"的启发式知识自动化：对每个库文件算 MD5/SHA1/SHA256/ImpHash 四个哈希、解析 PE 元数据、跑异常规则、汇总成 0-100 的威胁评分。

它的架构是清晰的三层协作：`DLLAnalyzer`（编排，`Core/DLLAnalyzer.h:31`）协调 `PEAnalyzer`（元数据提取）、`AnomalyDetector`（启发式异常）、`DependencyAnalyzer`（依赖树与跨库关联）三个组件，结果经 `DLLAnalysisDatabase` 落库。并行是内建的：文件多时用 ThreadPool（线程数 = min(CPU 核数, 8)）并发分析（`DLLAnalyzerCore.cpp:75-139`）。

必须坦诚说明的现状：**这个模块目前扫的是分析机本机的系统目录，而不是镜像里提取的文件**。`scanDLLFiles()` 里的 TODO 写得明白——"从 WindowsFilesAnalyzer 获取已提取的 DLL 列表…当前版本扫描常见 Windows 系统目录"（`DLLAnalyzerCore.cpp:299-302`），Linux 下扫 `/usr/lib` 等本机路径（第 325-356 行），Windows 下扫 `%WINDIR%\System32`。因此在完整取证流水线里，它的产出是"分析机自身库文件的画像"，对镜像内可疑 DLL 的覆盖要靠后续把扫描源接到提取目录才能实现。理解这一点对使用者至关重要，对二次开发者则是第一优先级的接线点。

## 2. 核心数据结构

**PE 磁盘结构**（`Common/DLLDataTypes.h:63-187`，`#pragma pack(push,1)` 逐字节对齐后直接从文件读入）：

```cpp
struct DOSHeader {
    uint16_t e_magic;              // 0x5A4D "MZ"
    // ... 14 个 DOS 时代遗留字段（e_cblp/e_cp/…，取证基本无用）
    uint32_t e_lfanew;             // PE头偏移 —— 整个 PE 解析的起点
};
struct COFFHeader {
    uint16_t machine;              // 机器类型：0x14C=x86, 0x8664=x64, 0xAA64=ARM64
    uint16_t numberOfSections;
    uint32_t timestamp;             // 编译时间戳（可被伪造，需交叉验证）
    uint32_t pointerToSymbolTable;
    uint32_t numberOfSymbols;
    uint16_t sizeOfOptionalHeader;  // 决定节表位置
    uint16_t characteristics;
};
struct SectionHeader {
    char name[8];                   // 节名，8 字节不够长会被截断
    uint32_t virtualSize;
    uint32_t virtualAddress;
    uint32_t sizeOfRawData;
    uint32_t pointerToRawData;      // 节数据在文件中的位置
    uint32_t pointerToRelocations;
    uint32_t pointerToLinenumbers;
    uint16_t numberOfRelocations;
    uint16_t numberOfLinenumbers;
    uint32_t characteristics;       // R/W/X 权限位
};
```

三个结构就是"从 MZ 到节表"的定位链：`e_magic` 验 MZ → `e_lfanew` 跳到 PE 签名（`PE_SIGNATURE = 0x00004550`，即 "PE\0\0"，第 22 行）→ COFF 头 + 可选头（PE32 224 字节 / PE32+ 240 字节）之后紧跟节表数组。`MachineType/SubsystemType` 枚举（第 28-52 行）把整数值翻译成人类可读的架构/子系统（驱动 = NATIVE=1）。

**解析后的分析结构**（同文件 :219-291）：

```cpp
struct PESectionInfo {
    std::string name;
    uint32_t virtualAddress, virtualSize, rawDataSize, pointerToRawData;
    uint32_t characteristics;
    double entropy;           // Shannon 熵，加壳检测的核心特征
    bool isWriteable, isExecutable, isReadable;
};
struct Anomaly {
    std::string type;         // 异常类型
    std::string description;  // 详细描述
    RiskLevel risk;           // LOW/MEDIUM/HIGH/CRITICAL
    int riskScore;            // 风险分数 0-100
};
```

`DLLAnalysisResult`（第 294 行起）是单文件分析的全量载体：四个时间戳（mtime/ctime/atime/crtime）、`PEHeaderInfo`（含 `securityTableRVA` 等 7 个数据目录 RVA）、imports/exports、四哈希、版本信息四字段、签名状态三字段、anomalies 列表与 threatScore——正好一一对应 dll_base_info 的列布局。

### 2.1 核心接口清单

`DLLAnalyzer`（`Core/DLLAnalyzer.h:31-199`）的公开 API：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool initialize()` | 初始化 dll.db（建全部表） | `AnalysisOrchestrator` 两个入口 | false + 日志 |
| `void analyze()` | 全量流水：scanDLLFiles → 并行 analyzeDLL | `--analyze-dlls` / `--analyze-dlls-only` | 单文件异常捕获，不中断批次 |
| `bool analyzeSingleFile(dllPath, inode=0)` | 按需分析单个文件（流水线接线点） | 预留（当前无生产调用方） | PE 无效即 false |
| `void setWindowsDatabase(const WindowsAnalysisDatabase*)` | 挂只读 windows.db 做取证关联 | `--analyze-dlls` 与 `--windows-analyze` 连用（`AnalysisOrchestrator.cpp:351-367`） | 不挂则 Step 6 静默跳过 |
| `void setExtractDirectory(dir)` / `setMaxFileSize(bytes)` | 扫描目录/大小上限设置 | 预留（TODO 接线，见第 1 节） | — |
| `bool isAlreadyAnalyzed(path, inode)` | 增量跳过判定 | `analyzeDLL` 第一步 | — |
| `AnalysisStats getStats()` | 批次统计 | 编排层日志 | — |

## 3. 在流水线中的位置

三个入口，全部是 CLI/编排层主动调用，不参与 HTTP 任务流水线：

- **`--analyze-dlls`**：作为完整分析的第 4 步附加运行（`AnalysisOrchestrator.cpp:343-377`）。若同一命令还带了 `--windows-analyze`，会把刚生成的 files.db 以只读 `WindowsAnalysisDatabase` 挂进来做取证关联（第 351-367 行）。
- **`--analyze-dlls-only`**：独立子命令 `runDLLAnalysis`（`AnalysisOrchestrator.cpp:710-752`），只跑 DLL 分析。
- 输出库默认 `<镜像名>_dll.db`（可用 `--dll-db` 改），`--verify-signatures` 开签名验证（CLI 默认 true，分析器构造默认 false，`DLLAnalyzerCore.cpp:42`）。

输入是文件系统路径（见第 1 节的现状说明）；输出是 dll.db，建表直接复用 `windows_analysis_sql_tables::CREATE_ALL_TABLES`（即整个 Windows 表集 + 7 张 `dll_*` 表：dll_base_info、dll_sections、dll_imports、dll_exports、dll_anomalies、dll_dependencies、dll_forensic_links，见 `DLLAnalysisDatabase.cpp:48-63`）。

## 4. 证据来源与覆盖范围

扫描阶段按扩展名收文件：`.dll/.DLL/.so/.so.1-.so.3/.ocx/.cpl/.sys/.drv`（`DLLAnalyzerCore.cpp:246-249`），跳过白名单——14 个知名系统库名（kernel32.dll、libc.so.6 等）和 6 个系统目录前缀（第 21-30 行），这是性能优化，避免对成千上万个显然无害的系统库做完整分析。超过 100MB 的文件跳过（`maxFileSize_`，第 43 行）。

白名单与扫描源的真实代码：

```cpp
// DLLAnalyzerCore.cpp:21-30
const std::unordered_set<std::string> DLLAnalyzer::SYSTEM_DLL_NAMES_ = {
    "kernel32.dll", "kernelbase.dll", "ntdll.dll", "user32.dll", "gdi32.dll",
    "advapi32.dll", "ws2_32.dll", "wininet.dll", "ole32.dll", "oleaut32.dll",
    "libc.so.6", "libdl.so.2", "libpthread.so.0", "libm.so.6"
};
const std::unordered_set<std::string> DLLAnalyzer::SYSTEM_DIRECTORIES_ = {
    "/usr/lib", "/usr/lib64", "/lib", "/lib64",
    "c:\\windows\\system32", "c:\\windows\\syswow64"
};

// DLLAnalyzerCore.cpp:296-301（现状 TODO 原文）
std::vector<std::string> DLLAnalyzer::scanDLLFiles() {
    std::vector<std::string> dllFiles;
    // TODO: 从WindowsFilesAnalyzer获取已提取的DLL列表
    // 或从FileClassifier结果中获取EXECUTABLE类型的文件
    // 当前版本扫描常见Windows系统目录
```

两套白名单是两码事：`SYSTEM_DLL_NAMES_` 让这些库名**不进分析**（性能优化），`SYSTEM_DIRECTORIES_` 目前只被 `isWhitelistedDLL` 引用——在白名单目录里的文件跳过。而 TODO 注释是理解模块现状的钥匙：扫描源本应是"镜像里提取出的 DLL"，现在落在本机目录，产出因此是分析机自身的画像。

对每个文件，`PEAnalyzer::analyze()`（`PEAnalyzer.cpp:37-99`）产出的证据面包括：

- **身份**：MD5/SHA1/SHA256（任何文件都算，不只 PE）、文件时间戳（stat 系统调用，crtime 用 ctime 近似，第 57 行注释）。
- **PE 结构**：DOS/NT 头、节表（含每节熵值）、导入表、导出表、版本信息、编译时间戳（`extractTimestamps`）。
- **行为线索**：ImpHash（导入表哈希，同族恶意样本会撞值）、数字签名状态。

### 4.1 产出表结构说明（7 张 dll_* 表）

schema 在 `windows_analysis_sql_tables.h:464-590`：

| 表 | 关键列 | 取证含义 |
|----|--------|---------|
| `dll_base_info`（:464-517） | `inode/path/md5/sha1/sha256/imp_hash/rich_hash/machine_type/compile_timestamp/subsystem/entry_point/signature_status/cert_issuer/threat_score` | 单库主档：身份（四哈希）+ 架构 + 编译时间 + 签名与证书有效期 + 威胁评分；`path` UNIQUE 支撑增量去重 |
| `dll_sections`（:520-533） | `section_name/virtual_address/raw_data_size/entropy/is_writeable/is_executable` | 节级特征：`entropy>7 且 is_executable` 是加壳/加密代码的强指征 |
| `dll_imports`（:536-544） | `imported_dll_name/imported_function/import_ordinal/is_delayed` | 导入 API 面：异常检测的原始素材（注入/提权/反调试函数都在这里查） |
| `dll_exports`（:547-554） | `function_name/export_ordinal/export_rva` | 导出面：假冒系统 DLL 常见"导出表为空或只有转发桩" |
| `dll_anomalies`（:557-567） | `anomaly_type/description/risk_level/risk_score/details` | 每条启发式命中一行，带 0-100 风险分，供评分聚合与人工复核 |
| `dll_dependencies`（:570-578） | `parent_dll_id/child_dll_id/depth/is_resolved` | 依赖树边（威胁分 ≥30 才建） |
| `dll_forensic_links`（:581-589） | `link_type/source_id/source_data` | 跨库关联：`link_type` ∈ {prefetch, registry, eventlog}，`source_data` 是人读摘要串 |

## 5. 解析机制走读

**链路一：单个 DLL 的完整分析流水（`analyzeDLL`，`DLLAnalyzerCore.cpp:380-492`）。** 六步串行：先查 `isAlreadyAnalyzed`（按路径/inode 增量跳过）；`peAnalyzer_->analyze()` 做全部静态解析；`anomalyDetector_->detect()` 出异常列表并 `calculateThreatScore()` 汇总评分；威胁分 ≥30 时才做依赖树（省时间的取舍，第 410-415 行）；最后依次落 dll_base_info → dll_sections/imports/exports → dll_anomalies → updateThreatScore。评分逻辑（第 494-513 行）：所有异常 riskScore 求和、与已有分取大者、文件名含 inject/hook/keygen 等可疑词再加 10，最终夹在 0-100。

**链路二：节表解析与熵值计算（`Parsers/PEHeaderParser.cpp:255-300, 450-468`）。** 节表定位靠硬算的偏移：

```cpp
// PEHeaderParser.cpp:260-267（节表位置 = PE签名 + COFF头 + 可选头）
constexpr size_t PE32_OPTIONAL_SIZE = 224;
constexpr size_t PE32PLUS_OPTIONAL_SIZE = 240;
uint32_t optionalHeaderSize = isPE32Plus_ ? PE32PLUS_OPTIONAL_SIZE : PE32_OPTIONAL_SIZE;
uint32_t sectionOffset = peHeaderOffset_ + 4 + sizeof(COFFHeader) + optionalHeaderSize;

for (uint16_t i = 0; i < headerInfo_.numberOfSections; ++i) {
    file_.seekg(sectionOffset + i * sizeof(SectionHeader));
    SectionHeader section;
    file_.read(reinterpret_cast<char*>(&section), sizeof(SectionHeader));
    // ...
    // 计算节熵值（跳过>100MB的节以避免内存问题）
    if (sectionInfo.rawDataSize > 0 && sectionInfo.rawDataSize < 100 * 1024 * 1024) {
        std::vector<uint8_t> sectionData = readSectionData(sectionInfo);
        if (!sectionData.empty()) {
            sectionInfo.entropy = calculateEntropy(sectionData);
        }
    }
}
```

做什么：可选头不用完整结构体（PE32/PE32+ 字段宽窄不一），只取其**长度**（224/240）跳过去，直接把节表当定长数组逐项读。为什么可行：节表紧跟可选头、项长固定 40 字节，`#pragma pack(1)` 的 `SectionHeader` 可以原样 `read`。边界保护有二：读失败即 return false（截断/损坏文件）；超过 100MB 的节不算熵（防内存爆）。熵计算本体（第 452-467 行）是标准 Shannon 公式 `H = -Σ p(x)·log2 p(x)`，源码注释直接给出解读标尺——0-6 正常/压缩，6-7 疑似加壳，7-8 加密/高可疑。

**链路三：异常启发式（`AnomalyDetector.cpp:13-58` 的特征集）。** 这是模块的"专家知识"所在，全部是内置集合：

```cpp
// AnomalyDetector.cpp:17-53（节选）
const std::unordered_set<std::string> AnomalyDetector::INJECTION_FUNCTIONS = {
    "CreateRemoteThread", "WriteProcessMemory", "VirtualAllocEx",
    "SetWindowsHookEx", "CallNextHookEx", "GetAsyncKeyState",
    "OpenProcess", "ReadProcessMemory"
};
const std::unordered_set<std::string> AnomalyDetector::ANTI_DEBUG_FUNCTIONS = {
    "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
    "NtQueryInformationProcess", "OutputDebugString",
    "ZwSetInformationThread", "DebugActiveProcess"
};
const std::unordered_set<std::string> AnomalyDetector::PACKER_SIGNATURES = {
    "UPX0", "UPX1", "UPX!", "ASPack", "PECompact",
    ".themida", "VMProtect", ".vmp0", ".vmp1"
};
```

五组函数集（注入/提权/反调试/持久化）+ 壳节名签名 + 标准节名白名单（`STANDARD_SECTION_NAMES` 含 `.text/.idata` 等约 25 个）。`detect()` 逐项检查：高熵节（加壳）、非标准节名、导入表里的注入 API、无导出的 DLL、可疑时间戳等，每个异常带类型/描述/1-100 的 riskScore。这些规则很"经典"，适合初筛，不能当鉴定结论。

**链路四：与 Windows 取证库的关联（Step 6，`DLLAnalyzerCore.cpp:449-470`）。** 若 `setWindowsDatabase()` 挂了只读 WindowsAnalysisDatabase（files.db），`DependencyAnalyzer` 会拿 DLL 文件名去三个方向反查。Prefetch 方向的真实查询：

```cpp
// DependencyAnalyzer.cpp:124-150（节选）
std::vector<std::string> DependencyAnalyzer::getPrefetchReferences(
    const std::string& dllPath) {
    if (!windowsDb_) { return {}; }
    std::vector<std::string> references;
    std::string targetDll = extractFileName(dllPath);
    auto prefetchFiles = windowsDb_->queryPrefetchFiles("");
    for (const auto& prefetch : prefetchFiles) {
        for (const auto& refFile : prefetch.referencedFiles) {
            if (extractFileName(refFile) == targetDll) {
                references.push_back("Prefetch:" + prefetch.executableName +
                                    " (Hash:" + prefetch.prefetchHash +
                                    ", Runs:" + std::to_string(prefetch.runCount) + ")");
                break; // 每个 Prefetch 只记录一次
            }
        }
    }
    return references;
}
```

做什么：全量拉取 prefetch_files，在每条记录的 referencedFiles 列表里按**文件名**（不带路径）比对目标 DLL，命中则产出一条人读摘要（哪个可执行文件加载过它、运行了几次）。为什么按文件名而不是全路径：Windows 内部引用（Prefetch/Run 键）常用短路径或不同大小写，路径级比对会大量漏报。产物经 `insertForensicLink(dllId, "prefetch", "prefetch_files", ref)` 落 dll_forensic_links——把"静态可疑"升级为"在系统里真的活动过"的证据链。`--analyze-dlls` 与 `--windows-analyze` 连用时自动生效；注册表（getRegistryReferences）与事件日志（getEventLogReferences）方向同理（`DependencyAnalyzer.cpp:153-190+`）。

签名验证的真实路径在 `PEAnalyzer::verifySignature()` → `SignatureVerifier::verify()`（`SignatureVerifier.cpp:20-60`）：先查 PE 的 security directory 判断有无签名，有则优先 popen 外部 `osslsigncode` 验证，失败再退回自研 PKCS#7 解析做基本校验。注意 `analyzeDLL` Step 4 里 `enableSignatureVerification_` 控制的那段是占位实现（直接写 "Unsigned"，第 417-420 行注释"占位实现"）——真正的验证发生在 PEAnalyzer 内部且不受该开关控制，两个机制并存容易误读。

## 6. 与 LLM 的协作（当前未接线）

`Core/DLLAnalyzerLLMService.h` 定义了完整的 LLM 服务：输入 DLLAnalysisResult，产出摘要/描述/关键词/威胁评估/行为分析/可疑指标/建议八件套（`DLLLLMResult` 结构，第 43-58 行），底层走 `ModelRouter` 与 `FileAnalyzer`。但**全项目没有任何调用方**——`DLLAnalyzer::analyze()` 不调用它，编排层也不调用。它与 `tests/UnitTest/test_dll_analyzer_llm.cpp` 一起构成"已实现、待接线"的状态。这与 Windows/Linux/Android 分析器"LLM 内建在 analyze() 尾部"的模式不同，二次开发时可以参照那三个平台把调用补上。

## 7. 与其他模块的协作 / 注意事项

- **ELF 解析器的地位**：`Parsers/ELFParser*.cpp`（含 Sections/Dynamic 分文件）实现了完整的 ELF 头/节/动态段解析，但 `PEAnalyzer::analyze()` 只走 PE 路径，ELFParser 目前只有测试（`tests/integration_dll_analyzer.cpp`）在用。`.so` 文件会被扫描进来，但 PE 头无效即跳过（`DLLAnalyzerCore.cpp:399-402`），实际不产出记录。
- **`--dll-threshold` 是哑参数**：CommandLineParser 解析了它（默认 30，`CommandLineParser.cpp:260-261`），但没有任何代码消费——阈值 30 硬编码在 `DLLAnalyzerCore.cpp:411,473` 和统计查询里（`DLLAnalysisDatabase_Queries.cpp:232`）。
- **表结构共享**：dll.db 复用 `windows_analysis_sql_tables.h` 的全部建表语句，所以一个 dll.db 里也有 registry_values、event_logs 等 Windows 表（空表）；反过来 windows.db 里也有 7 张 dll_* 空表。这不是 bug，是共享 SQL 的副作用，查表时别被空表迷惑。
- **依赖**：OpenSSL（哈希/PKCS#7）、可选外部工具 osslsigncode（运行时探测，缺失则退回内置解析）。
- **`analyzeSingleFile(dllPath, inode)` 是留给流水线接线的公开接口**——未来把扫描源换成"镜像提取目录"时，WindowsFilesAnalyzer/FileClassifier 只需把候选文件逐个喂进来即可。

## 8. 如何验证与扩展

- 测试：`tests/test_dll_analyzer_gtest.cpp`（单元级：PE 解析、异常检测、评分）、`tests/integration_dll_analyzer.cpp`（集成，也是目前唯一用到 ELFParser 的地方）、`tests/UnitTest/test_dll_analyzer_llm.cpp`（LLM 服务，验证其自身可用）。
- 手工验证：`./build/forensic_analyzer --analyze-dlls-only --dll-db /tmp/t.db` 后查 `SELECT file_name, threat_score FROM dll_base_info ORDER BY threat_score DESC`，再交叉核对 dll_anomalies 的异常描述。
- 接线建议（如果要用于真实镜像）：在 `scanDLLFiles()` 里改为读取 `setExtractDirectory()` 指定的提取目录（字段和 setter 都已存在），或由编排层把 files.db 里 EXECUTABLE 类文件提取后逐个 `analyzeSingleFile()`。
- 加新异常规则：在 `AnomalyDetector.cpp` 的静态集合加条目或在 `detect()` 加检测方法（返回带 riskScore 的 `Anomaly`），威胁评分自动聚合。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
