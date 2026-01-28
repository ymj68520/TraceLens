/**
 * @file DBDataTypes.h
 * @brief 数据库取证分析模块数据类型定义
 * 
 * 包含所有数据库分析相关的枚举、结构体和类型别名
 */

#pragma once

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include <chrono>

namespace ForensicAnalyzer {
namespace Database {

// ============================================================================
// 枚举定义
// ============================================================================

/**
 * @brief 数据库类型枚举
 */
enum class DatabaseType {
    UNKNOWN = 0,
    SQLITE,
    MYSQL,
    POSTGRESQL,
    // 预留扩展
    MARIADB,
    ORACLE,
    MSSQL,
    MONGODB,
    LEVELDB,
    ROCKSDB
};

/**
 * @brief 数据库类型转字符串
 */
inline std::string databaseTypeToString(DatabaseType type) {
    switch (type) {
        case DatabaseType::SQLITE:     return "SQLite";
        case DatabaseType::MYSQL:      return "MySQL";
        case DatabaseType::POSTGRESQL: return "PostgreSQL";
        case DatabaseType::MARIADB:    return "MariaDB";
        case DatabaseType::ORACLE:     return "Oracle";
        case DatabaseType::MSSQL:      return "MSSQL";
        case DatabaseType::MONGODB:    return "MongoDB";
        case DatabaseType::LEVELDB:    return "LevelDB";
        case DatabaseType::ROCKSDB:    return "RocksDB";
        default:                       return "Unknown";
    }
}

/**
 * @brief 列数据类型枚举
 */
enum class ColumnDataType {
    UNKNOWN = 0,
    INTEGER,
    REAL,
    TEXT,
    BLOB,
    NULL_TYPE,
    BOOLEAN,
    DATETIME,
    JSON
};

/**
 * @brief 工件类型枚举
 */
enum class ArtifactType {
    UNKNOWN = 0,
    DELETED_RECORD,      // 已删除的记录
    WAL_ENTRY,           // 写前日志条目
    FREELIST_PAGE,       // 空闲页
    OVERFLOW_PAGE,       // 溢出页
    CONFIG_ENTRY,        // 配置条目
    USER_ACCOUNT,        // 用户账户
    TRANSACTION_LOG,     // 事务日志
    SCHEMA_CHANGE        // Schema变更
};

// ============================================================================
// 数据结构定义
// ============================================================================

/**
 * @brief 列信息
 */
struct DBColumnInfo {
    std::string name;                    // 列名
    std::string dataType;                // 数据类型（原始字符串）
    ColumnDataType type = ColumnDataType::UNKNOWN;  // 解析后的类型
    bool nullable = true;                // 是否可为空
    bool isPrimaryKey = false;           // 是否为主键
    bool isAutoIncrement = false;        // 是否自增
    std::string defaultValue;            // 默认值
    int ordinalPosition = 0;             // 列顺序
};

/**
 * @brief 索引信息
 */
struct DBIndexInfo {
    std::string name;                    // 索引名
    std::string tableName;               // 所属表名
    std::vector<std::string> columns;    // 索引列
    bool isUnique = false;               // 是否唯一索引
    bool isPrimaryKey = false;           // 是否主键索引
    std::string type;                    // 索引类型（B-Tree, Hash等）
};

/**
 * @brief 表信息
 */
struct DBTableInfo {
    std::string name;                    // 表名
    std::string schema;                  // Schema名（MySQL/PostgreSQL）
    int64_t rowCount = 0;                // 行数
    int64_t sizeBytes = 0;               // 表大小（字节）
    std::vector<DBColumnInfo> columns;   // 列信息
    std::vector<DBIndexInfo> indexes;    // 索引信息
    std::string createStatement;         // 建表语句
    std::string engine;                  // 存储引擎（如InnoDB）
    std::string collation;               // 字符集
};

/**
 * @brief 通用记录（键值对形式）
 */
struct DBRecordInfo {
    std::string tableName;               // 所属表名
    int64_t rowId = 0;                   // 行ID（如果有）
    std::map<std::string, std::string> values;  // 列名->值
    bool isDeleted = false;              // 是否为删除的记录
    int64_t pageNumber = 0;              // 页号（用于恢复分析）
    int64_t cellOffset = 0;              // 单元格偏移
};

/**
 * @brief 数据库用户信息
 */
struct DBUserInfo {
    std::string username;                // 用户名
    std::string host;                    // 主机（MySQL格式）
    std::string authMethod;              // 认证方法
    std::string passwordHash;            // 密码哈希（如可访问）
    std::vector<std::string> privileges; // 权限列表
    bool isLocked = false;               // 是否锁定
    int64_t createdAt = 0;               // 创建时间戳
    int64_t lastLogin = 0;               // 最后登录时间
};

/**
 * @brief 取证工件
 */
struct DBArtifact {
    ArtifactType type = ArtifactType::UNKNOWN;  // 工件类型
    std::string source;                  // 来源（表名、日志文件等）
    std::string description;             // 描述
    std::map<std::string, std::string> data;  // 工件数据
    int64_t pageNumber = 0;              // 页号
    int64_t offset = 0;                  // 文件偏移
    int64_t timestamp = 0;               // 时间戳
    std::string rawData;                 // 原始数据（十六进制或Base64）
};

/**
 * @brief 数据库分析摘要
 */
struct DBAnalysisSummary {
    std::string databasePath;            // 数据库路径
    DatabaseType type = DatabaseType::UNKNOWN;  // 数据库类型
    std::string version;                 // 数据库版本
    int64_t fileSizeBytes = 0;           // 文件大小
    int64_t tableCount = 0;              // 表数量
    int64_t totalRecords = 0;            // 总记录数
    int64_t deletedRecords = 0;          // 已删除记录数
    int64_t userCount = 0;               // 用户数量
    int64_t artifactCount = 0;           // 工件数量
    int64_t analyzedAt = 0;              // 分析时间戳
    std::string lastError;               // 最后错误信息
    
