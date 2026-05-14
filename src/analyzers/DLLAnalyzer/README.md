# DLLAnalyzer - PE/ELF文件深度分析引擎

## 1. 模块概述 (Overview)

**DLLAnalyzer** 是取证分析平台的专业二进制文件分析引擎,专注于 Windows 动态链接库(DLL)和 Linux 共享对象(.so)文件的深度取证分析。该模块能够从可执行文件中提取丰富的元数据、依赖关系、代码特征和异常指标,为恶意软件分析、软件侵权调查、漏洞研究等场景提供关键证据。

在现代数字取证中,可执行文件往往承载着重要的攻击指标(IOCs)和行为特征。DLLAnalyzer 通过多层分析技术,能够自动识别可疑代码模式、异常依赖关系、数字签名异常等潜在威胁,帮助调查人员快速定位恶意软件、未经授权的软件修改和潜在的供应链攻击。

**核心业务价值:**
- **深度二进制分析**:从PE/ELF文件中提取超过50项元数据和结构特征
- **威胁自动识别**:基于熵值、依赖关系、导入函数等特征自动检测可疑文件
- **供应链安全**:验证数字签名、证书链和文件完整性,识别篡改和伪造
- **高性能处理**:智能白名单、并行分析和增量分析技术,支持大规模文件集快速扫描
- **跨平台支持**:同时支持Windows PE和Linux ELF格式,统一分析框架

---

## 2. 核心功能列表 (Key Features)

### 2.1 PE文件分析 (Portable Executable Analysis)

**文件头解析**:
- DOS头和PE签名验证
- COFF头信息提取(机器类型、时间戳、节数量)
- 可选头解析(32位/64位、入口点、镜像基址、 Section对齐)
- 数据目录解析(导入表、导出表、资源、重定位、TLS等)

**节表分析**:
- 节名称、虚拟地址、物理大小
- 节属性(可执行、可写、只读)
- **熵值计算**:识别加密或压缩的节(高熵值=潜在混淆/加密)
- 节对齐验证和异常检测

**哈希计算**:
- MD5哈希(32字符十六进制)
- SHA1哈希(40字符十六进制)
- SHA256哈希(64字符十六进制)
- 用于文件完整性验证和IOC匹配

### 2.2 导入/导出分析 (Import/Export Analysis)

**导入表解析**:
- 导入的DLL列表(依赖库识别)
- 导入函数列表(API调用分析)
- **ImpHash计算**(Import Hash / dhash):基于导入函数的模糊哈希,用于恶意软件家族分类
- 异常导入检测(可疑API调用识别)

**导出表解析**:
- 导出函数列表
- 导出序号和RVA
- DLL功能推断(基于导出函数名称)

**依赖关系重建**:
- 构建完整的DLL依赖图
- 识别间接依赖(通过其他DLL的导入)
- 检测循环依赖和异常依赖链

### 2.3 ELF文件分析 (Executable and Linkable Format)

**ELF头解析**:
- 支持32位和64位ELF格式
- 文件类型识别(ET_DYN共享对象、ET_EXEC可执行文件、ET_REL重定位文件)
- 机器架构识别(x86、x86_64、ARM、ARM64、MIPS等)
- 操作系统ABI识别(System V、Linux、Windows等)

**程序头分析**:
- 段类型识别(LOAD、DYNAMIC、INTERP、NOTE等)
- 虚拟地址布局和内存映射
- 段标志(可读、可写、可执行)
- 加载地址计算

**节头分析**:
- 节名称和类型(.text、.data、.bss、.rodata、.dynsym、.dynstr等)
- 节标志和内存对齐
- 字符串表解析(.shstrtab)

**动态段解析**(进行中):
- NEEDED依赖库(动态链接库)
- SONAME(共享对象名称)
- RPATH和RUNPATH解析
- 符号表和字符串表索引

**符号表解析**(计划中):
- 全局和局部符号
- 函数符号和变量符号
- 符号版本信息

### 2.4 数字签名验证 (Digital Signature Verification)

**签名检测**:
- 自动检测PE文件是否包含数字签名
- 定位Security目录(IMAGE_DIRECTORY_ENTRY_SECURITY)
- 验证WIN_CERTIFICATE结构

**签名验证**:
- 集成osslsigncode工具进行Authenticode验证
- 验证证书链完整性
- 签名时间戳提取
- 验证失败时的降级处理

**证书信息提取**(计划中):
- 证书颁发者(Issuer)
- 证书主题(Subject)
- 序列号
- 签名算法
- 有效期

### 2.5 异常检测 (Anomaly Detection)

**熵值异常**:
- 代码节高熵值检测(潜在加密/混淆)
- 资源节异常分析
- 整体文件熵值评估

