// WindowsDBOperations_User.cpp
// User accounts, USB devices, Recycle Bin insert/query operations

#include "WindowsAnalysisDatabase.h"

#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)



// User account operations
bool WindowsAnalysisDatabase::insertUserInfo(const WindowsUserInfo& user) {
    const char* sql = "INSERT INTO user_accounts (rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_INT(stmt, 1, user.rid);
    BIND_TEXT(stmt, 2, user.username);
    BIND_TEXT(stmt, 3, user.fullName);
    BIND_TEXT(stmt, 4, user.comment);
    BIND_INT64(stmt, 5, user.lastLogin);
    BIND_INT64(stmt, 6, user.passwordLastSet);
    BIND_INT64(stmt, 7, user.accountExpires);
    BIND_INT64(stmt, 8, user.passwordExpires);
    BIND_TEXT(stmt, 9, user.accountFlags);
    BIND_INT(stmt, 10, user.isAdmin ? 1 : 0);
    BIND_TEXT(stmt, 11, user.homeDirectory);
    BIND_TEXT(stmt, 12, user.profilePath);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<WindowsUserInfo> WindowsAnalysisDatabase::queryUserAccounts(const std::string& whereClause) {
    std::vector<WindowsUserInfo> results;
    std::string sql = "SELECT rid, username, full_name, comment, last_login, password_last_set, account_expires, password_expires, account_flags, is_admin, home_directory, profile_path FROM user_accounts";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        WindowsUserInfo user;
        user.rid = sqlite3_column_int(stmt, 0);
        user.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        user.fullName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        user.comment = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        user.lastLogin = sqlite3_column_int64(stmt, 4);
        user.passwordLastSet = sqlite3_column_int64(stmt, 5);
        user.accountExpires = sqlite3_column_int64(stmt, 6);
        user.passwordExpires = sqlite3_column_int64(stmt, 7);
        user.accountFlags = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";
        user.isAdmin = sqlite3_column_int(stmt, 9) != 0;
        user.homeDirectory = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)) ?: "";
        user.profilePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)) ?: "";
        results.push_back(user);
    }
    sqlite3_finalize(stmt);
    return results;
}

// USB device operations
bool WindowsAnalysisDatabase::insertUSBDevice(const USBDeviceInfo& device) {
    const char* sql = "INSERT INTO usb_devices (vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, device.vendorId);
    BIND_TEXT(stmt, 2, device.productId);
    BIND_TEXT(stmt, 3, device.serialNumber);
    BIND_TEXT(stmt, 4, device.deviceDescription);
    BIND_TEXT(stmt, 5, device.friendlyName);
    BIND_TEXT(stmt, 6, device.deviceClass);
    BIND_INT64(stmt, 7, device.firstConnected);
    BIND_INT64(stmt, 8, device.lastConnected);
    BIND_TEXT(stmt, 9, device.lastDriveLetter);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<USBDeviceInfo> WindowsAnalysisDatabase::queryUSBDevices(const std::string& whereClause) {
    std::vector<USBDeviceInfo> results;
    std::string sql = "SELECT vendor_id, product_id, serial_number, device_description, friendly_name, device_class, first_connected, last_connected, last_drive_letter FROM usb_devices";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        USBDeviceInfo device;
        device.vendorId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        device.productId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        device.serialNumber = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        device.deviceDescription = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)) ?: "";
        device.friendlyName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4)) ?: "";
        device.deviceClass = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        device.firstConnected = sqlite3_column_int64(stmt, 6);
        device.lastConnected = sqlite3_column_int64(stmt, 7);
        device.lastDriveLetter = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8)) ?: "";
        results.push_back(device);
    }
    sqlite3_finalize(stmt);
    return results;
}

// Recycle bin operations
bool WindowsAnalysisDatabase::insertRecycleBinEntry(const RecycleBinEntry& entry) {
    const char* sql = "INSERT INTO recycle_bin (recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    BIND_TEXT(stmt, 1, entry.recycleFilePath);
    BIND_TEXT(stmt, 2, entry.originalPath);
    BIND_TEXT(stmt, 3, entry.fileName);
    BIND_INT64(stmt, 4, entry.deletionTime);
    BIND_INT64(stmt, 5, entry.originalSize);
    BIND_TEXT(stmt, 6, entry.userSid);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return result;
}

std::vector<RecycleBinEntry> WindowsAnalysisDatabase::queryRecycleBinEntries(const std::string& whereClause) {
    std::vector<RecycleBinEntry> results;
    std::string sql = "SELECT recycle_file_path, original_path, file_name, deletion_time, original_size, user_sid FROM recycle_bin";
    if (!whereClause.empty()) sql += " WHERE " + whereClause;
    sql += ";";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return results;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        RecycleBinEntry entry;
        entry.recycleFilePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
        entry.originalPath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
        entry.fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)) ?: "";
        entry.deletionTime = sqlite3_column_int64(stmt, 3);
        entry.originalSize = sqlite3_column_int64(stmt, 4);
        entry.userSid = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)) ?: "";
        results.push_back(entry);
    }
    sqlite3_finalize(stmt);
    return results;
}

