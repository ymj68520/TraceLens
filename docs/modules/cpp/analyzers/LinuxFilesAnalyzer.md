# LinuxFilesAnalyzer 模块文档

## 1. 模块概述

LinuxFilesAnalyzer 是一个全面的 Linux 取证分析模块，从磁盘镜像中提取并分析 Linux 系统的各类日志、配置和安全数据。模块采用**解析器 + 分析引擎 + 数据库**三层架构，支持 30+ 种日志类型和 6 种高级分析能力。

**输出数据库**：`<image>_linux.db`

## 2. 模块结构

```
src/analyzers/LinuxFilesAnalyzer/
├── LinuxFilesAnalyzer.h              # 主入口头文件
├── Common/
│   ├── LinuxDataTypes.h              # 30+ 数据结构定义
│   ├── LinuxAnalyzerDeclarations.h   # 前向声明
│   └── LinuxAnalyzerErrors.h         # 错误码定义
├── Core/
│   └── LinuxFilesAnalyzerCore.cpp    # 核心分析流程
├── Parsers/                          # 日志解析器
│   ├── LinuxLogParser.h/cpp          # 系统日志 (syslog, auth.log, kern.log)
│   ├── LinuxUserParser.h/cpp         # 用户账户 (/etc/passwd, /etc/shadow)
│   ├── LinuxHistoryParser.h/cpp      # Shell 历史 (bash, zsh, fish)
│   ├── ExtendedHistoryParser.h/cpp   # 扩展 Shell 历史
│   ├── JournalParser.h/cpp           # systemd Journal 二进制日志
│   ├── AuditdAggregator.h/cpp        # auditd 日志聚合
│   ├── CompressedLogParser.h/cpp     # 压缩和轮转日志 (.gz, .bz2, .xz)
│   ├── TimestampNormalizer.h/cpp     # 跨源时间戳标准化
│   ├── USBMountParser.h/cpp          # USB 设备挂载记录
│   ├── CloudParser.h/cpp             # 云元数据 (AWS, GCP, Azure)
│   ├── Security/                     # 安全分析解析器
│   │   ├── SetuidAnalyzer.h/cpp      # Setuid/Setgid 文件分析
│   │   ├── CapabilityAnalyzer.h/cpp  # Linux Capabilities 分析
│   │   ├── SELinuxAnalyzer.h/cpp     # SELinux 状态和 AVC 拒绝
│   │   ├── AppArmorParser.h/cpp      # AppArmor 配置文件和违规
│   │   └── SecurityBypassAnalyzer.h/cpp  # 安全绕过检测
│   ├── Container/                    # 容器解析器
│   │   ├── DockerContainerParser.h/cpp   # Docker 容器/镜像/卷
│   │   ├── PodmanParser.h/cpp            # Podman 容器和 Pod
│   │   └── ContainerRuntimeLogParser.h/cpp  # 容器运行时日志
│   ├── WebServer/                    # Web 服务器解析器
│   │   ├── ApacheParser.h/cpp        # Apache 访问日志和虚拟主机
│   │   ├── NginxParser.h/cpp         # Nginx 访问日志和 Server Block
│   │   └── MiddlewareLogParser.h/cpp # 中间件日志和 ModSecurity
│   ├── Database/DatabaseLogParser.h/cpp      # 数据库服务日志
│   ├── EmailVPN/EmailVPNLogParser.h/cpp      # 邮件和 VPN 日志
│   ├── FirewallSecurity/FirewallSecurityLogParser.h/cpp  # 防火墙和安全产品日志
│   ├── PackageManager/PackageManagerLogParser.h/cpp      # 包管理器日志
│   └── Detail/                       # 解析器实现细节
│       ├── LinuxLogParser.cpp
│       ├── LinuxUserParser.cpp
│       ├── LinuxNetworkParser.cpp
│       └── LinuxSystemParser.cpp
├── Analysis/                         # 高级分析引擎
│   ├── LogCorrelationEngine.h/cpp    # 日志关联引擎
│   ├── AnomalyDetector.h/cpp         # 异常行为检测
│   ├── LogTamperingDetector.h/cpp    # 日志篡改检测
│   ├── PersistenceDetector.h/cpp     # 持久化机制检测
│   ├── RuleEngine.h/cpp              # 规则引擎 (Sigma/IOC/ATT&CK)
│   ├── TimelineReconstructor.h/cpp   # 统一时间线重建
│   └── AccountSSH/AccountSSHAnalyzer.h/cpp  # 账户和 SSH 安全分析
└── Database/
    ├── LinuxAnalysisDatabase.h/cpp   # 数据库操作 (40+ 实体类型)
    ├── LinuxQueryBuilder.h           # 类型安全查询构建器
    └── Detail/                       # 数据库操作实现 (18 个文件)
```

