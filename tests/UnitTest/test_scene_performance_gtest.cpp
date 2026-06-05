#include <gtest/gtest.h>
#include <sqlite3.h>
#include <chrono>
#include <cstdio>
#include <string>

class ScenePerformanceTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbPath_ = "/tmp/test_scene_performance.db";

        sqlite3* db;
        ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

        const char* createTable = R"(
            CREATE TABLE IF NOT EXISTS files (
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
                scene_type TEXT,
                scene_priority INTEGER DEFAULT 0,
                scene_relevant INTEGER DEFAULT 0,
                llm_analyzed_at INTEGER
            );
        )";
        ASSERT_EQ(sqlite3_exec(db, createTable, nullptr, nullptr, nullptr), SQLITE_OK);

        const char* insertFiles = R"(
            INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) VALUES
            (1, 'contacts.db', '/data/data/com.android.providers.contacts/databases/contacts.db', 1024, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc1', 'android', 100, 1),
            (2, 'sms.db', '/data/data/com.android.providers.telephony/databases/sms.db', 2048, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc2', 'android', 100, 1),
            (3, 'mm.db', '/data/data/com.tencent.mm/databases/mm.db', 4096, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc3', 'android', 75, 1),
            (4, 'telegram.db', '/data/data/org.telegram.messenger/databases/telegram.db', 2048, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc4', 'android', 75, 1),
            (5, 'build.prop', '/system/build.prop', 512, '.prop', 'SYSTEM', 'REG', 1000, 1000, 0, 'abc5', 'android', 75, 1),
            (6, 'settings.db', '/data/system/users/0/settings.db', 1024, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc6', 'android', 100, 1),
            (7, 'packages.xml', '/data/system/packages.xml', 2048, '.xml', 'SYSTEM', 'REG', 1000, 1000, 0, 'abc7', 'android', 50, 1),
            (8, 'app.apk', '/data/app/com.example.app/app.apk', 10240, '.apk', 'ARCHIVE', 'REG', 1000, 1000, 0, 'abc8', 'android', 50, 1),
            (9, 'cache.db', '/data/data/com.android.chrome/cache/cache.db', 512, '.db', 'DATABASE', 'REG', 1000, 1000, 0, 'abc9', 'android', 25, 0),
            (10, 'log.txt', '/data/log/log.txt', 256, '.txt', 'LOG_FILE', 'REG', 1000, 1000, 0, 'abc10', 'android', 25, 0),

            (11, 'SAM', '/Windows/System32/config/SAM', 2048, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'def1', 'windows', 100, 1),
            (12, 'SYSTEM', '/Windows/System32/config/SYSTEM', 4096, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'def2', 'windows', 100, 1),
            (13, 'SOFTWARE', '/Windows/System32/config/SOFTWARE', 8192, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'def3', 'windows', 100, 1),
            (14, 'System.evtx', '/Windows/System32/winevt/Logs/System.evtx', 1024, '.evtx', 'SYSTEM', 'REG', 1000, 1000, 0, 'def4', 'windows', 100, 1),
            (15, 'Security.evtx', '/Windows/System32/winevt/Logs/Security.evtx', 2048, '.evtx', 'SYSTEM', 'REG', 1000, 1000, 0, 'def5', 'windows', 100, 1),
            (16, 'NTUSER.DAT', '/Users/Administrator/NTUSER.DAT', 4096, '.dat', 'SYSTEM', 'REG', 1000, 1000, 0, 'def6', 'windows', 100, 1),
            (17, 'Chrome_History', '/Users/Administrator/AppData/Local/Google/Chrome/User Data/Default/History', 512, '', 'DATABASE', 'REG', 1000, 1000, 0, 'def7', 'windows', 75, 1),
            (18, 'prefetch.pf', '/Windows/Prefetch/CHROME.EXE-12345678.pf', 256, '.pf', 'SYSTEM', 'REG', 1000, 1000, 0, 'def8', 'windows', 75, 1),
            (19, 'desktop.ini', '/Windows/desktop.ini', 128, '.ini', 'SYSTEM', 'REG', 1000, 1000, 0, 'def9', 'windows', 25, 0),
            (20, 'notepad.exe', '/Windows/System32/notepad.exe', 2048, '.exe', 'EXECUTABLE', 'REG', 1000, 1000, 0, 'def10', 'windows', 25, 0),

            (21, 'auth.log', '/var/log/auth.log', 1024, '.log', 'LOG_FILE', 'REG', 1000, 1000, 0, 'ghi1', 'linux', 100, 1),
            (22, 'syslog', '/var/log/syslog', 2048, '.log', 'LOG_FILE', 'REG', 1000, 1000, 0, 'ghi2', 'linux', 100, 1),
            (23, 'passwd', '/etc/passwd', 512, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'ghi3', 'linux', 100, 1),
            (24, 'shadow', '/etc/shadow', 256, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'ghi4', 'linux', 100, 1),
            (25, 'crontab', '/etc/crontab', 128, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'ghi5', 'linux', 100, 1),
            (26, 'authorized_keys', '/home/user/.ssh/authorized_keys', 256, '', 'SYSTEM', 'REG', 1000, 1000, 0, 'ghi6', 'linux', 100, 1),
            (27, 'bash_history', '/home/user/.bash_history', 512, '.history', 'SYSTEM', 'REG', 1000, 1000, 0, 'ghi7', 'linux', 75, 1),
            (28, 'nginx.conf', '/etc/nginx/nginx.conf', 1024, '.conf', 'SYSTEM', 'REG', 1000, 1000, 0, 'ghi8', 'linux', 75, 1),
            (29, 'apt.log', '/var/log/apt/history.log', 256, '.log', 'LOG_FILE', 'REG', 1000, 1000, 0, 'ghi9', 'linux', 25, 0),
            (30, 'kernel.log', '/var/log/kern.log', 128, '.log', 'LOG_FILE', 'REG', 1000, 1000, 0, 'ghi10', 'linux', 25, 0),

            (31, 'readme.txt', '/home/user/documents/readme.txt', 512, '.txt', 'DOCUMENT', 'REG', 1000, 1000, 0, 'jkl1', NULL, 0, 0),
            (32, 'photo.jpg', '/home/user/pictures/photo.jpg', 10240, '.jpg', 'IMAGE', 'REG', 1000, 1000, 0, 'jkl2', NULL, 0, 0),
            (33, 'music.mp3', '/home/user/music/music.mp3', 51200, '.mp3', 'AUDIO', 'REG', 1000, 1000, 0, 'jkl3', NULL, 0, 0),
            (34, 'video.mp4', '/home/user/videos/video.mp4', 102400, '.mp4', 'VIDEO', 'REG', 1000, 1000, 0, 'jkl4', NULL, 0, 0),
            (35, 'archive.zip', '/home/user/downloads/archive.zip', 20480, '.zip', 'ARCHIVE', 'REG', 1000, 1000, 0, 'jkl5', NULL, 0, 0),
            (36, 'document.pdf', '/home/user/documents/document.pdf', 4096, '.pdf', 'DOCUMENT', 'REG', 1000, 1000, 0, 'jkl6', NULL, 0, 0),
            (37, 'spreadsheet.xlsx', '/home/user/documents/spreadsheet.xlsx', 2048, '.xlsx', 'DOCUMENT', 'REG', 1000, 1000, 0, 'jkl7', NULL, 0, 0),
            (38, 'presentation.pptx', '/home/user/documents/presentation.pptx', 8192, '.pptx', 'DOCUMENT', 'REG', 1000, 1000, 0, 'jkl8', NULL, 0, 0),
            (39, 'code.py', '/home/user/projects/code.py', 256, '.py', 'SOURCE_CODE', 'REG', 1000, 1000, 0, 'jkl9', NULL, 0, 0),
            (40, 'config.json', '/home/user/config/config.json', 128, '.json', 'DOCUMENT', 'REG', 1000, 1000, 0, 'jkl10', NULL, 0, 0);
        )";
        ASSERT_EQ(sqlite3_exec(db, insertFiles, nullptr, nullptr, nullptr), SQLITE_OK);

        sqlite3_close(db);
    }

    void TearDown() override {
        std::remove(dbPath_.c_str());
    }

    std::string dbPath_;
};

// ============================================================================
// Basic Count Verification Tests
// ============================================================================

TEST_F(ScenePerformanceTest, CountTotalFiles) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG'", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int totalFiles = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    EXPECT_EQ(totalFiles, 40);
}

TEST_F(ScenePerformanceTest, CountAndroidRelevantFiles) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE scene_type = 'android' AND scene_priority > 0", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int androidFiles = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // All 10 Android files have priority > 0
    EXPECT_EQ(androidFiles, 10);
}

