// PEAnalyzer.cpp
// PE文件分析引擎实现

#include "PEAnalyzer.h"
#include "Parsers/PEHeaderParser.h"
#include "Parsers/PEImportExportParser.h"
#include <openssl/md5.h>
#include <openssl/sha.h>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <cstdint>
#include <sys/stat.h>

#ifdef __linux__
#include <unistd.h>
#endif

namespace forensics {
namespace dll {

// ============================================================================
// 构造 / 析构
// ============================================================================

PEAnalyzer::PEAnalyzer()
    : signatureVerifier_(std::make_unique<SignatureVerifier>()) {
}

PEAnalyzer::~PEAnalyzer() = default;

// ============================================================================
// 主入口：分析PE文件
// ============================================================================

DLLAnalysisResult PEAnalyzer::analyze(const std::string& filePath) {
    DLLAnalysisResult result{};
    result.filePath = filePath;
    result.fileName = std::filesystem::path(filePath).filename().string();

    // 获取文件大小和时间戳（C++17兼容实现）
    try {
        result.fileSize = static_cast<uint64_t>(std::filesystem::file_size(filePath));

        // 使用stat获取文件时间戳（跨平台C++17兼容）
        struct stat fileStat{};
        if (stat(filePath.c_str(), &fileStat) == 0) {
            result.mtime = static_cast<int64_t>(fileStat.st_mtime);  // 修改时间
            result.ctime = static_cast<int64_t>(fileStat.st_ctime);  // 元数据变更时间
            result.atime = static_cast<int64_t>(fileStat.st_atime);  // 访问时间
            result.crtime = result.ctime; // Linux st_ctime是元数据变更时间，作为创建时间近似
        } else {
            result.mtime = result.ctime = result.atime = result.crtime = 0;
        }
    } catch (...) {
        result.fileSize = 0;
        result.mtime = result.ctime = result.atime = result.crtime = 0;
    }

    // 1. 计算哈希（对任何文件都执行，无论是否为有效PE）
    result.md5Hash = calculateMD5(filePath);
    result.sha1Hash = calculateSHA1(filePath);
    result.sha256Hash = calculateSHA256(filePath);

    // 2. 解析PE头
    result.peHeader = parsePEHeader(filePath);
    if (!result.peHeader.isValid) {
        // PE头无效时，占位字段设为默认值后立即返回
        result.fileVersion = "Unknown";
        result.signatureStatus = "Unsigned";
        return result;
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

// ============================================================================
// 哈希计算（静态方法）
// ============================================================================

std::string PEAnalyzer::calculateMD5(const std::string& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return "";
    }

    MD5_CTX ctx;
    MD5_Init(&ctx);

    constexpr size_t BUFFER_SIZE = 8192;
    std::vector<uint8_t> buffer(BUFFER_SIZE);

    while (file) {
        file.read(reinterpret_cast<char*>(buffer.data()), BUFFER_SIZE);
        std::streamsize bytesRead = file.gcount();
        if (bytesRead > 0) {
            MD5_Update(&ctx, buffer.data(), static_cast<size_t>(bytesRead));
        }
    }

    uint8_t digest[MD5_DIGEST_LENGTH];
    MD5_Final(digest, &ctx);

    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (int i = 0; i < MD5_DIGEST_LENGTH; ++i) {
        oss << std::setw(2) << static_cast<int>(digest[i]);
    }
    return oss.str();
}

std::string PEAnalyzer::calculateSHA1(const std::string& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return "";
    }

    SHA_CTX ctx;
    SHA1_Init(&ctx);

    constexpr size_t BUFFER_SIZE = 8192;
    std::vector<uint8_t> buffer(BUFFER_SIZE);

    while (file) {
        file.read(reinterpret_cast<char*>(buffer.data()), BUFFER_SIZE);
        std::streamsize bytesRead = file.gcount();
        if (bytesRead > 0) {
            SHA1_Update(&ctx, buffer.data(), static_cast<size_t>(bytesRead));
        }
    }

    uint8_t digest[SHA_DIGEST_LENGTH];
    SHA1_Final(digest, &ctx);

    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (int i = 0; i < SHA_DIGEST_LENGTH; ++i) {
        oss << std::setw(2) << static_cast<int>(digest[i]);
    }
    return oss.str();
}

std::string PEAnalyzer::calculateSHA256(const std::string& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return "";
    }

    SHA256_CTX ctx;
    SHA256_Init(&ctx);

    constexpr size_t BUFFER_SIZE = 8192;
    std::vector<uint8_t> buffer(BUFFER_SIZE);

    while (file) {
        file.read(reinterpret_cast<char*>(buffer.data()), BUFFER_SIZE);
        std::streamsize bytesRead = file.gcount();
        if (bytesRead > 0) {
            SHA256_Update(&ctx, buffer.data(), static_cast<size_t>(bytesRead));
        }
    }

    uint8_t digest[SHA256_DIGEST_LENGTH];
    SHA256_Final(digest, &ctx);

    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (int i = 0; i < SHA256_DIGEST_LENGTH; ++i) {
        oss << std::setw(2) << static_cast<int>(digest[i]);
    }
    return oss.str();
}

// ============================================================================
// 子分析步骤实现
// ============================================================================

PEHeaderInfo PEAnalyzer::parsePEHeader(const std::string& filePath) {
    PEHeaderParser parser(filePath);
    parser.parse();
    return parser.getHeaderInfo();
}

std::vector<PESectionInfo> PEAnalyzer::parseSections(const std::string& filePath) {
    PEHeaderParser parser(filePath);
    if (!parser.parse()) {
        return {};
    }
    return parser.getHeaderInfo().sections;
}

std::vector<ImportedDLL> PEAnalyzer::parseImports(const std::string& filePath) {
    PEImportExportParser parser(filePath);
    std::vector<ImportedDLL> imports;
    parser.parseImports(imports);
    return imports;
}

std::vector<ExportedFunction> PEAnalyzer::parseExports(const std::string& filePath) {
    PEImportExportParser parser(filePath);
    std::vector<ExportedFunction> exports;
    parser.parseExports(exports);
    return exports;
}

std::string PEAnalyzer::extractVersionInfo(const std::string& filePath) {
    // 从.rsrc节提取版本信息
    // 实现：解析VS_VERSIONINFO资源结构

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return "Unknown";
    }

