// PackageManagerLogParser.cpp
// Implementation of package manager log parser
// Phase 9: Package Manager Log Enhancement

#ifdef linux
#undef linux
#endif

#include "PackageManagerLogParser.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <ctime>

using namespace forensics::linux;

// ============================================================================
// APT history.log Parsing
// Format: Start-Date: YYYY-MM-DD  HH:MM:SS
//         Commandline: apt-get install package
//         Install: package:arch (version, repository)
// ============================================================================

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

// ============================================================================
// APT term.log Parsing
// Format: Log started: YYYY-MM-DD  HH:MM:SS
//         (Reading database ... )
//         (Reading ... )
//         Preparing to unpack .../package_version_arch.deb ...
// ============================================================================

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

// ============================================================================
// dpkg.log Parsing
// Format: YYYY-MM-DD HH:MM:SS status <action> <package> <version>
//         YYYY-MM-DD HH:MM:SS install <package> <version> <architecture>
// ============================================================================

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

// ============================================================================
// yum.log Parsing
// Format: MMM DD HH:MM:SS Action: package-version.arch
// Or:     Oct 06 10:23:45 Installed: package-1.0-1.el7.x86_64
// ============================================================================

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

// ============================================================================
// dnf.log Parsing (similar to yum but with some differences)
// ============================================================================

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

// ============================================================================
// zypper.log Parsing
// Format: YYYY-MM-DD HH:MM:SS <action> package-version.arch
// ============================================================================

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

// ============================================================================
// pacman.log Parsing
// Format: [YYYY-MM-DDTHH:MM:SS+ZZZZ] [ACTION] package-version
// ============================================================================

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

// ============================================================================
// snap log Parsing
// ============================================================================