## 3. 解析器详解

### 3.1 系统日志解析器 (LinuxLogParser)

**数据源**：
| 日志文件 | 路径 | 说明 |
|----------|------|------|
| syslog | `/var/log/syslog` | 系统服务日志 |
| auth.log / secure | `/var/log/auth.log` | 认证和安全日志 |
| kern.log | `/var/log/kern.log` | 内核消息 |
| messages | `/var/log/messages` | 通用系统消息 |
| dpkg.log | `/var/log/dpkg.log` | 包管理日志 |
| dmesg | `/var/log/dmesg` | 内核启动消息 |

**提取数据结构** (`LinuxLogEntry`)：
- `logFile` - 日志来源文件
- `timestamp` / `unixTimestamp` - 原始时间戳和 Unix 时间戳
- `hostname` - 主机名
- `process` / `pid` - 进程名和 PID
- `message` - 日志消息内容
- `level` - 日志级别 (INFO, WARNING, ERROR, CRITICAL)
- `facility` - Syslog 设施 (auth, daemon, kern, local0-7)
- `normalizedTime` - 标准化时间戳
- `provenance` - 证据溯源信息

### 3.2 用户账户解析器 (LinuxUserParser)

**数据源**：
- `/etc/passwd` - 用户账户信息
- `/etc/shadow` - 密码哈希和策略
- `/etc/group` - 组信息

**提取数据结构** (`LinuxUserInfo`)：
- 用户名、UID、GID
- GECOS 字段（全名/描述）
- 主目录和登录 Shell
- 密码哈希（从 shadow 文件）
- 密码策略：最后更改日期、最大/最小有效期、警告天数、不活跃天数
- 账户过期日期、锁定状态、系统账户标识

**组信息** (`LinuxGroupInfo`)：组名、GID、成员列表

### 3.3 登录历史解析器

**数据源**：
- `/var/log/wtmp` - 成功登录记录
- `/var/log/btmp` - 失败登录尝试
- `/var/log/lastlog` - 最后登录时间

**提取数据结构** (`LinuxLoginRecord`)：
- 用户名、终端设备 (tty/pts)
- 远程主机 IP
- 登录/登出时间
- 登录类型：login, ssh, console, reboot, shutdown
- 认证状态（成功/失败）
- PID

### 3.4 Shell 历史解析器 (LinuxHistoryParser + ExtendedHistoryParser)

**支持的 Shell**：
| Shell | 历史文件 | 时间戳支持 |
|-------|----------|------------|
| Bash | `~/.bash_history` | HISTTIMEFORMAT |
| Zsh | `~/.zsh_history` | 扩展格式 |
| Fish | `~/.config/fish/fish_history` | 内置时间戳 |
| Sh | `~/.sh_history` | 无 |

**提取数据结构** (`ShellHistoryEntry`)：
- 用户名、Shell 类型
- 执行的命令
- 时间戳（如果可用）
- 行号和来源文件路径

### 3.5 Journal 解析器 (JournalParser)

解析 systemd Journal 二进制日志格式。

**提取数据结构** (`JournalEntry`)：
- 时间戳、主机名、进程名、PID
- 消息内容、优先级
- 设施、单元名称
- Boot ID（用于关联同一启动会话）

**附加结构**：
- `BootSession` - 启动会话信息
- `JournalAnomaly` - Journal 异常（缺失条目、时间跳跃等）

### 3.6 审计日志聚合器 (AuditdAggregator)

聚合多行 auditd 日志为完整事件。

