# 设计决策记录（ADR 摘编）

> 本文把散落在各模块文档里的"为什么"汇总成决策记录（ADR）风格：**背景 → 决策 → 理由与取舍 → 现状**。每条都链接到展开讨论的文档。新成员想理解"这个系统为什么长这样"，从这份清单入手最快。决策按主题分组，组内大致按引入时间排序。

## A. 宏观架构

### ADR-1 三服务拆分（C++ 分析 / Python 智能 / C/S 分发）
- **背景**：取证解析依赖 TSK/hivex/evtx/Xapian 等 C/C++ 生态，而图谱（graphiti-core）、文档转换（markitdown）、内存取证（volatility3）只在 Python 生态有一等支持；两者依赖树几乎不交叉。
- **决策**：拆成 `forensic_analyzer`（:8080）、`httpserver`（:8090）两个本地服务 + 可选的 C/S `server`（:8091），互相只通过 HTTP 通信、互不 spawn，由 run.sh 统一拉起。
- **取舍**：多进程部署/排障复杂度 ↔ 构建解耦、故障域隔离（Python 重启不影响长任务分析）、各自生态最优。
- **现状**：Python 把 C++ 当硬依赖（readiness），C++ 离了 Python 也能完成分析（图谱缺席）。详见 [Overview §2](./Overview.md)。

### ADR-2 分布式采用拉取式轮询而非推送
- **背景**：多取证机场景下，推送需要维护长连接与 NAT 穿透。
- **决策**：agent 轮询 `/api/commands/poll` 领命令、本地执行、回传结果（PG 十表）。
- **取舍**：实时性略差 ↔ 零连接管理、天然穿透。已知缺口：并发领取无 `FOR UPDATE SKIP LOCKED`、`retry_count` 无消费方（[server/Services](../modules/python/server/Services.md)）。

### ADR-3 本地服务无认证 + 前端 mock 登录
- **决策**：本地栈（8080/8090）不设认证，前端 `/login` 为占位交互；认证体系只在 C/S（JWT HS256 + 注册令牌）。
- **理由**：定位单机/内网工作站工具。**后果**：跨机部署必须靠网络隔离，详见 [Security](./Security.md)。

## B. 数据与存储

### ADR-4 SQLite 每任务一组文件，而非中心库
- **决策**：任务产出全部落在 `data/tasks/<task_id>/` 独立目录（raw/events/files/各平台库）。
- **理由**：取证天然"一镜像一世界"——并发隔离、删除即删目录、拷贝归档=文件操作、Python 侧可以 fail-closed 精确匹配任务路径（D2b 数据边界）。
- **代价**：跨任务聚合交给上层（Python 案件分析、Neo4j 图谱）。详见 [DatabaseSchema §1](./DatabaseSchema.md)。

### ADR-5 库间派生关系而非引用关系
- **决策**：raw.db 是唯一事实来源；events/files/平台库都是从它派生的"观点"；库间无外键，靠 inode/path/partition_num 逻辑对齐。
- **理由**：每层可独立重建（重跑分类不必重解析镜像）；schema 演进互不拖累。

### ADR-6 SQL-as-headers（schema 就是代码）
- **决策**：全部建表语句集中 `src/core/DatabaseManager/SQL/` 头文件，分析器引用常量。
- **理由**：改表必须过编译，schema 与消费代码不漂移。代价：新增表要动头文件（这也是好处）。详见 [DatabaseManager](../modules/cpp/core/DatabaseManager.md)。

### ADR-7 files.db 双轨：主表 + 24 张分类表
- **决策**：主 `files` 表（category/llm_*/scene_* 列）为权威，24 张分类表是按类物化的查询副本（模板建表、无 llm 列）。
- **理由**：前端"给我所有 Databases"变成单表扫描；主表保证任意维度的过滤（LLM/场景）不必跨 24 表 UNION。详见 [FileClassifier](../modules/cpp/core/FileClassifier.md)。

### ADR-8 raw.db 不可变 + `_filtered.db` 副本
- **决策**：过滤画像产出**新文件**而非原库 DELETE；下游切到 effectiveRawDb。
- **理由**：保住"事实来源"完整性，换画像重跑零成本。边界：画像全灭时回退全量并告警（宁可全量不产空结果）。详见 [FileFilter](../modules/cpp/core/FileFilter.md)、[DataFlow 第三幕](./DataFlow.md)。

### ADR-9 无版本迁移，"探测 + ALTER"自愈
- **决策**：SQLite 侧不做版本号迁移，代码打开库时探测缺列（如 llm_*/scene_*）并 ALTER 补齐。
- **现状**：comprehensive 时间线路径会顺手补 6 个 LLM 列（[SQLiteHelper](../modules/cpp/network/SQLiteHelper.md)）——注意自愈只在部分路径触发。C/S PG 侧有正经迁移文件但只自动应用 001（[UpgradeMigration](../ops/UpgradeMigration.md)）。

### ADR-10 审计独立于任务
- **决策**：`forensics_audit.db` 全局单库（WAL/写缓冲/LRU），不属于任何任务目录。
- **理由**：任务可删，审计不可删。已知缺口：轮转/保留函数实现了但无调用方，且库落 CWD（[AuditLog](../modules/cpp/core/AuditLog.md)）。

## C. 流水线

### ADR-11 场景检测先于过滤
- **决策**：SceneDetector 必须跑在 FileFilter 之前（读未过滤的 raw.db）。
- **理由**：过滤画像的职责恰是丢"系统噪音"，而场景特征路径就是系统路径——先过滤再检测等于自毁证据（TMA:227 注释原文）。检测写 SCENE_DETECTED 审计（含命中计数）保证可复核。

