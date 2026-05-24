# DLLAnalyzer - DLL/共享库分析模块

> **模块定位**: 分析 Windows PE (DLL/EXE) 和 Linux ELF (SO) 可执行文件，提供 PE 头解析、异常检测、依赖分析、威胁评分和数字签名验证

---

## 1. 模块背景

### 业务背景

在数字取证调查中，可执行文件和共享库是关键的分析目标：

- **恶意软件检测**: 识别可疑的 DLL/SO 文件，检测异常的导入表、节属性和代码特征
- **供应链分析**: 追踪 DLL 依赖关系，识别被篡改的系统库
- **数字签名验证**: 验证可执行文件的签名状态，发现未签名或签名异常的文件
- **威胁评分**: 基于多维度特征自动计算威胁分数，辅助调查优先级排序

### 技术背景

DLLAnalyzer 位于 `src/analyzers/DLLAnalyzer/`，采用模块化架构：

| 组件 | 职责 |
|------|------|
| `DLLAnalyzer` | 主协调器，管理分析流程 |
| `PEAnalyzer` | PE 文件解析（DLL/EXE） |
| `PEParser` | PE 头部详细解析 |
| `PEImportExportParser` | 导入/导出表解析 |
| `ELFParser` | ELF 文件解析（SO/可执行文件） |
| `AnomalyDetector` | 异常检测引擎 |
| `DependencyAnalyzer` | 依赖关系分析 |
| `SignatureVerifier` | 数字签名验证 |
| `DLLAnalysisDatabase` | 结果持久化到 `_dll.db` |

---

## 2. 模块功能

### 核心功能

#### 2.1 完整分析流程

```cpp
DLLAnalyzer analyzer("/output/disk_dll.db");
analyzer.initialize();
analyzer.enableAnomalyDetection(true);
analyzer.enableSignatureVerification(true);
analyzer.analyze();
```

分析流程：
1. 扫描磁盘镜像中的 DLL/EXE/SO 文件
2. 对每个文件进行 PE/ELF 头解析
3. 计算哈希（MD5/SHA1/SHA256/ImpHash）
4. 执行异常检测
5. 分析依赖关系
6. 存储结果到 `_dll.db`

#### 2.2 单文件分析

```cpp
analyzer.analyzeSingleFile("/path/to/suspicious.dll", inode_number);
```

#### 2.3 威胁评分

威胁评分范围 0-100，基于以下因素：
- 未签名文件 (+20)
- 可疑节属性（可写+可执行）(+15)
- 异常导入表 (+10)
- 可疑文件名/路径 (+10)
- 高熵节（可能加壳）(+10)
- 已知恶意哈希 (+35)

#### 2.4 异常检测

检测的异常类型包括：
- **节属性异常**: 同时具有写和执行权限的节
- **入口点异常**: 入口点位于非代码节
- **时间戳异常**: 未来时间戳或明显异常的时间戳
- **大小异常**: 节虚拟大小与原始数据大小差异过大
- **导入异常**: 导入已知的恶意 API 组合
- **加壳检测**: 高熵值节、异常的节名

#### 2.5 依赖分析

```cpp
// 获取 DLL 的依赖树
auto deps = analyzer.getDatabase()->getDependencies(dllId);
```

支持递归依赖分析，构建完整的依赖关系图。

### 数据结构

#### DLLAnalysisResult

```cpp
struct DLLAnalysisResult {
    // 文件信息
    int64_t inode;
    std::string filePath;
    std::string fileName;
    uint64_t fileSize;

    // PE 信息
    PEHeaderInfo peHeader;

    // 导入/导出
    std::vector<ImportedDLL> imports;
    std::vector<ExportedFunction> exports;

    // 哈希
    std::string md5Hash;
    std::string sha1Hash;
    std::string sha256Hash;
    std::string impHash;

    // 版本信息
    std::string fileVersion;
    std::string productVersion;
    std::string companyName;

    // 数字签名
    std::string signatureStatus;  // "Signed", "Unsigned", "Invalid"
    std::string signerName;

    // 异常检测
    std::vector<Anomaly> anomalies;
    int threatScore;  // 0-100
};
```

#### Anomaly

```cpp
struct Anomaly {
    std::string type;         // 异常类型
    std::string description;  // 详细描述
    RiskLevel risk;           // LOW, MEDIUM, HIGH, CRITICAL
    int riskScore;            // 0-100
};
```

### 数据库 Schema

分析结果存储在 `_dll.db` 中：

