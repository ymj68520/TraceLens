# WindowsFilesAnalyzer - Windows系统取证分析器

## 1. 模块概述 (Overview)

**WindowsFilesAnalyzer** 是取证分析平台的专业Windows系统痕迹分析引擎,提供从Windows磁盘镜像中深度提取和分析数字证据的能力。该模块能够自动识别并解析Windows系统的各类核心工件,包括注册表配置单元、事件日志、程序执行痕迹、浏览器历史、用户活动记录等关键证据,为调查人员提供完整的系统使用时间线和行为重建能力。

该模块对Windows环境下的数字取证至关重要。在内部调查、恶意软件分析、数据泄露溯源等场景中,Windows系统承载了大量的用户操作痕迹和系统状态信息。WindowsFilesAnalyzer通过多维度、多层次的数据提取和关联分析,能够快速还原用户行为、系统变更、程序执行等关键活动,为调查提供强有力的证据支持。

**核心业务价值:**
- **全面痕迹提取**:覆盖注册表、事件日志、浏览器、程序执行等12大类Windows工件
- **时间线重建**:整合多源时间戳数据,构建完整的用户活动时间线
- **行为分析**:识别程序执行模式、文件访问习惯、网络浏览行为
- **证据关联**:通过多源数据交叉验证,确保证据的准确性和可靠性
- **自动化分析**:无需人工干预,自动完成所有工件的提取和解析

---

## 2. 核心功能列表 (Key Features)

### 2.1 注册表分析 (Registry Analysis)

**支持的注册表配置单元**:
- **SAM**:用户账户信息、密码哈希、账户策略
- **SYSTEM**:系统配置、服务配置、启动项
- **SOFTWARE**:已安装软件、软件设置、文件关联
- **SECURITY**:安全策略、权限配置
- **NTUSER.DAT**:用户配置、桌面设置、应用程序设置

**提取内容**:
- 用户账户信息(用户名、RID、最后登录时间、账户状态)
- 已安装软件列表(软件名称、版本、安装时间、发布者)
- 系统服务配置(服务名称、可执行路径、启动类型、运行账户)
- 自动启动项(启动文件夹、Run键、Scheduled Tasks)
- USB设备历史记录(设备序列号、首次连接时间、最后连接时间)
- 网络配置(网络适配器、WiFi连接记录、RDP连接历史)
- 文件关联和打开记录(最近打开的文档、ShellBags查看记录)

### 2.2 事件日志分析 (Event Log Analysis)

**支持的日志类型**:
- **Security**:安全事件(登录/注销、对象访问、权限变更)
- **System**:系统事件(服务启停、驱动加载、系统崩溃)
- **Application**:应用程序事件(应用程序错误、挂起)
- **PowerShell**:PowerShell执行日志(脚本块日志、模块日志)
- **Windows Defender**:防病毒软件日志(扫描记录、威胁检测)

**关键事件识别**:
- 登录事件(类型2:交互式,类型10:远程桌面,类型3:网络)
- 账户管理事件(用户创建、删除、密码变更、组成员变更)
- 权限提升事件(管理员权限获取、敏感特权分配)
- 进程执行事件(进程创建、网络连接、文件创建)
- 系统错误事件(系统崩溃、服务异常、磁盘错误)

### 2.3 程序执行追踪 (Program Execution Tracking)

**Prefetch文件分析**:
- 可执行文件名称和完整路径
- 执行次数统计和最后执行时间
- 程序加载的DLL和资源文件列表
- 访问的目录列表

**Amcache分析**:
- 应用程序执行历史(SHA-1哈希、文件路径、大小)
- 程序元数据(公司名称、产品名称、版本、语言)
- PE文件链接时间(编译时间戳)

**Shimcache分析**:
- 应用程序兼容性缓存中的执行记录
- 最后修改时间戳

### 2.4 浏览器取证 (Browser Forensics)

**支持的浏览器**:
- Google Chrome
- Microsoft Edge
- Mozilla Firefox
- Internet Explorer

**Chrome/Edge数据提取**:
- **浏览历史**:URL、页面标题、访问时间、访问次数、访问类型
- **下载记录**:下载URL、目标路径、文件大小、开始/结束时间、下载状态
- **书签**:书签URL、标题、文件夹路径、添加/修改时间
- **Cookie**:域名、名称、值、创建/过期时间、安全标志
- **保存的密码**:URL、用户名、加密密码(存储为hex)、使用次数
- **扩展程序**:已安装的浏览器扩展列表

