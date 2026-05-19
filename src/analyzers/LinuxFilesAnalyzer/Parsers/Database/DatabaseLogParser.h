// DatabaseLogParser.h
// Parser for database service logs (MySQL, PostgreSQL, MongoDB, Redis)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#pragma once
#ifndef DATABASE_LOG_PARSER_H
#define DATABASE_LOG_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include "Common/LinuxDataTypes.h"

#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Database types
enum class DatabaseType {
    MySQL,
    MariaDB,
    PostgreSQL,
    MongoDB,
    Redis,
    Unknown
};

// Database log entry
struct DatabaseLogEntry {
    std::string timestamp;
    int64_t timestampUnix = 0;
    DatabaseType dbType = DatabaseType::Unknown;
    std::string severity;           // error, warning, notice, info, debug
    std::string component;          // server, client, replication, etc.
    std::string message;
    std::string sourceFile;         // log file path
    int lineNumber = 0;
    std::string username;           // authenticated user if available
    std::string database;           // database name if available
    std::string clientAddr;         // client IP:port
    std::string query;              // SQL/query if logged
    int errorCode = 0;
    EvidenceProvenance provenance;
};

// Database security finding
struct DatabaseSecurityFinding {
    std::string findingType;        // auth_failure, privilege_escalation, suspicious_query, config_weakness
    std::string severity;           // critical, high, medium, low
    std::string description;
    std::string evidence;
    std::string sourceFile;
    DatabaseType dbType = DatabaseType::Unknown;
    std::string username;
    std::string clientAddr;
    EvidenceProvenance provenance;
};

class DatabaseLogParser {
public:
    // Auto-detect database type from file path
    static DatabaseType detectDatabaseType(const std::string& filePath);

    // Parse MySQL/MariaDB error log
    static std::vector<DatabaseLogEntry> parseMySQLLog(
        const std::string& content, const std::string& filePath = "");

    // Parse PostgreSQL log
    static std::vector<DatabaseLogEntry> parsePostgreSQLLog(
        const std::string& content, const std::string& filePath = "");

    // Parse MongoDB log (JSON format)
    static std::vector<DatabaseLogEntry> parseMongoDBLog(
        const std::string& content, const std::string& filePath = "");

    // Parse Redis log
    static std::vector<DatabaseLogEntry> parseRedisLog(
        const std::string& content, const std::string& filePath = "");

    // Auto-detect and parse
    static std::vector<DatabaseLogEntry> parseAuto(
        const std::string& content, const std::string& filePath);

    // Security analysis
    static std::vector<DatabaseSecurityFinding> analyzeSecurity(
        const std::vector<DatabaseLogEntry>& entries);

private:
    // MySQL timestamp: 2024-01-15T10:30:00.000000+08:00
    static std::string parseMySQLTimestamp(const std::string& line);
    // PostgreSQL timestamp: 2024-01-15 10:30:00.000 CST
    static std::string parsePostgresTimestamp(const std::string& line);
    // MongoDB timestamp: {"t":{"$date":"2024-01-15T10:30:00.000+08:00"}}
    static std::string parseMongoTimestamp(const std::string& line);
    // Redis timestamp: 12345:M 15 Jan 2024 10:30:00.000
    static std::string parseRedisTimestamp(const std::string& line);

    static DatabaseType detectMySQLComponent(const std::string& line);
    static bool isSuspiciousQuery(const std::string& query);
    static bool isAuthFailure(const DatabaseLogEntry& entry);
};

} // namespace linux
} // namespace forensics

#endif // DATABASE_LOG_PARSER_H