**依赖异常**:
- 罕见或不常见API调用识别
- 深层目录依赖检测
- 系统DLL异常调用

**结构异常**:
- PE头字段异常(时间戳未来、无效RVA等)
- 节属性异常(代码节可写、数据节可执行)
- 大小和偏移量不一致检测

**威胁评分**:
- 综合多项指标计算威胁评分(0-100)
- 分级风险评估(低/中/高/严重)
- 可疑指标详细列出

### 2.6 性能优化 (Performance Optimization)

**智能白名单**:
- 预定义系统DLL列表(kernel32.dll、ntdll.dll、libc.so.6等)
- 系统目录识别(C:\Windows\System32、/usr/lib、/lib等)
- 跳过白名单文件以节省分析时间

**并行分析**:
- 基于ThreadPool的多线程并行处理
- 自动检测文件数量并决定是否启用并行
- 线程数自动适配CPU核心数
- 线程安全的统计数据收集

**增量分析**:
- 基于文件路径和inode的重复检测
- 跳过已分析文件的机制(与数据库集成)
- 支持断点续传和增量更新

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:恶意软件样本分析

**背景**:安全运营中心(SOC)收到可疑文件样本,需要快速评估其威胁级别。

**使用流程**:
```bash
# 1. 分析单个可疑DLL
./forensic_analyzer suspicious.dll --analyze-dll

# 输出: suspicious.dll_analysis.db

# 2. 查询分析结果
sqlite3 suspicious.dll_analysis.db \
  "SELECT fileName, sha256Hash, threatScore, signatureStatus FROM dll_analysis_results;"

# 3. 查看高威胁文件
sqlite3 suspicious.dll_analysis.db \
  "SELECT * FROM dll_analysis_results WHERE threatScore > 70 ORDER BY threatScore DESC;"

# 4. 检查导入的可疑API
sqlite3 suspicious.dll_analysis.db \
  "SELECT dllName, functionName FROM dll_imports WHERE functionName LIKE '%CreateRemoteThread%' OR functionName LIKE '%VirtualAlloc%';"

# 5. 查看异常依赖
sqlite3 suspicious.dll_analysis.db \
  "SELECT dependencyName, dependencyType FROM dll_dependencies WHERE isSuspicious = 1;"
```

**分析发现**:
- 哈希: SHA256=a3f5e8... (可在VirusTotal中查询)
- 威胁评分: 85分(高风险)
- 签名: 无数字签名或无效签名
- 导入API: 发现CreateRemoteThread、VirtualAllocEx等进程注入API
- 异常依赖: 依赖深度嵌套的临时目录

**价值体现**:快速识别恶意软件特征,为应急响应提供依据。

---

### 场景二:批量软件资产审计

**背景**:企业IT部门需要审计所有服务器上的DLL文件,识别未授权软件和版本合规问题。

**使用流程**:
```bash
# 1. 扫描整个目录(使用并行分析)
./forensic_analyzer --scan-dll-dir /usr/lib --output-dll-db software_audit.db

# 2. 识别非白名单DLL(第三方或自定义DLL)
sqlite3 software_audit.db \
  "SELECT fileName, filePath, sha256Hash FROM dll_analysis_results WHERE isWhitelisted = 0 ORDER BY fileName;"

# 3. 检查缺少数字签名的DLL
sqlite3 software_audit.db \
  "SELECT fileName, signerName FROM dll_analysis_results WHERE signatureStatus != 'Signed' AND isWhitelisted = 0;"

# 4. 识别高版本号DLL(潜在的版本冲突)
sqlite3 software_audit.db \
  "SELECT fileName, fileVersion FROM dll_analysis_results WHERE fileVersion IS NOT NULL ORDER BY fileName, fileVersion DESC;"

# 5. 导出所有非系统DLL的ImpHash用于威胁情报比对
sqlite3 software_audit.db -header -csv \
  "SELECT fileName, impHash FROM dll_analysis_results WHERE isWhitelisted = 0 AND impHash IS NOT NULL;" > imphash_export.csv
```

**分析发现**:
- 总计扫描: 15,234个DLL文件
- 白名单文件: 12,567个(已跳过深度分析)
- 非白名单文件: 2,667个
- 缺少签名: 1,234个
- 可疑文件(威胁评分>50): 89个

**价值体现**:自动化软件资产清点,快速识别合规风险和潜在威胁。

---

### 场景三:软件供应链安全审查

**背景**:企业发现第三方供应商提供的SDK可能存在安全风险,需要对DLL文件进行深度审查。

