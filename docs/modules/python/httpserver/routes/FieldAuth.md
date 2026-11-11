# FieldAuth 路由（python_service/httpserver/routes/field_auth.py，前缀 /api/field-auth）

> **一句话**：现场（field）部署的身份小端点——本地登录签发 JWT、回显当前身份、暴露发布指纹状态，以及给 C++ 中间件用的 Bearer 内省；四个端点本身极薄，真正的机制在全局认证中间件（main.py）与 field_security 服务（策略加载、角色权限表、双内部令牌）。

## 1. 这组路由承担什么职责（为什么存在）

现场部署（离线、有真实办案数据）需要最小但完整的认证：用户是谁（登录/身份）、他能做什么（权限）、这个 Python 服务是哪个构建（发布指纹——证据链要求能回答"这台机器跑的是哪个提交"）。field_auth.py 的 docstring（:1）写明定位："Field-only local login and C++ auth introspection endpoints"。四个端点全部围绕 `request.app.state.field_policy` 运转——这份策略由 services/field_security.py 的 `load_policy`（:97-145）在应用启动时从环境变量装配，且**配置错误宁可拒绝启动**（缺密钥/用户文件权限不 owner-only/local_only 模式缺模型白名单/存在代理环境变量都抛 `FieldConfigurationError`）。

与它配套但不属于这组路由的两件事：main.py 的 `field_authentication` 中间件（main.py:169-205，每请求鉴权）与 `field_response_headers` 中间件（:207-219，策略启用时强制安全响应头）。本组路由是它们的"配套门面"：login/introspect 两个端点被中间件显式豁免（:181），否则鸡生蛋问题无解。

## 2. 典型调用方（前端哪个页面/组件）

- **登录与身份**：`web/src/services/fieldSession.js` / `localOperatorSession.js`（现场登录态管理，写本地会话供 pythonApi 附 Bearer）。
- **C++ 侧**：C++ `FieldAuthMiddleware.before_handle`（src/network/HTTPServer/FieldApp.cpp:122 起）对每个用户请求调 `POST /api/field-auth/introspect`（FieldApp.cpp:158-193，httplib POST + `x-tracelens-service-token`）——C++ 从不自行解析用户 JWT，身份真源始终在 Python（FieldApp.h:8-9 注释："The Python field identity service validates signed user JWTs; C++ never trusts X-User or a nonempty Bearer"）。
- **状态探测**：`GET /status` 被现场部署的健康检查/部署校验脚本消费（返回构建指纹与策略开关）。

## 3. 核心数据结构

**FieldPolicy**（field_security.py，`load_policy` 装配）：`enabled`、`jwt_secret`、`cpp_to_python`、`python_to_cpp` 三密钥、`user_file`（owner-only 权限校验，:71-76）、`outbound_mode`（disabled|local_only）、`allowed_model_origins`（:55，模型服务白名单，必须是显式回环 origin 且无凭据，:129-137）、`browser_origin`（单一精确 origin，:118-119）。

**principal**：用户身份 `{"id": username, "role": role, "kind": "user"}`（`principal()` 解析后的形态，:194；`login` 返回的 principal 只有 `{"id","role"}`，:175）或服务身份 `{"id": "cpp-service", "role": "service", "kind": "service"}`（中间件 :189）。角色集合 `ROLES`（admin/analyst/reviewer/…，:167 校验 role 必须 ∈ ROLES）。

**权限判定**（field_security.py:199-206，`required_permission` 是一张方法×路径的决策表）：

| 请求形态 | 所需权限 |
|---|---|
| DELETE 任意路径；路径含 `/delete` `/export` `/download` `/cleanup` | `admin` |
| `/api/reports/evidence` 且非 GET/HEAD | `review` |
| 路径含 `/review` `/accept` `/reject` `/report-evidence` `/publish` 且非 GET | `review` |
| 其余 GET/HEAD | `read` |
| 其余写方法 | `write` |

`authorize`（:209-212）查 `role → permissions` 映射，缺权限抛 `PermissionError`（中间件转 403）。

## 4. 端点语义分组（散文）

- `GET /api/field-auth/status`（field_auth.py:16-23）：无鉴权（中间件只豁免 login/introspect，status 走正常鉴权链——策略启用时需登录后访问）。返回 `FIELD_SECURITY_VERSION`（"6a-v1"）、`RELEASE_ID`/`RELEASE_LAYOUT_VERSION`/`SOURCE_COMMIT`/`SOURCE_TREE_SHA256`（release_info.py），以及 `field_auth` 开关、`required_auth`（`TRACELENS_REQUIRE_FIELD_AUTH=1` 时部署必须启用，field_security.py:99-100）、`outbound_policy`。
- `POST /api/field-auth/login`（:26-34）：**策略未启用时固定 404**（"field login is disabled"，:29-30——普通部署没有登录这个概念）；成功返回 token + principal（field_security.py `login` :157-175，用户文件里 active 且角色合法才签发）；凭据错误/配置错误统一 401，`from None` 掐掉异常链（不泄露是哪种失败，:33-34）。
- `GET /api/field-auth/me`（:37-42）：读中间件写入的 `request.state.principal`，要求 kind=user——服务身份（cpp-service）不算用户，401。
- `POST /api/field-auth/introspect`（:45-62）：**C++ 专用**。先验 `x-tracelens-service-token`（`valid_internal`，direction=cpp_to_python，field_security.py:215-222：策略启用 + 请求方回环 + 常量时间比对三条件缺一不可），失败 401；再对 body 里的 `method`/`path` 做 `principal`+`authorize`，返回 `{"principal": subject}`——即"这个 Bearer 对这个路径有没有权限"的裁决服务。path 校验：必须以 `/` 开头且 ≤2048（:53-54）。

