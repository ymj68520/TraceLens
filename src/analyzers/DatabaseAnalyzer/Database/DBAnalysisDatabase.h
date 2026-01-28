/**
 * @file DBAnalysisDatabase.h
 * @brief 数据库分析结果存储模块
 * 
 * 将分析结果持久化到SQLite数据库
 */

#pragma once

#include "Common/DBDataTypes.h"
#include <sqlite3.h>
#include <string>
#include <vector>

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief 数据库分析结果存储
 * 
 * 使用SQLite存储分析结果，支持：
 * - 表结构信息
 * - 提取的记录
 * - 取证工件
 * - 用户信息
 */
class DBAnalysisDatabase {
public:
    /**
     * @brief 构造函数
     * @param dbPath 数据库文件路径
     */
    explicit DBAnalysisDatabase(const std::string& dbPath);
    ~DBAnalysisDatabase();
    
    // 禁止拷贝
    DBAnalysisDatabase(const DBAnalysisDatabase&) = delete;
    DBAnalysisDatabase& operator=(const DBAnalysisDatabase&) = delete;
    
    /**
     * @brief 初始化数据库（创建表）
     */
    bool initialize();
    
    /**
     * @brief 获取数据库路径
     */
    std::string getDbPath() const { return dbPath_; }
    
    // ========== 分析会话 ==========
    
    /**
     * @brief 开始新的分析会话
     * @param sourcePath 源数据库路径
     * @param type 数据库类型
     * @return 会话ID
     */
    int64_t beginSession(const std::string& sourcePath, DatabaseType type);
    
    /**
     * @brief 结束分析会话
     * @param sessionId 会话ID
     * @param summary 分析摘要
     */
    bool endSession(int64_t sessionId, const DBAnalysisSummary& summary);
    
    // ========== 表信息 ==========
    
    /**
     * @brief 插入表信息
     */
    bool insertTable(int64_t sessionId, const DBTableInfo& table);
    
    /**
     * @brief 批量插入表信息
     */
    int insertTables(int64_t sessionId, const std::vector<DBTableInfo>& tables);
    
    /**
     * @brief 获取会话的所有表
     */
    std::vector<DBTableInfo> getTables(int64_t sessionId);
    
    // ========== 记录 ==========
    
    /**
     * @brief 插入记录
     */
    bool insertRecord(int64_t sessionId, const DBRecordInfo& record);
    
    /**
     * @brief 批量插入记录
     */
    int insertRecords(int64_t sessionId, const std::vector<DBRecordInfo>& records);
    
    /**
     * @brief 获取表的记录
     */
    std::vector<DBRecordInfo> getRecords(int64_t sessionId, const std::string& tableName, 
                                         int limit = -1, int offset = 0);
    
    // ========== 工件 ==========
    
    /**
     * @brief 插入工件
     */
    bool insertArtifact(int64_t sessionId, const DBArtifact& artifact);
    
    /**
     * @brief 批量插入工件
     */
    int insertArtifacts(int64_t sessionId, const std::vector<DBArtifact>& artifacts);
    
    /**
     * @brief 获取所有工件
     */
    std::vector<DBArtifact> getArtifacts(int64_t sessionId);
    
    /**
     * @brief 按类型获取工件
     */
    std::vector<DBArtifact> getArtifactsByType(int64_t sessionId, ArtifactType type);
    
    // ========== 用户 ==========
    
    /**
     * @brief 插入用户信息
     */
    bool insertUser(int64_t sessionId, const DBUserInfo& user);
    
    /**
     * @brief 获取所有用户
     */
    std::vector<DBUserInfo> getUsers(int64_t sessionId);
    
    // ========== 查询 ==========
    
    /**
     * @brief 获取所有分析会话
     */
    std::vector<DBAnalysisSummary> getAllSessions();
    
    /**
     * @brief 获取会话摘要
     */
    DBAnalysisSummary getSessionSummary(int64_t sessionId);
    
    // ========== 事务 ==========
    
    bool beginTransaction();
    bool commit();
    bool rollback();
    
    // ========== 错误处理 ==========
    
    std::string getLastError() const { return lastError_; }

private:
    std::string dbPath_;
    sqlite3* db_ = nullptr;
    std::string lastError_;
    
    bool createTables();
    void setError(const std::string& error);
    
    // JSON序列化辅助
    std::string mapToJson(const std::map<std::string, std::string>& m);
    std::map<std::string, std::string> jsonToMap(const std::string& json);
    std::string vectorToJson(const std::vector<std::string>& v);
    std::vector<std::string> jsonToVector(const std::string& json);
};

} // namespace Database
} // namespace ForensicAnalyzer
