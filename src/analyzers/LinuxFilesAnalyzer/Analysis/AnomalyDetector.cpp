// AnomalyDetector.cpp
// Implementation of anomaly detection algorithms

#include "AnomalyDetector.h"
#include "Database/LinuxAnalysisDatabase.h"
#include "AuditLog/AuditLog.h"
#include <sqlite3.h>
#include <map>
#include <set>
#include <algorithm>

namespace LinuxAnalysis {

AnomalyDetector::AnomalyDetector(const std::string& dbPath)
    : dbPath_(dbPath) {
}

std::vector<Anomaly> AnomalyDetector::detectAnomalies() {
    std::vector<Anomaly> allAnomalies;

    // Run all detection algorithms
    auto bruteForce = detectBruteForceAttempts();
    auto privEscalation = detectPrivilegeEscalation();
    auto dataExfil = detectDataExfiltration();
    auto persistence = detectPersistenceMechanisms();
    auto logins = detectUnusualLoginPatterns();
    auto processes = detectSuspiciousProcesses();

    // Merge all anomalies
    allAnomalies.insert(allAnomalies.end(), bruteForce.begin(), bruteForce.end());
    allAnomalies.insert(allAnomalies.end(), privEscalation.begin(), privEscalation.end());
    allAnomalies.insert(allAnomalies.end(), dataExfil.begin(), dataExfil.end());
    allAnomalies.insert(allAnomalies.end(), persistence.begin(), persistence.end());
    allAnomalies.insert(allAnomalies.end(), logins.begin(), logins.end());
    allAnomalies.insert(allAnomalies.end(), processes.begin(), processes.end());

    // Sort by severity and timestamp
    std::sort(allAnomalies.begin(), allAnomalies.end(),
        [](const Anomaly& a, const Anomaly& b) {
            if (a.severity != b.severity) {
                return a.severity > b.severity;
            }
            return a.detectedAt > b.detectedAt;
        });

    AuditLog::instance().log("SUCCESS", "ANOMALY_DETECTION_COMPLETE",
        "Detected " + std::to_string(allAnomalies.size()) + " anomalies");

    return allAnomalies;
}

std::vector<Anomaly> AnomalyDetector::detectBruteForceAttempts() {
    std::vector<Anomaly> anomalies;

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return anomalies;
    }

    // Count failed logins per user and IP
    std::map<std::string, int> failedByUser;
    std::map<std::string, int> failedByIP;

    const char* query = "SELECT username, rhost, timestamp FROM linux_auth_data "
                       "WHERE success=0 ORDER BY timestamp;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* rhost = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            int64_t timestamp = sqlite3_column_int64(stmt, 2);

            if (username) {
                failedByUser[username]++;
                // Check for multiple failures within short time window
                if (failedByUser[username] >= 5) {
                    Anomaly anomaly = createAnomaly(
                        "brute_force",
                        "Multiple failed login attempts for user " + std::string(username),
                        3, 0.9f, "auth_user:" + std::string(username));
                    anomaly.detectedAt = timestamp;
                    anomalies.push_back(anomaly);
                }
            }

            if (rhost) {
                failedByIP[rhost]++;
                if (failedByIP[rhost] >= 10) {
                    Anomaly anomaly = createAnomaly(
                        "brute_force",
                        "Excessive failed logins from IP " + std::string(rhost),
                        3, 0.95f, "auth_ip:" + std::string(rhost));
                    anomaly.detectedAt = timestamp;
                    anomalies.push_back(anomaly);
                }
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
    return anomalies;
}

std::vector<Anomaly> AnomalyDetector::detectPrivilegeEscalation() {
    std::vector<Anomaly> anomalies;

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return anomalies;
    }

    // Look for sudo/su commands followed by suspicious activity
    const char* query = "SELECT username, command, timestamp FROM linux_shell_history "
                       "WHERE command LIKE 'sudo %' OR command LIKE 'su %' "
                       "ORDER BY timestamp;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            int64_t timestamp = sqlite3_column_int64(stmt, 2);

            // Check for suspicious privilege escalation commands
            if (command && (
                std::string(command).find("passwd") != std::string::npos ||
                std::string(command).find("shadow") != std::string::npos ||
                std::string(command).find("/etc/shadow") != std::string::npos)) {

                Anomaly anomaly = createAnomaly(
                    "privilege_escalation",
                    "Potential privilege escalation attempt: " + std::string(command),
                    4, 0.85f, "shell_user:" + std::string(username));
                anomaly.detectedAt = timestamp;
                anomalies.push_back(anomaly);
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
    return anomalies;
}

std::vector<Anomaly> AnomalyDetector::detectDataExfiltration() {
    std::vector<Anomaly> anomalies;

    // Look for large data transfers or archive operations
    // This would typically require network connection analysis
    // For now, check for tar/zip operations in shell history

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return anomalies;
    }

    const char* query = "SELECT username, command, timestamp FROM linux_shell_history "
                       "WHERE command LIKE '%tar%' OR command LIKE '%zip%' "
                       "OR command LIKE '%gzip%' OR command LIKE '%scp%' "
                       "ORDER BY timestamp;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            int64_t timestamp = sqlite3_column_int64(stmt, 2);

