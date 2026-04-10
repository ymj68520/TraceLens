// SELinuxAnalyzer.h
// Analyzer for SELinux status and AVC denials

#pragma once
#ifndef SELINUX_ANALYZER_H
#define SELINUX_ANALYZER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Analyzer for SELinux (Security-Enhanced Linux)
 *
 * Parses SELinux configuration and extracts AVC (Access Vector Cache)
 * denials from audit logs to identify security policy violations.
 */
class SELinuxAnalyzer {
public:
    /**
     * @brief Analysis result structure
     */
    struct AnalysisResult {
        SELinuxStatus status;
        std::vector<SELinuxAVCDenial> avcDenials;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Parse SELinux status from configuration file
     *
     * Parses /etc/selinux/config to determine SELinux mode and policy.
     *
     * @param configPath Path to SELinux config file (typically /etc/selinux/config)
     * @return AnalysisResult with SELinux status information
     */
    static AnalysisResult parseStatus(const std::string& configPath);

    /**
     * @brief Parse SELinux status from config content string
     *
     * Parses SELinux configuration from a string (for testing purposes).
     *
     * @param configContent SELinux config content as string
     * @return AnalysisResult with SELinux status information
     */
    static AnalysisResult parseStatusFromContent(const std::string& configContent);

    /**
     * @brief Extract AVC denials from audit log
     *
     * Parses audit log file for AVC denial messages.
     *
     * @param auditLogPath Path to audit log file
     * @return AnalysisResult with extracted AVC denials
     */
    static AnalysisResult extractAVCDenials(const std::string& auditLogPath);

    /**
     * @brief Extract AVC denials from audit log content string
     *
     * Parses audit log content for AVC denial messages (for testing purposes).
     *
     * @param auditLogContent Audit log content as string
     * @return AnalysisResult with extracted AVC denials
     */
    static AnalysisResult extractAVCDenialsFromContent(const std::string& auditLogContent);

    /**
     * @brief Parse AVC denial from a single log line
     *
     * @param line Log line containing AVC denial
     * @return SELinuxAVCDenial structure
     */
    static SELinuxAVCDenial parseAVCDenialLine(const std::string& line);

    /**
     * @brief Check if SELinux is enabled
     *
     * @param status SELinux status structure
     * @return true if SELinux is enabled, false otherwise
     */
    static bool isEnabled(const SELinuxStatus& status);

    /**
     * @brief Check if SELinux is in enforcing mode
     *
     * @param status SELinux status structure
     * @return true if enforcing, false if permissive or disabled
     */
    static bool isEnforcing(const SELinuxStatus& status);

private:
    /**
     * @brief Parse SELinux config line
     *
     * Format: KEY=value
     * e.g., SELINUX=enforcing
     */
    static void parseConfigLine(const std::string& line,
                                SELinuxStatus& status);

    /**
     * @brief Extract timestamp from audit message
     *
     * Format: type=AVC msg=audit(1234567890.123:456):
     */
    static int64_t extractAuditTimestamp(const std::string& line);

    /**
     * @brief Parse AVC denial message components
     *
     * Extracts source context, target context, permission, etc.
     */
    static bool parseAVCMessage(const std::string& message,
                                SELinuxAVCDenial& denial);

    /**
     * @brief Extract value from AVC message by key
     *
     * e.g., extract "scontext" from 'scontext="system_u:system_r:httpd_t:s0"'
     */
    static std::string extractAVCField(const std::string& message,
                                       const std::string& key);
};

} // namespace LinuxAnalysis

#endif // SELINUX_ANALYZER_H
