#pragma once

#include <string>
#include <vector>
#include <sqlite3.h>
#include "SqlCipherDatabase.h"

class WeChatDecryptor {
public:
    WeChatDecryptor();
    ~WeChatDecryptor();

    // Non-copyable, non-movable (owns the cipher handle)
    WeChatDecryptor(const WeChatDecryptor&) = delete;
    WeChatDecryptor& operator=(const WeChatDecryptor&) = delete;
    WeChatDecryptor(WeChatDecryptor&&) = delete;
    WeChatDecryptor& operator=(WeChatDecryptor&&) = delete;

    // Attempt to open an encrypted WeChat database
    // Returns true on success, false on failure
    bool openDatabase(const std::string& dbPath, const std::string& password);

    // Auto-derive password from device files in the image
    // Returns empty string on failure
    static std::string derivePassword(const std::string& imageMountPath);

    // Get the opened database handle (valid only after openDatabase returns true)
    sqlite3* getDb() const;

    // Close the database
    void close();

    // Get last error message
    const std::string& getLastError() const { return lastError_; }

private:
    SqlCipherDatabase cipher_;
    std::string lastError_;

    static std::string md5(const std::string& input);
};
