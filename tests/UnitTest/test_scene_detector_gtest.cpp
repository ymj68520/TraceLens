// test_scene_detector_gtest.cpp
// GTest-based unit tests for SceneDetector (platform auto-detection).
// Builds a temporary `files` table with marker paths and asserts which
// scenarios are detected, the detection order, and the dominant SceneType.

#include <gtest/gtest.h>
#include "network/HTTPServer/SceneDetector.h"
#include <sqlite3.h>
#include <cstdio>
#include <string>
#include <vector>

class SceneDetectorTest : public ::testing::Test {
protected:
    void TearDown() override {
        for (const auto& f : tempFiles_) std::remove(f.c_str());
    }

    // Create a raw-DB-style file with a `files` table and insert the given paths.
    // Returns the path via `outPath`; returns false on sqlite failure. Uses a
    // bool return (not ASSERT_*, which expand to void) so it composes inside a
    // helper called from non-void-aware test bodies.
    bool createRawDb(const std::vector<std::string>& paths, std::string& outPath) {
        outPath = "/tmp/test_scene_detector_" +
                  std::to_string(tempFiles_.size()) + ".db";
        tempFiles_.push_back(outPath);
        std::remove(outPath.c_str());  // clean any leftover from a crashed run

        sqlite3* db = nullptr;
        if (sqlite3_open(outPath.c_str(), &db) != SQLITE_OK) {
            if (db) sqlite3_close(db);
            return false;
        }

        const char* schema =
            "CREATE TABLE files ("
            "  id INTEGER PRIMARY KEY, path TEXT, is_deleted INTEGER);";
        if (sqlite3_exec(db, schema, nullptr, nullptr, nullptr) != SQLITE_OK) {
            sqlite3_close(db);
            return false;
        }

        sqlite3_stmt* stmt = nullptr;
        if (sqlite3_prepare_v2(db, "INSERT INTO files(path, is_deleted) VALUES (?, 0);",
                               -1, &stmt, nullptr) != SQLITE_OK) {
            sqlite3_close(db);
            return false;
        }
        for (const auto& p : paths) {
            sqlite3_bind_text(stmt, 1, p.c_str(), -1, SQLITE_TRANSIENT);
            if (sqlite3_step(stmt) != SQLITE_DONE) {
                sqlite3_finalize(stmt);
                sqlite3_close(db);
                return false;
            }
            sqlite3_reset(stmt);
        }
        sqlite3_finalize(stmt);
        sqlite3_close(db);
        return true;
    }

    bool hasScenario(const std::vector<ForensicScenario>& v, ForensicScenario s) {
        return std::find(v.begin(), v.end(), s) != v.end();
    }

    std::vector<std::string> tempFiles_;
};

// --- Android-only image -----------------------------------------------
TEST_F(SceneDetectorTest, DetectsAndroidOnly) {
    std::string db;
    ASSERT_TRUE(createRawDb({
        "/data/data/com.android.providers.contacts/databases/contacts2.db",
        "/data/system/packages.xml",
    }, db));

    SceneDetection d = detectScenes(db);
    ASSERT_TRUE(d.ok);
    EXPECT_EQ(d.detected.size(), 1u);
    EXPECT_EQ(d.detected.front(), ForensicScenario::ANDROID);
    EXPECT_EQ(d.dominant, SceneType::ANDROID);
    EXPECT_GT(d.counts[ForensicScenario::ANDROID], 0);
    EXPECT_EQ(d.counts[ForensicScenario::WINDOWS], 0);
}

// --- Windows-only image (backslash-style paths) ----------------------
TEST_F(SceneDetectorTest, DetectsWindowsBackslashPaths) {
    std::string db;
    ASSERT_TRUE(createRawDb({
        R"(C:\Windows\System32\config\SAM)",
        R"(C:\Windows\Prefetch\foo.pf)",
    }, db));

    SceneDetection d = detectScenes(db);
    ASSERT_TRUE(d.ok);
    EXPECT_EQ(d.detected.size(), 1u);
    EXPECT_EQ(d.detected.front(), ForensicScenario::WINDOWS);
    EXPECT_EQ(d.dominant, SceneType::WINDOWS);
}

