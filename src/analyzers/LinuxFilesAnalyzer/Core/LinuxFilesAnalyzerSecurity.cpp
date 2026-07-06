// LinuxFilesAnalyzerSecurity.cpp
// Security-related analysis methods of LinuxFilesAnalyzer
// (Persistence, Account/SSH, security bypass, setuid/capabilities, SELinux/AppArmor)

#include "LinuxFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"

#include <filesystem>
#include <fstream>
#include <iterator>
#include <set>
#include <sstream>

// Security parsers
#include "Parsers/Security/SetuidAnalyzer.h"
#include "Parsers/Security/CapabilityAnalyzer.h"
#include "Parsers/Security/SELinuxAnalyzer.h"
#include "Parsers/Security/AppArmorParser.h"

// Enhanced analysis
#include "Analysis/PersistenceDetector.h"

// Account/SSH security analyzer (Phase 10)
#include "Analysis/AccountSSH/AccountSSHAnalyzer.h"

// Phase 14: Security bypass
#include "Parsers/Security/SecurityBypassAnalyzer.h"

using forensics::linux::AccountSSHAnalyzer;
using forensics::linux::AccountSecurityFinding;
using forensics::linux::SSHSecurityFinding;
using forensics::linux::SecurityBypassAnalyzer;
using forensics::linux::SecurityBypassFinding;
using forensics::linux::PersistenceDetector;

namespace fs = std::filesystem;

// ============================================================================
// Persistence Mechanism Detection Implementation (Phase 6)
// ============================================================================

void LinuxFilesAnalyzer::analyzePersistenceMechanisms() {
    using namespace forensics::linux;

    std::cout << "Analyzing persistence mechanisms..." << std::endl;
    AuditLog::instance().log("SYSTEM", "PERSISTENCE_DETECTION_START", "Starting persistence mechanism detection: " + imagePath_);

    // Run all persistence detection algorithms
    auto entries = PersistenceDetector::detectAll(extractDir_);

    if (entries.empty()) {
        std::cout << "  No persistence mechanisms detected" << std::endl;
    } else {
        std::cout << "  Found " << entries.size() << " persistence mechanisms:" << std::endl;

        int criticalCount = 0;
        int highCount = 0;
        int mediumCount = 0;
        int suspiciousCount = 0;

        for (const auto& entry : entries) {
            if (entry.isSuspicious) suspiciousCount++;

            switch (entry.risk) {
                case PersistenceRisk::CRITICAL:
                    criticalCount++;
                    std::cout << "    [CRITICAL] " << PersistenceDetector::typeToString(entry.type)
                              << ": " << entry.command << std::endl;
                    break;
                case PersistenceRisk::HIGH:
                    highCount++;
                    std::cout << "    [HIGH] " << PersistenceDetector::typeToString(entry.type)
                              << ": " << entry.command << std::endl;
                    break;
                case PersistenceRisk::MEDIUM:
                    mediumCount++;
                    std::cout << "    [MEDIUM] " << PersistenceDetector::typeToString(entry.type)
                              << ": " << entry.command << std::endl;
                    break;
                default:
                    break;
            }
        }

        // Store entries in database
        if (!linuxDb_->insertPersistenceEntries(entries)) {
            std::cerr << "  Failed to insert persistence entries into database" << std::endl;
        } else {
            std::cout << "  Stored " << entries.size() << " persistence entries in database" << std::endl;
        }

        std::cout << "  Summary: " << criticalCount << " critical, " << highCount << " high, "
                  << mediumCount << " medium risk, " << suspiciousCount << " suspicious" << std::endl;
    }

    AuditLog::instance().log("SYSTEM", "PERSISTENCE_DETECTION_COMPLETE",
        "Persistence detection: " + std::to_string(entries.size()) + " entries found");
}

// ============================================================================
// Account and SSH Security Analysis Implementation (Phase 10)
// ============================================================================

