# SystemRoutes（src/network/HTTPServer/routes/SystemRoutes.cpp 及 SystemHealth/SystemInfo/SystemDocs）

> **职责**：运维与自描述面——健康检查（存活/就绪/依赖）、系统与数据库信息、日志查看、结果导出触发，以及把本服务自己的 API 文档（Swagger 注册表 + OpenAPI JSON）伺服出去。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

三个受众三种需求：**监控/编排系统**要探活与健康信号（部署探针、告警）；**运维**要看有哪些库、多大、日志说了什么；**前后端开发者**要一份活的端点清单（/api/docs UI 与 openapi.json）。注意这组路由里挂着一个"异类"——`POST /api/export/{task_id}`（结果导出触发）在 SystemInfoRoutes 里注册，属于历史归位问题而非语义归属。

## 2. 典型调用方

- **K8s/负载均衡探针**：/api/health/live（存活）、/api/health/ready（就绪）；
- **Dashboard/监控面板**：/api/system/health 的任务统计摘要（total/running/failed）；
- **设置页/调试**：/api/system/info（能力自述）、/api/system/databases、/api/system/logs；
- **开发联调**：/api/docs（文档 UI）、/api/docs/openapi.json（代码生成/Postman 导入）。

## 3. 端点分组与语义

### 3.1 聚合结构

`SystemRoutes` 构造函数组合 SystemHealthRoutes + SystemInfoRoutes + SystemDocsRoutes 三个子路由（SystemRoutes.cpp:8-13），自身零逻辑——是新增路由组时最简的模仿模板。

### 3.2 健康检查组（SystemHealthRoutes.cpp:13-31）

- `/api/system/health` 与 `/api/health`（同义双路径）：聚合 TaskManager 统计的"富健康"视图——status/version/task_management（total/running/failed/system_load）/services 清单（SystemHealthRoutes.cpp:34-62）；
- `/api/health/live`：纯存活，不做任何依赖检查（:64-77）——探针快速失败用；
- `/api/health/ready` 与 `/api/health/dependencies`：就绪与依赖细节，检查会涉及下游（Python 服务等）可达性。

语义分工是标准 K8s 套路：live 判"进程要不要重启"，ready 判"能不能接流量"。

### 3.3 系统信息组（SystemInfoRoutes.cpp:11-29）

- `/api/system/info`：静态能力自述（名称/版本/特性列表/支持镜像格式，:32-63）——**硬编码 JSON**，加新能力要改代码；
- `/api/system/databases?task_id=`：列出该任务产出库及文件大小（:65-100+），无 task_id 时列全局可见库；
- `/api/system/database-schema/<db_type>`：按类型返回表结构说明；
- `/api/system/logs`：读服务日志；
- `POST /api/export/<task_id>`：触发该任务结果导出（挂在 info 组属历史位置）。

### 3.4 文档组（SystemDocsRoutes.cpp:10-24）

四个端点：`/api/docs/endpoints`（**手写维护的端点清单 JSON**，:27-60+）、`/api/docs/database-schema`、`/api/docs/openapi.json`、`/api/docs`（简易 UI 页）。要区分两份"文档事实"：Swagger 单例注册表（各路由构造时 RegisterEndpoint 喂入，openapi.json 由此生成，**与代码同步**）与 endpoints 端点里的手写清单（**会过时**）——优先信前者。

## 4. 数据从哪来

- 健康统计：`TaskManager::get_task_statistics()`（内存态，源头 data/tasks.json）；
- databases：`AnalysisTask` 的 output_*_db 字段 + `std::filesystem::file_size`；
- logs：日志文件（PathManager 的 logs 目录）；
- docs：Swagger 注册表（内存）/ 手写 JSON 常量；
- 本组**不查任何业务 SQLite 表**（导出触发端点内部另行调用导出逻辑）。

## 5. 常见错误与边界

- **health 的 "healthy" 近乎无条件**：handle_system_health 只要 TaskManager 统计不抛异常就返回 healthy，running 任务很多也不会变 degraded——告警策略别指望它分级；
- **version 硬编码 "1.0.0"**：与构建版本无联动；
- **info 的特性清单会漂移**：新增能力忘了改就误导调用方；
- **endpoints 手写清单与真实路由可能不一致**：以 openapi.json/Swagger 注册表为准；
- **dependencies 检查的超时**：Python 服务慢时 ready 探针可能抖动，编排层需配容忍。

## 6. 如何验证与扩展

- 冒烟：`curl /api/health/live` 秒回 alive；`curl /api/system/health | jq .task_management`；`curl /api/docs/openapi.json | jq '.paths | keys | length'` 对比 RouteReference.md 的端点数；
- 扩展：健康维度（如磁盘水位、线程池队列长度）加在 SystemHealthRoutes 并考虑让 status 出现 degraded 档位；新路由组照抄 SystemRoutes.cpp:8-13 的三行聚合模式。

**最后更新**: 2026-08-23（解释式重写）
