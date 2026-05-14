// PEAnalyzer.cpp
// PE文件分析引擎实现

#include "PEAnalyzer.h"
#include "Parsers/PEHeaderParser.h"
#include "Parsers/PEImportExportParser.h"
#include <openssl/md5.h>
#include <openssl/sha.h>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <cstdint>

using namespace forensics::dll;

// ============================================================================
// 构造 / 析构
// ============================================================================

PEAnalyzer::PEAnalyzer() = default;

PEAnalyzer::~PEAnalyzer() = default;

// ============================================================================
// 主入口：分析PE文件
// ============================================================================

DLLAnalysisResult PEAnalyzer::analyze(const std::string& filePath) {
    DLLAnalysisResult result{};
    result.filePath = filePath;
    result.fileName = std::filesystem::path(filePath).filename().string();

    // 获取文件大小
    try {
        result.fileSize = static_cast<uint64_t>(std::filesystem::file_size(filePath));
    } catch (...) {
        result.fileSize = 0;
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
    // TODO：从.rsrc节提取版本信息
    // 当前返回占位符，后续任务将实现VS_VERSIONINFO解析
    (void)filePath;
    return "Unknown";
}

std::string PEAnalyzer::verifySignature(const std::string& filePath) {
    // TODO：验证PE数字签名（Authenticode）
    // 当前返回占位符，后续任务将实现证书链验证
    (void)filePath;
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
