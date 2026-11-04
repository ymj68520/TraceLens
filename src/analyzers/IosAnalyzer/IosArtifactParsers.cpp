#include "IosArtifactParsers.h"

#include "IosBackupExtractor.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileBackupSchema.h"

#include <sqlite3.h>

#include <algorithm>
#include <cctype>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace ios_artifacts {
namespace {

/** Logical paths inside an iOS backup, as recorded in Manifest.db. */
struct SourceSpec {
    const char* kind;        // coverage artifact_kind
    const char* logicalPath; // "<domain>/<relativePath>"
};

constexpr SourceSpec kSources[] = {
    {"sms", "HomeDomain/Library/SMS/sms.db"},
    {"contacts", "HomeDomain/Library/AddressBook/AddressBook.sqlitedb"},
    {"notes", "HomeDomain/Library/Notes/notes.sqlite"},
    {"calendar", "HomeDomain/Library/Calendar/Calendar.sqlitedb"},
    // Only present in full backups; a partial (iCloud-style) backup has
    // neither, which the coverage row reports as no_candidate_path.
    {"call_logs", "HomeDomain/Library/CallHistoryDB/CallHistory.storedata"},
    {"safari", "HomeDomain/Library/Safari/History.db"},
};

void binaryCollationFallback(void*, int, const void*) {}

void installCollations(sqlite3* db) {
    // iOS databases are built by Apple tooling and routinely declare BINARY
    // collations the host library may not have registered.
    sqlite3_create_collation(db, "BINARY", SQLITE_UTF8, nullptr,
                             [](void*, int aLength, const void* a, int bLength, const void* b) {
                                 const int shortest = aLength < bLength ? aLength : bLength;
                                 const int compared = shortest > 0 ? std::memcmp(a, b, shortest) : 0;
                                 return compared ? compared : (aLength - bLength);
                             });
    (void)&binaryCollationFallback;
}

bool openReadOnly(const std::string& path, sqlite3** db) {
    const std::string uri = "file:" + path + "?mode=ro";
    if (sqlite3_open_v2(uri.c_str(), db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nullptr) != SQLITE_OK) {
        if (*db) { sqlite3_close(*db); *db = nullptr; }
        return false;
    }
    sqlite3_exec(*db, "PRAGMA query_only=ON;", nullptr, nullptr, nullptr);
    installCollations(*db);
    return true;
}

std::string columnText(sqlite3_stmt* statement, int index) {
    const unsigned char* value = sqlite3_column_text(statement, index);
    return value ? reinterpret_cast<const char*>(value) : "";
}

long long columnInt64(sqlite3_stmt* statement, int index) {
    return sqlite3_column_type(statement, index) == SQLITE_NULL
               ? 0
               : sqlite3_column_int64(statement, index);
}

bool tableExists(sqlite3* db, const std::string& name) {
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                           -1, &statement, nullptr) != SQLITE_OK) {
        return false;
    }
    sqlite3_bind_text(statement, 1, name.c_str(), -1, SQLITE_TRANSIENT);
    const bool found = sqlite3_step(statement) == SQLITE_ROW;
    sqlite3_finalize(statement);
    return found;
}

/** Column names of a table, so a parser can adapt to schema variants. */
std::set<std::string> tableColumns(sqlite3* db, const std::string& table) {
    std::set<std::string> columns;
    const std::string sql = "PRAGMA table_info(" + table + ")";
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &statement, nullptr) != SQLITE_OK) {
        return columns;
    }
    while (sqlite3_step(statement) == SQLITE_ROW) {
        const std::string name = columnText(statement, 1);
        if (!name.empty()) columns.insert(name);
    }
    sqlite3_finalize(statement);
    return columns;
}

