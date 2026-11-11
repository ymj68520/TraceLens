# 环境变量参考：.env 完整手册

> 来源：`.env.example`（全量声明）+ 全部实际读取点。C++ 侧经
> `ConfigManager`（`src/core/ConfigManager/ConfigManager.cpp`，dotenv 库）；
> Python httpserver 侧经 pydantic `Settings`（`python_service/httpserver/config.py`）；
> Graphiti 管线侧经 `GraphitiConfig.from_env`（`python_service/graphiti_integration/config.py`）；
> 分布式 C/S 侧经 `python_service/server/config.py`；零散 `getenv` 逐点标注。
> file:line 均相对仓库根。**默认值列为"读取点代码中的缺省值"**，与 .env.example 的示例值可能不同。

## 1. .env 的加载机制（谁在什么时候读）

| 进程 | 加载逻辑 | 位置 |
|---|---|---|
| C++ forensic_analyzer | 启动即 `ConfigManager::load(".env")`，搜索顺序：`.env` → 可执行文件目录 → PROJECT_ROOT → `../`、`../../`、`../../../`，首个存在者生效 | main.cpp:56；ConfigManager.cpp:17-44 |
| Python httpserver (8090) | `find_env_file()` 从 CWD 向上逐级找 `.env`；pydantic-settings，`extra="ignore"`、大小写不敏感 | httpserver/config.py:18-26,125-130 |
| Python C/S server (8091) | `env_file=".env"`（相对 CWD），`case_sensitive=True`、`extra="ignore"`（共享同一份根 .env，必须忽略对方变量） | server/config.py:88 |
| Graphiti 集成 | `load_dotenv` 从 CWD 向上最多 5 级 | graphiti_integration/config.py:69-80 |
| run.sh | `set -a; source .env`，但**过滤掉** `PYTHON_CORS_ORIGINS=`（C++ dotenv 解析不了）与 `PROJECT_ROOT=`（空值会覆盖脚本推定的根） | run.sh:59-77 |

## 2. 路径与目录

| 变量 | 默认值 | 读取点 | 备注 |
|---|---|---|---|
| `PROJECT_ROOT` | C++ 空=按可执行文件自动检测；Python 空=按 `__file__` 上推 | C++ main.cpp:61-64；Python httpserver/config.py:30-38 | run.sh 显式忽略该变量（run.sh:70,76-77） |
| `DATA_DIR` | `data` | C++ main.cpp:65（`PathManager::setDataDirName`）；Python httpserver/config.py:138 | 决定 `data/tasks/<task_id>/` 任务目录布局 |

## 3. LLM 连接与模型

