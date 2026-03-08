/**
 * @file MySQLAnalyzer.cpp
 * @brief MySQL数据目录取证分析器实现
 */

#include "MySQLAnalyzer.h"

#include <fstream>
#include <sstream>
#include <algorithm>
#include <regex>
#include <cstring>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {

MySQLAnalyzer::MySQLAnalyzer() = default;

MySQLAnalyzer::~MySQLAnalyzer() {
    close();
}

bool MySQLAnalyzer::open(const std::string& path) {
    close();
    
    // 检查目录是否存在
    if (!fs::exists(path) || !fs::is_directory(path)) {
        setError("Path does not exist or is not a directory: " + path);
        return false;
    }
    
    dataDir_ = path;
    
    // 验证这是MySQL数据目录
    bool isMySQLDir = fs::exists(fs::path(path) / "mysql") ||
                      fs::exists(fs::path(path) / "ibdata1");
    
    if (!isMySQLDir) {
        // 尝试查找典型MySQL表文件
        for (const auto& entry : fs::directory_iterator(path)) {
            if (entry.is_regular_file()) {
                std::string ext = entry.path().extension().string();
                std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
                if (ext == ".frm" || ext == ".myi" || ext == ".myd" || ext == ".ibd") {
                    isMySQLDir = true;
                    break;
                }
            }
        }
    }
    
    if (!isMySQLDir) {
        setError("Directory does not appear to be a MySQL data directory: " + path);
        return false;
    }
    
    version_ = detectVersion();
    scanDataDirectory();
    isOpen_ = true;
    clearError();
    
    // Launch background daemon to allow record extraction
    daemon_ = std::make_unique<MySQLDaemon>(dataDir_);
    if (!daemon_->start()) {
        // We do not fail the whole open() process if daemon fails,
        // because we can still extract artifacts/metadata offline.
        // We just log the warning.
        reportProgress("Warning: Cannot start mysqld daemon: " + daemon_->getLastError(), 0, 0);
    }
    
    return true;
}

bool MySQLAnalyzer::connect(const DBConnectionConfig& config) {
    // 预留直接连接接口
    // 未来实现需要MySQL C API或connector
    (void)config;
    setError("Direct MySQL connection not yet implemented. Use open() for data directory analysis.");
    return false;
}

void MySQLAnalyzer::close() {
    if (daemon_) {
        daemon_->stop();
        daemon_.reset();
    }
    
    dataDir_.clear();
    version_.clear();
    databases_.clear();
    isOpen_ = false;
}

int64_t MySQLAnalyzer::getFileSize() const {
    if (dataDir_.empty()) return 0;
    return calculateDirectorySize(dataDir_);
}

int64_t MySQLAnalyzer::calculateDirectorySize(const std::string& dir) const {
    int64_t totalSize = 0;
    
    try {
        for (const auto& entry : fs::recursive_directory_iterator(dir)) {
            if (entry.is_regular_file()) {
                totalSize += static_cast<int64_t>(entry.file_size());
            }
        }
    } catch (...) {
        // 忽略权限错误等
    }
    
    return totalSize;
}

void MySQLAnalyzer::scanDataDirectory() {
    databases_.clear();
    
    if (dataDir_.empty()) return;
    
    fs::path dataPath(dataDir_);
    
    // 每个子目录通常是一个数据库
    for (const auto& entry : fs::directory_iterator(dataPath)) {
        if (entry.is_directory()) {
            std::string name = entry.path().filename().string();
            // 跳过系统目录
            if (name != "." && name != ".." && 
                name != "#innodb_temp" && name != "#innodb_redo") {
                databases_.push_back(name);
            }
        }
    }
}

std::vector<std::string> MySQLAnalyzer::getDatabases() const {
    return databases_;
}

std::string MySQLAnalyzer::detectVersion() const {
    if (dataDir_.empty()) return "";
    
    fs::path dataPath(dataDir_);
    
    // 检查MySQL 8.0+ 的 mysql.ibd
    if (fs::exists(dataPath / "mysql.ibd")) {
        return "8.0+";
    }
    
    // 检查MySQL 5.x 的 mysql/user.frm
    if (fs::exists(dataPath / "mysql" / "user.frm")) {
        return "5.x";
    }
    
    // 检查InnoDB文件
    if (fs::exists(dataPath / "ibdata1")) {
        return "InnoDB (version unknown)";
    }
    
    return "Unknown";
}

