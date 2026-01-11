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

class WindowsFilesAnalyzer {
public:
    WindowsFilesAnalyzer();
    WindowsFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);
    ~WindowsFilesAnalyzer();

    // Initialization
    bool initialize();
    void setOutputDatabasePath(const std::string& path) { outputDbPath_ = path; }
    void setExtractDirectory(const std::string& path) { extractDir_ = path; }

    // Main analysis entry point
    void analyzeWindowsData();

    // Windows system file analysis
    void analyzeRegistryHives();
    void analyzeEventLogs();
    void analyzePrefetchFiles();
    void analyzeLnkFiles();
    void analyzeJumpLists();
    void analyzeRecycleBin();
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
    bool extractFileToPath(int64_t inode, const std::string& outputPath);

    // Registry parsing helpers
    std::vector<WindowsUserInfo> parseUserAccountsFromSAM(const std::string& samPath);
    std::vector<USBDeviceInfo> parseUSBDevicesFromRegistry(const std::string& systemPath);
    std::vector<WindowsServiceInfo> parseServicesFromRegistry(const std::string& systemPath);

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
