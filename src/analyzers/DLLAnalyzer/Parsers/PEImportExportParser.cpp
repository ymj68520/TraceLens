// PEImportExportParser.cpp
// PE导入/导出表解析器实现

#include "PEImportExportParser.h"
#include "PEHeaderParser.h"
#include <algorithm>
#include <cctype>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <algorithm>

using namespace forensics::dll;

// ============================================================================
// 构造 / 析构
// ============================================================================

PEImportExportParser::PEImportExportParser(const std::string& filePath)
    : filePath_(filePath), isValid_(false),
      imageBase_(0), fileAlignment_(0x200),
      peHeaderOffset_(0), isPE32Plus_(false) {
    std::ifstream file(filePath_, std::ios::binary);
    if (!file.is_open()) {
        errorMessage_ = "Cannot open file: " + filePath_;
        return;
    }

    // 解析PE文件头以获取必要信息
    PEHeaderParser headerParser(filePath_);
    if (!headerParser.parse()) {
        errorMessage_ = "Failed to parse PE header: " + headerParser.getErrorMessage();
        return;
    }

    const PEHeaderInfo& headerInfo = headerParser.getHeaderInfo();

    // 缓存关键字段
    peHeaderOffset_ = headerParser.getPEOffset();
    isPE32Plus_ = headerParser.isPE32Plus();
    imageBase_ = static_cast<uint32_t>(headerInfo.imageBase);
    fileAlignment_ = headerInfo.fileAlignment;
    sections_ = headerInfo.sections;

    // 缓存导入/导出表RVA
    importTableRVA_ = headerInfo.importTableRVA;
    exportTableRVA_ = headerInfo.exportTableRVA;

    isValid_ = true;
}

PEImportExportParser::~PEImportExportParser() = default;

// ============================================================================
// 公共接口
// ============================================================================

bool PEImportExportParser::parseImports(std::vector<ImportedDLL>& imports) {
    imports.clear();

    if (!isValid_) {
        if (errorMessage_.find("Cannot open") != std::string::npos) {
            return false;
        }
        // 如果是因为解析失败，尝试提供更多信息
        errorMessage_ = "Parser not valid: " + errorMessage_;
        return false;
    }

    // 如果没有导入表，返回空（成功）
    if (importTableRVA_ == 0) {
        return true;
    }

    // 读取导入描述符数组
    std::vector<ImportDescriptor> descriptors = readImportDescriptors();
    if (descriptors.empty()) {
        return true; // 没有导入项，也算成功
    }

    // 解析每个导入DLL
    for (const auto& desc : descriptors) {
        // 如果OriginalFirstThunk和FirstThunk都为0，说明是结束标记
        if (desc.originalFirstThunk == 0 && desc.firstThunk == 0) {
            break;
        }

        ImportedDLL importedDLL;
        std::string dllName;
        if (!readStringAt(desc.name, dllName)) {
            continue;
        }
        importedDLL.name = dllName;

        // 解析导入函数（使用INT - Import Name Table）
        uint32_t thunkRVA = desc.originalFirstThunk != 0 ? desc.originalFirstThunk : desc.firstThunk;
        while (true) {
            uint32_t offset = rvaToOffset(thunkRVA);
            if (offset == UINT32_MAX) {
                break;
            }

            // 读取IMAGE_THUNK_DATA（32位或64位）
            if (isPE32Plus_) {
                // 64位: IMAGE_THUNK_DATA64
                uint64_t thunkData = 0;
                {
                    std::ifstream file(filePath_, std::ios::binary);
                    if (!file.is_open()) break;
                    file.seekg(offset);
                    file.read(reinterpret_cast<char*>(&thunkData), sizeof(thunkData));
                    if (!file) break;
                }

                // 最高位为1表示按序数导入
                if ((thunkData & 0x8000000000000000ULL) != 0) {
                    uint16_t ordinal = static_cast<uint16_t>(thunkData & 0xFFFF);
                    importedDLL.functions.push_back("Ordinal_" + std::to_string(ordinal));
                } else if (thunkData != 0) {
                    // 按名称导入: IMAGE_IMPORT_BY_NAME
                    uint32_t nameRVA = static_cast<uint32_t>(thunkData);
                    std::string funcName;
                    if (readStringAt(nameRVA, funcName)) {
                        // 跳过Hint字段（2字节），读取函数名
                        importedDLL.functions.push_back(funcName);
                    }
                } else {
                    // 全零结束
                    break;
                }
            } else {
                // 32位: IMAGE_THUNK_DATA32
                uint32_t thunkData = 0;
                {
                    std::ifstream file(filePath_, std::ios::binary);
                    if (!file.is_open()) break;
                    file.seekg(offset);
                    file.read(reinterpret_cast<char*>(&thunkData), sizeof(thunkData));
                    if (!file) break;
                }

                // 最高位为1表示按序数导入
                if ((thunkData & 0x80000000) != 0) {
                    uint16_t ordinal = static_cast<uint16_t>(thunkData & 0xFFFF);
                    importedDLL.functions.push_back("Ordinal_" + std::to_string(ordinal));
                } else if (thunkData != 0) {
                    // 按名称导入: IMAGE_IMPORT_BY_NAME
                    uint32_t nameRVA = static_cast<uint32_t>(thunkData);
                    std::string funcName;
                    if (readStringAt(nameRVA, funcName)) {
                        // 跳过Hint字段（2字节），读取函数名
                        importedDLL.functions.push_back(funcName);
                    }
                } else {
                    // 全零结束
                    break;
                }
            }

            // 下一个thunk数据
            thunkRVA += (isPE32Plus_ ? 8 : 4);
        }

        if (!importedDLL.name.empty()) {
            imports.push_back(importedDLL);
        }
    }

    return true;
}

