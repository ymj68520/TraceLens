# 验收框架指南（AcceptanceHarness）

本文覆盖两套验收资产：

1. **`scripts/acceptance/live_services.py`（1081 行）**——**进程级隔离验收框架**而非替代启动器：启动真实的 C++/Python 服务入口点、等待真实健康端点、跑预设旅程并在失败时收集诊断。现有 `docs/testing/live-integration.md` 记录了 Phase F 的历史执行情况，本文以脚本源码为准。
2. **`tests/acceptance_metrics/`（第三方指标验收集，本分支新增）**——面向第三方验收方的黑盒测试套件：对**已部署**服务只发 HTTP 请求判定合同指标，不 import 产品代码。

两者关系一句话：`live_services.py` 验"隔离环境里的旅程语义"（自起服务 + fake LLM + 随机端口），`acceptance_metrics` 验"真实部署上的指标口径"（真实模型、真实吞吐、真实报告）。前者不碰外部 LLM，后者刻意要真实 LLM。

---

# 第一部分：live_services.py 进程级验收框架

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
| 第三方合同指标验收 | 见下文第二部分（`tests/acceptance_metrics/`） |
| 演示案件一键建案 | `python3 scripts/create_demo_case.py`（见下文第三部分） |
| 慢 LLM 行为 | `python3 scripts/acceptance/live_services.py --profile analyst --llm-delay 2` |
| LLM 全故障降级 | `python3 scripts/acceptance/live_services.py --profile task --llm-failure` |
| 脏结构化输出容错 | `python3 scripts/acceptance/live_services.py --profile analyst --llm-invalid` |
| 失败留现场排查 | 追加 `--keep-on-failure`（失败后打印工作区路径） |
| GUI/浏览器手工验证 | `python3 scripts/acceptance/live_services.py --profile analyst --serve`（打印 `runtime.json` 内容并常驻，Ctrl-C 退出走正常关停） |
| 只起服务不起旅程 | 追加 `--no-smoke`（配合 `--serve` 做拓扑探查） |
| 分布式面冒烟 | `python3 scripts/acceptance/live_services.py --profile smoke --with-distributed --distributed-database-url "$PG_URL"` |
| 慢机器加超时 | `--timeout 60 --task-timeout 600` |

---

# 第二部分：第三方指标验收集（`tests/acceptance_metrics/`，本分支新增）

面向第三方验收方的**黑盒**测试套件：只通过已部署服务的 HTTP 端点与任务库判定合同验收指标，**不 import 产品代码**。每个用例首行 docstring 标注对应的验收指标与判定口径；套件自带 `README.md`（指标↔用例↔判定标准↔夹具四列对照表，是本节的一手来源）。

## 组成（实测清点）

| 文件 | 行数 | 用例数 | 覆盖指标 |
| --- | --- | --- | --- |
| `conftest.py` | 261 | — | 共享 live harness：对已部署实例发请求；提供环境变量解析与任务等待 |
| `prepare_fixtures.py` | 915 | — | 夹具生成器：仅 mkfs.ext4 + debugfs（**无需 root**），产出 `fixtures/` + `manifest.json`；`--only` 选择子（如 `--only raw dd timeline logs`），且含 `demo_datasets` 构建器（`:725-726`、`:899-900`，见第三部分） |
| `test_m1_lightweight.py` | 92 | 4 | 指标 1(2)：吞吐 ≥10MB/s、低价值剔除率 ≥70%、待分析压缩至 12-15%、统计口径一致性 |
| `test_m1_multisource.py` | 185 | 11 | 指标 1(1)：RAW/DD/E01 镜像、iOS、三类 Android（小米/鸿蒙/vivo 雷电）、服务器日志、阿里云 OSS、Windows |
| `test_m2_crossmodal.py` | 110 | 5 | 指标 2：文本/图像/视频信息提取、事件转化、重复证据去重 |
| `test_m3_timeline.py` | 95 | 2 | 指标 3：多模态同一事件聚合、≥100 事件节点 |
| `test_m4_reasoning.py` | 195 | 3 | 指标 4：推演报告结构完整、角色基本一致、证据溯源定位 |
| `README.md` | — | — | 指标↔用例↔判定标准↔夹具对照表 + 已知缺口 |
| `fixtures/` | — | — | 生成夹具（gitignore，仅 `manifest.json` 入库固化夹具组成） |

合计 **25 个用例**。LLM 依赖用例标注 `@pytest.mark.llm`；`/api/llm/models` 无可用模型时自动跳过（不误报失败）。

## 运行方式

```bash
# 0) 部署 TraceLens（C++ 8666 / Python 8090 默认）
# 1) 生成夹具
python3 tests/acceptance_metrics/prepare_fixtures.py
# 2) 非 LLM 指标（约 1 分钟）
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v -m "not llm"
# 3) 全量（含 LLM 案情推演与多模态聚合）
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v
```

