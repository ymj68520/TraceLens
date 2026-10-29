// MobileEvidencePackage.cpp
// 统一取数格式的读写实现。

#include "MobileEvidencePackage.h"
#include "MobileEvidenceSchema.h"

#include <sqlite3.h>

#include <cstdio>
#include <ctime>
#include <filesystem>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <utility>

#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace mobile_evidence {

namespace {

using Connection = std::unique_ptr<sqlite3, decltype(&sqlite3_close)>;
using Statement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;

std::string columnText(sqlite3_stmt* statement, int column) {
    const unsigned char* value = sqlite3_column_text(statement, column);
    return value ? reinterpret_cast<const char*>(value) : std::string{};
}

bool bindText(sqlite3_stmt* statement, int index, const std::string& value) {
    return sqlite3_bind_text(statement, index, value.c_str(), -1, SQLITE_TRANSIENT) == SQLITE_OK;
}

bool bindOptionalInt64(sqlite3_stmt* statement, int index,
                       const std::optional<std::int64_t>& value) {
    if (!value) return sqlite3_bind_null(statement, index) == SQLITE_OK;
    return sqlite3_bind_int64(statement, index, *value) == SQLITE_OK;
}

Statement prepare(sqlite3* db, const char* sql, std::string& error) {
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) != SQLITE_OK) {
        error = sqlite3_errmsg(db);
        return Statement(nullptr, sqlite3_finalize);
    }
    return Statement(raw, sqlite3_finalize);
}

std::string isoNowUtc() {
    const std::time_t now = std::time(nullptr);
    std::tm utc{};
#ifdef _WIN32
    gmtime_s(&utc, &now);
#else
    gmtime_r(&now, &utc);
#endif
    char buffer[32] = {};
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return buffer;
}

// row_uid：取数层未给稳定键时，用类别+包名+来源+行内序号兜底，
// 保证同一包重复导入幂等、不同行不互相覆盖。
std::string makeRowUid(const Record& record, std::size_t sequence) {
    std::ostringstream out;
    out << record.kind << '|' << record.nativeKind << '|' << record.packageName << '|'
        << record.appIndex << '|' << record.sourcePath << '|' << record.sourceTable << '|'
        << record.sourceKey << '|' << sequence;
    return out.str();
}

json parseJsonOrObject(const std::string& text) {
    if (text.empty()) return json::object();
    try {
        json value = json::parse(text);
        if (!value.is_object()) return json::object();
        return value;
    } catch (const json::exception&) {
        // 原始行必须保留；解析失败时包一层，避免整包写入失败。
        return json{{"__unparsed_raw", text}};
    }
}

}  // namespace

// ---------------------------------------------------------------------------
// Writer
// ---------------------------------------------------------------------------

Writer::Writer(std::string dbPath) : dbPath_(std::move(dbPath)) {}

Writer::~Writer() {
    close();
}

bool Writer::open() {
    if (db_) return true;
    // 写入端用独立临时文件再原子改名，避免中途失败留下半个包。
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath_.c_str(), &db) != SQLITE_OK) {
        error_ = db ? sqlite3_errmsg(db) : "cannot open output database";
        if (db) sqlite3_close(db);
        return false;
    }
    db_ = db;
    ownsDb_ = true;
    sqlite3_busy_timeout(db, 5000);
    if (sqlite3_exec(db, schema::kDDL, nullptr, nullptr, nullptr) != SQLITE_OK) {
        error_ = sqlite3_errmsg(db);
        return false;
    }
    return true;
}

