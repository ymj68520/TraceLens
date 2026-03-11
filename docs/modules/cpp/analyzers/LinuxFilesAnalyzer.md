# LinuxFilesAnalyzer 模块文档

## 1. 模块背景

### 业务背景

Linux 服务器是企业和云计算环境中的主要工作平台。Linux 取证分析需要从 Linux 系统中提取：

**核心需求**：
- **系统日志**：syslog、auth.log、kern.log 等系统活动记录
- **用户账户**：/etc/passwd、/etc/shadow 用户信息
- **登录历史**：wtmp、btmp 登录会话记录
- **Shell 历史**：.bash_history、.zsh_history 命令执行记录
- **Cron 任务**：/etc/crontab、systemd 服务定时任务
- **网络配置**：网络连接、监听端口

**解决挑战**：
- **文本日志解析**：不同 Linux 发行版的日志格式差异
- **二进制日志**：wtmp、btmp、utmp 二进制格式
- **权限获取**：某些文件需要 root 权限读取
- **数据关联**：跨多个数据源的用户活动重建

### 技术背景

**Linux 取证特点**：
- **文本配置**：大部分配置文件为纯文本
- **标准位置**：文件系统层次结构标准化（FHS）
- **开源生态**：大量工具和解析库可用
- **多发行版**：Ubuntu、CentOS、Debian 等差异

## 2. 模块功能

### 核心功能

#### 1. 系统日志分析

**支持的日志类型**：
- **syslog**：系统服务日志
- **auth.log / secure**：认证和安全日志
- **kern.log**：内核消息
- **dpkg.log**：软件包管理日志
- **dmesg**：内核启动消息

**提取的数据**：
- 时间戳和主机名
- 进程名和 PID
- 日志级别和设施
- 消息内容

#### 2. 用户账户分析

**数据源**：
- `/etc/passwd`：用户账户信息
- `/etc/shadow`：密码哈希和策略
- `/etc/group`：组信息

**提取的数据**：
- 用户名、UID/GID
- 主目录和默认 Shell
- 密码哈希（加密）
- 账户过期信息
- 系统账户标识

#### 3. 登录历史分析

**数据源**：
- `/var/log/wtmp`：登录会话记录
- `/var/log/btmp`：失败的登录尝试
- `/var/log/lastlog`：最后登录时间

**提取的数据**：
- 用户名、终端
- 远程主机 IP
- 登录/登出时间
- 会话时长
- 认证状态

#### 4. Shell 历史分析

**支持的历史类型**：
- Bash：`~/.bash_history`
- Zsh：`~/.zsh_history`
- Fish：`~/.config/fish/`
- 通用历史文件

**提取的数据**：
- 执行的命令
- 时间戳（如果启用 HISTTIMEFORMAT）
- 命令序号

#### 5. Cron 任务分析

**数据源**：
- `/etc/crontab`：系统级 cron 任务
- `/etc/cron.d/*`：cron.d 目录
- `/var/spool/cron/crontabs/*`：用户 cron 任务
- `systemd` 服务：systemd 单元文件

**提取的数据**：
- 任务调度规则（分、时、日、月、周）
- 执行命令
- 任务所有者
- 启用状态

#### 6. SSH 密钥分析

**数据源**：
- `~/.ssh/authorized_keys`：公钥
- `~/.ssh/known_hosts`：已知主机
- `/etc/ssh/sshd_config`：服务配置

**提取的数据**：
- 公钥指纹和类型
- 主机密钥和 IP
- SSH 配置选项

### 边界与限制

**功能边界**：
- ❌ 不支持 LUKS 加密分区（需先解密）
- ❌ 不解析二进制系统日志（journalctl 输出）
- ❌ 不恢复已删除的日志文件
- ❌ 不支持所有发行版的特殊格式

**已知限制**：
| 限制 | 影响 | 缓解方法 |
|------|------|----------|
| 需要 root 权限 | 某些文件无法访问 | 使用镜像挂载 |
| 日志轮转 | 历史日志可能丢失 | 检查轮转配置 |
| 加密数据 | 无法读取密钥哈希 | 记录加密状态 |

