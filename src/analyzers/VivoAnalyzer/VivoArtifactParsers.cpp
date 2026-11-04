#include "VivoArtifactParsers.h"

#include "VivoBackupExtractor.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileBackupSchema.h"

#include <sqlite3.h>

#include <cstring>
#include <iostream>
#include <map>
#include <sstream>
#include <string>

namespace vivo_artifacts {
namespace {

/** Category -> artifact kind used in mobile_artifacts and coverage rows. */
const char* categoryKind(const std::string& category) {
    if (category == "album") return "media_photo";
    if (category == "video") return "media_video";
    if (category == "music") return "media_audio";
    if (category == "record") return "recording";
    if (category == "document") return "document";
    if (category == "zip_file") return "archive";
    if (category == "settings_file") return "app_settings";
    if (category == "app") return "app_package";
    return "backup_file";
}

std::string jsonEscape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 8);
    for (char character : value) {
        switch (character) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += character; break;
        }
    }
    return out;
}

bool insertRecord(sqlite3* db, const std::string& kind, const std::string& package,
                  const std::string& sourcePath, const std::string& sourceTable,
                  const std::string& sourceKey, const std::string& recordJson,
                  long long timestampSeconds, const std::string& parserVersion,
                  const std::string& relatedPath) {
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db,
            "INSERT OR REPLACE INTO mobile_artifacts(kind,package_name,app_index,"
            "source_path,source_table,source_key,record_json,timestamp_raw,time_unit,"
            "timestamp_seconds,source_db_sha256,source_wal_sha256,parser_version,"
            "related_path,related_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            -1, &statement, nullptr) != SQLITE_OK) {
        return false;
    }
    sqlite3_bind_text(statement, 1, kind.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, package.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(statement, 3, 0);
    sqlite3_bind_text(statement, 4, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 5, sourceTable.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 6, sourceKey.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 7, recordJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_null(statement, 8);
    sqlite3_bind_null(statement, 9);
    if (timestampSeconds > 0) sqlite3_bind_int64(statement, 10, timestampSeconds);
    else sqlite3_bind_null(statement, 10);
    sqlite3_bind_null(statement, 11);
    sqlite3_bind_null(statement, 12);
    sqlite3_bind_text(statement, 13, parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 14, relatedPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 15, "indexed", -1, SQLITE_TRANSIENT);
    const bool ok = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return ok;
}

void recordManifest(VivoBackupExtractor& extractor, AndroidAnalysisDatabase& database) {
    sqlite3* dest = database.handle();
    if (!dest) return;
    if (sqlite3_exec(dest, mobile_backup_schema::DDL, nullptr, nullptr, nullptr) != SQLITE_OK) {
        return;
    }
    const std::string label = extractor.model().empty() ? "vivo" : extractor.model();
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(dest,
            "INSERT OR REPLACE INTO mobile_backup_manifest VALUES(1,?,?,?,?,?,?,?)",
            -1, &statement, nullptr) != SQLITE_OK) {
        return;
    }
    sqlite3_bind_text(statement, 1, "Android", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, label.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 3, extractor.backupVersion().c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(statement, 4, extractor.backupTimeMs());
    sqlite3_bind_int64(statement, 5, static_cast<sqlite3_int64>(extractor.applicationCount()));
    sqlite3_bind_text(statement, 6, "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 7, "vivo-backup-v1", -1, SQLITE_TRANSIENT);
    sqlite3_step(statement);
    sqlite3_finalize(statement);
}

}  // namespace

VivoParseResult analyzeVivoBackup(VivoBackupExtractor& extractor,
                                  AndroidAnalysisDatabase& database) {
    VivoParseResult result;
    sqlite3* dest = database.handle();
    if (!dest) {
        result.failures = 1;
        return result;
    }
    if (sqlite3_exec(dest, mobile_backup_schema::DDL, nullptr, nullptr, nullptr) != SQLITE_OK) {
        result.failures = 1;
        return result;
    }

    recordManifest(extractor, database);

    // Thousands of rows cannot be inserted one implicit transaction at a time:
    // each would fsync and the task would appear hung. One transaction for the
    // whole index keeps a 5k-entry backup in the sub-second range.
    const bool transaction = database.beginTransaction();

    // Applications: one installed_packages row per bundle the backup captured.
    std::map<std::string, std::size_t> packageItems;
    for (const auto& item : extractor.items()) {
        if (item.category != "app" || item.package.empty()) continue;
        packageItems[item.package] += 1;
    }
    for (const auto& [package, count] : packageItems) {
        InstalledPackageInfo info;
        info.packageName = package;
        info.codePath = "vivo-backup";
        info.version = "";
        info.installer = "vivo-backup";
        if (database.insertInstalledPackage(info)) {
            ++result.applications;
            (void)count;
        }
    }

    // Every indexed file becomes one mobile_artifacts row so it is citable.
    // "obfuscated" describes the source package; "readable" says whether the
    // built-in key actually decodes this package. They differ if the vendor
    // changes the key, in which case nothing is claimed as parseable.
    const bool obfuscated = extractor.obfuscated();
    const bool readable = extractor.payloadReadable();
    std::map<std::string, std::size_t> perCategory;
    for (const auto& item : extractor.items()) {
        const std::string kind = categoryKind(item.category);
        const long long seconds = item.mtimeMs > 0 ? item.mtimeMs / 1000 : 0;
        std::ostringstream record;
        record << "{\"category\":\"" << jsonEscape(item.category) << "\","
               << "\"original_path\":\"" << jsonEscape(item.originalPath) << "\","
               << "\"hash\":\"" << jsonEscape(item.hash) << "\","
               << "\"size\":" << item.size << ","
               << "\"mtime_ms\":" << item.mtimeMs << ","
               << "\"payload_state\":\""
               << (!obfuscated ? "readable" : readable ? "deobfuscated" : "obfuscated")
               << "\"}";
        // source_key must be valid JSON: readers parse it directly.
        std::ostringstream key;
        key << "{\"category\":\"" << jsonEscape(item.category) << "\","
            << "\"hash\":\"" << jsonEscape(item.hash) << "\"}";

        if (insertRecord(dest, kind, item.package, item.originalPath,
                         item.category, key.str(), record.str(), seconds,
                         "vivo-backup-v1", item.hash)) {
            ++result.fileRecords;
            perCategory[item.category] += 1;
        } else {
            ++result.failures;
        }
    }

    // One coverage row per category. Obfuscated payloads are locked, and a
    // record-only category is reported as absent rather than parsed.
    for (const auto& [category, count] : perCategory) {
        const std::string status = !obfuscated ? "PARSED"
            : readable ? "PARSED" : "locked_or_unsupported";
        const std::string detail = !obfuscated
            ? std::to_string(count) + " item(s) indexed"
            : readable
                ? std::to_string(count) + " item(s) indexed; payload deobfuscated with the built-in key"
                : "Index lists " + std::to_string(count) +
                      " item(s); payload bytes are xor-obfuscated with an unrecognised key";
        database.recordSourceCoverage(category, "vivo:" + category, status, detail);
        ++result.categories;
    }

    if (transaction) database.commitTransaction();
    return result;
}

}  // namespace vivo_artifacts
