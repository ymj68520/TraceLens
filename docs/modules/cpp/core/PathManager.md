# PathManager（src/core/PathManager/）

> **一句话**：进程级单例的"路径宪法"，把所有运行时路径（data 目录、任务目录、任务数据库命名、日志/审计文件位置、临时文件）锚定到可配置的 `DATA_DIR` 下，让程序从任何工作目录启动都把数据写到同一个地方。

## 1. 为什么有这个模块

取证服务刚起步时最容易出现的混乱是"数据写到哪去了"：用 systemd 启动时 CWD 是 `/`，手动启动时是仓库根，测试时又是 build 目录——于是 raw.db、tasks.json 散落各处，任务重启后找不到历史数据，清理时不知道删哪个目录。更隐蔽的是多分区并发：两个任务同时写 `tasks.json` 或互相覆盖同名数据库。

PathManager 用两条规则终结这类问题。第一，**一切路径从一个根推导**：根 = 可执行文件所在目录（运行时通过 `/proc/self/exe` 解析，不依赖 argv[0] 是否为相对路径），再叠加 `.env` 的 `PROJECT_ROOT`/`DATA_DIR` 覆盖。第二，**命名收敛到唯一函数**：每个任务的七个数据库文件名由 `getTaskDbPaths()` 一处定义（`PathManager.cpp:102-115`），HTTP 流水线、任务持久化、路由层都向它要路径，拼写漂移（`raw.db` vs `image_raw.db`）从此不可能发生。

## 2. 在系统中的位置

PathManager 是启动序列的第一块基石：`main()` 先 `PathManager::instance().initialize(argv[0])`，**然后**才能加载 `.env`（因为 ConfigManager 找配置文件时要用 exeDir/projectRoot，见 ConfigManager.cpp:26-31），最后用配置回写 PROJECT_ROOT/DATA_DIR 并创建目录树（`main.cpp:53-66`）。这个"先初始化、后覆盖"的顺序是刻意的：配置文件本身的位置也依赖 PathManager。

下游消费者遍布 HTTP 层与分析层：TaskPersistence（`data/tasks.json`）、TaskManagerAnalysis（任务库路径）、各路由（SearchRoutes、FileExtractionRoutes、TaskCRUDRoutes、CaseManager 等）、以及 ImageAnalyzer/AndroidAnalyzer 等分析器。它不调用任何业务模块，只依赖 `<filesystem>`。

```
main.cpp 启动序列（顺序敏感）:
  PathManager.initialize(argv[0])      # 解析 exeDir
  ConfigManager.load(".env")           # 借助 exeDir/projectRoot 找 .env
  setProjectRoot / setDataDirName      # .env 覆盖生效
  ensureDirectories()                  # 建 data/ 树
  ── 之后所有模块通过 instance() 取路径 ──
```

## 3. 核心概念与设计

**三层路径模型**：`exeDir_`（可执行文件目录，不可变）→ `projectRoot_`（默认等于 exeDir，可被 PROJECT_ROOT 覆盖）→ `dataDir_ = projectRoot / dataDirName_`（dataDirName_ 默认 `"data"`，可被 DATA_DIR 覆盖；若 DATA_DIR 是绝对路径则直接使用，`PathManager.cpp:60-66`）。这个小逻辑是"同机部署改根目录、容器部署给挂载卷"的开关。

**exeDir 解析的容错**：优先 `/proc/self/exe`（Linux 上最可靠，解析符号链接后的真实路径），失败才退回 `canonical(argv[0])`，再失败退回当前目录并打警告（`PathManager.cpp:16-35`）。这保证了通过 symlink 启动、或从其他目录用相对路径调用时行为一致。

**任务目录布局**是整个系统数据组织的核心约定，由 `getTaskDbPaths()` 定义（`PathManager.cpp:102-115`）：

