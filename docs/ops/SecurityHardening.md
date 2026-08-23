# 部署安全清单（SecurityHardening）

> 适用场景：把 TraceLens 从"开发机默认配置"收尾为"可长期驻留的内网生产部署"时的逐项核对。
> 前置：先读 `docs/architecture/Security.md`（安全机制总览）。本手册是操作清单，不重复设计论述。
> 总原则：本地三服务**按无认证设计**，安全边界靠网络隔离；C/S（8091）是唯一有真实认证的服务。

## 速查卡

```bash
# 1. .env 权限（含全部密钥）
chmod 600 .env && ls -l .env

# 2. 轮换 JWT 密钥（使所有已发 token 立即失效）
NEW=$(openssl rand -hex 32); sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${NEW}|" .env
# 重启 8091 后用新口令重新登录验证

# 3. Neo4j 改密并联动 .env
cypher-shell -u neo4j -p '<旧密码>' "ALTER CURRENT USER SET PASSWORD FROM '<旧密码>' TO '<新密码>';"
sed -i "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=<新密码>|" .env

# 4. C/S super_admin 改默认口令（admin123 → 强口令）
curl -s -X POST http://localhost:8091/api/auth/login -H 'Content-Type: application/json' \
     -d '{"username":"super_admin","password":"admin123"}'   # 拿 token 后走改密/建新管理员流程

# 5. 收紧 CORS / 路径围栏（.env）
PYTHON_CORS_ORIGINS='["http://localhost:5173"]'
FTS_ALLOWED_ROOT=/home/xxx/TraceLens/build/data

# 6. 网络面（无认证服务的硬边界）
ss -ltnp | grep -E '8666|8090|8091'      # 确认只绑预期接口；HTTP_SERVER_HOST/PYTHON_HTTP_HOST 默认 0.0.0.0
```

## 1. 本地服务无认证的边界与网络隔离要求

背景：C++（8666/8080）与 Python httpserver（8090）的**所有端点均无认证**——能连通端口的任何人都能创建任务、读分析结果、触发 LLM 调用、读系统日志。前端 `/login` 是 mock（写 localStorage 一个假 token，服务端无对应校验）。这是设计现状，不是配置遗漏。

操作（部署时必须至少做一项）：
- 首选**网络层隔离**：防火墙只放行使用者的机器；`HTTP_SERVER_HOST`/`PYTHON_HTTP_HOST` 默认 `0.0.0.0`（`.env.example:110,124`），单机使用应改为 `127.0.0.1` 后重启；
- 需要远程访问时加反向代理做认证 + TLS 终止（仓库不提供该配置，需自建）；
- 永不将 8666/8090 映射到公网或不可信网段。

验证：`ss -ltnp | grep -E '8666|8090|8091'` 看监听地址；从另一台机器 `curl -m 3 http://<host>:8666/api/system/health` 应不可达（预期外网拒绝）。
失败排查：改 HOST 后前端跨端口调用失败属预期——前端页面与 API 必须同源（生产模式均由 C++ 8666 托管）。

## 2. C/S（8091）的 JWT_SECRET_KEY 与口令治理

背景：8091 是唯一有真实认证的服务：JWT HS256（`JWT_SECRET_KEY`）+ 一次性注册令牌（`registration_tokens` 表）。token 有效期：user 1 小时、client 30 天（`server/services/auth_service.py:34-35, 51-83, 86-116`）。

操作：
- **轮换 JWT_SECRET_KEY**：生成强随机值写入 `.env` 并重启 8091。效果：所有存量 token 立即失效（校验在 `auth_service.py:119-135`，换 key 后 `InvalidTokenError` → None → 401），用户需重新登录、agent 需重新注册/换发——**预先通知使用方**。
- 默认值兜底警告：`JWT_SECRET_KEY` 未设置时代码回退到字符串 `change-this-in-production`（`server/config.py:54`），等于无密钥，必须显式设置。
- super_admin：种子口令 `admin123`（001/003 迁移均标注 CHANGE IN PRODUCTION），上线即改；确保 003 迁移已应用（否则该账号恒 401，见 UpgradeMigration.md §2.2）。
- 算法固定 HS256（`JWT_ALGORITHM`）；如需 RS256 需自备密钥对，代码不会自动切换（`auth_service.py:12-18` 文档字符串）。

验证：换 key 后旧 token 调 `/api/auth/me` 应 401；`grep -c "change-me\|change-this" .env` 应为 0。
失败排查：8091 全部 401 → 先确认不是 key 刚轮换（预期）；时钟漂移会让 `exp` 判定异常（代码已用 UTC 时间戳，NTP 保持对时即可）。

