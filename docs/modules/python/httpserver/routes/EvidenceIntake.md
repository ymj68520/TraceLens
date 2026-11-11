# EvidenceIntake 路由（python_service/httpserver/routes/evidence_intake.py + raid_task_intake.py，前缀 /api/evidence-intake）

> **一句话**：陌生检材进场前的"有界预检"与进场后的"显式冻结"——candidates/jobs 是对证据收件箱文件的只读格式假设+完整性盘点（后台线程、可取消、产物 NDJSON manifest），android-artifacts/coverage 是 Android 行级数据的读取与"选定行冻结成调查证据"，raid/* 是 RAID 多盘成员重建为任务镜像源的准入与绑定校验；新行内容端点全部 fail-closed 鉴权。

## 1. 这组路由承担什么职责（为什么存在）

两个文件共享一个前缀但分工互补（都挂 `/api/evidence-intake`，main.py:360-362）：

- **evidence_intake.py**（docstring :1："Read-only, bounded preflight jobs for unfamiliar evidence packages"）管"读与冻结"：前半是对证据收件箱（`evidence_inbox`）候选文件的预检作业（格式假设、哈希、清单——绝不解压执行内容，evidence_preflight.py:1-4 docstring），后半是 Android 产物库的行级读取（artifacts/coverage）与**选定行冻结**（capture：把某行连同其 `record_hash`+`source_revision` 冻结成 result set 并捕获为调查证据——行内容可能随后续重解析漂移，冻结行是二次调查的不变基线）。
- **raid_task_intake.py**（docstring :1："RAID image preparation inside the existing task intake namespace"）管 RAID 源：列盘组候选 → 建准备作业（重组校验成员哈希）→ 任务创建时把镜像源**绑定**到某次作业的 manifest，之后任何时刻都能回查绑定是否仍然成立（raid-source 端点四重比对）。

## 2. 典型调用方（前端哪个页面/组件）

- **预检作业**：`web/src/services/evidenceIntakeService.js:6-17`（candidates/start/status/cancel/manifestUrl），消费方是创建任务流的 `components/tasks/EvidencePreflightPanel.jsx`（陌生包先预检再进任务）。
- **RAID**：`components/tasks/RaidImageSource.jsx:3`（"RAID selection is a field in the existing task form, not a new page"）——直调 `/api/evidence-intake/raid`（:5），嵌在 CreateTaskModal 里（CreateTaskModal.raid.test.jsx）。
- **Android 行级读取/冻结**：`evidenceIntakeService.js:19-32`（getAndroidArtifacts/captureAndroidArtifact/getFrozenAndroidArtifact/coverage 下载链接），供调查工作台的证据捕获路径。
- 服务间：capture 经 `get_service_manager().investigation_service`（evidence_intake.py:37）落证据快照——是 investigation 域的上游入口之一。

## 3. 核心数据结构

**预检候选与作业**（services/evidence_preflight.py）：候选 = 收件箱文件的盘点条目（`list_candidates`，:403）；作业目录 `{DATA_ROOT}/.../preflight_jobs/<job_id>/`（`_job_dir`，:440）内 `job.json`（状态）+ `manifest.jsonl`（逐文件 NDJSON 清单）。作业参数（路由 :196-212）：`candidate_id`、`full_hash`（布尔，全量 SHA-256 还是头部抽样）、`password`（≤1024 字符，容器解密尝试）、`selected_slot`（0..31，Android 容器的槽位选择）。状态机经 `start_job/cancel_job`（:702/:741）驱动后台线程，终态 `completed` 或 `partial`（被取消但有部分结果）。

**冻结证据键**（evidence_intake.py:43）：`android_artifact:v1:{task_id}:{result_set_id}:{kind}:{row_id}`——capture 请求体**只允许** `{record_hash, source_revision}` 两键（:30-31，多余缺失都 400）：行必须仍哈希一致且源版本未变才冻结（`freeze_selected_result` 的乐观校验，漂移 → `ArtifactChanged` → 409）。

**RAID 作业与绑定**（services/raid_task_intake.py + 路由 :70-90）：作业含 owner、status、manifest_sha256、image_path、member_sha256 表；任务侧绑定写在 task.metadata（`source_kind=raid`、`raid_job_id`、`requested_by`、`raid_manifest_sha256`）。`raid-source` 端点的四重比对（:79-82）：owner==requested_by、status==ready、manifest_sha256 一致、image_path 一致——任何一条不成立即 `TASK_RAID_SOURCE_BINDING_MISMATCH`。成功响应固定带 `"verification_state": "MACHINE_RECONSTRUCTED_UNVERIFIED"`（:88）——机器重组 ≠ 取证验证，这个措辞是契约的一部分。

## 4. 端点语义分组（散文）

**预检（candidates/jobs）**：`GET /candidates`（:191）、`POST /jobs`（:196，**202**）、`GET /jobs/{id}`（:217）、`POST /jobs/{id}/cancel`（:227）、`GET /jobs/{id}/manifest`（:237）——manifest 仅终态可下载（其余 409 "manifest is not finalized"，:241-242），`FileResponse` NDJSON 附件 + `X-Content-Type-Options: nosniff`（:246-249）。

**Android 行级（artifacts/coverage）**：`GET .../android-artifacts/{kind}`（:98，分页 ≤100）、`POST .../android-artifacts/{kind}/search`（:115，query ≤200 + page 类型严格校验，:121-122）、`GET .../android-artifacts/{kind}/{row_id}`（:134）、`POST .../android-artifacts/{kind}/{row_id}/capture`（:25，冻结，见上）、`GET .../android-result-sets/{rsid}/{kind}/{row_id}`（:60，读已冻结副本而非活库）。coverage 三端点（:150/:159/:175）**不过 field gate**（只暴露计数与 manifest 摘要，无行内容），manifest 两端点以附件下载返回并强制 nosniff。

**RAID（raid_task_intake.py）**：`GET /raid/candidates`（:30，仅需 user 身份）、`POST /raid/jobs`（:37，**202**，body 严格 `{member_ids}`，:40）、`GET /raid/jobs/{id}`（:45，`public(job_id, actor_id)` 按 owner 隔离）、`POST /raid/jobs/{id}/prepare`（:51，**202**，`allow_partial` 仅 admin——部分诊断需要管理员，:58-59）、`POST /raid/jobs/{id}/cancel`（:64）、`GET /tasks/{task_id}/raid-source`（:70，绑定回查，见第 3 节）。

## 5. 数据流（读什么库/服务、写什么）

**写**：预检作业目录（job.json + manifest.jsonl + work/ 预览，evidence_preflight.py:446-463）；RAID 作业状态与重组产物（services/raid_task_intake.py 管理）；capture 写两处——`android_result_sets` 冻结副本（android_result_sets.freeze_selected_result）+ investigation 域证据快照（evidence_intake.py:36-45）。任务侧 RAID 绑定由创建任务流写入 metadata，本组路由只读它。

**读**：收件箱目录候选（`evidence_inbox()`）；任务 Android 产物库（`list_artifacts`/`artifact_detail`，路径只信 `get_task_record` 的任务记录——所有端点第一步都是取任务并验 id 一致，:33-35 等）；冻结副本库（read_frozen_artifact）。

**fail-closed 鉴权门**（`_field_gate`，:78-95）是本组的第二条主线：

```python
# evidence_intake.py:78-95（节选）
policy = getattr(request.app.state, "field_policy", None)
if policy is not None and policy.enabled:
    if getattr(request.state, "principal", None) is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return  # the global field policy already checked this same request
expected = os.environ.get("TRACELENS_FIELD_API_TOKEN", "")
supplied = request.headers.get("x-tracelens-field-token", "")
if len(expected) < 32:
    raise HTTPException(status_code=503, detail="field access is not configured")
if not hmac.compare_digest(expected, supplied):
    raise HTTPException(status_code=401, detail="field access denied")
```

docstring（:79-83）写明边界：它只保护**新的行内容 API**，不追溯保护遗留服务；全局 field 认证开启时走主中间件的 principal（见 [FieldAuth.md](FieldAuth.md)），否则退化为静态 token 比对（长度不足 32 直接 503"未配置"，常量时间比较防时序侧信道）。前端同源演示部署由构建期把令牌注入 bundle（vite.config.js:53-57 的 `VITE_FIELD_API_TOKEN`，由 pythonApi 自动附加）。

## 6. 边界与已知状态（错误码/降级）

- **400/404/409 的分工**：语法/参数问题 400（严格 body、槽位越界 :206-207、搜索参数类型 :121-122）；任务/文件不存在 404（TaskStoreError/FileNotFoundError）；行漂移（ArtifactChanged）与调查库 schema 迁移中（InvestigationMigrationRequiredError）都是 **409**（:48-49、:54-55）——"状态冲突，请刷新后重试"而非错误。
- **503**：capture 时 investigation 存储不可用（EvidenceStoreError/RuntimeError → "investigation capture is unavailable"，:56-57）；field gate 未配置（:92-93）。
- **RAID 的 403 语义**：PermissionError（owner 不符/角色不足）统一 403 "RAID job access denied"，其余 RaidError 400（raid_task_intake.py:25-27）；`allow_partial` 是唯一的角色特权点（admin only，:58-59）。
- 预检作业**重启即丢**：作业状态在文件系统 job.json，但后台线程不跨重启恢复，中断作业停留在旧状态（无 resume 语义）。
- 路由层直接访问 `intake._job_dir`（:243）读 manifest 路径——私有函数跨层使用，属可接受的模块内耦合。

## 7. 如何验证

- 路由层：`python_service/tests/unit/` 下 evidence_intake/raid intake 路由测试（field gate 三态、capture 409、raid 绑定不匹配）。
- 前端契约：`web/src/services/evidenceIntakeService.js`、`components/tasks/EvidencePreflightPanel.test.jsx`、`RaidImageSource.test.jsx`、`CreateTaskModal.raid.test.jsx`。
- 活体验证：往收件箱放一个包 → 创建任务流里跑预检 → 下载 manifest 核对哈希；对已完成的 Android 任务 capture 一行再改动源库重放 capture 应得 409。

相关阅读：[FieldAuth.md](FieldAuth.md)（全局 field 认证中间件）、[Investigation.md](Investigation.md)（capture 的下游证据域）、services 侧证据预检与 RAID 准入实现（services/evidence_preflight.py、services/raid_task_intake.py）；C++ 侧对应准入在 [TaskManager.md](../../../cpp/network/TaskManager.md) 引用的 AndroidPreflightAdmission/RaidTaskAdmission。

## 8. 二轮深化 A：capture 的乐观并发契约

```python
# evidence_intake.py:30-45（节选）
if set(payload) != {"record_hash", "source_revision"}:
    raise HTTPException(status_code=400, detail="selected row hash and revision required")
...
manifest = await asyncio.to_thread(
    freeze_selected_result, task, kind, row_id,
    expected_row_hash=payload["record_hash"],
    expected_source_revision=payload["source_revision"],
)
key = f"android_artifact:v1:{task_id}:{manifest['result_set_id']}:{kind}:{row_id}"
snapshot = await capture_service.capture(task_id, key)
```

客户端在读取列表时拿到每行的 `record_hash` 与当前 `source_revision`，capture 时原样交回——冻结动作是**带前提条件的 CAS**：服务端只有在校验"这一行仍然是你看到的那一行、且源库没被重写"后才落冻结副本。两个失败面：行内容变了（`ArtifactChanged`，409）或源库 revision 变了（同样 409）。docstring（:28）强调设计取向："Explicit selected-row freeze; no client path or arbitrary evidence key"——证据键由服务端从任务与 result_set 拼出，客户端永远不能指定路径或键，即不存在"冻结任意文件"的滥用面。`investigation_db_path_for_task(task)`（:36）在发布任何结果集**之前**先验证调查库可定位，把失败提前到副作用之前。

**最后更新**: 2026-11-10（新建：证据预检/冻结与 RAID 准入路由文档）
