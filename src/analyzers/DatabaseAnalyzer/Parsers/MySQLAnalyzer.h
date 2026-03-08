/**
 * @file MySQLAnalyzer.h
 * @brief MySQL数据目录取证分析器
 * 
 * 分析MySQL数据目录结构，提取元数据和配置信息
 * 当前版本支持目录分析，预留直接连接接口供未来扩展
 */

#pragma once

#include "IDBParser.h"
#include "MySQLDaemon.h"
#include <filesystem>
#include <memory>

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief MySQL数据目录分析器
 * 
 * 分析MySQL数据目录，提取：
 * - 数据库和表结构（从.frm文件）
 * - InnoDB元数据
 * - 用户账户信息
 * - 配置文件
 */
class MySQLAnalyzer : public IDBParser {
public:
    MySQLAnalyzer();
    ~MySQLAnalyzer() override;
    
    // 禁止拷贝
    MySQLAnalyzer(const MySQLAnalyzer&) = delete;
    MySQLAnalyzer& operator=(const MySQLAnalyzer&) = delete;
    
    // ========== IDBParser接口实现 ==========
    
    bool open(const std::string& path) override;
    bool connect(const DBConnectionConfig& config) override;
    void close() override;
    bool isOpen() const override { return isOpen_; }
    
    DatabaseType getType() const override { return DatabaseType::MYSQL; }
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
    
    // ========== MySQL特有方法 ==========
    
    /**
     * @brief 获取所有数据库名
     */
    std::vector<std::string> getDatabases() const;
    
    /**
     * @brief 获取InnoDB系统表空间信息
     */
    std::map<std::string, std::string> getInnoDBInfo() const;
    
    /**
     * @brief 解析.frm文件
     * @param frmPath .frm文件路径
     * @return 表信息
     */
    DBTableInfo parseFrmFile(const std::string& frmPath);
    
    /**
     * @brief 检测MySQL版本
     */
    std::string detectVersion() const;
    
    /**
     * @brief 获取配置文件内容
     */
    std::map<std::string, std::string> getConfigFromFile() const;

private:
    std::string dataDir_;
    std::string version_;
    bool isOpen_ = false;
    std::unique_ptr<MySQLDaemon> daemon_;
    
    // 缓存的数据库列表
    mutable std::vector<std::string> databases_;
    
    // 扫描数据目录
    void scanDataDirectory();
    
    // 解析MySQL 5.x .frm文件头
    bool parseFrmHeader(const std::string& frmPath, DBTableInfo& table);
    
    // 解析MySQL 8.0+ SDI信息
    bool parseSdiFile(const std::string& sdiPath, DBTableInfo& table);
    
    // 查找配置文件
    std::string findConfigFile() const;
    
    // 解析InnoDB ibdata1文件
    std::map<std::string, std::string> parseIbdata() const;
    
    // 计算目录总大小
    int64_t calculateDirectorySize(const std::string& dir) const;
};

} // namespace Database
} // namespace ForensicAnalyzer
