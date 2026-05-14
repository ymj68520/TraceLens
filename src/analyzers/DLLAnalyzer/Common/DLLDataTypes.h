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
    uint32_t pointerToRawData;
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

// ============================================================================
// ELF文件格式常量
// ============================================================================

// ELF标识
inline constexpr uint8_t EI_MAG0 = 0x7F;
inline constexpr uint8_t EI_MAG1 = 'E';
inline constexpr uint8_t EI_MAG2 = 'L';
inline constexpr uint8_t EI_MAG3 = 'F';

// ELF类型
inline constexpr uint16_t ET_NONE = 0x0000;      // 无文件类型
inline constexpr uint16_t ET_REL = 0x0001;        // 可重定位文件
inline constexpr uint16_t ET_EXEC = 0x0002;       // 可执行文件
inline constexpr uint16_t ET_DYN = 0x0003;        // 共享目标文件（.so）
inline constexpr uint16_t ET_CORE = 0x0004;       // Core文件

// ELF机器类型
inline constexpr uint16_t EM_NONE = 0x0000;       // 无机器类型
inline constexpr uint16_t EM_M32 = 0x0001;        // AT&T WE 32100
inline constexpr uint16_t EM_SPARC = 0x0002;      // SPARC
inline constexpr uint16_t EM_386 = 0x0003;        // x86
inline constexpr uint16_t EM_68K = 0x0004;        // Motorola 68000
inline constexpr uint16_t EM_88K = 0x0005;        // Motorola 88000
inline constexpr uint16_t EM_486 = 0x0006;        // Intel 80486
inline constexpr uint16_t EM_860 = 0x0007;        // Intel 80860
inline constexpr uint16_t EM_MIPS = 0x0008;       // MIPS R3000
inline constexpr uint16_t EM_PARISC = 0x000F;     // HP PA-RISC
inline constexpr uint16_t EM_SPARC32PLUS = 0x0012;// SPARC V8+
inline constexpr uint16_t EM_PPC = 0x0014;        // PowerPC
inline constexpr uint16_t EM_PPC64 = 0x0015;      // PowerPC 64-bit
inline constexpr uint16_t EM_ARM = 0x0028;        // ARM
inline constexpr uint16_t EM_X86_64 = 0x003E;     // x86-64
inline constexpr uint16_t EM_AARCH64 = 0x00B7;    // ARM64
inline constexpr uint16_t EM_RISCV = 0x00F3;      // RISC-V

// ELF版本
inline constexpr uint32_t EV_NONE = 0x00000000;   // 无效版本
inline constexpr uint32_t EV_CURRENT = 0x00000001;// 当前版本

// ELF类
inline constexpr uint8_t ELFCLASSNONE = 0;        // 无效类
inline constexpr uint8_t ELFCLASS32 = 1;          // 32位
inline constexpr uint8_t ELFCLASS64 = 2;          // 64位

// 程序头类型
inline constexpr uint32_t PT_NULL = 0x00000000;   // 空段
inline constexpr uint32_t PT_LOAD = 0x00000001;   // 可加载段
inline constexpr uint32_t PT_DYNAMIC = 0x00000002;// 动态链接信息
inline constexpr uint32_t PT_INTERP = 0x00000003; // 解释器路径
inline constexpr uint32_t PT_NOTE = 0x00000004;   // 辅助信息
inline constexpr uint32_t PT_SHLIB = 0x00000005;  // 保留
inline constexpr uint32_t PT_PHDR = 0x00000006;   // 程序头表
inline constexpr uint32_t PT_TLS = 0x00000007;    // 线程局部存储
inline constexpr uint32_t PT_GNU_EH_FRAME = 0x6474E550;
inline constexpr uint32_t PT_GNU_STACK = 0x6474E551;
inline constexpr uint32_t PT_GNU_RELRO = 0x6474E552;

// 节头类型
inline constexpr uint32_t SHT_NULL = 0x00000000;  // 空节
inline constexpr uint32_t SHT_PROGBITS = 0x00000001; // 程序信息
inline constexpr uint32_t SHT_SYMTAB = 0x00000002;// 符号表
inline constexpr uint32_t SHT_STRTAB = 0x00000003;// 字符串表
inline constexpr uint32_t SHT_RELA = 0x00000004;  // 重定位（带显式加数）
inline constexpr uint32_t SHT_HASH = 0x00000005;  // 符号哈希表
inline constexpr uint32_t SHT_DYNAMIC = 0x00000006;// 动态链接信息
inline constexpr uint32_t SHT_NOTE = 0x00000007;  // 注释信息
inline constexpr uint32_t SHT_NOBITS = 0x00000008;// 不占用空间（如.bss）
inline constexpr uint32_t SHT_REL = 0x00000009;   // 重定位项
inline constexpr uint32_t SHT_SHLIB = 0x0000000A; // 保留
inline constexpr uint32_t SHT_DYNSYM = 0x0000000B;// 动态符号表
inline constexpr uint32_t SHT_GNU_HASH = 0x6FFFFFF6;// GNU符号哈希表

