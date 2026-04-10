// AppArmorParser.h
// Parser for AppArmor profiles and violations

#pragma once
#ifndef APPARMOR_PARSER_H
#define APPARMOR_PARSER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Parser for AppArmor security profiles and violations
 *
 * Parses AppArmor profile definitions and extracts violation information
 * from system logs.
 */
class AppArmorParser {
public:
    /**
     * @brief Parse result structure
     */
    struct ParseResult {
        std::vector<AppArmorProfile> profiles;
        std::vector<AppArmorViolation> violations;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Parse AppArmor profiles from directory
     *
     * Parses profile files from /etc/apparmor.d/ directory.
     *
     * @param apparmorDir Path to AppArmor profiles directory
     * @return ParseResult containing parsed profiles
     */
    static ParseResult parseProfiles(const std::string& apparmorDir);

    /**
     * @brief Parse single AppArmor profile file
     *
     * @param profilePath Path to profile file
     * @return AppArmorProfile structure
     */
    static AppArmorProfile parseProfileFile(const std::string& profilePath);

    /**
     * @brief Parse profile from content string
     *
     * @param content Profile file content
     * @param filePath Source file path
     * @return AppArmorProfile structure
     */
    static AppArmorProfile parseProfileContent(const std::string& content,
                                               const std::string& filePath);

    /**
     * @brief Extract AppArmor violations from log file
     *
     * Parses syslog or auth.log for AppArmor violation messages.
     *
     * @param logPath Path to log file
     * @return ParseResult containing extracted violations
     */
    static ParseResult extractViolations(const std::string& logPath);

    /**
     * @brief Parse AppArmor violation from log line
     *
     * @param line Log line containing violation
     * @return AppArmorViolation structure
     */
    static AppArmorViolation parseViolationLine(const std::string& line);

    /**
     * @brief Parse profile declaration line (for testing)
     *
     * Format: profile name { or profile name flags {
     */
    static std::string parseProfileDeclaration(const std::string& line);

    /**
     * @brief Parse file access rule (for testing)
     *
     * Formats:
     * /path/to/file r,
     * /path/to/file rw,
     * deny /path/to/file w,
     */
    static void parseFileRule(const std::string& rule,
                             AppArmorProfile& profile);

private:
    /**
     * @brief Extract profile flags from declaration
     *
     * Flags: enforce, complain, attach_disconnected, etc.
     */
    static std::string parseProfileFlags(const std::string& declaration);

    /**
     * @brief Parse violation message components
     *
     * Extracts profile, operation, target path, etc.
     */
    static bool parseViolationMessage(const std::string& line,
                                      AppArmorViolation& violation);

    /**
     * @brief Extract timestamp from log line
     *
     * Supports syslog format timestamps
     */
    static int64_t extractLogTimestamp(const std::string& line);
};

} // namespace LinuxAnalysis

#endif // APPARMOR_PARSER_H