**提取数据结构** (`AggregatedAuditEvent`)：
- 审计序列号
- 事件类型 (SYSCALL, USER_AUTH, USER_CMD 等)
- 主体（用户/进程）和客体
- 执行的操作和结果
- 原始消息

### 3.7 压缩日志解析器 (CompressedLogParser)

解析轮转和压缩的日志文件。

**支持格式**：`.gz`, `.bz2`, `.xz`, `.zip`

**检测内容**：
- 轮转日志文件列表 (RotatedLogFile)
- 轮转时间线和完整性

### 3.8 USB 挂载解析器 (USBMountParser)

从系统日志和 udev 规则中提取 USB 设备挂载记录。

### 3.9 云元数据解析器 (CloudParser)

检测云环境元数据：
- AWS (EC2 实例元数据)
- GCP (实例元数据)
- Azure (实例元数据)

### 3.10 时间戳标准化器 (TimestampNormalizer)

将不同来源的时间戳统一转换为 UTC Unix 时间戳。

**标准化时间戳结构** (`NormalizedTimestamp`)：
- 原始时间戳字符串
- 标准化 UTC Unix 时间戳
- 时区来源 (file/system/inferred/utc)
- 时间戳置信度 (0-100)
- Boot ID（用于单调时间戳）
- 推断年份（syslog 无年份时推断）
- 时钟偏移标志

---

## 4. 安全分析解析器

### 4.1 Setuid/Setgid 分析器 (SetuidAnalyzer)

扫描文件系统中的 Setuid/Setgid 文件。

**提取数据结构** (`SetuidFileInfo`)：
- 文件路径、所有者、组
- 权限模式
- Setuid/Setgid 标志
- 文件大小、MD5/SHA256 哈希
- 可疑标志和原因

### 4.2 Capabilities 分析器 (CapabilityAnalyzer)

分析 Linux 文件 Capabilities。

**提取数据结构** (`FileCapability`)：
- 文件路径
- Capabilities 列表
- Capability 集合
- 继承标志
- 可疑标志

### 4.3 SELinux 分析器 (SELinuxAnalyzer)

**提取内容**：
- SELinux 状态 (`SELinuxStatus`)：启用状态、模式、策略名
- AVC 拒绝记录 (`SELinuxAVCDenial`)：源/目标上下文、对象类、权限

### 4.4 AppArmor 解析器 (AppArmorParser)

**提取内容**：
- AppArmor 配置 (`AppArmorProfile`)：配置名、模式、允许/拒绝路径
- AppArmor 违规 (`AppArmorViolation`)：操作、目标路径、可执行文件

### 4.5 安全绕过分析器 (SecurityBypassAnalyzer)

检测安全机制绕过尝试。

---

## 5. 容器解析器

### 5.1 Docker 解析器 (DockerContainerParser)

**提取数据结构**：
| 结构 | 内容 |
|------|------|
| `DockerContainerInfo` | 容器 ID、镜像、命令、状态、挂载、端口、网络模式 |
| `DockerImageInfo` | 镜像 ID、标签、大小、层 ID |
| `DockerVolumeInfo` | 卷名、挂载点、驱动、关联容器 |

### 5.2 Podman 解析器 (PodmanParser)

**提取数据结构**：
| 结构 | 内容 |
|------|------|
| `PodmanContainerInfo` | 容器 ID、镜像、Pod 名、Rootless 标志、状态 |
| `PodmanPodInfo` | Pod 名、ID、关联容器、状态 |

### 5.3 容器运行时日志解析器 (ContainerRuntimeLogParser)

**提取数据结构**：
- `DockerLogEntry` - Docker 守护进程日志
- `CRILogEntry` - CRI (Container Runtime Interface) 日志
- `KubernetesPodLogEntry` - Kubernetes Pod 日志
- `ContainerSecurityFinding` - 容器安全发现

---

## 6. Web 服务器解析器

### 6.1 Apache 解析器 (ApacheParser)

**提取数据结构**：
| 结构 | 内容 |
|------|------|
| `ApacheAccessLogEntry` | 时间戳、远程 IP、方法、URL、状态码、响应大小、Referer、User-Agent、虚拟主机 |
| `ApacheVHostConfig` | 服务器名、文档根、别名、SSL 证书路径 |