TEST_F(ScenePerformanceTest, CountWindowsRelevantFiles) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE scene_type = 'windows' AND scene_priority > 0", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int windowsFiles = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // All 10 Windows files have priority > 0
    EXPECT_EQ(windowsFiles, 10);
}

TEST_F(ScenePerformanceTest, CountLinuxRelevantFiles) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE scene_type = 'linux' AND scene_priority > 0", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int linuxFiles = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // All 10 Linux files have priority > 0
    EXPECT_EQ(linuxFiles, 10);
}

// ============================================================================
// Priority-Based Count Tests
// ============================================================================

TEST_F(ScenePerformanceTest, CountHighPriorityFiles) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE scene_priority >= 75", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int highPriorityFiles = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // Android (6): contacts, sms, mm, telegram, build.prop, settings
    // Windows (8): SAM, SYSTEM, SOFTWARE, System.evtx, Security.evtx, NTUSER, Chrome, prefetch
    // Linux (8): auth.log, syslog, passwd, shadow, crontab, authorized_keys, bash_history, nginx.conf
    // Total: 22 files
    EXPECT_EQ(highPriorityFiles, 22);
}

TEST_F(ScenePerformanceTest, CountCriticalPriorityFiles) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE scene_priority = 100", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int criticalFiles = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // Android (3): contacts, sms, settings
    // Windows (6): SAM, SYSTEM, SOFTWARE, System.evtx, Security.evtx, NTUSER
    // Linux (6): auth.log, syslog, passwd, shadow, crontab, authorized_keys
    // Total: 15 files
    EXPECT_EQ(criticalFiles, 15);
}

