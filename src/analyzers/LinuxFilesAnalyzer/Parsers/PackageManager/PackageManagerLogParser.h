// PackageManagerLogParser.h
// Parser for package manager logs (apt, dpkg, yum, dnf, zypper, pacman, snap, flatpak)
// Phase 9: Package Manager Log Enhancement

#pragma once
#ifndef PACKAGE_MANAGER_LOG_PARSER_H
#define PACKAGE_MANAGER_LOG_PARSER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"

#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Package manager operation types
enum class PackageOperation {
    INSTALL,
    REMOVE,
    UPGRADE,
    DOWNGRADE,
    PURGE,
    REINSTALL,
    HOLD,
    UNHOLD,
    CONFIGURE,
    TRIGGERS,
    UNKNOWN
};

// Package manager log entry
struct PackageLogEntry {
    int64_t timestamp = 0;
    std::string packageManager;     // apt, dpkg, yum, dnf, zypper, pacman, snap, flatpak
    std::string packageName;
    std::string packageVersion;
    std::string architecture;
    PackageOperation operation = PackageOperation::UNKNOWN;
    std::string operationDetail;    // raw operation string
    std::string status;             // installed, removed, upgraded, etc.
    std::string user;               // user who performed the operation
    std::string commandLine;        // command line used
    std::string filePath;
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// Suspicious package finding
struct SuspiciousPackageFinding {
    std::string findingType;        // attack_tool, security_removal, suspicious_install, unusual_time
    std::string severity;           // critical, high, medium, low
    std::string packageName;
    std::string packageVersion;
    std::string description;
    std::string evidence;
    std::string filePath;
    EvidenceProvenance provenance;
};

// Known attack tools and security packages
struct PackagePattern {
    std::string packageName;
    std::string category;           // attack_tool, security_tool, penetration_tool, rootkit
    std::string severity;
    std::string description;
};

class PackageManagerLogParser {
public:
    // APT history.log parsing
    static std::vector<PackageLogEntry> parseAptHistoryLog(
        const std::string& content, const std::string& filePath = "");

    // APT term.log parsing
    static std::vector<PackageLogEntry> parseAptTermLog(
        const std::string& content, const std::string& filePath = "");

    // dpkg.log parsing
    static std::vector<PackageLogEntry> parseDpkgLog(
        const std::string& content, const std::string& filePath = "");

    // yum.log parsing
    static std::vector<PackageLogEntry> parseYumLog(
        const std::string& content, const std::string& filePath = "");

    // dnf.log parsing
    static std::vector<PackageLogEntry> parseDnfLog(
        const std::string& content, const std::string& filePath = "");

    // zypper.log parsing
    static std::vector<PackageLogEntry> parseZypperLog(
        const std::string& content, const std::string& filePath = "");

    // pacman.log parsing
    static std::vector<PackageLogEntry> parsePacmanLog(
        const std::string& content, const std::string& filePath = "");

    // snap change parsing
    static std::vector<PackageLogEntry> parseSnapLog(
        const std::string& content, const std::string& filePath = "");

    // flatpak install parsing
    static std::vector<PackageLogEntry> parseFlatpakLog(
        const std::string& content, const std::string& filePath = "");

    // Auto-detect format and parse
    static std::vector<PackageLogEntry> parsePackageManagerLog(
        const std::string& content, const std::string& filePath = "");

    // Security analysis
    static std::vector<SuspiciousPackageFinding> analyzeSuspiciousPackages(
        const std::vector<PackageLogEntry>& entries);

    // Detect package manager type from content/path
    static std::string detectPackageManagerType(const std::string& content, const std::string& filePath = "");

private:
    // Timestamp parsers
    static int64_t parseAptTimestamp(const std::string& timestampStr);
    static int64_t parseDpkgTimestamp(const std::string& timestampStr);
    static int64_t parseYumTimestamp(const std::string& timestampStr);
    static int64_t parseZypperTimestamp(const std::string& timestampStr);
    static int64_t parsePacmanTimestamp(const std::string& timestampStr);

    // Operation string to enum
    static PackageOperation parseAptOperation(const std::string& opStr);
    static PackageOperation parseDpkgOperation(const std::string& opStr);
    static PackageOperation parseYumOperation(const std::string& opStr);
    static PackageOperation parsePacmanOperation(const std::string& opStr);

    // Known attack tools patterns
    static std::vector<PackagePattern> getAttackToolPatterns();
    static std::vector<PackagePattern> getSecurityToolPatterns();

    // Helper to convert operation to string
    static std::string operationToString(PackageOperation op);
};

} // namespace linux
} // namespace forensics

#endif // PACKAGE_MANAGER_LOG_PARSER_H
