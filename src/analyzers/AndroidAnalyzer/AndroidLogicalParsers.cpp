/**
 * @file AndroidLogicalParsers.cpp
 * @brief Parsers for Android logical-extraction artifacts that the legacy TSK
 *        pipeline does not surface: device identifiers (SSAID), plaintext
 *        note-taking app databases, and an inventory of SQLCipher-encrypted app
 *        databases with their discovered key hints.
 *
 * All file access goes through fileExtractor_->extractFileByPath(), so these
 * parsers work identically against a TSK image, an extracted directory, or a
 * zip archive (Phase 1 IFileExtractor backends).
 */

#include "AndroidAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "PathManager/PathManager.h"
#include "SqlCipherDatabase.h"

#include <sqlite3.h>

#include <algorithm>
#include <cctype>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

namespace fs = std::filesystem;

namespace {
// Minimal base64 decoder for the key fields in Flutter password.json.
std::string base64Decode(const std::string& in) {
    static const char* chars =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    auto lookup = [&](char c) -> int {
        for (int i = 0; i < 64; ++i) {
            if (chars[i] == c) return i;
        }
        return -1;
    };
    std::string out;
    int val = 0, bits = 0;
    for (char c : in) {
        if (c == '=' || c == '\n' || c == '\r' || c == ' ') continue;
        int d = lookup(c);
        if (d < 0) continue;
        val = (val << 6) | d;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<char>((val >> bits) & 0xFF));
        }
    }
    return out;
}

bool decodeRawKeyBase64(const std::string& value, std::string& decoded) {
    decoded.clear();
    if (value.size() != 44 || value.back() != '=') return false;
    static const char* characters =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (size_t index = 0; index + 1 < value.size(); ++index) {
        if (std::strchr(characters, value[index]) == nullptr) return false;
    }
    decoded = base64Decode(value);
    return decoded.size() == 32;
}

std::string toHex(const std::string& bytes) {
    static const char* h = "0123456789abcdef";
    std::string out;
    out.reserve(bytes.size() * 2);
    for (unsigned char b : bytes) {
        out.push_back(h[b >> 4]);
        out.push_back(h[b & 0xF]);
    }
    return out;
}

bool isPlaintextSqlite(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    char magic[16] = {0};
    f.read(magic, 16);
    static const char expected[16] = {'S','Q','L','i','t','e',' ','f','o','r','m','a','t',' ','3','\0'};
    if (f.gcount() != 16 || std::memcmp(magic, expected, sizeof(expected)) != 0) return false;

    sqlite3* db = nullptr;
    const std::string uri = "file:" + path + "?mode=ro";
    if (sqlite3_open_v2(uri.c_str(), &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return false;
    }
    sqlite3_stmt* statement = nullptr;
    const int prepare = sqlite3_prepare_v2(
        db, "SELECT name FROM sqlite_master LIMIT 1;", -1, &statement, nullptr);
    const int step = prepare == SQLITE_OK ? sqlite3_step(statement) : SQLITE_ERROR;
    const bool valid = prepare == SQLITE_OK && (step == SQLITE_ROW || step == SQLITE_DONE);
    if (statement) sqlite3_finalize(statement);
    sqlite3_close(db);
    return valid;
}

// Read a whole file to string.
std::string slurp(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}
}  // namespace

// ---------------------------------------------------------------------------
// Device identifiers (Android SSAID / "Android ID")
// ---------------------------------------------------------------------------