/** Stage one backup member next to the task's secure temp root. */
bool stage(sqlite3* /*unused*/, IosBackupExtractor& extractor, const std::string& logicalPath,
           const std::string& secureTempRoot, std::string* stagedPath) {
    fs::path directory = secureTempRoot.empty()
                             ? fs::temp_directory_path() / "tracelens_ios"
                             : fs::path(secureTempRoot);
    std::error_code error;
    fs::create_directories(directory, error);
    std::string leaf = logicalPath;
    std::replace(leaf.begin(), leaf.end(), '/', '_');
    const fs::path destination = directory / ("ios_" + leaf);
    if (!extractor.extractFileByPath(logicalPath, destination.string())) {
        return false;
    }
    *stagedPath = destination.string();
    return true;
}

void stageSidecars(IosBackupExtractor& extractor, const std::string& logicalPath,
                   const std::string& stagedPath) {
    // iOS ships -wal/-shm beside live databases; the manifest indexes them
    // like any other file, so stage them for the SQLite reader.
    for (const char* suffix : {"-wal", "-shm"}) {
        const std::string member = logicalPath + suffix;
        const std::string target = stagedPath + suffix;
        if (!extractor.extractFileByPath(member, target)) {
            std::error_code error;
            fs::remove(target, error);
        }
    }
}

void cleanup(const std::string& stagedPath) {
    std::error_code error;
    fs::remove(stagedPath, error);
    for (const char* suffix : {"-wal", "-shm"}) {
        fs::remove(stagedPath + suffix, error);
    }
}

// ---------------------------------------------------------------- SMS

int parseSms(const std::string& dbPath, AndroidAnalysisDatabase& database) {
    sqlite3* db = nullptr;
    if (!openReadOnly(dbPath, &db)) return 0;

    // handle.ROWID is what message.handle_id points at; join it so the
    // counterpart number is a phone number, not an internal id.
    const char* sql =
        "SELECT m.ROWID, m.guid, m.text, m.subject, m.date, m.is_from_me, "
        "       m.service, m.attributedBody, h.id "
        "FROM message m LEFT JOIN handle h ON h.ROWID = m.handle_id "
        "ORDER BY m.date ASC";

    int inserted = 0;
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return 0;
    }
    while (sqlite3_step(statement) == SQLITE_ROW) {
        const long long rawDate = columnInt64(statement, 4);
        std::string body = columnText(statement, 2);
        if (body.empty()) {
            // Modern iOS stores the body in attributedBody when text is null.
            const void* blob = sqlite3_column_blob(statement, 7);
            const int blobSize = sqlite3_column_bytes(statement, 7);
            if (blob && blobSize > 0) {
                body.assign(static_cast<const char*>(blob),
                            static_cast<std::size_t>(blobSize));
                std::replace_if(body.begin(), body.end(),
                                [](unsigned char c) { return !std::isprint(c) && c != '\n'; },
                                ' ');
            }
        }
        const std::string subject = columnText(statement, 3);
        if (!subject.empty()) {
            body = subject + "\n" + body;
        }
        const std::string handle = columnText(statement, 8);
        const std::string service = columnText(statement, 6);
        const bool fromMe = columnInt64(statement, 5) != 0;

        std::map<std::string, std::string> record;
        // The counterpart is the handle for inbound and outbound alike; keep
        // direction in `type` so the shared schema stays Android-shaped.
        record["address"] = handle.empty() ? service : handle;
        record["body"] = body;
        record["date"] = std::to_string(rawDate);
        record["date_seconds"] = std::to_string(toUnixSeconds(rawDate));
        record["type"] = fromMe ? "2" : "1";  // 1=inbox, 2=sent (Android convention)
        if (database.insertSMS(record)) ++inserted;
    }
    sqlite3_finalize(statement);
    sqlite3_close(db);
    return inserted;
}

// ------------------------------------------------------------ contacts

