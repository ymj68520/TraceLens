#include "WechatArtifactParsers.h"

#include "AndroidAnalysisDatabase.h"
#include "MiuiArtifactParsers.h"
#include "MiuiBackupExtractor.h"

#include <openssl/evp.h>
#include <pugixml.hpp>
#include <sqlite3.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

constexpr char kWechatPackage[] = "com.tencent.mm";
constexpr uint64_t kMaximumArtifactBytes = 2ULL * 1024 * 1024;
constexpr uint64_t kMaximumXmlBytes = 1024ULL * 1024;
constexpr size_t kMaximumRecoveredValueBytes = 4096;
constexpr size_t kMaximumSqliteRowsPerTable = 100;
constexpr size_t kMaximumSqliteRecords = 1000;

struct ArtifactInfo {
    std::string category;
    std::string format;
    std::string parseStatus;
    std::string summary;
};

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool startsWith(const std::string& value, const char* prefix) {
    return value.rfind(prefix, 0) == 0;
}

bool isSensitiveKey(const std::string& key) {
    const std::string value = lower(key);
    return value.find("token") != std::string::npos ||
           value.find("guid") != std::string::npos ||
           value.find("android_id") != std::string::npos ||
           value.find("androidid") != std::string::npos ||
           value.find("mac") != std::string::npos ||
           value.find("uin") != std::string::npos ||
           value.find("device") != std::string::npos ||
           value.find("key") != std::string::npos ||
           value.find("session") != std::string::npos ||
           value.find("private") != std::string::npos ||
           value.find("imei") != std::string::npos ||
           value.find("password") != std::string::npos;
}

bool endsWith(const std::string& value, const char* suffix) {
    const size_t length = std::char_traits<char>::length(suffix);
    return value.size() >= length && value.compare(value.size() - length, length, suffix) == 0;
}

bool containsSegment(const std::string& memberName, const char* segment) {
    const std::string needle = std::string("/") + segment + "/";
    return memberName.find(needle) != std::string::npos ||
           endsWith(memberName, (std::string("/") + segment).c_str());
}

ArtifactInfo classifyArtifact(const std::string& memberName) {
    ArtifactInfo result{"binary", "unknown", "recognized", "WeChat binary artifact"};
    const std::string base = memberName.substr(memberName.find_last_of('/') + 1);

    if (endsWith(base, "-wal") || endsWith(base, "-shm") || endsWith(base, "-journal")) {
        result.category = "database_sidecar";
        result.format = "sqlite_sidecar";
        result.summary = "SQLite sidecar file";
    } else if (isMiuiWeChatDatabaseMember(memberName)) {
        // Per-account SQLCipher EnMicroMsg.db held in MIUI's r/MicroMsg or db
        // subtree. Decryption is handled by the dedicated message pipeline; here
        // we only inventory it as recognized evidence.
        result.category = "database";
        result.format = "sqlcipher";
        result.summary = "WeChat SQLCipher primary database (EnMicroMsg.db)";
    } else if (startsWith(memberName, "apps/com.tencent.mm/db/")) {
        result.category = "database";
        result.format = "unknown";
        result.summary = "WeChat database candidate";
    } else if (containsSegment(memberName, "mmkv")) {
        result.category = "mmkv";
        result.format = endsWith(base, ".crc") ? "mmkv_crc" : "mmkv";
        result.summary = "WeChat MMKV key-value store";
    } else if (startsWith(memberName, "apps/com.tencent.mm/sp/") ||
               startsWith(memberName, "apps/com.tencent.mm/d_sp/") ||
               containsSegment(memberName, "shared_prefs")) {
        result.category = "shared_pref";
        result.format = endsWith(base, ".xml") ? "xml" : "unknown";
        result.summary = "WeChat shared preference";
    } else if (containsSegment(memberName, "xlog") ||
               endsWith(base, ".wxlog") || endsWith(base, ".xlog")) {
        result.category = "xlog";
        result.format = endsWith(base, ".wxlog") ? "wxlog" : "xlog";
        result.summary = "WeChat Xlog runtime log";
    } else if (endsWith(base, ".json")) {
        result.category = "config";
        result.format = "json";
        result.summary = "WeChat JSON configuration or UI resource";
    } else if (endsWith(base, ".zip")) {
        result.category = "cache";
        result.format = "zip";
        result.summary = "WeChat packaged UI resource";
    }
    return result;
}

