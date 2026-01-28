/**
 * @file PostgreSQLAnalyzer.cpp
 * @brief PostgreSQL数据目录取证分析器实现
 */

#include "PostgreSQLAnalyzer.h"

#include <fstream>
#include <sstream>
#include <algorithm>
#include <regex>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {

PostgreSQLAnalyzer::PostgreSQLAnalyzer() = default;

PostgreSQLAnalyzer::~PostgreSQLAnalyzer() {
    close();
}

bool PostgreSQLAnalyzer::open(const std::string& path) {
    close();
    
    // 检查目录是否存在
    if (!fs::exists(path) || !fs::is_directory(path)) {
        setError("Path does not exist or is not a directory: " + path);
        return false;
    }
    
    dataDir_ = path;
    
    // 验证这是PostgreSQL数据目录
    fs::path dataPath(path);
    
    bool isPgDir = fs::exists(dataPath / "PG_VERSION") ||
                   (fs::exists(dataPath / "base") && fs::exists(dataPath / "global"));
    
    if (!isPgDir) {
        setError("Directory does not appear to be a PostgreSQL data directory: " + path);
        return false;
    }
    
    version_ = readPgVersion();
    scanDataDirectory();
    isOpen_ = true;
    clearError();
    
    return true;
}

bool PostgreSQLAnalyzer::connect(const DBConnectionConfig& config) {
    // 预留直接连接接口
    // 未来实现需要 libpq
    (void)config;
    setError("Direct PostgreSQL connection not yet implemented. Use open() for data directory analysis.");
    return false;
}

void PostgreSQLAnalyzer::close() {
    dataDir_.clear();
    version_.clear();
    isOpen_ = false;
}

int64_t PostgreSQLAnalyzer::getFileSize() const {
    if (dataDir_.empty()) return 0;
    return calculateDirectorySize(dataDir_);
}

