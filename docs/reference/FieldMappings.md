# 跨层字段映射参考

> 这份手册解决最容易出错的一类问题：同一个概念在 C++ 结构体、JSON、SQLite、Python 模型、前端 state 中使用了不同名字或大小写。每张表都标出映射方向与注意事项；具体实现仍以源码为准。

## 1. 任务创建字段映射

| 语义 | HTTP 请求字段 | C++ 字段 | tasks.json 字段 | Python/前端使用 | 注意 |
|---|---|---|---|---|---|
| 镜像位置 | `image_path` | `AnalysisTask::image_path` | `image_path` | `taskService.createTask` | 服务端必须能访问；不是浏览器本地路径 |
| 优先级 | `priority` | `priority` | `priority` | `taskSlice` | REST 小写，落盘序列化可能大写 |
| 场景 | `scenarios` | `scenarios` | `scenarios` | CreateTaskModal 多选 | 空数组触发 SceneDetector |
| XFS 模式 | `xfs_mode` | `xfs_mode` | `xfs_mode` | Advanced 选项 | `auto/native/pure` |
| 过滤画像 | `filter_profile` | `filter_profile` | `filter_profile` | FilterProfileSelector | 产出 `_filtered.db` 副本 |
| LLM 开关 | `llm_analyze` | `llm_analyze` | `llm_analyze` | 前端当前固定开启 | Android 工件 LLM另有端点门控 |
| LLM 模式 | `llm_mode` | `llm_mode` | `llm_mode` | full/smart | smart 有粗选预算 |
| 案情 | `case_description` | `case_description` | `case_description` | CreateTaskModal 必填 | 进入 prompt 上下文 |
| Android 源 | `android_source` | `android_source` | `android_source` | tsk/dir/zip/miui-backup | 只在 Android 分析链解释 |
| 备份密码 | `backup_password` | `backup_password` | `backup_password` | stdin/fd 更安全 | 不建议写入 JSON/argv |
| 解密 | `enable_decryption` | `enable_decryption` | `enable_decryption` | Advanced | 密钥目录另传 |
| 密钥目录 | `key_file_dir`/兼容 `key_dir` | `key_file_dir` | `key_file_dir` | CreateTaskModal | 兼容键是历史契约 |
| 雕刻 | `file_carving` | `file_carving` | `file_carving` | Tasks 页 | 29 种签名，3% 权重 |

### 1.1 创建请求的最小与完整形态

最小请求只需要可达的镜像路径：

```json
{
  "image_path": "/evidence/case-001.dd"
}
```

生产前端通常发送完整形态：

```json
{
  "image_path": "/evidence/case-001.dd",
  "priority": "high",
  "scenarios": ["linux"],
  "xfs_mode": "auto",
  "filter_profile": "general_forensics",
  "llm_analyze": true,
  "llm_mode": "smart",
  "case_description": "调查异常 SSH 登录与持久化",
  "file_carving": false
}
```

字段映射的排查顺序：先看 `TaskCRUDRoutes.cpp` 的 JSON 解析，再看 `TaskSerialization.cpp` 的 JSON 往返，最后看前端 `taskService.js`。只改其中一层会出现“创建成功但重启丢字段”或“界面有值但后端没读”的假成功。

## 2. 任务状态映射

| 生命周期语义 | REST/API | `HTTPServerDataTypes` | tasks.json | 前端常见判断 |
|---|---|---|---|---|
| 排队 | `pending` | `PENDING` | `PENDING` | `pending` |
| 执行 | `running` | `RUNNING` | `RUNNING` | `running` |
| 完成 | `completed` | `COMPLETED` | `COMPLETED` | `completed` |
| 失败 | `failed` | `FAILED` | `FAILED` | `failed` |
| 取消 | `cancelled` | `CANCELLED` | `CANCELLED` | `cancelled` |

这不是单纯的大小写风格：REST 序列化路径和任务持久化路径分别调用不同的转换函数。脚本直接读 tasks.json 时必须使用大写；调用 API 时必须使用小写。新增状态时要同时修改枚举、序列化、前端常量、过滤器和统计聚合，否则列表可能显示而统计不计数。

## 3. 任务阶段映射

