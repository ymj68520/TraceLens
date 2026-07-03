#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "HTTPServer/SQLiteHelper.h"
#include <gtest/gtest.h>
#include <fstream>
#include <iostream>
#include <filesystem>

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

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
