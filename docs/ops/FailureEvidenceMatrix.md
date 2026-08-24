# 故障证据矩阵

> 排障不应只看一个错误字符串。每类症状都要同时收集：服务日志、健康响应、任务状态、审计事件、数据库对象和外部依赖状态。下面的矩阵把“症状”映射成可重复的取证证据包。

## 1. 任务状态矩阵

| 症状 | 第一证据 | 第二证据 | 常见根因 | 不要做 |
|---|---|---|---|---|
| PENDING 很久 | `/progress` + tasks.json | ThreadPool 配置/CPU | 池饱和、调度丢失 | 不要手工改 status |
| RUNNING 不动 | 最后进度时间 | cpp log + 看门狗阈值 | 阶段长任务/死循环/LLM 排队 | 不要立刻重启丢日志 |
| FAILED | `error_details` | 阶段日志 + 输入库 integrity | 输入/解析/外部依赖 | 不要只看 HTTP 500 |
| CANCELLED 后又写 | 删除时间 + 任务日志 | D4b existing-only 证据 | 竞态/迟到 worker | 不要恢复目录复活 |
| COMPLETED 但无图 | graphiti_job_id | Python job errors/Neo4j | fire-and-forget/依赖降级 | 不要重跑整镜像前查 job |

## 2. 服务健康矩阵

| 服务 | 健康 | ready | 依赖异常的实际影响 |
|---|---|---|---|
| C++ | `/api/system/health` 500/200 | `/api/health/ready` | C++ 不可用，Python 也不可 ready |
| Python | `/health` | `/health/ready` body | C++ 硬；Neo4j/LLM/Redis 可选降级 |
| C/S | `/health` degraded 字段 | `/health/ready` 503 | PG 不可用，agent 无法轮询 |
| Neo4j | Graphiti status | Python ready optional | 分析成功、图谱缺席 |
| Redis | redis/status | Python ready optional | 作业内存回退，重启丢 |
| LLM | /v1/models | Python ready optional | 文件/工件/图谱语义层缺席 |

## 3. 数据库证据包

每次重大故障采集以下信息（只读）：

```bash
mkdir -p /tmp/tracelens-diag-<task>
cp build/logs/*.log /tmp/tracelens-diag-<task>/ 2>/dev/null || true
cp data/tasks/<task>/tasks.json /tmp/tracelens-diag-<task>/ 2>/dev/null || true
for db in data/tasks/<task>/*.db; do
  sqlite3 "$db" 'PRAGMA integrity_check;' > "$db.integrity.txt"
  sqlite3 "$db" '.schema' > "$db.schema.txt"
done
```

### 3.1 空结果证据

| 空结果 | 应检查 | 解释 |
|---|---|---|
| files 为空 | raw 行数、filter stats、effectiveRawDb | 过滤全灭是否回退 |
| events 为空 | raw 时间戳、EventExtractor 错误 | 输入是否只有目录/无 REG |
| linux 工件为空 | marker 路径、场景列表 | 场景是否自动检测/选择错误 |
| LLM 列为空 | endpoint、llm_analyzed_at、SELECT prepare | 限额/端点/坏列 |
| 图谱为空 | job 状态、episode errors、Neo4j | 摄取是否触发/案例聚合 |
| report 无页面 | manifest、generation 状态 | 202 是否轮询完成 |

## 4. 日志证据包的时间统一

- SQLite events 时间：Unix 秒；
- audit_logs 时间：Unix 毫秒；
- C++ 日志：按实际 formatter；
- Python 日志：结构化/非结构化两种；
- PG `created_at`：TIMESTAMP。

统一时把审计毫秒除以 1000，再用 ±60 秒窗口 grep 三服务日志；不要直接拿字符串时间排序。

## 5. 外部依赖故障矩阵

| 依赖 | 发现命令 | 可继续的功能 | 受影响功能 |
|---|---|---|---|
| Neo4j | `systemctl status neo4j` + Graphiti status | C++ 分析/SQLite/CLI 报告 | Graphiti 图谱 |
| Redis | `/api/system/redis/status` | 同进程作业 | 重启持久化/多 worker |
| PG | `psql $DATABASE_URL -c 'select 1'` | 本地栈 | C/S login/poll/results |
| LLM | `/v1/models` + chat 冒烟 | raw/events/files 基础 | LLM 列/图谱/智能报告 |

## 6. 修复后回归证据

修复一个问题后，证据必须能回答“问题消失且没有旁边的问题”：

1. 单元测试结果（精确目标名）；
2. 最小复现输入再次执行；
3. 受影响 DB 的行数/字段/完整性前后对比；
4. 相关健康端点；
5. 若涉及跨服务，至少一条真实 socket 调用；
6. 文档注意事项从“现存”改为“已修复（commit）”。

---


## 7. 证据包最小字段

| 类别 | 必采字段 | 目的 |
|---|---|---|
| 版本 | git commit、构建时间、OS、编译器 | 排除环境差异 |
| 服务 | PID、端口、启动参数、CWD | 解释相对路径与端口回退 |
| 配置 | 脱敏后的变量名/值来源 | 解释默认值漂移 |
| 任务 | id/status/phase/progress/error | 定位状态机分支 |
| 路径 | image_path/raw/output_raw_db | 定位过滤副本与权限 |
| SQLite | integrity/schema/row counts | 判断库是否可读与是否空 |
| LLM | endpoint/model/job id | 区分端点、模型、队列 |
| 图谱 | Neo4j status/job errors | 区分摄取失败与查询失败 |

## 8. 典型错误到验证命令

| 错误 | 命令/查询 | 结果解释 |
|---|---|---|
| image not found | `stat <image_path>` | C++ 进程用户是否有权限 |
| database locked | `fuser <task>/files.db` | 是否有旧进程持有句柄 |
| no events | `SELECT COUNT(*) FROM events` | input raw 是否有 REG 与时间戳 |
| no Linux artifacts | `SELECT scenarios FROM tasks.json` | 场景是否检测/显式指定 |
| LLM 404 | `curl $LLM_BASE_URL/v1/models` | model id 是否一致 |
| Graphiti disabled | `curl :8090/health/ready` | Neo4j optional 状态 |
| PG 401 | `SELECT email FROM users` | 003 是否应用 |
| agent no result | `SELECT status FROM command_queue` | assigned 后是否回传 |
| report 409 | generation/evidence API | 准入绑定组是否完整 |
| frontend blank | `curl cpp:/` | dist 是否被同步 |

## 9. 安全采集规则

1. 不把原始镜像复制到诊断包；记录路径、大小、hash 即可；
2. `.env` 只记录变量名和是否设置，值用掩码；
3. 日志可能含证据路径，上传前做路径脱敏；
4. SQLite 诊断只读打开，避免 `sqlite3` 产生修改；
5. 审计库副本用 `.backup`，不要直接复制 WAL 未合并的主文件；
6. PG 查询用只读账号或事务 `BEGIN READ ONLY`；
7. 删除诊断包前确认其中没有密码、JWT 或原始消息内容。

## 10. 关闭事件

故障修复后记录：根因、影响窗口、发现证据、修复 commit、回归命令、残留风险。若根因已写在模块文档“已知问题”，修复后把状态改为“已修复（commit）”，避免下一位维护者重复排查旧问题。
**最后更新**: 2026-08-24（新建：故障证据矩阵）
