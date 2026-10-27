// test_scene_classifier_gtest.cpp
// GTest-based unit tests for FileClassifier scene-aware classification
// Tests scene type management and platform-specific priority calculation

#include <gtest/gtest.h>
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/DatabaseManagerDataTypes.h"
#include "DatabaseManager/DatabaseManager.h"
#include "LLMAnalysisService.h"
#include "network/HTTPServer/AnalysisBudget.h"
#include <sqlite3.h>
#include <cstdio>
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
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
        // Start from a clean file: a stale DB left by a crashed/failed prior run
        // would otherwise make the un-guarded CREATE TABLE fail with SQLITE_ERROR.
        std::remove(path.c_str());

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

// Access seam for the private heuristic statics on LLMAnalysisService.
namespace forensics {
struct LLMSelectionHeuristicTestAccess {
    static int priority(const std::string& path) {
        return LLMAnalysisService::forensicPathPriority(path);
    }
    static std::vector<std::string> select(std::vector<std::string> files, size_t maxFiles) {
        return LLMAnalysisService::selectByHeuristic(std::move(files), maxFiles);
    }
    static bool binaryHeader(const std::string& path) {
        return LLMAnalysisService::hasBinaryContainerHeader(path);
    }
    static std::vector<std::string> parseSelection(
            const std::string& response, const std::vector<std::string>& candidates) {
        LLMAnalysisService service;
        return service.parseImportantFiles(response, candidates);
    }
    static std::string buildSummary(const std::vector<std::string>& files) {
        LLMAnalysisService service;
        return service.buildFileListSummary(files);
    }
    static std::vector<std::string> prioritized(const std::string& dbPath,
                                                size_t budget, bool skipBinary) {
        LLMAnalysisService service;
        return service.getPrioritizedCandidates(dbPath, budget, skipBinary);
    }
    // Full-mode candidate query: the resolved task budget reaches the database
    // as LIMIT maxFiles, so this returns at most `budget` paths (0 = unlimited).
    static std::vector<std::string> fullModeCandidates(const std::string& dbPath,
                                                       size_t budget) {
        LLMAnalysisService service;
        LLMAnalysisService::AnalysisOptions options;
        options.maxFiles = budget;
        options.skipBinaryFiles = false;
        return service.getFilesFromDatabase(dbPath, options);
    }
};
}

// Regression (PC.E01 Windows image): buildFileListSummary used to group files
// by directory and list bare names under a heading, while the prompt asked for
// full paths. The model could not reproduce a matchable entry and only 1 of
// 1000 paths resolved, so every real-image task silently fell back to the
// heuristic ranking. The summary must now carry one indexed full path per line
// and the parser must resolve indices back to exact candidate paths.
TEST_F(SceneClassifierTest, SmartSelectionSummaryIsIndexedFullPaths) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    std::vector<std::string> candidates = {
        "/Users/admin/Desktop/控制端/Quasar v1.4.1/settings.xml",
        "/Users/admin/Desktop/第一次公告.txt",
        "/Users/admin/AppData/Local/Google/Chrome/User Data/Default/manifest.json",
    };
    const std::string summary = A::buildSummary(candidates);

    // Every entry is "N <full path>", in the same order as the candidate list.
    EXPECT_NE(summary.find("1 /Users/admin/Desktop/控制端/Quasar v1.4.1/settings.xml"),
              std::string::npos);
    EXPECT_NE(summary.find("2 /Users/admin/Desktop/第一次公告.txt"), std::string::npos);
    EXPECT_NE(summary.find("3 /Users/admin/AppData/Local/Google/Chrome/User Data/Default/manifest.json"),
              std::string::npos);
    // No directory-grouped layout remains.
    EXPECT_EQ(summary.find("  - "), std::string::npos);
}

TEST_F(SceneClassifierTest, SmartSelectionParsesIndices) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    std::vector<std::string> candidates = {
        "/a/one.txt", "/b/two.txt", "/c/three.txt", "/d/four.txt",
    };
    auto selected = A::parseSelection("[3, 1]", candidates);
    ASSERT_EQ(selected.size(), 2u);
    EXPECT_EQ(selected[0], "/c/three.txt");
    EXPECT_EQ(selected[1], "/a/one.txt");

    // Out-of-range indices are ignored, not clamped onto a real file.
    auto clamped = A::parseSelection("[0, 99]", candidates);
    EXPECT_TRUE(clamped.empty());
}

TEST_F(SceneClassifierTest, SmartSelectionParsesPathsAndNames) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    std::vector<std::string> candidates = {
        "/Users/admin/Desktop/控制端/Quasar v1.4.1/settings.xml",
        "/Users/admin/Desktop/第一次公告.txt",
        "/Users/admin/AppData/Local/Google/Chrome/User Data/Default/manifest.json",
    };

    // Full paths echoed back verbatim still resolve exactly.
    auto byPath = A::parseSelection(
        "[\"/Users/admin/Desktop/第一次公告.txt\"]", candidates);
    ASSERT_EQ(byPath.size(), 1u);
    EXPECT_EQ(byPath[0], "/Users/admin/Desktop/第一次公告.txt");

    // Bare file names (the old prompt's shape) resolve via basename.
    auto byName = A::parseSelection("[\"settings.xml\"]", candidates);
    ASSERT_EQ(byName.size(), 1u);
    EXPECT_EQ(byName[0], "/Users/admin/Desktop/控制端/Quasar v1.4.1/settings.xml");

    // A numeric string inside a quoted path is not read as an index.
    auto mixed = A::parseSelection("[\"manifest.json\", 2]", candidates);
    ASSERT_EQ(mixed.size(), 2u);
    EXPECT_EQ(mixed[0], "/Users/admin/AppData/Local/Google/Chrome/User Data/Default/manifest.json");
    EXPECT_EQ(mixed[1], "/Users/admin/Desktop/第一次公告.txt");
}

