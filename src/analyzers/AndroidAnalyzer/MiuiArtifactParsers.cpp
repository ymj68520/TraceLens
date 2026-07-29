#include "MiuiArtifactParsers.h"

#include "AndroidAnalysisDatabase.h"
#include "MiuiBackupExtractor.h"

#include <sqlite3.h>

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <system_error>
#include <unordered_set>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr uint64_t kMaximumExtractedDatabaseBytes = 512ULL * 1024 * 1024;
constexpr uint64_t kMaximumBundleBytes = 768ULL * 1024 * 1024;
constexpr uint64_t kMaximumInventoryRows = 10000;
constexpr size_t kMaximumInventoryTables = 10000;
constexpr int kSqliteLengthLimit = 64 * 1024 * 1024;
constexpr int kSqliteColumnLimit = 2048;
constexpr int kSqliteSqlLengthLimit = 1024 * 1024;
constexpr int kProgressInterval = 1000;
constexpr int kMaximumQueryInstructions = 2000000;
constexpr size_t kHeaderBytes = 16;

using SqliteConnection = std::unique_ptr<sqlite3, decltype(&sqlite3_close)>;
using SqliteStatement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;

class TemporaryDirectory {
public:
    TemporaryDirectory() = default;
    ~TemporaryDirectory() {
        if (!path_.empty()) {
            std::error_code error;
            fs::remove_all(path_, error);
        }
    }

    TemporaryDirectory(const TemporaryDirectory&) = delete;
    TemporaryDirectory& operator=(const TemporaryDirectory&) = delete;

    bool create() {
        static std::atomic_uint64_t serial{0};
        std::error_code error;
        const fs::path root = fs::temp_directory_path(error);
        if (error) {
            return false;
        }

        for (unsigned attempt = 0; attempt < 64; ++attempt) {
            const auto timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
            fs::path candidate = root /
                ("tracelens-miui-inventory-" + std::to_string(timestamp) + "-" +
                 std::to_string(serial.fetch_add(1, std::memory_order_relaxed)));
            error.clear();
            if (!fs::create_directory(candidate, error)) {
                if (error && error != std::errc::file_exists) {
                    return false;
                }
                continue;
            }

            fs::permissions(candidate, fs::perms::owner_all,
                            fs::perm_options::replace, error);
            if (error) {
                fs::remove(candidate, error);
                return false;
            }
            path_ = std::move(candidate);
            return true;
        }
        return false;
    }

    const fs::path& path() const { return path_; }

private:
    fs::path path_;
};

class TemporaryBundle {
public:
    explicit TemporaryBundle(fs::path basePath) : basePath_(std::move(basePath)) {}
    ~TemporaryBundle() {
        for (const auto& path : paths_) {
            std::error_code error;
            fs::remove(path, error);
        }
    }

    const fs::path& basePath() const { return basePath_; }

    void track(const fs::path& path) { paths_.push_back(path); }

private:
    fs::path basePath_;
    std::vector<fs::path> paths_;
};

struct InstructionBudget {
    int remaining = kMaximumQueryInstructions;
};

int consumeInstructionBudget(void* context) {
    auto* budget = static_cast<InstructionBudget*>(context);
    budget->remaining -= kProgressInterval;
    return budget->remaining <= 0 ? 1 : 0;
}

bool isSidecar(const std::string& memberName) {
    const auto endsWith = [&](const char* suffix) {
        const size_t length = std::char_traits<char>::length(suffix);
        return memberName.size() >= length &&
               memberName.compare(memberName.size() - length, length, suffix) == 0;
    };
    return endsWith("-wal") || endsWith("-shm") || endsWith("-journal");
}

bool isPrimaryDatabaseMember(const std::string& memberName, std::string& packageName) {
    constexpr char prefix[] = "apps/";
    if (memberName.rfind(prefix, 0) != 0 || isSidecar(memberName)) {
        return false;
    }

    const size_t packageStart = sizeof(prefix) - 1;
    const size_t packageEnd = memberName.find('/', packageStart);
    if (packageEnd == std::string::npos || packageEnd == packageStart) {
        return false;
    }

    const std::string databasePrefix = memberName.substr(0, packageEnd + 1) + "db/";
    if (memberName.rfind(databasePrefix, 0) != 0 ||
        memberName.size() == databasePrefix.size()) {
        return false;
    }

    packageName = memberName.substr(packageStart, packageEnd - packageStart);
    return true;
}

