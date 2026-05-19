// DatabaseLogParser.cpp
// Parser for database service logs (MySQL, PostgreSQL, MongoDB, Redis)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#include "DatabaseLogParser.h"
#include <sstream>
#include <algorithm>
#include <regex>

namespace forensics {
namespace linux {

// ============================================================================
// Auto-detection
// ============================================================================

DatabaseType DatabaseLogParser::detectDatabaseType(const std::string& filePath) {
    std::string lower = filePath;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower.find("mysql") != std::string::npos) return DatabaseType::MySQL;
    if (lower.find("mariadb") != std::string::npos) return DatabaseType::MariaDB;
    if (lower.find("postgresql") != std::string::npos || lower.find("postgres") != std::string::npos) return DatabaseType::PostgreSQL;
    if (lower.find("mongodb") != std::string::npos || lower.find("mongod") != std::string::npos) return DatabaseType::MongoDB;
    if (lower.find("redis") != std::string::npos) return DatabaseType::Redis;

    return DatabaseType::Unknown;
}

std::vector<DatabaseLogEntry> DatabaseLogParser::parseAuto(
    const std::string& content, const std::string& filePath) {
    DatabaseType type = detectDatabaseType(filePath);

    switch (type) {
        case DatabaseType::MySQL:
        case DatabaseType::MariaDB:
            return parseMySQLLog(content, filePath);
        case DatabaseType::PostgreSQL:
            return parsePostgreSQLLog(content, filePath);
        case DatabaseType::MongoDB:
            return parseMongoDBLog(content, filePath);
        case DatabaseType::Redis:
            return parseRedisLog(content, filePath);
        default:
            // Try to detect from content
            if (content.find("InnoDB:") != std::string::npos ||
                content.find("[Note]") != std::string::npos ||
                content.find("[Warning]") != std::string::npos) {
                return parseMySQLLog(content, filePath);
            }
            if (content.find("LOG:") != std::string::npos && content.find("PostgreSQL") != std::string::npos) {
                return parsePostgreSQLLog(content, filePath);
            }
            if (content.find("\"t\":{\"$date\"") != std::string::npos) {
                return parseMongoDBLog(content, filePath);
            }
            if (content.find("Redis version=") != std::string::npos ||
                content.find(":M ") != std::string::npos || content.find(":S ") != std::string::npos) {
                return parseRedisLog(content, filePath);
            }
            return {};
    }
}

// ============================================================================
// MySQL/MariaDB Log Parser
// ============================================================================

// MySQL error log format: 2024-01-15T10:30:00.000000+08:00 0 [Note] ...
// Older format: 240115 10:30:00 [Note] ...
std::vector<DatabaseLogEntry> DatabaseLogParser::parseMySQLLog(
    const std::string& content, const std::string& filePath) {
    std::vector<DatabaseLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        DatabaseLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.dbType = DatabaseType::MySQL;
        entry.provenance.parserName = "DatabaseLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // MySQL 8.x format: 2024-01-15T10:30:00.000000+08:00 0 [Note] ...
        static std::regex mysql8Regex(R"(^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})\s+\d+\s+\[(\w+)\]\s+(.*)$)");
        // Older format: 240115 10:30:00 [Note] ...
        static std::regex mysqlOldRegex(R"(^(\d{6}\s+\d{1,2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.*)$)");

        std::smatch match;
        if (std::regex_match(line, match, mysql8Regex)) {
            entry.timestamp = match[1].str();
            entry.severity = match[2].str();
            std::transform(entry.severity.begin(), entry.severity.end(), entry.severity.begin(), ::tolower);
            entry.message = match[3].str();
        } else if (std::regex_match(line, match, mysqlOldRegex)) {
            entry.timestamp = match[1].str();
            entry.severity = match[2].str();
            std::transform(entry.severity.begin(), entry.severity.end(), entry.severity.begin(), ::tolower);
            entry.message = match[3].str();
        } else {
            continue;
        }

        // Extract component from message prefix (e.g., "InnoDB:", "Server", etc.)
        size_t colonPos = entry.message.find(':');
        if (colonPos != std::string::npos && colonPos < 30) {
            entry.component = entry.message.substr(0, colonPos);
        }

        // Extract client address if present
        static std::regex clientRegex(R"(host:\s*([\d.]+)\s*port:\s*(\d+))");
        std::smatch clientMatch;
        if (std::regex_search(entry.message, clientMatch, clientRegex)) {
            entry.clientAddr = clientMatch[1].str() + ":" + clientMatch[2].str();
        }

        // Extract user if present
        static std::regex userRegex(R"(user:\s*['\"]?(\w+)['\"]?)");
        std::smatch userMatch;
        if (std::regex_search(entry.message, userMatch, userRegex)) {
            entry.username = userMatch[1].str();
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// PostgreSQL Log Parser
// ============================================================================

// PostgreSQL format: 2024-01-15 10:30:00.000 CST [12345]: [1-1] user=admin,db=mydb,app=psql,client=127.0.0.1 LOG:  statement: SELECT ...
std::vector<DatabaseLogEntry> DatabaseLogParser::parsePostgreSQLLog(
    const std::string& content, const std::string& filePath) {
    std::vector<DatabaseLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    // Regex: timestamp [pid]: [line] user=...,db=..., LOG/ERROR/WARNING: message
    static std::regex pgRegex(R"(^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\w+)\s+\[(\d+)\]:\s+\[\d+-\d+\]\s+(?:user=(\w+),db=(\w+))?.*?\s+(LOG|ERROR|WARNING|NOTICE|FATAL|PANIC|DEBUG\d?):\s+(.*)$)");
    // Simpler format without user/db: 2024-01-15 10:30:00.000 CST [12345]: LOG:  message
    static std::regex pgSimpleRegex(R"(^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\w+)\s+\[(\d+)\]:\s+(LOG|ERROR|WARNING|NOTICE|FATAL|PANIC|DEBUG\d?):\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        DatabaseLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.dbType = DatabaseType::PostgreSQL;
        entry.provenance.parserName = "DatabaseLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, pgRegex)) {
            entry.timestamp = match[1].str();
            entry.username = match[3].str();
            entry.database = match[4].str();
            entry.severity = match[5].str();
            std::transform(entry.severity.begin(), entry.severity.end(), entry.severity.begin(), ::tolower);
            entry.message = match[6].str();
        } else if (std::regex_match(line, match, pgSimpleRegex)) {
            entry.timestamp = match[1].str();
            entry.severity = match[3].str();
            std::transform(entry.severity.begin(), entry.severity.end(), entry.severity.begin(), ::tolower);
            entry.message = match[4].str();
        } else {
            continue;
        }

        // Extract client address
        static std::regex clientRegex(R"(client=(\d+\.\d+\.\d+\.\d+))");
        std::smatch clientMatch;
        if (std::regex_search(entry.message, clientMatch, clientRegex)) {
            entry.clientAddr = clientMatch[1].str();
        }

        // Extract SQL query
        if (entry.message.find("statement:") == 0) {
            entry.query = entry.message.substr(11);
        } else if (entry.message.find("execute ") != std::string::npos) {
            size_t colonPos = entry.message.find(':');
            if (colonPos != std::string::npos) {
                entry.query = entry.message.substr(colonPos + 2);
            }
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// MongoDB Log Parser
// ============================================================================

// MongoDB format (JSON): {"t":{"$date":"2024-01-15T10:30:00.000+08:00"},"s":"I","c":"NETWORK","id":51800,"ctx":"conn123","msg":"connection accepted","attr":{...}}
std::vector<DatabaseLogEntry> DatabaseLogParser::parseMongoDBLog(
    const std::string& content, const std::string& filePath) {
    std::vector<DatabaseLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        // MongoDB log lines are JSON objects
        if (line[0] != '{') continue;

        DatabaseLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.dbType = DatabaseType::MongoDB;
        entry.provenance.parserName = "DatabaseLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // Simple JSON field extraction (no full JSON parser needed)
        // Extract timestamp: "t":{"$date":"..."}
        size_t datePos = line.find("\"$date\":\"");
        if (datePos != std::string::npos) {
            datePos += 9;
            size_t endPos = line.find('"', datePos);
            if (endPos != std::string::npos) {
                entry.timestamp = line.substr(datePos, endPos - datePos);
            }
        }

        // Extract severity: "s":"I" / "W" / "E" / "F"
        size_t sPos = line.find("\"s\":\"");
        if (sPos != std::string::npos) {
            sPos += 5;
            std::string sev = line.substr(sPos, 1);
            if (sev == "F" || sev == "E") entry.severity = "error";
            else if (sev == "W") entry.severity = "warning";
            else if (sev == "I") entry.severity = "info";
            else if (sev == "D") entry.severity = "debug";
        }

        // Extract component: "c":"NETWORK"
        size_t cPos = line.find("\"c\":\"");
        if (cPos != std::string::npos) {
            cPos += 5;
            size_t endPos = line.find('"', cPos);
            if (endPos != std::string::npos) {
                entry.component = line.substr(cPos, endPos - cPos);
            }
        }

        // Extract message: "msg":"..."
        size_t msgPos = line.find("\"msg\":\"");
        if (msgPos != std::string::npos) {
            msgPos += 7;
            size_t endPos = msgPos;
            while (endPos < line.size() && !(line[endPos] == '"' && line[endPos - 1] != '\\')) {
                endPos++;
            }
            if (endPos < line.size()) {
                entry.message = line.substr(msgPos, endPos - msgPos);
            }
        }

        // Extract client address from attr
        size_t clientPos = line.find("\"client\":\"");
        if (clientPos != std::string::npos) {
            clientPos += 10;
            size_t endPos = line.find('"', clientPos);
            if (endPos != std::string::npos) {
                entry.clientAddr = line.substr(clientPos, endPos - clientPos);
            }
        }

        // Extract user from attr
        size_t userPos = line.find("\"user\":\"");
        if (userPos != std::string::npos) {
            userPos += 8;
            size_t endPos = line.find('"', userPos);
            if (endPos != std::string::npos) {
                entry.username = line.substr(userPos, endPos - userPos);
            }
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Redis Log Parser
// ============================================================================

// Redis format: 12345:M 15 Jan 2024 10:30:00.000 * message
// or: 12345:M 15 Jan 2024 10:30:00.000 # Warning message
std::vector<DatabaseLogEntry> DatabaseLogParser::parseRedisLog(
    const std::string& content, const std::string& filePath) {
    std::vector<DatabaseLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    // Redis log regex: PID:ROLE DATE TIME LEVEL message
    static std::regex redisRegex(R"(^\d+:[MS]\s+(\d+\s+\w+\s+\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+([*.#])\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        DatabaseLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.dbType = DatabaseType::Redis;
        entry.provenance.parserName = "DatabaseLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, redisRegex)) {
            entry.timestamp = match[1].str();
            std::string level = match[2].str();
            entry.message = match[3].str();

            if (level == "#") entry.severity = "warning";
            else if (level == "*") entry.severity = "info";
            else entry.severity = "debug";
        } else {
            continue;
        }

        // Extract client info from message
        static std::regex clientRegex(R"(client=\d+\s+\S+\s+addr=([\d.]+:\d+))");
        std::smatch clientMatch;
        if (std::regex_search(entry.message, clientMatch, clientRegex)) {
            entry.clientAddr = clientMatch[1].str();
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Security Analysis
// ============================================================================

bool DatabaseLogParser::isSuspiciousQuery(const std::string& query) {
    static const std::vector<std::string> suspiciousPatterns = {
        "DROP TABLE", "DROP DATABASE", "TRUNCATE", "DELETE FROM",
        "GRANT ALL", "CREATE USER", "ALTER USER", "SET PASSWORD",
        "UNION SELECT", "OR 1=1", "OR '1'='1", "--", "/*",
        "xp_cmdshell", "LOAD_FILE", "INTO OUTFILE", "INTO DUMPFILE",
        "BENCHMARK(", "SLEEP(", "WAITFOR DELAY", "pg_sleep",
        "db.adminCommand", "db.eval", "$where"
    };

    std::string upper = query;
    std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);

    for (const auto& pattern : suspiciousPatterns) {
        std::string upperPattern = pattern;
        std::transform(upperPattern.begin(), upperPattern.end(), upperPattern.begin(), ::toupper);
        if (upper.find(upperPattern) != std::string::npos) {
            return true;
        }
    }
    return false;
}

bool DatabaseLogParser::isAuthFailure(const DatabaseLogEntry& entry) {
    std::string lower = entry.message;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    return lower.find("access denied") != std::string::npos ||
           lower.find("authentication failed") != std::string::npos ||
           lower.find("password authentication failed") != std::string::npos ||
           lower.find("auth error") != std::string::npos ||
           lower.find("login failed") != std::string::npos ||
           lower.find("connection refused") != std::string::npos;
}

std::vector<DatabaseSecurityFinding> DatabaseLogParser::analyzeSecurity(
    const std::vector<DatabaseLogEntry>& entries) {
    std::vector<DatabaseSecurityFinding> findings;

    // Track auth failures per client
    std::map<std::string, int> authFailureCount;

    for (const auto& entry : entries) {
        // Auth failures
        if (isAuthFailure(entry)) {
            DatabaseSecurityFinding f;
            f.findingType = "auth_failure";
            f.severity = "high";
            f.description = "Database authentication failure";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.dbType = entry.dbType;
            f.username = entry.username;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "DatabaseLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);

            if (!entry.clientAddr.empty()) {
                authFailureCount[entry.clientAddr]++;
            }
        }

        // Suspicious queries
        if (!entry.query.empty() && isSuspiciousQuery(entry.query)) {
            DatabaseSecurityFinding f;
            f.findingType = "suspicious_query";
            f.severity = "high";
            f.description = "Suspicious database query detected";
            f.evidence = "Query: " + entry.query;
            f.sourceFile = entry.sourceFile;
            f.dbType = entry.dbType;
            f.username = entry.username;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "DatabaseLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Configuration warnings
        std::string lower = entry.message;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower.find("bound to") != std::string::npos && lower.find("0.0.0.0") != std::string::npos) {
            DatabaseSecurityFinding f;
            f.findingType = "config_weakness";
            f.severity = "high";
            f.description = "Database bound to all interfaces (0.0.0.0)";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.dbType = entry.dbType;
            f.provenance.parserName = "DatabaseLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Replication issues
        if (lower.find("replication") != std::string::npos &&
            (lower.find("error") != std::string::npos || lower.find("stopped") != std::string::npos)) {
            DatabaseSecurityFinding f;
            f.findingType = "replication_error";
            f.severity = "medium";
            f.description = "Database replication error";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.dbType = entry.dbType;
            f.provenance.parserName = "DatabaseLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }
    }

    // Brute force detection: more than 5 auth failures from same client
    for (const auto& [client, count] : authFailureCount) {
        if (count >= 5) {
            DatabaseSecurityFinding f;
            f.findingType = "auth_failure";
            f.severity = "critical";
            f.description = "Possible brute force attack: " + std::to_string(count) + " auth failures from " + client;
            f.evidence = "Client: " + client + ", Failures: " + std::to_string(count);
            f.clientAddr = client;
            f.provenance.parserName = "DatabaseLogParser";
            f.provenance.parserVersion = "1.0.0";
            findings.push_back(f);
        }
    }

    return findings;
}

} // namespace linux
} // namespace forensics
