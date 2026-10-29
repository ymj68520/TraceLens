// MobileEvidenceHarmonyAdapter.cpp
// 鸿蒙已解密备份 → 统一取数包。
//
// 该文件持有鸿蒙的**唯一**解析路径：MobileEvidenceHarmonyAdapter.cpp 产出
// Package，HarmonyArtifactParsers.cpp 只负责把包写进 android.db。这样取数
// 规则不会在两条链路之间漂移。

#include "MobileEvidenceHarmonyAdapter.h"

#include "HarmonyBackupExtractor.h"
#include "MobileEvidencePackage.h"

#include <openssl/evp.h>

#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>
#include <sqlite3.h>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace mobile_evidence {
namespace {

using Connection = std::unique_ptr<sqlite3, decltype(&sqlite3_close)>;
using Statement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;

constexpr const char* kParserVersion = "harmony-decrypted-v1";

std::string quote(const std::string& s) {
    std::string out = "\"";
    for (char c : s) { out += c; if (c == '"') out += c; }
    return out + '"';
}

std::string text(sqlite3_stmt* s, int i) {
    const auto* p = sqlite3_column_text(s, i);
    return p ? reinterpret_cast<const char*>(p) : "";
}

Statement prepare(sqlite3* db, const std::string& sql) {
    sqlite3_stmt* s = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &s, nullptr) != SQLITE_OK)
        throw std::runtime_error(sqlite3_errmsg(db));
    return Statement(s, sqlite3_finalize);
}

std::string serialized(const json& j) {
    return j.dump(-1, ' ', false, json::error_handler_t::replace);
}

std::string scalar(const json& j, const char* key) {
    if (!j.contains(key) || j[key].is_null()) return {};
    return j[key].is_string() ? j[key].get<std::string>() : j[key].dump();
}

json rowJson(sqlite3_stmt* s) {
    json j = json::object();
    for (int i = 0; i < sqlite3_column_count(s); ++i) {
        const std::string name = sqlite3_column_name(s, i);
        switch (sqlite3_column_type(s, i)) {
            case SQLITE_NULL: j[name] = nullptr; break;
            case SQLITE_INTEGER: j[name] = sqlite3_column_int64(s, i); break;
            case SQLITE_FLOAT: j[name] = sqlite3_column_double(s, i); break;
            case SQLITE_BLOB:
                j[name] = {{"type", "blob"}, {"bytes", sqlite3_column_bytes(s, i)},
                           {"decoded", false}};
                break;
            default: j[name] = text(s, i); break;
        }
    }
    return j;
}

struct Rule { std::string table, kind, time; };

std::vector<Rule> rulesFor(const HarmonyBackupExtractor::Entry& e) {
    const auto name = fs::path(e.originalPath).filename().string();
    if (e.bundle == "com.huawei.hmos.calendardata" && name == "calendardata.db")
        return {{"Events", "calendar", "dtstart"}};
    if (e.bundle == "com.huawei.hmos.soundrecorder" && name == "recorderSound.db")
        return {{"normal_record_table", "recording", "date_added"}};
    if (e.bundle == "com.huawei.hmos.callrecorder" && name == "call_record.db")
        return {{"record_log", "call_recording", "date_added"}};
    if (e.bundle == "com.ohos.medialibrary.medialibrarydata" && name == "media_library.db")
        return {{"Photos", "media", "date_taken"}, {"Files", "media_file", "date_taken"}};
    if (e.bundle == "com.huawei.hmos.notepad" && name == "notepad.db")
        return {{"note", "note", "create_time"}, {"todo", "todo", "create_time"},
                {"content", "note_content", ""}};
    if (e.bundle == "org.b3log.siyuan.ho" && name == "siyuan.db")
        return {{"blocks", "note_block", "created"}};
    // Legacy migrated QQ data; NT/SQLCipher messages are inventoried separately.
    if (e.bundle == "com.tencent.mqq" && name.ends_with(".db") && name.size() > 3 &&
        name.substr(0, name.size() - 3).find_first_not_of("0123456789") == std::string::npos)
        return {{"Friends", "qq_contact", ""}, {"TroopInfoV2", "qq_group", ""},
                {"recent", "qq_recent", "lastmsgtime"}};
    return {};
}

