# OSSRoutes（src/network/HTTPServer/routes/OSSRoutes.cpp 及 OSSAnalysisRoutes/OSSQueryRoutes/OSSStatsRoutes）

> **⚠️ 未注册：运行时 404。** `HTTPServer` 只构造了六个路由聚合器（TaskRoutes/ForensicsRoutes/SystemRoutes/SearchRoutes/CaseCRUDRoutes/FilterRoutes，HTTPserver.cpp:63-75），**从未实例化 OSSRoutes**——本组定义的 `/api/forensics/oss/*` 端点在运行时全部未注册，请求一律 404。前端 /oss 页（OSS.jsx）因此调不通，这不是部署问题，是代码现状。

## 1. 这组路由（本应）承担什么

按代码意图，它规划了阿里云 OSS（对象存储）取证的完整 REST 面：analyze（启动分析作业）、objects/logs（查询分析结果）、summary/stats/*（统计）、ai/filter、ai/analyze（Python 服务协作的 AI 分析）、download（对象下载）。

## 2. 为什么是死代码：历史与证据

一系列 TODO 注释还原了时间线：OSSAnalysisRoutes.cpp:232-235 写着 "TODO: Integrate with Python service ... Implementation Plan: Tasks 8-11"、:271-279 写着 "Task 6 (C++ Backend - Download Endpoint)"。可以判断：当时按实施计划先写了**路由骨架**（含 Swagger 注册），等 OSSClient 与 Python 侧能力就绪后再接线；但聚合器从未被挂进 HTTPServer 的构造列表，后续真实的 server/cloud 场景走了完全不同的路径（见 §5），这组骨架就永远停在了"已编译、未注册"状态。

即便手动注册，多数端点也拿不到真数据（见 §3）——**双层未完成**。

## 3. 端点分组与"如果调用会怎样"

> 完整端点清单见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。下表是语义 + 实际实现状态。

| 组 | 端点（/api/forensics/oss/...） | 设计语义 | 实现现状（假设已注册） |
|---|---|---|---|
| 聚合器 | — | 组合三个子路由（OSSRoutes.cpp:23-28） | 从未被 HTTPServer 构造 → **运行时 404** |
| 分析 | POST analyze、GET analyze/status | 后台 OSS 分析作业 | 占位实现：起线程睡 100ms 即"完成"，status 恒回 completed（OSSAnalysisRoutes.cpp:222-229） |
| AI | POST ai/filter、ai/analyze，GET ai/status | 转发 Python 服务 | 恒 503 "Python LLM service not available"（:231-269、:296-319） |
| 下载 | POST download | OSSClient 下载对象 | 恒 501 "not yet implemented"（:271-294） |
| 查询 | GET objects、GET logs | 查分析产物 | 恒返回空数组占位（OSSQueryRoutes.cpp:54-65、:94-105） |
| 统计 | GET summary、stats/storage-class、stats/extensions、buckets | 汇总统计 | 恒返回全零占位（OSSStatsRoutes.cpp:75-80+） |

## 4. 典型调用方（标注：调不通）

- **/oss 页（OSS.jsx）**：设计上的消费者，当前所有请求 404——**该页面在现版本不可用，属已知状态**。
- Swagger/OpenAPI 文档：各端点构造时注册过 Swagger 元数据，openapi.json 里可能出现这些路径，**文档里有 ≠ 运行时可用**，自动化客户端勿据此生成调用。

## 5. 数据本来要从哪来（以及现在 OSS 数据的真实去向）

设计上 objects/logs/summary 查询的应是某个 OSS 分析产出库；但真实的 server/cloud 取证路径与此无关：

- 任务选 `server_cloud` 场景时，TaskManager 在 PLATFORM_ANALYSIS 阶段调 **LinuxFilesAnalyzer::analyzeServerCloudArtifacts**，产出写进任务目录的 `_oss.db`（TaskManagerAnalysis.cpp:502-517）；
- 该库经 ForensicsRoutes 族的通用查询（statistics/files 等）即可访问。

即：**OSS/云场景的分析能力活在任务流水线里，这组 REST 骨架从未接上它**。

## 6. 常见错误与边界（现状下的正确预期）

- 调 `/api/forensics/oss/*` 得到 Crow 的 404——不是任务不存在、不是权限问题；
- 前端 OSS 页报网络错误，根因同上；
- 不要因为 Swagger/openapi.json 里出现这些路径就认为可用（§4）；
- `OSSRoutes_new.cpp/h`（14 行）是另一层遗留残骸，同样未使用。

## 7. 处置建议（如何"复活"或了断）

- **复活**：实现 OSSAnalysisRoutes 的真实作业 → 把产出写入任务 `_oss.db` → 在 HTTPserver.cpp:63-75 初始化列表加 `oss_routes_(app_)` 一行；Swagger 注册已就绪。
- **了断**：删除 OSSRoutes/OSSAnalysisRoutes/OSSQueryRoutes/OSSStatsRoutes/OSSRoutes_new 及前端 /oss 页入口，避免后来者反复踩坑；server/cloud 场景继续走 LinuxFilesAnalyzer 路径（本仓库已有文档口径：分析器在流水线中活跃）。

**最后更新**: 2026-08-23（解释式重写）