| 变量 | 默认值（C++ / Py） | 读取点 | 备注 |
|---|---|---|---|
| `LLM_BASE_URL` | `http://192.168.31.170:1234` / 同 | C++ ConfigManager.cpp:86；Py config.py:159 | |
| `LLM_ENDPOINT` | `/v1/chat/completions` / 同 | C++ :87；Py :160 + 校验器 :163-170 | Py 校验器把"裸模型名"等旧值规范回 `/v1/chat/completions` |
| `LLM_API_KEY` | 空 / 空 | C++ ConfigManager.cpp `getLLMApiKey`；Py `llm_api_key`；Graphiti 回落 | 文本/视觉未单独配 key 时的共享回落 |
| `LLM_TEXT_API_KEY` | 空=回落 `LLM_API_KEY` | C++ `getTextApiKey`；Py `llm_api_key_for("text")`；Graphiti `from_env` 与 `_build_graphiti_config` | 空串与纯空白都回落，.env 里留空占位行不影响 |
| `LLM_TEXT_BASE_URL` | 回退 `LLM_BASE_URL` / `http://192.168.31.170:1234` | C++ :100；Py :172；Graphiti config.py:83（自动补 `/v1`） | |
| `LLM_TEXT_MODEL` | C++ `gpt-oss`；Py `openai/gpt-oss-20b`；Graphiti `openai/gpt-oss-20b` | C++ :101；Py :173；Graphiti :93 | **C++ 缺省与 Python 不同**，建议显式设置 |
| `LLM_TEXT_MAX_TOKENS` | C++ `2048`；Py `4096` | C++ :102；Py :174 | **两侧缺省不一致**；.env.example 给 4096 |
| `LLM_TEXT_TEMPERATURE` | `0.7` / `0.7` | C++ :103；Py :175 | |
| `LLM_VISION_API_KEY` | 空=回落 `LLM_API_KEY` | C++ `getVisionApiKey`；Py `llm_api_key_for("vision")` | 视觉请求与 `/v1/models` 探活用；语义同文本 key |
| `LLM_VISION_BASE_URL` | 回退 `LLM_BASE_URL` / `http://192.168.31.170:1234` | C++ :119；Py :177 | |
| `LLM_VISION_MODEL` | C++ `qwen3-vl`；Py `qwen/qwen3-vl-4b` | C++ :120；Py :178 | 两侧缺省不同 |
| `LLM_VISION_MAX_TOKENS` | `4096` / `4096` | C++ :121；Py :179 | |
| `LLM_VISION_TEMPERATURE` | `0.5` / `0.5` | C++ :122；Py :180 | |
| `LLM_TIMEOUT_SECONDS` | `120` / `120` | C++ :89；Py :182 | |
| `LLM_MAX_RETRIES` | `3` / `3` | C++ :90；Py :183 | |
| `LLM_MAX_CONCURRENCY` | C++ `1`（钳 1..64）；Py `1`（ge=1 le=64） | C++ ConfigManager.cpp:142-149；Py config.py:227 | C++ 侧 0/负值按 1 处理（worker 池不能无界）；每个 worker 独立 LLMClient。.env.example 示例 32 |
| `LLM_THINKING_MODE` | 空（不注入 thinking 字段）；仅接受 `enabled`/`disabled`，其余按空处理 | C++ ConfigManager.cpp:101-104；Py config.py:194-201 | DeepSeek 式思考开关，作为顶层 `thinking` 请求字段发送 |
| `LLM_MAX_ARTIFACTS` | C++ `500`（钳 1..100000，`0`=显式不限）；Py `500`（ge=1 le=100000） | C++ ConfigManager.cpp:124；Py config.py:347 | 工件 LLM 分析预算 |
| `LLM_SMART_CANDIDATE_FILES` | `1000`（钳 1..100000，`0`=显式不限） | C++ ConfigManager.cpp:123（Python 侧不读，见 config.py:336 注释"owned by the C++ side"） | smart 粗选扫描上限，应 ≥ `LLM_MAX_FILES`。.env.example 示例 5000 |
| `LLM_ARTIFACT_BATCH_SIZE` | `1`（钳 1..64，`0`=显式不限） | C++ ConfigManager.cpp:134 | 工件按 N 条/请求打包（1=旧式逐条调用） |
| `LLM_ARTIFACT_BATCH_RETRIES` | `1`（钳 1..5） | C++ ConfigManager.cpp:135 | 工件批量调用失败重试次数 |
| `ANDROID_ARTIFACT_LLM_CONCURRENCY` | `32`（钳 1..64，0/负值按 1） | C++ ConfigManager.cpp:152-158 | Android 工件逐条扇出的硬 worker 上限；不在 .env.example |
| `WIN_LINUX_ARTIFACT_LLM_ENABLED` | `false` | C++ ConfigManager.cpp:160 | 提取后 Windows/Linux 工件 LLM 管线开关（MVP §4.8 裁剪为默认关）；不影响结构化提取与 Android |
| `LLM_MAX_EVENT_CLUSTERS` | `200`（有界缺省，钳 1..100000；显式设 `0` 才是"不限"） | C++ ConfigManager.cpp:122（`bounded_limit`）；消费点 TaskManagerAnalysis.cpp | .env.example 示例同步为 200 |
| `LLM_CONTEXT_LENGTH` | C++ `4096`；Py `4096` | C++ :176；Py :184 | .env.example 写 `163840`，**代码缺省远小于示例值** |
| `LLM_RESERVED_TOKENS` | —（无读取点） | 仅 .env.example | **未接线** |
| `LLM_CHARS_PER_TOKEN` | —（无读取点） | 仅 .env.example | **未接线** |

## 4. MCP（当前整体未接线）