注意：该目录**不在** `python_service/pytest.ini` 的 testpaths 内（那里只收录 `python_service/tests/`），必须显式指路径运行；`llm` 标记也未在 pytest.ini 注册，靠默认（非 strict）配置容忍。

## 环境变量（conftest 实证）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TRACELENS_CPP_BASE` | `http://127.0.0.1:8666` | C++ 后端地址 |
| `TRACELENS_PY_BASE` | `http://127.0.0.1:8090` | Python 服务地址 |
| `TRACELENS_ACCEPT_USER/_PASSWORD` | 无 | 服务开启 field-auth 时必填 |
| `TRACELENS_ACCEPT_FIXTURES` | `tests/acceptance_metrics/fixtures` | 夹具目录 |
| `TRACELENS_DATA_DIR` | `<repo>/data`（兜底 `build/data`） | 任务库/审计库根目录（黑盒直读任务库判定） |
| `TRACELENS_ACCEPT_TASK_TIMEOUT` | 3600 | 单任务完成超时（秒） |
| `TRACELENS_E01_IMAGE` | 无 | 真实 E01 镜像路径（开源工具无法凭空生成 E01） |
| `TRACELENS_ACCEPT_MIN_MB_S` | 10 | 吞吐阈值（合同值 10MB/s） |
| `TRACELENS_ACCEPT_REPORT_TIMEOUT` | 1800 | 推演报告生成超时（秒） |
| `TRACELENS_ACCEPT_ASSUME_LLM` | 无 | 置 1 时跳过 LLM 探测直接运行 LLM 用例 |

## 与 live_services.py 的分工

| 维度 | live_services.py | acceptance_metrics |
| --- | --- | --- |
| 服务来源 | 框架自起（隔离工作区 + 随机端口） | 外部已部署实例（默认 8666/8090） |
| LLM | 内嵌 fake provider，零网络 | **真实模型**（无模型则相关用例自跳过） |
| 断言对象 | 旅程语义（快照不可变、崩溃恢复、引用回溯） | 合同指标口径（吞吐/剔除率/压缩比/节点数/报告结构） |
| 失败诊断 | 工作区诊断包（日志 + .env + 产物库） | `-v -s` 内联打印关键度量，直接转录验收记录 |
| 入库门禁 | `make acceptance-*` | 无 Makefile 包装，手工/现场运行 |

README 的"已知缺口"记录了口径边界（值得现场验收前重读）：吞吐 2026-10-17 复测 12.2-12.7MB/s 达标但十万级文件未复测；去重只覆盖过滤保留的小文件；任务态 LLM 分析可能被未知二进制卡死（推演用例因此使用纯文本镜像 raw_llm.img）；E01 用例需外部真实镜像；叙事生成为概率性输出，`citation_invalid` 类失败重跑即可。

---

# 第三部分：演示数据集与实战案件脚本（本分支新增）

## `demo_datasets/`：7 个演示数据集

面向第三方权威测试机构现场验收的**脱敏演示数据集**（git 入库，磁盘占用约 105MB），覆盖合同指标要求的全部来源类型；全部植入统一案情证据链（嫌疑人：张伟-仓库主管、李娜-财务经理、王五-收款账户；涉案标的：￥386,000 设备采购与异常调拨款项）。

| 序号 | 目录 / 文件 | 数据源类型 | 核心工件 | 对应指标 |
| --- | --- | --- | --- | --- |
| 01 | `01_windows/windows_evidence.img` | Windows 镜像 | Prefetch（CMD/PowerShell）、EVTX、LNK、注册表 Hive、财务审计文档 | 1(1) 磁盘镜像与操作系统 |
| 02 | `02_linux/linux_evidence.img` | Linux RAW/DD | 沟通记录/合同/台账、syslog/auth.log、重复文件对、低价值系统文件 | 1(1) + 1(2) 轻量化过滤 + 2(2) 去重 |
| 03 | `03_aliyun_oss/file_m-demo_aliyun_system.raw.tar.gz` | 阿里云 OSS/ECS 导出包 | Alibaba Cloud Linux、nginx 访问日志、OSS 接口转账调用日志 | 1(1) 服务器日志与云数据源 |
| 04 | `04_ios/ios_backup_evidence/` **新增** | iOS 逻辑备份（iTunes/Finder 规范） | Manifest.plist/db、涉案 iMessage 短信、通讯录、备忘录、日程 | 1(1) iOS 移动设备 |
| 05 | `05_android_miui/miui_backup_evidence/` **新增** | 小米 MIUI 备份 | descript.xml、Contacts/Mms `.bak` 库 | 1(1) Android 类别 1（小米） |
| 06 | `06_android_harmony/harmony_backup_evidence/` **新增** | 华为鸿蒙备份 | `.info.json` 清单、part.0.tarx 分卷、WAL 日志、日历/通讯工件 | 1(1) Android 类别 2（鸿蒙） |
| 07 | `07_android_vivo/vivo_backup_evidence/` **新增** | vivo/OPPO 雷电快取备份 | `.backup` 头、LevelDB 索引 index.json、转账截图相册、微信应用包 | 1(1) Android 类别 3（vivo/OPPO） |

