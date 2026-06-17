// ELFParser.cpp
// ELF文件格式解析器实现
//
// This file holds construction, top-level parse() entry, ELF header parsing
// (32/64-bit), and shared helpers (string table, entropy, machine/ABI/section
// type names). The per-area parsers live in:
//   - ELFParser_Sections.cpp   Program Headers & Section Headers
//   - ELFParser_Dynamic.cpp    Dynamic Section & Symbol Table

#include "analyzers/DLLAnalyzer/Parsers/ELFParser.h"
#include "analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h"
#include "core/Logger/Logger.h"
#include <algorithm>
#include <cctype>

namespace forensics {
namespace dll {

ELFParser::ELFParser() = default;

ELFParser::~ELFParser() = default;

ELFHeaderInfo ELFParser::parse(const std::string& filePath) {
    ELFHeaderInfo info;
    info.isValid = false;
    info.is64Bit = false;
    info.fileType = ET_NONE;
    info.machine = EM_NONE;
    info.version = EV_NONE;
    info.entryPoint = 0;

    // 解析ELF头
    if (!parseELFHeader(filePath, info)) {
        LOG_WARNING("Failed to parse ELF header: " + filePath);
        return info;
    }

    // 解析程序头表
    parseProgramHeaders(filePath, info);

    // 解析节头表
    parseSectionHeaders(filePath, info);

    // 解析动态段
    parseDynamicSection(filePath, info);

    // 解析符号表
    parseSymbolTable(filePath, info);

    info.isValid = true;
    return info;
}

bool ELFParser::isValidELF(const std::string& filePath) const {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    uint8_t magic[4];
    file.read(reinterpret_cast<char*>(magic), 4);

    return (magic[0] == EI_MAG0 && magic[1] == EI_MAG1 &&
            magic[2] == EI_MAG2 && magic[3] == EI_MAG3);
}

bool ELFParser::parseELFHeader(const std::string& filePath, ELFHeaderInfo& info) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        LOG_WARNING("Cannot open file: " + filePath);
        return false;
    }

    // 读取标识
    ELFIdent ident;
    file.read(reinterpret_cast<char*>(&ident), sizeof(ELFIdent));

    // 验证魔术字节
    if (ident.magic[0] != EI_MAG0 || ident.magic[1] != EI_MAG1 ||
        ident.magic[2] != EI_MAG2 || ident.magic[3] != EI_MAG3) {
        LOG_DEBUG("Invalid ELF magic bytes: " + filePath);
        return false;
    }

    // 根据class解析对应头
    if (ident.fileClass == ELFCLASS32) {
        return parseELFHeader32(file, info);
    } else if (ident.fileClass == ELFCLASS64) {
        return parseELFHeader64(file, info);
    } else {
        LOG_WARNING("Unknown ELF class: " + std::to_string(ident.fileClass));
        return false;
    }
}

bool ELFParser::parseELFHeader32(std::ifstream& file, ELFHeaderInfo& info) {
    file.seekg(0, std::ios::beg);

    ELFHeader32 header;
    file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader32));

    if (!file) {
        LOG_WARNING("Failed to read ELF32 header");
        return false;
    }

    info.is64Bit = false;
    info.fileType = header.type;
    info.machine = header.machine;
    info.version = header.version;
    info.entryPoint = header.entry;
    info.abi = getABIName(header.ident.osAbi);
    info.machineName = getMachineName(header.machine);

    LOG_DEBUG("Parsed ELF32 header: type=" + std::to_string(header.type) +
              " machine=" + std::to_string(header.machine));

    return true;
}

bool ELFParser::parseELFHeader64(std::ifstream& file, ELFHeaderInfo& info) {
    file.seekg(0, std::ios::beg);

    ELFHeader64 header;
    file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader64));

    if (!file) {
        LOG_WARNING("Failed to read ELF64 header");
        return false;
    }

    info.is64Bit = true;
    info.fileType = header.type;
    info.machine = header.machine;
    info.version = header.version;
    info.entryPoint = header.entry;
    info.abi = getABIName(header.ident.osAbi);
    info.machineName = getMachineName(header.machine);

    LOG_DEBUG("Parsed ELF64 header: type=" + std::to_string(header.type) +
              " machine=" + std::to_string(header.machine));

    return true;
}

std::string ELFParser::getStringTable(const std::string& filePath, uint64_t sectionOffset, uint32_t sectionIndex) {
    std::string result;

    if (filePath.empty() || sectionOffset == 0) {
        return result;
    }

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return result;
    }

    file.seekg(sectionOffset, std::ios::beg);
    if (file.fail()) {
        return result;
    }

    // 读取整个字符串表
    const size_t MAX_STRING_TABLE_SIZE = 65536; // 64KB最大
    std::vector<char> buffer(MAX_STRING_TABLE_SIZE);

    file.read(buffer.data(), buffer.size());
    if (!file) {
        std::streamsize actualSize = file.gcount();
        if (actualSize > 0) {
            buffer.resize(static_cast<size_t>(actualSize));
        } else {
            return result;
        }
    }

    // 手动查找null-terminator
    size_t len = 0;
    while (len < buffer.size() && buffer[len] != '\0') {
        len++;
    }

    result.assign(buffer.data(), len);
    return result;
}

