# AnalysisOrchestrator - 分析编排器

> **模块定位**: 顶层工作流编排器，协调所有分析流程的执行

---

## 1. 模块概述

### 位置

`src/AnalysisOrchestrator.h`

### 设计目标

AnalysisOrchestrator 是整个取证分析工具的顶层入口，负责根据命令行参数调度不同的分析工作流。它将 `main.cpp` 的业务逻辑与命令行解析解耦。

### 架构定位

```
main.cpp
    ↓
CommandLineParser::parse()
    ↓
AnalysisOrchestrator::run*()
    ↓
┌──────────────────────────────────────┐
│  runAnalysis()      → 完整分析管道    │
│  runExtraction()    → 文件提取        │
│  runFullTextSearch() → 全文搜索       │
│  runFileCarving()   → 文件雕刻        │
│  runHTTPServer()    → HTTP 服务       │
│  runDLLAnalysis()   → DLL 分析        │
└──────────────────────────────────────┘
    ↓
核心分析引擎 (ImageAnalyzer, EventExtractor, etc.)
```

---

## 2. API 参考

### 方法列表

```cpp
namespace forensics {

class AnalysisOrchestrator {
public:
    // 完整分析管道：镜像分析 → 事件提取 → 文件分类 → 平台分析
    static int runAnalysis(const CommandLineArgs& args);

    // 文件提取：从数据库中提取文件
    static int runExtraction(const CommandLineArgs& args);

    // 全文搜索：索引或搜索文件内容
    static int runFullTextSearch(const CommandLineArgs& args);

    // 文件雕刻：从未分配空间恢复删除文件
    static int runFileCarving(const CommandLineArgs& args);

    // HTTP 服务器模式
    static int runHTTPServer(int port);

    // DLL 分析：PE/ELF 文件分析
    static int runDLLAnalysis(const CommandLineArgs& args);

private:
    // 辅助方法
    static std::string getBaseName(const std::string& path);
    static std::string getDatabaseDir(const CommandLineArgs& args);
};

} // namespace forensics
```

### 工作流说明

#### runAnalysis

完整的取证分析管道：

1. **ImageAnalyzer**: 解析磁盘镜像，提取文件元数据 → `_raw.db`
2. **EventExtractor**: 从元数据生成时间线事件 → `_events.db`
3. **FileClassifier**: 按类型分类文件（24 类分类表 + 主 files 表）→ `_files.db`
4. **平台分析**（可选）:
   - AndroidAnalyzer → `_android.db`
   - WindowsFilesAnalyzer → `_windows.db`
   - LinuxFilesAnalyzer → `_linux.db`
5. **DLL 分析**（可选）→ `_dll.db`
6. **LLM 分析**（可选）: 生成文件描述

#### runExtraction

从已分析的数据库中提取文件：
- 支持按模式、扩展名、名称提取
- 支持提取已删除文件
- 支持全量提取

#### runFullTextSearch

全文搜索操作：
- **索引模式**: 使用 Xapian 索引提取的文件
- **搜索模式**: 在已索引的内容中搜索关键词

#### runFileCarving

文件雕刻操作：
- 从磁盘镜像的未分配空间中恢复文件
- 基于文件签名（magic bytes）识别 30+ 种文件类型

#### runHTTPServer

启动 Crow HTTP 服务器，提供 REST API 接口。

#### runDLLAnalysis

DLL/共享库分析：
- PE 文件解析（Windows DLL/EXE）
- ELF 文件解析（Linux SO/可执行文件）
- 异常检测和威胁评分

---

## 3. 命令行参数

AnalysisOrchestrator 使用 `CommandLineArgs` 结构体：

```cpp
struct CommandLineArgs {
    std::string image_path;           // 磁盘镜像路径
    std::string database_path;        // 已有数据库路径
    std::string output_dir;           // 输出目录
    std::string db_dir;               // 数据库输出目录
    std::string extract_pattern;      // 提取模式
    std::string search_keyword;       // 搜索关键词
    std::string index_path;           // 索引路径
    std::string dll_db;               // DLL 数据库路径

    XFSMode xfs_mode = XFSMode::Auto; // XFS 解析模式
    int http_port = 0;                // HTTP 服务器端口
    int dll_threshold = 30;           // DLL 威胁阈值

    bool android_analyze = false;     // 启用 Android 分析
    bool windows_analyze = false;     // 启用 Windows 分析
    bool linux_analyze = false;       // 启用 Linux 分析
    bool analyze_dlls = false;        // 启用 DLL 分析
    bool analyze_dlls_only = false;   // 仅 DLL 分析
    bool carve = false;               // 启用文件雕刻
    bool show_help = false;           // 显示帮助
    bool show_version = false;        // 显示版本
    bool index_mode = false;          // 索引模式
    bool search_mode = false;         // 搜索模式
    // ... 更多参数
};
```

---

## 4. 典型调用流程

```cpp
#include "AnalysisOrchestrator.h"
#include "CommandLineParser.h"

int main(int argc, char* argv[]) {
    auto args = forensics::CommandLineParser::parse(argc, argv);

    if (args.show_help) {
        forensics::CommandLineParser::printUsage(argv[0]);
        return 0;
    }

    if (args.http_port > 0) {
        return forensics::AnalysisOrchestrator::runHTTPServer(args.http_port);
    }

    if (args.analyze_dlls_only) {
        return forensics::AnalysisOrchestrator::runDLLAnalysis(args);
    }

    if (args.search_mode || args.index_mode) {
        return forensics::AnalysisOrchestrator::runFullTextSearch(args);
    }

    if (args.carve) {
        return forensics::AnalysisOrchestrator::runFileCarving(args);
    }

    if (!args.extract_pattern.empty() || args.extract_all) {
        return forensics::AnalysisOrchestrator::runExtraction(args);
    }

    return forensics::AnalysisOrchestrator::runAnalysis(args);
}
```

---

## 相关模块

| 模块 | 说明 |
|------|------|
| [CommandLineParser](./CommandLineParser.md) | 命令行参数解析 |
| [ImageAnalyzer](../analyzers/ImageAnalyzer.md) | 磁盘镜像分析 |
| [TaskManager](../network/TaskManager.md) | HTTP 模式下的任务管理 |