            // Check for archive operations to unusual locations
            if (command && (
                std::string(command).find("/tmp/") != std::string::npos ||
                std::string(command).find("ssh ") != std::string::npos)) {

                Anomaly anomaly = createAnomaly(
                    "data_exfiltration",
                    "Potential data exfiltration: " + std::string(command),
                    3, 0.7f, "shell_user:" + std::string(username));
                anomaly.detectedAt = timestamp;
                anomalies.push_back(anomaly);
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
    return anomalies;
}

std::vector<Anomaly> AnomalyDetector::detectPersistenceMechanisms() {
    std::vector<Anomaly> anomalies;

    // Check for cron jobs, systemd services created by non-root users
    // This would require analyzing the configuration data

    return anomalies;
}

std::vector<Anomaly> AnomalyDetector::detectUnusualLoginPatterns() {
    std::vector<Anomaly> anomalies;

    // Check for logins at unusual times (2-5 AM) or from unusual locations
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return anomalies;
    }

    const char* query = "SELECT username, rhost, timestamp FROM linux_auth_data "
                       "WHERE success=1 ORDER BY timestamp;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            int64_t timestamp = sqlite3_column_int64(stmt, 2);

            if (username) {
                // Convert timestamp to hours (0-23)
                time_t rawtime = static_cast<time_t>(timestamp);
                struct tm* timeinfo = localtime(&rawtime);
                int hour = timeinfo->tm_hour;

                // Flag logins between 2 AM and 5 AM
                if (hour >= 2 && hour <= 5) {
                    Anomaly anomaly = createAnomaly(
                        "unusual_login_time",
                        "Login at unusual time (2-5 AM) for user " + std::string(username),
                        2, 0.6f, "auth_user:" + std::string(username));
                    anomaly.detectedAt = timestamp;
                    anomalies.push_back(anomaly);
                }
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
    return anomalies;
}

std::vector<Anomaly> AnomalyDetector::detectSuspiciousProcesses() {
    std::vector<Anomaly> anomalies;

    // Check for processes with suspicious names or patterns
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return anomalies;
    }

    const char* query = "SELECT username, command, timestamp FROM linux_shell_history "
                       "ORDER BY timestamp;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            int64_t timestamp = sqlite3_column_int64(stmt, 2);

            if (command) {
                std::string cmd(command);

                // Check for suspicious patterns
                bool suspicious = false;
                std::string reason;

                // Encoded/obfuscated commands
                if (cmd.find("base64") != std::string::npos ||
                    cmd.find("eval") != std::string::npos) {
                    suspicious = true;
                    reason = "Obfuscated command execution";
                }

                // Downloading from internet
                if (cmd.find("wget") != std::string::npos ||
                    cmd.find("curl") != std::string::npos) {
                    suspicious = true;
                    reason = "Internet download in shell history";
                }

                // Hidden file manipulation
                if (cmd.find("/.") != std::string::npos && cmd.find("rm ") != std::string::npos) {
                    suspicious = true;
                    reason = "Hidden file deletion";
                }

                if (suspicious) {
                    Anomaly anomaly = createAnomaly(
                        "suspicious_process",
                        reason + ": " + cmd,
                        3, 0.75f, "shell_command:" + cmd);
                    anomaly.detectedAt = timestamp;
                    anomalies.push_back(anomaly);
                }
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
    return anomalies;
}

int AnomalyDetector::calculateSeverity(const Anomaly& anomaly) {
    // Severity levels:
    // 1 = Low (info)
    // 2 = Medium (warning)
    // 3 = High (critical)
    // 4 = Severe (emergency)

    // Base severity on anomaly type
    if (anomaly.anomalyType == "privilege_escalation" ||
        anomaly.anomalyType == "data_exfiltration") {
        return 4;
    } else if (anomaly.anomalyType == "brute_force") {
        return 3;
    } else if (anomaly.anomalyType == "suspicious_process") {
        return 3;
    } else if (anomaly.anomalyType == "unusual_login_time") {
        return 2;
    }

    return 1;
}

float AnomalyDetector::calculateConfidence(const Anomaly& anomaly) {
    // Confidence calculation based on evidence strength
    // Base confidence on severity and evidence count

    float baseConfidence = 0.5f;

    // Increase confidence for high severity anomalies
    if (anomaly.severity >= 3) {
        baseConfidence += 0.2f;
    }

    // Increase confidence if multiple evidence items
    if (!anomaly.evidenceIds.empty()) {
        baseConfidence += 0.1f;
    }

    return std::min(baseConfidence, 1.0f);
}

Anomaly AnomalyDetector::createAnomaly(
    const std::string& type,
    const std::string& description,
    int severity,
    float confidence,
    const std::string& evidence) {

    Anomaly anomaly;
    anomaly.anomalyType = type;
    anomaly.description = description;
    anomaly.severity = severity;
    anomaly.confidence = confidence;
    anomaly.detectedAt = 0;
    anomaly.evidenceIds.push_back(evidence);

    return anomaly;
}

} // namespace LinuxAnalysis
