// SetuidAnalyzer.h
// Analyzer for setuid/setgid files on Linux systems

#pragma once
#ifndef SETUID_ANALYZER_H
#define SETUID_ANALYZER_H

#include <string>
#include <vector>
#include <unordered_set>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Analyzer for setuid/setgid files
 *
 * Scans filesystem for setuid/setgid files and flags suspicious ones.
 * Suspicious indicators:
 * - Files in temporary directories (tmp, var/tmp)
 * - Files owned by non-root users in system directories
 * - Recently created setuid files
 * - Files not in known-good whitelist
 */
class SetuidAnalyzer {
public:
    /**
     * @brief Analysis result structure
     */
    struct AnalysisResult {
        std::vector<SetuidFileInfo> setuidFiles;
        std::vector<SetuidFileInfo> setgidFiles;
        std::vector<SetuidFileInfo> suspiciousFiles;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Analyze setuid/setgid files from file listing
     *
     * Parses file listing (typically from 'find' command output) and
     * identifies files with setuid/setgid bits set.
     *
     * @param fileListPath Path to file containing find output
     * @return AnalysisResult containing discovered setuid/setgid files
     */
    static AnalysisResult analyzeSetuidFiles(const std::string& fileListPath);

    /**
     * @brief Parse find command output directly
     *
     * @param findOutput Output from 'find / -perm -4000 -o -perm -2000 -ls'
     * @return AnalysisResult containing discovered setuid/setgid files
     */
    static AnalysisResult parseFindOutput(const std::string& findOutput);

    /**
     * @brief Flag suspicious setuid/setgid files
     *
     * Identifies files that match suspicious indicators:
     * - Located in temporary directories
     * - Owned by non-root in system directories
     * - Not in known-good whitelist
     *
     * @param files Vector of setuid/setgid files to analyze
     * @return Vector of suspicious files with reasons
     */
    static std::vector<SetuidFileInfo> flagSuspiciousFiles(std::vector<SetuidFileInfo>& files);

    /**
     * @brief Check if a file path is in the known-good whitelist
     *
     * @param filePath Full path to check
     * @return true if file is in whitelist, false otherwise
     */
    static bool isKnownGoodFile(const std::string& filePath);

private:
    /**
     * @brief Parse a line from find -ls output
     *
     * Format: inode permissions owner group size month day time path
     * Example: 12345 -rwsr-xr-x root root 45000 Jan 1 12:00 /usr/bin/sudo
     */
    static SetuidFileInfo parseFindLine(const std::string& line);

    /**
     * @brief Parse permissions string to extract setuid/setgid bits
     *
     * @param permissions Permission string (e.g., "-rwsr-xr-x")
     * @param isSetuid Output parameter for setuid bit
     * @param isSetgid Output parameter for setgid bit
     */
    static void parsePermissions(const std::string& permissions, bool& isSetuid, bool& isSetgid);

    /**
     * @brief Check if file is in a suspicious location
     *
     * @param filePath File path to check
     * @return true if in suspicious location, false otherwise
     */
    static bool isInSuspiciousLocation(const std::string& filePath);

    /**
     * @brief Check if file owner is suspicious for its location
     *
     * @param filePath File path
     * @param owner File owner
     * @return true if owner is suspicious for location, false otherwise
     */
    static bool hasSuspiciousOwner(const std::string& filePath, const std::string& owner);

    // Known-good setuid/setgid files whitelist
    static const std::unordered_set<std::string> KNOWN_SETUID_FILES;
};

} // namespace LinuxAnalysis

#endif // SETUID_ANALYZER_H