```sql
-- DLL 基础信息
CREATE TABLE dll_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inode INTEGER,
    file_path TEXT,
    file_name TEXT,
    file_size INTEGER,
    md5_hash TEXT,
    sha1_hash TEXT,
    sha256_hash TEXT,
    imp_hash TEXT,
    is_dll BOOLEAN,
    machine_type TEXT,
    timestamp INTEGER,
    threat_score INTEGER,
    signature_status TEXT,
    signer_name TEXT,
    file_version TEXT,
    product_version TEXT,
    company_name TEXT,
    llm_summary TEXT,
    llm_description TEXT,
    llm_keywords TEXT
);

-- 节表
CREATE TABLE dll_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER REFERENCES dll_analysis(id),
    name TEXT,
    virtual_address INTEGER,
    virtual_size INTEGER,
    raw_data_size INTEGER,
    characteristics INTEGER,
    entropy REAL
);

-- 导入表
CREATE TABLE dll_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER REFERENCES dll_analysis(id),
    library_name TEXT,
    function_name TEXT,
    is_delayed BOOLEAN
);

-- 导出表
CREATE TABLE dll_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER REFERENCES dll_analysis(id),
    function_name TEXT,
    ordinal INTEGER,
    rva INTEGER
);

-- 异常检测结果
CREATE TABLE dll_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER REFERENCES dll_analysis(id),
    anomaly_type TEXT,
    description TEXT,
    risk_level TEXT,
    risk_score INTEGER
);

-- 依赖关系
CREATE TABLE dll_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES dll_analysis(id),
    child_id INTEGER REFERENCES dll_analysis(id),
    depth INTEGER
);

-- 取证关联
CREATE TABLE dll_forensic_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dll_id INTEGER REFERENCES dll_analysis(id),
    link_type TEXT,
    source_id TEXT,
    source_data TEXT
);
```

---

## 3. 配置选项

| 选项 | 方法 | 默认值 | 说明 |
|------|------|--------|------|
| 异常检测 | `enableAnomalyDetection(bool)` | true | 启用/禁用异常检测 |
| 签名验证 | `enableSignatureVerification(bool)` | true | 启用/禁用数字签名验证 |
| 最大文件大小 | `setMaxFileSize(size_t)` | 100MB | 跳过超过此大小的文件 |
| 提取目录 | `setExtractDirectory(string)` | - | 设置文件提取目录 |
| 威胁阈值 | `--dll-threshold N` | 30 | CLI 参数，低于此分数的不标记为可疑 |

### 白名单机制

系统 DLL（如 `kernel32.dll`, `ntdll.dll`, `libc.so`）和系统目录（如 `System32`, `/usr/lib`）中的文件会被自动白名单处理，降低误报率。

---

## 4. CLI 使用

```bash
# 启用 DLL 分析（作为常规分析的一部分）
./forensic_analyzer disk.dd --analyze-dlls

# 仅执行 DLL 分析
./forensic_analyzer disk.dd --analyze-dlls-only

# 设置威胁评分阈值
./forensic_analyzer disk.dd --analyze-dlls --dll-threshold 50

# 禁用签名验证（加速分析）
./forensic_analyzer disk.dd --analyze-dlls --no-verify-signatures
```

---

## 5. REST API

DLL 分析通过 `DLLAnalysisRoutes` 暴露 HTTP 端点：

```bash
# 获取所有分析的 DLL
GET /api/dll/list?task_id={task_id}&limit=100

# 获取可疑 DLL
GET /api/dll/suspicious?task_id={task_id}&threshold=30

# 获取单个 DLL 详情
GET /api/dll/{dll_id}?task_id={task_id}

# 获取 DLL 依赖关系
GET /api/dll/{dll_id}/dependencies?task_id={task_id}

# 获取 DLL 异常
GET /api/dll/{dll_id}/anomalies?task_id={task_id}

# 获取 DLL 统计信息
GET /api/dll/statistics?task_id={task_id}
```

---

## 6. 取证关联

DLLAnalyzer 支持与 WindowsFilesAnalyzer 数据关联：
- 将 DLL 分析结果与 Prefetch 数据关联，识别频繁加载的 DLL
- 将 DLL 与注册表中的自启动项关联
- 将 DLL 与浏览器下载历史关联

通过 `setWindowsDatabase()` 方法设置关联数据库。

---

## 相关模块

| 模块 | 说明 |
|------|------|
| [WindowsFilesAnalyzer](./WindowsFilesAnalyzer.md) | Windows 工件分析，提供关联数据 |
| [ImageAnalyzer](./ImageAnalyzer.md) | 磁盘镜像分析，提供文件提取 |
| [FileClassifier](../core/FileClassifier.md) | 文件分类，识别可执行文件 |