// 动态表标签
inline constexpr uint32_t DT_NULL = 0;            // 结束标记
inline constexpr uint32_t DT_NEEDED = 1;          // 需要的共享库
inline constexpr uint32_t DT_PLTRELSZ = 2;        // PLT重定位大小
inline constexpr uint32_t DT_PLTGOT = 3;          // PLT全局偏移表
inline constexpr uint32_t DT_HASH = 4;            // 符号哈希表
inline constexpr uint32_t DT_STRTAB = 5;          // 字符串表地址
inline constexpr uint32_t DT_SYMTAB = 6;          // 符号表地址
inline constexpr uint32_t DT_RELA = 7;            // 重定位表
inline constexpr uint32_t DT_RELASZ = 8;          // 重定位表大小
inline constexpr uint32_t DT_RELAENT = 9;         // 重定位表项大小
inline constexpr uint32_t DT_STRSZ = 10;          // 字符串表大小
inline constexpr uint32_t DT_SYMENT = 11;         // 符号表项大小
inline constexpr uint32_t DT_INIT = 12;           // 初始化函数地址
inline constexpr uint32_t DT_FINI = 13;           // 终止函数地址
inline constexpr uint32_t DT_SONAME = 14;         // 共享对象名
inline constexpr uint32_t DT_RPATH = 15;          // 搜索路径
inline constexpr uint32_t DT_SYMBOLIC = 16;       // 符号解析
inline constexpr uint32_t DT_REL = 17;            // 重定位表
inline constexpr uint32_t DT_RELSZ = 18;          // 重定位表大小
inline constexpr uint32_t DT_RELENT = 19;         // 重定位表项大小
inline constexpr uint32_t DT_PLTREL = 20;         // PLT重定位类型
inline constexpr uint32_t DT_DEBUG = 21;          // 调试信息
inline constexpr uint32_t DT_TEXTREL = 22;        // 文本重定位
inline constexpr uint32_t DT_JMPREL = 23;         // PLT重定位地址
inline constexpr uint32_t DT_BIND_NOW = 24;       // 立即绑定
inline constexpr uint32_t DT_INIT_ARRAY = 25;     // 初始化函数数组
inline constexpr uint32_t DT_FINI_ARRAY = 26;     // 终止函数数组
inline constexpr uint32_t DT_INIT_ARRAYSZ = 27;   // 初始化函数数组大小
inline constexpr uint32_t DT_FINI_ARRAYSZ = 28;   // 终止函数数组大小
inline constexpr uint32_t DT_GNU_HASH = 0x6FFFFEF5;// GNU哈希表

// 节标志
inline constexpr uint32_t SHF_WRITE = 0x00000001; // 可写
inline constexpr uint32_t SHF_ALLOC = 0x00000002; // 占用内存
inline constexpr uint32_t SHF_EXECINSTR = 0x00000004; // 可执行
inline constexpr uint32_t SHF_MERGE = 0x00000010;
inline constexpr uint32_t SHF_STRINGS = 0x00000020;
inline constexpr uint32_t SHF_INFO_LINK = 0x00000040;
inline constexpr uint32_t SHF_TLS = 0x00000400;
inline constexpr uint32_t SHF_COMPRESSED = 0x00000800;

// ============================================================================
// ELF数据结构
// ============================================================================

#pragma pack(push, 1)

// ELF标识（e_ident前16字节）
struct ELFIdent {
    uint8_t magic[4];        // 0x7F 'E' 'L' 'F'
    uint8_t fileClass;       // 1=32-bit, 2=64-bit
    uint8_t dataEncoding;    // 1=LE, 2=BE
    uint8_t fileVersion;     // 1=current
    uint8_t osAbi;           // OS/ABI
    uint8_t abiVersion;      // ABI version
    uint8_t padding[7];      // 填充
};

// ELF头（32位）
struct ELFHeader32 {
    ELFIdent ident;                    // 标识
    uint16_t type;                     // 文件类型
    uint16_t machine;                  // 机器类型
    uint32_t version;                  // 版本
    uint32_t entry;                    // 入口点地址
    uint32_t phoff;                    // 程序头表偏移
    uint32_t shoff;                    // 节头表偏移
    uint32_t flags;                    // 处理器相关标志
    uint16_t ehsize;                   // ELF头大小
    uint16_t phentsize;                // 程序头表项大小
    uint16_t phnum;                    // 程序头表项数量
    uint16_t shentsize;                // 节头表项大小
    uint16_t shnum;                    // 节头表项数量
    uint16_t shstrndx;                 // 节头字符串表索引
};

// ELF头（64位）
struct ELFHeader64 {
    ELFIdent ident;                    // 标识
    uint16_t type;                     // 文件类型
    uint16_t machine;                  // 机器类型
    uint32_t version;                  // 版本
    uint64_t entry;                    // 入口点地址
    uint64_t phoff;                    // 程序头表偏移
    uint64_t shoff;                    // 节头表偏移
    uint32_t flags;                    // 处理器相关标志
    uint16_t ehsize;                   // ELF头大小
    uint16_t phentsize;                // 程序头表项大小
    uint16_t phnum;                    // 程序头表项数量
    uint16_t shentsize;                // 节头表项大小
    uint16_t shnum;                    // 节头表项数量
    uint16_t shstrndx;                 // 节头字符串表索引
};