bool PEImportExportParser::parseExports(std::vector<ExportedFunction>& exports) {
    exports.clear();

    if (!isValid_) {
        if (errorMessage_.find("Cannot open") != std::string::npos) {
            return false;
        }
        errorMessage_ = "Parser not valid: " + errorMessage_;
        return false;
    }

    // 如果没有导出表，返回空（成功）
    if (exportTableRVA_ == 0) {
        return true;
    }

    // 读取导出目录
    ExportDirectory exportDir;
    if (!readExportDirectory(exportDir)) {
        return true; // 无法读取导出目录，返回空（成功）
    }

    if (exportDir.numberOfNames == 0 || exportDir.numberOfFunctions == 0) {
        return true;
    }

    // 读取导出名称表（ENT）
    std::vector<uint32_t> nameRVAs(exportDir.numberOfNames);
    {
        uint32_t entOffset = rvaToOffset(exportDir.addressOfNames);
        if (entOffset == UINT32_MAX) return true;

        std::ifstream file(filePath_, std::ios::binary);
        if (!file.is_open()) return true;
        file.seekg(entOffset);
        file.read(reinterpret_cast<char*>(nameRVAs.data()), exportDir.numberOfNames * sizeof(uint32_t));
        if (!file) return true;
    }

    // 读取导出序数表（EOT）
    std::vector<uint16_t> ordinals(exportDir.numberOfNames);
    {
        uint32_t eotOffset = rvaToOffset(exportDir.addressOfNameOrdinals);
        if (eotOffset == UINT32_MAX) return true;

        std::ifstream file(filePath_, std::ios::binary);
        if (!file.is_open()) return true;
        file.seekg(eotOffset);
        file.read(reinterpret_cast<char*>(ordinals.data()), exportDir.numberOfNames * sizeof(uint16_t));
        if (!file) return true;
    }

    // 读取导出地址表（EAT）
    std::vector<uint32_t> functionRVAs(exportDir.numberOfFunctions);
    {
        uint32_t eatOffset = rvaToOffset(exportDir.addressOfFunctions);
        if (eatOffset == UINT32_MAX) return true;

        std::ifstream file(filePath_, std::ios::binary);
        if (!file.is_open()) return true;
        file.seekg(eatOffset);
        file.read(reinterpret_cast<char*>(functionRVAs.data()), exportDir.numberOfFunctions * sizeof(uint32_t));
        if (!file) return true;
    }

    // 解析导出函数
    for (uint32_t i = 0; i < exportDir.numberOfNames; ++i) {
        ExportedFunction func;
        func.ordinal = static_cast<uint16_t>(exportDir.base + ordinals[i]);

        std::string name;
        if (readStringAt(nameRVAs[i], name)) {
            func.name = name;
        } else {
            continue;
        }

        // 使用序数索引在EAT中查找导出RVA
        if (ordinals[i] < exportDir.numberOfFunctions) {
            func.rva = functionRVAs[ordinals[i]];
        }

        exports.push_back(func);
    }

    return true;
}

std::string PEImportExportParser::calculateImpHash() {
    std::vector<ImportedDLL> imports;
    if (!parseImports(imports)) {
        return "";
    }

    // 1. 收集所有导入项，按"dll_lower.function_lower"拼接
    std::vector<std::string> importStrings;
    for (const auto& importedDLL : imports) {
        // 转小写DLL名
        std::string dllNameLower = importedDLL.name;
        std::transform(dllNameLower.begin(), dllNameLower.end(),
                      dllNameLower.begin(), ::tolower);

        for (const auto& func : importedDLL.functions) {
            // 转小写函数名
            std::string funcNameLower = func;
            std::transform(funcNameLower.begin(), funcNameLower.end(),
                          funcNameLower.begin(), ::tolower);

            std::string combined = dllNameLower + "." + funcNameLower;
            importStrings.push_back(combined);
        }
    }

    // 2. 按字母顺序排序（对ImpHash计算很重要）
    std::sort(importStrings.begin(), importStrings.end());

    // 3. 拼接所有字符串
    std::string combined;
    for (const auto& str : importStrings) {
        combined += str;
    }

    // 4. 计算dhash
    return computeDhash(combined);
}

bool PEImportExportParser::isValid() const {
    return isValid_;
}

