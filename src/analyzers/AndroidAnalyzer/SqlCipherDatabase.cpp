#include "SqlCipherDatabase.h"
#include <vector>
#include <string>
#include <cstdio>
#include <filesystem>

SqlCipherDatabase::~SqlCipherDatabase() {
    close();
}

void SqlCipherDatabase::close() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

std::string SqlCipherDatabase::escapeSqlSingle(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 4);
    for (char c : s) {
        if (c == '\'') out += "''";
        else out += c;
    }
    return out;
}

bool SqlCipherDatabase::tryOpen(const std::string& dbPath,
                                const std::string& pragmaKeySql,
                                const SqlCipherConfig& config,
                                bool isRawKey) {
    close();
    lastError_.clear();

    // A missing/empty input is not a successfully decrypted empty database.
    // Never let sqlite3_open create a file at an evidence path.
    std::error_code error;
    if (!std::filesystem::is_regular_file(dbPath, error) || error ||
        std::filesystem::file_size(dbPath, error) < 16 || error) {
        lastError_ = "数据库文件不存在、为空或无法读取";
        return false;
    }
    if (sqlite3_open_v2(dbPath.c_str(), &db_, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        lastError_ = "无法以只读方式打开数据库文件";
        close();
        return false;
    }

    // Key must be set before any other PRAGMA.
    if (sqlite3_exec(db_, pragmaKeySql.c_str(), nullptr, nullptr, nullptr) != SQLITE_OK) {
        lastError_ = "PRAGMA key failed";
        close();
        return false;
    }

    auto exec = [this](const char* sql) {
        sqlite3_exec(db_, sql, nullptr, nullptr, nullptr);
    };

    if (config.compatibility > 0) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "PRAGMA cipher_compatibility = %d;", config.compatibility);
        exec(buf);
    }
    if (config.pageSize > 0) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "PRAGMA cipher_page_size = %d;", config.pageSize);
        exec(buf);
    }
    if (!isRawKey && config.kdfIterations > 0) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "PRAGMA kdf_iter = %d;", config.kdfIterations);
        exec(buf);
    }
    if (!config.hmacAlgo.empty()) {
        exec(("PRAGMA cipher_hmac_algorithm = " + config.hmacAlgo + ";").c_str());
    }

    // Verify decryption by reading the schema catalog.
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, "SELECT count(*) FROM sqlite_master;", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            sqlite3_finalize(stmt);
            return true;
        }
        sqlite3_finalize(stmt);
    }

    lastError_ = "Decryption verification failed";
    close();
    return false;
}

namespace {
// Build the parameter matrix used for auto-retry when the caller leaves fields
// at their defaults. These cover SQLCipher v1-v4 defaults and the common
// sqflite_sqlcipher / Flutter variants.
std::vector<SqlCipherConfig> candidateConfigs() {
    // (compat, pageSize, hmac, kdfIter)
    struct P { int c; int ps; const char* h; int k; };
    const P presets[] = {
        {4, 0, "", 0},       // SQLCipher 4 defaults (256000/sha512/4096)
        {3, 0, "", 0},       // SQLCipher 3 defaults (64000/sha1/1024)
        {2, 0, "", 0},       // SQLCipher 2 defaults (4000/sha1/1024)
        {1, 0, "", 0},       // SQLCipher 1 defaults (4000/sha1/1024)
        {0, 4096, "sha512", 0},
        {0, 1024, "sha1", 0},
        {0, 4096, "sha256", 0},
        {0, 4096, "sha1", 0},
        {0, 1024, "sha512", 0},
    };
    std::vector<SqlCipherConfig> v;
    for (const auto& p : presets) {
        SqlCipherConfig c;
        c.compatibility = p.c;
        c.pageSize = p.ps;
        c.hmacAlgo = p.h;
        c.kdfIterations = p.k;
        v.push_back(c);
    }
    return v;
}
}  // namespace

bool SqlCipherDatabase::openWithPassphrase(const std::string& dbPath,
                                           const std::string& pass,
                                           const SqlCipherConfig& config) {
    if (pass.empty()) {
        lastError_ = "Passphrase is empty";
        return false;
    }
    std::string pragma = "PRAGMA key = '" + escapeSqlSingle(pass) + "';";

    if (config.compatibility > 0 || config.pageSize > 0 ||
        config.kdfIterations > 0 || !config.hmacAlgo.empty()) {
        return tryOpen(dbPath, pragma, config, /*isRawKey=*/false);
    }

    for (const auto& c : candidateConfigs()) {
        if (tryOpen(dbPath, pragma, c, false)) {
            return true;
        }
    }
    return false;
}

bool SqlCipherDatabase::openWithRawKey(const std::string& dbPath,
                                       const std::string& keyHex,
                                       const SqlCipherConfig& config) {
    if (keyHex.empty()) {
        lastError_ = "Raw key is empty";
        return false;
    }
    // SQLCipher raw-key syntax: PRAGMA key = "x'<64 hex>'";
    // Note the double-quote outer wrapper is required for the x'' literal.
    std::string pragma = "PRAGMA key = \"x'" + keyHex + "'\";";

    if (config.compatibility > 0 || config.pageSize > 0 ||
        !config.hmacAlgo.empty()) {
        return tryOpen(dbPath, pragma, config, /*isRawKey=*/true);
    }

    for (const auto& c : candidateConfigs()) {
        if (tryOpen(dbPath, pragma, c, true)) {
            return true;
        }
    }
    return false;
}
