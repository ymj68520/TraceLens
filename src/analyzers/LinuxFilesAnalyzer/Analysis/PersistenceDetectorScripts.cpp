// PersistenceDetectorScripts.cpp
// Persistence mechanism detection — split from PersistenceDetector.cpp.
// All functions are members of the forensics::linux::PersistenceDetector class
// (declared in PersistenceDetector.h) and rely on its private helpers.

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

// Script-based persistence detection

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

