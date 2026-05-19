// SecurityBypassAnalyzer.cpp
// Security bypass and dynamic linker configuration analysis

#include "SecurityBypassAnalyzer.h"
#include <sstream>
#include <regex>
#include <algorithm>

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// ============================================================================
// ld.so.preload analysis
// ============================================================================

std::vector<SecurityBypassFinding> SecurityBypassAnalyzer::analyzeLdSoPreload(
    const std::string& content,
    const std::string& filePath) {

    std::vector<SecurityBypassFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        // Trim whitespace
        line.erase(0, line.find_first_not_of(" \t"));
        line.erase(line.find_last_not_of(" \t") + 1);
        if (line.empty() || line[0] == '#') continue;

        SecurityBypassFinding finding;
        finding.findingType = "LD_PRELOAD";
        finding.filePath = filePath;
        finding.evidence = line;
        finding.provenance.parserName = "SecurityBypassAnalyzer";
        finding.provenance.parserVersion = "1.0";
        finding.provenance.sourceFile = filePath;
        finding.provenance.rawRecord = line;

        // Any entry in ld.so.preload is suspicious by nature
        if (isSuspiciousLibrary(line)) {
            finding.severity = 5;
            finding.description = "Suspicious library in ld.so.preload: " + line;
            finding.isConfirmed = true;
        } else {
            finding.severity = 3;
            finding.description = "Library preloaded via ld.so.preload: " + line;
        }

        findings.push_back(std::move(finding));
    }
    return findings;
}

// ============================================================================
// ld.so.conf analysis
// ============================================================================

std::vector<SecurityBypassFinding> SecurityBypassAnalyzer::analyzeLdSoConf(
    const std::string& content,
    const std::string& filePath) {

    std::vector<SecurityBypassFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        line.erase(0, line.find_first_not_of(" \t"));
        line.erase(line.find_last_not_of(" \t") + 1);
        if (line.empty() || line[0] == '#') continue;

        // "include" directives are normal, but custom paths are suspicious
        if (line.find("include") == 0) continue;

        if (isSuspiciousPath(line)) {
            SecurityBypassFinding finding;
            finding.findingType = "DYNAMIC_LINKER_HIJACK";
            finding.filePath = filePath;
            finding.severity = 4;
            finding.description = "Suspicious library path in ld.so.conf: " + line;
            finding.evidence = line;
            finding.provenance.parserName = "SecurityBypassAnalyzer";
            finding.provenance.parserVersion = "1.0";
            finding.provenance.sourceFile = filePath;
            finding.provenance.rawRecord = line;
            findings.push_back(std::move(finding));
        }
    }
    return findings;
}

// ============================================================================
// Environment file analysis
// ============================================================================

std::vector<SecurityBypassFinding> SecurityBypassAnalyzer::analyzeEnvironmentFiles(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<SecurityBypassFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        SecurityBypassFinding finding;
        finding.provenance.parserName = "SecurityBypassAnalyzer";
        finding.provenance.parserVersion = "1.0";
        finding.provenance.sourceFile = filePath;
        finding.provenance.rawRecord = line;
        finding.username = username;
        finding.filePath = filePath;

        // Check for LD_PRELOAD
        if (line.find("LD_PRELOAD") != std::string::npos) {
            finding.findingType = "LD_PRELOAD";
            finding.severity = 5;
            finding.description = "LD_PRELOAD set in environment: " + line;
            finding.evidence = line;
            findings.push_back(std::move(finding));
        }
        // Check for LD_LIBRARY_PATH
        else if (line.find("LD_LIBRARY_PATH") != std::string::npos) {
            finding.findingType = "ENV_HIJACK";
            finding.severity = 3;
            finding.description = "LD_LIBRARY_PATH modified: " + line;
            finding.evidence = line;
            findings.push_back(std::move(finding));
        }
        // Check for PATH manipulation with relative paths or temp directories
        else if (line.find("PATH") != std::string::npos &&
                 (line.find("/tmp") != std::string::npos ||
                  line.find("/var/tmp") != std::string::npos ||
                  line.find(":.") != std::string::npos)) {
            finding.findingType = "PATH_MANIPULATION";
            finding.severity = 4;
            finding.description = "PATH contains suspicious directories: " + line;
            finding.evidence = line;
            findings.push_back(std::move(finding));
        }
    }
    return findings;
}

// ============================================================================
// Shell startup file analysis
// ============================================================================