bool Writer::writePackage(const Package& package) {
    if (!open()) return false;
    auto* db = static_cast<sqlite3*>(db_);

    if (sqlite3_exec(db, "BEGIN IMMEDIATE", nullptr, nullptr, nullptr) != SQLITE_OK) {
        error_ = sqlite3_errmsg(db);
        return false;
    }
    const auto rollback = [&](const std::string& message) {
        error_ = message;
        sqlite3_exec(db, "ROLLBACK", nullptr, nullptr, nullptr);
        return false;
    };

    // 重写同一个包时清空旧内容，保证幂等。
    if (sqlite3_exec(db,
                     "DELETE FROM mobile_evidence_record;"
                     "DELETE FROM mobile_evidence_file;"
                     "DELETE FROM mobile_evidence_coverage;"
                     "DELETE FROM mobile_evidence_meta;",
                     nullptr, nullptr, nullptr) != SQLITE_OK) {
        return rollback(sqlite3_errmsg(db));
    }

    // ---- meta ----
    {
        auto meta = prepare(db, "INSERT OR REPLACE INTO mobile_evidence_meta(key,value) VALUES(?,?)",
                            error_);
        if (!meta) return rollback(error_);
        const std::pair<const char*, std::string> entries[] = {
            {schema::meta_key::kFormat, kFormatName},
            {schema::meta_key::kSchemaVersion, std::to_string(kSchemaVersion)},
            {schema::meta_key::kCreatedAt, isoNowUtc()},
            {schema::meta_key::kRecordCount, std::to_string(package.records.size())},
            {schema::meta_key::kFileCount, std::to_string(package.files.size())},
            {schema::meta_key::kCoverageCount, std::to_string(package.coverage.size())},
            {schema::meta_key::kAdapterName, package.acquisition.adapterName},
            {schema::meta_key::kAdapterVersion, package.acquisition.adapterVersion},
            {schema::meta_key::kPlatform, package.device.platform},
        };
        for (const auto& [key, value] : entries) {
            if (!bindText(meta.get(), 1, key) || !bindText(meta.get(), 2, value) ||
                sqlite3_step(meta.get()) != SQLITE_DONE) {
                return rollback(sqlite3_errmsg(db));
            }
            sqlite3_reset(meta.get());
        }

        const json device = {
            {"platform", package.device.platform},
            {"manufacturer", package.device.manufacturer},
            {"brand", package.device.brand},
            {"model", package.device.model},
            {"device_name", package.device.deviceName},
            {"os_version", package.device.osVersion},
            {"build_version", package.device.buildVersion},
            {"serial_number", package.device.serialNumber},
            {"imei", package.device.imei},
            {"meid", package.device.meid},
            {"iccid", package.device.iccid},
            {"msisdn", package.device.msisdn},
            {"android_id", package.device.androidId},
            {"unique_identifier", package.device.uniqueIdentifier},
            {"timezone", package.device.timezone},
            {"locale", package.device.locale},
            {"extra", parseJsonOrObject(package.device.extraJson)},
        };
        const json acquisition = {
            {"adapter_name", package.acquisition.adapterName},
            {"adapter_version", package.acquisition.adapterVersion},
            {"source_type", package.acquisition.sourceType},
            {"source_path", package.acquisition.sourcePath},
            {"source_sha256", package.acquisition.sourceSha256},
            {"acquired_at", package.acquisition.acquiredAt},
            {"acquired_at_seconds", package.acquisition.acquiredAtSeconds},
            {"operator", package.acquisition.operatorName},
            {"tool_version", package.acquisition.toolVersion},
            {"notes", package.acquisition.notes},
            {"extra", parseJsonOrObject(package.acquisition.extraJson)},
        };
        const std::pair<const char*, std::string> blobs[] = {
            {schema::meta_key::kDeviceJson, device.dump()},
            {schema::meta_key::kAcquisitionJson, acquisition.dump()},
        };
        for (const auto& [key, value] : blobs) {
            if (!bindText(meta.get(), 1, key) || !bindText(meta.get(), 2, value) ||
                sqlite3_step(meta.get()) != SQLITE_DONE) {
                return rollback(sqlite3_errmsg(db));
            }
            sqlite3_reset(meta.get());
        }

        if (package.manifest.present) {
            const json manifest = {
                {"target_table", package.manifest.targetTable},
                {"platform", package.manifest.platform},
                {"device", package.manifest.device},
                {"backup_version", package.manifest.backupVersion},
                {"backup_time_ms", package.manifest.backupTimeMs},
                {"module_count", package.manifest.moduleCount},
                {"manifest_sha256", package.manifest.manifestSha256},
                {"adapter_version", package.manifest.adapterVersion},
            };
            if (!bindText(meta.get(), 1, schema::meta_key::kManifestJson) ||
                !bindText(meta.get(), 2, manifest.dump()) ||
                sqlite3_step(meta.get()) != SQLITE_DONE) {
                return rollback(sqlite3_errmsg(db));
            }
            sqlite3_reset(meta.get());
        }
    }

    // ---- records ----
    {
        auto insert = prepare(db,
            "INSERT OR REPLACE INTO mobile_evidence_record("
            "row_uid,kind,native_kind,mobile_artifact,package_name,app_index,"
            "source_path,source_table,source_key,"
            "raw_json,payload_json,timestamp_raw,timestamp_unit,timestamp_seconds,"
            "source_sha256,source_wal_sha256,parser_version,related_path,related_status,"
            "database_path,database_table,database_columns_json,database_open_status,"
            "database_row_count,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", error_);
        if (!insert) return rollback(error_);

        std::size_t sequence = 0;
        for (const auto& record : package.records) {
            ++sequence;
            const std::string uid = record.sourceKey.empty()
                ? makeRowUid(record, sequence)
                : makeRowUid(record, 0);
            const std::string raw = parseJsonOrObject(record.rawJson).dump();
            const std::string payload = parseJsonOrObject(record.payloadJson).dump();
            const std::string unit = record.timestampUnit.empty() && !record.timestampRaw.empty()
                ? std::string(time_unit::kText) : record.timestampUnit;

            int index = 1;
            bool ok = bindText(insert.get(), index++, uid)
                   && bindText(insert.get(), index++, record.kind)
                   && (record.nativeKind.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.nativeKind))
                   && sqlite3_bind_int(insert.get(), index++, record.mobileArtifact ? 1 : 0) == SQLITE_OK
                   && bindText(insert.get(), index++, record.packageName)
                   && sqlite3_bind_int(insert.get(), index++, record.appIndex) == SQLITE_OK
                   && bindText(insert.get(), index++, record.sourcePath)
                   && bindText(insert.get(), index++, record.sourceTable)
                   && bindText(insert.get(), index++, record.sourceKey)
                   && bindText(insert.get(), index++, raw)
                   && bindText(insert.get(), index++, payload)
                   && (record.timestampRaw.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.timestampRaw))
                   && (unit.empty() ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                                    : bindText(insert.get(), index++, unit))
                   && bindOptionalInt64(insert.get(), index++, record.timestampSeconds)
                   && (record.sourceSha256.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.sourceSha256))
                   && (record.sourceWalSha256.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.sourceWalSha256))
                   && bindText(insert.get(), index++, record.parserVersion)
                   && (record.relatedPath.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.relatedPath))
                   && (record.relatedStatus.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.relatedStatus))
                   && (record.databasePath.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.databasePath))
                   && (record.databaseTable.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.databaseTable))
                   && (record.databaseColumnsJson.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.databaseColumnsJson))
                   && (record.databaseOpenStatus.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, record.databaseOpenStatus))
                   && (record.databaseRowCount
                           ? sqlite3_bind_int64(insert.get(), index++,
                                 static_cast<sqlite3_int64>(*record.databaseRowCount)) == SQLITE_OK
                           : sqlite3_bind_null(insert.get(), index++) == SQLITE_OK)
                   && bindText(insert.get(), index++, record.status);
            if (!ok || sqlite3_step(insert.get()) != SQLITE_DONE) {
                return rollback(sqlite3_errmsg(db));
            }
            sqlite3_reset(insert.get());
        }
    }

    // ---- files ----
    {
        auto insert = prepare(db,
            "INSERT OR REPLACE INTO mobile_evidence_file("
            "relative_path,file_name,extension,category,package_name,size,"
            "modified_time_ms,sha256,status) VALUES(?,?,?,?,?,?,?,?,?)", error_);
        if (!insert) return rollback(error_);
        for (const auto& file : package.files) {
            int index = 1;
            bool ok = bindText(insert.get(), index++, file.relativePath)
                   && bindText(insert.get(), index++, file.fileName)
                   && bindText(insert.get(), index++, file.extension)
                   && bindText(insert.get(), index++, file.category)
                   && bindText(insert.get(), index++, file.packageName)
                   && sqlite3_bind_int64(insert.get(), index++, static_cast<sqlite3_int64>(file.size)) == SQLITE_OK
                   && sqlite3_bind_int64(insert.get(), index++,
                          static_cast<sqlite3_int64>(file.modifiedTimeMs)) == SQLITE_OK
                   && (file.sha256.empty() ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                                           : bindText(insert.get(), index++, file.sha256))
                   && bindText(insert.get(), index++, file.status);
            if (!ok || sqlite3_step(insert.get()) != SQLITE_DONE) {
                return rollback(sqlite3_errmsg(db));
            }
            sqlite3_reset(insert.get());
        }
    }

    // ---- coverage ----
    {
        auto insert = prepare(db,
            "INSERT OR REPLACE INTO mobile_evidence_coverage("
            "artifact_kind,source_path,status,native_status,detail,record_count) "
            "VALUES(?,?,?,?,?,?)", error_);
        if (!insert) return rollback(error_);
        for (const auto& entry : package.coverage) {
            int index = 1;
            bool ok = bindText(insert.get(), index++, entry.artifactKind)
                   && bindText(insert.get(), index++, entry.sourcePath)
                   && bindText(insert.get(), index++, entry.status)
                   && (entry.nativeStatus.empty()
                           ? sqlite3_bind_null(insert.get(), index++) == SQLITE_OK
                           : bindText(insert.get(), index++, entry.nativeStatus))
                   && bindText(insert.get(), index++, entry.detail)
                   && sqlite3_bind_int64(insert.get(), index++,
                          static_cast<sqlite3_int64>(entry.recordCount)) == SQLITE_OK;
            if (!ok || sqlite3_step(insert.get()) != SQLITE_DONE) {
                return rollback(sqlite3_errmsg(db));
            }
            sqlite3_reset(insert.get());
        }
    }

    if (sqlite3_exec(db, "COMMIT", nullptr, nullptr, nullptr) != SQLITE_OK) {
        return rollback(sqlite3_errmsg(db));
    }
    error_.clear();
    return true;
}