```
data/
├── tasks.json                  # 任务列表持久化（getTasksJsonPath, :84-86）
├── tasks/<task_id>/            # getTaskDir（按需创建, ensureTaskDir :110-113）
│   ├── raw.db / events.db / files.db      # 三段流水线产物
│   ├── android.db / windows.db / linux.db / oss.db   # 平台库
│   └── extracted_files/        # getTaskExtractDir（:120-122）
├── audit/                      # getAuditDir（:74-76）
└── logs/                       # getLogsDir（:78-80）
```

`getTaskDbPaths` 的 `imageName` 参数是**死参数**——历史上任务库以镜像名命名，现在改为固定文件名，参数保留只为兼容旧调用（`PathManager.cpp:103-104` 的注释）。

**临时路径生成**（`makeTempPath`，`PathManager.cpp:137-145`）用"pid + 线程 id 哈希 + 进程内原子计数器"三元组保证多线程、多进程下不碰撞，供挂载点、解密中间文件等场景使用。

### 3.1 核心数据结构：TaskDbPaths（PathManager.h:84-104）

```cpp
    struct TaskDbPaths {
        std::filesystem::path rawDb;
        std::filesystem::path eventsDb;
        std::filesystem::path filesDb;
        std::filesystem::path androidDb;
        std::filesystem::path ossDb;
        std::filesystem::path windowsDb;
        std::filesystem::path linuxDb;
    };

    TaskDbPaths getTaskDbPaths(const std::string& taskId,
                               const std::string& imageName = "") const;
```

七个字段即任务全部产物库，逐个说明：`rawDb`（raw.db）是 ImageAnalyzer 的全量文件清单库，流水线第一阶段产物；`eventsDb`（events.db）是 EventExtractor 汇出的事件时间线；`filesDb`（files.db）是 FileClassifier 建的 24 分表分类库，也是各平台 Analyzer 工件的并入目标；`androidDb`/`windowsDb`/`linuxDb`/`ossDb` 是平台专属库，供平台深度分析单独落库。返回值语义是"一次性拿全套"——调用方解构后传给各阶段，避免各阶段各自拼路径产生漂移；配合头文件注释（`PathManager.h:96-101`）"filenames are fixed"的约定，文件名空间被完全冻结。

私有状态极简（`PathManager.h:160-163`）：`initialized_`（是否已 initialize）、`exeDir_`、`projectRoot_`（均 `std::filesystem::path`）、`dataDirName_`（string，默认 `"data"`）。注意**没有缓存 dataDir_**——每次 `getDataDir()` 现算（`PathManager.cpp:60-66`），换来的是 `setDataDirName` 立即生效、无需失效逻辑。

### 3.2 核心接口清单

| 签名（PathManager.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `void initialize(const std::string& executablePath)` | 解析 exeDir、置 initialized | main.cpp:54 | 解析失败回退 CWD 并打警告，不抛 |
| `void ensureDirectories() const` | 建 data/、tasks/、audit/、logs/ | main.cpp:66 | create_directories 抛 filesystem_error 由上层接 |
| `std::filesystem::path getExeDir() / getProjectRoot() / getDataDir() const` | 三层根路径 | ConfigManager.load、路由层、分析器 | 未初始化时返回空/相对路径（见第 6 节） |
| `std::filesystem::path getTaskDir(taskId) const` | data/tasks/<id> | TaskManager 系列、路由 | 纯拼接不创建 |
| `void ensureTaskDir(taskId) const`（头文件内联 :110-113） | 建任务目录（幂等） | TaskManagerAnalysis | 抛 filesystem_error |
| `TaskDbPaths getTaskDbPaths(taskId, imageName="") const` | 七库路径打包 | TaskManagerAnalysis、TaskPersistence | 纯拼接 |
| `std::filesystem::path getTasksJsonPath() const` | data/tasks.json | TaskPersistence、TaskWatchdog | 纯拼接 |
| `std::filesystem::path getAuditDbPath() / getLogFilePath() / getDebugLogPath() const` | 审计库/日志文件规范位置 | **无生产调用方**（未接线，见第 5 节） | 纯拼接 |
| `void setDataDirName(name) / setProjectRoot(root)` | 覆盖 DATA_DIR/PROJECT_ROOT（空串被忽略） | main.cpp:61-65 | 静默忽略空串 |
| `std::string makeTempPath(prefix, suffix="") const` | 生成系统临时目录下唯一路径 | 解密/挂载中间文件 | 无（getTempDir 抛时上抛） |

