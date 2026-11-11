# 升级与迁移手册（UpgradeMigration）

> 适用场景：`git pull` 拉新代码后重建与重启、PostgreSQL 全新建库（001）与增量迁移（002/003）、SQLite 侧结构自愈说明、Graphiti 图谱结构迁移、前端产物同步。
> 前置：升级前先做数据备份（见 DataAndBackup.md §4）；确认磁盘余量（一次 `--clean` 重建需要完整重编译空间）。

## 速查卡

```bash
# 标准升级（保留数据）
git pull
./run.sh --clean            # 清编译产物（保留 build/data、*.db、logs）→ 全量重编译 → 启动

# 只换代码不动 C++（改了 Python/前端时）
git pull && ./run.sh --no-build --no-web     # 直接用旧二进制启动
cd web && npm run build && ./run.sh --no-build   # 前端有改动时

# PostgreSQL 全新建库（首次部署，从 python_service 目录）
cd python_service
.venv/bin/python -m server.db.init_db --migrate --init --seed   # 应用 001 + 补 ORM 缺表 + 种子
# 随后仍需手工补增量（服务启动不会应用 SQL 迁移文件）：
psql "$DATABASE_URL" -f migrations/postgresql/002_command_task_fk.sql
psql "$DATABASE_URL" -f migrations/postgresql/003_fix_super_admin_seed_credentials.sql

# PostgreSQL 增量迁移（已有库升级后必查；001 勿重跑，见 §2）
psql "$DATABASE_URL" -f migrations/postgresql/002_command_task_fk.sql
psql "$DATABASE_URL" -f migrations/postgresql/003_fix_super_admin_seed_credentials.sql

# SQLite 自愈验证（files 表 LLM 列/分区列是否补齐）
sqlite3 build/data/tasks/<id>/files.db "PRAGMA table_info(files);" | grep -E "llm_summary|partition_num"

# 图谱迁移状态
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (t:Task) RETURN t.id LIMIT 5;"

# 前端 dist 同步确认
ls build/web/dist/index.html && diff -q web/dist/index.html build/web/dist/index.html
```

## 1. 代码升级（git pull → 重建 → 重启）

背景：升级的核心决策是"清理到什么程度"。仓库有两个语义完全不同的清理入口，**选错会丢数据**：

| 命令 | 范围 | 数据影响 |
|------|------|---------|
| `./run.sh --clean` | 只删 build 顶层的 `CMakeFiles/ CMakeCache.txt cmake_install.cmake Makefile CTestTestfile.cmake Testing/ *.o`（`run.sh:113-119`） | **保留** `build/data/`（tasks.json、任务库）、`build/*.db`（审计库）、`build/logs/` |
| `make clean` / `make rebuild` | `rm -rf build` + `rm -rf web/dist`（`Makefile:109-117`） | **删除全部任务数据与审计库**！仅适合全新环境 |

标准升级流程：

```bash
# 1. 停服（前台脚本 Ctrl+C）
# 2. 备份（tar data + audit db，见 DataAndBackup.md）
# 3. 拉代码
git pull
# 4. 依赖可能变化：venv 有 .deps_installed 标记，删掉它可强制重装
#    rm -f python_service/.venv/.deps_installed   （run.sh/启动脚本会据此重装双 requirements）
# 5. 重建 + 启动
./run.sh --clean
```

`run.sh --no-...` 组合（参数解析在 `run.sh:50-66`）按改动面裁剪：
- 只改 Python：`./run.sh --no-build`（venv 缺依赖时脚本会自动 `pip install`，`run.sh:215-230`）；
- 只改 C++：`./run.sh --no-web`（省掉 npm build；前端改动见 §5）；
- 只改前端：`cd web && npm run build` 后手动同步 dist（§5）或直接 `./run.sh --no-build`（它会重新做 npm build + 同步）；
- CI/只验证编译：`./run.sh --build-only`。

验证：三服务健康检查通过（ServiceRunbook.md §3）；抽查一个旧任务 `curl http://localhost:8666/api/tasks/list` 能列出、`/api/forensics/...` 查询正常。