bool hasSqliteHeader(const fs::path& path) {
    static constexpr std::array<char, kHeaderBytes> expected = {
        'S', 'Q', 'L', 'i', 't', 'e', ' ', 'f', 'o', 'r', 'm', 'a', 't', ' ', '3', '\0'
    };

    std::ifstream input(path, std::ios::binary);
    std::array<char, kHeaderBytes> actual{};
    input.read(actual.data(), static_cast<std::streamsize>(actual.size()));
    return input.gcount() == static_cast<std::streamsize>(actual.size()) && actual == expected;
}

std::string columnText(sqlite3_stmt* statement, int column) {
    const unsigned char* value = sqlite3_column_text(statement, column);
    return value ? reinterpret_cast<const char*>(value) : std::string{};
}

bool makePrivateFile(const fs::path& path) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        return false;
    }
    output.close();

    std::error_code error;
    fs::permissions(path, fs::perms::owner_read | fs::perms::owner_write,
                    fs::perm_options::replace, error);
    if (error) {
        fs::remove(path, error);
        return false;
    }
    return true;
}

bool extractBoundedMember(MiuiBackupExtractor& src, const std::string& memberName,
                          const fs::path& outputPath, uint64_t maximumBytes,
                          uint64_t& extractedBytes) {
    uint64_t size = 0;
    if (!src.entrySize(memberName, size) || size > maximumBytes ||
        extractedBytes > kMaximumBundleBytes - size) {
        return false;
    }
    if (!makePrivateFile(outputPath) ||
        !src.extractTarMember(memberName, outputPath.string())) {
        std::error_code error;
        fs::remove(outputPath, error);
        return false;
    }
    extractedBytes += size;
    return true;
}

bool openEvidenceDatabase(const fs::path& path, sqlite3** output) {
    *output = nullptr;
    const std::string uri = "file:" + path.string() + "?mode=ro";
    const int flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI | SQLITE_OPEN_NOMUTEX;
    if (sqlite3_open_v2(uri.c_str(), output, flags, nullptr) != SQLITE_OK) {
        if (*output) {
            sqlite3_close(*output);
            *output = nullptr;
        }
        return false;
    }

    sqlite3_limit(*output, SQLITE_LIMIT_LENGTH, kSqliteLengthLimit);
    sqlite3_limit(*output, SQLITE_LIMIT_SQL_LENGTH, kSqliteSqlLengthLimit);
    sqlite3_limit(*output, SQLITE_LIMIT_COLUMN, kSqliteColumnLimit);
    sqlite3_busy_timeout(*output, 1000);
    return true;
}

bool tableRowCount(sqlite3* connection, const std::string& tableName, uint64_t& count) {
    count = 0;
    char* quoted = sqlite3_mprintf("%w", tableName.c_str());
    if (!quoted) {
        return false;
    }
    const std::string query = "SELECT 1 FROM \"" + std::string(quoted) +
                              "\" LIMIT " +
                              std::to_string(kMaximumInventoryRows + 1);
    sqlite3_free(quoted);

    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(connection, query.c_str(), -1, &raw, nullptr) != SQLITE_OK) {
        return false;
    }
    SqliteStatement statement(raw, sqlite3_finalize);
    InstructionBudget budget;
    sqlite3_progress_handler(connection, kProgressInterval,
                             consumeInstructionBudget, &budget);

    int result = SQLITE_ROW;
    while ((result = sqlite3_step(statement.get())) == SQLITE_ROW) {
        ++count;
        if (count > kMaximumInventoryRows) {
            sqlite3_progress_handler(connection, 0, nullptr, nullptr);
            count = 0;
            return false;
        }
    }
    sqlite3_progress_handler(connection, 0, nullptr, nullptr);
    return result == SQLITE_DONE;
}

bool tableColumns(sqlite3* connection, const std::string& tableName, std::string& columns) {
    columns.clear();
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(connection,
                          "SELECT name FROM pragma_table_info(?) ORDER BY cid",
                          -1, &raw, nullptr) != SQLITE_OK) {
        return false;
    }
    SqliteStatement statement(raw, sqlite3_finalize);
    if (sqlite3_bind_text(statement.get(), 1, tableName.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK) {
        return false;
    }

    int result = SQLITE_ROW;
    while ((result = sqlite3_step(statement.get())) == SQLITE_ROW) {
        if (!columns.empty()) {
            columns.push_back(',');
        }
        columns += columnText(statement.get(), 0);
    }
    return result == SQLITE_DONE;
}

void recordFailure(AndroidAnalysisDatabase& database, const std::string& packageName,
                   const std::string& memberName, const std::string& status) {
    database.insertAppDbInventory(packageName, memberName, "", 0, "", status);
}