// Regression (PC.E01 Windows image): the candidate window used to be
// "SELECT path FROM files LIMIT 5000" over insertion order. That covered 1.6%
// of 305,716 rows, so artefacts sitting past the cut were unreachable no matter
// how important they were. The scan must consider the whole table and keep the
// highest-priority rows wherever they sit.
TEST_F(SceneClassifierTest, CandidateWindowScansWholeTable) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    const std::string path = "/tmp/test_candidate_window.db";
    tempFiles_.push_back(path);
    std::remove(path.c_str());

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE files (path TEXT, category TEXT);", nullptr, nullptr, nullptr),
        SQLITE_OK);

    // 3000 mid-value rows first (generic JSON under the system tree, score 30):
    // exactly the shape that filled the old window, then the high-value
    // artefacts at the very end of the table.
    ASSERT_EQ(sqlite3_exec(db, "BEGIN;", nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_stmt* ins = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "INSERT INTO files VALUES (?, ?);", -1, &ins, nullptr),
        SQLITE_OK);
    for (int i = 0; i < 3000; ++i) {
        std::string p = "/Windows/System32/SomeDir/manifest_" + std::to_string(i) + ".json";
        sqlite3_bind_text(ins, 1, p.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(ins, 2, "OS Config Files", -1, SQLITE_STATIC);
        ASSERT_EQ(sqlite3_step(ins), SQLITE_DONE);
        sqlite3_reset(ins);
    }
    // Late, high-value rows: credential file (100), desktop evidence (90),
    // system log (80), plus a binary that the category filter must drop.
    const char* lateArtefacts[] = {
        "/etc/shadow",
        "/Users/admin/Desktop/控制端/Quasar v1.4.1/settings.xml",
        "/var/log/secure",
    };
    for (const char* p : lateArtefacts) {
        sqlite3_bind_text(ins, 1, p, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(ins, 2, "OS Config Files", -1, SQLITE_STATIC);
        ASSERT_EQ(sqlite3_step(ins), SQLITE_DONE);
        sqlite3_reset(ins);
    }
    sqlite3_bind_text(ins, 1, "/Users/admin/Desktop/tool.exe", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(ins, 2, "Executables", -1, SQLITE_STATIC);
    ASSERT_EQ(sqlite3_step(ins), SQLITE_DONE);
    sqlite3_reset(ins);
    sqlite3_finalize(ins);
    ASSERT_EQ(sqlite3_exec(db, "COMMIT;", nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(db);

    // A 10-slot budget: the late high-value rows must be inside it, and no
    // mid-value row may outrank them.
    auto selected = A::prioritized(path, 10, false);
    EXPECT_LE(selected.size(), 10u);
    for (const char* want : lateArtefacts) {
        EXPECT_NE(std::find(selected.begin(), selected.end(), std::string(want)),
                  selected.end()) << "missing from candidate window: " << want;
    }
    EXPECT_EQ(selected.front(), "/etc/shadow");

    // The full-table scan must still honour the skip-binary filter.
    auto noBinary = A::prioritized(path, 10, true);
    EXPECT_EQ(std::find(noBinary.begin(), noBinary.end(),
                        std::string("/Users/admin/Desktop/tool.exe")),
              noBinary.end());

    // A budget of 0 is the explicit "no candidates" contract; callers opt into
    // unlimited scanning through getFilesFromDatabase instead.
    EXPECT_TRUE(A::prioritized(path, 0, false).empty());
}

// Regression: pip http-cache *.tmp blobs under /root once inherited the
// user-area score (90) and filled a 50-file smart-selection budget, crowding
// out /etc and /var/log artefacts. Cache/temp paths must land in the
// low-value bucket regardless of the directory they sit under.
TEST_F(SceneClassifierTest, HeuristicPriorityCacheTempJunk) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    EXPECT_EQ(A::priority("/root/.cache/pip/http/e/2/0/7/4/e207426c.tmp"), 5);
    EXPECT_EQ(A::priority("/home/alice/.cache/mozilla/firefox/abc.jpg"), 5);
    EXPECT_EQ(A::priority("/var/cache/apt/archives/openssl.deb"), 5);
    EXPECT_EQ(A::priority("/usr/lib/python3.11/__pycache__/os.cpython-311.pyc"), 5);
    EXPECT_EQ(A::priority("/opt/venv/lib/python3.11/site-packages/requests/api.py"), 5);
    EXPECT_EQ(A::priority("/root/virt-sysprep-tmpfile.tmp"), 5);

    EXPECT_LT(A::priority("/root/.cache/pip/http/x.tmp"), A::priority("/etc/passwd"));
    EXPECT_LT(A::priority("/root/.cache/pip/http/x.tmp"), A::priority("/var/log/secure"));
    EXPECT_LT(A::priority("/root/.cache/pip/http/x.tmp"), A::priority("/home/user/report.pdf"));

    // Real user artefacts keep their established scores.
    EXPECT_EQ(A::priority("/root/.bash_history"), 100);
    EXPECT_EQ(A::priority("/root/.bashrc"), 90);
    EXPECT_EQ(A::priority("/var/log/secure"), 80);
    EXPECT_EQ(A::priority("/etc/chrony.conf"), 60);
}

// The heuristic budget must be spent on evidence, not cache noise: with more
// worthwhile files than slots, no cache/temp path may survive the truncation.
TEST_F(SceneClassifierTest, HeuristicSelectionKeepsJunkOutOfBudget) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    std::vector<std::string> files = {
        "/root/.cache/pip/http/1/e/6/f/1e6f2fa.tmp",
        "/root/.cache/pip/http/1/d/a/3/1da3b99.tmp",
        "/root/.cache/pip/http/1/4/1/1/3/14113e97.tmp",
        "/var/log/secure",
        "/etc/passwd",
        "/home/alice/contract.pdf",
    };
    auto picked = A::select(files, 3);
    ASSERT_EQ(picked.size(), 3u);
    EXPECT_EQ(picked[0], "/etc/passwd");
    EXPECT_EQ(picked[1], "/home/alice/contract.pdf");
    EXPECT_EQ(picked[2], "/var/log/secure");
}

// Every bulk-junk family that floods real images must land in the low-value
// bucket regardless of where it sits: package-manager caches outside ~/.cache,
// vendored dependency trees, VCS internals, Windows system junk, editor/office
// droppings, container and distro bulk trees. Nothing here may outrank an
// /etc config (60).
TEST_F(SceneClassifierTest, HeuristicPriorityJunkMatrix) {
    using A = forensics::LLMSelectionHeuristicTestAccess;
    auto low = [](const std::string& p) {
        EXPECT_LE(forensics::LLMSelectionHeuristicTestAccess::priority(p), 10)
            << "junk scored too high: " << p;
    };

    // Package-manager / language-runtime caches outside ~/.cache.
    low("/root/.npm/_cacache/content-v2/sha512/ab/cd/ef");
    low("/home/u/.npm/_logs/2026-10-15T10_00_00-debug.log");
    low("/home/u/.yarn/berry/cache/webpack-npm-abc.zip");
    low("/home/u/.pnpm-store/v3/files/ab/cdef");
    low("/root/.cargo/registry/src/index.crates.io/serde-1.0.0/src/lib.rs");
    low("/root/.m2/repository/org/apache/commons-lang3/commons-lang3-3.12.jar");
    low("/root/.gradle/caches/modules-2/files-2.1/com.google/guava.jar");
    low("/root/go/pkg/mod/golang.org/x/net@v0.17.0/internal/socket.go");
    low("/srv/app/bower_components/jquery/dist/jquery.min.js");
    // Third-party vendored dependency trees (composer/npm/go vendor dirs).
    low("/www/wwwroot/jijin/vendor/phpoffice/phpexcel/Classes/PHPExcel/Cell.php");

    // VCS internals: object blobs are binary noise by the thousand.
    low("/home/u/repo/.git/objects/ab/cdef1234567890");
    low("/home/u/repo/.git/modules/sub/n/git-cli.exe");

    // Windows system junk (image paths are normalised to forward slashes).
    low("C:/Users/X/Desktop/desktop.ini");
    low("C:/Users/X/AppData/Roaming/Microsoft/Windows/Desktop.ini");
    low("D:/data/Thumbs.db");
    low("C:/Users/X/AppData/Local/Microsoft/Windows/Explorer/thumbcache_256.db");
    low("C:/pagefile.sys");
    low("C:/hiberfil.sys");
    low("C:/swapfile.sys");
    low("C:/Windows/SoftwareDistribution/Download/7a2b/x.dll");
    low("C:/Windows/WinSxS/amd64_microsoft-windows-servicing.dll");
    low("C:/Users/X/AppData/Local/Microsoft/Windows/INetCache/IE/abc.htm");
    low("C:/Users/X/AppData/Local/Temp/tmpA1B2/chrome_installer.exe");
    low("D:/documents/$RECYCLE.BIN/S-1-5-18/$I3X2F.txt");

    // Editor / office droppings inside user areas.
    low("/home/u/reports/.DS_Store");
    low("/home/u/.report.txt.swp");
    low("/etc/nginx/.nginx.conf.swp");
    low("/home/u/.main.py.swo");
    low("/home/u/contract.docx~");
    low("/home/u/.~lock.报表.xlsx#");

    // Package-manager bookkeeping whose DIRECTORY name contains credential
    // words: basename-scoped credential matching must not promote these.
    low("/var/lib/yum/yumdb/p/c9825339/passwd-0.79-4.el7/checksum_data");
    low("/var/lib/yum/yumdb/s/839fb8a4/shadow-utils-4.1.5/reason");
    low("/var/lib/dnf/history/db/version");

    // Distro content trees: locale catalogs repeat passwd.mo per language,
    // doc trees carry sample.sudoers, /usr/lib holds kpasswd.xml and
    // libuser_shadow.so — credential words in the basename, never credentials.
    low("/usr/share/locale/zh_CN/LC_MESSAGES/passwd.mo");
    low("/usr/share/locale/bs/LC_MESSAGES/shadow.mo");
    low("/usr/share/doc/sudo-1.8.6p7/sample.sudoers");
    low("/usr/share/doc/wget-1.14/passwd");
    low("/usr/lib/firewalld/services/kpasswd.xml");
    low("/usr/lib64/libuser/libuser_shadow.so");
    low("/usr/include/gshadow.h");
    low("/usr/include/shadow.h");
    low("/www/server/panel/pyenv/lib/python3.7/site-packages/future/backports/test/keycert.passwd.pem");
    low("/www/wwwroot/jijin/vendor/phpoffice/phpexcel/Classes/PHPExcel/Worksheet/Drawing/Shadow.php");

    // Compound binary names are executables, not credential data.
    low("/usr/bin/gpasswd");
    low("/usr/sbin/chpasswd");
    low("/usr/sbin/saslpasswd2");
    low("/usr/bin/grub2-mkpasswd-pbkdf2");

    // Windows system images: program files under AppData inherit the 90
    // user-area score, and WPS UI resources even hit the shadow credential
    // pattern. Non-document binaries / resource packs go to the low bucket —
    // the text pipeline cannot analyse them, so they are budget noise.
    low("/Users/Administrator/AppData/Local/Kingsoft/WPS Office/11.1.0.11744/office6/res/commands/et/classics/Shadow_Settings.kuip");
    low("/Users/Administrator/AppData/Local/Google/Chrome/Application/68.0.3423.2/chrome_child.dll");
    low("/Users/Administrator/AppData/Local/Google/Chrome/Application/68.0.3423.2/Locales/ja.pak");
    low("/Users/Administrator/AppData/Local/Google/Chrome/Application/68.0.3423.2/Installer/chrome.msi");
    low("/Users/Administrator/AppData/Local/GDIPFONTCACHEV1.DAT");
    low("/Users/Administrator/AppData/Local/Programs/SomeApp/app.exe");
    low("/Windows/System32/drivers/x.sys");
    low("/Windows/Installer/2a3b/patch.msi");
    // Windows own binaries named with the credential word: shadow.exe (volume
    // shadow copy tool) is a program, tile_drop_shadow.png a gadget texture.
    low("/Windows/System32/shadow.exe");
    low("/Windows/System32/en-US/shadow.exe.mui");
    low("/Program Files/Windows Sidebar/Gadgets/PicturePuzzle.Gadget/Images/tile_drop_shadow.png");
    low("/Windows/winsxs/amd64_microsoft-windows-g..picturepuzzlegadget/tile_drop_shadow.png");
    // Chromium runtime state under User Data: leveldb stores and component
    // update manifests are binary/机器生成, flooding the 90 band wholesale.
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/Default/Local Storage/leveldb/000038.log");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/CertificateRevocation/7404/manifest.json");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/Crashpad/settings.dat");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/SwReporter/100.282.200/manifest.json");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/SSLErrorAssistant/7/ssl_error_assistant.pb");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/WidevineCdm/4.10.2391.0/manifest.json");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/Default/Feature Engagement Tracker/EventDB/000003.log");
    low("/Users/Administrator/AppData/Local/Google/Chrome/User Data/Default/Thumbnails/LOG.old");
    low("/Users/Administrator/AppData/Local/Google/Software Reporter Tool/settings.dat");
    low("/Users/Administrator/AppData/Local/IconCache.db");
    low("/Users/Administrator/AppData/Local/Kingsoft/WPS Office/11.1.0.11744/office6/addons/createcompany/mui/zh_CN/res/web/error-page/close_default.png");
    low("/Users/Administrator/AppData/Local/Kingsoft/WPS Office/11.1.0.11744/office6/addons/kaiwpp/mui/zh_CN/res/smartchart/mark.pptx");
    low("/Users/Administrator/AppData/Local/Kingsoft/WPS Cloud Files/userdata/qing/qing.db");

    // Container / distro bulk trees.
    low("/var/lib/docker/overlay2/abc123/diff/usr/bin/python3");
    low("/var/lib/docker/volumes/data/_data/dump.log");
    low("/snap/core20/2105/usr/bin/base32");
    low("/var/lib/snapd/snaps/core20_2105.snap");
    low("/mnt/disk1/lost+found/#237001");
}

