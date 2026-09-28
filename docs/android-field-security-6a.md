# 第六阶段 6A：现场身份与出站控制

本文件描述**隔离构建中的实现**，不宣称现有生产进程已加载。2026-09-27 执行前：分支 `feature/android-forensics-report-structure`，HEAD `c7f1fc3c0281527fb635773515521ed23960aecc`，工作区已有 196 个变更项。生产进程当时为 8666/C++ PID 1068876、8090/Python PID 1065136、8091/C/S 主进程 PID 467728（worker 会变化），均监听 `0.0.0.0`。C++ health 当时报告 43 个 Task、0 个运行中。预检作业文件有 1 个 `running` 标记，是否活跃不能仅凭文件断定；图谱 Redis 队列与报告库未见运行中项。**本轮未重启这些服务、未导入真实样本、未迁移已有 Task/报告。**切换前必须重新核对，而不是复用这些数字。

## 最小身份模型

现场 systemd 单元固定 `TRACELENS_REQUIRE_FIELD_AUTH=1`；若认证模式变量缺失或拼错，进程拒绝启动，不能回落到旧匿名运行方式。
生产 C++ 单元通过 `UnsetEnvironment` 去掉不需要的用户文件位置和 JWT 签名密钥；只有 Python 身份端需要签发用户 token。两个方向的服务 token 仍按各自调用/验证职责使用，均不得放入前端。

现场模式由 `TRACELENS_FIELD_AUTH=enabled` 显式开启。复用已经安装的开源 PyJWT 与 bcrypt/passlib，不使用旧 C/S 的开发默认密钥或尚未落实权限检查的 `require_permission`。C/S 8091 **不属于单机现场 profile**，其生产实例不由本轮停止。现场用户文件是仓库外、0600 的 JSON；`scripts/field_user_admin.py` 从终端无回显读取口令并保存 bcrypt 哈希，不在参数或前端构建中放密码。三个独立的至少 32 字节高熵凭据分别用于用户 JWT、C++→Python、Python→C++；占位符、重复字符和相同凭据均拒绝。缺配置时现场进程拒绝启动或拒绝受保护访问，不降级为匿名。

登录：前端 `/login` POST 到 Python `/api/field-auth/login`，服务端验证口令并签发 15 分钟 HS256 Bearer JWT。JWT 固定校验算法、`iss=tracelens-field`、`aud=tracelens-api`、`exp/iat/nbf/sub/jti`；每次访问还读用户文件的启用状态、角色和 `token_version`。禁用用户或更新口令/版本即撤销旧 token。前端只把用户 token 留在内存，刷新页面须重新登录；不再生成 `mock_jwt_token`，也不在 `localStorage` 中保留现场 token。用户令牌不等于服务凭据。

C++ 所有 API 先过 Crow 全局中间件，通过仅限 loopback 的 Python `/api/field-auth/introspect` 验签和鉴权；8090 中间件独立验证同一用户 JWT。C++/Python 互调用方向不同的服务 token，且要求 loopback；Python→C++ 仅有 Task/工件的读权限及明确的提取、DLL 分析 POST，不能用服务 token 删除或复核。C++→Python 仅有图谱内部调用、文件分析结果写入和健康检查，不能借此读取报告。客户端的 `X-User`、`X-Forwarded-*` 不构成身份。认证组件断线、JWT 过期、用户被禁用、服务 token 方向错误时拒绝访问。

角色：viewer=只读，analyst=读取与非复核写入，reviewer=analyst+复核/报告证据判定，admin=全部。删除、清理、下载/导出仅 admin。`reviewer`、`added_by`、`updated_by`、`requested_by` 等当前新决策字段在现场模式使用服务端 `current_principal`，不信任客户端同名字段；旧历史记录不重写，保留旧来源语义。此规则是当前单机部署的粗粒度权限，不是多租户隔离；具体资源仍由原有 Task/import 归属和路径边界校验决定。

## 受保护范围与精确例外

从实际 FastAPI router 注册和 CMake 编译的 `CROW_ROUTE` 声明生成的完整清单在 [`field-protected-routes.json`](field-protected-routes.json)，生成器是 [`../scripts/field_route_inventory.py`](../scripts/field_route_inventory.py)。6B 增量后当前清单含 C++ 92 个非 OPTIONS 声明、Python 222 个注册方法（新增单条冻结 POST=`write` 与同版来源 GET=`read`）；全局守卫还覆盖**未列出的** `/api/*`，所以新增接口不会默认为匿名。C++/Python 均不注册 WebSocket 路由；Python 日志 SSE 和数据库流式下载同样经过 HTTP 中间件，前端在现场模式使用带 Bearer 的 `fetch` 流，不依赖不能附加 Authorization 的原生 EventSource。前端旧未注册的 WebSocket 连接在现场模式禁用。