int parseContacts(const std::string& dbPath, AndroidAnalysisDatabase& database) {
    sqlite3* db = nullptr;
    if (!openReadOnly(dbPath, &db)) return 0;

    // Phone numbers live in ABMultiValue rows whose property is 3
    // (kABPersonPhoneProperty); 0 is the generic "other" multivalue.
    const char* sql =
        "SELECT p.ROWID, p.First, p.Last, p.Middle, p.Organization, p.Nickname, "
        "       p.JobTitle, p.Department, m.value "
        "FROM ABPerson p LEFT JOIN ABMultiValue m "
        "  ON m.record_id = p.ROWID AND m.property = 3 "
        "ORDER BY p.ROWID";

    int inserted = 0;
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return 0;
    }
    while (sqlite3_step(statement) == SQLITE_ROW) {
        std::string display;
        for (int index : {1, 2, 3}) {
            const std::string part = columnText(statement, index);
            if (part.empty()) continue;
            if (!display.empty()) display += " ";
            display += part;
        }
        if (display.empty()) display = columnText(statement, 4);  // organization
        const std::string nickname = columnText(statement, 5);
        if (display.empty()) display = nickname;
        if (display.empty()) display = columnText(statement, 6);  // job title
        if (display.empty()) display = columnText(statement, 7);  // department
        if (display.empty()) continue;

        std::map<std::string, std::string> record;
        record["display_name"] = display;
        record["phone"] = columnText(statement, 8);
        if (database.insertContact(record)) ++inserted;
    }
    sqlite3_finalize(statement);
    sqlite3_close(db);
    return inserted;
}

// --------------------------------------------------------------- notes

int parseNotes(const std::string& dbPath, AndroidAnalysisDatabase& database) {
    sqlite3* db = nullptr;
    if (!openReadOnly(dbPath, &db)) return 0;

    int inserted = 0;
    if (tableExists(db, "ZICCLOUDSYNCINGOBJECT")) {
        // iOS 15+ note store.
        const char* sql =
            "SELECT Z_PK, ZTITLE1, ZSNIPPET, ZIDENTIFIER FROM ZICCLOUDSYNCINGOBJECT "
            "WHERE ZTITLE1 IS NOT NULL OR ZSNIPPET IS NOT NULL LIMIT 50000";
        sqlite3_stmt* statement = nullptr;
        if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
            while (sqlite3_step(statement) == SQLITE_ROW) {
                const std::string title = columnText(statement, 1);
                const std::string snippet = columnText(statement, 2);
                const std::string identifier = columnText(statement, 3);
                if (title.empty() && snippet.empty()) continue;
                if (database.insertAppNote("com.apple.mobilenotes",
                                           identifier.empty()
                                               ? std::to_string(columnInt64(statement, 0))
                                               : identifier,
                                           title, snippet, "", false, dbPath)) {
                    ++inserted;
                }
            }
            sqlite3_finalize(statement);
        }
    } else if (tableExists(db, "ZNOTE")) {
        // Legacy note store (iOS 9-14) keeps body in ZNOTEBODY.
        const char* sql =
            "SELECT n.Z_PK, n.ZTITLE, b.ZCONTENT, n.ZGUID FROM ZNOTE n "
            "LEFT JOIN ZNOTEBODY b ON b.ZOWNER = n.Z_PK "
            "WHERE n.ZTITLE IS NOT NULL OR b.ZCONTENT IS NOT NULL LIMIT 50000";
        sqlite3_stmt* statement = nullptr;
        if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
            while (sqlite3_step(statement) == SQLITE_ROW) {
                const std::string title = columnText(statement, 1);
                const std::string content = columnText(statement, 2);
                const std::string guid = columnText(statement, 3);
                if (title.empty() && content.empty()) continue;
                if (database.insertAppNote("com.apple.mobilenotes",
                                           guid.empty()
                                               ? std::to_string(columnInt64(statement, 0))
                                               : guid,
                                           title, content, "", false, dbPath)) {
                    ++inserted;
                }
            }
            sqlite3_finalize(statement);
        }
    }
    sqlite3_close(db);
    return inserted;
}

// ------------------------------------------------------------ calendar

