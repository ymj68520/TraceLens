#include "ThunderForensicCaseDatabase.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileEvidenceAnalysis.h"
#include "ThunderForensicBackupExtractor.h"

#include <sqlite3.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

constexpr const char* kParserVersion = "thunderforensic-v2";
constexpr std::size_t kMaxDatabases = 512;
constexpr std::size_t kMaxTablesPerDatabase = 8;
constexpr int kProgressEveryInstructions = 1000;
constexpr int kInstructionBudget = 20000000;

std::string serialized(const json& value) {
    return value.dump(-1, ' ', false, json::error_handler_t::replace);
}

std::string toLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

bool hasPrefix(const std::string& value, const std::string& prefix) {
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}

std::string columnText(sqlite3_stmt* statement, int index) {
    const unsigned char* text = sqlite3_column_text(statement, index);
    if (!text) return {};
    return std::string(reinterpret_cast<const char*>(text),
                       static_cast<std::size_t>(sqlite3_column_bytes(statement, index)));
}

// The case databases store values as TEXT (occasionally BLOB for non-UTF-8
// contact names); normalize without losing bytes.
std::string columnValue(sqlite3_stmt* statement, int index) {
    const int type = sqlite3_column_type(statement, index);
    if (type == SQLITE_NULL) return {};
    if (type == SQLITE_BLOB) {
        const auto* data = static_cast<const char*>(sqlite3_column_blob(statement, index));
        const auto size = static_cast<std::size_t>(sqlite3_column_bytes(statement, index));
        return data ? std::string(data, size) : std::string{};
    }
    if (type == SQLITE_INTEGER)
        return std::to_string(sqlite3_column_int64(statement, index));
    if (type == SQLITE_FLOAT) {
        std::ostringstream out;
        out << sqlite3_column_double(statement, index);
        return out.str();
    }
    return columnText(statement, index);
}

bool isUtf8(const std::string& value) {
    std::size_t i = 0;
    while (i < value.size()) {
        const unsigned char c = static_cast<unsigned char>(value[i]);
        std::size_t extra = 0;
        if (c < 0x80) extra = 0;
        else if ((c & 0xE0) == 0xC0) extra = 1;
        else if ((c & 0xF0) == 0xE0) extra = 2;
        else if ((c & 0xF8) == 0xF0) extra = 3;
        else return false;
        if (i + extra >= value.size() && extra > 0) return false;
        for (std::size_t k = 1; k <= extra; ++k) {
            if (i + k >= value.size()) return false;
            if ((static_cast<unsigned char>(value[i + k]) & 0xC0) != 0x80) return false;
        }
        i += extra + 1;
    }
    return true;
}

std::string safeText(const std::string& value) {
    return isUtf8(value) ? value : std::string{};
}

// ThunderForensic serializes timestamps as local-time strings without a zone
// ("2019-04-23 03:49:54"). Parsing them as UTC would invent a timezone, so the
// raw text is kept and only converted when the value is unambiguously numeric.
std::optional<std::int64_t> parseEpoch(const std::string& raw) {
    if (raw.empty()) return std::nullopt;
    std::int64_t value = 0;
    std::size_t consumed = 0;
    try {
        value = std::stoll(raw, &consumed);
    } catch (const std::exception&) {
        return std::nullopt;
    }
    if (consumed != raw.size() || value <= 0) return std::nullopt;
    if (value > 1000000000000000LL) return std::nullopt;
    if (value > 100000000000LL) return value / 1000;         // epoch ms
    if (value > 1000000000LL) return value;                  // epoch s
    return std::nullopt;
}

struct CaseKindRule {
    const char* suffix;        // evidence_1_<suffix>
    const char* kind;
    const char* timestamp;     // preferred timestamp column
    const char* secondaryTimestamp;
};