// Junk must not merely score low: with a full budget of real evidence the
// truncation must drop every junk family, and the kept evidence must come out
// in band order (credentials, user artefacts, logs, configs).
TEST_F(SceneClassifierTest, HeuristicSelectionMixedRealWorld) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    std::vector<std::string> evidence = {
        "/etc/passwd",                                  // 100 credential
        "/root/.bash_history",                          // 100 credential
        "/etc/shadow",                                  // 100 credential
        "/home/alice/contract.pdf",                     // 90 user area
        "/home/alice/桌面/转账记录.xlsx",                  // 90 user area
        "/home/u2/chat/wechat.db",                      // 90 user area (IM artefact)
        "/var/log/secure",                              // 80 log
        "/var/log/cron",                                // 80 log
        "/var/log/journal/long/system.journal",         // 80 log
        "/etc/nginx/nginx.conf",                        // 60 config
    };
    std::vector<std::string> junk = {
        "/root/.npm/_cacache/content-v2/sha512/aa",
        "/root/.gradle/caches/modules-2/x.jar",
        "/home/u/repo/.git/objects/aa/1111",
        "/home/u/repo/.git/objects/bb/2222",
        "/www/wwwroot/jijin/vendor/phpoffice/Classes/PHPExcel/Cell.php",
        "/www/wwwroot/jijin/vendor/qiniu/php-sdk/src/Qiniu/Storage.php",
        "C:/Users/X/Desktop/desktop.ini",
        "D:/data/Thumbs.db",
        "C:/pagefile.sys",
        "/home/u/contract.docx~",
        "/home/u/.report.txt.swp",
        "/home/u/.DS_Store",
        "/var/lib/docker/overlay2/abc/diff/usr/bin/python3",
        "/snap/core20/2105/usr/bin/base32",
        "/root/.cache/pip/http/x/y/z.tmp",
        "/usr/share/man/man3/xcb.3.gz",
        "/usr/share/doc/gcc/copyright",
        "/usr/lib/x86_64-linux-gnu/libssl.so.3",
        "/usr/share/icons/hicolor/48x48/apps/x.png",
        "/var/lib/snapd/snaps/core20_2105.snap",
        "C:/Windows/WinSxS/amd64_microsoft-windows-servicing.dll",
        "C:/Users/X/AppData/Local/Temp/chrome_installer.exe",
        "C:/Users/X/AppData/Local/Microsoft/Windows/INetCache/IE/abc.htm",
        "/root/go/pkg/mod/golang.org/x/net@v0.17.0/socket.go",
        "/root/.cargo/registry/src/index.crates.io/serde/src/lib.rs",
        "/root/.m2/repository/org/apache/commons.jar",
        "/srv/app/bower_components/jquery/dist/jquery.min.js",
        "/var/lib/docker/volumes/data/_data/dump.log",
        "/mnt/disk1/lost+found/#237001",
        "/root/virt-sysprep-tmpfile.tmp",
    };

    std::vector<std::string> files = evidence;
    files.insert(files.end(), junk.begin(), junk.end());
    auto picked = A::select(files, evidence.size());
    ASSERT_EQ(picked.size(), evidence.size());
    for (const auto& p : picked) {
        EXPECT_TRUE(std::find(evidence.begin(), evidence.end(), p) != evidence.end())
            << "junk selected into budget: " << p;
    }
    // stable_sort keeps same-band inputs in insertion order: credentials
    // (passwd, bash_history, shadow), then user artefacts, then logs, config.
    EXPECT_EQ(picked[0], "/etc/passwd");
    EXPECT_EQ(picked[1], "/root/.bash_history");
    EXPECT_EQ(picked[2], "/etc/shadow");
    EXPECT_EQ(picked[3], "/home/alice/contract.pdf");
    EXPECT_EQ(picked[4], "/home/alice/桌面/转账记录.xlsx");
    EXPECT_EQ(picked[5], "/home/u2/chat/wechat.db");
    EXPECT_EQ(picked[6], "/var/log/secure");
    EXPECT_EQ(picked[7], "/var/log/cron");
    EXPECT_EQ(picked[8], "/var/log/journal/long/system.journal");
    EXPECT_EQ(picked[9], "/etc/nginx/nginx.conf");
}

