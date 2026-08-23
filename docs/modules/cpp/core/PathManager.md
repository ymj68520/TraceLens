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

## 4. 工作流程走读

以一次 HTTP 分析任务创建路径为例：

1. 服务启动：`initialize(argv[0])` 解析出 exeDir（`PathManager.cpp:12-40`）；`main.cpp:61-65` 读到 `PROJECT_ROOT`/`DATA_DIR` 后调用 `setProjectRoot`/`setDataDirName`（空串被忽略，`PathManager.cpp:119-129`，防止误把根清空）；`ensureDirectories()` 用 `create_directories` 建好 data/ 四个子目录（`PathManager.cpp:42-48`，幂等）。
2. TaskManager 收到新任务，生成 UUID，调用 `getTaskDbPaths(taskId)` 一次性拿到七个库路径（`PathManager.cpp:102-115`），`ensureTaskDir` 顺带创建任务目录。
3. 流水线各阶段向这些路径写库；任务状态变化时 TaskPersistence 写 `getTasksJsonPath()`。
4. 路由层收到查询请求，同样用 `getTaskDir(taskId)` 拼出库文件路径——写方和读方引用同一函数，天然一致。

## 5. 与其他模块的协作

- **ConfigManager**：双向依赖的解法是"时序"——ConfigManager 找 `.env` 时调用 `PathManager::getExeDir()/getProjectRoot()`（`ConfigManager.cpp:26-31`，带 try/catch，因为此时 PathManager 可能未初始化）；反向地，main.cpp 把 ConfigManager 读到的 PROJECT_ROOT/DATA_DIR 回写给 PathManager。
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

## 7. 如何验证与扩展

- 单元测试：PathManager 没有独立的 gtest 目标；最直接的验证是运行 `./run.sh` 启动服务、创建一个任务，然后检查 `data/tasks/<uuid>/` 下七个库文件是否齐备。
- 快速实验：分别用 `DATA_DIR=/tmp/tl_data ./forensic_analyzer ...` 和默认配置各跑一次，对比数据落点，验证第 3 节的绝对路径规则。
- 扩展场景入手点：(1) 接线审计库路径——改 `main.cpp:69-74` 用 `getAuditDbPath().string()` 作为默认值；(2) 新增任务级产物目录（如 carved_files）——在 `PathManager.h:120-122` 旁加一个 `getTaskDir(id) / "carved_files"` 的内联函数，并在使用方统一改调它，不要在业务代码里手拼字符串。

**最后更新**: 2026-08-23（解释式重写）