void AndroidAnalyzer::analyzeDeviceIdentifiers() {
    // Android 8+ stores per-app SSAID ("Android ID") in:
    //   data/system/users/<uid>/settings_ssaid.xml
    // The "userkey" entry (package="android") is the device-wide seed.
    const std::string srcPaths[] = {
        "data/system/users/0/settings_ssaid.xml",
        "data/system/settings_ssaid.xml",
    };

    for (const auto& rel : srcPaths) {
        std::string temp = makeAnalysisTempPath(rel);
        if (!fileExtractor_->extractFileByPath(rel, temp)) {
            fs::remove(temp);
            continue;
        }
        std::string xml = slurp(temp);
        fs::remove(temp);
        if (xml.empty()) continue;

        // Each <setting ... name="<n>" value="<v>" package="<pkg>" .../>
        size_t pos = 0;
        int count = 0;
        while ((pos = xml.find("<setting", pos)) != std::string::npos) {
            size_t end = xml.find("/>", pos);
            if (end == std::string::npos) break;
            std::string tag = xml.substr(pos, end - pos);

            auto attr = [&](const std::string& key) -> std::string {
                std::string k = key + "=\"";
                size_t p = tag.find(k);
                if (p == std::string::npos) return {};
                p += k.size();
                size_t e = tag.find("\"", p);
                return e == std::string::npos ? std::string() : tag.substr(p, e - p);
            };

            std::string name = attr("name");
            std::string value = attr("value");
            std::string pkg = attr("package");
            if (!value.empty()) {
                std::string type = (pkg == "android") ? "ssaid_seed" : "android_id";
                androidDb_->insertDeviceIdentifier(type, value, pkg, rel);
                ++count;
            }
            pos = end;
        }
        std::cout << "  Device identifiers: parsed " << count
                  << " SSAID entries from " << rel << std::endl;
        break;  // first available source wins
    }
}

// ---------------------------------------------------------------------------
// Plausible note DBs to scan (package -> list of candidate db files).
// Only plaintext DBs yield notes; encrypted ones are inventoried separately.
// ---------------------------------------------------------------------------

namespace {
struct NoteDbTarget {
    const char* package;
    const char* dbRelPath;
};

const NoteDbTarget kNoteTargets[] = {
    {"com.jinghong.notebookkssjh", "data/data/com.jinghong.notebookkssjh/databases/NotePal.db"},
    {"com.jinghong.notebookkssjh", "data/data/com.jinghong.notebookkssjh/databases/GTNotes.db"},
    {"com.notevault.app", "data/data/com.notevault.app/databases/notevault.db"},
    {"com.miui.notes", "data/data/com.miui.notes/databases/note.db"},
    {"com.android.providers.notes", "data/data/com.android.providers.notes/databases/note.db"},
};

// Heuristic: list tables, and if a table looks note-like, pull (title|name,
// content|body|preview) rows generically.
void extractNotesGeneric(const std::string& dbLocalPath,
                         const std::string& pkg,
                         const std::string& srcRel,
                         AndroidAnalysisDatabase* out) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbLocalPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }

    // Find candidate note tables.
    std::vector<std::string> tables;
    sqlite3_stmt* st = nullptr;
    if (sqlite3_prepare_v2(db, "SELECT name FROM sqlite_master WHERE type='table';",
                           -1, &st, nullptr) == SQLITE_OK) {
        while (sqlite3_step(st) == SQLITE_ROW) {
            std::string t = reinterpret_cast<const char*>(sqlite3_column_text(st, 0));
            std::string tl = t;
            std::transform(tl.begin(), tl.end(), tl.begin(), ::tolower);
            if (tl.find("note") != std::string::npos || tl.find("memo") != std::string::npos) {
                tables.push_back(t);
            }
        }
        sqlite3_finalize(st);
    }

    for (const auto& table : tables) {
        // Resolve column names for this table.
        std::string pragma = "PRAGMA table_info(\"" + table + "\");";
        if (sqlite3_prepare_v2(db, pragma.c_str(), -1, &st, nullptr) != SQLITE_OK) continue;
        std::vector<std::string> cols;
        while (sqlite3_step(st) == SQLITE_ROW) {
            cols.emplace_back(reinterpret_cast<const char*>(sqlite3_column_text(st, 1)));
        }
        sqlite3_finalize(st);

        auto hasCol = [&](const std::vector<std::string>& names) -> std::string {
            for (const auto& want : names) {
                for (const auto& c : cols) {
                    std::string cl = c;
                    std::transform(cl.begin(), cl.end(), cl.begin(), ::tolower);
                    if (cl == want) return c;
                }
            }
            return {};
        };

        std::string idCol = hasCol({"id", "_id", "note_id"});
        std::string titleCol = hasCol({"title", "name", "subject"});
        std::string contentCol = hasCol({"content", "body", "preview_content", "preview", "text", "note"});
        std::string tagsCol = hasCol({"tags", "tag", "category"});

        if (titleCol.empty() && contentCol.empty()) continue;

        std::string sql = "SELECT ";
        sql += (idCol.empty() ? "NULL" : "\"" + idCol + "\"") + ", ";
        sql += (titleCol.empty() ? "NULL" : "\"" + titleCol + "\"") + ", ";
        sql += (contentCol.empty() ? "NULL" : "\"" + contentCol + "\"");
        if (!tagsCol.empty()) sql += ", \"" + tagsCol + "\"";
        sql += " FROM \"" + table + "\";";

        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &st, nullptr) != SQLITE_OK) continue;
        while (sqlite3_step(st) == SQLITE_ROW) {
            auto txt = [](sqlite3_stmt* s, int i) -> std::string {
                if (sqlite3_column_type(s, i) == SQLITE_NULL) return {};
                const unsigned char* v = sqlite3_column_text(s, i);
                return v ? reinterpret_cast<const char*>(v) : std::string();
            };
            std::string id = txt(st, 0);
            std::string title = txt(st, 1);
            std::string content = txt(st, 2);
            std::string tags = tagsCol.empty() ? std::string() : txt(st, 3);
            out->insertAppNote(pkg, id, title, content, tags, /*isPrivate=*/false, srcRel);
        }
        sqlite3_finalize(st);
    }
    sqlite3_close(db);
}
}  // namespace

