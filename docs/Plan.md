# Linux 泛日志解析增强：Vibe Coding 计划书

参考现有 `LinuxFilesAnalyzer` 功能说明进行整理，目标是在现有 Linux 取证分析框架基础上，按优先级补齐日志解析与证据预处理能力，并确保**所有文件、日志、配置、结构化结果最终都必须进入 AI 分析流程**。预处理、解析、结构化、关联分析只是先后顺序问题，最终统一交给 AI 分析，整个AI分析流程需要参考现有文件的分析流程，最终需要gtraphti集成。

---

## 1. 总体目标

完善 Linux 泛日志类型解析能力，重点增强：

1. `systemd-journald` 二进制日志解析；
2. 压缩与轮转日志解析；
3. 时间戳归一化；
4. auditd 多行事件聚合；
5. 日志篡改检测；
6. 持久化机制检测扩展；
7. Web / 容器 / 包管理器 / 云主机 / 数据库 / 中间件等日志类型扩展；
8. 所有分析结果最终进入 AI 分析流程。

---

## 2. 核心原则

### 2.1 所有文件最终必须走 AI 分析

所有类型的文件与解析结果都必须进入 AI 分析流程，包括：

* 原始日志文件；
* 压缩日志文件；
* 轮转日志文件；
* 二进制日志；
* 配置文件；
* 账户文件；
* Shell 历史；
* Web 日志；
* 容器日志；
* auditd 日志；
* systemd journal；
* 数据库日志；
* 云主机日志；
* 中间件日志；
* 结构化后的数据库记录；
* 时间线事件；
* 异常检测结果；
* 关联事件结果。

预处理阶段只负责让 AI 更好理解数据，包括：

* 解压；
* 格式识别；
* 二进制解析；
* 字段提取；
* 时间戳归一化；
* 多行事件聚合；
* 去重；
* 关联；
* 时间线排序。

最终所有数据必须进入 AI 分析。

---

## 3. 开发顺序

## Phase 0：状态口径调整

### 目标

修正文档中“100% 完成 / Production Ready”与已知限制之间的不一致。

### 开发任务

1. 调整实现状态描述；
2. 明确当前系统属于“核心框架完成，仍需增强泛日志解析能力”；
3. 标注以下能力为待增强：

   * journald；
   * 压缩轮转日志；
   * capabilities；
   * `/proc` 实时进程；
   * USB 设备历史；
   * Web error log；
   * 容器 runtime log；
   * auditd 事件聚合。

### AI 分析流程

状态调整后，现有所有解析结果仍保持进入 AI 分析流程。

---

## Phase 1：压缩与轮转日志预处理

### 目标

补齐历史日志解析能力，避免遗漏攻击窗口。

### 覆盖对象

```text
auth.log.1
auth.log.2.gz
syslog.1
syslog.3.gz
messages-YYYYMMDD
secure-YYYYMMDD.gz
audit.log.1
audit.log.2.xz
*.bz2
*.zst
```

### 开发任务

1. 自动枚举日志轮转文件；
2. 识别 `.gz`、`.xz`、`.bz2`、`.zst`；
3. 支持流式解压；
4. 保留原始文件名；
5. 保留压缩状态；
6. 保留文件 inode、mtime、ctime；
7. 解析失败时记录 error artifact；
8. 将解压后的内容交给对应日志解析器；
9. 将原始文件、解压内容、结构化结果全部交给 AI 分析。

### AI 分析流程

```text
压缩/轮转日志
→ 解压与枚举
→ 格式识别
→ 结构化解析
→ 时间戳归一化
→ 入库
→ AI 分析
```

---

## Phase 2：systemd-journald 二进制日志解析

### 目标

补齐现代 Linux 系统中的核心日志来源。

### 覆盖对象

```text
/var/log/journal/<machine-id>/*.journal
/run/log/journal/*/*.journal
用户级 journal
journal export 文件
```

### 重点字段

```text
_SYSTEMD_UNIT
_USER_UNIT
_PID
_UID
_GID
_COMM
_EXE
_CMDLINE
_TRANSPORT
_BOOT_ID
MESSAGE
MESSAGE_ID
SYSLOG_IDENTIFIER
```

### 开发任务