**使用流程**:
```cpp
#include "DLLAnalyzer/DLLAnalyzer.h"

// 1. 分析SDK目录中的所有DLL
forensics::dll::DLLAnalyzer analyzer;
auto results = analyzer.scanDirectoryParallel("/opt/vendor_sdk/bin");

// 2. 检查数字签名验证
for (const auto& dllPath : results) {
    forensics::dll::DLLAnalysisResult result = analyzer.analyzeDLL(dllPath);

    // 检查签名状态
    if (result.peHeader.signatureStatus != "Signed") {
        LOG_WARNING("Unsigned DLL: " + dllPath);
    }

    // 检查威胁评分
    if (result.threatScore > 60) {
        LOG_ERROR("High risk DLL detected: " + dllPath + " Score: " + std::to_string(result.threatScore));
    }

    // 检查异常依赖
    for (const auto& dep : result.dependencies) {
        if (dep.isSuspicious) {
            LOG_WARNING("Suspicious dependency: " + dep.name + " in " + dllPath);
        }
    }
}

// 3. 导出分析报告
analyzer.exportAnalysisReport("vendor_sdk_audit_report.json");
```

**分析发现**:
- 签名问题: 3个DLL缺少数字签名或签名无效
- 异常依赖: 1个DLL依赖非常用系统API
- 高熵值: 2个DLL的代码节熵值>7.0(可能被混淆)
- 重复文件: 发现5组哈希相同的DLL(可能的冗余分发)

**价值体现**:全面评估第三方软件的安全性,降低供应链攻击风险。

---

### 场景四:入侵溯源 - DLL侧加载检测

**背景**:EDR检测到某进程执行了非常见路径的DLL,疑似DLL侧加载攻击。

**使用流程**:
```bash
# 1. 分析可疑DLL
./forensic_analyzer /tmp/malicious.dll --analyze-dll

# 2. 检查导入表
sqlite3 analysis.db \
  "SELECT * FROM dll_imports WHERE dllName = 'suspicious.dll';"

# 3. 查看依赖树
sqlite3 analysis.db \
  "WITH RECURSIVE dep_tree AS (
     SELECT dependencyName, 1 AS depth FROM dll_dependencies WHERE dllName = 'suspicious.dll'
     UNION ALL
     SELECT d.dependencyName, dep_tree.depth + 1
     FROM dll_dependencies d
     INNER JOIN dep_tree ON d.dllName = dep_tree.dependencyName
   ) SELECT * FROM dep_tree;"

# 4. 查看异常特征
sqlite3 analysis.db \
  "SELECT * FROM dll_analysis_results WHERE fileName = 'suspicious.dll';"

# 5. 导出完整分析报告(包含所有元数据)
curl -X GET "http://localhost:8090/api/db/tasks/xxx/export/json?table=dll_analysis_results&table=dll_imports&table=dll_dependencies" > full_report.json
```

**分析发现**:
- 文件路径: /tmp/malicious.dll(非常见目录)
- 签名状态: 未签名
- 导入函数: 包含大量系统管理API(注册表访问、服务控制)
- 依赖关系: 依赖其他可疑DLL形成攻击链
- 威胁评分: 92分(严重风险)

**价值体现**:识别DLL侧加载攻击,揭示攻击者使用的持久化技术。

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**操作系统支持**:
- Linux: Ubuntu 20.04+, Debian 11+, CentOS 8+
- Windows: Windows 10/11 (通过WSL2或MinGW)
- macOS: macOS 11+ (仅ELF文件分析)

**编译要求**:
- GCC 9.0+ 或 Clang 10.0+
- 支持 C++20 标准
- CMake 3.16+

**必需库**:
```bash
# 核心依赖
sudo apt-get install build-essential cmake git
sudo apt-get install libsqlite3-dev nlohmann-json3-dev

# OpenSSL (用于哈希计算)
sudo apt-get install libssl-dev

# 可选: osslsigncode (用于数字签名验证)
sudo apt-get install osslsigncode

# 可选: Google Test (用于单元测试)
sudo apt-get install libgtest-dev libgmock-dev
```

**系统要求**:
- RAM: 4GB最低, 8GB推荐(并行分析大量文件)
- 磁盘: SSD推荐(提升文件I/O性能)
- CPU: 多核心CPU推荐(启用并行分析)

### 配置说明

**命令行使用**:
```bash
# 分析单个DLL
./forensic_analyzer suspicious.dll --analyze-dll

# 扫描目录(并行处理)
./forensic_analyzer --scan-dll-dir /path/to/dlls --output-dll-db results.db

# 通过HTTP API分析
curl -X POST http://localhost:8080/api/dll/analyze \
  -F "file=@suspicious.dll"
```

**性能调优**:
```cpp
// 配置DLLAnalyzer
DLLAnalyzer::Config config;

// 并行分析线程数(默认=CPU核心数)
config.numThreads = std::thread::hardware_concurrency();

// 白名单启用/禁用
config.enableWhitelist = true;

// 增量分析(跳过已分析文件)
config.enableIncremental = true;

// 威胁评分阈值(高于此值标记为可疑)
config.threatScoreThreshold = 70;

// 熵值阈值(高于此值视为加密/混淆)
config.entropyThreshold = 7.0;
```