## 4. 工作流程走读

以一次 HTTP 分析任务创建路径为例：

1. 服务启动：`initialize(argv[0])` 解析出 exeDir（`PathManager.cpp:12-40`）；`main.cpp:61-65` 读到 `PROJECT_ROOT`/`DATA_DIR` 后调用 `setProjectRoot`/`setDataDirName`（空串被忽略，`PathManager.cpp:119-129`，防止误把根清空）；`ensureDirectories()` 用 `create_directories` 建好 data/ 四个子目录（`PathManager.cpp:42-48`，幂等）。
2. TaskManager 收到新任务，生成 UUID，调用 `getTaskDbPaths(taskId)` 一次性拿到七个库路径（`PathManager.cpp:102-115`），`ensureTaskDir` 顺带创建任务目录。
3. 流水线各阶段向这些路径写库；任务状态变化时 TaskPersistence 写 `getTasksJsonPath()`。
4. 路由层收到查询请求，同样用 `getTaskDir(taskId)` 拼出库文件路径——写方和读方引用同一函数，天然一致。

### 4.1 代码走读：initialize 的三级回退（PathManager.cpp:12-40）

```cpp
void PathManager::initialize(const std::string& executablePath) {
    namespace fs = std::filesystem;

    try {
        // Resolve symlinks and get absolute path of the executable
        fs::path exePath;

        // Try /proc/self/exe first (Linux-specific, most reliable)
#ifdef __linux__
        if (fs::exists("/proc/self/exe")) {
            exePath = fs::canonical("/proc/self/exe");
        } else
#endif
        {
            exePath = fs::canonical(executablePath);
        }

        exeDir_ = exePath.parent_path();
    } catch (const fs::filesystem_error&) {
        // Fallback: use current directory
        exeDir_ = fs::current_path();
        std::cerr << "[PathManager] Warning: could not resolve executable path, "
                     "falling back to CWD: " << exeDir_ << std::endl;
    }

    // Default projectRoot_ to exeDir_ (overridden later if PROJECT_ROOT is set)
    projectRoot_ = exeDir_;
    initialized_ = true;
}
```

逐块解释：`/proc/self/exe` 由内核维护、永远指向真实二进制（连符号链接启动也会解析到本体），比 argv[0] 可靠得多——argv[0] 可以被调用方任意伪造、也可能只是相对名。`#ifdef __linux__` 使这段在非 Linux 平台编译为 argv[0] 路径，可移植性靠条件编译而非抽象层解决。两级 canonical 都失败（如二进制已被删除）才退 CWD 并打警告——**注意退化后程序不停止**，所有数据将从 CWD 推导，这正是第 1 节要消灭的散乱场景，所以启动日志里的这条 Warning 值得监控。最后 `initialized_ = true` 无条件置位：即使走了回退分支，后续 `isInitialized()` 也为真——该标志只区分"从未初始化"与"初始化过"，不区分初始化质量。

### 4.2 代码走读：getDataDir 的绝对/相对分流（PathManager.cpp:60-66）

```cpp
std::filesystem::path getDataDir() const {
    const std::filesystem::path configured(dataDirName_);
    if (configured.is_absolute()) {
        return configured;
    }
    return projectRoot_ / configured;
}
```

逐块解释：短短六行是部署形态的开关。`dataDirName_` 为相对名（默认 `"data"`、或 `.env` 里 `DATA_DIR=data`）时，数据落 `projectRoot_/data`——同机部署、根随 PROJECT_ROOT 走；为绝对路径（`DATA_DIR=/mnt/evidence`）时 `is_absolute()` 直接短路返回——projectRoot 完全不参与，适合容器挂载卷或 CI 隔离目录（`main.cpp:59` 注释的 isolated acceptance runs）。每次调用现拼现返（无缓存）意味着 `setDataDirName` 之后立即生效，但也意味着热路径上每条路径查询都过一遍 path 拼接——对这个频次（任务级而非文件级）完全无所谓，是正确的取舍。