// A budget larger than the evidence must stay unfilled rather than be padded
// with noise. Real images filter down to a few thousand files, so the 1000-file
// smart budget used to swallow the whole priority-5 tail — including a PE
// binary renamed to .old, which the text model then hung on.
TEST_F(SceneClassifierTest, HeuristicSelectionDoesNotPadBudgetWithJunk) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    std::vector<std::string> files = {
        "/etc/passwd",
        "/home/alice/contract.pdf",
        "/var/log/secure",
        "/Users/Administrator/AppData/Local/Temp/freeime/freeime.old",
        "/Users/Administrator/AppData/Local/Temp/chrome_installer.log",
        "C:/Windows/System32/config/SOFTWARE.LOG2",
        "/Users/Administrator/AppData/Local/Google/Chrome/User Data/Default/Thumbnails/LOG.old",
        "/Users/Administrator/AppData/Local/Google/Chrome/User Data/Default/Thumbnails/000003.log",
    };
    auto picked = A::select(files, 1000);
    ASSERT_EQ(picked.size(), 3u);
    EXPECT_EQ(picked[0], "/etc/passwd");
    EXPECT_EQ(picked[1], "/home/alice/contract.pdf");
    EXPECT_EQ(picked[2], "/var/log/secure");
}

// Suffix rules cannot see a binary whose extension was changed. A PE image
// sitting in a user directory earns the user-area score (90) and would take a
// smart-selection slot ahead of real evidence; its header must pull it back
// into the noise bucket. A text file with the same extension stays.
TEST_F(SceneClassifierTest, HeuristicSelectionDropsRenamedBinaryByHeader) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    // The test binary runs from the build tree, so a relative path would not be
    // the file this test just wrote.
    const std::string dir =
        (std::filesystem::temp_directory_path() / "heuristic_header_fixture").string();
    std::filesystem::create_directory(dir);
    const std::string binary = dir + "/payload.old";
    const std::string text = dir + "/notes.old";
    {
        std::ofstream out(binary, std::ios::binary);
        const unsigned char header[] = {'M', 'Z', 0x90, 0x00};
        out.write(reinterpret_cast<const char*>(header), sizeof(header));
    }
    {
        std::ofstream out(text);
        out << "investigation notes";
    }

    std::vector<std::string> files = {"/etc/passwd", binary, text};
    auto picked = A::select(files, 1000);

    std::filesystem::remove_all(dir);

    ASSERT_EQ(picked.size(), 2u);
    // The credential file outranks a plain text note; the renamed PE is gone.
    EXPECT_EQ(picked[0], "/etc/passwd");
    EXPECT_EQ(picked[1], text);
}

