# linux.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h` + `linux_analysis_sql_crud.h` + `linux_analysis_sql_llm.h`）

> linux.db 是全项目最大的平台库（73 张表，全部 `linux_` 前缀）：files.db 之上的**Linux 语义观点**（DatabaseSchema.md 派生链：files.db → linux.db）。SERVER_CLOUD 场景下任务目录里的 `oss.db` 也是本文件这批 `linux_*` 表（同名不同物，见 [OssDB.md](./OssDB.md)）。两组 CREATE 块：`CREATE_ALL_TABLES`（44 表，`linux_analysis_sql_tables.h:10-783`）+ `CREATE_LINUX_ANALYSIS_PROGRESS_TABLE`（29 表，`:785-1578`，虽叫 PROGRESS 但装的是 Phase 2~11 的新表）。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `LinuxFilesAnalyzer` 的 `LinuxAnalysisDatabase`（建表执行两个 CREATE 块；行数据写入如 `Database/Detail/LinuxLogOperations.cpp:29`、`LinuxUserOperations.cpp:28` 等内联/常量 INSERT）；部分新表（journal/usb/mount/cloud/extended_history/security_bypass/rule_matches）由各 Phase 解析器写入 |
| 谁读 | HTTP 查询路由、Web 前端 Linux 页、`LinuxLLMAnalysisService`（`LinuxLLMAnalysisService_Database.cpp` 按 ArtifactType 分发 pending SELECT，`:157-168`） |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/linux.db`；SERVER_CLOUD 场景任务里的 `oss.db`；CLI 集成模式并入 files.db 的 `linux_artifacts` |

## 表清单总表（73 张，9 分组）

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `linux_log_entries` | 系统基础 | syslog/通用日志行 | 15 |
| `linux_users` | 系统基础 | /etc/passwd+shadow 合并 | 19 |
| `linux_groups` | 系统基础 | /etc/group | 4 |
| `linux_login_records` | 系统基础 | wtmp/btmp/lastlog 登录 | 13 |
| `linux_shell_history` | 系统基础 | bash/zsh 历史 | 12 |
| `linux_cron_jobs` | 系统基础 | cron 计划任务 | 14 |
| `linux_ssh_keys` | 系统基础 | authorized_keys/公钥 | 11 |
| `linux_ssh_known_hosts` | 系统基础 | known_hosts | 10 |
| `linux_packages` | 系统基础 | 包管理器清单 | 14 |
| `linux_network_connections` | 系统基础 | /proc/net 活动连接 | 14 |
| `linux_systemd_services` | 系统基础 | systemd 单元状态 | 14 |
| `linux_kernel_modules` | 系统基础 | lsmod/模块信息 | 11 |
| `linux_firewall_rules` | 安全与合规 | iptables 规则 | 14 |
| `linux_audit_logs` | 安全与合规 | auditd 原始行 | 13 |
| `linux_audit_events` | 安全与合规 | 按 serial 聚合的审计事件 | 40 |
| `linux_tampering_findings` | 安全与合规 | 日志防篡改发现 | 15 |
| `linux_setuid_files` | 安全与合规 | setuid/setgid 文件 | 11 |
| `linux_capabilities` | 安全与合规 | 文件 capabilities | 6 |
| `linux_selinux_status` | 安全与合规 | SELinux 全局状态 | 5 |
| `linux_selinux_avc_denials` | 安全与合规 | SELinux AVC 拒绝 | 7 |
| `linux_apparmor_profiles` | 安全与合规 | AppArmor profile | 7 |
| `linux_apparmor_violations` | 安全与合规 | AppArmor 违规 | 7 |
| `linux_security_bypass` | 安全与合规 | 安全机制绕过发现 | 21 |
| `linux_rule_matches` | 安全与合规 | 取证规则命中（ATT&CK 映射） | 22 |
| `linux_account_security_findings` | 安全与合规 | 账户安全发现 | 15 |
| `linux_ssh_security_findings` | 安全与合规 | SSH 安全发现 | 18 |
| `linux_database_security_findings` | 安全与合规 | 数据库安全发现 | 17 |
| `linux_email_security_findings` | 安全与合规 | 邮件安全发现 | 15 |
| `linux_vpn_security_findings` | 安全与合规 | VPN 安全发现 | 16 |
| `linux_security_product_findings` | 安全与合规 | 安全产品发现 | 16 |
| `linux_container_security_findings` | 安全与合规 | 容器安全发现 | 18 |
| `linux_browser_profiles` | 浏览器与桌面 | 浏览器 profile 注册 | 11 |
| `linux_browser_history` | 浏览器与桌面 | 历史记录 | 17 |
| `linux_browser_cookies` | 浏览器与桌面 | Cookie | 16 |
| `linux_browser_downloads` | 浏览器与桌面 | 下载 | 18 |
| `linux_browser_bookmarks` | 浏览器与桌面 | 书签 | 15 |
| `linux_recent_documents` | 浏览器与桌面 | XDG 最近文档 | 11 |
| `linux_trash_entries` | 浏览器与桌面 | XDG 回收站 | 11 |
| `linux_desktop_files` | 浏览器与桌面 | .desktop 启动项 | 14 |
| `linux_docker_containers` | 容器与云 | Docker 容器 | 10 |
| `linux_docker_images` | 容器与云 | Docker 镜像 | 5 |
| `linux_docker_volumes` | 容器与云 | Docker 卷 | 5 |
| `linux_podman_containers` | 容器与云 | Podman 容器 | 6 |
| `linux_podman_pods` | 容器与云 | Podman pod | 5 |
| `linux_container_logs` | 容器与云 | 容器运行时日志 | 19 |
| `linux_cloud_logs` | 容器与云 | 云厂商 agent 日志 | 24 |
| `linux_apache_access_logs` | Web 与中间件 | Apache 访问日志 | 11 |
| `linux_apache_vhosts` | Web 与中间件 | Apache 虚拟主机 | 6 |
| `linux_nginx_access_logs` | Web 与中间件 | Nginx 访问日志 | 11 |
| `linux_nginx_server_blocks` | Web 与中间件 | Nginx server 块 | 8 |
| `linux_web_error_logs` | Web 与中间件 | Web 错误日志 | 18 |
| `linux_middleware_logs` | Web 与中间件 | 中间件应用日志 | 18 |
| `linux_modsecurity_logs` | Web 与中间件 | WAF 审计日志 | 18 |
| `linux_database_logs` | 服务日志 | MySQL/PG/Mongo/Redis 日志 | 19 |
| `linux_email_logs` | 服务日志 | Postfix/Exim/Dovecot 日志 | 21 |
| `linux_vpn_logs` | 服务日志 | OpenVPN/WireGuard 日志 | 21 |
| `linux_firewall_logs` | 服务日志 | UFW/firewalld 日志 | 21 |
| `linux_security_product_logs` | 服务日志 | fail2ban/ClamAV 等日志 | 19 |
| `linux_package_logs` | 服务日志 | apt/yum/dnf 操作日志 | 19 |
| `linux_suspicious_packages` | 服务日志 | 可疑包发现 | 16 |
| `linux_journal_entries` | 服务日志 | systemd journal（含证据溯源） | 33 |
| `linux_correlated_events` | 时间线与关联 | 跨源相关事件 | 9 |
| `linux_attack_chains` | 时间线与关联 | 攻击链 | 7 |
| `linux_timeline_events` | 时间线与关联 | 归一时间线事件 | 9 |
| `linux_timeline_gaps` | 时间线与关联 | 时间线断档 | 7 |
| `linux_anomalies` | 时间线与关联 | 异常发现 | 10 |
| `linux_journal_anomalies` | 时间线与关联 | journal 异常 | 10 |
| `linux_persistence_entries` | 持久化与外设 | 持久化机制 | 22 |
| `linux_boot_sessions` | 持久化与外设 | 开机会话 | 5 |
| `linux_usb_events` | 持久化与外设 | USB 插拔事件 | 26 |
| `linux_mount_entries` | 持久化与外设 | 挂载事件 | 25 |
| `linux_extended_history` | 持久化与外设 | Python/MySQL/Git 等扩展历史 | 23 |
| `linux_analysis_progress` | 进度 | LLM 进度（task 主键） | 8 |

LLM 5 列组（`llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, llm_model_used TEXT`）直接建在大多数表里（区别于 android.db 的 ALTER 追加）；下文表格用"LLM5"代指。

## 逐表字段说明

### 分组一：系统基础（12 张）

Linux 侧"五 W"的原料层：账户（users/groups）、进出（login_records/shell_history）、定时（cron）、远程（ssh_*）、软件（packages）、网络（network_connections）、服务（systemd）、内核（kernel_modules）加日志（log_entries）。这是入侵检测横向铺开的底座。

#### linux_log_entries（`linux_analysis_sql_tables.h:12-28`，写入 `linux_analysis_sql_crud.h:14-17`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| log_file | TEXT | — | 来源日志文件（证据回溯） |
| timestamp | TEXT | — | 原始时间戳串（syslog 原样） |
| unix_timestamp | INTEGER | — | 归一后的 unix 秒（排序/检索用；有索引） |
| hostname | TEXT | — | 主机名 |
| process | TEXT | — | 进程/服务名 |
| pid | INTEGER | — | 进程号 |
| message | TEXT | — | 正文 |
| level | TEXT | — | 级别 |
| facility | TEXT | — | syslog facility |
| LLM5 | — | — | 5 列组 |

索引：`idx_log_timestamp(unix_timestamp)`、`idx_log_file(log_file)`、`idx_log_llm_analyzed(llm_analyzed_at)`（`:29-31`）。

#### linux_users（`:34-56`，写入 `crud.h:19-24` 15 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | UNIQUE | 用户名 |
| uid / gid | INTEGER | — | UID/GID |
| full_name | TEXT | — | GECOS |
| home_directory | TEXT | — | 主目录 |
| shell | TEXT | — | 登录 shell（nologin vs bash 是线索） |
| password_hash | TEXT | — | shadow 哈希（空/`!`/`*` 语义各异） |
| last_password_change | INTEGER | — | chage 天数（源格式） |
| password_max_age / password_min_age / password_warn_days / inactive_days / account_expires | INTEGER | — | 密码策略五件套 |
| is_locked | INTEGER | — | 1 = 锁定 |
| is_system_account | INTEGER | — | 1 = 系统账户（UID<1000） |
| LLM5 | — | — | 5 列组 |

索引：`idx_users_uid(uid)`、`idx_users_llm_analyzed`（`:57-58`）。

#### linux_groups（`:61-66`，写入 `crud.h:26-27`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| group_name | TEXT | UNIQUE | 组名 |
| gid | INTEGER | — | GID |
| members | TEXT | — | 成员清单（逗号串） |

#### linux_login_records（`:69-84`，写入 `crud.h:29-32`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 登录账户 |
| terminal | TEXT | — | tty/pts/:0 |
| remote_host | TEXT | — | 远程来源（SSH 场景关键） |
| login_time / logout_time | INTEGER | — | 进/出时刻 |
| login_type | TEXT | — | LOGIN/LOGOUT/FAIL/CRASH |
| is_success | INTEGER | — | 成败 |
| pid | INTEGER | — | 会话进程 |
| LLM5 | — | — | 5 列组 |

索引：`idx_login_time`、`idx_login_user`、`idx_login_llm_analyzed`（`:85-87`）。

#### linux_shell_history（`:90-103`，写入 `crud.h:34-37`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 所属用户 |
| shell_type | TEXT | — | bash/zsh/fish |
| command | TEXT | — | 命令行 |
| timestamp | INTEGER | — | 执行时刻（需要 HISTTIMEFORMAT 才有） |
| line_number | INTEGER | — | 历史文件行号 |
| history_file | TEXT | — | 来源文件 |
| LLM5 | — | — | 5 列组 |

索引：`idx_history_user`、`idx_history_time`、`idx_history_llm_analyzed`（`:104-106`）。

#### linux_cron_jobs（`:109-125`，写入 `crud.h:39-42`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 运行账户（crontab 属主） |
| minute / hour / day_of_month / month / day_of_week | TEXT | — | 五段 cron 时间域（原样字符串） |
| command | TEXT | — | 命令 |
| cron_file | TEXT | — | 来源文件 |
| cron_type | TEXT | — | user/system/daily... |
| LLM5 | — | — | 5 列组 |

索引：`idx_cron_llm_analyzed`（`:126`）。

#### linux_ssh_keys（`:129-142`，写入 `crud.h:44-47`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 所属用户 |
| key_type | TEXT | — | ssh-rsa/ed25519... |
| public_key | TEXT | — | 公钥内容 |
| key_path | TEXT | — | 文件路径（authorized_keys/id_*.pub） |
| comment | TEXT | — | 注释（常含生成者邮箱） |
| options | TEXT | — | key 选项（command= 强制命令 = 后门高发区） |
| LLM5 | — | — | 5 列组 |

#### linux_ssh_known_hosts（`:146-158`，写入 `crud.h:49-52`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 所属用户 |
| hostname | TEXT | — | 曾连主机（可被哈希） |
| key_type | TEXT | — | 密钥类型 |
| public_key | TEXT | — | 主机公钥 |
| is_hashed | INTEGER | — | 1 = 主机名已哈希 |
| LLM5 | — | — | 5 列组 |

#### linux_packages（`:162-177`，写入 `crud.h:54-57`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| name / version / architecture | TEXT | — | 包名/版本/架构 |
| install_time | INTEGER | — | 安装时刻 |
| package_manager | TEXT | — | dppm/rpm/pacman |
| status | TEXT | — | 安装状态 |
| description | TEXT | — | 描述 |
| maintainer | TEXT | — | 维护者 |
| LLM5 | — | — | 5 列组 |

索引：`idx_pkg_name`、`idx_pkg_llm_analyzed`（`:178-179`）。

#### linux_network_connections（`:182-199`，写入 `crud.h:59-62`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| protocol | TEXT | — | tcp/tcp6/udp |
| local_address / local_port | TEXT/INTEGER | — | 本端 |
| remote_address / remote_port | TEXT/INTEGER | — | 对端（外联检测核心列） |
| state | TEXT | — | LISTEN/ESTABLISHED... |
| uid | INTEGER | — | 属主 UID |
| inode | INTEGER | — | socket inode（**与文件 inode 无关**，但可与进程匹配） |
| process / pid | TEXT/INTEGER | — | 归属进程 |
| LLM5 | — | — | 5 列组 |

#### linux_systemd_services（`:203-219`，写入 `crud.h:64-67`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| service_name | TEXT | — | 单元名 |
| description | TEXT | — | 描述 |
| load_state / active_state / sub_state | TEXT | — | systemd 三态 |
| unit_file | TEXT | — | 单元文件路径 |
| exec_start | TEXT | — | 启动命令 |
| user | TEXT | — | 运行账户 |
| is_enabled | INTEGER | — | 开机启用 |
| LLM5 | — | — | 5 列组 |

#### linux_kernel_modules（`:223-237`，写入 `crud.h:69-72`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| module_name | TEXT | — | 模块名 |
| size | INTEGER | — | 字节 |
| used_count | INTEGER | — | 引用计数 |
| used_by | TEXT | — | 依赖者列表 |
| state | TEXT | — | Live/Loading... |
| filename | TEXT | — | .ko 路径 |
| LLM5 | — | — | 5 列组 |

### 分组二：安全与合规（19 张）

两组子家族：**原始证据**（audit_logs、selinux_*、apparmor_*、setuid、capabilities、firewall_rules）与**加工结论**（*_findings、tampering、security_bypass、rule_matches）。findings 家族共享一个模板：`finding_type + severity + description + evidence + source_file + parser_name/version + LLM5`，差异只在上下文列。

#### linux_firewall_rules（`:240-256`，写入 `crud.h:74-77`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| chain / table_name | TEXT | — | iptables 链/表 |
| protocol | TEXT | — | 协议 |
| source / destination | TEXT | — | 源/目的 |
| source_port / destination_port | INTEGER | — | 端口 |
| action | TEXT | — | ACCEPT/DROP/REJECT |
| rule_spec | TEXT | — | 完整规则串 |
| LLM5 | — | — | 5 列组 |

#### linux_audit_logs（`:260-275`，写入 `crud.h:79-82`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻（unix 秒） |
| serial_number | INTEGER | — | audit serial（同事件多行同号） |
| type | TEXT | — | 记录类型（SYSCALL/PATH...） |
| message | TEXT | — | 原始消息 |
| subject / object / action / result | TEXT | — | 主/客体/动作/结果（浅解析） |
| LLM5 | — | — | 5 列组 |

索引：`idx_audit_time`、`idx_audit_type`、`idx_audit_llm_analyzed`（`:276-278`）。

#### linux_audit_events（`:281-324`，SQL 注释："Aggregated Audit Events (multi-line events grouped by serial)"）

auditd 一条事件横跨多行，本表按 serial 聚合成单行——全库列数最多的表（40 列）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| event_id | TEXT | UNIQUE | 聚合事件标识 |
| timestamp | INTEGER | — | 时刻 |
| serial_number | INTEGER | — | audit serial |
| syscall | INTEGER | — | 系统调用号 |
| syscall_name | TEXT | — | 调用名（execve/open...） |
| success | INTEGER | — | 成败 |
| exit_code | INTEGER | — | 返回码 |
| pid / ppid | INTEGER | — | 进程/父进程 |
| uid / gid / euid / egid / auid | INTEGER | — | 五重身份（auid=审计登录 ID，提权检测关键） |
| session_id | INTEGER | — | 会话 |
| exe / comm / terminal | TEXT | — | 可执行/命令名/终端 |
| audit_key | TEXT | — | audit 规则 key |
| argv | TEXT | — | 参数串 |
| argc | INTEGER | — | 参数数 |
| cwd | TEXT | — | 工作目录 |
| proctitle | TEXT | — | 完整命令行 |
| auth_user / auth_op / auth_addr | TEXT | — | 认证三件套 |
| avc_action / avc_class / avc_permission | TEXT | — | AVC 三件套（SELinux 拒绝内嵌） |
| event_type | TEXT | — | 归类 |
| severity | INTEGER | — | 严重度 |
| path_list | TEXT | — | PATH 记录聚合 |
| raw_lines | TEXT | — | 原始行拼接 |
| parser_name / parser_version | TEXT | — | 解析器溯源 |
| source_file | TEXT | — | 来源文件 |
| LLM5 | — | — | 5 列组 |

索引 6 个（`:325-330`）：time/type/pid/auid/severity/llm_analyzed。

#### linux_tampering_findings（`:333-350`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| tampering_type | TEXT | NOT NULL | 篡改类型（清空/截断/时间倒流...） |
| severity | INTEGER | DEFAULT 0 | 严重度 |
| description | TEXT | — | 说明 |
| log_source | TEXT | — | 被篡改日志 |
| timestamp_start / timestamp_end | INTEGER | — | 窗口 |
| evidence | TEXT | — | 证据描述 |
| related_files | TEXT | — | 相关文件 |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引：type/severity/time/llm（`:351-354`）。

#### linux_setuid_files（`:635-648`，写入 `crud.h:197-200`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_path | TEXT | — | 路径 |
| owner / group_name | TEXT | — | 属主/组 |
| permissions | INTEGER | — | 权限位（数值） |
| is_setuid / is_setgid | INTEGER | — | 两个标志 |
| size | INTEGER | — | 字节 |
| md5_hash / sha256_hash | TEXT | — | 双哈希 |
| is_suspicious | INTEGER | — | 可疑标志 |
| suspicious_reason | TEXT | — | 原因 |

索引：`idx_setuid_file_path`、`idx_setuid_suspicious`（`:649-650`）。

#### linux_capabilities（`:653-660`，写入 `crud.h:202-205`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_path | TEXT | — | 路径 |
| capabilities | TEXT | — | cap 串（cap_net_raw+p...） |
| capability_set | TEXT | — | 集（effective/inheritable...） |
| is_inherited | INTEGER | — | 继承标志 |
| is_suspicious | INTEGER | — | 可疑标志 |

#### linux_selinux_status（`:665-671`，写入 `crud.h:207-210`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| is_enabled | INTEGER | — | 启用 |
| mode | TEXT | — | enforcing/permissive/disabled |
| policy_name | TEXT | — | 策略名 |
| current_mode | TEXT | — | 当前模式 |

#### linux_selinux_avc_denials（`:674-682`，写入 `crud.h:212-215`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| source_context / target_context | TEXT | — | 源/目标 SELinux 上下文 |
| object_class / permission | TEXT | — | 客体类/权限 |
| executable_path | TEXT | — | 触发可执行文件 |

#### linux_apparmor_profiles（`:687-695`，写入 `crud.h:217-220`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| profile_name | TEXT | — | profile 名 |
| mode | TEXT | — | enforce/complain |
| file_path | TEXT | — | profile 文件 |
| allowed_paths / denied_paths | TEXT | — | 允许/拒绝路径清单 |
| is_enabled | INTEGER | — | 启用 |

#### linux_apparmor_violations（`:700-708`，写入 `crud.h:222-225`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| profile / operation / target_path / executable / status | TEXT | — | 违规五要素 |

#### findings 家族（7 张同构表）

七张表共享一个模板（公共列见下），差异只在 2~4 个上下文列；逐表差异列：

**linux_account_security_findings**（`:1084-1100`）：

| 列 | 类型 | 含义 |
|----|------|------|
| username | TEXT | 涉事账户 |

**linux_ssh_security_findings**（`:1106-1124`）：

| 列 | 类型 | 含义 |
|----|------|------|
| username | TEXT | 涉事账户 |
| hostname | TEXT | 涉事主机 |
| key_type | TEXT | 密钥类型 |

**linux_database_security_findings**（`:1173-1190`）：

| 列 | 类型 | 含义 |
|----|------|------|
| db_type | TEXT | mysql/postgresql/... |
| username | TEXT | DB 账户 |
| client_addr | TEXT | 客户端地址 |

**linux_email_security_findings**（`:1227-1243`）：

| 列 | 类型 | 含义 |
|----|------|------|
| service_type | TEXT | postfix/exim/dovecot |
| client_addr | TEXT | 客户端地址 |

**linux_vpn_security_findings**（`:1279-1296`）：

| 列 | 类型 | 含义 |
|----|------|------|
| service_type | TEXT | openvpn/wireguard |
| username | TEXT | 账户 |
| client_addr | TEXT | 客户端地址 |

**linux_security_product_findings**（`:1361-1377`）：

| 列 | 类型 | 含义 |
|----|------|------|
| tool_type | TEXT | fail2ban/clamav/... |
| target_file | TEXT | 目标文件 |

**linux_container_security_findings**（`:1005-1026`，唯一 finding_type 带 NOT NULL 的成员）：

| 列 | 类型 | 含义 |
|----|------|------|
| container_id / container_name | TEXT | 容器定位 |
| pod_name / namespace | TEXT | pod 定位 |

公共列（七表一致）：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| finding_type | TEXT |（仅 container 表 NOT NULL）| 发现类型 |
| severity | TEXT | — | 严重度（**TEXT**，与 tampering 的 INTEGER 不一致） |
| description | TEXT | — | 说明 |
| evidence | TEXT | — | 证据 |
| source_file / file_path | TEXT | — | 来源文件（列名两种叫法） |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

各表索引形态一致：`idx_<缩写>_type(finding_type)`、`idx_<缩写>_severity(severity)`（部分多一列上下文索引）+ `idx_<缩写>_llm`。

#### linux_security_bypass（`:1517-1540`，Phase 10）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| finding_type | TEXT | — | 绕过类型（selinux/apparmor/sudo...） |
| severity | INTEGER | DEFAULT 0 | 严重度（**INTEGER**，与 findings 家族 TEXT 不一致） |
| file_path | TEXT | — | 涉事文件 |
| description | TEXT | — | 说明 |
| evidence | TEXT | — | 证据 |
| username | TEXT | — | 涉事用户 |
| is_confirmed | INTEGER | DEFAULT 0 | 1 = 已证实 |
| 溯源组 + confidence | — | — | source_offset/inode/hash、parse_error、raw_record（DEFAULT 100） |
| LLM5 | — | — | 5 列组 |

索引（`:1541-1544`）：finding_type/severity/username/llm。

#### linux_rule_matches（`:1547-1571`，Phase 12）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| rule_id / rule_type / rule_name | TEXT | — | 命中规则 |
| description | TEXT | — | 说明 |
| matched_event_ids | TEXT | — | 命中的事件 ID 清单 |
| attck_technique | TEXT | — | ATT&CK 技术编号（T1059...） |
| attack_stage | TEXT | — | 攻击阶段 |
| severity | INTEGER | DEFAULT 0 | 严重度 |
| confidence | REAL | DEFAULT 0.0 | 置信度 |
| 溯源组 | — | — | parser_name/version、source_file/offset/inode/hash、parse_error、raw_record |
| LLM5 | — | — | 5 列组（注意：无 confidence DEFAULT，本表 confidence 在溯源组前） |

索引 6 个（`:1572-1577`）：rule_id/rule_type/technique/stage/severity/llm。

### 分组三：浏览器与桌面（8 张）

Linux 桌面用户行为层：五大 browser_* 表（Chrome/Firefox profile 解析）+ XDG 三表（最近文档/回收站/desktop 项）。

#### linux_browser_profiles（`:357-369`，写入 `crud.h:84-87`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_type | INTEGER | — | 浏览器枚举（**INTEGER**，与下四表的 TEXT 不一致） |
| browser_name / profile_name / profile_path / username | TEXT | — | 浏览器/profile/路径/系统用户 |
| LLM5 | — | — | 5 列组 |

#### linux_browser_history（`:373-391`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_type | TEXT | — | 浏览器（**TEXT**） |
| profile_path | TEXT | — | 所属 profile（回连 profiles 表） |
| url / title | TEXT | — | 目标 |
| visit_time | INTEGER | — | 访问时刻 |
| visit_count / visit_duration | INTEGER | — | 计数/时长 |
| transition_type | TEXT | — | 跳转类型 |
| is_redirect | INTEGER | — | 重定向 |
| referrer | TEXT | — | 来源 |
| source_file | TEXT | — | 证据文件（History DB 路径） |
| LLM5 | — | — | 5 列组 |

索引：`idx_browser_history_time(visit_time)`、`idx_browser_history_url(url)`（`:392-393`）。

#### linux_browser_cookies（`:396-414`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_type / profile_path | TEXT | — | 归属 |
| host_key / name / value / path | TEXT | — | Cookie 四要素 |
| expires_utc | INTEGER | — | 过期（Chrome epoch 微秒） |
| is_secure / is_httponly / is_persistent | INTEGER | — | 标志 |
| source_file | TEXT | — | 证据文件 |
| LLM5 | — | — | 5 列组 |

索引：`idx_browser_cookies_host(host_key)`（`:415`）。

#### linux_browser_downloads（`:418-437`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_type / profile_path | TEXT | — | 归属 |
| url / target_path | TEXT | — | 来源/落盘 |
| start_time / end_time | INTEGER | — | 起止 |
| received_bytes / total_bytes | INTEGER | — | 进度字节 |
| state | INTEGER | — | 状态码（**INTEGER**，windows 侧同名列是 TEXT） |
| danger_type | TEXT | — | 危险类型 |
| mime_type | TEXT | — | MIME |
| source_file | TEXT | — | 证据文件 |
| LLM5 | — | — | 5 列组 |

#### linux_browser_bookmarks（`:441-456`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_type / profile_path | TEXT | — | 归属 |
| url / title / folder_path | TEXT | — | 书签 |
| date_added / date_last_used | INTEGER | — | 时刻 |
| source_file | TEXT | — | 证据文件 |
| LLM5 | — | — | 5 列组 |

#### linux_recent_documents（`:459-473`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 所属用户 |
| file_path | TEXT | — | 最近打开的文件路径 |
| uri | TEXT | — | XDG URI 形式 |
| mime_type | TEXT | — | MIME |
| modified_time | INTEGER | — | 访问时刻 |
| is_bookmarked | INTEGER | — | GTK 书签标志 |
| source_file | TEXT | — | 证据文件（recently-used.xbel） |
| LLM5 | — | — | 5 列组 |

#### linux_trash_entries（`:476-489`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| username | TEXT | — | 所属用户 |
| original_path | TEXT | — | 删除前路径 |
| deletion_time | INTEGER | — | 删除时刻 |
| trash_file_path | TEXT | — | 回收站内路径（~/.local/share/Trash） |
| file_size | INTEGER | — | 字节 |
| source_file | TEXT | — | 证据文件（trashinfo） |
| LLM5 | — | — | 5 列组 |

#### linux_desktop_files（`:492-508`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_path | TEXT | — | .desktop 文件路径 |
| name | TEXT | — | 显示名 |
| exec_command | TEXT | — | Exec= 命令（autostart 目录下即持久化指标） |
| icon | TEXT | — | 图标 |
| categories | TEXT | — | Categories= 分类 |
| mime_type | TEXT | — | MIME |
| is_hidden | INTEGER | — | NoDisplay= 标志 |
| is_autostart | INTEGER | — | 位于 autostart 目录 |
| source_file | TEXT | — | 证据文件 |
| LLM5 | — | — | 5 列组 |

### 分组四：容器与云（7 张）

Docker/Podman 的容器-镜像-卷三元组 + 运行时日志 + 云 agent 日志。容器逃逸检测的原料。

#### linux_docker_containers（`:511-523`，写入 `crud.h:152-155`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| container_id | TEXT | — | 容器 ID |
| image_name / image_tag | TEXT | — | 镜像:标签 |
| command | TEXT | — | 启动命令 |
| created_at | INTEGER | — | 创建 |
| state | TEXT | — | 状态 |
| mounts / ports | TEXT | — | 挂载/端口映射（序列化） |
| network_mode | TEXT | — | host/bridge...（host = 逃逸风险） |
| host_config | TEXT | — | HostConfig JSON |

索引：container_id/state（`:524-525`）。

#### linux_docker_images（`:528-535`，写入 `crud.h:157-160`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| image_id | TEXT | — | 镜像 ID |
| tags | TEXT | — | 标签清单 |
| size | INTEGER | — | 大小 |
| created_at | INTEGER | — | 创建 |
| layer_ids | TEXT | — | 层 ID 清单 |

索引：image_id（`:536`）。

#### linux_docker_volumes（`:539-547`，写入 `crud.h:162-165`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| volume_name / mountpoint / driver | TEXT | — | 卷名/挂载点/驱动 |
| created_at | INTEGER | — | 创建 |
| container_ids | TEXT | — | 使用者容器清单 |

索引：volume_name（`:547`）。

#### linux_podman_containers（`:550-558`，写入 `crud.h:167-170`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| container_id | TEXT | — | 容器 ID |
| image_name | TEXT | — | 镜像名 |
| pod_name | TEXT | — | 所属 pod |
| is_rootless | INTEGER | — | 1 = rootless 容器 |
| state | TEXT | — | 状态 |
| created_at | INTEGER | — | 创建 |

索引：`idx_podman_container_id(container_id)`、`idx_podman_container_state(state)`（`:559-560`）。

#### linux_podman_pods（`:563-572`，写入 `crud.h:172-175`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| pod_name | TEXT | — | pod 名 |
| pod_id | TEXT | — | pod ID |
| container_ids | TEXT | — | 成员容器清单 |
| state | TEXT | — | 状态 |
| created_at | INTEGER | — | 创建 |

索引：`idx_podman_pod_id(pod_id)`、`idx_podman_pod_state(state)`（`:571-572`）。

#### linux_container_logs（`:975-997`，Phase 8）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| stream | TEXT | — | stdout/stderr |
| message | TEXT | — | 正文 |
| container_id / container_name / pod_name / namespace | TEXT | — | 容器定位四件套 |
| runtime_type | TEXT | — | docker/podman/kube |
| file_path | TEXT | — | 日志文件（json-file 路径） |
| 溯源组 + LLM5 | — | — | parser/source/raw + 5 列 |

索引 5 个（`:998-1002`）。

#### linux_cloud_logs（`:1452-1478`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| provider | TEXT | — | 云厂商 |
| agent_name | TEXT | — | agent（cloudmonitor/aegis...） |
| event_type / level / module | TEXT | — | 事件/级别/模块 |
| message | TEXT | — | 正文 |
| instance_id / region / availability_zone | TEXT | — | 云资源定位 |
| 溯源组 + LLM5 | — | — | 完整证据溯源 + 5 列 |

索引 5 个（`:1479-1483`）。

### 分组五：Web 与中间件（7 张）

Apache/Nginx 访问日志 + 配置解析（vhosts/server blocks）+ 错误/中间件/WAF 日志。Web 入侵取证（webshell 落地链）的骨架。

#### linux_apache_access_logs（`:575-587`，写入 `crud.h:177-180`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| remote_ip | TEXT | — | 客户端 IP |
| method / url / http_version | TEXT | — | 请求行 |
| status_code / response_size | INTEGER | — | 状态/响应字节 |
| referer / user_agent | TEXT | — | 头 |
| vhost | TEXT | — | 命中的虚拟主机 |

索引：timestamp/remote_ip/status_code（`:588-590`）。

#### linux_apache_vhosts（`:593-600`，写入 `crud.h:182-185`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| server_name / document_root / server_aliases / ssl_certificates / config_file_path | TEXT | — | vhost 五要素 |

#### linux_nginx_access_logs（`:604-616`，写入 `crud.h:187-190`）

同 Apache 十列里的九列（无 http_version）+ `request_time REAL`（耗时秒）+ `upstream_addr TEXT`（上游）。索引 3（`:617-619`）。

#### linux_nginx_server_blocks（`:622-632`，写入 `crud.h:192-195`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| server_name / root / locations | TEXT | — | server 块三要素 |
| ssl_certificate / ssl_certificate_key | TEXT | — | 证书对（私钥路径是高价值证据） |
| upstreams / config_file_path | TEXT | — | 上游/配置路径 |

#### linux_web_error_logs（`:889-910`，Phase 7）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| level | TEXT | — | 级别（error/warn...） |
| source | TEXT | — | 来源（apache/nginx/php-fpm） |
| client_ip | TEXT | — | 客户端 IP |
| message | TEXT | — | 正文 |
| module | TEXT | — | 模块（mod_php/mod_ssl...） |
| pid | TEXT | — | 进程号（**TEXT**） |
| file_path | TEXT | — | 错误日志文件路径 |
| parser_name / parser_version | TEXT | — | 溯源 |
| source_file | TEXT | — | 证据文件 |
| raw_record | TEXT | — | 原始行 |
| LLM5 | — | — | 5 列组 |

索引（`:911-914`）：timestamp/level/source/llm。

#### linux_middleware_logs（`:917-939`，Phase 7）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| level | TEXT | — | 级别 |
| source | TEXT | — | 来源（tomcat/weblogic/应用名） |
| logger | TEXT | — | logger 名（注意：不是 component，见"已知边界"） |
| message | TEXT | — | 正文 |
| thread | TEXT | — | 线程名 |
| exception | TEXT | — | 堆栈（多行拼接） |
| pid | TEXT | — | 进程号 |
| file_path | TEXT | — | 日志路径 |
| parser_name / parser_version | TEXT | — | 溯源 |
| source_file | TEXT | — | 证据文件 |
| raw_record | TEXT | — | 原始行 |
| LLM5 | — | — | 5 列组 |

索引（`:940-943`）：timestamp/level/source/llm。

#### linux_modsecurity_logs（`:946-968`，Phase 7，WAF 审计日志）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| client_ip | TEXT | — | 客户端 IP |
| method | TEXT | — | 请求方法 |
| uri | TEXT | — | 请求 URI |
| rule_id | TEXT | — | 命中规则 ID |
| rule_message | TEXT | — | 规则说明 |
| severity | TEXT | — | 严重度 |
| action | TEXT | — | 处置（deny/log/pass） |
| file_path | TEXT | — | 审计日志路径 |
| parser_name / parser_version | TEXT | — | 溯源 |
| source_file | TEXT | — | 证据文件 |
| raw_record | TEXT | — | 原始行 |
| LLM5 | — | — | 5 列组 |

索引（`:969-972`）：timestamp/client_ip/rule_id/llm。

### 分组六：服务日志（8 张）

Phase 11 的"服务日志 + findings"配对家族：每类服务一张日志表 + （部分）一张 findings 表。**注意本组时间双列设计**：`timestamp TEXT`（原文）+ `timestamp_unix INTEGER`（归一，索引列）——与全库其余 INTEGER timestamp 不同。

#### linux_database_logs（`:1144-1166`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | TEXT | — | 原始时间戳串 |
| timestamp_unix | INTEGER | — | 归一（索引） |
| db_type | TEXT | — | mysql/postgresql/mongodb/redis |
| severity / component | TEXT | — | 级别/组件 |
| message | TEXT | — | 正文 |
| source_file / line_number | TEXT/INTEGER | — | 证据定位 |
| username / database_name / client_addr / query_text | TEXT | — | DB 语义四件套 |
| error_code | INTEGER | — | 错误码 |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引：db_type/severity/timestamp_unix/llm（`:1167-1170`）。

#### linux_email_logs（`:1196-1220`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | TEXT | — | 原始时间戳串 |
| timestamp_unix | INTEGER | — | 归一（索引） |
| service_type | TEXT | — | postfix/exim/dovecot |
| severity | TEXT | — | 级别 |
| component | TEXT | — | 组件（smtp/lmtp/imap） |
| message_id | TEXT | — | 邮件 Message-ID |
| message | TEXT | — | 正文 |
| source_file | TEXT | — | 证据文件 |
| line_number | INTEGER | — | 行号 |
| sender | TEXT | — | 发件人 |
| recipient | TEXT | — | 收件人 |
| client_addr | TEXT | — | 客户端 IP |
| relay_host | TEXT | — | 中继主机 |
| message_size | INTEGER | — | 邮件字节 |
| status | TEXT | — | 投递状态（sent/deferred/bounced） |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引（`:1221-1224`）：service_type/status/timestamp_unix/llm。

#### linux_vpn_logs（`:1249-1272`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | TEXT | — | 原始时间戳串 |
| timestamp_unix | INTEGER | — | 归一（索引） |
| service_type | TEXT | — | openvpn/wireguard |
| severity | TEXT | — | 级别 |
| message | TEXT | — | 正文 |
| source_file | TEXT | — | 证据文件 |
| line_number | INTEGER | — | 行号 |
| username | TEXT | — | 登录用户 |
| client_addr | TEXT | — | 客户端 IP |
| virtual_addr | TEXT | — | 分配的虚拟 IP |
| server_addr | TEXT | — | 服务端地址 |
| common_name | TEXT | — | 证书 CN |
| bytes_sent | INTEGER | — | 发送字节 |
| bytes_received | INTEGER | — | 接收字节 |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引（`:1273-1276`）：service_type/username/timestamp_unix/llm。

#### linux_firewall_logs（`:1302-1326`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | TEXT | — | 原始时间戳串 |
| timestamp_unix | INTEGER | — | 归一（索引） |
| tool_type | TEXT | — | ufw/firewalld |
| severity | TEXT | — | 级别 |
| message | TEXT | — | 正文 |
| source_file | TEXT | — | 证据文件 |
| line_number | INTEGER | — | 行号 |
| action | TEXT | — | 动作（ALLOW/DENY） |
| protocol | TEXT | — | 协议 |
| src_addr | TEXT | — | 源地址（索引） |
| src_port | INTEGER | — | 源端口 |
| dst_addr | TEXT | — | 目的地址 |
| dst_port | INTEGER | — | 目的端口 |
| interface_name | TEXT | — | 网卡 |
| chain_name | TEXT | — | 链名 |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引（`:1327-1331`）：tool_type/action/src_addr/timestamp_unix/llm，共 5 个。

#### linux_security_product_logs（`:1334-1353`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | TEXT | — | 原始时间戳串 |
| timestamp_unix | INTEGER | — | 归一（索引） |
| tool_type | TEXT | — | fail2ban/clamav/rkhunter/ossec/aide |
| severity | TEXT | — | 级别 |
| message | TEXT | — | 正文 |
| source_file | TEXT | — | 证据文件 |
| line_number | INTEGER | — | 行号 |
| event_type | TEXT | — | 事件类型（ban/detect...） |
| target_file | TEXT | — | 目标文件（扫描对象/规则文件） |
| result | TEXT | — | 结果（clean/infected/found） |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引（`:1354-1358`）：tool_type/event_type/result/timestamp_unix/llm，共 5 个。

#### linux_package_logs（`:1032-1054`）

`timestamp(INTEGER), package_manager, package_name, package_version, architecture, operation, operation_detail, status, user_name, command_line, file_path` + 溯源 + LLM5。索引 5（`:1055-1059`）。

#### linux_suspicious_packages（`:1061-1078`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| finding_type | TEXT | — | 发现类型 |
| severity | TEXT | — | 严重度（TEXT） |
| package_name / package_version | TEXT | — | 涉事包 |
| description | TEXT | — | 说明 |
| evidence | TEXT | — | 证据 |
| file_path | TEXT | — | 证据文件 |
| parser_name / parser_version | TEXT | — | 溯源 |
| LLM5 | — | — | 5 列组 |

索引（`:1079-1082`）：finding_type/severity/package_name/llm。

#### linux_journal_entries（`:787-822`，Phase 2，本组明星表）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| realtime_timestamp | INTEGER | — | 实际时刻（微秒，journal 导出惯例） |
| monotonic_timestamp | INTEGER | — | 单调钟 |
| boot_id | TEXT | — | 引导 ID（关联 boot_sessions） |
| systemd_unit / user_unit | TEXT | — | 系统/用户单元 |
| pid / uid / gid | INTEGER | — | 进程身份 |
| comm / exe / cmdline | TEXT | — | 命令三件套 |
| transport | TEXT | — | 传输（journal/stdout...） |
| message | TEXT | — | 正文 |
| message_id | TEXT | — | journal 消息模板 ID |
| syslog_identifier | TEXT | — | syslog 标识 |
| priority | TEXT | — | 优先级 |
| cursor_id | TEXT | — | 游标（防重放） |
| 溯源组 | — | — | parser_name/version、source_file/offset/inode/hash、parse_error、raw_record |
| confidence | INTEGER | DEFAULT 100 | 解析置信度 |
| LLM5 | — | — | 5 列组 |

索引 7（`:823-829`）：realtime_timestamp/boot_id/systemd_unit/pid/uid/priority/llm。

### 分组七：时间线与关联（6 张）

分析层输出：把前面六组的原料折叠成归一时间线、断档、相关事件、攻击链与异常。

#### linux_correlated_events（`:713-723`，写入 `crud.h:227-230`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| start_timestamp / end_timestamp | INTEGER | — | 窗口 |
| event_type | TEXT | — | 归类 |
| initiating_user / initiating_process | TEXT | — | 发起者 |
| related_event_ids | TEXT | — | 成员事件 ID 清单 |
| description | TEXT | — | 叙事 |
| severity | INTEGER | — | 严重度 |

#### linux_attack_chains（`:728-736`，写入 `crud.h:232-235`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| chain_id | TEXT | — | 链标识 |
| attack_type | TEXT | — | 链类型 |
| events | TEXT | — | 事件序列（序列化） |
| timeline | TEXT | — | 时间线摘要 |
| summary | TEXT | — | 结论叙事 |
| confidence | REAL | — | 置信度 |

#### linux_timeline_events（`:741-751`，写入 `crud.h:237-240`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| source_type | TEXT | — | 来源表标识（哪个分析模块产出） |
| event_type | TEXT | — | 归类 |
| description | TEXT | — | 叙事 |
| username | TEXT | — | 涉事用户 |
| ip_address | TEXT | — | 涉事 IP |
| details | TEXT | — | 细节 |
| confidence | INTEGER | — | 置信度 |

索引：`idx_timeline_events_timestamp`、`idx_timeline_events_type`（`:752-753`）。

#### linux_timeline_gaps（`:756-763`，写入 `crud.h:242-245`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| start_time / end_time | INTEGER | — | 断档窗口 |
| duration | INTEGER | — | 时长（秒） |
| description | TEXT | — | 说明 |
| is_suspicious | INTEGER | — | 可疑标志（防篡改的间接信号） |

索引：`idx_timeline_gaps_time`、`idx_timeline_gaps_suspicious`（`:764-765`）。

#### linux_anomalies（`:768-779`，写入 `crud.h:247-250`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| anomaly_type | TEXT | — | 异常大类 |
| anomaly_subtype | TEXT | — | 子类 |
| description | TEXT | — | 说明 |
| severity | INTEGER | — | 严重度（INTEGER） |
| confidence | REAL | — | 置信度 |
| evidence_ids | TEXT | — | 支撑证据事件 ID 清单 |
| mitigation | TEXT | — | 缓解建议 |
| detected_at | INTEGER | — | 发现时刻 |
| additional_data | TEXT | — | 附加数据 |

索引：type/severity/detected_at（`:780-782`）。

#### linux_journal_anomalies（`:842-852`，Phase 2）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| anomaly_type | TEXT | — | 异常类型 |
| description | TEXT | — | 说明 |
| timestamp | INTEGER | — | 时刻 |
| severity | INTEGER | — | 严重度（INTEGER） |
| parser_name / parser_version | TEXT | — | 溯源 |
| source_file | TEXT | — | 证据文件 |

（本表无 LLM 列。）索引：anomaly_type/severity（`:853-854`）。

### 分组八：持久化与外设（6 张，Phase 6/9）

#### linux_persistence_entries（`:857-882`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| persistence_type | TEXT | NOT NULL | 类型（rc.local/systemd/cron/ld.so.preload...） |
| risk_level | TEXT | — | 风险级 |
| file_path | TEXT | — | 落点 |
| entry_name | TEXT | — | 条目名 |
| command / arguments | TEXT | — | 命令/参数 |
| username | TEXT | — | 归属用户 |
| schedule | TEXT | — | 计划（cron 型） |
| is_enabled | INTEGER | — | 启用 |
| is_suspicious / suspicious_reason | INTEGER/TEXT | — | 可疑判定 |
| raw_content | TEXT | — | 原文 |
| 溯源组 + LLM5 | — | — | parser + source_file/line + 5 列 |

索引 4（`:883-886`）。

#### linux_boot_sessions（`:832-838`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| boot_id | TEXT | UNIQUE | 引导 ID（与 journal_entries.boot_id 对齐） |
| start_time / end_time | INTEGER | — | 开机/关机时刻 |
| entry_count | INTEGER | — | 本次引导的 journal 条数 |

索引：`idx_boot_session_start(start_time)`（`:839`）。

#### linux_usb_events（`:1383-1411`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| event_type | TEXT | — | add/remove/mount |
| vendor_id / product_id | TEXT | — | VID/PID |
| serial_number | TEXT | — | 序列号（设备唯一） |
| manufacturer / product | TEXT | — | 厂商/产品名 |
| device_path | TEXT | — | /dev 路径 |
| mount_point | TEXT | — | 挂载点 |
| filesystem | TEXT | — | 文件系统 |
| capacity_bytes | INTEGER | — | 容量 |
| kernel_device | TEXT | — | 内核设备名（sdb1...） |
| 溯源组 | — | — | parser_name/version、source_file/offset/inode/hash、parse_error、raw_record |
| confidence | INTEGER | DEFAULT 100 | 解析置信度 |
| LLM5 | — | — | 5 列组 |

索引（`:1412-1416`）：timestamp/event_type/vendor_id/product_id/llm。

#### linux_mount_entries（`:1419-1445`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| device | TEXT | — | 设备 |
| mount_point | TEXT | — | 挂载点 |
| filesystem | TEXT | — | 文件系统 |
| mount_options | TEXT | — | 挂载选项（noexec/ro 有取证含义） |
| total_bytes / used_bytes / available_bytes | INTEGER | — | 容量三元组 |
| is_external | INTEGER | DEFAULT 0 | 外部盘 |
| is_network | INTEGER | DEFAULT 0 | 网络盘（nfs/cifs） |
| 溯源组 + confidence | — | — | 同上（DEFAULT 100） |
| LLM5 | — | — | 5 列组 |

索引（`:1446-1449`）：device/mount_point/is_external/llm。

#### linux_extended_history（`:1486-1510`，注释："Python, MySQL, Git, Docker, Kube, Cloud credentials"）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| timestamp | INTEGER | — | 时刻 |
| tool_type | TEXT | — | python/mysql/git/docker/kube/cloud |
| username | TEXT | — | 执行用户 |
| command | TEXT | — | 命令/语句 |
| database_name | TEXT | — | MySQL 场景的库名 |
| working_dir | TEXT | — | 工作目录 |
| source_file | TEXT | — | 证据文件（.mysql_history/.gitconfig...） |
| is_sensitive | INTEGER | DEFAULT 0 | 含凭据/令牌 |
| sensitive_reason | TEXT | — | 判定原因 |
| 溯源组 + confidence | — | — | offset/inode/hash/parse_error/raw_record（DEFAULT 100） |
| LLM5 | — | — | 5 列组 |

索引（`:1511-1514`）：tool_type/username/is_sensitive/llm。

### 分组九：进度（1 张）

#### linux_analysis_progress（`:1131-1139`，写入 `llm.h:238-246`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| task_id | TEXT | PRIMARY KEY | 任务 ID |
| table_name | TEXT | — | 对应表名 |
| total_artifacts / completed_artifacts | INTEGER | — | 进度 |
| started_at / last_updated | INTEGER | — | 时刻 |
| status | TEXT | DEFAULT 'running' | 状态 |

## 索引总览

索引全部内联在建表 SQL 后（非独立常量），按组分布：系统基础 20+、安全审计 6+、浏览器 4、容器 10、Web 16、服务日志 30+、时间线 8、持久化/外设 20+、journal 7。共同模式：几乎每张带 LLM5 的表都有 `idx_*_llm_analyzed(llm_analyzed_at)`（pending 扫描需要）+ 常用过滤列（时间/类型/IP）。

## 跨表关联键

- **username** 贯穿全库：`linux_users.username` ↔ shell_history/login_records/ssh_*/browser_profiles/recent_documents/trash_entries/persistence_entries 的 `username`。
- **source_file / source_inode / source_hash**（溯源组）：回指 files.db/raw.db 的证据文件——Phase 2+ 表把证据链做进了列里。
- **boot_id**：journal_entries ↔ boot_sessions。
- **container_id**：container_logs ↔ docker_containers/podman_containers。

真实 JOIN 示例（登录后 10 分钟内的 shell 命令——横向串联两张原料表）：

```sql
SELECT h.username, h.timestamp, h.command
FROM linux_shell_history h
JOIN linux_login_records l
  ON l.username = h.username
 AND h.timestamp BETWEEN l.login_time AND l.login_time + 600
