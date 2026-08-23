# 验收框架指南（AcceptanceHarness）

本文是 `scripts/acceptance/live_services.py`（1081 行）的源码级指南。它是**进程级验收框架**而非替代启动器：启动真实的 C++/Python 服务入口点、等待真实健康端点、跑预设旅程并在失败时收集诊断。现有 `docs/testing/live-integration.md` 记录了 Phase F 的历史执行情况，本文以脚本源码为准。

## 一句话模型

```
临时工作区 tracelens-acceptance-XXXX/   ← tempfile.mkdtemp（live_services.py:210）
├── .env              ← 框架自己写（:286-323），指向工作区内部与随机端口
├── data/{tasks,audit,logs}
├── output/ reports/ fixture/          ← notes.txt / events.txt / fixture.img / acceptance.xlsx
├── web -> build/web                   ← 符号链接到已构建前端（:263-267）
└── logs/{cpp,python,distributed}.log
    + 内嵌 FakeLLMServer（ThreadingHTTPServer，随机 127.0.0.1 端口）
```

## 隔离契约（源码逐条）

| 契约 | 源码依据 |
| --- | --- |
| **临时工作区**：一切服务 cwd、数据、输出都落在 `tracelens-acceptance-*` 临时目录 | `LiveHarness.__init__`（`:210`），`_write_fixture_and_config`（`:227-268`），`_start(... cwd=self.workspace ...)`（`:342/351/360`） |
| **不读仓库 `.env`**：框架写自己的 `.env` 到工作区（`PROJECT_ROOT`、`DATA_DIR`、`AUDIT_LOG_DB`、`DB_OUTPUT_DIR`、`FORENSIC_REPORT_DIR` 等全部指向工作区），并以 `env_lines` 覆盖进程环境 | `:286-332`；注释与模块 docstring 明言"No repository data or .env file is used by default"（`:6-7`） |
| **不写仓库 `data/`**：产物库（raw/events/files.db）、审计库、报告全部写入工作区；Journey A 还显式断言 db 路径"必须位于隔离工作区内" | `:480-481`（`is_relative_to(self.workspace.resolve())` 检查） |
| **随机回环端口**：`free_port()` 绑定 `127.0.0.1:0` 取空闲端口（cpp/python/fake_llm，`--with-distributed` 时再加一个） | `:269-275`、`:970-973` |
| **禁用外部依赖**：`GRAPHITI_ENABLED=false`，Neo4j/Redis 指向 `127.0.0.1:1`（不可达占位）；`NO_PROXY=127.0.0.1,localhost` 防代理劫持 | `:305-308`、`:326-332` |
| **LLM 零网络**：三个 LLM URL 全指向内嵌 fake provider | `:299-301` |

前提条件（缺失时抛 `HarnessError` 并给出可操作信息）：
- `build/forensic_analyzer`（`:335-336`）、`python_service/.venv/bin/python`（`:337-338`）、`build/web` 前端产物（`:264-266`）。
- `task/analyst/restart/matrix` 四个档案需要仓库根 `test_image.img`；缺失时报"ENVIRONMENT BLOCKED ... create it with scripts/create_test_image.sh"（`:246-255`）。
- `matrix` 另生成 `fixture/acceptance.xlsx`（内置 `create_xlsx_fixture`，纯 zipfile 手写 OOXML，`:946-957`），并复制 `tests/samples/pe/test_minimal.exe`（缺失时 DLL 环节标记 NOT APPLICABLE 而非失败，`:259-262`、`:705-707`）。

## 启动与关停生命周期

1. `start()`（`:334-363`）：先起 C++（`forensic_analyzer --http-server <port>`，健康路径 `/api/system/health`），`wait_ready` 通过后起 Python（`.venv/bin/python -m httpserver.main`，健康路径 `/health`）；`--with-distributed` 再起 `.venv/bin/python -m server.main`。
2. `wait_ready()`（`:380-395`）：`--timeout`（默认 30s）内轮询健康端点，进程提前退出立即带 `diagnostic()` 报错。
3. 服务用 `start_new_session=True` 拉起（`:375`），stdout/stderr 合流写 `logs/<name>.log`。
4. **SIGTERM→SIGKILL 关停**（`stop()`，`:918-933`）：逆序对每个进程组 `os.killpg(SIGTERM)`，等 8 秒；超时升级 `SIGKILL` 再等 3 秒；最后 `fake_llm.shutdown()+server_close()`。`restart` 旅程中故意用 `SIGKILL` 模拟进程崩溃（`_restart_python`，`:833-841`）。
5. `close_workspace(failed)`（`:939-943`）：成功或未加 `--keep-on-failure` 时 `shutil.rmtree` 工作区；**失败且 `--keep-on-failure` 时保留并打印路径**——工作区即诊断包（含三份服务日志、`.env`、产物库、fixture）。