失败排查：
- 编译失败：`build/` 下有 `cmake-configure.log`、`forensic_analyzer-build.log`（setup.sh 产物；run.sh 路径的输出直接在终端）。缺新系统库时重跑 `./setup.sh`（幂等，已装的跳过）。
- 新增 Python 依赖报 ImportError：`rm -f python_service/.venv/.deps_installed` 后重跑，或 `make setup-venv`。
- 启动即 404/行为异常：多为 `build/web/dist` 与新后端不匹配（§5）。

## 2. PostgreSQL 迁移（001 全新建库；002/003 已有库手工增量）

背景：`migrations/postgresql/` 下三个文件按序号即应用顺序，作用对象都是 C/S server（`:8091`）的 PostgreSQL 库（`python_service/server/` 的 ORM 层）。server 启动只做 ORM `create_all`（`server/db/session.py` 的 `init_db()`，由 `server/main.py` 的 lifespan 调用——lifespan 定义 `main.py:80`，启动时在 `:93` 调 `initialize_database()`，后者定义 `:51-76`、内部在 `:56` 经 `asyncio.to_thread(init_db)` 执行建表），**SQL 迁移文件不会被自动应用**（见 ExternalServices.md §3.2）。三者的分工：

- **001_initial_schema.sql = 全新建库**：10 张业务表（organizations/users/clients/disk_images/command_queue/analysis_tasks/analysis_results/llm_analysis/task_history/registration_tokens）、6 个索引、CHECK 约束与种子数据（Default Organization + super_admin）。应用方式二选一（等价）：
  - `cd python_service && .venv/bin/python -m server.db.init_db --migrate --init --seed`——`--migrate` 在单事务里执行 001 文件（`server/db/init_db.py:122-133`），`--init` 补 ORM 元数据里的缺表（`:59-62`），`--seed` 幂等创建默认组织与 super_admin（`:71-119`）；
  - `psql "$DATABASE_URL" -f migrations/postgresql/001_initial_schema.sql`。
  - 001 的 `CREATE TABLE` 不带 `IF NOT EXISTS`：**对已有表的非空库执行会整体报错回滚，无副作用**——这也是判定"库是否初始化过"的天然哨兵。
- **002/003 = 已有库升级增量**：升级到带 002/003 的版本后**必须手工执行一次**（§2.1/§2.2），服务启动不会补。

迁移与建库的关系：`create_all` 只保证"ORM 元数据里声明的表存在"，**不含 001 的种子行与部分约束/索引**；001 才是权威 schema。全新库的正确顺序 = 001 → 002 → 003（三步都要，Deployment.md §6 步骤 1 同此口径）。已知坑：两条建库路径的种子 super_admin 邮箱都是 `super_admin@tracelens.local`（001 文件与 `init_db.py:109` 字面量；`:110` 是其下的 `password_hash=` 行），该保留 TLD 会让 `GET /api/auth/me` 500——003 的邮箱 UPDATE 正是修它，所以**即便走 init_db --seed（密码哈希是运行时算的、没有 001 文件里那个坏哈希问题），003 也必须应用**。

判定与操作：拿到不确定状态的库，直接执行 `init_db --migrate --init --seed`——成功 = 新库建好（再补 002/003）；报 `relation "organizations" already exists` = 库已存在，转 §2.1/§2.2 检查增量是否应用过。

### 2.1 002_command_task_fk.sql

- 内容：给 `command_queue` 加 `task_id UUID REFERENCES analysis_tasks ON DELETE CASCADE` 真外键（替代 parameters JSONB 软链接），回填存量行（校验 UUID 格式），建 `idx_command_queue_task`。
- **幂等**：`ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`，回填 WHERE task_id IS NULL——重复执行无副作用。
- 操作与验证：
```bash
psql "$DATABASE_URL" -f migrations/postgresql/002_command_task_fk.sql
psql "$DATABASE_URL" -c "\d command_queue" | grep task_id     # 列与 FK 存在
```