int64_t PostgreSQLAnalyzer::calculateDirectorySize(const std::string& dir) const {
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

std::string PostgreSQLAnalyzer::readPgVersion() const {
    if (dataDir_.empty()) return "";
    
    fs::path versionFile = fs::path(dataDir_) / "PG_VERSION";
    if (!fs::exists(versionFile)) return "";
    
    std::ifstream file(versionFile);
    std::string version;
    std::getline(file, version);
    
    // 去除空白
    version.erase(version.find_last_not_of(" \t\r\n") + 1);
    
    return version;
}

void PostgreSQLAnalyzer::scanDataDirectory() {
    // 基本目录扫描，识别PostgreSQL结构
    if (dataDir_.empty()) return;
    
    // PostgreSQL数据目录结构:
    // - base/         数据库文件
    // - global/       共享系统表
    // - pg_wal/       WAL日志 (PostgreSQL 10+)
    // - pg_xlog/      WAL日志 (PostgreSQL 9.x)
    // - pg_tblspc/    表空间链接
    
    reportProgress("Scanning PostgreSQL data directory", 0, -1);
}

std::map<int64_t, std::string> PostgreSQLAnalyzer::getDatabaseOids() const {
    std::map<int64_t, std::string> databases;
    
    if (dataDir_.empty()) return databases;
    
    fs::path basePath = fs::path(dataDir_) / "base";
    
    if (!fs::exists(basePath)) return databases;
    
    // base目录下每个子目录是一个数据库，目录名是OID
    for (const auto& entry : fs::directory_iterator(basePath)) {
        if (entry.is_directory()) {
            std::string name = entry.path().filename().string();
            try {
                int64_t oid = std::stoll(name);
                
                // 根据已知OID识别系统数据库
                std::string dbName;
                switch (oid) {
                    case 1:     dbName = "template1"; break;
                    case 12709: dbName = "template0"; break;  // 典型值，可能不同
                    case 12710: dbName = "postgres"; break;   // 典型值，可能不同
                    default:    dbName = "database_" + name; break;
                }
                
                databases[oid] = dbName;
            } catch (...) {
                // 非数字目录名
            }
        }
    }
    
    return databases;
}

std::vector<DBTableInfo> PostgreSQLAnalyzer::getTables() {
    std::vector<DBTableInfo> tables;
    if (!isOpen_) return tables;
    
    reportProgress("Scanning PostgreSQL tables", 0, -1);
    
    fs::path basePath = fs::path(dataDir_) / "base";
    
    if (!fs::exists(basePath)) return tables;
    
    auto databases = getDatabaseOids();
    
    // 遍历每个数据库目录
    for (const auto& [oid, dbName] : databases) {
        fs::path dbPath = basePath / std::to_string(oid);
        
        if (!fs::is_directory(dbPath)) continue;
        
        // 每个文件可能是一个表（或表的一部分）
        // PostgreSQL的文件命名规则：
        // - 数字文件名是表文件（relfilenode）
        // - 带后缀的是额外的段：.1, .2, etc.
        // - _fsm是free space map
        // - _vm是visibility map
        
        std::map<int64_t, int64_t> tableFiles;  // relfilenode -> total size
        
        for (const auto& entry : fs::directory_iterator(dbPath)) {
            if (!entry.is_regular_file()) continue;
            
            std::string filename = entry.path().filename().string();
            
            // 跳过非数据文件
            if (filename.find("_fsm") != std::string::npos ||
                filename.find("_vm") != std::string::npos) {
                continue;
            }
            
            // 提取基础文件号
            std::string baseNum = filename;
            size_t dotPos = filename.find('.');
            if (dotPos != std::string::npos) {
                baseNum = filename.substr(0, dotPos);
            }
            
            try {
                int64_t relfilenode = std::stoll(baseNum);
                tableFiles[relfilenode] += static_cast<int64_t>(entry.file_size());
            } catch (...) {
                // 跳过非数字文件名
            }
        }
        
        // 创建表信息
        for (const auto& [relfilenode, size] : tableFiles) {
            // 跳过系统表（通常OID < 16384）
            if (relfilenode < 16384) continue;
            
            DBTableInfo table;
            table.name = "table_" + std::to_string(relfilenode);
            table.schema = dbName;
            table.sizeBytes = size;
            
            tables.push_back(std::move(table));
        }
    }
    
    reportProgress("Scanning PostgreSQL tables", tables.size(), tables.size());
    return tables;
}

DBTableInfo PostgreSQLAnalyzer::getTableInfo(const std::string& tableName) {
    DBTableInfo table;
    table.name = tableName;
    
    // 需要从pg_class等系统表获取详细信息
    // 这在目录分析模式下不可用
    
    return table;
}

std::vector<DBRecordInfo> PostgreSQLAnalyzer::getRecords(
    const std::string& tableName, 
    int limit,
    int offset) {
    
    // 数据目录分析模式不支持直接读取记录
    (void)tableName;
    (void)limit;
    (void)offset;
    
    setError("Record extraction requires direct database connection. Use connect() method (not yet implemented).");
    return {};
}

std::vector<DBUserInfo> PostgreSQLAnalyzer::getUsers() {
    std::vector<DBUserInfo> users;
    if (!isOpen_) return users;
    
    // PostgreSQL用户信息存储在global目录的pg_authid表中
    // 这需要解析PostgreSQL的堆文件格式
    
    // 目前返回占位符信息
    fs::path globalPath = fs::path(dataDir_) / "global";
    
    if (fs::exists(globalPath)) {
        DBUserInfo user;
        user.username = "[user data in pg_authid]";
        user.authMethod = "PostgreSQL";
        users.push_back(user);
    }
    
    return users;
}

std::vector<DBArtifact> PostgreSQLAnalyzer::extractArtifacts(const DBAnalysisOptions& options) {
    std::vector<DBArtifact> artifacts;
    if (!isOpen_) return artifacts;
    
    (void)options;
    
    reportProgress("Extracting PostgreSQL artifacts", 0, -1);
    
    fs::path dataPath(dataDir_);
    
    // 1. WAL日志
    auto walFiles = getWalFiles();
    for (const auto& walFile : walFiles) {
        DBArtifact artifact;
        artifact.type = ArtifactType::TRANSACTION_LOG;
        artifact.source = walFile;
        artifact.description = "PostgreSQL WAL file";
        artifact.data["file_name"] = fs::path(walFile).filename().string();
        if (fs::exists(walFile)) {
            artifact.data["file_size"] = std::to_string(fs::file_size(walFile));
        }
        artifacts.push_back(std::move(artifact));
    }
    
    // 2. 配置文件
    if (fs::exists(dataPath / "postgresql.conf")) {
        DBArtifact artifact;
        artifact.type = ArtifactType::CONFIG_ENTRY;
        artifact.source = (dataPath / "postgresql.conf").string();
        artifact.description = "PostgreSQL main configuration file";
        artifact.data = getPostgresConfig();
        artifacts.push_back(std::move(artifact));
    }
    
    // 3. pg_hba.conf
    if (fs::exists(dataPath / "pg_hba.conf")) {
        DBArtifact artifact;
        artifact.type = ArtifactType::CONFIG_ENTRY;
        artifact.source = (dataPath / "pg_hba.conf").string();
        artifact.description = "PostgreSQL host-based authentication configuration";
        
        auto rules = getPgHbaRules();
        for (size_t i = 0; i < rules.size(); i++) {
            artifact.data["rule_" + std::to_string(i)] = rules[i];
        }
        artifacts.push_back(std::move(artifact));
    }
    
    // 4. pg_ident.conf
    if (fs::exists(dataPath / "pg_ident.conf")) {
        DBArtifact artifact;
        artifact.type = ArtifactType::CONFIG_ENTRY;
        artifact.source = (dataPath / "pg_ident.conf").string();
        artifact.description = "PostgreSQL user name mapping configuration";
        artifacts.push_back(std::move(artifact));
    }
    
    // 5. postmaster.pid
    if (fs::exists(dataPath / "postmaster.pid")) {
        DBArtifact artifact;
        artifact.type = ArtifactType::CONFIG_ENTRY;
        artifact.source = (dataPath / "postmaster.pid").string();
        artifact.description = "PostgreSQL server process ID file";
        
        std::ifstream pidFile((dataPath / "postmaster.pid").string());
        std::string line;
        int lineNum = 0;
        while (std::getline(pidFile, line) && lineNum < 6) {
            switch (lineNum) {
                case 0: artifact.data["pid"] = line; break;
                case 1: artifact.data["data_directory"] = line; break;
                case 2: artifact.data["start_timestamp"] = line; break;
                case 3: artifact.data["port"] = line; break;
                case 4: artifact.data["socket_directory"] = line; break;
                case 5: artifact.data["listen_address"] = line; break;
            }
            lineNum++;
        }
        artifacts.push_back(std::move(artifact));
    }
    
    // 6. 表空间信息
    fs::path tblspcPath = dataPath / "pg_tblspc";
    if (fs::exists(tblspcPath)) {
        for (const auto& entry : fs::directory_iterator(tblspcPath)) {
            if (entry.is_symlink()) {
                DBArtifact artifact;
                artifact.type = ArtifactType::CONFIG_ENTRY;
                artifact.source = entry.path().string();
                artifact.description = "PostgreSQL tablespace link";
                artifact.data["oid"] = entry.path().filename().string();
                artifact.data["target"] = fs::read_symlink(entry.path()).string();
                artifacts.push_back(std::move(artifact));
            }
        }
    }
    
    reportProgress("Extracting PostgreSQL artifacts", artifacts.size(), artifacts.size());
    return artifacts;
}

std::vector<std::string> PostgreSQLAnalyzer::getWalFiles() const {
    std::vector<std::string> walFiles;
    if (dataDir_.empty()) return walFiles;
    
    // PostgreSQL 10+: pg_wal
    // PostgreSQL 9.x: pg_xlog
    fs::path walPath = fs::path(dataDir_) / "pg_wal";
    if (!fs::exists(walPath)) {
        walPath = fs::path(dataDir_) / "pg_xlog";
    }
    
    if (!fs::exists(walPath)) return walFiles;
    
    for (const auto& entry : fs::directory_iterator(walPath)) {
        if (entry.is_regular_file()) {
            std::string filename = entry.path().filename().string();
            // WAL文件名通常是24位十六进制数
            if (filename.size() == 24) {
                bool isHex = true;
                for (char c : filename) {
                    if (!std::isxdigit(c)) {
                        isHex = false;
                        break;
                    }
                }
                if (isHex) {
                    walFiles.push_back(entry.path().string());
                }
            }
        }
    }
    
    // 排序
    std::sort(walFiles.begin(), walFiles.end());
    
    return walFiles;
}

std::map<std::string, std::string> PostgreSQLAnalyzer::getPostgresConfig() const {
    fs::path configPath = fs::path(dataDir_) / "postgresql.conf";
    return parseConfigFile(configPath.string());
}

std::map<std::string, std::string> PostgreSQLAnalyzer::parseConfigFile(const std::string& path) const {
    std::map<std::string, std::string> config;
    
    std::ifstream file(path);
    if (!file.is_open()) return config;
    
    std::string line;
    std::regex kvRegex(R"(^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*'?([^'#]*)'?\s*(?:#.*)?)");
    
    while (std::getline(file, line)) {
        // 跳过注释和空行
        size_t start = line.find_first_not_of(" \t");
        if (start == std::string::npos || line[start] == '#') continue;
        
        std::smatch match;
        if (std::regex_match(line, match, kvRegex)) {
            std::string key = match[1];
            std::string value = match[2];
            
            // 去除尾部空白
            value.erase(value.find_last_not_of(" \t\r\n") + 1);
            
            config[key] = value;
        }
    }
    
    return config;
}

std::vector<std::string> PostgreSQLAnalyzer::getPgHbaRules() const {
    std::vector<std::string> rules;
    
    fs::path hbaPath = fs::path(dataDir_) / "pg_hba.conf";
    if (!fs::exists(hbaPath)) return rules;
    
    std::ifstream file(hbaPath);
    std::string line;
    
    while (std::getline(file, line)) {
        // 跳过注释和空行
        size_t start = line.find_first_not_of(" \t");
        if (start == std::string::npos || line[start] == '#') continue;
        
        // 去除空白
        line.erase(line.find_last_not_of(" \t\r\n") + 1);
        if (!line.empty()) {
            rules.push_back(line);
        }
    }
    
    return rules;
}

DBAnalysisSummary PostgreSQLAnalyzer::getAnalysisSummary() {
    DBAnalysisSummary summary;
    
    summary.databasePath = dataDir_;
    summary.type = DatabaseType::POSTGRESQL;
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
