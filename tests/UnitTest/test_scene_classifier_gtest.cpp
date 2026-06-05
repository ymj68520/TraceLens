// test_scene_classifier_gtest.cpp
// GTest-based unit tests for FileClassifier scene-aware classification
// Tests scene type management and platform-specific priority calculation

#include <gtest/gtest.h>
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/DatabaseManagerDataTypes.h"
#include "LLMAnalysisService.h"
#include <sqlite3.h>
#include <cstdio>
#include <string>

class SceneClassifierTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbPath_ = ":memory:";
    }

    void TearDown() override {
        // Clean up temporary files
        for (const auto& f : tempFiles_) {
            std::remove(f.c_str());
        }
    }

    // Helper: create a source database file with test data
    std::string createSourceDb(const std::string& filename) {
        std::string path = "/tmp/test_scene_" + filename + ".db";
        tempFiles_.push_back(path);

        sqlite3* db;
        int rc = sqlite3_open(path.c_str(), &db);
        EXPECT_EQ(rc, SQLITE_OK);

        const char* schema = R"(
            CREATE TABLE files (
                id INTEGER PRIMARY KEY,
                inode INTEGER,
                name TEXT,
                path TEXT,
                size INTEGER,
                type TEXT,
                mtime INTEGER,
                ctime INTEGER,
                is_deleted INTEGER,
                md5 TEXT
            );
            INSERT INTO files VALUES (1, 100, 'contacts.db', '/data/data/com.android.providers.contacts/databases/contacts.db', 1024, 'REG', 1000, 1000, 0, 'abc123');
            INSERT INTO files VALUES (2, 101, 'SAM', '/Windows/System32/config/SAM', 2048, 'REG', 1000, 1000, 0, 'def456');
            INSERT INTO files VALUES (3, 102, 'auth.log', '/var/log/auth.log', 4096, 'REG', 1000, 1000, 0, 'ghi789');
        )";
        EXPECT_EQ(sqlite3_exec(db, schema, nullptr, nullptr, nullptr), SQLITE_OK);
        sqlite3_close(db);
        return path;
    }

    // Helper: query a single int value from a database
    int queryInt(const std::string& dbPath, const std::string& sql) {
        sqlite3* db;
        if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) return -999;
        sqlite3_stmt* stmt;
        int result = -999;
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
            if (sqlite3_step(stmt) == SQLITE_ROW) {
                result = sqlite3_column_int(stmt, 0);
            }
            sqlite3_finalize(stmt);
        }
        sqlite3_close(db);
        return result;
    }

    // Helper: query a single text value from a database
    std::string queryText(const std::string& dbPath, const std::string& sql) {
        sqlite3* db;
        if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) return "";
        sqlite3_stmt* stmt;
        std::string result;
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
            if (sqlite3_step(stmt) == SQLITE_ROW) {
                const char* text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
                result = text ? text : "";
            }
            sqlite3_finalize(stmt);
        }
        sqlite3_close(db);
        return result;
    }

    std::string dbPath_;
    std::vector<std::string> tempFiles_;
};

TEST_F(SceneClassifierTest, SceneTypeNoneByDefault) {
    FileClassifier classifier(":memory:", ":memory:");
    EXPECT_EQ(classifier.getSceneType(), SceneType::NONE);
}

TEST_F(SceneClassifierTest, SetSceneTypeAndroid) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);
    EXPECT_EQ(classifier.getSceneType(), SceneType::ANDROID);
}

TEST_F(SceneClassifierTest, SetSceneTypeWindows) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::WINDOWS);
    EXPECT_EQ(classifier.getSceneType(), SceneType::WINDOWS);
}

TEST_F(SceneClassifierTest, SetSceneTypeLinux) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::LINUX);
    EXPECT_EQ(classifier.getSceneType(), SceneType::LINUX);
}

TEST_F(SceneClassifierTest, AndroidScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    EXPECT_EQ(classifier.calculateScenePriority("/data/data/com.android.providers.contacts/", "contacts.db", FileCategory::DATABASE), ScenePriority::CRITICAL);
    EXPECT_EQ(classifier.calculateScenePriority("/data/system/", "system.db", FileCategory::DATABASE), ScenePriority::CRITICAL);
}

TEST_F(SceneClassifierTest, AndroidScenePriorityHigh) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    EXPECT_EQ(classifier.calculateScenePriority("/data/data/com.tencent.mm/", "mm.db", FileCategory::DATABASE), ScenePriority::HIGH);
    EXPECT_EQ(classifier.calculateScenePriority("/data/app/", "app.apk", FileCategory::ARCHIVE), ScenePriority::HIGH);
}

