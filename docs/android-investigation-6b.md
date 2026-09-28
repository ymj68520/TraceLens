# 第六阶段 6B：单条 Android 工件研判与报告引用

范围：当前分支的隔离代码与合成数据。本阶段不改 AndroidAnalyzer 解析规则，不把第三方 HTML `records.db` 并入 `android.db`，不迁移生产任务。生产认证/出站阻塞仍以 [6A 记录](android-field-security-6a.md) 为准；真实手机/美亚样本仍为 `REAL_SAMPLE_REQUIRED`。

## 证据语义与生产链

用户在 Android 页面选中**一条**短信/联系人/应用/Wi-Fi 解析记录。详情 GET 返回当前结果库版本 token 与解析行哈希；显式 POST 冻结时服务端重新核对，再用 SQLite Backup API 建立该 Task 的不可变 `android.db` 结果集。若当前行/数据库变更，返回 409；GET 不创建结果集。结果集 manifest 与数据库均用 SHA-256 检查，独立于原始镜像与 HTML 报告 `records.db`。

证据键为 `android_artifact:v1:<task_id>:<result_set_id>:<sms|contacts|apps|wifi>:<解析结果行id>`。同内容的不同行有不同键；同版本重复选中幂等。`investigation.db` v8 以独立 CHECK 存储该类型，不借用 `file:`/`cluster:`，不造 `files.db`/`events.db` 行。v7 的纯 GET 仍只读；写入前的 v7→v8 迁移在单个事务内重建快照表、逐列比较旧行、检查外键并恢复不可变触发器，失败回滚。旧文件/事件证据键、旧快照 JSON 和旧报告输入版本不重写。

冻结快照包含结果集 ID/SHA、解析行 ID/哈希、保守字段投影、候选来源、coverage 和 warning。旧解析器仅给候选来源文件，**没有逐条原库表/主键、WAL frame、磁盘偏移、账号/Android user 和可信时间单位/时区**；这些字段是 null/unknown。即使候选文件有哈希，也不能断言该结果行已绑定该文件。`android.db` 的 `id` 不等于原始短信数据库主键。Wi-Fi 凭据在网页、快照及报告投影中遮盖，`redacted_fields` 明示遮盖字段；记录哈希仍针对派生库原始行。来源回跳是 Task 限定的同一冻结结果集中的**派生行**，不是原库精确行回跳。

单条快照进入已有 Investigation 分析、人工复核和 Report Evidence 判定。Android 分析输入采用 envelope v3 与 `investigation-evidence-analysis:v4`；旧 v1/v2 输入原样可读。最终报告包含 Android 工件时采用 envelope v3 与 `final-report:v3`；这一版本的段落引用可携带显式绑定的 `analysis_id`/`claim_id`，而旧 v2 仍禁止段落引用派生分析。新 citation 仍需通过原有 Evidence 白名单及准确的冻结分析/Claim 绑定校验。报告引用面板深链回该条快照及冻结结果集。无本地模型时确定性查询、冻结、判定和离线包可用，不能声称二次分析或最终报告 LLM 已运行。

现场操作（仅在 6A 已安全切换且检材获准后）：在 Task 的 Android 工件卡片选中一条记录，核对候选来源限制，点“将此单条记录加入调查研判”；工作台显示 result_set_id、record_hash、冻结字段与同版原记录。若现场明确启用获准本地模型和 Workbench LLM 功能开关，分析员在此提交二次分析；审核员在 `review_pending` 决定接受/拒绝，不能由模型自动接受。审核员把该工件判为正文/附件，再在“报告引用的分析版本”中**显式**选择已接受的版本；无绑定时报告只引用工件本身。沿现有最终报告页生成 R2，点击 citation 打开同一 `android_artifact` 键的调查工作台与冻结版本。结果包通过现有操作员 CLI 对该 Task 生成；提供受控 `--report-root` 才会附入 R2 citation 映射。

结果包新增 `selected_android_evidence.json`，含 Task 内已冻结 Android 单条快照、判定、绑定分析版本/复核决定、同版本脱敏记录和来源；按不同结果版本各带一个 `android-result-<result_set_id>.db` 冻结数据库副本，离线验包逐行复算原始派生行哈希（合计上限 2 GiB，不复制镜像）。包清单哈希覆盖这些文件。操作员显式提供可信 `--report-root` 时，`selected_android_citations.json` 汇集该 Task 已就绪 R2 版本的精确 citation 映射；未提供则该映射为空且 warnings 明确说明。打包时复核结果集/行哈希，缺失或篡改则失败。此文件不替代已有报告正文，也不代表包外未知报告版本均已打包。

