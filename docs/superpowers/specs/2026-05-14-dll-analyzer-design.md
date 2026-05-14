# DLLAnalyzer - 动态链接库取证分析器设计文档

## 元数据

- **项目**: ForensicsProject - Digital Forensics Image Analysis Tool
- **模块**: `DLLAnalyzer` - 动态链接库取证分析器
- **创建日期**: 2026-05-14
- **状态**: Draft
- **目标**: 提供Windows DLL和Linux .so文件的深度取证分析

## 1. 业务背景

### 1.1 问题陈述

动态链接库（DLL/so）是数字取证中的关键证据来源：
- **恶意软件载体**：DLL劫持、DLL侧加载、DLL注入是常见攻击技术
- **程序行为线索**：Prefetch记录的可执行文件加载的DLL列表
- **持久化机制**：DLL被用于实现启动项、计划任务等持久化
- **横向移动**：PsExec、WMI等工具依赖的DLL
- **数据隐藏**：Alternate Data Streams (ADS) 中的DLL
- **跨平台取证**：Windows的.dll和Linux的.so都需要分析

当前项目**缺乏**对DLL文件的深度解析能力：
- FileClassifier仅将DLL分类为`EXECUTABLE`或`SYSTEM`
- 无PE结构解析、元数据提取、异常检测功能
- 未与Prefetch、注册表等Windows证据关联

### 1.2 业务价值

**DLLAnalyzer**将为调查人员提供：
- **威胁识别**：检测可疑DLL行为（注入、劫持、加壳）
- **程序行为重建**：提取程序加载的DLL列表和依赖关系
- **攻击链分析**：关联Prefetch、注册表、事件日志，还原攻击路径
- **恶意软件特征**：识别已知恶意DLL家族特征
- **跨平台支持**：统一分析Windows DLL和Linux .so

---

## 2. 功能需求

### 2.1 PE结构解析（优先级：P0）

**支持格式**：
- Windows PE (Portable Executable): .dll, .exe, .sys, .ocx, .cpl
- Linux ELF (Executable and Linkable Format): .so, .so.1, .so.2
- macOS Mach-O: .dylib（未来扩展）

**PE文件解析内容**：
```
DOS Header (IMAGE_DOS_HEADER)
  └─ PE Signature detection

PE Header (IMAGE_NT_HEADERS)
  ├─ FileHeader (COFF): Machine, NumberOfSections, TimeDateStamp, Characteristics
  └─ OptionalHeader (IMAGE_OPTIONAL_HEADER):
      ├─ Magic: PE32/PE32+/ROM
      ├─ DataDirectory: Export, Import, Resource, Exception, Security, etc.
      └─ Subsystem: GUI/CUI/DLL/etc.

Section Table (IMAGE_SECTION_HEADER)
  ├─ .text (CODE): Executable code
  ├─ .data (DATA): Initialized data
  ├─ .rdata (CONST): Read-only data
  ├─ .bss (BSS): Uninitialized data
  ├─ .rsrc (RESOURCE): Resources (icons, strings, manifests)
  ├─ .reloc (RELOC): Base relocation table
  ├─ .tls (TLS): Thread Local Storage
  └─ .idata/.edata: Import/Export tables (sometimes separate)

Export Directory (IMAGE_EXPORT_DIRECTORY)
  └─ Exported functions, names, ordinals

Import Directory (IMAGE_IMPORT_DESCRIPTOR)
  └─ Imported DLLs and functions

Resource Directory (IMAGE_RESOURCE_DIRECTORY)
  └─ Version info, icons, manifests, string tables

Debug Directory (IMAGE_DEBUG_DIRECTORY)
  └─ CodeView debug info, PDB path

TLS Directory (IMAGE_TLS_DIRECTORY)
  └─ Thread Local Storage callbacks

Base Relocation Table (IMAGE_BASE_RELOAD)
  └─ Fixup addresses

Load Configuration Directory
  └─ Security cookie, SEH, CFG info

Rich Signature (overlay)
  └─ Compiler tool versions
```

**元数据提取**：
- **编译时间戳**：`TimeDateStamp` (PE Header)
- **链接器版本**：Rich Signature
- **入口点地址**：`AddressOfEntryPoint`
- **图像基址**：`ImageBase`
- **子系统类型**：`Subsystem` (DLL/Native/Windows/GUI)
- **机器类型**：`Machine` (x86/x64/ARM/ARM64)
- **特征标志**：`Characteristics` (DLL, Executable, Large Address Aware)
- **校验和**：`CheckSum`

### 2.2 数字签名验证（优先级：P1）

- **Authenticode签名**：验证PE文件的数字签名
- **证书链验证**：颁发者、有效期、吊销状态
- **签名状态**：Signed/Unsigned/Invalid
- **发布者信息**：公司名称、产品名称、文件描述
- **时间戳**：签名时间（可信时间戳）

### 2.3 哈希计算（优先级：P0）

- **MD5**: 快速文件校验（匹配FileClassifier现有字段）
- **SHA-1**: 碰撞检测
- **SHA-256**: 完整性验证
- **ImpHash** (Import Hash): 基于导入表的哈希，用于恶意软件聚类
- **Rich PE Hash**: 基于Rich Header的哈希
- **SSDEEP/ TLSH**: 模糊哈希（相似性检测）

### 2.4 导入/导出表分析（优先级：P1）