1. 识别 journal 文件；
2. 解析二进制 journal；
3. 提取 systemd unit；
4. 提取 PID、UID、GID；
5. 提取进程名、可执行路径、命令行；
6. 提取 boot ID；
7. 按 boot ID 重建启动周期；
8. 检测 journal vacuum、缺失、截断；
9. 检测时间跳变；
10. 将 journal 原始事件和结构化事件交给 AI 分析。

### AI 分析流程

```text
journal 文件
→ 二进制解析
→ 字段提取
→ boot ID 关联
→ 时间戳归一化
→ 入库
→ AI 分析
```

---

## Phase 3：时间戳归一化

### 目标

提升时间线重建和跨日志关联的准确性。

### 需要处理的问题

1. syslog 无年份；
2. syslog 无时区；
3. dmesg 相对启动时间；
4. auditd epoch 秒加小数；
5. journal realtime 与 monotonic 时间；
6. wtmp/btmp 结构差异；
7. 容器 RFC3339 纳秒时间；
8. Web 日志时区；
9. clock skew；
10. 时间倒退。

### 开发任务

新增统一时间模型：

```text
original_timestamp
normalized_utc_timestamp
timezone_source
timestamp_confidence
boot_id
monotonic_timestamp
inferred_year
clock_skew_flag
```

### AI 分析流程

```text
原始时间戳
→ 时间戳识别
→ 时区推断
→ 年份推断
→ UTC 归一化
→ 置信度标注
→ 入库
→ AI 分析
```

---

## Phase 4：auditd 多行事件聚合

### 目标

将 auditd 的多行事件聚合成完整行为事件。

### 覆盖类型

```text
SYSCALL
EXECVE
CWD
PATH
PROCTITLE
USER_AUTH
USER_ACCT
AVC
```

### 聚合依据

```text
msg=audit(timestamp:serial)
```

### 开发任务

1. 按 serial 聚合同一 audit 事件；
2. 提取 syscall；
3. 提取 exe；
4. 提取 cwd；
5. 提取 argv；
6. 提取 proctitle；
7. 提取 path 列表；
8. 提取 auid、uid、euid、ses；
9. 提取 success、exit；
10. 提取 tty；
11. 提取 source addr；
12. 将聚合事件交给 AI 分析。

### AI 分析流程

```text
audit.log
→ 单行解析
→ serial 聚合
→ 行为事件生成
→ 时间戳归一化
→ 入库
→ AI 分析
```

---

## Phase 5：日志篡改检测

### 目标

识别日志清理、截断、缺失、时间异常和交叉证据不一致。

### 检测内容

1. 日志清空；
2. 日志截断；
3. 轮转断层；
4. 时间倒退；
5. 时间空窗；
6. wtmp/btmp 与 auth.log 不一致；
7. journal 缺失；
8. auditd 中断；
9. 时间线异常空隙。

### 开发任务

1. 增加日志连续性检测；
2. 增加时间线 gap 检测；
3. 增加跨日志一致性检测；
4. 增加篡改疑点 artifact；
5. 将篡改疑点交给 AI 分析。

### AI 分析流程

```text
日志集合
→ 连续性检测
→ 交叉一致性检测
→ 可疑空窗生成
→ 入库
→ AI 分析
```

---

## Phase 6：持久化机制检测增强

### 目标

在 cron 和 systemd 基础上扩展更多持久化入口。

### 覆盖对象

```text
/etc/rc.local
/etc/init.d/*
/etc/profile
/etc/bash.bashrc
~/.bashrc
~/.profile
~/.ssh/authorized_keys
/etc/ld.so.preload
/etc/sudoers
/etc/sudoers.d/*
udev rules
polkit rules
xinetd/inetd
systemd timer
at/batch 任务
```

### 开发任务

1. 解析 rc.local；
2. 解析 init.d；
3. 解析 shell profile；
4. 解析 authorized_keys；
5. 解析 ld.so.preload；
6. 解析 sudoers；
7. 解析 udev rules；
8. 解析 polkit rules；
9. 解析 xinetd/inetd；
10. 解析 systemd timer；
11. 解析 at/batch；
12. 将所有持久化候选项交给 AI 分析。

### AI 分析流程

```text
持久化相关文件
→ 规则解析
→ 命令提取
→ 可疑项标注
→ 时间线关联
→ 入库
→ AI 分析
```

---

## Phase 7：Web 与中间件日志增强

### 目标

