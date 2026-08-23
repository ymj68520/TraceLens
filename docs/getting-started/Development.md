# 开发环境配置

本文档面向 TraceLens 的开发者：目录结构、构建、三个技术栈各自的测试命令、vite 代理，以及"把代码加到哪里"的位置指引。

---

## 1. 目录结构速览

```
TraceLens/
├── setup.sh / run.sh / Makefile       # 一键安装 / 一键构建启动 / 快捷命令
├── .env.example                       # 全量环境变量（见 Installation.md 第 5 节）
├── CMakeLists.txt                     # 主构建（CMake ≥ 3.20，C++20）
├── config/filter_profiles/            # 过滤 profile（general_forensics / telecom_fraud /
│                                      #   data_breach / virus_intrusion，JSON）
├── libs/aliyun-oss-cpp-sdk/           # vendored 阿里云 OSS C++ SDK
├── resources/                         # volatility3 插件（BitLocker FVEK）、dwarf2json 等
├── scripts/                           # 辅助脚本（见第 6 节）
├── src/                               # C++ 主代码
│   ├── core/                          # 基础设施：Logger / ConfigManager / DatabaseManager /
│   │                                  #   FileFilter / FullTextSearch / ThreadPool / ErrorHandling /
│   │                                  #   PathManager / AuditLog / EventCorrelationEngine / TOONExporter
│   ├── analyzers/                     # 平台与专项分析器（Android/Windows/Linux/ImageAnalyzer/
│   │                                  #   MemoryAnalyzer/FileCarving/DLLAnalyzer 等）
│   ├── network/HTTPServer/            # Crow HTTP 服务：HTTPserver、TaskManager、TaskWatchdog、
│   │   └── routes/                    #   LLM*AnalysisService + routes/（按域拆分的路由文件）
│   ├── integration/                   # LLM / MCP / OSS 等外部集成
│   ├── http_agent/                    # HTTP agent 相关
│   ├── export/ 与 report/             # 导出与报告
│   ├── AnalysisOrchestrator.*         # 分析编排（CLI 各模式的流程入口）
│   └── CommandLineParser.* / main.cpp # CLI 定义与入口
├── python_service/
│   ├── httpserver/                    # FastAPI 服务（:8090）：routes/ + services/ + config.py
│   ├── server/                        # 分布式 C/S 服务（:8091）：api/ + db/ + models/ + services/
│   ├── graphiti_integration/          # Graphiti 摄取管线（含独立 tests/）
│   ├── config.py / requirements.txt
│   ├── pytest.ini                     # testpaths=tests；markers: integration/unit/slow/
│   │                                  #   concurrency/migration_matrix；asyncio_mode=auto
│   ├── scripts/test.py                # 稳定回归档案（focused/investigation/fast/full）
│   └── tests/                         # 顶层测 server（C/S），tests/unit/ 测 httpserver 与
│                                      #   evidence/forensic_report/investigation 子包
├── web/                               # React 前端（Vite + Redux Toolkit + Tailwind + d3）
│   ├── vite.config.js                 # dev 端口 3000 + API 代理（见第 5 节）
│   └── src/{pages,components,services,store,hooks,locales,routes.jsx}
└── tests/                             # C++ GTest
    └── UnitTest/                      # test_*.cpp（约 60+ 个测试可执行目标）
```

---

## 2. 构建

```bash
# 推荐：开发日常
./run.sh --build-only           # Release 构建 + web 前端（-j4）
./run.sh --build-only --no-web -j$(nproc)   # 只要 C++

# Makefile
make build                      # cmake -DCMAKE_BUILD_TYPE=Release + --build -j$(nproc)
make web-frontend               # 仅 npm run build
make clean / make rebuild

# 手动
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_WEB_FRONTEND=OFF
cmake --build . -j$(nproc)
```

- `BUILD_WEB_FRONTEND` 默认 ON（CMake 会在 ALL 目标触发 npm）；命令行构建建议 OFF，前端单独 `npm run build`。
- 构建产物：`build/forensic_analyzer`、`build/web/dist/`（run.sh 会把 `web/dist` 同步过去，C++ 从相对路径 `web/dist` 读取前端）。

---

## 3. C++ 测试

```bash
make test                # = test-cpp：cd build && ctest --output-on-failure
# 或
cd build && ctest --output-on-failure

# 单跑某个目标（目标名对应 tests/UnitTest/test_*.cpp）
./build/test_file_classifier --gtest_filter='ClassName.MethodName'
```

测试源码在 `tests/UnitTest/*.cpp`（约 60+ 个 GTest 可执行目标，由 `tests/CMakeLists.txt` 注册）。

---

## 4. Python 测试

```bash
make test-python                                   # pytest tests/ -v（cd python_service）
make test-python-focused ARGS="tests/unit/test_x.py -k foo"
make test-python-investigation                    # Investigation 快速回归（固定路径集合）
make test-python-fast                             # tests/unit 且排除 slow/concurrency/migration_matrix
make test-python-full                             # 完整 unit 套件

# 等价直接调用（任何工作目录均可，脚本自行 cd 到 python_service）
python_service/.venv/bin/python python_service/scripts/test.py fast
python_service/.venv/bin/python python_service/scripts/test.py focused tests/unit/test_filter_config.py

# graphiti_integration 的测试不在 pytest.ini 的 testpaths 内，需单独跑
cd python_service && .venv/bin/python -m pytest graphiti_integration/tests/ -v
```

