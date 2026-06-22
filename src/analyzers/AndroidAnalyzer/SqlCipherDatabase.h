/**
 * @file SqlCipherDatabase.h
 * @brief Reusable SQLCipher-encrypted SQLite opener for arbitrary Android apps.
 *
 * WeChatDecryptor hard-coded WeChat's specific cipher configuration. Most other
 * Flutter/Android apps that bundle libsqlcipher (e.g. the 4th Pangu-Stone-Cup
 * final's social_chat / hidden_notes / notevault apps) store their DB key or
 * passphrase in a discoverable place (password.json, shared_prefs, an "options"
 * table) but use varying SQLCipher parameters.
 *
 * SqlCipherDatabase factors out the cipher-opening kernel so every app parser
 * can reuse it:
 *   1. open the file with the sqlcipher-enabled sqlite3 build,
 *   2. set PRAGMA key (passphrase OR raw 32-byte hex key via x'...'),
 *   3. try a set of common (compat / page_size / hmac / kdf_iter) combinations,
 *   4. verify by reading sqlite_master.
 *
 * Callers that already know the exact parameters may pass them directly;
 * callers that only have a key/passphrase may pass an empty config to trigger
 * the built-in auto-retry matrix.
 */

#pragma once
#ifndef SQLCIPHER_DATABASE_H
#define SQLCIPHER_DATABASE_H

#include <string>
#include <sqlite3.h>

/**
 * @brief Exact SQLCipher parameters for a known database.
 *
 * If any field is left at its default / empty, SqlCipherDatabase will iterate
 * that dimension during auto-retry.
 */
struct SqlCipherConfig {
    /// SQLCipher major compatibility level (1-4). 0 = auto.
    int compatibility = 0;
    /// Page size in bytes. 0 = auto (default per compat level).
    int pageSize = 0;
    /// HMAC algorithm: "" (auto), "sha1", "sha256", "sha512".
    std::string hmacAlgo;
    /// PBKDF2 iteration count. 0 = auto (default per compat level). Ignored
    /// for raw-key mode.
    int kdfIterations = 0;
};

class SqlCipherDatabase {
public:
    SqlCipherDatabase() = default;
    ~SqlCipherDatabase();

    SqlCipherDatabase(const SqlCipherDatabase&) = delete;
    SqlCipherDatabase& operator=(const SqlCipherDatabase&) = delete;
    SqlCipherDatabase(SqlCipherDatabase&&) = delete;
    SqlCipherDatabase& operator=(SqlCipherDatabase&&) = delete;

    /**
     * @brief Open a database using a passphrase (KDF-derived key).
     * @param dbPath   Path to the .db file.
     * @param pass     Passphrase string (not hex).
     * @param config   Optional exact config; empty/auto fields trigger retry.
     * @return true if sqlite_master could be read after decryption.
     */
    bool openWithPassphrase(const std::string& dbPath,
                            const std::string& pass,
                            const SqlCipherConfig& config = {});

    /**
     * @brief Open a database using a raw 256-bit key.
     * @param dbPath   Path to the .db file.
     * @param keyHex   64 hex chars (32 bytes). No KDF is applied.
     * @param config   Optional exact config; empty/auto fields trigger retry.
     *                 (kdfIterations is ignored in raw-key mode.)
     * @return true if sqlite_master could be read after decryption.
     */
    bool openWithRawKey(const std::string& dbPath,
                        const std::string& keyHex,
                        const SqlCipherConfig& config = {});

    /// Opened sqlite3 handle (valid only after a successful open call).
    sqlite3* get() const { return db_; }

    void close();

    const std::string& lastError() const { return lastError_; }

private:
    sqlite3* db_ = nullptr;
    std::string lastError_;

    /**
     * @brief Set PRAGMA key then the given parameters and verify sqlite_master.
     * @param pragmaKeySql  Full "PRAGMA key = '...';" or "PRAGMA key = \"x'..'\";"
     *                      statement with the value already escaped.
     * @param isRawKey      When true, kdfIterations is not applied.
     */
    bool tryOpen(const std::string& dbPath,
                 const std::string& pragmaKeySql,
                 const SqlCipherConfig& config,
                 bool isRawKey);

    static std::string escapeSqlSingle(const std::string& s);
};

#endif // SQLCIPHER_DATABASE_H