bool Writer::close() {
    if (!db_) return true;
    auto* db = static_cast<sqlite3*>(db_);
    if (ownsDb_) {
        sqlite3_close(db);
    }
    db_ = nullptr;
    ownsDb_ = false;
    return true;
}

// ---------------------------------------------------------------------------
// Reader
// ---------------------------------------------------------------------------

Reader::Reader(std::string dbPath) : dbPath_(std::move(dbPath)) {}

Reader::~Reader() {
    close();
}

bool Reader::open() {
    if (db_) return true;
    if (!fs::exists(dbPath_)) {
        error_ = "package not found: " + dbPath_;
        return false;
    }
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath_.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        error_ = db ? sqlite3_errmsg(db) : "cannot open package";
        if (db) sqlite3_close(db);
        return false;
    }
    if (sqlite3_exec(db, "PRAGMA query_only=1;", nullptr, nullptr, nullptr) != SQLITE_OK) {
        error_ = sqlite3_errmsg(db);
        sqlite3_close(db);
        return false;
    }
    db_ = db;
    sqlite3_busy_timeout(db, 5000);

    // 校验格式标识，避免把任意 SQLite 误当成本格式。
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db,
            "SELECT value FROM mobile_evidence_meta WHERE key='format'", -1, &raw, nullptr)
        == SQLITE_OK) {
        Statement stmt(raw, sqlite3_finalize);
        if (sqlite3_step(stmt.get()) == SQLITE_ROW && columnText(stmt.get(), 0) == kFormatName) {
            if (sqlite3_prepare_v2(db,
                    "SELECT value FROM mobile_evidence_meta WHERE key='schema_version'",
                    -1, &raw, nullptr) == SQLITE_OK) {
                Statement version(raw, sqlite3_finalize);
                if (sqlite3_step(version.get()) == SQLITE_ROW) {
                    try { schemaVersion_ = std::stoi(columnText(version.get(), 0)); }
                    catch (const std::exception&) { schemaVersion_ = 0; }
                }
            }
            error_.clear();
            return true;
        }
    }
    error_ = "not a mobile evidence package: " + dbPath_;
    sqlite3_close(db);
    db_ = nullptr;
    return false;
}