// ============================================================================
// LLM Analysis Optimization Tests
// ============================================================================

TEST_F(ScenePerformanceTest, LLMAnalysisOptimization) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;

    // Without scene specialization: analyze all files not yet analyzed
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int allFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    // With Android scene specialization: only analyze Android files with priority > 0
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'android' AND scene_priority > 0", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int androidFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    // With Windows scene specialization: only analyze Windows files with priority > 0
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'windows' AND scene_priority > 0", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int windowsFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    // With Linux scene specialization: only analyze Linux files with priority > 0
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'linux' AND scene_priority > 0", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int linuxFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    sqlite3_close(db);

    // Verify raw counts
    EXPECT_EQ(allFilesForLLM, 40);       // All files need analysis
    EXPECT_EQ(androidFilesForLLM, 10);   // Only Android files
    EXPECT_EQ(windowsFilesForLLM, 10);   // Only Windows files
    EXPECT_EQ(linuxFilesForLLM, 10);     // Only Linux files

    // Calculate optimization percentages
    double androidOptimization = (1.0 - static_cast<double>(androidFilesForLLM) / allFilesForLLM) * 100;
    double windowsOptimization = (1.0 - static_cast<double>(windowsFilesForLLM) / allFilesForLLM) * 100;
    double linuxOptimization = (1.0 - static_cast<double>(linuxFilesForLLM) / allFilesForLLM) * 100;

    // Verify at least 70% optimization (10/40 = 25% of files analyzed, 75% reduction)
    EXPECT_GE(androidOptimization, 70.0);
    EXPECT_GE(windowsOptimization, 70.0);
    EXPECT_GE(linuxOptimization, 70.0);

    // Log results for visibility
    std::cout << "\n=== LLM Analysis Optimization Results ===" << std::endl;
    std::cout << "Total files for analysis: " << allFilesForLLM << std::endl;
    std::cout << "Android scene files: " << androidFilesForLLM
              << " (" << androidOptimization << "% reduction)" << std::endl;
    std::cout << "Windows scene files: " << windowsFilesForLLM
              << " (" << windowsOptimization << "% reduction)" << std::endl;
    std::cout << "Linux scene files: " << linuxFilesForLLM
              << " (" << linuxOptimization << "% reduction)" << std::endl;
}