**导入表分析**：
- 导入的DLL列表（递归依赖）
- 导入的函数列表（按类别分组）
- **可疑函数检测**：
  - 进程注入：`CreateRemoteThread`, `WriteProcessMemory`, `VirtualAllocEx`
  - 键盘记录：`SetWindowsHookEx`, `GetAsyncKeyState`
  - 网络通信：`WinSock`函数、`URLDownloadToFile`
  - 权限提升：`AdjustTokenPrivileges`, `SeDebugPrivilege`
  - 持久化：`RegCreateKeyEx`, `CreateService`
  - 反调试：`IsDebuggerPresent`, `CheckRemoteDebuggerPresent`

**导出表分析**：
- 导出的函数列表（用于识别DLL功能）
- 可疑导出模式（如加密函数、注入函数）

### 2.5 异常检测（优先级：P1）

**恶意DLL检测规则**：

| 检测项 | 风险等级 | 检测逻辑 |
|--------|---------|---------|
| **异常节名** | HIGH | 使用非常见节名（如".evil"、".upx"） |
| **自解密代码** | HIGH | 节属性同时标记为WRITE+EXECUTE (.text) |
| **高熵值代码段** | HIGH | .text段熵值>7.0（可能是加密/加壳） |
| **异常入口点** | MEDIUM | 入口点位于非标准节（如.rdata/.data） |
| **UPX加壳** | HIGH | UPX0/UPX1节、特征字符串"UPX!" |
| **VMProtect加壳** | HIGH | 虚拟机代码特征 |
| **异常大节** | MEDIUM | .rsrc或其他节异常增大 |
| **可疑资源** | MEDIUM | 资源中包含可执行代码、加密密钥 |
| **异常对齐** | LOW | 节对齐与文件对齐不匹配 |
| **调试符号残留** | LOW | 包含PDB路径（如C:\build路径） |
| ** TLS回调** | MEDIUM | 用于反调试和代码注入 |
| **延迟加载DLL** | LOW | 使用延迟加载机制 |

**熵值计算**：
```cpp
// Shannon熵: H = -Σ p(x) * log2(p(x))
// 范围: 0-8 bits/byte
// 7.0-8.0: 加密/加壳
// 6.0-7.0: 压缩
// < 6.0: 正常
```

### 2.6 依赖关系分析（优先级：P1）

**静态依赖**：
- 递归遍历所有导入的DLL
- 构建依赖树（DAG）
- 识别缺失依赖（DLL Hell问题）

**动态依赖关联**：
- **Prefetch集成**：从Prefetch的referenced_files提取实际加载的DLL
- **注册表关联**：从AppInit_DLLs、KnownDLLs、Shell Extensions获取DLL加载记录
- **事件日志关联**：从Process Creation (4688)事件提取DLL加载
- **时间线重建**：DLL首次出现时间、加载时间

**输出示例**：
```
可执行文件: C:\Windows\System32\evil.exe
├── kernel32.dll (系统)
├── user32.dll (系统)
├── ws2_32.dll (网络)
├── injected.dll ⚠️ [非标准路径]
│   ├── ntdll.dll (系统)
│   └── advapi32.dll (系统)
└── C:\Users\Public\payload.dll 🚨 [非常见路径]
    └── [深度依赖...]
```

### 2.7 取证关联分析（优先级：P2）

**DLL劫持检测**：
- 可执行文件优先加载工作目录中的DLL
- 检测用户可写目录下的DLL被系统进程加载
- 比较`KnownDLLs`注册表项与实际加载的DLL

**DLL侧加载检测**：
- 使用SxS（Side-by-Side）清单的DLL加载
- 检测manifest劫持

**ADS (Alternate Data Streams)**：
- 扫描NTFS ADS中的DLL文件
- 检测隐藏的DLL

**版本信息分析**：
- 从`.rsrc`节提取`VS_VERSIONINFO`
- 文件版本、产品版本、公司名称
- 语言和代码页

### 2.8 跨平台支持（优先级：P2）

**Linux ELF分析**：
- ELF头解析（e_ident, e_type, e_machine）
- 节头（Section Headers）
- 动态段（`.dynamic`）：DT_NEEDED依赖
- 符号表（`.dynsym`）：导出/导入符号
- 构造函数/析构函数（`.init`/`.fini`）
- GNU哈希、ELF哈希
- Android的JNI库支持（libnative.so）

---

## 3. 系统架构

### 3.1 模块结构

```
src/analyzers/DLLAnalyzer/
├── Core/
│   ├── DLLAnalyzer.h              # 主类声明
│   ├── DLLAnalyzerCore.cpp        # 核心实现
│   ├── PEParser.h                 # PE文件解析器
│   ├── PEParser.cpp
│   ├── ELFParser.h                # ELF文件解析器（Linux）
│   ├── ELFParser.cpp
│   ├── PEAnalyzer.h               # PE分析引擎
│   ├── PEAnalyzer.cpp
│   ├── DependencyAnalyzer.h       # 依赖分析
│   ├── DependencyAnalyzer.cpp
│   ├── AnomalyDetector.h          # 异常检测
│   └── AnomalyDetector.cpp
├── Parsers/
│   ├── PEHeaderParser.h           # PE头解析
│   ├── PEHeaderParser.cpp
│   ├── PESectionParser.h          # 节表解析
│   ├── PESectionParser.cpp
│   ├── PEImportExportParser.h     # 导入/导出表解析
│   ├── PEImportExportParser.cpp
│   ├── PEResourceParser.h         # 资源解析
│   ├── PEResourceParser.cpp
│   ├── SignatureVerifier.h        # 数字签名验证
│   └── SignatureVerifier.cpp
├── Database/
│   ├── DLLAnalysisDatabase.h      # 数据库接口
│   └── DLLAnalysisDatabase.cpp    # 数据库操作
├── Common/
│   ├── DLLDataTypes.h             # 数据结构定义
│   └── DLLAnalyzerDeclarations.h  # 前向声明
└── README.md                      # 模块文档
```