std::string ELFParser::readDynamicString(std::ifstream& file, uint64_t strTabOffset, uint64_t strTabSize, uint64_t val) {
    std::string result;

    if (!file.is_open() || file.fail() || strTabOffset == 0 || strTabSize == 0) {
        return result;
    }

    // val是字符串在字符串表中的偏移
    if (val >= strTabSize) {
        return result;
    }

    // 保存当前位置
    std::streampos currentPos = file.tellg();

    // 定位到字符串
    file.seekg(strTabOffset + val, std::ios::beg);
    if (file.fail()) {
        file.seekg(currentPos); // 恢复位置
        return result;
    }

    // 读取字符串直到'\0'或达到合理限制
    const size_t MAX_STRING_LEN = 4096;
    std::vector<char> buffer(MAX_STRING_LEN);

    for (size_t i = 0; i < MAX_STRING_LEN; ++i) {
        char c;
        file.get(c);
        if (!file || c == '\0') {
            buffer[i] = '\0';
            result = buffer.data();
            break;
        }
        buffer[i] = c;
    }

    // 恢复文件位置
    file.seekg(currentPos);

    return result;
}

double ELFParser::calculateSectionEntropy(const std::string& filePath, uint64_t offset, uint64_t size) {
    if (filePath.empty() || size == 0 || size > 100 * 1024 * 1024) {
        return 0.0; // 跳过超过100MB的节
    }

    std::vector<uint8_t> buffer = readFileBuffer(filePath, offset, size);
    if (buffer.empty()) {
        return 0.0;
    }

    // 复用PEHeaderParser的熵值计算方法
    return PEHeaderParser::calculateEntropy(buffer);
}

std::vector<uint8_t> ELFParser::readFileBuffer(const std::string& filePath, uint64_t offset, uint64_t size) {
    std::vector<uint8_t> buffer;
    if (filePath.empty() || size == 0) {
        return buffer;
    }

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return buffer;
    }

    file.seekg(offset, std::ios::beg);
    buffer.resize(static_cast<size_t>(size));
    file.read(reinterpret_cast<char*>(buffer.data()), size);

    if (!file) {
        buffer.clear();
    }

    return buffer;
}

std::string ELFParser::getMachineName(uint16_t machine) const {
    switch (machine) {
        case EM_NONE: return "None";
        case EM_M32: return "AT&T WE 32100";
        case EM_SPARC: return "SPARC";
        case EM_386: return "x86";
        case EM_68K: return "Motorola 68000";
        case EM_88K: return "Motorola 88000";
        case EM_486: return "Intel 80486";
        case EM_MIPS: return "MIPS";
        case EM_PARISC: return "HP PA-RISC";
        case EM_SPARC32PLUS: return "SPARC V8+";
        case EM_PPC: return "PowerPC";
        case EM_PPC64: return "PowerPC 64-bit";
        case EM_ARM: return "ARM";
        case EM_X86_64: return "x86-64";
        case EM_AARCH64: return "ARM64";
        case EM_RISCV: return "RISC-V";
        default: return "Unknown (0x" + std::to_string(machine) + ")";
    }
}

std::string ELFParser::getABIName(uint8_t osAbi) const {
    switch (osAbi) {
        case 0: return "System V";
        case 1: return "HP-UX";
        case 2: return "NetBSD";
        case 3: return "Linux";
        case 4: return "GNU Hurd";
        case 5: return "Solaris";
        case 6: return "AIX";
        case 7: return "IRIX";
        case 8: return "FreeBSD";
        case 9: return "Tru64";
        case 10: return "Novell Modesto";
        case 11: return "OpenBSD";
        case 12: return "OpenVMS";
        case 13: return "NonStop Kernel";
        case 14: return "AROS";
        case 15: return "Fenix";
        case 16: return "CloudABI";
        case 17: return "OpenVOS";
        default: return "Unknown (0x" + std::to_string(osAbi) + ")";
    }
}

std::string ELFParser::getSectionTypeName(uint32_t type) const {
    switch (type) {
        case SHT_NULL: return "NULL";
        case SHT_PROGBITS: return "PROGBITS";
        case SHT_SYMTAB: return "SYMTAB";
        case SHT_STRTAB: return "STRTAB";
        case SHT_RELA: return "RELA";
        case SHT_HASH: return "HASH";
        case SHT_DYNAMIC: return "DYNAMIC";
        case SHT_NOTE: return "NOTE";
        case SHT_NOBITS: return "NOBITS";
        case SHT_REL: return "REL";
        case SHT_SHLIB: return "SHLIB";
        case SHT_DYNSYM: return "DYNSYM";
        case SHT_GNU_HASH: return "GNU_HASH";
        default: return "Unknown (0x" + std::to_string(type) + ")";
    }
}


} // namespace dll
} // namespace forensics