### 6.2 Nginx 解析器 (NginxParser)

**提取数据结构**：
| 结构 | 内容 |
|------|------|
| `NginxAccessLogEntry` | 时间戳、远程 IP、方法、URL、状态码、响应大小、请求时间、上游地址 |
| `NginxServerBlock` | 服务器名、根目录、Location、SSL 证书、上游配置 |

### 6.3 中间件日志解析器 (MiddlewareLogParser)

**提取数据结构**：
- `WebErrorLogEntry` - Web 错误日志
- `MiddlewareLogEntry` - 应用中间件日志
- `ModSecurityAuditEntry` - ModSecurity WAF 审计日志

---

## 7. 其他服务解析器

### 7.1 数据库日志解析器 (DatabaseLogParser)

**提取数据结构**：
- `DatabaseLogEntry` - 数据库服务日志 (MySQL, PostgreSQL, MongoDB 等)
- `DatabaseSecurityFinding` - 数据库安全发现

### 7.2 邮件/VPN 日志解析器 (EmailVPNLogParser)

**提取数据结构**：
- `EmailLogEntry` - 邮件服务日志 (Postfix, Sendmail, Dovecot)
- `VPNLogEntry` - VPN 服务日志 (OpenVPN, WireGuard)
- `EmailSecurityFinding` / `VPNSecurityFinding` - 安全发现

### 7.3 防火墙/安全产品日志解析器 (FirewallSecurityLogParser)

**提取数据结构**：
- `FirewallLogEntry` - 防火墙日志 (iptables/nftables)
- `SecurityProductLogEntry` - 安全产品日志 (Fail2Ban, CrowdSec)
- `SecurityProductFinding` - 安全产品发现

### 7.4 包管理器日志解析器 (PackageManagerLogParser)

**提取数据结构**：
- `PackageLogEntry` - 包管理器操作日志 (apt, yum, dnf)
- `SuspiciousPackageFinding` - 可疑包安装发现
- `PackageInfo` - 已安装包信息

### 7.5 网络配置解析器

**提取数据结构** (`NetworkConnection`)：
- 协议 (tcp/tcp6/udp/udp6)
- 本地/远程地址和端口
- 连接状态 (LISTEN, ESTABLISHED 等)
- UID 和 Socket inode

### 7.6 系统服务解析器

**提取数据结构** (`SystemdServiceInfo`)：
- 服务名、描述
- 加载状态、活跃状态、子状态
- 单元文件路径、ExecStart 命令
- 运行用户、启用状态

### 7.7 内核模块解析器

**提取数据结构** (`KernelModuleInfo`)：
- 模块名、大小、使用计数
- 依赖模块列表
- 模块文件路径

### 7.8 防火墙规则解析器

**提取数据结构** (`FirewallRule`)：
- 链 (INPUT/OUTPUT/FORWARD)、表 (filter/nat/mangle)
- 协议、源/目标地址和端口
- 动作 (ACCEPT/DROP/REJECT)

### 7.9 浏览器配置解析器

**提取数据结构** (`LinuxBrowserProfile`)：
- 浏览器类型 (Chrome/Chromium/Firefox/Opera/Brave)
- 配置名和路径
- 所属用户

---

## 8. 高级分析引擎

### 8.1 日志关联引擎 (LogCorrelationEngine)

跨日志源关联事件，构建攻击链。

**核心能力**：
- `correlateEvents()` - 关联认证事件、命令执行、网络活动
- `buildAttackChains()` - 构建攻击链（侦察 → 利用 → 提权 → 数据窃取）
- `detectAnomalies()` - 检测异常模式

**关联规则**：
- 登录与后续命令关联
- 网络连接与进程关联
- 文件访问与用户活动关联

**输出结构**：
- `CorrelatedEvent` - 关联事件（时间范围、事件类型、发起用户/进程、严重度）
- `AttackChain` - 攻击链（链 ID、攻击类型、事件序列、置信度）

### 8.2 异常检测器 (AnomalyDetector)

检测 6 类异常行为：

