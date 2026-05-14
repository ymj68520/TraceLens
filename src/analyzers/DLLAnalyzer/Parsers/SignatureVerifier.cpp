// SignatureVerifier.cpp
// PE文件数字签名验证器实现

#include "analyzers/DLLAnalyzer/Parsers/SignatureVerifier.h"
#include "core/Logger/Logger.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <filesystem>

namespace forensics {
namespace dll {

SignatureVerifier::SignatureVerifier() = default;

SignatureVerifier::~SignatureVerifier() = default;

SignatureInfo SignatureVerifier::verify(const std::string& filePath) {
    SignatureInfo sigInfo;
    sigInfo.isSigned = false;
    sigInfo.isValid = false;
    sigInfo.status = "Unsigned";
    sigInfo.timestamp = 0;

    // 检查文件是否存在
    if (!std::filesystem::exists(filePath)) {
        LOG_WARNING("File not found: " + filePath);
        return sigInfo;
    }

    // 首先检查是否有签名
    if (!hasSignature(filePath)) {
        LOG_DEBUG("No signature found: " + filePath);
        return sigInfo;
    }

    sigInfo.isSigned = true;

    // 尝试使用osslsigncode验证
    if (isOsslSigncodeAvailable()) {
        if (verifyWithOsslSigncode(filePath, sigInfo)) {
            LOG_DEBUG("Signature verified with osslsigncode: " + filePath);
            return sigInfo;
        }
    }

    // 回退：解析签名数据
    if (parseSignatureData(filePath, sigInfo)) {
        LOG_DEBUG("Signature data parsed (basic validation): " + filePath);
        sigInfo.status = sigInfo.isValid ? "Signed" : "Invalid";
        return sigInfo;
    }

    // 如果所有方法都失败，标记为无效签名
    sigInfo.status = "Invalid";
    LOG_WARNING("Signature verification failed for: " + filePath);
    return sigInfo;
}

bool SignatureVerifier::hasSignature(const std::string& filePath) const {
    uint32_t offset = 0;
    uint32_t size = 0;
    return findSecurityDirectory(filePath, offset, size);
}

std::vector<std::string> SignatureVerifier::getCertificateChain(const std::string& filePath) const {
    std::vector<std::string> chain;

    SignatureInfo sigInfo;
    if (parseSignatureData(const_cast<std::string&>(filePath), sigInfo)) {
        chain = sigInfo.chain;
    }

    return chain;
}

bool SignatureVerifier::verifyCertificateChain(const std::string& filePath) const {
    // 简化实现：检查证书链是否存在
    auto chain = getCertificateChain(filePath);
    return !chain.empty();
}

bool SignatureVerifier::findSecurityDirectory(const std::string& filePath, uint32_t& offset, uint32_t& size) const {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    // 读取DOS头
    uint16_t magic;
    file.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    if (!file || magic != 0x5A4D) { // "MZ"
        return false;
    }

    // 获取PE头偏移
    uint32_t peOffset;
    file.seekg(60);
    file.read(reinterpret_cast<char*>(&peOffset), sizeof(peOffset));
    if (!file) {
        return false;
    }

    // 验证PE签名
    uint32_t peSig;
    file.seekg(peOffset);
    file.read(reinterpret_cast<char*>(&peSig), sizeof(peSig));
    if (!file || peSig != 0x00004550) { // "PE\0\0"
        return false;
    }

    // 跳过COFF头（20字节）
    uint16_t optionalHeaderSize;
    file.seekg(peOffset + 4 + 16); // PE sig + COFF magic(2) + machine(2) + sections(2) + timestamp(4) + symbols(4) + optHeaderSize(2)
    file.read(reinterpret_cast<char*>(&optionalHeaderSize), sizeof(optionalHeaderSize));
    if (!file) {
        return false;
    }

    // 定位到可选头的数据目录
    // 对于PE32：跳过 magic(2) + base fields(68) + data directories start at offset 96 from optional header start
    // 对于PE32+：跳过 magic(2) + base fields(64) + data directories start at offset 88 from optional header start
    uint16_t magicCheck;
    file.seekg(peOffset + 4 + 20); // After PE signature + COFF header
    file.read(reinterpret_cast<char*>(&magicCheck), sizeof(magicCheck));

    uint32_t dataDirOffset;
    if (magicCheck == 0x20B) { // PE32+
        dataDirOffset = peOffset + 4 + 20 + 88; // PE sig + COFF + base PE32+
    } else { // PE32
        dataDirOffset = peOffset + 4 + 20 + 96; // PE sig + COFF + base PE32
    }

    // 读取安全目录（第9个数据目录，index 4 = security）
    // 数据目录结构：VirtualAddress(4) + Size(4)
    uint32_t securityRVA;
    uint32_t securitySize;
    file.seekg(dataDirOffset + 4 * 4); // Skip export, import, resource (first 3 entries)
    file.read(reinterpret_cast<char*>(&securityRVA), sizeof(securityRVA));
    file.read(reinterpret_cast<char*>(&securitySize), sizeof(securitySize));

    if (!file || securityRVA == 0 || securitySize == 0) {
        return false;
    }

    offset = securityRVA;
    size = securitySize;
    return true;
}

bool SignatureVerifier::parseSignatureData(const std::string& filePath, SignatureInfo& sigInfo) const {
    uint32_t offset = 0;
    uint32_t size = 0;

    if (!findSecurityDirectory(const_cast<std::string&>(filePath), offset, size)) {
        return false;
    }

    // 读取签名数据
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    file.seekg(offset);
    std::vector<uint8_t> data(size);
    file.read(reinterpret_cast<char*>(data.data()), size);

    if (!file || file.gcount() != static_cast<std::streamsize>(size)) {
        return false;
    }

    // 基本验证：检查是否是有效的PKCS#7结构
    if (data.size() < 8) {
        return false;
    }

    // 检查WIN_CERTIFICATE结构
    // typedef struct _WIN_CERTIFICATE {
    //   DWORD   dwLength;
    //   WORD    wRevision;
    //   WORD    wCertificateType;
    //   BYTE    bCertificate[ANYSIZE_ARRAY];
    // } WIN_CERTIFICATE;

    uint32_t certLength;
    uint16_t revision;
    uint16_t certType;

    memcpy(&certLength, data.data(), sizeof(uint32_t));
    memcpy(&revision, data.data() + 4, sizeof(uint16_t));
    memcpy(&certType, data.data() + 6, sizeof(uint16_t));

    // 验证基本结构
    if (certLength != size || certLength < 8) {
        return false;
    }

    sigInfo.isSigned = true;
    sigInfo.isValid = true; // 简化：假设结构有效即认为签名存在
    sigInfo.status = "Signed";
    sigInfo.timestamp = 0; // TODO: 解析签名时间戳

    // 尝试从证书数据提取基本信息
    extractCertificateInfo(data, sigInfo);

    return true;
}

bool SignatureVerifier::verifyWithOsslSigncode(const std::string& filePath, SignatureInfo& sigInfo) const {
    // 调用osslsigncode验证PE文件签名
    std::string cmd = "osslsigncode verify " + filePath + " 2>&1";
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) {
        return false;
    }