### 2.2 003_fix_super_admin_seed_credentials.sql

- 修复 001 种子的两个坏值：password_hash 与文档口令 `admin123` 不匹配（**登录恒 401** 的根因）；email 用了保留 TLD `.local`（`GET /api/auth/me` 500 的根因）。
- **幂等且非破坏**：UPDATE 带 WHERE 旧值匹配，操作员已改过密码/邮箱则不受影响。
- 操作与验证：
```bash
psql "$DATABASE_URL" -f migrations/postgresql/003_fix_super_admin_seed_credentials.sql
curl -s -X POST http://localhost:8091/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"super_admin","password":"admin123"}'        # 应返回 token
```
- 仍 401：确认 001 的种子行存在且未被改过密码（`SELECT username, password_hash FROM users WHERE username='super_admin';` 对照 003 文件里的旧哈希）；确认请求打到 8091 而非 8090。
- **升级后立即改掉 admin123**（001/003 都标注 CHANGE IN PRODUCTION）。

## 3. SQLite 侧：无版本迁移，代码内置"探测 + ALTER"自愈

背景：任务库（raw/files/events 等）没有迁移版本号机制；新代码打开旧库时按需探测缺列并 `ALTER TABLE ADD COLUMN`，这就是"自愈"。

- `DatabaseManager::checkAndMigrate()`（`src/core/DatabaseManager/DatabaseManager.cpp`：定义 `:65`；构造流程 `:54` 调 `createTables()`、`:59` 调 `checkAndMigrate()`）：`PRAGMA table_info(files)`（`:68`）探测 `llm_summary` 列，缺失则在 `:84-85` 批量执行 `FileClassifierSQL::ALTER_FILES_ADD_LLM_COLUMNS`（llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used 等；`createTables()` 定义 `:90`，files 建表 SQL 内同名 LLM 列在 `:105-117`、`llm_summary` 在 `:110`）。
- `partition_num` 列同样走探测补齐（"ALTER 失败（列已存在）即忽略"的写法）：`DatabaseManager.cpp:123-135`（ALTER 语句 `:129`）；`FileClassifier.cpp` 三处——源库 `:72-77`（注释 `:72-74`）、输出库 files.db `:103-106`、分类表 `:160-165`（"intentionally ignored" 注释 `:160-162`、语句 `:164`）。
- 事件库/分析库在建库时即开 WAL + synchronous=NORMAL（`EventExtractorCore.cpp:64-65`：`PRAGMA journal_mode=WAL` `:64`、`synchronous=NORMAL` `:65`；FileClassifier 输出库同款在 `FileClassifier.cpp:85-86`），无结构迁移需求。

操作：**无需任何手工步骤**——升级后第一次打开旧任务库时自动补列（stdout 会打 `[DB Migration] Adding LLM columns to files table ...`）。

验证：`sqlite3 build/data/tasks/<id>/files.db "PRAGMA table_info(files);"` 看新列；C++ 日志出现 DB Migration 行。
失败排查：列补齐要求库文件可写（备份恢复后权限问题会让 ALTER 静默失败，表现为新功能查不到数据）；只读打开的库不做迁移。

## 4. 图谱迁移（episode → File 实体结构）

背景：Graphiti 结构从"以 episode 为中心"演进为"以 File 实体为中心"（Task -[:CONTAINS_FILE]-> File，episode -[:SOURCE_FILE]-> File，实体 -[:MENTIONED_IN]-> File）。`MigrationManager`（`python_service/graphiti_integration/migration.py`）提供兼容查询与一次性迁移工具，**查询路径自带懒迁移**。