bool Reader::close() {
    if (!db_) return true;
    sqlite3_close(static_cast<sqlite3*>(db_));
    db_ = nullptr;
    return true;
}

bool Reader::readDevice(DeviceInfo& out) const {
    if (!db_) return false;
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_),
            "SELECT value FROM mobile_evidence_meta WHERE key='device_json'",
            -1, &raw, nullptr) != SQLITE_OK) {
        return false;
    }
    Statement stmt(raw, sqlite3_finalize);
    if (sqlite3_step(stmt.get()) != SQLITE_ROW) return false;

    json value = parseJsonOrObject(columnText(stmt.get(), 0));
    const auto pick = [&value](const char* key) -> std::string {
        if (!value.contains(key) || value[key].is_null()) return {};
        return value[key].is_string() ? value[key].get<std::string>() : value[key].dump();
    };
    out.platform = pick("platform");
    out.manufacturer = pick("manufacturer");
    out.brand = pick("brand");
    out.model = pick("model");
    out.deviceName = pick("device_name");
    out.osVersion = pick("os_version");
    out.buildVersion = pick("build_version");
    out.serialNumber = pick("serial_number");
    out.imei = pick("imei");
    out.meid = pick("meid");
    out.iccid = pick("iccid");
    out.msisdn = pick("msisdn");
    out.androidId = pick("android_id");
    out.uniqueIdentifier = pick("unique_identifier");
    out.timezone = pick("timezone");
    out.locale = pick("locale");
    out.extraJson = value.contains("extra") ? value["extra"].dump() : std::string{};
    return true;
}

