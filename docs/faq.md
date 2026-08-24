# 常见问题（FAQ）

> 按主题分组的 50 问。每答给出结论与详细文档链接；与 Troubleshooting 的分工：那边按"症状→操作"，这边按"疑问→解释"。已知缺陷的完整索引见 [Troubleshooting §13 的已知问题索引表](getting-started/Troubleshooting.md)。

## 安装与启动

**Q1 为什么有时候端口是 8080 有时候是 8666？**
C++ 代码与 `.env.example` 默认 8080（`HTTP_SERVER_PORT`），但 `run.sh` 在未设置该变量时**回退 8666**。用 run.sh 启动就访问 8666，用 `make cpp` 手动启动是 8080。[详见](reference/Environment.md)

**Q2 前端 dev 端口是多少？为什么不是 Vite 默认的 5173？**
3000（`web/vite.config.js` 显式指定）。生产模式没有独立前端端口——C++ 服务从 `web/dist` 托管 SPA，浏览器直接访问 C++ 端口。

**Q3 三个服务必须全启动吗？**
不必。C++ 单独即可分析；Python 不在则无图谱/报告/markitdown（C++ 的 Office 解析会回退旧解析器）；C/S 不在只影响分布式模式。run.sh 里 C++ 健康检查是硬失败，另两个是软失败。

**Q4 setup.sh 报 Neo4j/Redis 相关失败？**
Redis 是可跳过项（任务队列回退内存）；Neo4j 装失败会导致图谱降级但不影响分析。确认 `NEO4J_PASSWORD` 已在 .env（setup.sh 用它做初始密码）。[详见](ops/ExternalServices.md)

**Q5 .env 里配了 LOG_LEVEL 为什么没效果？**
该变量未接线——无生产代码调 `Logger::setLevel/setOutput`，实际恒 INFO/stdout。同类未接线变量见 [Environment 的标注](reference/Environment.md)。

## 任务与分析

