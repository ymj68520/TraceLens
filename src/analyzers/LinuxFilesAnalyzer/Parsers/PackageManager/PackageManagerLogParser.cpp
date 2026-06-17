// PackageManagerLogParser.cpp
// Implementation of package manager log parser
// Phase 9: Package Manager Log Enhancement
//
// This file holds the dispatcher (detectPackageManagerType, parsePackageManagerLog)
// and the shared timestamp/operation helpers. The per-distro parser implementations
// live in sibling translation units:
//   - PackageManagerLogParser_LinuxParsers.cpp           (apt/dpkg/yum/dnf/zypper/pacman)
//   - PackageManagerLogParser_UniversalAndAnalysis.cpp   (snap/flatpak + suspicious-pattern matching)

#ifdef linux
#undef linux
#endif

#include "PackageManagerLogParser.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <ctime>

using namespace forensics::linux;

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