bool readBounded(const fs::path& path, uint64_t maximum, std::string& output) {
    output.clear();
    std::error_code error;
    const uint64_t size = fs::file_size(path, error);
    if (error || size > maximum) return false;

    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    output.assign(static_cast<size_t>(size), '\0');
    input.read(output.data(), static_cast<std::streamsize>(output.size()));
    return input.good() || (input.eof() && input.gcount() == static_cast<std::streamsize>(output.size()));
}

std::string sha256(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};

    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1) return {};
    std::array<char, 64 * 1024> buffer{};
    while (input) {
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto bytes = input.gcount();
        if (bytes > 0 && EVP_DigestUpdate(context.get(), buffer.data(), static_cast<size_t>(bytes)) != 1) {
            return {};
        }
    }
    if (!input.eof()) return {};

    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
    unsigned int digestLength = 0;
    if (EVP_DigestFinal_ex(context.get(), digest.data(), &digestLength) != 1) return {};
    std::ostringstream encoded;
    encoded << std::hex << std::setfill('0');
    for (size_t index = 0; index < digestLength; ++index) {
        encoded << std::setw(2) << static_cast<unsigned>(digest[index]);
    }
    return encoded.str();
}

std::string sha256Text(std::string_view value) {
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(context.get(), value.data(), value.size()) != 1) {
        return {};
    }

    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
    unsigned int digestLength = 0;
    if (EVP_DigestFinal_ex(context.get(), digest.data(), &digestLength) != 1) return {};
    std::ostringstream encoded;
    encoded << std::hex << std::setfill('0');
    for (size_t index = 0; index < digestLength; ++index) {
        encoded << std::setw(2) << static_cast<unsigned>(digest[index]);
    }
    return encoded.str();
}

bool stageMember(MiuiBackupExtractor& source, const std::string& memberName,
                 const fs::path& path) {
    std::error_code error;
    fs::remove(path, error);
    return source.extractTarMember(memberName, path.string());
}

bool parseSharedPreferences(const fs::path& path, const std::string& sourcePath,
                            AndroidAnalysisDatabase& database) {
    std::string bytes;
    if (!readBounded(path, kMaximumXmlBytes, bytes)) return false;

    pugi::xml_document document;
    if (!document.load_buffer(bytes.data(), bytes.size(), pugi::parse_default, pugi::encoding_utf8)) {
        return false;
    }
    const auto root = document.child("map");
    if (!root) return false;

    const std::string nameSpace = fs::path(sourcePath).stem().string();
    for (const auto& node : root.children()) {
        const std::string type = node.name();
        const auto name = node.attribute("name");
        if (!name || std::string(name.value()).empty()) continue;

        std::string value;
        if (type == "string") {
            value = node.text().as_string();
        } else if (type == "set") {
            bool first = true;
            for (const auto& item : node.children("string")) {
                if (!first) value.push_back('\n');
                value += item.text().as_string();
                first = false;
            }
        } else if (type == "int" || type == "long" || type == "float" || type == "boolean") {
            value = node.attribute("value").as_string();
        } else {
            continue;
        }

        if (value.size() > kMaximumRecoveredValueBytes) value.resize(kMaximumRecoveredValueBytes);
        const bool sensitive = isSensitiveKey(name.value());
        if (!database.insertWechatKvRecord(sourcePath, nameSpace, name.value(), type, value,
                                           sha256Text(value), sensitive, "parsed")) {
            return false;
        }
    }
    return true;
}

bool isSqlite(const fs::path& path) {
    static constexpr std::array<char, 16> header = {
        'S', 'Q', 'L', 'i', 't', 'e', ' ', 'f', 'o', 'r', 'm', 'a', 't', ' ', '3', '\0'
    };
    std::ifstream input(path, std::ios::binary);
    std::array<char, header.size()> actual{};
    input.read(actual.data(), static_cast<std::streamsize>(actual.size()));
    return input.gcount() == static_cast<std::streamsize>(actual.size()) && actual == header;
}

bool isRecoverableTable(const std::string& tableName, std::string& kind) {
    const std::string value = lower(tableName);
    for (const auto& rule : std::array<std::pair<const char*, const char*>, 9>{
             {{"message", "message"}, {"chat", "message"}, {"conversation", "conversation"},
              {"contact", "contact"}, {"friend", "contact"}, {"group", "group"},
              {"chatroom", "group"}, {"account", "account"}, {"device", "device"}}}) {
        if (value.find(rule.first) != std::string::npos) {
            kind = rule.second;
            return true;
        }
    }
    return false;
}

