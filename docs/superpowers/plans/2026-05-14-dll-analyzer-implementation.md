# DLLAnalyzer 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现动态链接库（DLL/so）的完整取证分析，包括PE/ELF结构解析、元数据提取、异常检测和依赖分析

**Architecture:** 创建独立DLLAnalyzer模块，采用三层架构：PE/ELF解析层 → 元数据提取层 → 取证分析层（异常检测+依赖分析）。集成到Windows分析器pipeline，数据存储在现有Windows数据库。

**Tech Stack:** C++20, SQLite, TSK, GTest, CMake

---

## 文件结构总览

```
src/analyzers/DLLAnalyzer/
├── Common/
│   ├── DLLDataTypes.h              # 数据结构定义
│   └── DLLAnalyzerDeclarations.h   # 前向声明
├── Core/
│   ├── DLLAnalyzer.h               # 主类声明
│   ├── DLLAnalyzerCore.cpp         # 主类实现
│   ├── PEAnalyzer.h                # PE分析引擎
│   └── PEAnalyzer.cpp
├── Parsers/
│   ├── PEHeaderParser.h            # PE头解析
│   ├── PEHeaderParser.cpp
│   ├── PESectionParser.h           # 节表解析
│   ├── PESectionParser.cpp
│   ├── PEImportExportParser.h      # 导入/导出解析
│   ├── PEImportExportParser.cpp
│   ├── PEResourceParser.h          # 资源解析
│   └── SignatureVerifier.h         # 签名验证
└── Database/
    ├── DLLAnalysisDatabase.h       # 数据库接口
    └── DLLAnalysisDatabase.cpp

src/core/DatabaseManager/SQL/
├── windows_analysis_sql_tables.h   # 修改：添加DLL表
├── windows_analysis_sql_crud.h     # 修改：添加DLL CRUD
└── windows_analysis_sql_llm.h      # 修改：添加DLL LLM支持

tests/UnitTest/
└── test_dll_analyzer_gtest.cpp     # 新增：单元测试

src/analyzers/WindowsFilesAnalyzer/
└── WindowsFilesAnalyzerCore.cpp    # 修改：集成DLL分析
```

---

## 阶段0：基础设施（Database Schema + 数据类型）

### Task 1: 创建DLL数据结构定义

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Common/DLLDataTypes.h`
- Create: `src/analyzers/DLLAnalyzer/Common/DLLAnalyzerDeclarations.h`

- [ ] **Step 1: 创建DLLDataTypes.h基础结构**

```cpp
// DLLDataTypes.h
// 数据结构定义：PE头、节、导入/导出、分析结果

#pragma once
#ifndef DLL_DATA_TYPES_H
#define DLL_DATA_TYPES_H

#include <string>
#include <vector>
#include <cstdint>
#include <sqlite3.h>

namespace forensics {
namespace dll {

// ============================================================================
// PE文件格式常量
// ============================================================================

// PE签名
inline constexpr uint16_t DOS_MAGIC = 0x5A4D;        // "MZ"
inline constexpr uint32_t PE_SIGNATURE = 0x00004550;  // "PE\0\0"
inline constexpr uint16_t PE32_MAGIC = 0x10B;         // PE32
inline constexpr uint16_t PE32PLUS_MAGIC = 0x20B;     // PE32+ (x64)
inline constexpr uint16_t ROM_MAGIC = 0x107;          // ROM

// 机器类型
enum class MachineType : uint16_t {
    UNKNOWN = 0x0,
    X86 = 0x14C,
    x64 = 0x8664,
    ARM = 0x1C0,
    ARM64 = 0xAA64,
    IA64 = 0x200
};

// 子系统类型
enum class SubsystemType : uint16_t {
    UNKNOWN = 0,
    NATIVE = 1,
    WINDOWS_GUI = 2,
    WINDOWS_CUI = 3,
    OS2_CUI = 5,
    POSIX_CUI = 7,
    NATIVE_WINDOWS = 8,
    WINDOWS_CE_GUI = 9,
    EFI_APPLICATION = 10,
    EFI_BOOT_SERVICE = 11,
    EFI_RUNTIME = 12,
    EFI_ROM = 13,
    XBOX = 14
};

// 节特征标志
inline constexpr uint32_t SECTION_READ = 0x40000000;
inline constexpr uint32_t SECTION_WRITE = 0x80000000;
inline constexpr uint32_t SECTION_EXECUTE = 0x20000000;

// ============================================================================
// PE数据结构
// ============================================================================

#pragma pack(push, 1)

// DOS头
struct DOSHeader {
    uint16_t e_magic;              // 0x5A4D "MZ"
    uint16_t e_cblp;
    uint16_t e_cp;
    uint16_t e_crlc;
    uint16_t e_cparhdr;
    uint16_t e_minalloc;
    uint16_t e_maxalloc;
    uint16_t e_ss;
    uint16_t e_sp;
    uint16_t e_csum;
    uint16_t e_ip;
    uint16_t e_cs;
    uint16_t e_lfarlc;
    uint16_t e_ovno;
    uint16_t e_res[4];
    uint16_t e_oemid;
    uint16_t e_oeminfo;
    uint16_t e_res2[10];
    uint32_t e_lfanew;             // PE头偏移
};

// COFF文件头
struct COFFHeader {
    uint16_t machine;              // 机器类型
    uint16_t numberOfSections;
    uint32_t timestamp;
    uint32_t pointerToSymbolTable;
    uint32_t numberOfSymbols;
    uint16_t sizeOfOptionalHeader;
    uint16_t characteristics;
};

// 数据目录项
struct DataDirectory {
    uint32_t virtualAddress;
    uint32_t size;
};

// 可选头（PE32/PE32+通用部分）
struct OptionalHeaderBase {
    uint16_t magic;                // PE32/PE32+
    uint8_t  majorLinkerVersion;
    uint8_t  minorLinkerVersion;
    uint32_t sizeOfCode;
    uint32_t sizeOfInitializedData;
    uint32_t sizeOfUninitializedData;
    uint32_t addressOfEntryPoint;
    uint32_t baseOfCode;
    // PE32+: baseOfData omitted, uint64_t imageBase follows
};

// PE32可选头（32位）
struct OptionalHeaderPE32 {
    OptionalHeaderBase base;
    uint32_t baseOfData;
    uint32_t imageBase;
    uint32_t sectionAlignment;
    uint32_t fileAlignment;
    uint16_t majorOSVersion;
    uint16_t minorOSVersion;
    uint16_t majorImageVersion;
    uint16_t minorImageVersion;
    uint16_t majorSubsystemVersion;
    uint16_t minorSubsystemVersion;
    uint32_t win32VersionValue;
    uint32_t sizeOfImage;
    uint32_t sizeOfHeaders;
    uint32_t checkSum;
    uint16_t subsystem;
    uint16_t dllCharacteristics;
    uint32_t sizeOfStackReserve;
    uint32_t sizeOfStackCommit;
    uint32_t sizeOfHeapReserve;
    uint32_t sizeOfHeapCommit;
    uint32_t loaderFlags;
    uint32_t numberOfRvaAndSizes;
    DataDirectory dataDirectories[16];
};

// PE32+可选头（64位）
struct OptionalHeaderPE32Plus {
    OptionalHeaderBase base;
    uint64_t imageBase;
    uint32_t sectionAlignment;
    uint32_t fileAlignment;
    uint16_t majorOSVersion;
    uint16_t minorOSVersion;
    uint16_t majorImageVersion;
    uint16_t minorImageVersion;
    uint16_t majorSubsystemVersion;
    uint16_t minorSubsystemVersion;
    uint32_t win32VersionValue;
    uint32_t sizeOfImage;
    uint32_t sizeOfHeaders;
    uint32_t checkSum;
    uint16_t subsystem;
    uint16_t dllCharacteristics;
    uint64_t sizeOfStackReserve;
    uint64_t sizeOfStackCommit;
    uint64_t sizeOfHeapReserve;
    uint64_t sizeOfHeapCommit;
    uint32_t loaderFlags;
    uint32_t numberOfRvaAndSizes;
    DataDirectory dataDirectories[16];
};

// 节表项
struct SectionHeader {
    char name[8];
    uint32_t virtualSize;
    uint32_t virtualAddress;
    uint32_t sizeOfRawData;
    uint32_t pointerToRawData;
    uint32_t pointerToRelocations;
    uint32_t pointerToLinenumbers;
    uint16_t numberOfRelocations;
    uint16_t numberOfLinenumbers;
    uint32_t characteristics;
};

#pragma pack(pop)

// ============================================================================
// 分析数据结构
// ============================================================================

// PE节信息
struct PESectionInfo {
    std::string name;
    uint32_t virtualAddress;
    uint32_t virtualSize;
    uint32_t rawDataSize;
    uint32_t characteristics;
    double entropy;
    bool isWriteable;
    bool isExecutable;
    bool isReadable;
};

// 导入的DLL
struct ImportedDLL {
    std::string name;
    std::vector<std::string> functions;
    bool isDelayed;
};

// 导出的函数
struct ExportedFunction {
    std::string name;
    uint16_t ordinal;
    uint32_t rva;
};

// PE头信息汇总
struct PEHeaderInfo {
    // 基础信息
    bool isValid;
    std::string format;             // "PE32" or "PE32+"
    MachineType machine;
    uint16_t numberOfSections;
    uint32_t timestamp;
    uint16_t characteristics;
    bool isDLL;

