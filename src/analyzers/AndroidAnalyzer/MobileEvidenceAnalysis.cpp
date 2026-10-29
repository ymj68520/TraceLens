// MobileEvidenceAnalysis.cpp
// 统一取数包 → android.db 的分析阶段实现。

#include "MobileEvidenceAnalysis.h"

#include "AndroidAnalysisDatabase.h"
#include "MobileBackupSchema.h"

#include <sqlite3.h>

#include <map>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace mobile_evidence {
namespace {

using json = nlohmann::json;

// mobile_artifacts 是鸿蒙/雷电适配器的原生输出格式，时间轴、LLM 分析、
// artifact reader 都读它。统一包里的记录只要标记了 mobileArtifact，就按
// 原有列语义逐列回写，保证下游契约不变。
bool insertMobileArtifact(AndroidAnalysisDatabase& database, const Record& record) {
    sqlite3* dest = database.handle();
    if (!dest) return false;
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(dest,
                           "INSERT OR REPLACE INTO mobile_artifacts(kind,package_name,"
                           "app_index,source_path,source_table,source_key,record_json,"
                           "timestamp_raw,time_unit,timestamp_seconds,source_db_sha256,"
                           "source_wal_sha256,parser_version,related_path,related_status) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           -1, &statement, nullptr) != SQLITE_OK) {
        return false;
    }
    const std::string kindName = record.nativeKind.empty() ? record.kind : record.nativeKind;
    sqlite3_bind_text(statement, 1, kindName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, record.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(statement, 3, record.appIndex);
    sqlite3_bind_text(statement, 4, record.sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 5, record.sourceTable.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 6, record.sourceKey.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 7, record.rawJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 8, record.timestampRaw.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 9, record.timestampUnit.c_str(), -1, SQLITE_TRANSIENT);
    if (record.timestampSeconds) sqlite3_bind_int64(statement, 10, *record.timestampSeconds);
    else sqlite3_bind_null(statement, 10);
    sqlite3_bind_text(statement, 11, record.sourceSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 12, record.sourceWalSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 13, record.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 14, record.relatedPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 15, record.relatedStatus.c_str(), -1, SQLITE_TRANSIENT);
    const bool ok = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return ok;
}

std::string stringField(const json& value, const char* key) {
    if (!value.contains(key) || value[key].is_null()) return {};
    if (value[key].is_string()) return value[key].get<std::string>();
    return value[key].dump();
}

std::string intAsString(const json& value, const char* key, const std::string& fallback = "0") {
    if (!value.contains(key) || value[key].is_null()) return fallback;
    if (value[key].is_number_integer()) return std::to_string(value[key].get<long long>());
    if (value[key].is_string()) return value[key].get<std::string>();
    return fallback;
}

json payloadOf(const Record& record) {
    if (record.payloadJson.empty()) return json::object();
    try {
        json value = json::parse(record.payloadJson);
        return value.is_object() ? value : json::object();
    } catch (const json::exception&) {
        return json::object();
    }
}

// 分析阶段各 kind 的落地函数。签名统一，便于后续按 kind 扩展而不改调度。
bool writeContact(AndroidAnalysisDatabase& db, const Record& record) {
    const json payload = payloadOf(record);
    std::map<std::string, std::string> row;
    row["display_name"] = stringField(payload, "display_name");
    row["phone"] = stringField(payload, "phone_number");
    return db.insertContact(row);
}

// date 列的语义在各来源之间历史上并不统一（MIUI 写毫秒，雷电写秒）。取数层
// 在 payload 中显式给出 date 时一律照搬，避免分析层臆断单位而改写既有结果；
// 未给出时才回退到规范化秒值。
std::string dateValue(const Record& record, const json& payload) {
    if (payload.contains("date") && !payload["date"].is_null()) {
        if (payload["date"].is_string()) return payload["date"].get<std::string>();
        return payload["date"].dump();
    }
    return record.timestampSeconds ? std::to_string(*record.timestampSeconds)
                                   : std::string("0");
}

bool writeCallLog(AndroidAnalysisDatabase& db, const Record& record) {
    const json payload = payloadOf(record);
    std::map<std::string, std::string> row;
    row["number"] = stringField(payload, "number");
    row["date"] = dateValue(record, payload);
    row["duration"] = intAsString(payload, "duration_seconds");
    row["type"] = intAsString(payload, "type");
    // 取数层已经给出规范化秒值；date 保留原值只为回查。
    if (record.timestampSeconds) row["date_seconds"] = std::to_string(*record.timestampSeconds);
    return db.insertCallLog(row);
}

bool writeSms(AndroidAnalysisDatabase& db, const Record& record) {
    const json payload = payloadOf(record);
    std::map<std::string, std::string> row;
    row["address"] = stringField(payload, "address");
    row["body"] = stringField(payload, "body");
    row["date"] = dateValue(record, payload);
    row["type"] = intAsString(payload, "type");
    if (record.timestampSeconds) row["date_seconds"] = std::to_string(*record.timestampSeconds);
    return db.insertSMS(row);
}

bool writeNote(AndroidAnalysisDatabase& db, const Record& record) {
    const json payload = payloadOf(record);
    return db.insertAppNote(record.packageName,
                            stringField(payload, "note_id"),
                            stringField(payload, "title"),
                            stringField(payload, "content"),
                            stringField(payload, "tags"),
                            false,
                            record.relatedPath.empty() ? record.sourcePath : record.relatedPath);
}

bool writeInstalledApp(AndroidAnalysisDatabase& db, const Record& record) {
    const json payload = payloadOf(record);
    const std::string packageName = stringField(payload, "package_name").empty()
        ? record.packageName : stringField(payload, "package_name");
    return db.insertInstalledApp(packageName,
                                 stringField(payload, "display_name"),
                                 {}, {},
                                 static_cast<uint64_t>(std::stoull(
                                     intAsString(payload, "data_size"))),
                                 static_cast<uint64_t>(std::stoull(
                                     intAsString(payload, "sd_size"))),
                                 std::stoi(intAsString(payload, "bak_type")),
                                 {});
}

bool writeWifi(AndroidAnalysisDatabase& db, const Record& record) {
    WifiNetwork network;
    const json payload = payloadOf(record);
    network.ssid = stringField(payload, "ssid");
    network.preSharedKey = stringField(payload, "pre_shared_key");
    network.keyMgmt = stringField(payload, "key_mgmt");
    if (network.ssid.empty()) return true;  // 空 SSID 不落表，但不算失败
    return db.insertWifiNetwork(network);
}

bool writeDeviceIdentity(AndroidAnalysisDatabase& db, const Record& record) {
    const json payload = payloadOf(record);
    const std::string type = stringField(payload, "identifier_type");
    const std::string value = stringField(payload, "value");
    if (type.empty() || value.empty()) return true;
    return db.insertDeviceIdentifier(type, value, record.packageName, record.sourcePath);
}

bool writeDatabaseTable(AndroidAnalysisDatabase& db, const Record& record) {
    // "表不可用"与"表存在但 0 行"是不同事实：前者 row_count 必须为 NULL。
    // insertAppDbInventory 只接受 uint64，这里按 open_status 区分后直接落库。
    if (record.databaseRowCount || record.databaseOpenStatus == "readable" ||
        record.databaseOpenStatus == "decrypted") {
        return db.insertAppDbInventory(record.packageName, record.databasePath,
                                       record.databaseTable,
                                       record.databaseRowCount.value_or(0),
                                       record.databaseColumnsJson,
                                       record.databaseOpenStatus);
    }
    sqlite3* dest = db.handle();
    if (!dest) return false;
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(dest,
            "INSERT INTO app_db_inventory(package_name,db_path,table_name,row_count,"
            "columns,open_status) VALUES(?,?,?,NULL,?,?)",
            -1, &statement, nullptr) != SQLITE_OK) {
        return false;
    }
    sqlite3_bind_text(statement, 1, record.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, record.databasePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 3, record.databaseTable.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 4, record.databaseColumnsJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 5, record.databaseOpenStatus.c_str(), -1, SQLITE_TRANSIENT);
    const bool ok = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return ok;
}

// 备份清单：MIUI 与 Harmony/ThunderForensic 落在不同表上，按 targetTable 分派。
bool writeManifest(AndroidAnalysisDatabase& db, const BackupManifest& manifest) {
    if (manifest.targetTable == "miui_backup_manifest") {
        return db.insertMiuiBackupManifest(manifest.device, manifest.backupVersion,
                                           static_cast<uint64_t>(manifest.backupTimeMs),
                                           0, static_cast<int>(manifest.moduleCount), {});
    }
    if (manifest.targetTable != "mobile_backup_manifest") return true;
    sqlite3* dest = db.handle();
    if (!dest) return false;
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(dest,
                           "INSERT OR REPLACE INTO mobile_backup_manifest "
                           "VALUES(1,?,?,?,?,?,?,?)", -1, &statement, nullptr) != SQLITE_OK) {
        return false;
    }
    sqlite3_bind_text(statement, 1, manifest.platform.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, manifest.device.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 3, manifest.backupVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(statement, 4, manifest.backupTimeMs);
    sqlite3_bind_int64(statement, 5, manifest.moduleCount);
    sqlite3_bind_text(statement, 6, manifest.manifestSha256.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 7, manifest.adapterVersion.c_str(), -1, SQLITE_TRANSIENT);
    const bool ok = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return ok;
}

}  // namespace

