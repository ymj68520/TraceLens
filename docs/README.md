# ForensicsProject 技术文档索引

欢迎使用 **ForensicsProject** 技术文档。本索引帮助您快速找到所需的文档。

---

## 快速导航

### 🚀 新手入门
- **[快速入门指南](getting-started/QuickStart.md)** - 30 分钟完成安装和第一次分析
- **[安装指南](getting-started/Installation.md)** - 详细安装步骤和依赖配置
- **[开发环境配置](getting-started/Development.md)** - IDE 设置、调试和测试框架
- **[常见开发任务](getting-started/CommonTasks.md)** - 添加分析器、路由等开发指南
- **[故障排查](getting-started/Troubleshooting.md)** - 常见问题诊断和解决方案
- **[架构总览](architecture/Overview.md)** - 系统整体架构和技术栈
- **[C++ REST API 参考](api_reference/CPP_REST_API.md)** - C++ 服务 API（端口 8080）
- **[Python REST API 参考](api_reference/Python_REST_API.md)** - Python 服务 API（端口 8090）

### 📚 核心模块文档
- **[镜像分析器](modules/cpp/analyzers/ImageAnalyzer.md)** - 磁盘镜像分析核心
- **[数据库管理器](modules/cpp/core/DatabaseManager.md)** - SQLite 操作核心
- **[文件分类器](modules/cpp/core/FileClassifier.md)** - 13 类文件分类
- **[事件提取器](modules/cpp/core/EventExtractor.md)** - 时间线事件生成
- **[HTTP 服务器](modules/cpp/network/HTTPServer.md)** - C++ Crow HTTP 服务器
- **[任务管理器](modules/cpp/network/TaskManager.md)** - 异步任务生命周期管理
- **[Python 主程序](modules/python/httpserver/Main.md)** - FastAPI 服务架构
- **[服务管理器](modules/python/httpserver/services/ServiceManager.md)** - Python 服务协调

### 🔬 深入专题
- **[数据流架构](architecture/DataFlow.md)** - 取证分析数据流详解
- **[LLM 集成](modules/cpp/integration/LLMIntegration.md)** - OpenAI 兼容 API 客户端
- **[知识图谱集成](modules/python/graphiti_integration/GraphitiIngestor.md)** - Graphiti 数据摄取
- **[全文搜索](modules/cpp/core/FullTextSearch.md)** - Xapian 搜索引擎
- **[TOON 导出器](modules/cpp/core/TOONExporter.md)** - LLM 优化的导出格式

---

## 文档分类

### 1. 入门指南（Getting Started）

| 文档 | 描述 | 预计阅读时间 |
|------|------|-------------|
| [QuickStart.md](getting-started/QuickStart.md) | 30 分钟快速入门 | 15 分钟 |
| [Installation.md](getting-started/Installation.md) | 详细安装指南（依赖、编译、配置） | 20 分钟 |
| [Development.md](getting-started/Development.md) | 开发环境配置（IDE、调试、测试） | 25 分钟 |
| [CommonTasks.md](getting-started/CommonTasks.md) | 常见开发任务指南 | 30 分钟 |
| [Troubleshooting.md](getting-started/Troubleshooting.md) | 故障排查指南 | - |
| [faq.md](getting-started/faq.md) | 常见问题 | - |

### 2. 架构文档（Architecture）

| 文档 | 描述 | 预计阅读时间 |
|------|------|-------------|
| [Overview.md](architecture/Overview.md) | 系统整体架构 | 30 分钟 |
| [DataFlow.md](architecture/DataFlow.md) | 数据流架构 | 20 分钟 |
| [DatabaseSchema.md](architecture/DatabaseSchema.md) | 数据库模式设计（6 种数据库） | 25 分钟 |
| [Deployment.md](architecture/Deployment.md) | 部署架构、扩展性、高可用 | 20 分钟 |
| [Security.md](architecture/Security.md) | 安全设计、权限控制、审计 | 15 分钟 |

### 3. API 参考（API Reference）

| 文档 | 描述 | 端口 |
|------|------|------|
| [CPP_REST_API.md](api_reference/CPP_REST_API.md) | C++ 服务 REST API | 8080 |
| [Python_REST_API.md](api_reference/Python_REST_API.md) | Python 服务 REST API | 8090 |

### 4. C++ 模块文档（Modules/C++）