| 异常类型 | 检测方法 |
|----------|----------|
| 暴力破解 (Brute Force) | 短时间内大量失败登录 |
| 提权 (Privilege Escalation) | sudo/su 异常使用模式 |
| 数据窃取 (Data Exfiltration) | 大量数据传输到外部 |
| 持久化 (Persistence) | 异常的启动/定时任务 |
| 异常登录 (Unusual Login) | 非工作时间/异常位置登录 |
| 可疑进程 (Suspicious Process) | 异常进程行为模式 |

**输出结构** (`Anomaly`)：
- 异常类型和子类型
- 描述和缓解建议
- 严重度 (1-5) 和置信度 (0.0-1.0)
- 证据 ID 列表

### 8.3 日志篡改检测器 (LogTamperingDetector)

检测 10 种日志篡改类型：

| 篡改类型 | 枚举值 | 说明 |
|----------|--------|------|
| 日志清除 | `LOG_CLEARED` | 文件大小骤降或内容重置 |
| 轮转缺失 | `ROTATION_GAP` | 缺少轮转日志文件 |
| 时间倒退 | `TIME_REVERSAL` | 时间戳逆序 |
| 时间窗口缺失 | `TIME_WINDOW_GAP` | 大段时间无日志 |
| 跨日志矛盾 | `CROSS_LOG_INCONSISTENCY` | wtmp 与 auth.log 不一致 |
| Journal 缺失 | `JOURNAL_MISSING` | Journal 条目缺失 |
| 审计中断 | `AUDITD_INTERRUPTED` | 审计日志异常中断 |
| 重复时间戳 | `DUPLICATE_TIMESTAMPS` | 大量条目共享同一时间戳 |
| 时间戳异常 | `TIMESTAMP_ANOMALY` | 时间戳不符合预期模式 |
| 格式突变 | `LOG_PATTERN_BREAK` | 日志格式突然改变 |

**输出结构** (`TamperingFinding`)：
- 篡改类型和严重度 (INFO/LOW/MEDIUM/HIGH/CRITICAL)
- 描述和受影响时间段
- 证据和关联文件

### 8.4 持久化机制检测器 (PersistenceDetector)

检测 13 种 Linux 持久化机制：

| 持久化类型 | 枚举值 | 检测路径 |
|------------|--------|----------|
| rc.local | `RC_LOCAL` | `/etc/rc.local` |
| init.d 脚本 | `INIT_D_SCRIPT` | `/etc/init.d/*` |
| Shell 配置 | `SHELL_PROFILE` | `/etc/profile`, `~/.bashrc`, `~/.profile` |
| SSH 授权密钥 | `AUTHORIZED_KEYS` | `~/.ssh/authorized_keys` |
| LD_PRELOAD | `LD_SO_PRELOAD` | `/etc/ld.so.preload` |
| Sudoers | `SUDOERS` | `/etc/sudoers`, `/etc/sudoers.d/*` |
| udev 规则 | `UDEV_RULE` | `/etc/udev/rules.d/*.rules` |
| Polkit 规则 | `POLKIT_RULE` | `/etc/polkit-1/rules.d/*.rules` |
| xinetd 服务 | `XINETD_SERVICE` | `/etc/xinetd.d/*` |
| Systemd 定时器 | `SYSTEMD_TIMER` | `*.timer` 单元 |
| at 任务 | `AT_JOB` | `/var/spool/at/*` |
| Cron 任务 | `CRON_JOB` | `/etc/crontab`, `/etc/cron.d/*` |
| Systemd 服务 | `SYSTEMD_SERVICE` | systemd 单元文件 |

**风险评估** (`PersistenceRisk`)：
- `LOW` - 标准系统持久化
- `MEDIUM` - 异常但可能合法
- `HIGH` - 可疑模式
- `CRITICAL` - 已知恶意模式

**输出结构** (`PersistenceEntry`)：
- 持久化类型和风险级别
- 文件路径、条目名、命令、参数
- 所有者、调度计划
- 启用状态、可疑标志和原因

### 8.5 规则引擎 (RuleEngine)

基于规则的攻击链分析，支持 MITRE ATT&CK 映射。

