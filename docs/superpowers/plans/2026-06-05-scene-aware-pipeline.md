# 场景感知管道集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将场景特化分析功能集成到主管道中，实现场景感知分类和优化的 LLM 分析

**Architecture:** 扩展 `_files.db` 数据库架构支持场景特化数据，修改 FileClassifier 实现场景感知分类，改造场景分析器写入 `_files.db`，优化 LLM 分析使用场景优先级

**Tech Stack:** C++20, SQLite3, The Sleuth Kit 4.14.0, Crow HTTP Framework

---

## 文件结构

### 核心修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `src/core/DatabaseManager/SQL/file_classifier_sql.h` | 添加场景相关 SQL 定义 |
| `src/core/DatabaseManager/FileClassifier/FileClassifier.h` | 添加 SceneType 枚举和场景感知方法 |
| `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp` | 实现场景标记和分类逻辑 |
| `src/AnalysisOrchestrator.cpp` | 修改主管道支持场景感知 |
| `src/network/HTTPServer/TaskManager.cpp` | 修改 HTTP 管道支持场景感知 |
| `src/network/HTTPServer/LLMAnalysisService.h` | 添加场景优先级支持 |
| `src/network/HTTPServer/LLMAnalysisService.cpp` | 实现场景优先级排序 |
| `src/network/HTTPServer/HTTPServerDataTypes.h` | 添加 SceneConfig 结构 |
| `src/core/DatabaseManager/EventExtractor/EventExtractor.h` | 添加 importSceneArtifacts 方法 |
| `src/core/DatabaseManager/EventExtractor/Detail/EventExtractorCore.cpp` | 实现场景工件导入 |

### 场景分析器修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h` | 添加集成模式支持 |
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp` | 实现集成模式写入 |
| `src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h` | 添加集成模式支持 |
| `src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp` | 实现集成模式写入 |
| `src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.h` | 添加集成模式支持 |
| `src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.cpp` | 实现集成模式写入 |

### 测试文件

| 文件路径 | 测试内容 |
|----------|----------|
| `tests/UnitTest/test_scene_classifier_gtest.cpp` | 场景分类器单元测试 |
| `tests/UnitTest/test_scene_database_gtest.cpp` | 场景数据库集成测试 |
| `tests/test_scene_integration.sh` | 场景集成测试脚本 |

---

## Task 1: 添加场景 SQL 定义

**Files:**
- Modify: `src/core/DatabaseManager/SQL/file_classifier_sql.h`
- Test: `tests/UnitTest/test_scene_database_gtest.cpp`

- [ ] **Step 1: 创建测试文件**

```cpp
// tests/UnitTest/test_scene_database_gtest.cpp
#include <gtest/gtest.h>
#include <sqlite3.h>
#include "DatabaseManager/SQL/file_classifier_sql.h"

class SceneDatabaseTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbPath_ = ":memory:";
        ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db_), SQLITE_OK);
    }

    void TearDown() override {
        if (db_) sqlite3_close(db_);
    }

    sqlite3* db_ = nullptr;
    const char* dbPath_;
};

TEST_F(SceneDatabaseTest, CreateMainFilesTableWithSceneColumns) {
    // 执行创建表语句
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_MAIN_FILES_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);

    // 验证表存在
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT scene_type, scene_priority, scene_relevant FROM files LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateAndroidArtifactsTable) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_ANDROID_ARTIFACTS_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT id, file_id, artifact_type, artifact_data FROM android_artifacts LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateWindowsArtifactsTable) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_WINDOWS_ARTIFACTS_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT id, file_id, artifact_type, artifact_data FROM windows_artifacts LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}

TEST_F(SceneDatabaseTest, CreateLinuxArtifactsTable) {
    ASSERT_EQ(sqlite3_exec(db_, FileClassifierSQL::CREATE_LINUX_ARTIFACTS_TABLE, nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, "SELECT id, file_id, artifact_type, artifact_data FROM linux_artifacts LIMIT 0", -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_finalize(stmt);
}
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake .. -DCMAKE_BUILD_TYPE=Debug
cmake --build . --target test_scene_database
./test_scene_database
```

预期：编译失败，`CREATE_ANDROID_ARTIFACTS_TABLE` 未定义

- [ ] **Step 3: 添加场景 SQL 定义**

在 `src/core/DatabaseManager/SQL/file_classifier_sql.h` 的 `FileClassifierSQL` 命名空间中添加：

```cpp
// ============================================================================
// Scene Specialization Tables
// ============================================================================

// Android artifacts table
inline constexpr const char* CREATE_ANDROID_ARTIFACTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS android_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER REFERENCES files(id),
        artifact_type TEXT NOT NULL,
        artifact_data TEXT,
        extracted_at INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
)";

// Windows artifacts table
inline constexpr const char* CREATE_WINDOWS_ARTIFACTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS windows_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER REFERENCES files(id),
        artifact_type TEXT NOT NULL,
        artifact_data TEXT,
        extracted_at INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
)";

// Linux artifacts table
inline constexpr const char* CREATE_LINUX_ARTIFACTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER REFERENCES files(id),
        artifact_type TEXT NOT NULL,
        artifact_data TEXT,
        extracted_at INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
)";

// Scene artifacts indices
inline constexpr const char* CREATE_SCENE_ARTIFACTS_INDICES = R"(
    CREATE INDEX IF NOT EXISTS idx_android_artifacts_file_id ON android_artifacts(file_id);
    CREATE INDEX IF NOT EXISTS idx_android_artifacts_type ON android_artifacts(artifact_type);
    CREATE INDEX IF NOT EXISTS idx_windows_artifacts_file_id ON windows_artifacts(file_id);
    CREATE INDEX IF NOT EXISTS idx_windows_artifacts_type ON windows_artifacts(artifact_type);
    CREATE INDEX IF NOT EXISTS idx_linux_artifacts_file_id ON linux_artifacts(file_id);
    CREATE INDEX IF NOT EXISTS idx_linux_artifacts_type ON linux_artifacts(artifact_type);
)";