#### 4.1 分析器（Analyzers）

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [ImageAnalyzer](modules/cpp/analyzers/ImageAnalyzer.md) | 磁盘镜像分析核心引擎 | ⭐⭐⭐⭐⭐ |
| [AndroidAnalyzer](modules/cpp/analyzers/AndroidAnalyzer.md) | Android 取证分析 | ⭐⭐⭐⭐ |
| [DatabaseAnalyzer](modules/cpp/analyzers/DatabaseAnalyzer.md) | 数据库取证分析 | ⭐⭐⭐ |
| [FileCarving](modules/cpp/analyzers/FileCarving.md) | 文件恢复与雕刻 | ⭐⭐⭐⭐ |
| [LinuxFilesAnalyzer](modules/cpp/analyzers/LinuxFilesAnalyzer.md) | Linux 系统工件分析 | ⭐⭐⭐ |
| [OfficeAnalyzer](modules/cpp/analyzers/OfficeAnalyzer.md) | Office 文档解析 | ⭐⭐ |
| [OSSAnalyzer](modules/cpp/analyzers/OSSAnalyzer.md) | 阿里云 OSS 集成 | ⭐⭐ |
| [PDFAnalyzer](modules/cpp/analyzers/PDFAnalyzer.md) | PDF 元数据提取 | ⭐⭐ |
| [VisionAnalysis](modules/cpp/analyzers/VisionAnalysis.md) | 图像/视频视觉分析 | ⭐⭐⭐⭐ |
| [WindowsFilesAnalyzer](modules/cpp/analyzers/WindowsFilesAnalyzer.md) | Windows 系统工件分析 | ⭐⭐⭐⭐ |

#### 4.2 核心基础设施（Core）

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [AuditLog](modules/cpp/core/AuditLog.md) | 审计日志系统 | ⭐⭐⭐ |
| [ConfigManager](modules/cpp/core/ConfigManager.md) | 配置管理 | ⭐⭐ |
| [DatabaseManager](modules/cpp/core/DatabaseManager.md) | 数据库操作核心 | ⭐⭐⭐⭐⭐ |
| [EventExtractor](modules/cpp/core/EventExtractor.md) | 时间线事件提取 | ⭐⭐⭐⭐ |
| [FileClassifier](modules/cpp/core/FileClassifier.md) | 文件分类引擎 | ⭐⭐⭐ |
| [FileExtractor](modules/cpp/core/FileExtractor.md) | 文件内容提取 | ⭐⭐⭐ |
| [FullTextSearch](modules/cpp/core/FullTextSearch.md) | 全文搜索引擎 | ⭐⭐⭐⭐ |
| [Logger](modules/cpp/core/Logger.md) | 日志系统 | ⭐⭐ |
| [PathManager](modules/cpp/core/PathManager.md) | 路径管理 | ⭐⭐ |
| [ThreadPool](modules/cpp/core/ThreadPool.md) | 线程池 | ⭐⭐⭐ |
| [TOONExporter](modules/cpp/core/TOONExporter.md) | TOON 格式导出 | ⭐⭐⭐⭐ |

#### 4.3 网络通信（Network）

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [HTTPServer](modules/cpp/network/HTTPServer.md) | C++ HTTP 服务器核心 | ⭐⭐⭐⭐⭐ |
| [TaskManager](modules/cpp/network/TaskManager.md) | 异步任务管理 | ⭐⭐⭐⭐⭐ |
| [LLMAnalysisService](modules/cpp/network/LLMAnalysisService.md) | LLM 分析服务 | ⭐⭐⭐⭐ |
| [TaskRoutes](modules/cpp/network/routes/TaskRoutes.md) | 任务管理路由 | ⭐⭐⭐ |
| [ForensicsRoutes](modules/cpp/network/routes/ForensicsRoutes.md) | 取证分析路由 | ⭐⭐⭐⭐ |
| [SearchRoutes](modules/cpp/network/routes/SearchRoutes.md) | 搜索路由 | ⭐⭐⭐ |
| [SystemRoutes](modules/cpp/network/routes/SystemRoutes.md) | 系统路由 | ⭐⭐⭐ |
| [Swagger](modules/cpp/network/Swagger.md) | API 文档生成 | ⭐⭐ |

#### 4.4 集成模块（Integration）

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [LLMIntegration](modules/cpp/integration/LLMIntegration.md) | LLM 集成核心 | ⭐⭐⭐⭐⭐ |
| [ModelRouter](modules/cpp/integration/ModelRouter.md) | 多模型路由 | ⭐⭐⭐⭐ |
| [MCPIntegration](modules/cpp/integration/MCPIntegration.md) | MCP 协议服务 | ⭐⭐⭐⭐ |
| [AndroidAdbExtractor](modules/cpp/integration/AndroidAdbExtractor.md) | ADB 数据提取 | ⭐⭐⭐ |

### 5. Python 模块文档（Modules/Python）