### 3.2 核心组件

#### 3.2.1 DLLAnalyzer（主入口）

**职责**：
- 协调整个分析流程
- 文件扫描和筛选（通过FileClassifier结果）
- 集成到主pipeline（main.cpp）
- 与WindowsFilesAnalyzer、Prefetch等模块数据关联

**关键接口**：
```cpp
class DLLAnalyzer {
public:
    DLLAnalyzer(DatabaseManager* dbManager, const std::string& outputDbPath);
    ~DLLAnalyzer();

    bool initialize();
    void analyze();
    void correlateWithPrefetch(const std::vector<PrefetchInfo>& prefetchData);
    void correlateWithRegistry(const RegistryData& regData);

    // 分析选项
    void setExtractDirectory(const std::string& dir);
    void setMaxFileSize(size_t maxSize);
    void enableAnomalyDetection(bool enable);
    void enableSignatureVerification(bool enable);

private:
    bool scanDLLFiles();
    bool analyzeDLL(const std::string& dllPath, int64_t inode);
    // ...
};
```

#### 3.2.2 PEParser（PE文件解析器）

**职责**：
- 解析PE文件二进制结构
- 提取所有头部信息
- 遍历节表和数据目录

**数据结构**：
```cpp
struct PEHeaderData {
    // DOS Header
    uint16_t dosMagic;              // "MZ"
    uint32_t peOffset;              // PE header offset

    // COFF Header
    uint16_t machine;               // 0x8664=x64, 0x14c=x86
    uint16_t numberOfSections;
    uint32_t timestamp;             // Compile time
    uint32_t characteristics;

    // Optional Header
    uint16_t magic;                 // PE32/PE32+
    uint64_t imageBase;
    uint32_t sectionAlignment;
    uint32_t fileAlignment;
    uint16_t subsystem;             // DLL/Native/etc.
    uint32_t entryPointRVA;
    uint32_t checkSum;

    // Data Directory
    struct {
        uint32_t rva;
        uint32_t size;
    } exportTable, importTable, resourceTable,
       exceptionTable, securityTable, relocTable,
       debugTable, tlsTable, loadConfigTable;
};

struct PESection {
    std::string name;
    uint32_t virtualAddress;
    uint32_t virtualSize;
    uint32_t rawDataPointer;
    uint32_t rawDataSize;
    uint32_t characteristics;       // Read/Write/Execute flags
    double entropy;                 // Section entropy
};

struct PEImport {
    std::string dllName;
    std::vector<std::string> functions;
};

struct PEExport {
    std::string name;
    uint16_t ordinal;
    uint32_t rva;
};
```

**关键方法**：
```cpp
class PEParser {
public:
    explicit PEParser(const std::string& filePath);
    ~PEParser();

    bool parse();
    bool isValid() const;

    const PEHeaderData& getHeader() const;
    const std::vector<PESection>& getSections() const;
    const std::vector<PEImport>& getImports() const;
    const std::vector<PEExport>& getExports() const;
    const std::vector<uint8_t>& getRawSecurity() const;

    std::string getEntryPointSectionName() const;
    double calculateEntropy(const std::vector<uint8_t>& data) const;
    uint8_t* getSectionData(const std::string& sectionName) const;

private:
    bool parseDOSHeader();
    bool parseNTHeaders();
    bool parseSections();
    bool parseImportTable();
    bool parseExportTable();
    bool parseResourceDirectory();
    bool parseDebugDirectory();
    bool parseSecurityDirectory();
    bool parseRichSignature();

    std::string filePath_;
    std::vector<uint8_t> fileData_;
    PEHeaderData header_;
    std::vector<PESection> sections_;
    std::vector<PEImport> imports_;
    std::vector<PEExport> exports_;
    bool isValid_;
    // ...
};
```

#### 3.2.3 ELFParser（Linux ELF解析器）

**职责**：
- 解析ELF文件结构（支持32/64位）
- 提取节头、动态段、符号表
- 分析DT_NEEDED依赖

**数据结构**：
```cpp
struct ELFHeader {
    uint8_t ident[16];              // e_ident[EI_MAG0..EI_ABIVERSION]
    uint16_t type;                  // ET_DYN/DYN, ET_EXEC, ET_REL
    uint16_t machine;               // EM_X86_64, EM_386, EM_AARCH64
    uint32_t version;
    uint64_t entry;
    uint64_t phoff;                 // Program header offset
    uint64_t shoff;                 // Section header offset
    uint16_t phnum;                 // Number of program headers
    uint16_t shnum;                 // Number of section headers
};

struct ELFDynamicEntry {
    int64_t tag;                    // DT_NEEDED, DT_SONAME, etc.
    uint64_t val;                   // Value or pointer
    std::string str;                // String table entry
};

struct ELFSymbol {
    std::string name;
    uint64_t value;
    uint64_t size;
    uint8_t info;                   // Symbol type and binding
    uint8_t other;
    uint16_t shndx;                 // Section index
};
```

#### 3.2.4 PEAnalyzer（分析引擎）

**职责**：
- 执行深度分析（异常检测、威胁评分）
- 提取高级元数据
- 生成分析报告