## 3. NEO4J_PASSWORD 修改联动

背景：`.env` 的 `NEO4J_PASSWORD` 被 Python 侧（Graphiti）与 `wipe_neo4j.py` 共用；setup.sh 只在**新装** Neo4j 时用它设置初始密码（`setup.sh:379-391`），改已有实例密码要手动。

操作：
1. `cypher-shell` 里 `ALTER CURRENT USER SET PASSWORD ...`（见速查卡）；
2. 同步改 `.env` 的 `NEO4J_PASSWORD`；
3. 重启 Python httpserver（GraphitiService 启动时探测连接，密码错 → "Graphiti service will be disabled" 降级，`graphiti_parts/_core.py:26-32`）。

验证：`curl localhost:8090/health/ready` 的 `checks.neo4j.status=connected`；日志无 "Neo4j is not available"。
失败排查：降级警告在启动时打一次，改完密码不重启不会恢复。

## 4. .env 权限与密钥文件治理

背景：`.env` 集中存放 NEO4J_PASSWORD、JWT_SECRET_KEY、DATABASE_URL（含 PG 口令）、REDIS_URL（可含密码）、OSS_ACCESS_KEY_*、LLM_API_KEY；仓库默认权限通常为 644（组/其他可读）。

操作：
```bash
chmod 600 .env
grep -E "PASSWORD|SECRET|KEY|DATABASE_URL|REDIS_URL" .env   # 人工核对无残留 change-me
```
- `.env` 已被 `.gitignore` 排除（不要把生产 `.env` 提交进库；`.env.example` 里的占位值保持占位）；
- 备份 `.env` 的介质加密（见 DataAndBackup.md §4）。
验证：`stat -c '%a' .env` 应为 600；`git status` 不出现 `.env`。

## 5. run.sh 对 PYTHON_CORS_ORIGINS 的过滤（原因与边界）

背景：`run.sh:63-75` 在 source `.env` 前会 grep 掉 `PYTHON_CORS_ORIGINS=` 行，原因有二（脚本注释原文）：
1. 值是 JSON 数组（`["*"]`），**C++ 的 dotenv 解析器无法解析**，透传会在 C++ 侧产生告警；
2. 同时过滤空值 `PROJECT_ROOT=`，防止把脚本算出的项目根覆盖成 `/`（后续 `$PROJECT_ROOT/python_service` 变成 `/python_service` 触发权限错误）。

边界说明：这只影响 run.sh 进程导出给 C++ 的环境；**Python 服务自己仍会从 `.env` 读到 PYTHON_CORS_ORIGINS**（pydantic-settings env_file），所以改 CORS 收紧是生效的、不会因 run.sh 过滤而失效。默认 `["*"]` 全放行，生产应收紧为明确来源（解析逻辑支持 JSON 数组或逗号分隔，`httpserver/config.py:236-271`）。C/S 侧 CORS 默认仅放行 localhost:5173/3000（`server/config.py:60-64`），一般无需动。

## 6. FTS_ALLOWED_ROOT 围栏与 markitdown workspace 门控

背景：两类端点接受用户提供的文件路径，代码用"锚定根目录 + 词法相对路径检查"防 `/etc/passwd` 式任意读取。

- **FTS**（C++ `POST /api/search/index` / `GET /api/search/fulltext`）：默认只允许 PathManager 的 data 目录；操作员可用环境变量 `FTS_ALLOWED_ROOT` 放宽到别的根（实现 `src/network/HTTPServer/routes/SearchRoutes.cpp:14-35`，越界返回 400 + 提示 "set FTS_ALLOWED_ROOT to widen the permitted directory"）。**收紧方向**：不要为图省事把围栏设为 `/`。
- **markitdown**（Python 8090 `POST /api/markitdown/convert`）：必须提供 `task_id` 或 `workspace_root` 锚点，候选文件必须 `resolved_within(workspace)`，越界 400 "file is outside the task workspace"（`python_service/httpserver/routes/markitdown.py:50-76, 80-109`）。注意 `workspace_root` 是给 CLI 调用方的显式锚点（**调用方自己指定根**），面向浏览器暴露时依赖任务态锚点（task_id）更稳。

操作：按需设置 `FTS_ALLOWED_ROOT`（绝对路径）；不要修改代码绕过围栏。
验证：`curl "http://localhost:8666/api/search/fulltext?q=x&index=/etc"` 类越界请求得到 400 而非结果。
失败排查：合法目录被拒 → 围栏对候选路径做 weakly_canonical 归一，符号链接指向围栏外会被拒（按设计），把真实目录纳入围栏。

