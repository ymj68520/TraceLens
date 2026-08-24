# PostgreSQL（C/S 服务端）字段参考（定义位置：`migrations/postgresql/001_initial_schema.sql` + `002_command_task_fk.sql` + `003_fix_super_admin_seed_credentials.sql`）

> 这是唯一的非 SQLite 持久层：server（:8091）的多租户元数据库（DatabaseSchema.md 决定一的反面案例——**跨任务共享的中心库**，所以它必须有真外键和 CHECK 约束，SQLite 侧的"无外键文化"在这里不适用）。注意它只存镜像**元数据/目录项**，原始镜像永不离开客户端（001 文件头注释）。迁移按文件序号执行，是唯一走迁移文件而非 SQL 头文件的 schema（决定三在此让位于 PG 迁移惯例）。

## 库概览

| 项 | 内容 |
|----|------|
| 谁写 | C/S 服务端（Python/FastAPI 侧，`DATABASE_URL` 指向）；迁移由部署流程执行 001→002→003 |
| 谁读 | 服务端 API（登录/任务下发/结果聚合）、tracelens_agent 轮询 command_queue |
| 扩展依赖 | `uuid-ossp`（001:16，`uuid_generate_v4()` 默认值） |
| 表间关系 | organizations 1..N users/clients/registration_tokens；clients 1..N disk_images/command_queue/analysis_tasks；analysis_tasks 1..N analysis_results/task_history/llm_analysis（001 文件头 erDiagram 注释） |

## 表清单总表（10 张）

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `organizations` | 租户 | 多租户组织 | 5 |
| `users` | 租户 | 服务端用户（JWT 登录，4 角色） | 8 |
| `clients` | 接入 | 注册的取证机代理 | 11 |
| `registration_tokens` | 接入 | 客户端注册令牌（限量/过期） | 8 |
| `disk_images` | 镜像目录 | 代理上报的磁盘镜像元数据 | 9 |
| `command_queue` | 任务流转 | 服务端→客户端命令队列 | 13(+1=14) |
| `analysis_tasks` | 任务流转 | 分析任务 | 13 |
| `analysis_results` | 任务产出 | 任务结果工件登记 | 9 |
| `llm_analysis` | 任务产出 | LLM 分析结果（计费维度） | 10 |
| `task_history` | 任务产出 | 任务状态流转审计 | 6 |

## 逐表字段说明

### organizations（`001_initial_schema.sql:21-27`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 组织 ID |
| name | VARCHAR(255) | NOT NULL UNIQUE | 组织名 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时刻 |
| settings | JSONB | DEFAULT '{}' | 组织设置 |
| subscription_tier | VARCHAR(50) | DEFAULT 'free' | 订阅档位 |

### users（`:32-42`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 用户 ID |
| org_id | UUID | REFERENCES organizations(id) ON DELETE CASCADE | 所属组织 |
| username | VARCHAR(100) | NOT NULL, UNIQUE(org_id, username) | 用户名（组织内唯一） |
| email | VARCHAR(255) | NOT NULL | 邮箱（Pydantic EmailStr 校验，见 003） |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 哈希 |
| role | VARCHAR(50) | NOT NULL CHECK IN ('super_admin','org_admin','analyst','auditor') | 角色 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建 |
| last_login | TIMESTAMP | — | 最近登录 |

### clients（`:47-60`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 客户端 ID |
| org_id | UUID | FK→organizations ON DELETE CASCADE | 所属组织 |
| hostname | VARCHAR(255) | NOT NULL, UNIQUE(org_id, hostname) | 主机名 |
| registration_token | VARCHAR(255) | UNIQUE | 注册令牌 |
| jwt_secret | VARCHAR(255) | — | 客户端 JWT 密钥 |
| capabilities | JSONB | DEFAULT '{}' | 能力声明 |
| status | VARCHAR(50) | DEFAULT 'offline' CHECK IN ('online','offline','error') | 在线状态 |
| last_poll / last_seen | TIMESTAMP | — | 最近轮询/最近在线 |
| version | VARCHAR(50) | — | agent 版本 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 注册时刻 |

### registration_tokens（`:172-182`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 令牌 ID |
| org_id | UUID | FK→organizations ON DELETE CASCADE | 所属组织 |
| token | VARCHAR(255) | UNIQUE NOT NULL | 令牌串 |
| max_clients | INTEGER | DEFAULT 10 CHECK (>0) | 最多注册数 |
| used_count | INTEGER | DEFAULT 0 CHECK (>=0) | 已用数 |
| expires_at | TIMESTAMP | NOT NULL | 过期时刻 |
| created_by | UUID | FK→users(id)（无级联） | 签发人 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 签发时刻 |
| — | — | CHECK (used_count <= max_clients) | 表级约束（`:181`）：用量不超限 |