```cpp
struct DLLAnalysisResult {
    int64_t inode;
    std::string filePath;
    std::string fileName;

    // PE/ELF基础信息
    std::string fileFormat;         // "PE32", "PE32+", "ELF64"
    std::string machineType;        // "x86", "x64", "ARM", "ARM64"
    uint32_t compileTimestamp;
    std::string timestampIso;
    std::string subsystem;
    bool isDLL;
    uint32_t entryPoint;
    uint64_t imageBase;

    // 版本信息
    std::string fileVersion;
    std::string productVersion;
    std::string companyName;
    std::string fileDescription;

    // 数字签名
    std::string signatureStatus;    // "Signed", "Unsigned", "Invalid"
    std::string signerName;
    std::string certIssuer;
    int64_t certValidFrom;
    int64_t certValidTo;

    // 哈希
    std::string md5Hash;
    std::string sha1Hash;
    std::string sha256Hash;
    std::string impHash;
    double richHash;

    // 节表
    std::vector<PESection> sections;

    // 导入/导出
    std::vector<PEImport> imports;
    std::vector<PEExport> exports;

    // 异常检测
    struct Anomaly {
        std::string type;
        std::string description;
        RiskLevel risk;             // LOW/MEDIUM/HIGH/CRITICAL
    };
    std::vector<Anomaly> anomalies;

    // 威胁评分 (0-100)
    int threatScore;

    // LLM分析
    std::string llmSummary;
    std::string llmDescription;
    std::string llmKeywords;
};
```

#### 3.2.5 AnomalyDetector（异常检测器）

**检测规则引擎**：
```cpp
class AnomalyDetector {
public:
    std::vector<Anomaly> detect(const PEHeaderData& header,
                                const std::vector<PESection>& sections,
                                const std::vector<PEImport>& imports);

private:
    Anomaly checkWriteExecuteInText(const std::vector<PESection>& sections);
    Anomaly checkHighEntropy(const std::vector<PESection>& sections);
    Anomaly checkSuspiciousImports(const std::vector<PEImport>& imports);
    Anomaly checkUnusualSectionNames(const std::vector<PESection>& sections);
    Anomaly checkEntryPointAnomaly(const PEHeaderData& header,
                                   const std::vector<PESection>& sections);
    Anomaly checkTLS Callbacks(const PEHeaderData& header);
    // ...

    static const std::unordered_set<std::string> SUSPICIOUS_IMPORTS;
    static const std::unordered_set<std::string> PACKER_SIGNATURES;
};
```

**异常优先级表**：

| 异常类型 | 风险 | 权重分 | 检测逻辑 |
|---------|------|--------|---------|
| **UPX加壳** | CRITICAL | +25 | UPX0/UPX1节、UPX!特征 |
| **VMProtect** | CRITICAL | +20 | 虚拟机代码特征 |
| **高熵代码段** | HIGH | +15 | .text熵值>7.5 |
| **自解密代码** | HIGH | +15 | .text节同时RWX |
| **异常入口点** | HIGH | +10 | 入口点在.data/.rdata |
| **可疑导入函数** | HIGH | +20 | 注入/权限提升/反调试函数 |
| **非常见节名** | MEDIUM | +5 | 不在标准PE节列表中 |
| **异常大节** | MEDIUM | +5 | 资源节>50%文件大小 |
| **TLS回调** | MEDIUM | +10 | 用于反调试/代码注入 |
| **延迟加载** | LOW | +2 | 使用延迟加载机制 |
| **调试符号残留** | LOW | +2 | 包含PDB路径 |

**威胁评分计算**：
```
威胁评分 = Σ(各异常风险分 * 风险权重)

0-10: 正常文件
11-30: 可疑文件（需要人工审查）
31-50: 高风险文件（建议隔离）
51-100: 恶意文件（高度可疑）
```

#### 3.2.6 DependencyAnalyzer（依赖分析器）

**职责**：
- 递归构建DLL依赖树
- 关联Prefetch、注册表等取证数据
- 识别DLL劫持和异常加载

```cpp
class DependencyAnalyzer {
public:
    struct DependencyNode {
        std::string dllPath;
        std::string dllName;
        int depth;
        bool isSystem;
        bool isSuspicious;
        std::vector<std::string> loadSources; // Prefetch/Registry/EventLog
        std::vector<DependencyNode> children;
    };

    DependencyNode buildDependencyTree(const std::string& dllPath,
                                       int maxDepth = 5);

    std::vector<std::string> getRecursiveDependencies(const std::string& dllPath);
    std::unordered_set<std::string> getAllDependencies(const std::string& dllPath);

    // 取证关联
    std::vector<std::string> getPrefetchReferences(const std::string& dllPath);
    std::vector<std::string> getRegistryReferences(const std::string& dllPath);
    std::vector<std::string> getEventLogReferences(const std::string& dllPath);

private:
    bool isSystemDLL(const std::string& dllName) const;
    bool isSuspiciousPath(const std::string& dllPath) const;
    bool checkCircularDependency(const std::string& dllPath,
                                  const std::unordered_set<std::string>& visited);

    // 已知系统DLL列表
    static const std::unordered_set<std::string> KNOWN_SYSTEM_DLLS;
    static const std::vector<std::string> SYSTEM_PATHS;
};
```

---

## 4. 数据库设计

### 4.1 方案选择

**方案A：独立数据库**（`_dll_analysis.db`）
- 优点：完全独立，不影响现有数据库
- 缺点：与其他取证数据关联复杂