TEST_F(SceneClassifierTest, AndroidScenePriorityIrrelevant) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/config/", "SAM", FileCategory::SYSTEM), ScenePriority::IRRELEVANT);
    EXPECT_EQ(classifier.calculateScenePriority("/usr/lib/", "lib.so", FileCategory::SYSTEM), ScenePriority::IRRELEVANT);
}

TEST_F(SceneClassifierTest, WindowsScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::WINDOWS);

    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/config/", "SAM", FileCategory::SYSTEM), ScenePriority::CRITICAL);
    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/winevt/", "System.evtx", FileCategory::SYSTEM), ScenePriority::CRITICAL);
}

TEST_F(SceneClassifierTest, LinuxScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::LINUX);

    EXPECT_EQ(classifier.calculateScenePriority("/var/log/auth.log", "auth.log", FileCategory::LOG_FILE), ScenePriority::CRITICAL);
    EXPECT_EQ(classifier.calculateScenePriority("/etc/passwd", "passwd", FileCategory::SYSTEM), ScenePriority::CRITICAL);
}

TEST_F(SceneClassifierTest, IsSceneRelevant) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    // CRITICAL path should be relevant
    EXPECT_TRUE(classifier.isSceneRelevant("/data/data/com.android.providers.contacts/", "contacts.db"));

    // IRRELEVANT path should not be relevant
    EXPECT_FALSE(classifier.isSceneRelevant("/Windows/System32/config/", "SAM"));
}

TEST_F(SceneClassifierTest, ServerCloudScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::SERVER_CLOUD);

    // Should inherit Linux rules
    EXPECT_EQ(classifier.calculateScenePriority("/var/log/auth.log", "auth.log", FileCategory::LOG_FILE), ScenePriority::CRITICAL);

    // Cloud-specific paths
    EXPECT_EQ(classifier.calculateScenePriority("/var/log/nginx/access.log", "access.log", FileCategory::LOG_FILE), ScenePriority::CRITICAL);
}

TEST_F(SceneClassifierTest, SceneTypeNoneReturnsIrrelevant) {
    FileClassifier classifier(":memory:", ":memory:");
    // Default is NONE - should return IRRELEVANT for any path
    EXPECT_EQ(classifier.calculateScenePriority("/data/data/com.android.providers.contacts/", "contacts.db", FileCategory::DATABASE), ScenePriority::IRRELEVANT);
    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/config/", "SAM", FileCategory::SYSTEM), ScenePriority::IRRELEVANT);
    EXPECT_EQ(classifier.calculateScenePriority("/var/log/auth.log", "auth.log", FileCategory::LOG_FILE), ScenePriority::IRRELEVANT);
}

