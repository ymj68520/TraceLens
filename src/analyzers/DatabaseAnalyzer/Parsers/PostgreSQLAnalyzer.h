/**
 * @file PostgreSQLAnalyzer.h
 * @brief PostgreSQL数据目录取证分析器
 * 
 * 分析PostgreSQL数据目录结构，提取元数据和配置信息
 * 当前版本支持目录分析，预留直接连接接口供未来扩展
 */

#pragma once

#include "IDBParser.h"
#include "PostgreSQLDaemon.h"
#include <filesystem>
#include <memory>

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief PostgreSQL数据目录分析器
 * 
 * 分析PostgreSQL数据目录，提取：
 * - 数据库列表
 * - 表文件信息
 * - 用户账户信息
 * - 配置文件
 * - WAL日志
 */
class PostgreSQLAnalyzer : public IDBParser {
public:
    PostgreSQLAnalyzer();
    ~PostgreSQLAnalyzer() override;
    
    // 禁止拷贝
    PostgreSQLAnalyzer(const PostgreSQLAnalyzer&) = delete;
    PostgreSQLAnalyzer& operator=(const PostgreSQLAnalyzer&) = delete;
    
    // ========== IDBParser接口实现 ==========
    
    bool open(const std::string& path) override;
    bool connect(const DBConnectionConfig& config) override;
    void close() override;
    bool isOpen() const override { return isOpen_; }
    
    DatabaseType getType() const override { return DatabaseType::POSTGRESQL; }
    std::string getVersion() const override { return version_; }
    std::string getPath() const override { return dataDir_; }
    int64_t getFileSize() const override;
    
    std::vector<DBTableInfo> getTables() override;
    DBTableInfo getTableInfo(const std::string& tableName) override;
    
    std::vector<DBRecordInfo> getRecords(
        const std::string& tableName, 
        int limit = -1,
        int offset = 0) override;
    
    std::vector<DBArtifact> extractArtifacts(
        const DBAnalysisOptions& options = DBAnalysisOptions()) override;
    
    std::vector<DBUserInfo> getUsers() override;
    
    DBAnalysisSummary getAnalysisSummary() override;
    
    // ========== PostgreSQL特有方法 ==========
    
    /**
     * @brief 获取所有数据库OID和名称
     */
    std::map<int64_t, std::string> getDatabaseOids() const;
    
    /**
     * @brief 读取PG_VERSION文件
     */
    std::string readPgVersion() const;
    
    /**
     * @brief 获取postgresql.conf配置
     */
    std::map<std::string, std::string> getPostgresConfig() const;
    
    /**
     * @brief 获取pg_hba.conf认证配置
     */
    std::vector<std::string> getPgHbaRules() const;
    
    /**
     * @brief 获取WAL目录信息
     */
    std::vector<std::string> getWalFiles() const;

private:
    std::string dataDir_;
    std::string version_;
    bool isOpen_ = false;
    std::unique_ptr<PostgreSQLDaemon> daemon_;
    
    // 扫描数据目录
    void scanDataDirectory();
    
    // 解析pg_database
    void parsePgDatabase();
    
    // 解析pg_class（表信息）
    void parsePgClass();
    
    // 计算目录总大小
    int64_t calculateDirectorySize(const std::string& dir) const;
    
    // 读取配置文件
    std::map<std::string, std::string> parseConfigFile(const std::string& path) const;
};

} // namespace Database
} // namespace ForensicAnalyzer