**数据库优化**:
```sql
-- 启用WAL模式提升并发性能
PRAGMA journal_mode = WAL;

-- 增加缓存大小(64MB)
PRAGMA cache_size = -64000;

-- 批量插入优化
PRAGMA mmap_size = 268435456;  -- 256MB mmap
```

### 分析时间估算

**典型场景分析时间**(基于Intel i7-9700K, SSD):
- 单个DLL分析: <1秒
- 100个DLL批量分析: 10-30秒
- 1000个DLL批量分析(并行): 30-60秒
- 10,000个DLL批量分析(并行): 5-10分钟

**影响因素**:
- DLL文件大小(大型DLL需要更多I/O时间)
- 是否启用签名验证(osslsigncode调用耗时)
- 是否启用深度分析(熵值计算、完整导入表解析)
- 磁盘I/O性能(机械硬盘vs SSD)

---

## 5. 接口与集成说明 (API & Integration)

### 数据库表结构

**DLL分析结果** (dll_analysis_results):
```sql
CREATE TABLE dll_analysis_results (
    id INTEGER PRIMARY KEY,
    fileName TEXT NOT NULL,
    filePath TEXT NOT NULL,
    fileSize INTEGER,
    md5Hash TEXT,
    sha1Hash TEXT,
    sha256Hash TEXT,
    impHash TEXT,
    peTimestamp INTEGER,
    machineType TEXT,
    is64Bit BOOLEAN,
    entryPoint TEXT,
    imageBase TEXT,
    fileNameVersion TEXT,
    fileVersion TEXT,
    signatureStatus TEXT,
    signerName TEXT,
    issuerName TEXT,
    serialNumber TEXT,
    timestamp INTEGER,
    algorithm TEXT,
    isWhitelisted BOOLEAN,
    threatScore INTEGER,
    analysisStatus TEXT,
    errorMessage TEXT,
    createdAt INTEGER
);
```

**节信息** (pe_sections):
```sql
CREATE TABLE pe_sections (
    id INTEGER PRIMARY KEY,
    resultId INTEGER,
    sectionName TEXT,
    virtualAddress TEXT,
    virtualSize INTEGER,
    rawSize INTEGER,
    characteristics TEXT,
    entropy REAL,
    FOREIGN KEY (resultId) REFERENCES dll_analysis_results(id)
);
```

**导入函数** (dll_imports):
```sql
CREATE TABLE dll_imports (
    id INTEGER PRIMARY KEY,
    resultId INTEGER,
    dllName TEXT,
    functionName TEXT,
    ordinal INTEGER,
    FOREIGN KEY (resultId) REFERENCES dll_analysis_results(id)
);
```

**导出函数** (dll_exports):
```sql
CREATE TABLE dll_exports (
    id INTEGER PRIMARY KEY,
    resultId INTEGER,
    functionName TEXT,
    ordinal INTEGER,
    rva TEXT,
    FOREIGN KEY (resultId) REFERENCES dll_analysis_results(id)
);
```

**依赖项** (dll_dependencies):
```sql
CREATE TABLE dll_dependencies (
    id INTEGER PRIMARY KEY,
    resultId INTEGER,
    dependencyName TEXT,
    dependencyType TEXT,
    isSuspicious BOOLEAN,
    FOREIGN KEY (resultId) REFERENCES dll_analysis_results(id)
);
```

**异常指标** (dll_anomalies):
```sql
CREATE TABLE dll_anomalies (
    id INTEGER PRIMARY KEY,
    resultId INTEGER,
    anomalyType TEXT,
    severity TEXT,
    description TEXT,
    evidence TEXT,
    FOREIGN KEY (resultId) REFERENCES dll_analysis_results(id)
);
```

### C++ 编程接口

**基本使用**:
```cpp
#include "DLLAnalyzer/DLLAnalyzer.h"

// 创建分析器实例
forensics::dll::DLLAnalyzer analyzer;

// 分析单个DLL
forensics::dll::DLLAnalysisResult result = analyzer.analyze("suspicious.dll");

// 访问结果
std::cout << "File: " << result.fileName << std::endl;
std::cout << "SHA256: " << result.sha256Hash << std::endl;
std::cout << "Threat Score: " << result.threatScore << std::endl;
std::cout << "Signature: " << result.signatureStatus << std::endl;

// 访问PE头信息
std::cout << "Machine Type: " << result.peHeader.machineType << std::endl;
std::cout << "Entry Point: " << result.peHeader.entryPoint << std::endl;

// 访问节信息
for (const auto& section : result.peHeader.sections) {
    std::cout << "Section: " << section.sectionName
              << " Entropy: " << section.entropy << std::endl;
}

// 访问导入
for (const auto& import : result.imports) {
    std::cout << "DLL: " << import.dllName << std::endl;
    for (const auto& func : import.importedFunctions) {
        std::cout << "  Function: " << func.functionName << std::endl;
    }
}
```