TEST_F(SceneClassifierTest, LLMAnalysisScenePriority) {
    // Test LLM analysis scene priority sorting
    // Create a test database with scene columns
    std::string dbPath = "/tmp/test_llm_scene_priority.db";
    tempFiles_.push_back(dbPath);

    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &db), SQLITE_OK);

    const char* schema = R"(
        CREATE TABLE files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            extension TEXT,
            category TEXT,
            type TEXT,
            mtime INTEGER,
            ctime INTEGER,
            is_deleted INTEGER,
            md5 TEXT,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT,
            scene_type TEXT,
            scene_priority INTEGER DEFAULT 0,
            scene_relevant INTEGER DEFAULT 0
        );
        INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant)
            VALUES (100, 'contacts.db', '/data/data/com.android.providers.contacts/databases/contacts.db', 1024, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc', 'android', 100, 1);
        INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant)
            VALUES (101, 'settings.db', '/data/system/settings.db', 512, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'def', 'android', 75, 1);
        INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant)
            VALUES (102, 'unrelated.txt', '/tmp/unrelated.txt', 256, '.txt', 'DOCUMENT', 'REG', 1000, 1000, 0, 'ghi', '', 0, 0);
        INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant)
            VALUES (103, 'SAM', '/Windows/System32/config/SAM', 2048, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'jkl', '', 0, 0);
    )";
    ASSERT_EQ(sqlite3_exec(db, schema, nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(db);

    // Test with scene type set
    forensics::LLMAnalysisService service;
    service.setSceneType(SceneType::ANDROID);
    EXPECT_EQ(service.getSceneType(), SceneType::ANDROID);

    // Open database and test getScenePrioritizedFiles
    sqlite3* testDb;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &testDb), SQLITE_OK);

    auto prioritized = service.getScenePrioritizedFiles(testDb, 10);
    sqlite3_close(testDb);

    // Should return only scene-relevant files (scene_priority > 0), ordered by priority DESC
    ASSERT_EQ(prioritized.size(), 2u);
    EXPECT_EQ(prioritized[0].name, "contacts.db");
    EXPECT_EQ(prioritized[0].scenePriority, ScenePriority::CRITICAL);
    EXPECT_EQ(prioritized[0].sceneType, "android");
    EXPECT_EQ(prioritized[1].name, "settings.db");
    EXPECT_EQ(prioritized[1].scenePriority, ScenePriority::HIGH);

    // Test shouldSkipFile
    FileRecord highPriorityFile;
    highPriorityFile.scenePriority = ScenePriority::HIGH;
    EXPECT_FALSE(service.shouldSkipFile(highPriorityFile));

    FileRecord irrelevantFile;
    irrelevantFile.scenePriority = ScenePriority::IRRELEVANT;
    EXPECT_TRUE(service.shouldSkipFile(irrelevantFile));

    // Test shouldSkipFile with SceneType::NONE - should never skip
    forensics::LLMAnalysisService noneService;
    EXPECT_EQ(noneService.getSceneType(), SceneType::NONE);
    EXPECT_FALSE(noneService.shouldSkipFile(irrelevantFile));

    // Test getSceneSpecificPrompt
    FileRecord androidFile;
    androidFile.path = "/data/data/com.android.providers.contacts/databases/contacts.db";
    androidFile.name = "contacts.db";
    std::string prompt = service.getSceneSpecificPrompt(androidFile);
    EXPECT_NE(prompt.find("Android forensic analysis"), std::string::npos);
    EXPECT_NE(prompt.find("contacts.db"), std::string::npos);

    // Test Windows scene prompt
    forensics::LLMAnalysisService winService;
    winService.setSceneType(SceneType::WINDOWS);
    std::string winPrompt = winService.getSceneSpecificPrompt(androidFile);
    EXPECT_NE(winPrompt.find("Windows forensic analysis"), std::string::npos);

    // Test Linux scene prompt
    forensics::LLMAnalysisService linuxService;
    linuxService.setSceneType(SceneType::LINUX);
    std::string linuxPrompt = linuxService.getSceneSpecificPrompt(androidFile);
    EXPECT_NE(linuxPrompt.find("Linux forensic analysis"), std::string::npos);

    // Test Server/Cloud scene prompt
    forensics::LLMAnalysisService cloudService;
    cloudService.setSceneType(SceneType::SERVER_CLOUD);
    std::string cloudPrompt = cloudService.getSceneSpecificPrompt(androidFile);
    EXPECT_NE(cloudPrompt.find("Server/Cloud forensic analysis"), std::string::npos);

    // Test NONE scene prompt (no scene-specific text)
    forensics::LLMAnalysisService nonePromptService;
    std::string nonePrompt = nonePromptService.getSceneSpecificPrompt(androidFile);
    EXPECT_EQ(nonePrompt.find("forensic analysis"), std::string::npos);

    // Test with scene type NONE - should return all unanalyzed files
    sqlite3* noneDb;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &noneDb), SQLITE_OK);
    auto allFiles = noneService.getScenePrioritizedFiles(noneDb, 10);
    sqlite3_close(noneDb);
    EXPECT_EQ(allFiles.size(), 4u);
}

TEST_F(SceneClassifierTest, WindowsAppDataWildcardMatch) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::WINDOWS);

    // Should match paths with both "Users/" and "/AppData/"
    EXPECT_EQ(classifier.calculateScenePriority("/Users/john/AppData/Local/file.txt", "file.txt", FileCategory::SYSTEM), ScenePriority::HIGH);
    EXPECT_EQ(classifier.calculateScenePriority("/Users/Administrator/AppData/Roaming/config.ini", "config.ini", FileCategory::SYSTEM), ScenePriority::HIGH);
}

TEST_F(SceneClassifierTest, WindowsAppDataNoMatchOnPartialPath) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::WINDOWS);

    // Should NOT match paths with only "Users/" (no /AppData/)
    EXPECT_NE(classifier.calculateScenePriority("/Users/john/Documents/file.txt", "file.txt", FileCategory::DOCUMENT), ScenePriority::HIGH);

    // Should NOT match paths with only "/AppData/" (no Users/)
    EXPECT_NE(classifier.calculateScenePriority("/ProgramData/AppData/file.txt", "file.txt", FileCategory::SYSTEM), ScenePriority::HIGH);
}

