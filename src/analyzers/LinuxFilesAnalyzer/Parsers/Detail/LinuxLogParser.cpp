// LinuxLogParser.cpp
// System log analysis implementation

#include "../LinuxFilesAnalyzer.h"
#include "LinuxLogParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

// ============================================================================
// System Log Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeSystemLogs() {
    std::cout << "Analyzing system logs (syslog, messages)..." << std::endl;

    // Find syslog files
    auto syslogFiles = queryFilesByPattern("%/var/log/syslog%");
    auto messagesFiles = queryFilesByPattern("%/var/log/messages%");

    for (const auto& file : syslogFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "syslog");
            linuxDb_->insertLogEntries(entries);
            AuditLog::instance().log("SYSTEM", "LINUX_SYSLOG_PARSED",
                                      "Parsed " + std::to_string(entries.size()) + " syslog entries");
        }
    }

    for (const auto& file : messagesFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "messages");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

void LinuxFilesAnalyzer::analyzeAuthLogs() {
    std::cout << "Analyzing authentication logs (auth.log, secure)..." << std::endl;

    auto authFiles = queryFilesByPattern("%/var/log/auth.log%");
    auto secureFiles = queryFilesByPattern("%/var/log/secure%");

    for (const auto& file : authFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "auth");
            linuxDb_->insertLogEntries(entries);
            AuditLog::instance().log("SYSTEM", "LINUX_AUTH_PARSED",
                                      "Parsed " + std::to_string(entries.size()) + " auth.log entries");
        }
    }

    for (const auto& file : secureFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "secure");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

void LinuxFilesAnalyzer::analyzeKernelLogs() {
    std::cout << "Analyzing kernel logs..." << std::endl;

    auto kernFiles = queryFilesByPattern("%/var/log/kern.log%");
    auto dmesgFiles = queryFilesByPattern("%/var/log/dmesg%");

    for (const auto& file : kernFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "kern");
            linuxDb_->insertLogEntries(entries);
        }
    }

    for (const auto& file : dmesgFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "dmesg");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

void LinuxFilesAnalyzer::analyzeApplicationLogs() {
    std::cout << "Analyzing application logs..." << std::endl;

    // dpkg logs for package installations
    auto dpkgFiles = queryFilesByPattern("%/var/log/dpkg.log%");
    for (const auto& file : dpkgFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "dpkg");
            linuxDb_->insertLogEntries(entries);
        }
    }

    // apt history
    auto aptFiles = queryFilesByPattern("%/var/log/apt/history.log%");
    for (const auto& file : aptFiles) {
        std::string extractPath = getExtractPath("var/log/apt/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "apt");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

std::vector<LinuxLogEntry> LinuxFilesAnalyzer::parseLogFile(const std::string& logPath,
                                                             const std::string& logType) {
    std::vector<LinuxLogEntry> entries;

    std::ifstream file(logPath);
    if (!file.is_open()) {
        return entries;
    }

    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) continue;

        LinuxLogEntry entry;
        if (logType == "kern" || logType == "dmesg") {
            entry = LinuxLogParser::parseKernelLogLine(line, logPath);
        } else if (logType == "dpkg") {
            entry = LinuxLogParser::parseDpkgLogLine(line, logPath);
        } else if (logType == "apt") {
            entry = LinuxLogParser::parseAptHistoryLine(line, logPath);
        } else {
            entry = LinuxLogParser::parseSyslogLine(line, logPath);
        }

        entries.push_back(entry);
    }

    return entries;
}
