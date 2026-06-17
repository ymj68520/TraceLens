// ELFParser_Sections.cpp
// ELF Program Header & Section Header parsing (32/64-bit)
// Part of ELFParser implementation; methods belong to forensics::dll::ELFParser
// declared in analyzers/DLLAnalyzer/Parsers/ELFParser.h. Split from ELFParser.cpp.

#include "analyzers/DLLAnalyzer/Parsers/ELFParser.h"
#include "analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h"
#include "core/Logger/Logger.h"
#include <algorithm>
#include <cctype>

namespace forensics {
namespace dll {

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


} // namespace dll
} // namespace forensics