| 阶段 | 权重 | 主要写入 | 主要调用方 |
|---|---:|---|---|
| `INITIALIZING` | 5 | 任务目录/句柄 | TaskManagerAnalysis |
| `IMAGE_ANALYSIS` | 25 | raw.db | ImageAnalyzer |
| `EVENT_EXTRACTION` | 10 | events.db | EventExtractor |
| `FILE_CLASSIFICATION` | 15 | files.db | FileFilter/FileClassifier |
| `LLM_ANALYSIS` | 20 | files.db 的 llm 列、事件 LLM 列 | LLMAnalysisService/EventClusterAnalyzer |
| `PLATFORM_ANALYSIS` | 20 | android/windows/linux/oss.db | 平台分析器 |
| `FILE_CARVING` | 3 | carved_files/ | FileCarver |
| `FINALIZING` | 2 | tasks.json、Graphiti job id | TaskManager/LLMPythonProxy |

阶段顺序本身是契约。不要把场景分析新增为 `ANDROID_ANALYSIS` 阶段；Android/Windows/Linux/Server 都属于 `PLATFORM_ANALYSIS`。进度计算依赖枚举排序与 `TaskManager.cpp:545` 的 map。

## 4. 文件记录映射

| 原始文件 | 分类主表 | Python `FileRecord` | LLM 结果 | 语义 |
|---|---|---|---|---|
| `raw.files.path` | `files.path` | `path` | `file_path`/`path` | 跨库主要连接键 |
| `raw.files.inode` | `files.inode` | `inode` | 可选 | 多分区时必须加 partition_num |
| `raw.files.partition_num` | `files.partition_num` | `partition_num` | 可选 | 消除 inode 碰撞 |
| `raw.files.size` | `files.size` | `size` | `file_size` | 字节数 |
| `raw.files.mtime` | `files.mtime` | `mtime` | `modified_at`/可选 | Unix 秒，具体 reader 转换需看实现 |
| — | `files.category` | `category` | `file_category` | FileClassifier 判定 |
| — | `files.scene_priority` | `scene_priority` | 可选 | 0-100 |
| — | `files.llm_summary` | `summary` | `summary` | 主表摘要 |
| — | `files.llm_description` | `description` | `description` | 主表描述 |
| — | `files.llm_keywords` | `keywords` | `keywords` | JSON/文本协议视服务而定 |
| — | `file_descriptions.is_relevant` | `is_relevant` | `is_relevant` | Python 重分析开关 |

跨层读取时不要假定 Python 的 `FileRecord` 是 SQLite 行的逐列复制。reader 会做缺列容错、时间归一化和截断；调试应同时打印原始 `PRAGMA table_info` 与 reader 生成对象。

## 5. 事件映射

| C++ events 列 | timeline API | EventCluster | Python investigation |
|---|---|---|---|
| `timestamp` | `timestamp`/格式化时间 | 分钟桶 `timestamp/60` | snapshot 中的 event time |
| `event_type` | `event_type` | cluster type | evidence key 的 cluster 类型 |
| `file_path` | `file_path` | 路径/父目录 | `file:<normalized_path>` |
| `inode` | `inode` | 可选关联 | 文件证据 resolver 的辅助键 |
| `description` | `description` | LLM 上下文 | claim 的 source context |

事件簇的分钟桶不是调查证据键的完整格式。后者是 `cluster:v1:<minute>:<encoded-type>`；前者只是 SQL 聚类键。混用会导致证据无法解析。

## 6. 平台工件映射

- Linux 登录：`linux_login_records` → `/api/forensics/system/events` / Python reader → investigation evidence；
- Linux 持久化：`linux_persistence_entries` → LinuxLLMAnalysisService 的表驱动选择；
- Windows 注册表：`registry_values` → `/api/forensics/dlls` 之外的系统查询；
- Android 微信：`wechat_messages`/`wechat_contacts` → `/api/forensics/android/miui-wechat-*` 与 `/api/wechat/graph`；
- 内存：`processes`/`network_connections` → `/api/forensics/memory/*`，库命名由 CLI 旁路约定发现；
- SERVER_CLOUD：`oss.db` 文件名，但实际是 LinuxFilesAnalyzer 的服务器/云工件表族，不是 `oss_objects` 表。

## 7. 映射变更后的验证矩阵

