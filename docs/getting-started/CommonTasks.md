# 常见开发任务

本文档提供 ForensicsProject 的常见开发任务指南，帮助开发者快速上手。

---

## 1. 添加新的文件分类

### 1.1 添加新分类

```cpp
// src/core/DatabaseManager/FileClassifier/FileClassifier.h

enum class FileCategory {
    IMAGES,
    VIDEOS,
    DOCUMENTS,
    // ... 现有分类
    VIRTUAL_MACHINE,  // 新增分类
    UNKNOWN
};
```

### 1.2 注册文件扩展名

```cpp
// src/core/DatabaseManager/FileClassifier/FileClassifier.cpp

void FileClassifier::initializeExtensionMaps() {
    // ... 现有映射

    // 虚拟机文件扩展名
    extensionToCategory_[".vmdk"] = FileCategory::VIRTUAL_MACHINE;
    extensionToCategory_[".vhd"] = FileCategory::VIRTUAL_MACHINE;
    extensionToCategory_[".qcow2"] = FileCategory::VIRTUAL_MACHINE;
    extensionToCategory_[".vdi"] = FileCategory::VIRTUAL_MACHINE;
}
```

### 1.3 更新数据库模式

```sql
-- src/core/DatabaseManager/SQL/file_classifier_sql.h

const char* CREATE_VIRTUAL_MACHINE_TABLE = R"(
CREATE TABLE IF NOT EXISTS virtual_machine_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inode INTEGER,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER,
    extension TEXT,
    created_time INTEGER,
    modified_time INTEGER,
    accessed_time INTEGER,
    llm_summary TEXT,
    llm_description TEXT,
    llm_keywords TEXT,
    llm_analyzed_at INTEGER,
    llm_model_used TEXT
);

CREATE INDEX IF NOT EXISTS idx_vm_files_path ON virtual_machine_files(path);
CREATE INDEX IF NOT EXISTS idx_vm_files_extension ON virtual_machine_files(extension);
)";
```

### 1.4 更新视图

```sql
const char* CREATE_FILE_SUMMARY_VIEW = R"(
CREATE VIEW IF NOT EXISTS file_summary AS
    SELECT id, name, path, size, extension, 'image' AS category FROM images
    UNION ALL
    SELECT id, name, path, size, extension, 'video' AS category FROM videos
    -- ... 其他分类
    UNION ALL
    SELECT id, name, path, size, extension, 'virtual_machine' AS category FROM virtual_machine_files
)";
```

### 1.5 测试新分类

```cpp
// tests/UnitTest/test_file_classifier.cpp

TEST_F(FileClassifierTest, ClassifyVirtualMachineFiles) {
    EXPECT_EQ(classifier_.classifyByExtension("test.vmdk"), FileCategory::VIRTUAL_MACHINE);
    EXPECT_EQ(classifier_.classifyByExtension("test.qcow2"), FileCategory::VIRTUAL_MACHINE);
}
```

---

## 2. 添加新的分析器

### 2.1 创建分析器目录结构

```bash
mkdir -p src/analyzers/NewAnalyzer/{Core,Database}
touch src/analyzers/NewAnalyzer/NewAnalyzerCore.h
touch src/analyzers/NewAnalyzer/NewAnalyzerCore.cpp
touch src/analyzers/NewAnalyzer/Database/NewAnalyzerDatabase.h
touch src/analyzers/NewAnalyzer/Database/NewAnalyzerDatabase.cpp
touch src/analyzers/NewAnalyzer/README.md
```

### 2.2 实现核心分析器