| 变量 | 声明值 | 读取点 | 状态 |
|---|---|---|---|
| `MCP_SERVER_PORT` | `8890` | 无任何代码引用 | **未接线** |
| `MCP_SERVER_HOST` | `localhost` | 无任何代码引用（C++ 读的是另一个名字 `MCP_HOST`，见第 10 节） | **未接线** |
| `MCP_ALLOWED_PATHS` | 空 | 无任何代码引用 | **未接线** |

唯一在用的 MCP 变量是 `MCP_HOST`（缺省 `0.0.0.0`），由
`src/integration/LLMIntegration/MCPIntegration.cpp:35` 读取，不在 .env.example 中。

## 5. 文件分析与数据库

| 变量 | 默认值 | 读取点 | 备注 |
|---|---|---|---|
| `FILE_ANALYSIS_MAX_CONTENT` | `10000` / `10000` | C++ ConfigManager.cpp:174；Py config.py:222 | |
| `FILE_ANALYSIS_MAX_KEYWORDS` | `10` / `10` | C++ :175；Py :223 | |
| `FILE_ANALYSIS_MAX_CONTENT_LIMIT` | Py `12000` | Py config.py:224 | .env.example 写 `50000`，与代码缺省 `12000` 不一致；C++ 不读 |
| `LLM_MAX_CONTENT_LENGTH` | `10000` | C++ :96（消费 FileAnalyzer.cpp:199） | 与上一条是两个不同变量 |
| `LLM_MAX_FILES` | `500` | C++ :91 | 全局默认预算；单任务可用请求字段 `llm_max_files` 覆盖（0=继承本值） |
| `LLM_SKIP_BINARY` | `true` | C++ :97 | |
| `DB_OUTPUT_DIR` | `./output` / `./output` | C++ :179；Py :211 | |
| `DB_NAME` | `forensics.db` / `forensics.db` | C++ :180；Py :212 | |

## 6. Neo4j / Graphiti（注意两套读取点）

httpserver 的 `Settings` 与 `GraphitiConfig.from_env` 都会读这些变量，**缺省值不完全一致**：