bool extractDatabaseBundle(MiuiBackupExtractor& src,
                           const std::unordered_set<std::string>& members,
                           const std::string& primaryMember,
                           TemporaryBundle& bundle) {
    uint64_t extractedBytes = 0;
    if (!extractBoundedMember(src, primaryMember, bundle.basePath(),
                              kMaximumExtractedDatabaseBytes, extractedBytes)) {
        return false;
    }
    bundle.track(bundle.basePath());

    for (const char* suffix : {"-wal", "-shm", "-journal"}) {
        const std::string sidecarMember = primaryMember + suffix;
        if (members.find(sidecarMember) == members.end()) {
            continue;
        }
        const fs::path sidecarPath = bundle.basePath().string() + suffix;
        if (!extractBoundedMember(src, sidecarMember, sidecarPath,
                                  kMaximumExtractedDatabaseBytes, extractedBytes)) {
            return false;
        }
        bundle.track(sidecarPath);
    }
    return true;
}

void inventoryExtractedDatabase(const fs::path& extractedPath,
                                const std::string& packageName,
                                const std::string& memberName,
                                AndroidAnalysisDatabase& database) {
    if (!hasSqliteHeader(extractedPath)) {
        recordFailure(database, packageName, memberName, "parse_error");
        return;
    }

    sqlite3* rawConnection = nullptr;
    if (!openEvidenceDatabase(extractedPath, &rawConnection)) {
        recordFailure(database, packageName, memberName, "encrypted_locked");
        return;
    }
    SqliteConnection connection(rawConnection, sqlite3_close);

    sqlite3_stmt* rawTables = nullptr;
    const char* tableSql =
        "SELECT name FROM sqlite_schema "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name";
    if (sqlite3_prepare_v2(connection.get(), tableSql, -1, &rawTables, nullptr) != SQLITE_OK) {
        recordFailure(database, packageName, memberName, "encrypted_locked");
        return;
    }
    SqliteStatement tables(rawTables, sqlite3_finalize);

    size_t tableCount = 0;
    bool insertedTable = false;
    int result = SQLITE_ROW;
    while ((result = sqlite3_step(tables.get())) == SQLITE_ROW) {
        if (++tableCount > kMaximumInventoryTables) {
            recordFailure(database, packageName, memberName, "parse_error");
            return;
        }

        const std::string tableName = columnText(tables.get(), 0);
        uint64_t rowCount = 0;
        std::string columns;
        if (!tableRowCount(connection.get(), tableName, rowCount) ||
            !tableColumns(connection.get(), tableName, columns)) {
            recordFailure(database, packageName, memberName, "parse_error");
            return;
        }
        database.insertAppDbInventory(packageName, memberName, tableName,
                                      rowCount, columns, "decrypted");
        insertedTable = true;
    }

    if (result != SQLITE_DONE) {
        recordFailure(database, packageName, memberName, "parse_error");
    } else if (!insertedTable) {
        database.insertAppDbInventory(packageName, memberName, "", 0, "", "decrypted");
    }
}

}  // namespace

void writeMiuiManifest(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    const BackupMeta& manifest = src.manifest();
    db.insertMiuiBackupManifest(manifest.device, manifest.miuiVersion, manifest.date,
                                manifest.totalSize,
                                static_cast<int>(manifest.packages.size()),
                                manifest.sourceFolder);

    for (const BackupPackage& package : manifest.packages) {
        db.insertInstalledApp(package.packageName, "", "", "",
                              package.pkgSize, package.sdSize, package.bakType, "");
    }
}

void writeAppDbInventory(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    for (const auto& failure : src.packageFailures()) {
        recordFailure(db, failure.packageName, failure.bakFile, failure.openStatus);
    }

    std::vector<std::string> entries;
    std::unordered_set<std::string> entrySet;
    src.enumerateEntries([&](const std::string& memberName, const std::string&) {
        entries.push_back(memberName);
        entrySet.insert(memberName);
    });

    TemporaryDirectory temporaryDirectory;
    if (!temporaryDirectory.create()) {
        for (const auto& memberName : entries) {
            std::string packageName;
            if (isPrimaryDatabaseMember(memberName, packageName)) {
                recordFailure(db, packageName, memberName, "parse_error");
            }
        }
        return;
    }

    uint64_t sequence = 0;
    for (const auto& memberName : entries) {
        std::string packageName;
        if (!isPrimaryDatabaseMember(memberName, packageName)) {
            continue;
        }

        TemporaryBundle bundle(temporaryDirectory.path() /
                               ("database-" + std::to_string(sequence++) + ".db"));
        if (!extractDatabaseBundle(src, entrySet, memberName, bundle)) {
            recordFailure(db, packageName, memberName, "parse_error");
            continue;
        }
        inventoryExtractedDatabase(bundle.basePath(), packageName, memberName, db);
    }
}