```cpp
// src/analyzers/NewAnalyzer/NewAnalyzerCore.h

#pragma once

#include <string>
#include <vector>
#include <memory>
#include "DatabaseManager/DatabaseManager.h"

class NewAnalyzerCore {
public:
    explicit NewAnalyzerCore(DatabaseManager* dbManager);
    ~NewAnalyzerCore() = default;

    /**
     * @brief 分析目标并提取数据
     * @param targetPath 目标路径
     * @return true 分析成功，false 分析失败
     */
    bool analyze(const std::string& targetPath);

    /**
     * @brief 获取分析结果统计
     */
    struct AnalysisStats {
        int totalItems = 0;
        int processedItems = 0;
        int failedItems = 0;
    };
    AnalysisStats getStats() const;

private:
    DatabaseManager* dbManager_;
    AnalysisStats stats_;

    bool extractData(const std::string& targetPath);
    bool saveToDatabase(const std::vector<DataItem>& items);
};
```

```cpp
// src/analyzers/NewAnalyzer/NewAnalyzerCore.cpp

#include "NewAnalyzerCore.h"
#include "Logger/Logger.h"
#include <fstream>

NewAnalyzerCore::NewAnalyzerCore(DatabaseManager* dbManager)
    : dbManager_(dbManager) {}

bool NewAnalyzerCore::analyze(const std::string& targetPath) {
    LOG_INFO("开始分析: " + targetPath);

    if (!extractData(targetPath)) {
        LOG_ERROR("数据提取失败");
        return false;
    }

    LOG_INFO("分析完成，处理项目数: " + std::to_string(stats_.processedItems));
    return true;
}

bool NewAnalyzerCore::extractData(const std::string& targetPath) {
    // 实现具体的数据提取逻辑
    // ...

    return true;
}

NewAnalyzerCore::AnalysisStats NewAnalyzerCore::getStats() const {
    return stats_;
}
```

### 2.3 实现数据库接口

```cpp
// src/analyzers/NewAnalyzer/Database/NewAnalyzerDatabase.h

#pragma once

#include <string>
#include <vector>
#include "DatabaseManager/DatabaseManager.h"

struct DataItem {
    std::string name;
    std::string value;
    long timestamp;
};

class NewAnalyzerDatabase {
public:
    explicit NewAnalyzerDatabase(DatabaseManager* dbManager);
    ~NewAnalyzerDatabase() = default;

    bool createTables();
    bool insertItem(const DataItem& item);
    bool insertItems(const std::vector<DataItem>& items);
    std::vector<DataItem> queryItems(const std::string& whereClause = "");

private:
    DatabaseManager* dbManager_;
};
```

### 2.4 定义数据库模式

```cpp
// src/analyzers/NewAnalyzer/Database/NewAnalyzerDatabase.cpp

#include "NewAnalyzerDatabase.h"
#include "Logger/Logger.h"

bool NewAnalyzerDatabase::createTables() {
    const char* createSQL = R"(
        CREATE TABLE IF NOT EXISTS new_analyzer_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            value TEXT,
            timestamp INTEGER,
            created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
        );
        CREATE INDEX IF NOT EXISTS idx_new_analyzer_timestamp
            ON new_analyzer_data(timestamp);
    )";

    return dbManager_->executeSQL(createSQL);
}

bool NewAnalyzerDatabase::insertItem(const DataItem& item) {
    const char* insertSQL =
        "INSERT INTO new_analyzer_data (name, value, timestamp) VALUES (?, ?, ?)";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDatabase(), insertSQL, -1, &stmt, nullptr) != SQLITE_OK) {
        LOG_ERROR("Failed to prepare insert statement");
        return false;
    }

    sqlite3_bind_text(stmt, 1, item.name.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, item.value.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, item.timestamp);

    bool result = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    return result;
}
```

### 2.5 更新 CMakeLists.txt

```cmake
# src/analyzers/CMakeLists.txt

# 添加新分析器库
add_library(new_analyzer STATIC
    NewAnalyzer/NewAnalyzerCore.cpp
    NewAnalyzer/Database/NewAnalyzerDatabase.cpp
)

target_include_directories(new_analyzer PUBLIC
    ${CMAKE_SOURCE_DIR}/src
    ${CMAKE_SOURCE_DIR}/libs
)

target_link_libraries(new_analyzer PUBLIC
    database_manager
    logger
    ${SQLITE3_LIBRARIES}
)
```

