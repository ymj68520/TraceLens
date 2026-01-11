#include "AndroidAnalyzer.h"
#include <iostream>
#include <sqlite3.h>

// Android Data Parsers Implementation

bool AndroidAnalyzer::extractAndParseDB(const std::string& dbPathInImage, const std::string& parseFunction) {
    std::string tempPath = "/tmp/" + std::to_string(std::time(nullptr)) + "_" + std::filesystem::path(dbPathInImage).filename().string();
    if (!fileExtractor_->extractFileByPath(dbPathInImage, tempPath)) {
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

    std::filesystem::remove(tempPath);
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
