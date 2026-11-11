# FieldApp（src/network/HTTPServer/FieldApp.{h,cpp}：FieldAuthMiddleware + field_runtime_ready + HttpApp 别名）

> **一句话**：现场部署的 C++ 侧全局 fail-closed 认证中间件——用户身份从不由 C++ 自己判断（Bearer 一律转发 Python `/api/field-auth/introspect` 裁决），内部服务令牌只认回环 + 双向不同密钥；外加一份"现场运行时就绪"自检（密钥/认证 URL/发布布局/无代理/模型白名单），任一不满足即拒绝启动现场模式。

## 1. 为什么有这个模块

普通部署（本地工作站）没有认证；现场部署（offline、真实案件数据）必须有。FieldApp.h:8-9 的结构注释给出信任模型："The Python field identity service validates signed user JWTs; C++ never trusts X-User or a nonempty Bearer."——身份裁决收敛在 Python 一处（用户文件、角色、激活状态都在那边），C++ 每请求拿到的是**已裁决的** `{principal, role}`。模块共三件东西：`FieldAuthMiddleware`（Crow 全局中间件，`before_handle` 逐请求裁决）、`field_runtime_ready()`（启动期配置自检，HTTPserver 与部署校验用它判定现场模式能否起）、`HttpApp` 别名（`crow::App<FieldAuthMiddleware>`——全服务器以"带中间件的 App"实例化，中间件不可绕过）。

## 2. 在系统中的位置

- **谁消费它**：HTTPserver.cpp 以 `HttpApp` 创建应用（所有路由注册在带中间件的 app 上）；`field_runtime_ready` 被启动序列调用，失败即现场模式拒绝启动。
- **它调用谁**：httplib 客户端 POST `FIELD_AUTH_URL` + `/api/field-auth/introspect`（FieldApp.cpp:158-193，头带 `x-tracelens-service-token` = `FIELD_CPP_TO_PYTHON_TOKEN`）；ConfigManager（local_only 模式下校验三个模型 URL 白名单，:113-119）。
- **对端**：Python 侧的同一条信任链见 [FieldAuth.md（Python 路由）](../../python/httpserver/routes/FieldAuth.md)——本模块的 `FIELD_CPP_TO_PYTHON_TOKEN` 即 Python `valid_internal(direction="cpp_to_python")` 验的那把令牌。

## 3. 核心数据结构

**context**（FieldApp.h:10-14）：`{principal: std::string, role: std::string}`——中间件裁决结果写入 ctx，路由处理器经 Crow 的 context 机制读取；`after_handle` 为空（无响应期逻辑）。

**环境变量族**（FieldApp.cpp:92-119 的消费清单）：

| 变量 | 含义 | 校验 |
|---|---|---|
| `TRACELENS_FIELD_AUTH` | 非 `enabled` 即 legacy 运行时，中间件直通（:123，注释"checker flags it"——静态检查器会标记未启用现场认证的现场构建） | — |
| `FIELD_JWT_SECRET`（Python 侧持有多余） | — | — |
| `FIELD_CPP_TO_PYTHON_TOKEN` | C++ 调 Python introspect 的服务令牌 | `configured_secret`：≥32 字符、非 `REPLACE_` 前缀、非示例值、字符集 ≥16 种（:29-33） |
| `FIELD_PYTHON_TO_CPP_TOKEN` | Python 调 C++ 的服务令牌 | 同上，且**必须与 c2p 不同**（:96 `equal_secret(c2p, p2p)` 为真即 not ready） |
| `FIELD_AUTH_URL` | Python 认证服务地址 | 只接受 `http://127.0.0.1:<port>` / `http://[::1]:<port>` 数值端口（:44-53 `valid_auth_url`） |
| `TRACELENS_REQUIRE_RELEASE_LAYOUT` / `TRACELENS_RELEASE_ROOT` / `TRACELENS_PYTHON_BIN` | 发布布局锁 | 绝对路径 + 目录真实存在 + 两个桥接脚本在位（:97-104） |
| `FIELD_OUTBOUND_POLICY` / `FIELD_MODEL_ORIGINS` | 出站策略 | disabled 或 local_only；local_only 必须有白名单且三个 LLM URL 都在名单内（:110-119） |
| `HTTP_PROXY` 等六个代理变量 | 现场模式**禁止**任何代理 | 任一非空即 not ready（:106-109） |

## 4. 核心机制走读

### 4.1 field_runtime_ready：现场模式的启动闸（FieldApp.cpp:91-120）

顺序即优先级：非现场模式恒 ready（:92）→ 双服务令牌存在、配置合格、**互不相同**（:93-96）→ 可选发布布局锁（:97-104）→ 无代理环境（:106-109）→ 出站策略收口（:110-119，local_only 时用 ConfigManager 的三个模型 URL 逐个过 `allowed_model_url`，LLM endpoint 还必须是以 `/` 开头的路径——不允许绝对 URL 绕过白名单）。这份自检与 Python 侧 `load_policy` 的同族检查（FIELD_SECURITY_VERSION 6a-v1）构成**两侧独立但语义对齐**的启动防线：任一侧配置不合格，现场模式就起不来——宁可拒服务，不带病运行。

### 4.2 before_handle 的裁决链（FieldApp.cpp:122-203）