**并行扫描目录**:
```cpp
// 扫描目录中的所有DLL(自动跳过白名单)
std::vector<std::string> dllFiles = analyzer.scanDirectoryParallel("/path/to/directory");

// 批量分析
std::vector<forensics::dll::DLLAnalysisResult> results;
for (const auto& dllPath : dllFiles) {
    results.push_back(analyzer.analyze(dllPath));
}

// 导出结果
analyzer.exportResultsToJSON("analysis_report.json");
```

### REST API集成

**通过C++ HTTP服务**:
```bash
# 分析单个文件
POST /api/dll/analyze
Content-Type: multipart/form-data

# 批量扫描目录
POST /api/dll/scan-directory
{
    "directory_path": "/path/to/dlls",
    "recursive": true,
    "enable_whitelist": true,
    "parallel": true
}

# 查询分析结果
GET /api/dll/analysis/{task_id}

# 获取威胁评分最高的文件
GET /api/dll/threats?task_id=xxx&min_score=70

# 导出分析报告
GET /api/dll/export/{task_id}?format=json
```

**通过Python HTTP服务**(支持LLM分析):
```bash
# 提交DLL分析任务
curl -X POST http://localhost:8090/api/llm/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "xxx",
    "file_path": "/path/to/dll.dll",
    "enable_llm_analysis": true
  }'

# 批量分析(结合TOON格式导出)
curl -X GET "http://localhost:8090/api/db/tasks/xxx/export/toon?table=dll_analysis_results" > dll_analysis.toon
```

---

## 6. 常见问题 (FAQ)

**Q1:白名单机制的工作原理是什么?如何自定义白名单?**

A:DLLAnalyzer使用两层白名单机制:

1. **文件名白名单**:预定义的系统DLL名称列表
   ```cpp
   kernel32.dll, ntdll.dll, user32.dll, gdi32.dll,
   libc.so.6, libdl.so.2, libpthread.so.0, libm.so.6
   ```

2. **目录路径白名单**:系统目录路径前缀匹配
   ```cpp
   /usr/lib, /usr/lib64, /lib, /lib64
   c:\windows\system32, c:\windows\syswow64
   ```

**自定义白名单**:
```cpp
DLLAnalyzer analyzer;

// 添加自定义白名单DLL
analyzer.addToWhitelist("custom_lib.dll");

// 添加自定义白名单目录
analyzer.addWhitelistDirectory("/opt/custom_libs");

// 禁用白名单
DLLAnalyzer::Config config;
config.enableWhitelist = false;
```

**使用场景**:
- 仅分析第三方或自定义DLL
- 忽略已知安全的系统DLL以加速分析
- 聚焦于潜在风险文件

---

**Q2:威胁评分是如何计算的?准确性如何?**

A:威胁评分基于多维度指标加权计算(0-100分):

**评分维度**:
- 数字签名异常(0-20分):未签名=20分,无效签名=15分
- 高熵值节(0-25分):单节熵>7.5=25分,>7.0=15分
- 可疑导入函数(0-30分):每个可疑API+5-10分
- 异常依赖(0-15分):非常用路径依赖=15分
- 结构异常(0-10分):PE头字段异常、节属性异常等

**准确性和局限性**:
- **优势**:快速识别已知恶意模式(高评分通常对应真实风险)
- **局限**:可能产生误报(良性软件也可能使用敏感API)
- **建议**:威胁评分应作为优先级指标,而非绝对判断依据
- **最佳实践**:结合VirusTotal、沙箱分析等多源验证

---

**Q3:ImpHash有什么用?如何用于威胁 hunting?**

A:**ImpHash**(Import Hash)是基于DLL导入函数列表计算的模糊哈希,用于恶意软件家族分类和威胁 hunting。

**计算原理**:
1. 提取DLL的所有导入函数名称
2. 按字母顺序排序
3. 连接成字符串
4. 计算MD5哈希

**应用场景**:
```bash
# 1. 导出所有样本的ImpHash
sqlite3 analysis.db -header -csv \
  "SELECT fileName, impHash, sha256Hash FROM dll_analysis_results WHERE impHash IS NOT NULL;" > imphashes.csv

# 2. 在威胁情报平台查询相同ImpHash的样本
# (使用VirusTotal、Hybrid Analysis等平台API)

# 3. 批量查询可疑ImpHash
# 假设发现某个ImpHash对应已知恶意软件家族
sqlite3 analysis.db \
  "SELECT * FROM dll_analysis_results WHERE impHash = 'a3f5e8d9c4b2a1f0e7d6c5b4a3928176';"
```