// ============================================================================
// Integration Tests: classifyAndExtract with Scene Marking
// ============================================================================

TEST_F(SceneClassifierTest, ClassifyAndExtractWithAndroidScene) {
    std::string sourcePath = createSourceDb("android");
    std::string outputPath = "/tmp/test_scene_android_output.db";
    tempFiles_.push_back(outputPath);

    FileClassifier classifier(sourcePath, outputPath);
    classifier.setSceneType(SceneType::ANDROID);
    ASSERT_TRUE(classifier.classifyAndExtract());

    // Android contacts.db in /data/data/com.android.providers.contacts/ -> CRITICAL, relevant
    EXPECT_EQ(queryText(outputPath, "SELECT scene_type FROM files WHERE name='contacts.db'"), "android");
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='contacts.db'"), ScenePriority::CRITICAL);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='contacts.db'"), 1);

    // Windows SAM not in Android scene -> IRRELEVANT
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='SAM'"), ScenePriority::IRRELEVANT);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='SAM'"), 0);

    // Linux auth.log not in Android scene -> IRRELEVANT
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='auth.log'"), ScenePriority::IRRELEVANT);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='auth.log'"), 0);
}

TEST_F(SceneClassifierTest, ClassifyAndExtractWithWindowsScene) {
    std::string sourcePath = createSourceDb("windows");
    std::string outputPath = "/tmp/test_scene_windows_output.db";
    tempFiles_.push_back(outputPath);

    FileClassifier classifier(sourcePath, outputPath);
    classifier.setSceneType(SceneType::WINDOWS);
    ASSERT_TRUE(classifier.classifyAndExtract());

    // Windows SAM in /Windows/System32/config/ -> CRITICAL, relevant
    EXPECT_EQ(queryText(outputPath, "SELECT scene_type FROM files WHERE name='SAM'"), "windows");
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='SAM'"), ScenePriority::CRITICAL);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='SAM'"), 1);

    // Android contacts.db not in Windows scene -> IRRELEVANT
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='contacts.db'"), ScenePriority::IRRELEVANT);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='contacts.db'"), 0);
}

TEST_F(SceneClassifierTest, ClassifyAndExtractWithLinuxScene) {
    std::string sourcePath = createSourceDb("linux");
    std::string outputPath = "/tmp/test_scene_linux_output.db";
    tempFiles_.push_back(outputPath);

    FileClassifier classifier(sourcePath, outputPath);
    classifier.setSceneType(SceneType::LINUX);
    ASSERT_TRUE(classifier.classifyAndExtract());

    // Linux auth.log in /var/log/ -> CRITICAL, relevant
    EXPECT_EQ(queryText(outputPath, "SELECT scene_type FROM files WHERE name='auth.log'"), "linux");
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='auth.log'"), ScenePriority::CRITICAL);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='auth.log'"), 1);

    // Android contacts.db not in Linux scene -> IRRELEVANT
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='contacts.db'"), ScenePriority::IRRELEVANT);
}

TEST_F(SceneClassifierTest, ClassifyAndExtractWithNoScene) {
    std::string sourcePath = createSourceDb("none");
    std::string outputPath = "/tmp/test_scene_none_output.db";
    tempFiles_.push_back(outputPath);

    FileClassifier classifier(sourcePath, outputPath);
    // SceneType::NONE is the default, do not set scene
    ASSERT_TRUE(classifier.classifyAndExtract());

    // With no scene, scene_type should be empty and priorities should be 0
    EXPECT_EQ(queryText(outputPath, "SELECT scene_type FROM files WHERE name='contacts.db'"), "");
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='contacts.db'"), 0);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='contacts.db'"), 0);

    EXPECT_EQ(queryText(outputPath, "SELECT scene_type FROM files WHERE name='SAM'"), "");
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='SAM'"), 0);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='SAM'"), 0);

    EXPECT_EQ(queryText(outputPath, "SELECT scene_type FROM files WHERE name='auth.log'"), "");
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_priority FROM files WHERE name='auth.log'"), 0);
    EXPECT_EQ(queryInt(outputPath, "SELECT scene_relevant FROM files WHERE name='auth.log'"), 0);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