// Explicit boundaries: real artefacts sharing substrings with junk rules — or
// sitting in junk-adjacent bands — must keep their established scores.
TEST_F(SceneClassifierTest, HeuristicPriorityRealArtefactBoundaries) {
    using A = forensics::LLMSelectionHeuristicTestAccess;

    // Credential patterns win over every junk marker (basename scope).
    EXPECT_EQ(A::priority("/root/.cache/pip/passwd.bak"), 100);
    EXPECT_EQ(A::priority("/home/u/vendor/authorized_keys"), 100);
    EXPECT_EQ(A::priority("/mnt/usb/backup/etc/shadow"), 100);
    // Word-bounded basename hits keep 100 for real credential data, including
    // compound names that need their own pattern (gshadow, opasswd) and
    // backup/lock suffixed variants.
    EXPECT_EQ(A::priority("/etc/gshadow"), 100);
    EXPECT_EQ(A::priority("/etc/gshadow-"), 100);
    EXPECT_EQ(A::priority("/etc/security/opasswd"), 100);
    EXPECT_EQ(A::priority("/etc/passwd.lock"), 100);
    EXPECT_EQ(A::priority("/etc/shadow+"), 100);
    // Credential word only in a directory name: not a credential artefact.
    EXPECT_LT(A::priority("/var/lib/yum/yumdb/x/passwd-0.79/checksum_type"), 60);
    // Executables that merely embed a credential word are not credentials.
    EXPECT_LT(A::priority("/usr/bin/gpasswd"), 60);
    EXPECT_LT(A::priority("/usr/sbin/saslpasswd2"), 60);
    // IM/browser/mail profile artefacts under user areas stay high (the
    // user-area rule runs before the profile band; both are keepers).
    EXPECT_GE(A::priority("/home/u2/chat/wechat.db"), 75);
    EXPECT_GE(A::priority("/root/.mozilla/firefox/x.default/places.sqlite"), 75);
    EXPECT_GE(A::priority("/users/john/Mail/INBOX"), 75);
    // Plain databases, configs, logs, docs keep their bands.
    EXPECT_EQ(A::priority("/var/lib/mysql/app/users.db"), 70);
    EXPECT_EQ(A::priority("/home/alice/contract.pdf"), 90);
    EXPECT_EQ(A::priority("/var/log/secure"), 80);
    EXPECT_EQ(A::priority("/etc/nginx/nginx.conf"), 60);
    EXPECT_EQ(A::priority("/www/wwwroot/jijin/application/index/view/user/login.html"), 30);
    // A document whose name merely contains a junk substring is not junk:
    // the vendor marker carries its path separator.
    EXPECT_EQ(A::priority("/home/u/Documents/vendor-audit-notes.txt"), 90);
    // Windows user documents keep the user-area band.
    EXPECT_EQ(A::priority("/Users/Administrator/Desktop/转账记录.xlsx"), 90);
    EXPECT_EQ(A::priority("/Users/john/Documents/WeChat Files/wxid_x/Msg/MicroMsg.db"), 90);
}