### disk_images（`:65-75`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 镜像 ID |
| client_id | UUID | FK→clients ON DELETE CASCADE | 上报客户端 |
| path | VARCHAR(1000) | NOT NULL | 客户端本地路径（**元数据 only**，镜像本体不上传） |
| size_bytes | BIGINT | NOT NULL | 大小 |
| format | VARCHAR(50) | NOT NULL CHECK IN ('E01','DD','Directory') | 格式 |
| md5_hash | VARCHAR(32) | — | 校验哈希 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 上报时刻 |
| indexed_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 索引完成时刻 |
| metadata | JSONB | DEFAULT '{}' | 扩展元数据 |

### command_queue（`:80-98`，002 迁移后共 14 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 命令 ID |
| client_id | UUID | FK→clients ON DELETE CASCADE | 目标客户端 |
| user_id | UUID | FK→users ON DELETE SET NULL | 发起用户 |
| command_type | VARCHAR(100) | NOT NULL CHECK IN ('analyze_disk','extract_file','health_check') | 命令类型 |
| parameters | JSONB | NOT NULL | 参数（早期任务 id 软链曾藏在这里，002 已实列化） |
| priority | VARCHAR(50) | DEFAULT 'normal' CHECK IN ('low','normal','high','critical') | 优先级 |
| status | VARCHAR(50) | DEFAULT 'pending' CHECK IN ('pending','assigned','in_progress','completed','failed','expired') | 状态机 |
| ttl | TIMESTAMP | NOT NULL | 过期时刻（轮询判废） |
| created_at / assigned_at / completed_at | TIMESTAMP | DEFAULT/— | 生命周期三时刻 |
| result_message | TEXT | — | 结果消息 |
| retry_count | INTEGER | DEFAULT 0 | 重试计数 |
| task_id | UUID | FK→analysis_tasks(id) ON DELETE CASCADE（**002:5-6 增列**） | 关联任务（回填自 parameters->>'task_id'，002:9-13） |

### analysis_tasks（`:103-122`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 任务 ID |
| org_id | UUID | FK→organizations ON DELETE CASCADE | 组织 |
| client_id | UUID | FK→clients ON DELETE SET NULL | 执行客户端 |
| user_id | UUID | FK→users ON DELETE SET NULL | 发起用户 |
| disk_image_id | UUID | FK→disk_images ON DELETE SET NULL | 目标镜像 |
| task_name | VARCHAR(255) | NOT NULL | 任务名 |
| analysis_type | VARCHAR(100) | NOT NULL CHECK IN ('full','quick','windows','android','linux') | 分析类型 |
| status | VARCHAR(50) | DEFAULT 'created' CHECK IN ('created','queued','running','completed','failed','cancelled') | 状态机 |
| progress | INTEGER | DEFAULT 0 CHECK (0..100) | 进度百分比 |
| created_at / started_at / completed_at | TIMESTAMP | DEFAULT/— | 生命周期 |
| error_message | TEXT | — | 失败原因 |
| metadata | JSONB | DEFAULT '{}' | 扩展字段 |

### analysis_results（`:127-139`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 结果 ID |
| task_id | UUID | FK→analysis_tasks ON DELETE CASCADE | 所属任务 |
| client_id | UUID | FK→clients ON DELETE SET NULL | 产出客户端 |
| result_type | VARCHAR(100) | NOT NULL CHECK IN ('database','file','metadata') | 工件类型 |
| file_path | VARCHAR(1000) | — | 工件路径 |
| file_size | BIGINT | — | 大小 |
| storage_location | VARCHAR(500) | — | 存储位置 |
| metadata | JSONB | DEFAULT '{}' | 扩展 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 登记时刻 |

### llm_analysis（`:144-155`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 行 ID |
| task_id | UUID | FK→analysis_tasks ON DELETE CASCADE | 所属任务 |
| file_id | UUID | —（**无 FK**——SQLite 侧文件没有 UUID，故意不链） | 逻辑关联文件 |
| file_path | VARCHAR(1000) | — | 文件路径（跨体系对齐键） |
| input_text_hash | VARCHAR(64) | — | 输入文本哈希（缓存/防重算） |
| analysis_result | TEXT | NOT NULL | 分析结论 |
| model_used | VARCHAR(100) | — | 模型 |
| tokens_used | INTEGER | — | token 数 |
| cost | DECIMAL(10,4) | — | 成本（计费审计） |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 时刻 |

### task_history（`:160-167`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | UUID | PRIMARY KEY DEFAULT uuid_generate_v4() | 行 ID |
| task_id | UUID | FK→analysis_tasks ON DELETE CASCADE | 所属任务 |
| user_id | UUID | FK→users ON DELETE SET NULL | 操作人 |
| action | VARCHAR(100) | NOT NULL | 动作（created/started/...） |
| details | JSONB | — | 详情 |
| timestamp | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 时刻 |

