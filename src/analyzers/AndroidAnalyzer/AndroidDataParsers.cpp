#include "AndroidAnalyzer.h"
#include "PathManager/PathManager.h"
#include "WeChatDecryptor.h"
#include "Logger/Logger.h"
#include <iostream>
#include <sqlite3.h>

// Android Data Parsers Implementation

std::string AndroidAnalyzer::makeAnalysisTempPath(const std::string& sourcePath,
                                                  const std::string& suffix) const {
    const std::string name = std::to_string(std::time(nullptr)) + "_" +
        std::filesystem::path(sourcePath).filename().string() + suffix;
    if (!secureTemporaryRoot_.empty()) {
        return (std::filesystem::path(secureTemporaryRoot_) / name).string();
    }
    return forensics::PathManager::instance().makeTempPath(name);
}

bool AndroidAnalyzer::stageSqliteBundle(const std::string& dbPathInImage,
                                        const std::string& primaryTempPath,
                                        std::vector<std::string>& stagedPaths) {
    stagedPaths.clear();
    if (!fileExtractor_->extractFileByPath(dbPathInImage, primaryTempPath)) {
        std::filesystem::remove(primaryTempPath);
        return false;
    }
    stagedPaths.push_back(primaryTempPath);
    for (const char* suffix : {"-wal", "-shm", "-journal"}) {
        const std::string sidecarSource = dbPathInImage + suffix;
        const std::string sidecarTemp = primaryTempPath + suffix;
        if (fileExtractor_->extractFileByPath(sidecarSource, sidecarTemp)) {
            stagedPaths.push_back(sidecarTemp);
        } else {
            std::filesystem::remove(sidecarTemp);
        }
    }
    return true;
}

bool AndroidAnalyzer::extractAndParseDB(const std::string& dbPathInImage, const std::string& parseFunction) {
    std::string tempPath = makeAnalysisTempPath(dbPathInImage);
    std::vector<std::string> stagedPaths;
    if (!stageSqliteBundle(dbPathInImage, tempPath, stagedPaths)) {
        std::cout << "Failed to extract database: " << dbPathInImage << std::endl;
        return false;
    }

    if (parseFunction == "parseSMS") {
        parseSMS(tempPath);
    } else if (parseFunction == "parseContacts") {
        parseContacts(tempPath);
    } else if (parseFunction == "parseCallLog") {
        parseCallLog(tempPath);
    } else if (parseFunction == "parseWhatsApp") {
        auto messages = parseWhatsApp(tempPath);
        for (const auto& msg : messages) {
            androidDb_->insertWhatsAppMessage(msg);
        }
    } else if (parseFunction == "parseTelegram") {
        auto messages = parseTelegram(tempPath);
        for (const auto& msg : messages) {
            androidDb_->insertTelegramMessage(msg);
        }
    } else if (parseFunction == "parseWeChat") {
        auto messages = parseWeChat(tempPath);
        for (const auto& msg : messages) {
            androidDb_->insertWeChatMessage(msg);
        }
    } else if (parseFunction == "parseChromeHistory") {
        parseChromeHistory(tempPath);
    }

    for (const std::string& path : stagedPaths) {
        std::filesystem::remove(path);
    }
    return true;
}

void AndroidAnalyzer::parseSMS(const std::string& dbPath) {
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open SMS DB: " << sqlite3_errmsg(db) << std::endl;
        return;
    }

    std::string sql = "SELECT address, body, date, type FROM sms;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        int count = 0;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            std::map<std::string, std::string> record;
            const char* address = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            record["address"] = address ? address : "";
            const char* body = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            record["body"] = body ? body : "";
            record["date"] = std::to_string(sqlite3_column_int64(stmt, 2));
            record["type"] = std::to_string(sqlite3_column_int(stmt, 3));
            androidDb_->insertSMS(record);
            count++;
        }
        if (count == 0) std::cout << "No SMS messages found in " << dbPath << std::endl;
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare SMS SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
}

void AndroidAnalyzer::parseContacts(const std::string& dbPath) {
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open Contacts DB: " << sqlite3_errmsg(db) << std::endl;
        return;
    }

    std::string sql = "SELECT display_name, data1 FROM view_contacts WHERE mimetype = 'vnd.android.cursor.item/phone_v2';";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        int count = 0;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            std::map<std::string, std::string> record;
            const char* display_name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            record["display_name"] = display_name ? display_name : "";
            const char* phone = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            record["phone"] = phone ? phone : "";
            androidDb_->insertContact(record);
            count++;
        }
        if (count == 0) std::cout << "No contacts found in " << dbPath << std::endl;
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare Contacts SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
}

