#include "MiuiArtifactParsers.h"
#include "QqntArtifactParsers.h"
#include "WechatArtifactParsers.h"

#include "AndroidAnalysisDatabase.h"
#include "MiuiBackupExtractor.h"

#include <sqlite3.h>

#ifndef _WIN32
#include <unistd.h>
#endif

#include <array>
#include <atomic>
#include <cstring>
#include <charconv>
#include <chrono>
#include <cstdlib>
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
constexpr size_t kMaximumCandidateDatabases = 100000;
constexpr uint64_t kMaximumGlobalInventoryRows = 50000000;
constexpr uint64_t kMaximumGlobalNameBytes = 256ULL * 1024 * 1024;
constexpr uint64_t kMaximumGlobalSqliteInstructions = 2000000000ULL;
constexpr int kSqliteLengthLimit = 64 * 1024 * 1024;
constexpr int kSqliteColumnLimit = 2048;
constexpr int kSqliteSqlLengthLimit = 1024 * 1024;
constexpr int kProgressInterval = 1000;
constexpr int kMaximumQueryInstructions = 2000000;
constexpr size_t kMaximumSerializedColumnsBytes = 4096;
constexpr size_t kHeaderBytes = 16;
constexpr const char* kInventoryLimitEnvironment = "TRACELENS_MIUI_MAX_CANDIDATES";

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

    bool create(const fs::path& root) {
        std::error_code error;
        if (root.empty() || !fs::is_directory(root, error) || error) return false;

#ifndef _WIN32
        std::string pattern = (root / "tracelens-miui-inventory-XXXXXX").string();
        std::vector<char> writablePattern(pattern.begin(), pattern.end());
        writablePattern.push_back('\0');
        char* created = mkdtemp(writablePattern.data());
        if (!created) {
            return false;
        }
        path_ = fs::path(created);
        return true;
#else
        static std::atomic_uint64_t serial{0};
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
            path_ = std::move(candidate);
            return true;
        }
        return false;
#endif
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

struct InventoryBudget {
    uint64_t rows = 0;
    uint64_t nameBytes = 0;
    uint64_t instructions = 0;
};

struct InstructionBudget {
    int remaining = kMaximumQueryInstructions;
    InventoryBudget* global = nullptr;
};

int consumeInstructionBudget(void* context) {
    auto* budget = static_cast<InstructionBudget*>(context);
    budget->remaining -= kProgressInterval;
    if (budget->global) {
        budget->global->instructions += kProgressInterval;
        if (budget->global->instructions > kMaximumGlobalSqliteInstructions) return 1;
    }
    return budget->remaining <= 0 ? 1 : 0;
}

size_t candidateLimit() {
    const char* configured = std::getenv(kInventoryLimitEnvironment);
    if (!configured || *configured == '\0') return kMaximumCandidateDatabases;
    uint64_t parsed = 0;
    const char* end = configured + std::char_traits<char>::length(configured);
    const auto [parsedEnd, error] = std::from_chars(configured, end, parsed, 10);
    if (error != std::errc{} || parsedEnd != end || parsed == 0 ||
        parsed > kMaximumCandidateDatabases) {
        return kMaximumCandidateDatabases;
    }
    return static_cast<size_t>(parsed);
}

bool isSidecar(const std::string& memberName) {
    const auto endsWith = [&](const char* suffix) {
        const size_t length = std::char_traits<char>::length(suffix);
        return memberName.size() >= length &&
               memberName.compare(memberName.size() - length, length, suffix) == 0;
    };
    return endsWith("-wal") || endsWith("-shm") || endsWith("-journal");
}

