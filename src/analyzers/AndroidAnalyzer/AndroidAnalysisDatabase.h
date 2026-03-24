// AndroidAnalysisDatabase.h
// Database class for Android analysis

#pragma once

#include "AndroidDataTypes.h"
#include <string>
#include <map>
#include <sqlite3.h>
#include "fileSystem.h"

class AndroidAnalysisDatabase {
public:
    explicit AndroidAnalysisDatabase(const std::string& dbPath);
    ~AndroidAnalysisDatabase();

    bool initialize();
    
    // System Data
    bool insertBuildProperty(const SystemBuildProperty& prop);
    bool insertSystemApp(const SystemAppRecord& app);
    bool insertFrameworkFile(const FrameworkFileRecord& file);
    
    // User Data
    bool insertSMS(const std::map<std::string, std::string>& record);
    bool insertContact(const std::map<std::string, std::string>& record);
    bool insertCallLog(const std::map<std::string, std::string>& record);
    bool insertWhatsAppMessage(const ChatMessage& msg);
    bool insertTelegramMessage(const ChatMessage& msg);
    bool insertWeChatMessage(const ChatMessage& msg);
    
    // New Artifacts
    bool insertWifiNetwork(const WifiNetwork& net);
    bool insertChromeHistory(const ChromeHistoryItem& item);
    bool insertInstalledPackage(const InstalledPackageInfo& pkg);
    bool insertUsageStat(const UsageStatRecord& stat);
    bool insertSystemLog(const SystemLogEntry& log);

private:
    std::string dbPath_;
    sqlite3* db_;

    bool createTables();
    bool executeSQL(const std::string& sql);
};
