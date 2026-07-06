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

/**
 * @brief Analyzes Linux file system and artifacts
 * Handles parsing of logs, user accounts, history, and system configuration.
 */
class LinuxFilesAnalyzer {
public:
    LinuxFilesAnalyzer();
    /**
     * @brief Construct a new Linux Files Analyzer
     * @param imagePath Path to disk image
     * @param dbManager Database manager
     */
    LinuxFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);
    ~LinuxFilesAnalyzer();

    // Initialization
    bool initialize();
    void setOutputDatabasePath(const std::string& path) { outputDbPath_ = path; }
    void setExtractDirectory(const std::string& path) { extractDir_ = path; }
    void setSkipAI(bool skip) { skipAI_ = skip; }

    /**
     * @brief Main analysis entry point
     * Orchestrates the analysis of all Linux artifacts.
     * This is a MANDATORY step that includes LLM analysis for AI insights.
     */
    void analyzeLinuxData();

    /**
     * @brief Server/Cloud analysis entry point
     * Focuses on server and cloud-specific artifacts: containers, web servers,
     * cloud logs, network configuration, security posture, and extended history.
     */
    void analyzeServerCloudArtifacts();

    /**
     * @brief Analyze Linux artifacts with LLM for AI-powered insights
     * This is a MANDATORY step for Linux forensics.
     * All parsed system artifacts are analyzed by AI to provide contextual understanding.
     */
    void analyzeWithLLM();

    // Compressed and rotated log analysis (Phase 1)
    /** @brief Analyze compressed and rotated log files (.gz, .xz, .bz2, .zst) */
    void analyzeCompressedLogs();

    // System log analysis
    /** @brief Analyze system logs (syslog, messages) */
    void analyzeSystemLogs();
    /** @brief Analyze authentication logs (auth.log, secure) */
    void analyzeAuthLogs();
    /** @brief Analyze kernel logs (kern.log) */
    void analyzeKernelLogs();
    /** @brief Analyze application specific logs */
    void analyzeApplicationLogs();

    // Journal analysis (Phase 2)
    /** @brief Analyze systemd-journald journal files */
    void analyzeJournalLogs();

    // User and authentication analysis
    // User and authentication analysis
    /** @brief Analyze user accounts (/etc/passwd, shadow) */
    void analyzeUserAccounts();
    /** @brief Analyze login history (wtmp, btmp) */
    void analyzeLoginHistory();
    /** @brief Analyze SSH keys and config */
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

    // Container analysis
    void analyzeDockerContainers();
    void analyzeDockerImages();
    void analyzeDockerVolumes();
    void analyzePodmanContainers();

    // Web server analysis
    void analyzeApacheServers();
    void analyzeNginxServers();

    // Security posture analysis
    void analyzeSetuidFiles();
    void analyzeCapabilities();
    void analyzeSELinux();
    void analyzeAppArmor();

    // Enhanced analysis
    void analyzeLogTampering();
    void analyzePersistenceMechanisms();
    void analyzeMiddlewareLogs();
    void analyzeContainerRuntimeLogs();
    void analyzePackageManagerLogs();
    void analyzeAccountSSHSecurity();
    void analyzeDatabaseLogs();
    void analyzeEmailVPNLogs();
    void analyzeFirewallSecurityLogs();

    // Phase 12: USB/Mount/Desktop/Cloud
    void analyzeUSBEvents();
    void analyzeMountEntries();
    void analyzeCloudLogs();

    // Phase 13: Extended history
    void analyzeExtendedHistory();

    // Phase 14: Security bypass
    void analyzeSecurityBypass();

    // Phase 15: Pseudo-filesystem markers
    void analyzePseudoFilesystems();

    // Phase 16: DNS configuration
    void analyzeDNSConfiguration();

    // Phase 17: CUPS logs
    void analyzeCUPSLogs();

    // Phase 18: systemd-coredump
    void analyzeCoredumps();

    // Phase 19: Snap/Flatpak packages
    void analyzeSnapFlatpak();

    // Phase 20: Browser detailed data
    void analyzeBrowserDetailedData();

    // Phase 21: XDG desktop artifacts
    void analyzeXDGArtifacts();

    // Phase 16: Rule engine
    void analyzeWithRuleEngine();

    void correlateEvents();
    void reconstructTimeline();
    void detectAnomalies();

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
    bool extractFileToPath(int64_t inode, const std::string& outputPath, int partitionNum = -1);

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
    bool skipAI_ = false;
    DatabaseManager* dbManager_;
    std::unique_ptr<FileExtractor> fileExtractor_;
    std::unique_ptr<LinuxAnalysisDatabase> linuxDb_;
};

#endif // LINUX_ANALYZER_DECLARATIONS_H