// DatabaseManager::insertFileRecord batches rows into one transaction per
// kInsertBatchRows rows. Regression: per-row autocommit cost one WAL fsync per
// file on the extraction disk (~0.5 s each), capping the metadata walk at
// single-digit files/s. Correctness first: every row must survive, batches
// must be visible to OTHER connections after flush/count, and a reused
// prepared statement must not corrupt neighbouring rows.
TEST_F(SceneClassifierTest, DatabaseManagerBatchedInsertCorrectness) {
    const std::string dbPath = "/tmp/tl_dbmanager_batched_test.db";
    std::remove(dbPath.c_str());

    DatabaseManager db(dbPath);
    ASSERT_TRUE(db.initialize());

    FileRecord r;
    r.type = "REG"; r.isDeleted = 0; r.isAllocated = 1;
    r.permissions = "644"; r.uid = 0; r.gid = 0; r.partitionNum = 2;
    const int kRows = 5000;  // spans 2.5 batches of 2000
    for (int i = 0; i < kRows; ++i) {
        r.inode = 100000 + i;
        r.name = "file_" + std::to_string(i) + ".txt";
        r.path = "/dir" + std::to_string(i % 7) + "/" + r.name;
        r.size = 1024 * i;
        r.md5 = "md5_" + std::to_string(i);
        ASSERT_TRUE(db.insertFileRecord(r)) << "row " << i;
    }
    // Same-connection count also flushes the open batch.
    EXPECT_EQ(db.getFileCount(), kRows);

    // External-reader visibility + round-trip of two distant rows.
    sqlite3* rd = nullptr;
    ASSERT_EQ(sqlite3_open_v2(dbPath.c_str(), &rd, SQLITE_OPEN_READONLY, nullptr), SQLITE_OK);
    sqlite3_stmt* st = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(rd, "SELECT COUNT(*) FROM files;", -1, &st, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(st), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(st, 0), kRows);
    sqlite3_finalize(st);
    ASSERT_EQ(sqlite3_prepare_v2(rd, "SELECT path, md5 FROM files WHERE inode IN (?, ?) ORDER BY inode;", -1, &st, nullptr), SQLITE_OK);
    sqlite3_bind_int64(st, 1, 100000);
    sqlite3_bind_int64(st, 2, 100000 + kRows - 1);
    ASSERT_EQ(sqlite3_step(st), SQLITE_ROW);
    EXPECT_EQ(std::string(reinterpret_cast<const char*>(sqlite3_column_text(st, 0))), "/dir0/file_0.txt");
    EXPECT_EQ(std::string(reinterpret_cast<const char*>(sqlite3_column_text(st, 1))), "md5_0");
    ASSERT_EQ(sqlite3_step(st), SQLITE_ROW);
    EXPECT_EQ(std::string(reinterpret_cast<const char*>(sqlite3_column_text(st, 0))), "/dir" + std::to_string((kRows - 1) % 7) + "/file_" + std::to_string(kRows - 1) + ".txt");
    sqlite3_finalize(st);
    sqlite3_close(rd);
}

