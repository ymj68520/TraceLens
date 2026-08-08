// SceneDetector.cpp
// Platform-scenario auto-detection by probing the raw database's `files` table.
// See SceneDetector.h for the design rationale.

#include "SceneDetector.h"

#include <algorithm>
#include <sqlite3.h>

// Marker path patterns per platform. These mirror the artifact locations that
// each analyzer actually targets, so a positive hit is a strong signal that the
// platform's data is present and its analyzer will find something to process.
//
// Patterns are SQL LIKE expressions, matched against the `path` column of the
// `files` table. We use '%' wildcards to absorb partition-root / drive-letter
// prefixes (e.g. both "/data/data/..." and "C:/Users/..." style paths). Windows
// hives sometimes store paths with backslashes, so each Windows pattern is also
// tried with backslashes.
namespace {

struct Marker {
    ForensicScenario scenario;
    const char* like;  // SQL LIKE pattern
};

// Fixed tie-break priority when two scenarios match equal counts. Lower index =
// higher priority. Keeps results deterministic.
const ForensicScenario PRIORITY_ORDER[] = {
    ForensicScenario::ANDROID,
    ForensicScenario::WINDOWS,
    ForensicScenario::LINUX,
    ForensicScenario::SERVER_CLOUD,
};

const std::vector<Marker> MARKERS = {
    // --- Android: app data, system state, telephony providers ---
    {ForensicScenario::ANDROID, "%/data/data/com.android.%"},
    {ForensicScenario::ANDROID, "%/data/system/%"},
    {ForensicScenario::ANDROID, "%/data/media/%"},
    {ForensicScenario::ANDROID, "%/data/misc/%"},

    // --- Windows: registry hives, prefetch, system dirs ---
    {ForensicScenario::WINDOWS, "%/Windows/System32/config/%"},
    {ForensicScenario::WINDOWS, "%/Windows/Prefetch/%"},
    {ForensicScenario::WINDOWS, "%/Windows/System32/Tasks/%"},
    {ForensicScenario::WINDOWS, "%\\Windows\\System32\\config\\%"},
    {ForensicScenario::WINDOWS, "%\\Windows\\Prefetch\\%"},

    // --- Linux: logs, account files ---
    {ForensicScenario::LINUX, "/var/log/%"},
    {ForensicScenario::LINUX, "%/etc/passwd"},
    {ForensicScenario::LINUX, "%/etc/shadow"},
    {ForensicScenario::LINUX, "%/.bash_history"},

    // --- Server / Cloud: service configs, container/cloud runtimes ---
    {ForensicScenario::SERVER_CLOUD, "%/etc/nginx/%"},
    {ForensicScenario::SERVER_CLOUD, "%/etc/apache2/%"},
    {ForensicScenario::SERVER_CLOUD, "%/etc/httpd/%"},
    {ForensicScenario::SERVER_CLOUD, "%/var/lib/docker/%"},
    {ForensicScenario::SERVER_CLOUD, "%/etc/kubernetes/%"},
};

// Run `SELECT COUNT(*) FROM files WHERE path LIKE ? AND is_deleted=0`.
// Returns 0 on any error (treated as "no match" — safe default).
int countMatches(sqlite3* db, const std::string& likePattern) {
    const char* sql =
        "SELECT COUNT(*) FROM files WHERE path LIKE ? AND is_deleted=0;";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        if (stmt) sqlite3_finalize(stmt);
        return 0;
    }
    sqlite3_bind_text(stmt, 1, likePattern.c_str(),
                      static_cast<int>(likePattern.size()), SQLITE_TRANSIENT);

    int count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
    return count;
}

}  // namespace

SceneDetection detectScenes(const std::string& rawDbPath) {
    SceneDetection result;
    // Initialize every scenario to 0 so counts always has the full key set.
    for (auto s : PRIORITY_ORDER) {
        result.counts[s] = 0;
    }

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(rawDbPath.c_str(), &db,
                        SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return result;  // ok stays false
    }

    // Aggregate per-scenario match counts.
    for (const auto& m : MARKERS) {
        result.counts[m.scenario] += countMatches(db, m.like);
    }

    sqlite3_close(db);
    result.ok = true;

    // Build the detected list (count > 0), ordered by count desc then by the
    // fixed PRIORITY_ORDER for deterministic tie-breaking.
    std::vector<ForensicScenario> present;
    for (auto s : PRIORITY_ORDER) {
        if (result.counts[s] > 0) present.push_back(s);
    }
    std::stable_sort(present.begin(), present.end(),
                     [&result](ForensicScenario a, ForensicScenario b) {
                         if (result.counts[a] != result.counts[b]) {
                             return result.counts[a] > result.counts[b];
                         }
                         // Tie: respect PRIORITY_ORDER (a comes first if its
                         // index is smaller).
                         auto idxOf = [](ForensicScenario s) {
                             for (size_t i = 0;
                                  i < sizeof(PRIORITY_ORDER) / sizeof(PRIORITY_ORDER[0]);
                                  ++i) {
                                 if (PRIORITY_ORDER[i] == s) return i;
                             }
                             return SIZE_MAX;
                         };
                         return idxOf(a) < idxOf(b);
                     });
    result.detected = std::move(present);

    // Dominant = highest-count scenario (the head of the sorted list, if any).
    if (!result.detected.empty()) {
        switch (result.detected.front()) {
            case ForensicScenario::ANDROID:
                result.dominant = SceneType::ANDROID; break;
            case ForensicScenario::WINDOWS:
                result.dominant = SceneType::WINDOWS; break;
            case ForensicScenario::LINUX:
                result.dominant = SceneType::LINUX; break;
            case ForensicScenario::SERVER_CLOUD:
                result.dominant = SceneType::SERVER_CLOUD; break;
        }
    }

    return result;
}