## 环境变量与端口

框架写入工作区 `.env` 并注入进程环境（`:286-332`）：

| 变量 | 取值 | 说明 |
| --- | --- | --- |
| `PROJECT_ROOT` / `DATA_DIR` / `AUDIT_LOG_DB` | 工作区内路径 | 服务全部状态落工作区 |
| `HTTP_SERVER_PORT` / `PYTHON_HTTP_PORT` / `CS_PORT` | 随机空闲端口 | `free_port()` 分配（`:269-275`） |
| `PYTHON_SERVICE_URL` / `CPP_BACKEND_URL` / `DLL_CPP_BACKEND_URL` | `http://127.0.0.1:<port>` | 跨服务回调互指 |
| `DB_OUTPUT_DIR` / `FORENSIC_REPORT_DIR` | 工作区 `output/`、`reports/` | 产物库与报告目录 |
| `LLM_BASE_URL` / `LLM_TEXT_BASE_URL` / `LLM_VISION_BASE_URL` / `LLM_ENDPOINT` | fake 端口 + `/v1/chat/completions` | 全部 LLM 流量指向 fake provider |
| `LLM_TEXT_MODEL` / `LLM_VISION_MODEL` | `tracelens-fake` | 与 fake `/v1/models` 返回一致 |
| `GRAPHITI_ENABLED` / `GRAPHITI_USE_LOCAL_LLM` | `false` | 关闭知识图谱依赖 |
| `NEO4J_URI` / `REDIS_URL` | `neo4j://127.0.0.1:1`、`redis://127.0.0.1:1` | 刻意不可达占位 |
| `LOG_LEVEL` / `ENVIRONMENT` | `INFO` / `test` | |
| `DATABASE_URL` / `PORT`（仅 distributed） | 用户传入的 PG URL / 随机端口 | `--with-distributed` 时 |
| `NO_PROXY` / `no_proxy` / `PYTHONPATH` | `127.0.0.1,localhost` / `python_service` | 防代理劫持 + 模块解析（`:326-332`） |

端口拓扑：`topology:` 行在启动时打印（`:1039`），形如 `cpp=127.0.0.1:P1, python=127.0.0.1:P2, fake_llm=127.0.0.1:P3[, distributed=127.0.0.1:P4]`。

## 前提准备清单

验收前需一次性的仓库准备（缺失时 harness 报 `HarnessError` 并给出提示）：

| 前提 | 怎么准备 | 消费者 |
| --- | --- | --- |
| `build/forensic_analyzer` | `make build` | 全部档案 |
| `build/web` 前端产物 | `make build`（内含 web 构建）或 `make web-frontend` | 全部档案（`web` 符号链接，`:263-267`） |
| `python_service/.venv/bin/python` | `make setup-venv` | 全部档案 |
| 仓库根 `test_image.img` | `bash scripts/create_test_image.sh`（详见 TestFixtures.md） | task/analyst/restart/matrix |
| `tests/samples/pe/test_minimal.exe` | 仓库已内置（`tests/create_pe_sample.py` 历史产物） | 仅 matrix 的 DLL 两环节（缺失降级为 NOT APPLICABLE） |
| 隔离 PostgreSQL URL | 自备（如 `postgresql://.../tracelens_acceptance`） | 仅 `--with-distributed` |

与其它测试资产的关系：