    // 首先使用PEHeaderParser获取.rsrc节信息
    PEHeaderParser headerParser(filePath);
    if (!headerParser.parse()) {
        return "Unknown";
    }

    const PEHeaderInfo& headerInfo = headerParser.getHeaderInfo();

    // 查找.rsrc节
    const PESectionInfo* rsrcSection = nullptr;
    for (const auto& section : headerInfo.sections) {
        std::string sectionName = section.name;
        // 节名可能是".rsrc"或截断为8字节的".rsrc\0\0"
        if (sectionName.rfind(".rsrc", 0) == 0) {
            rsrcSection = &section;
            break;
        }
    }

    if (!rsrcSection || rsrcSection->rawDataSize == 0) {
        return "Unknown";
    }

    // 读取.rsrc节数据
    std::vector<uint8_t> rsrcData(rsrcSection->rawDataSize);
    file.seekg(rsrcSection->pointerToRawData);
    file.read(reinterpret_cast<char*>(rsrcData.data()), rsrcSection->rawDataSize);

    if (!file || file.gcount() != static_cast<std::streamsize>(rsrcSection->rawDataSize)) {
        return "Unknown";
    }

    // 解析资源目录树查找VS_VERSION_INFO
    // 资源目录结构：
    // - 资源目录表（Resource Directory Table）
    // - 资源目录项（Resource Directory Entries）
    // - 资源数据入口（Resource Data Entry）

    // 简化实现：直接搜索"VS_VERSION_INFO"字符串
    const char* vsVersionKey = "VS_VERSION_INFO";
    const size_t keyLen = strlen(vsVersionKey);

    // 在.rsrc数据中搜索版本信息结构
    for (size_t i = 0; i < rsrcData.size() - keyLen; ++i) {
        bool found = true;
        for (size_t j = 0; j < keyLen; ++j) {
            if (rsrcData[i + j] != static_cast<uint8_t>(vsVersionKey[j])) {
                found = false;
                break;
            }
        }

        if (found) {
            // 找到VS_VERSION_INFO，尝试提取版本信息
            // VS_VERSIONINFO结构：
            // WORD wLength
            // WORD wValueLength
            // WORD wType
            // WCHAR szKey[]

            if (i + 6 > rsrcData.size()) {
                continue;
            }

            uint16_t wLength = *reinterpret_cast<const uint16_t*>(&rsrcData[i]);
            uint16_t wValueLength = *reinterpret_cast<const uint16_t*>(&rsrcData[i + 2]);
            uint16_t wType = *reinterpret_cast<const uint16_t*>(&rsrcData[i + 4]);

            if (wLength < 6 || wLength > rsrcData.size() - i) {
                continue;
            }

            // 检查是否有FixedFileInfo
            if (wValueLength >= sizeof(VS_FIXEDFILEINFO)) {
                size_t valueOffset = i + 6 + ((keyLen + 3) & ~3); // 对齐到32位边界
                if (valueOffset + sizeof(VS_FIXEDFILEINFO) <= i + wLength) {
                    const VS_FIXEDFILEINFO* fixedInfo =
                        reinterpret_cast<const VS_FIXEDFILEINFO*>(&rsrcData[valueOffset]);

                    // 验证签名
                    if (fixedInfo->dwSignature == 0xFEEF04BD) {
                        // 提取版本号
                        uint32_t versionMS = fixedInfo->dwFileVersionMS;
                        uint32_t versionLS = fixedInfo->dwFileVersionLS;

                        int major = (versionMS >> 16) & 0xFFFF;
                        int minor = versionMS & 0xFFFF;
                        int build = (versionLS >> 16) & 0xFFFF;
                        int revision = versionLS & 0xFFFF;

                        char versionBuf[64];
                        snprintf(versionBuf, sizeof(versionBuf), "%d.%d.%d.%d",
                                major, minor, build, revision);

                        std::string version = versionBuf;
                        // 如果版本是0.0.0.0，可能是占位符，继续查找字符串信息
                        if (major != 0 || minor != 0 || build != 0 || revision != 0) {
                            return version;
                        }
                    }
                }
            }

            // 如果FixedFileInfo没有提供有用信息，尝试解析StringFileInfo
            // StringFileInfo包含字符串化的版本信息
            // 继续搜索StringFileInfo块
            // （这是一个简化实现，完整实现需要递归解析资源目录）
        }
    }

    return "Unknown";
}

std::string PEAnalyzer::verifySignature(const std::string& filePath) {
    if (signatureVerifier_) {
        SignatureInfo sigInfo = signatureVerifier_->verify(filePath);
        if (sigInfo.isSigned) {
            return sigInfo.isValid ? "Signed" : "Invalid";
        }
    }
    return "Unsigned";
}

std::string PEAnalyzer::calculateImpHash(const std::string& filePath) {
    PEImportExportParser parser(filePath);
    return parser.calculateImpHash();
}

void PEAnalyzer::extractTimestamps(const PEHeaderInfo& header,
                                    DLLAnalysisResult& result) {
    // 从PE头提取编译时间戳
    if (header.isValid) {
        result.peHeader.timestamp = header.timestamp;
    }
}

} // namespace dll
} // namespace forensics
