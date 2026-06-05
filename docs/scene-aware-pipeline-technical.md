# 场景感知管道集成技术文档

**版本：** 1.0
**日期：** 2026-06-05
**作者：** Forensics Team

## 概述

本文档描述将场景特化分析功能集成到主管道中的技术实现。场景感知管道允许用户在创建分析任务时选择特定的取证场景（Android、Windows、Linux、Server/Cloud），系统会根据场景自动优化文件分类、LLM 分析和工件提取。

## 架构变更

### 1. 数据库架构扩展

#### 1.1 场景相关列

在 `_files.db` 的 `files` 表中添加了三个新列：

```sql
ALTER TABLE files ADD COLUMN scene_type TEXT;           -- 'android', 'windows', 'linux', 'server_cloud', NULL
ALTER TABLE files ADD COLUMN scene_priority INTEGER DEFAULT 0;  -- 场景优先级 (0-100)
ALTER TABLE files ADD COLUMN scene_relevant INTEGER DEFAULT 0;  -- 是否为场景关键文件 (0/1)
```

#### 1.2 场景工件表

创建了三个场景工件表，使用模板化设计：

```sql
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
```

相同的结构用于 `windows_artifacts` 和 `linux_artifacts` 表。

#### 1.3 场景统计视图

```sql
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
```

### 2. FileClassifier 场景感知改造

#### 2.1 新增枚举和结构

```cpp
enum class SceneType {
    NONE,
    ANDROID,
    WINDOWS,
    LINUX,
    SERVER_CLOUD
};

struct ScenePriority {
    static constexpr int CRITICAL = 100;   // 场景关键文件
    static constexpr int HIGH = 75;        // 场景重要文件
    static constexpr int MEDIUM = 50;      // 场景相关文件
    static constexpr int LOW = 25;         // 场景次要文件
    static constexpr int IRRELEVANT = 0;   // 与场景无关
};
```

#### 2.2 场景特化规则

每个场景都有特定的路径和文件匹配规则：

**Android 场景：**
- CRITICAL: `/data/data/`, `/data/system/`, 系统提供者数据库
- HIGH: 第三方应用（微信、Telegram、WhatsApp）
- MEDIUM: `/data/app/`, `/system/build.prop`

**Windows 场景：**
- CRITICAL: `Windows/System32/config/`（注册表）, `Windows/System32/winevt/`（事件日志）
- HIGH: `Windows/Prefetch/`, `Users/*/AppData/`
- 关键文件: SAM, SYSTEM, SOFTWARE, SECURITY, NTUSER.DAT

**Linux 场景：**
- CRITICAL: `/var/log/`, `/etc/`, `/var/spool/cron/`
- HIGH: `/home/`, `/root/`, `/var/lib/docker/`
- 关键文件: passwd, shadow, group, sudoers, crontab

**Server/Cloud 场景：**
- 继承 Linux 规则
- 额外: `/var/log/nginx/`, `/var/log/apache2/`, `/var/lib/mysql/`, `/etc/docker/`, `/etc/kubernetes/`

### 3. 管道集成

#### 3.1 CLI 管道 (AnalysisOrchestrator)

```cpp
// Step 3: 场景感知文件分类
auto classifier = std::make_unique<FileClassifier>(effectiveRawDb, fileDbPath);

// 设置场景类型
SceneType sceneType = SceneType::NONE;
if (args.android_analyze) sceneType = SceneType::ANDROID;
else if (args.windows_analyze) sceneType = SceneType::WINDOWS;
else if (args.linux_analyze) sceneType = SceneType::LINUX;

classifier->setSceneType(sceneType);
classifier->classifyAndExtract();

// Step 4: 场景特化分析（写入 files.db）
if (args.android_analyze) {
    auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(args.image_path, dbMgr.get());
    androidAnalyzer->setOutputDatabasePath(fileDbPath);  // 写入 files.db
    androidAnalyzer->analyzeAndroidData();
}

// Step 5: 时间线生成（导入场景工件）
auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
if (eventExtractor->extractEvents()) {
    eventExtractor->importSceneArtifacts(fileDbPath, "android");
}
```

#### 3.2 HTTP 管道 (TaskManager)

```cpp
// 文件分类阶段：设置场景类型
auto classifier = std::make_unique<FileClassifier>(rawDbPath, fileDbPath);

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
classifier->classifyAndExtract();

// LLM 分析：使用场景优先级
LLMAnalysisService llmService;
llmService.setSceneType(sceneType);
llmService.analyzeFiles(fileDbPath, task.llm_mode);
```

### 4. LLM 分析优化

#### 4.1 场景优先级排序

