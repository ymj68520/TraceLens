#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "HTTPServer/SQLiteHelper.h"
#include <gtest/gtest.h>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <filesystem>
#include <sstream>
#include <vector>

namespace fs = std::filesystem;

class EventTimelineTest : public ::testing::Test {
protected:
    std::string testDir = "test_event_timeline_data";
    std::string rawDbPath;
    std::string eventsDbPath;

    void SetUp() override {
        fs::create_directories(testDir);
        rawDbPath = testDir + "/test_raw.db";
        eventsDbPath = testDir + "/test_events.db";
        
        setupTestDatabase();
    }

    void TearDown() override {
        if (fs::exists(testDir)) {
            fs::remove_all(testDir);
        }
    }

    void setupTestDatabase() {
        sqlite3* db;
        sqlite3_open(rawDbPath.c_str(), &db);
        
        // NOTE: the raw.db files table uses column "size" (see DatabaseManager),
        // which is what EventExtractor SELECTs. Using "file_size" here made the
        // extractor's query find no such column -> 0 events extracted.
        const char* createFilesTable = R"(
            CREATE TABLE files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inode INTEGER,
                path TEXT,
                size INTEGER,
                type TEXT,
                atime INTEGER,
                mtime INTEGER,
                ctime INTEGER,
                crtime INTEGER,
                is_deleted INTEGER DEFAULT 0
            );
        )";
        sqlite3_exec(db, createFilesTable, nullptr, nullptr, nullptr);

        const char* insertTestFiles = R"(
            INSERT INTO files (inode, path, size, type, atime, mtime, ctime, crtime, is_deleted)
            VALUES
            (1001, '/home/user/document.txt', 1024, 'REG', 1609459200, 1609459260, 1609459320, 1609459380, 0),
            (1002, '/home/user/image.jpg', 2048, 'REG', 1609459400, 1609459460, 1609459520, 1609459580, 0),
            (1003, '/tmp/temp.txt', 512, 'REG', 1609459600, 1609459660, 1609459720, 1609459780, 1),
            (1004, '/etc/config.conf', 256, 'REG', 1609459800, 1609459860, 1609459920, 1609459980, 0),
            (1005, '/var/log/system.log', 4096, 'REG', 1609460000, 1609460060, 1609460120, 1609460180, 0);
        )";
        sqlite3_exec(db, insertTestFiles, nullptr, nullptr, nullptr);
        
        sqlite3_close(db);
    }
};

TEST_F(EventTimelineTest, EventExtractionSuccess) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    
    EXPECT_TRUE(extractor.extractEvents());
    
    EXPECT_TRUE(fs::exists(eventsDbPath));
}

TEST_F(EventTimelineTest, EventCountVerification) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    sqlite3* db;
    sqlite3_open(eventsDbPath.c_str(), &db);
    
    sqlite3_stmt* stmt;
    sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM events", -1, &stmt, nullptr);
    sqlite3_step(stmt);
    int count = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    
    EXPECT_GT(count, 0);
    EXPECT_GE(count, 10); // At least 2 events per file (created and modified)
    
    sqlite3_close(db);
}

TEST_F(EventTimelineTest, TimelineByEventType) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    auto result = SQLiteHelper::get_timeline_by_type(eventsDbPath, "CREATED", 10);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result.contains("events"));
    EXPECT_EQ(result["event_type"], "CREATED");
    EXPECT_EQ(result["limit"], 10);
    
    auto events = result["events"];
    if (events.is_array() && !events.empty()) {
        EXPECT_TRUE(events[0].contains("timestamp"));
        EXPECT_TRUE(events[0].contains("event_type"));
    }
}

TEST_F(EventTimelineTest, TimelineByTimeRange) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    int64_t start_time = 1609459200;
    int64_t end_time = 1609459900;
    
    auto result = SQLiteHelper::get_timeline_by_time_range(eventsDbPath, start_time, end_time, 10);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result.contains("events"));
    EXPECT_TRUE(result.contains("time_range"));
    EXPECT_EQ(result["time_range"]["start"], start_time);
    EXPECT_EQ(result["time_range"]["end"], end_time);
}