**Firefox数据提取**:
- places.sqlite(历史记录、书签)
- downloads.sqlite(下载记录)
- cookies.sqlite(Cookie)
- logins.json(保存的密码)

**Internet Explorer数据提取**:
- index.dat(历史记录、缓存)
- 浏览历史和 Typed URLs

### 2.5 用户活动重建 (User Activity Reconstruction)

**快捷方式(LNK)文件分析**:
- 目标文件路径和属性
- 工作目录和命令行参数
- 创建/修改/访问时间戳
- 卷序列号和驱动器类型
- 网络共享的NetBIOS名称

**Jump Lists分析**:
- 应用程序ID和目标路径
- 最后访问时间和访问次数
- 是否固定到任务栏

**回收站分析**:
- 被删除文件的原始路径和文件名
- 删除时间戳和原始文件大小
- 删除操作的用户SID

**最近打开的文档**:
- Office文档最近打开记录
- 资源管理器最近的文件访问记录

### 2.6 系统元数据分析 (System Metadata Analysis)

**MFT记录提取**:
- MFT条目编号和文件路径
- 文件大小(逻辑大小和物理大小)
- 时间戳(创建、修改、访问、MFT修改)
- 删除文件标记
- 备用数据流(ADS)检测

**时间戳精度**:
- SI(Standard Information)时间戳
- FN(File Name)时间戳
- 用于时间线重建和事件关联

### 2.7 高级取证功能

**SRUM分析**:
- 应用程序网络使用情况(发送/接收字节数)
- CPU使用时间(前台和后台)
- 应用程序运行时长
- 用户标识和时间戳

**计划任务提取**:
- 任务名称和路径
- 触发类型和执行操作
- 最后运行时间和下次计划运行时间
- 运行账户和任务状态

**Windows服务记录**:
- 服务名称和显示名称
- 可执行文件路径和启动类型
- 服务账户和描述信息

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:内部违规调查

**背景**:公司怀疑某员工在离职前窃取了商业机密数据,需要调查其计算机使用情况。

**使用流程**:
```bash
# 1. 创建分析任务
./forensic_analyzer employee_disk.dd --windows-analyze

# 输出: employee_disk_windows.db

# 2. 查询USB设备插入记录(检查是否使用U盘拷贝数据)
sqlite3 employee_disk_windows.db \
  "SELECT * FROM usb_devices ORDER BY last_connected DESC;"

# 3. 查询大文件下载记录
sqlite3 employee_disk_windows.db \
  "SELECT * FROM browser_downloads WHERE file_size > 10485760 ORDER BY start_time;"

# 4. 查询浏览器历史(访问云存储、邮箱等)
sqlite3 employee_disk_windows.db \
  "SELECT * FROM browser_history WHERE url LIKE '%dropbox%' OR url LIKE '%gmail%' ORDER BY visit_time DESC;"

# 5. 查询文件删除记录(回收站)
sqlite3 employee_disk_windows.db \
  "SELECT * FROM recycle_bin WHERE deletion_time > '离职前1周的时间戳' ORDER BY deletion_time DESC;"

# 6. 查询程序执行记录(检查是否使用压缩工具)
sqlite3 employee_disk_windows.db \
  "SELECT * FROM prefetch WHERE executable_name LIKE '%winrar%' OR executable_name LIKE '%7zip%' ORDER BY last_run_time DESC;"
```

**分析发现**:
- USB设备:检测到2个U盘在离职前3天内插入
- 下载记录:发现大量文件上传到个人云存储
- 浏览器历史:频繁访问竞争公司网站和求职网站
- 程序执行:大量使用WinRAR压缩文件

**价值体现**:
- 完整还原离职前的行为时间线
- 定位数据窃取的具体时间、手段和范围
- 为法律诉讼提供确凿证据

---

### 场景二:恶意软件感染溯源

**背景**:企业服务器感染勒索软件,需要分析攻击路径和持久化机制。

