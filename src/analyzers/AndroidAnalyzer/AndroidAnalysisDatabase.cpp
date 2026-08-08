#include "AndroidAnalysisDatabase.h"
#include "DatabaseManager/SQL/android_analysis_sql.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include <iostream>
#include <sqlite3.h>
#include "fileSystem.h"

// AndroidAnalysisDatabase Implementation
AndroidAnalysisDatabase::AndroidAnalysisDatabase(const std::string& dbPath, bool integratedMode)
    : dbPath_(dbPath), db_(nullptr), integratedMode_(integratedMode) {
}

AndroidAnalysisDatabase::~AndroidAnalysisDatabase() {
    if (db_) {
        sqlite3_close(db_);
    }
}

bool AndroidAnalysisDatabase::initialize() {
    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open android analysis database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    if (integratedMode_) {
        return createArtifactsTable();
    }
    return createTables();
}

bool AndroidAnalysisDatabase::createTables() {
    return executeSQL(AndroidAnalysisSQL::CREATE_ALL_TABLES) &&
           executeSQL(AndroidAnalysisSQL::CREATE_MIUI_TABLES);
}

bool AndroidAnalysisDatabase::createArtifactsTable() {
    std::string sql = FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE;
    std::string tableName = "android_artifacts";
    size_t pos = 0;
    while ((pos = sql.find("%TABLE_NAME%", pos)) != std::string::npos) {
        sql.replace(pos, 12, tableName);  // 12 = length of "%TABLE_NAME%"
        pos += tableName.length();
    }
    return executeSQL(sql);
}

