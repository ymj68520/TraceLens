# Python 测试目录（PythonTestCatalog）

本文盘点 `python_service/` 下全部 pytest 资产：`python_service/tests/`（**testpaths 收录**的唯一树，共 **209 个**测试文件，2026-11-10 实测清点）、`python_service/httpserver/tests/`（嵌套小套件）、`python_service/graphiti_integration/tests/`（不在 testpaths）、以及仓库根 `tests/` 下散落的 Python 测试。运行档案以 `python_service/scripts/test.py` 源码为准（现有 `docs/testing/test-profiles.md` 为历史基线记录）。本分支新增文件以 **新增** 标注：相对上一版清单逐一 diff 得出**新增 92 个、移除 0 个**（上一版自报总数 117 与其逐项清单 116 不符——investigation 子包多记 1 个；实际新增分解：unit 平铺 +71、forensic_report +9、integration +7、investigation +5——其中 `test_investigation_seed_bootstrap.py` 实际位于 `tests/unit/` 平铺层，已计入平铺层 +71）。

## 目录全景

```
python_service/
├── pytest.ini                 # 唯一的 pytest 配置；testpaths = tests
├── scripts/test.py            # 四档案稳定回归入口（focused/investigation/fast/full，74 行）
├── tests/                     # ← testpaths 收录（209 个 test_*.py）
│   ├── conftest.py            # 顶层共享 fixture（10 个 fixture + 2 个辅助函数）
│   ├── test_*.py              # 15 个：server 应用（分布式 C/S 服务）层
│   ├── integration/           # 8 个：ANALYZED_ONLY e2e + 6C/6B/现场只读（7 个新增）
│   │   └── README.md          # 仍只描述最早的 analyzed_only 一个文件（滞后，见问题 6）
│   └── unit/                  # httpserver 服务为主体（129 个平铺 + 3 个子包 57 个）
│       ├── evidence/          # 2 个：Evidence 键解析与解析器（C1/C2）
│       ├── forensic_report/   # 24 个：报告快照/生成/引用/叙事（R1/R2 系列，+9）
│       └── investigation/     # 31 个 + conftest.py：调查工作台（+5；conftest 断言 schema v8）
├── httpserver/tests/          # 3 个文件，历史嵌套套件（不在 testpaths）
├── graphiti_integration/tests/# 4 个文件（不在 testpaths）
└── test_archive.py            # 仓库外散件（不被任何 runner 收录）
```

数量核对（`find tests -name 'test_*.py'` 实测）：顶层 15 + integration 8 + unit 平铺 129 + evidence 2 + forensic_report 24 + investigation 31 = **209**。

## 顶层 `tests/test_*.py` —— server 应用（分布式 C/S 服务，15 个，无变化）

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
| `test_tasks_api.py` | 任务管理端点（`server.api.tasks`）；DB 依赖被 `mock_db` 替换 |

## `tests/integration/`（8 个，7 个新增）

目录 `README.md` 与 `pytest.mark.integration` 标记约定依旧（该标记仍只落在 `test_analyzed_only_ingestion_e2e.py`）。

| 文件 | 测什么（docstring 归纳） |
| --- | --- |
| `test_analyzed_only_ingestion_e2e.py` | ANALYZED_ONLY 摄取模式端到端（httpx + mock，不依赖真服务） |
| `test_6c_backup_restore.py` **新增** | 静默合成应用备份/恢复；不打开真实 Task |
| `test_6c_citation_scope.py` **新增** | 两个独立 R2 版本可同时引用 c001，无跨报告查找 |
| `test_6c_tls_check.py` **新增** | 合成证书 fixture；不改宿主信任 |
| `test_android_6b_full_http.py` **新增** | 6B 全 HTTP 工作流：真实 6A 认证 + 既有 R2 路由（纯合成数据） |
| `test_android_6b_http.py` **新增** | 隔离合成 HTTP 捕获与精确版本回溯；无真实 Task |
| `test_external_html_report_sample.py` **新增** | opt-in 集成测试：本地未提交的第三方 HTML 报告样本 |
| `test_field_readonly_real_manager.py` **新增** | disabled 发布模式下真实 manager 初始化；无 executor mock |