bool analyzePackage(const Package& package, AndroidAnalysisDatabase& database,
                    const AnalysisOptions& options, AnalysisResult& result) {
    result = AnalysisResult{};
    const std::vector<Record>& records = package.records;

    // mobile_artifacts / mobile_backup_manifest 是 Harmony 与 ThunderForensic
    // 的原生结果表。包来自这两类来源时按原 schema 建表，保证时间轴、LLM 与
    // artifact reader 行为不变。
    bool needsMobileSchema = false;
    for (const auto& record : records) {
        if (record.mobileArtifact) { needsMobileSchema = true; break; }
    }
    if (package.manifest.present &&
        package.manifest.targetTable == "mobile_backup_manifest") {
        needsMobileSchema = true;
    }
    if (needsMobileSchema && database.handle()) {
        if (sqlite3_exec(database.handle(), mobile_backup_schema::DDL,
                         nullptr, nullptr, nullptr) != SQLITE_OK) {
            return false;
        }
    }
    if (package.manifest.present) {
        if (!writeManifest(database, package.manifest)) return false;
    }

    for (const auto& record : records) {
        bool ok = true;
        if (record.kind == kind::kContact) {
            ok = writeContact(database, record);
            if (ok) ++result.contacts;
        } else if (record.kind == kind::kCallLog) {
            ok = writeCallLog(database, record);
            if (ok) ++result.callLogs;
        } else if (record.kind == kind::kSms) {
            ok = writeSms(database, record);
            if (ok) ++result.sms;
        } else if (record.kind == kind::kNote) {
            ok = writeNote(database, record);
            if (ok) ++result.notes;
        } else if (record.kind == kind::kInstalledApp) {
            ok = writeInstalledApp(database, record);
            if (ok) ++result.installedApps;
        } else if (record.kind == kind::kWifiNetwork) {
            ok = writeWifi(database, record);
            if (ok) ++result.wifiNetworks;
        } else if (record.kind == kind::kDeviceIdentity) {
            ok = writeDeviceIdentity(database, record);
            if (ok) ++result.deviceIdentifiers;
        } else if (record.kind == kind::kDatabaseTable) {
            ok = writeDatabaseTable(database, record);
            if (ok) ++result.databaseTables;
        } else {
            // 尚未有专用落地表的类别（IM、浏览历史、账户、位置等）先计入
            // 覆盖度，保证"取到了但没落表"可被观察到，而不是静默丢弃。
            ++result.otherRecords;
        }
        if (!ok) return false;

        if (record.mobileArtifact) {
            if (!insertMobileArtifact(database, record)) return false;
            ++result.mobileArtifacts;
        }
    }

    if (options.mirrorFiles) {
        for (const auto& file : package.files) {
            // miui_external_files 是既有的文件清单表；这里只回写非数据库条目，
            // 数据库成员的盘点由 android_source_coverage 承载。
            if (file.category == "database") continue;
            const std::string extension = file.extension;
            if (!database.insertMiuiExternalFile(file.relativePath, file.fileName,
                                                 extension, file.category,
                                                 file.size, file.modifiedTimeMs)) {
                return false;
            }
            ++result.files;
        }
    }

    if (options.mirrorCoverage) {
        for (const auto& entry : package.coverage) {
            const std::string& status =
                entry.nativeStatus.empty() ? entry.status : entry.nativeStatus;
            if (!database.recordSourceCoverage(entry.artifactKind, entry.sourcePath,
                                               status, entry.detail)) {
                return false;
            }
            ++result.coverageEntries;
        }
    }

    return true;
}

bool analyzePackage(const Reader& reader, AndroidAnalysisDatabase& database,
                    const AnalysisOptions& options, AnalysisResult& result) {
    Package package;
    package.records = reader.readRecords();
    package.files = reader.readFiles();
    package.coverage = reader.readCoverage();
    reader.readManifest(package.manifest);
    return analyzePackage(package, database, options, result);
}

bool analyzePackage(const std::string& packagePath, AndroidAnalysisDatabase& database,
                    const AnalysisOptions& options, AnalysisResult& result) {
    Reader reader(packagePath);
    if (!reader.open()) return false;
    return analyzePackage(reader, database, options, result);
}

}  // namespace mobile_evidence
