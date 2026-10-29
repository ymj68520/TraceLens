#include "AndroidAnalysisDatabase.h"
#include "DatabaseManager/SQL/android_analysis_sql.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include "IFileExtractor.h"
#include <iostream>
#include <set>
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
    if (!executeSQL(AndroidAnalysisSQL::CREATE_ALL_TABLES) ||
        !executeSQL(AndroidAnalysisSQL::CREATE_MIUI_TABLES) ||
        !executeSQL(AndroidAnalysisSQL::CREATE_ANALYSIS_PROGRESS) ||
        !executeSQL(AndroidAnalysisSQL::CREATE_SOURCE_COVERAGE) ||
        !executeSQL(AndroidAnalysisSQL::CREATE_CONTAINER_PROVENANCE) ||
        !executeSQL(AndroidAnalysisSQL::CREATE_FILESYSTEM_PROVENANCE)) {
        return false;
    }
    // Existing task databases predate the source-path column. The duplicate
    // column error is harmless; all other errors are surfaced.
    bool hasSourcePath = false;
    sqlite3_stmt* columns = nullptr;
    if (sqlite3_prepare_v2(db_, "PRAGMA table_info(wechat_messages)", -1, &columns, nullptr) == SQLITE_OK) {
        while (sqlite3_step(columns) == SQLITE_ROW) {
            const char* name = reinterpret_cast<const char*>(sqlite3_column_text(columns, 1));
            if (name && std::string(name) == "source_path") hasSourcePath = true;
        }
    }
    sqlite3_finalize(columns);
    if (!hasSourcePath && !executeSQL("ALTER TABLE wechat_messages ADD COLUMN source_path TEXT"))
        return false;
    // Add the 5 llm_* columns to every artifact table that the LLM service
    // analyzes. Each ALTER is idempotent: a duplicate-column error is tolerated
    // so re-opening an existing android.db is safe.
    static const char* kLlmTables[] = {
        "sms_messages", "wechat_messages", "whatsapp_messages", "telegram_messages",
        "contacts", "call_logs",
        "miui_backup_manifest", "installed_apps",
        "wechat_sqlite_records", "wechat_kv_records", "qqnt_sqlite_records",
        "system_logs", "device_identifiers", "wifi_networks"
    };
    for (const char* tbl : kLlmTables) {
        if (!addLlmColumns(tbl)) {
            // Non-fatal: a malformed/incompatible table should not abort init.
            std::cerr << "Warning: failed to add llm_* columns to " << tbl << std::endl;
        }
    }
    return true;
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
    const std::string& talker, const std::string& sourcePath) {
    const char* sql = "INSERT INTO wechat_messages (sender, receiver, content, timestamp, msg_type, is_send, chatroom_name, sender_nickname, talker, source_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
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
    sqlite3_bind_text(stmt, 10, sourcePath.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::recordSourceCoverage(
    const std::string& artifactKind, const std::string& sourcePath,
    const std::string& status, const std::string& detail) {
    // SQLCipher builds used by the runtime may embed SQLite without UPSERT.
    // REPLACE is portable and preserves the table's uniqueness contract.
    const char* sql = "INSERT OR REPLACE INTO android_source_coverage "
                      "(artifact_kind, source_path, status, detail, updated_at) "
                      "VALUES (?, ?, ?, ?, strftime('%s','now'))";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Android source coverage prepare failed: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }
    sqlite3_bind_text(stmt, 1, artifactKind.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, status.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, detail.c_str(), -1, SQLITE_TRANSIENT);
    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) std::cerr << "Android source coverage write failed: " << sqlite3_errmsg(db_) << std::endl;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::insertSourceProvenance(const AndroidSourceProvenance& item) {
    const char* sql = "INSERT OR REPLACE INTO android_source_provenance "
        "(source_container,source_container_sha256,source_member_path,normalized_android_path,"
        "member_size,member_sha256,adapter_type,adapter_version) VALUES (?,?,?,?,?,?,?,?)";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, item.sourceContainer.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, item.containerSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, item.sourceMemberPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, item.normalizedAndroidPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, static_cast<sqlite3_int64>(item.memberSize));
    sqlite3_bind_text(stmt, 6, item.memberSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, item.adapterType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, item.adapterVersion.c_str(), -1, SQLITE_TRANSIENT);
    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    if (!success || item.filesystemType.empty()) return success;
    const char* imageSql = "INSERT OR REPLACE INTO android_filesystem_provenance "
        "(source_evidence_id,source_image_sha256,container_type,partition_number,partition_name,"
        "partition_start_offset,filesystem_type,filesystem_object_id,filesystem_path,"
        "normalized_android_path,file_size,file_sha256,reader,reader_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)";
    if (sqlite3_prepare_v2(db_, imageSql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, item.containerSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, item.containerSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, item.imageContainerType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 4, item.partitionNumber);
    sqlite3_bind_text(stmt, 5, item.partitionName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6, item.partitionStartOffset);
    sqlite3_bind_text(stmt, 7, item.filesystemType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, item.filesystemObjectId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, item.sourceMemberPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, item.normalizedAndroidPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 11, item.memberSize);
    sqlite3_bind_text(stmt, 12, item.memberSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 13, item.filesystemReader.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 14, item.adapterVersion.c_str(), -1, SQLITE_TRANSIENT);
    const bool imageSuccess = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return imageSuccess;
}

bool AndroidAnalysisDatabase::insertFilesystemMetrics(
    const std::string& source, const std::string& filesystem, const std::string& reader,
    std::uint64_t walkMs, std::uint64_t indexed, std::uint64_t extracted,
    std::uint64_t bytesRead, std::uint64_t analysisMs) {
    const char* sql = "INSERT OR REPLACE INTO android_filesystem_metrics "
        "(source_image,filesystem_type,reader,walk_milliseconds,indexed_file_count,"
        "extracted_member_count,bytes_read,analysis_milliseconds) VALUES (?,?,?,?,?,?,?,?)";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, source.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, filesystem.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, reader.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, walkMs);
    sqlite3_bind_int64(stmt, 5, indexed);
    sqlite3_bind_int64(stmt, 6, extracted);
    sqlite3_bind_int64(stmt, 7, bytesRead);
    sqlite3_bind_int64(stmt, 8, analysisMs);
    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool AndroidAnalysisDatabase::recordContainerCoverage(
    const std::string& sourcePath, const std::string& normalizedPath,
    const std::string& adapter, const std::string& status, const std::string& reason) {
    const char* sql = "INSERT OR REPLACE INTO android_container_coverage "
        "(source_path,normalized_path,adapter,status,reason) VALUES (?,?,?,?,?)";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;
    sqlite3_bind_text(stmt, 1, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, normalizedPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, adapter.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, status.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, reason.c_str(), -1, SQLITE_TRANSIENT);
    const bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

int AndroidAnalysisDatabase::artifactRowCount(const std::string& tableName) const {
    static const std::set<std::string> allowed{
        "sms_messages", "contacts", "installed_packages", "wifi_networks"};
    if (!allowed.count(tableName)) return -1;
    const std::string sql = "SELECT COUNT(*) FROM " + tableName;
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return -1;
    const int count = sqlite3_step(stmt) == SQLITE_ROW ? sqlite3_column_int(stmt, 0) : -1;
    sqlite3_finalize(stmt);
    return count;
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
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Installed package prepare failed: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    sqlite3_bind_text(stmt, 1, pkg.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, pkg.codePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, pkg.version.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, pkg.installer.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    if (!success) std::cerr << "Installed package write failed: " << sqlite3_errmsg(db_) << std::endl;
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

bool AndroidAnalysisDatabase::insertMiuiExternalFile(const std::string& relativePath,
                                                     const std::string& fileName,
                                                     const std::string& extension,
                                                     const std::string& category,
                                                     uint64_t size,
                                                     uint64_t modifiedTime) {
    const char* sql = "INSERT OR REPLACE INTO miui_external_files (relative_path, file_name, extension, category, size, modified_time) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, relativePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, fileName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, extension.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, category.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, static_cast<sqlite3_int64>(size));
    sqlite3_bind_int64(stmt, 6, static_cast<sqlite3_int64>(modifiedTime));

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

bool AndroidAnalysisDatabase::insertWechatArtifactInventory(
    const std::string& packageName, const std::string& sourcePath, const std::string& bakFile,
    const std::string& category, const std::string& format, uint64_t size,
    uint64_t modifiedTime, const std::string& typeFlag, const std::string& parseStatus,
    const std::string& summary, const std::string& sourceHash) {
    const char* sql = R"(
        INSERT OR REPLACE INTO wechat_artifact_inventory
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

bool AndroidAnalysisDatabase::insertWechatKvRecord(
    const std::string& sourcePath, const std::string& nameSpace, const std::string& key,
    const std::string& valueType, const std::string& valueText, const std::string& valueHash,
    bool isSensitive, const std::string& parseStatus) {
    const char* sql = R"(
        INSERT INTO wechat_kv_records
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

bool AndroidAnalysisDatabase::insertWechatSqliteRecord(
    const std::string& sourcePath, const std::string& tableName, const std::string& recordKey,
    const std::string& recordJson, const std::string& artifactKind, bool isSensitive) {
    const char* sql = R"(
        INSERT INTO wechat_sqlite_records
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

bool AndroidAnalysisDatabase::insertWechatLogEvent(
    const std::string& sourcePath, uint64_t eventTime, const std::string& level,
    const std::string& tag, const std::string& message, const std::string& parseStatus,
    bool isSensitive) {
    const char* sql = R"(
        INSERT INTO wechat_log_events
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

bool AndroidAnalysisDatabase::addLlmColumns(const std::string& tableName) {
    // The 5 llm_* columns mirror the Linux/Windows artifact-table convention.
    // ALTER TABLE ... ADD COLUMN cannot add multiple columns in one statement,
    // so we issue one statement per column. A "duplicate column" error means
    // the column already exists (re-opened db) and is treated as success.
    static const char* kColumnDefs[] = {
        "llm_summary TEXT",
        "llm_description TEXT",
        "llm_keywords TEXT",
        "llm_analyzed_at INTEGER",
        "llm_model_used TEXT"
    };
    for (const char* colDef : kColumnDefs) {
        std::string sql = "ALTER TABLE " + tableName + " ADD COLUMN " + colDef + ";";
        char* errMsg = nullptr;
        int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg);
        if (rc != SQLITE_OK) {
            // "duplicate column name" → already migrated; anything else → real error.
            const std::string err = errMsg ? errMsg : "";
            sqlite3_free(errMsg);
            if (err.find("duplicate column name") == std::string::npos) {
                return false;
            }
        }
    }
    return true;
}
