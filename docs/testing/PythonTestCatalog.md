# Python 测试目录（PythonTestCatalog）

本文盘点 `python_service/` 下全部 pytest 资产：`python_service/tests/`（**testpaths 收录**的唯一树，共 117 个测试文件）、`python_service/httpserver/tests/`（嵌套小套件）、`python_service/graphiti_integration/tests/`（不在 testpaths）、以及仓库根 `tests/` 下散落的 Python 测试。运行档案以 `python_service/scripts/test.py` 源码为准（现有 `docs/testing/test-profiles.md` 为历史基线记录）。

## 目录全景

```
python_service/
├── pytest.ini                 # 唯一的 pytest 配置；testpaths = tests
├── scripts/test.py            # 四档案稳定回归入口（focused/investigation/fast/full）
├── tests/                     # ← testpaths 收录（117 个 test_*.py）
│   ├── conftest.py            # 顶层共享 fixture（DB/TestClient/后端 mock 等 11 个）
│   ├── test_*.py              # 15 个：server 应用（分布式 C/S 服务）层
│   ├── integration/
│   │   └── test_analyzed_only_ingestion_e2e.py   # ANALYZED_ONLY 摄取端到端
│   └── unit/                  # httpserver 服务为主体（58 个平铺 + 3 个子包 43 个）
│       ├── evidence/          # 2 个：Evidence 键解析与解析器（C1/C2）
│       ├── forensic_report/   # 15 个：报告快照/生成/引用/叙事（R1/R2 系列）
│       └── investigation/     # 26 个 + conftest.py：调查工作台（C3-C9、Phase C/R/D4b）
├── httpserver/tests/          # 3 个文件，历史嵌套套件（不在 testpaths）
├── graphiti_integration/tests/# 4 个文件（不在 testpaths）
└── test_archive.py            # 仓库外散件（不被任何 runner 收录）
```

数量核对：顶层 15 + integration 1 + unit 平铺 58 + evidence 2 + forensic_report 15 + investigation 26 = **117**。

## 顶层 `tests/test_*.py` —— server 应用（分布式 C/S 服务）

这些文件测试 `python_service/server/` 包（FastAPI 组装的应用：认证、任务、命令、结果聚合），与 unit 树的 `httpserver/` 服务是两套代码。每个文件对应 docstring 首行（源码原句归纳）：

| 文件 | 测什么 |
| --- | --- |
| `test_auth_algorithm.py` | JWT 算法/配置处理回归（Task 1） |
| `test_auth_api.py` | 认证 API 端点（`server.api.auth`） |
| `test_auth_middleware.py` | JWT 认证中间件（`server.middleware.auth`） |
| `test_auth_service.py` | 认证服务（`server.services.auth_service`） |
| `test_clients_api.py` | 客户端注册与管理端点（`server.api.clients`） |
| `test_command_queue.py` | 命令队列服务（`server.services.command_queue`） |
| `test_commands_api.py` | 命令队列 API 端点（`server.api.commands`） |
| `test_command_task_fk.py` | `command_queue.task_id` 是真外键而非 JSONB 软链接（Task 4） |
| `test_config_port.py` | 分布式 C/S 服务端口配置（`Settings`） |
| `test_main_app.py` | 组装后 FastAPI 应用（`server.main`）的集成测试 |
| `test_organizations_api.py` | 组织管理端点（`server.api.organizations`） |
| `test_result_aggregator.py` | 结果聚合服务（`server.services.result_aggregator`） |
| `test_results_api.py` | 结果上传/读取端点（`server.api.results`） |
| `test_task_orchestrator.py` | 任务编排服务（`server.services.task_orchestrator`） |
| `test_tasks_api.py` | 任务管理端点（`server.api.tasks`）；DB 依赖被 `mock_db` 替换（`test_tasks_api.py:141-149`） |
| `tests/integration/test_analyzed_only_ingestion_e2e.py` | ANALYZED_ONLY 摄取模式端到端（httpx + mock，不依赖真服务） |

## `tests/unit/` —— httpserver 服务单测（平铺 58 个）

逐文件清单（测什么 = 源文件 docstring 首行或用例归纳），按主题排序：

