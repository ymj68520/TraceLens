# 监控手册：日志、健康与审计三通道

> 适用场景：把 TraceLens 当作常驻服务运行时的日常监控。前置：三服务已按 [ServiceRunbook](ServiceRunbook.md) 启动。本文给"看什么、多久看一次、什么条件该行动"，以及一套可直接落地的采样脚本骨架。

## 速查卡

```bash
# 健康三连（C++ 硬检查 / Python 就绪 / C/S 就绪）
curl -sf http://localhost:8666/api/system/health | head -c 300
curl -sf http://localhost:8090/health/ready | python3 -m json.tool | head -20
curl -sf http://localhost:8091/health/ready >/dev/null && echo CS-OK || echo CS-DEGRADED
# 任务面
curl -s http://localhost:8666/api/tasks/statistics
# 日志尾随
tail -f build/logs/cpp_server.log build/logs/python_service.log
# 审计近 30 分钟动作分布
sqlite3 build/forensics_audit.db "SELECT action, COUNT(*) FROM audit_logs \
  WHERE timestamp > (strftime('%s','now')-1800)*1000 GROUP BY action ORDER BY 2 DESC"
```

## 1. 三通道各自看什么

### 通道一：服务日志（build/logs/*.log）
- 三个文件对应三服务，**启动即覆盖、无轮转**（已知现状）——监控要自己留存（见 §4 的 rotate 建议）。
- 关键词告警：C++ 侧 `Error`/`Failed to`（分析失败、Graphiti 触发异常）；Python 侧 `WARNING`（降级发生：graphiti disabled、redis fallback、cpp backend 不可达）；`Failed to aggregate files from image`（案例级摄取问题，历史 NameError 修复后不应再出现，出现即升级排查）。
- C++ 数据日志另在 `data/logs/forensics.log`（调试输出 DEBUG_OUTPUT_MODE 控制）。

### 通道二：健康端点（口径别混）
| 端点 | 语义 | 监控用法 |
|------|------|---------|
| C++ `GET /api/system/health` | run.sh 同款硬检查 | 探活：非 200 即挂 |
| C++ `/api/health/dependencies` | 依赖视角 | 看它报告的各依赖状态 |
| Python `/health/ready` | 恒 200，看 body | `ready:false` 且 `cpp_backend` 异常 = 硬依赖失联；Neo4j/LLM/Redis 异常 = 降级运行（分析不受影响，图谱/报告受限） |
| Python `/api/system/redis/status` | 队列持久化状态 | redis in_use=false = 摄取作业重启即失 |
| C/S `/health/ready` | 503 = DB 不可用 | 注意它是**启动快照**：中途宕库不会自动变红（已知边界） |

### 通道三：审计库（build/forensics_audit.db）
- 独立于任务的行动记录：任务创建/取消/删除、SCENE_DETECTED、GRAPHITI_INGESTION、证据操作。
- 监控视角的价值：**"系统替人做的判断"都在这**。定期采样动作分布，突增的 FAILED/异常组合是早期信号。
- 注意库位置在进程 CWD（run.sh 下是 build/）；轮转/保留函数存在但未接线——库会一直长（见 §4）。

## 2. 建议的监控项与阈值

| 项 | 采样 | 行动阈值（建议起点，按负载调） |
|----|------|------------------------------|
| C++ 健康 | 30s | 连续 2 次失败告警 |
| Python ready.cpp_backend | 60s | false 即告警（C++ 挂或网络断） |
| 任务失败率 | 5min 统计 | 近 1h failed/(failed+completed) > 20% 人工看 |
| RUNNING 任务数 | 60s | 持续 ≥ THREAD_POOL_SIZE+2 说明积压 |
| PENDING 最长等待 | 60s | > 30 分钟将被看门狗判死——提前介入 |
| 磁盘水位（data/ 与审计库所在盘） | 5min | > 80% 预警（carved/extracted 是大户） |
| Redis in_use | 5min | 持续 false 告警（作业不持久） |
| 审计库大小 | 1h | > 2GB 提示归档（无自动轮转） |

## 3. 日志-健康-审计三方对时间定位法

出问题时按"审计毫秒为基准"对齐三方（审计是毫秒、events 是秒、日志各行格式不一）：
1. 审计锁定动作时间窗：`WHERE timestamp BETWEEN :s*1000 AND :e*1000`；
2. 三份服务日志 `grep` 该窗 ±60s；
3. 若涉及任务库，events 按 `timestamp BETWEEN :s AND :e` 对（秒）。完整方法与 jq 技巧见 [Troubleshooting §13](../getting-started/Troubleshooting.md)。

## 4. 最小落地：cron 采样脚本骨架

```bash
#!/usr/bin/env bash
# /etc/cron.d/tracelens-mon 每 5 分钟由 cron 调用
BASE=/path/to/TraceLens; LOG=$BASE/build/logs/monitor.log
ts() { date +%FT%T; }
{
  curl -sf -m 5 http://localhost:8666/api/system/health >/dev/null \
    || echo "$(ts) CPP-DOWN"
  ready=$(curl -sf -m 5 http://localhost:8090/health/ready | python3 -c 'import sys,json;print(json.load(sys.stdin).get("ready"))' 2>/dev/null)
  [ "$ready" = "True" ] || echo "$(ts) PY-NOT-READY($ready)"
  curl -sf -m 5 "http://localhost:8666/api/tasks/statistics" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print("tasks",d)' 2>/dev/null
  df -h "$BASE/data" | tail -1
  ls -la "$BASE/build/forensics_audit.db" | awk '{print "audit", $5}'
} >> "$LOG" 2>&1
```
（Python 侧 ready 字段名以 `/health/ready` 实际返回为准；告警接入交给你的运维通道。）

另建议：低峰期 `cp` 归档当日三份服务日志 + 审计库（SQLite 在 WAL 下建议用 `sqlite3 .backup`），弥补"启动覆盖、无轮转"的缺口。

## 5. 与代码的对应

| 机制 | 位置 |
|------|------|
| 健康端点语义 | [Health 路由](../modules/python/httpserver/routes/Health.md)、[SystemRoutes](../modules/cpp/network/routes/SystemRoutes.md) |
| 审计写入与查询 | [AuditLog 模块](../modules/cpp/core/AuditLog.md)（写缓冲/异步刷盘；轮转未接线） |
| 日志落点 | run.sh（`>` 重定向）、PathManager（data/logs） |
| 看门狗阈值 | TaskWatchdog（TASK_WATCHDOG_STALE/PENDING_MINUTES，默认 30 分钟） |

---

**最后更新**: 2026-08-24（新建：监控手册）
