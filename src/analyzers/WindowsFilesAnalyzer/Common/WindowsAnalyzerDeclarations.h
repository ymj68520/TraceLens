// WindowsAnalyzerDeclarations.h
// Declarations for WindowsFilesAnalyzer class

#pragma once
#ifndef WINDOWS_ANALYZER_DECLARATIONS_H
#define WINDOWS_ANALYZER_DECLARATIONS_H

#include <string>
#include <vector>
#include <memory>
#include "WindowsDataTypes.h"
#include "WindowsAnalysisDatabase.h"
#include <libevtx.h>

// Forward declarations
class DatabaseManager;
class FileExtractor;
struct FileRecord;

/**
 * @brief Analyzes Windows file system and artifacts
 * Handles parsing of Registry, Event Logs, Prefetch, LNK, and other Windows artifacts.
 */
class WindowsFilesAnalyzer {
public:
    WindowsFilesAnalyzer();
    /**
     * @brief Construct a new Windows Files Analyzer
     * @param imagePath Path to disk image
     * @param dbManager Database manager
     */
    WindowsFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);
    ~WindowsFilesAnalyzer();

    // Initialization
    // Initialization
    bool initialize();
    void setOutputDatabasePath(const std::string& path) { outputDbPath_ = path; }
    void setExtractDirectory(const std::string& path) { extractDir_ = path; }

    /**
     * @brief Main analysis entry point
     * Orchestrates the analysis of all Windows artifacts.
     * This is a MANDATORY step that includes LLM analysis for AI insights.
     */
    void analyzeWindowsData();

    /**
     * @brief Analyze Windows artifacts with LLM for AI-powered insights
     * This is a MANDATORY step for Windows forensics.
     * All parsed system artifacts are analyzed by AI to provide contextual understanding.
     */
    void analyzeWithLLM();

    // Windows system file analysis
    // Windows system file analysis
    /** @brief Analyze Registry hives (SYSTEM, SOFTWARE, SAM, etc.) */
    void analyzeRegistryHives();
    /** @brief Analyze Windows Event Logs (.evtx) */
    void analyzeEventLogs();
    /** @brief Analyze Prefetch files */
    void analyzePrefetchFiles();
    /** @brief Analyze Shortcut (.lnk) files */
    void analyzeLnkFiles();
    /** @brief Analyze Jump Lists */
    void analyzeJumpLists();
    /** @brief Analyze Recycle Bin ($Recycle.Bin) */
    void analyzeRecycleBin();
    /** @brief Analyze NTFS metadata (MFT) */
    void analyzeNTFSMetadata();

    // System configuration analysis
    void analyzeWindowsServices();
    void analyzeScheduledTasks();
    void analyzeAmcache();
    void analyzeSRUM();

    // User data analysis
    void analyzeUserProfiles();
    void analyzeBrowserData();
    void analyzeRecentDocuments();

    // Individual parsers (public for testing)
    std::vector<RegistryValue> parseRegistryHive(const std::string& hivePath, 
                                                  const std::string& hiveType);
    std::vector<EventLogEntry> parseEventLog(const std::string& logPath);
    PrefetchInfo parsePrefetchFile(const std::string& prefetchPath);
    LnkFileInfo parseLnkFile(const std::string& lnkPath);
    std::vector<JumpListEntry> parseJumpListFile(const std::string& jumpListPath);
    std::vector<RecycleBinEntry> parseRecycleBin(const std::string& recycleBinPath);

private:
    // File extraction helpers
    bool extractWindowsSystemFiles(const std::string& outputDir);
    std::vector<FileRecord> queryWindowsSystemFiles();
    std::vector<FileRecord> queryFilesByPattern(const std::string& pathPattern);
    std::vector<FileRecord> queryFilesByCategory(const std::string& category);
    bool extractFileToPath(int64_t inode, const std::string& outputPath, int partitionNum = -1);

    // Registry parsing helpers
    std::vector<WindowsUserInfo> parseUserAccountsFromSAM(const std::string& samPath);
    std::vector<USBDeviceInfo> parseUSBDevicesFromRegistry(const std::string& systemPath);
    std::vector<WindowsServiceInfo> parseServicesFromRegistry(const std::string& systemPath);
    std::vector<WiFiProfileInfo> parseWiFiProfilesFromRegistry(const std::string& softwarePath);
    std::vector<RDPConnectionInfo> parseRDPConnectionsFromRegistry(const std::string& ntuserPath);
    std::vector<ShimcacheEntryInfo> parseShimcacheFromRegistry(const std::string& systemPath);
    std::vector<UserAssistEntryInfo> parseUserAssistFromRegistry(const std::string& ntuserPath);

    // Event Log parsing helpers
    std::pair<std::vector<EventLogEntry>, int> parseEventLogWithRecovery(const std::string& logPath);
    EventLogEntry extractEventLogEntry(libevtx_record_t* record,
                                       const std::string& logSource,
                                       const std::string& logPath,
                                       bool isRecovered);

    // Path utilities
    std::string getExtractPath(const std::string& relativePath);
    bool isWindowsPath(const std::string& path);
    std::string normalizeWindowsPath(const std::string& path);

    // Binary parsing utilities
    uint16_t readUInt16LE(const char* data);
    uint32_t readUInt32LE(const char* data);
    uint64_t readUInt64LE(const char* data);
    int64_t filetimeToUnixTime(uint64_t filetime);
    std::string readNullTerminatedString(const char* data, size_t maxLen);
    std::string readUTF16LEString(const char* data, size_t maxLen);

    // Private members
    std::string imagePath_;
    std::string outputDbPath_;
    std::string extractDir_;
    DatabaseManager* dbManager_;
    std::unique_ptr<FileExtractor> fileExtractor_;
    std::unique_ptr<WindowsAnalysisDatabase> windowsDb_;
};

#endif // WINDOWS_ANALYZER_DECLARATIONS_H
