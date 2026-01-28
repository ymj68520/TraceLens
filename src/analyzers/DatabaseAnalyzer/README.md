# DatabaseAnalyzer Module

数据库取证分析模块 - 用于对各种类型的数据库文件进行取证分析。

## 功能特性

- **多数据库支持**
  - SQLite（完整分析）
  - MySQL数据目录（元数据分析）
  - PostgreSQL数据目录（元数据分析）

- **取证功能**
  - 表结构提取
  - 记录读取
  - 删除记录恢复（SQLite）
  - WAL/日志分析
  - 用户账户提取
  - 配置文件解析

- **可扩展设计**
  - 策略模式：`IDBParser`接口
  - 工厂模式：`DBParserFactory`自动检测
  - 运行时注册新解析器

## 快速开始

```cpp
#include "DatabaseAnalyzer.h"

using namespace ForensicAnalyzer::Database;

// 创建分析器
DatabaseAnalyzer analyzer;
analyzer.initialize("/path/to/results.db");

// 分析SQLite数据库
int64_t sessionId = analyzer.analyze("/path/to/database.sqlite");

// 获取结果
auto summary = analyzer.getSessionSummary(sessionId);
auto tables = analyzer.getTables(sessionId);
auto artifacts = analyzer.getArtifacts(sessionId);
```

## 扩展新数据库类型

1. 创建新解析器类，实现`IDBParser`接口
2. 在`DBParserFactory`中注册：

```cpp
DBParserFactory::registerParser(DatabaseType::NEW_TYPE, []() {
    return std::make_unique<NewTypeAnalyzer>();
});
```

## 目录结构

```
DatabaseAnalyzer/
├── DatabaseAnalyzer.h      # 主入口
├── Common/
│   └── DBDataTypes.h       # 数据类型定义
├── Core/
│   └── DatabaseAnalyzerCore.cpp
├── Database/
│   ├── DBAnalysisDatabase.h/cpp  # 结果存储
└── Parsers/
    ├── IDBParser.h         # 解析器接口
    ├── DBParserFactory.h/cpp  # 解析器工厂
    ├── SQLiteAnalyzer.h/cpp
    ├── MySQLAnalyzer.h/cpp
    └── PostgreSQLAnalyzer.h/cpp
```
