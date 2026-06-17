// PersistenceDetector.cpp
// Implementation of persistence mechanism detection
// Phase 6: Persistence Mechanisms Detection Enhancement
//
// This file holds the top-level orchestration (detectAll) and the shared
// private helpers (risk assessment, file IO, suspicious-pattern matching).
// The per-mechanism detect* implementations are split into:
//   - PersistenceDetectorScripts.cpp  (rc.local/init.d/shell/ld.so/sudoers/at)
//   - PersistenceDetectorSystem.cpp   (udev/polkit/xinetd/systemd-timers)

#ifdef linux
#undef linux
#endif

#include "PersistenceDetector.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <regex>
#include <algorithm>
#include <iostream>

namespace fs = std::filesystem;
using namespace forensics::linux;

// ============================================================================
// Main Detection Entry Point
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectAll(const std::string& extractDir) {
    std::vector<PersistenceEntry> allEntries;

    auto rcLocal = detectRcLocal(extractDir);
    allEntries.insert(allEntries.end(), rcLocal.begin(), rcLocal.end());

    auto initD = detectInitDScripts(extractDir);
    allEntries.insert(allEntries.end(), initD.begin(), initD.end());

    auto profiles = detectShellProfiles(extractDir);
    allEntries.insert(allEntries.end(), profiles.begin(), profiles.end());

    auto ldPreload = detectLdSoPreload(extractDir);
    allEntries.insert(allEntries.end(), ldPreload.begin(), ldPreload.end());

    auto sudoers = detectSudoers(extractDir);
    allEntries.insert(allEntries.end(), sudoers.begin(), sudoers.end());

    auto udev = detectUdevRules(extractDir);
    allEntries.insert(allEntries.end(), udev.begin(), udev.end());

    auto polkit = detectPolkitRules(extractDir);
    allEntries.insert(allEntries.end(), polkit.begin(), polkit.end());

    auto xinetd = detectXinetdServices(extractDir);
    allEntries.insert(allEntries.end(), xinetd.begin(), xinetd.end());

    auto timers = detectSystemdTimers(extractDir);
    allEntries.insert(allEntries.end(), timers.begin(), timers.end());

    auto atJobs = detectAtJobs(extractDir);
    allEntries.insert(allEntries.end(), atJobs.begin(), atJobs.end());

    // Assess risk for all entries
    for (auto& entry : allEntries) {
        entry.risk = assessRisk(entry);
    }

    return allEntries;
}

PersistenceRisk PersistenceDetector::assessRisk(const PersistenceEntry& entry) {
    // Critical: ld.so.preload (library injection)
    if (entry.type == PersistenceType::LD_SO_PRELOAD) {
        return PersistenceRisk::CRITICAL;
    }

    // High: suspicious commands or rules
    if (entry.isSuspicious) {
        return PersistenceRisk::HIGH;
    }

    // High: sudoers NOPASSWD or ALL rules
    if (entry.type == PersistenceType::SUDOERS) {
        if (entry.command.find("NOPASSWD") != std::string::npos ||
            entry.command.find("ALL") != std::string::npos) {
            return PersistenceRisk::HIGH;
        }
    }

    // Medium: user-level persistence that's unusual
    if (entry.type == PersistenceType::SHELL_PROFILE && !entry.username.empty()) {
        if (entry.command.find("curl") != std::string::npos ||
            entry.command.find("wget") != std::string::npos ||
            entry.command.find("nc ") != std::string::npos) {
            return PersistenceRisk::MEDIUM;
        }
    }

    // Medium: xinetd services
    if (entry.type == PersistenceType::XINETD_SERVICE) {
        return PersistenceRisk::MEDIUM;
    }

    // Low: standard system persistence
    return PersistenceRisk::LOW;
}