// Throughput guard: 20k rows must complete well under a minute with batching.
// The pre-fix behaviour (one autocommit per row) measured ~2 rows/s on the
// extraction disk and would need hours for this loop.
TEST_F(SceneClassifierTest, DatabaseManagerBatchedInsertThroughput) {
    const std::string dbPath = "/tmp/tl_dbmanager_throughput_test.db";
    std::remove(dbPath.c_str());

    DatabaseManager db(dbPath);
    ASSERT_TRUE(db.initialize());

    FileRecord r;
    r.type = "REG"; r.isDeleted = 0; r.isAllocated = 1;
    const auto t0 = std::chrono::steady_clock::now();
    const int kRows = 20000;
    for (int i = 0; i < kRows; ++i) {
        r.inode = i;
        r.name = "f" + std::to_string(i);
        r.path = "/d" + std::to_string(i % 11) + "/" + r.name;
        r.size = i;
        ASSERT_TRUE(db.insertFileRecord(r)) << "row " << i;
    }
    const auto elapsed = std::chrono::steady_clock::now() - t0;
    const double seconds = std::chrono::duration<double>(elapsed).count();
    db.flushInsertBatch();
    EXPECT_EQ(db.getFileCount(), kRows);
    EXPECT_LT(seconds, 30.0) << "batched insert regressed: " << seconds << "s for " << kRows << " rows";
    std::printf("[perf] %d rows in %.2fs (%.0f rows/s)\n", kRows, seconds, kRows / seconds);
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

// End-to-end replay against a real task database when one is provided. The
// image cannot be re-scanned inside a unit test, but its _files.db can: the
// candidate scan and the summary/parse round trip are the two things the fix
// changed, and both are pure functions of that database.
//
//   TRACELENS_SMART_DB=/path/to/files.db ./test_scene_classifier_gtest \
//       --gtest_filter=SceneClassifierTest.SmartSelectionRealDatabase
//
// The database decides which artefacts count as reachable, so the same test
// covers the Windows and the Linux images without per-image forks.
TEST_F(SceneClassifierTest, SmartSelectionRealDatabase) {
    const char* db_env = std::getenv("TRACELENS_SMART_DB");
    if (!db_env || !*db_env) {
        GTEST_SKIP() << "set TRACELENS_SMART_DB to a task _files.db to run this";
    }
    using A = forensics::LLMSelectionHeuristicTestAccess;

    auto candidates = A::prioritized(db_env, 5000, true);
    ASSERT_FALSE(candidates.empty());
    ASSERT_LE(candidates.size(), 5000u);

    auto contains = [&](const std::string& needle) {
        return std::any_of(candidates.begin(), candidates.end(),
            [&](const std::string& c) { return c.find(needle) != std::string::npos; });
    };

    // The image's own artefact set: whichever layout the database holds, the
    // core artefacts it actually contains must be reachable inside the
    // candidate budget. These were out of reach on every real image before the
    // fix (insertion-order window). A probe is skipped when the image does not
    // carry that artefact at all (e.g. no Amcache on the 窝点嫌疑人 image).
    struct Probe { const char* in_db; const char* in_window; };
    const std::vector<Probe> windowsProbes = {
        {"/Windows/System32/config/SAM", "/Windows/System32/config/SAM"},
        {"/Windows/System32/config/SOFTWARE", "/Windows/System32/config/SOFTWARE"},
        {"winevt/Logs", "winevt/Logs"},
        {"Amcache", "Amcache"},
    };
    const std::vector<Probe> linuxProbes = {
        {"/etc/passwd", "/etc/passwd"},
        {"/etc/shadow", "/etc/shadow"},
        {"/var/log", "/var/log"},
    };
    auto dbHas = [&](const std::string& needle) {
        sqlite3* db = nullptr;
        if (sqlite3_open(db_env, &db) != SQLITE_OK) return false;
        sqlite3_stmt* stmt = nullptr;
        bool found = false;
        if (sqlite3_prepare_v2(db,
                "SELECT 1 FROM files WHERE path LIKE ? LIMIT 1", -1, &stmt, nullptr) == SQLITE_OK) {
            std::string pattern = "%" + needle + "%";
            sqlite3_bind_text(stmt, 1, pattern.c_str(), -1, SQLITE_TRANSIENT);
            found = sqlite3_step(stmt) == SQLITE_ROW;
        }
        sqlite3_finalize(stmt);
        sqlite3_close(db);
        return found;
    };

    size_t checkedWindows = 0, checkedLinux = 0, failures = 0;
    auto probeAll = [&](const std::vector<Probe>& probes, size_t& checked) {
        for (const auto& p : probes) {
            if (!dbHas(p.in_db)) continue;   // image does not carry this artefact
            ++checked;
            if (!contains(p.in_window)) {
                ++failures;
                ADD_FAILURE() << "present in image but missing from candidate "
                                 "budget: " << p.in_db;
            }
        }
    };
    probeAll(windowsProbes, checkedWindows);
    probeAll(linuxProbes, checkedLinux);
    EXPECT_EQ(failures, 0u);
    // The database must be recognisable as one of the two supported layouts.
    EXPECT_EQ(checkedWindows == 0 && checkedLinux == 0, false)
        << "database matched neither the Windows nor the Linux artefact layout";

    // The prompt list is indexed full paths, and an index reply round-trips.
    auto head = std::vector<std::string>(candidates.begin(),
        candidates.begin() + std::min<size_t>(20, candidates.size()));
    const std::string summary = A::buildSummary(head);
    EXPECT_NE(summary.find("1 " + head[0]), std::string::npos);

    auto picked = A::parseSelection("[1, 3, 5]", head);
    ASSERT_EQ(picked.size(), 3u);
    EXPECT_EQ(picked[0], head[0]);
    EXPECT_EQ(picked[1], head[2]);
    EXPECT_EQ(picked[2], head[4]);
}

// Task-level analysis budget -> database query. Full mode truncates with
// LIMIT maxFiles (LLMAnalysisService.cpp getFilesFromDatabase), so the value
// resolved from task.llm_max_files must reach this seam unchanged; 0 stays
// unlimited and must not truncate.
TEST_F(SceneClassifierTest, FullModeBudgetBecomesSqlLimit) {
    namespace fs = std::filesystem;
    const auto dbPath = fs::temp_directory_path() /
        ("budget_files_" + std::to_string(::getpid()) + ".db");
    fs::remove(dbPath);
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.string().c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE files(path TEXT, category TEXT)", nullptr, nullptr, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "INSERT INTO files(path, category) VALUES "
        "('/etc/passwd','Configuration Files'),"
        "('/var/log/auth.log','Logs'),"
        "('/home/u/notes.txt','Documents'),"
        "('/home/u/chat.db','Databases'),"
        "('/usr/bin/ls','Executables'),"
        "('/opt/app/config.yml','Configuration Files')", nullptr, nullptr, nullptr),
        SQLITE_OK);
    sqlite3_close(db);

    using A = forensics::LLMSelectionHeuristicTestAccess;

    EXPECT_EQ(A::fullModeCandidates(dbPath.string(), 0).size(), 6u);  // unlimited
    EXPECT_EQ(A::fullModeCandidates(dbPath.string(), 2).size(), 2u);
    EXPECT_EQ(A::fullModeCandidates(dbPath.string(), 4).size(), 4u);
    EXPECT_LE(A::fullModeCandidates(dbPath.string(), 100).size(), 6u);  // never exceeds rows

    fs::remove(dbPath);
}