// One rule per evidence_<n>_<suffix> table family observed across the OPPO /
// OnePlus / vivo samples. Unknown suffixes fall back to the table name, so a
// new vendor build still lands in mobile_artifacts.
const std::array<CaseKindRule, 26>& caseKindRules() {
    static const std::array<CaseKindRule, 26> rules = {{
        {"application", "application", "install_time", "last_update_time"},
        {"datatraffic", "app_traffic", "time", nullptr},
        {"deviceinfo", "device_info", nullptr, nullptr},
        {"sms", "sms", "time", "sent_time"},
        {"calllog", "call_log", "time", nullptr},
        {"contact", "contact", nullptr, nullptr},
        {"wifi", "wifi", "last_joined", "first_join_time"},
        {"bluetooth", "bluetooth", "last_joined", "first_joined"},
        {"siminfo", "sim_info", "last_update_time", nullptr},
        {"imageandvideoinfo", "media", "create_time", "modify_time"},
        {"mediainfo", "media", "create_time", "modify_time"},
        {"immsginfo", "im_message", "time", nullptr},
        {"imuserinfo", "im_contact", "register_time", "last_active_time"},
        {"imfavinfo", "im_favorite", "time", nullptr},
        {"imsnsinfo", "im_social_post", "time", nullptr},
        {"imweiboinfo", "im_weibo_post", "time", nullptr},
        {"troopgroupinfo", "im_group", "create_time", "join_time"},
        {"troopfileinfo", "im_group_file", "time", "local_modify_time"},
        {"calendar", "calendar_event", "start_time", "create_time"},
        {"webhistory", "web_history", "last_visit_time", "created_time"},
        {"searchhistory", "search_history", "time", nullptr},
        {"webbookmark", "web_bookmark", "added_time", "modified_time"},
        {"account", "account", "creation_time", "modify_time"},
        {"mail", "mail", "sent_time", "recieved_time"},
        {"downloadfile", "download", "creat_time", "finish_time"},
        {"file", "file_inventory", "mtime", "ctime"},
    }};
    return rules;
}

const CaseKindRule* ruleFor(const std::string& suffix) {
    for (const auto& rule : caseKindRules()) {
        if (suffix == rule.suffix) return &rule;
    }
    return nullptr;
}

// Only the tables an analyst would query first are projected into the standard
// tables; everything else stays in mobile_artifacts.
struct StandardProjection {
    bool sms = false;
    bool call = false;
    bool contact = false;
    bool wifi = false;
    bool app = false;
    bool sim = false;
    bool media = false;
};

StandardProjection projectionFor(const std::string& suffix) {
    StandardProjection projection;
    if (suffix == "sms") projection.sms = true;
    else if (suffix == "calllog") projection.call = true;
    else if (suffix == "contact") projection.contact = true;
    else if (suffix == "wifi") projection.wifi = true;
    else if (suffix == "application") projection.app = true;
    else if (suffix == "siminfo") projection.sim = true;
    else if (suffix == "imageandvideoinfo" || suffix == "mediainfo") projection.media = true;
    return projection;
}

std::string pick(const std::map<std::string, std::string>& row,
                 std::initializer_list<const char*> keys) {
    for (const char* key : keys) {
        const auto found = row.find(key);
        if (found != row.end() && !found->second.empty()) return found->second;
    }
    return {};
}

class Statement {
public:
    Statement(sqlite3* db, const std::string& sql) {
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &statement_, nullptr) != SQLITE_OK)
            throw std::runtime_error(sqlite3_errmsg(db));
    }
    ~Statement() { if (statement_) sqlite3_finalize(statement_); }
    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;
    sqlite3_stmt* get() const { return statement_; }

private:
    sqlite3_stmt* statement_ = nullptr;
};

std::string quoteIdentifier(const std::string& identifier) {
    std::string out = "\"";
    for (char c : identifier) {
        if (c == '"') out += "\"\"";
        else out += c;
    }
    out += "\"";
    return out;
}