int parseCalendar(const std::string& dbPath, AndroidAnalysisDatabase& database) {
    sqlite3* db = nullptr;
    if (!openReadOnly(dbPath, &db)) return 0;

    int inserted = 0;
    if (tableExists(db, "CalendarItem")) {
        const char* sql =
            "SELECT ROWID, summary, description, start_date, end_date, location "
            "FROM CalendarItem ORDER BY start_date ASC LIMIT 50000";
        sqlite3_stmt* statement = nullptr;
        if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
            while (sqlite3_step(statement) == SQLITE_ROW) {
                const std::string summary = columnText(statement, 1);
                const std::string description = columnText(statement, 2);
                if (summary.empty() && description.empty()) continue;
                const std::string location = columnText(statement, 5);
                std::string body = description;
                if (!location.empty()) {
                    if (!body.empty()) body += "\n";
                    body += "地点：" + location;
                }
                const long long start = toUnixSeconds(columnInt64(statement, 3));
                const long long end = toUnixSeconds(columnInt64(statement, 4));
                if (!end) {
                    // Fall through: still record the item with its start time.
                }
                if (database.insertAppNote("com.apple.mobilecal",
                                           std::to_string(columnInt64(statement, 0)),
                                           summary, body, "", false, dbPath)) {
                    ++inserted;
                }
                (void)start;
            }
            sqlite3_finalize(statement);
        }
    }
    sqlite3_close(db);
    return inserted;
}

// ------------------------------------------------------------ call history

int parseCallHistory(const std::string& dbPath, AndroidAnalysisDatabase& database) {
    sqlite3* db = nullptr;
    if (!openReadOnly(dbPath, &db)) return 0;

    int inserted = 0;
    // CallHistory.storedata is a Core Data store. Column names carry the
    // Z-prefix; the record table is ZCALLRECORD on every iOS version that
    // ships the store. Older builds name the address column differently, so
    // resolve the columns once instead of guessing per row.
    if (tableExists(db, "ZCALLRECORD")) {
        const auto columns = tableColumns(db, "ZCALLRECORD");
        const std::string addressColumn =
            columns.count("ZADDRESS") ? "ZADDRESS"
            : columns.count("ZREMOTEPARTICIPANT") ? "ZREMOTEPARTICIPANT"
            : "";
        const std::string dateColumn = columns.count("ZDATE") ? "ZDATE" : "";
        const std::string durationColumn = columns.count("ZDURATION") ? "ZDURATION" : "";
        const std::string typeColumn = columns.count("ZCALLTYPE") ? "ZCALLTYPE" : "";
        if (!addressColumn.empty() && !dateColumn.empty()) {
            const std::string sql =
                "SELECT " + addressColumn + ", " + dateColumn +
                (durationColumn.empty() ? ", 0" : ", " + durationColumn) +
                (typeColumn.empty() ? ", 0" : ", " + typeColumn) +
                " FROM ZCALLRECORD ORDER BY " + dateColumn + " ASC LIMIT 100000";
            sqlite3_stmt* statement = nullptr;
            if (sqlite3_prepare_v2(db, sql.c_str(), -1, &statement, nullptr) == SQLITE_OK) {
                while (sqlite3_step(statement) == SQLITE_ROW) {
                    const long long rawDate = columnInt64(statement, 1);
                    double duration = 0.0;
                    if (sqlite3_column_type(statement, 2) != SQLITE_NULL) {
                        duration = sqlite3_column_double(statement, 2);
                    }
                    std::map<std::string, std::string> record;
                    record["number"] = columnText(statement, 0);
                    record["date"] = std::to_string(rawDate);
                    record["date_seconds"] = std::to_string(toUnixSeconds(rawDate));
                    // Core Data stores call duration as a float; the shared
                    // schema wants whole seconds.
                    record["duration"] = std::to_string(static_cast<long long>(duration));
                    record["type"] = std::to_string(columnInt64(statement, 3));
                    if (database.insertCallLog(record)) ++inserted;
                }
                sqlite3_finalize(statement);
            }
        }
    }
    sqlite3_close(db);
    return inserted;
}

// ------------------------------------------------------------ safari history