匿名例外仅：C++/Python `GET /health/live` 固定返回 `{"status":"alive"}`；Python `POST /api/field-auth/login` 只验证提交的凭据；`OPTIONS` 仅由 CORS/协议处理且不返回业务数据；C++ 仅从 `web/dist` 边界内提供静态 SPA 文件。`POST /api/field-auth/introspect` 不是匿名例外，要求 C++ 服务 token+loopback。旧 `/api/system/health`、Task/文件/搜索/报告、配置、日志、图谱和模型接口均需认证。未知 `/api/*` 不再回退为返回 200 的 SPA 页面。报告原页继续由既有 import root 与页哈希校验，登录不会赋予任意本机路径读取能力。

没有 Cookie 会话，故本轮没有 Cookie CSRF 例外；使用 Bearer header，浏览器不自动附带。前端与 Python 在 HTTPS 网关下同源 `/python`；示例 Nginx 配置明确剥离客户端送来的服务身份头。后端即使被直接访问，也必须认证。C++ 静态页的 CSP 禁止外部脚本/连接、frame/object；Python 的原始报告安全文本视图使用更严格的 CSP。二者都设置 nosniff/no-referrer。**配置模板不是已部署的代理。**

## 现场出站策略

`FIELD_OUTBOUND_POLICY=disabled`：不初始化 Python LLM/Graphiti/embedding/摄取管理器，不恢复此前队列；C++ Task 的 LLM 标志降为 false 并记录策略，自动 Graphiti 步骤被跳过，C++ 配置读出的模型 URL 为空；网络能力不明的 `server_cloud` Task 被拒绝，图谱/LLM/OSS 网络入口返回 503。确定性 Android 解析、受保护查询与离线打包仍可运行。字段中的文字只当数据，不能改变策略。

`local_only`：模型源需明确列出 `FIELD_MODEL_ORIGINS=http://127.0.0.1:<port>`；配置的 LLM/文字/视觉/embedding origin 必须逐一匹配，不接受 DNS 名、用户信息、通配符或代理环境变量。C++ 与 Python 启动检查都拒绝未授权端点；服务端响应重定向不被用于认证；系统级 `IPAddressDeny=any` 阻止模型调用直接跳公网。**但本地模型服务自身可能充当公网代理**：在其服务进程、版本、用途和出站约束另行核验前，检查器仍报 `LOCAL_MODEL_SERVICE_EGRESS_UNVERIFIED`，不能把 local_only 当已通过现场验收。

部署模板在 [`../deploy/field/`](../deploy/field/field.env.example)：两服务绑定 `127.0.0.1`，不启动 8091；systemd 对两个进程分别设置 `IPAddressDeny=any`、`IPAddressAllow=localhost`，不改全机防火墙或管理网络。当前 WSL 的**受控合成标记测试**：普通进程可达本机非 loopback 地址；带相同 systemd 限制的临时单元仍可达 127.0.0.1，但访问相同标记的非 loopback 地址失败。这说明当前内核机制实际生效；**生产进程不在这些新单元中**，生产状态仍是 `OS_EGRESS_ENFORCEMENT_UNVERIFIED`。一个外网地址恰好不通不是上述测试依据。

## 操作、验收与回滚

### 本轮隔离结果（非生产）

在临时数据目录、随机 127.0.0.1 端口与两个临时 systemd 单元中运行 [`test_field_security_e2e.py`](../tests/integration/test_field_security_e2e.py)：旧 C++ Task、文件/搜索和 Python 报告/调查入口匿名为 401；合法用户读取及合成日志 SSE 为 200；分析员删除、复核和导出为 403；两个方向的服务认证为 200，方向错误令牌为 401；随机端口无 IPv6 监听。主动停止隔离身份服务后，C++ 对原先有效的用户 token 返回 503，未放行。`disabled` 下图谱摄取入口 503，但合成 Android 目录任务仍解析出短信 2、联系人 1、应用 1、Wi-Fi 1，SQLite 一致性结果包可校验；合成 HTML 报告得到 1 条派生记录，可带用户令牌读详情并回跳安全来源页。实际单元属性与受控标记出站测试均通过，`android_field_check.py` 对**隔离实例**返回 `PASS_SECURITY_BASELINE`。无头浏览器在 mock 数据下完成现场登录与 Android 页面渲染，未替代真实后端认证测试。