// Scene file summary view
inline constexpr const char* CREATE_SCENE_FILE_SUMMARY_VIEW = R"(
    CREATE VIEW IF NOT EXISTS scene_file_summary AS
    SELECT
        scene_type,
        COUNT(*) as total_files,
        SUM(CASE WHEN scene_relevant = 1 THEN 1 ELSE 0 END) as relevant_files,
        SUM(size) as total_size,
        SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as llm_analyzed_files
    FROM files
    WHERE scene_type IS NOT NULL
    GROUP BY scene_type;
)";

// Scene artifact summary view
inline constexpr const char* CREATE_SCENE_ARTIFACT_SUMMARY_VIEW = R"(
    CREATE VIEW IF NOT EXISTS scene_artifact_summary AS
    SELECT
        'android' as scene_type,
        artifact_type,
        COUNT(*) as artifact_count,
        SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_count
    FROM android_artifacts
    GROUP BY artifact_type
    UNION ALL
    SELECT
        'windows' as scene_type,
        artifact_type,
        COUNT(*) as artifact_count,
        SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_count
    FROM windows_artifacts
    GROUP BY artifact_type
    UNION ALL
    SELECT
        'linux' as scene_type,
        artifact_type,
        COUNT(*) as artifact_count,
        SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_count
    FROM linux_artifacts
    GROUP BY artifact_type;
)";

// Migration: Add scene columns to existing files table
inline constexpr const char* ALTER_FILES_ADD_SCENE_COLUMNS[] = {
    "ALTER TABLE files ADD COLUMN scene_type TEXT;",
    "ALTER TABLE files ADD COLUMN scene_priority INTEGER DEFAULT 0;",
    "ALTER TABLE files ADD COLUMN scene_relevant INTEGER DEFAULT 0;"
};
inline const int ALTER_FILES_ADD_SCENE_COLUMNS_COUNT = 3;

// Insert into artifacts tables
inline constexpr const char* INSERT_ANDROID_ARTIFACT =
    "INSERT INTO android_artifacts (file_id, artifact_type, artifact_data, extracted_at) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_WINDOWS_ARTIFACT =
    "INSERT INTO windows_artifacts (file_id, artifact_type, artifact_data, extracted_at) VALUES (?, ?, ?, ?);";

inline constexpr const char* INSERT_LINUX_ARTIFACT =
    "INSERT INTO linux_artifacts (file_id, artifact_type, artifact_data, extracted_at) VALUES (?, ?, ?, ?);";

// Update artifact LLM analysis
inline constexpr const char* UPDATE_ANDROID_ARTIFACT_LLM = R"(
    UPDATE android_artifacts SET
        llm_summary = ?,
        llm_description = ?,
        llm_keywords = ?,
        llm_analyzed_at = ?,
        llm_model_used = ?
    WHERE id = ?;
)";

inline constexpr const char* UPDATE_WINDOWS_ARTIFACT_LLM = R"(
    UPDATE windows_artifacts SET
        llm_summary = ?,
        llm_description = ?,
        llm_keywords = ?,
        llm_analyzed_at = ?,
        llm_model_used = ?
    WHERE id = ?;
)";

inline constexpr const char* UPDATE_LINUX_ARTIFACT_LLM = R"(
    UPDATE linux_artifacts SET
        llm_summary = ?,
        llm_description = ?,
        llm_keywords = ?,
        llm_analyzed_at = ?,
        llm_model_used = ?
    WHERE id = ?;
)";

// Select scene files for LLM analysis
inline constexpr const char* SELECT_SCENE_FILES_FOR_LLM = R"(
    SELECT id, inode, name, path, size, extension, category, type,
           mtime, ctime, is_deleted, md5,
           scene_type, scene_priority, scene_relevant
    FROM files
    WHERE type = 'REG'
      AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)
      AND scene_priority > 0
    ORDER BY scene_priority DESC, size ASC
    LIMIT ?;
)";

// Scene statistics queries
inline constexpr const char* SELECT_SCENE_FILE_STATS = R"(
    SELECT
        scene_type,
        COUNT(*) as total_files,
        SUM(CASE WHEN scene_relevant = 1 THEN 1 ELSE 0 END) as relevant_files,
        SUM(size) as total_size,
        SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as llm_analyzed_files
    FROM files
    WHERE scene_type IS NOT NULL
    GROUP BY scene_type;
)";
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . --target test_scene_database
./test_scene_database
```

预期：所有测试通过

- [ ] **Step 5: 提交**

```bash
git add src/core/DatabaseManager/SQL/file_classifier_sql.h tests/UnitTest/test_scene_database_gtest.cpp
git commit -m "feat(database): add scene specialization SQL definitions"
```

---

## Task 2: 修改 FileClassifier 支持场景感知

**Files:**
- Modify: `src/core/DatabaseManager/FileClassifier/FileClassifier.h:11-100`
- Modify: `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp:31-50,166-270`
- Test: `tests/UnitTest/test_scene_classifier_gtest.cpp`

- [ ] **Step 1: 创建测试文件**

```cpp
// tests/UnitTest/test_scene_classifier_gtest.cpp
#include <gtest/gtest.h>
#include "DatabaseManager/FileClassifier/FileClassifier.h"

class SceneClassifierTest : public ::testing::Test {
protected:
    void SetUp() override {
        // 创建内存数据库用于测试
        dbPath_ = ":memory:";
    }

    std::string dbPath_;
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