std::vector<DBTableInfo> MySQLAnalyzer::getTables() {
    std::vector<DBTableInfo> tables;
    if (!isOpen_) return tables;
    
    fs::path dataPath(dataDir_);
    
    reportProgress("Scanning tables", 0, -1);
    
    // 遍历所有数据库目录
    for (const auto& db : databases_) {
        fs::path dbPath = dataPath / db;
        
        if (!fs::is_directory(dbPath)) continue;
        
        for (const auto& entry : fs::directory_iterator(dbPath)) {
            if (!entry.is_regular_file()) continue;
            
            std::string ext = entry.path().extension().string();
            std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
            
            // MySQL 5.x: .frm 文件
            if (ext == ".frm") {
                DBTableInfo table = parseFrmFile(entry.path().string());
                table.schema = db;
                tables.push_back(std::move(table));
            }
            // MySQL 8.0+: 可能需要解析SDI或从数据字典读取
        }
    }
    
    reportProgress("Scanning tables", tables.size(), tables.size());
    return tables;
}

DBTableInfo MySQLAnalyzer::getTableInfo(const std::string& tableName) {
    DBTableInfo table;
    table.name = tableName;
    
    // 查找表文件
    for (const auto& db : databases_) {
        fs::path frmPath = fs::path(dataDir_) / db / (tableName + ".frm");
        if (fs::exists(frmPath)) {
            table = parseFrmFile(frmPath.string());
            table.schema = db;
            break;
        }
    }
    
    return table;
}

DBTableInfo MySQLAnalyzer::parseFrmFile(const std::string& frmPath) {
    DBTableInfo table;
    
    fs::path path(frmPath);
    table.name = path.stem().string();
    
    // .frm 文件结构复杂，这里提供基本解析
    std::ifstream file(frmPath, std::ios::binary);
    if (!file.is_open()) {
        return table;
    }
    
    // 读取文件头
    char header[64];
    file.read(header, 64);
    
    if (file.gcount() < 64) {
        return table;
    }
    
    // .frm 文件magic: 0xFE 0x01 (MyISAM) 或其他
    if (static_cast<unsigned char>(header[0]) == 0xFE) {
        // 有效的.frm文件
        
        // 字节偏移 3: 数据库类型
        unsigned char dbType = static_cast<unsigned char>(header[3]);
        switch (dbType) {
            case 0: table.engine = "UNKNOWN"; break;
            case 1: table.engine = "ISAM"; break;
            case 2: table.engine = "HEAP"; break;
            case 3: table.engine = "MERGE"; break;
            case 4: table.engine = "MyISAM"; break;
            case 5: table.engine = "MRG_MYISAM"; break;
            case 9: table.engine = "InnoDB"; break;
            case 10: table.engine = "TokuDB"; break;
            case 11: table.engine = "FEDERATEDX"; break;
            case 12: table.engine = "CSV"; break;
            case 18: table.engine = "PARTITION"; break;
            default: table.engine = "Engine_" + std::to_string(dbType); break;
        }
        
        // 注意：完整的.frm解析需要大量工作
        // 列定义在文件的后半部分，格式复杂
        
        // 获取文件大小作为参考
        table.sizeBytes = static_cast<int64_t>(fs::file_size(frmPath));
    }
    
    // 检查对应的数据文件大小
    fs::path ibdPath = path.parent_path() / (table.name + ".ibd");
    if (fs::exists(ibdPath)) {
        table.sizeBytes = static_cast<int64_t>(fs::file_size(ibdPath));
    }
    
    return table;
}

