# SQLiteHelper - SQLite 查询助手

> **模块定位**: 提供 REST API 层的数据查询方法，封装所有数据库查询逻辑

---

## 1. 模块概述

### 位置

`src/network/HTTPServer/SQLiteHelper.h`

### 设计目标

SQLiteHelper 是 C++ HTTP 服务器的数据访问层，将所有数据库查询逻辑从路由代码中分离出来。提供 30+ 个静态方法，涵盖：
- 时间线分析
- 文件分析
- Android 取证
- 统计分析
- 事件导出

所有方法返回 `nlohmann::json`，直接用于 HTTP 响应。

---

## 2. API 参考

### 时间线分析

```cpp
// 综合时间线
json timeline = SQLiteHelper::get_comprehensive_timeline(
    raw_db, events_db,
    "2024-01-01",  // start_time
    "2024-12-31",  // end_time
    1000,          // limit
    0,             // offset
    "MODIFIED",    // event_type
    true           // cluster_events
);

// 时间线详情（特定簇内的事件）
json details = SQLiteHelper::get_timeline_details(
    events_db, 3600, "MODIFIED", "/home/user",
    1000, 0, "search_term"
);

// 时间线分布统计
json distribution = SQLiteHelper::get_timeline_distribution(events_db);

// 文件活动时间线
json activity = SQLiteHelper::get_file_activity_timeline(
    raw_db, events_db, "/path/to/file", -1
);

// 可疑模式检测
json suspicious = SQLiteHelper::get_suspicious_patterns(raw_db, events_db);

// 用户活动分析
json userActivity = SQLiteHelper::get_user_activity_analysis(raw_db, events_db);

// 系统事件
json events = SQLiteHelper::get_system_events(
    events_db, "2024-01-01", "2024-12-31", 1000, 0
);

// 系统事件摘要
json summary = SQLiteHelper::get_system_event_summary(events_db);
```

### 文件分析

```cpp
// 最大文件
json largest = SQLiteHelper::get_largest_files(files_db, 50);

// 最近文件
json recent = SQLiteHelper::get_recent_files(files_db, "24");

// 可疑文件
json suspicious = SQLiteHelper::get_suspicious_files(raw_db, files_db);

// 重复文件
json duplicates = SQLiteHelper::get_duplicate_files(files_db);

// 扩展名分析
json extensions = SQLiteHelper::get_extensions_analysis(files_db);

// LLM 分析结果
json llmResults = SQLiteHelper::get_llm_results(descriptions_db);
```

### Android 取证

```cpp
json comm = SQLiteHelper::get_android_communication_summary(android_db);
json apps = SQLiteHelper::get_android_app_usage(android_db);
json device = SQLiteHelper::get_android_device_info(android_db);
json media = SQLiteHelper::get_android_media_analysis(android_db);
```

### 统计分析

```cpp
json overview = SQLiteHelper::get_overview_statistics(raw_db, files_db, events_db);
json distribution = SQLiteHelper::get_file_distribution_analysis(files_db);
json patterns = SQLiteHelper::get_activity_patterns(events_db);
json deleted = SQLiteHelper::get_deleted_files_analysis(raw_db);
```

### 增强时间线

```cpp
// 按事件类型
json byType = SQLiteHelper::get_timeline_by_type(events_db, "MODIFIED", 100);

// 按时间范围
json byTime = SQLiteHelper::get_timeline_by_time_range(events_db, start, end, 100);

// 按文件
json byFile = SQLiteHelper::get_timeline_by_file(events_db, "/path/to/file", 100);

// 完整时间线
json full = SQLiteHelper::get_timeline_full(events_db, 100, 0);

// 按时间段统计
json stats = SQLiteHelper::get_event_statistics_by_period(events_db, "day");
```

### 事件导出

```cpp
// 导出为 JSON
json result = SQLiteHelper::export_events_to_json(events_db, "/output/events.json");

// 导出为 CSV
json result = SQLiteHelper::export_events_to_csv(events_db, "/output/events.csv");

// 导出为可视化格式
json result = SQLiteHelper::export_events_for_visualization(events_db, "/output/timeline.html");
```

---

## 3. 内部辅助方法

```cpp
// 数据库操作
static sqlite3* open_database(const std::string& db_path, json& error_result);
static json execute_query(sqlite3* db, const std::string& sql);
static bool table_exists(sqlite3* db, const std::string& table_name);

// 工具方法
static std::string format_timestamp(int64_t timestamp);
static int64_t parse_timestamp(const std::string& time_str);
static bool is_suspicious_extension(const std::string& ext);
static bool is_suspicious_path(const std::string& path);
```

---

## 4. 使用模式

SQLiteHelper 的方法被路由模块直接调用：

```cpp
// 在 ForensicsRoutes.cpp 中
CROW_ROUTE(app, "/api/forensics/timeline").methods("GET"_method)(
    [&app](const crow::request& req) {
        auto task = TaskManager::instance().get_task(task_id);
        auto result = SQLiteHelper::get_comprehensive_timeline(
            task.output_raw_db, task.output_events_db,
            start_time, end_time, limit, offset
        );
        return crow::response(result.dump());
    }
);
```

---

**最后更新**: 2026-05-19