## `tests/unit/` —— httpserver 服务单测（平铺 129 个）

逐文件清单（测什么 = 源文件 docstring 首行或用例归纳），按主题分组；**新增** = 相对上一版清单的 71 个新文件。

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

**IM 导入（4 个，全部新增）**——WhatsApp/微信/QQ/老版 QQ 四平台取证导入

| 文件 | 测什么 |
| --- | --- |
| `test_whatsapp_import_service.py` **新增** | iOS WhatsApp 导入服务（ChatStorage.sqlite） |
| `test_wechat_forensics_import.py` **新增** | 微信取证导入管线（微信取证） |
| `test_qq_forensics_import.py` **新增** | QQ 取证导入管线（QQ 取证） |
| `test_qq_legacy_import.py` **新增** | 老版移动 QQ 4.x 账户库导入（pre-NTQQ） |

**关系图谱与时间线（6 个，全部新增）**

| 文件 | 测什么 |
| --- | --- |
| `test_comm_graph.py` **新增** | 统一通讯图：身份合并、边聚合、覆盖度 |
| `test_comm_graph_routes.py` **新增** | `/api/comm` 路由契约 |
| `test_people_graph.py` **新增** | 人员发现图 |
| `test_people_graph_android_sources.py` **新增** | Android 逻辑采集源的人员图材料读取 |
| `test_event_graph.py` **新增** | 事件图 |
| `test_timeline_summary.py` **新增** | 时间线摘要 |

**file-analysis SPEC 七阶段回归（8 个，全部新增）**

| 文件 | 测什么 |
| --- | --- |
| `test_file_analysis_phase1_ingestion.py` **新增** | Phase 1 摄取回归（SPEC C1） |
| `test_file_analysis_phase2_ground.py` **新增** | Phase 2 数据地基回归 |
| `test_file_analysis_phase3_orchestration.py` **新增** | Phase 3 编排与并发回归 |
| `test_file_analysis_phase4_graphiti.py` **新增** | Phase 4 Graphiti 预算与时间回归 |
| `test_file_analysis_phase5_cluster_context.py` **新增** | Phase 5（C3-v0）related_file_summaries 派生 |
| `test_file_analysis_phase6_outputs.py` **新增** | Phase 6 D15 结构化输出（宽松解析器+提示词） |
| `test_file_analysis_phase7_lifecycle.py` **新增** | Phase 7 D8 版本链（analysis_id_upstream）与生命周期 |
| `test_file_analysis_record.py` **新增** | `POST /api/file-analysis/record` 管线三写入入口（SPEC E） |

**事件聚类分析（7 个，全部新增）**

| 文件 | 测什么 |
| --- | --- |
| `test_cluster_analysis_schema.py` **新增** | 聚类分析表结构/DDL（SPEC §3） |
| `test_cluster_analysis_backfill.py` **新增** | per-event llm_* 回填为分析行（SPEC §3.3） |
| `test_cluster_analysis_adaptive.py` **新增** | 预算驱动自适应分桶与任务级运行（SPEC §5/§8.1） |
| `test_cluster_analysis_mapreduce.py` **新增** | 聚类 map-reduce 分析与 Graphiti 摄取（SPEC §6/§9） |
| `test_cluster_golden.py` **新增** | 聚类坐标 golden fixture（SPEC §4.4，Python 侧） |
| `test_event_cluster_analysis_routes.py` **新增** | `/api/llm/event-cluster-analysis*` 路由（SPEC §8.1） |
| `test_llm_cluster_analysis_route.py` **新增** | `POST /api/llm/analyze-event-cluster` 回归 |

**KG 摄取加固与吞吐门（11 个，全部新增）**