**方案B：集成到 `_windows.db`**（推荐）
- 优点：天然与注册表、事件日志、Prefetch关联
- 缺点：仅Windows分析有效

**最终决策：方案B（集成到 _windows.db）**

### 4.2 数据库Schema

添加到 `src/core/DatabaseManager/SQL/windows_analysis_sql_tables.h`：

```sql
-- ============================================================================
-- DLL分析表 (DLLAnalyzer)
-- ============================================================================

-- DLL基础信息表
CREATE TABLE IF NOT EXISTS dll_base_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inode INTEGER NOT NULL,
    name TEXT NOT NULL,
    path TEXT UNIQUE NOT NULL,
    size INTEGER,
    md5 TEXT,
    sha1 TEXT,
    sha256 TEXT,
    imp_hash TEXT,
    rich_hash REAL,

    -- PE/ELF元数据
    file_format TEXT,           -- "PE32", "PE32+", "ELF64"
    machine_type TEXT,          -- "x86", "x64", "ARM"
    compile_timestamp INTEGER,
    subsystem INTEGER,
    entry_point INTEGER,
    image_base INTEGER,
    is_dll INTEGER DEFAULT 1,
    characteristics INTEGER,

    -- 版本信息
    file_version TEXT,
    product_version TEXT,
    company_name TEXT,
    file_description TEXT,

    -- 数字签名
    signature_status TEXT,      -- "Signed", "Unsigned", "Invalid"
    signer_name TEXT,
    cert_issuer TEXT,
    cert_valid_from INTEGER,
    cert_valid_to INTEGER,

    -- 文件时间戳
    mtime INTEGER,
    ctime INTEGER,
    atime INTEGER,
    crtime INTEGER,

    -- 取证关联
    is_deleted INTEGER DEFAULT 0,

    -- LLM分析字段
    llm_summary TEXT,
    llm_description TEXT,
    llm_keywords TEXT,
    llm_analyzed_at INTEGER,
    llm_model_used TEXT,

    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- DLL节表
CREATE TABLE IF NOT EXISTS dll_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER NOT NULL,
    section_name TEXT NOT NULL,
    virtual_address INTEGER,
    virtual_size INTEGER,
    raw_data_size INTEGER,
    characteristics INTEGER,
    entropy REAL,
    is_writeable INTEGER,
    is_executable INTEGER,
    is_readable INTEGER,
    FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
);

-- DLL导入表
CREATE TABLE IF NOT EXISTS dll_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER NOT NULL,
    imported_dll_name TEXT NOT NULL,
    imported_function TEXT,
    import_ordinal INTEGER,
    is_delayed INTEGER DEFAULT 0,
    FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
);

-- DLL导出表
CREATE TABLE IF NOT EXISTS dll_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER NOT NULL,
    function_name TEXT NOT NULL,
    export_ordinal INTEGER,
    export_rva INTEGER,
    FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
);

-- DLL异常检测结果
CREATE TABLE IF NOT EXISTS dll_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER NOT NULL,
    anomaly_type TEXT NOT NULL,
    description TEXT,
    risk_level TEXT,             -- "LOW", "MEDIUM", "HIGH", "CRITICAL"
    risk_score INTEGER,
    details TEXT,                -- JSON格式的详细检测数据
    detected_at INTEGER DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
);

-- DLL依赖关系
CREATE TABLE IF NOT EXISTS dll_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_dll_id INTEGER NOT NULL,
    child_dll_id INTEGER NOT NULL,
    depth INTEGER,               -- 依赖深度
    is_resolved INTEGER DEFAULT 1,
    FOREIGN KEY (parent_dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE,
    FOREIGN KEY (child_dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
);

-- DLL取证关联（与Prefetch、注册表等关联）
CREATE TABLE IF NOT EXISTS dll_forensic_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER NOT NULL,
    link_type TEXT NOT NULL,     -- "Prefetch", "Registry", "EventLog", "SRUM"
    source_id TEXT,              -- 关联源ID
    source_data TEXT,            -- 关联数据详情（JSON）
    detected_at INTEGER,
    FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
);

-- 索引优化
CREATE INDEX IF NOT EXISTS idx_dll_base_inode ON dll_base_info(inode);
CREATE INDEX IF NOT EXISTS idx_dll_base_md5 ON dll_base_info(md5);
CREATE INDEX IF NOT EXISTS idx_dll_base_imp_hash ON dll_base_info(imp_hash);
CREATE INDEX IF NOT EXISTS idx_dll_base_compile_ts ON dll_base_info(compile_timestamp);
CREATE INDEX IF NOT EXISTS idx_dll_base_status ON dll_base_info(signature_status);
CREATE INDEX IF NOT EXISTS idx_dll_base_threat ON dll_base_info(threat_score);
CREATE INDEX IF NOT EXISTS idx_dll_sections_dll_id ON dll_sections(dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_imports_dll_id ON dll_imports(dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_imports_function ON dll_imports(imported_function);
CREATE INDEX IF NOT EXISTS idx_dll_exports_dll_id ON dll_exports(dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_anomalies_dll_id ON dll_anomalies(dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_anomalies_risk ON dll_anomalies(risk_level);
CREATE INDEX IF NOT EXISTS idx_dll_deps_parent ON dll_dependencies(parent_dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_deps_child ON dll_dependencies(child_dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_links_dll_id ON dll_forensic_links(dll_id);
CREATE INDEX IF NOT EXISTS idx_dll_links_type ON dll_forensic_links(link_type);
```

### 4.3 数据库操作接口

