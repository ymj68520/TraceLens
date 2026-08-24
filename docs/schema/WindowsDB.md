# windows.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/windows_analysis_sql_tables.h` + `windows_analysis_sql_crud.h` + `windows_analysis_sql_llm.h`）

> windows.db 是 files.db 的**平台语义观点**（DatabaseSchema.md 派生链：files.db → windows.db）：注册表、预取、LNK、事件日志等 Windows 特有工件的结构化抽取。32 张表分五组：工件表 24 张（其中浏览器 6 张、DLL 7 张），加进度表。DLL 组同时服务 CLI 独立输出 `<image>_dll.db`（`--analyze-dlls` 系列参数）——同一组 SQL 常量两处建库。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `WindowsAnalysisDatabase`：建表执行 `CREATE_ALL_TABLES` + `CREATE_WINDOWS_ANALYSIS_PROGRESS_TABLE`（`windows_analysis_sql_tables.h:10-623`）；行数据由 WindowsFilesAnalyzer 各解析器经 `insertXxx` 写入（内联 SQL，如 `WindowsDBOperations_System.cpp:18` MFT、`WindowsDBOperations_Browser.cpp:179` Cookie、注册表解析 `Parsers/WindowsRegistryParser.cpp`、系统工件 `Parsers/WindowsRegistryArtifacts.cpp`） |
| 谁读 | HTTP 查询路由、Web 前端 Windows 页、`WindowsLLMAnalysisService`（pending SELECT 见 `windows_analysis_sql_llm.h:60-100`）、DLL 分析视图 |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/windows.db`；CLI `<image>_dll.db`（仅 DLL 7 表）；CLI 集成模式并入 files.db 的 `windows_artifacts` |

## 表清单总表（32 张）

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `registry_values` | 注册表与账户 | 注册表值（含 forensic_importance 评级） | 16 |
| `user_accounts` | 注册表与账户 | 本机账户（SAM） | 13 |
| `event_logs` | 事件与痕迹 | Windows 事件日志（EVTX）行 | 15 |
| `prefetch_files` | 事件与痕迹 | 预取文件（程序执行痕迹） | 15 |
| `lnk_files` | 事件与痕迹 | 快捷方式（目标与卷信息） | 19 |
| `jump_list_entries` | 事件与痕迹 | 跳转列表（最近文档） | 10 |
| `amcache_entries` | 事件与痕迹 | Amcache（程序清单与哈希） | 15 |
| `shimcache_entries` | 事件与痕迹 | Shimcache/AppCompatCache | 10（恒空，见边界） |
| `user_assist_entries` | 事件与痕迹 | UserAssist（GUI 程序执行计数） | 13（恒空） |
| `shell_bag_entries` | 事件与痕迹 | ShellBag（目录访问痕迹） | 14（恒空） |
| `mft_entries` | 事件与痕迹 | $MFT 条目（含 $FILE_NAME 时间） | 21 |
| `browser_history` | 浏览器 | 浏览历史 | 15 |
| `browser_downloads` | 浏览器 | 下载记录 | 18 |
| `browser_bookmarks` | 浏览器 | 书签 | 12 |
| `browser_cookies` | 浏览器 | Cookie | 13（无 llm 列） |
| `browser_logins` | 浏览器 | 保存的登录凭据 | 15 |
| `browser_artifacts` | 浏览器 | 旧版通用浏览器工件（兼容保留） | 13 |
| `windows_services` | 系统组件 | 服务清单 | 13 |
| `scheduled_tasks` | 系统组件 | 计划任务 | 17 |
| `srum_entries` | 系统组件 | SRUM 资源使用计量 | 13 |
| `usb_devices` | 系统组件 | USB 设备史 | 10（无 llm 列） |
| `recycle_bin` | 系统组件 | 回收站条目 | 8（无 llm 列） |
| `wifi_profiles` | 系统组件 | WiFi 连接档案 | 13（恒空） |
| `rdp_connections` | 系统组件 | RDP 连接史 | 9（恒空） |
| `dll_base_info` | DLL 分析 | DLL/PE 主记录（哈希+签名+LLM） | 37 |
| `dll_sections` | DLL 分析 | PE 节表 | 11 |
| `dll_imports` | DLL 分析 | 导入函数 | 6 |
| `dll_exports` | DLL 分析 | 导出函数 | 5 |
| `dll_anomalies` | DLL 分析 | 异常发现（风险评级） | 8 |
| `dll_dependencies` | DLL 分析 | DLL 间依赖图（父子+深度） | 6 |
| `dll_forensic_links` | DLL 分析 | 与其他证据源的关联 | 7 |
| `windows_analysis_progress` | 进度 | LLM 分析进度（task 主键） | 8 |

## 逐表字段说明

### 分组一：注册表与账户（2 张）

注册表是 Windows 取证的事实底座：账户、服务、痕迹表大多从 SYSTEM/SOFTWARE/SAM 三个 hive 抽出；`forensic_importance`/`source_hive` 等列把"值来自哪个 hive"留作证据链。

#### registry_values（`windows_analysis_sql_tables.h:12-27`，写入 `windows_analysis_sql_crud.h:14-16`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| hive_path | TEXT | — | hive 文件路径（镜像内） |
| hive_type | TEXT | — | hive 类别（SYSTEM/SOFTWARE/SAM/NTUSER...） |
| key_path | TEXT | — | 注册表键路径 |
| value_name | TEXT | — | 值名 |
| value_type | TEXT | — | 值类型（REG_SZ/REG_DWORD...） |
| value_data | TEXT | — | 值内容（文本化） |
| last_modified | INTEGER | — | 键最后修改时间（registry transaction log） |
| forensic_importance | TEXT | — | 取证重要性评级（解析器赋值） |
| llm_summary … llm_model_used | 5×TEXT/INTEGER | — | 标准 5 列 LLM 组（本表随建表携带，非 ALTER） |

（下文表格中"LLM 5 列组"不再逐行列出，均指 `llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, llm_model_used TEXT`。）

#### user_accounts（`:110-124`，写入 `crud.h:34-36`；无 LLM 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| rid | INTEGER | — | 相对 ID（SAM 内账户标识） |
| username | TEXT | — | 账户名 |
| full_name | TEXT | — | 全名 |
| comment | TEXT | — | 描述 |
| last_login | INTEGER | — | 最近登录 |
| password_last_set | INTEGER | — | 密码最近设置 |
| account_expires | INTEGER | — | 过期时刻 |
| password_expires | INTEGER | — | 密码过期 |
| account_flags | TEXT | — | 账户标志串 |
| is_admin | INTEGER | — | 1 = 管理组 |
| home_directory | TEXT | — | 主目录 |
| profile_path | TEXT | — | profile 路径 |

### 分组二：事件与痕迹（9 张）

程序执行与文件访问的"行为层"证据：prefetch/LNK/jump list/amcache 互相印证"什么程序何时跑过、碰过哪些文件"。

#### event_logs（`:30-47`，写入 `crud.h:18-20`；LLM 5 列组随表携带）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| record_id | INTEGER | — | EVTX 记录号 |
| log_source | TEXT | — | 通道（System/Application/Security） |
| event_id | INTEGER | — | 事件 ID（4624 登录等） |
| level | TEXT | — | 级别 |
| timestamp | INTEGER | — | 事件时刻 |
| source | TEXT | — | 事件源（Provider） |
| message | TEXT | — | 消息正文（模板渲染后） |
| computer_name | TEXT | — | 计算机名 |
| user_sid | TEXT | — | 关联 SID |
| channel | TEXT | — | 通道名 |

#### prefetch_files（`:50-66`，写入 `crud.h:22-24`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_path | TEXT | — | .pf 文件路径 |
| executable_name | TEXT | — | 被预取的可执行名 |
| executable_path | TEXT | — | 其完整路径 |
| prefetch_hash | TEXT | — | 预取哈希 |
| run_count | INTEGER | — | 运行次数 |
| last_run_time | INTEGER | — | 最近运行（可多次记录） |
| creation_time | INTEGER | — | .pf 创建时间（≈首跑） |
| referenced_files | TEXT | — | 引用文件清单（序列化） |
| referenced_directories | TEXT | — | 引用目录清单 |

#### lnk_files（`:69-90`，写入 `crud.h:26-28`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| lnk_path | TEXT | — | LNK 自身路径 |
| target_path | TEXT | — | 目标路径 |
| working_directory | TEXT | — | 工作目录 |
| arguments | TEXT | — | 启动参数 |
| icon_location | TEXT | — | 图标位置 |
| creation_time | INTEGER | — | 目标创建时间 |
| modification_time | INTEGER | — | 目标修改时间 |
| access_time | INTEGER | — | 目标访问时间 |
| target_size | INTEGER | — | 目标大小 |
| drive_type | TEXT | — | 驱动器类型（可移动/固定/网络） |
| volume_serial | TEXT | — | 卷序列号（设备溯源） |
| netbios_name | TEXT | — | 主机 NetBIOS 名 |
| relative_path | TEXT | — | 相对路径 |
| description | TEXT | — | 描述 |

#### jump_list_entries（`:93-107`，写入 `crud.h:30-32`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| app_id | TEXT | — | 应用 AppUserModelID |
| entry_path | TEXT | — | 条目路径 |
| entry_name | TEXT | — | 条目名 |
| access_time | INTEGER | — | 访问时刻 |
| creation_time | INTEGER | — | 创建时刻 |
| access_count | INTEGER | — | 访问计数 |
| is_pinned | INTEGER | — | 1 = 固定项 |

#### amcache_entries（`:333-351`，写入 `crud.h:62-64`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| file_path | TEXT | — | 文件路径 |
| file_hash | TEXT | — | SHA1（Amcache 惯例） |
| file_name | TEXT | — | 文件名 |
| company_name | TEXT | — | 公司 |
| product_name | TEXT | — | 产品 |
| product_version | TEXT | — | 版本 |
| file_description | TEXT | — | 描述 |
| file_size | INTEGER | — | 大小 |
| link_time | INTEGER | — | 链接/编译时间 |
| last_modified | INTEGER | — | 最近修改 |
| language | TEXT | — | 语言 |

#### shimcache_entries（`:406-419`；LLM 5 列组；**恒空**）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| entry_path | TEXT | — | AppCompatCache 条目路径 |
| last_modified_time | INTEGER | — | 条目时间戳 |
| entry_size | INTEGER | — | 条目大小 |
| execution_flag | INTEGER | — | 执行标志（win8+ 才有） |
| data_source | TEXT | — | 数据源说明 |
| source_hive | TEXT | — | 来源 hive |

#### user_assist_entries（`:422-437`；LLM 5 列组；**恒空**）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| user_sid | TEXT | — | 用户 SID |
| entry_guid | TEXT | — | UserAssist GUID |
| rot13_path | TEXT | — | ROT13 编码路径（原始） |
| decoded_path | TEXT | — | 解码后路径 |
| run_count | INTEGER | — | 运行计数 |
| focus_time | INTEGER | — | 焦点时长（毫秒） |
| last_run_time | INTEGER | — | 最近运行 |
| source_hive | TEXT | — | 来源 NTUSER.DAT |

#### shell_bag_entries（`:440-457`；LLM 5 列组；**恒空**）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| user_sid | TEXT | — | 用户 SID |
| bag_type | TEXT | — | Bag 类型 |
| slot_index | INTEGER | — | 槽位号 |
| shell_item_type | INTEGER | — | ShellItem 类型码 |
| path | TEXT | — | 解出的路径 |
| short_name | TEXT | — | 8.3 短名 |
| created_time | INTEGER | — | 目录创建时间 |
| modified_time | INTEGER | — | 目录修改时间 |
| accessed_time | INTEGER | — | 目录访问时间 |
| source_hive | TEXT | — | 来源 hive |

#### mft_entries（`:267-290`，写入 `WindowsDBOperations_System.cpp:19`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| entry_number | INTEGER | — | MFT 记录号（= NTFS 文件引用） |
| file_name | TEXT | — | $FILE_NAME 里的名 |
| file_path | TEXT | — | 重建全路径 |
| parent_entry | INTEGER | — | 父目录 MFT 号（路径重建依据） |
| logical_size | INTEGER | — | 逻辑大小 |
| physical_size | INTEGER | — | 磁盘占用 |
| creation_time | INTEGER | — | $STANDARD_INFORMATION 创建 |
| modification_time | INTEGER | — | SI 修改 |
| access_time | INTEGER | — | SI 访问 |
| mft_modification_time | INTEGER | — | MFT 条目自身修改 |
| fn_creation_time | INTEGER | — | $FILE_NAME 创建 |
| fn_modification_time | INTEGER | — | FN 修改（SI/FN 双时间戳对照是反反取证关键） |
| is_directory | INTEGER | — | 1 = 目录 |
| is_deleted | INTEGER | — | 1 = 已删除条目 |
| has_ads | INTEGER | — | 1 = 有备用数据流 |
| permissions | TEXT | — | 权限串 |

### 分组三：浏览器（6 张）

profile 维度是新增关键：`browser_name + profile_name` 前缀所有表，多账户多浏览器可并存。

#### browser_history（`:152-169`，写入 `crud.h:90-92`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_name | TEXT | — | 浏览器（Chrome/Edge/Firefox） |
| profile_name | TEXT | — | profile 名 |
| url | TEXT | — | URL |
| title | TEXT | — | 标题 |
| visit_time | INTEGER | — | 访问时刻 |
| visit_duration | INTEGER | — | 停留时长 |
| visit_count | INTEGER | — | 访问计数 |
| visit_type | TEXT | — | 跳转类型 |
| is_redirect | INTEGER | — | 1 = 重定向 |
| referrer | TEXT | — | 来源页 |

#### browser_downloads（`:172-192`，写入 `crud.h:94-96`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_name / profile_name | TEXT | — | 同上 |
| url | TEXT | — | 下载源 |
| target_path | TEXT | — | 落盘路径 |
| file_name | TEXT | — | 文件名 |
| file_size | INTEGER | — | 大小 |
| start_time / end_time | INTEGER | — | 起止时刻 |
| state | TEXT | — | 状态（完成/中断） |
| mime_type | TEXT | — | MIME |
| referrer | TEXT | — | 来源页 |
| received_bytes | INTEGER | — | 已收字节 |
| danger_accepted | INTEGER | — | 1 = 用户确认过危险提示 |

#### browser_bookmarks（`:195-209`，写入 `crud.h:98-100`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_name / profile_name | TEXT | — | 同上 |
| url / title | TEXT | — | 书签目标 |
| folder_path | TEXT | — | 所在文件夹路径 |
| date_added | INTEGER | — | 加入时刻 |
| date_modified | INTEGER | — | 修改时刻 |

#### browser_cookies（`:212-226`，写入 `WindowsDBOperations_Browser.cpp:180`；**无 LLM 列**）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_name / profile_name | TEXT | — | 同上 |
| domain | TEXT | — | 域 |
| name | TEXT | — | Cookie 名 |
| path | TEXT | — | 路径 |
| creation_time | INTEGER | — | 创建 |
| expiration_time | INTEGER | — | 过期 |
| last_access_time | INTEGER | — | 最近访问 |
| is_secure / is_http_only / is_persistent | INTEGER | — | 三个标志位 |
| same_site | TEXT | — | SameSite 策略 |

#### browser_logins（`:229-246`，写入 `crud.h:106-108`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_name / profile_name | TEXT | — | 同上 |
| url / action_url | TEXT | — | 登录页/提交页 |
| username | TEXT | — | 用户名（明文） |
| encrypted_password | TEXT | — | 加密密码（DPAPI 密文，**不**解密存储） |
| date_created / date_last_used / date_modified | INTEGER | — | 三个时刻 |
| times_used | INTEGER | — | 使用次数 |

#### browser_artifacts（`:249-264`，注释标 "Legacy - for backwards compatibility"；写入 `crud.h:46-48`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| browser_name | TEXT | — | 浏览器 |
| artifact_type | TEXT | — | 工件类型（history/download/...） |
| url / title | TEXT | — | 内容 |
| timestamp | INTEGER | — | 时刻 |
| visit_count | INTEGER | — | 计数 |
| local_path | TEXT | — | 本地路径 |
| file_size | INTEGER | — | 大小 |

### 分组四：系统组件（7 张）

#### windows_services（`:293-308`，写入 `crud.h:54-56`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| service_name / display_name | TEXT | — | 服务键名/显示名 |
| image_path | TEXT | — | 二进制路径（持久化排查重点） |
| start_type | TEXT | — | 启动类型 |
| service_type | TEXT | — | 服务类型 |
| account_name | TEXT | — | 运行账户 |
| description | TEXT | — | 描述 |
| is_running | INTEGER | — | 1 = 运行中 |

#### scheduled_tasks（`:311-330`，写入 `crud.h:58-60`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| task_name / task_path | TEXT | — | 任务名/路径 |
| author | TEXT | — | 作者 |
| description | TEXT | — | 描述 |
| action_type / action_path | TEXT | — | 动作类型/目标 |
| arguments | TEXT | — | 参数 |
| trigger_type | TEXT | — | 触发器 |
| last_run_time / next_run_time | INTEGER | — | 上次/下次运行 |
| status | TEXT | — | 状态 |
| run_as | TEXT | — | 运行账户 |

#### srum_entries（`:354-369`，写入 `crud.h:66-68`；LLM 5 列组）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| app_name | TEXT | — | 应用标识 |
| user_name | TEXT | — | 用户 SID |
| timestamp | INTEGER | — | 计量小时 |
| bytes_received / bytes_sent | INTEGER | — | 收发字节 |
| foreground_duration / background_duration | INTEGER | — | 前后台时长 |
| cpu_time_ms | INTEGER | — | CPU 毫秒 |

#### usb_devices（`:127-138`；**无 LLM 列**；写入 `crud.h:38-40`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| vendor_id / product_id / serial_number | TEXT | — | VID/PID/序列号（设备唯一性） |
| device_description / friendly_name / device_class | TEXT | — | 描述/友好名/类 |
| first_connected / last_connected | INTEGER | — | 首/末连接 |
| last_drive_letter | TEXT | — | 最近盘符 |

#### recycle_bin（`:141-149`；**无 LLM 列**；写入 `crud.h:42-44`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| recycle_file_path | TEXT | — | $R 文件路径 |
| original_path | TEXT | — | $I 记录的原路径 |
| file_name | TEXT | — | 文件名 |
| deletion_time | INTEGER | — | 删除时刻 |
| original_size | INTEGER | — | 原大小 |
| user_sid | TEXT | — | 所属用户 SID |

#### wifi_profiles（`:372-388`；LLM 5 列组；**恒空**）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| profile_name | TEXT | — | 档案名 |
| ssid | TEXT | — | SSID |
| connection_type | TEXT | — | 连接类型 |
| connection_mode | TEXT | — | 自动/手动 |
| mac_address | TEXT | — | BSSID |
| first_connected / last_connected | INTEGER | — | 首/末连接（时间戳可做位置推断） |
| dns_suffix | TEXT | — | DNS 后缀 |
| source_hive | TEXT | — | 来源 hive |

#### rdp_connections（`:391-403`；LLM 5 列组；**恒空**）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| server_address | TEXT | — | 曾连接的 RDP 服务器（注册表 MRU） |
| username_hint | TEXT | — | 用户名提示 |
| last_connection_time | INTEGER | — | 最近连接 |
| entry_type | TEXT | — | 条目类型（server/用户） |
| source_hive | TEXT | — | 来源 hive |

### 分组五：DLL 分析（7 张）

CLI `--analyze-dlls` 的产物。**本组是全项目唯一一组带真实 FOREIGN KEY + ON DELETE CASCADE 的表**（DLL 子表挂 `dll_base_info(id)`），建表 SQL 见 `:464-589`。

#### dll_base_info（`:464-517`，写入 `crud.h:176-185` 32 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | DLL 主键（子表外键目标） |
| inode | INTEGER | NOT NULL | 源文件 inode（跨库对齐 raw.db） |
| name | TEXT | NOT NULL | 文件名 |
| path | TEXT | UNIQUE NOT NULL | 全路径 |
| size | INTEGER | — | 字节 |
| md5 / sha1 / sha256 | TEXT | — | 内容哈希三连 |
| imp_hash | TEXT | — | 导入表哈希（Mandiant 算法，横向比对的王牌） |
| rich_hash | REAL | — | Rich 头哈希（编译器指纹） |
| file_format | TEXT | — | PE/ELF |
| machine_type | TEXT | — | 目标架构 |
| compile_timestamp | INTEGER | — | PE 时间戳（可被伪造，对照用） |
| subsystem | INTEGER | — | 子系统码 |
| entry_point | INTEGER | — | 入口 RVA |
| image_base | INTEGER | — | 首选加载基址 |
| is_dll | INTEGER | DEFAULT 1 | 1 = DLL（表也存 EXE） |
| characteristics | INTEGER | — | PE 特征位 |
| file_version / product_version / company_name / file_description | TEXT | — | 版本资源四件套 |
| signature_status | TEXT | — | 签名状态 |
| signer_name / cert_issuer | TEXT | — | 签署者/签发者 |
| cert_valid_from / cert_valid_to | INTEGER | — | 证书有效期 |
| mtime / ctime / atime / crtime | INTEGER | — | 文件系统四时间戳 |
| is_deleted | INTEGER | DEFAULT 0 | 删除标志 |
| threat_score | INTEGER | DEFAULT 0 | 威胁分（`SELECT_SUSPICIOUS_DLLS` 按 ≥? 阈值取） |
| llm_* 5 列组 | — | — | 同上 |
| created_at | INTEGER | DEFAULT (strftime('%s','now')) | 落库时刻 |

#### dll_sections（`:520-533`，写入 `crud.h:227-233`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| dll_id | INTEGER | NOT NULL, FK→dll_base_info(id) ON DELETE CASCADE | 所属 DLL |
| section_name | TEXT | NOT NULL | 节名（.text/.rdata...） |
| virtual_address / virtual_size | INTEGER | — | 虚拟地址/大小 |
| raw_data_size | INTEGER | — | 原始大小 |
| characteristics | INTEGER | — | 节属性位 |
| entropy | REAL | — | 熵（加壳检测） |
| is_writeable / is_executable / is_readable | INTEGER | DEFAULT 0 | W/X/R 标志（W+X 可疑） |

#### dll_imports（`:536-544`，写入 `crud.h:240-243`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| dll_id | INTEGER | NOT NULL, FK CASCADE | 所属 DLL |
| imported_dll_name | TEXT | NOT NULL | 被导入 DLL 名 |
| imported_function | TEXT | — | 函数名 |
| import_ordinal | INTEGER | — | 序号导入 |
| is_delayed | INTEGER | DEFAULT 0 | 延迟加载导入 |

#### dll_exports（`:547-554`，写入 `crud.h:245-248`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| dll_id | INTEGER | NOT NULL, FK CASCADE | 所属 DLL |
| function_name | TEXT | NOT NULL | 导出函数 |
| export_ordinal | INTEGER | — | 序号 |
| export_rva | INTEGER | — | RVA |

#### dll_anomalies（`:557-567`，写入 `crud.h:259-262`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| dll_id | INTEGER | NOT NULL, FK CASCADE | 所属 DLL |
| anomaly_type | TEXT | NOT NULL | 异常类型 |
| description | TEXT | — | 说明 |
| risk_level | TEXT | — | 风险级别 |
| risk_score | INTEGER | — | 分数 |
| details | TEXT | — | 细节 JSON |
| detected_at | INTEGER | DEFAULT (strftime('%s','now')) | 发现时刻 |

#### dll_dependencies（`:570-578`，写入 `crud.h:269-272`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| parent_dll_id / child_dll_id | INTEGER | NOT NULL, FK CASCADE ×2 | 依赖边两端 |
| depth | INTEGER | — | 传递深度 |
| is_resolved | INTEGER | DEFAULT 1 | 1 = 子 DLL 已入库 |

#### dll_forensic_links（`:581-589`，写入 `crud.h:279-282`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| dll_id | INTEGER | NOT NULL, FK CASCADE | 所属 DLL |
| link_type | TEXT | NOT NULL | 关联类型 |
| source_id | TEXT | — | 外部证据 ID |
| source_data | TEXT | — | 关联数据 |
| detected_at | INTEGER | — | 关联时刻 |

### windows_analysis_progress（`:613-623`，写入 `llm.h:126-134`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| task_id | TEXT | PRIMARY KEY | 任务 ID |
| table_name | TEXT | — | 对应表名 |
| total_artifacts / completed_artifacts | INTEGER | — | 总数/完成 |
| started_at / last_updated | INTEGER | — | 起止刷新 |
| status | TEXT | DEFAULT 'running' | 状态 |

## 索引

- 工件表：**除 DLL 组外无手工索引**（24 张表全靠扫）。
- DLL 组（`CREATE_DLL_INDICES`，`:593-610`）16 个：`dll_base_info` 的 inode/md5/imp_hash/compile_timestamp/signature_status/threat_score 6 列各一；`dll_sections/imports/exports/anomalies/dependencies/forensic_links` 的外键列与常用过滤列（`imported_function`、`risk_level`、`link_type`）。

## 跨表关联键

- **库内**：DLL 组 `dll_id → dll_base_info.id`（显式 FK + CASCADE）；MFT `parent_entry → entry_number`（值对齐，可递归重建目录树）。
- **跨库**：`dll_base_info.inode` ↔ raw.db/files.db `files.inode`；`mft_entries.file_path` ↔ files.db `files.path`；`event_logs.user_sid` ↔ `user_assist/shell_bag.user_sid`。

真实 JOIN 示例（DLL 异常 → 引用它的导入方，DLL 图的一跳）：

```sql
SELECT dep.parent_dll_id AS importer, p.path AS importer_path,
       a.anomaly_type, a.risk_level