**规则类型**：
| 类型 | 说明 |
|------|------|
| Sigma | 模式匹配日志事件 |
| IOC | 妥协指标匹配 |
| ATT&CK | MITRE ATT&CK 技术映射 |
| Custom | 自定义规则 |

**核心方法**：
- `evaluateSigmaRules()` - 评估 Sigma 规则
- `matchIOCs()` - 匹配 IOC
- `mapAnomaliesToATTCK()` - 将异常映射到 ATT&CK 技术
- `buildAttackChains()` - 从规则匹配构建攻击链

**输出结构** (`RuleMatch`)：
- 规则 ID、类型、名称
- 匹配的事件 ID 列表
- ATT&CK 技术 ID (如 T1059.004)
- 攻击阶段（战术）
- 严重度和置信度

### 8.6 时间线重建器 (TimelineReconstructor)

从多个 Linux 数据源重建统一时间线。

**核心方法**：
- `buildTimeline()` - 构建完整时间线
- `mergeEvents()` - 合并并按时间排序事件
- `identifyGaps()` - 识别可疑时间线间隙

**输出结构**：
- `Timeline` - 包含事件列表和间隙列表
- `LinuxTimelineEvent` - 时间线事件（时间戳、来源类型、事件类型、描述、用户、IP）
- `TimelineGap` - 时间线间隙（起止时间、持续时间、是否可疑）

### 8.7 账户/SSH 安全分析器 (AccountSSHAnalyzer)

分析账户和 SSH 配置的安全性。

**输出结构**：
- `AccountSecurityFinding` - 账户安全发现
- `SSHSecurityFinding` - SSH 安全发现

---

## 9. 数据库架构

### LinuxAnalysisDatabase

提供 40+ 实体类型的线程安全数据库操作，支持类型安全查询构建器 (`QueryBuilder`)。

**核心实体操作**：

| 实体类别 | 操作实体 |
|----------|----------|
| 日志 | LogEntry, JournalEntry, AuditLog, AuditEvent |
| 用户 | UserInfo, GroupInfo, LoginRecord |
| Shell | ShellHistory |
| 定时任务 | CronJob |
| SSH | SSHKey, SSHKnownHost |
| 包管理 | PackageInfo, PackageLog |
| 网络 | NetworkConnection |
| 系统 | SystemdService, KernelModule, FirewallRule |
| 安全 | SetuidFile, FileCapability, SELinuxStatus, SELinuxAVCDenial, AppArmorProfile, AppArmorViolation |
| 容器 | DockerContainer, DockerImage, DockerVolume, PodmanContainer, PodmanPod, ContainerLog, CRILog |
| Web | ApacheAccessLog, ApacheVHost, NginxAccessLog, NginxServerBlock, WebErrorLog, MiddlewareLog, ModSecurityLog |
| 服务 | DatabaseLog, EmailLog, VPNLog, FirewallLog, SecurityProductLog |
| 浏览器 | BrowserProfile |
| 分析结果 | CorrelatedEvent, AttackChain, TimelineEvent, TimelineGap, Anomaly |
| 持久化 | PersistenceEntry |
| Journal | BootSession, JournalAnomaly |
| 安全发现 | AccountSecurityFinding, SSHSecurityFinding, DatabaseSecurityFinding, EmailSecurityFinding, VPNSecurityFinding, ContainerSecurityFinding, SecurityProductFinding, SuspiciousPackageFinding |
| 篡改检测 | TamperingFinding |

**安全查询**：所有查询方法均提供 `Safe` 后缀版本，使用 `QueryBuilder` 防止 SQL 注入。旧版字符串查询方法已标记为 `[[deprecated]]`。

---

## 10. 数据结构概览

### 证据溯源 (EvidenceProvenance)

所有解析结果均包含证据溯源信息：

```cpp
struct EvidenceProvenance {
    std::string parserName;      // 解析器名称
    std::string parserVersion;   // 解析器版本
    std::string sourceFile;      // 源文件路径
    int64_t sourceOffset;        // 源文件字节偏移
    int64_t sourceLine;          // 源文件行号
    int64_t sourceInode;         // 源文件 inode
    std::string sourceHash;      // 源文件哈希
    std::string parseError;      // 解析错误信息
    std::string rawRecord;       // 原始记录
    int confidence;              // 置信度 0-100
};
```