TEST_F(ScenePerformanceTest, HighPriorityAnalysisOptimization) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;

    // Without scene specialization: analyze all files
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int allFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    // With scene specialization and high priority threshold
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_priority >= 75", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int highPriorityFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    sqlite3_close(db);

    // Verify optimization results
    EXPECT_EQ(allFilesForLLM, 40);          // All files
    EXPECT_EQ(highPriorityFilesForLLM, 22); // Only high priority files

    // Calculate optimization percentage
    double optimization = (1.0 - static_cast<double>(highPriorityFilesForLLM) / allFilesForLLM) * 100;

    // Verify at least 40% optimization (22/40 = 55% of files, so 45% reduction)
    EXPECT_GE(optimization, 40.0);

    // Log results
    std::cout << "\n=== High Priority Analysis Optimization ===" << std::endl;
    std::cout << "Total files: " << allFilesForLLM << std::endl;
    std::cout << "High priority files: " << highPriorityFilesForLLM
              << " (" << optimization << "% reduction)" << std::endl;
}

TEST_F(ScenePerformanceTest, CriticalPriorityAnalysisOptimization) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;

    // Without scene specialization: analyze all files
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int allFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    // With scene specialization and critical priority threshold
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_priority = 100", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int criticalFilesForLLM = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    sqlite3_close(db);

    // Verify optimization results
    EXPECT_EQ(allFilesForLLM, 40);         // All files
    EXPECT_EQ(criticalFilesForLLM, 15);    // Only critical files (3 Android + 6 Windows + 6 Linux)

    // Calculate optimization percentage
    double optimization = (1.0 - static_cast<double>(criticalFilesForLLM) / allFilesForLLM) * 100;

    // Verify at least 60% optimization (15/40 = 37.5% of files, so 62.5% reduction)
    EXPECT_GE(optimization, 60.0);

    // Log results
    std::cout << "\n=== Critical Priority Analysis Optimization ===" << std::endl;
    std::cout << "Total files: " << allFilesForLLM << std::endl;
    std::cout << "Critical priority files: " << criticalFilesForLLM
              << " (" << optimization << "% reduction)" << std::endl;
}

// ============================================================================
// Timing Performance Tests
// ============================================================================

