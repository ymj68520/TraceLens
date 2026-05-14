// ELFParser.cpp
// ELF文件格式解析器实现

#include "analyzers/DLLAnalyzer/Parsers/ELFParser.h"
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

void ELFParser::parseProgramHeaders(const std::string& filePath, ELFHeaderInfo& info) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return;
    }

    file.seekg(0, std::ios::beg);

    // 读取标识确定class
    ELFIdent ident;
    file.read(reinterpret_cast<char*>(&ident), sizeof(ELFIdent));

    // 重新定位到文件开头读取完整头
    file.seekg(0, std::ios::beg);

    if (ident.fileClass == ELFCLASS32) {
        ELFHeader32 header;
        file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader32));
        if (header.phoff > 0 && header.phnum > 0) {
            parseProgramHeaders32(file, header.phoff, header.phnum, info.programHeaders);
        }
    } else if (ident.fileClass == ELFCLASS64) {
        ELFHeader64 header;
        file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader64));
        if (header.phoff > 0 && header.phnum > 0) {
            parseProgramHeaders64(file, header.phoff, header.phnum, info.programHeaders);
        }
    }
}

void ELFParser::parseProgramHeaders32(std::ifstream& file, uint64_t offset, uint16_t count,
                                       std::vector<ELFProgramHeader>& entries) {
    file.seekg(offset, std::ios::beg);

    if (!file) {
        LOG_WARNING("Failed to seek to program headers at offset " + std::to_string(offset));
        return;
    }

    entries.reserve(count);
    for (uint16_t i = 0; i < count; i++) {
        ProgramHeader32 ph32;
        file.read(reinterpret_cast<char*>(&ph32), sizeof(ProgramHeader32));

        if (!file) {
            LOG_WARNING("Failed to read program header " + std::to_string(i) + " at offset " + std::to_string(file.tellg()));
            break;
        }

        ELFProgramHeader ph;
        ph.type = ph32.type;
        ph.virtualAddress = ph32.vaddr;
        ph.fileOffset = ph32.offset;
        ph.fileSize = ph32.filesz;
        ph.memorySize = ph32.memsz;
        ph.flags = ph32.flags;
        ph.alignment = ph32.align;

        entries.push_back(ph);
    }
}

void ELFParser::parseProgramHeaders64(std::ifstream& file, uint64_t offset, uint16_t count,
                                       std::vector<ELFProgramHeader>& entries) {
    file.seekg(offset, std::ios::beg);

    entries.reserve(count);
    for (uint16_t i = 0; i < count; i++) {
        ProgramHeader64 ph64;
        file.read(reinterpret_cast<char*>(&ph64), sizeof(ProgramHeader64));

        if (!file) {
            LOG_WARNING("Failed to read program header " + std::to_string(i));
            break;
        }

        ELFProgramHeader ph;
        ph.type = ph64.type;
        ph.virtualAddress = ph64.vaddr;
        ph.fileOffset = ph64.offset;
        ph.fileSize = ph64.filesz;
        ph.memorySize = ph64.memsz;
        ph.flags = ph64.flags;
        ph.alignment = ph64.align;

        entries.push_back(ph);
    }
}

void ELFParser::parseSectionHeaders(const std::string& filePath, ELFHeaderInfo& info) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return;
    }

    file.seekg(0, std::ios::beg);

    // 读取标识确定class
    ELFIdent ident;
    file.read(reinterpret_cast<char*>(&ident), sizeof(ELFIdent));

    // 重新定位到文件开头读取完整头
    file.seekg(0, std::ios::beg);

    if (ident.fileClass == ELFCLASS32) {
        ELFHeader32 header;
        file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader32));
        if (header.shoff > 0 && header.shnum > 0) {
            parseSectionHeaders32(file, header.shoff, header.shnum, info.sections);
        }
    } else if (ident.fileClass == ELFCLASS64) {
        ELFHeader64 header;
        file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader64));
        if (header.shoff > 0 && header.shnum > 0) {
            parseSectionHeaders64(file, header.shoff, header.shnum, info.sections);
        }
    }
}