    // 统计信息
    std::map<std::string, int64_t> tableRecordCounts;  // 每表记录数
    std::map<std::string, int64_t> tableSizes;         // 每表大小
};

/**
 * @brief 数据库连接配置（用于未来直接连接分析）
 */
struct DBConnectionConfig {
    DatabaseType type = DatabaseType::UNKNOWN;
    std::string host = "localhost";
    int port = 0;                        // 0表示使用默认端口
    std::string database;                // 数据库名
    std::string username;
    std::string password;
    std::string socketPath;              // Unix socket路径
    int connectTimeoutMs = 10000;
    int queryTimeoutMs = 30000;
    bool useSSL = false;
    std::string sslCertPath;
    std::string sslKeyPath;
    std::string sslCAPath;
    
    // 获取默认端口
    int getDefaultPort() const {
        switch (type) {
            case DatabaseType::MYSQL:
            case DatabaseType::MARIADB:
                return 3306;
            case DatabaseType::POSTGRESQL:
                return 5432;
            case DatabaseType::MSSQL:
                return 1433;
            case DatabaseType::ORACLE:
                return 1521;
            case DatabaseType::MONGODB:
                return 27017;
            default:
                return 0;
        }
    }
};

/**
 * @brief 分析选项
 */
struct DBAnalysisOptions {
    bool extractSchema = true;           // 提取表结构
    bool extractRecords = true;          // 提取记录
    bool extractDeletedRecords = true;   // 尝试恢复删除的记录
    bool extractArtifacts = true;        // 提取取证工件
    bool extractUsers = true;            // 提取用户信息
    bool parseWAL = true;                // 解析WAL日志
    bool parseBinaryLogs = true;         // 解析二进制日志（MySQL）
    int maxRecordsPerTable = -1;         // 每表最大记录数（-1表示无限制）
    int maxDeletedRecords = 10000;       // 最大恢复删除记录数
    std::vector<std::string> includeTables;  // 仅分析指定表
    std::vector<std::string> excludeTables;  // 排除指定表
};

} // namespace Database
} // namespace ForensicAnalyzer