FROM dll_anomalies a
JOIN dll_base_info d ON d.id = a.dll_id
JOIN dll_dependencies dep ON dep.child_dll_id = d.id
JOIN dll_base_info p ON p.id = dep.parent_dll_id
WHERE a.risk_level = 'high';
```

## 已知边界

- **五张表恒空**：`shimcache_entries` / `user_assist_entries` / `rdp_connections` / `wifi_profiles` 的 INSERT 方法（`WindowsDBOperations_System.cpp:274/321/360/401`）**没有任何生产调用方**（解析器未接线）；`shell_bag_entries` 连 INSERT 方法都不存在——建表即终态，任务产出中恒 0 行。查询侧已就绪（SELECT 存在），写入侧缺失。
- **`crud.h` 两处占位符 bug（未爆雷的坏副本）**：`INSERT_MFT_ENTRY`（`windows_analysis_sql_crud.h:50-52`）16 列只给 15 个 `?`；`INSERT_BROWSER_COOKIE`（`:102-104`）12 列只给 11 个 `?`。这两个常量**没有生产调用方**——WindowsFilesAnalyzer 实际用的是 `WindowsDBOperations_System.cpp:19` / `WindowsDBOperations_Browser.cpp:180` 的内联 SQL（占位符正确）。照抄常量会在 prepare 阶段失败。
- **LLM 列覆盖不均**：`user_accounts`/`usb_devices`/`recycle_bin`/`browser_cookies` 无 LLM 5 列组，`windows_analysis_sql_llm.h` 也不为它们提供 pending/UPDATE 语句。
- **`browser_artifacts` 是兼容遗留**：建表注释明言 Legacy；与 5 张明细表并存，新代码不应再写它。

---


## 附录：写入时序与查询手册

### 写入时序

| 分组表 | 写入方 | 时机 | 备注 |
|--------|--------|------|------|
| 注册表/账户 | WindowsRegistryParser（hivex） | PLATFORM_ANALYSIS·WINDOWS | |
| 事件与痕迹（event_logs/prefetch/lnk/jump/amcache/mft） | 各解析器 | 同上 | shimcache/user_assist/rdp/wifi 四表**恒空**（解析器未接线） |
| 浏览器 6 表 | Chromium/Firefox 解析器 | 同上 | |
| 系统组件（services/scheduled_tasks/srum/usb/recycle） | 各解析器 | 同上 | |
| dll_* 7 表 | DLLAnalyzer | `--analyze-dlls` 或任务内 | 当前扫描源是**分析机本机目录**（已知局限） |
| LLM5 列组 | WindowsLLMAnalysisService | 工件级 | includeMFT 默认 false（成本控制） |

### 查询手册（列名以本文档字段表为准）

**1. 自启动三源交叉（持久化排查主力）**
```sql
SELECT 'registry' src, key_path item, value_name, value_data
FROM registry_values WHERE key_path LIKE '%\\Run%'
UNION ALL
SELECT 'service', service_name, image_path, start_type
FROM windows_services WHERE start_type LIKE 'AUTO%'
UNION ALL
SELECT 'task', task_name, action_path, arguments
FROM scheduled_tasks
ORDER BY item;
```

**2. 程序执行痕迹（Prefetch）**
```sql
SELECT executable_name, run_count, file_path
FROM prefetch_files ORDER BY run_count DESC LIMIT 100;
```

**3. 浏览行为时间线**
```sql
SELECT datetime(visit_time,'unixepoch') t, browser_name, title, url
FROM browser_history ORDER BY visit_time DESC LIMIT 200;
```

**4. 服务画像（第三方/自动启动）**
```sql
SELECT service_name, display_name, image_path, account_name
FROM windows_services
WHERE image_path NOT LIKE 'C:\\Windows\\%' OR account_name NOT IN ('LocalSystem');
```

**5. 注册表取证重要性排序（解析器已评级）**
```sql
SELECT hive_type, key_path, value_name, substr(value_data,1,60), forensic_importance
FROM registry_values WHERE forensic_importance IS NOT NULL
ORDER BY forensic_importance LIMIT 200;
```

**6. DLL 威胁面（dll_base_info + anomalies）**
```sql
SELECT b.path, b.name, b.threat_score, a.anomaly_type, a.risk_level
FROM dll_base_info b LEFT JOIN dll_anomalies a ON a.dll_id=b.id
WHERE b.threat_score >= 30 ORDER BY b.threat_score DESC;
-- 注意当前 dll 数据源是本机目录；列名以字段表为准
```

## 分析案例

### 案例一：自启动持久化审计

**取证问题**：员工主机疑似被植入远控。要求穷举自启动面并定位可疑项。

**第 1 步：三源交叉清单**
```sql
SELECT 'registry' src, key_path, value_name, substr(value_data,1,60) val
FROM registry_values WHERE key_path LIKE '%\Run%' OR key_path LIKE '%\RunOnce%'
UNION ALL
SELECT 'service', service_name, image_path, start_type FROM windows_services
UNION ALL
SELECT 'task', task_name, action_path, arguments FROM scheduled_tasks
ORDER BY 2;
```
读法：三个来源各查一遍后按"落地路径"归并——同一可疑 EXE 同时出现在 ≥2 个来源是强植入信号（攻击者做冗余保活）。

**第 2 步：执行佐证（Prefetch）**
```sql
SELECT executable_name, run_count, file_path FROM prefetch_files
WHERE executable_name IN (<第1步可疑EXE名列表>);
```
读法：run_count>0 证明"注册过且真跑过"；run_count 与注册时间（registry last_modified）配合估计植入时长。

**第 3 步：外联与收敛**
browser_history 的异常时段 + event_logs 的安全事件（登录/进程创建类 ID 按字段表）收尾；结论落到"删除建议+取证固证"（哪些键值要导出存档）。

**边界提醒**：shimcache/user_assist/rdp/wifi 四表恒空（未接线）——不能作为"没有痕迹"的证据，见"已知边界"。

### 案例二：DLL 威胁面速查（本机扫描的有限用法）

dll_base_info（threat_score/imp_hash/signature_status）与 dll_anomalies 联查评估系统库完整性；注意当前数据源是分析机本机目录——结论只适用于"这台分析机自身被植入"的场景，不能外推到镜像。

## 自检清单

- [ ] registry_values 各 hive 都有行（缺 hive=提取失败）
- [ ] prefetch_files 非空（系统盘应有）
- [ ] 恒空四表（shimcache/user_assist/rdp/wifi）忽略——已知未接线
- [ ] dll_* 有行仅当分析机自身被扫描过（数据源局限）
- [ ] browser_history 各 browser_name 分布合理
**最后更新**: 2026-08-24（补：写入时序与查询手册）
