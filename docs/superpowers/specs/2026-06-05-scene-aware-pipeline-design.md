# 场景感知管道集成设计文档

**日期：** 2026-06-05
**状态：** 已批准
**作者：** Forensics Team

## 概述

本文档描述将场景特化分析功能集成到主管道中的设计方案。当前场景特化分析（Android、Windows、Linux）在主管道完成后作为独立步骤运行，本设计将其融入主管道，实现场景感知分类和优化的 LLM 分析。

## 设计目标

1. **场景感知分类**：在文件分类阶段识别和标记场景相关文件
2. **数据库合并**：将场景特化数据合并到 `_files.db` 中，消除独立数据库
3. **LLM 分析优化**：使用场景优先级减少 LLM 分析的文件数量，降低分析时间
4. **向后兼容**：保持现有功能不变，支持渐进式迁移
5. **用户选择**：场景类型由用户通过前端 UI 选择，而非自动检测

## 架构变更

### 当前架构

```
ImageAnalyzer → FileFilter → FileClassifier → SceneAnalyzers → EventExtractor
                                    ↓
                              _files.db
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
              _android.db     _windows.db      _linux.db
```

### 目标架构

```
ImageAnalyzer → FileFilter → Scene-Aware FileClassifier → SceneAnalyzers → EventExtractor
                                    ↓
                              _files.db (扩展)
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
             android_artifacts  windows_artifacts  linux_artifacts
```

## 详细设计

### 1. 数据库架构变更

#### 1.1 扩展 `files` 表

```sql
ALTER TABLE files ADD COLUMN scene_type TEXT;           -- 'android', 'windows', 'linux', 'server_cloud', NULL
ALTER TABLE files ADD COLUMN scene_priority INTEGER DEFAULT 0;  -- 场景相关文件优先级 (0-100)
ALTER TABLE files ADD COLUMN scene_relevant INTEGER DEFAULT 0;  -- 是否为场景关键文件 (0/1)
```

#### 1.2 添加场景特化数据表

```sql
-- Android 场景特化数据
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

-- Windows 场景特化数据
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

-- Linux 场景特化数据
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
```

#### 1.3 添加索引

```sql
CREATE INDEX IF NOT EXISTS idx_android_artifacts_file_id ON android_artifacts(file_id);
CREATE INDEX IF NOT EXISTS idx_android_artifacts_type ON android_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_windows_artifacts_file_id ON windows_artifacts(file_id);
CREATE INDEX IF NOT EXISTS idx_windows_artifacts_type ON windows_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_linux_artifacts_file_id ON linux_artifacts(file_id);
CREATE INDEX IF NOT EXISTS idx_linux_artifacts_type ON linux_artifacts(artifact_type);
```

#### 1.4 添加视图

```sql
-- 场景文件统计视图
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

-- 场景工件统计视图
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
    static constexpr int CRITICAL = 100;
    static constexpr int HIGH = 75;
    static constexpr int MEDIUM = 50;
    static constexpr int LOW = 25;
    static constexpr int IRRELEVANT = 0;
};
```

#### 2.2 FileClassifier 新增方法

```cpp
class FileClassifier {
public:
    void setSceneType(SceneType scene);
    SceneType getSceneType() const;
    
private:
    SceneType sceneType_ = SceneType::NONE;
    
    void markSceneFiles();
    int calculateScenePriority(const std::string& path, const std::string& filename, FileCategory category);
    bool isSceneRelevant(const std::string& path, const std::string& filename);
    
    void applyAndroidSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    void applyWindowsSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    void applyLinuxSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
    void applyServerCloudSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
};
```

#### 2.3 场景特化规则

**Android 场景关键路径：**
- `/data/data/` - 应用数据
- `/data/system/` - 系统数据
- `/data/app/` - 安装的应用
- `/system/build.prop` - 系统属性

**Windows 场景关键路径：**
- `Windows/System32/config/` - 注册表
- `Windows/System32/winevt/` - 事件日志
- `Windows/Prefetch/` - 预取文件
- `Users/*/AppData/` - 用户应用数据

**Linux 场景关键路径：**
- `/var/log/` - 系统日志
- `/etc/` - 配置文件
- `/home/` - 用户目录
- `/var/spool/cron/` - 定时任务

### 3. 管道集成

#### 3.1 AnalysisOrchestrator 修改

```cpp
int AnalysisOrchestrator::runAnalysis(const CommandLineArgs& args) {
    // Step 1: ImageAnalyzer (不变)
    // Step 2: FileFilter (不变)
    
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
        auto analyzer = std::make_unique<AndroidAnalyzer>(args.image_path, dbMgr.get());
        analyzer->setOutputDatabasePath(fileDbPath);  // 写入 files.db
        analyzer->analyzeAndroidData();
    }
    // ... Windows 和 Linux 类似 ...
    
    // Step 5: 时间线生成（导入场景工件）
    auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
    eventExtractor->extractEvents();
    eventExtractor->importSceneArtifacts(fileDbPath, "android");
    eventExtractor->importSceneArtifacts(fileDbPath, "windows");
    eventExtractor->importSceneArtifacts(fileDbPath, "linux");
}
```

#### 3.2 TaskManager 修改

