/**
 * @file DatabaseAnalyzer.h
 * @brief 数据库取证分析模块主头文件
 * 
 * 提供数据库文件/目录的取证分析功能，支持：
 * - SQLite数据库（完整分析）
 * - MySQL数据目录（元数据分析）
 * - PostgreSQL数据目录（元数据分析）
 * 
 * 采用策略模式设计，易于扩展新的数据库类型
 */

#pragma once

// 标准库
#include <string>
#include <vector>
#include <memory>
#include <functional>

// 模块头文件
#include "Common/DBDataTypes.h"
#include "Parsers/IDBParser.h"
#include "Parsers/DBParserFactory.h"
#include "Database/DBAnalysisDatabase.h"

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief 分析进度回调
 * @param phase 当前阶段描述
 * @param current 当前进度
 * @param total 总量（-1表示未知）
 */
using AnalysisProgressCallback = std::function<void(const std::string& phase, int64_t current, int64_t total)>;

/**
 * @class DatabaseAnalyzer
 * @brief 数据库取证分析器
 * 
 * 主入口类，提供统一的分析接口
 */
class DatabaseAnalyzer {
public:
    DatabaseAnalyzer();
    ~DatabaseAnalyzer();
    
    // 禁止拷贝
    DatabaseAnalyzer(const DatabaseAnalyzer&) = delete;
    DatabaseAnalyzer& operator=(const DatabaseAnalyzer&) = delete;
    
    /**
     * @brief 初始化分析器
     * @param outputDbPath 结果存储数据库路径
     * @return 成功返回true
     */
    bool initialize(const std::string& outputDbPath);
    
    /**
     * @brief 设置分析选项
     */
    void setOptions(const DBAnalysisOptions& options) { options_ = options; }
    
    /**
     * @brief 设置进度回调
     */
    void setProgressCallback(AnalysisProgressCallback callback) { progressCallback_ = callback; }
    
    // ========== 主分析入口 ==========
    
    /**
     * @brief 分析单个数据库文件或目录
     * @param path 文件或目录路径
     * @return 会话ID（失败返回-1）
     */
    int64_t analyze(const std::string& path);
    
    /**
     * @brief 分析指定类型的数据库
     * @param path 文件或目录路径
     * @param type 数据库类型
     * @return 会话ID（失败返回-1）
     */
    int64_t analyze(const std::string& path, DatabaseType type);
    
    /**
     * @brief 扫描目录中的所有数据库
     * @param directory 要扫描的目录
     * @param recursive 是否递归扫描子目录
     * @return 发现的数据库路径和类型
     */
    std::vector<std::pair<std::string, DatabaseType>> scanDirectory(
        const std::string& directory, 
        bool recursive = true);
    
    /**
     * @brief 批量分析目录中的所有数据库
     * @param directory 要扫描的目录
     * @param recursive 是否递归扫描
     * @return 成功分析的数量
     */
    int analyzeDirectory(const std::string& directory, bool recursive = true);
    
    // ========== 查询方法 ==========
    
    /**
     * @brief 获取所有分析会话
     */
    std::vector<DBAnalysisSummary> getAllSessions();
    
    /**
     * @brief 获取会话摘要
     */
    DBAnalysisSummary getSessionSummary(int64_t sessionId);
    
    /**
     * @brief 获取会话的表信息
     */
    std::vector<DBTableInfo> getTables(int64_t sessionId);
    
    /**
     * @brief 获取表的记录
     */
    std::vector<DBRecordInfo> getRecords(int64_t sessionId, const std::string& tableName, 
                                         int limit = -1, int offset = 0);
    
    /**
     * @brief 获取会话的工件
     */
    std::vector<DBArtifact> getArtifacts(int64_t sessionId);
    
    /**
     * @brief 获取会话的用户
     */
    std::vector<DBUserInfo> getUsers(int64_t sessionId);
    
    // ========== 工具方法 ==========
    
    /**
     * @brief 获取最后错误信息
     */
    std::string getLastError() const { return lastError_; }
    
    /**
     * @brief 检测文件/目录的数据库类型
     */
    static DatabaseType detectType(const std::string& path) {
        return DBParserFactory::detectType(path);
    }
    
    /**
     * @brief 获取支持的数据库类型列表
     */
    static std::vector<DatabaseType> getSupportedTypes() {
        return DBParserFactory::getRegisteredTypes();
    }

private:
    std::unique_ptr<DBAnalysisDatabase> resultDb_;
    DBAnalysisOptions options_;
    AnalysisProgressCallback progressCallback_;
    std::string lastError_;
    
    void setError(const std::string& error);
    void reportProgress(const std::string& phase, int64_t current, int64_t total);
    
    // 执行单个数据库分析
    int64_t doAnalyze(IDBParser* parser);
};

} // namespace Database
} // namespace ForensicAnalyzer