std::string sqliteValue(sqlite3_stmt* statement, int column) {
    switch (sqlite3_column_type(statement, column)) {
        case SQLITE_INTEGER: return std::to_string(sqlite3_column_int64(statement, column));
        case SQLITE_FLOAT: return std::to_string(sqlite3_column_double(statement, column));
        case SQLITE_TEXT: {
            const auto* value = sqlite3_column_text(statement, column);
            return value ? reinterpret_cast<const char*>(value) : std::string{};
        }
        case SQLITE_BLOB: return "<BLOB>";
        default: return {};
    }
}

bool recoverSqliteRecords(const fs::path& path, const std::string& sourcePath,
                          AndroidAnalysisDatabase& database, size_t& recordCount) {
    sqlite3* raw = nullptr;
    if (sqlite3_open_v2(path.string().c_str(), &raw, SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX,
                        nullptr) != SQLITE_OK) {
        if (raw) sqlite3_close(raw);
        return false;
    }
    std::unique_ptr<sqlite3, decltype(&sqlite3_close)> connection(raw, sqlite3_close);
    sqlite3_busy_timeout(connection.get(), 1000);
    sqlite3_limit(connection.get(), SQLITE_LIMIT_LENGTH, 8 * 1024 * 1024);
    sqlite3_limit(connection.get(), SQLITE_LIMIT_COLUMN, 256);

    sqlite3_stmt* rawTables = nullptr;
    if (sqlite3_prepare_v2(connection.get(),
                           "SELECT name FROM sqlite_schema WHERE type='table' "
                           "AND name NOT LIKE 'sqlite_%' ORDER BY name", -1,
                           &rawTables, nullptr) != SQLITE_OK) {
        return false;
    }
    std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> tables(rawTables, sqlite3_finalize);

    recordCount = 0;
    while (sqlite3_step(tables.get()) == SQLITE_ROW && recordCount < kMaximumSqliteRecords) {
        const auto* rawName = sqlite3_column_text(tables.get(), 0);
        if (!rawName) continue;
        const std::string tableName = reinterpret_cast<const char*>(rawName);
        std::string kind;
        if (!isRecoverableTable(tableName, kind)) continue;

        char* quoted = sqlite3_mprintf("%w", tableName.c_str());
        if (!quoted) return false;
        const std::string query = "SELECT * FROM \"" + std::string(quoted) + "\" LIMIT " +
                                  std::to_string(kMaximumSqliteRowsPerTable);
        sqlite3_free(quoted);

        sqlite3_stmt* rawRows = nullptr;
        if (sqlite3_prepare_v2(connection.get(), query.c_str(), -1, &rawRows, nullptr) != SQLITE_OK) continue;
        std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> rows(rawRows, sqlite3_finalize);
        const int columns = sqlite3_column_count(rows.get());
        while (sqlite3_step(rows.get()) == SQLITE_ROW && recordCount < kMaximumSqliteRecords) {
            json row = json::object();
            bool sensitive = false;
            std::string recordKey;
            for (int index = 0; index < columns; ++index) {
                const char* name = sqlite3_column_name(rows.get(), index);
                if (!name) continue;
                std::string value = sqliteValue(rows.get(), index);
                if (value.size() > kMaximumRecoveredValueBytes) value.resize(kMaximumRecoveredValueBytes);
                row[name] = value;
                if (recordKey.empty() && (std::string(name) == "_id" || std::string(name) == "id")) {
                    recordKey = value;
                }
                sensitive = sensitive || isSensitiveKey(name);
            }
            if (!database.insertWechatSqliteRecord(sourcePath, tableName, recordKey, row.dump(), kind,
                                                    sensitive)) {
                return false;
            }
            ++recordCount;
        }
    }
    return true;
}

uint64_t parseXlogTime(const std::string& sourcePath) {
    // WeChat Xlog files are commonly named <YYYY>-<MM>-<DD>.<HH>.wxlog. Accept
    // dotted or dashed date fragments for robustness.
    static const std::regex datePattern(R"((\d{4})[-.](\d{2})[-.](\d{2})[-.](\d{2}))");
    std::smatch match;
    if (!std::regex_search(sourcePath, match, datePattern)) return 0;
    std::tm value{};
    value.tm_year = std::stoi(match[1]) - 1900;
    value.tm_mon = std::stoi(match[2]) - 1;
    value.tm_mday = std::stoi(match[3]);
    value.tm_hour = std::stoi(match[4]);
#if defined(_WIN32)
    return static_cast<uint64_t>(_mkgmtime(&value));
#else
    return static_cast<uint64_t>(timegm(&value));
#endif
}

}  // namespace