| 变量 | httpserver 默认 | GraphitiConfig 默认 | 读取点 |
|---|---|---|---|
| `NEO4J_URI` | `neo4j://127.0.0.1:7687` | 同 | Py config.py:196；graphiti config.py:89 |
| `NEO4J_USER` | `neo4j` | 同 | Py :197；graphiti :90 |
| `NEO4J_PASSWORD` | 空 | 空 | Py :198；graphiti :91（.env.example 示例 `change-me`） |
| `GRAPHITI_LLM_API_KEY` | 空=回落文本 key，再回落 `LLM_API_KEY` | 同 | Py `graphiti_llm_api_key`；graphiti `from_env`。空白与空串都回落 |
| `GRAPHITI_USE_LOCAL_LLM` | `true` | `true` | Py :200；graphiti :107 |
| `GRAPHITI_BATCH_SIZE` | **`50`** | **`10`** | Py :201；graphiti :104。**两处缺省不一致（50 vs 10）**；.env.example 又给 `25`。实际生效值取决于哪条代码路径读的：管线 CLI 用 GraphitiConfig=10，httpserver 任务用 Settings=50 |
| `GRAPHITI_MAX_RETRIES` | `3` | `3` | Py :202；graphiti :105 |
| `GRAPHITI_GROUP_ID` | `forensics_files` | 同 | Py :203；graphiti :106 |
| `GRAPHITI_INCLUDE_FULL_DESC` | **`true`** | **`false`** | Py :207；graphiti :109。**两处缺省相反** |
| `GRAPHITI_MAX_EPISODE_TOKENS` | `3000` | `3000` | Py :208；graphiti :108 | |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_DIM` | — / `text-embedding-nomic-embed-text-v1.5` / 空=回落图谱 key→文本 key→`LLM_API_KEY`→`OPENAI_API_KEY` / `768` | graphiti `from_env`；Py `embedding_api_key` | |
| `GRAPHITI_DB_PATH` | 空 | graphiti config.py:103 | 不在 .env.example |

C++ 侧的摄取等待预算（`TaskManagerAnalysis.cpp` 读取，TaskManager 自带轮询取代了旧的 `LLMPythonProxy::wait_for_job_completion`，见 TaskManagerAnalysis.cpp:310-325 注释）：

| 变量 | 默认 | 读取点 | 备注 |
|---|---|---|---|
| `GRAPHITI_INGEST_WAIT_TIMEOUT_MIN` | `720`（分钟，与 Python 侧 12h 对齐） | TaskManagerAnalysis.cpp:316,1668 | C++ FINALIZING 等待 Graphiti 摄取 job 的预算；`0` 恢复旧的 fire-and-forget 完成。.env.example 示例 720 |
| `GRAPHITI_INGEST_RETRIES` | `2`（总尝试 = 1 + RETRIES） | TaskManagerAnalysis.cpp:323 | 摄取失败重试次数；仅在 .env.example 的注释中被提及，无显式示例行 |
| `GRAPHITI_INGEST_POLL_SECONDS` | `10` | TaskManagerAnalysis.cpp:365 | 自带轮询的间隔；仅在 .env.example 注释中被提及 |

## 7. 端口与服务地址（联动关系）

| 变量 | 默认值 | 读取点 | 备注 |
|---|---|---|---|
| `HTTP_SERVER_PORT` | C++ `8080`；Py `8080` | C++ ConfigManager.cpp:140（供信息接口）；Py config.py:142；vite.config.js:10（前端代理缺省 8080）；web/src/services/api.js:4 | run.sh 经 `scripts/lib/tracelens_env.sh:38` 的 `: "${HTTP_SERVER_PORT:=8080}"` 同样回退 **8080**——与代码缺省一致。`8666` 只是 `.env.example` 模板示例值（复制模板部署时生效） |
| `HTTP_SERVER_HOST` | `0.0.0.0` / `0.0.0.0` | C++ :141；Py :143 | |
| `PYTHON_HTTP_PORT` | `8090` | Py config.py:133；C++ ConfigManager.cpp:142（组装 Python 服务 URL 的回退端口）；run.sh:80 | |
| `PYTHON_HTTP_HOST` | `0.0.0.0` | Py config.py:134 | |
| `PYTHON_SERVICE_URL` | C++：`PYTHON_SERVICE_URL` 优先，否则 `http://localhost:<PYTHON_HTTP_PORT>` | C++ ConfigManager.cpp:142（LLMPythonProxy.h:69、MarkitdownProxy.cpp:22、FileAnalyzer.cpp:173）；OfficeAnalyzer.cpp:21 **直接 getenv，缺省硬编码 `http://localhost:8090`，不回退 PYTHON_HTTP_PORT** | 不在 .env.example。若把 Python 服务换端口，必须显式设此变量，否则 OfficeAnalyzer 仍打 8090 |
| `CPP_BACKEND_URL` | `http://localhost:8080` | Py config.py:141（CppBackendService 与 multi_analysis 回调 C++ 用） | 与 `cpp_backend_base_url` 属性（`http://<HTTP_SERVER_HOST>:<HTTP_SERVER_PORT>`，config.py:294-297）并存，两条拼法 |
| `CS_PORT` | `8091` | run.sh:81 | 不在 .env.example，仅 run.sh 用 |

启动/恢复预算（仅 httpserver Settings 读取）：

| 变量 | 默认 | 读取点 |
|---|---|---|
| `CPP_STARTUP_REQUEST_TIMEOUT` | `5.0` | Py config.py:151 |
| `CPP_RECOVERY_TIMEOUT` | `8.0` | Py :152 |
| `NEO4J_CONNECT_TIMEOUT` | `5.0` | Py :153 |
| `NEO4J_QUERY_TIMEOUT` | `5.0` | Py :154 |
| `OPTIONAL_SERVICE_INIT_TIMEOUT` | `12.0` | Py :155 |
| `PYTHON_STARTUP_TIMEOUT` | `30.0` | Py :156 |

## 8. 调试 / 日志 / CORS