```cpp
void TaskManager::start_analysis(const std::string& task_id) {
    // ... 现有步骤 ...
    
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
    
    // 场景特化分析：写入 files.db
    for (auto scenario : task.scenarios) {
        switch (scenario) {
            case ForensicScenario::ANDROID: {
                auto analyzer = std::make_unique<AndroidAnalyzer>(task.image_path, dbMgr.get());
                analyzer->setOutputDatabasePath(fileDbPath);
                analyzer->analyzeAndroidData();
                break;
            }
            // ... Windows 和 Linux 类似 ...
        }
    }
    
    // LLM 分析：使用场景优先级
    if (task.llm_analyze) {
        LLMAnalysisService llmService;
        llmService.setSceneType(sceneType);
        llmService.analyzeFiles(fileDbPath, task.llm_mode);
    }
}
```

### 4. LLM 分析优化

#### 4.1 场景优先级排序

```cpp
std::vector<FileRecord> LLMAnalysisService::getScenePrioritizedFiles(sqlite3* db, int limit) {
    std::string query;
    
    if (sceneType_ != SceneType::NONE) {
        // 场景模式：按场景优先级排序
        query = R"(
            SELECT * FROM files
            WHERE type = 'REG'
              AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)
              AND scene_priority > 0
            ORDER BY scene_priority DESC, size ASC
            LIMIT ?
        )";
    } else {
        // 非场景模式：按文件大小排序
        query = R"(
            SELECT * FROM files
            WHERE type = 'REG'
              AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0)
            ORDER BY size ASC
            LIMIT ?
        )";
    }
    
    // ... 执行查询 ...
}
```

#### 4.2 场景特定提示

```cpp
std::string LLMAnalysisService::getSceneSpecificPrompt(const FileRecord& file) {
    std::string basePrompt = "Analyze this forensic file...\n";
    
    if (sceneType_ == SceneType::ANDROID) {
        basePrompt += "\nAndroid forensic analysis. Focus on:\n"
            "- Mobile application data\n"
            "- User communications\n"
            "- App usage patterns\n";
    } else if (sceneType_ == SceneType::WINDOWS) {
        basePrompt += "\nWindows forensic analysis. Focus on:\n"
            "- Registry artifacts\n"
            "- Event logs\n"
            "- User activity\n";
    } else if (sceneType_ == SceneType::LINUX) {
        basePrompt += "\nLinux forensic analysis. Focus on:\n"
            "- System logs\n"
            "- User accounts\n"
            "- Network configuration\n";
    }
    
    return basePrompt;
}
```

### 5. API 变更

#### 5.1 新增数据类型

```cpp
struct SceneConfig {
    bool enabled = false;
    std::string sceneType;
    int priorityThreshold = 50;
    bool autoDetect = false;
    std::vector<std::string> customRules;
};
```

#### 5.2 新增 API 端点

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/tasks/{id}/scene-stats` | 获取场景统计信息 |
| GET | `/api/tasks/{id}/scene-artifacts` | 获取场景工件列表 |

#### 5.3 修改 API 端点

| 方法 | 端点 | 修改内容 |
|------|------|----------|
| POST | `/api/tasks` | 支持 `scene_config` 参数 |
| GET | `/api/tasks/{id}` | 返回场景配置信息 |

### 6. 实施计划

#### 阶段一：数据库架构扩展（1-2天）
- 修改 `file_classifier_sql.h`
- 修改 `FileClassifier`
- 数据库迁移测试

#### 阶段二：场景分析器改造（2-3天）
- 修改 `AndroidAnalysisDatabase`
- 修改 `WindowsAnalysisDatabase`
- 修改 `LinuxAnalysisDatabase`

#### 阶段三：管道集成（1-2天）
- 修改 `AnalysisOrchestrator`
- 修改 `TaskManager`
- 修改 `EventExtractor`

#### 阶段四：LLM 分析优化（1天）
- 修改 `LLMAnalysisService`
- 性能测试

#### 阶段五：API 与前端集成（1-2天）
- 修改 API 数据类型
- 添加场景查询 API
- 前端集成（可选）

**总计：6-10天**

### 7. 风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 数据库迁移失败 | 高 | 低 | 自动备份、回滚机制 |
| 场景分析器写入失败 | 高 | 低 | 兼容旧模式、错误处理 |
| LLM 分析性能提升不足 | 中 | 中 | 调整优先级阈值、优化筛选逻辑 |
| API 向后兼容性问题 | 中 | 低 | 版本控制、渐进式迁移 |

### 8. 验收标准

- [ ] `_files.db` 包含场景相关列和表
- [ ] 场景分析器可以写入 `_files.db`
- [ ] 主管道支持场景感知分类
- [ ] LLM 分析使用场景优先级
- [ ] API 支持场景配置
- [ ] 性能提升 30-70%
- [ ] 旧数据库自动迁移成功
- [ ] 向后兼容性测试通过

## 附录

### A. 参考文献

- [The Sleuth Kit Documentation](https://www.sleuthkit.org/sleuthkit/docs/)
- [SQLite Documentation](https://www.sqlite.org/docs/)
- [Crow Framework Documentation](https://crowcpp.org/)

### B. 相关文件

- `src/core/DatabaseManager/SQL/file_classifier_sql.h`
- `src/core/DatabaseManager/FileClassifier/FileClassifier.h/cpp`
- `src/AnalysisOrchestrator.cpp`
- `src/network/HTTPServer/TaskManager.cpp`
- `src/analyzers/AndroidAnalyzer/`
- `src/analyzers/WindowsFilesAnalyzer/`
- `src/analyzers/LinuxFilesAnalyzer/`
- `src/network/HTTPServer/LLMAnalysisService.h/cpp`