**文件筛选 / 确定性选择（6 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_deterministic_filter.py` | FileFilter 中非 LLM 的确定性文件筛选 |
| `test_multi_deterministic_filter.py` | 确定性多镜像文件选择 |
| `test_file_matcher.py` | `FileMatcher` |
| `test_filter_config.py` | 确定性筛选配置项 |
| `test_filter_validator.py` | `FilterResultValidator` |
| `test_ingestion_analyzed_only.py` | `IngestionJobManager._process_analyzed_only` |

**LLM 分析与持久化（7 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_llm_endpoint.py` | OpenAI 兼容端点处理回归 |
| `test_llm_response_parser.py` | `LLMResponseParser` |
| `test_batch_persist_callback.py` | `FileAnalyzer._run_batch_analysis` 持久化回调（A6/A7） |
| `test_custom_prompt_preserves_content.py` | `FileAnalyzer.analyze_file` 提示词组装（A8） |
| `test_persist_to_files_db.py` | `LLMService.persist_to_files_db`（A2/A3/A4/A5） |
| `test_associations.py` | Phase B 关联端点（cluster-files / file-clusters） |
| `test_wechat_dataset.py` | 生成的 WeChat 数据集守护校验（见 TestFixtures.md） |

**Evidence 身份与溯源（3 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_normalize_evidence_path.py` | `normalize_evidence_path` 证据身份规范化（A1） |
| `test_claim_provenance_reader.py` | 严格只读的历史 Claim 溯源 |
| `test_citation_validation.py` | 引用校验 |

**Investigation HTTP 契约（8 个，与 investigation 子包的持久层互补）**

| 文件 | 测什么 |
| --- | --- |
| `test_investigation_routes.py` | C3 快照路由契约 |
| `test_investigation_event_routes.py` | C7a 事件 API |
| `test_investigation_graph_routes.py` | C8b 图谱 API |
| `test_investigation_read_routes.py` | C9a Workbench 只读 API 面 |
| `test_investigation_refresh_routes.py` | C7c-1 刷新准入/历史 |
| `test_investigation_review_routes.py` | C6 分析师评审 API |
| `test_investigation_evidence.py` | Investigation 证据层 |
| `test_investigation_persistence.py` | Investigation 持久层 |

**报告管线（10 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_report_dataset.py` | 报告数据集组装 |
| `test_section_planning.py` | 章节规划 |
| `test_report_rendering.py` | Phase 4D 受限章节渲染 |
| `test_report_render_repository.py` | 4D 任务本地渲染候选仓库 |
| `test_report_final_validation.py` | Phase 4E 终验规则与溯源哈希 |
| `test_report_validation_repository.py` | 4E 独立验证持久化 |
| `test_final_report_assembly.py` | 确定性最终报告装配 |
| `test_final_report_presentation.py` | 确定性最终报告呈现 |
| `test_final_report_repository.py` | 不可变报告版本与发布 |
| `test_intelligence_report_routes.py` | 证据情报报告只读 API |

**阶段回归 D1/D2b/D4b（7 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_d1_error_sanitization.py` | D1：客户端可见的内部错误保持脱敏 |
| `test_d2b_db_ownership.py` | D2b：HTTP 任务模式持久化绑定任务自有 files.db |
| `test_d2b_office_routes.py` | D2b：Office 解析器任务/工作区契约 |
| `test_d2b_standalone_contracts.py` | D2b：独立工作区与参数化 Windows 严重度 |
| `test_d2b_task_store.py` | D2b：任务自有 store/路径解析助手 |
| `test_d4b_graphiti_cleanup.py` | D4b：自有 Graphiti 资源清理 |
| `test_d4b_temp_resource_cleanup.py` | D4b：临时分析资源清理 |

**分析器客户端与内容路由（8 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_cluster_analyzer.py` | 聚类分析器 |
| `test_dll_analyzer.py` | DLL 分析器客户端 |
| `test_dll_markdown_generator.py` | `DLLMarkdownGenerator` |
| `test_dll_route.py` | DLL 分析路由 |
| `test_markitdown_routes.py` | 原子单文件 MarkItDown 转换路由 |
| `test_media_metadata.py` | 韧性视频元数据提取 |
| `test_forensic_extractors.py` | 取证文件类型提取器 |
| `test_graphiti_integration_fixes.py` | Graphiti 集成修复回归 |