在 Apache/Nginx access log 基础上补齐 error log 和常见中间件日志。

### 覆盖对象

```text
Apache error.log
Nginx error.log
PHP-FPM logs
Tomcat catalina.out
Jetty logs
Node.js pm2 logs
Gunicorn logs
uWSGI logs
ModSecurity audit.log
```

### 开发任务

1. 解析 Apache error.log；
2. 解析 Nginx error.log；
3. 解析 PHP-FPM 日志；
4. 解析 Tomcat 日志；
5. 解析 Jetty 日志；
6. 解析 PM2 日志；
7. 解析 Gunicorn 日志；
8. 解析 uWSGI 日志；
9. 解析 ModSecurity audit.log；
10. 支持自定义 JSON access log；
11. 支持 `X-Forwarded-For`；
12. 将所有 Web 与中间件日志交给 AI 分析。

### AI 分析流程

```text
Web/中间件日志
→ 格式识别
→ 字段解析
→ 攻击特征提取
→ 时间戳归一化
→ 入库
→ AI 分析
```

---

## Phase 8：容器日志增强

### 目标

补齐 Docker、Podman、containerd、Kubernetes 场景中的运行时日志。

### 覆盖对象

```text
/var/lib/docker/containers/<id>/<id>-json.log
/var/log/containers/*.log
/var/log/pods/*/*.log
/var/log/kubelet.log
/var/log/crio/pods/
/var/lib/containerd/
```

### 开发任务

1. 解析 Docker json-file 日志；
2. 解析 containerd / CRI 日志；
3. 解析 Kubernetes Pod 日志；
4. 解析 kubelet 日志；
5. 解析 CRI-O 痕迹；
6. 提取 Pod、container、namespace、image；
7. 提取 restartCount；
8. 关联容器配置；
9. 检测 privileged、hostPID、hostNetwork、hostPath、Docker socket 挂载；
10. 将容器日志和容器配置交给 AI 分析。

### AI 分析流程

```text
容器日志/配置
→ runtime 识别
→ 日志解析
→ 配置关联
→ 逃逸风险标注
→ 入库
→ AI 分析
```

---

## Phase 9：包管理器日志增强

### 目标

补齐软件安装、卸载、更新和安全软件移除痕迹。

### 覆盖对象

```text
/var/log/apt/history.log
/var/log/apt/term.log
/var/log/dpkg.log
/var/log/yum.log
/var/log/dnf.log
/var/log/zypper.log
/var/log/pacman.log
snap logs
flatpak 安装记录
```

### 开发任务

1. 解析 apt history；
2. 解析 apt term；
3. 解析 dpkg log；
4. 解析 yum log；
5. 解析 dnf log；
6. 解析 zypper log；
7. 解析 pacman log；
8. 解析 snap；
9. 解析 flatpak；
10. 识别攻击工具安装；
11. 识别安全软件卸载；
12. 将包管理器日志交给 AI 分析。

### AI 分析流程

```text
包管理器日志
→ 软件操作解析
→ 安装/卸载时间线
→ 可疑软件标注
→ 入库
→ AI 分析
```

---

## Phase 10：账户、权限与 SSH 增强

### 目标

增强账户异常、权限异常和 SSH 横向移动分析。

### 覆盖对象

```text
/etc/passwd
/etc/shadow
/etc/group
/etc/sudoers
/etc/sudoers.d/*
/etc/ssh/sshd_config
/etc/ssh/ssh_config
~/.ssh/config
~/.ssh/known_hosts
~/.ssh/authorized_keys
~/.ssh/authorized_keys2
~/.ssh/id_rsa
~/.ssh/id_ed25519
```

### 检测内容

1. UID 0 非 root 用户；
2. 空密码；
3. shadow/passwd 不一致；
4. sudoers 高危规则；
5. wheel/sudo/docker/lxd 组成员异常；
6. 过期账户重新启用；
7. SSH key 新增时间与登录时间关联；
8. `PermitRootLogin yes`；
9. `PasswordAuthentication yes`；
10. `AuthorizedKeysCommand`；
11. `ForceCommand`；
12. `Match User`；
13. `ProxyCommand`；
14. 私钥权限异常；
15. known_hosts 横向移动线索。

### AI 分析流程