bool Reader::readAcquisition(AcquisitionInfo& out) const {
    if (!db_) return false;
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_),
            "SELECT value FROM mobile_evidence_meta WHERE key='acquisition_json'",
            -1, &raw, nullptr) != SQLITE_OK) {
        return false;
    }
    Statement stmt(raw, sqlite3_finalize);
    if (sqlite3_step(stmt.get()) != SQLITE_ROW) return false;

    json value = parseJsonOrObject(columnText(stmt.get(), 0));
    const auto pick = [&value](const char* key) -> std::string {
        if (!value.contains(key) || value[key].is_null()) return {};
        return value[key].is_string() ? value[key].get<std::string>() : value[key].dump();
    };
    out.adapterName = pick("adapter_name");
    out.adapterVersion = pick("adapter_version");
    out.sourceType = pick("source_type");
    out.sourcePath = pick("source_path");
    out.sourceSha256 = pick("source_sha256");
    out.acquiredAt = pick("acquired_at");
    out.acquiredAtSeconds = value.contains("acquired_at_seconds") &&
                            value["acquired_at_seconds"].is_number()
        ? value["acquired_at_seconds"].get<std::int64_t>() : 0;
    out.operatorName = pick("operator");
    out.toolVersion = pick("tool_version");
    out.notes = pick("notes");
    out.extraJson = value.contains("extra") ? value["extra"].dump() : std::string{};
    return true;
}