### 4.3 代码走读：makeTempPath 的三元唯一性（PathManager.cpp:137-145）

```cpp
std::string makeTempPath(const std::string& prefix,
                                       const std::string& suffix) const {
    static std::atomic<uint64_t> counter{0};
    auto tid = std::hash<std::thread::id>{}(std::this_thread::get_id());
    auto name = prefix + std::to_string(getpid()) + "_" +
                std::to_string(tid) + "_" +
                std::to_string(counter.fetch_add(1)) + suffix;
    return (getTempDir() / name).string();
}
```

逐块解释：唯一性由三个正交维度叠加——`getpid()` 隔离多进程（两台并发跑的实例）、线程 id 哈希隔离同进程多线程（解密与挂载常并发）、函数级 `static atomic` 计数器隔离同线程连续调用（`fetch_add` 返回旧值保证递增不重号）。返回的是**路径字符串而非已存在的文件**：调用方要自己 open/create，存在理论竞态（拿到路径到创建之间别人可能占用），但对前缀受控的内部使用场景足够；需要强保证的场合应换成 `mkdtemp` 一类的原子创建接口。`getTempDir()` 转发 `std::filesystem::temp_directory_path()`（读 TMPDIR/TMP 环境变量），运维可用环境变量把中间文件引到大盘。

### 4.4 代码走读：setDataDirName/setProjectRoot 的空串护栏（PathManager.cpp:119-129）

```cpp
void PathManager::setDataDirName(const std::string& name) {
    if (!name.empty()) {
        dataDirName_ = name;
    }
}

void PathManager::setProjectRoot(const std::string& root) {
    if (!root.empty()) {
        projectRoot_ = root;
    }
}
```

逐块解释：两个 setter 共用同一护栏——空串被静默忽略。动机是 main.cpp 的调用形态：`ConfigManager::instance().get("PROJECT_ROOT", "")` 在 .env 未写该键时返回**空串**而非"不调用"，没有护栏会把 projectRoot_ 清空、随后所有 getDataDir() 拼出 `/data`（根为空）——灾难性路径漂移。护栏的另一面（第 6 节已记）：**无法主动清回默认**，覆盖一旦发生只能重启。还有一层细节：setDataDirName 不做 is_absolute 归一，大小写、尾斜线原样保留——`DATA_DIR=./out/` 会得到 `projectRoot_/"./out/"`（lexically_normal 由消费方 filesystem 自动处理，通常无碍）；setProjectRoot 同样不 canonicalize，`.env` 里写相对 PROJECT_ROOT 时 data 目录随 CWD 漂移，运维应写绝对路径。

### 4.5 代码走读：ensureTaskDir/getTaskExtractDir 的头文件内联（PathManager.h:110-126）

```cpp
    void ensureTaskDir(const std::string& taskId) const {
        std::error_code ec;
        std::filesystem::create_directories(getTaskDir(taskId), ec);
    }

    std::filesystem::path getTaskExtractDir(const std::string& taskId) const {
        return getTaskDir(taskId) / "extracted_files";
    }
```

逐块解释：这对内联函数体现本模块的两种风格并存——**ensureTaskDir 用 error_code 重载吞掉异常**（创建失败静默，后续 SQLite open 才会真正报错），而 `ensureDirectories()`（cpp:42-48，无 ec 版本）失败会抛 filesystem_error；同为建目录、容错语义相反，因为任务目录创建失败属于"单任务可失败"而 data 根目录失败属于"进程不可用"。getTaskExtractDir 是 getTaskDir 的一行特化，`extracted_files` 这个名字被 HTTP 提取路由与 FileExtractor 的输出拼装共用（FileExtractionRoutes.cpp:147 一带的 task_extract_dir）——提取产物因此天然落在任务目录内、随任务一起归档/清理。

