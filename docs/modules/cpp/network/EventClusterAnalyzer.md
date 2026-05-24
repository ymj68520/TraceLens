# EventClusterAnalyzer - 事件簇分析器

> **模块定位**: 使用 LLM 对时间线事件簇进行智能分析，识别重要事件模式和生成描述

---

## 1. 模块概述

### 位置

`src/network/HTTPServer/EventClusterAnalyzer.h`

### 设计目标

时间线可能包含数万条事件，人工审查不现实。EventClusterAnalyzer 通过 LLM 自动：
- 将相似事件分组为簇
- 识别重要的事件簇
- 为每个事件簇生成人类可读的描述
- 提取关键词和摘要

---

## 2. API 参考

### 初始化

```cpp
EventClusterAnalyzer analyzer;
analyzer.initialize();
```

### 分析方法

```cpp
// 分析单个事件簇
analyzer.analyzeEventCluster(
    "/path/to/events.db",
    3600,           // 时间窗口（秒）
    "MODIFIED",     // 事件类型
    "/home/user"    // 父目录
);

// 批量分析事件簇
std::vector<std::tuple<int64_t, std::string, std::string>> clusters = {
    {3600, "MODIFIED", "/home/user"},
    {1800, "ACCESSED", "/var/log"}
};
int analyzed = analyzer.analyzeEventClusters("/path/to/events.db", clusters);

// 智能分析（自动选择重要簇）
int analyzed = analyzer.analyzeSmartEventClusters("/path/to/events.db", 50);

// 选择重要事件簇（不分析）
auto important = analyzer.selectImportantEventClusters("/path/to/events.db", 50);

// 获取所有事件簇
auto all = analyzer.getAllEventClusters("/path/to/events.db");
```

### 存储结果

```cpp
analyzer.storeClusterDescription(
    "/path/to/events.db",
    3600, "MODIFIED", "/home/user",
    "User modified multiple config files",     // 摘要
    "Between 2:00-3:00 AM, user modified...",  // 描述
    {"config", "suspicious", "night-activity"}, // 关键词
    "gpt-4",     // 使用的模型
    true         // 是否相关
);
```

---

## 3. 事件簇定义

事件簇由三个维度定义：
- **时间窗口**: 事件发生的时间范围（秒）
- **事件类型**: CREATED, MODIFIED, ACCESSED, CHANGED, DELETED
- **父目录**: 事件发生的目录路径

---

## 4. 智能分析流程

1. 从数据库获取所有事件簇
2. 构建事件簇摘要
3. 发送给 LLM，让其选择最重要的簇
4. 解析 LLM 返回的重要簇列表
5. 对每个重要簇执行详细分析
6. 将结果存储回数据库

---

## 5. REST API

通过 `EventClusterRoutes` 暴露：

```bash
# 分析所有事件簇
POST /api/event-clusters/analyze
{
    "task_id": "task_123",
    "max_clusters": 50
}

# 获取事件簇列表
GET /api/event-clusters?task_id={task_id}

# 获取事件簇详情
GET /api/event-clusters/{cluster_id}?task_id={task_id}
```

---

**最后更新**: 2026-05-19