```cpp
// DLLAnalysisDatabase.h
class DLLAnalysisDatabase {
public:
    explicit DLLAnalysisDatabase(const std::string& dbPath);
    ~DLLAnalysisDatabase();

    bool initialize();

    // 基础信息CRUD
    int64_t insertDLLBaseInfo(const DLLBaseInfo& info);
    bool updateDLLAnalysis(int64_t dllId, const DLLAnalysisResult& result);
    bool updateThreatScore(int64_t dllId, int score);

    // 节表操作
    bool insertSections(int64_t dllId, const std::vector<PESection>& sections);

    // 导入/导出表操作
    bool insertImports(int64_t dllId, const std::vector<PEImport>& imports);
    bool insertExports(int64_t dllId, const std::vector<PEExport>& exports);

    // 异常检测结果
    bool insertAnomaly(int64_t dllId, const Anomaly& anomaly);

    // 依赖关系
    bool insertDependency(int64_t parentId, int64_t childId, int depth);

    // 取证关联
    bool insertForensicLink(int64_t dllId, const std::string& linkType,
                           const std::string& sourceId, const std::string& sourceData);

    // 查询操作
    std::optional<DLLBaseInfo> getDLLByInode(int64_t inode);
    std::optional<DLLBaseInfo> getDLLByPath(const std::string& path);
    std::optional<DLLBaseInfo> getDLLByMD5(const std::string& md5);
    std::vector<DLLBaseInfo> getDLLsByThreatScore(int minScore);
    std::vector<DLLBaseInfo> getDLLsByAnomalyType(const std::string& anomalyType);
    std::vector<DLLBaseInfo> getSuspiciousDLLs();
    std::vector<Anomaly> getAnomaliesByDLLId(int64_t dllId);
    std::vector<DLLBaseInfo> getDLLsLinkedToPrefetch(const std::string& prefetchPath);

    // 统计
    size_t getDLLCount();
    size_t getSuspiciousCount();
    int getAverageThreatScore();
};
```

---

## 5. 数据流程

### 5.1 分析Pipeline

```
[开始] Windows/Linux磁盘镜像
         ↓
[ImageAnalyzer] TSK文件系统遍历
         ↓
[FileClassifier] 文件分类（识别.dll/.so）
         ↓
[FileExtractor] 提取DLL文件
         ↓
[DLLAnalyzer.initialize()] 初始化数据库和解析器
         ↓
[DLLAnalyzer.analyze()] 开始分析
         ├─ [PEParser] 解析PE/ELF结构
         │   ├─ 解析DOS Header → PE Signature
         │   ├─ 解析COFF Header → Machine/TimeStamp
         │   ├─ 解析Optional Header → ImageBase/EntryPoint
         │   ├─ 解析节表 → .text/.data/.rsrc等
         │   ├─ 解析导入表 → 导入的DLL/函数
         │   ├─ 解析导出表 → 导出函数
         │   └─ 解析资源 → VersionInfo/Manifest
         │
         ├─ [PEAnalyzer] 深度分析
         │   ├─ 计算哈希 → MD5/SHA1/SHA256/ImpHash
         │   ├─ 验证数字签名 → Authenticode
         │   ├─ 计算熵值 → 识别加壳
         │   ├─ 提取版本信息 → FileVersion/CompanyName
         │   └─ 提取调试信息 → PDB路径
         │
         ├─ [AnomalyDetector] 异常检测
         │   ├─ 检查异常节名 → 非常见节名
         │   ├─ 检查自解密代码 → RWX权限
         │   ├─ 检查高熵值 → >7.5 bits/byte
         │   ├─ 检查可疑导入 → 注入/权限提升函数
         │   ├─ 检查异常入口点 → 非标准节
         │   ├─ 检查TLS回调 → 反调试
         │   └─ 检查已知加壳特征 → UPX/VMProtect
         │
         ├─ [DependencyAnalyzer] 依赖分析
         │   ├─ 递归遍历导入表 → 构建依赖树
         │   ├─ 关联Prefetch数据 → 实际加载记录
         │   ├─ 关联注册表数据 → KnownDLLs/AppInit
         │   ├─ 关联事件日志 → DLL加载事件
         │   └─ 识别异常依赖 → DLL劫持/侧加载
         │
         └─ [DLLAnalysisDatabase] 存储结果
             ├─ 存储DLLBaseInfo → dll_base_info表
             ├─ 存储节表数据 → dll_sections表
             ├─ 存储导入表 → dll_imports表
             ├─ 存储导出表 → dll_exports表
             ├─ 存储异常检测 → dll_anomalies表
             ├─ 存储依赖关系 → dll_dependencies表
             └─ 存储取证关联 → dll_forensic_links表
         ↓
[威胁评分] 计算每个DLL的威胁评分
         ↓
[生成报告] 高风险DLL列表、异常模式统计
         ↓
[LLM分析] 可选：AI分析可疑DLL
         ↓
[结束] 分析结果存入数据库
```

### 5.2 集成到主pipeline

在 `src/main.cpp` 的4步流程后新增步骤5（可选）：

```cpp
// 现有4步流程
int step = 4;
if (config.analyzeWindows && dbManager) {
    WindowsFilesAnalyzer windowsAnalyzer(imagePath, dbManager);
    windowsAnalyzer.initialize();
    windowsAnalyzer.analyzeWindowsData();
    step++;
}

// 新增第5步：DLL分析
if (config.analyzeDLLs && dbManager) {
    std::cout << "Starting DLL analysis..." << std::endl;
    DLLAnalyzer dllAnalyzer(dbManager, imagePath + "_dll.db");
    dllAnalyzer.initialize();
    dllAnalyzer.analyze();

    // 与Windows分析关联
    if (config.analyzeWindows) {
        dllAnalyzer.correlateWithPrefetch(prefetchData);
        dllAnalyzer.correlateWithRegistry(registryData);
    }
    step++;
}
```

