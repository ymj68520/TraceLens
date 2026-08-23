# FilterRoutes（src/network/HTTPServer/routes/FilterRoutes.cpp）

> **职责**：文件过滤画像的 REST 管理面——列出/查看/创建/删除 `config/filter_profiles/` 下的 JSON 画像，以及手动把某画像应用到某个任务的 raw.db（`POST /api/filter/apply`）。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。
> **特殊性**：这组路由是**全服务唯一**使用统一 `ApiResponse` 封装（`{success, message, data, timestamp, pagination, error_code}`）的路由——响应形状与其它所有路由不同。

## 1. 这组路由承担什么

[FileFilter](../../../cpp/core/FileFilter.md) 的画像原本只能靠改文件；本组路由把它变成可运营能力：前端"过滤画像编辑器"（web/src/components/filters/FilterProfileEditor.jsx、ScenarioPicker 等，经 redux filterSlice → services/filterService.js）可以列内置画像、查看规则细节、保存自定义画像、删除自定义画像；`/api/filter/apply` 则提供"对已完成任务的 raw.db 重放一个画像"的手动入口。

## 2. 典型调用方

- **前端过滤组件**：`web/src/services/filterService.js` 封装了全部 5 个端点（fetchFilterProfiles / fetchFilterProfileDetail / createFilterProfile / deleteFilterProfile / applyFilter），消费方是任务创建流程里的画像/场景选择组件（components/filters/*）；
- **脚本/运维**：画像即 JSON 文件，REST 与手工编辑等效——CI 里可以用 POST 固化标准画像。

## 3. 端点分组与语义

### 3.1 画像 CRUD（4 条）

- `GET /api/filter/profiles`：枚举目录内 .json（FileFilter::listProfiles，坏画像跳过），返回 `{filename, name, description}[]` + count（FilterRoutes.cpp:98-133）；
- `GET /api/filter/profiles/{name}`：读单画像，回显 include/exclude 条件与 combine_mode（:139-180）；
- `POST /api/filter/profiles`：upsert 语义——文件已存在则 200 "Profile updated"，否则 201 "Profile created"（:245-312 的 is_update 分支）；服务端重建完整画像 JSON（缺省值兜底）后 pretty-dump 落盘；
- `DELETE /api/filter/profiles/{name}`：删文件；内置画像拒绝删除（403 FORBIDDEN）。

**内置画像保护**：`general_forensics / telecom_fraud / data_breach / virus_intrusion` 四个名字在 POST（覆盖，:225-239）与 DELETE（:365-379）两处硬编码拒绝——它们是流水线默认值的依赖（AnalysisOrchestrator 默认 general_forensics），被删/被改坏会伤及所有未指定画像的任务。

**路径安全**：`isValidProfileName`（:17-23）拒绝空名、`..`、`/`、`\`、NUL——防目录穿越读/写任意文件，所有接受名字的端点都先过这道闸。

### 3.2 手动应用（1 条）

`POST /api/filter/apply`（:398-440）：body `{task_id, profile_name}` → 查 TaskManager 拿 `task.output_raw_db` → 按 `_raw.db → _filtered.db` 命名规则生成目标路径 → `FileFilter::applyFilterByName` → 返回 total/included/excluded 计数与 filtered_db 路径。任务或 raw.db 不存在分别 404（NOT_FOUND / DB_NOT_FOUND）。

### 3.3 ApiResponse 封装：只有这组在用

`ApiResponse` 定义在 HTTPserver.h:35-64（实现 HTTPserver.cpp:20-59）：统一 `{success, message, data, timestamp, pagination, error_code}` 骨架、`create_success/create_error` 工厂。全库检索它的使用面：**仅 FilterRoutes.cpp**（加上定义处的 HTTPserver）——其余路由（Task/Case/Search/Forensics…）各自手拼响应体。这是一次"统一响应格式"的试验性落地，尚未推广。后果两面：写客户端时 Filter 组可以统一解包（error_code 机器可读，如 VALIDATION_ERROR / FORBIDDEN / NOT_FOUND）；但也意味着**同一服务两套响应形状并存**，通用错误处理代码要兼容两种。

## 4. 数据从哪来

- 画像列表/内容：直接读 `config/filter_profiles/*.json`（getProfilesDirectory 的多候选探测，:498-515；与 FileFilter::findProfilesDirectory 类似但候选更少）；
- apply：TaskManager 内存态取 output_raw_db → FileFilter 同步跑（大库时这个 POST 会长时间阻塞，无异步 job）→ 只产 filtered.db 副本。

## 5. 常见错误与边界

- **apply 不回写任务字段**：手动 apply 生成的 `_filtered.db` **不会**替换 `task.output_raw_db`（对比流水线路径 TaskManagerAnalysis.cpp:291-297 会替换）——已完成的任务继续以 raw.db 为结果库；filtered.db 只是摆在旁边的一份副本。指望"apply 后任务结果就变了"是常见误解。
- **apply 是同步阻塞的**：几十万文件的库过滤要几十秒，HTTP 超时/网关超时风险自担；没有 job/进度查询端点。
- **pagination 字段恒为 null**：ApiResponse 有这个字段但 FilterRoutes 从不填——解包时别假设它有值。
- **POST 的 exclude 条件丢字段**：服务端重建画像时 exclude 分支只保留 extensions/path_patterns/filename_patterns 三项（:282-294），不带 min_size/max_size/include_deleted/include_allocated（include 分支 :258-278 带全）——通过 REST 写"exclude 大于某尺寸"的画像会被静默降配，直接改文件才保得住。**已知不一致**。
- **目录找不到时行为分裂**：列表/详情/删除返回 500 DIR_NOT_FOUND；创建则退而创建相对路径 `config/filter_profiles`（:240-243，取决于服务 CWD）。
- **内置画像清单两处硬编码**（POST 与 DELETE 各一份），加第五个内置画像要改两处 + config 目录三处同步。

## 6. 如何验证与扩展

- 冒烟：`curl :8080/api/filter/profiles | jq .data.count`（应为 4+）；POST 一个自定义画像 → 确认 201 与文件落盘 → POST 同名再确认 200（update）→ DELETE 后 GET 应 404；`curl -X POST :8080/api/filter/apply -d '{"task_id":"<id>","profile_name":"telecom_fraud"}'` 核对计数与任务 output_raw_db 未变。
- 扩展：新匹配维度（如 mtime）需 FileFilter 与本路由的 jsonToCondition/conditionToJson（:532-555）同步；若 ApiResponse 要推广到其它路由组，注意 timestamp 用的是 `std::ctime` 截断（HTTPserver.cpp:52-55）——非严格 ISO 8601，先修再推。

**最后更新**: 2026-08-23（新建，解释式）