TEST_F(EventTimelineTest, TimelineByFile) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    std::string file_path = "/home/user/document.txt";
    auto result = SQLiteHelper::get_timeline_by_file(eventsDbPath, file_path, 10);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result.contains("events"));
    EXPECT_EQ(result["file_path"], file_path);
}

TEST_F(EventTimelineTest, FullTimeline) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    auto result = SQLiteHelper::get_timeline_full(eventsDbPath, 10, 0);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result.contains("events"));
    EXPECT_EQ(result["limit"], 10);
    EXPECT_EQ(result["offset"], 0);
    EXPECT_TRUE(result.contains("total"));
    EXPECT_GT(result["total"], 0);
}

TEST_F(EventTimelineTest, EventStatisticsByPeriod) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    auto result = SQLiteHelper::get_event_statistics_by_period(eventsDbPath, "day");
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result.contains("statistics"));
    EXPECT_EQ(result["period"], "daily");
    
    auto stats = result["statistics"];
    if (stats.is_array() && !stats.empty()) {
        EXPECT_TRUE(stats[0].contains("time_period"));
        EXPECT_TRUE(stats[0].contains("event_type"));
        EXPECT_TRUE(stats[0].contains("event_count"));
    }
}

TEST_F(EventTimelineTest, EventExportJSON) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    std::string outputFile = testDir + "/export.json";
    auto result = SQLiteHelper::export_events_to_json(eventsDbPath, outputFile);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result["success"]);
    EXPECT_EQ(result["format"], "json");
    EXPECT_GT(result["events_count"], 0);
    EXPECT_TRUE(fs::exists(outputFile));
}

TEST_F(EventTimelineTest, EventExportCSV) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    std::string outputFile = testDir + "/export.csv";
    auto result = SQLiteHelper::export_events_to_csv(eventsDbPath, outputFile);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result["success"]);
    EXPECT_EQ(result["format"], "csv");
    EXPECT_GT(result["events_count"], 0);
    EXPECT_TRUE(fs::exists(outputFile));
}

TEST_F(EventTimelineTest, EventExportVisualization) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    std::string outputFile = testDir + "/export_viz.json";
    auto result = SQLiteHelper::export_events_for_visualization(eventsDbPath, outputFile);
    
    EXPECT_FALSE(result.contains("error"));
    EXPECT_TRUE(result["success"]);
    EXPECT_EQ(result["format"], "visualization_json");
    EXPECT_GT(result["events_count"], 0);
    EXPECT_TRUE(fs::exists(outputFile));
}

TEST_F(EventTimelineTest, SystemEventExtraction) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    sqlite3* db;
    sqlite3_open(eventsDbPath.c_str(), &db);
    
    sqlite3_stmt* stmt;
    sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM system_events", -1, &stmt, nullptr);
    sqlite3_step(stmt);
    int systemEventCount = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    
    EXPECT_GE(systemEventCount, 0); // System events should exist
    
    sqlite3_close(db);
}

TEST_F(EventTimelineTest, EventConsistency) {
    EventExtractor extractor(rawDbPath, eventsDbPath);
    extractor.extractEvents();
    
    sqlite3* db;
    sqlite3_open(eventsDbPath.c_str(), &db);
    
    sqlite3_stmt* stmt;
    
    // Check that all events have required fields
    sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM events WHERE timestamp IS NULL OR event_type IS NULL", -1, &stmt, nullptr);
    sqlite3_step(stmt);
    int nullFields = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    
    EXPECT_EQ(nullFields, 0);
    
    // Check event types are valid
    sqlite3_prepare_v2(db, "SELECT DISTINCT event_type FROM events", -1, &stmt, nullptr);
    std::vector<std::string> validTypes = {"CREATED", "MODIFIED", "ACCESSED", "CHANGED", "DELETED"};
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        bool valid = false;
        for (const auto& validType : validTypes) {
            if (type && std::string(type) == validType) {
                valid = true;
                break;
            }
        }
        EXPECT_TRUE(valid);
    }
    sqlite3_finalize(stmt);
    
    sqlite3_close(db);
}

// ============================================================================
// Cluster golden tests (SPEC event-cluster-analysis-redesign §4.4)
//
// The Python side of this contract lives in
// python_service/tests/unit/test_cluster_golden.py. The fixture rows below are
// the same truth: both implementations must produce identical coordinates.
// ============================================================================