void AndroidAnalyzer::analyzeAppNotes() {
    int total = 0;
    for (const auto& t : kNoteTargets) {
        const std::string temp = makeAnalysisTempPath(t.dbRelPath);
        std::vector<std::string> stagedPaths;
        if (!stageSqliteBundle(t.dbRelPath, temp, stagedPaths)) {
            std::cout << "  App notes: (absent) " << t.dbRelPath << std::endl;
            continue;
        }
        // Only parse plaintext DBs here. Encrypted DBs are inventoried by
        // analyzeEncryptedAppDatabases().
        const bool plain = isPlaintextSqlite(temp);
        std::cout << "  App notes: found " << t.dbRelPath
                  << " (" << (plain ? "plaintext" : "encrypted") << ")" << std::endl;
        if (plain) {
            extractNotesGeneric(temp, t.package, t.dbRelPath, androidDb_.get());
            ++total;
        }
        for (const auto& path : stagedPaths) fs::remove(path);
    }
    std::cout << "  App notes: parsed " << total << " plaintext note DB(s)" << std::endl;
}

// ---------------------------------------------------------------------------
// Encrypted DB inventory with key hints
// ---------------------------------------------------------------------------

namespace {
struct EncTarget {
    const char* package;
    const char* dbRelPath;
    const char* keyHintRelPath;  // may be nullptr
};

const EncTarget kEncTargets[] = {
    {"com.socialchat.social_chat_app",
     "data/data/com.socialchat.social_chat_app/databases/social_chat.db",
     "data/data/com.socialchat.social_chat_app/app_flutter/files/password.json"},
    {"com.hidden.calculator",
     "data/data/com.hidden.calculator/databases/hidden_notes.db",
     "data/data/com.hidden.calculator/app_flutter/files/password.json"},
    {"com.notevault.app",
     "data/data/com.notevault.app/databases/notevault.db",
     "data/data/com.notevault.app/app_flutter/files/password.json"},
    {"com.tencent.mm",
     "data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db",
     nullptr},
};
}  // namespace

