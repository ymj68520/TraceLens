# LinuxLLMAnalysisService - Linux 取证 LLM 分析服务

> **模块定位**: 使用 LLM 分析 Linux 系统工件，为调查提供 AI 驱动的上下文理解

---

## 1. 模块概述

### 位置

`src/network/HTTPServer/LinuxLLMAnalysisService.h`

### 设计目标

LinuxLLMAnalysisService 是 Linux 取证分析的**必需步骤**。它对所有 Linux 系统工件进行 LLM 分析，生成摘要、描述和关键词，帮助调查人员快速理解系统状态和用户行为。

### 支持的工件类型（30+）

| 类别 | 工件类型 |
|------|---------|
| **日志** | LOG_ENTRY, JOURNAL_ENTRY, ERROR_LOG, MIDDLEWARE_LOG, CONTAINER_LOG, DATABASE_LOG, EMAIL_LOG |
| **用户** | USER_ACCOUNT, LOGIN_RECORD, ACCOUNT_ANOMALY |
| **Shell** | SHELL_HISTORY |
| **定时任务** | CRON_JOB |
| **SSH** | SSH_KEY, SSH_KNOWN_HOST |
| **包管理** | PACKAGE, PACKAGE_OPERATION |
| **网络** | NETWORK_CONNECTION, VPN_LOG, FIREWALL_LOG, FIREWALL_RULE |
| **服务** | SYSTEMD_SERVICE |
| **内核** | KERNEL_MODULE |
| **审计** | AUDIT_LOG, AGGREGATED_AUDIT_EVENT |
| **浏览器** | BROWSER_PROFILE |
| **安全** | TAMPERING_INDICATOR, PERSISTENCE_ENTRY, SECURITY_PRODUCT_LOG |
| **启动** | BOOT_SESSION |

---

## 2. 数据结构

### AnalysisOptions

```cpp
struct AnalysisOptions {
    size_t maxArtifacts = 1000;      // 每种类型最大分析数
    bool includeLogs = true;
    bool includeUsers = true;
    bool includeLogins = true;
    bool includeShellHistory = true;
    bool includeCron = true;
    bool includeSSH = true;
    bool includePackages = true;
    bool includeNetwork = true;
    bool includeSystemd = true;
    bool includeKernel = true;
    bool includeFirewall = true;
    bool includeAudit = true;
    bool includeBrowser = true;
};
```

### AnalysisResult

```cpp
struct AnalysisResult {
    bool success;
    std::string summary;
    std::string description;
    std::vector<std::string> keywords;
    std::string modelUsed;
};
```

---

## 3. API 参考

### 初始化

```cpp
LinuxLLMAnalysisService service;
service.initialize();
```

### 分析所有工件

```cpp
LinuxLLMAnalysisService::AnalysisOptions options;
options.maxArtifacts = 500;
options.includeLogs = true;
options.includeUsers = true;

int analyzed = service.analyzeLinuxArtifacts(
    "/output/linux.db",
    options,
    [](const std::string& type, int current, int total, const std::string& details) {
        std::cout << "[" << type << "] " << current << "/" << total << ": " << details << std::endl;
    }
);
```

### 分析特定类型

```cpp
int analyzed = service.analyzeArtifactType(
    "/output/linux.db",
    LinuxLLMAnalysisService::ArtifactType::SHELL_HISTORY,
    100,  // 最大数量
    progressCallback
);
```

---

## 4. 分析流程

1. 从 `_linux.db` 读取工件记录
2. 将工件数据格式化为 LLM 可理解的文本
3. 调用 LLM 生成分析结果
4. 将结果（摘要、描述、关键词）写回数据库

每种工件类型有专门的分析方法：
- `analyzeLogArtifact()` - 系统日志
- `analyzeUserArtifact()` - 用户账户
- `analyzeLoginArtifact()` - 登录记录
- `analyzeShellHistoryArtifact()` - Shell 历史
- `analyzeCronArtifact()` - 定时任务
- `analyzeSSHArtifact()` - SSH 密钥
- `analyzePackageArtifact()` - 安装包
- `analyzeNetworkArtifact()` - 网络连接
- `analyzeSystemdArtifact()` - 系统服务
- `analyzeKernelModuleArtifact()` - 内核模块
- `analyzeFirewallArtifact()` - 防火墙规则
- `analyzeAuditLogArtifact()` - 审计日志
- `analyzeBrowserProfileArtifact()` - 浏览器配置

---

## 5. 使用场景

- **入侵调查**: 分析 SSH 密钥、登录记录、Shell 历史，追踪攻击者行为
- **恶意软件分析**: 分析定时任务、系统服务、内核模块，发现持久化机制
- **数据泄露**: 分析网络连接、防火墙日志，识别数据外传路径
- **合规审计**: 分析用户账户、包管理、安全配置，评估系统合规性

---

## 相关模块

| 模块 | 说明 |
|------|------|
| [LinuxFilesAnalyzer](../analyzers/LinuxFilesAnalyzer.md) | Linux 工件提取 |
| [WindowsLLMAnalysisService](./WindowsLLMAnalysisService.md) | Windows 平台对应模块 |
| [LLMAnalysisService](./LLMAnalysisService.md) | 文件级 LLM 分析 |