bool Reader::readManifest(BackupManifest& out) const {
    if (!db_) return false;
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_),
            "SELECT value FROM mobile_evidence_meta WHERE key='manifest_json'",
            -1, &raw, nullptr) != SQLITE_OK) {
        return false;
    }
    Statement stmt(raw, sqlite3_finalize);
    if (sqlite3_step(stmt.get()) != SQLITE_ROW) return false;

    json value = parseJsonOrObject(columnText(stmt.get(), 0));
    const auto pick = [&value](const char* key) -> std::string {
        if (!value.contains(key) || value[key].is_null()) return {};
        return value[key].is_string() ? value[key].get<std::string>() : value[key].dump();
    };
    out.targetTable = pick("target_table");
    out.platform = pick("platform");
    out.device = pick("device");
    out.backupVersion = pick("backup_version");
    out.backupTimeMs = value.contains("backup_time_ms") && value["backup_time_ms"].is_number()
        ? value["backup_time_ms"].get<std::int64_t>() : 0;
    out.moduleCount = value.contains("module_count") && value["module_count"].is_number()
        ? value["module_count"].get<std::int64_t>() : 0;
    out.manifestSha256 = pick("manifest_sha256");
    out.adapterVersion = pick("adapter_version");
    out.present = !out.targetTable.empty();
    return out.present;
}

std::vector<Record> Reader::readRecords() const {
    return readRecords(std::string{});
}

std::vector<Record> Reader::readRecords(const std::string& kindFilter) const {
    std::vector<Record> rows;
    if (!db_) return rows;

    const char* sqlWithKind =
        "SELECT kind,native_kind,mobile_artifact,package_name,app_index,"
        "source_path,source_table,source_key,"
        "raw_json,payload_json,timestamp_raw,timestamp_unit,timestamp_seconds,"
        "source_sha256,source_wal_sha256,parser_version,related_path,related_status,"
        "database_path,database_table,database_columns_json,database_open_status,"
        "database_row_count,status "
        "FROM mobile_evidence_record WHERE kind=? ORDER BY id";
    const char* sqlAll =
        "SELECT kind,native_kind,mobile_artifact,package_name,app_index,"
        "source_path,source_table,source_key,"
        "raw_json,payload_json,timestamp_raw,timestamp_unit,timestamp_seconds,"
        "source_sha256,source_wal_sha256,parser_version,related_path,related_status,"
        "database_path,database_table,database_columns_json,database_open_status,"
        "database_row_count,status "
        "FROM mobile_evidence_record ORDER BY id";

    sqlite3_stmt* raw = nullptr;
    const char* sql = kindFilter.empty() ? sqlAll : sqlWithKind;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_), sql, -1, &raw, nullptr) != SQLITE_OK) {
        error_ = sqlite3_errmsg(static_cast<sqlite3*>(db_));
        return rows;
    }
    Statement stmt(raw, sqlite3_finalize);
    if (!kindFilter.empty()) {
        sqlite3_bind_text(stmt.get(), 1, kindFilter.c_str(), -1, SQLITE_TRANSIENT);
    }

    while (sqlite3_step(stmt.get()) == SQLITE_ROW) {
        Record record;
        record.kind = columnText(stmt.get(), 0);
        record.nativeKind = columnText(stmt.get(), 1);
        record.mobileArtifact = sqlite3_column_int(stmt.get(), 2) != 0;
        record.packageName = columnText(stmt.get(), 3);
        record.appIndex = sqlite3_column_int(stmt.get(), 4);
        record.sourcePath = columnText(stmt.get(), 5);
        record.sourceTable = columnText(stmt.get(), 6);
        record.sourceKey = columnText(stmt.get(), 7);
        record.rawJson = columnText(stmt.get(), 8);
        record.payloadJson = columnText(stmt.get(), 9);
        record.timestampRaw = columnText(stmt.get(), 10);
        record.timestampUnit = columnText(stmt.get(), 11);
        if (sqlite3_column_type(stmt.get(), 12) != SQLITE_NULL) {
            record.timestampSeconds = sqlite3_column_int64(stmt.get(), 12);
        }
        record.sourceSha256 = columnText(stmt.get(), 13);
        record.sourceWalSha256 = columnText(stmt.get(), 14);
        record.parserVersion = columnText(stmt.get(), 15);
        record.relatedPath = columnText(stmt.get(), 16);
        record.relatedStatus = columnText(stmt.get(), 17);
        record.databasePath = columnText(stmt.get(), 18);
        record.databaseTable = columnText(stmt.get(), 19);
        record.databaseColumnsJson = columnText(stmt.get(), 20);
        record.databaseOpenStatus = columnText(stmt.get(), 21);
        if (sqlite3_column_type(stmt.get(), 22) != SQLITE_NULL) {
            record.databaseRowCount =
                static_cast<std::uint64_t>(sqlite3_column_int64(stmt.get(), 22));
        }
        record.status = columnText(stmt.get(), 23);
        rows.push_back(std::move(record));
    }
    return rows;
}