| 改动 | 最低验证 |
|---|---|
| API 字段改名 | C++ 路由测试 + Python client + 前端 service 测试 |
| SQLite 列改名 | 新库建表 + 插入 + 每个 SELECT consumer |
| 任务字段新增 | POST 创建→GET→tasks.json→重启恢复 |
| 状态新增 | 任务状态、统计、前端颜色、看门狗 |
| evidence key 改动 | investigation 单测 + report citation + live analyst |
| 后缀改变 | PathManager + DatabaseFactory + task_store + Graphiti reader |

---


## 8. 平台字段映射清单

### Linux

| 取证概念 | 表 | 关键列 | 下游 |
|---|---|---|---|
| 登录主体 | linux_login_records | username/remote_host/login_time/is_success | Investigation evidence |
| Shell 历史 | linux_shell_history | username/command/timestamp | 时间窗交叉 |
| 扩展历史 | linux_extended_history | source/command/timestamp | Python/脚本证据 |
| SSH key | linux_ssh_keys | user/key_type/fingerprint/path | 持久化判断 |
| 计划任务 | linux_cron_jobs | user/schedule/command/file_path | persistence |
| systemd | linux_systemd_services | unit_name/load_state/active_state/exec_start | persistence |
| 篡改 | linux_tampering_findings | tampering_type/severity/log_source/timestamp_start | 反取证结论 |
| 持久化 | linux_persistence_entries | persistence_type/risk_level/command/is_suspicious | LLM/报告 |
| 攻击链 | linux_attack_chains | chain_id/attack_type/events/timeline/confidence | 叙事报告 |
| 容器 | linux_docker_containers | container_id/image_name/state/host_config | SERVER_CLOUD |
| Nginx | linux_nginx_access_logs | timestamp/remote_ip/method/url/status_code | Web 行为 |
| USB | linux_usb_events | timestamp/manufacturer/product/serial_number/mount_point | 外带 |

### Windows

| 取证概念 | 表 | 关键列 | 下游 |
|---|---|---|---|
| 注册表值 | registry_values | hive_type/key_path/value_name/value_data | persistence |
| Prefetch | prefetch_files | executable_name/executable_path/run_count | 执行佐证 |
| 服务 | windows_services | service_name/image_path/start_type/account_name | 自启动 |
| 计划任务 | scheduled_tasks | task_name/action_path/arguments | 自启动 |
| 浏览历史 | browser_history | browser_name/url/title/visit_time | 行为时间线 |
| DLL 基础 | dll_base_info | path/md5/sha256/imp_hash/threat_score | 威胁评分 |
| DLL 异常 | dll_anomalies | dll_id/anomaly_type/risk_level/risk_score | 报告 |

### Android

| 取证概念 | 表 | 关键列 | 下游 |
|---|---|---|---|
| 微信消息 | wechat_messages | sender/receiver/content/timestamp/is_send | 微信图/报告 |
| 微信联系人 | wechat_contacts | username/nickname/alias | 关系节点 |
| 通话 | call_logs | number/date/duration/type/name | 行为序列 |
| 短信 | sms_messages | address/date/date_sent/read/body | 通信证据 |
| Chrome | chrome_history | url/title/last_visit_time/visit_count | Web 行为 |
| 安装包 | installed_packages | package_name/version/first_install_time | 应用画像 |
| MIUI 头 | miui_backup_manifest | device/miui_version/backup_date/package_count | 备份核对 |
| 加密库 | encrypted_db_inventory | package_name/db_path/key_hint/open_status | 解密覆盖 |

### 跨层命名规则

- 时间字段：C++ SQLite 多为 Unix 秒；PG `TIMESTAMP`；前端通常格式化成浏览器时区；
- 路径字段：raw/files 用 `path`，LLM 描述可能用 `file_path`，Graphiti FileRecord 归一为 `path`；
- 主键字段：SQLite 自增 `id` 不等于 inode；跨库对齐用 inode+partition_num 或 path；
- 状态字段：API 小写、落盘大写、Graphiti job 大写；不要做全局 lower/upper 替换；
- LLM 字段：主表使用 llm_summary/description/keywords/analyzed_at/model_used，Python API 的 response 可能简化成 summary/description/keywords。
**最后更新**: 2026-08-24（新建：跨层字段映射参考）