```text
账户/权限/SSH 文件
→ 结构化解析
→ 异常规则检测
→ 登录记录关联
→ 时间线关联
→ 入库
→ AI 分析
```

---

## Phase 11：数据库、邮件、VPN、DNS、防火墙与安全产品日志

### 目标

扩展更多服务器侧日志来源。

### 覆盖对象

#### 数据库日志

```text
MySQL
MariaDB
PostgreSQL
MongoDB
Redis
```

#### 邮件日志

```text
mail.log
maillog
exim4
postfix
dovecot
```

#### VPN 日志

```text
OpenVPN
WireGuard
PPP
```

#### DHCP / DNS / 网络管理日志

```text
NetworkManager
dhcpd
named
bind
unbound
dnsmasq
```

#### 防火墙与安全产品日志

```text
ufw.log
firewalld
fail2ban.log
clamav
rkhunter
chkrootkit
ossec
aide
```

### 开发任务

1. 解析数据库日志；
2. 解析邮件日志；
3. 解析 VPN 日志；
4. 解析 DHCP/DNS 日志；
5. 解析 NetworkManager 日志；
6. 解析 UFW/firewalld 日志；
7. 解析 fail2ban 日志；
8. 解析 ClamAV 日志；
9. 解析 rkhunter/chkrootkit 日志；
10. 解析 OSSEC/AIDE 日志；
11. 将所有日志交给 AI 分析。

### AI 分析流程

```text
服务日志
→ 类型识别
→ 字段解析
→ 异常提取
→ 时间线关联
→ 入库
→ AI 分析
```

---

## Phase 12：USB、挂载、桌面与云主机日志

### 目标

补齐工作站、云主机和外设相关取证痕迹。

### 覆盖对象

#### USB / 外设

```text
kern.log
syslog
journal kernel records
udev logs
```

#### 文件系统与挂载

```text
/etc/fstab
/proc/mounts 导出
systemd mount units
mount 记录
```

#### 桌面环境

```text
lightdm
gdm
Xorg.0.log
~/.xsession-errors
```

#### 云主机

```text
cloud-init.log
cloud-init-output.log
waagent.log
amazon-ssm-agent.log
google-guest-agent.log
```

### 开发任务

1. 提取 USB VID/PID；
2. 提取 USB 序列号；
3. 提取插入/拔出时间；
4. 提取挂载点；
5. 提取文件系统 UUID；
6. 解析 fstab；
7. 解析 mount units；
8. 解析桌面登录日志；
9. 解析 cloud-init；
10. 解析 SSM / guest agent 日志；
11. 将所有结果交给 AI 分析。

### AI 分析流程

```text
USB/挂载/桌面/云日志
→ 事件解析
→ 时间线关联
→ 用户行为关联
→ 入库
→ AI 分析
```

---

## Phase 13：Shell、开发工具与凭据痕迹增强

### 目标

扩展 Shell 历史之外的交互式工具历史与开发运维痕迹。

### 覆盖对象

```text
~/.python_history
~/.mysql_history
~/.psql_history
~/.rediscli_history
~/.sqlite_history
~/.lesshst
~/.viminfo
~/.local/share/nano/search_history
.git/logs/HEAD
.git/logs/refs/*
~/.gitconfig
~/.docker/config.json
~/.kube/config
~/.aws/credentials
~/.config/gcloud/*
~/.azure/*
```

### 开发任务

1. 解析 Python 历史；
2. 解析 MySQL 历史；
3. 解析 PostgreSQL 历史；
4. 解析 Redis CLI 历史；
5. 解析 SQLite 历史；
6. 解析 less/vim/nano 痕迹；
7. 解析 Git reflog；
8. 解析 Docker config；
9. 解析 kube config；
10. 解析 AWS/GCloud/Azure 配置；
11. 将所有文件和结果交给 AI 分析。

### AI 分析流程

```text
历史/开发/凭据文件
→ 类型识别
→ 敏感字段提取
→ 行为重建
→ 时间线关联
→ 入库
→ AI 分析
```

---

## Phase 14：安全绕过与动态链接配置分析

### 目标

增强用户态 rootkit、环境变量持久化和动态库注入检测。

### 覆盖对象

```text
/etc/ld.so.preload
/etc/ld.so.conf
/etc/ld.so.conf.d/*
/etc/profile
/etc/environment
~/.bashrc
~/.profile
```