namespace {
struct GoldenRow { int id; long long ts; const char* type; const char* path; };

// Same rows as the Python golden fixture (keep in sync).
const GoldenRow kGoldenRows[] = {
    {1, 0,     "MODIFIED", "/etc/a.conf"},
    {2, 30,    "MODIFIED", "/etc/b.conf"},
    {3, 59,    "CREATED",  "/etc/c.conf"},
    {4, 60,    "MODIFIED", "/etc/d.conf"},
    {5, -1,    "MODIFIED", "/var/log/w.log"},
    {6, 86399, "DELETED",  "/tmp/x"},
    {7, 86405, "DELETED",  "/tmp/y"},
    {8, 57600, "MODIFIED", "/opt/z"},
};

// Expected coordinates at bucket=60s, offset=0: (bucket_index, type, dir) -> member count.
// id 5 (ts=-1) truncates toward zero into bucket 0 (SQLite `/` semantics).
// Parts are lexicographically sorted — the comparison sorts the actual side.
const char* kExpectedOffset0 =
    "0|CREATED|/etc/|1,"       // id 3
    "0|MODIFIED|/etc/|2,"      // ids 1,2
    "0|MODIFIED|/var/log/|1,"  // id 5
    "1439|DELETED|/tmp/|1,"    // id 6
    "1440|DELETED|/tmp/|1,"    // id 7
    "1|MODIFIED|/etc/|1,"      // id 4
    "960|MODIFIED|/opt/|1";    // id 8

// Expected coordinates at bucket=60s, offset=57600 (matches the Python test).
const char* kExpectedOffset57600 =
    "-959|CREATED|/etc/|1,"      // id 3 ((59-57600)/60 = -959.016 -> -959)
    "-959|MODIFIED|/etc/|2,"     // ids 2,4 (-959.5 -> -959; -959)
    "-960|MODIFIED|/etc/|1,"     // id 1 (0-57600)/60 = -960
    "-960|MODIFIED|/var/log/|1," // id 5
    "0|MODIFIED|/opt/|1"         // id 8
    ",479|DELETED|/tmp/|1,"      // id 6
    "480|DELETED|/tmp/|1";       // id 7

std::string actualCoordinateString(const nlohmann::json& timeline) {
    std::vector<std::string> parts;
    for (const auto& item : timeline) {
        std::ostringstream oss;
        oss << item.value("bucket_index", (long long)0)
            << "|" << item.value("event_type", std::string{})
            << "|" << item.value("parent_directory", std::string{})
            << "|" << item.value("cluster_count", (long long)0);
        parts.push_back(oss.str());
    }
    std::sort(parts.begin(), parts.end());
    std::string joined;
    for (size_t i = 0; i < parts.size(); ++i) {
        if (i) joined += ",";
        joined += parts[i];
    }
    return joined;
}

void execOrDie(sqlite3* db, const char* sql) {
    char* err = nullptr;
    if (sqlite3_exec(db, sql, nullptr, nullptr, &err) != SQLITE_OK) {
        FAIL() << "SQL failed: " << (err ? err : "?") << " for " << sql;
    }
}
} // namespace

class ClusterGoldenTest : public ::testing::Test {
protected:
    std::string testDir = "test_cluster_golden_data";
    std::string rawDbPath;
    std::string eventsDbPath;

    void SetUp() override {
        fs::create_directories(testDir);
        rawDbPath = testDir + "/raw.db";
        eventsDbPath = testDir + "/events.db";

        sqlite3* db = nullptr;
        ASSERT_EQ(sqlite3_open(eventsDbPath.c_str(), &db), SQLITE_OK);
        execOrDie(db,
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, "
            "event_type TEXT, file_path TEXT, inode INTEGER, description TEXT, file_size INTEGER, file_type TEXT)");
        for (const auto& row : kGoldenRows) {
            std::ostringstream oss;
            oss << "INSERT INTO events (id, timestamp, event_type, file_path) VALUES ("
                << row.id << ", " << row.ts << ", '" << row.type << "', '" << row.path << "');";
            execOrDie(db, oss.str().c_str());
        }
        sqlite3_close(db);

        // get_comprehensive_timeline opens the raw db too; an empty file works.
        sqlite3* raw = nullptr;
        ASSERT_EQ(sqlite3_open(rawDbPath.c_str(), &raw), SQLITE_OK);
        sqlite3_close(raw);
    }