bool isMiuiWeChatDatabaseMemberName(const std::string& memberName) {
    constexpr char prefix[] = "apps/com.tencent.mm/";
    constexpr char suffix[] = "/EnMicroMsg.db";
    if (memberName.rfind(prefix, 0) != 0 || isSidecar(memberName)) {
        return false;
    }

    const std::string tail = memberName.substr(sizeof(prefix) - 1);
    const bool isRTree = tail.rfind("r/MicroMsg/", 0) == 0;
    const bool isDbTree = tail.rfind("db/", 0) == 0;
    if ((!isRTree && !isDbTree) || tail.size() < sizeof(suffix) - 1) {
        return false;
    }
    return tail.compare(tail.size() - (sizeof(suffix) - 1), sizeof(suffix) - 1,
                        suffix) == 0;
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

    packageName = memberName.substr(packageStart, packageEnd - packageStart);
    const std::string tail = memberName.substr(packageEnd + 1);
    // WeChat stores its per-account SQLCipher database below r/MicroMsg in
    // some MIUI exports rather than the conventional db/ directory.
    if (packageName == "com.tencent.mm" && isMiuiWeChatDatabaseMemberName(memberName)) {
        return true;
    }

    const std::string databasePrefix = "db/";
    if (tail.rfind(databasePrefix, 0) != 0 || tail.size() == databasePrefix.size()) {
        return false;
    }
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
#ifndef _WIN32
    std::string pattern = path.string() + ".XXXXXX";
    std::vector<char> writablePattern(pattern.begin(), pattern.end());
    writablePattern.push_back('\0');
    const int descriptor = mkstemp(writablePattern.data());
    if (descriptor == -1) {
        return false;
    }
    if (close(descriptor) != 0) {
        std::remove(writablePattern.data());
        return false;
    }
    std::error_code error;
    fs::rename(fs::path(writablePattern.data()), path, error);
    if (error) {
        std::remove(writablePattern.data());
        return false;
    }
    return true;
#else
    std::error_code statusError;
    if (fs::exists(fs::symlink_status(path, statusError)) || statusError) {
        return false;
    }
    std::ofstream output(path, std::ios::binary | std::ios::out);
    if (!output) {
        return false;
    }
    output.close();
    std::error_code permissionError;
    fs::permissions(path, fs::perms::owner_read | fs::perms::owner_write,
                    fs::perm_options::replace, permissionError);
    if (permissionError) {
        fs::remove(path, permissionError);
        return false;
    }
    return true;
#endif
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
    const int flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX;
    if (sqlite3_open_v2(path.string().c_str(), output, flags, nullptr) != SQLITE_OK) {
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

bool tableRowCount(sqlite3* connection, const std::string& tableName, uint64_t& count,
                   InventoryBudget& globalBudget) {
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
    budget.global = &globalBudget;
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
    if (result != SQLITE_DONE || globalBudget.rows > kMaximumGlobalInventoryRows - count) {
        count = 0;
        return false;
    }
    globalBudget.rows += count;
    return true;
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
        const std::string name = columnText(statement.get(), 0);
        const size_t separatorBytes = columns.empty() ? 0 : 1;
        if (name.size() > kMaximumSerializedColumnsBytes - separatorBytes ||
            columns.size() > kMaximumSerializedColumnsBytes - separatorBytes - name.size()) {
            columns.clear();
            return false;
        }
        if (separatorBytes != 0) {
            columns.push_back(',');
        }
        columns += name;
    }
    return result == SQLITE_DONE;
}

bool recordFailure(AndroidAnalysisDatabase& database, const std::string& packageName,
                   const std::string& memberName, const std::string& status) {
    return database.insertAppDbInventory(packageName, memberName, "", 0, "", status);
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

bool inventoryExtractedDatabase(const fs::path& extractedPath,
                                const std::string& packageName,
                                const std::string& memberName,
                                AndroidAnalysisDatabase& database,
                                InventoryBudget& globalBudget) {
    if (!hasSqliteHeader(extractedPath)) {
        const bool wechatCipherDatabase = isMiuiWeChatDatabaseMemberName(memberName);
        return recordFailure(database, packageName, memberName,
                             wechatCipherDatabase ? "encrypted_locked" : "parse_error");
    }

    sqlite3* rawConnection = nullptr;
    if (!openEvidenceDatabase(extractedPath, &rawConnection)) {
        return recordFailure(database, packageName, memberName, "parse_error");
    }
    SqliteConnection connection(rawConnection, sqlite3_close);

    sqlite3_stmt* rawTables = nullptr;
    const char* tableSql =
        "SELECT name FROM sqlite_schema "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name";
    if (sqlite3_prepare_v2(connection.get(), tableSql, -1, &rawTables, nullptr) != SQLITE_OK) {
        return recordFailure(database, packageName, memberName, "parse_error");
    }
    SqliteStatement tables(rawTables, sqlite3_finalize);

    size_t tableCount = 0;
    bool insertedTable = false;
    int result = SQLITE_ROW;
    while ((result = sqlite3_step(tables.get())) == SQLITE_ROW) {
        if (++tableCount > kMaximumInventoryTables) {
            return recordFailure(database, packageName, memberName, "incomplete_limit");
        }

        const std::string tableName = columnText(tables.get(), 0);
        if (globalBudget.nameBytes > kMaximumGlobalNameBytes - tableName.size()) {
            return recordFailure(database, packageName, memberName, "incomplete_limit");
        }
        globalBudget.nameBytes += tableName.size();
        uint64_t rowCount = 0;
        std::string columns;
        if (!tableRowCount(connection.get(), tableName, rowCount, globalBudget)) {
            return recordFailure(database, packageName, memberName, "incomplete_limit");
        }
        if (!tableColumns(connection.get(), tableName, columns)) {
            return recordFailure(database, packageName, memberName, "parse_error");
        }
        if (!database.insertAppDbInventory(packageName, memberName, tableName,
                                           rowCount, columns, "decrypted")) {
            return false;
        }
        insertedTable = true;
    }

    if (result != SQLITE_DONE) {
        return recordFailure(database, packageName, memberName, "parse_error");
    }
    if (!insertedTable) {
        return database.insertAppDbInventory(packageName, memberName, "", 0, "", "decrypted");
    }
    return true;
}

}  // namespace

bool isMiuiWeChatDatabaseMember(const std::string& memberName) {
    return isMiuiWeChatDatabaseMemberName(memberName);
}

bool writeMiuiManifestRows(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    const BackupMeta& manifest = src.manifest();
    bool success = db.insertMiuiBackupManifest(
        manifest.device, manifest.miuiVersion, manifest.date, manifest.totalSize,
        static_cast<int>(manifest.packages.size()), manifest.sourceFolder);

    for (size_t packageIndex = 0; packageIndex < manifest.packages.size(); ++packageIndex) {
        if (!success) break;
        if (!src.hasUniqueManifestBakFile(packageIndex)) continue;
        const BackupPackage& package = manifest.packages[packageIndex];
        success = db.insertInstalledApp(package.packageName, "", "", "",
                                        package.pkgSize, package.sdSize,
                                        package.bakType, "");
    }
    return success;
}

bool writeAppDbInventoryRows(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    bool success = true;
    for (const auto& failure : src.packageFailures()) {
        if (!recordFailure(db, failure.packageName, failure.bakFile, failure.openStatus)) {
            success = false;
            break;
        }
    }

    if (!success) return false;

    std::vector<std::string> entries;
    std::vector<std::string> databaseCandidates;
    std::unordered_set<std::string> entrySet;
    src.enumerateEntryDetails([&](const std::string& memberName, const std::string&,
                                  const TarEntry& entry) {
        entries.push_back(memberName);
        entrySet.insert(memberName);

        std::string packageName;
        if (entry.isRegularFile() && isPrimaryDatabaseMember(memberName, packageName)) {
            databaseCandidates.push_back(memberName);
        }
    });

    bool wechatDatabaseFound = false;
    for (const auto& memberName : databaseCandidates) {
        if (isMiuiWeChatDatabaseMemberName(memberName)) {
            wechatDatabaseFound = true;
            break;
        }
    }
    bool wechatFailureRecorded = false;
    for (const auto& failure : src.packageFailures()) {
        if (failure.packageName == "com.tencent.mm") {
            wechatFailureRecorded = true;
            break;
        }
    }
    bool wechatPackageListed = false;
    for (const auto& package : src.manifest().packages) {
        if (package.packageName == "com.tencent.mm") {
            wechatPackageListed = true;
            break;
        }
    }
    // Keep the generic inventory explicit when the manifest says WeChat was
    // backed up but no database entry was recoverable. Do not add a synthetic
    // row to unrelated backups that do not contain the WeChat package.
    if (wechatPackageListed && !wechatDatabaseFound && !wechatFailureRecorded &&
        !recordFailure(db, "com.tencent.mm", "MIUI_WECHAT_DISCOVERY", "not_found")) {
        return false;
    }

    TemporaryDirectory temporaryDirectory;
    if (!temporaryDirectory.create(src.temporaryRoot())) {
        for (const auto& memberName : databaseCandidates) {
            std::string packageName;
            if (isPrimaryDatabaseMember(memberName, packageName) &&
                !recordFailure(db, packageName, memberName, "parse_error")) {
                success = false;
                break;
            }
        }
        return success;
    }

    const size_t maximumCandidates = candidateLimit();
    uint64_t sequence = 0;
    size_t candidateCount = 0;
    InventoryBudget inventoryBudget;
    for (const auto& memberName : databaseCandidates) {
        std::string packageName;
        if (!isPrimaryDatabaseMember(memberName, packageName)) {
            continue;
        }
        if (++candidateCount > maximumCandidates ||
            inventoryBudget.nameBytes > kMaximumGlobalNameBytes - memberName.size() ||
            inventoryBudget.nameBytes + memberName.size() > kMaximumGlobalNameBytes - packageName.size()) {
            success = recordFailure(db, packageName, memberName, "incomplete_limit");
            break;
        }
        inventoryBudget.nameBytes += memberName.size() + packageName.size();

        TemporaryBundle bundle(temporaryDirectory.path() /
                               ("database-" + std::to_string(sequence++) + ".db"));
        if (!extractDatabaseBundle(src, entrySet, memberName, bundle)) {
            if (!recordFailure(db, packageName, memberName, "parse_error")) {
                success = false;
                break;
            }
            continue;
        }
        if (!inventoryExtractedDatabase(bundle.basePath(), packageName, memberName,
                                        db, inventoryBudget)) {
            success = false;
            break;
        }
    }
    return success;
}

bool writeMiuiManifest(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    if (!db.beginTransaction()) return false;
    if (writeMiuiManifestRows(src, db) && db.commitTransaction()) return true;
    db.rollbackTransaction();
    return false;
}

bool writeAppDbInventory(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    if (!db.beginTransaction()) return false;
    if (writeAppDbInventoryRows(src, db) && db.commitTransaction()) return true;
    db.rollbackTransaction();
    return false;
}

bool persistMiuiBackupAnalysis(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    if (!db.beginTransaction()) return false;
    if (writeMiuiManifestRows(src, db) && writeAppDbInventoryRows(src, db) &&
        persistQqntBackupAnalysis(src, db) && persistWechatBackupAnalysis(src, db) &&
        db.commitTransaction()) {
        return true;
    }
    db.rollbackTransaction();
    return false;
}
