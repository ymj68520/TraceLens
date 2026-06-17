// ELFParser_Dynamic.cpp
// ELF Dynamic Section & Symbol Table parsing (32/64-bit)
// Part of ELFParser implementation; methods belong to forensics::dll::ELFParser
// declared in analyzers/DLLAnalyzer/Parsers/ELFParser.h. Split from ELFParser.cpp.

#include "analyzers/DLLAnalyzer/Parsers/ELFParser.h"
#include "analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h"
#include "core/Logger/Logger.h"
#include <algorithm>
#include <cctype>

namespace forensics {
namespace dll {

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
    if (!file.is_open() || file.fail()) {
        return;
    }

    file.seekg(offset, std::ios::beg);
    if (file.fail()) {
        return;
    }

    // 读取程序头以找到PT_DYNAMIC段
    // 动态段的偏移和大小在程序头中
    uint64_t dynamicOffset = 0;
    uint64_t dynamicSize = 0;
    uint64_t strTabOffset = 0;
    uint64_t strTabSize = 0;

    for (const auto& phdr : info.programHeaders) {
        if (phdr.type == PT_DYNAMIC) {
            dynamicOffset = phdr.fileOffset;
            dynamicSize = phdr.fileSize;
            break;
        }
    }

    if (dynamicOffset == 0 || dynamicSize == 0) {
        return; // 没有动态段
    }

    // 解析动态表项 (Elf32_Dyn)
    struct Elf32_Dyn {
        int32_t tag;
        uint32_t val;
    };

    file.seekg(dynamicOffset, std::ios::beg);
    size_t numEntries = static_cast<size_t>(dynamicSize / sizeof(Elf32_Dyn));

    for (size_t i = 0; i < numEntries; ++i) {
        Elf32_Dyn dyn;
        file.read(reinterpret_cast<char*>(&dyn), sizeof(dyn));
        if (!file) break;

        // DT_NULL标记动态段结束
        if (dyn.tag == DT_NULL) {
            break;
        }

        // DT_NEEDED: 需要的共享库
        if (dyn.tag == DT_NEEDED) {
            // val是字符串表偏移
            std::string libName = readDynamicString(file, strTabOffset, strTabSize, dyn.val);
            if (!libName.empty()) {
                ELFDependency dep;
                dep.name = libName;
                dep.type = DT_NEEDED;
                info.dependencies.push_back(dep);
            }
        }
        // DT_SONAME: 共享对象名
        else if (dyn.tag == DT_SONAME) {
            std::string soname = readDynamicString(file, strTabOffset, strTabSize, dyn.val);
            if (!soname.empty()) {
                info.abi = soname;
            }
        }
        // DT_STRTAB: 字符串表地址
        else if (dyn.tag == DT_STRTAB) {
            strTabOffset = dyn.val;
        }
        // DT_STRSZ: 字符串表大小
        else if (dyn.tag == DT_STRSZ) {
            strTabSize = dyn.val;
        }
    }
}

void ELFParser::parseDynamicSection64(std::ifstream& file, uint64_t offset, ELFHeaderInfo& info) {
    if (!file.is_open() || file.fail()) {
        return;
    }

    file.seekg(offset, std::ios::beg);
    if (file.fail()) {
        return;
    }

    // 64位动态表项 (Elf64_Dyn)
    struct Elf64_Dyn {
        int64_t tag;
        uint64_t val;
    };

    uint64_t dynamicOffset = 0;
    uint64_t dynamicSize = 0;
    uint64_t strTabOffset = 0;
    uint64_t strTabSize = 0;

    for (const auto& phdr : info.programHeaders) {
        if (phdr.type == PT_DYNAMIC) {
            dynamicOffset = phdr.fileOffset;
            dynamicSize = phdr.fileSize;
            break;
        }
    }

    if (dynamicOffset == 0 || dynamicSize == 0) {
        return;
    }

    file.seekg(dynamicOffset, std::ios::beg);
    size_t numEntries = static_cast<size_t>(dynamicSize / sizeof(Elf64_Dyn));

    for (size_t i = 0; i < numEntries; ++i) {
        Elf64_Dyn dyn;
        file.read(reinterpret_cast<char*>(&dyn), sizeof(dyn));
        if (!file) break;

        if (dyn.tag == DT_NULL) {
            break;
        }

        if (dyn.tag == DT_NEEDED) {
            std::string libName = readDynamicString(file, strTabOffset, strTabSize, dyn.val);
            if (!libName.empty()) {
                ELFDependency dep;
                dep.name = libName;
                dep.type = DT_NEEDED;
                info.dependencies.push_back(dep);
            }
        }
        else if (dyn.tag == DT_SONAME) {
            std::string soname = readDynamicString(file, strTabOffset, strTabSize, dyn.val);
            if (!soname.empty()) {
                info.abi = soname;
            }
        }
        else if (dyn.tag == DT_STRTAB) {
            strTabOffset = dyn.val;
        }
        else if (dyn.tag == DT_STRSZ) {
            strTabSize = dyn.val;
        }
    }
}

void ELFParser::parseSymbolTable(const std::string& filePath, ELFHeaderInfo& info) {
    if (filePath.empty() || !info.isValid) {
        return;
    }

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return;
    }