- 懒迁移：`query_file_with_fallback()`（`migration.py:161-212`）先查 File 实体，查不到再按文件名找旧 Episodic 节点，找到即触发 `migrate_single_episode` 后重试——日常使用**不需要**主动跑迁移。
- 主动迁移单任务：`migrate_task(task_id)`（`migration.py:276-368`）：取该 group_id 的全部 `source_description="forensics_file_analysis"` episode → 逐条建 File 实体（File.id = 路径的 SHA-256，`migration.py:392-465`）→ 建 SOURCE_FILE 边 → 建 Task 节点与 CONTAINS_FILE → 建 MENTIONED_IN 边。返回 `MigrationResult`（files_migrated/episodes_linked/entities_linked/errors）。
- 状态检查：`is_migrated(task_id)`（`:214-229`）/ `get_migration_status(task_id)`（`:231-274`，含 file_entities/total_episodes/linked_episodes/progress）。
- **MD5 去重**：`deduplicate_by_md5()`（`:527-572`）跨任务找相同 MD5 的 File 实体，两两建双向 `SAME_CONTENT_AS {confidence:1.0}` 边（N 个同哈希文件产出 N*(N-1) 条边，大库耗时线性膨胀，低峰期跑）。
- 旧结构清理：`cleanup_old_structure(task_id)`（`:574-600`）只给已挂接的 episode 打 `migrated=true` 标记，**不删数据**（文件头 WARNING：验证迁移结果后才可运行）。

操作（脚本化示例，从 python_service 目录）：
```bash
cd python_service
.venv/bin/python - <<'EOF'
import asyncio
from graphiti_integration.migration import MigrationManager
async def main():
    async with MigrationManager("neo4j://127.0.0.1:7687", "neo4j", "<pwd>") as m:
        print(await m.get_migration_status("<task_id>"))
        r = await m.migrate_task("<task_id>")
        print(r.files_migrated, r.episodes_linked, r.errors[:3])
asyncio.run(main())
EOF
```

验证：`cypher-shell` 查 `MATCH (t:Task {id:'<task_id>'})-[:CONTAINS_FILE]->(f) RETURN count(f);`。
失败排查：ConstraintError 会被 `_run_query` 自动重试（并发 MERGE，`migration.py:127-159`）；连不上先按 ExternalServices.md §1 排查 Neo4j。图谱彻底乱了可 `wipe_neo4j.py` 清空后重摄取（旧任务库还在，数据不丢）。

## 5. 前端 dist 同步（build/web/dist）

背景：生产模式下前端由 C++ 从**可执行文件相对路径** `web/dist` 托管，即 `build/web/dist/`；`web/dist` 只是 npm 的输出目录，两者必须同步。

- `run.sh` 的同步逻辑（`run.sh:137-155`）：`npm run build` 校验 `web/dist/index.html` 存在后，`rm -rf build/web/dist && cp -r web/dist/. build/web/dist/`。
- `./run.sh --no-web` **不会同步**——升级若包含前端改动，要么去掉 `--no-web`，要么手动：
```bash
cd web && npm run build && cd ..
rm -rf build/web/dist && mkdir -p build/web/dist && cp -r web/dist/. build/web/dist/
```
- `make build` 路径：CMake 的 `web_frontend` 目标处理（`-DBUILD_WEB_FRONTEND` 默认开；run.sh 显式关掉它改由 npm 单独构建，避免 CMake ALL 目标触发全量 npm 占满 CPU，`run.sh:125-128` 注释）。

验证：浏览器强刷 `http://localhost:8666/`；`diff -r web/dist build/web/dist` 应无差异；404/白屏多为 dist 未同步或 `--no-web` 用错。
失败排查：`npm run build` 失败先 `cd web && npm install`（node_modules 缺失）；Node 版本要求见 setup.sh Step 0（NVM + Node 22 LTS）。

## 6. 升级前后清单与回滚

背景：把 §1-§5 串成一次可执行的升级流程，并预置回滚路径。

升级前（打勾）：
- [ ] 备份 `build/data/`、`build/forensics_audit.db*`、`.env`（DataAndBackup.md §4）
- [ ] PostgreSQL 备份：`pg_dump "$DATABASE_URL" > pg-$(date +%F).dump`
- [ ] 记录当前 git 版本：`git rev-parse HEAD`
- [ ] 确认磁盘余量足够一次全量重编译（`--clean` 后全量构建）
- [ ] 无 RUNNING 任务（`curl localhost:8666/api/tasks/statistics`）

