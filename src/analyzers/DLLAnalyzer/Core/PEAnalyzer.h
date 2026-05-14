// PEAnalyzer.h
// PE文件分析引擎

#pragma once
#ifndef PE_ANALYZER_H
#define PE_ANALYZER_H

#include <string>
#include <vector>
#include <fstream>
#include <iomanip>
#include <sstream>
#include "../Common/DLLDataTypes.h"
#include "Parsers/PEHeaderParser.h"
#include "Parsers/PEImportExportParser.h"

namespace forensics {
namespace dll {

/**
 * @brief PE文件分析引擎
 *
 * 职责：
 *   - 计算文件哈希（MD5、SHA1、SHA256）
 *   - 解析PE文件头（PEHeaderParser）
 *   - 解析节表并计算熵值
 *   - 解析导入/导出表
 *   - 计算ImpHash（导入函数模糊哈希）
 *   - 提取版本信息（占位实现）
 *   - 验证数字签名（占位实现）
 *   - 汇总DLLAnalysisResult
 */
class PEAnalyzer {
public:
    PEAnalyzer();
    ~PEAnalyzer();

    // 禁止拷贝
    PEAnalyzer(const PEAnalyzer&) = delete;
    PEAnalyzer& operator=(const PEAnalyzer&) = delete;

    /**
     * @brief 分析PE文件，返回完整分析结果
     * @param filePath PE文件路径
     * @return DLLAnalysisResult 包含所有分析数据
     */
    DLLAnalysisResult analyze(const std::string& filePath);

    /**
     * @brief 计算文件MD5哈希
     * @param filePath 文件路径
     * @return 32字符小写十六进制MD5字符串，失败返回空字符串
     */
    static std::string calculateMD5(const std::string& filePath);

    /**
     * @brief 计算文件SHA1哈希
     * @param filePath 文件路径
     * @return 40字符小写十六进制SHA1字符串，失败返回空字符串
     */
    static std::string calculateSHA1(const std::string& filePath);

    /**
     * @brief 计算文件SHA256哈希
     * @param filePath 文件路径
     * @return 64字符小写十六进制SHA256字符串，失败返回空字符串
     */
    static std::string calculateSHA256(const std::string& filePath);

private:
    // =========================================================================
    // 子分析步骤
    // =========================================================================

    /**
     * @brief 解析PE文件头
     * @param filePath 文件路径
     * @return PEHeaderInfo 解析结果（isValid=false表示失败）
     */
    PEHeaderInfo parsePEHeader(const std::string& filePath);

    /**
     * @brief 解析节表并计算各节熵值
     * @param filePath 文件路径
     * @return PESectionInfo列表
     */
    std::vector<PESectionInfo> parseSections(const std::string& filePath);

    /**
     * @brief 解析导入表
     * @param filePath 文件路径
     * @return ImportedDLL列表
     */
    std::vector<ImportedDLL> parseImports(const std::string& filePath);

    /**
     * @brief 解析导出表
     * @param filePath 文件路径
     * @return ExportedFunction列表
     */
    std::vector<ExportedFunction> parseExports(const std::string& filePath);

    /**
     * @brief 从资源节提取版本信息
     * @param filePath 文件路径
     * @return 版本字符串（占位实现，当前返回"Unknown"）
     */
    std::string extractVersionInfo(const std::string& filePath);

    /**
     * @brief 验证PE文件数字签名
     * @param filePath 文件路径
     * @return 签名状态（占位实现，当前返回"Unsigned"）
     */
    std::string verifySignature(const std::string& filePath);

    /**
     * @brief 计算ImpHash（Import Hash / dhash）
     * @param filePath 文件路径
     * @return 16位小写十六进制ImpHash字符串，失败返回空字符串
     */
    std::string calculateImpHash(const std::string& filePath);

    /**
     * @brief 从PE头提取时间戳并填入结果
     * @param header 已解析的PE头信息
     * @param result 分析结果（将修改此结构体）
     */
    void extractTimestamps(const PEHeaderInfo& header, DLLAnalysisResult& result);
};

} // namespace dll
} // namespace forensics

#endif // PE_ANALYZER_H