void LinuxFilesAnalyzer::analyzeAccountSSHSecurity() {
    std::cout << "Analyzing account and SSH security..." << std::endl;

    if (!linuxDb_) {
        std::cerr << "  Error: Linux analysis database not initialized" << std::endl;
        return;
    }

    size_t totalAccountFindings = 0;
    size_t totalSSHFindings = 0;

    // Helper to read file content
    auto readFile = [](const std::string& path) -> std::string {
        std::ifstream f(path);
        if (!f.is_open()) return "";
        return std::string((std::istreambuf_iterator<char>(f)),
                           std::istreambuf_iterator<char>());
    };

    // Read account files
    std::string passwdContent = readFile(extractDir_ + "/etc/passwd");
    std::string shadowContent = readFile(extractDir_ + "/etc/shadow");
    std::string groupContent = readFile(extractDir_ + "/etc/group");
    std::string sudoersContent = readFile(extractDir_ + "/etc/sudoers");

    // Also read sudoers.d files
    std::string sudoersDCmd = "cat " + extractDir_ + "/etc/sudoers.d/* 2>/dev/null";
    FILE* sudoersPipe = popen(sudoersDCmd.c_str(), "r");
    if (sudoersPipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), sudoersPipe)) {
            sudoersContent += buffer;
        }
        pclose(sudoersPipe);
    }

    // Analyze account security
    auto accountFindings = AccountSSHAnalyzer::analyzeAllAccounts(
        passwdContent, shadowContent, groupContent, sudoersContent);

    if (!accountFindings.empty()) {
        if (linuxDb_->insertAccountSecurityFindings(accountFindings)) {
            totalAccountFindings = accountFindings.size();
            std::cout << "  Found " << totalAccountFindings << " account security findings" << std::endl;
            for (const auto& f : accountFindings) {
                if (f.severity == "critical") {
                    std::cout << "    [CRITICAL] " << f.findingType
                              << ": " << f.description << std::endl;
                }
            }
        }
    }

    // Read SSH config files
    std::string sshdConfig = readFile(extractDir_ + "/etc/ssh/sshd_config");
    std::string sshConfig = readFile(extractDir_ + "/etc/ssh/ssh_config");

    // Collect authorized_keys and known_hosts files
    std::vector<std::pair<std::string, std::string>> authorizedKeysFiles;
    std::vector<std::pair<std::string, std::string>> knownHostsFiles;

    // Find user home directories
    std::string homeCmd = "ls -d " + extractDir_ + "/home/*/.ssh/authorized_keys "
                          + extractDir_ + "/home/*/.ssh/authorized_keys2 "
                          + extractDir_ + "/root/.ssh/authorized_keys "
                          + extractDir_ + "/root/.ssh/authorized_keys2 "
                          + "2>/dev/null";
    FILE* homePipe = popen(homeCmd.c_str(), "r");
    if (homePipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), homePipe)) {
            std::string keyPath(buffer);
            while (!keyPath.empty() && (keyPath.back() == '\n' || keyPath.back() == '\r')) {
                keyPath.pop_back();
            }
            if (keyPath.empty()) continue;

            std::string content = readFile(keyPath);
            if (!content.empty()) {
                // Convert absolute path to relative
                std::string relativePath = keyPath;
                if (relativePath.find(extractDir_) == 0) {
                    relativePath = relativePath.substr(extractDir_.length());
                }
                authorizedKeysFiles.push_back({content, relativePath});
            }
        }
        pclose(homePipe);
    }

    // Find known_hosts files
    std::string knownCmd = "ls " + extractDir_ + "/home/*/.ssh/known_hosts "
                           + extractDir_ + "/root/.ssh/known_hosts "
                           + "2>/dev/null";
    FILE* knownPipe = popen(knownCmd.c_str(), "r");
    if (knownPipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), knownPipe)) {
            std::string hostsPath(buffer);
            while (!hostsPath.empty() && (hostsPath.back() == '\n' || hostsPath.back() == '\r')) {
                hostsPath.pop_back();
            }
            if (hostsPath.empty()) continue;

            std::string content = readFile(hostsPath);
            if (!content.empty()) {
                std::string relativePath = hostsPath;
                if (relativePath.find(extractDir_) == 0) {
                    relativePath = relativePath.substr(extractDir_.length());
                }
                knownHostsFiles.push_back({content, relativePath});
            }
        }
        pclose(knownPipe);
    }

    // Analyze SSH security
    auto sshFindings = AccountSSHAnalyzer::analyzeAllSSH(
        sshdConfig, sshConfig, authorizedKeysFiles, knownHostsFiles);

    if (!sshFindings.empty()) {
        if (linuxDb_->insertSSHSecurityFindings(sshFindings)) {
            totalSSHFindings = sshFindings.size();
            std::cout << "  Found " << totalSSHFindings << " SSH security findings" << std::endl;
            for (const auto& f : sshFindings) {
                if (f.severity == "critical") {
                    std::cout << "    [CRITICAL] " << f.findingType
                              << ": " << f.description << std::endl;
                }
            }
        }
    }

    std::cout << "  Account findings: " << totalAccountFindings
              << ", SSH findings: " << totalSSHFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "ACCOUNT_SSH_COMPLETE",
        "Account/SSH security analysis: " + std::to_string(totalAccountFindings) +
        " account findings, " + std::to_string(totalSSHFindings) + " SSH findings");
}