std::string PEImportExportParser::getErrorMessage() const {
    return errorMessage_;
}

// ============================================================================
// 私有内部方法实现
// ============================================================================

bool PEImportExportParser::readExportDirectory(ExportDirectory& exportDir) {
    uint32_t offset = rvaToOffset(exportTableRVA_);
    if (offset == UINT32_MAX) {
        return false;
    }

    std::ifstream file(filePath_, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    file.seekg(offset);
    file.read(reinterpret_cast<char*>(&exportDir), sizeof(ExportDirectory));

    return file.good();
}

std::vector<PEImportExportParser::ImportDescriptor>
PEImportExportParser::readImportDescriptors() {
    std::vector<ImportDescriptor> descriptors;

    if (importTableRVA_ == 0) {
        return descriptors;
    }

    uint32_t offset = rvaToOffset(importTableRVA_);
    if (offset == UINT32_MAX) {
        return descriptors;
    }

    std::ifstream file(filePath_, std::ios::binary);
    if (!file.is_open()) {
        return descriptors;
    }

    file.seekg(offset);

    // 读取导入描述符数组，直到遇到全零结构
    while (true) {
        ImportDescriptor desc;
        file.read(reinterpret_cast<char*>(&desc), sizeof(ImportDescriptor));

        if (!file) {
            break;
        }

        // 检查是否为全零结构（结束标记）
        if (desc.originalFirstThunk == 0 &&
            desc.timeDateStamp == 0 &&
            desc.forwarderChain == 0 &&
            desc.name == 0 &&
            desc.firstThunk == 0) {
            break;
        }

        descriptors.push_back(desc);
    }

    return descriptors;
}

bool PEImportExportParser::readStringAt(uint32_t rva, std::string& out) {
    out.clear();

    uint32_t offset = rvaToOffset(rva);
    if (offset == UINT32_MAX) {
        return false;
    }

    std::ifstream file(filePath_, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    file.seekg(offset);

    // 逐字节读取直到遇到'\0'或达到最大长度
    const size_t MAX_STRING_LENGTH = 4096;
    char buffer[MAX_STRING_LENGTH + 1];

    for (size_t i = 0; i < MAX_STRING_LENGTH; ++i) {
        char c;
        file.get(c);
        if (!file || c == '\0') {
            buffer[i] = '\0';
            out = buffer;
            return true;
        }
        buffer[i] = c;
    }

    // 超出最大长度
    buffer[MAX_STRING_LENGTH] = '\0';
    out = buffer;
    return true;
}

uint32_t PEImportExportParser::rvaToOffset(uint32_t rva) const {
    // 遍历节表，找到包含该RVA的节
    for (const auto& section : sections_) {
        uint32_t sectionStart = section.virtualAddress;
        uint32_t sectionEnd = sectionStart + section.virtualSize;

        if (rva >= sectionStart && rva < sectionEnd) {
            // RVA在该节范围内，计算文件偏移
            uint32_t offsetInSection = rva - sectionStart;
            return section.pointerToRawData + offsetInSection;
        }
    }

    // RVA不在任何节范围内，返回UINT32_MAX表示失败
    return UINT32_MAX;
}

bool PEImportExportParser::readAtOffset(uint32_t offset, void* buffer, uint32_t size) const {
    if (offset == UINT32_MAX || buffer == nullptr || size == 0) {
        return false;
    }

    std::ifstream file(filePath_, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    file.seekg(offset);
    file.read(reinterpret_cast<char*>(buffer), size);

    return file.good() && static_cast<uint32_t>(file.gcount()) == size;
}

// ============================================================================
// 静态工具方法
// ============================================================================

std::string PEImportExportParser::computeDhash(const std::string& input) {
    if (input.empty()) {
        return "";
    }

    // ImpHash实现：计算导入字符串的16位dhash
    // 使用简化的dhash算法（基于ssdeep/TLSH风格）
    // 算法步骤：
    // 1. 初始化两个64位哈希变量 (B1=0x1505, B2=0x45d9f)
    // 2. 对每个字符，按窗口长度4进行滑动处理
    // 3. 最终取低32位并格式化为8位十六进制

    const uint64_t B1 = 0x1505;
    const uint64_t B2 = 0x45d9f;

    uint64_t h1 = B1;
    uint64_t h2 = B2;

    const size_t window = 4;
    size_t len = input.length();

    for (size_t i = 0; i < len; ++i) {
        // 窗口处理：每个字符影响多个位置
        for (size_t j = 0; j < window && (i + j) < len; ++j) {
            uint8_t c = static_cast<uint8_t>(input[i + j]);
            h1 = (h1 * B1) + c;
            h2 = (h2 * B2) + c;
        }
    }

    // 组合两个哈希并取低32位
    uint32_t result = static_cast<uint32_t>((h1 & 0xFFFFFFFF) ^ (h2 & 0xFFFFFFFF));

    // 返回8位小写十六进制
    std::ostringstream oss;
    oss << std::hex << std::setw(8) << std::setfill('0') << result;
    return oss.str();
}
