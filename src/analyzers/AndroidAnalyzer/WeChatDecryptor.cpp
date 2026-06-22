#include "WeChatDecryptor.h"

// Suppress OpenSSL 3.x deprecation warnings for legacy MD5 API
#define OPENSSL_SUPPRESS_DEPRECATED
#include <openssl/md5.h>

#include <fstream>
#include <algorithm>
#include <cstring>
#include <cstdio>

#include <openssl/crypto.h>

WeChatDecryptor::WeChatDecryptor() = default;

WeChatDecryptor::~WeChatDecryptor() {
    close();
}

void WeChatDecryptor::close() {
    cipher_.close();
}

sqlite3* WeChatDecryptor::getDb() const {
    return cipher_.get();
}

bool WeChatDecryptor::openDatabase(const std::string& dbPath, const std::string& password) {
    close();
    lastError_.clear();

    if (password.empty()) {
        lastError_ = "Password is empty";
        return false;
    }

    // WeChat uses SQLCipher. Try the documented v4 defaults first, then the
    // legacy v2 defaults, then fall back to the full auto-retry matrix. The
    // exact-config attempts short-circuit the broad search for the common case.
    SqlCipherConfig v4;
    v4.compatibility = 4;
    if (cipher_.openWithPassphrase(dbPath, password, v4)) {
        return true;
    }

    SqlCipherConfig v2;
    v2.kdfIterations = 4000;
    v2.hmacAlgo = "sha1";
    if (cipher_.openWithPassphrase(dbPath, password, v2)) {
        return true;
    }

    // Broad auto-retry across SQLCipher v1-v4 presets.
    if (cipher_.openWithPassphrase(dbPath, password)) {
        return true;
    }

    lastError_ = "Failed to decrypt database with provided password";
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
            // Android SharedPreferences XML: <int name="_auth_uin" value="123456"/>
            size_t pos = content.find("_auth_uin");
            if (pos == std::string::npos) pos = content.find("default_uin");
            if (pos != std::string::npos) {
                size_t valueAttr = content.find("value=\"", pos);
                if (valueAttr != std::string::npos && valueAttr - pos < 200) {
                    valueAttr += 7; // skip 'value="'
                    size_t valueEnd = content.find("\"", valueAttr);
                    if (valueEnd != std::string::npos) {
                        uin = content.substr(valueAttr, valueEnd - valueAttr);
                        // Trim whitespace
                        uin.erase(std::remove_if(uin.begin(), uin.end(), ::isspace), uin.end());
                        if (!uin.empty()) break;
                    }
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
    // Zero intermediate material that contains IMEI + UIN
    OPENSSL_cleanse(&combined[0], combined.size());
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
        snprintf(&mdString[i * 2], 3, "%02x", (unsigned int)digest[i]);
    }
    mdString[32] = '\0';
    return std::string(mdString);
}