#### 5.1 HTTP 服务

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [FastAPI Main](modules/python/httpserver/Main.md) | FastAPI 主程序 | ⭐⭐⭐⭐ |
| [ServiceManager](modules/python/httpserver/services/ServiceManager.md) | 服务生命周期管理 | ⭐⭐⭐⭐ |
| [CppBackendClient](modules/python/httpserver/services/CppBackendClient.md) | C++ 后端通信 | ⭐⭐⭐ |
| [Health Routes](modules/python/httpserver/routes/Health.md) | 健康检查路由 | ⭐⭐ |
| [Graphiti Routes](modules/python/httpserver/routes/Graphiti.md) | 知识图谱路由 | ⭐⭐⭐ |
| [LLM Routes](modules/python/httpserver/routes/LLM.md) | LLM 分析路由 | ⭐⭐⭐ |
| [Database Routes](modules/python/httpserver/routes/Database.md) | 数据库路由 | ⭐⭐⭐ |

#### 5.2 Graphiti 集成

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [GraphitiIngestor](modules/python/graphiti_integration/GraphitiIngestor.md) | 数据摄取引擎 | ⭐⭐⭐⭐⭐ |
| [TOONTransformer](modules/python/graphiti_integration/TOONTransformer.md) | TOON 转换器 | ⭐⭐⭐⭐ |
| [DatabaseReader](modules/python/graphiti_integration/DatabaseReader.md) | 数据库读取器 | ⭐⭐⭐ |
| [Pipeline](modules/python/graphiti_integration/Pipeline.md) | 管道编排 | ⭐⭐⭐⭐ |

#### 5.3 服务层

| 模块 | 描述 | 复杂度 |
|------|------|--------|
| [GraphitiService](modules/python/services/GraphitiService.md) | Graphiti 服务封装 | ⭐⭐⭐⭐ |
| [LLMService](modules/python/services/LLMService.md) | LLM 分析服务 | ⭐⭐⭐⭐ |

---

## 按角色查找文档

### 👨‍💻 全栈开发者

1. **环境搭建**
   - [安装指南](getting-started/Installation.md)
   - [开发环境配置](getting-started/Development.md)
   - [快速入门指南](getting-started/QuickStart.md)

2. **理解系统架构**
   - [架构总览](architecture/Overview.md)
   - [数据流架构](architecture/DataFlow.md)
   - [数据库模式](architecture/DatabaseSchema.md)

3. **C++ 开发**
   - [镜像分析器](modules/cpp/analyzers/ImageAnalyzer.md)
   - [数据库管理器](modules/cpp/core/DatabaseManager.md)
   - [HTTP 服务器](modules/cpp/network/HTTPServer.md)
   - [C++ REST API](api_reference/CPP_REST_API.md)
   - [常见开发任务](getting-started/CommonTasks.md)

4. **Python 开发**
   - [FastAPI 主程序](modules/python/httpserver/Main.md)
   - [服务管理器](modules/python/httpserver/services/ServiceManager.md)
   - [Python REST API](api_reference/Python_REST_API.md)

5. **问题排查**
   - [故障排查指南](getting-started/Troubleshooting.md)

### 🔍 取证分析师

1. **快速入门**
   - [安装指南](getting-started/Installation.md)
   - [快速入门指南](getting-started/QuickStart.md)
   - [API 使用指南](getting-started/APIUsageGuide.md)

2. **分析功能**
   - [Android 分析](modules/cpp/analyzers/AndroidAnalyzer.md)
   - [Windows 分析](modules/cpp/analyzers/WindowsFilesAnalyzer.md)
   - [Linux 分析](modules/cpp/analyzers/LinuxFilesAnalyzer.md)
   - [文件雕刻](modules/cpp/analyzers/FileCarving.md)

3. **智能分析**
   - [LLM 集成](modules/cpp/integration/LLMIntegration.md)
   - [知识图谱集成](modules/python/graphiti_integration/GraphitiIngestor.md)

### 🏗️ 系统架构师

1. **架构设计**
   - [架构总览](architecture/Overview.md)
   - [数据流架构](architecture/DataFlow.md)
   - [数据库模式](architecture/DatabaseSchema.md)
   - [部署架构](architecture/Deployment.md)
   - [安全设计](architecture/Security.md)

2. **扩展性设计**
   - [任务管理器](modules/cpp/network/TaskManager.md) - 异步任务架构
   - [服务管理器](modules/python/httpserver/services/ServiceManager.md) - 服务协调
   - [模型路由](modules/cpp/integration/ModelRouter.md) - 多模型架构