    // 可选头信息
    uint64_t imageBase;
    uint32_t sectionAlignment;
    uint32_t fileAlignment;
    uint16_t subsystem;
    uint32_t entryPointRVA;
    uint32_t checkSum;

    // 数据目录RVA
    uint32_t exportTableRVA;
    uint32_t importTableRVA;
    uint32_t resourceTableRVA;
    uint32_t debugTableRVA;
    uint32_t tlsTableRVA;
    uint32_t loadConfigTableRVA;
    uint32_t securityTableRVA;

    // 节表
    std::vector<PESectionInfo> sections;
};

// 异常检测结果
enum class RiskLevel {
    LOW = 0,
    MEDIUM = 1,
    HIGH = 2,
    CRITICAL = 3
};

struct Anomaly {
    std::string type;               // 异常类型
    std::string description;        // 详细描述
    RiskLevel risk;
    int riskScore;                  // 风险分数 0-100
};

// DLL分析结果汇总
struct DLLAnalysisResult {
    // 文件信息
    int64_t inode;
    std::string filePath;
    std::string fileName;
    uint64_t fileSize;

    // PE信息
    PEHeaderInfo peHeader;

    // 导入/导出
    std::vector<ImportedDLL> imports;
    std::vector<ExportedFunction> exports;

    // 哈希
    std::string md5Hash;
    std::string sha1Hash;
    std::string sha256Hash;
    std::string impHash;

    // 版本信息
    std::string fileVersion;
    std::string productVersion;
    std::string companyName;
    std::string fileDescription;

    // 数字签名
    std::string signatureStatus;    // "Signed", "Unsigned", "Invalid"
    std::string signerName;

    // 异常检测
    std::vector<Anomaly> anomalies;
    int threatScore;                // 0-100

    // LLM分析
    std::string llmSummary;
    std::string llmDescription;
    std::string llmKeywords;
};

} // namespace dll
} // namespace forensics

#endif // DLL_DATA_TYPES_H
```

- [ ] **Step 2: 创建DLLAnalyzerDeclarations.h前向声明**

```cpp
// DLLAnalyzerDeclarations.h
// 前向声明和类前置声明

#pragma once
#ifndef DLL_ANALYZER_DECLARATIONS_H
#define DLL_ANALYZER_DECLARATIONS_H

#include "DLLDataTypes.h"

