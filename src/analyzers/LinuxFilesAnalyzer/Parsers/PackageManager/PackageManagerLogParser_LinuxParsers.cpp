// PackageManagerLogParser_LinuxParsers.cpp
// Linux distro package manager log parsers (APT / dpkg / YUM / DNF / Zypper / Pacman)
// Part of PackageManagerLogParser implementation; methods belong to
// forensics::linux::PackageManagerLogParser declared in PackageManagerLogParser.h.
// Split from PackageManagerLogParser.cpp for maintainability.

#ifdef linux
#undef linux
#endif

#include "PackageManagerLogParser.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <ctime>

using namespace forensics::linux;

std::vector<PackageLogEntry> PackageManagerLogParser::parseAptHistoryLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    PackageLogEntry currentEntry;
    bool inEntry = false;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // Start-Date line
        if (line.find("Start-Date:") == 0) {
            if (inEntry && !currentEntry.packageName.empty()) {
                entries.push_back(currentEntry);
            }
            currentEntry = PackageLogEntry();
            currentEntry.filePath = filePath;
            currentEntry.packageManager = "apt";
            currentEntry.provenance.parserName = "PackageManagerLogParser";
            currentEntry.provenance.parserVersion = "1.0.0";
            currentEntry.provenance.sourceFile = filePath;
            currentEntry.provenance.rawRecord = line;

            std::string dateStr = line.substr(12); // skip "Start-Date: "
            currentEntry.timestamp = parseAptTimestamp(dateStr);
            inEntry = true;
            continue;
        }

        if (!inEntry) continue;

        // Commandline line
        if (line.find("Commandline:") == 0) {
            currentEntry.commandLine = line.substr(13); // skip "Commandline: "
            continue;
        }

        // Install/Remove/Upgrade/Purge lines
        // Format: Install: pkg1:arch (ver, repo), pkg2:arch (ver, repo)
        if (line.find("Install:") == 0 ||
            line.find("Remove:") == 0 ||
            line.find("Upgrade:") == 0 ||
            line.find("Purge:") == 0 ||
            line.find("Reinstall:") == 0) {

            if (line.find("Install:") == 0) currentEntry.operation = PackageOperation::INSTALL;
            else if (line.find("Remove:") == 0) currentEntry.operation = PackageOperation::REMOVE;
            else if (line.find("Upgrade:") == 0) currentEntry.operation = PackageOperation::UPGRADE;
            else if (line.find("Purge:") == 0) currentEntry.operation = PackageOperation::PURGE;
            else if (line.find("Reinstall:") == 0) currentEntry.operation = PackageOperation::REINSTALL;

            currentEntry.operationDetail = line;
            // Find the colon after the operation keyword
            size_t colonPos = line.find(':');
            if (colonPos != std::string::npos) {
                std::string rest = line.substr(colonPos + 1);
                // Parse: pkg:arch (ver, repo) or pkg:arch (ver)
                // Package name: word chars and hyphens, architecture: word chars
                std::regex pkgRegex("\\s*([\\w-]+):(\\S+)\\s+\\(([^,)]+)");
                auto begin = std::sregex_iterator(rest.begin(), rest.end(), pkgRegex);
                if (begin != std::sregex_iterator()) {
                    currentEntry.packageName = (*begin)[1].str();
                    currentEntry.architecture = (*begin)[2].str();
                    currentEntry.packageVersion = (*begin)[3].str();
                }
            }
            // Push entry and prepare for next one (keeping common fields)
            if (!currentEntry.packageName.empty()) {
                entries.push_back(currentEntry);
                currentEntry = PackageLogEntry();
                currentEntry.filePath = filePath;
                currentEntry.packageManager = "apt";
                currentEntry.provenance.parserName = "PackageManagerLogParser";
                currentEntry.provenance.parserVersion = "1.0.0";
                currentEntry.provenance.sourceFile = filePath;
                inEntry = true; // keep inEntry true for potential more operations
            }
            continue;
        }

        // Error line (skip but keep in raw record)
        if (line.find("Error:") == 0) {
            continue;
        }
    }

    // Don't forget the last entry
    if (inEntry && !currentEntry.packageName.empty()) {
        entries.push_back(currentEntry);
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parseAptTermLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    int64_t currentTimestamp = 0;
    std::string rawBlock;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // Log started line
        if (line.find("Log started:") == 0) {
            std::string dateStr = line.substr(13); // skip "Log started: "
            currentTimestamp = parseAptTimestamp(dateStr);
            rawBlock = line;
            continue;
        }

        rawBlock += "\n" + line;

        // Extract package from "Preparing to unpack" lines
        // Format: Preparing to unpack .../package_version_arch.deb
        std::regex unpackRegex("Preparing to unpack \\.\\.\\./([^_]+)_([^_]+)_([^\\.]+)\\.deb");
        std::smatch match;
        if (std::regex_search(line, match, unpackRegex)) {
            PackageLogEntry entry;
            entry.timestamp = currentTimestamp;
            entry.packageManager = "apt";
            entry.packageName = match[1].str();
            entry.packageVersion = match[2].str();
            entry.architecture = match[3].str();
            entry.operation = PackageOperation::INSTALL;
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = rawBlock;
            entries.push_back(entry);
        }

        // Extract from "Unpacking" lines
        std::regex unpackingRegex("Unpacking ([^\\s:]+)");
        if (std::regex_search(line, match, unpackingRegex)) {
            // Check if already captured by Preparing line
            std::string pkgName = match[1].str();
            bool alreadyCaptured = false;
            for (const auto& e : entries) {
                if (e.packageName == pkgName && e.timestamp == currentTimestamp) {
                    alreadyCaptured = true;
                    break;
                }
            }
            if (!alreadyCaptured) {
                PackageLogEntry entry;
                entry.timestamp = currentTimestamp;
                entry.packageManager = "apt";
                entry.packageName = pkgName;
                entry.operation = PackageOperation::INSTALL;
                entry.filePath = filePath;
                entry.provenance.parserName = "PackageManagerLogParser";
                entry.provenance.parserVersion = "1.0.0";
                entry.provenance.sourceFile = filePath;
                entry.provenance.rawRecord = line;
                entries.push_back(entry);
            }
        }

        // Extract from "Removing" lines
        std::regex removingRegex("Removing ([^\\s:]+)");
        if (std::regex_search(line, match, removingRegex)) {
            PackageLogEntry entry;
            entry.timestamp = currentTimestamp;
            entry.packageManager = "apt";
            entry.packageName = match[1].str();
            entry.operation = PackageOperation::REMOVE;
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parseDpkgLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        // Parse dpkg log line
        // Format: 2023-10-06 10:23:45 install nginx:amd64 <none> 1.18.0-6ubuntu14.4
        // Format: 2023-10-06 10:23:45 status installed nginx:amd64 1.18.0-6ubuntu14.4
        std::regex dpkgRegex("(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2})\\s+(\\S+)\\s+(\\S+)\\s+(\\S+)(?:\\s+(\\S+))?");
        std::smatch match;

        if (std::regex_match(line, match, dpkgRegex)) {
            PackageLogEntry entry;
            entry.timestamp = parseDpkgTimestamp(match[1].str());
            entry.packageManager = "dpkg";
            entry.operation = parseDpkgOperation(match[2].str());
            // For "status" lines, the third field is the status word (installed, etc.)
            // For action lines (install, remove, etc.), the third field is the package
            std::string action = match[2].str();
            if (action == "status") {
                entry.status = match[3].str();
                entry.packageName = match[4].str();
                if (match[5].matched) {
                    entry.packageVersion = match[5].str();
                }
            } else {
                // install, remove, upgrade, etc.
                entry.packageName = match[3].str();
                // match[4] could be <none> (for new installs) or old version
                std::string field4 = match[4].str();
                if (field4 == "<none>") {
                    // New install: version is in field 5
                    if (match[5].matched) {
                        entry.packageVersion = match[5].str();
                    }
                } else {
                    // field4 is old version, field5 is new version (or just current version)
                    if (match[5].matched) {
                        entry.packageVersion = match[5].str();
                    } else {
                        entry.packageVersion = field4;
                    }
                }
            }
            // Extract architecture from package name (e.g., nginx:amd64)
            size_t archPos = entry.packageName.rfind(':');
            if (archPos != std::string::npos) {
                entry.architecture = entry.packageName.substr(archPos + 1);
                entry.packageName = entry.packageName.substr(0, archPos);
            }
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parseYumLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        // yum log format: Oct 06 10:23:45 Installed: package-1.0-1.el7.x86_64
        std::regex yumRegex("(\\w{3}\\s+\\d{1,2}\\s+\\d{2}:\\d{2}:\\d{2})\\s+(\\w+):\\s+(\\S+)");
        std::smatch match;

        if (std::regex_match(line, match, yumRegex)) {
            PackageLogEntry entry;
            entry.timestamp = parseYumTimestamp(match[1].str());
            entry.packageManager = "yum";
            entry.operation = parseYumOperation(match[2].str());
            entry.operationDetail = match[2].str();

            // Parse package-version.arch from "nginx-1.20.1-10.el9.x86_64"
            // or "vim-enhanced-8.2.2637-20.el9.x86_64"
            std::string pkgFull = match[3].str();

            // First extract architecture (after last dot)
            std::string archStr;
            size_t lastDot = pkgFull.rfind('.');
            if (lastDot != std::string::npos) {
                std::string maybeArch = pkgFull.substr(lastDot + 1);
                // Common architectures
                if (maybeArch == "x86_64" || maybeArch == "amd64" || maybeArch == "i386" ||
                    maybeArch == "i686" || maybeArch == "noarch" || maybeArch == "aarch64" ||
                    maybeArch == "arm64" || maybeArch == "armv7hl" || maybeArch == "ppc64le" ||
                    maybeArch == "s390x") {
                    archStr = maybeArch;
                    pkgFull = pkgFull.substr(0, lastDot);
                }
            }

            // Now find the split point between package name and version
            // Version starts at the first dash followed by a digit (looking from right)
            // e.g., "nginx-1.20.1-10.el9" -> "nginx" + "1.20.1-10.el9"
            // e.g., "vim-enhanced-8.2.2637-20.el9" -> "vim-enhanced" + "8.2.2637-20.el9"
            // Find the first dash followed by a digit (version starts there)
            int splitPos = -1;
            for (size_t i = 0; i + 1 < pkgFull.length(); i++) {
                if (pkgFull[i] == '-' && std::isdigit(pkgFull[i + 1])) {
                    splitPos = static_cast<int>(i);
                    break;
                }
            }

            if (splitPos > 0) {
                entry.packageName = pkgFull.substr(0, splitPos);
                entry.packageVersion = pkgFull.substr(splitPos + 1);
            } else {
                entry.packageName = pkgFull;
            }
            entry.architecture = archStr;

            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parseDnfLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        // DNF log has two formats:
        // 1. Subprocess: ... dnf install package
        // 2. RPM transaction: <timestamp> INSTALL <pkg>

        // Try transaction format first
        std::regex dnfRegex("(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{4})\\s+(\\S+)\\s+(\\S+)(?:\\s+(\\S+))?");
        std::smatch match;

        if (std::regex_match(line, match, dnfRegex)) {
            PackageLogEntry entry;
            // Parse ISO timestamp
            struct tm tm = {};
            std::string tsStr = match[1].str();
            if (strptime(tsStr.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
                entry.timestamp = static_cast<int64_t>(timegm(&tm));
            }
            entry.packageManager = "dnf";
            entry.operation = parseYumOperation(match[2].str()); // reuse yum operation parser
            entry.operationDetail = match[2].str();
            entry.packageName = match[3].str();
            if (match[4].matched) {
                entry.packageVersion = match[4].str();
            }
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
            continue;
        }

        // Try Subprocess format: <timestamp> COMMAND_START: ... <pid> dnf install ...
        std::regex subprocessRegex("(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{4})\\s+COMMAND_(?:START|END):");
        if (std::regex_match(line, match, subprocessRegex)) {
            // Extract package name from command if present
            std::regex pkgCmd("dnf\\s+(?:install|remove|update|erase)\\s+.*?([\\w.-]+)");
            std::smatch pkgMatch;
            if (std::regex_search(line, pkgMatch, pkgCmd)) {
                PackageLogEntry entry;
                struct tm tm = {};
                std::string tsStr = match[1].str();
                if (strptime(tsStr.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
                    entry.timestamp = static_cast<int64_t>(timegm(&tm));
                }
                entry.packageManager = "dnf";
                entry.packageName = pkgMatch[1].str();
                entry.filePath = filePath;
                entry.provenance.parserName = "PackageManagerLogParser";
                entry.provenance.parserVersion = "1.0.0";
                entry.provenance.sourceFile = filePath;
                entry.provenance.rawRecord = line;
                entries.push_back(entry);
            }
        }
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parseZypperLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        // zypper log: 2023-10-06 10:23:45 <1> install_package-1.0-1.x86_64(package)
        // or: 2023-10-06 10:23:45 <1> install package-1.0-1.x86_64 (package) arch
        std::regex zypperRegex("(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2})\\s+<\\d+>\\s+(install|remove|upgrade|downgrade)[_ ](\\S+?)(?:-(\\d[\\w.-]*))?\\((\\S+)\\)");
        std::smatch match;

        if (std::regex_search(line, match, zypperRegex)) {
            PackageLogEntry entry;
            entry.timestamp = parseZypperTimestamp(match[1].str());
            entry.packageManager = "zypper";
            entry.operation = parseYumOperation(match[2].str()); // reuse yum parser
            entry.operationDetail = match[2].str();
            // Extract package name from match
            std::string pkgName = match[3].str();
            // Remove trailing version if accidentally captured
            size_t dashVer = pkgName.rfind('-');
            if (dashVer != std::string::npos && dashVer > 0 &&
                std::isdigit(pkgName[dashVer + 1])) {
                pkgName = pkgName.substr(0, dashVer);
            }
            entry.packageName = pkgName;
            if (match[4].matched) {
                entry.packageVersion = match[4].str();
            }
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parsePacmanLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // pacman log: [2023-10-06T10:23:45+0000] [ALPM] installed package (1.0-1)
        std::regex pacmanRegex("\\[(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{4})\\]\\s+\\[ALPM\\]\\s+(installed|removed|upgraded|reinstalled|downgraded)\\s+(\\S+)(?:\\s+\\(([^)]+)\\))?");
        std::smatch match;

        if (std::regex_match(line, match, pacmanRegex)) {
            PackageLogEntry entry;
            entry.timestamp = parsePacmanTimestamp(match[1].str());
            entry.packageManager = "pacman";
            entry.operation = parsePacmanOperation(match[2].str());
            entry.operationDetail = match[2].str();
            entry.packageName = match[3].str();
            if (match[4].matched) {
                entry.packageVersion = match[4].str();
            }
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