```cpp
std::vector<FileRecord> LLMAnalysisService::getScenePrioritizedFiles(sqlite3* db, int limit) {
    std::string query;
    if (sceneType_ != SceneType::NONE) {
        // 场景模式：按场景优先级排序
        query = "SELECT * FROM files "
                "WHERE type = 'REG' "
                "AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) "
                "AND scene_priority > 0 "
                "ORDER BY scene_priority DESC, size ASC LIMIT ?";
    } else {
        // 非场景模式：按文件大小排序
        query = "SELECT * FROM files "
                "WHERE type = 'REG' "
                "AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) "
                "ORDER BY size ASC LIMIT ?";
    }
    // ...
}
```

#### 4.2 文件筛选

```cpp
bool LLMAnalysisService::shouldSkipFile(const FileRecord& file) {
    if (sceneType_ == SceneType::NONE) return false;
    return file.scenePriority == 0;  // 跳过与场景无关的文件
}
```

#### 4.3 场景特定提示

```cpp
std::string LLMAnalysisService::getSceneSpecificPrompt(const FileRecord& file) {
    std::string basePrompt = "Analyze this forensic file...\n";

    if (sceneType_ == SceneType::ANDROID) {
        basePrompt += "\nAndroid forensic analysis. Focus on mobile app data, communications.\n";
    } else if (sceneType_ == SceneType::WINDOWS) {
        basePrompt += "\nWindows forensic analysis. Focus on registry, event logs.\n";
    } else if (sceneType_ == SceneType::LINUX) {
        basePrompt += "\nLinux forensic analysis. Focus on system logs, user accounts.\n";
    }

    return basePrompt;
}
```

### 5. 场景分析器集成模式

#### 5.1 集成模式构造函数

```cpp
class AndroidAnalysisDatabase {
public:
    AndroidAnalysisDatabase(const std::string& dbPath, bool integratedMode = false);

    bool initialize() {
        if (integratedMode_) {
            return createArtifactsTable();  // 创建工件表
        } else {
            return createTables();  // 创建完整平台表
        }
    }
};
```

#### 5.2 工件表创建

```cpp
bool AndroidAnalysisDatabase::createArtifactsTable() {
    // 使用模板创建工件表
    std::string sql = FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE;
    // 替换 %TABLE_NAME% 为 android_artifacts
    return executeSQL(sql.c_str());
}
```

### 6. 场景工件导入

#### 6.1 统一导入接口

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
```

#### 6.2 Android 工件导入

```cpp
bool EventExtractor::importAndroidArtifactsFromFilesDb(const std::string& fileDbPath) {
    // 查询 android_artifacts 表
    const char* query = R"(
        SELECT aa.artifact_type, aa.artifact_data, aa.extracted_at,
               f.path, f.name, f.size, f.extension
        FROM android_artifacts aa
        JOIN files f ON aa.file_id = f.id
        ORDER BY aa.extracted_at
    )";

    // 创建时间线事件
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        TimelineEvent event;
        event.timestamp = extractedAt;
        event.eventType = "ANDROID_ARTIFACT";
        event.filePath = filePath;
        event.description = "Android " + artifactType + ": " + fileName;
        event.source = EventSource::ANDROID_LOG;
        event.category = EventCategory::APPLICATION_EVENT;

        insertEvent(event);
    }
}
```

## API 变更

### 1. 新增 API 端点

#### GET /api/tasks/{id}/scene-stats

返回场景文件统计信息。

**响应示例：**
```json
{
  "scene_stats": [
    {
      "scene_type": "android",
      "total_files": 1500,
      "relevant_files": 450,
      "total_size": 1073741824,
      "llm_analyzed_files": 400
    }
  ],
  "artifact_stats": [
    {
      "scene_type": "android",
      "artifact_type": "sms",
      "artifact_count": 150,
      "analyzed_count": 120
    }
  ]
}
```

#### GET /api/tasks/{id}/scene-artifacts

返回分页的场景工件列表。

**查询参数：**
- `scene_type` (必需): "android", "windows", 或 "linux"
- `limit` (可选): 每页结果数（默认: 100）
- `offset` (可选): 跳过的结果数（默认: 0）

**响应示例：**
```json
{
  "artifacts": [
    {
      "id": 1,
      "artifact_type": "sms",
      "artifact_data": "{\"address\":\"+1234567890\",\"body\":\"Hello\"}",
      "extracted_at": 1234567890,
      "file_path": "/data/data/com.android.providers.telephony/databases/sms.db",
      "file_name": "sms.db",
      "file_size": 2048,
      "file_extension": ".db"
    }
  ],
  "total": 150,
  "limit": 100,
  "offset": 0
}
```

### 2. 任务创建 API 更新

```json
POST /api/tasks
{
  "image_path": "/path/to/disk.dd",
  "scenarios": ["android", "windows"],
  "priority": "high",
  "llm_analyze": true,
  "llm_mode": "smart"
}
```

## 性能优化

### LLM 分析时间优化

| 优化策略 | 文件数 | 减少比例 |
|----------|--------|----------|
| 无场景特化 | 40 | 0% |
| 单场景特化 | 10 | **75%** |
| 高优先级阈值 | 22 | **45%** |
| 关键优先级阈值 | 15 | **62.5%** |

### 优化原理

1. **场景标记阶段**：在文件分类时，根据场景规则标记文件优先级
2. **LLM 分析阶段**：按优先级排序，跳过优先级为 0 的文件
3. **工件提取阶段**：只提取场景相关的工件数据

## 文件变更清单

### 核心修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `src/core/DatabaseManager/SQL/file_classifier_sql.h` | 添加场景 SQL 定义 |
| `src/core/DatabaseManager/FileClassifier/FileClassifier.h` | 添加 SceneType 枚举 |
| `src/core/DatabaseManager/FileClassifier/FileClassifier.cpp` | 实现场景感知分类 |
| `src/AnalysisOrchestrator.cpp` | CLI 管道集成 |
| `src/network/HTTPServer/TaskManager.cpp` | HTTP 管道集成 |
| `src/network/HTTPServer/LLMAnalysisService.h/cpp` | 场景优先级支持 |
| `src/network/HTTPServer/HTTPServerDataTypes.h` | SceneConfig 结构 |
| `src/core/DatabaseManager/EventExtractor/EventExtractor.h/cpp` | 场景工件导入 |
| `src/network/HTTPServer/routes/SceneQueryRoutes.h/cpp` | 场景查询 API |

### 场景分析器修改

| 文件路径 | 修改内容 |
|----------|----------|
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h/cpp` | 集成模式支持 |
| `src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h/cpp` | 集成模式支持 |
| `src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.h/cpp` | 集成模式支持 |