## 3. 模块使用的库

### 依赖库清单

| 库名称 | 版本 | 用途 |
|--------|------|------|
| **SQLite3** | 3.35.0+ | 日志数据库解析 |

## 4. 模块实现方式

### 核心类

```cpp
class LinuxFilesAnalyzer {
public:
    LinuxFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager);

    // 初始化
    bool initialize();

    // 主分析入口
    void analyzeLinuxData();

    // 系统日志分析
    void analyzeSystemLogs();

    // 用户账户分析
    void analyzeUserAccounts();

    // 登录历史分析
    void analyzeLoginHistory();

    // Shell 历史分析
    void analyzeShellHistory();

    // Cron 任务分析
    void analyzeCronJobs();

    // SSH 密钥分析
    void analyzeSSHKeys();

    // 网络配置分析
    void analyzeNetworkConfig();

private:
    std::string imagePath_;
    DatabaseManager* dbManager_;
    std::unique_ptr<LinuxAnalysisDatabase> linuxDb_;
    std::unique_ptr<FileExtractor> fileExtractor_;
};
```

### 解析器类

**LinuxLogParser**：系统日志解析
**LinuxUserParser**：用户和认证数据解析
**LinuxHistoryParser**：Shell 历史解析

## 5. API 调用

### C++ API

```cpp
#include "analyzers/LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"

// 创建分析器
auto dbManager = std::make_unique<DatabaseManager>("evidence_raw.db");
LinuxFilesAnalyzer analyzer("linux_server.dd", dbManager.get());

// 初始化
if (!analyzer.initialize()) {
    std::cerr << "初始化失败" << std::endl;
    return 1;
}

// 执行分析
analyzer.analyzeLinuxData();

std::cout << "Linux 分析完成" << std::endl;
```

### 命令行 API

```bash
# Linux 分析（通过主程序）
./forensic_analyzer linux_server.dd --linux-analyze

# 输出数据库：linux_server_linux.db
```

### REST API

```bash
# 系统日志查询
curl "http://localhost:8080/api/forensics/linux/logs?task_id=task_abc123&limit=1000"

# 用户账户
curl "http://localhost:8080/api/forensics/linux/users?task_id=task_abc123"

# 登录记录
curl "http://localhost:8080/api/forensics/linux/logins?task_id=task_abc123&username=root"

# Cron 任务
curl "http://localhost:8080/api/forensics/linux/cron-jobs?task_id=task_abc123"
```

## 6. 二次开发

### 添加新的日志解析器

```cpp
// LinuxJournalParser.h
#pragma once
#include <string>
#include <vector>

struct JournalEntry {
    int64_t timestamp;
    std::string hostname;
    std::string process;
    int pid;
    std::string message;
    std::string priority;
};

class LinuxJournalParser {
public:
    static std::vector<JournalEntry> parseJournalLogs(
        const std::string& journalPath);

private:
    static int64_t parseBootTime(const std::string& timestamp);
};
```

## 7. 其他

### 测试

```bash
cd build
# 运行单元测试
ctest -R linux -V
```

### 配置

**相关配置**：
- Linux 镜像路径
- 数据库输出路径

### 故障排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| 日志文件未找到 | 路径不正确 | 检查镜像文件系统 |
| 权限被拒绝 | 需要 root 权限 | 使用 sudo 或镜像挂载 |
| 解析失败 | 日志格式不兼容 | 检查 Linux 发行版 |

### 相关模块

- **[FileExtractor](../core/FileExtractor.md)** - 文件提取
- **[AndroidAnalyzer](../analyzers/AndroidAnalyzer.md)** - Android 分析（Linux 基础）

### 参考资源

- [Linux 文件系统层次结构](https://en.wikipedia.org/wiki/Filesystem_Hierarchy_Standard)
- [Syslog 协议](https://en.wikipedia.org/wiki/Syslog)

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
