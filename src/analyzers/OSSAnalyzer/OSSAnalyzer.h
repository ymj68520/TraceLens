/**
 * @file OSSAnalyzer.h
 * @brief OSS分析器主头文件
 * 
 * 包含所有OSS分析模块需要的头文件和主类定义
 */

#pragma once

// 标准库
#include <string>
#include <vector>
#include <memory>
#include <functional>

// 项目头文件
#include "DatabaseManager/DatabaseManager.h"

// 模块头文件
#include "Common/OSSDataTypes.h"
#include "Common/OSSExportTypes.h"
#include "Database/OSSAnalysisDatabase.h"
#include "Client/OSSClient.h"

namespace ForensicAnalyzer {
namespace OSS {

/**
 * @brief 分析进度回调
 * @param phase 当前阶段描述
 * @param current 当前进度
 * @param total 总量（-1表示未知）
 */
using AnalysisProgressCallback = std::function<void(const std::string& phase, int64_t current, int64_t total)>;

/**
 * @class OSSAnalyzer
 * @brief 阿里云OSS分析器
 * 
 * 提供多种方式分析阿里云OSS数据：
 * - 直接API分析（实时连接）
 * - 本地目录分析（离线）
 * - Inventory清单分析
 * - 访问日志分析
 */
class OSSAnalyzer {
public:
    OSSAnalyzer();
    OSSAnalyzer(const OSSConnectionConfig& config, DatabaseManager* dbManager);
    ~OSSAnalyzer();
    
    // 禁止拷贝
    OSSAnalyzer(const OSSAnalyzer&) = delete;
    OSSAnalyzer& operator=(const OSSAnalyzer&) = delete;
    
    /**
     * @brief 初始化分析器
     * @return 成功返回true
     */
    bool initialize();
    
    /**
     * @brief 设置输出数据库路径
     * @param path 数据库文件路径
     */
    void setOutputDbPath(const std::string& path) { outputDbPath_ = path; }
    
    /**
     * @brief 设置进度回调
     * @param callback 进度回调函数
     */
    void setProgressCallback(AnalysisProgressCallback callback) { progressCallback_ = callback; }
    
    // ========== 主分析入口 ==========
    
    /**
     * @brief 执行OSS数据分析
     * 
     * 根据配置自动选择分析方式
     */
    void analyzeOSSData();
    
    /**
     * @brief 通过API直接分析OSS Bucket
     * @param bucketName Bucket名称（默认使用配置中的Bucket）
     * @param prefix 对象前缀筛选（可选）
     * @return 成功返回true
     */
    bool analyzeFromAPI(const std::string& bucketName = "", const std::string& prefix = "");
    
    /**
     * @brief 分析本地目录（OSS导出）
     * @param localDir 本地目录路径
     * @param bucketName 虚拟Bucket名称（用于数据库记录）
     * @return 成功返回true
     */
    bool analyzeFromLocalDirectory(const std::string& localDir, const std::string& bucketName = "local");
    
    /**
     * @brief 分析OSS Inventory清单文件
     * @param csvPath CSV清单文件路径
     * @return 成功返回true
     */
    bool analyzeFromInventory(const std::string& csvPath);
    
    /**
     * @brief 分析OSS访问日志
     * @param logPath 日志文件或目录路径
     * @return 成功返回true
     */
    bool analyzeAccessLogs(const std::string& logPath);
    
    /**
     * @brief 从OSS获取并分析访问日志
     * @param bucketName 要分析的Bucket
     * @param startTime 开始时间（可选）
     * @param endTime 结束时间（可选）
     * @return 成功返回true
     */
    bool fetchAndAnalyzeAccessLogs(
        const std::string& bucketName,
        int64_t startTime = 0,
        int64_t endTime = 0
    );
    
    // ========== 查询方法 ==========
    
    /**
     * @brief 获取所有分析的对象
     */
    std::vector<OSSObjectInfo> getAllObjects();
    
    /**
     * @brief 按Bucket获取对象
     */
    std::vector<OSSObjectInfo> getObjectsByBucket(const std::string& bucket);
    
    /**
     * @brief 按扩展名获取对象
     */
    std::vector<OSSObjectInfo> getObjectsByExtension(const std::string& extension);
    
    /**
     * @brief 获取访问日志
     */
    std::vector<OSSAccessLogEntry> getAccessLogs(int64_t startTime = 0, int64_t endTime = 0);
    
    /**
     * @brief 获取分析摘要
     */
    OSSAnalysisSummary getAnalysisSummary();
    
    // ========== 工具方法 ==========
    
    /**
     * @brief 获取最后错误信息
     */
    std::string getLastError() const { return lastError_; }
    
    /**
     * @brief 获取数据库路径
     */
    std::string getDbPath() const { return ossDb_ ? ossDb_->getDbPath() : ""; }
    
private:
    OSSConnectionConfig config_;
    DatabaseManager* dbManager_ = nullptr;
    std::string outputDbPath_;
    std::string lastError_;
    
    std::unique_ptr<OSSClient> client_;
    std::unique_ptr<OSSAnalysisDatabase> ossDb_;
    
    AnalysisProgressCallback progressCallback_;
    
    void setError(const std::string& error);
    void reportProgress(const std::string& phase, int64_t current, int64_t total);
    
    // 内部分析方法
    bool parseLocalDirectory(const std::string& dir, const std::string& bucket, const std::string& prefix = "");
    bool parseInventoryCSV(const std::string& csvPath);
    bool parseAccessLogFile(const std::string& logPath);
    OSSAccessLogEntry parseAccessLogLine(const std::string& line);
    
    // 从文件元数据创建对象信息
    OSSObjectInfo createObjectInfoFromFile(const std::string& filePath, const std::string& bucket, const std::string& relativePath);
};

} // namespace OSS
} // namespace ForensicAnalyzer