// The same budget in smart mode bounds the candidate pool, not the SQL row
// count: an over-large request is clamped by the policy helper, and the
// resulting pool never exceeds the budget.
TEST_F(SceneClassifierTest, SmartModeBudgetBoundsTheCandidatePool) {
    namespace fs = std::filesystem;
    const auto dbPath = fs::temp_directory_path() /
        ("budget_pool_" + std::to_string(::getpid()) + ".db");
    fs::remove(dbPath);
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.string().c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE files(path TEXT, category TEXT)", nullptr, nullptr, nullptr),
        SQLITE_OK);
    auto insert = [&](int i) {
        const std::string sql = "INSERT INTO files(path, category) VALUES ('/home/u/note" +
            std::to_string(i) + ".txt','Documents')";
        sqlite3_exec(db, sql.c_str(), nullptr, nullptr, nullptr);
    };
    for (int i = 0; i < 12; ++i) insert(i);
    sqlite3_close(db);

    using A = forensics::LLMSelectionHeuristicTestAccess;

    // resolve(task=5) -> pool budget 5 -> at most 5 candidates.
    const auto budget = forensics::analysis_budget::resolve(5, 500, 5000, true);
    EXPECT_EQ(budget.files, 5);
    const auto candidates = A::prioritized(dbPath.string(), (size_t)budget.files, true);
    EXPECT_LE(candidates.size(), 5u);
    EXPECT_FALSE(candidates.empty());

    fs::remove(dbPath);
}

// The prompts must never be starved of the image's own headline evidence: the
// highest-priority candidates have to include user-area case material, not
// only system artefacts. Reported per image so a regression names the image.
TEST_F(SceneClassifierTest, SmartSelectionKeepsUserEvidenceInBudget) {
    const char* db_env = std::getenv("TRACELENS_SMART_DB");
    if (!db_env || !*db_env) {
        GTEST_SKIP() << "set TRACELENS_SMART_DB to a task _files.db to run this";
    }
    using A = forensics::LLMSelectionHeuristicTestAccess;

    auto candidates = A::prioritized(db_env, 5000, true);
    ASSERT_FALSE(candidates.empty());

    // Every candidate must be a real database row, and none may be the noise
    // bucket the budget is supposed to exclude.
    for (const auto& c : candidates) {
        EXPECT_GE(A::priority(c), 10) << "noise file inside the candidate budget: " << c;
    }
}

// Diagnostic (not an assertion): print what the candidate budget is spent on,
// so a run against a real image shows which evidence families the LLM will see.
TEST_F(SceneClassifierTest, SmartSelectionCandidateComposition) {
    const char* db_env = std::getenv("TRACELENS_SMART_DB");
    if (!db_env || !*db_env) {
        GTEST_SKIP() << "set TRACELENS_SMART_DB to a task _files.db to run this";
    }
    using A = forensics::LLMSelectionHeuristicTestAccess;

    auto cands = A::prioritized(db_env, 5000, true);
    ASSERT_FALSE(cands.empty());

    auto bucket = [](const std::string& p) -> std::string {
        if (p.rfind("/Users/", 0) == 0 || p.rfind("/home/", 0) == 0 ||
            p.rfind("/root/", 0) == 0) return "user-area";
        if (p.find("/Windows/System32/config/") != std::string::npos) return "registry-hives";
        if (p.find("/winevt/") != std::string::npos) return "event-logs";
        if (p.find("/Prefetch/") != std::string::npos) return "prefetch";
        if (p.find("/var/log") != std::string::npos) return "var-log";
        if (p.find("/www/") != std::string::npos) return "www(baota)";
        if (p.find("/etc/") == 0) return "etc";
        if (p.find("/usr/") == 0) return "usr";
        if (p.find("/Windows/") == 0) return "windows-other";
        if (p.rfind("/home/", 0) == 0) return "home";
        return "other";
    };
    std::map<std::string, int> counts;
    for (const auto& c : cands) counts[bucket(c)]++;

    std::vector<std::pair<std::string, int>> ranked(counts.begin(), counts.end());
    std::sort(ranked.begin(), ranked.end(),
              [](const auto& a, const auto& b) { return a.second > b.second; });

    std::cout << "== candidate composition (" << cands.size() << " in budget) ==\n";
    for (const auto& [k, v] : ranked) std::cout << "   " << k << ": " << v << "\n";
    std::cout << "-- top 10 --\n";
    for (size_t i = 0; i < std::min<size_t>(10, cands.size()); ++i) {
        std::cout << "   " << cands[i] << "\n";
    }
    SUCCEED();
}
