// CapabilityAnalyzer.h
// Analyzer for Linux file capabilities

#pragma once
#ifndef CAPABILITY_ANALYZER_H
#define CAPABILITY_ANALYZER_H

#include <string>
#include <vector>
#include <unordered_set>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Analyzer for Linux capabilities
 *
 * Parses file capabilities from getcap output and identifies dangerous capabilities.
 * Linux capabilities provide fine-grained privilege splitting beyond setuid/setgid.
 */
class CapabilityAnalyzer {
public:
    /**
     * @brief Analysis result structure
     */
    struct AnalysisResult {
        std::vector<FileCapability> capabilities;
        std::vector<FileCapability> dangerousCapabilities;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Parse file capabilities from getcap output
     *
     * Parses output from: getcap -r /
     * Format: /path/to/file = cap_capability_set+flags
     *
     * @param getcapOutput Output from getcap command
     * @return AnalysisResult containing discovered capabilities
     */
    static AnalysisResult parseFileCapabilities(const std::string& getcapOutput);

    /**
     * @brief Parse file capabilities from a file
     *
     * @param filePath Path to file containing getcap output
     * @return AnalysisResult containing discovered capabilities
     */
    static AnalysisResult parseFileCapabilitiesFromFile(const std::string& filePath);

    /**
     * @brief Flag files with dangerous capabilities
     *
     * Identifies capabilities that pose security risks:
     * - CAP_SETUID, CAP_SETGID: privilege escalation
     * - CAP_SYS_ADMIN, CAP_SYS_MODULE: system administration
     * - CAP_NET_RAW, CAP_NET_ADMIN: network operations
     * - CAP_SYS_CHROOT, CAP_SYS_PTRACE: system operations
     *
     * @param caps Vector of file capabilities to analyze
     * @return Vector of files with dangerous capabilities
     */
    static std::vector<FileCapability> flagDangerousCapabilities(std::vector<FileCapability>& caps);

    /**
     * @brief Check if a capability is dangerous
     *
     * @param capability Capability name (e.g., "cap_setuid")
     * @return true if capability is dangerous, false otherwise
     */
    static bool isDangerousCapability(const std::string& capability);

private:
    /**
     * @brief Parse a single line from getcap output
     *
     * Format: /path/to/file = cap_net_raw+ep
     */
    static FileCapability parseCapLine(const std::string& line);

    /**
     * @brief Parse capability set string
     *
     * Extracts individual capabilities from comma-separated list
     * e.g., "cap_net_raw,cap_net_admin+ep" -> ["cap_net_raw", "cap_net_admin"]
     */
    static std::vector<std::string> parseCapabilitySet(const std::string& capSet);

    /**
     * @brief Parse capability flags
     *
     * Flags:
     * - e: effective
     * - i: inheritable
     * - p: permitted
     */
    static std::string parseCapabilityFlags(const std::string& flags);

    // Dangerous capabilities that require special attention
    static const std::unordered_set<std::string> DANGEROUS_CAPABILITIES;
};

} // namespace LinuxAnalysis

#endif // CAPABILITY_ANALYZER_H