**使用流程**:
```cpp
#include "WindowsFilesAnalyzer/WindowsFilesAnalyzer.h"

WindowsFilesAnalyzer analyzer;
analyzer.initialize();

// 1. 执行完整Windows分析
analyzer.analyzeWindowsData();

// 2. 查询可疑的计划任务
auto suspiciousTasks = analyzer.queryDatabase(
    "SELECT * FROM scheduled_tasks WHERE action_path LIKE '%Temp%' OR task_name LIKE '%Update%';"
);

// 3. 查询事件日志中的异常登录
auto suspiciousLogins = analyzer.queryDatabase(
    "SELECT * FROM event_logs WHERE event_id IN (4624, 4625) AND user_sid LIKE '%500%' ORDER BY timestamp;"
);

// 4. 查询注册表启动项
auto startupKeys = analyzer.queryDatabase(
    "SELECT * FROM registry_keys WHERE key_path LIKE '%Run%' AND value_data LIKE '%.exe%' ORDER BY last_modified;"
);

// 5. 查询Prefetch中的可疑程序执行
auto suspiciousExecs = analyzer.queryDatabase(
    "SELECT * FROM prefetch WHERE executable_path LIKE '%AppData%' ORDER BY last_run_time DESC;"
);

// 6. 查询网络连接(从事件日志或浏览器历史)
auto networkConnections = analyzer.queryDatabase(
    "SELECT * FROM event_logs WHERE event_id = 5156 ORDER BY timestamp DESC LIMIT 50;"
);
```

**分析发现**:
- 计划任务:发现名为"SystemUpdate"的隐藏任务,指向可疑可执行文件
- 事件日志:检测到大量夜间登录失败记录,随后成功登录
- 注册表:Run键中添加了持久化启动项
- Prefetch:可疑程序在感染前后被多次执行
- 网络:检测到与已知C2服务器的连接

**价值体现**:
- 还原攻击时间线:初始入侵→权限提升→持久化→横向移动→数据窃取
- 识别攻击技术和工具(TTPs)
- 为事件响应和系统加固提供依据

---

### 场景三:数据泄露事件响应

**背景**:检测到大量敏感数据被外泄,需要确定泄露途径和责任人。

**使用流程**:
```bash
# 使用Python HTTP服务的API进行查询

# 1. 查询特定时间段的文件访问记录
curl -X GET "http://localhost:8090/api/db/query" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM mft_entries WHERE file_name LIKE ''%.confidential%'' AND access_time > 1704067200000 ORDER BY access_time DESC;"
  }'

# 2. 查询浏览器上传活动
curl -X GET "http://localhost:8090/api/db/query" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM browser_history WHERE url LIKE ''%upload%'' AND visit_time > 1704067200000;"
  }'

# 3. 查询USB设备连接记录
curl -X GET "http://localhost:8090/api/db/query" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM usb_devices WHERE first_connected > 1704067200000 ORDER BY first_connected;"
  }'

# 4. 查询网络活动(SRUM数据)
curl -X GET "http://localhost:8090/api/db/query" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM srum_entries WHERE bytes_sent > 10485760 ORDER BY timestamp DESC LIMIT 20;"
  }'

# 5. 导出完整时间线
curl -X GET "http://localhost:8090/api/db/tasks/123/export/json" \
  -G --data-urlencode "table=event_logs" \
  --data-urlencode "table=browser_history" \
  --data-urlencode "table=mft_entries" > investigation_data.json
```

**价值体现**:
- 多维度数据关联,快速定位泄露源头
- 完整的证据链,支持法律追责
- 为安全防护改进提供数据支持

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**编译器要求**:
- GCC 9.0+ 或 Clang 10.0+
- 支持 C++20 标准

**必需的库**:
```bash
# 核心取证库
sudo apt-get install libtsk-dev  # The Sleuth Kit 4.14.0+

# Windows特定库
sudo apt-get install libhivex-dev      # 注册表解析
sudo apt-get install libolecf-dev      # OLE复合文档(用于某些工件)
sudo apt-get install libevtx-dev       # EVTX事件日志

# 数据库
sudo apt-get install libsqlite3-dev    # SQLite 3.x

# 其他依赖
sudo apt-get install nlohmann-json3-dev # JSON处理
```

**系统要求**:
- RAM:8GB最低,16GB推荐(处理大镜像)
- 磁盘:SSD强烈推荐(显著提升分析速度)
- 操作系统:Linux(Ubuntu 20.04+, Debian 11+)或Windows 10+