    // 测试 Android 关键路径
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
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . --target test_scene_classifier
./test_scene_classifier
```

预期：编译失败，`SceneType` 和 `ScenePriority` 未定义

- [ ] **Step 3: 修改 FileClassifier.h 添加场景支持**

在 `src/core/DatabaseManager/FileClassifier/FileClassifier.h` 中添加：

```cpp
// 在 FileCategory 枚举之后添加
enum class SceneType {
    NONE,
    ANDROID,
    WINDOWS,
    LINUX,
    SERVER_CLOUD
};

struct ScenePriority {
    static constexpr int CRITICAL = 100;
    static constexpr int HIGH = 75;
    static constexpr int MEDIUM = 50;
    static constexpr int LOW = 25;
    static constexpr int IRRELEVANT = 0;
};

// 在 FileClassifier 类的 public 区域添加
class FileClassifier {
public:
    // ... 现有接口 ...

    // 场景感知接口
    void setSceneType(SceneType scene);
    SceneType getSceneType() const;
    int calculateScenePriority(const std::string& path, const std::string& filename, FileCategory category);
    bool isSceneRelevant(const std::string& path, const std::string& filename);

private:
    // ... 现有成员 ...

    // 场景相关成员
    SceneType sceneType_ = SceneType::NONE;

    // 场景相关方法
    void markSceneFiles();
    void applyAndroidSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    void applyWindowsSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    void applyLinuxSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    void applyServerCloudSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    std::string getSceneTypeName(SceneType scene) const;
};
```

- [ ] **Step 4: 实现场景感知方法**

在 `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp` 中添加：

```cpp
// 在文件末尾添加
void FileClassifier::setSceneType(SceneType scene) {
    sceneType_ = scene;
}

SceneType FileClassifier::getSceneType() const {
    return sceneType_;
}

std::string FileClassifier::getSceneTypeName(SceneType scene) const {
    switch (scene) {
        case SceneType::ANDROID: return "android";
        case SceneType::WINDOWS: return "windows";
        case SceneType::LINUX: return "linux";
        case SceneType::SERVER_CLOUD: return "server_cloud";
        default: return "";
    }
}

int FileClassifier::calculateScenePriority(const std::string& path, const std::string& filename, FileCategory category) {
    int priority = ScenePriority::IRRELEVANT;
    bool relevant = false;

    switch (sceneType_) {
        case SceneType::ANDROID:
            applyAndroidSceneRules(path, filename, priority, relevant);
            break;
        case SceneType::WINDOWS:
            applyWindowsSceneRules(path, filename, priority, relevant);
            break;
        case SceneType::LINUX:
            applyLinuxSceneRules(path, filename, priority, relevant);
            break;
        case SceneType::SERVER_CLOUD:
            applyServerCloudSceneRules(path, filename, priority, relevant);
            break;
        default:
            break;
    }

    return priority;
}

bool FileClassifier::isSceneRelevant(const std::string& path, const std::string& filename) {
    int priority = calculateScenePriority(path, filename, determineCategory(filename, path));
    return priority >= ScenePriority::MEDIUM;
}

void FileClassifier::applyAndroidSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Android 关键路径
    static const std::vector<std::pair<std::string, int>> criticalPaths = {
        {"/data/data/", ScenePriority::CRITICAL},
        {"/data/system/", ScenePriority::CRITICAL},
        {"/data/misc/", ScenePriority::HIGH},
        {"/system/build.prop", ScenePriority::HIGH},
        {"/data/app/", ScenePriority::MEDIUM},
        {"/data/user/", ScenePriority::HIGH}
    };

    for (const auto& [criticalPath, p] : criticalPaths) {
        if (path.find(criticalPath) != std::string::npos) {
            priority = p;
            relevant = (p >= ScenePriority::MEDIUM);
            return;
        }
    }

    // Android 特定应用路径
    static const std::vector<std::string> appPaths = {
        "com.android.providers.contacts",
        "com.android.providers.telephony",
        "com.tencent.mm",
        "org.telegram.messenger",
        "com.whatsapp"
    };

    for (const auto& appPath : appPaths) {
        if (path.find(appPath) != std::string::npos) {
            priority = ScenePriority::HIGH;
            relevant = true;
            return;
        }
    }
}

void FileClassifier::applyWindowsSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Windows 关键路径
    static const std::vector<std::pair<std::string, int>> criticalPaths = {
        {"Windows/System32/config/", ScenePriority::CRITICAL},
        {"Windows/System32/winevt/", ScenePriority::CRITICAL},
        {"Windows/Prefetch/", ScenePriority::HIGH},
        {"Users/*/AppData/", ScenePriority::HIGH},
        {"$Recycle.Bin/", ScenePriority::HIGH}
    };

    for (const auto& [criticalPath, p] : criticalPaths) {
        if (path.find(criticalPath) != std::string::npos) {
            priority = p;
            relevant = (p >= ScenePriority::MEDIUM);
            return;
        }
    }

    // Windows 关键文件
    static const std::vector<std::string> criticalFiles = {
        "SAM", "SYSTEM", "SOFTWARE", "SECURITY", "NTUSER.DAT"
    };

    for (const auto& file : criticalFiles) {
        if (filename == file) {
            priority = ScenePriority::CRITICAL;
            relevant = true;
            return;
        }
    }
}

void FileClassifier::applyLinuxSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Linux 关键路径
    static const std::vector<std::pair<std::string, int>> criticalPaths = {
        {"/var/log/", ScenePriority::CRITICAL},
        {"/etc/", ScenePriority::CRITICAL},
        {"/home/", ScenePriority::HIGH},
        {"/root/", ScenePriority::HIGH},
        {"/var/spool/cron/", ScenePriority::CRITICAL},
        {"/var/lib/docker/", ScenePriority::HIGH}
    };

    for (const auto& [criticalPath, p] : criticalPaths) {
        if (path.find(criticalPath) != std::string::npos) {
            priority = p;
            relevant = (p >= ScenePriority::MEDIUM);
            return;
        }
    }

    // Linux 关键文件
    static const std::vector<std::string> criticalFiles = {
        "passwd", "shadow", "group", "sudoers", "crontab",
        "authorized_keys", "id_rsa", ".bash_history"
    };

    for (const auto& file : criticalFiles) {
        if (filename == file) {
            priority = ScenePriority::CRITICAL;
            relevant = true;
            return;
        }
    }
}

