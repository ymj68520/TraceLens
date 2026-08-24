# 阅读路线（按角色）

> 每条路线 6-10 步，顺序即建议阅读序；括号内是预计投入。全部链接均为仓库内文档。

## 取证分析师（用系统，不改系统）

1. [QuickStart](../getting-started/QuickStart.md)——跑通第一个任务（1h）
2. [Overview §1-3](../architecture/Overview.md)——心智模型与两种模式（30m）
3. [IncidentTriage](../tutorials/IncidentTriage.md)——未知镜像初筛决策树（45m）
4. 按场景选一门主教程：[Linux 入侵](../tutorials/LinuxIntrusion.md) / [Windows](../tutorials/WindowsCase.md) / [Android/微信](../tutorials/AndroidWechat.md)（各 1-2h）
5. [SqlCookbook](SqlCookbook.md)——把"看"变成"查"（1h）
6. [schema/ 对应库](../schema/LinuxDB.md)——字段级参考，按需查
7. [KnowledgeGraphReports](../tutorials/KnowledgeGraphReports.md)——图谱与报告出证（1h）
8. [FAQ](../faq.md)——随用随查

## C++ 后端开发者

1. [QuickStart](../getting-started/QuickStart.md) + [Development](../getting-started/Development.md)（1.5h）
2. [Overview](../architecture/Overview.md) + [DataFlow](../architecture/DataFlow.md)——全文（2h）
3. [Concurrency](../architecture/Concurrency.md)——锁/池/看门狗（45m）
4. [HTTPServer](../modules/cpp/network/HTTPServer.md) → [TaskManager](../modules/cpp/network/TaskManager.md) → [TaskInfrastructure](../modules/cpp/network/TaskInfrastructure.md)（3h）
5. 按域选：[ImageAnalyzer](../modules/cpp/analyzers/ImageAnalyzer.md) / [FileClassifier](../modules/cpp/core/FileClassifier.md) / 平台分析器三篇（各 1h）
6. [LLMClient](../modules/cpp/integration/LLMClient.md) + [FileAnalyzer](../modules/cpp/integration/FileAnalyzer.md)（1.5h）
7. [SQLiteHelper](../modules/cpp/network/SQLiteHelper.md) + [schema/](../schema/FilesDB.md)（1h）
8. [WritingTests](../testing/WritingTests.md) + 模块文档的"常见任务配方"（1h）

## Python 服务开发者

1. [Development](../getting-started/Development.md) + 环境（1h）
2. [Overview §2/§5](../architecture/Overview.md)（30m）
3. [httpserver/Main](../modules/python/httpserver/Main.md) → [ServiceManager](../modules/python/httpserver/services/ServiceManager.md)（2h）
4. [CppBackendClient](../modules/python/httpserver/services/CppBackendClient.md) + [ServiceContracts](ServiceContracts.md)（1h）
5. 图谱线：[GraphitiService](../modules/python/services/GraphitiService.md) → [GraphitiIngestor](../modules/python/graphiti_integration/GraphitiIngestor.md) → [TOONTransformer](../modules/python/graphiti_integration/TOONTransformer.md)（3h）
6. 报告/调查线：[ForensicReportService](../modules/python/services/ForensicReportService.md) → [InvestigationService](../modules/python/services/InvestigationService.md)（3h）
7. [TaskStore](../modules/python/services/TaskStore.md)（安全边界，30m）
8. [PythonTestCatalog](../testing/PythonTestCatalog.md) + [WritingTests](../testing/WritingTests.md)（1h）

## 前端开发者

1. [web/Overview](../modules/web/Overview.md)（1h）
2. [web/Pages](../modules/web/Pages.md)——23 页走读（2h）
3. [web/Services](../modules/web/Services.md)——三客户端与映射（1h）
4. [web/Store](../modules/web/Store.md) + [web/Hooks](../modules/web/Hooks.md)（2h）
5. [web/Components](../modules/web/Components.md) + [web/I18nTheming](../modules/web/I18nTheming.md)（1.5h）
6. [EndpointsFlat](EndpointsFlat.md)——后端契约速查（30m）
7. [web/Testing](../modules/web/Testing.md)（45m）

## 运维/部署

1. [ServiceRunbook](../ops/ServiceRunbook.md)（1h）
2. [Installation](../getting-started/Installation.md)——外部服务节（45m）
3. [ExternalServices](../ops/ExternalServices.md) + [LLMOperations](../ops/LLMOperations.md)（2h）
4. [Monitoring](../ops/Monitoring.md)（1h）
5. [DataAndBackup](../ops/DataAndBackup.md) + [UpgradeMigration](../ops/UpgradeMigration.md)（1.5h）
6. [CapacityPlanning](../ops/CapacityPlanning.md) + [PerformanceTuning](../ops/PerformanceTuning.md)（1.5h）
7. [SecurityHardening](../ops/SecurityHardening.md) + [ThreatModel](../architecture/ThreatModel.md)（1.5h）

## 分布式 C/S 管理员

1. [DistributedCS 教程](../tutorials/DistributedCS.md)（1h）
2. [server/Main](../modules/python/server/Main.md) → [server/Services](../modules/python/server/Services.md)（2h）
3. [schema/PostgreSQLCS](../schema/PostgreSQLCS.md)——十表字段级（45m）
4. [HttpAgent](../modules/cpp/http_agent/HttpAgent.md)（1h）
5. [UpgradeMigration](../ops/UpgradeMigration.md) 的 PG 节 + [Monitoring](../ops/Monitoring.md)（1h）

## 测试/质量

1. [CppTestCatalog](../testing/CppTestCatalog.md) + [PythonTestCatalog](../testing/PythonTestCatalog.md)（1.5h）
2. [AcceptanceHarness](../testing/AcceptanceHarness.md)（1h）
3. [TestFixtures](../testing/TestFixtures.md)（30m）
4. [WritingTests](../testing/WritingTests.md) + [test-profiles](../testing/test-profiles.md)（1h）
5. [web/Testing](../modules/web/Testing.md)（45m）

## 架构评审/新人导师

1. [Overview](../architecture/Overview.md) → [DesignDecisions](../architecture/DesignDecisions.md)（2h）
2. [DataFlow](../architecture/DataFlow.md) → [Concurrency](../architecture/Concurrency.md)（2h）
3. [History](../architecture/History.md)——演进与化石决策（1h）
4. [ThreatModel](../architecture/ThreatModel.md) + [Security](../architecture/Security.md)（1.5h）
5. 抽查 3 篇模块文档的"注意事项"——了解已知缺陷面（1h）

---

**最后更新**: 2026-08-24（新建：按角色阅读路线）