## 5. 与其他模块的协作

- **ConfigManager**：双向依赖的解法是"时序"——ConfigManager 找 `.env` 时调用 `PathManager::getExeDir()/getProjectRoot()`（`ConfigManager.cpp:26-31`，带 try/catch，因为此时 PathManager 可能未初始化）；反向地，main.cpp 把 ConfigManager 读到的 PROJECT_ROOT/DATA_DIR 回写给 PathManager。相关 .env 键：`PROJECT_ROOT`（getProjectRoot 的覆盖源，空则用 exeDir）、`DATA_DIR`（dataDirName_，默认 `"data"`，接受绝对或相对）。
- **TaskManager/TaskPersistence/TaskWatchdog**：任务目录与 `data/tasks.json` 的唯一权威来源；Watchdog 判僵死、断点续跑都依赖这套稳定布局。
- **AuditLog**：注意一个**未接线点**——PathManager 提供 `getAuditDbPath()`（`data/audit/forensics_audit.db`，`PathManager.cpp:88-90`），但 main.cpp 配置 AuditLog 时用的是 `AUDIT_LOG_DB` 环境变量、默认相对路径 `forensics_audit.db`（`main.cpp:70`），即审计库实际落在 CWD 而非 data/audit/。仓库根目录能看到 `forensics_audit.db` 就是这个原因（详见 AuditLog.md 第 6 节）。
- **FullTextSearch/SearchRoutes**：`FTS_ALLOWED_ROOT` 未设置时以 `getDataDir()` 作为索引允许根（`SearchRoutes.cpp:17-24`），PathManager 由此参与安全边界。
- 出错时行为：目录创建失败会在调用 `std::filesystem` 处抛异常，由上层 try/catch 转成任务失败；`initialize` 自身不抛（内部捕获，回退 CWD）。

## 6. 注意事项与已知问题

- **调用顺序是硬约束**：任何 `get*` 前必须 `initialize()`。未初始化时 exeDir/projectRoot 为空，相对 DATA_DIR 会拼出 `data/...` 相对路径（行为等于回到 CWD 时代）。ConfigManager 已做防御（`isInitialized()` 检查，`ConfigManager.cpp:27`），新代码也应检查。
- `getAuditDbPath()` 目前没有生产调用方（见上），属于"规划中但未接线"的 API；接线时应把 main.cpp:70 的默认值改成它。
- `setDataDirName`/`setProjectRoot` 忽略空串（`PathManager.cpp:119-129`），这是特性也是坑：想"清掉覆盖、回到默认"做不到，只能重启进程。
- DATA_DIR 设为绝对路径时 projectRoot 完全不影响数据位置——容器/CI 场景常用（`main.cpp:59` 注释提到的 isolated acceptance runs 即此用法）。
- 线程安全说明：getter 都是无状态读，但 `setProjectRoot`/`setDataDirName` 与并发读之间无锁；实践中它们只在 main 启动单线程阶段被调用，勿在运行期调用。
- `makeTempPath` 的线程 id 哈希与计数器都是"碰撞概率极小"而非"保证唯一"（见 4.3），对安全敏感的临时文件不要依赖它。
- 产物路径只做字符串拼接，**不检查磁盘空间/权限**；任务写到一半磁盘满的失败由 SQLite 层报出，PathManager 无感知。

## 7. 如何验证与扩展

- 单元测试：PathManager 没有独立的 gtest 目标；最直接的验证是运行 `./run.sh` 启动服务、创建一个任务，然后检查 `data/tasks/<uuid>/` 下七个库文件是否齐备。
- 快速实验：分别用 `DATA_DIR=/tmp/tl_data ./forensic_analyzer ...` 和默认配置各跑一次，对比数据落点，验证第 3 节的绝对路径规则。
- 扩展场景入手点：(1) 接线审计库路径——改 `main.cpp:69-74` 用 `getAuditDbPath().string()` 作为默认值；(2) 新增任务级产物目录（如 carved_files）——在 `PathManager.h:120-122` 旁加一个 `getTaskDir(id) / "carved_files"` 的内联函数，并在使用方统一改调它，不要在业务代码里手拼字符串。

