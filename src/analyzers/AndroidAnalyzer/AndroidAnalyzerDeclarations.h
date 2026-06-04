// AndroidAnalyzerDeclarations.h
// Declarations for AndroidAnalyzer class

#pragma once

#include "AndroidDataTypes.h"
#include "AndroidAnalysisDatabase.h"
#include <string>
#include <vector>
#include <memory>
#include "fileSystem.h"

class DatabaseManager;
class FileExtractor;

/**
 * @brief Analyzes Android device data
 * Handles parsing of Android artifacts including databases, logs, and system configs.
 */
class AndroidAnalyzer {
public:
    AndroidAnalyzer();
    /**
     * @brief Construct a new Android Analyzer
     * @param imagePath Path to the disk image or directory
     * @param dbManager Database manager for storing results
     */
    AndroidAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);
    ~AndroidAnalyzer();

    /**
     * @brief Main entry point to analyze a directory
     * @param rootPath Root path of the mounted image or backup
     */
    void analyze(const std::string& rootPath);

    // Android specific analysis
    // Android specific analysis
    /**
     * @brief Initialize the analyzer
     * @return true if initialization successful
     */
    bool initialize();
    
    void setOutputDatabasePath(const std::string& path) { outputDbPath_ = path; }

    void setWeChatPassword(const std::string& password) { wechatPassword_ = password; }
    const std::string& getWeChatPassword() const { return wechatPassword_; }
    
    /**
     * @brief Analyze all Android data
     */
    void analyzeAndroidData();

    /**
     * @brief Analyze the /system directory
     * @param systemPath Path to system directory
     */
    void analyzeSystemDirectory(const std::string& systemPath);

    // Specific analyzers
    std::vector<ChatMessage> parseWhatsApp(const std::string& dbPath);
    std::vector<ChatMessage> parseWeChat(const std::string& dbPath);
    std::vector<ChatMessage> parseTelegram(const std::string& dbPath);
    
    // New Analyzers
    void parseChromeHistory(const std::string& dbPath);
    bool parseWifiConfig(const std::string& configPath);
    void parseInstalledPackages(const std::string& xmlPath);
    void parseUsageStats(const std::string& usageStatsPath);
    
    // APK Analysis
    ApkSignatureInfo analyzeApk(const std::string& apkPath);
    
    // System Log Analysis
    void analyzeSystemLogs();
    std::vector<SystemLogEntry> parseSystemLogFile(const std::string& filePath, const std::string& originalPath);
    std::string getLogTypeFromPath(const std::string& path);

private:
    void scanUserData(const std::string& dataPath);
    void processAppDirectory(const std::string& appPath);
    bool isSQLiteDatabase(const std::string& filePath);
    
    // Helper to execute SQL query
    std::vector<std::map<std::string, std::string>> executeQuery(const std::string& dbPath, const std::string& query);

    // Android data parsing methods
    bool extractAndParseDB(const std::string& dbPathInImage, const std::string& tempPath);
    void parseSMS(const std::string& dbPath);
    void parseContacts(const std::string& dbPath);
    void parseCallLog(const std::string& dbPath);
    void parseGenericAppData(const std::string& packageName, const std::string& dbPath);

    // System analysis methods
    void scanSystemApps(const std::string& appDirPath);
    SystemAppInfo analyzeSystemApk(const std::string& apkPath, bool isPrivileged);
    void analyzeBuildProperties(const std::string& buildPropPath);
    void scanFrameworkDirectory(const std::string& frameworkPath);
    void extractAndScanSystemApps(const std::string& imageAppDir, const std::string& tempAppDir);
    void extractAndScanFramework(const std::string& imageFrameworkDir, const std::string& tempFrameworkDir);

    // Build.prop analysis methods
    BuildPropAnalysisResult analyzeBuildPropFile(const std::string& buildPropPath);
    void generateBuildPropReport(const BuildPropAnalysisResult& result, const std::string& outputPath);
    void generateUnrecognizedPropertiesReport(const std::vector<BuildPropEntry>& unrecognizedEntries, const std::string& outputPath);

    // Build.prop helper methods
    BuildPropEntry parseBuildPropEntry(const std::string& line);
    DeviceInfo extractDeviceInfo(const std::vector<BuildPropEntry>& entries);
    SecurityConfig extractSecurityConfig(const std::vector<BuildPropEntry>& entries);
    SystemConfig extractSystemConfig(const std::vector<BuildPropEntry>& entries);
    ForensicAnalysis performForensicAnalysis(const std::vector<BuildPropEntry>& entries, const DeviceInfo& deviceInfo);

    // Private members
    std::string imagePath_;
    std::string outputDbPath_;
    DatabaseManager* dbManager_;
    std::unique_ptr<FileExtractor> fileExtractor_;
    std::unique_ptr<AndroidAnalysisDatabase> androidDb_;
    std::string wechatPassword_;
};