int parseSafariHistory(const std::string& dbPath, AndroidAnalysisDatabase& database) {
    sqlite3* db = nullptr;
    if (!openReadOnly(dbPath, &db)) return 0;

    int inserted = 0;
    // Safari's History.db pairs `history_items` (one row per URL) with
    // `history_visits` (one row per visit). The visit timestamp is Apple-epoch
    // seconds; visit_count is derived by aggregating visits.
    if (tableExists(db, "history_items")) {
        const bool hasVisits = tableExists(db, "history_visits");
        const std::string sql = hasVisits
            ? "SELECT i.url, i.title, COUNT(v.id), MAX(v.visit_time) "
              "FROM history_items i LEFT JOIN history_visits v "
              "  ON v.history_item = i.id "
              "GROUP BY i.id ORDER BY MAX(v.visit_time) DESC LIMIT 100000"
            : "SELECT url, title, 0, 0 FROM history_items LIMIT 100000";
        sqlite3_stmt* statement = nullptr;
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &statement, nullptr) == SQLITE_OK) {
            while (sqlite3_step(statement) == SQLITE_ROW) {
                ChromeHistoryItem item;
                item.url = columnText(statement, 0);
                item.title = columnText(statement, 1);
                item.visitCount = columnInt64(statement, 2);
                item.lastVisitTime = toUnixSeconds(columnInt64(statement, 3));
                if (item.url.empty()) continue;
                if (database.insertChromeHistory(item)) ++inserted;
            }
            sqlite3_finalize(statement);
        }
    }
    sqlite3_close(db);
    return inserted;
}

// ------------------------------------------------------- installed apps

int recordInstalledApps(IosBackupExtractor& extractor, AndroidAnalysisDatabase& database) {
    // Any AppDomain-<bundle id> / AppDomainGroup-<group id> /
    // AppDomainPlugin-<bundle id> domain belongs to an app whose data was
    // actually captured. That is the honest iOS analogue of a package
    // inventory: it lists what the backup contains, not what the device had
    // installed. Group and plugin domains are attributed to their owning
    // bundle id so the count matches the app-level view.
    int recorded = 0;
    std::map<std::string, std::size_t> bundles;
    for (const std::string& domain : extractor.domains()) {
        std::string bundle;
        if (domain.rfind("AppDomainPlugin-", 0) == 0) {
            bundle = domain.substr(std::strlen("AppDomainPlugin-"));
        } else if (domain.rfind("AppDomain-", 0) == 0) {
            bundle = domain.substr(std::strlen("AppDomain-"));
        } else {
            continue;
        }
        if (bundle.empty()) continue;
        bundles[bundle] += extractor.listDomain(domain).size();
    }
    for (const auto& [bundle, members] : bundles) {
        InstalledPackageInfo package;
        package.packageName = bundle;
        package.codePath = "AppDomain-" + bundle;
        package.version = "";
        package.installer = "ios-backup";
        if (database.insertInstalledPackage(package)) {
            ++recorded;
            (void)members;
        }
    }
    return recorded;
}

void recordManifest(IosBackupExtractor& extractor, AndroidAnalysisDatabase& database) {
    sqlite3* dest = database.handle();
    if (!dest) return;
    // Reuse the vendor-neutral one-row manifest the UI already reads, so an
    // iOS task shows its device identity without a separate query path.
    if (sqlite3_exec(dest, mobile_backup_schema::DDL, nullptr, nullptr, nullptr) != SQLITE_OK) {
        return;
    }
    const auto& device = extractor.device();
    const auto value = [&device](const std::string& key) {
        const auto found = device.find(key);
        return found == device.end() ? std::string() : found->second;
    };
    const std::string model = value("product_type");
    const std::string osVersion = value("product_version");
    std::string label = model;
    if (!osVersion.empty()) label += " / iOS " + osVersion;

    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(dest,
            "INSERT OR REPLACE INTO mobile_backup_manifest VALUES(1,?,?,?,?,?,?,?)",
            -1, &statement, nullptr) != SQLITE_OK) {
        return;
    }
    sqlite3_bind_text(statement, 1, "iOS", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, label.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 3, extractor.backupVersion().c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(statement, 4, 0);
    sqlite3_bind_int64(statement, 5, static_cast<sqlite3_int64>(extractor.applicationCount()));
    sqlite3_bind_text(statement, 6, extractor.manifestSha256().c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 7, "ios-backup-v1", -1, SQLITE_TRANSIENT);
    sqlite3_step(statement);
    sqlite3_finalize(statement);
}

}  // namespace