## 8. 方法全清单

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `initialize(executablePath)` | cpp:12-40 | 解析 exeDir（三级回退） | main.cpp:54 |
| `isInitialized()` | h:44 | 读 initialized_ | ConfigManager:27、多处防御 |
| `ensureDirectories()` | cpp:42-48 | 建 data/tasks/audit/logs 四目录（抛错版） | main.cpp:66 |
| `getExeDir()` | cpp:50-58 | 可执行目录 | ConfigManager、SystemInfoRoutes |
| `getProjectRoot()` | cpp 同段 | 项目根（默认=exeDir） | ConfigManager、FileFilter |
| `getDataDir()` | cpp:60-66 | 绝对/相对分流的数据根 | SearchRoutes(FTS 根)、路由层 |
| `getTaskDir(taskId)` | h | data/tasks/<id>（纯拼接） | TaskManager 系列 |
| `ensureTaskDir(taskId)` | h:110-113 | 建任务目录（ec 吞错版） | TaskManagerAnalysis |
| `getTaskDbPaths(taskId, imageName="")` | cpp:102-115 | 七库路径打包 | TMA、TaskPersistence |
| `getTaskExtractDir(taskId)` | h:120-122 | 任务提取目录 | 提取路由 |
| `getAuditDir()/getLogsDir()` | cpp:74-80 | data/audit、data/logs | ensureDirectories |
| `getTasksJsonPath()` | cpp:84-86 | data/tasks.json | TaskPersistence/Watchdog |
| `getAuditDbPath()` | cpp:88-90 | data/audit/forensics_audit.db | **无生产调用方**（第 5 节） |
| `getLogFilePath()/getDebugLogPath()` | cpp:92-98 | logs/forensics.log、logs/debug.log | 仅 SystemInfoRoutes 展示（无写入方） |
| `setDataDirName(name)/setProjectRoot(root)` | cpp:119-129 | 覆盖（空串忽略） | main.cpp:61-65 |
| `getTempDir()` | cpp:131-135 | temp_directory_path 转发 | makeTempPath |
| `makeTempPath(prefix, suffix="")` | cpp:137-145 | 三元唯一临时路径 | DecryptionModule（12 处调用者之一） |

## 9. 关联矩阵（消费方全量，17 文件）

| 消费方 | 调用点数 | 用途 | 取的路径 |
|---|---|---|---|
| ImageAnalyzer/DecryptionModule.cpp | 12 | 解密工具定位、密钥目录、临时文件 | projectRoot、makeTempPath |
| TaskManager.cpp | 4 | 任务目录/库路径 | getTaskDir/getTaskDbPaths |
| TaskManagerAnalysis.cpp | 3 | 流水线产物路径 | 同上 |
| TaskHelpers/TaskSerialization/TaskPersistence | 4 | tasks.json 与任务字段 | getTasksJsonPath 等 |
| main.cpp | 2 | initialize + 覆盖回写 | 全部 |
| 路由层（Search/Filter/FileExtraction/Task/CaseManager/SystemInfo） | 6 | FTS 根、提取目录、案件目录、系统信息 | getDataDir/getTaskDir |
| ConfigManager.cpp | 1 | .env 候选目录 | getExeDir/getProjectRoot |
| FileFilter.cpp | 1 | 画像目录候选 | 同上 |
| NativeFilesystemWalker.cpp | 1 | 根定位 | projectRoot |
| DatabaseAnalyzer/PostgreSQLDaemon.cpp | 1 | 配置文件定位 | 同上 |
| AndroidDataParsers.cpp | 1 | 资源定位 | 同上 |

被调方：仅 std::filesystem 与（间接）unistd 的 getpid。