namespace forensics {
namespace dll {

// 前向声明
class PEParser;
class ELFParser;
class PEAnalyzer;
class AnomalyDetector;
class DependencyAnalyzer;

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYZER_DECLARATIONS_H
```

- [ ] **Step 3: 提交基础设施代码**

```bash
git add src/analyzers/DLLAnalyzer/Common/
git commit -m "feat: add DLL data types and declarations

- Add DLLDataTypes.h with PE header structures
- Add DLLAnalyzerDeclarations.h for forward declarations
- Define constants: DOS_MAGIC, PE_SIGNATURE, section flags
- Define enums: MachineType, SubsystemType, RiskLevel
- Define structs: DOSHeader, COFFHeader, OptionalHeaderPE32/PE32Plus
- Define structs: PESectionInfo, ImportedDLL, ExportedFunction
- Define structs: PEHeaderInfo, Anomaly, DLLAnalysisResult

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: 扩展数据库Schema

**Files:**
- Modify: `src/core/DatabaseManager/SQL/windows_analysis_sql_tables.h:10-8`
- Modify: `src/core/DatabaseManager/SQL/windows_analysis_sql_crud.h`
- Modify: `src/core/DatabaseManager/SQL/windows_analysis_sql_llm.h`

- [ ] **Step 1: 在windows_analysis_sql_tables.h中添加DLL表定义**

在现有文件末尾添加：

```cpp
// 添加到 windows_analysis_sql_tables.h 文件末尾

// ============================================================================
// DLL Analysis Tables
// ============================================================================

inline constexpr const char* CREATE_DLL_BASE_INFO_TABLE = R"(
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
        file_format TEXT,
        machine_type TEXT,
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
        signature_status TEXT,
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
        threat_score INTEGER DEFAULT 0,

        -- LLM分析字段
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT,

        created_at INTEGER DEFAULT (strftime('%s', 'now'))
    );
)";

inline constexpr const char* CREATE_DLL_SECTIONS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS dll_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        section_name TEXT NOT NULL,
        virtual_address INTEGER,
        virtual_size INTEGER,
        raw_data_size INTEGER,
        characteristics INTEGER,
        entropy REAL,
        is_writeable INTEGER DEFAULT 0,
        is_executable INTEGER DEFAULT 0,
        is_readable INTEGER DEFAULT 0,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

inline constexpr const char* CREATE_DLL_IMPORTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS dll_imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        imported_dll_name TEXT NOT NULL,
        imported_function TEXT,
        import_ordinal INTEGER,
        is_delayed INTEGER DEFAULT 0,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

inline constexpr const char* CREATE_DLL_EXPORTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS dll_exports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        function_name TEXT NOT NULL,
        export_ordinal INTEGER,
        export_rva INTEGER,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

inline constexpr const char* CREATE_DLL_ANOMALIES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS dll_anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        anomaly_type TEXT NOT NULL,
        description TEXT,
        risk_level TEXT,
        risk_score INTEGER,
        details TEXT,
        detected_at INTEGER DEFAULT (strftime('%s', 'now')),
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

inline constexpr const char* CREATE_DLL_DEPENDENCIES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS dll_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_dll_id INTEGER NOT NULL,
        child_dll_id INTEGER NOT NULL,
        depth INTEGER,
        is_resolved INTEGER DEFAULT 1,
        FOREIGN KEY (parent_dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE,
        FOREIGN KEY (child_dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

inline constexpr const char* CREATE_DLL_FORENSIC_LINKS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS dll_forensic_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dll_id INTEGER NOT NULL,
        link_type TEXT NOT NULL,
        source_id TEXT,
        source_data TEXT,
        detected_at INTEGER,
        FOREIGN KEY (dll_id) REFERENCES dll_base_info(id) ON DELETE CASCADE
    );
)";

// DLL索引
inline constexpr const char* CREATE_DLL_INDICES = R"(
    CREATE INDEX IF NOT EXISTS idx_dll_base_inode ON dll_base_info(inode);
    CREATE INDEX IF NOT EXISTS idx_dll_base_md5 ON dll_base_info(md5);
    CREATE INDEX IF NOT EXISTS idx_dll_base_imp_hash ON dll_base_info(imp_hash);
    CREATE INDEX IF NOT EXISTS idx_dll_base_compile_ts ON dll_base_info(compile_timestamp);
    CREATE INDEX IF NOT EXISTS idx_dll_base_signature ON dll_base_info(signature_status);
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
)";

// 添加到CREATE_ALL_TABLES
// 修改现有宏，在末尾添加:
// CREATE_DLL_BASE_INFO_TABLE
// CREATE_DLL_SECTIONS_TABLE
// CREATE_DLL_IMPORTS_TABLE
// CREATE_DLL_EXPORTS_TABLE
// CREATE_DLL_ANOMALIES_TABLE
// CREATE_DLL_DEPENDENCIES_TABLE
// CREATE_DLL_FORENSIC_LINKS_TABLE
// CREATE_DLL_INDICES
```

- [ ] **Step 2: 在windows_analysis_sql_crud.h中添加DLL CRUD操作**

```cpp
// 添加到 windows_analysis_sql_crud.h 文件末尾

// DLL基础信息
inline constexpr const char* INSERT_DLL_BASE_INFO = R"(
    INSERT INTO dll_base_info (
        inode, name, path, size, md5, sha1, sha256, imp_hash, rich_hash,
        file_format, machine_type, compile_timestamp, subsystem,
        entry_point, image_base, is_dll, characteristics,
        file_version, product_version, company_name, file_description,
        signature_status, signer_name, cert_issuer, cert_valid_from, cert_valid_to,
        mtime, ctime, atime, crtime, is_deleted, threat_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_BY_INODE = R"(
    SELECT * FROM dll_base_info WHERE inode = ?;
)";

inline constexpr const char* SELECT_DLL_BY_PATH = R"(
    SELECT * FROM dll_base_info WHERE path = ?;
)";

inline constexpr const char* SELECT_DLL_BY_MD5 = R"(
    SELECT * FROM dll_base_info WHERE md5 = ?;
)";

inline constexpr const char* SELECT_DLL_BY_IMP_HASH = R"(
    SELECT * FROM dll_base_info WHERE imp_hash = ?;
)";

inline constexpr const char* SELECT_SUSPICIOUS_DLLS = R"(
    SELECT * FROM dll_base_info WHERE threat_score >= ? ORDER BY threat_score DESC;
)";

inline constexpr const char* SELECT_ALL_DLLS = R"(
    SELECT * FROM dll_base_info ORDER BY compile_timestamp DESC;
)";

inline constexpr const char* UPDATE_DLL_THREAT_SCORE = R"(
    UPDATE dll_base_info SET threat_score = ? WHERE id = ?;
)";

inline constexpr const char* UPDATE_DLL_ANALYSIS = R"(
    UPDATE dll_base_info SET
        file_format = ?, machine_type = ?, compile_timestamp = ?,
        subsystem = ?, entry_point = ?, image_base = ?, characteristics = ?,
        file_version = ?, product_version = ?, company_name = ?, file_description = ?,
        signature_status = ?, signer_name = ?,
        md5 = ?, sha1 = ?, sha256 = ?, imp_hash = ?,
        threat_score = ?
    WHERE id = ?;
)";

// DLL节表操作
inline constexpr const char* INSERT_DLL_SECTION = R"(
    INSERT INTO dll_sections (
        dll_id, section_name, virtual_address, virtual_size,
        raw_data_size, characteristics, entropy,
        is_writeable, is_executable, is_readable
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_SECTIONS = R"(
    SELECT * FROM dll_sections WHERE dll_id = ?;
)";

// DLL导入/导出操作
inline constexpr const char* INSERT_DLL_IMPORT = R"(
    INSERT INTO dll_imports (dll_id, imported_dll_name, imported_function, import_ordinal, is_delayed)
    VALUES (?, ?, ?, ?, ?);
)";

inline constexpr const char* INSERT_DLL_EXPORT = R"(
    INSERT INTO dll_exports (dll_id, function_name, export_ordinal, export_rva)
    VALUES (?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_IMPORTS = R"(
    SELECT * FROM dll_imports WHERE dll_id = ?;
)";

inline constexpr const char* SELECT_DLL_EXPORTS = R"(
    SELECT * FROM dll_exports WHERE dll_id = ?;
)";

// DLL异常操作
inline constexpr const char* INSERT_DLL_ANOMALY = R"(
    INSERT INTO dll_anomalies (dll_id, anomaly_type, description, risk_level, risk_score, details)
    VALUES (?, ?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_ANOMALIES = R"(
    SELECT * FROM dll_anomalies WHERE dll_id = ?;
)";

// DLL依赖操作
inline constexpr const char* INSERT_DLL_DEPENDENCY = R"(
    INSERT INTO dll_dependencies (parent_dll_id, child_dll_id, depth, is_resolved)
    VALUES (?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_DEPENDENCIES = R"(
    SELECT * FROM dll_dependencies WHERE parent_dll_id = ?;
)";

// DLL取证关联
inline constexpr const char* INSERT_DLL_FORENSIC_LINK = R"(
    INSERT INTO dll_forensic_links (dll_id, link_type, source_id, source_data, detected_at)
    VALUES (?, ?, ?, ?, ?);
)";

inline constexpr const char* SELECT_DLL_FORENSIC_LINKS = R"(
    SELECT * FROM dll_forensic_links WHERE dll_id = ?;
)";
```

- [ ] **Step 3: 在windows_analysis_sql_llm.h中添加DLL LLM支持**

```cpp
// 添加到 windows_analysis_sql_llm.h 文件末尾

// DLL LLM分析
inline constexpr const char* UPDATE_DLL_LLM_ANALYSIS = R"(
    UPDATE dll_base_info SET
        llm_summary = ?,
        llm_description = ?,
        llm_keywords = ?,
        llm_analyzed_at = ?,
        llm_model_used = ?
    WHERE id = ?;
)";

inline constexpr const char* SELECT_DLL_PENDING_ANALYSIS = R"(
    SELECT id, path FROM dll_base_info
    WHERE llm_analyzed_at IS NULL AND threat_score >= ?
    ORDER BY threat_score DESC;
)";
```

- [ ] **Step 4: 更新CREATE_ALL_TABLES宏**

在 `windows_analysis_sql_tables.h` 中找到 `CREATE_ALL_TABLES` 的定义（约第10行），在现有SQL末尾添加DLL表：

```cpp
inline constexpr const char* CREATE_ALL_TABLES = R"(
    -- [现有表定义...]

    -- DLL Tables
    CREATE TABLE IF NOT EXISTS dll_base_info (
        -- [完整定义见上]
    );

    CREATE TABLE IF NOT EXISTS dll_sections ( ... );
    CREATE TABLE IF NOT EXISTS dll_imports ( ... );
    CREATE TABLE IF NOT EXISTS dll_exports ( ... );
    CREATE TABLE IF NOT EXISTS dll_anomalies ( ... );
    CREATE TABLE IF NOT EXISTS dll_dependencies ( ... );
    CREATE TABLE IF NOT EXISTS dll_forensic_links ( ... );

    -- DLL Indices
    CREATE INDEX IF NOT EXISTS idx_dll_base_inode ON dll_base_info(inode);
    -- [其他索引...]
)";
```

- [ ] **Step 5: 提交数据库Schema变更**

```bash
git add src/core/DatabaseManager/SQL/windows_analysis_sql_tables.h \
       src/core/DatabaseManager/SQL/windows_analysis_sql_crud.h \
       src/core/DatabaseManager/SQL/windows_analysis_sql_llm.h
git commit -m "feat: add DLL analysis database schema

- Add dll_base_info table for DLL metadata and analysis results
- Add dll_sections table for PE section information
- Add dll_imports table for imported DLLs and functions
- Add dll_exports table for exported functions
- Add dll_anomalies table for anomaly detection results
- Add dll_dependencies table for dependency tree
- Add dll_forensic_links table for forensic correlations
- Add comprehensive indices for query optimization
- Add CRUD SQL statements in windows_analysis_sql_crud.h
- Add LLM analysis support in windows_analysis_sql_llm.h

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: 创建DLLAnalysisDatabase类

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.h`
- Create: `src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.cpp`

- [ ] **Step 1: 编写DLLAnalysisDatabase.h接口**

```cpp
// DLLAnalysisDatabase.h
// 数据库操作接口

#pragma once
#ifndef DLL_ANALYSIS_DATABASE_H
#define DLL_ANALYSIS_DATABASE_H

#include <string>
#include <vector>
#include <optional>
#include <sqlite3.h>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class DLLAnalysisDatabase {
public:
    explicit DLLAnalysisDatabase(const std::string& dbPath);
    ~DLLAnalysisDatabase();

    // 禁止拷贝
    DLLAnalysisDatabase(const DLLAnalysisDatabase&) = delete;
    DLLAnalysisDatabase& operator=(const DLLAnalysisDatabase&) = delete;

    // 初始化数据库
    bool initialize();

    // ========================================================================
    // DLL基础信息操作
    // ========================================================================

    // 插入新的DLL记录，返回自增ID
    int64_t insertDLLBaseInfo(const DLLAnalysisResult& result);

    // 更新DLL分析结果
    bool updateDLLAnalysis(int64_t dllId, const DLLAnalysisResult& result);

    // 更新威胁评分
    bool updateThreatScore(int64_t dllId, int score);

    // ========================================================================
    // 节表操作
    // ========================================================================

    bool insertSections(int64_t dllId, const std::vector<PESectionInfo>& sections);
    std::vector<PESectionInfo> getSections(int64_t dllId);

    // ========================================================================
    // 导入/导出操作
    // ========================================================================

    bool insertImports(int64_t dllId, const std::vector<ImportedDLL>& imports);
    bool insertExports(int64_t dllId, const std::vector<ExportedFunction>& exports);

    std::vector<ImportedDLL> getImports(int64_t dllId);
    std::vector<ExportedFunction> getExports(int64_t dllId);

    // ========================================================================
    // 异常检测操作
    // ========================================================================

    bool insertAnomaly(int64_t dllId, const Anomaly& anomaly);
    std::vector<Anomaly> getAnomalies(int64_t dllId);

    // ========================================================================
    // 依赖关系操作
    // ========================================================================

    bool insertDependency(int64_t parentId, int64_t childId, int depth);
    std::vector<std::pair<int64_t, int64_t>> getDependencies(int64_t parentId);

    // ========================================================================
    // 取证关联操作
    // ========================================================================

    bool insertForensicLink(int64_t dllId, const std::string& linkType,
                           const std::string& sourceId, const std::string& sourceData);
    std::vector<std::tuple<std::string, std::string, std::string>>
    getForensicLinks(int64_t dllId);

    // ========================================================================
    // 查询操作
    // ========================================================================

    std::optional<DLLAnalysisResult> getDLLByInode(int64_t inode);
    std::optional<DLLAnalysisResult> getDLLByPath(const std::string& path);
    std::optional<DLLAnalysisResult> getDLLById(int64_t dllId);

    std::vector<DLLAnalysisResult> getDLLsByThreatScore(int minScore);
    std::vector<DLLAnalysisResult> getSuspiciousDLLs(int limit = 100);
    std::vector<DLLAnalysisResult> getAllDLLs(int limit = 1000);

    // ========================================================================
    // 统计操作
    // ========================================================================

    size_t getDLLCount();
    size_t getSuspiciousCount();
    int getAverageThreatScore();

private:
    bool executeSQL(const char* sql, ...);
    bool createTables();
    bool createIndices();

    // 辅助方法：从row读取DLLAnalysisResult
    DLLAnalysisResult readDLLFromRow(sqlite3_stmt* stmt);

    std::string dbPath_;
    sqlite3* db_;
};

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYSIS_DATABASE_H
```

- [ ] **Step 2: 编写DLLAnalysisDatabase.cpp实现**

```cpp
// DLLAnalysisDatabase.cpp
// 数据库操作实现

#include "DLLAnalysisDatabase.h"
#include "AuditLog/AuditLog.h"
#include <sstream>
#include <iomanip>

using namespace forensics::dll;

DLLAnalysisDatabase::DLLAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath), db_(nullptr) {
}

DLLAnalysisDatabase::~DLLAnalysisDatabase() {
    if (db_) {
        sqlite3_close(db_);
    }
}

bool DLLAnalysisDatabase::initialize() {
    AuditLog::instance().log("SYSTEM", "DLL_DB_INIT", "Initializing DLL analysis database: " + dbPath_);

    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open DLL database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    // 启用外键约束
    sqlite3_exec(db_, "PRAGMA foreign_keys = ON;", nullptr, nullptr, nullptr);

    if (!createTables() || !createIndices()) {
        return false;
    }

    AuditLog::instance().log("SYSTEM", "DLL_DB_INIT_COMPLETE", "DLL database initialized");
    return true;
}

bool DLLAnalysisDatabase::createTables() {
    // 执行windows_analysis_sql_tables.h中的CREATE_DLL_*_TABLE语句
    const char* createStatements[] = {
        CREATE_DLL_BASE_INFO_TABLE,
        CREATE_DLL_SECTIONS_TABLE,
        CREATE_DLL_IMPORTS_TABLE,
        CREATE_DLL_EXPORTS_TABLE,
        CREATE_DLL_ANOMALIES_TABLE,
        CREATE_DLL_DEPENDENCIES_TABLE,
        CREATE_DLL_FORENSIC_LINKS_TABLE
    };

    for (const char* sql : createStatements) {
        char* errMsg = nullptr;
        int rc = sqlite3_exec(db_, sql, nullptr, nullptr, &errMsg);
        if (rc != SQLITE_OK) {
            std::cerr << "Failed to create DLL table: " << errMsg << std::endl;
            sqlite3_free(errMsg);
            return false;
        }
    }
    return true;
}

bool DLLAnalysisDatabase::createIndices() {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, CREATE_DLL_INDICES, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create DLL indices: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

int64_t DLLAnalysisDatabase::insertDLLBaseInfo(const DLLAnalysisResult& result) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, INSERT_DLL_BASE_INFO, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert statement: " << sqlite3_errmsg(db_) << std::endl;
        return -1;
    }

    // 绑定参数
    sqlite3_bind_int64(stmt, 1, result.inode);
    sqlite3_bind_text(stmt, 2, result.fileName.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, result.filePath.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, static_cast<int64_t>(result.fileSize));
    sqlite3_bind_text(stmt, 5, result.md5Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 6, result.sha1Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 7, result.sha256Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 8, result.impHash.c_str(), -1, SQLITE_STATIC);

    // PE头信息
    sqlite3_bind_text(stmt, 9, result.peHeader.format.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 10, machineTypeToString(result.peHeader.machine).c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 11, static_cast<int>(result.peHeader.timestamp));
    sqlite3_bind_int(stmt, 12, static_cast<int>(result.peHeader.subsystem));
    sqlite3_bind_int(stmt, 13, static_cast<int>(result.peHeader.entryPointRVA));
    sqlite3_bind_int64(stmt, 14, static_cast<int64_t>(result.peHeader.imageBase));
    sqlite3_bind_int(stmt, 15, result.peHeader.isDLL ? 1 : 0);
    sqlite3_bind_int(stmt, 16, static_cast<int>(result.peHeader.characteristics));

    // 版本信息
    sqlite3_bind_text(stmt, 17, result.fileVersion.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 18, result.productVersion.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 19, result.companyName.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 20, result.fileDescription.c_str(), -1, SQLITE_STATIC);

    // 数字签名
    sqlite3_bind_text(stmt, 21, result.signatureStatus.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 22, result.signerName.c_str(), -1, SQLITE_STATIC);

    // 时间戳
    sqlite3_bind_int64(stmt, 27, static_cast<int64_t>(result.peHeader.timestamp)); // crtime

    // 威胁评分
    sqlite3_bind_int(stmt, 32, result.threatScore);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        std::cerr << "Failed to insert DLL base info: " << sqlite3_errmsg(db_) << std::endl;
        sqlite3_finalize(stmt);
        return -1;
    }

    int64_t rowId = sqlite3_last_insert_rowid(db_);
    sqlite3_finalize(stmt);
    return rowId;
}

// ... 其他方法实现（为节省篇幅省略，但必须实际实现）

std::string DLLAnalysisDatabase::machineTypeToString(MachineType type) {
    switch (type) {
        case MachineType::X86: return "x86";
        case MachineType::x64: return "x64";
        case MachineType::ARM: return "ARM";
        case MachineType::ARM64: return "ARM64";
        case MachineType::IA64: return "IA64";
        default: return "Unknown";
    }
}

bool DLLAnalysisDatabase::initialize() {
    // 实现已在上方
    return true;
}

// ... 其他方法的完整实现
```

- [ ] **Step 3: 提交DLLAnalysisDatabase**

```bash
git add src/analyzers/DLLAnalyzer/Database/
git commit -m "feat: add DLLAnalysisDatabase class

- Add DLLAnalysisDatabase.h with full interface
- Add DLLAnalysisDatabase.cpp with SQLite implementation
- Support CRUD operations for DLL metadata, sections, imports/exports
- Add anomaly, dependency, and forensic link storage
- Add query methods: by inode, path, threat score, MD5, ImpHash
- Add statistics: count, suspicious count, average threat score

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 阶段1：核心PE/ELF解析器（Week 1-2）

### Task 4: 实现PEHeaderParser

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h`
- Create: `src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.cpp`

- [ ] **Step 1: 编写PEHeaderParser.h**

```cpp
// PEHeaderParser.h
// PE文件头解析器

#pragma once
#ifndef PE_HEADER_PARSER_H
#define PE_HEADER_PARSER_H

#include <string>
#include <vector>
#include <fstream>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class PEHeaderParser {
public:
    explicit PEHeaderParser(const std::string& filePath);
    ~PEHeaderParser();

    // 禁止拷贝
    PEHeaderParser(const PEHeaderParser&) = delete;
    PEHeaderParser& operator=(const PEHeaderParser&) = delete;

    // 解析PE文件
    bool parse();

    // 获取解析结果
    const PEHeaderInfo& getHeaderInfo() const;
    bool isValid() const;
    std::string getErrorMessage() const;

    // 工具方法
    static std::string machineTypeToString(MachineType type);
    static std::string subsystemToString(SubsystemType type);
    static bool isDLL(uint16_t characteristics);

private:
    // 解析步骤
    bool parseDOSHeader();
    bool parsePEHeader();
    bool parseOptionalHeader();
    bool parseSectionTable();

    // 验证方法
    bool validateDOSHeader() const;
    bool validatePESignature() const;

    std::string filePath_;
    std::ifstream file_;
    PEHeaderInfo headerInfo_;
    bool isValid_;
    std::string errorMessage_;

    // 缓存
    uint32_t peHeaderOffset_;
    bool isPE32Plus_;
};

} // namespace dll
} // namespace forensics

#endif // PE_HEADER_PARSER_H
```

- [ ] **Step 2: 编写PEHeaderParser.cpp核心实现**

```cpp
// PEHeaderParser.cpp
// PE文件头解析器实现

#include "PEHeaderParser.h"
#include <iostream>
#include <stdexcept>
#include <cstring>

using namespace forensics::dll;

PEHeaderParser::PEHeaderParser(const std::string& filePath)
    : filePath_(filePath), file_(filePath, std::ios::binary),
      isValid_(false), peHeaderOffset_(0), isPE32Plus_(false) {
    if (!file_.is_open()) {
        errorMessage_ = "Cannot open file: " + filePath;
    }
}

PEHeaderParser::~PEHeaderParser() {
    if (file_.is_open()) {
        file_.close();
    }
}

bool PEHeaderParser::parse() {
    if (!file_.is_open()) {
        return false;
    }

    // 1. 解析DOS头
    if (!parseDOSHeader()) {
        errorMessage_ = "Failed to parse DOS header";
        return false;
    }

    // 2. 验证PE签名
    if (!validatePESignature()) {
        errorMessage_ = "Invalid PE signature";
        return false;
    }

    // 3. 解析COFF头
    if (!parsePEHeader()) {
        errorMessage_ = "Failed to parse COFF header";
        return false;
    }

    // 4. 解析可选头
    if (!parseOptionalHeader()) {
        errorMessage_ = "Failed to parse optional header";
        return false;
    }

    // 5. 解析节表
    if (!parseSectionTable()) {
        errorMessage_ = "Failed to parse section table";
        return false;
    }

    isValid_ = true;
    return true;
}

bool PEHeaderParser::parseDOSHeader() {
    file_.seekg(0);
    DOSHeader dosHeader;
    file_.read(reinterpret_cast<char*>(&dosHeader), sizeof(DOSHeader));

    if (!file_ || file_.gcount() != sizeof(DOSHeader)) {
        return false;
    }

    // 验证DOS签名 "MZ"
    if (!validateDOSHeader()) {
        return false;
    }

    peHeaderOffset_ = dosHeader.e_lfanew;
    return true;
}

bool PEHeaderParser::validateDOSHeader() const {
    file_.seekg(0);
    uint16_t magic;
    file_.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    return file_ && magic == DOS_MAGIC;
}

bool PEHeaderParser::validatePESignature() const {
    file_.seekg(peHeaderOffset_);
    uint32_t signature;
    file_.read(reinterpret_cast<char*>(&signature), sizeof(signature));
    return file_ && signature == PE_SIGNATURE;
}

bool PEHeaderParser::parsePEHeader() {
    file_.seekg(peHeaderOffset_ + 4); // 跳过"PE\0\0"

    COFFHeader coffHeader;
    file_.read(reinterpret_cast<char*>(&coffHeader), sizeof(COFFHeader));

    if (!file_) {
        return false;
    }

    headerInfo_.machine = static_cast<MachineType>(coffHeader.machine);
    headerInfo_.numberOfSections = coffHeader.numberOfSections;
    headerInfo_.timestamp = coffHeader.timestamp;
    headerInfo_.characteristics = coffHeader.characteristics;
    headerInfo_.isDLL = isDLL(coffHeader.characteristics);

    return true;
}

bool PEHeaderParser::parseOptionalHeader() {
    // 定位到可选头开始位置
    file_.seekg(peHeaderOffset_ + 4 + sizeof(COFFHeader));

    uint16_t magic;
    file_.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    if (!file_) {
        return false;
    }

    isPE32Plus_ = (magic == PE32PLUS_MAGIC);
    headerInfo_.format = isPE32Plus_ ? "PE32+" : "PE32";

    file_.seekg(peHeaderOffset_ + 4 + sizeof(COFFHeader));
    OptionalHeaderBase baseHeader;
    file_.read(reinterpret_cast<char*>(&baseHeader), sizeof(OptionalHeaderBase));

    if (!file_) {
        return false;
    }

    headerInfo_.entryPointRVA = baseHeader.addressOfEntryPoint;
    headerInfo_.imageBase = isPE32Plus_ ? 0 : baseHeader.baseOfCode; // 简化
    headerInfo_.sectionAlignment = baseHeader.sectionAlignment;
    headerInfo_.fileAlignment = baseHeader.fileAlignment;
    headerInfo_.subsystem = static_cast<SubsystemType>(baseHeader.subsystem);
    headerInfo_.checkSum = 0; // TODO: 在PE32/PE32+结构中解析

    // 继续读取数据目录（简化版）
    // TODO: 完整实现数据目录解析

    return true;
}

bool PEHeaderParser::parseSectionTable() {
    headerInfo_.sections.clear();
    headerInfo_.sections.reserve(headerInfo_.numberOfSections);

    // 节表紧跟在可选头之后
    uint32_t sectionOffset = peHeaderOffset_ + 4 + sizeof(COFFHeader)
                           + (isPE32Plus_ ? sizeof(OptionalHeaderPE32Plus) : sizeof(OptionalHeaderPE32));

    for (uint16_t i = 0; i < headerInfo_.numberOfSections; ++i) {
        file_.seekg(sectionOffset + i * sizeof(SectionHeader));

        SectionHeader section;
        file_.read(reinterpret_cast<char*>(&section), sizeof(SectionHeader));
        if (!file_) {
            return false;
        }

        PESectionInfo sectionInfo;
        sectionInfo.name = std::string(section.name, strnlen(section.name, 8));
        sectionInfo.virtualAddress = section.virtualAddress;
        sectionInfo.virtualSize = section.virtualSize;
        sectionInfo.rawDataSize = section.sizeOfRawData;
        sectionInfo.characteristics = section.characteristics;

        // 解析节属性
        sectionInfo.isReadable = (section.characteristics & SECTION_READ) != 0;
        sectionInfo.isWriteable = (section.characteristics & SECTION_WRITE) != 0;
        sectionInfo.isExecutable = (section.characteristics & SECTION_EXECUTE) != 0;

        // 计算熵值（需要读取节数据）
        // TODO: 实现熵值计算

        headerInfo_.sections.push_back(sectionInfo);
    }

    return true;
}

const PEHeaderInfo& PEHeaderParser::getHeaderInfo() const {
    return headerInfo_;
}

bool PEHeaderParser::isValid() const {
    return isValid_;
}

std::string PEHeaderParser::getErrorMessage() const {
    return errorMessage_;
}

// ============================================================================
// 工具方法
// ============================================================================

std::string PEHeaderParser::machineTypeToString(MachineType type) {
    switch (type) {
        case MachineType::X86: return "x86";
        case MachineType::x64: return "x64";
        case MachineType::ARM: return "ARM";
        case MachineType::ARM64: return "ARM64";
        case MachineType::IA64: return "IA64";
        default: return "Unknown";
    }
}

std::string PEHeaderParser::subsystemToString(SubsystemType type) {
    switch (type) {
        case SubsystemType::NATIVE: return "Native";
        case SubsystemType::WINDOWS_GUI: return "Windows GUI";
        case SubsystemType::WINDOWS_CUI: return "Windows Console";
        case SubsystemType::EFI_APPLICATION: return "EFI Application";
        case SubsystemType::EFI_BOOT_SERVICE: return "EFI Boot Service";
        case SubsystemType::EFI_RUNTIME: return "EFI Runtime";
        default: return "Unknown";
    }
}

bool PEHeaderParser::isDLL(uint16_t characteristics) {
    return (characteristics & 0x2000) != 0; // IMAGE_FILE_DLL
}
```

- [ ] **Step 3: 为PEHeaderParser编写单元测试**

```cpp
// 添加到 tests/UnitTest/test_dll_analyzer_gtest.cpp

#include "analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h"

TEST(PEHeaderParserTest, ParseValidPE32) {
    // 创建测试用的PE文件（最小化）
    std::string testFile = "/tmp/test_pe32.dll";
    std::ofstream out(testFile, std::ios::binary);

    // DOS头
    IMAGE_DOS_HEADER dosHeader = {};
    dosHeader.e_magic = 0x5A4D; // "MZ"
    dosHeader.e_lfanew = 0x80;   // PE头偏移
    out.write(reinterpret_cast<const char*>(&dosHeader), sizeof(dosHeader));

    // 填充到PE头位置
    out.seekp(0x80);

    // PE签名
    uint32_t peSig = 0x00004550;
    out.write(reinterpret_cast<const char*>(&peSig), sizeof(peSig));

    // COFF头
    IMAGE_FILE_HEADER coffHeader = {};
    coffHeader.Machine = 0x8664; // x64
    coffHeader.NumberOfSections = 1;
    coffHeader.Characteristics = 0x2002; // DLL + Executable
    out.write(reinterpret_cast<const char*>(&coffHeader), sizeof(coffHeader));

    // PE32+可选头
    IMAGE_OPTIONAL_HEADER64 optHeader = {};
    optHeader.Magic = 0x20B; // PE32+
    optHeader.Subsystem = 3; // Windows CUI
    out.write(reinterpret_cast<const char*>(&optHeader), sizeof(optHeader));

    // 节表
    IMAGE_SECTION_HEADER section = {};
    strncpy(reinterpret_cast<char*>(section.Name), ".text", 8);
    section.SizeOfRawData = 0x1000;
    out.write(reinterpret_cast<const char*>(&section), sizeof(section));

    out.close();

    // 测试解析
    PEHeaderParser parser(testFile);
    EXPECT_TRUE(parser.parse());
    EXPECT_TRUE(parser.isValid());

    const auto& header = parser.getHeaderInfo();
    EXPECT_EQ("PE32+", header.format);
    EXPECT_EQ(MachineType::x64, header.machine);
    EXPECT_TRUE(header.isDLL);

    // 清理
    std::remove(testFile.c_str());
}

TEST(PEHeaderParserTest, RejectInvalidSignature) {
    std::string testFile = "/tmp/test_invalid.bin";
    std::ofstream out(testFile, std::ios::binary);
    out.write("NOT_A_PE_FILE", 12);
    out.close();

    PEHeaderParser parser(testFile);
    EXPECT_FALSE(parser.parse());
    EXPECT_FALSE(parser.isValid());

    std::remove(testFile.c_str());
}
```

- [ ] **Step 4: 提交PEHeaderParser**

```bash
git add src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.* \
       tests/UnitTest/test_dll_analyzer_gtest.cpp
git commit -m "feat: add PEHeaderParser for PE file header parsing

- Add PEHeaderParser.h with complete interface
- Add PEHeaderParser.cpp with DOS/COFF/Optional header parsing
- Support PE32 and PE32+ formats
- Parse machine type, timestamp, subsystem, entry point
- Parse section table with RWX characteristics
- Add machineTypeToString and subsystemToString utilities
- Add unit tests for PE32/PE32+ parsing and invalid file rejection

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: 实现PESectionParser（节熵值计算）

**Files:**
- Modify: `src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h`
- Modify: `src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.cpp`
- Create: `src/analyzers/DLLAnalyzer/Parsers/PESectionParser.h` (optional, can merge into PEHeaderParser)

**TDD模式：先写测试，再实现**

- [ ] **Step 1: 编写熵值计算测试**

```cpp
// 添加到 test_dll_analyzer_gtest.cpp

// 熵值计算测试
TEST(EntropyCalculatorTest, ZeroEntropy) {
    // 全是0的数据：熵应为0
    std::vector<uint8_t> data(256, 0);
    double entropy = calculateEntropy(data);
    EXPECT_NEAR(entropy, 0.0, 0.01);
}

TEST(EntropyCalculatorTest, MaxEntropy) {
    // 完全随机数据：熵应接近8.0
    std::vector<uint8_t> data(256);
    std::random_device rd;
    std::generate(data.begin(), data.end(), [&rd]() { return rd(); });
    double entropy = calculateEntropy(data);
    EXPECT_NEAR(entropy, 8.0, 0.1);
}

TEST(EntropyCalculatorTest, CompressibleData) {
    // 高度压缩的数据（如重复序列）
    std::vector<uint8_t> data;
    for (int i = 0; i < 256; ++i) {
        data.push_back(i % 10); // 只有10种不同值
    }
    double entropy = calculateEntropy(data);
    EXPECT_LT(entropy, 3.0); // 低熵
}

TEST(EntropyCalculatorTest, EncryptedData) {
    // 加密数据模拟（伪随机）
    std::vector<uint8_t> data(4096);
    for (size_t i = 0; i < data.size(); ++i) {
        data[i] = static_cast<uint8_t>(i ^ 0xAA);
    }
    double entropy = calculateEntropy(data);
    EXPECT_GT(entropy, 7.5); // 高熵，可能是加密/加壳
}
```

- [ ] **Step 2: 在PEHeaderParser中实现calculateEntropy**

```cpp
// 添加到 PEHeaderParser.cpp

double PEHeaderParser::calculateEntropy(const std::vector<uint8_t>& data) {
    if (data.empty()) {
        return 0.0;
    }

    // 统计字节频率
    std::array<int, 256> freq = {0};
    for (uint8_t byte : data) {
        freq[byte]++;
    }

    // 计算Shannon熵: H = -Σ p(x) * log2(p(x))
    double entropy = 0.0;
    size_t total = data.size();

    for (int count : freq) {
        if (count > 0) {
            double probability = static_cast<double>(count) / total;
            entropy -= probability * std::log2(probability);
        }
    }

    return entropy;
}
```

- [ ] **Step 3: 实现节数据读取和熵计算**

```cpp
// 在PEHeaderParser.h中添加
class PEHeaderParser {
    // ...
    std::vector<uint8_t> readSectionData(const PESectionInfo& section);
    double calculateEntropy(const std::vector<uint8_t>& data);
};

// 在PEHeaderParser.cpp中实现
std::vector<uint8_t> PEHeaderParser::readSectionData(const PESectionInfo& section) {
    if (!file_.is_open() || section.rawDataSize == 0) {
        return {};
    }

    file_.seekg(section.pointerToRawData);
    std::vector<uint8_t> data(section.rawDataSize);
    file_.read(reinterpret_cast<char*>(data.data()), section.rawDataSize);

    if (!file_) {
        return {};
    }

    return data;
}

// 修改parseSectionTable以计算熵值
bool PEHeaderParser::parseSectionTable() {
    headerInfo_.sections.clear();
    headerInfo_.sections.reserve(headerInfo_.numberOfSections);

    // ... 现有代码 ...

    for (uint16_t i = 0; i < headerInfo_.numberOfSections; ++i) {
        // ... 读取节头 ...

        // 计算熵值（读取节数据）
        if (sectionInfo.rawDataSize > 0 && sectionInfo.rawDataSize < 100 * 1024 * 1024) {
            // 跳过>100MB的节以避免内存问题
            std::vector<uint8_t> sectionData = readSectionData(sectionInfo);
            if (!sectionData.empty()) {
                sectionInfo.entropy = calculateEntropy(sectionData);
            }
        }

        headerInfo_.sections.push_back(sectionInfo);
    }

    return true;
}
```

- [ ] **Step 4: 运行熵值测试**

```bash
cd build && ctest -R EntropyCalculatorTest -V
```

- [ ] **Step 5: 提交PESectionParser**

```bash
git add src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.*
git commit -m "feat: add section entropy calculation to PEHeaderParser

- Add calculateEntropy() using Shannon entropy formula
- Add readSectionData() to read section content
- Calculate entropy during section table parsing
- Skip sections >100MB to avoid memory issues
- Add unit tests for entropy calculation

Entropy thresholds:
- 0.0-6.0: Normal/Compressed
- 6.0-7.0: Compressed/Packed
- 7.0-8.0: Encrypted/Packed (highly suspicious)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: 实现PEImportExportParser

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Parsers/PEImportExportParser.h`
- Create: `src/analyzers/DLLAnalyzer/Parsers/PEImportExportParser.cpp`

- [ ] **Step 1: 编写PEImportExportParser.h**

```cpp
// PEImportExportParser.h
// PE导入/导出表解析器

#pragma once
#ifndef PE_IMPORT_EXPORT_PARSER_H
#define PE_IMPORT_EXPORT_PARSER_H

#include <string>
#include <vector>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class PEImportExportParser {
public:
    explicit PEImportExportParser(const std::string& filePath);
    ~PEImportExportParser();

