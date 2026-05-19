// PersistenceDetector.h
// Detects persistence mechanisms in Linux systems
// Phase 6: Persistence Mechanisms Detection Enhancement

#pragma once
#ifndef PERSISTENCE_DETECTOR_H
#define PERSISTENCE_DETECTOR_H

#include <string>
#include <vector>
#include <map>
#include "LinuxDataTypes.h"

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

class PersistenceDetector {
public:
    // Main detection entry point - runs all detection methods
    static std::vector<PersistenceEntry> detectAll(const std::string& extractDir);

    // Individual detection methods
    static std::vector<PersistenceEntry> detectRcLocal(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectInitDScripts(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectShellProfiles(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectLdSoPreload(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectSudoers(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectUdevRules(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectPolkitRules(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectXinetdServices(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectSystemdTimers(const std::string& extractDir);
    static std::vector<PersistenceEntry> detectAtJobs(const std::string& extractDir);

    // Risk assessment
    static PersistenceRisk assessRisk(const PersistenceEntry& entry);
    static std::string typeToString(PersistenceType type);
    static std::string riskToString(PersistenceRisk risk);

private:
    // Helper to read file content
    static std::string readFileContent(const std::string& path);

    // Helper to list files matching pattern
    static std::vector<std::string> listFiles(const std::string& dir, const std::string& pattern);

    // Helper to check if file exists
    static bool fileExists(const std::string& path);

    // Suspicious command patterns
    static bool isSuspiciousCommand(const std::string& command);
    static bool isSuspiciousSudoersRule(const std::string& rule);
    static bool isSuspiciousUdevRule(const std::string& rule);
};

} // namespace linux
} // namespace forensics

#endif // PERSISTENCE_DETECTOR_H