```
① TRACELENS_FIELD_AUTH != enabled → 直通（legacy 运行时）
② OPTIONS → 204（预检放行；真实请求仍过本关）
③ /health/live → 放行（存活探针）
④ 非 API 路径（/api、/tasks、/python/、/cs/ 前缀之外）：
     GET/HEAD 放行（静态资源），其余 deny 401
⑤ 带 X-TraceLens-Service-Token：
     回环 + 与 FIELD_PYTHON_TO_CPP_TOKEN 常量时间匹配 → principal="python-service"/role="service"
        → python_service_scope 白名单（GET 仅 /api/security/status、/api/health、
          /api/tasks*、/api/forensics/*；POST 仅 /api/forensics/extract、
          /api/forensics/dlls/analyze，:78-87）越界 → 403 "service scope denied"
        → 可选出站闸（FIELD_OUTBOUND_POLICY=disabled 时 oss/graphiti/embedding → 503，:71-76）
     不匹配 → 401 "invalid service credential"（给了令牌但不对，绝不回落用户链路）
⑥ 否则必须 Bearer：格式不对 → 401 "bearer token required"
     认证服务地址/令牌未配置 → 503 "field authentication unavailable"（fail-closed，:160-162）
     httplib POST introspect → 裁决出的 principal/role 写入 ctx；httplib 失败（Python 不可达）→ 503
     "field authentication unavailable"（:177-180），introspect 非 200 → 503（:185-188），
     仅 introspect 返回 401/403 时原码透传（:181-184）
```

关键安全细节：**服务令牌分支没有静默回落**——`internal` 非空但验证失败直接 401 结束（:150-151），不会"当没有令牌继续走用户认证"，杜绝同一请求两个身份语义混淆；`equal_secret` 用 OpenSSL `CRYPTO_memcmp` 常量时间比较（:24-27），且要求长度相等才比较。静态资源放行只对 GET/HEAD（:134），写方法打到静态路径同样 401。

### 4.3 deny 的统一出口（FieldApp.cpp:35-42）

`deny(res, code, detail)`：401 时附 `WWW-Authenticate: Bearer`、恒设 JSON Content-Type 与 `Cache-Control: no-store`（认证失败的响应不允许被缓存）——与 Python 侧中间件的 401/403 形态一一对应。

## 5. 数据流（读什么、写什么）

**读**：环境变量（每请求读，无缓存——改 env 需重启进程生效的一致语义）、ConfigManager（仅 local_only 自检时）、introspect 的 JSON 响应。**写**：无持久化；ctx 是每请求的裁决载体。

## 6. 边界与已知状态

- **introspect 是每请求一次的回环 HTTP**：延迟代价被"必须回环"封顶（valid_auth_url 只接受 127.0.0.1/[::1]），跨机部署必须由入口代理终结认证。
- **legacy 直通是显式的**：`TRACELENS_FIELD_AUTH != "enabled"` 时中间件完全不设防（:123 注释承认"checker flags it"）——这是给本地开发保留的后门，现场构建由静态检查器把关。
- **服务白名单是闭合枚举**：python_service_scope（:78-87）逐一列出允许的方法×路径，新端点默认拒绝——与 Python 侧中间件"服务身份只许三个面"的最小权限取向一致。
- **401/403/503 分工**：凭据缺失/坏 401；身份合法但越权 403；现场基础设施未配置/可选服务被关 503。

## 7. 如何验证

- 部署自检：`TRACELENS_FIELD_AUTH=enabled` 但故意配两个相同的服务令牌 → 启动应失败（field_runtime_ready 返回 false）。
- 请求链路：无 Bearer 访问 /api/tasks → 401；带坏服务令牌 → 401 "invalid service credential"；带正确 p2c 令牌访问白名单外路径（如 /api/cases）→ 403 "service scope denied"；带合法用户 Bearer → introspect 命中并放行。
- Python 对端：见 [FieldAuth.md（Python 路由）](../../python/httpserver/routes/FieldAuth.md) 第 7 节。

相关阅读：[TaskManager.md](TaskManager.md)（现场模式下经认证的任务面）、[HTTPServer.md](HTTPServer.md)（HttpApp 的宿主）、EvidenceIntake 路由的 `_field_gate`（Python 侧行级令牌的退化路径）。

## 8. 二轮深化 A：为什么"给令牌但错了"要立即 401 而不是继续

before_handle 的第⑤分支（FieldApp.cpp:138-152）是整段代码里最锋利的一处：请求带了 `X-TraceLens-Service-Token` 头但值不对 → 直接 `deny 401 "invalid service credential"`，**不会**继续走第⑥分支的 Bearer 链路。对照相反设计的后果：若"令牌错就当没带"，攻击者可以用穷举服务令牌的请求夹带合法用户 Bearer，让每次失败的令牌猜测都退化成一次正常的用户请求——服务令牌校验就从"门"变成了"无副作用的探测"。立即 401 让"声称是服务"成为一种**要么全对要么全拒**的承诺。同一取向在 `configured_secret`（:29-33）也有：占位符值（`REPLACE_` 前缀、示例值 `change-this-in-production`）不算配置——"看起来配了"和"真的配了"被显式区分，杜绝用默认值带病上岗。

**最后更新**: 2026-11-10（新建：现场认证中间件文档）