    // 禁止拷贝
    PEImportExportParser(const PEImportExportParser&) = delete;
    PEImportExportParser& operator=(const PEImportExportParser&) = delete;

    // 解析导入表
    bool parseImports(std::vector<ImportedDLL>& imports);

    // 解析导出表
    bool parseExports(std::vector<ExportedFunction>& exports);

    // 计算ImpHash (Import Hash)
    std::string calculateImpHash();

    bool isValid() const;
    std::string getErrorMessage() const;

private:
    struct ImportDescriptor {
        uint32_t originalFirstThunk;
        uint32_t timeDateStamp;
        uint32_t forwarderChain;
        uint32_t name;
        uint32_t firstThunk;
    };

    struct ExportDirectory {
        uint32_t characteristics;
        uint32_t timeDateStamp;
        uint16_t majorVersion;
        uint16_t minorVersion;
        uint32_t name;
        uint32_t base;
        uint32_t numberOfFunctions;
        uint32_t numberOfNames;
        uint32_t addressOfFunctions;
        uint32_t addressOfNames;
        uint32_t addressOfNameOrdinals;
    };

    bool readExportDirectory(ExportDirectory& exportDir);
    bool readImportDescriptors(std::vector<ImportDescriptor>& descriptors);
    bool readStringAt(uint32_t rva, std::string& out);

