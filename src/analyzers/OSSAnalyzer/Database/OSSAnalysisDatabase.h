/**
 * @file OSSAnalysisDatabase.h
 * @brief OSS分析数据库操作类
 * 
 * 提供OSS对象、访问日志和Bucket信息的数据库存储和查询接口
 */

#pragma once

#include <string>
#include <vector>
#include <memory>
#include <sqlite3.h>

#include "../Common/OSSDataTypes.h"

namespace ForensicAnalyzer {
namespace OSS {

/**
 * @class OSSAnalysisDatabase
 * @brief OSS分析结果数据库操作类
 */
class OSSAnalysisDatabase {
public:
    explicit OSSAnalysisDatabase(const std::string& dbPath);
    ~OSSAnalysisDatabase();
    
    // 禁止拷贝
    OSSAnalysisDatabase(const OSSAnalysisDatabase&) = delete;
    OSSAnalysisDatabase& operator=(const OSSAnalysisDatabase&) = delete;
    
    /**
     * @brief 初始化数据库（创建表和索引）
     * @return 成功返回true
     */
    bool initialize();
    
    /**
     * @brief 关闭数据库连接
     */
    void close();
    
    // ========== 对象操作 ==========
    
    /**
     * @brief 插入或更新OSS对象信息
     * @param object 对象信息
     * @return 成功返回true
     */
    bool insertObject(const OSSObjectInfo& object);
    
    /**
     * @brief 批量插入对象
     * @param objects 对象列表
     * @return 成功插入的数量
     */
    int insertObjects(const std::vector<OSSObjectInfo>& objects);
    
    /**
     * @brief 获取所有对象
     * @return 对象列表
     */
    std::vector<OSSObjectInfo> getAllObjects();
    
    /**
     * @brief 按Bucket获取对象
     * @param bucket Bucket名称
     * @return 对象列表
     */
    std::vector<OSSObjectInfo> getObjectsByBucket(const std::string& bucket);
    
    /**
     * @brief 按前缀获取对象
     * @param bucket Bucket名称
     * @param prefix 对象键前缀
     * @return 对象列表
     */
    std::vector<OSSObjectInfo> getObjectsByPrefix(const std::string& bucket, const std::string& prefix);
    
    /**
     * @brief 按扩展名获取对象
     * @param extension 文件扩展名（如 ".jpg"）
     * @return 对象列表
     */
    std::vector<OSSObjectInfo> getObjectsByExtension(const std::string& extension);
    
    // ========== 访问日志操作 ==========
    
    /**
     * @brief 插入访问日志条目
     * @param logEntry 日志条目
     * @return 成功返回true
     */
    bool insertAccessLog(const OSSAccessLogEntry& logEntry);
    
    /**
     * @brief 批量插入访问日志
     * @param logEntries 日志条目列表
     * @return 成功插入的数量
     */
    int insertAccessLogs(const std::vector<OSSAccessLogEntry>& logEntries);
    
    /**
     * @brief 按时间范围获取访问日志
     * @param startTime 开始时间（Unix时间戳）
     * @param endTime 结束时间（Unix时间戳）
     * @return 日志条目列表
     */
    std::vector<OSSAccessLogEntry> getAccessLogsByTimeRange(int64_t startTime, int64_t endTime);
    
    /**
     * @brief 按操作类型获取访问日志
     * @param operation 操作类型（如 "GetObject"）
     * @return 日志条目列表
     */
    std::vector<OSSAccessLogEntry> getAccessLogsByOperation(const std::string& operation);
    
    /**
     * @brief 按对象键获取访问历史
     * @param objectKey 对象键
     * @return 日志条目列表
     */
    std::vector<OSSAccessLogEntry> getAccessLogsByObject(const std::string& objectKey);
    
    // ========== Bucket操作 ==========
    
    /**
     * @brief 插入或更新Bucket信息
     * @param bucket Bucket信息
     * @return 成功返回true
     */
    bool insertBucket(const OSSBucketInfo& bucket);
    
    /**
     * @brief 获取所有Bucket
     * @return Bucket列表
     */
    std::vector<OSSBucketInfo> getAllBuckets();
    
    // ========== 统计操作 ==========
    
    /**
     * @brief 获取分析摘要
     * @return 分析摘要
     */
    OSSAnalysisSummary getAnalysisSummary();
    
    /**
     * @brief 按存储类型统计对象
     * @return 存储类型 -> (数量, 大小) 映射
     */
    std::map<std::string, std::pair<int64_t, int64_t>> getObjectCountByStorageClass();
    
    /**
     * @brief 按扩展名统计对象
     * @return 扩展名 -> (数量, 大小) 映射
     */
    std::map<std::string, std::pair<int64_t, int64_t>> getObjectCountByExtension();
    
    /**
     * @brief 按操作类型统计访问日志
     * @return 操作类型 -> 数量 映射
     */
    std::map<std::string, int64_t> getOperationCounts();
    
    // ========== 事务操作 ==========
    
    /**
     * @brief 开始事务
     */
    void beginTransaction();
    
    /**
     * @brief 提交事务
     */
    void commitTransaction();
    
    /**
     * @brief 回滚事务
     */
    void rollbackTransaction();
    
    /**
     * @brief 获取数据库路径
     */
    const std::string& getDbPath() const { return dbPath_; }
    
private:
    std::string dbPath_;
    sqlite3* db_ = nullptr;
    
    bool executeSQL(const char* sql);
    OSSObjectInfo parseObjectRow(sqlite3_stmt* stmt);
    OSSAccessLogEntry parseAccessLogRow(sqlite3_stmt* stmt);
    OSSBucketInfo parseBucketRow(sqlite3_stmt* stmt);
};

} // namespace OSS
} // namespace ForensicAnalyzer