- C++ 单测/ctest：见 [CppTestCatalog.md](CppTestCatalog.md)——验收是进程级补充，不替代单测。
- Python 单测四档案：见 [PythonTestCatalog.md](PythonTestCatalog.md)——investigation/报告单测使用 in-process TestClient 与 mock，本框架用真实端口/真实进程验证同一路由面。
- 浏览器 E2E：见 [browser-e2e.md](browser-e2e.md)；`--serve` 档案（写 `runtime.json` 后常驻）即为 GUI 人工验证/浏览器 E2E 提供稳定拓扑。
- fixtures 与镜像生成：见 [TestFixtures.md](TestFixtures.md)。

## Fake LLM Provider

`FakeLLMServer`（`:180-195`）持有 `fake_state = {delay, failure, invalid, failure_status: 503}` 与证据注入槽（`evidence_key`、`report_evidence_key`、`report_analysis_id`、`report_claim_id`、`report_original_key`）。端点行为（`FakeLLMHandler`，`:46-177`）：

| 端点 | 行为 |
| --- | --- |
| `GET /health` | `200 {"status":"healthy","model":"tracelens-fake"}`（`:63-66`） |
| `GET /v1/models` | `200 {"object":"list","data":[{"id":"tracelens-fake"}]}`（`:67-69`） |
| `POST /v1/chat/completions` | 按 prompt 内容路由三种确定性 JSON（见下）；其余路径 404，坏 JSON 400 |

`/v1/chat/completions` 的内容路由：

| prompt 特征 | 返回的 content | 服务对象 |
| --- | --- | --- |
| 含 `"冻结 Report"` 或 `"最终报告"` | 报告 JSON：`title`、`sections[].citation_ids`、`citations[]`（citation 回绑真实 `evidence_key`/`analysis_id`/`claim_id`，若存在 `report_original_key` 再加一条 original 引用） | Journey B 步骤 9 的报告生成 |
| 含 `"Event ID:"` | `{"title","summary"}` 的刷新 JSON | 事件 refresh 执行 |
| 其他 | 通用分析 JSON：`description`、`summary`、三条 claims（`FACT`/`INFERENCE`/`HYPOTHESIS`），`evidence_refs` 指向注入的 `evidence_key`（默认 `file:fixture/notes.txt`） | 二次分析执行 |

三个故障开关（`fake_state`，`:183-190`）：

| 开关 | 行为 | 验收用途 |
| --- | --- | --- |
| `--llm-delay N` | 处理前 `time.sleep(N)`（`:83-84`） | 慢 LLM 下的超时/重试路径 |
| `--llm-failure` | 一律 `503 {"error":"fake provider failure"}`（`:85-87`） | LLM 服务故障降级 |
| `--llm-invalid` | 返回字符串 `"this is intentionally not valid structured output"`（`:94-95`） | 非法结构化输出的解析容错 |

框架侧通过 `set_evidence_key()`（`:425-428`）与 `_configure_report_fake()`（`:889-894`）把旅程中拿到的真实 ID 注入 fake server，使引用校验端到端闭环。响应外壳统一为 OpenAI chat.completion 形状（`id=chatcmpl-tracelens-fake`、`model` 原样回显、`usage` 占位，`:167-177`）。

## 五个 Profile 的旅程

| Profile | 旅程 | 前置 |
| --- | --- | --- |
| `smoke` | 仅启动 + smoke | 无需镜像 |
| `task` | Journey A | 需 `test_image.img` |
| `analyst` | Journey A + Journey B | 需 `test_image.img` |
| `restart` | Journey A + B + 崩溃恢复 | 需 `test_image.img` |
| `matrix` | Journey A' + 提取器交接矩阵 | 需 `test_image.img`（PE fixture 可选） |

### smoke（`smoke()`，`:397-423`）

| 步 | 目标 | 路径 | 期望 |
| --- | --- | --- | --- |
| 1 | C++ | `GET /api/tasks` | 2xx（`:398-407`） |
| 2 | Python | `GET /health` | 2xx |
| 3 | C++ | `GET /`（前端路由，经 `web` 符号链接到 `build/web`） | 2xx |
| 4 | distributed（可选） | `GET /health` | 2xx |
| 5 | fake LLM | `GET /v1/models` | 200 且 JSON dict（`:409-414`） |
| 6 | fake LLM | `POST /v1/chat/completions`（一条 "smoke" 消息） | 200 且 JSON dict（`:415-423`） |