    std::string filePath_;
    bool isValid_;
    std::string errorMessage_;

    // 缓存（简化：实际应该读取PEHeaderParser的结果）
    uint32_t imageBase_;
    uint32_t fileAlignment_;
};

} // namespace dll
} // namespace forensics

#endif // PE_IMPORT_EXPORT_PARSER_H
```

- [ ] **Step 2: 实现PEImportExportParser.cpp（简化版）**

```cpp
// PEImportExportParser.cpp

#include "PEImportExportParser.h"
#include <fstream>
#include <windows.h> // 仅在Windows上可用，需要条件编译

using namespace forensics::dll;

PEImportExportParser::PEImportExportParser(const std::string& filePath)
    : filePath_(filePath), isValid_(false), imageBase_(0), fileAlignment_(0) {
}

bool PEImportExportParser::parseImports(std::vector<ImportedDLL>& imports) {
    // TODO: 完整实现
    // 1. 定位IMAGE_DIRECTORY_ENTRY_IMPORT
    // 2. 遍历IMAGE_IMPORT_DESCRIPTOR数组
    // 3. 读取每个DLL的名称
    // 4. 读取IAT（Import Address Table）或INT（Import Name Table）
    // 5. 提取导入的函数名/序数

    // 占位实现
    return true;
}