    // 遍历节头表，找到符号表和字符串表
    uint64_t symTabOffset = 0;
    uint64_t symTabSize = 0;
    uint64_t strTabOffset = 0;
    uint64_t strTabSize = 0;
    uint32_t symCount = 0;
    bool isDynamic = false;

    // 查找.dynsym和.dynstr（动态符号表）或.symtab和.strtab（静态符号表）
    for (size_t i = 0; i < info.sections.size(); ++i) {
        const auto& section = info.sections[i];
        std::string secName = section.name;

        if (secName == ".dynsym") {
            symTabOffset = section.fileOffset;
            symTabSize = section.fileSize;
            symCount = static_cast<uint32_t>(section.fileSize / (info.is64Bit ? sizeof(SymEntry64) : sizeof(SymEntry32)));
            isDynamic = true;

            // 查找对应的字符串表（通常在.dynstr后面）
            for (size_t j = i + 1; j < info.sections.size() && j < i + 3; ++j) {
                if (info.sections[j].name == ".dynstr") {
                    strTabOffset = info.sections[j].fileOffset;
                    strTabSize = info.sections[j].fileSize;
                    break;
                }
            }
            break;
        }
        else if (secName == ".symtab") {
            symTabOffset = section.fileOffset;
            symTabSize = section.fileSize;
            symCount = static_cast<uint32_t>(section.fileSize / (info.is64Bit ? sizeof(SymEntry64) : sizeof(SymEntry32)));
            isDynamic = false;

            // 查找对应的字符串表（通常在.strtab后面）
            for (size_t j = i + 1; j < info.sections.size() && j < i + 3; ++j) {
                if (info.sections[j].name == ".strtab") {
                    strTabOffset = info.sections[j].fileOffset;
                    strTabSize = info.sections[j].fileSize;
                    break;
                }
            }
            break;
        }
    }

    if (symTabOffset == 0 || strTabOffset == 0 || symCount == 0) {
        return;
    }

    // 读取字符串表
    std::string strTab = getStringTable(filePath, strTabOffset, 0);
    if (strTab.empty()) {
        return;
    }

    // 解析符号表
    if (info.is64Bit) {
        parseSymbolTable64(file, strTabOffset, symTabOffset, symCount, strTab, isDynamic, info);
    } else {
        parseSymbolTable32(file, strTabOffset, symTabOffset, symCount, strTab, isDynamic, info);
    }
}

void ELFParser::parseSymbolTable32(std::ifstream& file, uint64_t strOffset, uint64_t symOffset,
                                     uint32_t count, const std::string& strTab, bool isDynamic,
                                     ELFHeaderInfo& info) {
    if (!file.is_open() || file.fail()) {
        return;
    }

    file.seekg(symOffset, std::ios::beg);
    if (file.fail()) {
        return;
    }

    for (uint32_t i = 0; i < count; ++i) {
        SymEntry32 sym;
        file.read(reinterpret_cast<char*>(&sym), sizeof(sym));
        if (!file) break;

        // 提取符号名
        std::string name;
        if (sym.name < strTab.size()) {
            name = strTab.substr(sym.name);
        }

        if (name.empty()) {
            continue;
        }

        ELFSymbol symbol;
        symbol.name = name;
        symbol.value = sym.value;
        symbol.size = sym.size;
        symbol.type = sym.info & 0x0F;
        symbol.binding = sym.info >> 4;
        symbol.sectionIndex = sym.shndx;

        if (isDynamic) {
            info.importedSymbols.push_back(name);
        } else {
            info.symbols.push_back(symbol);
        }
    }
}

void ELFParser::parseSymbolTable64(std::ifstream& file, uint64_t strOffset, uint64_t symOffset,
                                     uint32_t count, const std::string& strTab, bool isDynamic,
                                     ELFHeaderInfo& info) {
    if (!file.is_open() || file.fail()) {
        return;
    }

    file.seekg(symOffset, std::ios::beg);
    if (file.fail()) {
        return;
    }

    for (uint32_t i = 0; i < count; ++i) {
        SymEntry64 sym;
        file.read(reinterpret_cast<char*>(&sym), sizeof(sym));
        if (!file) break;

        std::string name;
        if (sym.name < strTab.size()) {
            name = strTab.substr(sym.name);
        }

        if (name.empty()) {
            continue;
        }

        ELFSymbol symbol;
        symbol.name = name;
        symbol.value = sym.value;
        symbol.size = sym.size;
        symbol.type = sym.info & 0x0F;
        symbol.binding = sym.info >> 4;
        symbol.sectionIndex = sym.shndx;

        if (isDynamic) {
            info.importedSymbols.push_back(name);
        } else {
            info.symbols.push_back(symbol);
        }
    }
}


} // namespace dll
} // namespace forensics
