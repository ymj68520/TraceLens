// PersistenceDetectorSystem.cpp
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

// System-service persistence detection

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

