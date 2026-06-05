// test_scene_database_gtest.cpp
// Tests for scene specialization SQL definitions in file_classifier_sql.h

#include <gtest/gtest.h>
#include <sqlite3.h>
#include <string>
#include <cstdio>
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"

// Helper: substitute %TABLE_NAME% in a template with the given table name
static std::string substituteTable(const char* templ, const std::string& tableName) {
    std::string sql(templ);
    std::string::size_type pos = 0;
    while ((pos = sql.find("%TABLE_NAME%", pos)) != std::string::npos) {
        sql.replace(pos, 12, tableName);  // 12 = length of "%TABLE_NAME%"
        pos += tableName.length();
    }
    return sql;
}

class SceneDatabaseTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbPath_ = ":memory:";
        ASSERT_EQ(sqlite3_open(dbPath_, &db_), SQLITE_OK);
    }

    void TearDown() override {
        if (db_) sqlite3_close(db_);
    }

    sqlite3* db_ = nullptr;
    const char* dbPath_;
};

TEST_F(SceneDatabaseTest, CreateMainFilesTableWithSceneColumns) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT scene_type, scene_priority, scene_relevant FROM files LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateAndroidArtifactsTable) {
    auto sql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "android_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT id, file_id, artifact_type, artifact_data FROM android_artifacts LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateWindowsArtifactsTable) {
    auto sql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "windows_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT id, file_id, artifact_type, artifact_data FROM windows_artifacts LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateLinuxArtifactsTable) {
    auto sql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "linux_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT id, file_id, artifact_type, artifact_data FROM linux_artifacts LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateSceneArtifactsIndices) {
    // Create prerequisite tables first
    auto sqlAndroid = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "android_artifacts");
    auto sqlWindows = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "windows_artifacts");
    auto sqlLinux = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "linux_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, sqlAndroid.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, sqlWindows.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, sqlLinux.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    // Create indices
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_SCENE_ARTIFACTS_INDICES, nullptr, nullptr, nullptr), SQLITE_OK);

    // Verify indices exist by querying sqlite_master
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%_artifacts_%'",
        -1, &stmt, nullptr), SQLITE_OK);

    int index_count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        index_count++;
    }
    sqlite3_finalize(stmt);
    ASSERT_EQ(index_count, 6);
}