TEST_F(ScenePerformanceTest, QueryTimingComparison) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    const int iterations = 1000;

    // Time the "analyze all" query (no scene specialization)
    auto startAll = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        ASSERT_EQ(sqlite3_prepare_v2(db,
            "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)",
            -1, &stmt, nullptr), SQLITE_OK);
        ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
        sqlite3_finalize(stmt);
    }
    auto endAll = std::chrono::high_resolution_clock::now();
    auto durationAll = std::chrono::duration_cast<std::chrono::microseconds>(endAll - startAll).count();

    // Time the "scene-specialized" query (Android only)
    auto startScene = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        ASSERT_EQ(sqlite3_prepare_v2(db,
            "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'android' AND scene_priority > 0",
            -1, &stmt, nullptr), SQLITE_OK);
        ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
        sqlite3_finalize(stmt);
    }
    auto endScene = std::chrono::high_resolution_clock::now();
    auto durationScene = std::chrono::duration_cast<std::chrono::microseconds>(endScene - startScene).count();

    sqlite3_close(db);

    // Log timing results
    std::cout << "\n=== Query Timing Comparison (" << iterations << " iterations) ===" << std::endl;
    std::cout << "Analyze-all query: " << durationAll << " us total, "
              << (static_cast<double>(durationAll) / iterations) << " us/query" << std::endl;
    std::cout << "Scene-specialized query: " << durationScene << " us total, "
              << (static_cast<double>(durationScene) / iterations) << " us/query" << std::endl;

    // Both queries should complete in reasonable time
    // The key metric is not query speed but the number of files that would be sent to LLM
    EXPECT_GT(durationAll, 0);
    EXPECT_GT(durationScene, 0);
}

TEST_F(ScenePerformanceTest, CombinedOptimizationSummary) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;

    // Count all unanalyzed files
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    int total = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);

    // Count scene-specific files at various priority levels
    auto countQuery = [&](const char* sql) -> int {
        sqlite3_stmt* s;
        if (sqlite3_prepare_v2(db, sql, -1, &s, nullptr) != SQLITE_OK) return -1;
        int count = 0;
        if (sqlite3_step(s) == SQLITE_ROW) {
            count = sqlite3_column_int(s, 0);
        }
        sqlite3_finalize(s);
        return count;
    };

    int sceneAny = countQuery(
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_priority > 0");
    int sceneHigh = countQuery(
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_priority >= 75");
    int sceneCritical = countQuery(
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_priority = 100");
    int sceneAndroid = countQuery(
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'android' AND scene_priority > 0");
    int sceneWindows = countQuery(
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'windows' AND scene_priority > 0");
    int sceneLinux = countQuery(
        "SELECT COUNT(*) FROM files WHERE type = 'REG' AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) AND scene_type = 'linux' AND scene_priority > 0");

    sqlite3_close(db);

    // Verify counts are within expected ranges
    EXPECT_EQ(total, 40);
    EXPECT_EQ(sceneAny, 30);       // All scene-tagged files with priority > 0
    EXPECT_EQ(sceneHigh, 22);      // High priority across all scenes
    EXPECT_EQ(sceneCritical, 15);  // Critical priority across all scenes
    EXPECT_EQ(sceneAndroid, 10);   // Android-only
    EXPECT_EQ(sceneWindows, 10);   // Windows-only
    EXPECT_EQ(sceneLinux, 10);     // Linux-only

    // Print combined summary
    auto pct = [](int part, int whole) -> double {
        return (1.0 - static_cast<double>(part) / whole) * 100.0;
    };

    std::cout << "\n=== Combined LLM Analysis Optimization Summary ===" << std::endl;
    std::cout << "Total files: " << total << std::endl;
    std::cout << std::endl;
    std::cout << "Strategy                          | Files | Reduction" << std::endl;
    std::cout << "----------------------------------|-------|----------" << std::endl;
    std::cout << "No optimization (all files)       | " << total << "      | 0.0%" << std::endl;
    std::cout << "Any scene priority > 0            | " << sceneAny << "      | " << pct(sceneAny, total) << "%" << std::endl;
    std::cout << "High priority (>= 75)             | " << sceneHigh << "      | " << pct(sceneHigh, total) << "%" << std::endl;
    std::cout << "Critical priority (= 100)         | " << sceneCritical << "      | " << pct(sceneCritical, total) << "%" << std::endl;
    std::cout << "Android scene only                | " << sceneAndroid << "      | " << pct(sceneAndroid, total) << "%" << std::endl;
    std::cout << "Windows scene only                | " << sceneWindows << "      | " << pct(sceneWindows, total) << "%" << std::endl;
    std::cout << "Linux scene only                  | " << sceneLinux << "      | " << pct(sceneLinux, total) << "%" << std::endl;
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