void AndroidAnalyzer::parseCallLog(const std::string& dbPath) {
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open CallLog DB: " << sqlite3_errmsg(db) << std::endl;
        return;
    }

    std::string sql = "SELECT number, date, duration, type FROM calls;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        int count = 0;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            std::map<std::string, std::string> record;
            const char* number = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            record["number"] = number ? number : "";
            record["date"] = std::to_string(sqlite3_column_int64(stmt, 1));
            record["duration"] = std::to_string(sqlite3_column_int(stmt, 2));
            record["type"] = std::to_string(sqlite3_column_int(stmt, 3));
            androidDb_->insertCallLog(record);
            count++;
        }
        if (count == 0) std::cout << "No call logs found in " << dbPath << std::endl;
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare CallLog SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
}

std::vector<ChatMessage> AndroidAnalyzer::parseWhatsApp(const std::string& dbPath) {
    std::vector<ChatMessage> messages;
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open WhatsApp DB: " << sqlite3_errmsg(db) << std::endl;
        return messages;
    }

    std::string sql = "SELECT sender, receiver, content, timestamp FROM messages;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            ChatMessage msg;
            const char* sender = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            msg.sender = sender ? sender : "";
            const char* receiver = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            msg.receiver = receiver ? receiver : "";
            const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
            msg.content = content ? content : "";
            msg.timestamp = std::to_string(sqlite3_column_int64(stmt, 3));
            messages.push_back(msg);
        }
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare WhatsApp SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
    return messages;
}

std::vector<ChatMessage> AndroidAnalyzer::parseTelegram(const std::string& dbPath) {
    std::vector<ChatMessage> messages;
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open Telegram DB: " << sqlite3_errmsg(db) << std::endl;
        return messages;
    }

    std::string sql = "SELECT sender, receiver, content, date FROM messages;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            ChatMessage msg;
            const char* sender = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            msg.sender = sender ? sender : "";
            const char* receiver = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            msg.receiver = receiver ? receiver : "";
            const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
            msg.content = content ? content : "";
            msg.timestamp = std::to_string(sqlite3_column_int64(stmt, 3));
            messages.push_back(msg);
        }
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare Telegram SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
    return messages;
}

std::vector<ChatMessage> AndroidAnalyzer::parseWeChat(const std::string& dbPath) {
    std::vector<ChatMessage> messages;
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open WeChat DB: " << sqlite3_errmsg(db) << std::endl;
        return messages;
    }

    std::string sql = "SELECT talker, content, createTime FROM message;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            ChatMessage msg;
            const char* talker = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            msg.sender = talker ? talker : "";
            msg.receiver = "Unknown"; // WeChat doesn't store receiver in this table
            const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            msg.content = content ? content : "";
            msg.timestamp = std::to_string(sqlite3_column_int64(stmt, 2));
            messages.push_back(msg);
        }
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare WeChat SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
    return messages;
}

std::vector<WeChatContact> AndroidAnalyzer::parseWeChatContacts(sqlite3* db) {
    std::vector<WeChatContact> contacts;
    const char* sql = "SELECT username, nickname, conRemark, type, chatroomFlag FROM rcontact WHERE username NOT LIKE '%@chatroom%' AND username != 'weixin' AND username != 'filehelper';";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            WeChatContact contact;
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            const char* remark = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

            contact.username = username ? username : "";
            contact.nickname = nickname ? nickname : "";
            contact.remark = remark ? remark : "";
            contact.type = sqlite3_column_int(stmt, 3);
            contact.isChatroom = false;

            if (!contact.username.empty()) {
                contacts.push_back(contact);
            }
        }
        sqlite3_finalize(stmt);
    }
    return contacts;
}

std::vector<WeChatChatroom> AndroidAnalyzer::parseWeChatChatrooms(sqlite3* db) {
    std::vector<WeChatChatroom> chatrooms;
    const char* sql = "SELECT chatroomname, roomowner, memberlist, membercount, addtime FROM chatroom;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            WeChatChatroom room;
            const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* owner = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            const char* members = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

            room.chatroomName = name ? name : "";
            room.owner = owner ? owner : "";
            room.memberList = members ? members : "";
            room.memberCount = sqlite3_column_int(stmt, 3);
            room.createTime = sqlite3_column_int64(stmt, 4);

            if (!room.chatroomName.empty()) {
                chatrooms.push_back(room);
            }
        }
        sqlite3_finalize(stmt);
    }
    return chatrooms;
}