`--no-smoke` 只做启动+就绪检查。注意步骤 5-6 意味着 smoke 档案也间接验证了 fake provider 的可用性，不只测服务本体。

### task = Journey A（`task_journey()`，`:430-534`，F2 边界）

| 步 | 调用 / 动作 | 期望（源码断言） |
| --- | --- | --- |
| 1 | `POST /api/tasks` `{image_path: fixture.img, llm_analyze: false, priority: normal}` | HTTP 201 且返回 `id`（`:435-447`） |
| 2 | 轮询 `GET /api/tasks/{id}`（1s 间隔） | 到达 `completed`（终态集合 `completed/failed/cancelled`，非 completed 即失败）；完成后 `sleep(3)` 等落盘（`:452-468`） |
| 3 | `GET /api/tasks/{id}/databases` | 类型集合 ⊇ `{raw, events, files}`（`:475-477`） |
| 4 | 逐库检查 | 文件存在、路径 `is_relative_to(workspace)`、只读 `PRAGMA integrity_check == ok`（`:480-486`） |
| 5 | `GET /api/forensics/files/largest?task_id=&limit=20`、`GET /api/forensics/timeline/comprehensive?task_id=` | 均 200（活读路由，`:488-500`） |
| 6 | 从 `files.db` 取首个非空 `path` → `normalize_evidence_path` → `file:<path>` | 证据身份生成（`:502-510`；归一规则 `:960-967`：`\`→`/`、折叠 `//`、去尾 `/`） |
| 7 | `POST /api/investigation/snapshots`（同一 payload）×2 | 两次 200、`evidence_key` 一致、**两次响应字典完全相等**（快照不可变）（`:511-529`） |
| 8 | 复算 `files.db` SHA-256 | 与步骤 4 前一致——旅程对证据库零写回（`:530-532`） |

### analyst = Journey B（`analyst_journey()`，`:536-650`，F3 边界；依赖 A 的 `task_id`/`evidence_key`）

| 步 | 调用 / 动作 | 期望 |
| --- | --- | --- |
| 1 | `POST /api/investigation/analyses`（含 analyst_note/case_context） | 202 + `analysis_id`；轮询至 `review_pending`（`:545-558`） |
| 2 | `POST /api/investigation/analyses/{id}/review`（decision=accepted） | 200 且 `status=accepted`（`:560-567`） |
| 3 | `GET /api/investigation/analyses/{id}/claims?task_id=` | 200 且 `claims` 非空，取首个 `claim_id`（`:568-577`） |
| 4 | `POST /api/investigation/events` | 201 + `event_id`（`:579-587`） |
| 5 | `POST /api/investigation/events/{id}/evidence`（绑 evidence_key） | 200 且回显 evidence_key（`:589-597`） |
| 6 | `POST /api/investigation/events/{id}/refresh` | 201 + `refresh_id`；轮询至 `completed` 且有 `produced_version`（`:599-612`） |
| 7 | `GET /api/investigation/graph?task_id=` | 200；节点集含 `evidence:<key>` 与 `analysis:<id>`（`:614-623`） |
| 8 | `POST /api/reports/evidence`（绑定 analysis_id） | 200 且回显 analysis_id（`:625-633`） |
| 9 | `POST /api/reports/generate` | 202 + `generation_id`；轮询至 `completed` + `report_id`（`:634-645`） |
| 10 | 校验报告 manifest | `citations[0].evidence_key`/`analysis_id` 与旅程值**逐字相等**（引用回溯精确性，`:646-649`） |

关键机制：步骤 8 前调用 `_configure_report_fake()`（`:889-894`）把真实 `evidence_key`/`analysis_id`/`claim_id` 注入 fake LLM，fake 据此生成含正确 citation 的报告 JSON（`:96-133`），使步骤 10 的端到端引用校验闭环。

### restart（`restart_journey()`，`:727-796`，F5 边界；先跑 A+B）

对三类长任务重复"提交 → 等 `running` → `SIGKILL` Python → 重启 → 断言恢复语义"：