## 合成回归与界限

固定合成输入：两条内容相同、结果行 ID 不同的短信，号码 `10086`、正文 `同一条短信`、日期原值 `1700000000000`、方向原值 `1`。选中 ID 1 后仅冻结 1 条；ID 2 不自动纳入报告。分析与 R2 使用内存中的 `test-only-mock`，但经过现有执行器、状态机、人工复核、报告证据绑定、R2 发布和 citation 校验；接受后 R2 白名单恰为 ID 1，引用 ID 2 被拒绝，回跳读回同一结果集 ID 1。合成 v7 完整库核对迁移后的快照 ID/JSON、分析/报告绑定、外键与不可变触发器。隔离 HTTP 测试复用 6A 的真实 JWT/角色中间件，验证匿名 401、无权限复核/判定 403、伪造审核人无效、快照与 R2 报告 200、跨 Task 404、选中行失配 409。无头 Chrome 在隔离同源 mock 服务中点击短信→捕获→落到 exact-key Investigation 冻结面板，又打开合成 R2 报告的 `c001`、取得真实渲染的冻结工件链接并跟随它返回同版面板；浏览器里的报告和模型数据仍是 mock，不是现场模型发布。

验证入口：`python_service/tests/unit/investigation/test_android_artifact_report_chain.py`、`python_service/tests/integration/test_android_6b_http.py`、`web/src/utils/evidenceKey.test.js`、`web/src/components/reports/CitationTracebackPanel.test.jsx` 及旧 Investigation/R2/离线包回归。真实本地模型调用、真实镜像适配、账号/原库行精确 provenance 和生产迁移均**未验收**。不得把合成模型响应称为真实 AI 分析。

现场启用前先解决 6A 的生产认证/出站与监听阻塞，确认预检、图谱和报告无在途作业。已有 v7 库的常规写入**不会自动迁移**，而是明确失败关闭；GET 仍可读。操作员在停写维护窗口使用 `scripts/prepare_investigation_v8.py --task-record <经核准的本地 Task JSON> --output-copy <新文件路径>`：脚本用 SQLite Backup API 为指定 Task 生成迁移后的**副本**，核对源 bundle 在备份期间未变化、目标 integrity/FK/user_version 与 SHA-256，拒绝覆盖已有目标；**不替换源库**。先在合成库/授权副本上演练、保存源库及 WAL 的一致性备份与哈希，再由运维批准并实施停机切换。回滚只能在停写后用原备份恢复，不将 v8 新数据塞回 v7；本轮未执行生产切换或真实库迁移。未经授权不得接收新真实检材。

本轮执行前对生产预检作业只读核查：持久作业文件仍标 `running`，当前 8090 查询返回派生状态 `interrupted`；未见可独立证明 owner PID、heartbeat 或终态的字段。因此不能仅由 `interrupted` 推定所有外部执行进程已退出；本轮未更改该作业。生产 8666/8090/8091 仍有 `0.0.0.0` 监听，8666/8090 PID 与 6A 记录相同；`tasks.json` 和 `reports.db` 的 mtime 仍为 2026-09-23 的历史值。这里只证明本轮没有对历史任务/报告执行写操作，不是全量字节哈希证明。

执行记录中的隔离偏差：首次旧前端构建的浏览器冒烟仍使用 Vite 默认 Python `localhost:8090`，可能对既有服务发出合成 Task ID 的只读查询（包括以 POST 实现的搜索）；没有发起捕获、取证、删除或迁移。发现后重新构建为 `VITE_PYTHON_API_URL=/python`，最终无头浏览器验收全部通过随机端口的同源 mock 服务，未把早期冒烟当成隔离验收依据。

验收层级：无模型查询/冻结/结果包为 `PASS_DETERMINISTIC_RECORD_EXPORT`（合成）；隔离 JWT/角色 + 测试替身模型 + HTTP/R2 + 无头浏览器的报告 citation 回跳为 `PASS_SYNTHETIC_RECORD_WORKFLOW`。浏览器未独立执行模型复核和 R2 生成；这些由隔离 HTTP 测试覆盖。真实获准本地模型的服务出站边界未验证，仍是 `LOCAL_MODEL_VALIDATION_REQUIRED`；生产为 `BLOCKED`，LAN TLS 未切换，真实样本为 `REAL_SAMPLE_REQUIRED`。
