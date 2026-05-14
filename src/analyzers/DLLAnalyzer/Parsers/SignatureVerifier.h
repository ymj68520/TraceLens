// SignatureVerifier.h
// PE文件数字签名验证器（Authenticode）

#pragma once
#ifndef SIGNATURE_VERIFIER_H
#define SIGNATURE_VERIFIER_H

#include <string>
#include <vector>
#include <cstdint>

namespace forensics {
namespace dll {

/**
 * @brief 数字签名信息
 */
struct SignatureInfo {
    bool isSigned;           // 是否有签名
    bool isValid;            // 签名是否有效
    std::string status;      // "Signed", "Unsigned", "Invalid"
    std::string signerName;  // 签名者名称
    std::string issuerName;  // 颁发者名称
    std::string subjectName; // 证书主题
    std::string serialNumber;// 序列号
    std::string version;     // 版本信息
    uint64_t timestamp;      // 签名时间戳
    std::string algorithm;   // 签名算法
    std::vector<std::string> chain; // 证书链
};

/**
 * @brief PE文件数字签名验证器
 *
 * 职责：
 *   - 检测PE文件是否包含Authenticode签名
 *   - 提取签名证书信息
 *   - 验证证书链（基础验证）
 *   - 提取签名者信息
 *   - 返回签名状态和详细信息
 *
 * 实现策略：
 *   - 尝试使用osslsigncode库（跨平台）
 *   - 在Windows上可使用WinVerifyTrust API
 *   - 如果库不可用，回退到基本签名检测（检查Security目录）
 */
class SignatureVerifier {
public:
    SignatureVerifier();
    ~SignatureVerifier();

    // 禁止拷贝
    SignatureVerifier(const SignatureVerifier&) = delete;
    SignatureVerifier& operator=(const SignatureVerifier&) = delete;

    /**
     * @brief 验证PE文件数字签名
     * @param filePath PE文件路径
     * @return SignatureInfo 签名信息
     */
    SignatureInfo verify(const std::string& filePath);

    /**
     * @brief 检查PE文件是否有签名
     * @param filePath PE文件路径
     * @return true如果文件已签名
     */
    bool hasSignature(const std::string& filePath) const;

    /**
     * @brief 获取证书链
     * @param filePath PE文件路径
     * @return 证书链列表
     */
    std::vector<std::string> getCertificateChain(const std::string& filePath) const;

    /**
     * @brief 验证证书链（基础验证）
     * @param filePath PE文件路径
     * @return true如果证书链有效
     */
    bool verifyCertificateChain(const std::string& filePath) const;

private:
    /**
     * @brief 查找PE文件的安全目录
     * @param filePath PE文件路径
     * @param offset 输出偏移
     * @param size 输出大小
     * @return true如果找到
     */
    bool findSecurityDirectory(const std::string& filePath, uint32_t& offset, uint32_t& size) const;

    /**
     * @brief 解析签名数据（简化版）
     * @param filePath PE文件路径
     * @param sigInfo 输出签名信息
     * @return true如果解析成功
     */
    bool parseSignatureData(const std::string& filePath, SignatureInfo& sigInfo) const;

    /**
     * @brief 使用osslsigncode验证签名
     * @param filePath PE文件路径
     * @param sigInfo 输出签名信息
     * @return true如果验证成功
     */
    bool verifyWithOsslSigncode(const std::string& filePath, SignatureInfo& sigInfo) const;

    /**
     * @brief 从二进制数据提取证书信息
     * @param data 签名数据
     * @param sigInfo 输出签名信息
     * @return true如果提取成功
     */
    bool extractCertificateInfo(const std::vector<uint8_t>& data, SignatureInfo& sigInfo) const;

    /**
     * @brief 将Windows时间戳转换为Unix时间戳
     * @param windowsTimestamp Windows文件时间（100纳秒间隔自1601年1月1日）
     * @return Unix时间戳
     */
    uint64_t windowsTimestampToUnix(uint64_t windowsTimestamp) const;

    /**
     * @brief 检查osslsigncode是否可用
     * @return true如果可用
     */
    bool isOsslSigncodeAvailable() const;
};

} // namespace dll
} // namespace forensics

#endif // SIGNATURE_VERIFIER_H