| 对象 | 提交/等待 | 重启后断言 |
| --- | --- | --- |
| 二次分析 | `POST /api/investigation/analyses` + `_wait_for_analysis_running`（`:809-818`） | `status=failed`、`error_code=service_restart`、**无重放**（`:749-752`） |
| 事件刷新 | `POST .../events/{id}/refresh` + `_wait_for_refresh_running`（`:820-831`） | 同上错误语义，**历史保留**（`:766-769`） |
| 报告生成 | `POST /api/reports/evidence`（200/409 均可）+ `POST /api/reports/generate` + `_wait_for_generation_running`（`:798-807`） | 同上错误语义，且 `report_id`/`report` 为 None——**崩溃中不得发布部分输出**（`:791-795`） |

崩溃注入：`_restart_python`（`:833-841`）对 Python 进程组 `os.killpg(SIGKILL)` 并等待退出；`_start_python_again`（`:843-853`）以同一命令/cwd/env 重新拉起并等健康。

### matrix（`matrix_journey()`，`:652-725`，提取器交接矩阵）

| 环节 | 调用 | 期望 |
| --- | --- | --- |
| C++→Python MarkItDown 代理 | `POST /api/tasks`（`llm_analyze=true, llm_mode="smart", case_description="live markitdown proxy"`）+ 轮询完成 | 任务 completed，打印 `C++ -> Python Markitdown proxy task: PASS`（`:656-676`） |
| MarkItDown 状态 | `GET /api/markitdown/status` | 200，打印 `available=<bool>`（`:677-681`） |
| MarkItDown 转换 | `POST /api/markitdown/convert`（`fixture/notes.txt`） | 200 且 `success=true`（`:682-690`） |
| Office 类型 | `GET /api/office/supported-types` | 200 且 `supported_types` 非空（`:692-694`） |
| Office 解析 | `POST /api/office/parse`（内置 `acceptance.xlsx`） | 200 且 `success=true`（`:695-703`） |
| C++ DLL 分析 | `POST /api/forensics/dlls/analyze`（`test_minimal.exe`） | 200 且 `success=true`，超时 ≥45s（`:708-716`） |
| Python→C++ DLL 交接 | `POST /api/llm/analyze/dll`（回调 C++） | 200 且 `success=true`（`:717-725`）；PE fixture 缺失时打印 `DLL live handoff: NOT APPLICABLE` 后返回 |

## CLI 参数全集（`parse_args`，`:1012-1029`）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--profile` | `smoke` | `smoke/task/analyst/restart/matrix` |
| `--timeout` | 30.0 | 单服务就绪/读超时（秒） |
| `--task-timeout` | 180.0 | 任务完成等待上限（秒） |
| `--keep-on-failure` | 关 | 失败时保留工作区与日志（诊断包） |
| `--with-distributed` | 关 | 同时启动 `server.main` 分布式服务 |
| `--distributed-database-url` | 空 | **`--with-distributed` 的硬前提**：必须提供隔离 PostgreSQL URL——其 schema 使用 JSONB，SQLite 不支持（`:312-318`） |
| `--llm-delay` / `--llm-failure` / `--llm-invalid` | 0 / 关 / 关 | fake LLM 故障注入三件套 |
| `--no-smoke` | 关 | 只启动 + 就绪检查 |
| `--serve` | 关 | 旅程后保留工作区与服务供 GUI 人工验证，写 `workspace/runtime.json`（含 cpp_url/python_url/task_id/evidence_key/analysis_id/event_id）并永久阻塞（`:1053-1067`） |

退出码：0 且打印 `LIVE HARNESS <PROFILE> PASS`；任何 `HarnessError`/`OSError` 打印 `LIVE HARNESS FAIL` + 诊断并返回 1（`:1068-1073`）。

诊断包解剖（`--keep-on-failure` 保留的工作区）：

```
tracelens-acceptance-XXXXXXXX/
├── logs/cpp.log / python.log / distributed.log   # 失败时 diagnostic() 还会内联最后 40 行（:902-916）
├── .env                                          # 实际生效的隔离配置（端口/路径/fake LLM URL）
├── data/{tasks,audit,logs}/                      # 任务状态与审计库（SQLite 可直接查）
├── output/                                       # raw/events/files.db 产物库
├── reports/                                      # 报告版本与渲染产物
├── fixture/  fixture.img                         # 输入副本（notes.txt/events.txt/xlsx/PE）
└── runtime.json                                  # 仅 --serve：cpp_url/python_url/task_id/evidence_key/...
```