| 变量 | 默认值 | 读取点 | 状态 |
|---|---|---|---|
| `DEBUG_OUTPUT_MODE` | `stdout` / `stdout` | C++ ConfigManager.cpp:183；Py config.py:229 | |
| `DEBUG_LOG_FILE` | `debug.log` | 仅 .env.example | **未接线**（实际调试日志路径是 PathManager 固定的 `logs/debug.log`，PathManager.cpp:96-98） |
| `LOG_LEVEL` | `INFO` / `INFO` | C++ ConfigManager.cpp:181（无调用方）；Py config.py:227（仅 health.py:262 回显） | **未接线**：不驱动任何实际日志级别 |
| `LOG_FILE` | `forensics.log` / `forensics.log` | C++ :182（无调用方）；Py config.py:228（system_logs.py:78-93 找日志用的是固定路径表，不读它） | **未接线** |
| `PYTHON_CORS_ORIGINS` | `["*"]` | Py config.py:236-241 + 解析 :243-271（JSON 数组，回退逗号分隔） | run.sh 会把它从 source 中剔除（run.sh:69） |
| `CORS_ALLOW_ORIGIN` | `*` | C++ RouteHelpers.cpp:16-17（C++ HTTP 响应头） | 不在 .env.example |

## 9. 性能 / 数据库行为 / DLL / OSS

| 变量 | 默认值 | 读取点 | 备注 |
|---|---|---|---|
| `THREAD_POOL_SIZE` | `4` / `4` | C++ ConfigManager.cpp:138（TaskManager.cpp:23、FileAnalyzer.cpp:280）；Py config.py:232 | |
| `MAX_BATCH_SIZE` | `100` / `100` | C++ :139；Py :233 | |
| `LOG_MAX_DISPLAY_FILES` | `20` | C++ :157；消费 ImageAnalyzer.cpp:403,557,730,809 | |
| `DB_JOURNAL_MODE` | `WAL` | C++ :147 | |
| `DB_BUSY_TIMEOUT_MS` | `5000` | C++ :146 | 不在 .env.example |
| `DB_SYNCHRONOUS_OFF` | `false` | C++ :148 | 不在 .env.example |
| `SEARCH_MAX_CACHE_SIZE` / `SEARCH_MAX_CONTENT_LENGTH` / `SEARCH_SNIPPET_LENGTH` / `SEARCH_DEFAULT_LIMIT` | `1000` / `50000` / `150` / `10` | C++ :151-154；消费 FullTextSearch.cpp:66,83 | 不在 .env.example |
| `EXTRA_<CATEGORY>_EXTS` | 空 | C++ :159-173；消费 FileClassifierMappings.cpp（IMAGE/VIDEO/AUDIO/DOCUMENT/ARCHIVE/EXECUTABLE/DATABASE/SOURCE_CODE/WEB/EMAIL/SYSTEM/ENCRYPTED） | 逗号分隔，如 `EXTRA_IMAGE_EXTS="webp,avif"` |
| `DLL_ANALYSIS_ENABLED` | `true` | Py config.py:146 | |
| `DLL_CPP_BACKEND_URL` | `http://localhost:8080` | Py config.py:147 | **未接线**：字段定义后无任何消费者（DLL 路由实际用 `cpp_backend_url`） |
| `DLL_ANALYSIS_TIMEOUT` | `30.0` | Py config.py:148；消费 dll_analyzer.py:26 | |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_ENDPOINT` / `OSS_REGION` | 空/空/空/`cn-hangzhou` | Py config.py:190-193 | |

## 10. 只存在于 getenv / Settings、不在 .env.example 的变量

| 变量 | 默认 | 读取点 | 用途 |
|---|---|---|---|
| `AUDIT_LOG_DB` / `AUDIT_LOG_CACHE_SIZE` / `AUDIT_LOG_WAL` | `forensics_audit.db` / `100` / `true` | main.cpp:70-72 | C++ 审计库 |
| `TASK_WATCHDOG_STALE_MINUTES` / `TASK_WATCHDOG_PENDING_MINUTES` | `30` / `30` | TaskWatchdog.cpp:29,33 | 任务看门狗 |
| `FTS_ALLOWED_ROOT` | 未设=不限制 | SearchRoutes.cpp:20 | 检索路由的根目录白名单 |
| `FORENSICS_PROJECT_ROOT` | 空 | ImageAnalyzer/DecryptionModule.cpp:462 | 解密工具（cryptsetup 等）的根定位 |
| `MCP_HOST` | `0.0.0.0` | MCPIntegration.cpp:35 | MCP 集成（与未接线的 MCP_SERVER_HOST 是两个名字） |
| `FILE_FILTER_MODE` / `FILTER_MAX_FILES` | `deterministic` / `0` | httpserver/config.py:280-292 | 文件筛选模式 |
| `FORENSIC_REPORT_DIR` / `FORENSIC_REPORT_GENERATOR_VERSION` | `build/data/reports` / `1.0.0` | httpserver/config.py:214-219 | 报告输出 |
| `REDIS_URL` | `redis://localhost:6379` | httpserver/config.py:187 | 采集任务管理器可选 Redis，缺省回退内存 |
| `WINDIR` | 系统 | DLLAnalyzerCore.cpp:305 | Windows 系统目录 |
| `HOME` | 系统 | MemoryAnalyzerCore.cpp:140 | vol3 符号默认搜索 |
| `TRACELENS_SERVER_URL/POLL_INTERVAL/REINDEX_INTERVAL/TOKEN_PATH/HOSTNAME/ANALYZER_PATH/WORK_DIR/STATE_DB/IMAGE_DIRS` | 见 client_config.cpp | http_agent/client_config.cpp:107-115 | http_agent 客户端 |
| `TRACELENS_MIUI_MAX_MANIFEST_PACKAGES/_FIELD_BYTES/_METADATA_BYTES` | 见源文件 | MiuiBackupManifest.cpp:26-31 | MIUI 清单解析上限 |
| `TRACELENS_MIUI_MAX_CANDIDATES` | 见源文件 | MiuiArtifactParsers.cpp:49,149 | MIUI 工件候选上限 |