### 配置说明

**基本使用**:
```bash
# 自动检测并分析Windows工件
./forensic_analyzer windows_image.dd --windows-analyze

# 输出数据库: windows_image_windows.db
```

**通过HTTP服务使用**:
```bash
# 启动HTTP服务
./forensic_analyzer --http-server 8080

# 创建Windows分析任务
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/path/to/windows.dd",
    "analysis_type": "full",
    "platforms": ["windows"]
  }'

# 查询分析结果
curl http://localhost:8080/api/windows/registry?task_id=xxx
curl http://localhost:8080/api/windows/events?task_id=xxx
curl http://localhost:8080/api/windows/browser?task_id=xxx
```

### 配置选项

**选择性分析**(节省时间):
```cpp
// 在WindowsFilesAnalyzerCore.cpp中配置
struct AnalyzerConfig {
    bool parseRegistry = true;      // 注册表分析
    bool parseEventLogs = true;     // 事件日志分析
    bool parsePrefetch = true;      // Prefetch分析
    bool parseBrowsers = true;      // 浏览器分析
    bool parseAmcache = true;       // Amcache分析
    bool parseSrum = true;          // SRUM分析
    bool parseJumpLists = true;     // Jump Lists分析
    bool parseLnkFiles = true;      // LNK文件分析
    bool parseRecycleBin = true;    // 回收站分析
    bool parseScheduledTasks = true;// 计划任务分析
};
```

**性能优化**:
```cpp
// 增加数据库缓存大小
PRAGMA cache_size = -64000;  // 64MB

// 启用WAL模式提升并发性能
PRAGMA journal_mode = WAL;

// 批量插入优化
batch_size = 1000;
```

### 分析时间估算

**典型镜像分析时间**(基于Intel i7,SSD):
- 50GB镜像:约30-60分钟
- 100GB镜像:约60-120分钟
- 500GB镜像:约4-8小时

**影响因素**:
- 镜像中的文件数量
- 是否需要深度浏览器分析(耗时最长)
- 磁盘I/O性能(机械硬盘vs SSD)
- 是否启用选择性分析

---

## 5. 接口与集成说明 (API & Integration)

### 数据库表结构

**注册表数据** (registry_keys):
```sql
CREATE TABLE registry_keys (
    id INTEGER PRIMARY KEY,
    hive_path TEXT,
    hive_type TEXT,
    key_path TEXT,
    value_name TEXT,
    value_type TEXT,
    value_data TEXT,
    last_modified INTEGER,
    forensic_importance TEXT
);
```

**事件日志** (event_logs):
```sql
CREATE TABLE event_logs (
    id INTEGER PRIMARY KEY,
    record_id INTEGER,
    log_source TEXT,
    event_id INTEGER,
    level TEXT,
    timestamp INTEGER,
    source TEXT,
    message TEXT,
    computer_name TEXT,
    user_sid TEXT,
    channel TEXT
);
```

**浏览器历史** (browser_history):
```sql
CREATE TABLE browser_history (
    id INTEGER PRIMARY KEY,
    browser_name TEXT,
    profile_name TEXT,
    url TEXT,
    title TEXT,
    visit_time INTEGER,
    visit_duration INTEGER,
    visit_count INTEGER,
    visit_type TEXT,
    is_redirect BOOLEAN
);
```

**Prefetch数据** (prefetch):
```sql
CREATE TABLE prefetch (
    id INTEGER PRIMARY KEY,
    executable_name TEXT,
    executable_path TEXT,
    prefetch_hash TEXT,
    run_count INTEGER,
    last_run_time INTEGER,
    creation_time INTEGER
);
```

**MFT条目** (mft_entries):
```sql
CREATE TABLE mft_entries (
    id INTEGER PRIMARY KEY,
    entry_number INTEGER,
    file_name TEXT,
    file_path TEXT,
    logical_size INTEGER,
    physical_size INTEGER,
    creation_time INTEGER,
    modification_time INTEGER,
    access_time INTEGER,
    is_deleted BOOLEAN
);
```

### 核心接口