std::vector<FileEntry> Reader::readFiles() const {
    std::vector<FileEntry> rows;
    if (!db_) return rows;

    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_),
            "SELECT relative_path,file_name,extension,category,package_name,size,"
            "modified_time_ms,sha256,status FROM mobile_evidence_file ORDER BY id",
            -1, &raw, nullptr) != SQLITE_OK) {
        error_ = sqlite3_errmsg(static_cast<sqlite3*>(db_));
        return rows;
    }
    Statement stmt(raw, sqlite3_finalize);
    while (sqlite3_step(stmt.get()) == SQLITE_ROW) {
        FileEntry entry;
        entry.relativePath = columnText(stmt.get(), 0);
        entry.fileName = columnText(stmt.get(), 1);
        entry.extension = columnText(stmt.get(), 2);
        entry.category = columnText(stmt.get(), 3);
        entry.packageName = columnText(stmt.get(), 4);
        entry.size = static_cast<std::uint64_t>(sqlite3_column_int64(stmt.get(), 5));
        entry.modifiedTimeMs = static_cast<std::uint64_t>(sqlite3_column_int64(stmt.get(), 6));
        entry.sha256 = columnText(stmt.get(), 7);
        entry.status = columnText(stmt.get(), 8);
        rows.push_back(std::move(entry));
    }
    return rows;
}

std::vector<Coverage> Reader::readCoverage() const {
    std::vector<Coverage> rows;
    if (!db_) return rows;

    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_),
            "SELECT artifact_kind,source_path,status,native_status,detail,record_count "
            "FROM mobile_evidence_coverage ORDER BY id", -1, &raw, nullptr) != SQLITE_OK) {
        error_ = sqlite3_errmsg(static_cast<sqlite3*>(db_));
        return rows;
    }
    Statement stmt(raw, sqlite3_finalize);
    while (sqlite3_step(stmt.get()) == SQLITE_ROW) {
        Coverage entry;
        entry.artifactKind = columnText(stmt.get(), 0);
        entry.sourcePath = columnText(stmt.get(), 1);
        entry.status = columnText(stmt.get(), 2);
        entry.nativeStatus = columnText(stmt.get(), 3);
        entry.detail = columnText(stmt.get(), 4);
        entry.recordCount = static_cast<std::uint64_t>(sqlite3_column_int64(stmt.get(), 5));
        rows.push_back(std::move(entry));
    }
    return rows;
}

std::map<std::string, std::uint64_t> Reader::recordCountsByKind() const {
    std::map<std::string, std::uint64_t> counts;
    if (!db_) return counts;

    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(static_cast<sqlite3*>(db_),
            "SELECT kind,COUNT(*) FROM mobile_evidence_record GROUP BY kind", -1, &raw, nullptr)
        != SQLITE_OK) {
        return counts;
    }
    Statement stmt(raw, sqlite3_finalize);
    while (sqlite3_step(stmt.get()) == SQLITE_ROW) {
        counts[columnText(stmt.get(), 0)] =
            static_cast<std::uint64_t>(sqlite3_column_int64(stmt.get(), 1));
    }
    return counts;
}

bool looksLikePackage(const std::string& dbPath) {
    Reader reader(dbPath);
    return reader.open();
}

std::string defaultPackagePath(const std::string& sourcePath) {
    fs::path path(sourcePath);
    // 去掉末尾分隔符，避免空文件名。
    while (path.has_relative_path() && path.filename().empty()) {
        path = path.parent_path();
    }
    std::string stem = path.filename().string();
    if (stem.empty()) stem = "mobile_evidence";
    return (path.parent_path() / (stem + "_mobile_evidence.mep.db")).string();
}

}  // namespace mobile_evidence
