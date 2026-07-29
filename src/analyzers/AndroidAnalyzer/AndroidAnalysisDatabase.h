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
    explicit AndroidAnalysisDatabase(const std::string& dbPath, bool integratedMode = false);
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
    bool insertWeChatEnhancedMessage(const ChatMessage& msg, int msgType, int isSend,
                                      const std::string& chatroomName, const std::string& senderNickname,
                                      const std::string& talker);
    bool insertWeChatContact(const WeChatContact& contact);
    bool insertWeChatChatroom(const WeChatChatroom& chatroom);
    bool insertWeChatOwnerInfo(const WeChatOwnerInfo& owner);

    // New Artifacts
    bool insertWifiNetwork(const WifiNetwork& net);
    bool insertChromeHistory(const ChromeHistoryItem& item);
    bool insertInstalledPackage(const InstalledPackageInfo& pkg);
    bool insertUsageStat(const UsageStatRecord& stat);
    bool insertSystemLog(const SystemLogEntry& log);

    // Logical-extraction artifacts (Phase 2)
    // Android SSAID / per-app Android ID (settings_ssaid.xml)
    bool insertDeviceIdentifier(const std::string& type, const std::string& value,
                                const std::string& packageName, const std::string& sourcePath);
    // Notes recovered from plaintext note-taking app databases (generic)
    bool insertAppNote(const std::string& packageName, const std::string& noteId,
                       const std::string& title, const std::string& content,
                       const std::string& tags, bool isPrivate, const std::string& sourceDb);
    // Inventory of an encrypted app DB with its discovered key hint
    bool insertEncryptedDb(const std::string& packageName, const std::string& dbPath,
                           const std::string& keyHintType, const std::string& keyHintValue,
                           const std::string& keySourcePath, const std::string& openStatus);

    // MIUI offline-backup forensic metadata
    bool insertMiuiBackupManifest(const std::string& device, const std::string& miuiVersion,
                                  uint64_t date, uint64_t totalSize, int packageCount,
                                  const std::string& sourceFolder);
    bool insertInstalledApp(const std::string& packageName, const std::string& displayName,
                            const std::string& versionCode, const std::string& versionName,
                            uint64_t dataSize, uint64_t sdSize, int bakType,
                            const std::string& manifestSummary);
    bool insertAppDbInventory(const std::string& packageName, const std::string& dbPath,
                              const std::string& tableName, uint64_t rowCount,
                              const std::string& columns, const std::string& openStatus);

private:
    std::string dbPath_;
    sqlite3* db_;
    bool integratedMode_;

    bool createTables();
    bool createArtifactsTable();
    bool executeSQL(const std::string& sql);
};