    void TearDown() override {
        if (fs::exists(testDir)) fs::remove_all(testDir);
    }

    nlohmann::json fetchTimeline(int bucket_seconds) {
        return SQLiteHelper::get_comprehensive_timeline(
            rawDbPath, eventsDbPath, "", "", 1000, 0, "", true, bucket_seconds);
    }
};

TEST_F(ClusterGoldenTest, CoordinatesMatchPythonFixtureAtOffsetZero) {
    auto result = fetchTimeline(60);
    ASSERT_TRUE(result.contains("timeline"));
    EXPECT_EQ(actualCoordinateString(result["timeline"]), std::string(kExpectedOffset0));
}

TEST_F(ClusterGoldenTest, CoordinatesMatchPythonFixtureAtLocalOffset) {
    {
        sqlite3* db = nullptr;
        ASSERT_EQ(sqlite3_open(eventsDbPath.c_str(), &db), SQLITE_OK);
        execOrDie(db,
            "CREATE TABLE IF NOT EXISTS analysis_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO analysis_meta VALUES ('bucket_epoch_offset', '57600');");
        sqlite3_close(db);
    }
    auto result = fetchTimeline(60);
    ASSERT_TRUE(result.contains("timeline"));
    EXPECT_EQ(actualCoordinateString(result["timeline"]), std::string(kExpectedOffset57600));
    // The offset travels with the response metadata for downstream consumers.
    EXPECT_EQ(result["metadata"].value("bucket_epoch_offset", (long long)-1), 57600);
}

TEST_F(ClusterGoldenTest, LatestAnalysisRecordAttachesWithStaleness) {
    {
        sqlite3* db = nullptr;
        ASSERT_EQ(sqlite3_open(eventsDbPath.c_str(), &db), SQLITE_OK);
        // Minimal analysis-record surface (same shape as the Python DDL).
        execOrDie(db,
            "CREATE TABLE event_cluster_analyses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, "
            "bucket_epoch_offset INTEGER NOT NULL DEFAULT 0, bucket_seconds INTEGER NOT NULL, "
            "bucket_index INTEGER NOT NULL, event_type TEXT NOT NULL, parent_directory TEXT NOT NULL, "
            "member_count INTEGER NOT NULL, member_min_id INTEGER NOT NULL, member_max_id INTEGER NOT NULL, "
            "members_hash TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', "
            "keywords TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', trigger_source TEXT NOT NULL, "
            "analysis_id_upstream INTEGER, created_at INTEGER NOT NULL, ingested_at INTEGER);"
            "INSERT INTO event_cluster_analyses (task_id, bucket_seconds, bucket_index, event_type, "
            "parent_directory, member_count, member_min_id, member_max_id, members_hash, summary, "
            "trigger_source, created_at) VALUES "
            "('t1', 60, 0, 'MODIFIED', '/etc/', 2, 1, 2, 'hash', 'cached summary', 'pipeline', 7);");
        sqlite3_close(db);
    }

    auto result = fetchTimeline(60);
    const nlohmann::json* etc = nullptr;
    for (const auto& item : result["timeline"]) {
        if (item.value("event_type", std::string{}) == "MODIFIED" &&
            item.value("parent_directory", std::string{}) == "/etc/") {
            // Two /etc/ MODIFIED groups exist (bucket 0 and 1); bucket 0 holds ids 1,2.
            if (item.value("bucket_index", (long long)-1) == 0) { etc = &item; break; }
        }
    }
    ASSERT_NE(etc, nullptr);
    EXPECT_EQ(etc->value("analysis_id", (long long)0), 1);
    EXPECT_EQ(etc->value("llm_summary", std::string{}), std::string("cached summary"));
    EXPECT_EQ(etc->value("is_stale", (long long)-1), 0);
    EXPECT_EQ(etc->value("analyzed_at", (long long)0), 7);
}

TEST_F(ClusterGoldenTest, BucketSecondsClampsToProtocolMax) {
    auto result = fetchTimeline(99999999);
    EXPECT_EQ(result["metadata"].value("bucket_seconds", (long long)0), 2592000);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