bool PEImportExportParser::parseExports(std::vector<ExportedFunction>& exports) {
    // TODO: 完整实现
    // 1. 定位IMAGE_DIRECTORY_ENTRY_EXPORT
    // 2. 读取IMAGE_EXPORT_DIRECTORY
    // 3. 遍历导出地址表（EAT）
    // 4. 读取导出名称表（ENT）
    // 5. 构建函数名->序数映射

    return true;
}

// ... 其他方法实现
```

- [ ] **Step 3: 提交PEImportExportParser框架**

```bash
git add src/analyzers/DLLAnalyzer/Parsers/PEImportExportParser.*
git commit -m "feat: add PEImportExportParser for import/export parsing

- Add PEImportExportParser.h with interface
- Add PEImportExportParser.cpp with placeholder implementation
- Design ImportedDLL and ExportedFunction structures
- Define calculateImpHash() interface for import hash
- TODO: Complete implementation in next task

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 阶段2：分析引擎（Week 3）

### Task 7: 实现PEAnalyzer（元数据提取）

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Core/PEAnalyzer.h`
- Create: `src/analyzers/DLLAnalyzer/Core/PEAnalyzer.cpp`

- [ ] **Step 1: 编写PEAnalyzer.h**

```cpp
// PEAnalyzer.h
// PE文件分析引擎

