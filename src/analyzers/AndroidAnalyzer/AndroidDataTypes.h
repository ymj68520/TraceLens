// AndroidDataTypes.h
// Common data types and structures for Android analysis

#pragma once

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include "fileSystem.h"
#include "DatabaseManager/DatabaseManagerDataTypes.h"

struct AppData {
    std::string packageName;
    std::string installPath;
    std::vector<FileRecord> dbFiles;  // 使用 FileRecord 以包含完整路径信息
};

struct ChatMessage {
    std::string sender;
    std::string receiver;
    std::string content;
    std::string timestamp;
    std::string appName;
};

struct WeChatContact {
    std::string username;
    std::string nickname;
    std::string remark;
    std::string avatarPath;
    int type = 0;
    bool isChatroom = false;
};

struct WeChatChatroom {
    std::string chatroomName;
    std::string owner;
    std::string memberList;  // comma-separated usernames
    int memberCount = 0;
    int64_t createTime = 0;
};

struct WeChatOwnerInfo {
    std::string username;
    std::string nickname;
    int uin = 0;
    std::string imei;
};

struct ApkSignatureInfo {
    std::string apkPath;
    bool hasSignature;
    std::string signerName; // Simplified for this example
    std::string certificateFingerprint;
};

struct SystemAppInfo {
    std::string packageName;
    std::string apkPath;
    std::string versionName;
    std::string versionCode;
    ApkSignatureInfo signatureInfo;
    bool isSystemApp;
    bool isPrivileged;
};

struct AndroidAppData {
    std::string packageName;
    std::string dbPath;
    std::string dataType; // e.g., "SMS", "Contacts", "CallLog"
    std::vector<std::map<std::string, std::string>> records;
};

struct SystemBuildProperty {
    std::string key;
    std::string value;
};

struct SystemAppRecord {
    std::string packageName;
    std::string apkPath;
    std::string versionName;
    std::string versionCode;
    bool isSystemApp;
    bool isPrivileged;
};

struct FrameworkFileRecord {
    std::string fileName;
    std::string filePath;
    std::string fileType; // jar, dex, so, etc.
    int64_t fileSize;
};

struct WifiNetwork {
    std::string ssid;
    std::string preSharedKey;
    std::string keyMgmt;
};

struct ChromeHistoryItem {
    std::string url;
    std::string title;
    int64_t visitCount;
    int64_t lastVisitTime;
};

struct InstalledPackageInfo {
    std::string packageName;
    std::string codePath;
    std::string nativeLibraryPath;
    int64_t firstInstallTime;
    int64_t lastUpdateTime;
    std::string version;
    std::string installer;
};

struct UsageStatRecord {
    std::string packageName;
    int64_t totalTimeInForeground;
    int64_t lastTimeUsed;
    int64_t firstTimeStamp;
};

// Build.prop analysis structures
struct BuildPropEntry {
    std::string key;
    std::string value;
    std::string category;
    std::string description;
    std::string securityImplication;
    bool isIdentified;
};

struct DeviceInfo {
    std::string manufacturer;
    std::string brand;
    std::string model;
    std::string device;
    std::string product;
    std::string fingerprint;
    std::string securityPatchLevel;
    std::string buildVersion;
    int sdkVersion;
    std::string buildDate;
};

struct SecurityConfig {
    bool adbEnabled;
    bool debugEnabled;
    bool mockLocationDisabled;
    bool secureEnabled;
    bool otaEncrypted;
    std::vector<std::string> securityFlags;
};

struct SystemConfig {
    std::string cpuArch;
    std::vector<std::string> cpuAbilist;
    int screenDensity;
    std::string locale;
    std::vector<std::string> supportedGps;
    bool blurSupported;
    std::string openglVersion;
};

struct ForensicAnalysis {
    std::string deviceIdentifier;
    std::string extractionDate;
    std::vector<std::string> securityConcerns;
    std::vector<std::string> unusualConfigurations;
    std::vector<std::string> carrierCustomizations;
    std::vector<std::string> vendorModifications;
    std::string riskAssessment;
};

struct BuildPropAnalysisResult {
    DeviceInfo deviceInfo;
    SecurityConfig securityConfig;
    SystemConfig systemConfig;
    ForensicAnalysis forensicAnalysis;
    std::vector<BuildPropEntry> allEntries;
    std::vector<BuildPropEntry> unrecognizedEntries;
    std::vector<BuildPropEntry> securityRelevantEntries;
};

struct SystemLogEntry {
    int64_t timestamp;
    std::string logLevel;
    std::string tag;
    std::string process;
    int pid;
    std::string message;
    std::string logFile;
    std::string logSource;
};