**初始化**:
```cpp
#include "WindowsFilesAnalyzer/WindowsFilesAnalyzer.h"

WindowsFilesAnalyzer analyzer;
analyzer.setDatabasePath("output_windows.db");
analyzer.setExtractDir("extracted_files");

if (!analyzer.initialize()) {
    LOG_ERROR("Failed to initialize Windows analyzer");
    return;
}
```

**执行分析**:
```cpp
// 完整分析(所有模块)
analyzer.analyzeWindowsData();

// 或者分步执行
analyzer.parseRegistryHives();
analyzer.parseEventLogs();
analyzer.parseBrowserArtifacts();
analyzer.parsePrefetchFiles();
// ...
```

**查询数据**:
```cpp
// 查询注册表
auto registryResults = analyzer.queryDatabase(
    "SELECT * FROM registry_keys WHERE forensic_importance = 'HIGH'"
);

// 查询事件日志
auto eventResults = analyzer.queryDatabase(
    "SELECT * FROM event_logs WHERE event_id = 4624 ORDER BY timestamp DESC"
);

// 查询浏览器历史
auto browserResults = analyzer.queryDatabase(
    "SELECT * FROM browser_history WHERE url LIKE '%github.com%'"
);
```

### REST API集成

**通过C++ HTTP服务**:
```bash
# 查询Windows分析结果
GET /api/windows/registry?task_id=xxx&limit=100
GET /api/windows/events?task_id=xxx&event_id=4624
GET /api/windows/browser?task_id=xxx&browser=chrome
GET /api/windows/prefetch?task_id=xxx&min_runs=5
GET /api/windows/user-activity?task_id=xxx
```

**通过Python HTTP服务**(支持导出):
```bash
# 导出TOON格式用于LLM分析
GET /api/db/tasks/xxx/export/toon?table=browser_history&table=event_logs

# 自定义SQL查询
POST /api/db/query
{
    "sql": "SELECT * FROM registry_keys WHERE key_path LIKE '%Software%'"
}
```

---

## 6. 常见问题 (FAQ)

**Q1:Windows分析最耗时的部分是什么?**

A:按耗时排序:

1. **浏览器历史分析**(30-40%时间)
   - Chrome/Edge历史数据库可能很大
   - SQLite查询和解析耗时
   - 建议选择性分析:只分析特定用户或时间范围

2. **事件日志解析**(20-30%时间)
   - EVTX格式解析复杂
   - 大量事件需要逐一处理
   - 优化:只分析关键日志(Security、System)

3. **文件扫描**(15-20%时间)
   - Prefetch、LNK、Jump Lists文件分散
   - 需要遍历整个文件系统
   - 优化:限制搜索范围

4. **注册表解析**(10-15%时间)
   - Hive文件较大但结构化
   - libhivex解析效率高

**优化建议**:
```bash
# 只分析关键模块,跳过浏览器
./forensic_analyzer image.dd --windows-analyze --skip-browsers

# 或只分析特定时间范围
./forensic_analyzer image.dd --windows-analyze --time-start="2024-01-01" --time-end="2024-01-31"
```

---

**Q2:如何处理BitLocker加密的Windows镜像?**

A:需要先解密:

**方法1:使用libbde**
```bash
# 安装libbde
sudo apt-get install libbde-tools

# 挂载加密镜像
bdemount -p recovery_password /path/to/encrypted.dd /mnt/decrypted

# 分析解密后的镜像
./forensic_analyzer /mnt/decrypted/disk.raw --windows-analyze
```

**方法2:使用专业工具**
- EnCase:内置BitLocker解密
- FTK Imager:支持恢复密码和BEK文件
- Passware Kit:商业解密工具

**注意事项**:
- 需要恢复密码(48位)或BEK文件
- 解密大镜像需要很长时间(可能数小时)
- 解密后确保有足够磁盘空间存储

---

**Q3:浏览器密码能解密吗?**

A:技术上可以,但有限制:

**Chrome/Edge密码**:
- 存储在"Login Data"文件中
- 使用Windows DPAPI加密
- 需要用户Windows登录密码才能解密
- 当前版本:导出为hex格式的加密密码

**Firefox密码**:
- 使用主密码加密
- 如果主密码为空,可以直接解密
- 有主密码:需要暴力破解或字典攻击