测试布局：

- `python_service/tests/` 顶层 —— 分布式 `server` 应用（auth/clients/commands/results/tasks 等）；
- `python_service/tests/unit/` —— httpserver 与 `evidence/`、`forensic_report/`、`investigation/` 子包；
- marker：`integration` / `unit` / `slow` / `concurrency` / `migration_matrix`（`--strict-markers`）；
- `asyncio_mode=auto`，异步测试无需逐个标注。

---

## 5. Web 前端

```bash
cd web
npm run dev        # vite 开发服务器，http://localhost:3000
npm run test       # vitest（48 个 *.test.{js,jsx} 文件）
npm run lint       # eslint --max-warnings 0
npm run format     # prettier
npm run build      # 产物 web/dist
```

`vite.config.js` 的代理表（开发模式生效）：

| 前缀 | 目标 |
|------|------|
| `/tasks` 与兜底 `/api` | C++ 服务：`http://localhost:${HTTP_SERVER_PORT || 8080}`（可用 `VITE_CPP_PROXY_TARGET` 覆盖；仓库 `.env` 设了 8666 就转发 8666） |
| `/api/reports`、`/api/graphiti`、`/api/llm`、`/api/office`、`/api/db`、`/api/wechat`、`/api/investigation` | `http://localhost:8090`（Python httpserver） |
| `/csapi`（重写去掉前缀） | `http://localhost:8091`（C/S server） |

注意 `loadEnv(mode, '..', '')` 会向上读取仓库根的 `.env`，所以根目录 `HTTP_SERVER_PORT` 直接影响 dev 代理目标。

---

## 6. 添加代码的位置指引

### 6.1 添加新分析器（C++）

1. 在 `src/analyzers/<NewAnalyzer>/` 新建 `NewAnalyzerCore.{h,cpp}`（可参考现有 `LinuxFilesAnalyzer` 等目录的组织方式：核心逻辑 + Database 子目录）；
2. 在顶层 `CMakeLists.txt` 的 `LIB_SOURCES` 列表追加源文件（如需条件编译，参考 `DecryptionModule.cpp` 的 `list(APPEND LIB_SOURCES ...)` 写法）；
3. 在 `src/AnalysisOrchestrator.cpp` 的流程中接入（它按 CLI 模式编排：全量分析 → 平台分析 → 时间线 → DLL → 报告）；
4. 如需 CLI 开关，在 `src/CommandLineParser.cpp` 的 `printUsage()` + `parse()` 中加参数；
5. 在 `tests/UnitTest/` 加 `test_new_analyzer.cpp` 并在 `tests/CMakeLists.txt` 注册。

### 6.2 添加新 HTTP 路由（C++）

路由按域拆分在 `src/network/HTTPServer/routes/`（如 `StatisticsRoutes.cpp`、`TimelineRoutes.cpp`），每个文件一个聚合器类：

1. 仿照现有文件创建 `XxxRoutes.{h,cpp}`，在 `registerRoutes(crow::App<>& app)` 里写 `CROW_ROUTE(app, "/api/...")`；
2. 需要对外文档时用 `Swagger::instance().RegisterEndpoint(...)` 注册（现有文件均有示例）；
3. 把源文件加入 `CMakeLists.txt` 的 `LIB_SOURCES`，并在 `HTTPserver.h/.cpp` 中实例化并调用聚合器（参考 `TaskRoutes` 组合 `TaskCRUDRoutes/TaskBatchRoutes/TaskMonitoringRoutes` 的方式）。

### 6.3 Python httpserver 路由

`python_service/httpserver/routes/` 下新增模块，在 `main.py` 的 `create_app()` 中 `app.include_router(xxx.router, prefix="/api/xxx", tags=[...])`（简单端点也可像 `system.py` 一样在路由内写全路径）。

### 6.4 前端

- 页面：`web/src/pages/`；组件：`web/src/components/`；
- API 封装：`web/src/services/`（如 `taskService.js`、`graphitiService.js`）；
- 状态：`web/src/store/`（Redux Toolkit）；路由：`web/src/routes.jsx`。

---

## 7. 常用开发命令汇总

```bash
./run.sh --no-build              # 只启动服务（改了 Python/前端之外无需重编）
./run.sh --no-python             # 只启动 C++（调 C++ 时）
make web-dev                     # 前端热更新开发（3000，代理到 C++/Python）
make cpp                         # 单起 C++（${HTTP_SERVER_PORT:-8080}）
make python                      # 单起 httpserver（8090）
make test / make test-python-full
make acceptance-smoke            # 隔离环境的活服务冒烟（scripts/acceptance/live_services.py）
make acceptance-task             # Task → Evidence 旅程
make acceptance-analyst          # Investigation → Report 旅程
make acceptance-restart          # 进程重启恢复旅程
make acceptance-matrix           # Markitdown/Office/DLL 交接矩阵
```

---

## 相关文档

- **[安装指南](Installation.md)** - 依赖与 `.env` 变量
- **[常见任务](CommonTasks.md)** - 面向使用者的工作流（也是验证改动的手段）
- **[故障排查](Troubleshooting.md)** - 健康检查与日志定位

---

**最后更新**: 2026-08-23（以代码为准重写）
