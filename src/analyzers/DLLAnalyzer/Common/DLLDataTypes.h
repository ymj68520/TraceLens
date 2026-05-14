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
