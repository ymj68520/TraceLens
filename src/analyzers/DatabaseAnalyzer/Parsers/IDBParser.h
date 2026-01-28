/**
 * @file IDBParser.h
 * @brief 数据库解析器抽象接口
 * 
 * 定义所有数据库解析器必须实现的接口，遵循策略模式
 * 便于扩展新的数据库类型支持
 */

#pragma once

#include <string>
#include <vector>
#include <memory>
#include <functional>

#include "Common/DBDataTypes.h"

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief 解析进度回调
 * @param phase 当前阶段
 * @param current 当前进度
 * @param total 总量（-1表示未知）
 */
using ParseProgressCallback = std::function<void(const std::string& phase, int64_t current, int64_t total)>;

/**
 * @brief 数据库解析器抽象接口
 * 
 * 所有数据库类型的解析器都必须实现此接口
 * 使用策略模式，便于添加新的数据库类型支持
 */
class IDBParser {
public:
    virtual ~IDBParser() = default;
    
    // ========== 生命周期管理 ==========
    
    /**
     * @brief 打开数据库文件或数据目录
     * @param path 文件路径或目录路径
     * @return 成功返回true
     */
    virtual bool open(const std::string& path) = 0;
    
    /**
     * @brief 使用连接配置打开数据库（用于未来直接连接）
     * @param config 连接配置
     * @return 成功返回true
     * @note 默认实现返回false，子类可按需实现
     */
    virtual bool connect(const DBConnectionConfig& config) {
        (void)config;
        lastError_ = "Direct connection not supported for this database type";
        return false;
    }
    
    /**
     * @brief 关闭数据库
     */
    virtual void close() = 0;
    
    /**
     * @brief 检查是否已打开
     */
    virtual bool isOpen() const = 0;
    
    // ========== 基本信息 ==========
    
    /**
     * @brief 获取数据库类型
     */
    virtual DatabaseType getType() const = 0;
    
    /**
     * @brief 获取数据库类型名称
     */
    virtual std::string getTypeName() const {
        return databaseTypeToString(getType());
    }
    
    /**
     * @brief 获取数据库版本
     */
    virtual std::string getVersion() const = 0;
    
    /**
     * @brief 获取数据库文件路径
     */
    virtual std::string getPath() const = 0;
    
    /**
     * @brief 获取数据库文件大小
     */
    virtual int64_t getFileSize() const = 0;
    
    // ========== Schema分析 ==========
    
    /**
     * @brief 获取所有表信息
     */
    virtual std::vector<DBTableInfo> getTables() = 0;
    
    /**
     * @brief 获取指定表信息
     * @param tableName 表名
     */
    virtual DBTableInfo getTableInfo(const std::string& tableName) = 0;
    
    /**
     * @brief 获取所有索引信息
     */
    virtual std::vector<DBIndexInfo> getIndexes() {
        std::vector<DBIndexInfo> allIndexes;
        for (const auto& table : getTables()) {
            allIndexes.insert(allIndexes.end(), 
                table.indexes.begin(), table.indexes.end());
        }
        return allIndexes;
    }
    
    // ========== 数据提取 ==========
    
    /**
     * @brief 获取表中的记录
     * @param tableName 表名
     * @param limit 最大记录数（-1表示无限制）
     * @param offset 起始偏移
     */
    virtual std::vector<DBRecordInfo> getRecords(
        const std::string& tableName, 
        int limit = -1,
        int offset = 0) = 0;
    
    /**
     * @brief 使用SQL查询获取记录（仅支持部分数据库）
     * @param query SQL查询语句
     * @return 查询结果
     * @note 默认实现返回空结果
     */
    virtual std::vector<DBRecordInfo> executeQuery(const std::string& query) {
        (void)query;
        return {};
    }
    
    // ========== 取证分析 ==========
    
    /**
     * @brief 提取取证工件（删除记录、WAL等）
     * @param options 分析选项
     */
    virtual std::vector<DBArtifact> extractArtifacts(
        const DBAnalysisOptions& options = DBAnalysisOptions()) = 0;
    
    /**
     * @brief 尝试恢复已删除的记录
     * @param maxRecords 最大恢复记录数
     */
    virtual std::vector<DBRecordInfo> recoverDeletedRecords(int maxRecords = 10000) {
        (void)maxRecords;
        return {};  // 默认不支持
    }
    
    /**
     * @brief 获取用户账户信息
     */
    virtual std::vector<DBUserInfo> getUsers() {
        return {};  // 默认不支持
    }
    
    // ========== 分析统计 ==========
    
    /**
     * @brief 获取分析摘要
     */
    virtual DBAnalysisSummary getAnalysisSummary() = 0;
    
    // ========== 回调设置 ==========
    
    /**
     * @brief 设置进度回调
     */
    void setProgressCallback(ParseProgressCallback callback) {
        progressCallback_ = std::move(callback);
    }
    
    // ========== 错误处理 ==========
    
    /**
     * @brief 获取最后错误信息
     */
    std::string getLastError() const { return lastError_; }
    
    /**
     * @brief 检查是否有错误
     */
    bool hasError() const { return !lastError_.empty(); }
    
    /**
     * @brief 清除错误信息
     */
    void clearError() { lastError_.clear(); }

protected:
    /**
     * @brief 设置错误信息
     */
    void setError(const std::string& error) { lastError_ = error; }
    
    /**
     * @brief 报告进度
     */
    void reportProgress(const std::string& phase, int64_t current, int64_t total) {
        if (progressCallback_) {
            progressCallback_(phase, current, total);
        }
    }
    
    std::string lastError_;
    ParseProgressCallback progressCallback_;
};

/**
 * @brief 智能指针别名
 */
using IDBParserPtr = std::unique_ptr<IDBParser>;
using IDBParserSharedPtr = std::shared_ptr<IDBParser>;

} // namespace Database
} // namespace ForensicAnalyzer