数据集与验收的两种用法（`demo_datasets/README.md` 原文口径）：

1. **自动化**：`prepare_fixtures.py` 一键生成夹具与演示数据集（`build_all_demo_datasets` 默认写回 `demo_datasets/`），再跑第二部分的 pytest；四个 Android/iOS 夹具与 04-07 数据集内容一致。
2. **人工图形化**：Web 前端"新建任务"逐个导入（来源类型分别选 `windows/linux` 场景勾选、`aliyun-image`、`ios-backup`、`miui-backup`、`harmony-backup`、`vivo-backup`），完成后在工件卡片、重复证据列表、动态时间线、案情推演报告中查看结构化成果。

## `scripts/create_demo_case.py`（245 行，新增）

**演示案件一键建案脚本**：对 `demo_datasets/` 的 7 个数据源执行完整"取证 + 分析"数据流——逐个 `POST /api/tasks`（默认打 `http://127.0.0.1:8666`）、按来源类型附加预检字段（阿里云源会在 `data/evidence_preflight/<md5>/job.json` 现场播种 `verified` 预检结果）、轮询任务到完成并打印阶段进度。前提：双服务在线、`demo_datasets/` 就位。适合现场演示前一键预热全部 7 个任务。

## `scripts/create_real_case.py`（266 行，新增）

**实战多源案件建案脚本**：基于移动硬盘与 `/data2` 真实检材创建实战案件，接入 7 大真实镜像（Windows、Linux、阿里云 OSS、iOS、三个 Android）。与演示版同构（同样的任务提交/预检播种/轮询骨架），但数据源指向真实检材路径——**不可在无真实介质的机器上运行**。建案后配合 `web/scripts/verify-real-case-reports-and-im.mjs`（见 [browser-e2e.md](browser-e2e.md)）做浏览器级报告与 IM 关系图验收：该脚本内硬编码了本次实战案件 7 个任务的 UUID 与预期图节点数（微信 49 / QQ 47）。

---

# 已发现的测试层面问题

1. **`smoke` 档案会连带打 fake LLM**（`:409-423`）：`--no-smoke` 是唯一关闭途径，无法只验服务不碰 LLM 层；若只想测 C++ 也必须先起 Python（启动顺序硬编码 `:339-354`）。
2. **`matrix` 的 DLL 环节静默降级**：`tests/samples/pe/test_minimal.exe` 缺失时打印 NOT APPLICABLE 直接 PASS（`:705-707`），仓库漏放样本不会让验收失败。
3. **`restart` 旅程强依赖 analyst 全程成功**：任何 B 阶段断言失败都会让 F5 崩溃恢复覆盖归零，缺少独立的最小 restart 变体。
4. **`--with-distributed` 无独立旅程**：只多启动一个服务并加一条 `/health` smoke，没有针对分布式面的任务级验收。
5. **硬编码等待**：Journey A 完成后固定 `time.sleep(3.0)`（`:467`）等待落盘，慢机器上可能不稳定（框架其余部分均为轮询式）。
6. **`acceptance_metrics` 的 `llm` 标记未注册**：套件依赖 `@pytest.mark.llm` 走 `-m "not llm"` 选择，但 `python_service/pytest.ini` 未声明该标记（该目录也不在其 testpaths 内）；用根目录或其它 strict-markers 配置跑会直接报错。
7. **两份案情数据集各占 100-220MB**：`demo_datasets/`（约 105MB，git 入库）与 `tests/acceptance_metrics/fixtures/`（实测约 223MB，gitignore）内容同源（前者可由 `prepare_fixtures.py` 再生），仓库内同时保留两份且无哈希互检，漂移不可感知。
8. **`create_real_case.py` 绑定本机环境**：检材路径（移动硬盘、`/data2`）与预检播种目录写死在脚本常量里，且会向 `data/`、`build/data/` 写入播种文件——它不是只读验收工具。
9. **`verify-real-case-reports-and-im.mjs` 的 taskId 硬编码**（见 browser-e2e.md 问题 2）：实战案件验收链的最后一环无法参数化，换案件批次必须改源码。

**最后更新**: 2026-11-10（feature/model-routing 分支改版：并入第三方指标验收集与演示/实战建案资产；live_services.py 部分经锚点复核未变）