### 2.6 集成到主程序

```cpp
// src/main.cpp

#include "analyzers/NewAnalyzer/NewAnalyzerCore.h"

int main(int argc, char* argv[]) {
    // ... 现有代码

    // 添加新分析器选项
    if (parser.exists("new-analyze")) {
        std::string target = parser.get<std::string>("target");

        NewAnalyzerCore newAnalyzer(&dbManager);
        if (!newAnalyzer.analyze(target)) {
            LOG_ERROR("新分析器分析失败");
            return 1;
        }

        LOG_INFO("新分析器分析完成");
        return 0;
    }
}
```

### 2.7 添加单元测试

```cpp
// tests/UnitTest/test_new_analyzer.cpp

#include <gtest/gtest.h>
#include "analyzers/NewAnalyzer/NewAnalyzerCore.h"

class NewAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbManager = std::make_unique<DatabaseManager>();
        dbManager->open(":memory:");
    }

    void TearDown() override {
        dbManager->close();
    }

    std::unique_ptr<DatabaseManager> dbManager;
};

TEST_F(NewAnalyzerTest, AnalyzeValidTarget) {
    NewAnalyzerCore analyzer(dbManager.get());
    bool result = analyzer.analyze("tests/fixtures/test_target");

    EXPECT_TRUE(result);
    EXPECT_GT(analyzer.getStats().processedItems, 0);
}
```

---

## 3. 添加 REST API 端点

### 3.1 C++ 服务端点

#### 创建路由处理器

```cpp
// src/network/HTTPServer/routes/NewRoutes.cpp

#include "NewRoutes.h"
#include "HTTPServer/HTTPServer.h"
#include "Logger/Logger.h"
#include <crow/json.h>

void NewRoutes::registerRoutes(crow::SimpleApp& app) {
    // GET /api/new/items - 获取所有项目
    CROW_ROUTE(app, "/api/new/items").methods("GET"_method)(
        [](const crow::request& req) {
            try {
                // 查询参数
                int limit = 100;
                int offset = 0;

                std::string limitStr = req.url_params.get("limit");
                std::string offsetStr = req.url_params.get("offset");

                if (!limitStr.empty()) limit = std::stoi(limitStr);
                if (!offsetStr.empty()) offset = std::stoi(offsetStr);

                // 业务逻辑
                auto items = getItems(limit, offset);

                // 构建响应
                crow::json::wvalue response;
                response["status"] = "success";
                response["data"] = crow::json::wvalue::list();

                int index = 0;
                for (const auto& item : items) {
                    response["data"][index]["id"] = item.id;
                    response["data"][index]["name"] = item.name;
                    response["data"][index]["value"] = item.value;
                    index++;
                }

                return crow::response(200, response);

            } catch (const std::exception& e) {
                LOG_ERROR("Error in GET /api/new/items: " + std::string(e.what()));
                crow::json::wvalue error;
                error["status"] = "error";
                error["message"] = e.what();
                return crow::response(500, error);
            }
        }
    );

    // POST /api/new/items - 创建新项目
    CROW_ROUTE(app, "/api/new/items").methods("POST"_method)(
        [](const crow::request& req) {
            try {
                // 解析请求体
                auto body = crow::json::load(req.body);
                if (!body) {
                    crow::json::wvalue error;
                    error["status"] = "error";
                    error["message"] = "Invalid JSON";
                    return crow::response(400, error);
                }

                // 提取数据
                std::string name = body["name"].s();
                std::string value = body["value"].s();

                // 创建项目
                auto item = createItem(name, value);

                // 返回响应
                crow::json::wvalue response;
                response["status"] = "success";
                response["data"]["id"] = item.id;
                response["data"]["name"] = item.name;

                return crow::response(201, response);

            } catch (const std::exception& e) {
                LOG_ERROR("Error in POST /api/new/items: " + std::string(e.what()));
                crow::json::wvalue error;
                error["status"] = "error";
                error["message"] = e.what();
                return crow::response(500, error);
            }
        }
    );

    // GET /api/new/items/<id> - 获取单个项目
    CROW_ROUTE(app, "/api/new/items/<int>").methods("GET"_method)(
        [](const crow::request& req, int id) {
            auto item = getItemById(id);

            if (!item) {
                crow::json::wvalue error;
                error["status"] = "error";
                error["message"] = "Item not found";
                return crow::response(404, error);
            }

            crow::json::wvalue response;
            response["status"] = "success";
            response["data"]["id"] = item->id;
            response["data"]["name"] = item->name;
            response["data"]["value"] = item->value;

            return crow::response(200, response);
        }
    );
}
```

