// SecurityBypassAnalyzer.h
// Security bypass and dynamic linker configuration analysis

#pragma once
#ifndef SECURITY_BYPASS_ANALYZER_H
#define SECURITY_BYPASS_ANALYZER_H

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

#include <string>
#include <vector>
#include <cstdint>
#include "LinuxDataTypes.h"

namespace forensics {
namespace linux {

struct SecurityBypassFinding {
    std::string findingType;    // LD_PRELOAD, LD_LIBRARY_PATH, PATH_MANIPULATION,
                                // DYNAMIC_LINKER_HIJACK, ENV_HIJACK, SUID_BYPASS,
                                // CAPABILITY_ABUSE, NAMESPACE_ESCAPE
    int severity = 0;           // 1-5
    std::string filePath;
    std::string description;
    std::string evidence;
    std::string username;
    bool isConfirmed = false;
    EvidenceProvenance provenance;
};

class SecurityBypassAnalyzer {
public:
    // Analyze ld.so.preload for library injection
    static std::vector<SecurityBypassFinding> analyzeLdSoPreload(
        const std::string& content,
        const std::string& filePath);

    // Analyze /etc/ld.so.conf and ld.so.conf.d/*
    static std::vector<SecurityBypassFinding> analyzeLdSoConf(
        const std::string& content,
        const std::string& filePath);

    // Analyze environment variable files for LD_PRELOAD, LD_LIBRARY_PATH
    static std::vector<SecurityBypassFinding> analyzeEnvironmentFiles(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Analyze shell startup files for suspicious modifications
    static std::vector<SecurityBypassFinding> analyzeShellStartup(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Detect PATH manipulation (shadow binaries)
    static std::vector<SecurityBypassFinding> analyzePathManipulation(
        const std::string& pathEnv,
        const std::string& filePath);

    // Detect dynamic library injection
    static std::vector<SecurityBypassFinding> analyzeLibraryInjection(
        const std::string& content,
        const std::string& filePath);

private:
    static bool isSuspiciousLibrary(const std::string& libPath);
    static bool isSuspiciousPath(const std::string& path);
    static int assessSeverity(const std::string& findingType,
                               const std::string& evidence);
};

} // namespace linux
} // namespace forensics

#endif // SECURITY_BYPASS_ANALYZER_H