### 测试文件

| 文件路径 | 测试内容 |
|----------|----------|
| `tests/UnitTest/test_scene_database_gtest.cpp` | 场景数据库测试 |
| `tests/UnitTest/test_scene_classifier_gtest.cpp` | 场景分类器测试 |
| `tests/UnitTest/test_scene_performance_gtest.cpp` | 性能优化测试 |
| `tests/test_scene_integration.sh` | 集成测试脚本 |

## 向后兼容性

### 1. 数据库迁移

- 自动检测并添加场景相关列
- 旧数据库自动迁移到新架构
- 不影响现有数据

### 2. API 兼容性

- 旧的 `android_analyze`、`windows_analyze`、`linux_analyze` 参数自动转换为 `scenarios` 数组
- 新的 `scenarios` 参数是推荐的使用方式

### 3. 场景分析器兼容性

- `integratedMode` 参数默认为 `false`，保持旧行为
- 设置为 `true` 时使用新的集成模式

## 使用示例

### CLI 模式

```bash
# Android 场景分析
./forensic_analyzer disk.img --android-analyze

# Windows 场景分析
./forensic_analyzer disk.img --windows-analyze

# Linux 场景分析
./forensic_analyzer disk.img --linux-analyze
```

### HTTP API 模式

```bash
# 创建 Android 场景任务
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/path/to/disk.dd",
    "scenarios": ["android"],
    "llm_analyze": true
  }'

# 查询场景统计
curl http://localhost:8080/api/tasks/{task_id}/scene-stats

# 查询场景工件
curl "http://localhost:8080/api/tasks/{task_id}/scene-artifacts?scene_type=android&limit=50"
```

## 测试验证

### 单元测试

```bash
cd build
cmake --build . --target test_scene_classifier_gtest
./test_scene_classifier_gtest

cmake --build . --target test_scene_database_gtest
./test_scene_database_gtest

cmake --build . --target test_scene_performance_gtest
./test_scene_performance_gtest
```

### 集成测试

```bash
bash tests/test_scene_integration.sh
```

## 总结

场景感知管道集成实现了以下目标：

1. **场景感知分类**：在文件分类阶段识别和标记场景相关文件
2. **数据库合并**：将场景特化数据合并到 `_files.db` 中
3. **LLM 分析优化**：使用场景优先级减少 LLM 分析的文件数量（减少 45-75%）
4. **向后兼容**：保持现有功能不变，支持渐进式迁移
5. **用户选择**：场景类型由用户通过前端 UI 选择

该集成显著降低了 LLM 分析时间，同时保持了完整的取证分析能力。
