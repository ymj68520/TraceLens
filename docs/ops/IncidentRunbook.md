# 应急 Runbook：三大症状的处置树

> 服务异常时的快速动作清单。每步"做什么→看什么→下一步分叉"。深挖工具在 [Troubleshooting §13](../getting-started/Troubleshooting.md)，并发剧本在 [Concurrency §7](../architecture/Concurrency.md)。

## 症状一：前端打不开 / 全白

```
1. curl http://<cpp端口>/            → 200?
   ├─ 是 → 前端缓存/浏览器问题（强刷；确认访问的是 C++ 端口不是 3000）
   └─ 否 → 2
2. curl http://<cpp端口>/api/system/health → 200?
   ├─ 是 → C++ 活着但静态目录不对：确认 build/web/dist 存在（run.sh 会同步 web/dist）
   └─ 否 → 3
3. build/logs/cpp_server.log 尾部
   ├─ 端口占用 → run.sh 已自动清；手动 lsof -i:<端口>
   ├─ 构建产物缺失 → 重新 run.sh（勿 --no-build）
   └─ 崩溃栈 → 按栈定位模块文档
```

## 症状二：任务失败/卡死

```
1. GET /api/tasks/<id> 看 status+error_details
   ├─ FAILED+阶段原因 → 按阶段查模块文档"错误处理"节（镜像不可达/密码错最常见）
   ├─ FAILED+inactivity → 看门狗判死：Concurrency 剧本 A
   └─ RUNNING → 2
2. GET progress：百分比变化？
   ├─ 变 → 没坏，只是慢（CapacityPlanning 时间预算）
   └─ 不变 → 日志定位该 task_id 最后输出；LLM 阶段查端点（LLMOperations 速查卡）
3. 批量失败 → /api/tasks/statistics 看失败率；同时段系统事件（磁盘满/端点挂）
```

## 症状三：Python 功能缺失（图谱/报告/转换不可用）

```
1. curl :8090/health/ready → body 各项
   ├─ cpp_backend 异常 → 回症状一先修 C++（Python 硬依赖）
   ├─ graphiti 异常 → 2
   └─ redis 异常 → 3
2. Neo4j：systemctl status neo4j；密码对不对（.env vs 服务端）
   → 图谱降级不阻断分析；修好后重摄取（POST /api/graphiti/ingest）
3. Redis：可选件；内存回退已自动生效（作业重启丢失），装回即可
```

## 附：什么时候重启服务

- 该重启：Python 侧配置变更、Neo4j 恢复后、进程崩溃。
- 别用重启掩盖：任务反复失败（先定位根因——重启不清任务状态，tasks.json 还在）。
- 重启副作用清单：RUNNING 任务被标 FAILED（恢复语义）、进行中摄取作业丢失（Redis 在则续）、服务日志被覆盖（先归档）。

---

**最后更新**: 2026-08-24（新建：应急 Runbook）
