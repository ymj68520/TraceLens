#include "WeChatDecryptor.h"

// Suppress OpenSSL 3.x deprecation warnings for legacy MD5 API
#define OPENSSL_SUPPRESS_DEPRECATED
#include <openssl/md5.h>

#include <fstream>
#include <sstream>
#include <algorithm>
#include <cstring>

WeChatDecryptor::WeChatDecryptor() = default;

WeChatDecryptor::~WeChatDecryptor() {
    close();
}

void WeChatDecryptor::close() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

bool WeChatDecryptor::openDatabase(const std::string& dbPath, const std::string& password) {
    close();
    lastError_.clear();

    if (password.empty()) {
        lastError_ = "Password is empty";
        return false;
    }

    // Try SQLCipher 4.x defaults first (newer WeChat versions)
    if (tryOpenWithCipher(dbPath, password, 64000, "sha512")) {
        return true;
    }

    // Fall back to SQLCipher 2.x defaults (older WeChat versions)
    if (tryOpenWithCipher(dbPath, password, 4000, "sha1")) {
        return true;
    }

    lastError_ = "Failed to decrypt database with provided password";
    return false;
}

bool WeChatDecryptor::tryOpenWithCipher(const std::string& dbPath, const std::string& password,
                                         int kdfIterations, const std::string& hmacAlgo) {
    close();

    if (sqlite3_open(dbPath.c_str(), &db_) != SQLITE_OK) {
        lastError_ = "Failed to open database file: " + std::string(sqlite3_errmsg(db_));
        db_ = nullptr;
        return false;
    }

    // Set SQLCipher key
    std::string pragmaKey = "PRAGMA key = '" + password + "';";
    if (sqlite3_exec(db_, pragmaKey.c_str(), nullptr, nullptr, nullptr) != SQLITE_OK) {
        lastError_ = "Failed to set cipher key: " + std::string(sqlite3_errmsg(db_));
        close();
        return false;
    }

    // Configure SQLCipher parameters
    std::string pragmaKdf = "PRAGMA kdf_iter = " + std::to_string(kdfIterations) + ";";
    sqlite3_exec(db_, pragmaKdf.c_str(), nullptr, nullptr, nullptr);

    std::string pragmaHmac = "PRAGMA cipher_use_hmac = ON;";
    sqlite3_exec(db_, pragmaHmac.c_str(), nullptr, nullptr, nullptr);

    if (hmacAlgo == "sha512") {
        sqlite3_exec(db_, "PRAGMA cipher_page_size = 4096;", nullptr, nullptr, nullptr);
        sqlite3_exec(db_, "PRAGMA cipher_compatibility = 4;", nullptr, nullptr, nullptr);
    } else {
        sqlite3_exec(db_, "PRAGMA cipher_page_size = 1024;", nullptr, nullptr, nullptr);
    }

    // Verify by querying sqlite_master
    sqlite3_stmt* stmt = nullptr;
    const char* testSql = "SELECT count(*) FROM sqlite_master;";
    if (sqlite3_prepare_v2(db_, testSql, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            sqlite3_finalize(stmt);
            return true;  // Successfully decrypted
        }
        sqlite3_finalize(stmt);
    }

    lastError_ = "Decryption verification failed: " + std::string(sqlite3_errmsg(db_));
    close();
    return false;
}

std::string WeChatDecryptor::derivePassword(const std::string& imageMountPath) {
    // Try to find UIN from shared_prefs
    std::string uin;
    std::vector<std::string> uinPaths = {
        "/data/data/com.tencent.mm/shared_prefs/auth_info_key_prefs.xml",
        "/data/data/com.tencent.mm/shared_prefs/system_config_prefs.xml"
    };

    for (const auto& path : uinPaths) {
        std::string fullPath = imageMountPath + path;
        std::ifstream file(fullPath);
        if (file.is_open()) {
            std::string content((std::istreambuf_iterator<char>(file)),
                                 std::istreambuf_iterator<char>());
            // Look for _auth_uin or default_uin
            size_t pos = content.find("_auth_uin");
            if (pos == std::string::npos) pos = content.find("default_uin");
            if (pos != std::string::npos) {
                size_t valStart = content.find(">", pos);
                size_t valEnd = content.find("<", valStart);
                if (valStart != std::string::npos && valEnd != std::string::npos) {
                    uin = content.substr(valStart + 1, valEnd - valStart - 1);
                    // Trim whitespace
                    uin.erase(std::remove_if(uin.begin(), uin.end(), ::isspace), uin.end());
                    if (!uin.empty()) break;
                }
            }
        }
    }

    if (uin.empty()) return "";

    // Try to find IMEI (may be empty on newer devices)
    // Default fallback when IMEI is not available from the image
    std::string imei = "1234567890ABCDEF";

    // Derive password: MD5(IMEI + UIN).substring(0, 7)
    std::string combined = imei + uin;
    std::string hash = md5(combined);
    if (hash.length() >= 7) {
        return hash.substr(0, 7);
    }
    return "";
}

std::string WeChatDecryptor::md5(const std::string& input) {
    unsigned char digest[MD5_DIGEST_LENGTH];
    MD5(reinterpret_cast<const unsigned char*>(input.c_str()), input.size(), digest);

    char mdString[33];
    for (int i = 0; i < 16; i++) {
        sprintf(&mdString[i * 2], "%02x", (unsigned int)digest[i]);
    }
    mdString[32] = '\0';
    return std::string(mdString);
}