WeChatOwnerInfo AndroidAnalyzer::identifyWeChatOwner(sqlite3* db) {
    WeChatOwnerInfo owner;
    // Try userinfo table first
    const char* sql = "SELECT value FROM userinfo WHERE id = 2;";  // id=2 is typically username
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (username) owner.username = username;
        }
        sqlite3_finalize(stmt);
    }

    // Get nickname
    sql = "SELECT value FROM userinfo WHERE id = 4;";  // id=4 is typically nickname
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (nickname) owner.nickname = nickname;
        }
        sqlite3_finalize(stmt);
    }

    return owner;
}

void AndroidAnalyzer::parseWeChatEnhanced(const std::string& dbPath, const std::string& password) {
    WeChatDecryptor decryptor;
    if (!decryptor.openDatabase(dbPath, password)) {
        LOG_WARNING("Failed to decrypt WeChat database: " + decryptor.getLastError());
        return;
    }

    sqlite3* db = decryptor.getDb();

    // 1. Identify device owner
    WeChatOwnerInfo owner = identifyWeChatOwner(db);
    androidDb_->insertWeChatOwnerInfo(owner);

    // 2. Parse contacts
    auto contacts = parseWeChatContacts(db);
    for (const auto& contact : contacts) {
        androidDb_->insertWeChatContact(contact);
    }

    // 3. Parse chatrooms
    auto chatrooms = parseWeChatChatrooms(db);
    for (const auto& room : chatrooms) {
        androidDb_->insertWeChatChatroom(room);
    }

    // 4. Parse messages with enhanced fields
    const char* msgSql = "SELECT talker, content, createTime, type, isSend FROM message WHERE type IN (1, 3, 34, 43, 47, 49) ORDER BY createTime;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, msgSql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            ChatMessage msg;
            const char* talker = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));

            msg.content = content ? content : "";
            msg.timestamp = std::to_string(sqlite3_column_int64(stmt, 2));
            int msgType = sqlite3_column_int(stmt, 3);
            int isSend = sqlite3_column_int(stmt, 4);

            std::string talkerStr = talker ? talker : "";
            std::string chatroomName;
            std::string sender;
            std::string receiver;
            std::string senderNickname;

            if (talkerStr.find("@chatroom") != std::string::npos) {
                // Group chat
                chatroomName = talkerStr;
                // Extract sender from content XML header (format: "wxid_xxx:\n<message>")
                size_t colonPos = msg.content.find(":\n");
                if (colonPos != std::string::npos) {
                    sender = msg.content.substr(0, colonPos);
                    msg.content = msg.content.substr(colonPos + 2);
                }
                receiver = chatroomName;
            } else {
                // Private chat
                if (isSend == 1) {
                    sender = owner.username;
                    receiver = talkerStr;
                } else {
                    sender = talkerStr;
                    receiver = owner.username;
                }
            }

            // Look up nickname for sender
            for (const auto& c : contacts) {
                if (c.username == sender) {
                    senderNickname = c.remark.empty() ? c.nickname : c.remark;
                    break;
                }
            }

            msg.sender = sender;
            msg.receiver = receiver;

            androidDb_->insertWeChatEnhancedMessage(msg, msgType, isSend, chatroomName, senderNickname, talkerStr);
        }
        sqlite3_finalize(stmt);
    }

    decryptor.close();
    LOG_INFO("WeChat enhanced parsing completed: " + std::to_string(contacts.size()) + " contacts, " +
             std::to_string(chatrooms.size()) + " chatrooms");
}

void AndroidAnalyzer::parseChromeHistory(const std::string& dbPath) {
    sqlite3* db;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        std::cerr << "Failed to open Chrome DB: " << sqlite3_errmsg(db) << std::endl;
        return;
    }

    std::string sql = "SELECT url, title, visit_count, last_visit_time FROM urls;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        int count = 0;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            ChromeHistoryItem item;
            const char* url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            item.url = url ? url : "";
            const char* title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            item.title = title ? title : "";
            item.visitCount = sqlite3_column_int64(stmt, 2);
            item.lastVisitTime = sqlite3_column_int64(stmt, 3);
            androidDb_->insertChromeHistory(item);
            count++;
        }
        if (count == 0) std::cout << "No Chrome history items found in " << dbPath << std::endl;
        sqlite3_finalize(stmt);
    } else {
        std::cerr << "Failed to prepare Chrome SQL: " << sqlite3_errmsg(db) << std::endl;
    }
    sqlite3_close(db);
}