| 文件 | 测什么 |
| --- | --- |
| `test_graphiti_local_evidence_query.py` **新增** | 本地 KG 锚定任务自有 file-path 实体 |
| `test_graphiti_model_config.py` **新增** | `GRAPHITI_LLM_MODEL` 钉 phi-4（mvp SPEC §3） |
| `test_graphiti_read_path_hardening.py` **新增** | KG 加固 Phase B（SPEC §A2/§A3） |
| `test_graphiti_relationship_trace.py` **新增** | 图事实只溯源本任务的 episode 与文件 |
| `test_kg_ingestion_dispatch.py` **新增** | KG 加固 Phase C（SPEC §B1/§B2 摄取分派） |
| `test_worker_episode_rows_offloop.py` **新增** | KG 加固 Phase A（SPEC §A1 worker episode 行离环） |
| `test_episode_chunk_budget.py` **新增** | CJK 感知 episode 预算（phi-4 上下文适配） |
| `test_episode_completion_gate.py` **新增** | Path-A episode 完成门（诚实终态） |
| `test_ingestion_gate.py` **新增** | 前台门 + episode 门（llm-throughput-hardening SPEC A） |
| `test_ingestion_report_tail.py` **新增** | 摄取完成触发管线尾报告回调（且仅此时触发） |
| `test_mvp_feature_gates.py` **新增** | MVP 特性门（mvp-phase1-acceptance §4） |

**多源接入预检与归一（13 个，全部新增）**——手机备份/云导出/未知源的预检分诊与结果归一

| 文件 | 测什么 |
| --- | --- |
| `test_android_archive_preflight.py` **新增** | 确定性、非敏感的逻辑容器预检 fixture |
| `test_android_container_pipeline.py` **新增** | sparse/LP fail-closed 探测（全部合成镜像） |
| `test_android_image_preflight.py` **新增** | Android 镜像预检 |
| `test_ios_backup_preflight.py` **新增** | iOS 逻辑备份预检分诊 |
| `test_vivo_backup_preflight.py` **新增** | vivo(iQOO) 备份预检分诊 |
| `test_aliyun_image.py` **新增** | 阿里云镜像接入 |
| `test_evidence_preflight.py` **新增** | 未知取证源的合成只读预检 fixture |
| `test_android_coverage.py` **新增** | Android 覆盖度 |
| `test_android_result_sets.py` **新增** | AndroidAnalyzer 输出的结果集 |
| `test_android_report_import.py` **新增** | 离线报告导入（纯合成 fixture） |
| `test_harmony_artifacts.py` **新增** | 鸿蒙记录走既有冻结 Android 证据/报告契约 |
| `test_android_sample_manifest_6c.py` **新增** | 样本清单（不做全机样本扫描） |
| `test_6c_lp_frozen_tool_pin.py` **新增** | LP 冻结工具钉版 |

**现场交付 field（3 个，全部新增）**

| 文件 | 测什么 |
| --- | --- |
| `test_field_security.py` **新增** | 现场凭据/角色（合成凭据，不碰真实用户与证据） |
| `test_android_field_check.py` **新增** | `scripts/android_field_check.py` 基线检查契约 |
| `test_android_field_delivery.py` **新增** | 现场交付回归（纯合成） |