**服务装配与基础设施（10 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_service_manager_investigation.py` | ServiceManager C3 Investigation 服务接线 |
| `test_service_manager_report_lifecycle.py` | ServiceManager 报告生命周期 |
| `test_startup_reliability.py` | 分布式 server 启动可靠性契约 |
| `test_cors_config.py` | CORS 配置 |
| `test_case_analysis_routes.py` | D3b：旧 case-analysis 生成软退役契约 |
| `test_wechat_graph_routes.py` | WeChat 图谱 FastAPI 路由回归 |
| `test_database_models.py` | SQLAlchemy ORM 模型（`server.models.database`，server 侧） |
| `test_db_session.py` | 数据库会话管理（`server.db.session`，server 侧） |
| `test_schemas.py` | Pydantic API schema（`server.models.schemas`，server 侧） |

（合计 58 个，与目录清点一致。）

## `tests/unit/` 三个子包

### `unit/evidence/`（2 个）

| 文件 | 测什么 |
| --- | --- |
| `test_keys.py` | `parse_evidence_key` / `ParsedEvidenceKey`（C1） |
| `test_resolver.py` | `EvidenceResolver`（C2 + C2.1）：任务域、fail-closed、零写入 |

### `unit/forensic_report/`（15 个）

| 文件 | 测什么 |
| --- | --- |
| `test_generation_admission.py` | R2b 冻结报告生成准入（§26 矩阵） |
| `test_generation_execution.py` | R2c 生成执行与引用校验（§25-§28） |
| `test_report_generation_routes.py` | `POST /api/reports/generate` 与 generations 查询路由契约 |
| `test_report_narrative_routes.py` | R2d 严格任务域叙事 Viewer 只读路由 |
| `test_analysis_adapter.py` / `test_cpp_backend_task_lookup.py` / `test_sqlite_task_adapter.py` / `test_source_resolver.py` | 报告数据适配层（C++ 后端任务定位、SQLite 任务适配、来源解析） |
| `test_ids.py` / `test_models.py` / `test_repository.py` / `test_search_index.py` / `test_service.py` / `test_snapshot_writer.py` | ID 生成、模型、仓库、检索索引、服务、快照写入 |
| `test_routes.py` | 版本化报告快照 HTTP 契约 |

### `unit/investigation/`（26 个 + `conftest.py`）

共享 `conftest.py` 提供 session 级 `investigation_v7_baseline`：一次构建空 schema-v7 `investigation.db`，断言 `integrity_check=ok` 且 `user_version==SUPPORTED_SCHEMA_VERSION==7`，其余用例从该基线拷贝。按阶段：

- 持久层/服务：`test_investigation_repository.py`（C4a 捕获与幂等）、`test_investigation_service.py`（C3 编排）、`test_investigation_acquisition.py`（快照候选构建）、`test_investigation_paths.py`（fail-closed 任务域路径）、`test_investigation_secondary.py`（C4b-1 版本状态机）、`test_investigation_execution.py`（C4b-2 执行层）、`test_investigation_completion.py` / `test_investigation_structured.py`（C5b 原子完成与结构化解析）、`test_investigation_grounding.py`（C5a Claims 持久化与 Grounding 校验）、`test_investigation_review.py`（C6 评审）、`test_investigation_event.py`（C7a schema v5 与 DB 级约束）、`test_investigation_propagation.py`（C7b 已接受分析→事件）、`test_investigation_refresh.py` / `test_investigation_refresh_execution.py`（C7c-1/2）、`test_investigation_graph.py`（C8b overlay 读取与合成）、`test_investigation_read.py`（C9a）、`test_investigation_context.py`（C4c Analyst Context Snapshot）、`test_investigation_report_evidence.py` + `test_report_evidence_routes.py`（R1 冻结显式绑定 §19）。
- Phase C 跨阶段集成：`test_phase_c_evidence_to_review_flow.py`、`test_phase_c_accept_to_event_dirty_flow.py`、`test_phase_c_event_refresh_clean_flow.py`、`test_phase_c_refresh_new_accept_keeps_dirty.py`、`test_phase_c_read_side_no_mutation.py`、`test_phase_c_cross_task_isolation.py`。
- D4b 边界：`test_d4b_task_deletion_boundary.py`。

## 顶层 `tests/conftest.py` 关键 fixture

`python_service/tests/conftest.py`（供全树使用）：`test_db_path`（临时 SQLite 文件）、`database_with_analyzed_files`、`events_database`、`neo4j_available`（探测跳过）、`test_settings`（`httpserver.config.Settings`，Neo4j/Redis 指向本地占位）、`test_app`（`create_app` + settings 覆盖）、`test_client`（**保持 lifespan 打开**，让后台摄取任务存活）、`mock_cpp_backend`、`db_session`（自建引擎绑定 `TEST_DATABASE_URL`，绕开 import 期读取 `DATABASE_URL` 的 `server.db.session`）、`org_and_client`。

## `pytest.ini` 标记体系

`python_service/pytest.ini` 全文要点：

- `testpaths = tests` —— **只**发现 `python_service/tests/`；httpserver/tests、graphiti_integration/tests、仓库根 tests 均不在内。
- `markers`（配合 `--strict-markers`，未注册标记直接报错）：`integration`、`unit`、`slow`、`concurrency`、`migration_matrix`、`asyncio`。
- `asyncio_mode = auto` —— async 用例无需逐个加 `@pytest.mark.asyncio`。
- `addopts = -v --strict-markers --tb=short`；`log_cli` 开启 INFO 级实时日志；过滤 DeprecationWarning。

实际标记使用统计（grep 全树）：`pytest.mark.asyncio` 276 处、`parametrize` 35、`concurrency` 18、`migration_matrix` 7、`integration` 5、`slow` 1（`asyncio_mode=auto` 下大量 asyncio 标记其实冗余）。

标记落点（以文件为单位，全部 grep 实证）：

- `concurrency`（18 处 / 8 文件）：`tests/unit/test_markitdown_routes.py`、`tests/unit/test_service_manager_report_lifecycle.py`、`tests/unit/investigation/test_investigation_execution.py`、`test_investigation_secondary.py`、`test_investigation_repository.py`、`tests/unit/forensic_report/test_repository.py`、`test_service.py`、`test_source_resolver.py`。
- `migration_matrix`（7 处 / 5 文件）：`tests/unit/investigation/` 下的 `test_investigation_secondary.py`、`test_investigation_refresh.py`、`test_investigation_event.py`、`test_investigation_completion.py`、`test_investigation_grounding.py`——全部围绕 schema v5/v7 历史升级。
- `slow`（1 处）：`tests/unit/test_wechat_dataset.py`（数据集全量校验，被 fast/investigation 档案排除）。
- `integration`（5 处）：`tests/integration/test_analyzed_only_ingestion_e2e.py`（该目录另有 README 说明标记约定）。

标记的语义在 `scripts/test.py:21` 处被消费：`FAST_EXPRESSION = "not slow and not concurrency and not migration_matrix"`——即"快档案"剔掉慢、并发与迁移矩阵三类；`full` 档案不做剔除。

## `scripts/test.py` 四档案与 Makefile 对应

`python_service/scripts/test.py`（74 行）是稳定回归入口：自行定位 `python_service` 根作为子进程 cwd、把 `.venv` 的 site-packages 注入 `PYTHONPATH`，因此**从仓库任何目录调用都有效**。核心常量：`FAST_EXPRESSION = "not slow and not concurrency and not migration_matrix"`（`scripts/test.py:21`）。

| 档案 | 命令 | 实际展开（源码为准） | Makefile 目标 |
| --- | --- | --- | --- |
| focused | `python scripts/test.py focused <任意 pytest 参数>` | 原样转发；无标记排除 | `make test-python-focused ARGS=...` |
| investigation | `python scripts/test.py investigation` | `tests/unit/investigation` + 6 个路由文件 + 2 个 ServiceManager 文件（`INVESTIGATION_PATHS`，`scripts/test.py:13-22`）+ `-m "<FAST_EXPRESSION>"` | `make test-python-investigation` |
| fast | `python scripts/test.py fast` | `tests/unit` + `-m "<FAST_EXPRESSION>"` | `make test-python-fast` |
| full | `python scripts/test.py full` | `tests/unit -q`，**无**标记排除 | `make test-python-full` |

注意：四个档案都只覆盖 `tests/unit`；顶层 server 应用 15 个文件与 `tests/integration/` 需用 focused 档案（如 `make test-python-focused ARGS="tests/test_auth_api.py -v"`）或直接 `make test-python`（= `.venv/bin/python -m pytest tests/ -v`，全树）。`docs/testing/test-profiles.md` 记录了历史基线（Investigation 425 passed / 26:15，Fast 1086 passed / 39:26 等），以当时的树为准。

## 嵌套套件：`httpserver/tests/`（3 个文件，不在 testpaths）

| 文件 | 测什么 |
| --- | --- |
| `httpserver/tests/unit/test_concurrent_filter.py` | `FilterLockManager` 并发过滤 |
| `httpserver/tests/unit/test_dll_route.py` | DLL 分析路由（与 `tests/unit/test_dll_route.py` 同名不同树） |
| `httpserver/tests/integration/test_file_filter_integration.py` | 增强文件过滤集成 |

目录内**没有**自己的 `pytest.ini` 或 `conftest.py`；单独跑：

```bash
cd python_service
.venv/bin/python -m pytest httpserver/tests -v
```

## `graphiti_integration/tests/`（4 个文件，不在 testpaths）

| 文件 | 测什么 |
| --- | --- |
| `test_database_reader.py` | database_reader 模块单测 |
| `test_graphiti_ingestor.py` | GraphitiIngestor（`IngestionResult`、异常路径，AsyncMock 打桩） |
| `test_pipeline_multi_source.py` | 多源数据库读取器与取证 episode 转换器 |
| `test_toon_transformer.py` | toon_transformer（EpisodeData） |

不在 `testpaths` 的原因：该包依赖 `graphiti_integration.config` 等自有依赖链（`from graphiti_integration...` 直接导入），历史上游离于主服务测试树，为避免默认收集引入额外依赖/慢路径而保持独立。单独跑：

```bash
cd python_service
.venv/bin/python -m pytest graphiti_integration/tests -v
```

## 常用单独运行配方

```bash
# 从仓库根（runner 自己切 cwd，无需 cd）
python3 python_service/scripts/test.py focused tests/unit/investigation/test_investigation_refresh.py -v
make test-python-focused ARGS="tests/test_auth_api.py -v"
make test-python-focused ARGS="tests/unit -k 'snapshot and not routes' --maxfail=1"