std::vector<DBRecordInfo> MySQLAnalyzer::getRecords(
    const std::string& tableName, 
    int limit,
    int offset) {
    
    std::vector<DBRecordInfo> records;
    if (!isOpen_) return records;
    
    if (!daemon_ || !daemon_->isRunning()) {
        setError("Record extraction requires mysqld daemon to be running. Daemon failed: " + 
                 (daemon_ ? daemon_->getLastError() : "Not initialized"));
        return records;
    }
    
    MYSQL* conn = daemon_->getConnection();
    if (!conn) {
        setError("MySQL connection is null.");
        return records;
    }
    
    // Find which schema this table belongs to
    std::string schemaName;
    for (const auto& db : databases_) {
        fs::path frmPath = fs::path(dataDir_) / db / (tableName + ".frm");
        fs::path ibdPath = fs::path(dataDir_) / db / (tableName + ".ibd");
        if (fs::exists(frmPath) || fs::exists(ibdPath)) {
            schemaName = db;
            break;
        }
    }
    
    if (schemaName.empty()) {
        setError("Schema for table " + tableName + " not found.");
        return records;
    }
    
    std::string query = "SELECT * FROM `" + schemaName + "`.`" + tableName + "`";
    if (limit > 0) {
        query += " LIMIT " + std::to_string(limit);
        if (offset > 0) {
            query += " OFFSET " + std::to_string(offset);
        }
    }
    
    if (mysql_query(conn, query.c_str()) != 0) {
        setError(std::string("Query failed: ") + mysql_error(conn));
        return records;
    }
    
    MYSQL_RES* result = mysql_store_result(conn);
    if (!result) {
        setError(std::string("Failed to store result: ") + mysql_error(conn));
        return records;
    }
    
    int numFields = mysql_num_fields(result);
    MYSQL_FIELD* fields = mysql_fetch_fields(result);
    
    MYSQL_ROW row;
    while ((row = mysql_fetch_row(result))) {
        DBRecordInfo recordInfo;
        for (int i = 0; i < numFields; i++) {
            std::string colName = fields[i].name ? fields[i].name : "col_" + std::to_string(i);
            std::string colValue = row[i] ? row[i] : "NULL";
            recordInfo.values[colName] = colValue;
        }
        records.push_back(std::move(recordInfo));
    }
    
    mysql_free_result(result);
    return records;
}

std::vector<DBUserInfo> MySQLAnalyzer::getUsers() {
    std::vector<DBUserInfo> users;
    if (!isOpen_) return users;
    
    // MySQL 5.x: mysql/user.MYD 包含用户数据
    // MySQL 8.0+: 数据存储在mysql.ibd中
    
    fs::path userMyd = fs::path(dataDir_) / "mysql" / "user.MYD";
    
    if (fs::exists(userMyd)) {
        // 基本的用户文件存在性检测
        DBArtifact artifact;
        artifact.type = ArtifactType::USER_ACCOUNT;
        artifact.source = userMyd.string();
        artifact.description = "MySQL user table data file found";
        
        // 完整解析需要了解MYD文件格式
        DBUserInfo user;
        user.username = "[user data in " + userMyd.string() + "]";
        user.authMethod = "MySQL native";
        users.push_back(user);
    }
    
    return users;
}

std::vector<DBArtifact> MySQLAnalyzer::extractArtifacts(const DBAnalysisOptions& options) {
    std::vector<DBArtifact> artifacts;
    if (!isOpen_) return artifacts;
    
    (void)options;  // 未来使用
    
    reportProgress("Extracting MySQL artifacts", 0, -1);
    
    fs::path dataPath(dataDir_);
    
    // 检测InnoDB系统表空间
    if (fs::exists(dataPath / "ibdata1")) {
        DBArtifact artifact;
        artifact.type = ArtifactType::CONFIG_ENTRY;
        artifact.source = (dataPath / "ibdata1").string();
        artifact.description = "InnoDB system tablespace";
        artifact.data["file_size"] = std::to_string(fs::file_size(dataPath / "ibdata1"));
        artifacts.push_back(std::move(artifact));
    }
    
    // 检测InnoDB日志
    for (int i = 0; i < 10; i++) {
        std::string logName = "ib_logfile" + std::to_string(i);
        if (fs::exists(dataPath / logName)) {
            DBArtifact artifact;
            artifact.type = ArtifactType::TRANSACTION_LOG;
            artifact.source = (dataPath / logName).string();
            artifact.description = "InnoDB redo log file " + std::to_string(i);
            artifact.data["file_size"] = std::to_string(fs::file_size(dataPath / logName));
            artifacts.push_back(std::move(artifact));
        }
    }
    
    // 检测二进制日志
    for (const auto& entry : fs::directory_iterator(dataPath)) {
        std::string filename = entry.path().filename().string();
        
        // 二进制日志通常命名为 mysql-bin.000001 等
        if (filename.find("-bin.") != std::string::npos || 
            filename.find("binlog.") != std::string::npos) {
            DBArtifact artifact;
            artifact.type = ArtifactType::TRANSACTION_LOG;
            artifact.source = entry.path().string();
            artifact.description = "MySQL binary log: " + filename;
            artifact.data["file_size"] = std::to_string(entry.file_size());
            artifacts.push_back(std::move(artifact));
        }
        
        // 慢查询日志
        if (filename.find("slow") != std::string::npos && 
            filename.find(".log") != std::string::npos) {
            DBArtifact artifact;
            artifact.type = ArtifactType::CONFIG_ENTRY;
            artifact.source = entry.path().string();
            artifact.description = "MySQL slow query log";
            artifact.data["file_size"] = std::to_string(entry.file_size());
            artifacts.push_back(std::move(artifact));
        }
    }
    
    // 检测配置文件
    std::string configPath = findConfigFile();
    if (!configPath.empty()) {
        DBArtifact artifact;
        artifact.type = ArtifactType::CONFIG_ENTRY;
        artifact.source = configPath;
        artifact.description = "MySQL configuration file";
        
        // 读取配置
        auto config = getConfigFromFile();
        for (const auto& [key, value] : config) {
            artifact.data[key] = value;
        }
        artifacts.push_back(std::move(artifact));
    }
    
    reportProgress("Extracting MySQL artifacts", artifacts.size(), artifacts.size());
    return artifacts;
}

