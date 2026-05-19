// DLLAnalyzer.h
// DLL分析器主类 - 协调整个DLL分析流程

#pragma once
#ifndef DLL_ANALYZER_H
#define DLL_ANALYZER_H

#include <string>
#include <vector>
#include <memory>
#include <unordered_set>
#include <mutex>
#include "analyzers/DLLAnalyzer/Common/DLLAnalyzerDeclarations.h"
#include "analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.h"
#include "analyzers/DLLAnalyzer/Core/DependencyAnalyzer.h"
#include "analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h"

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

    /**
     * @brief 分析单个DLL文件（公开接口，用于按需分析）
     * @param dllPath DLL文件路径
     * @param inode 文件inode号
     * @return true如果分析成功
     */
    bool analyzeSingleFile(const std::string& dllPath, int64_t inode = 0);

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
     * @brief 检查是否为已分析的DLL（用于增量分析）
     * @param dllPath DLL路径
     * @param inode 文件inode
     * @return true如果已分析过
     */
    bool isAlreadyAnalyzed(const std::string& dllPath, int64_t inode) const;

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

    /**
     * @brief Get pointer to the analysis database
     * @return Raw pointer to DLLAnalysisDatabase
     */
    DLLAnalysisDatabase* getDatabase() const { return dllDatabase_.get(); }

    /**
     * @brief 设置 Windows 取证数据库（用于取证关联）
     * @param windowsDb Windows 取证数据库指针（只读）
     */
    void setWindowsDatabase(const WindowsAnalysisDatabase* windowsDb);

private:
    /**
     * @brief 扫描DLL文件
     * @return 扫描到的DLL文件路径列表
     */
    std::vector<std::string> scanDLLFiles();

    /**
     * @brief 扫描单个目录中的DLL文件（辅助方法）
     * @param dirPath 目录路径
     * @return DLL文件列表
     */
    std::vector<std::string> scanDirectoryParallel(const std::string& dirPath);

    /**
     * @brief 检查DLL是否在白名单中
     * @param dllPath DLL路径
     * @return true如果在白名单中
     */
    bool isWhitelistedDLL(const std::string& dllPath) const;

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

    // Windows 取证数据库（只读，用于取证关联）
    const WindowsAnalysisDatabase* windowsDb_{nullptr};

    // 分析选项
    bool enableAnomalyDetection_;
    bool enableSignatureVerification_;
    size_t maxFileSize_;
    std::string extractDirectory_;

    // 性能优化：系统DLL白名单
    static const std::unordered_set<std::string> SYSTEM_DLL_NAMES_;
    static const std::unordered_set<std::string> SYSTEM_DIRECTORIES_;

    // 统计信息
    AnalysisStats stats_;
    mutable std::mutex statsMutex_;  // 保护stats_的互斥锁
};

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYZER_H