bool persistWechatBackupAnalysis(MiuiBackupExtractor& src, AndroidAnalysisDatabase& database) {
    bool success = true;
    size_t sequence = 0;
    src.enumerateEntryDetails([&](const std::string& memberName, const std::string& bakFile,
                                  const TarEntry& entry) {
        if (!success || !startsWith(memberName, "apps/com.tencent.mm/")) return;
        if (!entry.isRegularFile()) return;

        ArtifactInfo artifact = classifyArtifact(memberName);
        std::string hash;
        fs::path staged;
        // SQLCipher primary databases can be hundreds of megabytes; leave them
        // inventoried-as-recognized rather than staging.
        const bool stageable = entry.size <= kMaximumArtifactBytes &&
            (artifact.category == "shared_pref" || artifact.category == "mmkv" ||
             (artifact.category == "database" && artifact.format != "sqlcipher") ||
             artifact.category == "xlog");

        if (stageable) {
            staged = src.temporaryRoot() / ("wechat-artifact-" + std::to_string(sequence++));
            if (!stageMember(src, memberName, staged)) {
                artifact.parseStatus = "parse_error";
                artifact.summary = "Failed to stage WeChat artifact";
            } else {
                hash = sha256(staged);
                if (artifact.category == "shared_pref" && artifact.format == "xml") {
                    artifact.parseStatus = parseSharedPreferences(staged, memberName, database)
                        ? "parsed" : "parse_error";
                } else if (artifact.category == "mmkv" && artifact.format == "mmkv") {
                    // WeChat's MMKV is a protobuf-style appender log guarded by a
                    // CRC sidecar; treat presence as evidence rather than
                    // inferring printable key/value pairs.
                    artifact.parseStatus = "recognized";
                    artifact.summary = "WeChat MMKV store recognized; decoder and CRC verification required";
                } else if (artifact.category == "database") {
                    if (isSqlite(staged)) {
                        artifact.format = "sqlite";
                        size_t recoveredRecords = 0;
                        if (!recoverSqliteRecords(staged, memberName, database, recoveredRecords)) {
                            artifact.parseStatus = "parse_error";
                        } else if (recoveredRecords == 0) {
                            artifact.parseStatus = "recognized";
                            artifact.summary = "SQLite schema indexed; no WeChat allowlisted table matched";
                        } else {
                            artifact.parseStatus = "parsed";
                            artifact.summary = "SQLite records recovered from WeChat allowlisted tables";
                        }
                    } else {
                        artifact.parseStatus = "recognized";
                    }
                } else if (artifact.category == "xlog") {
                    const uint64_t eventTime = parseXlogTime(memberName);
                    artifact.parseStatus = "recognized";
                    if (eventTime != 0 && !database.insertWechatLogEvent(
                            memberName, eventTime, "file", "WeChatXlog",
                            "WeChatXlog file present; payload requires a WeChat proprietary decoder.",
                            "recognized", false)) {
                        success = false;
                    }
                }
                std::error_code error;
                fs::remove(staged, error);
            }
        } else if (artifact.category == "database" && artifact.format == "sqlcipher") {
            // Inventory-only: the dedicated EnMicroMsg.db decryption pipeline
            // owns content recovery; record it as locked/recognized evidence.
            artifact.parseStatus = "recognized";
        } else if (entry.size > kMaximumArtifactBytes &&
                   (artifact.category == "database" || artifact.category == "mmkv" ||
                    artifact.category == "shared_pref")) {
            artifact.parseStatus = "limit_exceeded";
            artifact.summary += "; exceeds WeChat parser staging limit";
        }

        const std::string typeFlag(1, entry.typeFlag == '\0' ? '0' : entry.typeFlag);
        if (!database.insertWechatArtifactInventory(kWechatPackage, memberName, bakFile,
                                                     artifact.category, artifact.format, entry.size,
                                                     entry.modifiedTime, typeFlag, artifact.parseStatus,
                                                     artifact.summary, hash)) {
            success = false;
        }
    });
    return success;
}