// 程序头（32位）
struct ProgramHeader32 {
    uint32_t type;        // 段类型
    uint32_t offset;      // 段在文件中的偏移
    uint32_t vaddr;       // 段在内存中的虚拟地址
    uint32_t paddr;       // 段在内存中的物理地址
    uint32_t filesz;      // 段在文件中的大小
    uint32_t memsz;       // 段在内存中的大小
    uint32_t flags;       // 段标志
    uint32_t align;       // 段对齐
};

// 程序头（64位）
struct ProgramHeader64 {
    uint32_t type;        // 段类型
    uint32_t flags;       // 段标志
    uint64_t offset;      // 段在文件中的偏移
    uint64_t vaddr;       // 段在内存中的虚拟地址
    uint64_t paddr;       // 段在内存中的物理地址
    uint64_t filesz;      // 段在文件中的大小
    uint64_t memsz;       // 段在内存中的大小
    uint64_t align;       // 段对齐
};

// 节头（32位）
struct SectionHeader32 {
    uint32_t name;        // 节名（字符串表索引）
    uint32_t type;        // 节类型
    uint32_t flags;       // 节标志
    uint32_t addr;        // 内存地址
    uint32_t offset;      // 文件偏移
    uint32_t size;        // 节大小
    uint32_t link;        // 关联节索引
    uint32_t info;        // 附加信息
    uint32_t addralign;   // 地址对齐
    uint32_t entsize;     // 表项大小
};

// 节头（64位）
struct SectionHeader64 {
    uint32_t name;        // 节名（字符串表索引）
    uint32_t type;        // 节类型
    uint64_t flags;       // 节标志
    uint64_t addr;        // 内存地址
    uint64_t offset;      // 文件偏移
    uint64_t size;        // 节大小
    uint32_t link;        // 关联节索引
    uint32_t info;        // 附加信息
    uint64_t addralign;   // 地址对齐
    uint64_t entsize;     // 表项大小
};

// 动态表项（32位）
struct DynEntry32 {
    uint32_t tag;         // 动态表标签
    uint32_t val;         // 值（地址或整数）
};

// 动态表项（64位）
struct DynEntry64 {
    uint64_t tag;         // 动态表标签
    uint64_t val;         // 值（地址或整数）
};

// 符号表项（32位）
struct SymEntry32 {
    uint32_t name;        // 符号名（字符串表索引）
    uint32_t value;       // 符号值
    uint32_t size;        // 符号大小
    uint8_t  info;        // 类型和绑定
    uint8_t  other;       // 未使用
    uint16_t shndx;       // 节索引
};

// 符号表项（64位）
struct SymEntry64 {
    uint32_t name;        // 符号名（字符串表索引）
    uint8_t  info;        // 类型和绑定
    uint8_t  other;       // 未使用
    uint16_t shndx;       // 节索引
    uint64_t value;       // 符号值
    uint64_t size;        // 符号大小
};

#pragma pack(pop)

// ELF节信息
struct ELFSectionInfo {
    std::string name;
    uint64_t virtualAddress;
    uint64_t fileOffset;
    uint64_t fileSize;
    uint64_t memorySize;
    uint32_t type;
    uint32_t flags;
    uint64_t addralign;   // 地址对齐
    double entropy;
    bool isWriteable;
    bool isExecutable;
    bool isAllocatable;
};

// ELF依赖的共享库
struct ELFDependency {
    std::string name;
    uint32_t type;        // DT_NEEDED等
};

// ELF符号
struct ELFSymbol {
    std::string name;
    uint64_t value;       // 地址或偏移
    uint64_t size;
    uint8_t type;         // STT_NOTYPE, STT_OBJECT, STT_FUNC, STT_FILE等
    uint8_t binding;      // STB_LOCAL, STB_GLOBAL, STB_WEAK
    uint16_t sectionIndex;
};

// ELF程序头（段）
struct ELFProgramHeader {
    uint32_t type;
    uint64_t virtualAddress;
    uint64_t fileOffset;
    uint64_t fileSize;
    uint64_t memorySize;
    uint32_t flags;
    uint64_t alignment;
};

// ELF头信息汇总
struct ELFHeaderInfo {
    bool isValid;
    bool is64Bit;         // true=ELFCLASS64, false=ELFCLASS32
    uint16_t fileType;    // ET_DYN, ET_EXEC, ET_REL
    uint16_t machine;     // EM_X86_64, EM_ARM, etc.
    uint32_t version;     // EV_CURRENT
    uint64_t entryPoint;  // e_entry
    std::string abi;      // 可读的ABI描述
    std::string machineName; // 可读的机器类型
    std::vector<ELFProgramHeader> programHeaders;
    std::vector<ELFSectionInfo> sections;
    std::vector<ELFDependency> dependencies;
    std::vector<ELFSymbol> symbols;
    std::vector<std::string> exportedSymbols;
    std::vector<std::string> importedSymbols;
};

} // namespace dll
} // namespace forensics

#endif // DLL_DATA_TYPES_H