#### 注册路由

```cpp
// src/network/HTTPServer/HTTPServer.cpp

#include "routes/NewRoutes.h"

void HTTPServer::run() {
    // ... 现有路由

    // 注册新路由
    NewRoutes newRoutes;
    newRoutes.registerRoutes(app_);

    // ... 启动服务器
}
```

### 3.2 Python 服务端点

#### 创建路由文件

```python
# python_service/httpserver/routes/new_feature.py

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

router = APIRouter(
    prefix="/api/new",
    tags=["new_feature"]
)

# 请求/响应模型
class ItemCreate(BaseModel):
    name: str = Field(..., description="项目名称")
    value: str = Field(..., description="项目值")

class ItemResponse(BaseModel):
    id: int
    name: str
    value: str
    created_at: datetime

class ItemsListResponse(BaseModel):
    status: str = "success"
    data: List[ItemResponse]
    total: int

# 路由处理器
@router.get("/items", response_model=ItemsListResponse)
async def get_items(
    limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """获取项目列表"""
    try:
        # 业务逻辑
        items = await fetch_items(limit, offset)

        return ItemsListResponse(
            status="success",
            data=items,
            total=len(items)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(item: ItemCreate):
    """创建新项目"""
    try:
        new_item = await insert_item(item.name, item.value)
        return new_item
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int):
    """获取单个项目"""
    item = await fetch_item_by_id(item_id)

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return item
```

#### 注册路由

```python
# python_service/httpserver/main.py

from routes import new_feature

def _register_routes(app: FastAPI):
    # ... 现有路由
    app.include_router(new_feature.router)
```

---

## 4. 添加 LLM 分析功能

### 4.1 定义分析提示词

```cpp
// src/integration/LLMIntegration/LLMClient.cpp

std::string FileAnalyzer::buildPrompt(const std::string& content) {
    return R"(
你是一个数字取证分析专家。请分析以下文件内容并提供：

1. **摘要（summary）**: 1-2 句话概括文件主要内容和目的
2. **详细描述（description）**: 详细分析文件结构、关键信息、潜在证据价值
3. **关键词（keywords）**: 提取 5-10 个重要关键词，用逗号分隔

文件内容：
)" + content;
}
```

### 4.2 调用 LLM API

```cpp
LLMResponse FileAnalyzer::analyze(const std::string& filePath) {
    // 读取文件内容
    std::string content = readFileContent(filePath);

    // 构建提示词
    std::string prompt = buildPrompt(content);

    // 调用 LLM
    LLMClient client(config_);
    LLMResponse response = client.complete(prompt);

    // 解析响应
    return parseAnalysisResponse(response);
}
```

### 4.3 保存分析结果

```cpp
void FileAnalyzer::saveAnalysisResult(int fileId, const LLMResponse& analysis) {
    const char* updateSQL = R"(
        UPDATE files SET
            llm_summary = ?,
            llm_description = ?,
            llm_keywords = ?,
            llm_analyzed_at = ?,
            llm_model_used = ?
        WHERE id = ?
    )";

    sqlite3_stmt* stmt;
    sqlite3_prepare_v2(db_->getDatabase(), updateSQL, -1, &stmt, nullptr);

    sqlite3_bind_text(stmt, 1, analysis.summary.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, analysis.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, analysis.keywords.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, getCurrentTimestamp());
    sqlite3_bind_text(stmt, 5, config_.model.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, fileId);

    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
}
```