`diagnostic()` 字段：`service=`、`pid=`、`exit_code=`、`health=`（URL）、`reason=`、`log=`（路径）+ `last_logs:` 尾部 40 行（`:902-916`）——失败信息自带现场，无需复跑。

## 日常用法

```bash
make acceptance-smoke      # = live_services.py --profile smoke
make acceptance-task       # Journey A
make acceptance-analyst    # Journey A+B
make acceptance-restart    # Journey A+B+崩溃恢复
make acceptance-matrix     # 交接矩阵

python3 scripts/acceptance/live_services.py --profile analyst --keep-on-failure
python3 scripts/acceptance/live_services.py --profile task --llm-delay 2      # 慢 LLM
python3 scripts/acceptance/live_services.py --profile task --llm-failure      # LLM 503 降级
python3 scripts/acceptance/live_services.py --profile task --llm-invalid      # 非法结构化输出
python3 scripts/acceptance/live_services.py --profile analyst --serve         # GUI 人工验证
python3 scripts/acceptance/live_services.py --profile smoke --with-distributed \
    --distributed-database-url "$TRACELENS_ACCEPTANCE_DATABASE_URL"           # 需 PG
```

与 `docs/testing/live-integration.md` 的关系：该文记录 Phase F 里程碑时的调用样例与当时的拓扑表，仍是理解设计动机的入口；参数语义、端口分配、旅程断言细节以后续脚本源码为准（例如 `--serve` 的 `runtime.json` 输出即该文档未覆盖的行为）。

## 场景化命令速查

| 目的 | 命令 |
| --- | --- |
| 提交前最小验证 | `make acceptance-smoke` |
| 验证分析全链产物完整性 | `make acceptance-task` |
| 验证调查→报告全旅程 | `make acceptance-analyst` |
| 验证进程崩溃恢复语义 | `make acceptance-restart` |
| 验证跨语言提取器交接 | `make acceptance-matrix` |
| 慢 LLM 行为 | `python3 scripts/acceptance/live_services.py --profile analyst --llm-delay 2` |
| LLM 全故障降级 | `python3 scripts/acceptance/live_services.py --profile task --llm-failure` |
| 脏结构化输出容错 | `python3 scripts/acceptance/live_services.py --profile analyst --llm-invalid` |
| 失败留现场排查 | 追加 `--keep-on-failure`（失败后打印工作区路径） |
| GUI/浏览器手工验证 | `python3 scripts/acceptance/live_services.py --profile analyst --serve`（打印 `runtime.json` 内容并常驻，Ctrl-C 退出走正常关停） |
| 只起服务不起旅程 | 追加 `--no-smoke`（配合 `--serve` 做拓扑探查） |
| 分布式面冒烟 | `python3 scripts/acceptance/live_services.py --profile smoke --with-distributed --distributed-database-url "$PG_URL"` |
| 慢机器加超时 | `--timeout 60 --task-timeout 600` |

## 已发现的测试层面问题

1. **`smoke` 档案会连带打 fake LLM**（`:409-423`）：`--no-smoke` 是唯一关闭途径，无法只验服务不碰 LLM 层；若只想测 C++ 也必须先起 Python（启动顺序硬编码 `:339-354`）。
2. **`matrix` 的 DLL 环节静默降级**：`tests/samples/pe/test_minimal.exe` 缺失时打印 NOT APPLICABLE 直接 PASS（`:705-707`），仓库漏放样本不会让验收失败。
3. **`restart` 旅程强依赖 analyst 全程成功**：任何 B 阶段断言失败都会让 F5 崩溃恢复覆盖归零，缺少独立的最小 restart 变体。
4. **`--with-distributed` 无独立旅程**：只多启动一个服务并加一条 `/health` smoke，没有针对分布式面的任务级验收。
5. **硬编码等待**：Journey A 完成后固定 `time.sleep(3.0)`（`:467`）等待落盘，慢机器上可能不稳定（框架其余部分均为轮询式）。

**最后更新**: 2026-08-24（新建，测试目录）