**优势**:
- 忽略代码变化,聚焦于行为特征
- 即使加壳或混淆,导入函数通常保持不变
- 快速家族聚类和批量检测

**局限**:
- 不同编译选项可能导致相同功能的不同ImpHash
- 空导入攻击可绕过(LoadLibrary/GetProcAddress动态加载)
- 建议结合其他IOC(哈希、YARA规则)综合判断

---

**Q4:如何识别DLL侧加载(DLL Side-Loading)攻击?**

A:DLL侧加载攻击利用Windows DLL搜索顺序劫持机制,DLLAnalyzer可通过以下方式检测:

**检测指标**:
```sql
-- 1. 非常见路径的DLL
SELECT fileName, filePath FROM dll_analysis_results
WHERE filePath NOT LIKE 'C:\Windows\%'
  AND filePath NOT LIKE 'C:\Program Files\%'
  AND isWhitelisted = 0;

-- 2. 缺少数字签名的高风险DLL
SELECT fileName, filePath, threatScore FROM dll_analysis_results
WHERE signatureStatus != 'Signed'
  AND threatScore > 60
  AND filePath LIKE '%\Temp\%';

-- 3. 异常依赖关系
SELECT d.dllName, d.dependencyName FROM dll_dependencies d
INNER JOIN dll_analysis_results r ON d.resultId = r.id
WHERE d.isSuspicious = 1
  AND r.filePath LIKE '%\AppData\%';

-- 4. 与知名DLL同名的文件(可能为伪装)
SELECT a.fileName, a.filePath, b.fileName AS legitName, b.filePath AS legitPath
FROM dll_analysis_results a
INNER JOIN dll_analysis_results b ON a.fileName = b.fileName
WHERE a.filePath != b.filePath
  AND a.signatureStatus != 'Signed'
  AND b.signatureStatus = 'Signed';
```

**验证方法**:
```cpp
// 检查DLL是否在可写目录
std::string dllPath = result.filePath;
std::filesystem::path path(dllPath);
auto dir = path.parent_path();

// 检查目录权限
if (std::filesystem::exists(dir)) {
    auto perms = std::filesystem::status(dir).permissions();
    bool isWritable = (perms & std::filesystem::perms::owner_write) != std::filesystem::perms::none;

    if (isWritable) {
        LOG_WARNING("DLL in writable directory (potential side-loading): " + dllPath);
    }
}
```

**响应建议**:
- 隔离可疑DLL文件
- 检查进程命令行和父进程
- 分析调用该DLL的进程行为
- 检查注册表Run键和计划任务(持久化)

---

**Q5:ELF文件分析的完整功能何时推出?**

A:ELF分析功能目前处于**部分可用**状态:

**已完成功能**:
- ✅ ELF头解析(32/64位)
- ✅ 机器架构识别
- ✅ 程序头解析(段类型、标志、虚拟地址)
- ✅ 节头解析(节名称、类型、标志)
- ✅ 字符串表读取(.shstrtab)

**进行中功能**(计划在v2.1.0):
- 🔄 动态段解析(NEEDED依赖库、SONAME、RPATH)
- 🔄 符号表解析(.dynsym、.symtab)

**计划功能**(v2.2.0):
- 📋 Relocation表解析
- 📋 GOT/PLT分析
- 📋 字符串提取(.rodata)
- 📋 动态链接器路径识别
- 📋 静态链接检测

**当前使用建议**:
- ELF头信息和程序头信息可用于架构识别和加载地址分析
- 完整依赖解析待后续版本
- 可与`readelf`、`objdump`等工具结合使用

---

**Q6:数字签名验证失败的可能原因有哪些?**

A:签名验证失败的原因有多种:

**1. 文件未签名**
```cpp
// SignatureVerifier返回"Unsigned"
if (result.signatureStatus == "Unsigned") {
    // 原因: Security目录不存在或为空
}
```

**2. 签名无效**
```cpp
// 签名存在但验证失败
if (result.signatureStatus == "Invalid") {
    // 可能原因:
    // - 证书已过期
    // - 证书被吊销
    // - 文件被篡改(哈希不匹配)
    // - 不受信任的根证书
    // - 签名算法过时
}
```

**3. osslsigncode不可用**
```cpp
// 回退到基本结构验证
if (!signatureVerifier.isOsslSigncodeAvailable()) {
    LOG_WARNING("osslsigncode not available, using basic validation");
    // 只能检测签名存在性,无法验证有效性
}
```

**4. 系统兼容性**
- Windows PE文件在Linux上分析:部分签名验证可能受限
- 跨架构分析(x86 vs x64):不影响签名验证