void FileClassifier::applyServerCloudSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // 继承 Linux 规则
    applyLinuxSceneRules(path, filename, priority, relevant);

    // 云特定路径
    static const std::vector<std::pair<std::string, int>> cloudPaths = {
        {"/var/log/nginx/", ScenePriority::CRITICAL},
        {"/var/log/apache2/", ScenePriority::CRITICAL},
        {"/var/lib/mysql/", ScenePriority::HIGH},
        {"/etc/docker/", ScenePriority::HIGH},
        {"/etc/kubernetes/", ScenePriority::HIGH}
    };

    for (const auto& [cloudPath, p] : cloudPaths) {
        if (path.find(cloudPath) != std::string::npos) {
            priority = std::max(priority, p);
            relevant = (priority >= ScenePriority::MEDIUM);
            return;
        }
    }
}
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . --target test_scene_classifier
./test_scene_classifier
```

预期：所有测试通过

- [ ] **Step 6: 提交**

```bash
git add src/core/DatabaseManager/FileClassifier/FileClassifier.h src/core/DatabaseManager/FileClassifier/FileClassifier.cpp tests/UnitTest/test_scene_classifier_gtest.cpp
git commit -m "feat(classifier): add scene-aware classification support"
```

---

## Task 3: 修改 classifyFiles 支持场景标记

**Files:**
- Modify: `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp:166-270`
- Test: `tests/UnitTest/test_scene_classifier_gtest.cpp`

- [ ] **Step 1: 添加集成测试**

在 `tests/UnitTest/test_scene_classifier_gtest.cpp` 中添加：

```cpp
TEST_F(SceneClassifierTest, ClassifyAndExtractWithScene) {
    // 创建源数据库
    sqlite3* sourceDb;
    ASSERT_EQ(sqlite3_open(":memory:", &sourceDb), SQLITE_OK);

    // 创建源表
    const char* createSourceTable = R"(
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
    ASSERT_EQ(sqlite3_exec(sourceDb, createSourceTable, nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(sourceDb);

    // 测试 Android 场景分类
    {
        FileClassifier classifier(":memory:", ":memory:");
        classifier.setSceneType(SceneType::ANDROID);
        // 注意：这里需要实际的数据库文件路径，内存数据库不支持跨连接
        // 实际测试需要使用临时文件
    }
}
```

- [ ] **Step 2: 修改 classifyFiles 方法**

在 `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp` 中修改 `classifyFiles` 方法：

```cpp
bool FileClassifier::classifyFiles() {
    // ... 现有的读取文件逻辑 ...

    // 修改插入语句以包含场景字段
    const char* insertSQL = R"(
        INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant)
        VALUES (?, ?, ?, ?, ?, ?, 'REG', ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* insertStmt;
    if (sqlite3_prepare_v2(fileDb_, insertSQL, -1, &insertStmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert statement" << std::endl;
        return false;
    }

    // ... 在遍历文件的循环中 ...
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        // ... 现有的文件处理逻辑 ...

        // 计算场景信息
        std::string sceneTypeStr = (sceneType_ != SceneType::NONE) ? getSceneTypeName(sceneType_) : "";
        int priority = (sceneType_ != SceneType::NONE) ? calculateScenePriority(path, filename, category) : 0;
        bool relevant = (sceneType_ != SceneType::NONE) ? isSceneRelevant(path, filename) : false;

        // 绑定参数
        sqlite3_bind_int(insertStmt, 1, inode);
        sqlite3_bind_text(insertStmt, 2, filename.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_text(insertStmt, 3, path.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_int64(insertStmt, 4, size);
        sqlite3_bind_text(insertStmt, 5, extension.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_text(insertStmt, 6, categoryStr.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_int64(insertStmt, 7, mtime);
        sqlite3_bind_int64(insertStmt, 8, ctime);
        sqlite3_bind_int(insertStmt, 9, isDeleted ? 1 : 0);
        sqlite3_bind_text(insertStmt, 10, md5.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_text(insertStmt, 11, sceneTypeStr.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_int(insertStmt, 12, priority);
        sqlite3_bind_int(insertStmt, 13, relevant ? 1 : 0);

        if (sqlite3_step(insertStmt) != SQLITE_DONE) {
            std::cerr << "Failed to insert file: " << filename << std::endl;
        }

        sqlite3_reset(insertStmt);
    }

    sqlite3_finalize(insertStmt);
    return true;
}
```

- [ ] **Step 3: 运行测试验证**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . --target test_scene_classifier
./test_scene_classifier
```

预期：所有测试通过

- [ ] **Step 4: 提交**

```bash
git add src/core/DatabaseManager/FileClassifier/FileClassifier.cpp
git commit -m "feat(classifier): integrate scene marking into classifyFiles"
```

---

## Task 4: 修改 AnalysisOrchestrator 支持场景感知

**Files:**
- Modify: `src/AnalysisOrchestrator.cpp:31-198`
- Test: `tests/test_scene_integration.sh`

- [ ] **Step 1: 创建集成测试脚本**

```bash
#!/bin/bash
# tests/test_scene_integration.sh

echo "=== Scene Integration Test ==="

# 编译项目
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)

# 创建测试镜像（如果不存在）
if [ ! -f "test_android.img" ]; then
    echo "Creating test Android image..."
    bash ../tests/create_android_image.sh
fi

# 测试 Android 场景
echo "Testing Android scene..."
./forensic_analyzer test_android.img --android-analyze --db-dir test_output
if [ $? -eq 0 ]; then
    echo "✓ Android scene analysis passed"

    # 验证数据库结构
    echo "Verifying database structure..."
    sqlite3 test_output/test_android_files.db "SELECT COUNT(*) FROM files WHERE scene_type = 'android';"
    sqlite3 test_output/test_android_files.db "SELECT COUNT(*) FROM android_artifacts;"
else
    echo "✗ Android scene analysis failed"
    exit 1
fi

echo "=== All scene integration tests passed ==="
```

- [ ] **Step 2: 修改 AnalysisOrchestrator.cpp**

在 `src/AnalysisOrchestrator.cpp` 中修改 `runAnalysis` 方法：

```cpp
int AnalysisOrchestrator::runAnalysis(const CommandLineArgs& args) {
    // ... 现有的 Step 1 和 Step 2 ...

    // Step 3: 场景感知文件分类
    std::cout << "[3/4] Classifying files..." << std::endl;
    auto classifier = std::make_unique<FileClassifier>(effectiveRawDb, fileDbPath);

    // 设置场景类型
    SceneType sceneType = SceneType::NONE;
    if (args.android_analyze) sceneType = SceneType::ANDROID;
    else if (args.windows_analyze) sceneType = SceneType::WINDOWS;
    else if (args.linux_analyze) sceneType = SceneType::LINUX;

    classifier->setSceneType(sceneType);

    if (!classifier->classifyAndExtract()) {
        std::cerr << "Error: Failed to classify files" << std::endl;
        return 1;
    }
    std::cout << "✓ File database: " << fileDbPath << "\n" << std::endl;

    // Step 4: 场景特化分析（写入 files.db）
    if (args.android_analyze) {
        std::cout << "[Android] Analyzing..." << std::endl;
        auto dbMgr = std::make_unique<DatabaseManager>(effectiveRawDb);
        auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(args.image_path, dbMgr.get());
        if (!args.wechat_password.empty()) {
            androidAnalyzer->setWeChatPassword(args.wechat_password);
        }
        // 修改：写入 files.db 而非独立数据库
        androidAnalyzer->setOutputDatabasePath(fileDbPath);
        if (androidAnalyzer->initialize()) {
            androidAnalyzer->analyzeAndroidData();
            std::cout << "✓ Android analysis complete\n" << std::endl;
        }
    }

    // ... Windows 和 Linux 类似修改 ...

    // Step 5: 生成时间线
    std::cout << "[4/4] Generating timeline..." << std::endl;
    auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
    if (eventExtractor->extractEvents()) {
        // 从 files.db 导入场景工件
        if (args.android_analyze) {
            eventExtractor->importSceneArtifacts(fileDbPath, "android");
        }
        if (args.windows_analyze) {
            eventExtractor->importSceneArtifacts(fileDbPath, "windows");
        }
        if (args.linux_analyze) {
            eventExtractor->importSceneArtifacts(fileDbPath, "linux");
        }
        std::cout << "✓ Timeline: " << eventDbPath << "\n" << std::endl;
    }

    // ... 其余代码 ...
}
```

- [ ] **Step 3: 运行集成测试**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
bash tests/test_scene_integration.sh
```

预期：所有测试通过

- [ ] **Step 4: 提交**

```bash
git add src/AnalysisOrchestrator.cpp tests/test_scene_integration.sh
git commit -m "feat(orchestrator): integrate scene-aware classification into main pipeline"
```

---

## Task 5: 修改场景分析器支持集成模式

**Files:**
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h`
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp`
- Modify: `src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h`
- Modify: `src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp`
- Modify: `src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.h`
- Modify: `src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.cpp`

- [ ] **Step 1: 修改 AndroidAnalysisDatabase.h**

```cpp
class AndroidAnalysisDatabase {
public:
    // 修改构造函数添加集成模式参数
    AndroidAnalysisDatabase(const std::string& dbPath, bool integratedMode = false);
    ~AndroidAnalysisDatabase();

    bool initialize();

    // ... 现有接口 ...

private:
    std::string dbPath_;
    sqlite3* db_;
    bool integratedMode_;  // 新增

    bool createTables();
    bool createArtifactsTable();  // 新增
    bool executeSQL(const char* sql);
};
```

- [ ] **Step 2: 修改 AndroidAnalysisDatabase.cpp**

```cpp
AndroidAnalysisDatabase::AndroidAnalysisDatabase(const std::string& dbPath, bool integratedMode)
    : dbPath_(dbPath), db_(nullptr), integratedMode_(integratedMode) {}

bool AndroidAnalysisDatabase::initialize() {
    if (sqlite3_open(dbPath_.c_str(), &db_) != SQLITE_OK) {
        std::cerr << "Cannot open database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    if (integratedMode_) {
        return createArtifactsTable();
    } else {
        return createTables();
    }
}

bool AndroidAnalysisDatabase::createArtifactsTable() {
    return executeSQL(FileClassifierSQL::CREATE_ANDROID_ARTIFACTS_TABLE);
}

// 修改插入方法以支持集成模式
bool AndroidAnalysisDatabase::insertSMS(int fileId, const std::string& address, const std::string& body, int64_t date, int type) {
    if (integratedMode_) {
        const char* sql = FileClassifierSQL::INSERT_ANDROID_ARTIFACT;
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

        std::string artifactData = "{\"address\":\"" + address + "\",\"body\":\"" + body + "\",\"date\":" + std::to_string(date) + ",\"type\":" + std::to_string(type) + "}";

        sqlite3_bind_int(stmt, 1, fileId);
        sqlite3_bind_text(stmt, 2, "sms", -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, artifactData.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(stmt, 4, time(nullptr));

        bool success = sqlite3_step(stmt) == SQLITE_DONE;
        sqlite3_finalize(stmt);
        return success;
    } else {
        // 原有逻辑
        // ...
    }
}
```

- [ ] **Step 3: 类似修改 WindowsAnalysisDatabase 和 LinuxAnalysisDatabase**

对 `WindowsAnalysisDatabase` 和 `LinuxAnalysisDatabase` 进行类似的修改，添加 `integratedMode_` 参数和 `createArtifactsTable()` 方法。

- [ ] **Step 4: 运行测试验证**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . -j$(nproc)
ctest --output-on-failure
```

预期：所有测试通过

- [ ] **Step 5: 提交**

```bash
git add src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp
git add src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp
git add src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.h src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.cpp
git commit -m "feat(analyzers): add integrated mode support for scene analyzers"
```

---

## Task 6: 添加 importSceneArtifacts 到 EventExtractor

**Files:**
- Modify: `src/core/DatabaseManager/EventExtractor/EventExtractor.h:95-146`
- Modify: `src/core/DatabaseManager/EventExtractor/Detail/EventExtractorCore.cpp`
- Test: `tests/UnitTest/test_scene_database_gtest.cpp`

- [ ] **Step 1: 添加测试**

在 `tests/UnitTest/test_scene_database_gtest.cpp` 中添加：

```cpp
TEST_F(SceneDatabaseTest, ImportSceneArtifacts) {
    // 创建 files.db 和 events.db
    // ... 测试逻辑 ...
}
```

- [ ] **Step 2: 修改 EventExtractor.h**

```cpp
class EventExtractor {
public:
    // ... 现有接口 ...

    // 新增：从 files.db 导入场景工件
    bool importSceneArtifacts(const std::string& fileDbPath, const std::string& sceneType);

private:
    // ... 现有成员 ...

    // 新增：导入场景工件的辅助方法
    bool importAndroidArtifactsFromFilesDb(const std::string& fileDbPath);
    bool importWindowsArtifactsFromFilesDb(const std::string& fileDbPath);
    bool importLinuxArtifactsFromFilesDb(const std::string& fileDbPath);
};
```

- [ ] **Step 3: 实现 importSceneArtifacts**

在 `src/core/DatabaseManager/EventExtractor/Detail/EventExtractorCore.cpp` 中添加：

```cpp
bool EventExtractor::importSceneArtifacts(const std::string& fileDbPath, const std::string& sceneType) {
    if (sceneType == "android") {
        return importAndroidArtifactsFromFilesDb(fileDbPath);
    } else if (sceneType == "windows") {
        return importWindowsArtifactsFromFilesDb(fileDbPath);
    } else if (sceneType == "linux") {
        return importLinuxArtifactsFromFilesDb(fileDbPath);
    }
    return false;
}

bool EventExtractor::importAndroidArtifactsFromFilesDb(const std::string& fileDbPath) {
    std::cout << "Importing Android artifacts from files.db..." << std::endl;

    sqlite3* fileDb;
    if (sqlite3_open(fileDbPath.c_str(), &fileDb) != SQLITE_OK) {
        std::cerr << "Failed to open files.db" << std::endl;
        return false;
    }

    const char* query = R"(
        SELECT aa.artifact_type, aa.artifact_data, aa.extracted_at,
               f.path, f.name, f.size, f.extension
        FROM android_artifacts aa
        JOIN files f ON aa.file_id = f.id
        ORDER BY aa.extracted_at
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(fileDb, query, -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(fileDb);
        return false;
    }

    int importedCount = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string artifactType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        std::string artifactData = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        int64_t extractedAt = sqlite3_column_int64(stmt, 2);
        std::string filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        std::string fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        int64_t fileSize = sqlite3_column_int64(stmt, 5);
        std::string extension = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));

        // 创建时间线事件
        TimelineEvent event;
        event.timestamp = extractedAt;
        event.eventType = "ANDROID_ARTIFACT";
        event.filePath = filePath;
        event.description = "Android " + artifactType + ": " + fileName;
        event.fileSize = fileSize;
        event.fileType = extension;
        event.source = EventSource::ANDROID_LOG;
        event.category = EventCategory::APPLICATION_EVENT;

        if (insertEvent(event)) {
            importedCount++;
        }
    }

    sqlite3_finalize(stmt);
    sqlite3_close(fileDb);

    std::cout << "Imported " << importedCount << " Android artifacts" << std::endl;
    return true;
}

// 类似实现 importWindowsArtifactsFromFilesDb 和 importLinuxArtifactsFromFilesDb
```

- [ ] **Step 4: 运行测试验证**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . --target test_scene_database
./test_scene_database
```

预期：所有测试通过

- [ ] **Step 5: 提交**

```bash
git add src/core/DatabaseManager/EventExtractor/EventExtractor.h src/core/DatabaseManager/EventExtractor/Detail/EventExtractorCore.cpp
git commit -m "feat(event-extractor): add importSceneArtifacts method"
```

---

## Task 7: 修改 LLMAnalysisService 支持场景优先级

**Files:**
- Modify: `src/network/HTTPServer/LLMAnalysisService.h:21-109`
- Modify: `src/network/HTTPServer/LLMAnalysisService.cpp:40-86,255-312`
- Test: `tests/UnitTest/test_scene_classifier_gtest.cpp`

- [ ] **Step 1: 添加测试**

在 `tests/UnitTest/test_scene_classifier_gtest.cpp` 中添加：

```cpp
TEST_F(SceneClassifierTest, LLMAnalysisScenePriority) {
    // 测试 LLM 分析场景优先级排序
}
```

- [ ] **Step 2: 修改 LLMAnalysisService.h**

```cpp
class LLMAnalysisService {
public:
    // ... 现有接口 ...

    // 新增：设置场景类型
    void setSceneType(SceneType scene);
    SceneType getSceneType() const;

private:
    // ... 现有成员 ...

    // 新增：场景类型
    SceneType sceneType_ = SceneType::NONE;

    // 新增：场景优先级文件获取
    std::vector<FileRecord> getScenePrioritizedFiles(sqlite3* db, int limit);
    bool shouldSkipFile(const FileRecord& file);
    std::string getSceneSpecificPrompt(const FileRecord& file);
};
```

- [ ] **Step 3: 实现场景优先级方法**

在 `src/network/HTTPServer/LLMAnalysisService.cpp` 中添加：

```cpp
void LLMAnalysisService::setSceneType(SceneType scene) {
    sceneType_ = scene;
}

SceneType LLMAnalysisService::getSceneType() const {
    return sceneType_;
}

std::vector<FileRecord> LLMAnalysisService::getScenePrioritizedFiles(sqlite3* db, int limit) {
    std::vector<FileRecord> files;

    std::string query;
    if (sceneType_ != SceneType::NONE) {
        query = "SELECT id, inode, name, path, size, extension, category, type, "
                "mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant "
                "FROM files WHERE type = 'REG' "
                "AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) "
                "AND scene_priority > 0 "
                "ORDER BY scene_priority DESC, size ASC LIMIT ?";
    } else {
        query = "SELECT id, inode, name, path, size, extension, category, type, "
                "mtime, ctime, is_deleted, md5, NULL, 0, 0 "
                "FROM files WHERE type = 'REG' "
                "AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) "
                "ORDER BY size ASC LIMIT ?";
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return files;
    }

    sqlite3_bind_int(stmt, 1, limit);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord file;
        file.id = sqlite3_column_int(stmt, 0);
        // ... 解析其他字段 ...
        files.push_back(file);
    }

    sqlite3_finalize(stmt);
    return files;
}

bool LLMAnalysisService::shouldSkipFile(const FileRecord& file) {
    if (sceneType_ == SceneType::NONE) return false;
    return file.scenePriority == 0;
}

std::string LLMAnalysisService::getSceneSpecificPrompt(const FileRecord& file) {
    std::string basePrompt = "Analyze this forensic file and provide:\n"
        "1. A brief summary of the file's purpose\n"
        "2. A detailed description of its contents\n"
        "3. Relevant keywords for searching\n\n"
        "File path: " + file.path + "\n"
        "File name: " + file.name + "\n";

    if (sceneType_ == SceneType::ANDROID) {
        basePrompt += "\nAndroid forensic analysis. Focus on mobile app data, communications, and device configuration.\n";
    } else if (sceneType_ == SceneType::WINDOWS) {
        basePrompt += "\nWindows forensic analysis. Focus on registry artifacts, event logs, and user activity.\n";
    } else if (sceneType_ == SceneType::LINUX) {
        basePrompt += "\nLinux forensic analysis. Focus on system logs, user accounts, and network configuration.\n";
    }

    return basePrompt;
}
```

- [ ] **Step 4: 运行测试验证**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . -j$(nproc)
ctest --output-on-failure
```

预期：所有测试通过

- [ ] **Step 5: 提交**

```bash
git add src/network/HTTPServer/LLMAnalysisService.h src/network/HTTPServer/LLMAnalysisService.cpp
git commit -m "feat(llm): add scene priority support to LLM analysis"
```

---

## Task 8: 修改 TaskManager 支持场景感知

**Files:**
- Modify: `src/network/HTTPServer/TaskManager.cpp:494-868`
- Modify: `src/network/HTTPServer/HTTPServerDataTypes.h:98-245`

- [ ] **Step 1: 修改 HTTPServerDataTypes.h**

```cpp
// 在 AnalysisTask 结构中添加
struct AnalysisTask {
    // ... 现有字段 ...

    // 新增：场景配置
    struct SceneConfig {
        bool enabled = false;
        int priorityThreshold = 50;
        bool autoDetect = false;
        std::vector<std::string> customRules;
    };
    std::map<ForensicScenario, SceneConfig> sceneConfigs;
};
```

- [ ] **Step 2: 修改 TaskManager.cpp 的 start_analysis 方法**

```cpp
void TaskManager::start_analysis(const std::string& task_id) {
    // ... 现有代码 ...

    // 文件分类阶段：设置场景类型
    task.phase = TaskPhase::FILE_CLASSIFICATION;
    update_task_progress(task_id, 30, "Classifying files...");

    auto classifier = std::make_unique<FileClassifier>(rawDbPath, fileDbPath);

    // 根据任务场景设置分类器
    SceneType sceneType = SceneType::NONE;
    if (!task.scenarios.empty()) {
        switch (task.scenarios[0]) {
            case ForensicScenario::ANDROID: sceneType = SceneType::ANDROID; break;
            case ForensicScenario::WINDOWS: sceneType = SceneType::WINDOWS; break;
            case ForensicScenario::LINUX: sceneType = SceneType::LINUX; break;
            case ForensicScenario::SERVER_CLOUD: sceneType = SceneType::SERVER_CLOUD; break;
        }
    }
    classifier->setSceneType(sceneType);

    if (!classifier->classifyAndExtract()) {
        task.status = TaskStatus::FAILED;
        task.error = "File classification failed";
        return;
    }

    // 场景特化分析
    task.phase = TaskPhase::PLATFORM_ANALYSIS;
    update_task_progress(task_id, 50, "Running scene-specific analysis...");

    for (auto scenario : task.scenarios) {
        if (is_task_cancelled(task_id)) {
            task.status = TaskStatus::CANCELLED;
            return;
        }

        switch (scenario) {
            case ForensicScenario::ANDROID: {
                auto dbMgr = std::make_unique<DatabaseManager>(rawDbPath);
                auto analyzer = std::make_unique<AndroidAnalyzer>(task.image_path, dbMgr.get());
                analyzer->setOutputDatabasePath(fileDbPath);
                if (analyzer->initialize()) {
                    analyzer->analyzeAndroidData();
                }
                break;
            }
            // ... Windows 和 Linux 类似 ...
        }
    }

    // LLM 分析：使用场景优先级
    if (task.llm_analyze) {
        task.phase = TaskPhase::LLM_ANALYSIS;
        update_task_progress(task_id, 70, "Running LLM analysis...");

        LLMAnalysisService llmService;
        llmService.setSceneType(sceneType);
        llmService.analyzeFiles(fileDbPath, task.llm_mode);
    }

    // ... 其余代码 ...
}
```

- [ ] **Step 3: 运行测试验证**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . -j$(nproc)
ctest --output-on-failure
```

预期：所有测试通过

- [ ] **Step 4: 提交**

```bash
git add src/network/HTTPServer/TaskManager.cpp src/network/HTTPServer/HTTPServerDataTypes.h
git commit -m "feat(task-manager): integrate scene-aware analysis into HTTP pipeline"
```

---

## Task 9: 添加场景查询 API

**Files:**
- Modify: `src/network/HTTPServer/routes/ForensicsRoutes.cpp`
- Test: `tests/test_scene_api.sh`

- [ ] **Step 1: 创建 API 测试脚本**

```bash
#!/bin/bash
# tests/test_scene_api.sh

echo "=== Scene API Test ==="

# 启动服务器
./forensic_analyzer --http-server 8080 &
SERVER_PID=$!
sleep 2

# 创建任务
echo "Creating task with scene config..."
RESPONSE=$(curl -s -X POST http://localhost:8080/api/tasks \
    -H "Content-Type: application/json" \
    -d '{
        "image_path": "test.img",
        "scenarios": ["android"],
        "llm_analyze": true
    }')

TASK_ID=$(echo $RESPONSE | jq -r '.id')
echo "Task ID: $TASK_ID"

# 等待任务完成
sleep 10

# 查询场景统计
echo "Querying scene stats..."
curl -s http://localhost:8080/api/tasks/$TASK_ID/scene-stats | jq .

# 查询场景工件
echo "Querying scene artifacts..."
curl -s "http://localhost:8080/api/tasks/$TASK_ID/scene-artifacts?scene_type=android" | jq .

# 停止服务器
kill $SERVER_PID

echo "=== Scene API Test Complete ==="
```

- [ ] **Step 2: 实现场景查询 API**

在 `src/network/HTTPServer/routes/ForensicsRoutes.cpp` 中添加：

```cpp
void ForensicsRoutes::handle_get_scene_stats(const crow::request& req, crow::response& res, const std::string& task_id) {
    try {
        auto& tm = TaskManager::instance();
        auto task = tm.get_task(task_id);

        if (task.status == TaskStatus::NOT_FOUND) {
            res.code = 404;
            res.write("{\"error\": \"Task not found\"}");
            res.end();
            return;
        }

        sqlite3* db;
        if (sqlite3_open(task.fileDbPath.c_str(), &db) != SQLITE_OK) {
            res.code = 500;
            res.write("{\"error\": \"Failed to open database\"}");
            res.end();
            return;
        }

        crow::json::wvalue response;

        // 查询场景文件统计
        const char* sceneStatsSQL = FileClassifierSQL::SELECT_SCENE_FILE_STATS;
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sceneStatsSQL, -1, &stmt, nullptr) == SQLITE_OK) {
            response["scene_stats"] = crow::json::wvalue(crow::json::type::List);
            int index = 0;

            while (sqlite3_step(stmt) == SQLITE_ROW) {
                crow::json::wvalue stat;
                stat["scene_type"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
                stat["total_files"] = sqlite3_column_int(stmt, 1);
                stat["relevant_files"] = sqlite3_column_int(stmt, 2);
                stat["total_size"] = sqlite3_column_int64(stmt, 3);
                stat["llm_analyzed_files"] = sqlite3_column_int(stmt, 4);

                response["scene_stats"][index] = std::move(stat);
                index++;
            }

            sqlite3_finalize(stmt);
        }

        sqlite3_close(db);

        res.code = 200;
        res.write(response.dump());
        res.end();

    } catch (const std::exception& e) {
        res.code = 500;
        res.write("{\"error\": \"" + std::string(e.what()) + "\"}");
        res.end();
    }
}
```

- [ ] **Step 3: 注册路由**

在 HTTPServer 构造函数中注册新路由：

```cpp
// GET /api/tasks/{id}/scene-stats
CROW_ROUTE(app, "/api/tasks/<string>/scene-stats")
    .methods("GET"_method)
    ([this](const crow::request& req, crow::response& res, const std::string& task_id) {
        forensicsRoutes_.handle_get_scene_stats(req, res, task_id);
    });
```

- [ ] **Step 4: 运行测试验证**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
bash tests/test_scene_api.sh
```

预期：所有 API 测试通过

- [ ] **Step 5: 提交**

```bash
git add src/network/HTTPServer/routes/ForensicsRoutes.cpp tests/test_scene_api.sh
git commit -m "feat(api): add scene statistics and artifacts query endpoints"
```

---

## 最终验证

- [ ] **运行完整测试套件**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
ctest --output-on-failure
```

- [ ] **运行集成测试**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
bash tests/test_scene_integration.sh
bash tests/test_scene_api.sh
```

- [ ] **验证向后兼容性**

```bash
# 测试旧数据库迁移
./forensic_analyzer old_image.img --android-analyze --db-dir test_migration
sqlite3 test_migration/old_image_files.db "SELECT scene_type, scene_priority, scene_relevant FROM files LIMIT 5;"
```

- [ ] **最终提交**

```bash
git add -A
git commit -m "feat: complete scene-aware pipeline integration"
```