#pragma once
#ifndef PE_ANALYZER_H
#define PE_ANALYZER_H

#include <string>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class PEAnalyzer {
public:
    PEAnalyzer();
    ~PEAnalyzer();

    // 禁止拷贝
    PEAnalyzer(const PEAnalyzer&) = delete;
    PEAnalyzer& operator=(const PEAnalyzer&) = delete;

    // 分析PE文件，返回完整结果
    DLLAnalysisResult analyze(const std::string& filePath);

    // 仅计算哈希
    static std::string calculateMD5(const std::string& filePath);
    static std::string calculateSHA1(const std::string& filePath);
    static std::string calculateSHA256(const std::string& filePath);

private:
    // 子分析步骤
    PEHeaderInfo parsePEHeader(const std::string& filePath);
    std::vector<PESectionInfo> parseSections(const std::string& filePath);
    std::vector<ImportedDLL> parseImports(const std::string& filePath);
    std::vector<ExportedFunction> parseExports(const std::string& filePath);
    std::string extractVersionInfo(const std::string& filePath);
    std::string verifySignature(const std::string& filePath);
    std::string calculateImpHash(const std::string& filePath);
    void extractTimestamps(const PEHeaderInfo& header, DLLAnalysisResult& result);
};

} // namespace dll
} // namespace forensics

#endif // PE_ANALYZER_H
```

- [ ] **Step 2: 实现PEAnalyzer.cpp**

```cpp
// PEAnalyzer.cpp
// PE文件分析引擎实现

#include "PEAnalyzer.h"
#include "Parsers/PEHeaderParser.h"
#include <openssl/md5.h>
#include <openssl/sha.h>
#include <iomanip>

using namespace forensics::dll;

PEAnalyzer::PEAnalyzer() = default;

PEAnalyzer::~PEAnalyzer() = default;

DLLAnalysisResult PEAnalyzer::analyze(const std::string& filePath) {
    DLLAnalysisResult result;
    result.filePath = filePath;
    result.fileName = std::filesystem::path(filePath).filename().string();

    // 1. 计算哈希
    result.md5Hash = calculateMD5(filePath);
    result.sha1Hash = calculateSHA1(filePath);
    result.sha256Hash = calculateSHA256(filePath);

    // 2. 解析PE头
    result.peHeader = parsePEHeader(filePath);
    if (!result.peHeader.isValid) {
        return result; // 返回空结果
    }

    // 3. 提取时间戳
    extractTimestamps(result.peHeader, result);

    // 4. 解析节表（已包含熵值）
    result.peHeader.sections = parseSections(filePath);

    // 5. 解析导入/导出
    result.imports = parseImports(filePath);
    result.exports = parseExports(filePath);

    // 6. 计算ImpHash
    result.impHash = calculateImpHash(filePath);

    // 7. 提取版本信息
    result.fileVersion = extractVersionInfo(filePath);

    // 8. 验证数字签名
    result.signatureStatus = verifySignature(filePath);

    // 9. 初始化威胁评分
    result.threatScore = 0;

    return result;
}

// ... 子方法实现（parsePEHeader, parseSections等）
// 这些方法需要实际的文件读取逻辑，这里省略但必须实现

std::string PEAnalyzer::calculateMD5(const std::string& filePath) {
    // 使用OpenSSL计算MD5
    // 实现...
    return "";
}

std::string PEAnalyzer::calculateSHA1(const std::string& filePath) {
    // 使用OpenSSL计算SHA1
    return "";
}

std::string PEAnalyzer::calculateSHA256(const std::string& filePath) {
    // 使用OpenSSL计算SHA256
    return "";
}
```

- [ ] **Step 3: 为PEAnalyzer编写测试**

```cpp
// 添加到 test_dll_analyzer_gtest.cpp

TEST(PEAnalyzerTest, AnalyzeTestDLL) {
    PEAnalyzer analyzer;
    std::string testFile = createMinimalTestPE(); // 辅助函数，创建最小PE文件

    DLLAnalysisResult result = analyzer.analyze(testFile);

    EXPECT_TRUE(result.fileName.find("test.dll") != std::string::npos);
    EXPECT_TRUE(result.md5Hash.length() == 32); // MD5 hex
    EXPECT_TRUE(result.sha256Hash.length() == 64); // SHA256 hex
    EXPECT_FALSE(result.impHash.empty());
    EXPECT_GE(result.threatScore, 0);
    EXPECT_LE(result.threatScore, 100);
}
```

- [ ] **Step 4: 提交PEAnalyzer**

```bash
git add src/analyzers/DLLAnalyzer/Core/PEAnalyzer.*
git commit -m "feat: add PEAnalyzer for PE file analysis

- Add PEAnalyzer.h with analysis interface
- Add PEAnalyzer.cpp with orchestration logic
- Calculate MD5/SHA1/SHA256 hashes using OpenSSL
- Parse PE headers, sections, imports, exports
- Extract version info and verify signatures
- Calculate ImpHash for malware clustering
- Add unit test for end-to-end analysis

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 阶段3：异常检测（Week 4）

### Task 8: 实现AnomalyDetector

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Core/AnomalyDetector.h`
- Create: `src/analyzers/DLLAnalyzer/Core/AnomalyDetector.cpp`

- [ ] **Step 1: 编写AnomalyDetector.h**

```cpp
// AnomalyDetector.h
// DLL异常检测器

#pragma once
#ifndef ANOMALY_DETECTOR_H
#define ANOMALY_DETECTOR_H

#include <vector>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class AnomalyDetector {
public:
    AnomalyDetector();
    ~AnomalyDetector();

    // 检测所有异常
    std::vector<Anomaly> detect(const DLLAnalysisResult& result);

    // 单独检测方法（用于单元测试）
    Anomaly checkHighEntropySections(const std::vector<PESectionInfo>& sections);
    Anomaly checkSuspiciousImports(const std::vector<ImportedDLL>& imports);
    Anomaly checkWriteExecuteInText(const std::vector<PESectionInfo>& sections);
    Anomaly checkUnusualSectionNames(const std::vector<PESectionInfo>& sections);
    Anomaly checkEntryPointAnomaly(const PEHeaderInfo& header);

private:
    // 已知系统DLL白名单
    static const std::unordered_set<std::string> SYSTEM_DLLS;
    static const std::unordered_set<std::string> PACKER_SIGNATURES;

    // 可疑函数库
    static const std::unordered_set<std::string> INJECTION_FUNCTIONS;
    static const std::unordered_set<std::string> PRIVILEGE_ESCALATION_FUNCTIONS;
    static const std::unordered_set<std::string> ANTI_DEBUG_FUNCTIONS;
    static const std::unordered_set<std::string> PERSISTENCE_FUNCTIONS;
};

} // namespace dll
} // namespace forensics