### 开发任务

1. 解析 `ld.so.preload`；
2. 解析动态链接配置；
3. 解析环境变量；
4. 解析 shell 启动文件；
5. 检测 LD_PRELOAD；
6. 检测命令劫持；
7. 检测动态库注入；
8. 将所有配置和检测结果交给 AI 分析。

### AI 分析流程

```text
动态链接/环境配置
→ 配置解析
→ 可疑项检测
→ 持久化关联
→ 入库
→ AI 分析
```

---

## Phase 15：证据可信度与原始记录保留

### 目标

提升取证结果的可复核性。

### 新增字段

```text
confidence
parser_name
parser_version
source_file
source_offset
source_inode
source_hash
parse_error
normalized_fields_json
raw_record
```

### 开发任务

1. 所有解析器保留原始记录；
2. 所有解析器记录 source_file；
3. 支持 byte offset；
4. 支持 line number；
5. 支持 parser version；
6. 支持 parse error；
7. 支持 confidence；
8. 支持 source hash；
9. 将原始记录和结构化记录都交给 AI 分析。

### AI 分析流程

```text
原始证据
→ 结构化解析
→ 可信度标注
→ 原文保留
→ 入库
→ AI 分析
```

---

## Phase 16：规则引擎与攻击链分析

### 目标

增强异常检测的可配置性和攻击链表达能力。

### 覆盖能力

```text
Sigma
YARA
IOC
ATT&CK 技术标签
攻击链阶段
```

### 攻击链阶段

```text
Initial Access
Execution
Persistence
Privilege Escalation
Defense Evasion
Credential Access
Discovery
Lateral Movement
Collection
Exfiltration
C2
```

### 开发任务

1. 支持 Sigma 规则；
2. 支持 YARA 规则；
3. 支持 IOC 匹配；
4. 支持 ATT&CK 标签；
5. 将异常检测结果映射到攻击链；
6. 将攻击链结果交给 AI 分析。

### AI 分析流程

需要参考现有的文件AI分析流程。

---

## 4. 最终统一 AI 分析流程

所有 Phase 最终统一进入以下流程：

```text
文件发现
→ 文件类型识别
→ 解压/二进制解析/文本解析
→ 字段结构化
→ 时间戳归一化
→ 事件聚合
→ 异常检测
→ 时间线重建
→ 关联分析
→ 入库
→ AI 分析
→ Graphitihg摄取
→ 报告生成
```

---

## 5. 开发优先级

| 优先级 |    Phase | 内容                        |
| --- | -------: | ------------------------- |
| P0  |  Phase 1 | 压缩与轮转日志预处理                |
| P0  |  Phase 2 | systemd-journald 二进制日志解析  |
| P0  |  Phase 3 | 时间戳归一化                    |
| P0  |  Phase 4 | auditd 多行事件聚合             |
| P0  |  Phase 5 | 日志篡改检测                    |
| P1  |  Phase 6 | 持久化机制检测增强                 |
| P1  |  Phase 7 | Web 与中间件日志增强              |
| P1  |  Phase 8 | 容器日志增强                    |
| P1  |  Phase 9 | 包管理器日志增强                  |
| P1  | Phase 10 | 账户、权限与 SSH 增强             |
| P2  | Phase 11 | 数据库、邮件、VPN、DNS、防火墙与安全产品日志 |
| P2  | Phase 12 | USB、挂载、桌面与云主机日志           |
| P2  | Phase 13 | Shell、开发工具与凭据痕迹增强         |
| P2  | Phase 14 | 安全绕过与动态链接配置分析             |
| P2  | Phase 15 | 证据可信度与原始记录保留              |
| P2  | Phase 16 | 规则引擎与攻击链分析                |

---

## 6. 验收标准

1. 所有新增文件类型都能被发现；
2. 所有压缩和轮转日志都能进入解析流程；
3. 所有二进制日志在预处理后能进入结构化流程；
4. 所有原始记录都能保留；
5. 所有结构化结果都能入库；
6. 所有解析失败结果都能形成 error artifact；
7. 所有事件都能参与时间线重建；
8. 所有异常结果都能参与关联分析；
9. 所有文件、日志、配置、事件、异常、时间线和关联结果最终都必须进入 AI 分析流程；
10. AI 分析只存在先后顺序差异，不存在是否分析的差异。
