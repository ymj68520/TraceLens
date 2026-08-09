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

    // QQNT MIUI-backup artifacts
    bool insertQqntArtifactInventory(const std::string& packageName, const std::string& sourcePath,
                                     const std::string& bakFile, const std::string& category,
                                     const std::string& format, uint64_t size, uint64_t modifiedTime,
                                     const std::string& typeFlag, const std::string& parseStatus,
                                     const std::string& summary, const std::string& sourceHash);
    bool insertQqntKvRecord(const std::string& sourcePath, const std::string& nameSpace,
                            const std::string& key, const std::string& valueType,
                            const std::string& valueText, const std::string& valueHash,
                            bool isSensitive, const std::string& parseStatus);
    bool insertQqntSqliteRecord(const std::string& sourcePath, const std::string& tableName,
                                const std::string& recordKey, const std::string& recordJson,
                                const std::string& artifactKind, bool isSensitive);
    bool insertQqntLogEvent(const std::string& sourcePath, uint64_t eventTime,
                            const std::string& level, const std::string& tag,
                            const std::string& message, const std::string& parseStatus,
                            bool isSensitive);
    // WeChat (com.tencent.mm) MIUI-backup artifacts — same shape as the QQNT
    // inventory, persisted into dedicated wechat_* tables.
    bool insertWechatArtifactInventory(const std::string& packageName, const std::string& sourcePath,
                                       const std::string& bakFile, const std::string& category,
                                       const std::string& format, uint64_t size, uint64_t modifiedTime,
                                       const std::string& typeFlag, const std::string& parseStatus,
                                       const std::string& summary, const std::string& sourceHash);
    bool insertWechatKvRecord(const std::string& sourcePath, const std::string& nameSpace,
                              const std::string& key, const std::string& valueType,
                              const std::string& valueText, const std::string& valueHash,
                              bool isSensitive, const std::string& parseStatus);
    bool insertWechatSqliteRecord(const std::string& sourcePath, const std::string& tableName,
                                  const std::string& recordKey, const std::string& recordJson,
                                  const std::string& artifactKind, bool isSensitive);
    bool insertWechatLogEvent(const std::string& sourcePath, uint64_t eventTime,
                              const std::string& level, const std::string& tag,
                              const std::string& message, const std::string& parseStatus,
                              bool isSensitive);
    bool beginTransaction();
    bool commitTransaction();
    bool rollbackTransaction();

private:
    std::string dbPath_;
    sqlite3* db_;
    bool integratedMode_;

    bool createTables();
    bool createArtifactsTable();
    bool executeSQL(const std::string& sql);
    // Idempotently add the llm_* analysis columns to a table. Safe to call on
    // tables/columns that already exist (duplicate-column errors are ignored).
    bool addLlmColumns(const std::string& tableName);
};
