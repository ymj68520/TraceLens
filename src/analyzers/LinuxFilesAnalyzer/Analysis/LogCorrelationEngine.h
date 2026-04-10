// LogCorrelationEngine.h
// Correlates events across multiple Linux log sources

#pragma once
#ifndef LOG_CORRELATION_ENGINE_H
#define LOG_CORRELATION_ENGINE_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Engine for correlating events across Linux log sources
 *
 * Correlates authentication events, command execution, and network
 * activity to build comprehensive attack chains.
 */
class LogCorrelationEngine {
public:
    /**
     * @brief Analysis result structure
     */
    struct CorrelationResult {
        std::vector<CorrelatedEvent> events;
        std::vector<AttackChain> attackChains;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Construct correlation engine
     *
     * @param dbPath Path to Linux analysis database
     */
    explicit LogCorrelationEngine(const std::string& dbPath);

    /**
     * @brief Correlate events across multiple log sources
     *
     * Analyzes relationships between logins, commands, network
     * connections, and file access patterns.
     *
     * @return Vector of correlated events
     */
    std::vector<CorrelatedEvent> correlateEvents();

    /**
     * @brief Build attack chains from correlated events
     *
     * Identifies sequences of related events that form attack patterns
     * such as reconnaissance, exploitation, privilege escalation, and
     * data exfiltration.
     *
     * @return Vector of detected attack chains
     */
    std::vector<AttackChain> buildAttackChains();

    /**
     * @brief Detect specific attack patterns
     *
     * @return Vector of detected anomalies
     */
    std::vector<Anomaly> detectAnomalies();

private:
    std::string dbPath_;

    // Correlation rules
    bool correlateLoginWithCommands(const std::string& username,
                                     int64_t loginTime,
                                     const std::vector<ShellHistoryEntry>& commands);

    bool correlateNetworkWithProcess(const std::string& remoteAddr,
                                      int64_t connTime,
                                      const ShellHistoryEntry& command);

    // Helper methods
    CorrelatedEvent createCorrelatedEvent(const std::string& type,
                                           const std::string& user,
                                           int64_t startTime,
                                           int64_t endTime);
};

} // namespace LinuxAnalysis

#endif // LOG_CORRELATION_ENGINE_H