std::string PersistenceDetector::typeToString(PersistenceType type) {
    switch (type) {
        case PersistenceType::RC_LOCAL: return "RC_LOCAL";
        case PersistenceType::INIT_D_SCRIPT: return "INIT_D_SCRIPT";
        case PersistenceType::SHELL_PROFILE: return "SHELL_PROFILE";
        case PersistenceType::AUTHORIZED_KEYS: return "AUTHORIZED_KEYS";
        case PersistenceType::LD_SO_PRELOAD: return "LD_SO_PRELOAD";
        case PersistenceType::SUDOERS: return "SUDOERS";
        case PersistenceType::UDEV_RULE: return "UDEV_RULE";
        case PersistenceType::POLKIT_RULE: return "POLKIT_RULE";
        case PersistenceType::XINETD_SERVICE: return "XINETD_SERVICE";
        case PersistenceType::SYSTEMD_TIMER: return "SYSTEMD_TIMER";
        case PersistenceType::AT_JOB: return "AT_JOB";
        case PersistenceType::CRON_JOB: return "CRON_JOB";
        case PersistenceType::SYSTEMD_SERVICE: return "SYSTEMD_SERVICE";
        default: return "UNKNOWN";
    }
}

std::string PersistenceDetector::riskToString(PersistenceRisk risk) {
    switch (risk) {
        case PersistenceRisk::LOW: return "LOW";
        case PersistenceRisk::MEDIUM: return "MEDIUM";
        case PersistenceRisk::HIGH: return "HIGH";
        case PersistenceRisk::CRITICAL: return "CRITICAL";
        default: return "UNKNOWN";
    }
}

std::string PersistenceDetector::readFileContent(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return "";

    std::stringstream buffer;
    buffer << file.rdbuf();
    return buffer.str();
}

std::vector<std::string> PersistenceDetector::listFiles(const std::string& dir, const std::string& pattern) {
    std::vector<std::string> files;
    if (!fs::exists(dir) || !fs::is_directory(dir)) return files;

    for (const auto& entry : fs::directory_iterator(dir)) {
        if (entry.is_regular_file()) {
            files.push_back(entry.path().string());
        }
    }
    return files;
}

bool PersistenceDetector::fileExists(const std::string& path) {
    return fs::exists(path) && fs::is_regular_file(path);
}

bool PersistenceDetector::isSuspiciousCommand(const std::string& command) {
    if (command.empty()) return false;

    // Network tools
    if (command.find("curl ") != std::string::npos ||
        command.find("wget ") != std::string::npos ||
        command.find("nc ") != std::string::npos ||
        command.find("ncat ") != std::string::npos ||
        command.find("socat ") != std::string::npos) {
        return true;
    }

    // Reverse shells
    if (command.find("/dev/tcp/") != std::string::npos ||
        command.find("bash -i") != std::string::npos ||
        command.find("python -c") != std::string::npos ||
        command.find("perl -e") != std::string::npos ||
        command.find("ruby -e") != std::string::npos) {
        return true;
    }

    // Encoding/obfuscation
    if (command.find("base64") != std::string::npos ||
        command.find("xxd") != std::string::npos) {
        return true;
    }

    // Credential access
    if (command.find("/etc/shadow") != std::string::npos ||
        command.find("/etc/passwd") != std::string::npos) {
        return true;
    }

    // Privilege escalation
    if (command.find("chmod u+s") != std::string::npos ||
        command.find("chmod +s") != std::string::npos) {
        return true;
    }

    return false;
}

bool PersistenceDetector::isSuspiciousSudoersRule(const std::string& rule) {
    // NOPASSWD rules
    if (rule.find("NOPASSWD") != std::string::npos) return true;

    // ALL privileges
    if (rule.find("ALL=(ALL)") != std::string::npos ||
        rule.find("ALL = ALL") != std::string::npos) return true;

    // Specific dangerous commands
    if (rule.find("/bin/bash") != std::string::npos ||
        rule.find("/bin/sh") != std::string::npos ||
        rule.find("/usr/bin/python") != std::string::npos ||
        rule.find("/usr/bin/perl") != std::string::npos) return true;

    return false;
}

bool PersistenceDetector::isSuspiciousUdevRule(const std::string& rule) {
    // Rules that run scripts
    if (rule.find("RUN+=\"/tmp/") != std::string::npos ||
        rule.find("RUN+=\"/var/tmp/") != std::string::npos) return true;

    // Rules with shell execution
    if (rule.find("RUN+=\"/bin/sh") != std::string::npos ||
        rule.find("RUN+=\"/bin/bash") != std::string::npos) return true;

    // Rules with network tools
    if (rule.find("curl") != std::string::npos ||
        rule.find("wget") != std::string::npos) return true;

    return false;
}