TEST_F(SceneDatabaseTest, CreateSceneFileSummaryView) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_SCENE_FILE_SUMMARY_VIEW, nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT scene_type, total_files, relevant_files, total_size, llm_analyzed_files FROM scene_file_summary",
        -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateSceneArtifactSummaryView) {
    auto sqlAndroid = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "android_artifacts");
    auto sqlWindows = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "windows_artifacts");
    auto sqlLinux = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "linux_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, sqlAndroid.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, sqlWindows.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, sqlLinux.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_SCENE_ARTIFACT_SUMMARY_VIEW, nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT scene_type, artifact_type, artifact_count, analyzed_count FROM scene_artifact_summary",
        -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, AlterFilesAddSceneColumns) {
    // Create table without scene columns first (simulate old schema)
    ASSERT_EQ(sqlite3_exec(db_,
        "CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, path TEXT);",
        nullptr, nullptr, nullptr), SQLITE_OK);

    // Apply migration
    for (int i = 0; i < FileClassifierSQL::ALTER_FILES_ADD_SCENE_COLUMNS_COUNT; i++) {
        ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::ALTER_FILES_ADD_SCENE_COLUMNS[i],
            nullptr, nullptr, nullptr), SQLITE_OK);
    }

    // Verify new columns exist
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT scene_type, scene_priority, scene_relevant FROM files LIMIT 0",
        -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, InsertAndroidArtifact) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);
    auto createSql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "android_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, createSql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    // Insert a file first
    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5) "
        "VALUES (1, 'sms.db', '/data/data/com.android.providers.telephony/databases/mmssms.db', 4096, '.db', 'Databases', 'REG', 0, 0, 0, 'abc123');",
        nullptr, nullptr, nullptr), SQLITE_OK);

    // Insert artifact
    sqlite3_stmt* stmt;
    auto insertSql = substituteTable(FileClassifierSQL::INSERT_ARTIFACT_TEMPLATE, "android_artifacts");
    ASSERT_EQ(sqlite3_prepare_v2(db_, insertSql.c_str(), -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int(stmt, 1, 1);  // file_id
    sqlite3_bind_text(stmt, 2, "sms", -1, SQLITE_STATIC);  // artifact_type
    sqlite3_bind_text(stmt, 3, "{\"count\": 42}", -1, SQLITE_STATIC);  // artifact_data
    sqlite3_bind_int64(stmt, 4, 1700000000);  // extracted_at
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Verify insertion
    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT artifact_type, artifact_data FROM android_artifacts WHERE file_id = 1",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "sms");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)), "{\"count\": 42}");
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, InsertWindowsArtifact) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);
    auto createSql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "windows_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, createSql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5) "
        "VALUES (1, 'SAM', '/Windows/System32/config/SAM', 8192, '', 'System Files', 'REG', 0, 0, 0, 'def456');",
        nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    auto insertSql = substituteTable(FileClassifierSQL::INSERT_ARTIFACT_TEMPLATE, "windows_artifacts");
    ASSERT_EQ(sqlite3_prepare_v2(db_, insertSql.c_str(), -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int(stmt, 1, 1);
    sqlite3_bind_text(stmt, 2, "registry", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "{\"keys\": 15}", -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, 1700000000);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT artifact_type FROM windows_artifacts WHERE file_id = 1",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "registry");
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, InsertLinuxArtifact) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);
    auto createSql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "linux_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, createSql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5) "
        "VALUES (1, 'auth.log', '/var/log/auth.log', 2048, '.log', 'Logs', 'REG', 0, 0, 0, 'ghi789');",
        nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    auto insertSql = substituteTable(FileClassifierSQL::INSERT_ARTIFACT_TEMPLATE, "linux_artifacts");
    ASSERT_EQ(sqlite3_prepare_v2(db_, insertSql.c_str(), -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int(stmt, 1, 1);
    sqlite3_bind_text(stmt, 2, "auth_log", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "{\"entries\": 100}", -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, 1700000000);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT artifact_type FROM linux_artifacts WHERE file_id = 1",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "auth_log");
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, UpdateAndroidArtifactLLM) {
    auto createSql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, "android_artifacts");
    ASSERT_EQ(sqlite3_exec(db_, createSql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);

    // Insert an artifact
    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO android_artifacts (file_id, artifact_type, artifact_data, extracted_at) "
        "VALUES (1, 'sms', '{}', 1700000000);",
        nullptr, nullptr, nullptr), SQLITE_OK);

    // Update with LLM analysis
    sqlite3_stmt* stmt;
    auto updateSql = substituteTable(FileClassifierSQL::UPDATE_ARTIFACT_LLM_TEMPLATE, "android_artifacts");
    ASSERT_EQ(sqlite3_prepare_v2(db_, updateSql.c_str(), -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_text(stmt, 1, "SMS database summary", -1, SQLITE_STATIC);  // llm_summary
    sqlite3_bind_text(stmt, 2, "Contains SMS messages", -1, SQLITE_STATIC);  // llm_description
    sqlite3_bind_text(stmt, 3, "sms,messages,contacts", -1, SQLITE_STATIC);  // llm_keywords
    sqlite3_bind_int64(stmt, 4, 1700001000);  // llm_analyzed_at
    sqlite3_bind_text(stmt, 5, "test-model", -1, SQLITE_STATIC);  // llm_model_used
    sqlite3_bind_int(stmt, 6, 1);  // id
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Verify update
    ASSERT_EQ(sqlite3_prepare_v2(db_,
        "SELECT llm_summary, llm_model_used FROM android_artifacts WHERE id = 1",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "SMS database summary");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)), "test-model");
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, SelectSceneFilesForLLM) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);

    // Insert files with different scene priorities
    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) "
        "VALUES (1, 'high.txt', '/high.txt', 100, '.txt', 'Documents', 'REG', 0, 0, 0, 'a', 'android', 10, 1);",
        nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) "
        "VALUES (2, 'low.txt', '/low.txt', 200, '.txt', 'Documents', 'REG', 0, 0, 0, 'b', 'android', 1, 0);",
        nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) "
        "VALUES (3, 'analyzed.txt', '/analyzed.txt', 50, '.txt', 'Documents', 'REG', 0, 0, 0, 'c', 'android', 20, 1);",
        nullptr, nullptr, nullptr), SQLITE_OK);
    // Mark as already analyzed
    ASSERT_EQ(sqlite3_exec(db_,
        "UPDATE files SET llm_analyzed_at = 1700000000 WHERE name = 'analyzed.txt';",
        nullptr, nullptr, nullptr), SQLITE_OK);

    // Select files for LLM analysis
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, FileClassifierSQL::SELECT_SCENE_FILES_FOR_LLM, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int(stmt, 1, 10);  // LIMIT

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
    }
    sqlite3_finalize(stmt);

    // Should return 2 files (high.txt and low.txt), not the already analyzed one
    ASSERT_EQ(count, 2);
}