---

## 5. 扩展知识图谱集成

### 5.1 添加新实体类型

```python
# python_service/graphiti_integration/entities.py

from pydantic import BaseModel
from datetime import datetime

class NetworkConnection(BaseModel):
    """网络连接实体"""
    ip_address: str
    port: int
    protocol: str
    timestamp: datetime
    source_file: Optional[str] = None

class ProcessExecution(BaseModel):
    """进程执行实体"""
    process_name: str
    pid: int
    command_line: str
    user: str
    start_time: datetime
    end_time: Optional[datetime] = None
```

### 5.2 定义实体关系

```python
# python_service/graphiti_integration/relationships.py

class FileAccessed:
    """文件访问关系"""
    source: str  # 进程 ID
    target: str  # 文件路径
    timestamp: datetime
    access_type: str  # read/write/delete

class ProcessConnected:
    """网络连接关系"""
    source: str  # 进程 ID
    target: str  # IP:Port
    timestamp: datetime
    bytes_sent: int
    bytes_received: int
```

### 5.3 摄取到 Graphiti

```python
# python_service/graphiti_integration/pipeline.py

async def ingest_network_connections(
    self,
    connections: List[NetworkConnection]
) -> Dict[str, int]:
    """摄取网络连接数据到知识图谱"""

    stats = {"created": 0, "failed": 0}

    for conn in connections:
        try:
            # 创建实体
            entity = await self.graphiti_client.create_entity(
                name=f"{conn.ip_address}:{conn.port}",
                entity_type="NetworkConnection",
                attributes={
                    "ip_address": conn.ip_address,
                    "port": conn.port,
                    "protocol": conn.protocol,
                    "timestamp": conn.timestamp.isoformat()
                }
            )

            # 创建关系
            if conn.source_file:
                await self.graphiti_client.create_relationship(
                    source_entity_name=conn.source_file,
                    target_entity_name=entity.name,
                    relationship_type="CONNECTED_TO",
                    attributes={"timestamp": conn.timestamp.isoformat()}
                )

            stats["created"] += 1

        except Exception as e:
            LOG_ERROR(f"Failed to ingest connection: {e}")
            stats["failed"] += 1

    return stats
```

---

## 6. 添加数据库迁移

### 6.1 创建迁移脚本

```cpp
// src/core/DatabaseManager/migrations/001_add_new_column.cpp

bool migrate_add_new_column(DatabaseManager* db) {
    const char* migrationSQL = R"(
        ALTER TABLE files ADD COLUMN new_field TEXT;
        CREATE INDEX IF NOT EXISTS idx_files_new_field
            ON files(new_field);
    )";

    return db->executeSQL(migrationSQL);
}
```

### 6.2 注册迁移

```cpp
// src/core/DatabaseManager/DatabaseManager.cpp

bool DatabaseManager::runMigrations() {
    int currentVersion = getSchemaVersion();

    if (currentVersion < 1) {
        LOG_INFO("Running migration 001: Add new column");
        if (!migrate_add_new_column(this)) {
            LOG_ERROR("Migration 001 failed");
            return false;
        }
        setSchemaVersion(1);
    }

    // 后续迁移...
    return true;
}
```

---

## 7. 添加配置选项

### 7.1 定义配置项

```cpp
// src/core/ConfigManager/ConfigManager.h

class ConfigManager {
public:
    struct Config {
        // LLM 配置
        std::string llmBaseUrl = "http://localhost:1234";
        std::string llmModel = "llama-3.2-3b";
        int llmMaxTokens = 4096;

        // 新增配置项
        int maxConcurrentTasks = 4;
        bool enableCache = true;
        std::string cachePath = "/tmp/forensics_cache";
    };

    static ConfigManager& instance();
    bool load(const std::string& filePath);
    const Config& getConfig() const;

private:
    Config config_;
};
```

### 7.2 从环境变量加载

