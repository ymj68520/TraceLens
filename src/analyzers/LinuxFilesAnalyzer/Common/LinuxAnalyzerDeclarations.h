// LinuxAnalyzerDeclarations.h
// Declarations for LinuxFilesAnalyzer class

#pragma once
#ifndef LINUX_ANALYZER_DECLARATIONS_H
#define LINUX_ANALYZER_DECLARATIONS_H

#include <string>
#include <vector>
#include <memory>
#include "LinuxDataTypes.h"

// Forward declarations
class DatabaseManager;
class FileExtractor;
struct FileRecord;
class LinuxAnalysisDatabase;

class LinuxFilesAnalyzer {
public:
    LinuxFilesAnalyzer();
    LinuxFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);
    ~LinuxFilesAnalyzer();

    // Initialization
    bool initialize();
    void setOutputDatabasePath(const std::string& path) { outputDbPath_ = path; }
    void setExtractDirectory(const std::string& path) { extractDir_ = path; }

    // Main analysis entry point
    void analyzeLinuxData();

    // System log analysis
    void analyzeSystemLogs();
    void analyzeAuthLogs();
    void analyzeKernelLogs();
    void analyzeApplicationLogs();

    // User and authentication analysis
    void analyzeUserAccounts();
    void analyzeLoginHistory();
    void analyzeSSHArtifacts();

    // Shell and command history
    void analyzeShellHistory();

    // System configuration analysis
    void analyzeCronJobs();
    void analyzeSystemdServices();
    void analyzeInstalledPackages();
    void analyzeNetworkConfiguration();

    // Security analysis
    void analyzeFirewallRules();
    void analyzeAuditLogs();

    // Browser data analysis
    void analyzeBrowserData();

    // Individual parsers (public for testing)
    std::vector<LinuxLogEntry> parseLogFile(const std::string& logPath, 
                                             const std::string& logType);
    std::vector<LinuxUserInfo> parsePasswdFile(const std::string& passwdPath);
    std::vector<LinuxUserInfo> parseShadowFile(const std::string& shadowPath,
                                                std::vector<LinuxUserInfo>& users);
    std::vector<LinuxGroupInfo> parseGroupFile(const std::string& groupPath);
    std::vector<LinuxLoginRecord> parseWtmpFile(const std::string& wtmpPath);
    std::vector<LinuxLoginRecord> parseBtmpFile(const std::string& btmpPath);
    std::vector<ShellHistoryEntry> parseHistoryFile(const std::string& historyPath,
                                                     const std::string& username,
                                                     const std::string& shellType);
    std::vector<CronJobEntry> parseCronFile(const std::string& cronPath,
                                             const std::string& username);
    std::vector<SSHKeyInfo> parseAuthorizedKeys(const std::string& keysPath,
                                                  const std::string& username);
    std::vector<PackageInfo> parseDpkgStatus(const std::string& statusPath);
    std::vector<PackageInfo> parseRpmDatabase(const std::string& rpmDbPath);
    
    // RPM package manager analysis
    void analyzeRpmPackages();
    
    // Distribution detection
    std::string detectLinuxDistribution();
    bool isRpmBasedDistro();
    bool isDpkgBasedDistro();

private:
    // File extraction helpers
    bool extractLinuxSystemFiles(const std::string& outputDir);
    std::vector<FileRecord> queryLinuxSystemFiles();
    std::vector<FileRecord> queryFilesByPattern(const std::string& pathPattern);
    std::vector<FileRecord> queryFilesByCategory(const std::string& category);
    bool extractFileToPath(int64_t inode, const std::string& outputPath);

    // Log parsing helpers
    LinuxLogEntry parseLogLine(const std::string& line, const std::string& logFile);
    int64_t parseSyslogTimestamp(const std::string& timestamp);

    // User parsing helpers
    LinuxUserInfo parsePasswdLine(const std::string& line);
    void parseShadowLine(const std::string& line, LinuxUserInfo& user);

    // Path utilities
    std::string getExtractPath(const std::string& relativePath);
    bool isLinuxPath(const std::string& path);
    std::string normalizeLinuxPath(const std::string& path);
    std::vector<std::string> findUserHomeDirectories();

    // Binary parsing utilities (for wtmp/btmp)
    uint16_t readUInt16LE(const char* data);
    uint32_t readUInt32LE(const char* data);
    uint64_t readUInt64LE(const char* data);
    std::string readFixedString(const char* data, size_t len);

    // Private members
    std::string imagePath_;
    std::string outputDbPath_;
    std::string extractDir_;
    DatabaseManager* dbManager_;
    std::unique_ptr<FileExtractor> fileExtractor_;
    std::unique_ptr<LinuxAnalysisDatabase> linuxDb_;
};

#endif // LINUX_ANALYZER_DECLARATIONS_H