void ELFParser::parseSectionHeaders32(std::ifstream& file, uint64_t offset, uint16_t count,
                                       std::vector<ELFSectionInfo>& entries) {
    file.seekg(offset, std::ios::beg);

    entries.reserve(count);
    uint64_t stringTableOffset = 0;
    uint64_t stringTableSize = 0;

    for (uint16_t i = 0; i < count; i++) {
        SectionHeader32 sh32;
        file.read(reinterpret_cast<char*>(&sh32), sizeof(SectionHeader32));

        if (!file) {
            LOG_WARNING("Failed to read section header " + std::to_string(i));
            break;
        }

        ELFSectionInfo section;
        section.type = sh32.type;
        section.flags = sh32.flags;
        section.virtualAddress = sh32.addr;
        section.fileOffset = sh32.offset;
        section.fileSize = sh32.size;
        section.addralign = sh32.addralign;
        section.isWriteable = (sh32.flags & SHF_WRITE) != 0;
        section.isExecutable = (sh32.flags & SHF_EXECINSTR) != 0;
        section.isAllocatable = (sh32.flags & SHF_ALLOC) != 0;

        // 计算熵
        if (sh32.size > 0 && sh32.offset > 0) {
            section.entropy = calculateSectionEntropy("", sh32.offset, sh32.size);
        } else {
            section.entropy = 0.0;
        }

        entries.push_back(section);
    }

    // 读取节名（简化版，仅对已知节名）
    file.seekg(offset, std::ios::beg);
    uint64_t shstrtabOffset = 0;
    uint64_t shstrtabSize = 0;

    for (uint16_t i = 0; i < count && i < entries.size(); i++) {
        SectionHeader32 sh32;
        file.read(reinterpret_cast<char*>(&sh32), sizeof(SectionHeader32));

        if (sh32.type == SHT_STRTAB && i > 0) {
            shstrtabOffset = sh32.offset;
            shstrtabSize = sh32.size;
            break;
        }
    }

    if (shstrtabOffset > 0 && shstrtabSize > 0) {
        std::vector<uint8_t> buf = readFileBuffer("", shstrtabOffset, shstrtabSize);
        std::string strTab(reinterpret_cast<char*>(buf.data()), buf.size());

        file.seekg(offset, std::ios::beg);
        for (uint16_t i = 0; i < count && i < entries.size(); i++) {
            SectionHeader32 sh32;
            file.read(reinterpret_cast<char*>(&sh32), sizeof(SectionHeader32));

            if (sh32.name < strTab.size()) {
                entries[i].name = strTab.substr(sh32.name);
            }
        }
    }
}

void ELFParser::parseSectionHeaders64(std::ifstream& file, uint64_t offset, uint16_t count,
                                       std::vector<ELFSectionInfo>& entries) {
    file.seekg(offset, std::ios::beg);

    entries.reserve(count);
    uint64_t stringTableOffset = 0;
    uint64_t stringTableSize = 0;

    for (uint16_t i = 0; i < count; i++) {
        SectionHeader64 sh64;
        file.read(reinterpret_cast<char*>(&sh64), sizeof(SectionHeader64));

        if (!file) {
            LOG_WARNING("Failed to read section header " + std::to_string(i));
            break;
        }

        ELFSectionInfo section;
        section.type = static_cast<uint32_t>(sh64.type);
        section.flags = static_cast<uint32_t>(sh64.flags);
        section.virtualAddress = sh64.addr;
        section.fileOffset = sh64.offset;
        section.fileSize = sh64.size;
        section.addralign = sh64.addralign;
        section.isWriteable = (sh64.flags & SHF_WRITE) != 0;
        section.isExecutable = (sh64.flags & SHF_EXECINSTR) != 0;
        section.isAllocatable = (sh64.flags & SHF_ALLOC) != 0;

        // 计算熵
        if (sh64.size > 0 && sh64.offset > 0) {
            section.entropy = calculateSectionEntropy("", sh64.offset, sh64.size);
        } else {
            section.entropy = 0.0;
        }

        entries.push_back(section);
    }
}

void ELFParser::parseDynamicSection(const std::string& filePath, ELFHeaderInfo& info) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return;
    }

    file.seekg(0, std::ios::beg);

    // 读取标识确定class
    ELFIdent ident;
    file.read(reinterpret_cast<char*>(&ident), sizeof(ELFIdent));

    if (ident.fileClass == ELFCLASS32) {
        ELFHeader32 header;
        file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader32));
        // 暂时跳过实现
        // parseDynamicSection32(file, header.phoff, info);
    } else if (ident.fileClass == ELFCLASS64) {
        ELFHeader64 header;
        file.read(reinterpret_cast<char*>(&header), sizeof(ELFHeader64));
        // 暂时跳过实现
        // parseDynamicSection64(file, header.phoff, info);
    }
}

void ELFParser::parseDynamicSection32(std::ifstream& file, uint64_t offset, ELFHeaderInfo& info) {
    // TODO: 实现32位动态段解析
}

void ELFParser::parseDynamicSection64(std::ifstream& file, uint64_t offset, ELFHeaderInfo& info) {
    // TODO: 实现64位动态段解析
}

void ELFParser::parseSymbolTable(const std::string& filePath, ELFHeaderInfo& info) {
    // TODO: 实现符号表解析
}

void ELFParser::parseSymbolTable32(std::ifstream& file, uint64_t strOffset, uint64_t symOffset,
                                     uint32_t count, const std::string& strTab, bool isDynamic,
                                     ELFHeaderInfo& info) {
    // TODO: 实现32位符号表解析
}

void ELFParser::parseSymbolTable64(std::ifstream& file, uint64_t strOffset, uint64_t symOffset,
                                     uint32_t count, const std::string& strTab, bool isDynamic,
                                     ELFHeaderInfo& info) {
    // TODO: 实现64位符号表解析
}

std::string ELFParser::getStringTable(const std::string& filePath, uint64_t sectionOffset, uint32_t sectionIndex) {
    // TODO: 实现字符串表读取
    return "";
}

double ELFParser::calculateSectionEntropy(const std::string& filePath, uint64_t offset, uint64_t size) {
    // TODO: 复用EntropyCalculator
    return 0.0;
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