## 7. 审计日志保留与取证留痕

背景：任务创建/删除/取消、DB_INIT 等动作写入 `forensics_audit.db`（WAL + synchronous=NORMAL，默认**同步写**保证崩溃安全，`AuditLog.cpp:101-112`、`AuditLogDataTypes.h:51-54`）。配置里 `retention_days=30`、`max_db_size_mb=100` 存在，但 `cleanup()/rotate()` **当前没有调用方**——即不会自动清理，也不会自动轮转（详见 DataAndBackup.md §2.3）。

操作：
- 有合规保留期要求（如 ≥90 天）：现状天然满足（不删），但要**防磁盘涨满**——人工按 `DELETE ... WHERE timestamp < cutoff; VACUUM;` 治理（参照 `AuditLog_Queries.cpp:228-250`），或把库迁到大盘；
- 定期导出归档（sqlite3 `.backup` + csv 导出，见 DataAndBackup.md 速查卡）作为第二副本；
- 查询入口：`GET /api/tasks/<id>/audit-log?limit&offset`（`TaskMonitoringRoutes.cpp:17`）。
验证：`sqlite3 build/forensics_audit.db "SELECT action, COUNT(*) FROM audit_logs GROUP BY action;"` 有记录在增长。

## 8. 网络隔离落地（无认证服务的硬边界）

背景：§1 说明了"必须隔离"，这里给出具体落地手段（仓库不提供防火墙配置，以下为宿主机常规操作）。

```bash
# 1. 只绑回环（单机使用，最简）
#    .env: HTTP_SERVER_HOST=127.0.0.1  PYTHON_HTTP_HOST=127.0.0.1
#    C/S 8091 需要被 agent 访问时保持 0.0.0.0，但要配合防火墙

# 2. ufw 白名单（仅放行使用方 IP；ufw 为宿主机工具，非仓库提供）
sudo ufw default deny incoming
sudo ufw allow from 192.168.31.0/24 to any port 8666 proto tcp   # 按实际网段收窄
sudo ufw allow from 192.168.31.10 to any port 8091 proto tcp     # agent 所在机器
sudo ufw enable

# 3. 审计当前监听面
ss -ltnp | grep -E ':8666|:8090|:8091|:7474|:7687|:6379|:5432|:1234'
```

注意外部依赖也要一起收：Neo4j HTTP 7474 / Bolt 7687、Redis 6379（未设密码时尤其危险——当前环境 REDIS_URL 带密码，属正确做法）、PostgreSQL 5432、LM Studio 1234 都应只对需要的接口开放。Redis 设密码：`redis-cli CONFIG SET requirepass '<pwd>'`（并同步 `REDIS_URL=redis://:<pwd>@localhost:6379`）。

验证：从白名单外的机器逐端口 `curl -m 3` / `nc -zv` 应全部拒绝；服务功能从白名单内机器正常。

## 9. 注册令牌与 agent 接入治理（C/S）

背景：取证机 agent 通过一次性注册令牌（`registration_tokens` 表，含 `max_clients`/`used_count`/`expires_at`，001 迁移定义）换取 30 天 client JWT；命令队列默认 TTL 24h（critical 1h），agent 轮询间隔默认 10s（`server/config.py:71-75`）。

操作：
- 令牌按批次发放、设短 `expires_at`，用完即弃（表上有 `used_count <= max_clients` CHECK 约束兜底）；
- agent 失窃/退役：轮换 `JWT_SECRET_KEY`（§2）一次性吊销全部 client token，再重新注册存活的 agent；
- 上传面控制：`MAX_UPLOAD_SIZE` 默认 5GB、`MAX_LLM_TEXT_SIZE` 默认 10MB（`server/config.py:67-68`），按实际镜像大小下调可减轻滥用面。

## 10. 事件响应：一次性轮换全部密钥

背景：怀疑 `.env` 泄露或主机被触及时，按以下顺序轮换（顺序错误会把自己锁在外面）。

```bash
# 1. PostgreSQL 口令（先改库再改 .env）
psql "$DATABASE_URL" -c "ALTER USER postgres PASSWORD '<新>';"
# 2. Neo4j（§3）
# 3. Redis requirepass（§8）
# 4. LM Studio / 云端 API key（在其控制台操作）
# 5. JWT_SECRET_KEY（最后，因为会踢掉所有在线会话）
# 6. chmod 600 .env；排查泄露途径（history、备份、截图）
```