// mobile_artifacts is written through the result database handle so the case
// rows share the exact schema the tar adapter uses (including the JSON
// source_key the artifact reader contract requires).
bool insertCaseArtifact(sqlite3* dest, const std::string& kind,
                        const std::string& sourcePath, const std::string& sourceTable,
                        const std::string& sourceKey, const std::string& recordJson,
                        const std::string& timestampRaw,
                        const std::optional<std::int64_t>& timestampSeconds,
                        const std::string& relatedPath, const std::string& relatedStatus) {
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(dest,
                           "INSERT OR REPLACE INTO mobile_artifacts(kind,package_name,"
                           "app_index,source_path,source_table,source_key,record_json,"
                           "timestamp_raw,time_unit,timestamp_seconds,parser_version,"
                           "related_path,related_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           -1, &statement, nullptr) != SQLITE_OK)
        return false;
    sqlite3_bind_text(statement, 1, kind.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(statement, 3, 0);
    sqlite3_bind_text(statement, 4, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 5, sourceTable.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 6, sourceKey.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 7, recordJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 8, timestampRaw.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 9, timestampSeconds ? "s" : "", -1, SQLITE_TRANSIENT);
    if (timestampSeconds) sqlite3_bind_int64(statement, 10, *timestampSeconds);
    else sqlite3_bind_null(statement, 10);
    sqlite3_bind_text(statement, 11, kParserVersion, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 12, relatedPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 13, relatedStatus.c_str(), -1, SQLITE_TRANSIENT);
    const bool ok = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return ok;
}


}  // namespace

ThunderForensicCaseStats buildPackageFromCaseDatabases(
    const fs::path& projectRoot, mobile_evidence::Package& package,
    const std::map<std::string, std::set<std::string>>& coveredMembers,
    std::vector<AndroidSourceProvenance>* provenanceOut,
    std::size_t maxRowsPerDatabase) {
    using mobile_evidence::Record;
    using mobile_evidence::Coverage;
    using mobile_evidence::kind::kGeneric;

    ThunderForensicCaseStats stats;
    if (projectRoot.empty()) return stats;
    std::error_code ec;
    const fs::path dataDir = projectRoot / "data";
    if (!fs::is_directory(dataDir, ec) || fs::is_symlink(fs::symlink_status(dataDir, ec)))
        return stats;

    // Case-database coverage keeps the published ThunderForensic vocabulary
    // (parsed/empty/PARTIAL/ERROR/PARTIAL); downstream filters on it verbatim.
    const auto addCoverage = [&package](const std::string& artifactKind,
                                        const std::string& sourcePath,
                                        const std::string& state,
                                        const std::string& detail,
                                        std::uint64_t count = 0) {
        Coverage entry;
        entry.artifactKind = artifactKind;
        entry.sourcePath = sourcePath;
        entry.status = state;
        entry.nativeStatus = state;
        entry.detail = detail;
        entry.recordCount = count;
        package.coverage.push_back(std::move(entry));
    };
    const auto addStandardRecord = [&package](const std::string& recordKind,
                                              const std::string& payloadJson,
                                              const std::string& sourcePath,
                                              const std::string& sourceTable,
                                              const std::string& sourceKey,
                                              const std::string& rawJson) {
        Record record;
        record.kind = recordKind;
        record.sourcePath = sourcePath;
        record.sourceTable = sourceTable;
        record.sourceKey = sourceKey;
        record.rawJson = rawJson;
        record.payloadJson = payloadJson;
        record.parserVersion = kParserVersion;
        package.records.push_back(std::move(record));
    };

    std::vector<fs::path> databases;
    for (const auto& item : fs::directory_iterator(dataDir, ec)) {
        std::error_code itemEc;
        if (!fs::is_regular_file(item.path(), itemEc)) continue;
        if (!hasPrefix(item.path().filename().string(), "evidence_")) continue;
        if (fs::is_symlink(fs::symlink_status(item.path(), itemEc))) continue;
        databases.push_back(item.path());
        if (databases.size() >= kMaxDatabases) break;
    }
    std::sort(databases.begin(), databases.end());
    if (databases.empty()) {
        addCoverage("case_database", "<data>", "not_found",
                    "no data/evidence_* case database in the project folder");
        return stats;
    }
    stats.found = true;

    std::set<std::string> wifiSeen;
    std::size_t totalRows = 0;

    for (const auto& path : databases) {
        const std::string filename = path.filename().string();
        // evidence_<n>_<suffix>
        std::string suffix;
        const std::size_t first = filename.find('_');
        if (first != std::string::npos) {
            const std::size_t second = filename.find('_', first + 1);
            if (second != std::string::npos) suffix = filename.substr(second + 1);
        }
        if (suffix.empty()) {
            addCoverage("case_database", filename, "UNSUPPORTED",
                        "unrecognized case database name");
            continue;
        }
        const CaseKindRule* rule = ruleFor(suffix);
        const std::string kind =
            rule ? std::string(rule->kind) : "case_" + toLower(suffix);
        const auto projection = projectionFor(suffix);
        const auto covered = coveredMembers.find(kind);

        std::array<char, 16> magic{};
        {
            std::ifstream probe(path, std::ios::binary);
            if (!probe) {
                addCoverage(kind, filename, "EXTRACT_FAILED",
                            "case database could not be opened");
                continue;
            }
            probe.read(magic.data(), magic.size());
        }
        if (std::string(magic.data(), 16) != std::string("SQLite format 3\0", 16)) {
            addCoverage(kind, filename, "UNSUPPORTED",
                        "non-SQLite header; not proof of encryption");
            continue;
        }

        sqlite3* source = nullptr;
        if (sqlite3_open_v2(path.string().c_str(), &source,
                            SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX, nullptr) != SQLITE_OK) {
            if (source) sqlite3_close(source);
            addCoverage(kind, filename, "ERROR", "sqlite_open_failed");
            continue;
        }
        struct Close {
            sqlite3* db;
            ~Close() { sqlite3_close(db); }
        } close{source};
        sqlite3_exec(source, "PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;",
                     nullptr, nullptr, nullptr);
        sqlite3_limit(source, SQLITE_LIMIT_LENGTH, 8 << 20);
        sqlite3_limit(source, SQLITE_LIMIT_COLUMN, 2048);
        int instructions = kInstructionBudget;
        auto budget = [](void* data) {
            auto* remaining = static_cast<int*>(data);
            if (--*remaining <= 0) return 1;
            return 0;
        };
        sqlite3_progress_handler(source, kProgressEveryInstructions, budget, &instructions);

        // thunderforensic-v2 keeps exactly one table per case database; if a
        // build ever ships more, read the first few and note the rest.
        std::vector<std::string> tables;
        try {
            Statement query(source,
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 9");
            int rc;
            while ((rc = sqlite3_step(query.get())) == SQLITE_ROW) {
                tables.push_back(columnText(query.get(), 0));
                if (tables.size() > kMaxTablesPerDatabase) break;
            }
            if (rc != SQLITE_DONE && rc != SQLITE_ROW)
                throw std::runtime_error("schema_read_failed");
        } catch (const std::exception&) {
            addCoverage(kind, filename, "ERROR", "schema_read_failed");
            continue;
        }
        if (tables.empty()) {
            addCoverage(kind, filename, "empty", "no user table");
            continue;
        }
        if (tables.size() > kMaxTablesPerDatabase) {
            tables.resize(kMaxTablesPerDatabase);
            stats.truncatedDatabases++;
        }

        ++stats.databases;
        std::size_t databaseRows = 0;
        std::size_t databaseStandardRows = 0;
        bool truncated = false;
        std::string failure;
        for (const std::string& table : tables) {
            std::vector<std::string> columns;
            try {
                Statement info(source, "PRAGMA table_info(" + quoteIdentifier(table) + ")");
                while (sqlite3_step(info.get()) == SQLITE_ROW)
                    columns.push_back(columnText(info.get(), 1));
            } catch (const std::exception&) {
                failure = "column_read_failed";
                continue;
            }
            if (columns.empty()) {
                failure = "no_columns";
                continue;
            }
            std::string select = "SELECT ";
            for (std::size_t i = 0; i < columns.size(); ++i) {
                if (i) select += ",";
                select += quoteIdentifier(columns[i]);
            }
            select += " FROM " + quoteIdentifier(table);
            std::size_t tableRows = 0;
            try {
                Statement rows(source, select);
                int rc;
                while ((rc = sqlite3_step(rows.get())) == SQLITE_ROW) {
                    if (databaseRows >= maxRowsPerDatabase) {
                        truncated = true;
                        break;
                    }
                    std::map<std::string, std::string> row;
                    json record = json::object();
                    for (std::size_t i = 0; i < columns.size(); ++i) {
                        std::string value = columnValue(rows.get(), static_cast<int>(i));
                        const std::string text = safeText(value);
                        if (text.empty() && !value.empty()) {
                            record[columns[i]] = {{"encoding", "non_utf8"},
                                                  {"bytes", value.size()}};
                            continue;
                        }
                        if (!text.empty()) {
                            row[columns[i]] = text;
                            record[columns[i]] = text;
                        }
                    }
                    const std::size_t index = tableRows++;
                    if (row.empty()) continue;
                    // Case rows name the container member they came from. When
                    // the tar layer already parsed that member, this row was
                    // already imported; re-adding it would double-count the
                    // same extraction record. Rows with no origin at all
                    // (vivo's 3615 provider contacts) are the same artifact
                    // family flattened without provenance, so they are skipped
                    // too once that family came from the container.
                    if (covered != coveredMembers.end()) {
                        const std::string origin = pick(row, {"src_file_path"});
                        const std::size_t slash = origin.find('/');
                        const std::string member = slash == std::string::npos
                            ? origin : origin.substr(slash + 1);
                        const bool sameMember = origin.empty() ||
                                                covered->second.count(origin) ||
                                                covered->second.count(member);
                        if (sameMember) {
                            ++stats.skippedDuplicateRows;
                            ++tableRows;
                            continue;
                        }
                    }
                    // Deleted rows are kept and flagged: "delete"=1 in these
                    // databases means the source record was marked deleted, not
                    // that the tool dropped it.
                    record["thunderforensic_delete"] = pick(row, {"delete"});
                    record["thunderforensic_source"] = pick(row, {"src_file_path"});
                    const std::string rawTime = rule && rule->timestamp
                        ? pick(row, {rule->timestamp})
                        : std::string{};
                    const std::string rawTime2 = rule && rule->secondaryTimestamp
                        ? pick(row, {rule->secondaryTimestamp}) : std::string{};
                    std::string timestampRaw = rawTime.empty() ? rawTime2 : rawTime;
                    const auto epoch = parseEpoch(timestampRaw);
                    const std::string recordKey =
                        serialized(json{{"database", filename}, {"table", table},
                                        {"row", index}});

                    std::string relatedPath;
                    std::string relatedStatus;
                    if (projection.media) {
                        const std::string mobile = pick(row, {"mobile_path", "raw_path",
                                                              "local_path", "static_path"});
                        if (!mobile.empty()) {
                            relatedPath = mobile;
                            relatedStatus = "reported_by_case_database";
                        }
                    }

                    Record artifact;
                    artifact.kind = kGeneric;
                    artifact.nativeKind = kind;
                    artifact.mobileArtifact = true;
                    artifact.sourcePath = filename;
                    artifact.sourceTable = table;
                    artifact.sourceKey = recordKey;
                    artifact.rawJson = serialized(record);
                    artifact.timestampRaw = timestampRaw;
                    if (epoch) {
                        artifact.timestampUnit = mobile_evidence::time_unit::kSeconds;
                        artifact.timestampSeconds = *epoch;
                    }
                    artifact.parserVersion = kParserVersion;
                    artifact.relatedPath = relatedPath;
                    artifact.relatedStatus = relatedStatus;
                    package.records.push_back(std::move(artifact));
                    ++databaseRows;
                    ++totalRows;

                    if (projection.app) {
                        const std::string packageName = pick(row, {"package_name"});
                        if (!packageName.empty()) {
                            addStandardRecord(
                                mobile_evidence::kind::kInstalledApp,
                                serialized(json{
                                    {"package_name", packageName},
                                    {"display_name", pick(row, {"app_name"})},
                                    {"version_code", pick(row, {"version_code"})},
                                    {"version_name", pick(row, {"version_name"})},
                                    {"data_size", "0"},
                                    {"sd_size", "0"},
                                    {"bak_type", "0"},
                                }),
                                filename, table, packageName, serialized(record));
                            ++databaseStandardRows;
                        }
                    } else if (projection.sms) {
                        const std::string address = pick(row, {"phone_number"});
                        const std::string body = pick(row, {"content"});
                        if (!address.empty() || !body.empty()) {
                            Record sms;
                            sms.kind = mobile_evidence::kind::kSms;
                            sms.sourcePath = filename;
                            sms.sourceTable = table;
                            sms.sourceKey = recordKey;
                            sms.rawJson = serialized(record);
                            sms.payloadJson = serialized(json{
                                {"address", address},
                                {"body", body},
                                {"date", epoch ? std::to_string(*epoch) : std::string{}},
                                {"type", pick(row, {"type"})},
                            });
                            if (epoch) {
                                sms.timestampUnit = mobile_evidence::time_unit::kSeconds;
                                sms.timestampSeconds = *epoch;
                            }
                            sms.parserVersion = kParserVersion;
                            package.records.push_back(std::move(sms));
                            ++databaseStandardRows;
                        }
                    } else if (projection.call) {
                        const std::string number = pick(row, {"phone_number"});
                        if (!number.empty()) {
                            Record call;
                            call.kind = mobile_evidence::kind::kCallLog;
                            call.sourcePath = filename;
                            call.sourceTable = table;
                            call.sourceKey = recordKey;
                            call.rawJson = serialized(record);
                            call.payloadJson = serialized(json{
                                {"number", number},
                                {"date", epoch ? std::to_string(*epoch) : std::string{}},
                                {"duration_seconds", pick(row, {"duration"})},
                                {"type", pick(row, {"type"})},
                            });
                            if (epoch) {
                                call.timestampUnit = mobile_evidence::time_unit::kSeconds;
                                call.timestampSeconds = *epoch;
                            }
                            call.parserVersion = kParserVersion;
                            package.records.push_back(std::move(call));
                            ++databaseStandardRows;
                        }
                    } else if (projection.contact) {
                        Record contact;
                        contact.kind = mobile_evidence::kind::kContact;
                        contact.sourcePath = filename;
                        contact.sourceTable = table;
                        contact.sourceKey = recordKey;
                        contact.rawJson = serialized(record);
                        contact.payloadJson = serialized(json{
                            {"display_name", pick(row, {"name", "nick_name"})},
                            {"phone_number", pick(row, {"phone_number"})},
                        });
                        contact.parserVersion = kParserVersion;
                        package.records.push_back(std::move(contact));
                        ++databaseStandardRows;
                    } else if (projection.wifi) {
                        std::string ssid = pick(row, {"ssid"});
                        if (ssid.size() >= 2 && ssid.front() == '"' && ssid.back() == '"')
                            ssid = ssid.substr(1, ssid.size() - 2);
                        if (!ssid.empty() && wifiSeen.insert(toLower(ssid)).second) {
                            Record wifi;
                            wifi.kind = mobile_evidence::kind::kWifiNetwork;
                            wifi.sourcePath = filename;
                            wifi.sourceTable = table;
                            wifi.sourceKey = recordKey;
                            wifi.rawJson = serialized(record);
                            wifi.payloadJson = serialized(json{
                                {"ssid", ssid},
                                {"pre_shared_key", pick(row, {"password"})},
                                {"key_mgmt", pick(row, {"key_type"})},
                            });
                            wifi.parserVersion = kParserVersion;
                            package.records.push_back(std::move(wifi));
                            ++databaseStandardRows;
                        }
                    } else if (projection.sim) {
                        for (const char* identifier : {"iccid", "imsi", "phonenumber"}) {
                            const std::string value = pick(row, {identifier});
                            if (value.empty()) continue;
                            Record identity;
                            identity.kind = mobile_evidence::kind::kDeviceIdentity;
                            identity.sourcePath = filename;
                            identity.sourceTable = table;
                            identity.sourceKey = std::string(identifier) + "|" + value;
                            identity.rawJson = serialized(record);
                            identity.payloadJson = serialized(json{
                                {"identifier_type", identifier},
                                {"value", value},
                            });
                            identity.parserVersion = kParserVersion;
                            package.records.push_back(std::move(identity));
                        }
                    }
                }
                if (rc != SQLITE_DONE && rc != SQLITE_ROW && !truncated)
                    failure = "row_read_failed";
            } catch (const std::exception&) {
                failure = "row_query_failed";
            }
            if (!failure.empty() || truncated) break;
        }

        std::string state = truncated ? "PARTIAL"
            : failure.empty() ? (databaseRows ? "parsed" : "empty")
                              : (databaseRows ? "PARTIAL" : "ERROR");
        std::string detail = "rows=" + std::to_string(databaseRows) +
                             "; standard_table_rows=" + std::to_string(databaseStandardRows) +
                             "; tables=" + std::to_string(tables.size());
        if (truncated)
            detail += "; truncated_at=" + std::to_string(maxRowsPerDatabase) + " (row limit)";
        if (!failure.empty()) detail += "; " + failure;
        addCoverage(kind, filename, state, detail, databaseRows);

        // Provenance: the case database is a parsed derivative of the
        // container, not the container itself, so it is recorded separately.
        if (provenanceOut) {
            AndroidSourceProvenance provenance;
            provenance.sourceContainer = path.string();
            provenance.containerSha256 = ThunderForensicBackupExtractor::sha256(path);
            provenance.sourceMemberPath = filename;
            provenance.normalizedAndroidPath = filename;
            provenance.memberSize = static_cast<std::size_t>(fs::file_size(path, ec));
            provenance.memberSha256 = provenance.containerSha256;
            provenance.adapterType = kThunderForensicSource;
            provenance.adapterVersion = kParserVersion;
            provenanceOut->push_back(std::move(provenance));
        }
        stats.rows += databaseRows;
    }

    addCoverage("case_database", "<data>", stats.rows ? "parsed" : "empty",
                "databases=" + std::to_string(stats.databases) +
                    "; rows=" + std::to_string(stats.rows) +
                    "; skipped_duplicate_rows=" + std::to_string(stats.skippedDuplicateRows) +
                    (stats.truncatedDatabases
                         ? "; truncated_databases=" + std::to_string(stats.truncatedDatabases)
                         : ""));
    return stats;
}

ThunderForensicCaseStats analyzeThunderForensicCaseDatabases(
    const fs::path& projectRoot, AndroidAnalysisDatabase& output,
    const std::map<std::string, std::set<std::string>>& coveredMembers,
    std::size_t maxRowsPerDatabase) {
    mobile_evidence::Package package;
    std::vector<AndroidSourceProvenance> provenance;
    const auto stats = buildPackageFromCaseDatabases(projectRoot, package,
                                                     coveredMembers, &provenance,
                                                     maxRowsPerDatabase);
    mobile_evidence::AnalysisOptions options;
    options.mirrorFiles = false;
    mobile_evidence::AnalysisResult result;
    if (!mobile_evidence::analyzePackage(package, output, options, result)) {
        return stats;
    }
    for (const auto& item : provenance) output.insertSourceProvenance(item);
    return stats;
}
