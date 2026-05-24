# WindowsLLMAnalysisService - Windows 取证 LLM 分析服务

> **模块定位**: 使用 LLM 分析 Windows 系统工件，为调查提供 AI 驱动的上下文理解

---

## 1. 模块概述

### 位置

`src/network/HTTPServer/WindowsLLMAnalysisService.h`

### 设计目标

WindowsLLMAnalysisService 是 Windows 取证分析的**必需步骤**。它对所有 Windows 系统工件进行 LLM 分析，生成摘要、描述和关键词。

### 支持的工件类型

| 工件类型 | 说明 |
|---------|------|
| REGISTRY | 注册表键值 |
| EVENT_LOG | Windows 事件日志 |
| PREFETCH | 预读取文件 |
| LNK | 快捷方式文件 |
| JUMP_LIST | 跳转列表 |
| BROWSER_HISTORY | 浏览器历史 |
| BROWSER_DOWNLOAD | 浏览器下载 |
| BROWSER_BOOKMARK | 浏览器书签 |
| BROWSER_LOGIN | 浏览器登录信息 |
| MFT_ENTRY | MFT 条目 |
| WINDOWS_SERVICE | Windows 服务 |
| SCHEDULED_TASK | 计划任务 |
| AMCACHE | Amcache 工件 |
| SRUM | SRUM 数据 |

---

## 2. 数据结构

### AnalysisOptions

```cpp
struct AnalysisOptions {
    size_t maxArtifacts = 1000;      // 每种类型最大分析数
    bool includeRegistry = true;
    bool includeEventLogs = true;
    bool includePrefetch = true;
    bool includeLnk = true;
    bool includeJumpLists = true;
    bool includeBrowser = true;
    bool includeSystem = true;       // 服务/计划任务/Amcache/SRUM
    bool includeMFT = false;         // MFT 条目（可能非常大）
};
```

---

## 3. API 参考

### 初始化

```cpp
WindowsLLMAnalysisService service;
service.initialize();
```

### 分析所有工件

```cpp
WindowsLLMAnalysisService::AnalysisOptions options;
options.maxArtifacts = 500;
options.includeRegistry = true;
options.includeEventLogs = true;

int analyzed = service.analyzeWindowsArtifacts(
    "/output/windows.db",
    options,
    [](const std::string& type, int current, int total, const std::string& details) {
        std::cout << "[" << type << "] " << current << "/" << total << ": " << details << std::endl;
    }
);
```

### 分析特定类型

```cpp
int analyzed = service.analyzeArtifactType(
    "/output/windows.db",
    WindowsLLMAnalysisService::ArtifactType::REGISTRY,
    100,  // 最大数量
    progressCallback
);
```

---

## 4. 分析流程

1. 从 `_windows.db` 读取工件记录
2. 将工件数据格式化为 LLM 可理解的文本
3. 调用 LLM 生成分析结果
4. 将结果写回数据库

每种工件类型有专门的分析方法：
- `analyzeRegistryArtifact()` - 注册表
- `analyzeEventLogArtifact()` - 事件日志
- `analyzePrefetchArtifact()` - 预读取
- `analyzeLnkArtifact()` - 快捷方式
- `analyzeJumpListArtifact()` - 跳转列表
- `analyzeBrowserArtifact()` - 浏览器
- `analyzeSystemArtifact()` - 服务/计划任务
- `analyzeMftArtifact()` - MFT

---

## 5. 使用场景

- **入侵调查**: 分析事件日志、注册表自启动项、计划任务
- **用户行为分析**: 分析浏览器历史、跳转列表、最近文件
- **恶意软件分析**: 分析预读取文件、服务、Amcache
- **数据恢复**: 分析 MFT 条目，恢复已删除文件信息

---

## 相关模块

| 模块 | 说明 |
|------|------|
| [WindowsFilesAnalyzer](../analyzers/WindowsFilesAnalyzer.md) | Windows 工件提取 |
| [LinuxLLMAnalysisService](./LinuxLLMAnalysisService.md) | Linux 平台对应模块 |
| [LLMAnalysisService](./LLMAnalysisService.md) | 文件级 LLM 分析 |