## 5. 数据流（谁读什么、谁写什么）

**写**：无持久化——用户与角色来自 `FIELD_USER_FILE`（JSON，每次读），token 是无状态 JWT。**读**：环境变量 + 用户文件 + `release_info` 构建指纹。

**中间件主链**（main.py:169-205，逐分支）：

```python
# main.py:169-205（节选，中文注释为本文所加）
policy = request.app.state.field_policy
if not policy.enabled: return await call_next(request)      # ① 普通部署全放行
if request.method == "OPTIONS": ...                          # ② 预检放行（真实请求仍过本关）
if path == "/health/live": return JSONResponse(...)          # ③ 存活探针免鉴权
if path in {"/api/field-auth/login", "/api/field-auth/introspect"}: ...  # ④ 自举豁免
service_token = request.headers.get("x-tracelens-service-token", "")
if service_token and valid_internal(policy, service_token, direction="cpp_to_python", peer=peer):
    # ⑤ 内部服务身份：只许三个面——/health、/api/graphiti/*、/api/llm/file-analysis/record
    if not (path == "/health" or path.startswith("/api/graphiti/")
            or path == "/api/llm/file-analysis/record"):
        return JSONResponse(status_code=403, ...)            # 越界即 403 "service scope denied"
    request.state.principal = {"id": "cpp-service", ...}
else:
    subject = principal(policy, request.headers.get("authorization", ""))   # ⑥ 用户 Bearer
    authorize(subject, request.method, path)
    ...
if policy.outbound_mode == "disabled" and (path.startswith("/api/graphiti") or
        path.startswith("/api/llm/") or "oss" in path.lower() or "embedding" in path.lower()):
    return JSONResponse(status_code=503, ...)                # ⑦ 出站关闭时智能服务整体停用
```

`valid_internal`（field_security.py:215-222）的三条件：策略启用、peer 是回环地址、常量时间比对通过——内部令牌永远不走网络上的非回环调用。`audit_actor`（:224-231）是决策侧的配套：field 模式下审计主体**必须**来自已验证 principal（服务身份不算，抛 FieldAuthenticationError），legacy 模式回退请求方传值。

响应头中间件（main.py:207-219）：策略启用时对一切响应加 `nosniff` / `Referrer-Policy: no-referrer` / `X-Frame-Options: DENY` / 锁死 `default-src 'none'` 的 CSP / `Cache-Control: no-store`——证据页面不允许被缓存或嵌入。

## 6. 边界与已知状态（错误码/降级）

- **401 vs 403**：未认证/凭据坏 → 401（带 `WWW-Authenticate: Bearer`，:196-197）；已认证但权限不足 → 403 "insufficient permission"（:198-199）；服务令牌越界 → 403 "service scope denied"（:188）。
- **配置错误即启动失败**：`load_policy` 的所有 `FieldConfigurationError` 在启动期抛出（含"field 模式禁止代理环境变量"，field_security.py:144-145）——不会带病运行成"半认证"状态。
- **status 端点不是公开的**：中间件只豁免 login/introspect，策略启用时未带 Bearer 的 status 请求会 401——它面向的是"已登录的现场操作员核对构建指纹"。
- **503 出站闸**：`FIELD_OUTBOUND_POLICY=disabled` 时 graphiti/llm/oss/embedding 全面 503（:200-204），对应现场"模型必须本地"的合规要求（local_only 模式下 load_policy 已把三个 LLM URL 钉进白名单，:129-137）。
- 全部细节错误原因（哪个密钥坏、哪个用户失效）只进日志/异常链，响应面统一 401/403/404 短句。

## 7. 如何验证

- 服务层：`python_service/tests/unit/` 下 field_security 测试（policy 装配、权限表、valid_internal 三条件、audit_actor 两种模式）；路由测试覆盖 404（未启用）/401/403 三态。
- C++ 侧：FieldApp 相关测试（introspect 调用、service scope 拒绝）。
- 活体验证：`TRACELENS_FIELD_AUTH=enabled` + 三密钥 + 用户文件启动 → 未登录访问任意 API 应 401 → login 换 token → reviewer 角色尝试 DELETE 任务应 403 → C++ 日志确认 introspect 命中；`GET /api/field-auth/status` 核对 SOURCE_COMMIT 与实际构建一致。

相关阅读：[EvidenceIntake.md](EvidenceIntake.md)（`_field_gate` 的行级静态令牌退化路径）、[Investigation.md](Investigation.md)（audit_actor 的使用方）、C++ 侧 [FieldApp.md](../../../cpp/network/FieldApp.md)（同一条信任链的 C++ 半边）。

## 8. 二轮深化 A：为什么 C++ 选择 introspect 而不是共享 JWT 密钥

FieldApp.h:8-9 的注释给出答案的前半："The Python field identity service validates signed user JWTs; C++ never trusts X-User or a nonempty Bearer"。后半是架构权衡：若 C++ 也持 `FIELD_JWT_SECRET`，密钥就有两份、撤销语义就要两边同步（用户文件只在 Python 侧）；introspect 把"签名验证 + 用户激活状态 + 角色存在"收敛在 Python 一处，C++ 每请求拿到的只是**已裁决的** `{id, role}`。代价是每请求一次回环 HTTP——`valid_internal` 要求 peer 回环（field_security.py:215-222）正是为了把这个代价封顶在本机：跨机部署必须由入口代理终结认证，而不是把内省端点暴露给网络。这与 Python 侧中间件⑤分支的设计（服务令牌只许三个面）构成同一条规则的两侧：内部服务身份永远是最小权限，不存在"service 万能通行"。

**最后更新**: 2026-11-10（新建：现场认证路由文档）