现场认证 / 安全开关（均不在 .env.example，属现场部署变量，详见 [Deployment §10](../architecture/Deployment.md)）：

| 变量 | 触发值 | 读取点 | 用途 |
|---|---|---|---|
| `TRACELENS_FIELD_AUTH` | `enabled` | C++ ConfigManager.cpp:15（`field_ai_disabled`）、HTTPserver.cpp:92-108、:135；scripts/android_field_check.py:54 | 现场模式总开关：启用后 `/api/security/status` 的 `field_auth=true`、CORS 不再放行 `*`，且要求服务绑定 loopback（127.0.0.1/::1）并完成 field runtime 自检；`enabled` + `FIELD_OUTBOUND_POLICY` 缺省/disabled 时 C++ 侧禁用出站 AI |
| `TRACELENS_REQUIRE_FIELD_AUTH` | `1` | HTTPserver.cpp:86-87（启动校验）、:135-136 | 强制现场认证：置 1 而 `TRACELENS_FIELD_AUTH` 未 enabled 时 C++ 拒绝启动；同时驱动认证中间件口径 |
| `TRACELENS_REQUIRE_RELEASE_LAYOUT` | `1` | HTTPserver.cpp:97-107；FieldApp.cpp:97；AndroidContainerNormalization.cpp:50；FilesystemEvidenceSource.cpp:94 | 发布布局校验：要求 `TRACELENS_RELEASE_ID` 与编译期身份一致（工作树构建的 `UNFROZEN_WORKTREE` 会被拒绝） |
| `VITE_FIELD_RELEASE_BUILD` | `1` | web/vite.config.js:101（构建期） | 前端发布构建开关：置 1 时关闭 sourcemap（现场部署产物不带映射） |

## 11. 分布式 C/S server（python_service/server，端口 8091）