std::vector<PackageLogEntry> PackageManagerLogParser::parseSnapLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // snap changes output: ID  Status  Spawn  Ready  Summary
        // or snap log format with timestamps
        std::regex snapRegex("(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{2}:?\\d{2})\\s+.*?\\s+(install|remove|refresh|revert)\\s+\"?(\\S+?)\"?\\s");
        std::smatch match;

        if (std::regex_search(line, match, snapRegex)) {
            PackageLogEntry entry;
            struct tm tm = {};
            std::string tsStr = match[1].str();
            if (strptime(tsStr.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
                entry.timestamp = static_cast<int64_t>(timegm(&tm));
            }
            entry.packageManager = "snap";
            std::string op = match[2].str();
            if (op == "install") entry.operation = PackageOperation::INSTALL;
            else if (op == "remove") entry.operation = PackageOperation::REMOVE;
            else if (op == "refresh") entry.operation = PackageOperation::UPGRADE;
            else if (op == "revert") entry.operation = PackageOperation::DOWNGRADE;
            else entry.operation = PackageOperation::UNKNOWN;
            entry.operationDetail = op;
            entry.packageName = match[3].str();
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

// ============================================================================
// flatpak log Parsing
// ============================================================================

std::vector<PackageLogEntry> PackageManagerLogParser::parseFlatpakLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // flatpak log: similar to "Installing app/org.app/x86_64/stable from remote"
        std::regex flatpakRegex("(Installing|Uninstalling|Updating)\\s+(\\S+)");
        std::smatch match;

        if (std::regex_search(line, match, flatpakRegex)) {
            PackageLogEntry entry;
            entry.packageManager = "flatpak";
            std::string op = match[1].str();
            if (op == "Installing") entry.operation = PackageOperation::INSTALL;
            else if (op == "Uninstalling") entry.operation = PackageOperation::REMOVE;
            else if (op == "Updating") entry.operation = PackageOperation::UPGRADE;
            else entry.operation = PackageOperation::UNKNOWN;
            entry.operationDetail = op;
            entry.packageName = match[2].str();
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

// ============================================================================
// Auto-detection and unified parsing
// ============================================================================

std::string PackageManagerLogParser::detectPackageManagerType(
    const std::string& content, const std::string& filePath) {
    // Check by file path first
    if (filePath.find("apt/history") != std::string::npos) return "apt-history";
    if (filePath.find("apt/term") != std::string::npos) return "apt-term";
    if (filePath.find("dpkg") != std::string::npos) return "dpkg";
    if (filePath.find("yum") != std::string::npos) return "yum";
    if (filePath.find("dnf") != std::string::npos) return "dnf";
    if (filePath.find("zypper") != std::string::npos) return "zypper";
    if (filePath.find("pacman") != std::string::npos) return "pacman";
    if (filePath.find("snap") != std::string::npos) return "snap";
    if (filePath.find("flatpak") != std::string::npos) return "flatpak";

    // Check by content
    if (content.find("Start-Date:") != std::string::npos) return "apt-history";
    if (content.find("Log started:") != std::string::npos) return "apt-term";
    if (content.find("status ") == 0 || content.find("install ") == 0) return "dpkg";
    if (content.find("Installed:") != std::string::npos || content.find("Removed:") != std::string::npos) return "yum";
    if (content.find("[ALPM]") != std::string::npos) return "pacman";
    if (content.find("snap") != std::string::npos && content.find("install") != std::string::npos) return "snap";
    if (content.find("Installing") != std::string::npos || content.find("Uninstalling") != std::string::npos) return "flatpak";

    return "unknown";
}

std::vector<PackageLogEntry> PackageManagerLogParser::parsePackageManagerLog(
    const std::string& content, const std::string& filePath) {
    std::string type = detectPackageManagerType(content, filePath);

    if (type == "apt-history") return parseAptHistoryLog(content, filePath);
    if (type == "apt-term") return parseAptTermLog(content, filePath);
    if (type == "dpkg") return parseDpkgLog(content, filePath);
    if (type == "yum") return parseYumLog(content, filePath);
    if (type == "dnf") return parseDnfLog(content, filePath);
    if (type == "zypper") return parseZypperLog(content, filePath);
    if (type == "pacman") return parsePacmanLog(content, filePath);
    if (type == "snap") return parseSnapLog(content, filePath);
    if (type == "flatpak") return parseFlatpakLog(content, filePath);

    return {};
}

// ============================================================================
// Security Analysis
// ============================================================================

std::vector<PackagePattern> PackageManagerLogParser::getAttackToolPatterns() {
    return {
        {"nmap", "network_scanner", "high", "Network port scanner used for reconnaissance"},
        {"masscan", "network_scanner", "high", "Fast network port scanner"},
        {"hydra", "password_cracker", "critical", "Password brute-force tool"},
        {"john", "password_cracker", "critical", "John the Ripper password cracker"},
        {"hashcat", "password_cracker", "critical", "GPU-based password cracker"},
        {"aircrack-ng", "wireless_attack", "critical", "WiFi network cracking tool"},
        {"metasploit", "exploit_framework", "critical", "Metasploit penetration testing framework"},
        {"msfconsole", "exploit_framework", "critical", "Metasploit console"},
        {"sqlmap", "web_attack", "critical", "SQL injection automation tool"},
        {"burpsuite", "web_attack", "high", "Web application security testing"},
        {"nikto", "web_scanner", "high", "Web server vulnerability scanner"},
        {"dirb", "web_scanner", "medium", "Web content directory scanner"},
        {"gobuster", "web_scanner", "medium", "Directory/file brute-forcer"},
        {"wfuzz", "web_fuzzer", "medium", "Web application fuzzer"},
        {"responder", "network_attack", "critical", "LLMNR/NBT-NS/MDNS poisoner"},
        {"impacket", "network_attack", "high", "Network protocol tools collection"},
        {"mimikatz", "credential_theft", "critical", "Windows credential extraction"},
        {"bloodhound", "ad_attack", "high", "Active Directory attack path analysis"},
        {"empire", "c2_framework", "critical", "PowerShell/Python post-exploitation framework"},
        {"cobalt-strike", "c2_framework", "critical", "Commercial penetration testing tool"},
        {"linpeas", "privilege_escalation", "high", "Linux privilege escalation enumeration"},
        {"winpeas", "privilege_escalation", "high", "Windows privilege escalation enumeration"},
        {"pspy", "process_monitor", "medium", "Process monitor for privilege escalation"},
        {"chisel", "tunneling", "high", "TCP/UDP tunnel over HTTP"},
        {"socat", "tunneling", "medium", "Multipurpose relay tool"},
        {"netcat", "network_tool", "medium", "Network utility (nc/ncat)"},
        {"ncat", "network_tool", "medium", "Nmap's netcat implementation"},
        {"socat", "network_tool", "medium", "Socket relay tool"},
        {"proxychains", "proxy", "high", "Force TCP connections through proxy"},
        {"tor", "anonymization", "medium", "Anonymity network client"},
        {"wireshark", "packet_capture", "medium", "Network protocol analyzer"},
        {"tcpdump", "packet_capture", "medium", "Command-line packet analyzer"},
        {"ettercap", "mitm", "high", "MITM attack framework"},
        {"bettercap", "mitm", "high", "Network attack and monitoring framework"},
        {"beef", "web_attack", "high", "Browser exploitation framework"},
        {"set", "social_engineering", "high", "Social Engineering Toolkit"},
        {"veil", "evasion", "high", "Payload generator for AV evasion"},
        {"shellter", "evasion", "high", "Dynamic shellcode injection"},
        {"reverse-shell", "backdoor", "critical", "Reverse shell handler"},
        {"weevely", "web_backdoor", "critical", "Web shell generator"},
        {"webshell", "web_backdoor", "critical", "Web shell for remote access"},
    };
}

std::vector<PackagePattern> PackageManagerLogParser::getSecurityToolPatterns() {
    return {
        {"selinux", "security_framework", "high", "SELinux security framework"},
        {"apparmor", "security_framework", "high", "AppArmor security framework"},
        {"fail2ban", "intrusion_prevention", "high", "Intrusion prevention tool"},
        {"aide", "file_integrity", "high", "Advanced Intrusion Detection Environment"},
        {"tripwire", "file_integrity", "high", "File integrity monitoring"},
        {"ossec", "ids", "high", "Host-based intrusion detection"},
        {"snort", "ids", "high", "Network intrusion detection"},
        {"suricata", "ids", "high", "Network threat detection engine"},
        {"clamav", "antivirus", "high", "Open-source antivirus engine"},
        {"rkhunter", "rootkit_detection", "high", "Rootkit scanner"},
        {"chkrootkit", "rootkit_detection", "high", "Rootkit detector"},
        {"lynis", "security_audit", "medium", "Security auditing tool"},
        {"ufw", "firewall", "high", "Uncomplicated Firewall"},
        {"iptables", "firewall", "high", "Linux firewall administration"},
        {"nftables", "firewall", "high", "Netfilter tables"},
        {"auditd", "audit", "high", "Linux audit daemon"},
    };
}

std::vector<SuspiciousPackageFinding> PackageManagerLogParser::analyzeSuspiciousPackages(
    const std::vector<PackageLogEntry>& entries) {
    std::vector<SuspiciousPackageFinding> findings;

    auto attackPatterns = getAttackToolPatterns();
    auto securityPatterns = getSecurityToolPatterns();

    for (const auto& entry : entries) {
        // Check for attack tools
        for (const auto& pattern : attackPatterns) {
            if (entry.packageName.find(pattern.packageName) != std::string::npos) {
                SuspiciousPackageFinding finding;
                finding.findingType = pattern.category;
                finding.severity = pattern.severity;
                finding.packageName = entry.packageName;
                finding.packageVersion = entry.packageVersion;
                finding.description = pattern.description;
                finding.evidence = "Package operation: " + operationToString(entry.operation) +
                                   " " + entry.packageName;
                finding.filePath = entry.filePath;
                finding.provenance = entry.provenance;
                findings.push_back(finding);
                break; // Only one match per entry
            }
        }

        // Check for security tool removals
        if (entry.operation == PackageOperation::REMOVE ||
            entry.operation == PackageOperation::PURGE) {
            for (const auto& pattern : securityPatterns) {
                if (entry.packageName.find(pattern.packageName) != std::string::npos) {
                    SuspiciousPackageFinding finding;
                    finding.findingType = "security_removal";
                    finding.severity = "critical";
                    finding.packageName = entry.packageName;
                    finding.packageVersion = entry.packageVersion;
                    finding.description = "Security tool removed: " + pattern.description;
                    finding.evidence = "Removed: " + entry.packageName;
                    finding.filePath = entry.filePath;
                    finding.provenance = entry.provenance;
                    findings.push_back(finding);
                    break;
                }
            }
        }
    }

    return findings;
}

// ============================================================================
// Timestamp Parsers
// ============================================================================

int64_t PackageManagerLogParser::parseAptTimestamp(const std::string& timestampStr) {
    // APT format: YYYY-MM-DD  HH:MM:SS
    struct tm tm = {};
    if (strptime(timestampStr.c_str(), "%Y-%m-%d  %H:%M:%S", &tm)) {
        return static_cast<int64_t>(timegm(&tm));
    }
    // Try without double space
    if (strptime(timestampStr.c_str(), "%Y-%m-%d %H:%M:%S", &tm)) {
        return static_cast<int64_t>(timegm(&tm));
    }
    return 0;
}

int64_t PackageManagerLogParser::parseDpkgTimestamp(const std::string& timestampStr) {
    // dpkg format: YYYY-MM-DD HH:MM:SS
    struct tm tm = {};
    if (strptime(timestampStr.c_str(), "%Y-%m-%d %H:%M:%S", &tm)) {
        return static_cast<int64_t>(timegm(&tm));
    }
    return 0;
}

int64_t PackageManagerLogParser::parseYumTimestamp(const std::string& timestampStr) {
    // yum format: Oct 06 10:23:45 (current year assumed)
    struct tm tm = {};
    if (strptime(timestampStr.c_str(), "%b %d %H:%M:%S", &tm)) {
        // Assume current year
        time_t now = time(nullptr);
        struct tm* nowTm = gmtime(&now);
        tm.tm_year = nowTm->tm_year;
        return static_cast<int64_t>(timegm(&tm));
    }
    return 0;
}

int64_t PackageManagerLogParser::parseZypperTimestamp(const std::string& timestampStr) {
    // zypper format: YYYY-MM-DD HH:MM:SS
    struct tm tm = {};
    if (strptime(timestampStr.c_str(), "%Y-%m-%d %H:%M:%S", &tm)) {
        return static_cast<int64_t>(timegm(&tm));
    }
    return 0;
}

int64_t PackageManagerLogParser::parsePacmanTimestamp(const std::string& timestampStr) {
    // pacman format: YYYY-MM-DDTHH:MM:SS+ZZZZ
    struct tm tm = {};
    if (strptime(timestampStr.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
        return static_cast<int64_t>(timegm(&tm));
    }
    return 0;
}

// ============================================================================
// Operation Parsers
// ============================================================================

PackageOperation PackageManagerLogParser::parseAptOperation(const std::string& opStr) {
    if (opStr == "install") return PackageOperation::INSTALL;
    if (opStr == "remove") return PackageOperation::REMOVE;
    if (opStr == "upgrade") return PackageOperation::UPGRADE;
    if (opStr == "purge") return PackageOperation::PURGE;
    if (opStr == "reinstall") return PackageOperation::REINSTALL;
    if (opStr == "hold") return PackageOperation::HOLD;
    if (opStr == "unhold") return PackageOperation::UNHOLD;
    return PackageOperation::UNKNOWN;
}

PackageOperation PackageManagerLogParser::parseDpkgOperation(const std::string& opStr) {
    if (opStr == "install") return PackageOperation::INSTALL;
    if (opStr == "remove") return PackageOperation::REMOVE;
    if (opStr == "upgrade") return PackageOperation::UPGRADE;
    if (opStr == "purge") return PackageOperation::PURGE;
    if (opStr == "configure") return PackageOperation::CONFIGURE;
    if (opStr == "trigproc") return PackageOperation::TRIGGERS;
    return PackageOperation::UNKNOWN;
}

PackageOperation PackageManagerLogParser::parseYumOperation(const std::string& opStr) {
    std::string lower = opStr;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    if (lower == "installed" || lower == "install") return PackageOperation::INSTALL;
    if (lower == "removed" || lower == "remove" || lower == "erase" || lower == "erased") return PackageOperation::REMOVE;
    if (lower == "updated" || lower == "update" || lower == "upgrade") return PackageOperation::UPGRADE;
    if (lower == "downgraded" || lower == "downgrade") return PackageOperation::DOWNGRADE;
    if (lower == "reinstalled" || lower == "reinstall") return PackageOperation::REINSTALL;
    return PackageOperation::UNKNOWN;
}

PackageOperation PackageManagerLogParser::parsePacmanOperation(const std::string& opStr) {
    if (opStr == "installed") return PackageOperation::INSTALL;
    if (opStr == "removed") return PackageOperation::REMOVE;
    if (opStr == "upgraded") return PackageOperation::UPGRADE;
    if (opStr == "reinstalled") return PackageOperation::REINSTALL;
    if (opStr == "downgraded") return PackageOperation::DOWNGRADE;
    return PackageOperation::UNKNOWN;
}

std::string PackageManagerLogParser::operationToString(PackageOperation op) {
    switch (op) {
        case PackageOperation::INSTALL: return "install";
        case PackageOperation::REMOVE: return "remove";
        case PackageOperation::UPGRADE: return "upgrade";
        case PackageOperation::DOWNGRADE: return "downgrade";
        case PackageOperation::PURGE: return "purge";
        case PackageOperation::REINSTALL: return "reinstall";
        case PackageOperation::HOLD: return "hold";
        case PackageOperation::UNHOLD: return "unhold";
        case PackageOperation::CONFIGURE: return "configure";
        case PackageOperation::TRIGGERS: return "triggers";
        default: return "unknown";
    }
}