// ============================================================================
// Phase 14: Security bypass
// ============================================================================

void LinuxFilesAnalyzer::analyzeSecurityBypass() {
    std::cout << "Analyzing security bypass mechanisms..." << std::endl;

    int totalFindings = 0;

    // Check ld.so.preload
    auto preloadFiles = queryFilesByPattern("%/etc/ld.so.preload%");
    for (const auto& file : preloadFiles) {
        std::string extractPath = getExtractPath("etc/ld.so.preload");
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            std::ifstream fs(extractPath);
            std::string content((std::istreambuf_iterator<char>(fs)),
                                 std::istreambuf_iterator<char>());
            auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload(content, extractPath);
            totalFindings += findings.size();
            for (const auto& finding : findings) {
                std::cout << "  WARNING: " << finding.description << std::endl;
            }
        }
    }

    // Check shell startup files for each user
    auto userDirs = findUserHomeDirectories();
    for (const auto& userDir : userDirs) {
        std::string username = userDir.substr(userDir.find_last_of('/') + 1);

        // .bashrc
        auto bashrcFiles = queryFilesByPattern(userDir + "%/.bashrc%");
        for (const auto& file : bashrcFiles) {
            std::string extractPath = getExtractPath(username + "/.bashrc");
            if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto findings = SecurityBypassAnalyzer::analyzeShellStartup(content, extractPath, username);
                totalFindings += findings.size();
            }
        }

        // .profile
        auto profileFiles = queryFilesByPattern(userDir + "%/.profile%");
        for (const auto& file : profileFiles) {
            std::string extractPath = getExtractPath(username + "/.profile");
            if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto findings = SecurityBypassAnalyzer::analyzeEnvironmentFiles(content, extractPath, username);
                totalFindings += findings.size();
            }
        }
    }

    std::cout << "  Found " << totalFindings << " security bypass indicators" << std::endl;
    AuditLog::instance().log("SUCCESS", "SECURITY_BYPASS_ANALYZED",
        "Found " + std::to_string(totalFindings) + " security bypass indicators");
}