```cpp
bool ConfigManager::loadFromEnv() {
    // LLM 配置
    if (const char* env = std::getenv("LLM_BASE_URL")) {
        config_.llmBaseUrl = env;
    }
    if (const char* env = std::getenv("LLM_MODEL")) {
        config_.llmModel = env;
    }

    // 新增配置
    if (const char* env = std::getenv("MAX_CONCURRENT_TASKS")) {
        config_.maxConcurrentTasks = std::stoi(env);
    }
    if (const char* env = std::getenv("ENABLE_CACHE")) {
        config_.enableCache = (std::string(env) == "true");
    }

    return true;
}
```

### 7.3 更新 .env.example

```env
# 新增配置项
MAX_CONCURRENT_TASKS=4
ENABLE_CACHE=true
CACHE_PATH=/tmp/forensics_cache
```

---

## 8. 添加单元测试

### 8.1 C++ 测试

```cpp
// tests/UnitTest/test_new_feature.cpp

#include <gtest/gtest.h>
#include "path/to/NewFeature.h"

class NewFeatureTest : public ::testing::Test {
protected:
    void SetUp() override {
        feature = std::make_unique<NewFeature>();
    }

    void TearDown() override {
        feature.reset();
    }

    std::unique_ptr<NewFeature> feature;
};

TEST_F(NewFeatureTest, BasicOperation) {
    // Arrange
    std::string input = "test";

    // Act
    auto result = feature->process(input);

    // Assert
    EXPECT_EQ(result, "expected_output");
}

TEST_F(NewFeatureTest, EdgeCaseHandling) {
    EXPECT_THROW(feature->process(""), std::invalid_argument);
}
```

### 8.2 Python 测试

```python
# tests/test_new_feature.py

import pytest
from httpserver.services.new_feature import NewFeatureService

@pytest.fixture
def service():
    return NewFeatureService()

def test_basic_operation(service):
    """测试基本操作"""
    result = service.process("test")
    assert result == "expected_output"

def test_edge_case(service):
    """测试边界情况"""
    with pytest.raises(ValueError):
        service.process("")

@pytest.mark.asyncio
async def test_async_operation(service):
    """测试异步操作"""
    result = await service.async_process("test")
    assert result is not None
```

---

## 9. 更新文档

### 9.1 更新 API 文档

```markdown
<!-- docs/api_reference/CPP_REST_API.md -->

## 新功能 API

### GET /api/new/items

获取所有项目。

**请求参数**：
- `limit` (可选): 返回数量限制，默认 100
- `offset` (可选): 偏移量，默认 0

**响应示例**：
\`\`\`json
{
  "status": "success",
  "data": [
    {
      "id": 1,
      "name": "Item 1",
      "value": "Value 1"
    }
  ]
}
\`\`\`
```

### 9.2 更新 CHANGELOG

```markdown
# Changelog

## [Unreleased]

### Added
- 新增虚拟机文件分类支持 (.vmdk, .vhd, .qcow2)
- 添加新的分析器用于分析 XYZ 格式
- 新增 `/api/new/items` REST 端点

### Changed
- 改进 LLM 分析性能

### Fixed
- 修复文件分类器对某些扩展名的处理错误
```

---

## 10. 代码审查检查清单

在提交 Pull Request 前，确保：

- [ ] 代码符合项目风格指南（通过 clang-format/black 检查）
- [ ] 添加了单元测试且测试通过
- [ ] 更新了相关文档（API 文档、README）
- [ ] 没有编译警告（`-Wall -Wextra`）
- [ ] 没有内存泄漏（Valgrind 检查）
- [ ] 更新了 CHANGELOG.md
- [ ] 提交信息符合 Conventional Commits 规范
- [ ] 代码审查已通过

---

## 相关文档

- **[架构总览](../architecture/Overview.md)** - 系统架构
- **[开发环境配置](Development.md)** - IDE 和工具设置
- **[安装指南](Installation.md)** - 依赖和编译
- **[API 参考](../api_reference/CPP_REST_API.md)** - REST API 文档

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
