// PersistenceDetector.cpp
// Implementation of persistence mechanism detection
// Phase 6: Persistence Mechanisms Detection Enhancement

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

// ============================================================================
// rc.local Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectRcLocal(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;
    std::string rcLocalPath = extractDir + "/etc/rc.local";

    if (!fileExists(rcLocalPath)) return entries;

    std::string content = readFileContent(rcLocalPath);
    if (content.empty()) return entries;

    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        // Skip comments and empty lines
        if (line.empty() || line[0] == '#' || line[0] == '\n') continue;

        // Trim whitespace
        line.erase(0, line.find_first_not_of(" \t\r\n"));
        line.erase(line.find_last_not_of(" \t\r\n") + 1);
        if (line.empty()) continue;

        PersistenceEntry entry;
        entry.type = PersistenceType::RC_LOCAL;
        entry.filePath = "/etc/rc.local";
        entry.entryName = "rc.local";
        entry.command = line;
        entry.isEnabled = true;
        entry.rawContent = line;

        entry.provenance.parserName = "PersistenceDetector";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = rcLocalPath;
        entry.provenance.sourceLine = lineNum;

        if (isSuspiciousCommand(line)) {
            entry.isSuspicious = true;
            entry.suspiciousReason = "Suspicious command in rc.local: " + line;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// init.d Scripts Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectInitDScripts(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;
    std::string initDir = extractDir + "/etc/init.d";

    if (!fs::exists(initDir) || !fs::is_directory(initDir)) return entries;

    for (const auto& dirEntry : fs::directory_iterator(initDir)) {
        if (!dirEntry.is_regular_file()) continue;

        std::string filePath = dirEntry.path().string();
        std::string fileName = dirEntry.path().filename().string();

        // Skip README and helper scripts
        if (fileName == "README" || fileName[0] == '.') continue;

        std::string content = readFileContent(filePath);
        if (content.empty()) continue;

        // Extract the main command from the script
        std::string mainCommand;
        std::istringstream stream(content);
        std::string line;
        while (std::getline(stream, line)) {
            // Look for DAEMON= or exec lines
            if (line.find("DAEMON=") == 0) {
                mainCommand = line.substr(7);
                break;
            }
            if (line.find("exec ") == 0) {
                mainCommand = line.substr(5);
                break;
            }
        }

        PersistenceEntry entry;
        entry.type = PersistenceType::INIT_D_SCRIPT;
        entry.filePath = "/etc/init.d/" + fileName;
        entry.entryName = fileName;
        entry.command = mainCommand.empty() ? fileName : mainCommand;
        entry.isEnabled = true;
        entry.rawContent = content.substr(0, 500); // First 500 chars

        entry.provenance.parserName = "PersistenceDetector";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        if (isSuspiciousCommand(mainCommand)) {
            entry.isSuspicious = true;
            entry.suspiciousReason = "Suspicious command in init.d script: " + fileName;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Shell Profile Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectShellProfiles(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;

    // System-wide profiles
    std::vector<std::string> systemProfiles = {
        "/etc/profile",
        "/etc/bash.bashrc",
        "/etc/zsh/zshrc"
    };

    for (const auto& profile : systemProfiles) {
        std::string fullPath = extractDir + profile;
        if (!fileExists(fullPath)) continue;

        std::string content = readFileContent(fullPath);
        if (content.empty()) continue;

        std::istringstream stream(content);
        std::string line;
        int lineNum = 0;

        while (std::getline(stream, line)) {
            lineNum++;
            // Skip comments and empty lines
            if (line.empty() || line[0] == '#') continue;

            // Look for command execution patterns
            if (line.find("source ") == 0 || line.find(". ") == 0 ||
                line.find("eval ") == 0 || line.find("exec ") == 0 ||
                line.find("export ") == 0 || line.find("alias ") == 0) {

                PersistenceEntry entry;
                entry.type = PersistenceType::SHELL_PROFILE;
                entry.filePath = profile;
                entry.entryName = profile;
                entry.command = line;
                entry.isEnabled = true;
                entry.rawContent = line;

                entry.provenance.parserName = "PersistenceDetector";
                entry.provenance.parserVersion = "1.0.0";
                entry.provenance.sourceFile = fullPath;
                entry.provenance.sourceLine = lineNum;

                if (isSuspiciousCommand(line)) {
                    entry.isSuspicious = true;
                    entry.suspiciousReason = "Suspicious command in shell profile: " + line;
                }

                entries.push_back(entry);
            }
        }
    }

    // User profiles
    std::string homeDir = extractDir + "/home";
    if (fs::exists(homeDir) && fs::is_directory(homeDir)) {
        for (const auto& userDir : fs::directory_iterator(homeDir)) {
            if (!userDir.is_directory()) continue;
            std::string username = userDir.path().filename().string();

            std::vector<std::string> userProfiles = {
                "/.bashrc",
                "/.profile",
                "/.bash_profile",
                "/.zshrc"
            };

            for (const auto& profile : userProfiles) {
                std::string fullPath = userDir.path().string() + profile;
                if (!fileExists(fullPath)) continue;

                std::string content = readFileContent(fullPath);
                if (content.empty()) continue;

                std::istringstream stream(content);
                std::string line;
                int lineNum = 0;

                while (std::getline(stream, line)) {
                    lineNum++;
                    if (line.empty() || line[0] == '#') continue;

                    if (line.find("source ") == 0 || line.find(". ") == 0 ||
                        line.find("eval ") == 0 || line.find("exec ") == 0) {

                        PersistenceEntry entry;
                        entry.type = PersistenceType::SHELL_PROFILE;
                        entry.filePath = "/home/" + username + profile;
                        entry.entryName = username + profile;
                        entry.command = line;
                        entry.username = username;
                        entry.isEnabled = true;
                        entry.rawContent = line;

                        entry.provenance.parserName = "PersistenceDetector";
                        entry.provenance.parserVersion = "1.0.0";
                        entry.provenance.sourceFile = fullPath;
                        entry.provenance.sourceLine = lineNum;

                        if (isSuspiciousCommand(line)) {
                            entry.isSuspicious = true;
                            entry.suspiciousReason = "Suspicious command in user profile: " + line;
                        }

                        entries.push_back(entry);
                    }
                }
            }
        }
    }

    return entries;
}

// ============================================================================
// ld.so.preload Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectLdSoPreload(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;
    std::string preloadPath = extractDir + "/etc/ld.so.preload";

    if (!fileExists(preloadPath)) return entries;

    std::string content = readFileContent(preloadPath);
    if (content.empty()) return entries;

    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        // Trim whitespace
        line.erase(0, line.find_first_not_of(" \t\r\n"));
        line.erase(line.find_last_not_of(" \t\r\n") + 1);
        if (line.empty() || line[0] == '#') continue;

        PersistenceEntry entry;
        entry.type = PersistenceType::LD_SO_PRELOAD;
        entry.filePath = "/etc/ld.so.preload";
        entry.entryName = "ld.so.preload";
        entry.command = line;
        entry.isEnabled = true;
        entry.rawContent = line;

        entry.provenance.parserName = "PersistenceDetector";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = preloadPath;
        entry.provenance.sourceLine = lineNum;

        // ld.so.preload is always suspicious in forensics context
        entry.isSuspicious = true;
        entry.suspiciousReason = "LD_PRELOAD library detected: " + line;
        entry.risk = PersistenceRisk::CRITICAL;

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Sudoers Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectSudoers(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;

    // Main sudoers file
    std::string sudoersPath = extractDir + "/etc/sudoers";
    if (fileExists(sudoersPath)) {
        std::string content = readFileContent(sudoersPath);
        if (!content.empty()) {
            std::istringstream stream(content);
            std::string line;
            int lineNum = 0;

            while (std::getline(stream, line)) {
                lineNum++;
                // Trim whitespace
                line.erase(0, line.find_first_not_of(" \t\r\n"));
                line.erase(line.find_last_not_of(" \t\r\n") + 1);
                if (line.empty() || line[0] == '#') continue;

                // Skip @include and @includedir directives
                if (line.find("@include") == 0) continue;

                PersistenceEntry entry;
                entry.type = PersistenceType::SUDOERS;
                entry.filePath = "/etc/sudoers";
                entry.entryName = "sudoers";
                entry.command = line;
                entry.isEnabled = true;
                entry.rawContent = line;

                entry.provenance.parserName = "PersistenceDetector";
                entry.provenance.parserVersion = "1.0.0";
                entry.provenance.sourceFile = sudoersPath;
                entry.provenance.sourceLine = lineNum;

                if (isSuspiciousSudoersRule(line)) {
                    entry.isSuspicious = true;
                    entry.suspiciousReason = "Suspicious sudoers rule: " + line;
                }

                entries.push_back(entry);
            }
        }
    }

    // sudoers.d drop-in files
    std::string sudoersDir = extractDir + "/etc/sudoers.d";
    if (fs::exists(sudoersDir) && fs::is_directory(sudoersDir)) {
        for (const auto& dirEntry : fs::directory_iterator(sudoersDir)) {
            if (!dirEntry.is_regular_file()) continue;

            std::string filePath = dirEntry.path().string();
            std::string fileName = dirEntry.path().filename().string();

            // Skip README and backup files
            if (fileName == "README" || fileName[0] == '~' || fileName.find(".bak") != std::string::npos) continue;

            std::string content = readFileContent(filePath);
            if (content.empty()) continue;

            std::istringstream stream(content);
            std::string line;
            int lineNum = 0;

            while (std::getline(stream, line)) {
                lineNum++;
                line.erase(0, line.find_first_not_of(" \t\r\n"));
                line.erase(line.find_last_not_of(" \t\r\n") + 1);
                if (line.empty() || line[0] == '#') continue;

                PersistenceEntry entry;
                entry.type = PersistenceType::SUDOERS;
                entry.filePath = "/etc/sudoers.d/" + fileName;
                entry.entryName = fileName;
                entry.command = line;
                entry.isEnabled = true;
                entry.rawContent = line;

                entry.provenance.parserName = "PersistenceDetector";
                entry.provenance.parserVersion = "1.0.0";
                entry.provenance.sourceFile = filePath;
                entry.provenance.sourceLine = lineNum;

                if (isSuspiciousSudoersRule(line)) {
                    entry.isSuspicious = true;
                    entry.suspiciousReason = "Suspicious sudoers rule: " + line;
                }

                entries.push_back(entry);
            }
        }
    }

    return entries;
}

// ============================================================================
// udev Rules Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectUdevRules(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;

    std::vector<std::string> udevDirs = {
        "/etc/udev/rules.d",
        "/lib/udev/rules.d",
        "/usr/lib/udev/rules.d"
    };

    for (const auto& udevDir : udevDirs) {
        std::string fullPath = extractDir + udevDir;
        if (!fs::exists(fullPath) || !fs::is_directory(fullPath)) continue;

        for (const auto& dirEntry : fs::directory_iterator(fullPath)) {
            if (!dirEntry.is_regular_file()) continue;

            std::string filePath = dirEntry.path().string();
            std::string fileName = dirEntry.path().filename().string();

            if (fileName.find(".rules") == std::string::npos) continue;

            std::string content = readFileContent(filePath);
            if (content.empty()) continue;

            std::istringstream stream(content);
            std::string line;
            int lineNum = 0;

            while (std::getline(stream, line)) {
                lineNum++;
                line.erase(0, line.find_first_not_of(" \t\r\n"));
                line.erase(line.find_last_not_of(" \t\r\n") + 1);
                if (line.empty() || line[0] == '#') continue;

                // Only interested in rules that run programs
                if (line.find("RUN") == std::string::npos &&
                    line.find("PROGRAM") == std::string::npos) continue;

                PersistenceEntry entry;
                entry.type = PersistenceType::UDEV_RULE;
                entry.filePath = udevDir + "/" + fileName;
                entry.entryName = fileName;
                entry.command = line;
                entry.isEnabled = true;
                entry.rawContent = line;

                entry.provenance.parserName = "PersistenceDetector";
                entry.provenance.parserVersion = "1.0.0";
                entry.provenance.sourceFile = filePath;
                entry.provenance.sourceLine = lineNum;

                if (isSuspiciousUdevRule(line)) {
                    entry.isSuspicious = true;
                    entry.suspiciousReason = "Suspicious udev rule: " + line;
                }

                entries.push_back(entry);
            }
        }
    }

    return entries;
}

// ============================================================================
// Polkit Rules Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectPolkitRules(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;

    std::vector<std::string> polkitDirs = {
        "/etc/polkit-1/rules.d",
        "/usr/share/polkit-1/rules.d"
    };

    for (const auto& polkitDir : polkitDirs) {
        std::string fullPath = extractDir + polkitDir;
        if (!fs::exists(fullPath) || !fs::is_directory(fullPath)) continue;

        for (const auto& dirEntry : fs::directory_iterator(fullPath)) {
            if (!dirEntry.is_regular_file()) continue;

            std::string filePath = dirEntry.path().string();
            std::string fileName = dirEntry.path().filename().string();

            if (fileName.find(".rules") == std::string::npos) continue;

            std::string content = readFileContent(filePath);
            if (content.empty()) continue;

            // Polkit rules are JavaScript-like - look for action returns
            std::istringstream stream(content);
            std::string line;
            int lineNum = 0;

            while (std::getline(stream, line)) {
                lineNum++;
                // Look for return values that grant permissions
                if (line.find("return polkit.Result.YES") != std::string::npos ||
                    line.find("return polkit.Result.AUTH_ADMIN_KEEP") != std::string::npos) {

                    PersistenceEntry entry;
                    entry.type = PersistenceType::POLKIT_RULE;
                    entry.filePath = polkitDir + "/" + fileName;
                    entry.entryName = fileName;
                    entry.command = line;
                    entry.isEnabled = true;
                    entry.rawContent = line;

                    entry.provenance.parserName = "PersistenceDetector";
                    entry.provenance.parserVersion = "1.0.0";
                    entry.provenance.sourceFile = filePath;
                    entry.provenance.sourceLine = lineNum;

                    // Polkit rules granting YES without auth are suspicious
                    if (line.find("return polkit.Result.YES") != std::string::npos) {
                        entry.isSuspicious = true;
                        entry.suspiciousReason = "Polkit rule grants permission without authentication";
                    }

                    entries.push_back(entry);
                }
            }
        }
    }

    return entries;
}

// ============================================================================
// xinetd Services Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectXinetdServices(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;
    std::string xinetdDir = extractDir + "/etc/xinetd.d";

    if (!fs::exists(xinetdDir) || !fs::is_directory(xinetdDir)) return entries;

    for (const auto& dirEntry : fs::directory_iterator(xinetdDir)) {
        if (!dirEntry.is_regular_file()) continue;

        std::string filePath = dirEntry.path().string();
        std::string fileName = dirEntry.path().filename().string();

        std::string content = readFileContent(filePath);
        if (content.empty()) continue;

        // Parse xinetd service config
        std::string server;
        std::string disable = "no";
        std::istringstream stream(content);
        std::string line;

        while (std::getline(stream, line)) {
            // Trim whitespace
            line.erase(0, line.find_first_not_of(" \t"));
            line.erase(line.find_last_not_of(" \t") + 1);

            if (line.find("server") == 0) {
                size_t eq = line.find('=');
                if (eq != std::string::npos) {
                    server = line.substr(eq + 1);
                    server.erase(0, server.find_first_not_of(" \t"));
                    server.erase(server.find_last_not_of(" \t") + 1);
                }
            }
            if (line.find("disable") == 0) {
                size_t eq = line.find('=');
                if (eq != std::string::npos) {
                    disable = line.substr(eq + 1);
                    disable.erase(0, disable.find_first_not_of(" \t"));
                    disable.erase(disable.find_last_not_of(" \t") + 1);
                }
            }
        }

        PersistenceEntry entry;
        entry.type = PersistenceType::XINETD_SERVICE;
        entry.filePath = "/etc/xinetd.d/" + fileName;
        entry.entryName = fileName;
        entry.command = server;
        entry.isEnabled = (disable == "no");
        entry.rawContent = content.substr(0, 500);

        entry.provenance.parserName = "PersistenceDetector";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        if (isSuspiciousCommand(server)) {
            entry.isSuspicious = true;
            entry.suspiciousReason = "Suspicious xinetd service: " + fileName;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Systemd Timers Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectSystemdTimers(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;

    std::vector<std::string> systemdDirs = {
        "/etc/systemd/system",
        "/lib/systemd/system",
        "/usr/lib/systemd/system"
    };

    for (const auto& systemdDir : systemdDirs) {
        std::string fullPath = extractDir + systemdDir;
        if (!fs::exists(fullPath) || !fs::is_directory(fullPath)) continue;

        for (const auto& dirEntry : fs::directory_iterator(fullPath)) {
            if (!dirEntry.is_regular_file()) continue;

            std::string filePath = dirEntry.path().string();
            std::string fileName = dirEntry.path().filename().string();

            // Only look at .timer files
            if (fileName.find(".timer") == std::string::npos) continue;

            std::string content = readFileContent(filePath);
            if (content.empty()) continue;

            // Parse timer unit
            std::string onCalendar;
            std::string onBootSec;
            std::string unit;
            std::istringstream stream(content);
            std::string line;

            while (std::getline(stream, line)) {
                line.erase(0, line.find_first_not_of(" \t"));
                line.erase(line.find_last_not_of(" \t") + 1);

                if (line.find("OnCalendar=") == 0) {
                    onCalendar = line.substr(11);
                } else if (line.find("OnBootSec=") == 0) {
                    onBootSec = line.substr(10);
                } else if (line.find("Unit=") == 0) {
                    unit = line.substr(5);
                }
            }

            std::string schedule = onCalendar.empty() ? onBootSec : onCalendar;

            PersistenceEntry entry;
            entry.type = PersistenceType::SYSTEMD_TIMER;
            entry.filePath = systemdDir + "/" + fileName;
            entry.entryName = fileName;
            entry.command = unit;
            entry.schedule = schedule;
            entry.isEnabled = true;
            entry.rawContent = content.substr(0, 500);

            entry.provenance.parserName = "PersistenceDetector";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;

            entries.push_back(entry);
        }
    }

    return entries;
}

// ============================================================================
// at/batch Jobs Detection
// ============================================================================

std::vector<PersistenceEntry> PersistenceDetector::detectAtJobs(const std::string& extractDir) {
    std::vector<PersistenceEntry> entries;
    std::string atDir = extractDir + "/var/spool/at";

    if (!fs::exists(atDir) || !fs::is_directory(atDir)) return entries;

    for (const auto& dirEntry : fs::directory_iterator(atDir)) {
        if (!dirEntry.is_regular_file()) continue;

        std::string filePath = dirEntry.path().string();
        std::string fileName = dirEntry.path().filename().string();

        // Skip control files
        if (fileName[0] == '.' || fileName == "SEQ") continue;

        std::string content = readFileContent(filePath);
        if (content.empty()) continue;

        // at job files contain the commands to run
        // First line is typically the shell setup
        std::string commands;
        std::istringstream stream(content);
        std::string line;
        bool inCommands = false;

        while (std::getline(stream, line)) {
            // Skip the header lines (shell, cd, etc.)
            if (line.find("#!/bin/sh") == 0 || line.find("cd ") == 0) continue;
            if (line.find("umask") == 0) continue;
            if (!line.empty() && line[0] != '#') {
                if (!commands.empty()) commands += "; ";
                commands += line;
                inCommands = true;
            }
        }

        PersistenceEntry entry;
        entry.type = PersistenceType::AT_JOB;
        entry.filePath = "/var/spool/at/" + fileName;
        entry.entryName = fileName;
        entry.command = commands;
        entry.isEnabled = true;
        entry.rawContent = content.substr(0, 500);

        entry.provenance.parserName = "PersistenceDetector";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        if (isSuspiciousCommand(commands)) {
            entry.isSuspicious = true;
            entry.suspiciousReason = "Suspicious at job command: " + commands;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Risk Assessment
// ============================================================================

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

// ============================================================================
// String Converters
// ============================================================================

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

// ============================================================================
// Helper Methods
// ============================================================================

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