同一代码在未加 systemd 出站约束的隔离进程中只得到 `BLOCKED`，表明代码自检不会把“写了 unit 模板”当成系统出站已经生效。现有 8666/8090/8091 生产进程未重启且仍是旧监听；对它们的判定继续为 `BLOCKED`，不是 `PASS_SECURITY_BASELINE`，也不是对真实美亚检材的授权。

生产只读复核：本轮结束前 C++ health 仍报告 43 个 Task、0 个运行中、17 个失败；预检状态计数仍为 completed 1 / running 1 / partial 1，图谱 completed 32 / failed 22，报告生成 completed 12 / failed 6。生产 `tasks.json` 与 `reports.db` 的 mtime 分别仍在 2026-09-23 15:02/15:53（北京时间），早于本轮；这支持“本轮未改动历史 Task/报告”，但不是对全部检材逐字节哈希的证明。预检 `running` 文件不等于作业仍活跃，切换前须再次核实。

### 现场操作与回滚

1. 在隔离主机复制 `field.env.example` 到仓库外 `/etc/tracelens/field.env`，权限 0600，替换三个占位符为独立随机值，按实际目录设置 `DATA_DIR`；用 `field_user_admin.py --create --file ... --username ... --role admin` 建立首个账号。不要将密钥放入 `VITE_*`、Git、普通日志或公开 CI。单机可先使用 loopback；LAN 必须先确定 TLS、Windows/WSL 转发、受控反代及现有任务安全切换计划。
2. 从源码构建 C++ 与前端；现场前端构建设置 `VITE_FIELD_AUTH=enabled VITE_PYTHON_API_URL=/python`。静态 Nginx 示例需经批准证书和地址后安装，不得直接照搬占位符。后端直接端口仍是有认证的 loopback，不可信代理头不会被当成用户。
3. 用合成 Task/import、隔离端口运行 `tests/integration/test_field_security_e2e.py`；`scripts/android_field_check.py --env-file ... --username ...` 会无回显提示密码，再检查运行 PID、监听、匿名/无效/过期/合法用户、内部调用和实际 systemd 单元限制。`PASS_SECURITY_BASELINE` **只代表这组检查通过**，不代表全面渗透审计或真实 Android 样本已验证。缺实际运行验证、生产尚未切换时为 `DEPLOYMENT_PENDING`；当前生产仍是 `BLOCKED`。
4. 生产切换前重新核对 C++ Task、Python 预检作业、图谱摄取和报告生成作业。若有在途作业，**不强制重启**；先保留旧服务并阻止新敏感检材准入。切换及回滚均先阻断外部入口、核查进程与数据目录，再逐个操作对应 field unit；不得删除/迁移旧 Task、报告或检材。需要回滚时停用新入口和 field unit、保留其隔离数据，再由管理员决定是否恢复旧二进制；不得让匿名旧端口重新暴露到 LAN。

现阶段真实样本仍为 `REAL_SAMPLE_REQUIRED`。本轮不增加镜像格式、不改变 Android parser 或原有调查数据库语义。

## 尚未解除的现场阻塞

| 状态 | 原因 |
| --- | --- |
| `BLOCKED`（生产） | 8666/8090/8091 旧进程仍对外监听，匿名旧 API 可读；未加载本轮构建，也未套用 field systemd 出站策略。不能把隔离实例的 PASS 套给生产。 |
| `DEPLOYMENT_PENDING` | 生产切换前需核实预检 `running` 状态是否有在途工作；未确认前不重启。LAN 的 HTTPS 证书、反向代理、Windows/WSL 转发和外部防火墙范围尚未部署与验证。 |
| `LOCAL_MODEL_SERVICE_EGRESS_UNVERIFIED` | `local_only` 配置仅限制请求目标为显式数字 loopback；本地模型服务自身可能继续代理/转发，须单独审计与约束其进程出站。当前只验收 `disabled`。 |
| `REAL_SAMPLE_REQUIRED` | 无项目方授权原始 Android 镜像；本轮没有触碰已有真实检材或把第三方 HTML 报告当原始镜像。 |