**调试建议**:
```bash
# 手动使用osslsigncode验证
osslsigncode verify suspicious.dll

# 查看详细输出
osslsigncode verify -in suspicious.dll -verbose

# 提取签名信息
osslsigncode extract -in suspicious.dll -out signature.p7
```

**未来改进**:
- 集成OpenSSL库进行纯代码实现(不依赖外部工具)
- 证书链完整验证
- CRL/OCP在线吊销检查

---

## 7. 架构设计 (Architecture)

### 组件结构

```
DLLAnalyzer/
├── Core/
│   ├── DLLAnalyzer.h              # 主类接口
│   ├── DLLAnalyzerCore.cpp        # 主类实现
│   └── PEAnalyzer.h/cpp           # PE文件分析引擎
├── Parsers/
│   ├── PEHeaderParser.h/cpp       # PE头解析器
│   ├── PEImportExportParser.h/cpp # 导入/导出表解析器
│   ├── ELFParser.h/cpp            # ELF文件解析器
│   └── SignatureVerifier.h/cpp    # 数字签名验证器
├── Common/
│   └── DLLDataTypes.h             # 数据结构定义(PE/ELF结构体)
├── Database/
│   └── DLLAnalysisDatabase.cpp    # 数据库接口
├── Utils/
│   ├── HashCalculator.h/cpp       # 哈希计算工具
│   └── EntropyCalculator.h/cpp    # 熵值计算工具
└── README.md                      # 本文档
```

### 核心类职责

**DLLAnalyzer**(主类):
- 对外接口:分析单个DLL、批量扫描目录
- 协调子分析器(PEAnalyzer、ELFParser等)
- 白名单管理和性能优化(并行、增量)
- 威胁评分计算和异常汇总
- 数据库存储和结果导出

**PEAnalyzer**(PE分析引擎):
- 哈希计算(MD5、SHA1、SHA256)
- PE头解析(委托给PEHeaderParser)
- 节表和熵值计算(委托给PEHeaderParser)
- 导入/导出表解析(委托给PEImportExportParser)
- ImpHash计算
- 数字签名验证(委托给SignatureVerifier)

**ELFParser**(ELF解析器):
- ELF头解析(32/64位)
- 程序头解析(段信息)
- 节头解析
- 动态段解析(计划中)
- 符号表解析(计划中)

**SignatureVerifier**(签名验证器):
- PE Security目录定位
- WIN_CERTIFICATE结构解析
- osslsigncode集成
- 证书信息提取(计划中)

**AnomalyDetector**(异常检测器):
- 熵值异常检测
- 依赖关系异常检测
- 结构异常检测
- 威胁评分计算

### 数据流程

```
1. 输入文件路径
   ↓
2. DLLAnalyzer::analyze()
   ↓
3. 白名单检查(跳过系统DLL)
   ↓
4. 增量检查(跳过已分析文件)
   ↓
5. 并行调度(多文件)
   ↓
6. PEAnalyzer/ELFParser执行分析
   ├─ 哈希计算
   ├─ 头解析
   ├─ 节/段分析
   ├─ 导入/导出解析
   ├─ 签名验证
   └─ 异常检测
   ↓
7. 威胁评分计算
   ↓
8. 数据库存储
   ↓
9. 返回分析结果
```

---

## 8. 测试 (Testing)

### 单元测试

使用Google Test框架,测试覆盖:
- PE头解析测试(PE32/PE32+)
- ELF头解析测试(32/64位)
- 导入/导出表解析测试
- 签名验证测试
- 异常检测测试
- 哈希计算测试

**运行测试**:
```bash
cd build
./test_dll_analyzer_gtest
```

**测试覆盖率**:
```bash
# 生成覆盖率报告
cmake -DCMAKE_BUILD_TYPE=Debug -DENABLE_COVERAGE=ON ..
make test_dll_analyzer_gtest
gcovr -r src/analyzers/DLLAnalyzer --html -o coverage.html
```

### 集成测试

**测试样本**:
- `tests/samples/benign/`: 已知良性DLL(系统DLL、常用库)
- `tests/samples/malicious/`: 已知恶意样本(需授权使用)
- `tests/samples/elf/`: ELF测试样本(各种架构)

**测试流程**:
```bash
# 批量分析测试样本
./forensic_analyzer --scan-dll-dir tests/samples --output-dll-db test_results.db

# 验证结果
sqlite3 test_results.db "SELECT COUNT(*) FROM dll_analysis_results;"
sqlite3 test_results.db "SELECT COUNT(*) FROM dll_analysis_results WHERE threatScore > 50;"
```

### 性能测试