std::string MySQLAnalyzer::findConfigFile() const {
    // 常见MySQL配置文件位置
    std::vector<std::string> configPaths = {
        "/etc/mysql/my.cnf",
        "/etc/my.cnf",
        "/usr/local/mysql/etc/my.cnf",
        dataDir_ + "/my.cnf"
    };
    
    for (const auto& path : configPaths) {
        if (fs::exists(path)) {
            return path;
        }
    }
    
    return "";
}

std::map<std::string, std::string> MySQLAnalyzer::getConfigFromFile() const {
    std::map<std::string, std::string> config;
    
    std::string configPath = findConfigFile();
    if (configPath.empty()) return config;
    
    std::ifstream file(configPath);
    if (!file.is_open()) return config;
    
    std::string line;
    std::string section;
    std::regex sectionRegex(R"(\[([^\]]+)\])");
    std::regex kvRegex(R"((\w+)\s*=\s*(.+))");
    
    while (std::getline(file, line)) {
        // 去除注释
        size_t commentPos = line.find('#');
        if (commentPos != std::string::npos) {
            line = line.substr(0, commentPos);
        }
        
        // 去除空白
        line.erase(0, line.find_first_not_of(" \t"));
        line.erase(line.find_last_not_of(" \t\r\n") + 1);
        
        if (line.empty()) continue;
        
        std::smatch match;
        if (std::regex_match(line, match, sectionRegex)) {
            section = match[1];
        } else if (std::regex_match(line, match, kvRegex)) {
            std::string key = section.empty() ? match[1].str() : (section + "." + match[1].str());
            config[key] = match[2];
        }
    }
    
    return config;
}

std::map<std::string, std::string> MySQLAnalyzer::getInnoDBInfo() const {
    std::map<std::string, std::string> info;
    
    fs::path ibdataPath = fs::path(dataDir_) / "ibdata1";
    if (!fs::exists(ibdataPath)) {
        return info;
    }
    
    info["ibdata1_size"] = std::to_string(fs::file_size(ibdataPath));
    
    // 计算InnoDB相关文件总大小
    int64_t totalInnoDB = 0;
    int logFiles = 0;
    
    for (const auto& entry : fs::directory_iterator(dataDir_)) {
        std::string filename = entry.path().filename().string();
        if (filename.find("ibdata") == 0 || filename.find("ib_logfile") == 0) {
            totalInnoDB += static_cast<int64_t>(entry.file_size());
            if (filename.find("ib_logfile") == 0) logFiles++;
        }
    }
    
    info["total_innodb_size"] = std::to_string(totalInnoDB);
    info["log_file_count"] = std::to_string(logFiles);
    
    return info;
}

DBAnalysisSummary MySQLAnalyzer::getAnalysisSummary() {
    DBAnalysisSummary summary;
    
    summary.databasePath = dataDir_;
    summary.type = DatabaseType::MYSQL;
    summary.version = version_;
    summary.fileSizeBytes = getFileSize();
    summary.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    
    auto tables = getTables();
    summary.tableCount = tables.size();
    
    for (const auto& table : tables) {
        summary.tableSizes[table.schema + "." + table.name] = table.sizeBytes;
    }
    
    auto users = getUsers();
    summary.userCount = users.size();
    
    return summary;
}

} // namespace Database
} // namespace ForensicAnalyzer