std::string AndroidAnalyzer::readPasswordJsonKey(const std::string& imageRelPath, std::string& outType) {
    std::string temp = makeAnalysisTempPath(imageRelPath);
    if (!fileExtractor_->extractFileByPath(imageRelPath, temp)) {
        fs::remove(temp);
        return {};
    }
    std::string content = slurp(temp);
    fs::remove(temp);

    // Trim surrounding whitespace.
    auto trim = [](std::string s) {
        auto notspace = [](int c) { return !std::isspace(c); };
        s.erase(s.begin(), std::find_if(s.begin(), s.end(), notspace));
        s.erase(std::find_if(s.rbegin(), s.rend(), notspace).base(), s.end());
        return s;
    };
    std::string body = trim(content);

    // Case 1: well-formed JSON object with a "key" or "password" field.
    auto extractStrValue = [&](const std::string& raw, const std::string& key) -> std::string {
        std::string needle = "\"" + key + "\"";
        size_t p = raw.find(needle);
        if (p == std::string::npos) {
            needle = key + ":";  // tolerate unquoted keys
            p = raw.find(needle);
        }
        if (p == std::string::npos) return {};
        size_t colon = raw.find(":", p);
        if (colon == std::string::npos) return {};
        size_t q1 = raw.find("\"", colon + 1);
        if (q1 == std::string::npos) return {};
        size_t q2 = raw.find("\"", q1 + 1);
        if (q2 == std::string::npos) return {};
        return raw.substr(q1 + 1, q2 - q1 - 1);
    };

    if (!body.empty() && body.front() == '{') {
        std::string key = extractStrValue(content, "key");
        std::string decoded;
        if (!key.empty() && decodeRawKeyBase64(key, decoded)) {
            outType = "raw_key_base64";
            return key;
        }
        std::string pass = extractStrValue(content, "password");
        if (!pass.empty()) {
            outType = "passphrase";
            return pass;
        }
    }

    // Case 2: a bare secret (no JSON wrapper). Some apps write the raw
    // passphrase directly to password.json. Accept it if it is short and
    // printable (sanity guard against accidentally reading a binary blob).
    if (!body.empty() && body.size() <= 256 &&
        std::all_of(body.begin(), body.end(), [](unsigned char c) { return c >= 0x20 && c < 0x7f; })) {
        outType = "passphrase_raw";
        return body;
    }

    return {};
}

void AndroidAnalyzer::analyzeEncryptedAppDatabases() {
    int count = 0;
    for (const auto& t : kEncTargets) {
        const std::string dbTemp = makeAnalysisTempPath(t.dbRelPath);
        std::vector<std::string> stagedPaths;
        if (!stageSqliteBundle(t.dbRelPath, dbTemp, stagedPaths)) {
            continue;
        }

        std::string keyHint, hintType, keySource;
        if (t.keyHintRelPath) {
            keyHint = readPasswordJsonKey(t.keyHintRelPath, hintType);
            if (!keyHint.empty()) keySource = t.keyHintRelPath;
        }

        std::string openStatus;
        if (isPlaintextSqlite(dbTemp)) {
            openStatus = "plaintext";
        } else if (keyHint.empty()) {
            openStatus = "parse_error";
        } else {
            // A key hint is positive evidence that the non-plaintext database is
            // intended to be SQLCipher. Do not classify arbitrary/truncated data
            // as encrypted merely because it appears in an encrypted-app path.
#ifdef HAVE_SQLCIPHER
            bool opened = false;
            SqlCipherDatabase cipher;
            if (hintType == "raw_key_base64") {
                std::string raw;
                if (decodeRawKeyBase64(keyHint, raw)) {
                    opened = cipher.openWithRawKey(dbTemp, toHex(raw));
                }
            } else if (hintType == "passphrase" || hintType == "passphrase_raw") {
                opened = cipher.openWithPassphrase(dbTemp, keyHint);
            }
            openStatus = opened ? "decrypted" : "encrypted_locked";
#else
            openStatus = "encrypted_no_sqlcipher_build";
#endif
        }

        androidDb_->insertEncryptedDb(t.package, t.dbRelPath,
                                      hintType.empty() ? "none_found" : hintType,
                                      keyHint, keySource, openStatus);
        ++count;
        for (const auto& path : stagedPaths) fs::remove(path);
    }
    std::cout << "  Encrypted DB inventory: recorded " << count << " app DB(s)" << std::endl;
}