### 关键数据结构一览

| 结构体 | 用途 | 关键字段 |
|--------|------|----------|
| `LinuxLogEntry` | 系统日志 | logFile, timestamp, process, pid, level, facility |
| `LinuxUserInfo` | 用户账户 | username, uid, gid, shell, passwordHash, accountExpires |
| `LinuxLoginRecord` | 登录记录 | username, terminal, remoteHost, loginTime, loginType |
| `ShellHistoryEntry` | Shell 历史 | username, shellType, command, timestamp |
| `CronJobEntry` | Cron 任务 | username, schedule, command, cronType |
| `SSHKeyInfo` | SSH 密钥 | username, keyType, publicKey, comment |
| `PackageInfo` | 已安装包 | name, version, packageManager, installTime |
| `NetworkConnection` | 网络连接 | protocol, localAddress, remoteAddress, state |
| `SystemdServiceInfo` | Systemd 服务 | serviceName, activeState, execStart, isEnabled |
| `KernelModuleInfo` | 内核模块 | moduleName, size, usedCount, state |
| `FirewallRule` | 防火墙规则 | chain, protocol, source, destination, action |
| `LinuxAuditLogEntry` | 审计日志 | type, subject, object, action, result |
| `DockerContainerInfo` | Docker 容器 | containerId, imageName, state, mounts, ports |
| `ApacheAccessLogEntry` | Apache 日志 | remoteIp, method, url, statusCode, userAgent |
| `NginxAccessLogEntry` | Nginx 日志 | remoteIp, method, url, statusCode, requestTime |
| `SetuidFileInfo` | Setuid 文件 | filePath, permissions, isSuspicious |
| `SELinuxStatus` | SELinux 状态 | isEnabled, mode, policyName |
| `AppArmorProfile` | AppArmor 配置 | profileName, mode, allowedPaths, deniedPaths |
| `PersistenceEntry` | 持久化条目 | type, risk, command, isEnabled, isSuspicious |
| `CorrelatedEvent` | 关联事件 | eventType, initiatingUser, severity |
| `AttackChain` | 攻击链 | chainId, attackType, events, confidence |
| `Anomaly` | 异常 | anomalyType, severity, confidence, evidenceIds |

---

## 11. API 调用

### C++ API

```cpp
#include "analyzers/LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"

auto dbManager = std::make_unique<DatabaseManager>("evidence_raw.db");
LinuxFilesAnalyzer analyzer("linux_server.dd", dbManager.get());

if (!analyzer.initialize()) {
    std::cerr << "初始化失败" << std::endl;
    return 1;
}

analyzer.analyzeLinuxData();
```

### 命令行

```bash
./forensic_analyzer linux_server.dd --linux-analyze
# 输出：linux_server_linux.db
```

### REST API

Linux 分析结果通过取证分析 API 端点查询，需要 `task_id` 参数。详见 [RouteReference.md](../network/routes/RouteReference.md)。

---

## 12. 故障排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| Journal 解析失败 | systemd 版本不兼容 | 检查镜像 systemd 版本 |
| 容器数据缺失 | Docker/Podman 未安装 | 确认容器运行时 |
| 时间戳不一致 | 时区配置差异 | 使用 TimestampNormalizer |
| 权限被拒绝 | 需要 root 权限 | 使用 sudo 或镜像挂载 |
| 压缩日志跳过 | 缺少解压库 | 安装 zlib/bzip2/xz |

---

## 13. 相关模块

- **[LinuxLLMAnalysisService](../network/LinuxLLMAnalysisService.md)** - Linux 取证 LLM 分析服务
- **[EventCorrelationEngine](../core/EventCorrelationEngine.md)** - 通用事件关联引擎
- **[WindowsFilesAnalyzer](./WindowsFilesAnalyzer.md)** - Windows 取证分析（类似架构）
- **[AndroidAnalyzer](./AndroidAnalyzer.md)** - Android 取证分析

---

**最后更新**: 2026-05-19
**维护者**: ymj68520