**Evidence 身份与溯源（3 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_normalize_evidence_path.py` | `normalize_evidence_path` 证据身份规范化（A1） |
| `test_claim_provenance_reader.py` | 严格只读的历史 Claim 溯源 |
| `test_citation_validation.py` | 引用校验 |

**Investigation HTTP 契约（9 个）**

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
| `test_investigation_workbench_routes.py` **新增** | Workbench bootstrap 路由契约（C9a） |

**报告管线（14 个）**

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
| `test_mobile_intelligence_report.py` **新增** | 情报报告必须暴露移动端专属章节 |
| `test_mobile_report_evidence.py` **新增** | 移动通讯记录可作为报告证据 |
| `test_report_citation_timeline_route.py` **新增** | 报告域精确时间线契约 |
| `test_initial_analysis_translation.py` **新增** | 译文覆盖层不改变冻结源快照 |

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

**分析器客户端与内容路由（13 个）**

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
| `test_office_parsers.py` **新增** | Office 文档解析器（Word 支持 + PPT 回退） |
| `test_audio_analyzer.py` **新增** | 音频转写栈（2026-09-19 音频分析设计） |
| `test_video_analyzer.py` **新增** | 视频分段内容分析（2026-09-19 设计） |
| `test_auto_extract_analyze.py` **新增** | 分析路由在缺文件时自动先提取 |
| `test_associations_report_mvp.py` **新增** | MVP 报告页关联端点 |

**中文输出（2 个，新增）**

| 文件 | 测什么 |
| --- | --- |
| `test_chinese_output_contract.py` **新增** | 中文展示/LLM 契约保留历史提示词与证据原文 |
| `test_chinese_prompts.py` **新增** | 简体中文 graphiti 提示词覆写 |

**服务装配与基础设施（16 个）**

| 文件 | 测什么 |
| --- | --- |
| `test_service_manager_investigation.py` | ServiceManager C3 Investigation 服务接线 |
| `test_service_manager_report_lifecycle.py` | ServiceManager 报告生命周期 |
| `test_investigation_seed_bootstrap.py` **新增** | `InvestigationService.bootstrap` 聚类种子集成（真实临时库跑种子服务：事件派生、证据链接与快照、幂等，不打 LLM） |
| `test_startup_reliability.py` | 分布式 server 启动可靠性契约 |
| `test_cors_config.py` | CORS 配置 |
| `test_case_analysis_routes.py` | D3b：旧 case-analysis 生成软退役契约 |
| `test_wechat_graph_routes.py` | WeChat 图谱 FastAPI 路由回归 |
| `test_database_models.py` | SQLAlchemy ORM 模型（`server.models.database`，server 侧） |
| `test_db_session.py` | 数据库会话管理（`server.db.session`，server 侧） |
| `test_schemas.py` | Pydantic API schema（`server.models.schemas`，server 侧） |
| `test_database_events_route.py` **新增** | `GET /api/db/tasks/{task_id}/events` 契约 |
| `test_case_deletion_cleanup_route.py` **新增** | `DELETE /api/llm/cases/{case_id}` 删除清理加固 |
| `test_reconcile_orphan_analysis.py` **新增** | 启动期合并案件跨镜像孤儿分析对账 |
| `test_extraction_layout.py` **新增** | `httpserver.services.extraction_layout` |
| `test_llm_patch_response_format.py` **新增** | llm_patch response_format 回退 |
| `test_validation_secret_redaction.py` **新增** | 校验失败不回显一次性归档密码 |

（合计 129 个，与目录清点一致。）

## `tests/unit/` 三个子包

### `unit/evidence/`（2 个，无变化）

| 文件 | 测什么 |
| --- | --- |
| `test_keys.py` | `parse_evidence_key` / `ParsedEvidenceKey`（C1） |
| `test_resolver.py` | `EvidenceResolver`（C2 + C2.1）：任务域、fail-closed、零写入 |

### `unit/forensic_report/`（24 个，+9 新增）

| 文件 | 测什么 |
| --- | --- |
| `test_generation_admission.py` | R2b 冻结报告生成准入（§26 矩阵） |
| `test_generation_execution.py` | R2c 生成执行与引用校验（§25-§28） |
| `test_report_generation_routes.py` | `POST /api/reports/generate` 与 generations 查询路由契约 |
| `test_report_narrative_routes.py` | R2d 严格任务域叙事 Viewer 只读路由 |
| `test_analysis_adapter.py` / `test_cpp_backend_task_lookup.py` / `test_sqlite_task_adapter.py` / `test_source_resolver.py` | 报告数据适配层（C++ 后端任务定位、SQLite 任务适配、来源解析） |
| `test_ids.py` / `test_models.py` / `test_repository.py` / `test_search_index.py` / `test_service.py` / `test_snapshot_writer.py` | ID 生成、模型、仓库、检索索引、服务、快照写入 |
| `test_routes.py` | 版本化报告快照 HTTP 契约 |
| `test_6c_readonly_repository.py` **新增** | 发布启动不得重写既有报告库 |
| `test_auto_report.py` **新增** | 管线尾自动报告：seed + submit 一次、幂等 |
| `test_chapter_packing.py` **新增** | 章节打包：章节数是代码属性而非模型属性 |
| `test_generation_classification.py` **新增** | 合成协议测试（非真实模型分类准确率声明） |
| `test_generation_sectioned.py` **新增** | final-report:v2 分节管线：分组、大纲、分节范围 |
| `test_report_stages.py` **新增** | 合成两阶段回归：真实冻结源/存储 + 脚本化模型 |
| `test_stage_narrative.py` **新增** | 阶段叙事编织：校验过的方向织入章节 |
| `test_task_purge.py` **新增** | 任务删除对报告库的级联清理 |
| `test_theme_induction.py` **新增** | 主题归纳（报告 shape v3，stages 1-2） |

### `unit/investigation/`（31 个 + `conftest.py`，+5 新增）

共享 `conftest.py` 提供 session 级 `investigation_v7_baseline`：一次构建空 schema `investigation.db`，断言 `integrity_check=ok` 且 `user_version==SUPPORTED_SCHEMA_VERSION`——**本分支已升到 v8**（`conftest.py:25` 断言 `== 8`；fixture 名仍叫 v7 是历史命名），其余用例从该基线拷贝。按阶段：

- 持久层/服务：`test_investigation_repository.py`（C4a 捕获与幂等）、`test_investigation_service.py`（C3 编排）、`test_investigation_acquisition.py`（快照候选构建）、`test_investigation_paths.py`（fail-closed 任务域路径）、`test_investigation_secondary.py`（C4b-1 版本状态机）、`test_investigation_execution.py`（C4b-2 执行层）、`test_investigation_completion.py` / `test_investigation_structured.py`（C5b 原子完成与结构化解析）、`test_investigation_grounding.py`（C5a Claims 持久化与 Grounding 校验）、`test_investigation_review.py`（C6 评审）、`test_investigation_event.py`（C7a schema 与 DB 级约束）、`test_investigation_propagation.py`（C7b 已接受分析→事件）、`test_investigation_refresh.py` / `test_investigation_refresh_execution.py`（C7c-1/2）、`test_investigation_graph.py`（C8b overlay 读取与合成）、`test_investigation_read.py`（C9a）、`test_investigation_context.py`（C4c Analyst Context Snapshot）、`test_investigation_report_evidence.py` + `test_report_evidence_routes.py`（R1 冻结显式绑定 §19）。
- **新增（5 个）**：`test_investigation_file_timeline.py`（文件中心工作台时间线投影）、`test_acceptance_repairs.py`（PC.E01 验收运行中观察到的回归修复）、`test_android_artifact_report_chain.py`（合成、显式选中的 Android 行走冻结 R2 引用链）、`test_6c_empty_v7_overview.py`（空 v7 概览）、`test_6c_v7_readonly_routes.py`（历史 v7 GET 保持可读、写操作显式 409 且零变异）。注：`test_investigation_seed_bootstrap.py` 同为新增文件，但实际位于 `tests/unit/` 平铺层（见"服务装配与基础设施"），不属本子包。
- Phase C 跨阶段集成：`test_phase_c_evidence_to_review_flow.py`、`test_phase_c_accept_to_event_dirty_flow.py`、`test_phase_c_event_refresh_clean_flow.py`、`test_phase_c_refresh_new_accept_keeps_dirty.py`、`test_phase_c_read_side_no_mutation.py`、`test_phase_c_cross_task_isolation.py`。
- D4b 边界：`test_d4b_task_deletion_boundary.py`。

> 注：上一版记录"26 个"与当时的逐项清单（25 个）本就不自洽；本版以逐文件清点为准（31 个，新增 5 个、移除 0 个）。

## 顶层 `tests/conftest.py` 关键 fixture

`python_service/tests/conftest.py`（供全树使用，结构未变）：`test_db_path`（临时 SQLite 文件，经 `_fast_sqlite_connect` 加速）、`database_with_analyzed_files`、`events_database`、`neo4j_available`（探测跳过）、`test_settings`（`httpserver.config.Settings`，Neo4j/Redis 指向本地占位）、`test_app`（`create_app` + settings 覆盖）、`test_client`（**保持 lifespan 打开**，让后台摄取任务存活）、`mock_cpp_backend`、`db_session`（自建引擎绑定 `TEST_DATABASE_URL`，绕开 import 期读取 `DATABASE_URL` 的 `server.db.session`）、`org_and_client`。

## `pytest.ini` 标记体系

`python_service/pytest.ini` 全文要点（未改动）：

- `testpaths = tests` —— **只**发现 `python_service/tests/`；httpserver/tests、graphiti_integration/tests、仓库根 tests 均不在内。
- `markers`（配合 `--strict-markers`，未注册标记直接报错）：`integration`、`unit`、`slow`、`concurrency`、`migration_matrix`、`asyncio`。
- `asyncio_mode = auto` —— async 用例无需逐个加 `@pytest.mark.asyncio`。
- `addopts = -v --strict-markers --tb=short`；`log_cli` 开启 INFO 级实时日志；过滤 DeprecationWarning。

实际标记使用统计（2026-11-10 grep 全树实证）：

- `pytest.mark.asyncio`：431 处 / 66 文件（`asyncio_mode=auto` 下基本冗余，清理空间进一步变大）。
- `parametrize`：52 处 / 25 文件。
- `concurrency`（8 文件，精确清单）：`tests/unit/test_markitdown_routes.py`、`test_service_manager_report_lifecycle.py`、`tests/unit/forensic_report/test_repository.py`、`test_service.py`、`test_source_resolver.py`、`tests/unit/investigation/test_investigation_execution.py`、`test_investigation_repository.py`、`test_investigation_secondary.py`。
- `migration_matrix`（7 处 / 5 文件）：`tests/unit/investigation/` 下的 `test_investigation_secondary.py`、`test_investigation_refresh.py`、`test_investigation_event.py`、`test_investigation_completion.py`、`test_investigation_grounding.py`——全部围绕 schema 历史升级。
- `slow`（1 处）：`tests/unit/test_wechat_dataset.py`（数据集全量校验，被 fast/investigation 档案排除）。
- `integration`（3 处 / 1 文件）：`tests/integration/test_analyzed_only_ingestion_e2e.py`（另有 README.md 文字提及）。

标记的语义在 `scripts/test.py:24` 处被消费：`FAST_EXPRESSION = "not slow and not concurrency and not migration_matrix"`——即"快档案"剔掉慢、并发与迁移矩阵三类；`full` 档案不做剔除。

## `scripts/test.py` 四档案与 Makefile 对应

`python_service/scripts/test.py`（74 行）是稳定回归入口：自行定位 `python_service` 根作为子进程 cwd、把 `.venv` 的 site-packages 注入 `PYTHONPATH`，因此**从仓库任何目录调用都有效**。核心常量：`FAST_EXPRESSION = "not slow and not concurrency and not migration_matrix"`（`scripts/test.py:24`）；`INVESTIGATION_PATHS`（`scripts/test.py:14-23`）仍是 8 条路径（investigation 子包 + 5 个路由文件 + 2 个 ServiceManager 文件），未把新增的 workbench/seed_bootstrap 文件纳入。

| 档案 | 命令 | 实际展开（源码为准） | Makefile 目标 |
| --- | --- | --- | --- |
| focused | `python scripts/test.py focused <任意 pytest 参数>` | 原样转发；无标记排除 | `make test-python-focused ARGS=...` |
| investigation | `python scripts/test.py investigation` | `tests/unit/investigation` + 5 个路由文件 + 2 个 ServiceManager 文件 + `-m "<FAST_EXPRESSION>"` | `make test-python-investigation` |
| fast | `python scripts/test.py fast` | `tests/unit` + `-m "<FAST_EXPRESSION>"` | `make test-python-fast` |
| full | `python scripts/test.py full` | `tests/unit -q`，**无**标记排除 | `make test-python-full` |

注意：四个档案都只覆盖 `tests/unit`；顶层 server 应用 15 个文件与 `tests/integration/` 需用 focused 档案（如 `make test-python-focused ARGS="tests/test_auth_api.py -v"`）或直接 `make test-python`（= `.venv/bin/python -m pytest tests/ -v`，全树 209 个文件）。`docs/testing/test-profiles.md` 记录了历史基线（Investigation 425 passed / 26:15，Fast 1086 passed / 39:26 等），以当时的树为准——树已翻倍，数字不可直接对比。

## 第三方指标验收套件（不在 testpaths，单独跑）

`tests/acceptance_metrics/` 是面向第三方验收方的黑盒指标验收集（25 个用例），只通过已部署服务的 HTTP 端点判定，不 import 产品代码，**不被 `python_service/pytest.ini` 收录**。详见 [AcceptanceHarness.md](AcceptanceHarness.md) 与该目录 `README.md`：

```bash
python3 tests/acceptance_metrics/prepare_fixtures.py                  # 先生成夹具（无需 root）
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v -m "not llm"   # 非 LLM 用例
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v                # 全量（含 LLM 推演）
```

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
make test-python-focused ARGS="tests/unit -k 'comm_graph and not routes' --maxfail=1"

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
| `tests/integration/test_field_security_e2e.py` **新增** | 隔离 live C++/Python 现场认证冒烟（见 CppTestCatalog.md 问题 5） | 手工运行；仅记录于 `docs/android-field-security-6a.md` |
| `tests/integration/test_pipeline_report_gate_http.py` **新增** | C++ 任务完成等待摄取与报告终态 | **无任何注册/引用**（同问题 5） |
| `tests/raid_validation/`（7 个 test_*.py + fixtures.py + http_task_e2e.py + __init__.py） **新增** | RAID（MD v1）解析验证：合成 MD fixture（独立编码 oracle）、真实 EWF 解码、live 隔离 RAID→Task 回归 | 手工 pytest（无配置收录） |
| `python_service/test_archive.py` | zip 归档辅助的独立脚本（顶层散件，前缀 `test_` 但无断言框架集成） | 手工 `python test_archive.py` |
| `tests/test_case_analysis_extraction.py` / `tests/test_streaming_filter.py` | AST/源码文本级静态冒烟（见 CppTestCatalog.md） | `python3 tests/test_case_analysis_extraction.py` |

## 已发现的测试层面问题

1. **四档案覆盖缺口扩大**：`test.py` 的 investigation/fast/full 全部只跑 `tests/unit`，顶层 server 应用 15 个文件与 `tests/integration/`（含 6B/6C 现场链路回归）不在任何稳定档案里；树从 117 涨到 209 后，"四档案≈全部"的错觉风险更高。
2. **`INVESTIGATION_PATHS` 未跟上新增文件**：`test_investigation_workbench_routes.py`、`test_investigation_seed_bootstrap.py`（均在 `tests/unit/` 平铺层）以及 investigation 子包 5 个新文件中不属于子包通配的部分，依赖"investigation 档案跑整个子包"才被覆盖；平铺层的两个新文件则**不在** investigation 档案内（`INVESTIGATION_PATHS` 只列 8 条路径），只能靠 fast/full 档案兜住。
3. **同套件中两处 `test_dll_route.py`**（`tests/unit/` 与 `httpserver/tests/unit/`），内容相近但分属两树，维护时容易改漏一处。
4. **孤儿测试继续增多**：仓库根 `tests/unit/*.py`、`tests/integration/test_ingestion_pipeline.py`、`tests/integration/test_pipeline_report_gate_http.py`、`tests/raid_validation/`、`python_service/test_archive.py` 均无 runner 收录（仓库根仍无任何 pytest 配置文件）。
5. **标记使用与声明漂移加剧**：`pytest.ini` 声明 6 个标记，实际 `integration` 仅 1 个文件、`slow` 仅 1 处，而 `asyncio_mode=auto` 下已有 431 处显式 `@pytest.mark.asyncio`（66 文件），清理欠账翻倍。
6. **`tests/integration/README.md` 滞后**：仍只描述 `test_analyzed_only_ingestion_e2e.py` 一个文件与"需要 Neo4j"的前提，对本分支新增的 7 个合成/隔离 e2e（多数不需要 Neo4j）只字未提。
7. **`test_wechat_dataset.py` 隐式再生成数据集**：fixture 检测 `tests/wechat_dataset_android.db` 缺失时自动调用 `scripts/generate_wechat_dataset.py`，"单测"会写仓库文件并在缺依赖时拖慢首次运行（详见 TestFixtures.md）。
8. **investigation conftest 断言 schema v8 但 fixture 名仍是 `investigation_v7_baseline`**：命名与实际 schema 版本脱节，后续升 v9 时容易再次误导。

**最后更新**: 2026-11-10（feature/model-routing 分支全面改版：209 个测试文件实测清点）