TEST_F(SceneDatabaseTest, SelectSceneFileStats) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_SCENE_FILE_SUMMARY_VIEW, nullptr, nullptr, nullptr), SQLITE_OK);

    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) "
        "VALUES (1, 'a.txt', '/a.txt', 100, '.txt', 'Documents', 'REG', 0, 0, 0, 'a', 'android', 5, 1);",
        nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db_,
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) "
        "VALUES (2, 'b.txt', '/b.txt', 200, '.txt', 'Documents', 'REG', 0, 0, 0, 'b', 'windows', 3, 0);",
        nullptr, nullptr, nullptr), SQLITE_OK);

    // Use the scene_file_summary view instead of the removed SELECT_SCENE_FILE_STATS query
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT scene_type, total_files, relevant_files, total_size, llm_analyzed_files FROM scene_file_summary", -1, &stmt, nullptr), SQLITE_OK);

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
    }
    sqlite3_finalize(stmt);

    ASSERT_EQ(count, 2);  // android and windows
}

// ============================================================================
// ImportSceneArtifacts Tests
// ============================================================================

// Helper: create a temporary files.db with files table and artifact data
static std::string createTempFilesDb(const std::string& sceneType) {
    char tmpPath[] = "/tmp/forensic_test_filesdb_XXXXXX";
    int fd = mkstemp(tmpPath);
    close(fd);
    std::string path(tmpPath);

    sqlite3* db;
    sqlite3_open(path.c_str(), &db);

    // Create files table
    sqlite3_exec(db, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr);

    // Create artifact table
    std::string tableName = sceneType + "_artifacts";
    auto createSql = substituteTable(FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE, tableName);
    sqlite3_exec(db, createSql.c_str(), nullptr, nullptr, nullptr);

    sqlite3_close(db);
    return path;
}