bool isPrimaryDatabase(const std::string& path) {
    return path.ends_with(".db") || path.ends_with(".sqlite") ||
           path.ends_with(".sqlite3") || path.ends_with(".sqlitedb");
}

int budget(void* ptr) {
    auto& n = *static_cast<int*>(ptr);
    return --n <= 0;
}

void addCoverage(Package& package, const std::string& kind, const std::string& path,
                 const std::string& state, const std::string& detail,
                 std::uint64_t count = 0) {
    Coverage entry;
    entry.artifactKind = kind;
    entry.sourcePath = path;
    entry.status = state;
    entry.detail = detail;
    entry.recordCount = count;
    package.coverage.push_back(std::move(entry));
}

// 归一化 harmony 的时间单位到统一命名；未识别时保留原文。
std::string normalizeUnit(const std::string& unit) {
    if (unit == "epoch_ms") return time_unit::kMilliseconds;
    if (unit == "epoch_s") return time_unit::kSeconds;
    return unit;
}

}  // namespace

bool buildPackageFromHarmony(HarmonyBackupExtractor& source,
                             const fs::path& temporaryRoot,
                             const HarmonyAdapterOptions& options,
                             Package& out) {
    out = Package{};
    out.acquisition.adapterName = "harmony-backup";
    out.acquisition.adapterVersion = options.adapterVersion;
    out.acquisition.sourceType = "directory";

    const auto& meta = source.manifest();
    out.device.platform = "harmonyos";
    out.device.model = meta.value("device", "");
    out.device.deviceName = meta.value("device", "");
    out.device.extraJson = json{{"backup_version", meta.value("backup_version", "")}}.dump();

    // ---- 备份清单 ----
    out.manifest.present = true;
    out.manifest.targetTable = "mobile_backup_manifest";
    out.manifest.platform = "HarmonyOS";
    out.manifest.device = meta.value("device", "");
    out.manifest.backupVersion = meta.value("backup_version", "");
    out.manifest.backupTimeMs = meta.value("backup_time_ms", 0LL);
    out.manifest.moduleCount = static_cast<std::int64_t>(meta["modules"].size());
    out.manifest.manifestSha256 = meta.value("manifest_sha256", "");
    out.manifest.adapterVersion = options.adapterVersion;

    // ---- 模块（应用清单） ----
    std::uint64_t appRows = 0;
    for (const auto& app : meta["modules"]) {
        Record record;
        record.kind = kind::kInstalledApp;
        record.packageName = app.value("bundle", "");
        record.sourcePath = "<harmony-backup>";
        record.sourceTable = "modules";
        record.sourceKey = record.packageName;
        record.parserVersion = options.adapterVersion;
        record.rawJson = serialized(app);
        record.payloadJson = json{
            {"package_name", app.value("bundle", "")},
            {"display_name", app.value("name", "")},
            {"version_name", app.value("version", "")},
            {"version_code", std::to_string(app.value("version_code", 0LL))},
            {"data_size", std::to_string(app.value("declared_size", 0LL))},
            {"sd_size", "0"},
            {"bak_type", "0"},
            {"app_index", app.value("appIndex", 0)},
        }.dump();
        out.records.push_back(std::move(record));
        ++appRows;
    }
    addCoverage(out, kind::kInstalledApp, "<harmony-backup>", status::kParsed,
                "backup module list", appRows);

    for (const auto& c : source.coverage()) {
        addCoverage(out, "backup_module", c.value("path", ""), c.value("status", ""),
                    c.value("detail", ""));
    }

    std::size_t serial = 0;
    std::uint64_t totalRows = 0;

    for (const auto& [path, entry] : source.entries()) {
        if (!isPrimaryDatabase(path)) continue;
        if (entry.size > (256ULL << 20)) {
            addCoverage(out, "database", path, status::kUnsupported, "database_size_limit");
            continue;
        }
        const auto local = temporaryRoot / ("harmony-db-" + std::to_string(++serial) + ".db");
        struct Cleanup {
            fs::path p;
            ~Cleanup() {
                for (const char* s : {"", "-wal", "-shm", "-journal"}) {
                    std::error_code ec;
                    fs::remove(p.string() + s, ec);
                }
            }
        } cleanup{local};

        if (!source.extractFileByPath(path, local.string())) {
            if (source.error() == "CANCELLED" || source.error().starts_with("EVIDENCE_CHANGED"))
                throw std::runtime_error(source.error());
            addCoverage(out, "database", path, status::kFailed, source.error());
            continue;
        }

        std::array<char, 16> magic{};
        std::ifstream probe(local, std::ios::binary);
        probe.read(magic.data(), magic.size());
        probe.close();
        if (std::string(magic.data(), 16) != std::string("SQLite format 3\0", 16)) {
            const std::string state = std::string(magic.data(), 7) == "unqlite"
                ? "unsupported_format" : "encrypted_or_unsupported";
            Record inventory;
            inventory.kind = kind::kDatabaseTable;
            inventory.packageName = entry.bundle;
            inventory.appIndex = entry.appIndex;
            inventory.sourcePath = path;
            inventory.databasePath = path;
            inventory.databaseColumnsJson = "[]";
            inventory.databaseOpenStatus = state;
            inventory.status = status::kLocked;
            inventory.parserVersion = options.adapterVersion;
            out.records.push_back(std::move(inventory));
            addCoverage(out, "database", path, status::kUnsupported,
                        state + "; non-SQLite header is not proof of encryption");
            continue;
        }

        bool sidecarsOk = true;
        for (const char* suffix : {"-wal", "-shm", "-journal"}) {
            auto side = source.entries().find(path + suffix);
            if (side == source.entries().end()) continue;
            if (side->second.size > (256ULL << 20) ||
                !source.extractFileByPath(path + suffix, local.string() + suffix))
                sidecarsOk = false;
        }
        if (!sidecarsOk) {
            if (source.error() == "CANCELLED" || source.error().starts_with("EVIDENCE_CHANGED"))
                throw std::runtime_error(source.error());
            addCoverage(out, "database", path, status::kFailed, "incomplete_sqlite_bundle");
            continue;
        }

        sqlite3* raw = nullptr;
        int rc = sqlite3_open_v2(local.string().c_str(), &raw, SQLITE_OPEN_READONLY, nullptr);
        Connection db(raw, sqlite3_close);
        if (rc != SQLITE_OK) {
            addCoverage(out, "database", path, "ERROR", "sqlite_open_failed");
            continue;
        }
        sqlite3_exec(db.get(), "PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;",
                     nullptr, nullptr, nullptr);
        sqlite3_limit(db.get(), SQLITE_LIMIT_LENGTH, 8 << 20);
        sqlite3_limit(db.get(), SQLITE_LIMIT_COLUMN, 2048);
        int instructions = 20000;
        sqlite3_progress_handler(db.get(), 1000, budget, &instructions);

        try {
            auto tables = prepare(db.get(),
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 10001");
            std::set<std::string> names;
            std::size_t unavailableTables = 0;
            while ((rc = sqlite3_step(tables.get())) == SQLITE_ROW) {
                const auto table = text(tables.get(), 0);
                if (names.size() >= 10000) throw std::runtime_error("table_limit");
                names.insert(table);
                try {
                    json cols = json::array();
                    auto cs = prepare(db.get(), "PRAGMA table_info(" + quote(table) + ")");
                    while (sqlite3_step(cs.get()) == SQLITE_ROW) cols.push_back(text(cs.get(), 1));
                    auto count = prepare(db.get(), "SELECT COUNT(*) FROM " + quote(table));
                    if (sqlite3_step(count.get()) != SQLITE_ROW)
                        throw std::runtime_error("inventory_query_limit_or_error");

                    Record inventory;
                    inventory.kind = kind::kDatabaseTable;
                    inventory.packageName = entry.bundle;
                    inventory.appIndex = entry.appIndex;
                    inventory.sourcePath = path;
                    inventory.databasePath = path;
                    inventory.databaseTable = table;
                    inventory.databaseColumnsJson = serialized(cols);
                    inventory.databaseOpenStatus = "readable";
                    inventory.databaseRowCount = static_cast<std::uint64_t>(
                        sqlite3_column_int64(count.get(), 0));
                    inventory.parserVersion = options.adapterVersion;
                    out.records.push_back(std::move(inventory));
                } catch (const std::exception& ex) {
                    ++unavailableTables;
                    // Missing FTS modules/custom collations affect an index, not
                    // necessarily the ordinary business tables in the same DB.
                    Record inventory;
                    inventory.kind = kind::kDatabaseTable;
                    inventory.packageName = entry.bundle;
                    inventory.appIndex = entry.appIndex;
                    inventory.sourcePath = path;
                    inventory.databasePath = path;
                    inventory.databaseTable = table;
                    inventory.databaseColumnsJson = serialized(json{{"error", ex.what()}});
                    inventory.databaseOpenStatus = "unsupported_table";
                    inventory.status = status::kUnsupported;
                    inventory.parserVersion = options.adapterVersion;
                    out.records.push_back(std::move(inventory));
                }
            }
            if (rc != SQLITE_DONE) throw std::runtime_error("schema_read_failed");

            addCoverage(out, "database", path,
                        unavailableTables ? status::kPartial : status::kParsed,
                        "schema_inventory; unavailable_tables=" +
                            std::to_string(unavailableTables) +
                            "; business_semantics_separately_reported");

            const auto dbHash = HarmonyBackupExtractor::sha256(local);
            const auto wal = fs::path(local.string() + "-wal");
            const auto walHash = fs::exists(wal) ? HarmonyBackupExtractor::sha256(wal) : "";

            for (const auto& rule : rulesFor(entry)) {
                if (!names.count(rule.table)) {
                    addCoverage(out, rule.kind, path, status::kUnsupported,
                                "expected_table_missing: " + rule.table);
                    continue;
                }
                auto columns = prepare(db.get(), "PRAGMA table_info(" + quote(rule.table) + ")");
                std::vector<std::string> keys;
                while (sqlite3_step(columns.get()) == SQLITE_ROW)
                    if (sqlite3_column_int(columns.get(), 5)) keys.push_back(text(columns.get(), 1));

                std::string select = keys.empty()
                    ? "SELECT rowid AS __source_rowid__,* FROM " : "SELECT * FROM ";
                auto rows = prepare(db.get(), select + quote(rule.table) + " LIMIT 50001");
                std::size_t parsed = 0;
                while ((rc = sqlite3_step(rows.get())) == SQLITE_ROW) {
                    if (parsed >= 50000 || totalRows >= 200000)
                        throw std::runtime_error("artifact_row_limit");

                    auto record = rowJson(rows.get());
                    json key = json::object();
                    if (keys.empty()) key["rowid"] = record["__source_rowid__"];
                    else for (const auto& k : keys) key[k] = record[k];

                    auto rawTime = rule.time.empty() ? "" : scalar(record, rule.time.c_str());
                    std::string unit = "unknown";
                    std::int64_t seconds = 0;
                    if (rule.kind == "note_block") unit = "local_datetime_timezone_unknown";
                    else if (!rawTime.empty()) {
                        try {
                            std::size_t end = 0;
                            auto n = std::stoll(rawTime, &end);
                            if (end != rawTime.size()) throw std::runtime_error("not_numeric");
                            if (n >= 1000000000000LL && n < 4102444800000LL) {
                                seconds = n / 1000;
                                unit = "epoch_ms";
                            } else if (n >= 1000000000LL && n < 4102444800LL) {
                                seconds = n;
                                unit = "epoch_s";
                            }
                        } catch (...) {}
                    }

                    Record artifact;
                    artifact.kind = kind::kGeneric;
                    artifact.nativeKind = rule.kind;
                    artifact.mobileArtifact = true;
                    artifact.packageName = entry.bundle;
                    artifact.appIndex = entry.appIndex;
                    artifact.sourcePath = path;
                    artifact.sourceTable = rule.table;
                    artifact.sourceKey = serialized(key);
                    artifact.rawJson = serialized(record);
                    artifact.timestampRaw = rawTime;
                    artifact.timestampUnit = normalizeUnit(unit);
                    if (seconds) artifact.timestampSeconds = seconds;
                    artifact.sourceSha256 = dbHash;
                    artifact.sourceWalSha256 = walHash;
                    artifact.parserVersion = options.adapterVersion;

                    std::string related, relatedStatus = "no_file_reference";
                    if (rule.kind == "recording" || rule.kind == "call_recording" ||
                        rule.kind == "media" || rule.kind == "media_file") {
                        auto original = scalar(record,
                            rule.kind == "recording" ? "_data"
                            : rule.kind == "call_recording" ? "file_path" : "data");
                        related = HarmonyBackupExtractor::scopedPath(entry.bundle, entry.appIndex,
                                                                    original);
                        relatedStatus = source.entries().count(related)
                            ? "present_in_backup" : "not_resolved_in_backup";
                        if (relatedStatus == "not_resolved_in_backup") {
                            std::string restored;
                            if ((rule.kind == "media" || rule.kind == "media_file") &&
                                original.starts_with("/storage/cloud/files/"))
                                restored = "/storage/media/local/files/" +
                                    original.substr(std::string("/storage/cloud/files/").size());
                            if (rule.kind == "call_recording" &&
                                original.starts_with("/data/storage/el2/group/")) {
                                const auto marker = original.find("/CallRecord/");
                                if (marker != std::string::npos)
                                    restored = "/data/storage/el2/base/.backup/restore" +
                                        original.substr(marker);
                            }
                            const auto candidate = HarmonyBackupExtractor::scopedPath(
                                entry.bundle, entry.appIndex, restored);
                            const auto target = source.entries().find(candidate);
                            // Only documented backup relocation roots and an exact
                            // suffix are considered; never match by basename globally.
                            if (target != source.entries().end() &&
                                (rule.kind == "call_recording" ||
                                 (record.contains("size") &&
                                  record["size"].is_number_integer() &&
                                  record["size"].get<std::int64_t>() >= 0 &&
                                  record["size"].get<std::uint64_t>() == target->second.size))) {
                                related = candidate;
                                relatedStatus = "present_in_backup_restore_path";
                            }
                        }
                    }
                    artifact.relatedPath = related;
                    artifact.relatedStatus = relatedStatus;

                    out.records.push_back(std::move(artifact));
                    ++parsed;
                    ++totalRows;
                }
                if (rc != SQLITE_DONE) throw std::runtime_error("artifact_query_failed");
                addCoverage(out, rule.kind, path, status::kParsed,
                            "table=" + rule.table + "; rows=" + std::to_string(parsed) +
                                (parsed ? "" : "; empty_table"), parsed);
            }
        } catch (const std::exception& ex) {
            std::cerr << "Harmony database " << path << ": " << ex.what() << std::endl;
            addCoverage(out, "database", path, "ERROR", ex.what());
        }
    }

    for (const auto* missing : {"sms", "contacts", "wechat"}) {
        addCoverage(out, missing, "<harmony-backup>", "NOT_PRESENT",
                    "no_verified_source_in_supported_backup_profile; "
                    "not evidence of absence on device");
    }

    if (!source.verifyIntegrity()) {
        throw std::runtime_error(source.error().empty()
            ? "EVIDENCE_CHANGED_AFTER_INDEX" : source.error());
    }
    return true;
}

}  // namespace mobile_evidence