std::vector<SecurityBypassFinding> SecurityBypassAnalyzer::analyzeShellStartup(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<SecurityBypassFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        // Skip comments and empty lines
        if (line.empty() || line[0] == '#') continue;

        SecurityBypassFinding finding;
        finding.provenance.parserName = "SecurityBypassAnalyzer";
        finding.provenance.parserVersion = "1.0";
        finding.provenance.sourceFile = filePath;
        finding.provenance.rawRecord = line;
        finding.username = username;
        finding.filePath = filePath;

        // Check for LD_PRELOAD export
        if (line.find("export LD_PRELOAD") != std::string::npos ||
            line.find("LD_PRELOAD=") != std::string::npos) {
            finding.findingType = "LD_PRELOAD";
            finding.severity = 5;
            finding.description = "LD_PRELOAD set in shell startup: " + line;
            finding.evidence = line;
            findings.push_back(std::move(finding));
        }
        // Check for reverse shells or suspicious connections
        else if (line.find("/dev/tcp/") != std::string::npos ||
                 line.find("nc -e") != std::string::npos ||
                 line.find("ncat") != std::string::npos ||
                 line.find("bash -i") != std::string::npos) {
            finding.findingType = "ENV_HIJACK";
            finding.severity = 5;
            finding.description = "Potential reverse shell in startup file: " + line;
            finding.evidence = line;
            findings.push_back(std::move(finding));
        }
        // Check for command aliasing to intercept commands
        else if (line.find("alias ") != std::string::npos &&
                 (line.find("alias sudo") != std::string::npos ||
                  line.find("alias su") != std::string::npos ||
                  line.find("alias ssh") != std::string::npos)) {
            finding.findingType = "PATH_MANIPULATION";
            finding.severity = 4;
            finding.description = "Command aliasing for privilege tools: " + line;
            finding.evidence = line;
            findings.push_back(std::move(finding));
        }
    }
    return findings;
}

// ============================================================================
// PATH manipulation detection
// ============================================================================

std::vector<SecurityBypassFinding> SecurityBypassAnalyzer::analyzePathManipulation(
    const std::string& pathEnv,
    const std::string& filePath) {

    std::vector<SecurityBypassFinding> findings;
    std::istringstream stream(pathEnv);
    std::string dir;

    while (std::getline(stream, dir, ':')) {
        if (isSuspiciousPath(dir)) {
            SecurityBypassFinding finding;
            finding.findingType = "PATH_MANIPULATION";
            finding.filePath = filePath;
            finding.severity = 4;
            finding.description = "Suspicious directory in PATH: " + dir;
            finding.evidence = dir;
            finding.provenance.parserName = "SecurityBypassAnalyzer";
            finding.provenance.parserVersion = "1.0";
            finding.provenance.sourceFile = filePath;
            findings.push_back(std::move(finding));
        }
    }
    return findings;
}

// ============================================================================
// Library injection detection
// ============================================================================

std::vector<SecurityBypassFinding> SecurityBypassAnalyzer::analyzeLibraryInjection(
    const std::string& content,
    const std::string& filePath) {

    std::vector<SecurityBypassFinding> findings;

    // Check for LD_PRELOAD in any config file
    if (content.find("LD_PRELOAD") != std::string::npos) {
        SecurityBypassFinding finding;
        finding.findingType = "DYNAMIC_LINKER_HIJACK";
        finding.filePath = filePath;
        finding.severity = 5;
        finding.description = "LD_PRELOAD reference detected";
        finding.evidence = "LD_PRELOAD found in file";
        finding.provenance.parserName = "SecurityBypassAnalyzer";
        finding.provenance.parserVersion = "1.0";
        finding.provenance.sourceFile = filePath;
        findings.push_back(std::move(finding));
    }

    return findings;
}

// ============================================================================
// Helper methods
// ============================================================================

bool SecurityBypassAnalyzer::isSuspiciousLibrary(const std::string& libPath) {
    // Suspicious if in temp directories or has unusual names
    if (libPath.find("/tmp") != std::string::npos ||
        libPath.find("/var/tmp") != std::string::npos ||
        libPath.find("/dev/shm") != std::string::npos) {
        return true;
    }
    // Suspicious if hidden file
    if (libPath.find("/.") != std::string::npos) {
        return true;
    }
    return false;
}

bool SecurityBypassAnalyzer::isSuspiciousPath(const std::string& path) {
    if (path.find("/tmp") != std::string::npos ||
        path.find("/var/tmp") != std::string::npos ||
        path.find("/dev/shm") != std::string::npos ||
        path.find("/var/crash") != std::string::npos) {
        return true;
    }
    // Relative paths in library config
    if (!path.empty() && path[0] != '/') {
        return true;
    }
    return false;
}

int SecurityBypassAnalyzer::assessSeverity(const std::string& findingType,
                                            const std::string& evidence) {
    if (findingType == "LD_PRELOAD") return 5;
    if (findingType == "DYNAMIC_LINKER_HIJACK") return 4;
    if (findingType == "PATH_MANIPULATION") return 4;
    if (findingType == "ENV_HIJACK") return 3;
    return 2;
}

} // namespace linux
} // namespace forensics