// Helper: populate files.db with a file and artifacts for the given scene type
static void populateFilesDbArtifacts(const std::string& dbPath, const std::string& sceneType) {
    sqlite3* db;
    sqlite3_open(dbPath.c_str(), &db);

    // Insert a file with scene_type using prepared statement
    const char* insertFileSql = "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type) "
        "VALUES (100, 'test_artifact.db', '/data/test_artifact.db', 4096, '.db', 'Databases', 'REG', 0, 0, 0, 'hash123', ?);";
    sqlite3_stmt* fileStmt;
    sqlite3_prepare_v2(db, insertFileSql, -1, &fileStmt, nullptr);
    sqlite3_bind_text(fileStmt, 1, sceneType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_step(fileStmt);
    sqlite3_finalize(fileStmt);

    // Insert artifact
    std::string tableName = sceneType + "_artifacts";
    auto insertSql = substituteTable(FileClassifierSQL::INSERT_ARTIFACT_TEMPLATE, tableName);
    sqlite3_stmt* stmt;
    sqlite3_prepare_v2(db, insertSql.c_str(), -1, &stmt, nullptr);
    sqlite3_bind_int(stmt, 1, 1);  // file_id = 1
    sqlite3_bind_text(stmt, 2, "test_type", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "{\"key\": \"value\"}", -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, 1700000000);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    sqlite3_close(db);
}

TEST_F(SceneDatabaseTest, ImportSceneArtifactsAndroid) {
    // Create a temporary files.db with Android artifacts
    std::string filesDbPath = createTempFilesDb("android");
    populateFilesDbArtifacts(filesDbPath, "android");

    // Create a temporary events.db (source db is not needed for this test)
    char tmpSourcePath[] = "/tmp/forensic_test_source_XXXXXX";
    int fd1 = mkstemp(tmpSourcePath);
    close(fd1);
    char tmpEventPath[] = "/tmp/forensic_test_event_XXXXXX";
    int fd2 = mkstemp(tmpEventPath);
    close(fd2);

    // Create a minimal source db with files table
    {
        sqlite3* srcDb;
        sqlite3_open(tmpSourcePath, &srcDb);
        sqlite3_exec(srcDb, "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, inode INTEGER, path TEXT, atime INTEGER, mtime INTEGER, ctime INTEGER, crtime INTEGER, type TEXT, size INTEGER, is_deleted INTEGER);",
            nullptr, nullptr, nullptr);
        sqlite3_close(srcDb);
    }

    EventExtractor extractor(tmpSourcePath, tmpEventPath);
    ASSERT_TRUE(extractor.extractEvents());

    // Now import Android artifacts from the unified files.db
    ASSERT_TRUE(extractor.importSceneArtifacts(filesDbPath, "android"));

    // Verify events were created in the events.db
    sqlite3* eventDb;
    ASSERT_EQ(sqlite3_open(tmpEventPath, &eventDb), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(eventDb,
        "SELECT event_type, file_path, event_source, event_category FROM events WHERE event_type = 'ANDROID_ARTIFACT'",
        -1, &stmt, nullptr), SQLITE_OK);

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "ANDROID_ARTIFACT");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)), "/data/test_artifact.db");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "ANDROID_LOG");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)), "APPLICATION_EVENT");
    }
    sqlite3_finalize(stmt);
    sqlite3_close(eventDb);

    ASSERT_EQ(count, 1);

    // Cleanup
    std::remove(filesDbPath.c_str());
    std::remove(tmpSourcePath);
    std::remove(tmpEventPath);
}

TEST_F(SceneDatabaseTest, ImportSceneArtifactsWindows) {
    std::string filesDbPath = createTempFilesDb("windows");
    populateFilesDbArtifacts(filesDbPath, "windows");

    char tmpSourcePath[] = "/tmp/forensic_test_source_XXXXXX";
    int fd1 = mkstemp(tmpSourcePath);
    close(fd1);
    char tmpEventPath[] = "/tmp/forensic_test_event_XXXXXX";
    int fd2 = mkstemp(tmpEventPath);
    close(fd2);

    {
        sqlite3* srcDb;
        sqlite3_open(tmpSourcePath, &srcDb);
        sqlite3_exec(srcDb, "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, inode INTEGER, path TEXT, atime INTEGER, mtime INTEGER, ctime INTEGER, crtime INTEGER, type TEXT, size INTEGER, is_deleted INTEGER);",
            nullptr, nullptr, nullptr);
        sqlite3_close(srcDb);
    }

    EventExtractor extractor(tmpSourcePath, tmpEventPath);
    ASSERT_TRUE(extractor.extractEvents());

    ASSERT_TRUE(extractor.importSceneArtifacts(filesDbPath, "windows"));

    sqlite3* eventDb;
    ASSERT_EQ(sqlite3_open(tmpEventPath, &eventDb), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(eventDb,
        "SELECT event_type, file_path, event_source FROM events WHERE event_type = 'WINDOWS_ARTIFACT'",
        -1, &stmt, nullptr), SQLITE_OK);

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "WINDOWS_ARTIFACT");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "WINDOWS_EVENT_LOG");
    }
    sqlite3_finalize(stmt);
    sqlite3_close(eventDb);

    ASSERT_EQ(count, 1);

    std::remove(filesDbPath.c_str());
    std::remove(tmpSourcePath);
    std::remove(tmpEventPath);
}