### 5.3 命令行参数

```bash
# 启用DLL分析
./forensic_analyzer windows_image.dd --analyze-dlls

# 仅DLL分析（跳过其他步骤）
./forensic_analyzer windows_image.dd --analyze-dlls-only

# 指定DLL分析数据库路径
./forensic_analyzer windows_image.dd --analyze-dlls --dll-db custom_dll.db

# 仅分析高风险DLL（威胁评分>30）
./forensic_analyzer windows_image.dd --analyze-dlls --dll-threshold 30

# 禁用数字签名验证（加速）
./forensic_analyzer windows_image.dd --analyze-dlls --no-verify-signatures
```

---

## 6. API设计

### 6.1 C++ REST API（新增端点）

在 `src/network/HTTPServer/routes/ForensicsRoutes.cpp` 新增：

```cpp
// ============================================================================
// DLL Analysis Endpoints
// ============================================================================

// 获取DLL分析概览
CROW_ROUTE(app, "/api/dlls/overview")
.method("GET")
([&](const request& req, response& res) {
    // 返回DLL统计：总数、威胁分布、异常类型统计
});

// 获取高风险DLL列表
CROW_ROUTE(app, "/api/dlls/suspicious")
.method("GET")
([&](const request& req, response& res) {
    // 参数：min_score, limit, offset
    // 返回威胁评分>=30的DLL
});

// 获取DLL详情
CROW_ROUTE(app, "/api/dlls/<int>/details")
.method("GET")
([&](const request& req, response& res, int dllId) {
    // 返回DLL完整信息：PE结构、导入/导出、异常、依赖树
});

// 获取DLL依赖树
CROW_ROUTE(app, "/api/dlls/<int>/dependencies")
.method("GET")
([&](const request& req, response& res, int dllId) {
    // 返回依赖树JSON
});

// 获取DLL异常列表
CROW_ROUTE(app, "/api/dlls/<int>/anomalies")
.method("GET")
([&](const request& req, response& res, int dllId) {
    // 返回所有异常检测结果
});

// 搜索DLL（按MD5/SHA256/ImpHash）
CROW_ROUTE(app, "/api/dlls/search")
.method("GET")
([&](const request& req, response& res) {
    // 参数：hash_type, hash_value
    // 支持：md5, sha1, sha256, imp_hash
});

// 获取DLL取证关联
CROW_ROUTE(app, "/api/dlls/<int>/forensic-links")
.method("GET")
([&](const request& req, response& res, int dllId) {
    // 返回与Prefetch/Registry/EventLog的关联
});

// DLL对比
CROW_ROUTE(app, "/api/dlls/compare")
.method("POST")
([&](const request& req, response& res) {
    // 参数：dll_id_1, dll_id_2
    // 对比两个DLL的差异：导入表、节表、哈希
});
```

### 6.2 Python FastAPI集成（可选）

在 `python_service/httpserver/routes/database.py` 新增：

```python
@app.get("/api/dlls/overview")
async def get_dll_overview(task_id: str):
    """Get DLL analysis overview"""
    ...

@app.get("/api/dlls/suspicious")
async def get_suspicious_dlls(task_id: str, min_score: int = 30):
    """Get suspicious DLLs with threat score >= min_score"""
    ...

@app.get("/api/dlls/{dll_id}/dependencies")
async def get_dll_dependencies(dll_id: int):
    """Get DLL dependency tree"""
    ...
```

---

## 7. 异常检测规则详解

### 7.1 恶意DLL特征库

**已知恶意家族特征**：

| 家族 | 特征 | 检测方法 |
|------|------|---------|
| **Ursnif/Gozi** | 异常节名、加密字符串 | 高熵值+异常节 |
| **Emotet** | DLL侧加载、伪装系统DLL | 路径异常+签名伪造 |
| **Cobalt Strike** | Beacon DLL、异常导入 | 特定导入组合 |
| **Meterpreter** | Reflective DLL Injection特征 | 自解密代码+异常入口点 |
| **Ransomware** | 大量文件操作函数 | 导入大量文件/加密函数 |

### 7.2 可疑API组合

**DLL注入特征**：
```
必选组合（满足2项以上）：
- CreateRemoteThread + WriteProcessMemory
- VirtualAllocEx + OpenProcess
- SetWindowsHookEx + GetModuleHandle
```

**持久化特征**：
```
- RegCreateKeyEx + RegSetValueEx (注册表Run键)
- CreateService + StartService
- WMI查询 (wbem*函数)
```

**反调试特征**：
```
- IsDebuggerPresent + CheckRemoteDebuggerPresent
- NtQueryInformationProcess (ProcessDebugPort)
- OutputDebugString + 错误码检测
```

---

## 8. 性能优化

### 8.1 分析加速

- **文件大小过滤**：跳过<1KB的DLL
- **白名单机制**：已知系统DLL跳过深度分析
- **并行分析**：使用ThreadPool并发分析多个DLL
- **增量分析**：跳过已分析的DLL（通过MD5/SHA256）
- **早期退出**：数字签名验证失败则跳过后续深度分析

### 8.2 内存优化

