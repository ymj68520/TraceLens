# OssAnalysis 路由（python_service/httpserver/routes/oss_analysis.py，前缀 /api/forensics/oss/ai）

> **一句话**：Python 侧的 OSS（对象存储）AI 过滤与分析端点——按案情描述用 LLM 从 `oss_objects` 表筛相关对象、启动对象分析作业；端点本身已注册可达，但当前**没有任何活跃调用方**（前端 /oss 页走的是未注册的 C++ 路由，见第 5 节）。

## 1. 这组路由承担什么职责（为什么存在）

C++ 侧解析 OSS 取证数据后需要"哪些对象值得看"的智能筛选与后续 LLM 分析，而 LLM 编排在 Python。oss_analysis.py 把这两个能力暴露在 `/api/forensics/oss/ai` 前缀下（router 自带 prefix，oss_analysis.py:15；main.py:242 无前缀挂载）。设计意图是 C++ 后端做代理转发（前端只认识 C++ 基址），Python 做 AI——但这条链目前两头都断着（第 5 节）。

## 2. 典型调用方（前端哪个页面/组件；如实记录）

- **设计上的调用方**是 C++ 后端：`src/network/HTTPServer/routes/OSSAnalysisRoutes.cpp:232-237、252-257` 的 TODO 注释写明"forward to OSSFilterService.filter_oss_objects() / OSSAnalysisService.analyze_oss_objects()，见 python_service/httpserver/routes/oss_analysis.py"——但这两个 C++ 代理 handler 目前是固定 503 的桩（"Python LLM service not available"），从未实现转发。
- **前端 `/oss` 页**（web/src/routes.jsx:77-78）经 web/src/services/ossService.js 调 `/api/forensics/oss/analyze`、`/analyze/status`、`/objects`、`/logs`、`/summary`、`/stats/*`、`/buckets`（ossService.js:9-60）——注意它用的是 **`api`（C++ 同源基座）而非 `pythonApi`**，且没有任何前端代码调用 `/api/forensics/oss/ai/*`（全仓 grep 无命中）。
- 结论：本组 Python 端点当前**可达但无人调用**。

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 14 节。仅两个端点：

- `POST /api/forensics/oss/ai/filter`（oss_analysis.py:54-88）——入参 task_id/oss_db_path/case_description/可选 bucket/max_objects（1-2000 默认 200）；返回筛选出的 object id 列表、计数与 LLM reasoning。
- `POST /api/forensics/oss/ai/analyze`（:91-123）——入参 task_id/object_ids/oss_db_path/download_dir/model_type（text|vision）；返回 job_id。

两个端点的服务实例通过给 ServiceManager **动态挂私有属性**懒加载（`_get_oss_filter_service`/`_get_oss_analysis_service`，:130-153）——不走 ServiceManager 的正式生命周期，是一个实用主义例外。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

`/filter` 读调用方给的 `oss_db_path` SQLite（**未过 task_store 门控**，与 markitdown/office 族的 D2b 纪律不同——路径直接来自请求体，:70），查询 `SELECT bucket, key, size, last_modified, storage_class FROM oss_objects`（services/oss_filter_service.py:247-249），按实现分流：走流式（:78 `_filter_oss_objects_streaming`）或 legacy（:74）；LLM 判定经 service_manager.llm_service，结论只回对象 id 集合与 reasoning，不写库。

`/analyze` 委托 `OSSAnalysisService.start_analysis`——这是一个**诚实的桩**（oss_analysis_service.py:60-84）：生成 `oss-{uuid}` 形式 job_id、warning 日志标明 stub、内部调同样 stub 的 `analyze_oss_objects`（返回 "OSS analysis service not fully implemented"）。路由契约完整（200 + job_id），作业无进度查询端点、无持久化。

## 5. 边界与已知状态（C++ 链路断裂的完整事实）

这是本组文档必须写清的现状：

1. **C++ 侧 `/api/forensics/oss/*` 整族未注册**。OSSAnalysisRoutes（含非 AI 的 `/api/forensics/oss/analyze`、`/analyze/status` 及 AI 三个桩）只在 `OSSRoutes`/`OSSRoutes_new` 的构造函数里被组装（src/network/HTTPServer/routes/OSSRoutes.cpp:25-27），而这两个聚合类**没有任何地方实例化**——HTTPServer 的路由成员只有 TaskRoutes/ForensicsRoutes/SystemRoutes/SearchRoutes/CaseCRUDRoutes/FilterRoutes 六组（src/network/HTTPServer/HTTPserver.h:91-96）。
2. 因此前端 `/oss` 页的全部请求（经 C++ 基址）拿到的是 404——页面调不通，这不是 Python 侧的问题。
3. 即便 C++ 路由被注册，其 AI 代理 handler 也是固定 503 的 TODO 桩（OSSAnalysisRoutes.cpp:232-237 等），并不会转发到本组 Python 端点。
4. **Python 端点是完整注册且可达的**（main.py:242）：`curl -XPOST :8090/api/forensics/oss/ai/filter` 会真实执行 LLM 过滤；`/ai/analyze` 可达但只返回 stub job_id。
5. 错误语义：两个端点的任何异常统一 500 且 detail 直接 `str(e)`（:86-88、:121-123）——与全局脱敏纪律不符，是已知瑕疵。

## 6. 如何验证

- 本组**没有 Python 单测**（tests/unit 无 oss 相关文件）；前端契约记忆在 `web/src/services/ossService.test.js`（注意其断言的是 C++ 基址路径）。
- 手工验证可达性：`curl -XPOST localhost:8090/api/forensics/oss/ai/filter -d '{"task_id":"t","oss_db_path":"<oss.db>","case_description":"..."}'`（需 llm_service 就绪）。
- 验证 C++ 断链：`curl localhost:8080/api/forensics/oss/objects` → 404；`grep -rn "OSSRoutes" src/` 仅命中 routes/OSSRoutes*.cpp 自身。
- 若要修复 /oss 页：注册 OSSRoutes（或把 ossService.js 切到 pythonApi），再把 C++ AI 桩换成真实转发——Python 侧无需改动。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[LLM.md](LLM.md)（llm_service 的通用分析面）、[CaseAnalysis.md](CaseAnalysis.md)（同为 LLM 编排但活跃在用的端点）。

**最后更新**: 2026-08-23（新建，解释式）