## 10. 配置影响表

| 参数 | 默认 | 影响 | 备注 |
|---|---|---|---|
| `PROJECT_ROOT` | 空=按可执行文件自动检测（main.cpp:61-64） | projectRoot_ 覆盖 | run.sh 显式剔除该行（run.sh:76-77）；建议绝对路径 |
| `DATA_DIR` | `data`（main.cpp:65） | dataDirName_；绝对路径时脱离 projectRoot | 相对/绝对分流见 4.2 |
| `TMPDIR`/`TMP` | 系统默认 | getTempDir → makeTempPath 的落点 | 环境变量非 .env |
| `FTS_ALLOWED_ROOT` | 未设=getDataDir | HTTP 索引白名单根 | SearchRoutes.cpp:17-35 |
| （无键） | — | 任务内文件名 raw.db 等七个**固定不可配** | 冻结约定 |

## 11. 性能与并发细节

- **纯函数式 getter**：无缓存（dataDir_ 现拼）、无锁——启动后路径成员只读，多线程并发 get* 安全；setter 仅限启动期（第 6 节）。开销为一次 path 拼接（纳秒级），任务级调用频率下可忽略。
- **唯一的 IO 在 ensure**：ensureDirectories/ensureTaskDir 的 create_directories 是幂等目录树创建，任务创建时一次、毫秒级。
- **makeTempPath 的静态计数器**是本模块唯一的可变共享状态（atomic），并发安全。
- **内存**：三个成员（两个 path 一个 string），常驻百字节。
- **可调参数影响**：DATA_DIR 指向不同磁盘可把库写入与镜像读分离（IO 分流是唯一性能相关的用法）；绝对路径绕过 projectRoot 使多实例同盘根下互不干扰。


## 12. 产物路径字典（本模块视角的全量路径清单）

PathManager 能产出的每一条路径及其真实写入方（"写入方为空"=规范位置无写入，接线状态一目了然）：

| 路径 | 生成函数 | 写入方 | 状态 |
|---|---|---|---|
| `<data>/tasks.json` | getTasksJsonPath | TaskPersistence（任务增删改后序列化） | 在用 |
| `<data>/tasks/<id>/` | getTaskDir/ensureTaskDir | TaskManagerAnalysis 建目录 | 在用 |
| `<data>/tasks/<id>/raw.db` | getTaskDbPaths.rawDb | ImageAnalyzer→DatabaseManager | 在用 |
| `<data>/tasks/<id>/events.db` | .eventsDb | EventExtractor | 在用 |
| `<data>/tasks/<id>/files.db` | .filesDb | FileClassifier + 平台 Analyzer 工件 | 在用 |
| `<data>/tasks/<id>/android.db` | .androidDb | 平台深度分析路径（当前工件并入 files.db，独立库仅遗留调用） | 半退役 |
| `<data>/tasks/<id>/windows.db` / `linux.db` / `oss.db` | 同结构字段 | 同上 | 半退役 |
| `<data>/tasks/<id>/extracted_files/` | getTaskExtractDir | HTTP 提取路由→FileExtractor | 在用 |
| `<data>/audit/forensics_audit.db` | getAuditDbPath | **无**（实际落 CWD 的 forensics_audit.db，见第 5 节） | **未接线** |
| `<data>/logs/forensics.log` | getLogFilePath | **无**（Logger 恒 STDOUT） | **未接线** |
| `<data>/logs/debug.log` | getDebugLogPath | **无** | **未接线** |
| `<系统临时目录>/<prefix><pid>_<tid>_<n><suffix>` | makeTempPath | DecryptionModule 挂载/解密中间文件 | 在用（用后即删） |

注意 CLI 形态**不经本模块**：`<镜像名>_raw.db` 等前缀式产物由 AnalysisOrchestrator 自行拼装（Orchestrator.cpp:196-202）——PathManager 只服务 HTTP 任务形态。两套命名并存是"同系统两种运行形态"在文件系统上的投影。

**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
