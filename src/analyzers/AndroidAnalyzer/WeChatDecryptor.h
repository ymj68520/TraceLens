#pragma once

#include <string>
#include <vector>
#include <sqlite3.h>

class WeChatDecryptor {
public:
    WeChatDecryptor();
    ~WeChatDecryptor();

    // Attempt to open an encrypted WeChat database
    // Returns true on success, false on failure
    bool openDatabase(const std::string& dbPath, const std::string& password);

    // Auto-derive password from device files in the image
    // Returns empty string on failure
    static std::string derivePassword(const std::string& imageMountPath);

    // Get the opened database handle (valid only after openDatabase returns true)
    sqlite3* getDb() const { return db_; }

    // Close the database
    void close();

    // Get last error message
    const std::string& getLastError() const { return lastError_; }

private:
    sqlite3* db_ = nullptr;
    std::string lastError_;

    bool tryOpenWithCipher(const std::string& dbPath, const std::string& password,
                           int kdfIterations, const std::string& hmacAlgo);
    static std::string md5(const std::string& input);
};