bool AndroidAnalysisDatabase::insertBuildProperty(const SystemBuildProperty& prop) {
    const char* sql = "INSERT OR REPLACE INTO system_build_properties (property_key, property_value) VALUES (?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, prop.key.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, prop.value.c_str(), -1, SQLITE_TRANSIENT);
    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertSystemApp(const SystemAppRecord& app) {
    const char* sql = "INSERT OR IGNORE INTO system_apps (package_name, apk_path, version_name, version_code, is_system_app, is_privileged) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, app.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, app.apkPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, app.versionName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, app.versionCode.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, app.isSystemApp);
    sqlite3_bind_int(stmt, 6, app.isPrivileged);
    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertFrameworkFile(const FrameworkFileRecord& file) {
    const char* sql = "INSERT OR IGNORE INTO framework_files (file_name, file_path, file_type, file_size) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, file.fileName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, file.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, file.fileType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, file.fileSize);
    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertSMS(const std::map<std::string, std::string>& record) {
    const char* sql = "INSERT INTO sms_messages (address, body, date, type) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    auto get = [&](const std::string& k) { auto it = record.find(k); return it != record.end() ? it->second.c_str() : ""; };

    sqlite3_bind_text(stmt, 1, get("address"), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, get("body"), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 3, std::stoll(get("date"))); } catch (...) { sqlite3_bind_int64(stmt, 3, 0); }
    try { sqlite3_bind_int(stmt, 4, std::stoi(get("type"))); } catch (...) { sqlite3_bind_int(stmt, 4, 0); }

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertContact(const std::map<std::string, std::string>& record) {
    const char* sql = "INSERT INTO contacts (display_name, phone_number) VALUES (?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    auto get = [&](const std::string& k) { auto it = record.find(k); return it != record.end() ? it->second.c_str() : ""; };
    sqlite3_bind_text(stmt, 1, get("display_name"), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, get("phone"), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertCallLog(const std::map<std::string, std::string>& record) {
    const char* sql = "INSERT INTO call_logs (number, date, duration, type) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    auto get = [&](const std::string& k) { auto it = record.find(k); return it != record.end() ? it->second.c_str() : ""; };
    sqlite3_bind_text(stmt, 1, get("number"), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 2, std::stoll(get("date"))); } catch (...) { sqlite3_bind_int64(stmt, 2, 0); }
    try { sqlite3_bind_int(stmt, 3, std::stoi(get("duration"))); } catch (...) { sqlite3_bind_int(stmt, 3, 0); }
    try { sqlite3_bind_int(stmt, 4, std::stoi(get("type"))); } catch (...) { sqlite3_bind_int(stmt, 4, 0); }

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWhatsAppMessage(const ChatMessage& msg) {
    const char* sql = "INSERT INTO whatsapp_messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, msg.sender.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, msg.receiver.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, msg.content.c_str(), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 4, std::stoll(msg.timestamp)); } catch (...) { sqlite3_bind_int64(stmt, 4, 0); }

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertTelegramMessage(const ChatMessage& msg) {
    const char* sql = "INSERT INTO telegram_messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, msg.sender.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, msg.receiver.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, msg.content.c_str(), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 4, std::stoll(msg.timestamp)); } catch (...) { sqlite3_bind_int64(stmt, 4, 0); }

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWeChatMessage(const ChatMessage& msg) {
    const char* sql = "INSERT INTO wechat_messages (sender, receiver, content, timestamp) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, msg.sender.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, msg.receiver.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, msg.content.c_str(), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 4, std::stoll(msg.timestamp)); } catch (...) { sqlite3_bind_int64(stmt, 4, 0); }

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWeChatEnhancedMessage(
    const ChatMessage& msg, int msgType, int isSend,
    const std::string& chatroomName, const std::string& senderNickname,
    const std::string& talker) {
    const char* sql = "INSERT INTO wechat_messages (sender, receiver, content, timestamp, msg_type, is_send, chatroom_name, sender_nickname, talker) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, msg.sender.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, msg.receiver.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, msg.content.c_str(), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 4, std::stoll(msg.timestamp)); } catch (...) { sqlite3_bind_int64(stmt, 4, 0); }
    sqlite3_bind_int(stmt, 5, msgType);
    sqlite3_bind_int(stmt, 6, isSend);
    sqlite3_bind_text(stmt, 7, chatroomName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, senderNickname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, talker.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWeChatContact(const WeChatContact& contact) {
    const char* sql = "INSERT OR IGNORE INTO wechat_contacts (username, nickname, remark, avatar_path, type, chatroom_flag) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, contact.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, contact.nickname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, contact.remark.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, contact.avatarPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, contact.type);
    sqlite3_bind_int(stmt, 6, contact.isChatroom ? 1 : 0);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWeChatChatroom(const WeChatChatroom& chatroom) {
    const char* sql = "INSERT OR IGNORE INTO wechat_chatrooms (chatroom_name, owner, member_list, member_count, create_time) VALUES (?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, chatroom.chatroomName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, chatroom.owner.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, chatroom.memberList.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 4, chatroom.memberCount);
    sqlite3_bind_int64(stmt, 5, chatroom.createTime);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWeChatOwnerInfo(const WeChatOwnerInfo& owner) {
    const char* sql = "INSERT OR REPLACE INTO wechat_owner_info (username, nickname, uin, imei) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, owner.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, owner.nickname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 3, owner.uin);
    sqlite3_bind_text(stmt, 4, owner.imei.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertWifiNetwork(const WifiNetwork& net) {
    const char* sql = "INSERT INTO wifi_networks (ssid, pre_shared_key, key_mgmt) VALUES (?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, net.ssid.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, net.preSharedKey.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, net.keyMgmt.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertChromeHistory(const ChromeHistoryItem& item) {
    const char* sql = "INSERT INTO chrome_history (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, item.url.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, item.title.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, item.visitCount);
    sqlite3_bind_int64(stmt, 4, item.lastVisitTime);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertInstalledPackage(const InstalledPackageInfo& pkg) {
    const char* sql = "INSERT OR REPLACE INTO installed_packages (package_name, code_path, version, installer) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, pkg.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, pkg.codePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, pkg.version.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, pkg.installer.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertUsageStat(const UsageStatRecord& stat) {
    const char* sql = "INSERT INTO usage_stats (package_name, total_time_foreground, last_time_used, interval_start) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, stat.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, stat.totalTimeInForeground);
    sqlite3_bind_int64(stmt, 3, stat.lastTimeUsed);
    sqlite3_bind_int64(stmt, 4, stat.firstTimeStamp);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertSystemLog(const SystemLogEntry& log) {
    const char* sql = "INSERT INTO system_logs (timestamp, log_level, tag, process, pid, message, log_file, log_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_int64(stmt, 1, log.timestamp);
    sqlite3_bind_text(stmt, 2, log.logLevel.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, log.tag.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, log.process.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, log.pid);
    sqlite3_bind_text(stmt, 6, log.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, log.logFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, log.logSource.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertDeviceIdentifier(const std::string& type, const std::string& value,
                                                     const std::string& packageName, const std::string& sourcePath) {
    const char* sql = "INSERT INTO device_identifiers (identifier_type, value, package_name, source_path) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, type.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, value.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, sourcePath.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertAppNote(const std::string& packageName, const std::string& noteId,
                                            const std::string& title, const std::string& content,
                                            const std::string& tags, bool isPrivate, const std::string& sourceDb) {
    const char* sql = "INSERT INTO app_notes (package_name, note_id, title, content, tags, is_private, source_db) VALUES (?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, noteId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, title.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, content.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, tags.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, isPrivate ? 1 : 0);
    sqlite3_bind_text(stmt, 7, sourceDb.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertEncryptedDb(const std::string& packageName, const std::string& dbPath,
                                                const std::string& keyHintType, const std::string& keyHintValue,
                                                const std::string& keySourcePath, const std::string& openStatus) {
    const char* sql = "INSERT INTO encrypted_db_inventory (package_name, db_path, key_hint_type, key_hint_value, key_source_path, open_status) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, dbPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, keyHintType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, keyHintValue.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, keySourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, openStatus.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertMiuiBackupManifest(const std::string& device,
                                                       const std::string& miuiVersion,
                                                       uint64_t date, uint64_t totalSize,
                                                       int packageCount,
                                                       const std::string& sourceFolder) {
    const char* sql = "INSERT INTO miui_backup_manifest (device, miui_version, backup_date, total_size, package_count, source_folder) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, device.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, miuiVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, static_cast<sqlite3_int64>(date));
    sqlite3_bind_int64(stmt, 4, static_cast<sqlite3_int64>(totalSize));
    sqlite3_bind_int(stmt, 5, packageCount);
    sqlite3_bind_text(stmt, 6, sourceFolder.c_str(), -1, SQLITE_TRANSIENT);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertInstalledApp(const std::string& packageName,
                                                 const std::string& displayName,
                                                 const std::string& versionCode,
                                                 const std::string& versionName,
                                                 uint64_t dataSize, uint64_t sdSize,
                                                 int bakType,
                                                 const std::string& manifestSummary) {
    const char* sql = "INSERT INTO installed_apps (package_name, display_name, version_code, version_name, data_size, sd_size, bak_type, manifest_summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, displayName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, versionCode.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, versionName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, static_cast<sqlite3_int64>(dataSize));
    sqlite3_bind_int64(stmt, 6, static_cast<sqlite3_int64>(sdSize));
    sqlite3_bind_int(stmt, 7, bakType);
    sqlite3_bind_text(stmt, 8, manifestSummary.c_str(), -1, SQLITE_TRANSIENT);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertAppDbInventory(const std::string& packageName,
                                                   const std::string& dbPath,
                                                   const std::string& tableName,
                                                   uint64_t rowCount,
                                                   const std::string& columns,
                                                   const std::string& openStatus) {
    const char* sql = "INSERT INTO app_db_inventory (package_name, db_path, table_name, row_count, columns, open_status) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, dbPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, tableName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, static_cast<sqlite3_int64>(rowCount));
    sqlite3_bind_text(stmt, 5, columns.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, openStatus.c_str(), -1, SQLITE_TRANSIENT);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertQqntArtifactInventory(
    const std::string& packageName, const std::string& sourcePath, const std::string& bakFile,
    const std::string& category, const std::string& format, uint64_t size,
    uint64_t modifiedTime, const std::string& typeFlag, const std::string& parseStatus,
    const std::string& summary, const std::string& sourceHash) {
    const char* sql = R"(
        INSERT OR REPLACE INTO qqnt_artifact_inventory
        (package_name, source_path, bak_file, artifact_category, format, size, modified_time,
         type_flag, parse_status, summary, source_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    )";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, bakFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, category.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, format.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6, static_cast<sqlite3_int64>(size));
    sqlite3_bind_int64(stmt, 7, static_cast<sqlite3_int64>(modifiedTime));
    sqlite3_bind_text(stmt, 8, typeFlag.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, parseStatus.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, summary.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, sourceHash.c_str(), -1, SQLITE_TRANSIENT);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertQqntKvRecord(
    const std::string& sourcePath, const std::string& nameSpace, const std::string& key,
    const std::string& valueType, const std::string& valueText, const std::string& valueHash,
    bool isSensitive, const std::string& parseStatus) {
    const char* sql = R"(
        INSERT INTO qqnt_kv_records
        (source_path, namespace, key, value_type, value_text, value_hash, is_sensitive, parse_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    )";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, nameSpace.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, key.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, valueType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, valueText.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, valueHash.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 7, isSensitive ? 1 : 0);
    sqlite3_bind_text(stmt, 8, parseStatus.c_str(), -1, SQLITE_TRANSIENT);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertQqntSqliteRecord(
    const std::string& sourcePath, const std::string& tableName, const std::string& recordKey,
    const std::string& recordJson, const std::string& artifactKind, bool isSensitive) {
    const char* sql = R"(
        INSERT INTO qqnt_sqlite_records
        (source_path, table_name, record_key, record_json, artifact_kind, is_sensitive)
        VALUES (?, ?, ?, ?, ?, ?);
    )";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, tableName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, recordKey.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, recordJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, artifactKind.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, isSensitive ? 1 : 0);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertQqntLogEvent(
    const std::string& sourcePath, uint64_t eventTime, const std::string& level,
    const std::string& tag, const std::string& message, const std::string& parseStatus,
    bool isSensitive) {
    const char* sql = R"(
        INSERT INTO qqnt_log_events
        (source_path, event_time, level, tag, message, parse_status, is_sensitive)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    )";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, static_cast<sqlite3_int64>(eventTime));
    sqlite3_bind_text(stmt, 3, level.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, tag.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, parseStatus.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 7, isSensitive ? 1 : 0);

    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::beginTransaction() {
    return executeSQL("BEGIN IMMEDIATE;");
}

bool AndroidAnalysisDatabase::commitTransaction() {
    return executeSQL("COMMIT;");
}

bool AndroidAnalysisDatabase::rollbackTransaction() {
    return executeSQL("ROLLBACK;");
}

bool AndroidAnalysisDatabase::executeSQL(const std::string& sql) {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg);

    if (rc != SQLITE_OK) {
        std::cerr << "SQL error: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }

    return true;
}