验证：旧凭据逐项连接失败；新凭据三服务健康检查全绿。
失败排查：轮换后 Graphiti 降级 → Neo4j 密码没同步（§3 的验证步骤）；8091 全 401 → JWT 轮换的预期效果，重新登录。

## 11. 已知不加固项（如实清单，勿当已防护）

以下为仓库现状中**明确没有**的防护，评估暴露面时必须计入：

1. **`GET /api/system/logs` 无鉴权**（`SystemInfoRoutes.cpp:27, 226-306`）：任何能连到 C++ 端口的人可读应用日志尾部（最多 1000 行，`?lines=` 参数）——日志可能含路径等敏感信息。缓解：靠 §1 的网络隔离。
2. 本地 8666/8090 全部 API 无认证、前端登录是 mock（`docs/architecture/Security.md` §1/§8）。
3. `PYTHON_CORS_ORIGINS` 默认 `["*"]`（`.env.example:203`）。
4. `MCP_ALLOWED_PATHS` 留空 = 允许所有路径（`.env.example:62-63`）。
5. 服务自身不做 TLS 终止，HTTP 明文（LLM/Neo4j/PG 连接是否加密取决于各 URL 协议）。
6. 审计 rotate/cleanup 未接线（§7）；`/api/tasks/<id>/priority` 端点只回显不生效（`docs/api_reference/CPP_REST_API.md` 备注）。
7. CLI 传口令若用 `--backup-password` 会进 argv（可被 ps 观测），应用 `--backup-password-stdin`/`--backup-password-fd`（`docs/architecture/Security.md` §4）。
8. OSS 凭据明文存 `.env`（靠 §4 的 600 权限缓解）。

## 与代码的对应

另附**部署前核对清单**（全部来自本手册各节，可打勾使用）：

- [ ] `.env` 权限 600，无 change-me/change-this 残留（§4）
- [ ] `JWT_SECRET_KEY` 为强随机值；super_admin 已改默认口令；003 迁移已应用（§2）
- [ ] `NEO4J_PASSWORD` 非初始值且与库一致（§3）
- [ ] 8666/8090 不可达于信任域之外（绑定地址或防火墙，§1/§8）
- [ ] `PYTHON_CORS_ORIGINS` 非 `["*"]`（§5）
- [ ] `FTS_ALLOWED_ROOT` 未指向 `/`；MCP_ALLOWED_PATHS 已按需收紧（§6、§11）
- [ ] Redis 已设密码（§8）
- [ ] 审计库有归档计划（§7）
- [ ] 已知不加固项（§11）已逐条知悉并有网络层缓解

| 机制 | 位置 |
|------|------|
| JWT 配置与默认密钥回退 | `python_service/server/config.py:53-57` |
| token 签发/校验/有效期 | `python_service/server/services/auth_service.py:29-35, 51-83, 86-135` |
| 认证依赖（get_current_user/client） | `python_service/server/middleware/auth.py:26-77` |
| Neo4j 初始密码（仅新装） | `setup.sh:379-391` |
| Graphiti 密码错→disabled 降级 | `python_service/httpserver/services/graphiti_parts/_core.py:26-32` |
| run.sh 过滤 PYTHON_CORS_ORIGINS/PROJECT_ROOT | `run.sh:63-75`（含原因注释） |
| CORS 解析（JSON/逗号分隔） | `python_service/httpserver/config.py:236-271` |
| C/S CORS 默认白名单 | `python_service/server/config.py:60-64` |
| FTS_ALLOWED_ROOT 围栏 | `src/network/HTTPServer/routes/SearchRoutes.cpp:14-35, 159` |
| markitdown workspace 门控 | `python_service/httpserver/routes/markitdown.py:50-76, 80-109` |
| /api/system/logs（无鉴权） | `src/network/HTTPServer/routes/SystemInfoRoutes.cpp:27, 226-306` |
| 注册令牌/命令 TTL/轮询间隔默认 | `migrations/postgresql/001_initial_schema.sql:172-182`；`python_service/server/config.py:67-75` |
| 上传大小上限 | `python_service/server/config.py:67-68` |
| 审计 WAL+同步写与保留默认 | `src/core/AuditLog/AuditLog.cpp:101-112`；`AuditLogDataTypes.h:47-58` |
| 口令进 argv 的风险与 stdin 替代 | `docs/architecture/Security.md` §4（实现 `src/CommandLineParser.cpp`） |
| 安全机制总览（上游文档） | `docs/architecture/Security.md` |

**最后更新**: 2026-08-24（新建，运维手册）