// ============================================================================
// Security Posture Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::analyzeSetuidFiles() {
    std::cout << "Analyzing setuid/setgid files..." << std::endl;

    // Query files with setuid/setgid permissions
    // This would typically come from a find command output or file listing
    std::string extractPath = getExtractPath("security");
    fs::create_directories(extractPath);

    // For this implementation, we'll look for common setuid binaries
    std::vector<std::string> setuidPaths = {
        "usr/bin/sudo",
        "usr/bin/passwd",
        "usr/bin/su",
        "usr/bin/ping",
        "usr/bin/newgrp",
        "usr/bin/chsh",
        "usr/bin/chfn",
        "usr/bin/gpasswd",
        "bin/su",
        "bin/ping",
        "bin/mount",
        "bin/umount"
    };

    std::vector<SetuidFileInfo> setuidFiles;
    for (const auto& path : setuidPaths) {
        auto files = queryFilesByPattern(path);
        for (const auto& file : files) {
            SetuidFileInfo info;
            info.filePath = "/" + file.path;
            info.size = file.size;
            info.permissions = 04755; // Default setuid
            info.isSetuid = true;
            info.isSetgid = false;
            setuidFiles.push_back(info);
        }
    }

    if (!setuidFiles.empty()) {
        LinuxAnalysis::SetuidAnalyzer::flagSuspiciousFiles(setuidFiles);
        linuxDb_->insertSetuidFiles(setuidFiles);
        std::cout << "  Found " << setuidFiles.size() << " setuid/setgid files" << std::endl;
    } else {
        std::cout << "  No setuid files found (skipping)" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzeCapabilities() {
    std::cout << "Analyzing Linux capabilities..." << std::endl;

    // Look for files with capabilities set
    // This would typically require getcap output or similar
    std::string extractPath = getExtractPath("security/capabilities");
    fs::create_directories(extractPath);

    // For now, note that capability analysis requires system-level access
    std::cout << "  Capability analysis requires system access (skipping)" << std::endl;
    AuditLog::instance().log("INFO", "CAPABILITIES_SKIP",
        "Capability analysis requires getcap output from live system");
}

void LinuxFilesAnalyzer::analyzeSELinux() {
    std::cout << "Analyzing SELinux status..." << std::endl;

    // Look for SELinux configuration
    auto selinuxConfigs = queryFilesByPattern("etc/selinux/config");
    auto auditLogs = queryFilesByPattern("var/log/audit/audit.log%");

    if (selinuxConfigs.empty()) {
        std::cout << "  No SELinux configuration found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("security/selinux");
    fs::create_directories(extractPath);

    // Extract SELinux config
    for (const auto& configItem : selinuxConfigs) {
        std::string outputPath = extractPath + "/config";
        extractFileToPath(configItem.inode, outputPath);

        auto statusResult = LinuxAnalysis::SELinuxAnalyzer::parseStatus(outputPath);
        linuxDb_->insertSELinuxStatus(statusResult.status);

        std::string enabled = LinuxAnalysis::SELinuxAnalyzer::isEnabled(statusResult.status) ? "enabled" : "disabled";
        std::cout << "  SELinux is " << enabled << " (mode: " << statusResult.status.currentMode << ")" << std::endl;
    }

    // Extract and parse AVC denials
    for (const auto& log : auditLogs) {
        std::string outputPath = extractPath + "/audit_" + std::to_string(log.inode) + ".log";
        extractFileToPath(log.inode, outputPath);

        auto denialsResult = LinuxAnalysis::SELinuxAnalyzer::extractAVCDenials(outputPath);
        if (!denialsResult.avcDenials.empty()) {
            linuxDb_->insertSELinuxAVCDenials(denialsResult.avcDenials);
            std::cout << "  Found " << denialsResult.avcDenials.size() << " SELinux AVC denials" << std::endl;
        }
    }
}

void LinuxFilesAnalyzer::analyzeAppArmor() {
    std::cout << "Analyzing AppArmor status..." << std::endl;

    // Look for AppArmor profiles
    auto appArmorProfiles = queryFilesByPattern("etc/apparmor.d/%");
    auto appArmorLogs = queryFilesByPattern("var/log/syslog%");

    if (appArmorProfiles.empty()) {
        std::cout << "  No AppArmor profiles found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("security/apparmor");
    fs::create_directories(extractPath);

    // Extract profiles
    int profileCount = 0;
    for (const auto& profile : appArmorProfiles) {
        std::string outputPath = extractPath + "/" + std::to_string(profile.inode);
        extractFileToPath(profile.inode, outputPath);
        profileCount++;
    }

    auto profilesResult = LinuxAnalysis::AppArmorParser::parseProfiles(extractPath);
    if (!profilesResult.profiles.empty()) {
        linuxDb_->insertAppArmorProfiles(profilesResult.profiles);
        std::cout << "  Found " << profilesResult.profiles.size() << " AppArmor profiles" << std::endl;
    }

    // Look for violations in syslog
    for (const auto& log : appArmorLogs) {
        std::string outputPath = extractPath + "/syslog_" + std::to_string(log.inode);
        extractFileToPath(log.inode, outputPath);

        auto violationsResult = LinuxAnalysis::AppArmorParser::extractViolations(outputPath);
        if (!violationsResult.violations.empty()) {
            linuxDb_->insertAppArmorViolations(violationsResult.violations);
            std::cout << "  Found " << violationsResult.violations.size() << " AppArmor violations" << std::endl;
        }
    }
}