### ADR-12 协作式取消 + 双阈值看门狗
- **决策**：取消=置原子标志、阶段边界检查，不强杀；看门狗 1 秒一跳，RUNNING/PENDING 各 30 分钟无进展判 FAILED。
- **理由**：强杀 SQLite 写事务会留半页；"诚实汇报进度的大任务不被误杀"。代价：阶段内部不可中断。详见 [Concurrency §2.3](./Concurrency.md)。

### ADR-13 Graphiti 触发是 fire-and-forget
- **决策**：任务收尾时 `async_ingest` 只提交作业即返回，try/catch 吞异常，job id 落 tasks.json。
- **理由**：分析成功不因图谱缺席而失败——故障域分离。代价：图谱缺席要用户在知识图谱页主动发现。详见 [DataFlow 第六幕](./DataFlow.md)。

### ADR-14 进度=加权累计（5/25/10/15/20/20/3/2）
- **决策**：`calculate_overall_percentage` 用 map 有序遍历做"已完成整份+当前按比例"。
- **理由**：实现简单且单调；FILE_CARVING 只占 3% 是体感设计（可选尾部步骤）。详见 [TaskManager](../modules/cpp/network/TaskManager.md)。

## D. LLM 与图谱

### ADR-15 LLM 三层分工（文件级/工件级/簇级）
- **决策**：文件级（LLMAnalysisService，成本低、SMART 粗选）、工件级（平台 LLM 服务，上下文干净、求准确）、簇级（EventClusterAnalyzer，求叙事）。
- **理由**：不同层信息密度不同，一层通吃做不了成本/准确/叙事三角取舍。详见 [Overview §5](./Overview.md)。

### ADR-16 SMART 模式（先粗选再精析）
- **决策**：smart 模式先让模型选重要文件（四道防线：$ 条目剔除/启发式排序限 48000 字符/三重回退/垃圾路径拒收）再逐个精析。
- **理由**：成本与覆盖的旋钮。详见 [LLMAnalysisService](../modules/cpp/network/LLMAnalysisService.md)。

### ADR-17 Graphiti 放 Python + 任务隔离图谱
- **决策**：图谱摄取/查询全在 Python（graphiti-core 生态），group_id=task_id 实现任务隔离，跨任务实体合并由 EntityRelationBuilder/MigrationManager 负责。
- **理由**：生态绑定 + 多任务数据不串。

### ADR-18 FORENSIC_EXTRACTION_INSTRUCTIONS + EpisodeType.text 渲染
- **背景**：Graphiti 默认抽取提示词**主动丢弃**日期/哈希/IP/路径——取证图谱近乎为空的根因。
- **决策**：注入定制抽取指令点名取证实体类型；episode 从 JSON 渲染成 `Field: value` 文本并按 text（而非 json）摄取以走宽松的 extract_text。
- **详见**：[GraphitiIngestor](../modules/python/graphiti_integration/GraphitiIngestor.md)——这是图谱质量的两个灵魂补丁。

### ADR-19 llm_patch 前置导入
- **决策**：monkey-patch `OpenAIGenericClient._generate_response` 清洗 `<think>`/围栏，必须在任何 graphiti_core 导入之前 import。
- **理由**：qwen3/deepseek-r1 本地模型的兼容问题在层内一次性解决，而非每个调用方自己处理。这是部署时最容易踩的时序坑。

### ADR-20 LLMClient 全局互斥 + 4xx 也重试
- **决策**：C++ LLM 客户端 get/post 用一把互斥串行化；重试覆盖 4xx。
- **理由**：本地单槽端点（LM Studio）下的自我保护。**后果**：批量"并发"实际串行；多槽端点时这是首要重审点（[Concurrency §2.5](./Concurrency.md)）。

## E. 接口与前端

### ADR-21 ApiResponse 封装只给 FilterRoutes
- **现状**：统一响应封装定义了（HTTPserver.h:35）但只有 FilterRoutes 采用；其余路由裸 JSON + `{"error":...}`。
- **教训**：半途的标准化——新路由跟随现状（裸 JSON），别误以为封装是通用约定。详见 [FilterRoutes](../modules/cpp/network/routes/FilterRoutes.md)。

### ADR-22 状态字面量双轨（API 小写 / 落盘大写）
- **决策**（事实上的）：REST 序列化输出小写（pending/running…），tasks.json 持久化大写（PENDING/RUNNING…）。
- **后果**：jq 直查与 API 比较必须各用一套——排障高频坑，已录入 [Troubleshooting §13](../getting-started/Troubleshooting.md) 与 [Glossary](../reference/Glossary.md)。

### ADR-23 前端三客户端 + vite 前缀路由
- **决策**：同源 `api`（C++，带 token/401 跳转）、`pythonApi`（:8090 直连）、`csApi`（:8091，独立 token）；开发期按前缀代理（/api/reports|graphiti|llm|office|db|wechat|investigation→8090，/csapi→8091，其余 /api→C++）。
- **已知漂移**：`/api/markitdown` 无专属前缀，dev 下前端直调会落到 /api 兜底打到 C++（[ServiceContracts](../reference/ServiceContracts.md)）。

### ADR-24 C++ 健康检查三口径
- **现状**：`/health`、`/api/health`、`/api/system/health` 并存，语义各异（run.sh 硬检查用最后一个）。新监控接 `/api/system/health`（C++）与 `/health/ready`（Python，C++ 硬依赖+其余可选）。

---

**最后更新**: 2026-08-24（新建：ADR 摘编，24 条决策）