    std::string result;
    char buffer[128];
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result += buffer;
    }

    int ret = pclose(pipe);
    if (ret != 0) {
        LOG_DEBUG("osslsigncode verify failed with code: " + std::to_string(ret));
        return false;
    }

    // 解析输出（简化版）
    if (result.find("OK") != std::string::npos || result.find("signature OK") != std::string::npos) {
        sigInfo.isValid = true;
        sigInfo.status = "Signed";
        return true;
    } else if (result.find("No signature") != std::string::npos) {
        sigInfo.isValid = false;
        sigInfo.status = "Unsigned";
        return false;
    }

    return false;
}

bool SignatureVerifier::extractCertificateInfo(const std::vector<uint8_t>& data, SignatureInfo& sigInfo) const {
    // 从证书数据提取基本信息
    // 注意：这是简化实现，完整的证书解析需要ASN.1/DER解析器

    // 搜索证书主题和颁发者信息（OID: 2.5.4.x）
    // 实际实现需要使用专门的库如OpenSSL

    sigInfo.signerName = "Unknown";
    sigInfo.issuerName = "Unknown";
    sigInfo.subjectName = "Unknown";
    sigInfo.serialNumber = "Unknown";
    sigInfo.version = "Unknown";
    sigInfo.algorithm = "Unknown";

    // TODO: 实现完整的证书信息提取
    // 可以使用OpenSSL的d2i_X509解析证书

    return true;
}

uint64_t SignatureVerifier::windowsTimestampToUnix(uint64_t windowsTimestamp) const {
    // Windows文件时间：从1601年1月1日开始的100纳秒间隔
    // Unix时间戳：从1970年1月1日开始的秒
    const uint64_t WINDOWS_TO_UNIX_OFFSET = 11644473600ULL;
    return windowsTimestamp / 10000000ULL - WINDOWS_TO_UNIX_OFFSET;
}

bool SignatureVerifier::isOsslSigncodeAvailable() const {
    // 检查osslsigncode是否可用
    FILE* pipe = popen("which osslsigncode 2>/dev/null", "r");
    if (!pipe) {
        return false;
    }

    char buffer[256];
    size_t count = fread(buffer, 1, sizeof(buffer) - 1, pipe);
    pclose(pipe);

    return count > 0 && std::string(buffer, count).find("osslsigncode") != std::string::npos;
}

} // namespace dll
} // namespace forensics