#endif // ANOMALY_DETECTOR_H
```

- [ ] **Step 2: 实现AnomalyDetector.cpp**

```cpp
// AnomalyDetector.cpp
// 异常检测实现

#include "AnomalyDetector.h"
#include <algorithm>

using namespace forensics::dll;

// 静态成员初始化
const std::unordered_set<std::string> AnomalyDetector::SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll",
    "ntdll.dll", "kernelbase.dll", "ws2_32.dll", "wininet.dll",
    "ole32.dll", "oleaut32.dll", "shell32.dll", "shlwapi.dll"
};

const std::unordered_set<std::string> AnomalyDetector::INJECTION_FUNCTIONS = {
    "CreateRemoteThread", "WriteProcessMemory", "VirtualAllocEx",
    "SetWindowsHookEx", "CallNextHookEx", "GetAsyncKeyState",
    "OpenProcess", "ReadProcessMemory"
};

const std::unordered_set<std::string> PRIVILEGE_ESCALATION_FUNCTIONS = {
    "AdjustTokenPrivileges", "SeDebugPrivilege", "LookupPrivilegeValue",
    "ImpersonateLoggedOnUser", "ImpersonateSelf"
};

const std::unordered_set<std::string> ANTI_DEBUG_FUNCTIONS = {
    "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
    "NtQueryInformationProcess", "OutputDebugString",
    "ZwSetInformationThread", "DebugActiveProcess"
};

const std::unordered_set<std::string> PERSISTENCE_FUNCTIONS = {
    "RegCreateKeyEx", "RegSetValueEx", "CreateService",
    "StartService", "WinHttpOpen", "URLDownloadToFile"
};

const std::unordered_set<std::string> AnomalyDetector::PACKER_SIGNATURES = {
    "UPX0", "UPX1", "UPX!", "ASPack", "PECompact",
    ".themida", "VMProtect", ".vmp0", ".vmp1"
};

std::vector<Anomaly> AnomalyDetector::detect(const DLLAnalysisResult& result) {
    std::vector<Anomaly> anomalies;
    int totalScore = 0;

    // 1. 检查高熵节
    Anomaly entropyAnomaly = checkHighEntropySections(result.peHeader.sections);
    if (entropyAnomaly.riskScore > 0) {
        anomalies.push_back(entropyAnomaly);
        totalScore += entropyAnomaly.riskScore;
    }

    // 2. 检查可疑导入
    Anomaly importAnomaly = checkSuspiciousImports(result.imports);
    if (importAnomaly.riskScore > 0) {
        anomalies.push_back(importAnomaly);
        totalScore += importAnomaly.riskScore;
    }

    // 3. 检查RWX权限
    Anomaly rwxAnomaly = checkWriteExecuteInText(result.peHeader.sections);
    if (rwxAnomaly.riskScore > 0) {
        anomalies.push_back(rwxAnomaly);
        totalScore += rwxAnomaly.riskScore;
    }

    // 4. 检查异常节名
    Anomaly sectionAnomaly = checkUnusualSectionNames(result.peHeader.sections);
    if (sectionAnomaly.riskScore > 0) {
        anomalies.push_back(sectionAnomaly);
        totalScore += sectionAnomaly.riskScore;
    }

    // 5. 检查入口点异常
    Anomaly entryAnomaly = checkEntryPointAnomaly(result.peHeader);
    if (entryAnomaly.riskScore > 0) {
        anomalies.push_back(entryAnomaly);
        totalScore += entryAnomaly.riskScore;
    }

    // 更新威胁评分
    // result.threatScore = std::min(totalScore, 100);

    return anomalies;
}

Anomaly AnomalyDetector::checkHighEntropySections(const std::vector<PESectionInfo>& sections) {
    for (const auto& section : sections) {
        // .text节高熵（>7.5）可能是加密/加壳
        if (section.name == ".text" && section.entropy > 7.5) {
            return Anomaly{
                "HIGH_ENTROPY_CODE",
                "Code section .text has high entropy: " + std::to_string(section.entropy),
                RiskLevel::HIGH,
                15
            };
        }
    }
    return {"NONE", "", RiskLevel::LOW, 0};
}

Anomaly AnomalyDetector::checkSuspiciousImports(const std::vector<ImportedDLL>& imports) {
    std::vector<std::string> suspiciousFuncs;

    for (const auto& importedDLL : imports) {
        for (const auto& func : importedDLL.functions) {
            if (INJECTION_FUNCTIONS.count(func) ||
                PRIVILEGE_ESCALATION_FUNCTIONS.count(func) ||
                ANTI_DEBUG_FUNCTIONS.count(func) ||
                PERSISTENCE_FUNCTIONS.count(func)) {
                suspiciousFuncs.push_back(func);
            }
        }
    }

    if (suspiciousFuncs.size() >= 3) {
        return Anomaly{
            "SUSPICIOUS_IMPORTS",
            "Found " + std::to_string(suspiciousFuncs.size()) + " suspicious functions",
            RiskLevel::HIGH,
            20
        };
    }

    return {"NONE", "", RiskLevel::LOW, 0};
}

// ... 其他检测方法实现
```

- [ ] **Step 3: 提交AnomalyDetector**

```bash
git add src/analyzers/DLLAnalyzer/Core/AnomalyDetector.*
git commit -m "feat: add AnomalyDetector for DLL anomaly detection

- Add AnomalyDetector.h with detection interface
- Add AnomalyDetector.cpp with rule-based detection
- Implement detection rules:
  - HIGH_ENTROPY_CODE: .text section entropy > 7.5
  - SUSPICIOUS_IMPORTS: 3+ injection/privilege escalation functions
  - RWX_CODE: .text section with write+execute permissions
  - UNUSUAL_SECTION_NAMES: Non-standard section names
  - ENTRY_POINT_ANOMALY: Entry point in non-standard section
- Add suspicious function libraries:
  - INJECTION_FUNCTIONS (CreateRemoteThread, etc.)
  - PRIVILEGE_ESCALATION_FUNCTIONS (AdjustTokenPrivileges, etc.)
  - ANTI_DEBUG_FUNCTIONS (IsDebuggerPresent, etc.)
  - PERSISTENCE_FUNCTIONS (RegCreateKeyEx, etc.)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 阶段4：依赖分析和集成（Week 5）

### Task 9: 实现DependencyAnalyzer

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Core/DependencyAnalyzer.h`
- Create: `src/analyzers/DLLAnalyzer/Core/DependencyAnalyzer.cpp`

(TDD方式实现)

---

### Task 10: 实现DLLAnalyzer主类

**Files:**
- Create: `src/analyzers/DLLAnalyzer/Core/DLLAnalyzer.h`
- Create: `src/analyzers/DLLAnalyzer/Core/DLLAnalyzerCore.cpp`

---

### Task 11: 集成到WindowsFilesAnalyzer和main.cpp

**Files:**
- Modify: `src/analyzers/WindowsFilesAnalyzer/WindowsFilesAnalyzerCore.cpp:90-95`
- Modify: `src/main.cpp`

---

### Task 12: 添加REST API端点

**Files:**
- Modify: `src/network/HTTPServer/routes/ForensicsRoutes.cpp`

---

## 后续优化（Week 6-8）

### Task 13-18

- Task 13: 性能优化（白名单、并行分析、增量分析）
- Task 14: ELF文件解析支持
- Task 15: 完善数字签名验证
- Task 16: 集成LLM分析（可选）
- Task 17: 完整文档
- Task 18: 集成测试和真实样本验证

---

## 里程碑检查点

### 检查点1（Week 2结束时）
- [ ] PEHeaderParser 可解析PE32/PE32+
- [ ] 数据库Schema已创建
- [ ] 单元测试通过

### 检查点2（Week 4结束时）
- [ ] PEAnalyzer 可提取元数据
- [ ] AnomalyDetector 可检测基本异常
- [ ] 威胁评分算法可用

### 检查点3（Week 6结束时）
- [ ] DLLAnalyzer 集成到主pipeline
- [ ] REST API端点可用
- [ ] 真实DLL样本测试通过

---

## 常见问题

### Q: PE解析依赖Windows API吗？
**A:** 不，所有PE结构解析手动实现（只读二进制），不依赖Windows API。数字签名验证可使用 `osslsigncode` 或仅在Windows上调用WinVerifyTrust。

### Q: 如何处理大型DLL文件？
**A:**
1. 流式读取，只加载需要的节
2. 跳过>100MB的节熵计算
3. 白名单已知系统DLL

### Q: ImpHash计算是否支持Delayed Imports？
**A:** 当前版本不支持。未来可扩展。

### Q: 如何降低误报率？
**A:**
1. 结合文件路径信息（System32目录的DLL可信度更高）
2. 数字签名验证（已签名的DLL可信度更高）
3. 威胁评分阈值可调（默认30分为可疑）

---

**计划版本：** 1.0
**最后更新：** 2026-05-14
**维护者：** Claude Opus 4.7
