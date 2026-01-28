/**
 * @file SQLiteAnalyzer.h
 * @brief SQLite数据库取证分析器
 * 
 * 提供SQLite数据库的完整取证分析功能，包括：
 * - Schema提取
 * - 记录读取
 * - 删除记录恢复
 * - WAL日志分析
 */

#pragma once

#include "IDBParser.h"
#include <sqlite3.h>

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief SQLite数据库分析器
 * 
 * 完整支持SQLite数据库的取证分析
 */
class SQLiteAnalyzer : public IDBParser {
public:
    SQLiteAnalyzer();
    ~SQLiteAnalyzer() override;
    
    // 禁止拷贝
    SQLiteAnalyzer(const SQLiteAnalyzer&) = delete;
    SQLiteAnalyzer& operator=(const SQLiteAnalyzer&) = delete;
    
    // ========== IDBParser接口实现 ==========
    
    bool open(const std::string& path) override;
    void close() override;
    bool isOpen() const override;
    
    DatabaseType getType() const override { return DatabaseType::SQLITE; }
    std::string getVersion() const override;
    std::string getPath() const override { return dbPath_; }
    int64_t getFileSize() const override;
    
    std::vector<DBTableInfo> getTables() override;
    DBTableInfo getTableInfo(const std::string& tableName) override;
    
    std::vector<DBRecordInfo> getRecords(
        const std::string& tableName, 
        int limit = -1,
        int offset = 0) override;
    
    std::vector<DBRecordInfo> executeQuery(const std::string& query) override;
    
    std::vector<DBArtifact> extractArtifacts(
        const DBAnalysisOptions& options = DBAnalysisOptions()) override;
    
    std::vector<DBRecordInfo> recoverDeletedRecords(int maxRecords = 10000) override;
    
    DBAnalysisSummary getAnalysisSummary() override;
    
    // ========== SQLite特有方法 ==========
    
    /**
     * @brief 获取数据库页大小
     */
    int getPageSize() const;
    
    /**
     * @brief 获取总页数
     */
    int64_t getTotalPages() const;
    
    /**
     * @brief 获取空闲页数
     */
    int64_t getFreelistPages() const;
    
    /**
     * @brief 获取数据库编码
     */
    std::string getEncoding() const;
    
    /**
     * @brief 分析WAL日志
     * @param walPath WAL文件路径（默认自动检测）
     */
    std::vector<DBArtifact> analyzeWAL(const std::string& walPath = "");
    
    /**
     * @brief 检测数据库应用类型
     * @return 应用名称（如"Chrome History", "Firefox Places"等）
     */
    std::string detectApplicationType() const;
    
    /**
     * @brief 获取SQLite原始句柄（高级用途）
     */
    sqlite3* getHandle() const { return db_; }

private:
    sqlite3* db_ = nullptr;
    std::string dbPath_;
    
    // 解析列类型
    ColumnDataType parseColumnType(const std::string& typeStr) const;
    
    // 获取表的列信息
    std::vector<DBColumnInfo> getTableColumns(const std::string& tableName);
    
    // 获取表的索引信息
    std::vector<DBIndexInfo> getTableIndexes(const std::string& tableName);
    
    // 估算表行数
    int64_t estimateRowCount(const std::string& tableName);
    
    // 解析删除记录（从freelist）
    std::vector<DBRecordInfo> parseFreelist();
    
    // 检测已知应用的表结构
    bool hasTable(const std::string& tableName) const;
    bool hasColumn(const std::string& tableName, const std::string& columnName) const;
};

} // namespace Database
} // namespace ForensicAnalyzer