| 变量 | 默认 | 读取点 | 备注 |
|---|---|---|---|
| `PORT` | `8091` | server/config.py:39 | 与 httpserver 的 8090 共存设计（注释 :33-37）；run.sh 用 `CS_PORT` 覆盖启动（run.sh:244） |
| `HOST` | `0.0.0.0` | server/config.py:38 | |
| `JWT_SECRET_KEY` | `change-this-in-production` | server/config.py:54 | .env.example 示例 `change-me-generate-a-unique-secret`；生产必须改 |
| `JWT_ALGORITHM` | `HS256` | server/config.py:55 | |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/tracelens` | server/config.py:42-45 | .env.example 示例口令为 `change-me` |
| `DB_CONNECT_TIMEOUT` / `DB_POOL_TIMEOUT` / `DB_STARTUP_TIMEOUT` | `5` / `5` / `30` | server/config.py:49-51 | |

## 12. 未接线清单（汇总）

以下变量在 .env.example 中声明，但**当前没有任何运行代码读取其值**：

| 变量 | 声明处 | 说明 |
|---|---|---|
| `MCP_SERVER_PORT` / `MCP_SERVER_HOST` / `MCP_ALLOWED_PATHS` | .env.example "MCP Server Settings" | 全仓库无引用；C++ 侧另有 `MCP_HOST` 在用 |
| `LOG_LEVEL` / `LOG_FILE` | .env.example "Logging Settings" | C++ getter 无调用方；Python 仅在 `/api/system/health` 回显、不驱动日志 |
| `DLL_CPP_BACKEND_URL` | .env.example "DLL Analysis Configuration" | Settings 字段无消费者（config.py:147） |
| `LLM_RESERVED_TOKENS` / `LLM_CHARS_PER_TOKEN` | .env.example "Context Window Settings" | 无引用；上下文预算实际只用 `LLM_CONTEXT_LENGTH` |
| `DEBUG_LOG_FILE` | .env.example "Debug Logging Settings" | 无引用；实际路径固定为 `logs/debug.log` |

## 13. 最小可用配置集（单机、本地 LLM、含知识图谱）

以下覆盖代码缺省中"必须显式对齐"的项；其余均可依赖缺省：

```bash
# ---- 端口（代码与 run.sh 兜底一致为 8080；按需显式对齐）----
HTTP_SERVER_PORT=8080
PYTHON_HTTP_PORT=8090
CPP_BACKEND_URL=http://localhost:8080

# ---- LLM（本地 LM Studio / Ollama）----
LLM_BASE_URL=http://192.168.31.170:1234
LLM_TEXT_BASE_URL=http://192.168.31.170:1234
LLM_TEXT_MODEL=openai/gpt-oss-20b
LLM_VISION_BASE_URL=http://192.168.31.170:1234
LLM_VISION_MODEL=qwen/qwen3-vl-4b

# ---- 知识图谱 ----
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<你的口令>
GRAPHITI_BATCH_SIZE=25
GRAPHITI_INCLUDE_FULL_DESC=true

# ---- C/S server（可选；不用可整段删）----
PORT=8091
JWT_SECRET_KEY=<随机串>
DATABASE_URL=postgresql://postgres:<口令>@localhost:5432/tracelens
```

## 14. 全量配置集样例

与 `.env.example` 主体对应（节选；标注★的行存在缺省不一致或未接线，见上文各节）：

```bash
# 路径
# PROJECT_ROOT=/abs/path            # 留空自动检测；run.sh 会忽略此行
DATA_DIR=data

# LLM 共享（.env.example 现示例为云端占位；本地 LM Studio 兜底为注释行）
LLM_BASE_URL=https://api.example.com
LLM_ENDPOINT=/v1/chat/completions
LLM_API_KEY=

# 文本模型（LLM_TEXT_API_KEY 留空回落 LLM_API_KEY）
LLM_TEXT_BASE_URL=https://api.example.com
LLM_TEXT_API_KEY=
LLM_TEXT_MODEL=step-5-preview
LLM_TEXT_MAX_TOKENS=256000          # ★C++ 缺省 2048
LLM_TEXT_TEMPERATURE=0.7

# 视觉模型（LLM_VISION_API_KEY 留空回落 LLM_API_KEY）
LLM_VISION_BASE_URL=https://api.example.com
LLM_VISION_API_KEY=
LLM_VISION_MODEL=step-5-preview
LLM_VISION_MAX_TOKENS=256000
LLM_VISION_TEMPERATURE=0.5

# 公共
LLM_TIMEOUT_SECONDS=600             # ★代码缺省 120
LLM_MAX_RETRIES=3
LLM_MAX_CONCURRENCY=32              # ★代码缺省 1（钳 1..64）
LLM_THINKING_MODE=                  # 空 = 不发送 thinking 字段
LLM_MAX_EVENT_CLUSTERS=200          # ★旧样例写 0（不限）——现缺省有界 200
LLM_MAX_FILES=50                    # ★代码缺省 500
LLM_SMART_CANDIDATE_FILES=5000      # ★代码缺省 1000
LLM_MAX_ARTIFACTS=500