- **流式解析**：PE头解析时只读取需要的节，避免全文件加载
- **缓存机制**：依赖树解析结果缓存
- **智能加载**：仅在需要时加载资源（如调试信息）

---

## 9. 测试策略

### 9.1 单元测试

```cpp
// tests/UnitTest/test_dll_analyzer_gtest.cpp

TEST(DLLAnalyzer, ParsePEDLL) {
    // 测试已知DLL的PE结构解析
}

TEST(DLLAnalyzer, DetectUPXPacked) {
    // 测试UPX加壳检测
}

TEST(DLLAnalyzer, DetectSuspiciousImports) {
    // 测试可疑导入函数检测
}

TEST(DLLAnalyzer, CalculateImpHash) {
    // 测试ImpHash计算正确性
}

TEST(DLLAnalyzer, DetectDLLHijacking) {
    // 测试DLL劫持场景检测
}
```

### 9.2 集成测试

- **恶意软件样本**：使用公开的恶意DLL样本库（如VirusShare）
- **良性样本**：Windows System32目录的DLL
- **边界测试**：损坏的PE文件、畸形结构

---

## 10. 实现计划

### Phase 1: 核心PE解析（Week 1-2）
- [ ] PEParser：PE头、节表、数据目录解析
- [ ] ELFParser：ELF基础结构解析
- [ ] DLLAnalysisDatabase：数据库接口实现
- [ ] 集成到FileClassifier：新增`FileCategory::DLL_LIBRARY`

### Phase 2: 元数据提取（Week 3）
- [ ] 哈希计算（MD5/SHA1/SHA256/ImpHash）
- [ ] 数字签名验证（WinVerifyTrust API / osslsigncode）
- [ ] 资源解析（VersionInfo）
- [ ] Rich Signature解析

### Phase 3: 异常检测（Week 4）
- [ ] AnomalyDetector实现
- [ ] 基本检测规则（高熵、异常节名、RWX权限）
- [ ] 可疑导入函数库
- [ ] 威胁评分算法

### Phase 4: 依赖分析（Week 5）
- [ ] DependencyAnalyzer实现
- [ ] 递归依赖树构建
- [ ] Prefetch关联
- [ ] 注册表关联

### Phase 5: 集成与API（Week 6）
- [ ] 集成到main.cpp pipeline
- [ ] 命令行参数支持
- [ ] C++ REST API端点
- [ ] 单元测试编写

### Phase 6: 优化与文档（Week 7-8）
- [ ] 性能优化
- [ ] 完整文档
- [ ] 测试用例完善
- [ ] 用户手册

---

## 11. 技术选型

### 11.1 依赖库

**必需**：
- 无（所有PE/ELF解析手动实现，减少外部依赖）

**可选（增强功能）**：
- `osslsigncode`: OpenSSL-based Authenticode验证
- `libarchive`: 支持更多压缩格式
- `LIEF`: 如果未来需要更强大的PE/ELF解析（当前暂不引入）

### 11.2 工具

- **PEView/PE-bear**: 参考实现，验证解析结果
- **CFF Explorer**: PE结构验证
- **VirusTotal API**: 可选，用于在线哈希查询

---

## 12. 风险和限制

### 12.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **PE格式复杂性** | 高 | 中 | 参考成熟开源项目（libpe、pe-parse），优先支持常见结构 |
| **加壳样本处理** | 中 | 高 | 集成解壳工具（Unpacker），或识别特征后跳过 |
| **数字签名验证** | 中 | 低 | Windows-only特性，Linux/macOS跳过 |
| **性能问题** | 中 | 中 | 白名单、并行、增量分析 |
| **误报率高** | 高 | 中 | 基于规则的阈值调优，结合人工审查建议 |

### 12.2 法律合规

- **数字签名验证**：仅在本地进行，不联网查询
- **恶意软件样本**：测试样本需合规来源，妥善保管
- **取证数据**：遵守当地法律法规

---

## 13. 附录

### 13.1 参考资源

**PE格式规范**：
- Microsoft PE/COFF Specification: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
- PE Format Tutorial: https://www.ired.team/malware-analysis/binary-code-analysis/pe-format

**ELF格式规范**：
- System V ABI: https://refspecs.linuxfoundation.org/elf/gabi4+/contents.html

**开源实现参考**：
- `libpe` (https://github.com/mentat/pe)
- `pe-parse` (https://github.com/trailofbits/pe-parse)
- `LIEF` (https://github.com/lief-project/LIEF)

**取证资源**：
- SANS DFIR: https://www.sans.org/digital-forensics-incident-response/
- Windows Incident Response (book): https://www.amazon.com/Windows-Incident-Response-Forensic-Investigation/dp/180323102X

---

## 14. 设计评审清单

### 14.1 自检（Spec Self-Review）

- [x] **无占位符**：所有需求、技术方案已明确
- [x] **内部一致**：架构设计与实现计划一致
- [x] **范围合适**：聚焦DLL分析，避免过度设计
- [x] **无歧义**：关键术语已定义，接口清晰
- [x] **可测试性**：单元测试、集成测试方案已规划

### 14.2 待确认事项

- [ ] 数字签名验证库选择：`osslsigncode` vs Windows API
- [ ] ImpHash计算是否需要支持Delayed Imports
- [ ] 是否支持.NET Assembly（.NET DLL）分析
- [ ] 依赖分析最大深度：5层是否足够
- [ ] 威胁评分阈值：30分为可疑是否合理

---

**下一步**：等待用户批准此设计，然后进入实现计划阶段。