TEST_F(SceneDatabaseTest, ImportSceneArtifactsLinux) {
    std::string filesDbPath = createTempFilesDb("linux");
    populateFilesDbArtifacts(filesDbPath, "linux");

    char tmpSourcePath[] = "/tmp/forensic_test_source_XXXXXX";
    int fd1 = mkstemp(tmpSourcePath);
    close(fd1);
    char tmpEventPath[] = "/tmp/forensic_test_event_XXXXXX";
    int fd2 = mkstemp(tmpEventPath);
    close(fd2);

    {
        sqlite3* srcDb;
        sqlite3_open(tmpSourcePath, &srcDb);
        sqlite3_exec(srcDb, "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, inode INTEGER, path TEXT, atime INTEGER, mtime INTEGER, ctime INTEGER, crtime INTEGER, type TEXT, size INTEGER, is_deleted INTEGER);",
            nullptr, nullptr, nullptr);
        sqlite3_close(srcDb);
    }

    EventExtractor extractor(tmpSourcePath, tmpEventPath);
    ASSERT_TRUE(extractor.extractEvents());

    ASSERT_TRUE(extractor.importSceneArtifacts(filesDbPath, "linux"));

    sqlite3* eventDb;
    ASSERT_EQ(sqlite3_open(tmpEventPath, &eventDb), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(eventDb,
        "SELECT event_type, file_path, event_source FROM events WHERE event_type = 'LINUX_ARTIFACT'",
        -1, &stmt, nullptr), SQLITE_OK);

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "LINUX_ARTIFACT");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "LINUX_SYSLOG");
    }
    sqlite3_finalize(stmt);
    sqlite3_close(eventDb);

    ASSERT_EQ(count, 1);

    std::remove(filesDbPath.c_str());
    std::remove(tmpSourcePath);
    std::remove(tmpEventPath);
}

TEST_F(SceneDatabaseTest, ImportSceneArtifactsUnknownType) {
    char tmpSourcePath[] = "/tmp/forensic_test_source_XXXXXX";
    int fd1 = mkstemp(tmpSourcePath);
    close(fd1);
    char tmpEventPath[] = "/tmp/forensic_test_event_XXXXXX";
    int fd2 = mkstemp(tmpEventPath);
    close(fd2);

    {
        sqlite3* srcDb;
        sqlite3_open(tmpSourcePath, &srcDb);
        sqlite3_exec(srcDb, "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, inode INTEGER, path TEXT, atime INTEGER, mtime INTEGER, ctime INTEGER, crtime INTEGER, type TEXT, size INTEGER, is_deleted INTEGER);",
            nullptr, nullptr, nullptr);
        sqlite3_close(srcDb);
    }

    EventExtractor extractor(tmpSourcePath, tmpEventPath);
    ASSERT_TRUE(extractor.extractEvents());

    // Unknown scene type should return false
    ASSERT_FALSE(extractor.importSceneArtifacts("/nonexistent.db", "unknown_type"));

    std::remove(tmpSourcePath);
    std::remove(tmpEventPath);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