# MCP（★整组未接线）
MCP_SERVER_PORT=8890
MCP_SERVER_HOST=localhost
MCP_ALLOWED_PATHS=

# 文件分析
FILE_ANALYSIS_MAX_CONTENT=10000
FILE_ANALYSIS_MAX_KEYWORDS=10

# 数据库
DB_OUTPUT_DIR=./output
DB_NAME=forensics.db

# Neo4j / Graphiti
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-me
GRAPHITI_LLM_API_KEY=             # 留空回落 LLM_TEXT_API_KEY，再回落 LLM_API_KEY
GRAPHITI_USE_LOCAL_LLM=true
GRAPHITI_BATCH_SIZE=50              # ★Settings 缺省 50 / GraphitiConfig 缺省 10 / .env.example 示例 50
GRAPHITI_MAX_CONCURRENCY=32         # ★Settings/GraphitiConfig 缺省 1
GRAPHITI_MAX_RETRIES=3
GRAPHITI_GROUP_ID=forensics_files
GRAPHITI_INCLUDE_FULL_DESC=true     # ★GraphitiConfig 缺省 false
GRAPHITI_MAX_EPISODE_TOKENS=256000  # ★代码缺省 3000
GRAPHITI_INGEST_WAIT_TIMEOUT_MIN=720  # C++ FINALIZING 等待摄取预算（0 = 恢复 fire-and-forget）

# Python HTTP 服务
PYTHON_HTTP_PORT=8090
PYTHON_HTTP_HOST=0.0.0.0
CPP_BACKEND_URL=http://localhost:8666     # 模板示例值；与 HTTP_SERVER_PORT 同步改
CPP_STARTUP_REQUEST_TIMEOUT=5
CPP_RECOVERY_TIMEOUT=8
NEO4J_CONNECT_TIMEOUT=5
NEO4J_QUERY_TIMEOUT=5
OPTIONAL_SERVICE_INIT_TIMEOUT=12
PYTHON_STARTUP_TIMEOUT=30

# C++ HTTP 服务
HTTP_SERVER_PORT=8666               # ★模板示例值；代码与 run.sh 兜底均为 8080
HTTP_SERVER_HOST=0.0.0.0

# 上下文窗口
LLM_CONTEXT_LENGTH=1000000          # ★代码缺省 4096
LLM_RESERVED_TOKENS=512             # ★未接线
LLM_CHARS_PER_TOKEN=4.0             # ★未接线
FILE_ANALYSIS_MAX_CONTENT_LIMIT=12000   # ★.env.example 示例已改 12000，与 Python 缺省一致

# 平台工件 LLM（MVP §4.8 默认关）
WIN_LINUX_ARTIFACT_LLM_ENABLED=false

# 调试
DEBUG_OUTPUT_MODE=stdout
DEBUG_LOG_FILE=debug.log            # ★未接线（实际固定 logs/debug.log）

# 日志（★未接线）
LOG_LEVEL=INFO
LOG_FILE=forensics.log

# 性能
THREAD_POOL_SIZE=4
MAX_BATCH_SIZE=100
LOG_MAX_DISPLAY_FILES=20
DB_JOURNAL_MODE=WAL

# DLL
DLL_ANALYSIS_ENABLED=true
DLL_CPP_BACKEND_URL=http://localhost:8666   # ★未接线（示例值随模板端口）
DLL_ANALYSIS_TIMEOUT=30

# OSS
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_ENDPOINT=
OSS_REGION=cn-hangzhou

# CORS
PYTHON_CORS_ORIGINS=["*"]           # run.sh source 时剔除该行

# 分布式 C/S server
PORT=8091
JWT_SECRET_KEY=change-me-generate-a-unique-secret
JWT_ALGORITHM=HS256
DATABASE_URL=postgresql://postgres:change-me@localhost:5432/tracelens
DB_CONNECT_TIMEOUT=5
DB_POOL_TIMEOUT=5
DB_STARTUP_TIMEOUT=30
```

**最后更新**: 2026-11-10（对齐：LLM 有界缺省与新变量、GRAPHITI_INGEST_* 预算、现场认证变量、run.sh 回退 8080、.env.example 现示例值）