3. **安全和监控**
   - [安全设计](architecture/Security.md)
   - [审计日志](modules/cpp/core/AuditLog.md)
   - [健康检查](api_reference/CPP_REST_API.md#4-系统信息-api)

---

## 按学习路径查找文档

### 📖 初级路径（入门到实践）

1. **Day 1: 环境搭建**
   - [安装指南](getting-started/Installation.md) - 依赖安装和编译
   - [开发环境配置](getting-started/Development.md) - IDE 和工具设置
   - [快速入门指南](getting-started/QuickStart.md) - 安装和第一次分析
   - [架构总览](architecture/Overview.md) - 理解系统架构

2. **Day 2: 核心概念**
   - [数据流架构](architecture/DataFlow.md) - 理解数据流
   - [镜像分析器](modules/cpp/analyzers/ImageAnalyzer.md) - 核心分析引擎

3. **Day 3: API 使用**
   - [C++ REST API](api_reference/CPP_REST_API.md) - C++ 服务 API
   - [Python REST API](api_reference/Python_REST_API.md) - Python 服务 API

### 📕 中级路径（深入理解）

1. **Week 1: 数据库架构**
   - [数据库管理器](modules/cpp/core/DatabaseManager.md)
   - [数据库模式](architecture/DatabaseSchema.md)
   - [事件提取器](modules/cpp/core/EventExtractor.md)
   - [文件分类器](modules/cpp/core/FileClassifier.md)

2. **Week 2: 平台分析**
   - [Android 分析](modules/cpp/analyzers/AndroidAnalyzer.md)
   - [Windows 分析](modules/cpp/analyzers/WindowsFilesAnalyzer.md)
   - [Linux 分析](modules/cpp/analyzers/LinuxFilesAnalyzer.md)

3. **Week 3: 高级功能**
   - [文件雕刻](modules/cpp/analyzers/FileCarving.md)
   - [全文搜索](modules/cpp/core/FullTextSearch.md)
   - [TOON 导出](modules/cpp/core/TOONExporter.md)

### 📗 高级路径（掌握架构）

1. **Month 1: 服务架构**
   - [HTTP 服务器](modules/cpp/network/HTTPServer.md)
   - [任务管理器](modules/cpp/network/TaskManager.md)
   - [服务管理器](modules/python/httpserver/services/ServiceManager.md)

2. **Month 2: 智能分析**
   - [LLM 集成](modules/cpp/integration/LLMIntegration.md)
   - [模型路由](modules/cpp/integration/ModelRouter.md)
   - [知识图谱集成](modules/python/graphiti_integration/GraphitiIngestor.md)

3. **Month 3: 扩展开发**
   - [常见开发任务](getting-started/CommonTasks.md) - 添加分析器、路由等
   - [添加新分析器](getting-started/development.md)
   - [添加新路由](modules/cpp/network/HTTPServer.md#二次开发)
   - [扩展 Python 服务](modules/python/httpserver/Main.md#二次开发)

---

## 文档贡献

如果您发现文档错误或想要改进文档，请：

1. 在 GitHub 上提交 Issue
2. 创建 Pull Request
3. 联系维护者

---

## 文档规范

### 模块文档模板

每个模块文档应包含以下章节：

1. **模块背景** - 业务背景和技术背景
2. **模块功能** - 核心功能和边界限制
3. **模块使用的库** - 依赖库清单和架构图
4. **模块实现方式** - 核心类/函数说明和关键流程
5. **API 调用** - C++/Python/REST API 示例
6. **二次开发** - 扩展点和添加新功能的步骤
7. **其他** - 测试、配置、故障排查

### 代码示例规范

- **C++ 代码**：使用 C++20 标准，包含必要的头文件
- **Python 代码**：使用 Python 3.10+ 语法，包含类型注解
- **JSON 示例**：使用 2 空格缩进，包含注释
- **Markdown 代码块**：指定语言高亮

### 图表规范

- **流程图**：使用 Mermaid `flowchart` 语法
- **时序图**：使用 Mermaid `sequenceDiagram` 语法
- **架构图**：使用 Mermaid `graph` 语法
- **类图**：使用 Mermaid `classDiagram` 语法
- **ER 图**：使用 Mermaid `erDiagram` 语法

---

## 常用命令

### 编译项目
```bash
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

### 运行测试
```bash
cd build
ctest --output-on-failure
```

### 启动服务
```bash
# C++ 服务
./build/forensic_analyzer --http-server 8080

# Python 服务
python -m python_service.httpserver.main

# 或同时启动
./scripts/start_services.sh
```

### 分析镜像
```bash
./build/forensic_analyzer evidence.E01
```

---

## 相关资源

- **[GitHub 仓库](https://github.com/ymj68520/ForensicsProject)** - 源代码
- **[问题追踪](https://github.com/ymj68520/ForensicsProject/issues)** - Bug 报告和功能请求
- **[Wiki](https://github.com/ymj68520/ForensicsProject/wiki)** - 社区贡献的文档
- **[Discussions](https://github.com/ymj68520/ForensicsProject/discussions)** - 技术讨论

---

**文档版本**: 1.0
**最后更新**: 2026-03-11
**维护者**: ymj68520