// --- Mixed Android + Linux, Android has more markers -----------------
TEST_F(SceneDetectorTest, DominantIsHigherCount) {
    std::string db;
    ASSERT_TRUE(createRawDb({
        // 3 Android markers
        "/data/data/com.android.providers.telephony/databases/mmssms.db",
        "/data/data/com.android.chrome/Default/History",
        "/data/system/usagestats/daily",
        // 1 Linux marker
        "/var/log/auth.log",
    }, db));

    SceneDetection d = detectScenes(db);
    ASSERT_TRUE(d.ok);
    ASSERT_EQ(d.detected.size(), 2u);
    // Ordered by count desc: Android (3) before Linux (1).
    EXPECT_EQ(d.detected[0], ForensicScenario::ANDROID);
    EXPECT_EQ(d.detected[1], ForensicScenario::LINUX);
    EXPECT_EQ(d.dominant, SceneType::ANDROID);
}

// --- Server / Cloud --------------------------------------------------
TEST_F(SceneDetectorTest, DetectsServerCloud) {
    std::string db;
    ASSERT_TRUE(createRawDb({
        "/etc/nginx/nginx.conf",
        "/var/lib/docker/overlay2/abc",
        "/etc/kubernetes/admin.conf",
    }, db));

    SceneDetection d = detectScenes(db);
    ASSERT_TRUE(d.ok);
    EXPECT_EQ(d.detected.size(), 1u);
    EXPECT_EQ(d.detected.front(), ForensicScenario::SERVER_CLOUD);
    EXPECT_EQ(d.dominant, SceneType::SERVER_CLOUD);
}

// --- No markers present ----------------------------------------------
TEST_F(SceneDetectorTest, NoMarkersYieldsNone) {
    std::string db;
    ASSERT_TRUE(createRawDb({
        "/random/path/file.txt",
        "/home/user/document.pdf",
    }, db));

    SceneDetection d = detectScenes(db);
    ASSERT_TRUE(d.ok);
    EXPECT_TRUE(d.detected.empty());
    EXPECT_EQ(d.dominant, SceneType::NONE);
}

// --- Empty table -----------------------------------------------------
TEST_F(SceneDetectorTest, EmptyTableYieldsNone) {
    std::string db;
    ASSERT_TRUE(createRawDb({}, db));
    SceneDetection d = detectScenes(db);
    ASSERT_TRUE(d.ok);
    EXPECT_TRUE(d.detected.empty());
    EXPECT_EQ(d.dominant, SceneType::NONE);
}

// --- Deleted files are ignored ---------------------------------------
TEST_F(SceneDetectorTest, IgnoresDeletedFiles) {
    std::string path = "/tmp/test_scene_detector_deleted.db";
    tempFiles_.push_back(path);
    std::remove(path.c_str());

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, is_deleted INTEGER);",
        nullptr, nullptr, nullptr), SQLITE_OK);
    // Insert an Android marker but mark it deleted.
    ASSERT_EQ(sqlite3_exec(db,
        "INSERT INTO files(path, is_deleted) VALUES "
        " ('/data/data/com.android.providers.contacts/databases/contacts2.db', 1);",
        nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(db);

    SceneDetection d = detectScenes(path);
    ASSERT_TRUE(d.ok);
    EXPECT_TRUE(d.detected.empty());
    EXPECT_EQ(d.dominant, SceneType::NONE);
}

// --- Missing DB file is handled gracefully ---------------------------
TEST_F(SceneDetectorTest, MissingDatabaseFailsCleanly) {
    SceneDetection d = detectScenes("/nonexistent/path/no_such.db");
    EXPECT_FALSE(d.ok);
    EXPECT_TRUE(d.detected.empty());
    EXPECT_EQ(d.dominant, SceneType::NONE);
}