```bash
# 1000个DLL的并行分析时间测试
time ./forensic_analyzer --scan-dll-dir /path/to/1000_dlls --output-dll-db perf_test.db

# 对比: 单线程 vs 多线程
./forensic_analyzer --scan-dll-dir /path/to/dlls --output-dll-db single.db --threads 1
./forensic_analyzer --scan-dll-dir /path/to/dlls --output-dll-db multi.db --threads 8
```

---

## 9. 开发指南 (Development Guide)

### 添加新的异常检测规则

```cpp
// 在AnomalyDetector.cpp中添加
bool AnomalyDetector::detectCustomAnomaly(const PEAnalyzerResult& result) {
    // 自定义检测逻辑
    if (/* 检测条件 */) {
        addAnomaly(result.id, "CUSTOM_ANOMALY", "HIGH", "描述信息");
        return true;
    }
    return false;
}
```

### 扩展白名单

```cpp
// 在DLLAnalyzerCore.cpp的静态初始化中添加
const std::unordered_set<std::string> DLLAnalyzer::SYSTEM_DLL_NAMES_ = {
    // ... 现有列表
    "custom_dll.dll"  // 添加自定义DLL
};
```

### 添加新的ELF解析功能

```cpp
// 在ELFParser.h中添加
class ELFParser {
public:
    // ... 现有方法
    bool parseGOT(const std::string& filePath, ELFHeaderInfo& info);
    bool parsePLT(const std::string& filePath, ELFHeaderInfo& info);
};
```

---

## 10. 贡献指南 (Contributing)

### 代码规范

- 遵循Google C++ Style Guide
- 使用clang-format格式化代码: `clang-format -i src/**/*.cpp`
- 所有公共方法必须包含Doxygen注释

### 提交规范

```
feat: 添加新功能
fix: 修复bug
docs: 文档更新
test: 测试相关
perf: 性能优化
refactor: 代码重构
```

### Pull Request流程

1. Fork项目仓库
2. 创建功能分支: `git checkout -b feature/amazing-feature`
3. 提交更改: `git commit -m 'feat: add amazing feature'`
4. 推送分支: `git push origin feature/amazing-feature`
5. 创建Pull Request

---

## 附录A:威胁评分详细算法

```
总威胁评分 = min(各项分数之和, 100)

评分项:
1. 数字签名异常 (0-20分)
   - 未签名: +20
   - 无效签名: +15
   - 签名但颁发者可疑: +10

2. 高熵值节 (0-25分)
   - 代码节熵 > 7.5: +25
   - 代码节熵 7.0-7.5: +15
   - 资源节熵 > 7.5: +10

3. 可疑导入函数 (0-30分)
   - 进程注入API(CreateRemoteThread等): +10
   - 内存操作API(VirtualAlloc等): +8
   - 注册表操作API: +5
   - 网络API(socket、connect等): +5
   - 加密API(CryptEncrypt等): +7

4. 异常依赖 (0-15分)
   - Temp目录DLL: +15
   - 用户目录DLL: +10
   - 深层嵌套路径: +5

5. 结构异常 (0-10分)
   - 未来时间戳: +5
   - 无效RVA: +5
   - 节属性矛盾(代码节可写): +5
```

---

## 附录B:常见导入函数分类

**进程注入类**(高风险):
- CreateRemoteThread, WriteProcessMemory, ReadProcessMemory
- VirtualAllocEx, VirtualProtectEx
- SetWindowsHookEx, EnumWindows

**持久化类**(中高风险):
- RegCreateKey, RegSetValue
- CreateService, StartService
- WritePrivateProfileString

**数据收集类**(中风险):
- GetKeyState, GetAsyncKeyState(键盘记录)
- BitBlt, GetDC(屏幕截图)
- FindFirstFile, FindNextFile(文件枚举)

**网络通信类**(中风险):
- socket, connect, send, recv
- InternetOpen, InternetConnect
- WSAStartup

**规避检测类**(高风险):
- IsDebuggerPresent, CheckRemoteDebuggerPresent
- NtQueryInformationProcess
- SetUnhandledExceptionFilter

---

## 附录C:熵值参考标准

| 熵值范围 | 解释 | 常见情况 |
|---------|------|---------|
| 0.0 - 1.0 | 极低熵值 | 空数据、全零填充 |
| 1.0 - 3.0 | 低熵值 | 纯文本、简单代码 |
| 3.0 - 5.0 | 中等熵值 | 编译后的代码、文档 |
| 5.0 - 7.0 | 较高熵值 | 压缩数据、部分加密 |
| 7.0 - 7.5 | 高熵值 | 轻度加密/混淆 |
| 7.5 - 8.0 | 极高熵值 | 强加密、恶意软件 |

**注意**:高熵值不等于恶意,但高熵值代码节需要重点关注。

---

*文档版本: 1.0.0 | 更新日期: 2026-05-14 | 维护者: ForensicsProject Team*