**Q6 任务状态哪里看？为什么 jq 查 tasks.json 和 API 返回的大小写不一样？**
API 返回小写（pending/running…），tasks.json 持久化大写——双轨是历史事实。[详见](getting-started/Troubleshooting.md#13-深挖工具箱)

**Q7 任务一直 RUNNING 怎么判断是卡死还是在跑？**
看进度百分比是否变化：变=在跑（阶段内可能长时间不汇报）；不变超过 30 分钟会被看门狗标 FAILED（1 秒一跳轮询，双阈值）。[详见](architecture/Concurrency.md#23-看门狗与协作式取消)

**Q8 场景（scenarios）不选会怎样？**
SceneDetector 会从 raw.db 特征路径自动检测并回填，写 SCENE_DETECTED 审计日志（含每场景命中数）。检测在过滤之前跑（先过滤会把特征路径当噪音丢掉）。

**Q9 过滤画像把文件全筛掉了怎么办？**
FileFilter 检测到 included_files=0 时打警告并**继续用未过滤库**——宁可全量分析不产空结果。换画像重跑只需重新复制 raw.db，原始库不动。

**Q10 任务删除后数据真的删干净了吗？**
删除即删任务目录；D4b 加固后还有终端写保护（删除后拒绝新写入）与 TOCTOU 防复活。审计日志保留（它独立于任务）。[详见](ops/DataAndBackup.md)

**Q11 LLM 分析能关吗？成本怎么控制？**
HTTP 任务前端固定开（llm_analyze=true）；CLI 不带相关参数即无 LLM。控制手段：llm_mode=smart（先粗选再精析）、LLM_MAX_FILES=500、LLM_MAX_EVENT_CLUSTERS。[详见](ops/PerformanceTuning.md)

**Q12 内存取证为什么在 HTTP 任务里找不到结果？**
`--memory-analyze` 是 CLI 专用旁路；HTTP 侧的 /memory 页靠命名约定（`_memory.db`）找库，CLI 与 HTTP 任务的目录布局需一致才能显示。[详见](tutorials/MemoryForensics.md)

**Q13 DLL 分析到底分析的是镜像里的文件吗？**
当前不是——`scanDLLFiles()` 扫的是分析机本机目录（/usr/lib 等，源码 TODO 自认）。`--dll-threshold` 也是哑参数（30 硬编码）。[详见](modules/cpp/analyzers/DLLAnalyzer.md)

## 数据与数据库

**Q14 一个任务到底产出哪些文件？**
`data/tasks/<id>/`：raw.db、events.db、files.db、android/windows/linux/oss.db、extracted_files/、carved_files/。CLI 模式则产在镜像旁边且平台工件并入 _files.db。[逐文件导览](getting-started/QuickStart.md#8-任务产出逐文件导览)

**Q15 oss.db 是阿里云 OSS 的分析结果吗？**
不是。任务目录里的 oss.db 是 SERVER_CLOUD 场景由 LinuxFilesAnalyzer 写的 linux_* 表族；阿里云 OSS 分析组件（OSSAnalyzer）当前无生产调用方。同名不同物。[详见](architecture/Overview.md#8-哪些代码不要参考)

**Q16 raw.db 里怎么有 llm_* 列但是空的？**
建表 SQL 带出但写入方从不写——死列。LLM 结论只落 files.db 主表。[详见](modules/cpp/core/DatabaseManager.md)

**Q17 event_correlations / event_chains 表为什么是空的？**
EventCorrelationEngine 未接入任务流水线（无生产调用方）。表结构就绪，等接线。[详见](modules/cpp/core/EventCorrelationEngine.md)

**Q18 Windows 库里 shimcache/user_assist/rdp/wifi 表为什么是空的？**
四个解析器完整实现但无调用方（shellbag 连解析器都没有）。接线方法见模块文档的"常见任务配方"。[详见](modules/cpp/analyzers/WindowsFilesAnalyzer.md)

**Q19 想直接 SQL 查证据，从哪里开始？**
[schema/ 九篇](schema/LinuxDB.md) 每篇末尾有"查询手册"（每库 5-8 条分析师常用 SQL）；跨库联查看 [SqlCookbook](reference/SqlCookbook.md)。

**Q20 _filtered.db 和 raw.db 什么关系？**
过滤画像产出的副本（raw.db 不可变纪律）；任务对象的 output_raw_db 指向它，前端展示的也是它。

## LLM 与知识图谱

**Q21 知识图谱为空怎么排查？**
顺序：①任务是否 completed 且触发了摄取（审计查 GRAPHITI_INGESTION / 任务对象 graphiti_job_id）→ ②job 状态（/api/graphiti/jobs/{id}）→ ③Neo4j 是否可用（/health/ready 的可选项）→ ④episode 级错误（job 详情逐条报错）。案例级历史坑（NameError 静默为空）已于 2026-08-24 修复。[详见](modules/python/services/GraphitiService.md)

**Q22 图谱为什么"稀疏"（实体很少）？**
三大要素：FORENSIC_EXTRACTION_INstructions（默认提示词会丢取证实体）、EpisodeType.text 渲染、llm_patch 前置。任一失效都会稀疏——检查顺序见模块文档。[详见](modules/python/graphiti_integration/GraphitiIngestor.md)

**Q23 换了 LLM 模型后图谱/描述质量骤降？**
检查模型名逐字一致（LLM_TEXT_MODEL 与服务端 /v1/models 的 ID）；双模型要求（gpt-oss-20b + nomic-embed）是否同载；换模型后 GRAPHITI_BATCH_SIZE 与上下文窗口是否匹配。[详见](ops/LLMOperations.md)

**Q24 GRAPHITI_BATCH_SIZE 到底默认多少？**
三处不一致：httpserver Settings=50、graphiti_integration from_env=10、.env.example=25。httpserver 路径以 Settings 为准；建议 .env 显式钉死。[详见](reference/Environment.md)

**Q25 LLM 请求明明并发提交了为什么实际串行？**
LLMClient 内部互斥锁——本地单槽端点的自我保护。多槽端点需重审该锁。[详见](architecture/Concurrency.md#25-llm-调用的串行化瓶颈)

**Q26 重分析（reanalyze）写到哪里？**
直接 UPDATE 该任务 files.db 的 llm_* 列与 file_descriptions（服务端解析路径，客户端只给提示——D2b 信任边界）。

## 报告与调查

**Q27 POST /api/llm/case-analysis 为什么返回 410？**
旧案件分析链路已退役（D3b）。现行：multi_analysis（多镜像案件）+ /api/reports（版本化报告）。[详见](modules/python/httpserver/routes/CaseAnalysis.md)

**Q28 调查工作台有些按钮为什么固定 409？**
五个端点（事件评审/版本拒绝/结论评审/笔记/发布的一部分）按契约固定 409——是冻结的边界而非故障。[409 契约表](modules/python/httpserver/routes/Investigation.md)

**Q29 报告生成 202 之后去哪查？**
轮询 GET /api/reports/generations/{id} 直到 completed；生成准入带 input_hash（输入冻结），重复请求同信封幂等。

**Q30 终版报告的"完整性校验"是什么？**
发布时计算内容哈希，前端 /investigation/report 页可校验——防报告被事后篡改。

## 前端

**Q31 登录页随便输都能进？**
是——mock 登录（本地栈无认证），token 只影响 401 跳转行为。[详见](modules/web/Overview.md)

**Q32 /analysis-center 打开就报错？**
已知 bug：该页从孤儿文件导入 useToast（context 无 Provider），渲染即崩被 ErrorBoundary 接住。[详见](modules/web/Pages.md)

**Q33 /oss 页面一直 404？**
它调用的 C++ OSS 路由从未注册（编译但没挂载，且聚合器内子路由是栈对象、即使补注册也是悬空指针）。[详见](modules/cpp/network/routes/OSSRoutes.md)

**Q34 侧栏"调查图谱"点了没反应？**
死链：Layout 链接 /investigation-graph，路由表无此路由（对应页面是无路由的死代码页面）。

**Q35 微信关系图的"缓存失效"按钮没用？**
路由每请求新建服务实例，实例级缓存与 invalidate 都是对空缓存操作——已知无效。[详见](modules/python/services/WeChatGraphService.md)

**Q36 界面有些文字显示成 nav.xxx？**
侧栏两个键在 en/zh 词表里缺失，直接显示键名原文。

## 分布式 C/S

**Q37 super_admin 登录一直 401？**
001 迁移的种子凭据是坏的（bcrypt 哈希错误 + .local 邮箱）；003 定向修复。自动迁移只跑 001——手工 `psql -f` 003。[详见](ops/UpgradeMigration.md)

**Q38 agent 能执行哪些命令？**
只有 analyze_disk 真执行；extract_file/health_check 是"确认但不执行"（返回 success 但无动作）——已知能力缺口。[详见](modules/cpp/http_agent/HttpAgent.md)

**Q39 已有环境升级要跑哪些 SQL？**
002（命令-任务外键回填）+ 003（种子修复），均幂等可重放。[详见](ops/UpgradeMigration.md)

**Q40 C/S 和本地栈能同机跑吗？**
能且默认如此（run.sh 同时拉起）：8090/8091 端口分离、数据库/认证完全独立、共享 .env 靠 extra="ignore" 兼容。

## 测试与开发

**Q41 C++ 测试怎么跑单个？**
`cd build && ctest -R <名字>`；61+1 个目标的名字与依赖见 [CppTestCatalog](testing/CppTestCatalog.md)。

**Q42 Python 测试为什么有的跑不到？**
四档案（fast 等）只收 tests/unit；顶层 server 应用 15 个文件与 integration 不在稳定档案；仓库根的孤儿测试不被任何 runner 收录。[详见](testing/PythonTestCatalog.md)

**Q43 改了 C++ 路由要同步改哪些地方？**
路由 handler → Swagger 注册表 →（如前端要用）vite 前缀/前端 service → 手写 endpoints 清单（SystemDocsRoutes）与 database-schema 三份描述的漂移检查。[配方](modules/cpp/network/HTTPServer.md#常见任务配方)

**Q44 想给分析器加一种新证据，从哪下手？**
对应平台分析器文档的"常见任务配方"章节（Linux/Windows/Android 各有四步法）。[Linux 例](modules/cpp/analyzers/LinuxFilesAnalyzer.md)

**Q45 文档和代码冲突了听谁的？**
代码。文档于 2026-08-24 全面对齐过代码，但代码会继续演进——发现冲突时以代码为准并欢迎修订文档（各文档"注意事项"里记录的缺陷修复后请同步删标注）。

## 运维

**Q46 服务日志在哪？怎么没了昨天的？**
`build/logs/{cpp_server,python_service,cs_server}.log`——启动即覆盖（`>` 重定向、无轮转），历史随重启丢失。C++ 数据日志在 data/logs/。[详见](ops/Monitoring.md)

**Q47 审计库在哪？**
实际落 CWD（run.sh 下在 build/）；PathManager 规划的 data/audit/ 未接线。轮转/保留函数已实现但无调用方。[详见](modules/cpp/core/AuditLog.md)

**Q48 备份要备什么？**
`data/` 整目录（任务库+tasks.json+审计）+ `.env` + `build/logs/`（可选）。SQLite 每任务独立文件，无需停服一致性快照（建议低峰）。[详见](ops/DataAndBackup.md)

**Q49 磁盘满了先删什么？**
大头依次：任务目录里的 carved_files/ 与 extracted_files/、审计库、日志。删任务用 API（走终端写保护）而非直接 rm。

**Q50 想让任务跑快点，调哪个参数？**
先 THREAD_POOL_SIZE（注意它同时放开任务并发与 LLM 并发两道闸）；确认 WAL 开启（不开会有 jbd2 卡顿教训）；大镜像先过滤画像减量。[详见](ops/PerformanceTuning.md)

## 性能与容量

**Q51 一块 1TB 镜像要分析多久？**
没有固定答案——耗时随**文件个数**（不是字节数）与 LLM 限额变化。规划方法与两个实测基线见 [CapacityPlanning](ops/CapacityPlanning.md)。

**Q52 怎么让任务跑快点？**
优先级从高到低：过滤画像减量 → smart 模式 → LLM_MAX_FILES/CLUSTERS 限额 → THREAD_POOL_SIZE（注意它同时放开 LLM 并发闸，而 LLM 实际串行）。

**Q53 THREAD_POOL_SIZE 调到 8 有什么副作用？**
分析并发 8 个任务的同时，LLM 批量也按 8 并发提交（但被 LLMClient 互斥串行化）；磁盘随机 IO 压力上升。决策表见 [CapacityPlanning §5](ops/CapacityPlanning.md)。

**Q54 Graphiti 摄取要多久？**
每 episode 一次 LLM 抽取 + 嵌入，量级与文件数×批量参数相关（GRAPHITI_BATCH_SIZE）。job 详情有逐 episode 计数与错误。

**Q55 建全文索引要多久？**
与被索引文本总量线性；先 filter 后 index 的策略能砍掉大头（[教程](tutorials/FullTextSearch.md)）。

## 开发与贡献

**Q56 怎么只跑一个 C++ 测试？**
`cd build && ctest -R <名字>`；61+1 个目标清单见 [CppTestCatalog](testing/CppTestCatalog.md)。

**Q57 加一个 HTTP 端点要动几个文件？**
四步：路由实现 → HTTPServer 注册 → Swagger 登记 →（前端要用的话）service+页面。完整配方见 [HTTPServer 模块文档](modules/cpp/network/HTTPServer.md)。

**Q58 加一种新证据解析从哪下手？**
对应平台分析器的"常见任务配方"章节（Linux/Windows/Android 各有四步法与样板函数）。

**Q59 改了代码怎么知道哪些文档要同步？**
"文档触达矩阵"在 [Development 的贡献者工作流](getting-started/Development.md)。

**Q60 文档写的和代码不一样怎么办？**
以代码为准（FAQ Q45）；模块文档"注意事项"里的缺陷标注在代码修复后应删除——这是双向约定。

## 报告与导出

**Q61 TOON 格式给谁用？**
给 LLM 的紧凑表格编码（省 30-60% token）：导出端点、Python TOON 流解析、dump-text 都用它。人读请用各 UI/JSON 导出。

**Q62 报告能改版式吗？**
Markdown/HTML 呈现由前端渲染器决定（web 报告 registry 加渲染器）；生成内容结构（章节）在 ReportGenerator/ForensicReportService 侧改。

**Q63 导出 JSON 的字段以哪为准？**
以 handler 实际返回为准（API 参考的示例标注了"响应要点"）；schema 字段参考 [schema/](schema/FilesDB.md)。

**Q64 多个任务的报告能合并吗？**
走案件（case）路径：多镜像案件分析产出案件级报告（tutorials/KnowledgeGraphReports）。

**Q65 终版报告发布后还能改吗？**
不能——发布带完整性哈希，改动即失效（这正是设计）；要改就发新版本。

## 故障复现

**Q66 怎么复现某个任务的 LLM 结果？**
同提示词重放不可保证（模型温度/端点状态），但可对比输入：files 的内容预算路径与 file_descriptions.model_used 记录了模型与时刻。

**Q67 验收 harness 能用来复现线上问题吗？**
能且推荐——隔离工作区+fake LLM，五个 profile 覆盖主要旅程；见 [AcceptanceHarness](testing/AcceptanceHarness.md)。

**Q68 怎么做最小复现镜像？**
scripts/create_test_image.sh（最小 ext4）或 create_multipartition_image.sh；生成脚本全景见 [TestFixtures](testing/TestFixtures.md)。

**Q69 为什么改日志级别没反应？**
LOG_LEVEL 未接线（FAQ Q5）；当前日志查看走 Monitoring 的三通道。

**Q70 仓库有 CI 吗？**
没有（test-profiles.md 记录）。回归靠本地 make test-all 与验收 profile——贡献者自查清单见 [WritingTests](testing/WritingTests.md)。

---

**最后更新**: 2026-08-24（50 问 + 扩充至 70 问）