## 索引（7 个）

001 建 6 个（`:187-192`）：

| 索引 | 列 | 服务查询 |
|------|----|---------|
| `idx_clients_org_status` | clients(org_id, status) | 按组织看在线客户端 |
| `idx_command_queue_client_status` | command_queue(client_id, status, ttl) | 客户端轮询领命令（最高频查询） |
| `idx_analysis_tasks_org_status` | analysis_tasks(org_id, status) | 组织任务面板 |
| `idx_analysis_results_task` | analysis_results(task_id) | 任务结果列表 |
| `idx_disk_images_client` | disk_images(client_id) | 客户端镜像列表 |
| `idx_task_history_task` | task_history(task_id) | 任务历史 |

002 增 1 个（`002:15`）：`idx_command_queue_task ON command_queue(task_id)`。

## 种子数据说明

- **001 种子（`:201-218`）**：`Default Organization`（enterprise 档，ON CONFLICT DO NOTHING）+ `super_admin` 用户（bcrypt 哈希，ON CONFLICT (org_id, username) DO NOTHING）。文件头注释（`:196-199`）强调先组织后用户的插入顺序（相对早期草稿的修复）。
- **001 种子自带两处坏值，003 定向修复（非破坏式，仅命中已知坏值才改，幂等）**：
  1. 密码哈希不匹配文档口令 `admin123` → 001 能建号但登录必 401；003:20-23 把该哈希替换为能验证 `admin123` 的新哈希；
  2. 邮箱 `super_admin@tracelens.local` 用了保留 TLD `.local`，Pydantic EmailStr 拒绝 → `/api/auth/me` 序列化 500；003:25-28 改为 `super_admin@example.com`。
  - 003 文件头注释（`:1-18`）完整记录了这两个缺陷的故障路径；运维改过口令/邮箱则不被覆盖。
- **生产警示**：两个迁移都内嵌 `CHANGE IN PRODUCTION` 提示——种子口令必须改。

## 状态机（CHECK 约束取值全集）

| 表 | 列 | 合法值（001 迁移原文） |
|----|----|----------------------|
| users | role | super_admin / org_admin / analyst / auditor |
| clients | status | online / offline / error |
| disk_images | format | E01 / DD / Directory |
| command_queue | command_type | analyze_disk / extract_file / health_check |
| command_queue | priority | low / normal / high / critical |
| command_queue | status | pending / assigned / in_progress / completed / failed / expired |
| analysis_tasks | analysis_type | full / quick / windows / android / linux |
| analysis_tasks | status | created / queued / running / completed / failed / cancelled |
| analysis_tasks | progress | 0..100 |
| analysis_results | result_type | database / file / metadata |

## 各表写入/读取方（按 001 头注释与迁移结构推断）

| 表 | 谁写 | 谁读 |
|----|------|------|
| organizations | 部署种子、组织管理 API | 一切按 org_id 过滤的查询 |
| users | 注册/管理 API（bcrypt 加密） | JWT 登录、鉴权中间件 |
| clients | agent 注册流程（凭 registration_tokens） | 命令下发、状态面板 |
| registration_tokens | 组织管理员签发 | 注册校验（used_count 递增） |
| disk_images | agent 索引上报 | 任务创建时的目标选择 |
| command_queue | 任务下发 API | agent 轮询（client_id+status+ttl 索引正为此设计） |
| analysis_tasks | 任务创建/状态回写 | 任务面板、命令关联（002 FK） |
| analysis_results | agent 结果登记 | 结果下载/聚合 |
| llm_analysis | LLM 流水线 | 计费统计（tokens_used/cost） |
| task_history | 状态流转钩子 | 任务审计页 |

## 跨表关联键

与 SQLite 侧"逻辑对齐"相反，本 schema 的关联全是**真外键**：

- 租户链：`*.org_id → organizations.id`（CASCADE）。
- 命令链：`command_queue.client_id → clients.id`；`command_queue.task_id → analysis_tasks.id`（002 的软链实列化，回填逻辑见 002:9-13）。
- 产物链：`analysis_results/llm_analysis/task_history.task_id → analysis_tasks.id`（CASCADE，删任务清产物）。

真实 JOIN 示例（组织视角拉"命令—任务—结果"全链——C/S 排障常用）：

```sql
SELECT o.name, c.hostname, q.command_type, q.status AS cmd_status,
       t.task_name, t.status AS task_status, r.result_type
FROM command_queue q
JOIN clients c      ON c.id = q.client_id
JOIN organizations o ON o.id = c.org_id
LEFT JOIN analysis_tasks t ON t.id = q.task_id
LEFT JOIN analysis_results r ON r.task_id = t.id
ORDER BY q.created_at DESC;
```

