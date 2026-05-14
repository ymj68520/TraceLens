// DLLAnalyzer.h
// DLL分析器主类 - 协调整个DLL分析流程

#pragma once
#ifndef DLL_ANALYZER_H
#define DLL_ANALYZER_H

#include <string>
#include <vector>
#include <memory>
#include "analyzers/DLLAnalyzer/Common/DLLAnalyzerDeclarations.h"
#include "analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.h"
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

/**
 * @brief DLL分析器主类
 *
 * 职责：
 *   - 协调整个DLL分析流程
 *   - 扫描DLL文件（从文件系统或数据库）
 *   - 调用PEAnalyzer、AnomalyDetector、DependencyAnalyzer
 *   - 将结果存入DLLAnalysisDatabase
 *   - 与WindowsFilesAnalyzer等模块数据关联
 */
class DLLAnalyzer {
public:
    /**
     * @brief 构造函数
     * @param outputDbPath 输出数据库路径
     */
    DLLAnalyzer(const std::string& outputDbPath);
    ~DLLAnalyzer();

    // 禁止拷贝
    DLLAnalyzer(const DLLAnalyzer&) = delete;
    DLLAnalyzer& operator=(const DLLAnalyzer&) = delete;

    /**
     * @brief 初始化分析器
     * @return true如果初始化成功
     */
    bool initialize();

    /**
     * @brief 执行DLL分析
     *
     * 分析流程：
     * 1. 扫描DLL文件
     * 2. 对每个DLL进行PE解析
     * 3. 计算哈希（MD5/SHA1/SHA256/ImpHash）
     * 4. 异常检测
     * 5. 依赖分析
     * 6. 存储到数据库
     */
    void analyze();

    // =========================================================================
    // 分析选项
    // =========================================================================

    /**
     * @brief 设置提取目录
     * @param dir 提取目录路径
     */
    void setExtractDirectory(const std::string& dir);

    /**
     * @brief 设置最大文件大小
     * @param maxSize 最大文件大小（字节）
     */
    void setMaxFileSize(size_t maxSize);

    /**
     * @brief 启用/禁用异常检测
     * @param enable true启用，false禁用
     */
    void enableAnomalyDetection(bool enable);

    /**
     * @brief 启用/禁用数字签名验证
     * @param enable true启用，false禁用
     */
    void enableSignatureVerification(bool enable);

    /**
     * @brief 获取分析统计信息
     * @return 统计信息结构体
     */
    struct AnalysisStats {
        size_t totalDLLsAnalyzed;
        size_t suspiciousDLLs;
        size_t signedDLLs;
        size_t unsignedDLLs;
        int averageThreatScore;
    };
    AnalysisStats getStats() const;

private:
    /**
     * @brief 扫描DLL文件
     * @return 扫描到的DLL文件路径列表
     */
    std::vector<std::string> scanDLLFiles();

    /**
     * @brief 分析单个DLL文件
     * @param dllPath DLL文件路径
     * @param inode 文件inode号
     * @return true如果分析成功
     */
    bool analyzeDLL(const std::string& dllPath, int64_t inode);

    /**
     * @brief 计算威胁评分
     * @param result DLL分析结果
     * @return 威胁评分（0-100）
     */
    int calculateThreatScore(const DLLAnalysisResult& result) const;

    /**
     * @brief 检查是否为可疑DLL（基于文件名和路径）
     * @param dllPath DLL路径
     * @return true如果可疑
     */
    bool isSuspiciousDLL(const std::string& dllPath) const;

    // DLL分析数据库
    std::unique_ptr<DLLAnalysisDatabase> dllDatabase_;

    // 分析组件
    std::unique_ptr<PEAnalyzer> peAnalyzer_;
    std::unique_ptr<AnomalyDetector> anomalyDetector_;
    std::unique_ptr<DependencyAnalyzer> dependencyAnalyzer_;

    // 分析选项
    bool enableAnomalyDetection_;
    bool enableSignatureVerification_;
    size_t maxFileSize_;
    std::string extractDirectory_;

    // 统计信息
    AnalysisStats stats_;
};

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYZER_H