long long toUnixSeconds(long long raw) {
    if (raw <= 0) return 0;
    // Apple-epoch nanoseconds: a 2023 stamp is ~7.15e17.
    if (raw > 100'000'000'000'000LL) return raw / 1'000'000'000LL + kAppleEpochOffset;
    // Apple-epoch seconds (~7.15e8) versus Unix seconds (>=9.8e8).
    if (raw < 1'200'000'000LL) return raw + kAppleEpochOffset;
    return raw;
}

std::string classifyTimestamp(long long raw) {
    if (raw <= 0) return "unix_s";
    if (raw > 100'000'000'000'000LL) return "apple_epoch_ns";
    if (raw < 1'200'000'000LL) return "apple_epoch_s";
    return "unix_s";
}

IosParseResult analyzeIosBackup(IosBackupExtractor& extractor,
                                AndroidAnalysisDatabase& database,
                                const std::string& secureTempRoot) {
    IosParseResult result;

    for (const SourceSpec& source : kSources) {
        const std::string logical = source.logicalPath;
        if (extractor.shardPathFor(logical).empty()) {
            // Absent from the backup: record why, and do not claim parsing.
            database.recordSourceCoverage(
                source.kind, logical, "no_candidate_path",
                "Backup index has no entry for this path; not evidence of absence");
            continue;
        }

        std::string staged;
        if (!stage(nullptr, extractor, logical, secureTempRoot, &staged)) {
            database.recordSourceCoverage(source.kind, logical, "extract_failed",
                                          "Manifest entry exists but shard could not be copied");
            ++result.failures;
            continue;
        }
        stageSidecars(extractor, logical, staged);

        int parsed = 0;
        if (std::strcmp(source.kind, "sms") == 0) {
            parsed = parseSms(staged, database);
        } else if (std::strcmp(source.kind, "contacts") == 0) {
            parsed = parseContacts(staged, database);
        } else if (std::strcmp(source.kind, "notes") == 0) {
            parsed = parseNotes(staged, database);
        } else if (std::strcmp(source.kind, "calendar") == 0) {
            parsed = parseCalendar(staged, database);
        } else if (std::strcmp(source.kind, "call_logs") == 0) {
            parsed = parseCallHistory(staged, database);
        } else if (std::strcmp(source.kind, "safari") == 0) {
            parsed = parseSafariHistory(staged, database);
        }
        cleanup(staged);

        if (parsed > 0) {
            database.recordSourceCoverage(source.kind, logical, "PARSED",
                                          std::to_string(parsed) + " record(s) parsed");
        } else {
            // Zero rows is not a parse failure: the store may simply be empty.
            // Say which it is so a reader does not mistake silence for a bug.
            database.recordSourceCoverage(
                source.kind, logical, "staged_for_parser",
                "Source staged; the store returned no rows "
                "(empty table, or a schema variant this parser does not cover)");
        }

        if (std::strcmp(source.kind, "sms") == 0) result.sms = parsed;
        else if (std::strcmp(source.kind, "contacts") == 0) result.contacts = parsed;
        else if (std::strcmp(source.kind, "notes") == 0) result.notes = parsed;
        else if (std::strcmp(source.kind, "calendar") == 0) result.calendar = parsed;
        else if (std::strcmp(source.kind, "call_logs") == 0) result.callLogs = parsed;
        else if (std::strcmp(source.kind, "safari") == 0) result.safariHistory = parsed;
    }

    result.installedApps = recordInstalledApps(extractor, database);
    recordManifest(extractor, database);

    for (const AndroidSourceProvenance& provenance : extractor.usedSourceProvenance()) {
        database.insertSourceProvenance(provenance);
    }
    return result;
}

}  // namespace ios_artifacts