升级后（验证）：
- [ ] 三服务健康检查全绿（ServiceRunbook.md §3）
- [ ] 旧任务可见且可查询（`/api/tasks/list` + 任一 `/api/forensics/...`）
- [ ] `files.db` 新列自愈完成（§3 验证命令）
- [ ] 002/003 已应用且幂等重跑无变化（§2）
- [ ] 前端页面正常加载（§5）
- [ ] `python_service/.venv` 依赖完整：`python_service/.venv/bin/python -c "import fastapi, pydantic"`

回滚：
```bash
# 代码回滚（数据兼容时——SQLite 有探测自愈，新列对旧代码无害）
git checkout <旧 commit> && ./run.sh --clean
# 数据回滚（升级弄坏了任务数据）
#   停服 → 用升级前 tar 解包覆盖 build/data 与审计库 → 启动
# PG 回滚
psql "$DATABASE_URL" -c "DROP DATABASE tracelens;" && sudo -u postgres createdb tracelens
psql "$DATABASE_URL" -f migrations/postgresql/001_initial_schema.sql   # 重建到 001
psql "$DATABASE_URL" -f pg-<日期>.dump                                  # 或整库导入
```
注意：002 的外键与 003 的种子修复都**不需要**回滚（向后兼容）；图谱结构迁移（§4）是加法（新增 File 实体与边，保留 episode），旧代码查询走 fallback 同样可用。

## 与代码的对应

| 机制 | 位置 |
|------|------|
| run.sh --clean 清理范围（保数据） | `run.sh:113-119` |
| make clean/rebuild（rm -rf build，删数据） | `Makefile:109-117` |
| venv 依赖标记 .deps_installed 与重装 | `run.sh:215-230`；`scripts/start_all_services.sh:206-215` |
| files 表 LLM 列探测 + ALTER 自愈 | `src/core/DatabaseManager/DatabaseManager.cpp:65-88`（PRAGMA `:68`、ALTER 循环 `:84-85`；构造流程调用于 `:54/:59`） |
| partition_num 补列（多处） | `src/core/DatabaseManager/DatabaseManager.cpp:123-135`（语句 `:129`）；`src/core/DatabaseManager/FileClassifier/FileClassifier.cpp:72-77, 103-106, 160-165` |
| 002 幂等外键迁移 | `migrations/postgresql/002_command_task_fk.sql:5-15` |
| 003 修复 401/.local 邮箱 | `migrations/postgresql/003_fix_super_admin_seed_credentials.sql:1-28` |
| 001 应用入口（--migrate 单事务执行 001 文件） | `python_service/server/db/init_db.py:122-133` |
| init_db --init（ORM create_all）与 --seed（组织/super_admin 幂等种子） | 同上 `:59-62`、`:71-119`（种子邮箱 `.local` 字面量 `:109`，`password_hash=` 在 `:110`） |
| server 启动仅 create_all（不跑 SQL 迁移） | `python_service/server/main.py:80`（lifespan）→ `:93` → `initialize_database :51-76`；`python_service/server/db/session.py`（init_db） |
| 图谱懒迁移 fallback | `python_service/graphiti_integration/migration.py:161-212` |
| migrate_task / 状态查询 | 同上 `:276-368`、`:214-274` |
| MD5 去重 / 旧结构标记清理 | 同上 `:527-572`、`:574-600` |
| ConstraintError 自动重试 | 同上 `:127-159` |
| dist 同步（rm+cp 到 build/web/dist） | `run.sh:137-155` |
| CMake 关闭内置前端目标 | `run.sh:125-128` |

**最后更新**: 2026-11-10（补 001 全新建库流程与 init_db 应用机制，口径与 ExternalServices.md §3.2 对齐；锚点校准——lifespan 定义 main.py:80/调用 :93、种子邮箱字面量 init_db.py:109、partition_num ALTER 位置、checkAndMigrate 结构、WAL PRAGMA EventExtractorCore.cpp:64-65）
