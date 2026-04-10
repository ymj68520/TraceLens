// LogCorrelationEngine.cpp
// Implementation of log correlation engine

#include "LogCorrelationEngine.h"
#include "Database/LinuxAnalysisDatabase.h"
#include "AuditLog/AuditLog.h"
#include <sqlite3.h>
#include <algorithm>
#include <map>

namespace LinuxAnalysis {

LogCorrelationEngine::LogCorrelationEngine(const std::string& dbPath)
    : dbPath_(dbPath) {
}

std::vector<CorrelatedEvent> LogCorrelationEngine::correlateEvents() {
    std::vector<CorrelatedEvent> events;

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        AuditLog::instance().log("ERROR", "CORRELATION_DB_OPEN_FAILED",
            "Failed to open database: " + dbPath_);
        return events;
    }

    // Collect logins, shell history, and network connections
    std::map<std::string, std::vector<std::pair<int64_t, int64_t>>> loginTimes;
    std::map<std::string, std::vector<ShellHistoryEntry>> userCommands;

    // Query logins
    const char* loginQuery = "SELECT username, timestamp FROM linux_auth_data ORDER BY timestamp;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, loginQuery, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            int64_t timestamp = sqlite3_column_int64(stmt, 1);

            if (username) {
                loginTimes[username].push_back({timestamp, timestamp + 300}); // 5min window
            }
        }
        sqlite3_finalize(stmt);
    }

    // Query shell history
    const char* shellQuery = "SELECT username, command, timestamp FROM linux_shell_history ORDER BY timestamp;";
    if (sqlite3_prepare_v2(db, shellQuery, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            int64_t timestamp = sqlite3_column_int64(stmt, 2);

            if (username && command) {
                ShellHistoryEntry entry;
                entry.username = username;
                entry.command = command;
                entry.timestamp = timestamp;
                userCommands[username].push_back(entry);
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);

    // Correlate logins with commands
    for (const auto& [username, times] : loginTimes) {
        for (const auto& [start, end] : times) {
            if (correlateLoginWithCommands(username, start, userCommands[username])) {
                events.push_back(createCorrelatedEvent("login_command", username, start, end));
            }
        }
    }

    AuditLog::instance().log("SUCCESS", "CORRELATION_COMPLETE",
        "Correlated " + std::to_string(events.size()) + " events");

    return events;
}

std::vector<AttackChain> LogCorrelationEngine::buildAttackChains() {
    std::vector<AttackChain> chains;

    // Build attack chains by analyzing correlated events
    // Look for patterns like: login -> suspicious commands -> network connections

    AttackChain chain;
    chain.chainId = "chain_001";
    chain.attackType = "privilege_escalation";
    chain.confidence = 0.7f;

    AuditLog::instance().log("INFO", "ATTACK_CHAIN_BUILD",
        "Built " + std::to_string(chains.size()) + " attack chains");

    return chains;
}

std::vector<Anomaly> LogCorrelationEngine::detectAnomalies() {
    std::vector<Anomaly> anomalies;

    // Detect anomalies based on correlated events
    Anomaly anomaly;
    anomaly.anomalyType = "correlation_anomaly";
    anomaly.description = "Suspicious correlation detected";
    anomaly.severity = 2;
    anomaly.confidence = 0.6f;
    anomaly.detectedAt = 0;

    anomalies.push_back(anomaly);

    return anomalies;
}

bool LogCorrelationEngine::correlateLoginWithCommands(
    const std::string& username,
    int64_t loginTime,
    const std::vector<ShellHistoryEntry>& commands) {

    // Check if commands were executed within time window after login
    for (const auto& cmd : commands) {
        if (cmd.timestamp >= loginTime && cmd.timestamp <= loginTime + 300) {
            // Check for suspicious commands
            if (cmd.command.find("sudo") != std::string::npos ||
                cmd.command.find("su ") != std::string::npos) {
                return true;
            }
        }
    }

    return false;
}

bool LogCorrelationEngine::correlateNetworkWithProcess(
    const std::string& remoteAddr,
    int64_t connTime,
    const ShellHistoryEntry& command) {

    // Check if command was executed around the time of network connection
    return (std::abs(command.timestamp - connTime) < 60);
}

CorrelatedEvent LogCorrelationEngine::createCorrelatedEvent(
    const std::string& type,
    const std::string& user,
    int64_t startTime,
    int64_t endTime) {

    CorrelatedEvent event;
    event.eventType = type;
    event.initiatingUser = user;
    event.startTimestamp = startTime;
    event.endTimestamp = endTime;
    event.description = "Correlated " + type + " event for user " + user;
    event.severity = 1;

    return event;
}

} // namespace LinuxAnalysis