## 已知边界

- **001 种子两处坏值**（口令哈希、.local 邮箱）由 003 修复——只跑过 001 未跑 003 的环境仍不可登录，这是 003 存在的全部理由。
- **`llm_analysis.file_id` 无外键**：UUID 世界（PG）与 INTEGER 自增世界（SQLite 文件库）之间没有可声明的引用，只留 `file_path` 软对齐。
- **`registration_tokens.created_by` 无级联**：删签发用户不删令牌（与 org/user 级联策略不一致，是有意保留审计线索）。
- **迁移幂等性差异**：002 用 `IF NOT EXISTS`（可重跑）；001/003 靠 ON CONFLICT/WHERE 条件实现幂等，但 001 的 CREATE TABLE 不可重跑（无 IF NOT EXISTS）——按序执行一次是前提。

---


## 附录：写入时序与查询手册

### 写入时序

| 表 | 写入方 | 时机 |
|----|--------|------|
| organizations/users/registration_tokens | 管理员经 /api/auth、/api/organizations | 初始化/运维 |
| clients | agent 凭注册令牌注册（/api/clients/register） | 首次接入 |
| disk_images | agent 的 image_indexer 上报 | 首轮索引 |
| command_queue | 运营方 /api/commands 下发；agent poll 领取置 assigned | 每次分析指令 |
| analysis_tasks / task_history | task_orchestrator（创建即双写 FK+软链接） | 命令关联任务 |
| analysis_results / llm_analysis | agent 的 result_uploader 回收 | 执行完成后 |

### 查询手册（psql）

**1. 命令队列健康（积压/卡死一眼看）**
```sql
SELECT status, COUNT(*), MIN(created_at) oldest
FROM command_queue GROUP BY status ORDER BY 2 DESC;
```

**2. 代理在线状态（60 秒窗口）**
```sql
SELECT hostname, status, last_seen_at FROM clients
WHERE last_seen_at > now() - interval '90 seconds' ORDER BY last_seen_at DESC;
```

**3. 任务成功率与耗时画像**
```sql
SELECT t.status, COUNT(*), ROUND(AVG(EXTRACT(EPOCH FROM (t.completed_at - t.created_at)))::numeric,0) avg_sec
FROM analysis_tasks t GROUP BY t.status;
```

**4. 结果体量 Top（磁盘大户）**
```sql
SELECT task_id, COUNT(*) files, ROUND(SUM(size_bytes)/1048576.0,1) mb
FROM analysis_results GROUP BY task_id ORDER BY mb DESC LIMIT 20;
```

**5. TTL 将过期命令（过期仅靠 expire 端点触发，先看有多少）**
```sql
SELECT id, command_type, status, expires_at FROM command_queue
WHERE expires_at < now() + interval '1 hour' AND status NOT IN ('completed','failed','expired')
ORDER BY expires_at;
```

**6. 迁移版本自检（002/003 是否已手工应用）**
```sql
-- 002 的证据：command_queue.task_id 列与 idx_command_queue_task 索引存在
SELECT indexname FROM pg_indexes WHERE tablename='command_queue';
-- 003 的证据：users 表种子邮箱应为 super_admin@example.com（.local 为未应用）
SELECT email FROM users WHERE role='super_admin';
```

## 分析案例

### 案例一：一次"命令下发了没执行"的复盘

**问题**：运营方称向某取证机下发了 analyze_disk，两小时无结果。psql 三步：
1. `command_queue` 按 id 查该命令状态与 `expires_at`——卡在 assigned 说明 agent 领了没回（agent 侧日志）；
2. `clients.last_seen` 判断代理是否离线（60 秒窗口外=离线，命令会悬着直到 TTL）；
3. `analysis_tasks`+`task_history`（按 command_queue.task_id FK 关联）看任务是否创建过——没创建=agent 执行 CLI 前就失败（常见：镜像路径不可达）；创建了但 failed=看 error_message。
结论模板：命令链四站（下发/领取/执行/回收）哪一站断的，本库全部可追溯。

### 案例二：代理接入潮的容量核对

registration_tokens 的 used_count/max_clients（表级 CHECK 约束保证不超发）与 clients 增速对比；analysis_results 的 size_bytes 按日聚合看回传洪峰——为 PG 磁盘与 result 存储扩容给依据（数据是登记行不是 blob 本体，注意区分）。

## 自检清单

- [ ] 002 索引存在 + 003 种子已修（查询手册第 6 条）
- [ ] command_queue 无长期 pending 积压
- [ ] clients.last_seen 在窗口内（代理在线）
- [ ] registration_tokens 未超发（used≤max 由 CHECK 保证，仍要看趋势）
**最后更新**: 2026-08-24（补：写入时序与查询手册）