WHERE l.is_success = 1
ORDER BY h.timestamp;
```

## 已知边界

- **7 个 LLM pending SELECT 引用不存在的列（运行时必失败）**：`linux_analysis_sql_llm.h` 中以下语句被 `LinuxLLMAnalysisService_Database.cpp:157-168` 生产分发，但 SELECT 的列不在建表 SQL 里，prepare 报 no such column、对应类型工件拿不到：
  - `SELECT_TAMPERING_FINDINGS_PENDING_ANALYSIS`（`:172`）取 `affected_log`，表列是 `log_source`；
  - `SELECT_WEB_ERROR_LOGS_PENDING_ANALYSIS`（`:181`）取 `error_code`，表中无此列；
  - `SELECT_MIDDLEWARE_LOGS_PENDING_ANALYSIS`（`:184`）取 `component`，表列是 `logger`；
  - `SELECT_DATABASE_LOGS_PENDING_ANALYSIS`（`:205`）取 `operation`，表中无此列；
  - `SELECT_EMAIL_LOGS_PENDING_ANALYSIS`（`:211`）取 `from_addr/to_addr/subject`，表列是 `sender/recipient` 且无 subject；
  - `SELECT_VPN_LOGS_PENDING_ANALYSIS`（`:217`）取 `event_type/remote_ip`，表中无此列；
  - `SELECT_SECURITY_PRODUCT_LOGS_PENDING_ANALYSIS`（`:226`）取 `target`，表列是 `target_file`。
  （`SELECT_MODSECURITY_LOGS_PENDING_ANALYSIS` 同病——取 `request_method/request_uri`，表列是 `method/uri`——但未发现生产调用方。）
- **时间戳类型三态**：多数表 `timestamp INTEGER`；Phase 11 服务日志五表是 `timestamp TEXT + timestamp_unix INTEGER` 双列；`linux_log_entries` 也是 TEXT+INTEGER 双列——跨表 UNION 时间线必须挑对列。
- **severity 类型不一致**：tampering/gaps/anomalies/journal_anomalies/rule_matches/security_bypass 是 INTEGER，findings 家族（account/ssh/database/email/vpn/security_product/container/suspicious_packages）是 TEXT。
- **browser_type 类型漂移**：`linux_browser_profiles.browser_type` INTEGER，其余 4 张 browser 表是 TEXT。
- **两块 CREATE 常量名不副实**：`CREATE_LINUX_ANALYSIS_PROGRESS_TABLE` 装了 28 张 Phase 2~11 表 + 进度表；阅读源码别被名字骗了。
- **LLM5 覆盖不全**：`linux_groups`、8 张容器/Web 老表（docker_*、podman_*、apache_*、nginx_*）、`linux_selinux_*`、`linux_apparmor_*`、`linux_setuid_files`、`linux_capabilities`、时间线 6 表（correlated/attack_chain/timeline/gaps/anomalies/journal_anomalies）、`linux_boot_sessions` 无 LLM 列——设计上"结论表"不给结论再加注。

---

**最后更新**: 2026-08-24（新建，字段级参考）
