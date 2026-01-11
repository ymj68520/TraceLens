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

class AndroidAnalyzer {
public:
    AndroidAnalyzer();
    AndroidAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);
    ~AndroidAnalyzer();

    // Main entry point to analyze a directory (mounted image or extracted backup)
    void analyze(const std::string& rootPath);

    // Android specific analysis
    bool initialize();
    void setOutputDatabasePath(const std::string& path) { outputDbPath_ = path; }
    void analyzeAndroidData();
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
};
