/**
 * @file DBParserFactory.cpp
 * @brief 数据库解析器工厂实现
 */

#include "DBParserFactory.h"
#include "SQLiteAnalyzer.h"
#include "MySQLAnalyzer.h"
#include "PostgreSQLAnalyzer.h"

#include <fstream>
#include <filesystem>
#include <algorithm>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {

// 静态注册表初始化
std::map<DatabaseType, ParserCreator>& DBParserFactory::getRegistry() {
    static std::map<DatabaseType, ParserCreator> registry;
    static bool initialized = false;
    
    if (!initialized) {
        // 注册内置解析器
        registry[DatabaseType::SQLITE] = []() { 
            return std::make_unique<SQLiteAnalyzer>(); 
        };
        registry[DatabaseType::MYSQL] = []() { 
            return std::make_unique<MySQLAnalyzer>(); 
        };
        registry[DatabaseType::POSTGRESQL] = []() { 
            return std::make_unique<PostgreSQLAnalyzer>(); 
        };
        initialized = true;
    }
    
    return registry;
}

DatabaseType DBParserFactory::detectType(const std::string& path) {
    // 检查路径是否存在
    if (!fs::exists(path)) {
        return DatabaseType::UNKNOWN;
    }
    
    // 如果是文件，检查magic bytes
    if (fs::is_regular_file(path)) {
        if (isSQLiteFile(path)) {
            return DatabaseType::SQLITE;
        }
        // 可以添加其他单文件数据库检测
    }
    
    // 如果是目录，检查目录结构
    if (fs::is_directory(path)) {
        if (isMySQLDataDir(path)) {
            return DatabaseType::MYSQL;
        }
        if (isPostgreSQLDataDir(path)) {
            return DatabaseType::POSTGRESQL;
        }
    }
    
    return DatabaseType::UNKNOWN;
}

IDBParserPtr DBParserFactory::createParser(const std::string& path) {
    DatabaseType type = detectType(path);
    if (type == DatabaseType::UNKNOWN) {
        return nullptr;
    }
    
    auto parser = createParser(type);
    if (parser && !parser->open(path)) {
        return nullptr;
    }
    
    return parser;
}

IDBParserPtr DBParserFactory::createParser(DatabaseType type) {
    auto& registry = getRegistry();
    auto it = registry.find(type);
    
    if (it != registry.end()) {
        return it->second();
    }
    
    return nullptr;
}

void DBParserFactory::registerParser(DatabaseType type, ParserCreator creator) {
    getRegistry()[type] = std::move(creator);
}

std::vector<DatabaseType> DBParserFactory::getRegisteredTypes() {
    std::vector<DatabaseType> types;
    for (const auto& [type, _] : getRegistry()) {
        types.push_back(type);
    }
    return types;
}

bool DBParserFactory::isTypeSupported(DatabaseType type) {
    return getRegistry().find(type) != getRegistry().end();
}

std::string DBParserFactory::getFileMagic(const std::string& path, size_t length) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) {
        return "";
    }
    
    std::string magic(length, '\0');
    file.read(&magic[0], length);
    magic.resize(file.gcount());
    
    return magic;
}

bool DBParserFactory::isSQLiteFile(const std::string& path) {
    // SQLite文件头: "SQLite format 3\0"
    static const std::string SQLITE_MAGIC = "SQLite format 3";
    
    std::string magic = getFileMagic(path, 16);
    return magic.size() >= 15 && magic.substr(0, 15) == SQLITE_MAGIC.substr(0, 15);
}

bool DBParserFactory::isMySQLDataDir(const std::string& path) {
    // MySQL数据目录特征文件
    // - mysql子目录（系统数据库）
    // - ibdata1文件（InnoDB系统表空间）
    // - ib_logfile0/1（InnoDB日志）
    
    fs::path dataDir(path);
    
    // 检查mysql系统数据库目录
    if (fs::exists(dataDir / "mysql") && fs::is_directory(dataDir / "mysql")) {
        return true;
    }
    
    // 检查InnoDB文件
    if (fs::exists(dataDir / "ibdata1")) {
        return true;
    }
    
    // 检查.frm文件（MySQL 5.x表定义）
    for (const auto& entry : fs::directory_iterator(path)) {
        if (entry.is_regular_file()) {
            std::string ext = entry.path().extension().string();
            std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
            if (ext == ".frm" || ext == ".myi" || ext == ".myd") {
                return true;
            }
        }
    }
    
    return false;
}

bool DBParserFactory::isPostgreSQLDataDir(const std::string& path) {
    // PostgreSQL数据目录特征文件
    // - PG_VERSION 文件
    // - base目录
    // - global目录
    // - pg_hba.conf配置文件
    
    fs::path dataDir(path);
    
    // PG_VERSION是最可靠的标识
    if (fs::exists(dataDir / "PG_VERSION")) {
        return true;
    }
    
    // 检查典型目录结构
    if (fs::exists(dataDir / "base") && 
        fs::is_directory(dataDir / "base") &&
        fs::exists(dataDir / "global") && 
        fs::is_directory(dataDir / "global")) {
        return true;
    }
    
    // 检查配置文件
    if (fs::exists(dataDir / "postgresql.conf") || 
        fs::exists(dataDir / "pg_hba.conf")) {
        return true;
    }
    
    return false;
}

} // namespace Database
} // namespace ForensicAnalyzer