# 直接用 venv 的 pytest（等价 make test-python，全树含 integration 目录）
cd python_service && .venv/bin/python -m pytest tests/ -v

# 三个树外套件
cd python_service
.venv/bin/python -m pytest httpserver/tests -v
.venv/bin/python -m pytest graphiti_integration/tests -v
.venv/bin/python -m pytest ../tests/unit/test_entity_relation_builder.py ../tests/unit/test_file_entity_ingestor.py

# 只跑某类标记（--strict-markers 下未注册名会报错）
.venv/bin/python -m pytest tests/unit -m "migration_matrix"      # 历史 schema 升级矩阵
.venv/bin/python -m pytest tests/unit -m "concurrency"           # 并发/生命周期次序
```

## 仓库根散落的 Python 测试（不被任何 runner 收录）

| 文件 | 测什么 | 怎么跑 |
| --- | --- | --- |
| `tests/unit/test_entity_relation_builder.py` | `graphiti_integration.entity_relation_builder` 单测（AsyncMock） | `cd python_service && .venv/bin/python -m pytest ../tests/unit/test_entity_relation_builder.py`（依赖 `PYTHONPATH` 解析 `graphiti_integration`） |
| `tests/unit/test_file_entity_ingestor.py` | `graphiti_integration.file_entity_ingestor` + `database_reader.raw_reader.FileRecord` | 同上 |
| `tests/integration/test_ingestion_pipeline.py` | Graphiti 摄取 API→知识图谱全流程（httpx AsyncClient，mock_task_exists 打桩） | 需带 `PYTHONPATH=python_service` 手工运行 |
| `python_service/test_archive.py` | zip 归档辅助的独立脚本（顶层散件，前缀 `test_` 但无断言框架集成） | 手工 `python test_archive.py` |
| `tests/test_case_analysis_extraction.py` / `tests/test_streaming_filter.py` | AST/源码文本级静态冒烟（见 CppTestCatalog.md） | `python3 tests/test_case_analysis_extraction.py` |

## 已发现的测试层面问题

1. **四档案覆盖缺口**：`test.py` 的 investigation/fast/full 全部只跑 `tests/unit`，顶层 server 应用 15 个文件与 `tests/integration/` 不在任何稳定档案里；`make test-python` 虽全树覆盖但不在"稳定回归"叙事内（`docs/testing/test-profiles.md` 的表述容易让人误以为四档案≈全部）。
2. **同套件中两处 `test_dll_route.py`**（`tests/unit/` 与 `httpserver/tests/unit/`），内容相近但分属两树，维护时容易改漏一处。
3. **孤儿测试**：仓库根 `tests/unit/*.py`、`tests/integration/test_ingestion_pipeline.py`、`python_service/test_archive.py` 均无 runner 收录，`testpaths` 与根目录缺乏 `pytest.ini`（仓库根无任何 pytest 配置文件）导致它们事实上不可发现。
4. **标记使用与声明漂移**：`pytest.ini` 声明 6 个标记，实际 `integration` 仅 5 处、`slow` 仅 1 处，而 `asyncio_mode=auto` 下仍有 276 处显式 `@pytest.mark.asyncio`，存在清理空间。
5. **`test_wechat_dataset.py` 隐式再生成数据集**：fixture 检测 `tests/wechat_dataset_android.db` 缺失时自动调用 `scripts/generate_wechat_dataset.py`（`test_wechat_dataset.py:57-70`），"单测"会写仓库文件并在缺依赖时拖慢首次运行（详见 TestFixtures.md）。

**最后更新**: 2026-08-24（新建，测试目录）