**法律和伦理考虑**:
- 仅在合法授权的调查中使用
- 需要明确的法律授权和证据保全链
- 建议:在报告中注明密码的加密状态

---

**Q4:如何验证分析结果的准确性?**

A:多源交叉验证:

**时间戳交叉验证**:
```sql
-- 验证程序执行:Prefetch vs 事件日志 vs Amcache
SELECT p.executable_name, p.last_run_time, e.timestamp, a.last_modified
FROM prefetch p
LEFT JOIN event_logs e ON e.message LIKE '%' || p.executable_name || '%'
LEFT JOIN amcache a ON a.file_path LIKE '%' || p.executable_name || '%'
WHERE p.executable_name = 'cmd.exe';
```

**用户行为验证**:
```sql
-- 验证文件访问:浏览器下载 vs MFT vs 回收站
SELECT b.target_path, b.end_time, m.file_path, m.access_time, r.original_path, r.deletion_time
FROM browser_downloads b
LEFT JOIN mft_entries m ON m.file_name = b.file_name
LEFT JOIN recycle_bin r ON r.file_name = b.file_name
WHERE b.file_name LIKE '%.confidential%';
```

**准确性指标**:
- 时间戳一致性:多个来源的时间戳应相近(误差<1分钟)
- 路径匹配:文件路径在不同来源中应一致
- 逻辑合理性:事件序列应符合逻辑因果关系

---

**Q5:如何快速定位关键证据?**

A:优先级查询策略:

**1. 最近修改的文件**(数据泄露指标)
```sql
SELECT * FROM mft_entries
WHERE modification_time > (strftime('%s', 'now') - 7*86400) * 1000
AND (file_name LIKE '%.doc%' OR file_name LIKE '%.xls%' OR file_name LIKE '%.pdf%')
ORDER BY modification_time DESC;
```

**2. 异常登录事件**(入侵指标)
```sql
SELECT * FROM event_logs
WHERE event_id IN (4624, 4625, 4625, 4768, 4776, 4771)
AND timestamp > (strftime('%s', 'now') - 30*86400) * 1000
ORDER BY timestamp DESC;
```

**3. 网络上传活动**(数据外传指标)
```sql
SELECT * FROM browser_history
WHERE url LIKE '%upload%' OR url LIKE '%transfer%'
ORDER BY visit_time DESC;
```

**4. 外部设备连接**(物理数据拷贝指标)
```sql
SELECT * FROM usb_devices
WHERE last_connected > (strftime('%s', 'now') - 30*86400) * 1000
ORDER BY last_connected DESC;
```

**5. 可疑程序执行**(恶意软件指标)
```sql
SELECT * FROM prefetch
WHERE executable_path LIKE '%Temp%' OR executable_path LIKE '%AppData%'
ORDER BY last_run_time DESC;
```

---

**Q6:分析结果如何用于报告?**

A:多种导出格式:

**1. JSON格式**(程序处理)
```bash
curl -X GET "http://localhost:8090/api/db/tasks/123/export/json" \
  -G --data-urlencode "table=event_logs" \
  --data-urlencode "table=browser_history" > evidence.json
```

**2. CSV格式**(Excel分析)
```bash
sqlite3 windows_image_windows.db \
  -header -csv \
  "SELECT * FROM event_logs WHERE event_id = 4624" > logins.csv
```

**3. TOON格式**(LLM分析)
```bash
curl -X GET "http://localhost:8090/api/db/tasks/123/export/toon" \
  -G --data-urlencode "include=event_logs,browser_history,prefetch" \
  --data-urlencode "time_start=1704067200000" \
  --data-urlencode "time_end=1706745600000" > timeline.toon
```

**4. HTML报告**(可视化)
```python
# 使用Python生成HTML报告
import pandas as pd
import sqlite3

conn = sqlite3.connect('windows_image_windows.db')

# 读取数据
events = pd.read_sql_query("SELECT * FROM event_logs LIMIT 100", conn)
browser = pd.read_sql_query("SELECT * FROM browser_history LIMIT 100", conn)

# 生成HTML
with open('report.html', 'w') as f:
    f.write('<h1>Windows取证分析报告</h1>')
    f.write('<h2>事件日志</h2>')
    f.write(events.to_html())
    f.write('<h2>浏览器历史</h2>')
    f.write(browser.to_html())
```

---
