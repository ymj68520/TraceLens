# 数字取证分析工具 - 模块化文档索引

## 文档导航

欢迎使用 ForensicsProject 模块化技术文档。本文档集提供了项目所有 C++ 和 Python 模块的详细技术说明。

### 快速开始

如果您是第一次接触本项目，建议按以下顺序阅读：

1. **[项目概述](../CLAUDE.md)** - 了解项目整体架构和功能
2. **[核心模块文档](#c-核心模块)** - 理解数据管理核心
3. **[分析器模块文档](#c-分析器模块)** - 学习各种取证分析器
4. **[网络模块文档](#c-网络通信模块)** - 了解 HTTP 服务器架构

---

## C++ 模块文档

### 核心基础设施

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **DatabaseManager** | [📖](cpp/core/DatabaseManager.md) | ✅ 完成 | 数据库管理核心，三层数据库架构 |
| **FileClassifier** | [📖](cpp/core/FileClassifier.md) | ✅ 完成 | 文件分类引擎，24+ 种文件类别 |
| **EventExtractor** | [📖](cpp/core/EventExtractor.md) | ✅ 完成 | 时间线事件提取器 |
| **FileExtractor** | [📖](cpp/core/FileExtractor.md) | ✅ 完成 | 文件内容提取器 |
| **AuditLog** | [📖](cpp/core/AuditLog.md) | ✅ 完成 | 审计日志系统 |
| **Logger** | [📖](cpp/core/Logger.md) | ✅ 完成 | 日志系统 |
| **ConfigManager** | [📖](cpp/core/ConfigManager.md) | ✅ 完成 | 配置管理 |
| **PathManager** | [📖](cpp/core/PathManager.md) | ✅ 完成 | 路径管理 |
| **FullTextSearch** | [📖](cpp/core/FullTextSearch.md) | ✅ 完成 | 全文搜索引擎 |
| **ThreadPool** | [📖](cpp/core/ThreadPool.md) | ✅ 完成 | 线程池 |
| **TOONExporter** | [📖](cpp/core/TOONExporter.md) | ✅ 完成 | TOON 格式导出器 |

### 分析器模块

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **ImageAnalyzer** | [📖](cpp/analyzers/ImageAnalyzer.md) | ✅ 完成 | 磁盘镜像分析核心引擎 |
| **AndroidAnalyzer** | [📖](cpp/analyzers/AndroidAnalyzer.md) | ✅ 完成 | Android 取证分析 |
| **WindowsFilesAnalyzer** | [📖](cpp/analyzers/WindowsFilesAnalyzer.md) | ✅ 完成 | Windows 系统工件分析 |
| **LinuxFilesAnalyzer** | [📖](cpp/analyzers/LinuxFilesAnalyzer.md) | ✅ 完成 | Linux 系统工件分析 |
| **DatabaseAnalyzer** | [📖](cpp/analyzers/DatabaseAnalyzer.md) | ✅ 完成 | 数据库取证分析 |
| **FileCarving** | [📖](cpp/analyzers/FileCarving.md) | ✅ 完成 | 文件恢复与雕刻 |
| **PDFAnalyzer** | [📖](cpp/analyzers/PDFAnalyzer.md) | ✅ 完成 | PDF 元数据提取 |
| **OfficeAnalyzer** | [📖](cpp/analyzers/OfficeAnalyzer.md) | ✅ 完成 | Office 文档解析 |
| **VisionAnalysis** | [📖](cpp/analyzers/VisionAnalysis.md) | ✅ 完成 | 图像/视频视觉分析 |
| **OSSAnalyzer** | [📖](cpp/analyzers/OSSAnalyzer.md) | ✅ 完成 | 阿里云 OSS 集成 |
| **DLLAnalyzer** | [📖](cpp/analyzers/DLLAnalyzer.md) | ✅ 完成 | PE/ELF 文件分析、异常检测、威胁评分 |

### 网络通信模块

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **HTTPServer** | [📖](cpp/network/HTTPServer.md) | ✅ 完成 | C++ HTTP 服务器核心 |
| **TaskManager** | [📖](cpp/network/TaskManager.md) | ✅ 完成 | 异步任务管理 |
| **LLMAnalysisService** | [📖](cpp/network/LLMAnalysisService.md) | ✅ 完成 | LLM 分析服务 |
| **TaskRoutes** | [📖](cpp/network/routes/TaskRoutes.md) | ✅ 完成 | 任务管理路由，异步任务生命周期管理 |
| **ForensicsRoutes** | [📖](cpp/network/routes/ForensicsRoutes.md) | ✅ 完成 | 取证分析路由，时间线、文件、Android 分析 |
| **SearchRoutes** | [📖](cpp/network/routes/SearchRoutes.md) | ✅ 完成 | 搜索路由，Xapian 全文搜索集成 |
| **SystemRoutes** | [📖](cpp/network/routes/SystemRoutes.md) | ✅ 完成 | 系统路由，健康检查、系统监控、Kubernetes 集成 |
| **OSSRoutes** | [📖](cpp/network/routes/OSSRoutes.md) | ✅ 完成 | 阿里云 OSS 分析路由，四种数据获取模式 |
| **CaseCRUDRoutes** | [📖](cpp/network/routes/CaseCRUDRoutes.md) | ✅ 完成 | 案例管理路由 |
| **DLLAnalysisRoutes** | - | ✅ 完成 | DLL 分析路由 |
| **FilterRoutes** | - | ✅ 完成 | 文件过滤配置路由 |
| **ExportRoutes** | - | ✅ 完成 | 数据导出路由（TOON/JSON/CSV） |
| **SceneQueryRoutes** | - | ✅ 完成 | 场景查询路由 |

### 集成模块

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **ModelRouter** | [📖](cpp/integration/ModelRouter.md) | ✅ 完成 | 多模型路由，五种路由策略 |
| **LLMClient** | [📖](cpp/integration/LLMClient.md) | ✅ 完成 | OpenAI 兼容 API 客户端 |
| **FileAnalyzer** | [📖](cpp/integration/FileAnalyzer.md) | ✅ 完成 | LLM 驱动的文件分析器 |
| **MCPIntegration** | [📖](cpp/integration/MCPIntegration.md) | ✅ 完成 | MCP 协议服务器 |
| **AndroidAdbExtractor** | [📖](cpp/integration/AndroidAdbExtractor.md) | ✅ 完成 | ADB 数据提取 |

---

## Python 模块文档

### HTTP 服务

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **FastAPI Main** | [📖](python/Main.md) | ✅ 完成 | FastAPI 主程序，中间件，路由注册 |
| **ServiceManager** | [📖](python/ServiceManager.md) | ✅ 完成 | 服务生命周期管理，懒加载 |
| **CppBackendClient** | [📖](python/CppBackendClient.md) | ✅ 完成 | C++ 后端通信，HTTP 客户端 |
| **HealthRoutes** | [📖](python/httpserver/routes/Health.md) | ✅ 完成 | 健康检查路由，Kubernetes liveness/readiness probes |
| **GraphitiRoutes** | [📖](python/httpserver/routes/Graphiti.md) | ✅ 完成 | 知识图谱路由，任务级图隔离，实体关系搜索 |
| **LLMRoutes** | [📖](python/httpserver/routes/LLM.md) | ✅ 完成 | LLM 分析路由，多模态文件分析，批量处理 |
| **DatabaseRoutes** | [📖](python/httpserver/routes/Database.md) | ✅ 完成 | 数据库路由，文件/事件查询，TOON/JSON 导出 |

### Graphiti 集成

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **GraphitiIntegration** | [📖](python/graphiti/GraphitiIntegration.md) | ✅ 完成 | Graphiti 知识图谱集成综合文档 |
| **GraphitiIngestor** | [📖](python/graphiti_integration/GraphitiIngestor.md) | ✅ 完成 | 数据摄取引擎 |
| **TOONTransformer** | [📖](python/graphiti_integration/TOONTransformer.md) | ✅ 完成 | TOON 转换器 |
| **DatabaseReader** | [📖](python/graphiti_integration/DatabaseReader.md) | ✅ 完成 | 数据库读取器 |

### 服务层

| 模块 | 文档 | 状态 | 描述 |
|------|------|------|------|
| **GraphitiService** | [📖](python/services/GraphitiService.md) | ✅ 完成 | Graphiti 服务封装 |
| **LLMService** | [📖](python/services/LLMService.md) | ✅ 完成 | LLM 分析服务 |

---

## 文档状态说明

| 状态图标 | 状态名称 | 说明 |
|---------|---------|------|
| ✅ 完成 | 文档已编写完成，可供阅读 |
| 🚧 待编写 | 文档计划中，尚未开始 |
| 📝 草稿 | 文档正在编写中，内容可能不完整 |
| 🔄 更新中 | 文档正在更新，添加新内容 |

---

## 架构总览

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         数字取证分析工具                          │
│                      Digital Forensics Analyzer                 │
└─────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│  C++ 后端     │         │  Python 服务  │         │   外部服务    │
│  (端口 8080)  │         │  (端口 8090)  │         │               │
└───────────────┘         └───────────────┘         └───────────────┘
        │                           │                           │
        │                           │                           │
        ▼                           ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        分析引擎层                                │
├─────────────┬─────────────┬─────────────┬─────────────┬────────┤
│ImageAnalyzer│EventExtractor│FileClassifier│PlatformAnalyzer│ ... │
└─────────────┴─────────────┴─────────────┴─────────────┴────────┘
        │                           │
        ▼                           ▼
┌───────────────┐         ┌───────────────┐
│   _raw.db     │────────▶│  _events.db   │
│  (原始元数据) │         │  (时间线事件) │
└───────────────┘         └───────────────┘
        │                           │
        ▼                           ▼
┌───────────────┐         ┌───────────────┐
│  _files.db    │         │ _platform.db  │
│ (分类文件)    │         │ (平台数据)    │
└───────────────┘         └───────────────┘
```

### 数据流图

```
磁盘镜像
    │
    ▼
┌─────────────┐
│ImageAnalyzer│──┐
└─────────────┘  │
                 │
                 ▼
            ┌─────────┐
            │_raw.db  │
            └─────────┘
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
    ┌──────┐ ┌──────┐ ┌──────┐
    │Event │ │ File │ │File  │
    │Extra │ │Class │ |Extra │
    │ctor  │ │ifier │ |ctor  │
    └──────┘ └──────┘ └──────┘
        │        │        │
        ▼        ▼        ▼
    _events.db _files.db 提取文件
        │        │
        ▼        ▼
    ┌────────────────────┐
    │   HTTP API 层      │
    │  (C++ + Python)    │
    └────────────────────┘
```

---

## 模块依赖关系

### 核心依赖链

```
ImageAnalyzer (分析镜像)
    │
    ▼
DatabaseManager (存储元数据)
    │
    ├──▶ EventExtractor (生成时间线)
    │
    ├──▶ FileClassifier (分类文件)
    │
    ├──▶ FileExtractor (提取内容)
    │
    └──▶ PlatformAnalyzers (平台分析)
            │
            ├──▶ AndroidAnalyzer
            ├──▶ WindowsFilesAnalyzer
            └──▶ LinuxFilesAnalyzer
```

### 服务依赖链

```
HTTPServer (C++)
    │
    ├──▶ TaskManager (任务管理)
    │
    ├──▶ LLMAnalysisService (LLM 分析)
    │
    └──▶ FullTextSearch (全文搜索)

Python HTTP Server
    │
    ├──▶ GraphitiService (知识图谱)
    │
    ├──▶ LLMService (LLM 集成)
    │
    └──▶ CppBackendClient (C++ 通信)
```

---

## 文档使用指南

### 按角色阅读

**全栈开发者**（推荐全部阅读）：
1. C++ 核心模块（必读）
2. Python 服务模块（必读）
3. 网络通信模块（必读）
4. 分析器模块（选读）

**C++ 开发者**：
1. DatabaseManager（必读）
2. 核心基础设施（必读）
3. 分析器模块（选读）
4. 网络模块（选读）

**Python 开发者**：
1. FastAPI 主程序（必读）
2. 服务层模块（必读）
3. Graphiti 集成（选读）
4. C++ 后端通信（必读）

**取证分析师**：
1. ImageAnalyzer（必读）
2. 各类分析器（必读）
3. REST API 文档（必读）

### 按功能查找

**磁盘镜像分析**：
- [ImageAnalyzer](cpp/analyzers/ImageAnalyzer.md)

**数据管理**：
- [DatabaseManager](cpp/core/DatabaseManager.md)
- [FileClassifier](cpp/core/FileClassifier.md)
- [EventExtractor](cpp/core/EventExtractor.md)

**文件提取**：
- [FileExtractor](cpp/core/FileExtractor.md)
- [FileCarving](cpp/analyzers/FileCarving.md)

**平台分析**：
- [AndroidAnalyzer](cpp/analyzers/AndroidAnalyzer.md)
- [WindowsFilesAnalyzer](cpp/analyzers/WindowsFilesAnalyzer.md)
- [LinuxFilesAnalyzer](cpp/analyzers/LinuxFilesAnalyzer.md)

**HTTP 服务**：
- [HTTPServer](cpp/network/HTTPServer.md)
- [FastAPI Main](python/httpserver/Main.md)

**LLM 集成**：
- [LLMIntegration](cpp/integration/LLMIntegration.md)
- [LLMAnalysisService](cpp/network/LLMAnalysisService.md)

---

## 编写规范

### 文档模板

所有模块文档遵循统一的模板结构：

```markdown
# [模块名称] 模块文档

## 1. 模块背景
### 业务背景
### 技术背景

## 2. 模块功能
### 核心功能
### 边界与限制

## 3. 模块使用的库
### 依赖库清单
### 依赖关系图

## 4. 模块实现方式
### 架构设计
### 核心类说明
### 关键流程
### 数据结构

## 5. API 调用
### C++ API
### 命令行 API
### REST API

## 6. 二次开发
### 扩展点
### 添加新功能的步骤
### 代码示例

## 7. 其他
### 测试
### 配置
### 故障排查
### 相关模块
### 参考资源
### 变更历史
```

### 文档风格

- **语言**：中文为主，技术术语保留英文
- **视角**：20年资深全栈工程师
- **深度**：代码级详细说明
- **图表**：使用 Mermaid/PlantUML
- **示例**：完整的可运行代码

### 质量标准

- [ ] 所有章节完整
- [ ] 代码示例可运行
- [ ] Mermaid 图表正确
- [ ] 交叉引用有效
- [ ] API 签名准确
- [ ] 版本信息完整

---

## 贡献指南

### 如何贡献文档

1. **选择模块**：从待编写列表中选择模块
2. **阅读代码**：理解模块实现
3. **编写文档**：遵循模板结构
4. **代码示例**：提供可运行的示例
5. **图表绘制**：使用 Mermaid/PlantUML
6. **审核校对**：确保技术准确性

### 文档提交

```bash
# 创建文档分支
git checkout -b docs/module-name

# 编写文档
# docs/modules/cpp/analyzers/NewModule.md

# 提交更改
git add docs/modules/cpp/analyzers/NewModule.md
git commit -m "docs: 添加 NewModule 模块文档"

# 推送分支
git push origin docs/module-name

# 创建 Pull Request
```

### 文档审核

提交的文档需要经过以下审核：

1. **完整性检查**：所有章节是否齐全
2. **技术审核**：内容是否准确
3. **可读性测试**：目标读者是否易懂
4. **链接验证**：所有链接是否有效

---

## 更新日志

### 2026-06-06

- ✅ 添加 DLLAnalyzer 到分析器模块表
- ✅ 添加 OSS 路由、Filter 路由、Export 路由、SceneQuery 路由到网络模块表
- ✅ 修复重复的 SystemRoutes/OSSRoutes 条目
- ✅ 更新模块总数和最后更新日期

### 2026-03-11

- ✅ 完成 ImageAnalyzer 模块文档
- ✅ 完成 DatabaseManager 模块文档
- ✅ 完成 FileClassifier 模块文档
- ✅ 创建文档索引

---

## 联系方式

如有文档相关问题，请通过以下方式联系：

- **GitHub Issues**: [项目问题跟踪](https://github.com/your-repo/issues)
- **项目文档**: 见项目根目录 `CLAUDE.md`
- **维护团队**: ymj68520

---

**最后更新**: 2026-06-06
**文档版本**: 1.0.0
**维护者**: ymj68520
